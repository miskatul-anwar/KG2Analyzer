"""Grounded conversational interface (thesis Algorithm 3).

ask(question):
  prompt <- grounded schema catalogue + compact aliases + question
  up to K_max times: draft <- translator(prompt); expand aliases; validate (4 rules);
                     on failure feed the diagnostics back into the prompt
  if still invalid: deterministic grounded parser (generalises the identity template)
  if still invalid: reject ("out-of-scope or ungrounded") without executing anything
  else execute and summarise.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

from kg2analyzer.catalog import STANDARD, Catalog
from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.nl.translators import GroundedParser, Translator, compose_prompt, extract_sparql
from kg2analyzer.nl.validator import Check, Validator
from kg2analyzer.store import MultiKGStore


@dataclass
class Attempt:
    translator: str
    raw: str
    sparql: str
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return bool(self.sparql) and all(c.ok for c in self.checks)


@dataclass
class Answer:
    question: str
    status: str  # "executed" | "fallback" | "rejected" | "error"
    sparql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    insight: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    seconds: float = 0.0
    trace: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["attempts"] = [{"translator": a.translator, "sparql": a.sparql, "ok": a.ok,
                          "checks": [asdict(c) for c in a.checks]} for a in self.attempts]
        return d


def expand_aliases(sparql: str, cat: Catalog) -> str:
    """Prepend PREFIX declarations for every compact alias the draft uses but does not declare."""
    declared = {m.group(1) for m in re.finditer(r"PREFIX\s+([A-Za-z][\w\-]*)\s*:", sparql, re.I)}
    used = set(re.findall(r"(?<![<\w])([A-Za-z][\w\-]*):[A-Za-z_]", re.sub(r"<[^>]*>|\"[^\"]*\"", "", sparql)))
    known = {**STANDARD, **cat.prefixes}
    extra = [f"PREFIX {p}: <{known[p]}>" for p in sorted(used - declared) if p in known]
    return ("\n".join(extra) + "\n" + sparql) if extra else sparql


class NLInterface:
    def __init__(self, store: MultiKGStore, cat: Catalog, translator: Translator | None = None, k_max: int = 2):
        self.store, self.cat, self.k_max = store, cat, k_max
        self.parser = GroundedParser(cat, store)
        self.translator = translator or self.parser
        self.validator = Validator(cat, node_exists=self._node_exists)
        self._answers: dict[str, Answer] = {}
        import os

        self.budget = float(os.environ.get("KG2A_LLM_BUDGET", "30"))  # seconds the LLM gets before the parser answers

    def _node_exists(self, iri: str) -> bool:
        from rdflib import URIRef

        ds = self.store.integrated
        return (URIRef(iri), None, None) in ds or (None, None, URIRef(iri)) in ds

    def _attempt(self, translator: Translator, question: str, prompt: str) -> Attempt:
        try:
            raw = translator.translate(question, prompt)
        except Exception as e:  # noqa: BLE001
            return Attempt(translator.name, "", "", [Check("syntax", False, f"translator error: {e}")])
        sparql = extract_sparql(raw) if raw else ""
        if not sparql:
            intent = getattr(translator, "last_trace", None)
            if intent is not None and intent.intent.startswith("mutation"):
                return Attempt(translator.name, raw, "", [Check("safety", False, "the question asks to modify data; "
                                                                "KG2Analyzer is read-only")])
            return Attempt(translator.name, raw, "", [Check("scope", False, "no catalogue vocabulary matches the question")])
        sparql = expand_aliases(sparql, self.cat)
        return Attempt(translator.name, raw, sparql, self.validator.validate(sparql, question))

    def ask(self, question: str) -> Answer:
        """Answer a question (answers are remembered until the loaded MDKGs or the translator change)."""
        import copy

        t0 = time.perf_counter()
        key = " ".join(question.lower().split())
        if key in self._answers:
            ans = copy.deepcopy(self._answers[key])
            ans.question, ans.seconds = question, time.perf_counter() - t0
            ans.trace = {**ans.trace, "cached": True}
            return ans
        ans = self._ask(question)
        if ans.status in ("executed", "fallback", "rejected"):
            self._answers[key] = copy.deepcopy(ans)
        return ans

    def _llm_attempts(self, question: str) -> list[Attempt]:
        out, feedback = [], ""
        for _ in range(self.k_max):
            a = self._attempt(self.translator, question, compose_prompt(question, self.cat, feedback))
            out.append(a)
            if a.ok:
                break
            feedback = "\n".join(f"- {c.rule}: {c.message}" for c in a.checks if not c.ok)
        return out

    def _ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        ans = Answer(question, "rejected")
        if self.translator is self.parser:
            a = self._attempt(self.parser, question, "")
            ans.attempts.append(a)
            if a.ok:
                ans.status, ans.sparql = "executed", a.sparql
        else:
            # The LLM drafts (with error-fed retries) in a worker; meanwhile the grounded parser answers in
            # milliseconds. If the LLM has no valid query within the time budget, the parser's answer is used.
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as Late

            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self._llm_attempts, question)
            parsed = self._attempt(self.parser, question, "")
            try:
                drafts = future.result(timeout=self.budget)
            except Late:
                drafts = [Attempt(self.translator.name, "", "", [Check(
                    "syntax", False, f"no answer within {self.budget:g} s (KG2A_LLM_BUDGET); the grounded parser answered")])]
            pool.shutdown(wait=False)
            ans.attempts += drafts
            good = next((a for a in drafts if a.ok), None)
            if good:
                ans.status, ans.sparql = "executed", good.sparql
            else:
                ans.attempts.append(parsed)
                if parsed.ok:
                    ans.status, ans.sparql = "fallback", parsed.sparql
        if self.parser.last_trace.cubes or self.parser.last_trace.intent:
            ans.trace = asdict(self.parser.last_trace)
        if not ans.sparql:
            last = ans.attempts[-1] if ans.attempts else None
            reasons = "; ".join(f"{c.rule}: {c.message}" for c in (last.checks if last else []) if not c.ok)
            ans.insight = f"Query rejected: out-of-scope or ungrounded vocabulary ({reasons}). Nothing was executed."
            ans.seconds = time.perf_counter() - t0
            return ans
        try:
            out = self.store.query(ans.sparql)
            ans.columns, ans.rows = out.vars, out.rows
            ans.insight = summarise(ans.columns, ans.rows, self.cat)
        except Exception as e:  # noqa: BLE001
            ans.status, ans.insight = "error", f"execution failed: {e}"
        ans.seconds = time.perf_counter() - t0
        return ans


def summarise(cols: list[str], rows: list[dict], cat: Catalog) -> str:
    if not rows:
        return "The query ran but matched no observations."
    num_cols = [c for c in cols if all(isinstance(r.get(c), (int, float)) or type(r.get(c)).__name__ == "Decimal"
                                         for r in rows if r.get(c) is not None) and not c.endswith("_n")]
    label_cols = [c for c in cols if c not in num_cols and not c.endswith("_n")]

    def show(v):
        if isinstance(v, str) and v.startswith("http"):
            return local_name(v)
        if type(v).__name__ == "Decimal" or isinstance(v, float):
            return f"{float(v):,.2f}"
        return str(v)

    top = rows[0]
    lead = ", ".join(show(top[c]) for c in label_cols if top.get(c) is not None and not c.endswith("_label")) or "overall"
    lab = next((top[c] for c in label_cols if c.endswith("_label") and top.get(c)), None)
    vals = ", ".join(f"{c} = {show(top[c])}" for c in num_cols if top.get(c) is not None)
    s = f"{len(rows)} row(s). " + (f"Top: {lab or lead} with {vals}." if label_cols else f"Result: {vals}.")
    return s
