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

        from concurrent.futures import ThreadPoolExecutor

        self.budget = float(os.environ.get("KG2A_LLM_BUDGET", "120"))  # seconds the LLM gets in the background
        self.patience = float(os.environ.get("KG2A_LLM_PATIENCE", "1.5"))  # seconds to wait before answering with the parser
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm")
        self._jobs: dict[str, tuple] = {}

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
        if ans.status in ("executed", "fallback", "rejected") and "llm_job" not in ans.trace:
            self._answers[key] = copy.deepcopy(ans)  # an interim answer is remembered once its LLM job ends
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
        job = None
        if self.translator is self.parser:
            a = self._attempt(self.parser, question, "")
            ans.attempts.append(a)
            if a.ok:
                ans.status, ans.sparql = "executed", a.sparql
        else:
            # The LLM drafts (with error-fed retries) in a worker while the grounded parser answers in
            # milliseconds. A quick LLM answer is used at once; otherwise the parser's answer is returned now and
            # the LLM keeps working as a job (``job``) whose answer replaces it, until KG2A_LLM_BUDGET runs out.
            from concurrent.futures import TimeoutError as Late

            future = self._pool.submit(self._llm_attempts, question)
            parsed = self._attempt(self.parser, question, "")
            try:
                drafts = future.result(timeout=self.patience)
            except Late:
                drafts = None
            if drafts is not None:
                ans.attempts += drafts
                good = next((a for a in drafts if a.ok), None)
                if good:
                    ans.status, ans.sparql = "executed", good.sparql
                else:
                    ans.attempts.append(parsed)
                    if parsed.ok:
                        ans.status, ans.sparql = "fallback", parsed.sparql
            else:
                import uuid

                job = uuid.uuid4().hex[:12]
                ans.attempts.append(parsed)
                if parsed.ok:
                    ans.status, ans.sparql = "executed", parsed.sparql
        if self.parser.last_trace.cubes or self.parser.last_trace.intent:
            ans.trace = asdict(self.parser.last_trace)
        self._run(ans)
        ans.seconds = time.perf_counter() - t0
        if job:
            ans.trace = {**ans.trace, "llm_job": job, "llm": self.translator.name}
            self._jobs[job] = (future, question, time.monotonic(), ans)
        return ans

    def _run(self, ans: Answer) -> None:
        """Execute a validated query and summarise it (or explain the rejection)."""
        if not ans.sparql:
            last = ans.attempts[-1] if ans.attempts else None
            reasons = "; ".join(f"{c.rule}: {c.message}" for c in (last.checks if last else []) if not c.ok)
            ans.insight = f"Query rejected: out-of-scope or ungrounded vocabulary ({reasons}). Nothing was executed."
            return
        try:
            out = self.store.query(ans.sparql)
            ans.columns, ans.rows = out.vars, out.rows
            ans.insight = summarise(ans.columns, ans.rows, self.cat)
        except Exception as e:  # noqa: BLE001
            ans.status, ans.insight = "error", f"execution failed: {e}"

    def job(self, job_id: str) -> dict:
        """State of a background LLM draft: running, done (with the LLM's answer), invalid, or timeout."""
        import copy

        if job_id not in self._jobs:
            raise KeyError(f"no pending LLM answer {job_id!r}")
        future, question, started, interim = self._jobs[job_id]
        elapsed = time.monotonic() - started + interim.seconds
        key = " ".join(question.lower().split())
        if not future.done():
            if elapsed <= self.budget:
                return {"state": "running", "seconds": round(elapsed, 1), "llm": self.translator.name}
            del self._jobs[job_id]
            self._answers[key] = copy.deepcopy(interim)
            return {"state": "timeout", "seconds": round(elapsed, 1), "llm": self.translator.name}
        del self._jobs[job_id]
        drafts = future.result()
        good = next((a for a in drafts if a.ok), None)
        if good is None:
            self._answers[key] = copy.deepcopy(interim)
            return {"state": "invalid", "seconds": round(elapsed, 1), "llm": self.translator.name,
                    "attempts": [{"translator": a.translator, "sparql": a.sparql, "ok": a.ok,
                                  "checks": [asdict(c) for c in a.checks]} for a in drafts]}
        ans = Answer(question, "executed", sparql=good.sparql, attempts=drafts, trace={"llm": self.translator.name})
        self._run(ans)
        ans.seconds = elapsed
        self._answers[key] = copy.deepcopy(ans)
        return {"state": "done", "seconds": round(elapsed, 1), "answer": ans.to_dict()}


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
