"""Four-stage validation of generated SPARQL (thesis section 3.6.3, appendix B.3).

1. Syntax    - parses as a SPARQL 1.1 SELECT/ASK query (RDFLib parser)
2. Grounding - every IRI exists in the schema catalogue or as a node of the store
3. Scope     - every domain the question mentions is covered by the query's graphs/datasets
4. Safety    - no update/mutation verbs and no SERVICE calls
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rdflib import URIRef
from rdflib.paths import Path
from rdflib.plugins.sparql import prepareQuery

from kg2analyzer.catalog import STANDARD, Catalog
from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.graphml import tokens

MUTATION = re.compile(r"(?<![?$\w:])(INSERT|DELETE|CLEAR|DROP|CREATE|LOAD|COPY|MOVE|ADD)\b", re.I)  # not ?add
SERVICE = re.compile(r"(?<![?$\w:])SERVICE\b", re.I)
STANDARD_TERMS = {
    STANDARD["qb"] + t for t in ("dataSet", "Observation", "DataSet", "structure", "component", "measure")
} | {STANDARD["qb4o"] + t for t in ("memberOf", "level", "rollup", "LevelProperty")} | {
    STANDARD["owl"] + "sameAs", STANDARD["rdf"] + "type", STANDARD["rdfs"] + "label",
    STANDARD["rdfs"] + "subClassOf",
}
STOP = {"the", "and", "for", "with", "from", "total", "sum", "average", "count", "number", "show", "list",
        "what", "which", "each", "per", "across", "between", "over", "date", "amount", "value", "level",
        "type", "data", "graph", "cost", "count", "reading", "readings"}


@dataclass
class Check:
    rule: str
    ok: bool
    message: str


def _iris(node, out: set[str]) -> None:
    if isinstance(node, URIRef):
        out.add(str(node))
    elif isinstance(node, Path):
        for attr in ("args", "path"):
            v = getattr(node, attr, None)
            if v is not None:
                _iris(v, out)
    elif isinstance(node, dict):
        for v in node.values():
            _iris(v, out)
    elif isinstance(node, (list, tuple, set)):
        for v in node:
            _iris(v, out)


def domain_keywords(cat: Catalog) -> dict[str, set[str]]:
    """Words that signal each KG/domain in a question, derived from the live catalogue."""
    raw: dict[str, set[str]] = {}
    for c in cat.cubes:
        words = set(tokens(c.kg)) | {c.kg.lower()} | set(tokens(local_name(c.fact_class)))
        for m in c.measures:
            words |= set(tokens(local_name(m.iri)))
        for d in c.dimensions:
            words |= set(tokens(local_name(d.prop)))
            for lvl in d.levels:
                words |= set(tokens(local_name(lvl)))
        raw[c.kg] = {w for w in words if len(w) > 3 and w not in STOP}
    # keep only words unique to one domain (plus the domain name itself)
    out = {}
    for kg, words in raw.items():
        others = set().union(*(w for k, w in raw.items() if k != kg)) if len(raw) > 1 else set()
        out[kg] = (words - others) | {kg.lower()}
    return out


def mentioned_domains(question: str, cat: Catalog) -> list[str]:
    toks = tokens(question)
    stems = {t.rstrip("s") for t in toks} | set(toks)
    found = []
    for kg, words in domain_keywords(cat).items():
        pos = [i for i, t in enumerate(toks) if t in words or t.rstrip("s") in words or any(
            w.rstrip("s") == t.rstrip("s") for w in words)]
        if pos or (words & stems):
            found.append((min(pos) if pos else 10**6, kg))
    return [kg for _, kg in sorted(found)]


class Validator:
    def __init__(self, cat: Catalog, node_exists=None):
        self.cat = cat
        self.node_exists = node_exists or (lambda iri: False)

    def validate(self, sparql: str, question: str = "") -> list[Check]:
        checks: list[Check] = []
        parsed = None
        try:
            parsed = prepareQuery(sparql)
            kind = parsed.algebra.name
            if kind not in ("SelectQuery", "AskQuery"):
                raise ValueError(f"only SELECT/ASK queries are allowed, got {kind}")
            checks.append(Check("syntax", True, "parses as SPARQL 1.1 " + kind))
        except Exception as e:  # noqa: BLE001
            checks.append(Check("syntax", False, f"parse error: {str(e)[:300]}"))
        if parsed is not None:
            found: set[str] = set()
            _iris(parsed.algebra, found)
            unknown = sorted(i for i in found if i not in self.cat.known_iris and i not in STANDARD_TERMS
                             and not i.startswith(STANDARD["xsd"]) and not self.node_exists(i))
            checks.append(Check("grounding", not unknown,
                                "all IRIs grounded in the catalogue" if not unknown else
                                "ungrounded IRIs: " + ", ".join(self.cat.alias(u) for u in unknown[:8])))
            needed = mentioned_domains(question, self.cat) if question else []
            missing = []
            for kg in needed:
                cube = self.cat.cube_for(kg)
                if cube and cube.graph not in found and cube.dataset not in found:
                    missing.append(kg)
            checks.append(Check("scope", not missing,
                                f"covers domains {needed}" if not missing else
                                f"question mentions {missing} but the query never scopes their graph/dataset "
                                f"({', '.join('<' + self.cat.cube_for(k).graph + '>' for k in missing)})"))
        bad = MUTATION.findall(_strip_literals(sparql))
        svc = SERVICE.search(_strip_literals(sparql))
        msg = []
        if bad:
            msg.append("mutation verbs " + ", ".join(sorted({b.upper() for b in bad})))
        if svc:
            msg.append("external SERVICE call")
        checks.append(Check("safety", not msg, "read-only, no SERVICE" if not msg else "rejected: " + "; ".join(msg)))
        return checks


def _strip_literals(q: str) -> str:
    q = re.sub(r"<[^>\s]*>", "<>", q)
    q = re.sub(r'"(?:\\.|[^"\\])*"', '""', q)
    return re.sub(r"#[^\n]*", "", q)
