"""Text-to-SPARQL translators.

* ``OllamaTranslator``  local LLM via Ollama (thesis default: qwen2.5-coder:3b, air-gapped)
* ``OpenAICompatibleTranslator``  any /v1/chat/completions server (llama.cpp, vLLM, LM Studio, ...)
* ``GroundedParser``  deterministic semantic parser over the live catalogue; needs no model,
  is used as the offline default and as the deterministic fallback after LLM retries fail.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from kg2analyzer.catalog import Catalog, CubeInfo
from kg2analyzer.graphml import tokens
from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.nl import semantic
from kg2analyzer.nl.validator import mentioned_domains
from kg2analyzer.olap import Axis, Filter, build_rollup
from kg2analyzer.planner import CrossCubeQuery, CubeSide, pushdown_sparql
from kg2analyzer.store import IDENTITY_GRAPH, MultiKGStore

SYSTEM_RULES = """You are a SPARQL query generator operating strictly over an existing QB4OLAP dataset.
Use ONLY the datasets, dimensions, and measures provided in the schema context below.
Do NOT invent prefixes, classes, or properties. Do NOT use SERVICE or FROM clauses.
Only generate SELECT queries. Never generate UPDATE, INSERT, or DELETE statements.
Observations are linked to their dataset with qb:dataSet and live inside GRAPH <graph IRI> { ... }.
Roll up dimension members with the roll-up predicates listed in the catalogue.
When combining two cubes, aggregate each cube in its own sub-SELECT before joining (pushdown pre-aggregation);
cross-domain entities are linked by owl:sameAs in the identity graph."""


class Translator(Protocol):
    name: str

    def translate(self, question: str, prompt: str) -> str: ...


def compose_prompt(question: str, cat: Catalog, feedback: str = "") -> str:
    p = f"{SYSTEM_RULES}\n\n{cat.prompt_context()}\n\nUser Question: {question}\n"
    if feedback:
        p += f"\nYour previous query was rejected by the validator:\n{feedback}\nFix these problems.\n"
    return p + "Generate ONLY executable SPARQL code enclosed in ```sparql ... ```."


def ollama_url() -> str:
    return os.environ.get("KG2A_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def ollama_models(url: str | None = None) -> dict:
    """The models installed in Ollama (``/api/tags``), with size and parameters, and which are loaded (``/api/ps``)."""
    url = (url or ollama_url()).rstrip("/")
    try:
        r = httpx.get(url + "/api/tags", timeout=3)
        r.raise_for_status()
        tags = r.json().get("models", [])
    except Exception as e:  # noqa: BLE001
        return {"server": url, "reachable": False, "models": [], "error": f"{type(e).__name__}: {e}"[:200]}
    try:
        loaded = {m.get("name") for m in httpx.get(url + "/api/ps", timeout=2).json().get("models", [])}
    except Exception:  # noqa: BLE001
        loaded = set()
    models = []
    for m in sorted(tags, key=lambda m: m.get("name", "")):
        d = m.get("details") or {}
        models.append({"name": m.get("name"), "size_gb": round((m.get("size") or 0) / 1e9, 2),
                       "parameters": d.get("parameter_size"), "family": d.get("family"),
                       "quantization": d.get("quantization_level"), "loaded": m.get("name") in loaded})
    return {"server": url, "reachable": True, "models": models, "error": None}


class OllamaTranslator:
    """A local LLM through Ollama. Kept loaded between questions (``keep_alive``), deterministic, with the
    output capped: the stable schema prefix of every prompt lets Ollama reuse its cache across questions."""

    def __init__(self, model: str | None = None, url: str | None = None, timeout: float | None = None):
        self.model = model or os.environ.get("KG2A_OLLAMA_MODEL", "qwen2.5-coder:3b")
        self.url = (url or ollama_url()).rstrip("/")
        self.timeout = timeout or float(os.environ.get("KG2A_LLM_TIMEOUT", "120"))
        self.keep_alive = os.environ.get("KG2A_OLLAMA_KEEP_ALIVE", "30m")
        self.name = f"ollama:{self.model}"

    def available(self) -> bool:
        info = ollama_models(self.url)
        return info["reachable"] and any(m["name"] == self.model or m["name"].startswith(self.model + ":")
                                         or m["name"].split(":")[0] == self.model for m in info["models"])

    def warm(self) -> None:
        """Load the model now (an empty prompt only loads it), so the first question does not wait for it."""
        try:
            httpx.post(self.url + "/api/generate", timeout=self.timeout,
                       json={"model": self.model, "prompt": "", "keep_alive": self.keep_alive})
        except Exception:  # noqa: BLE001 - the question itself will report a real problem
            pass

    def translate(self, question: str, prompt: str) -> str:
        body = {"model": self.model, "prompt": prompt, "stream": False, "keep_alive": self.keep_alive,
                # thinking models (qwen3, deepseek-r1 ...) would first write a long hidden reasoning: skip it
                "think": False,
                "options": {"temperature": 0, "num_predict": int(os.environ.get("KG2A_LLM_MAX_TOKENS", "512")),
                            "num_ctx": int(os.environ.get("KG2A_LLM_NUM_CTX", "8192"))}}
        r = httpx.post(self.url + "/api/generate", timeout=self.timeout, json=body)
        if r.status_code == 400 and "think" in r.text.lower():  # an Ollama or model that rejects the option
            body.pop("think")
            r = httpx.post(self.url + "/api/generate", timeout=self.timeout, json=body)
        r.raise_for_status()
        return strip_thinking(r.json().get("response", ""))


class OpenAICompatibleTranslator:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or os.environ.get("KG2A_OPENAI_BASE_URL", "http://localhost:8080/v1")).rstrip("/")
        self.model = model or os.environ.get("KG2A_OPENAI_MODEL", "qwen2.5-coder-3b-instruct")
        self.api_key = api_key or os.environ.get("KG2A_OPENAI_API_KEY", "")
        self.name = f"openai-compatible:{self.model}"

    def translate(self, question: str, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        r = httpx.post(self.base_url + "/chat/completions", headers=headers, timeout=120, json={
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM_RULES}, {"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


_LLM_CHECK: dict = {"at": 0.0, "value": None}


def llm_available() -> dict:
    """Is an LLM server reachable for the Ask translator? (checked at most every 20 s)"""
    import time

    if _LLM_CHECK["value"] is None or time.time() - _LLM_CHECK["at"] > 20:
        info = ollama_models()
        _LLM_CHECK.update(at=time.time(), value={"server": info["server"], "model": OllamaTranslator().model,
                                                 "reachable": info["reachable"], "models": len(info["models"])})
    return _LLM_CHECK["value"]


ANALYTIC = re.compile(r"\b(total|sum|average|avg|mean|how much|how many|count|number of|per|by|each|max|maximum|"
                      r"min|minimum|highest|lowest|top|most|least)\b", re.I)

AGG_WORDS = [
    ("avg", ("average", "avg", "mean", "typical")),
    ("max", ("maximum", "max", "highest", "peak", "largest", "biggest")),
    ("min", ("minimum", "min", "lowest", "smallest")),
    ("count", ("how many", "number of", "count of", "count")),
    ("sum", ("total", "sum", "overall", "combined")),
]
IDENTITY_WORDS = ("shared", "same", "both", "linked", "aligned", "common", "corporate", "who also", "across domains",
                  "identity", "sameas", "matched")
MUTATION_REQUEST = re.compile(r"^\s*(please\s+)?(delete|remove|drop|insert|update|add|create|clear|erase|wipe|modify|change)\b", re.I)
DATE_WORDS = ("daily", "per day", "each day", "by day", "by date", "per date", "same day", "shared date")


@dataclass
class ParseTrace:
    cubes: list[str] = field(default_factory=list)
    measures: list[str] = field(default_factory=list)
    aggregate: str | None = None
    group_by: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    intent: str = ""
    matches: list[str] = field(default_factory=list)  # embedding / spelling matches used


class GroundedParser:
    """Deterministic intent parser: question -> (cube, measure, aggregate, axes, filters) -> SPARQL.

    Only catalogue vocabulary can come out of it, so it cannot hallucinate.
    """

    name = "grounded-parser"

    def __init__(self, cat: Catalog, store: MultiKGStore):
        self.cat, self.store = cat, store
        self.last_trace = ParseTrace()
        self._question = ""
        self._members: dict[str, list[tuple[str, str, str, str]]] = {}

    # -- vocabulary helpers -------------------------------------------------------
    def _member_index(self, cube: CubeInfo) -> list[tuple[str, str, str, str]]:
        """(member iri, label, dimension prop, level) for every labelled level member of the cube."""
        if cube.kg not in self._members:
            rows = []
            for d in cube.dimensions:
                for lvl in d.levels:
                    q = (f"SELECT DISTINCT ?m ?l WHERE {{ GRAPH <{cube.graph}> {{ {Catalog.member_pattern('m', lvl)} . "
                         f"?m <http://www.w3.org/2000/01/rdf-schema#label> ?l }} }}")
                    for r in self.store.query(q).rows:
                        rows.append((r["m"], str(r["l"]), d.prop, lvl))
            self._members[cube.kg] = rows
        return self._members[cube.kg]

    def _measure(self, cube: CubeInfo, qtoks: list[str]):
        best, best_s = None, 0.0
        for m in cube.measures:
            mt = set(tokens(local_name(m.iri))) | set(tokens(m.label))
            s = sum(1 for t in qtoks if t in mt or t.rstrip("s") in mt)
            if s > best_s:
                best, best_s = m, s
        if best is None and self._question:
            head = re.split(r"\b(?:by|per|for each|grouped by|broken down by|in|at|for)\b", self._question.lower())[0]
            hit = semantic.SemanticIndex([(m.iri, m.label) for m in cube.measures]).match(semantic.phrases(head))
            if hit:
                self._note(hit)
                return next(m for m in cube.measures if m.iri == hit.key)
        if best is None:
            best = next((m for m in cube.measures if m.additivity == "additive"), cube.measures[0] if cube.measures else None)
        return best

    def _aggregate(self, q: str, cubes: list[CubeInfo] | None = None) -> str | None:
        ql = " ".join(tokens(q))
        # words inside a measure's own name are not aggregate requests ("occupancy count", "max temperature")
        for c in cubes or []:
            for m in c.measures:
                for phrase in {" ".join(tokens(local_name(m.iri))), " ".join(tokens(m.label))}:
                    if len(phrase.split()) > 1:
                        ql = re.sub(rf"\b{re.escape(phrase)}\b", " ", ql)
        for agg, words in AGG_WORDS:
            if any(re.search(rf"\b{re.escape(w)}\b", ql) for w in words):
                if agg == "max" and re.search(r"\btop\s+\d+", ql):
                    continue
                return agg
        return None

    def _axes(self, cube: CubeInfo, q: str) -> list[Axis]:
        ql = q.lower()
        axes = []
        for m in re.finditer(r"\b(?:by|per|for each|each|across|grouped by|broken down by)\s+([a-z][a-z \-]*)", ql):
            phrase = [t for t in tokens(m.group(1))[:3] if t not in ("and", "the", "in", "for")]
            phrase = phrase[: next((i for i, t in enumerate(phrase) if t in ("in", "of")), len(phrase))]
            hit = self._match_level(cube, phrase)
            if hit and hit not in [(a.dimension, a.level) for a in axes]:
                axes.append(Axis(*hit))
        if not axes:
            for w, lvl in (("monthly", "Month"), ("quarterly", "Quarter"), ("yearly", "Year"), ("annual", "Year"), ("daily", "Day")):
                if w in ql:
                    hit = self._match_level(cube, [lvl.lower()])
                    if hit:
                        axes.append(Axis(*hit))
        return axes

    def _match_level(self, cube: CubeInfo, phrase: list[str]):
        for word in reversed(phrase):  # head noun last: "product category" -> Category
            w = word.rstrip("s") if len(word) > 3 else word
            for d in cube.dimensions:  # level names first (Category, Month, Country ...)
                for lvl in d.levels:
                    if w in [t.rstrip("s") for t in tokens(d.level_name(lvl))]:
                        return (d.prop, lvl)
            for d in cube.dimensions:  # then dimension property names (customer, store, trader ...)
                if w in [t.rstrip("s") for t in tokens(d.name)]:
                    return (d.prop, None)
        # no exact word: match the phrase by meaning or spelling ("town" -> City, "catagory" -> Category)
        items = [((d.prop, lvl), d.level_name(lvl)) for d in cube.dimensions for lvl in d.levels]
        items += [((d.prop, None), d.name) for d in cube.dimensions]
        hit = semantic.SemanticIndex(items).match(semantic.phrases(" ".join(phrase)))
        if hit:
            self._note(hit)
            return hit.key
        return None

    def _filters(self, cube: CubeInfo, q: str, axes: list[Axis]) -> list[Filter]:
        caps = set(re.findall(r"\b[A-Z][a-zA-Z0-9\-]+", q)) | set(re.findall(r"\b\d{4}(?:-Q\d|-\d{2})?\b", q))
        caps |= {x for x in re.findall(r'"([^"]+)"', q)}
        out, seen = [], set()
        for iri, label, dprop, lvl in self._member_index(cube):
            lt = label.split()
            if label in caps or (lt and lt[0] in caps and len(lt[0]) > 2 and lt[0] not in ("Store", "Meter", "Sensor", "Room", "Broker", "Order")):
                if any(a.dimension == dprop and (a.level in (None, lvl)) for a in axes):
                    continue
                key = (dprop, lvl, iri)
                if key not in seen:
                    seen.add(key)
                    out.append(Filter(dprop, iri, lvl))
        return out[:3]

    def _note(self, hit) -> None:
        if hit.describe() not in self.last_trace.matches:
            self.last_trace.matches.append(hit.describe())

    def _semantic_cubes(self, question: str, exclude: str | None = None) -> list[str]:
        """KGs whose vocabulary the question matches by meaning or spelling (no KG word in the question)."""
        if not ANALYTIC.search(question):
            return []  # not an analytic request ("who won the world cup?"): stay out of scope
        # a KG is chosen by what is measured (its measures, fact class, name), never by a level alone
        items = []
        for c in (c for c in self.cat.cubes if c.kg != exclude):
            items += [(c.kg, c.kg), (c.kg, c.label)] + [(c.kg, m.label) for m in c.measures]
        index = semantic.SemanticIndex(items)
        first = index.match(semantic.phrases(question))
        if not first:
            return []
        self._note(first)
        found = [first.key]
        if identity_intent(question):  # a join needs a second KG
            rest = {c.kg for c in self.cat.cubes} - {first.key}
            second = index.match(semantic.phrases(question), keys=rest)
            if second:
                self._note(second)
                found.append(second.key)
        return found

    def _identity_dim(self, cube: CubeInfo):
        """The dimension whose members participate in the identity graph."""
        best, best_n = None, 0
        for d in cube.dimensions:
            q = (f"SELECT (COUNT(DISTINCT ?m) AS ?n) WHERE {{ GRAPH <{cube.graph}> {{ ?o <{d.prop}> ?m }} "
                 f"GRAPH <{IDENTITY_GRAPH}> {{ ?m <http://www.w3.org/2002/07/owl#sameAs> ?x }} }}")
            n = int(self.store.query(q).rows[0]["n"] or 0)
            if n > best_n:
                best, best_n = d, n
        return best

    def _date_dim(self, cube: CubeInfo):
        return next((d for d in cube.dimensions if d.level_name(d.base_level).lower() in ("day", "date", "time")), None)

    # -- translation ------------------------------------------------------------------
    def translate(self, question: str, prompt: str = "") -> str:
        tr = ParseTrace()
        self.last_trace = tr
        if MUTATION_REQUEST.search(question):
            tr.intent = "mutation request (refused: the interface is read-only)"
            return ""
        self._question = question
        kgs = mentioned_domains(question, self.cat)
        if not kgs:
            kgs = self._semantic_cubes(question)
        elif len(kgs) == 1 and identity_intent(question) and len(self.cat.cubes) > 1:
            kgs += self._semantic_cubes(question, exclude=kgs[0])[:1]  # "... and money sent, for customers in both"
        tr.cubes = kgs
        if not kgs:
            return ""  # out of scope: nothing in the catalogue matches
        qtoks = tokens(question)
        agg = self._aggregate(question, [c for c in (self.cat.cube_for(k) for k in kgs) if c])
        tr.aggregate = agg
        ql = question.lower()
        if len(kgs) >= 2:
            a, b = self.cat.cube_for(kgs[0]), self.cat.cube_for(kgs[1])
            ma, mb = self._measure(a, qtoks), self._measure(b, qtoks)
            tr.measures = [ma.iri, mb.iri]
            if any(w in ql for w in DATE_WORDS):
                da, db = self._date_dim(a), self._date_dim(b)
                if da and db:
                    tr.intent = "cross-cube conformed date (pushdown)"
                    q = CrossCubeQuery(CubeSide(a.kg, a.dataset, da.prop, ma.iri, agg or ma.aggregate),
                                       CubeSide(b.kg, b.dataset, db.prop, mb.iri, agg or mb.aggregate), "shared")
                    return pushdown_sparql(q)
            da, db = self._identity_dim(a), self._identity_dim(b)
            if da and db:
                tr.intent = "cross-cube identity join (pushdown)"
                q = CrossCubeQuery(CubeSide(a.kg, a.dataset, da.prop, ma.iri, agg or ma.aggregate),
                                   CubeSide(b.kg, b.dataset, db.prop, mb.iri, agg or mb.aggregate), "identity")
                return pushdown_sparql(q)
            tr.intent = "no join intent between domains; answering over the first-mentioned cube"
        cube = self.cat.cube_for(kgs[0])
        m = self._measure(cube, qtoks)
        if m is None:
            return ""
        axes = self._axes(cube, question)
        filters = self._filters(cube, question, axes)
        limit = 200
        top = re.search(r"\btop\s+(\d+)", ql)
        if top:
            limit = int(top.group(1))
            if not axes:
                hit = self._match_level(cube, qtoks)
                if hit:
                    axes = [Axis(*hit)]
        tr.measures = [m.iri]
        tr.group_by = [f"{local_name(a.dimension)}:{local_name(a.level) if a.level else 'base'}" for a in axes]
        tr.filters = [f"{local_name(f.dimension)}={f.value}" for f in filters]
        tr.intent = "roll-up" if axes else "aggregate"
        return build_rollup(self.cat, cube.kg, m.iri, axes, filters, agg, limit).sparql


def identity_intent(question: str) -> bool:
    ql = question.lower()
    return any(w in ql for w in IDENTITY_WORDS)


def strip_thinking(text: str) -> str:
    """Drop a reasoning block (<think>...</think>, also an unterminated one) that some models emit before answering."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return re.sub(r"<think>.*", "", text, flags=re.S | re.I).strip()


def extract_sparql(text: str) -> str:
    m = re.search(r"```(?:sparql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()
