"""Dynamic schema catalogue and compact aliases (thesis section 3.6.3, appendix B).

Built at runtime by querying every source's QB4OLAP schema graph, so it only
ever contains vocabulary that really exists in the store.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.store import IDENTITY_GRAPH, MultiKGStore, data_graph, schema_graph

PFX = """PREFIX qb: <http://purl.org/linked-data/cube#>
PREFIX qb4o: <http://purl.org/qb4olap/cubes#>
PREFIX kg2a: <http://example.org/kg2a#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""
STANDARD = {
    "qb": "http://purl.org/linked-data/cube#",
    "qb4o": "http://purl.org/qb4olap/cubes#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


@dataclass
class MeasureInfo:
    iri: str
    label: str
    aggregate: str
    additivity: str
    unit: str | None = None


@dataclass
class StepInfo:
    child: str
    parent: str
    prop: str
    many_to_many: bool = False


@dataclass
class DimensionInfo:
    prop: str
    base_level: str
    kinds: list[str] = field(default_factory=list)
    steps: list[StepInfo] = field(default_factory=list)

    @property
    def levels(self) -> list[str]:
        out = [self.base_level]
        for s in self.steps:
            for x in (s.child, s.parent):
                if x not in out:
                    out.append(x)
        return out

    def paths_to(self, level: str) -> list[list[str]]:
        """Roll-up property chains from the base level to ``level`` (several when ragged/alternative)."""
        out: list[list[str]] = []

        def walk(cur, props, seen):
            if cur == level:
                out.append(props)
                return
            for s in self.steps:
                if s.child == cur and s.parent not in seen and s.child != s.parent:
                    walk(s.parent, props + [s.prop], seen | {s.parent})

        walk(self.base_level, [], {self.base_level})
        return out


@dataclass
class CubeInfo:
    kg: str
    dataset: str
    fact_class: str
    label: str
    measures: list[MeasureInfo]
    dimensions: list[DimensionInfo]

    @property
    def graph(self) -> str:
        return str(data_graph(self.kg))

    def measure(self, iri_or_name: str) -> MeasureInfo | None:
        return next((m for m in self.measures if m.iri == iri_or_name or local_name(m.iri) == iri_or_name), None)

    def dimension(self, iri_or_name: str) -> DimensionInfo | None:
        return next((d for d in self.dimensions if d.prop == iri_or_name or local_name(d.prop) == iri_or_name), None)


class Catalog:
    def __init__(self, cubes: list[CubeInfo], identity_links: int = 0):
        self.cubes = cubes
        self.identity_links = identity_links
        self.prefixes: dict[str, str] = {}  # alias prefix -> namespace
        for c in cubes:
            ns = c.fact_class[: c.fact_class.rfind("#") + 1] if "#" in c.fact_class else c.fact_class.rsplit("/", 1)[0] + "/"
            self.prefixes[alias_prefix(c.kg)] = ns
        self.known_iris: set[str] = set()
        for c in cubes:
            self.known_iris |= {c.dataset, c.fact_class, c.graph, str(schema_graph(c.kg))}
            self.known_iris |= {m.iri for m in c.measures}
            for d in c.dimensions:
                self.known_iris |= {d.prop, d.base_level}
                for s in d.steps:
                    self.known_iris |= {s.child, s.parent, s.prop}
        self.known_iris.add(str(IDENTITY_GRAPH))

    @classmethod
    def build(cls, store: MultiKGStore) -> "Catalog":
        cubes = []
        for kg, ep in store.sources.items():
            sg = schema_graph(kg)
            try:
                _, ds_rows = ep.select(PFX + f"""SELECT ?ds ?fc ?label WHERE {{ GRAPH <{sg}> {{
                    ?ds a qb:DataSet ; kg2a:factClass ?fc . OPTIONAL {{ ?ds rdfs:label ?label }} }} }}""")
            except Exception:  # remote KG without a KG2MD schema graph
                continue
            for r in ds_rows:
                ds = r["ds"]
                _, ms = ep.select(PFX + f"""SELECT ?m ?label ?agg ?add ?unit WHERE {{ GRAPH <{sg}> {{
                    <{ds}> qb:structure ?dsd . ?dsd qb:component ?c . ?c qb:measure ?m ; qb4o:aggregateFunction ?agg .
                    OPTIONAL {{ ?m rdfs:label ?label }} OPTIONAL {{ ?m kg2a:additivity ?add }} OPTIONAL {{ ?m kg2a:unit ?unit }}
                }} }} ORDER BY ?m""")
                _, ds_dims = ep.select(PFX + f"""SELECT ?p ?base ?dim WHERE {{ GRAPH <{sg}> {{
                    <{ds}> qb:structure ?dsd . ?dsd qb:component ?c . ?c qb4o:level ?p . ?p kg2a:memberClass ?base .
                    ?dim kg2a:factProperty ?p . }} }} ORDER BY ?p""")
                dims = []
                for d in ds_dims:
                    _, kinds = ep.select(PFX + f"SELECT ?k WHERE {{ GRAPH <{sg}> {{ <{d['dim']}> kg2a:hierarchyKind ?k }} }}")
                    _, steps = ep.select(PFX + f"""SELECT ?c ?p ?r ?card WHERE {{ GRAPH <{sg}> {{ ?s kg2a:dimension <{d['dim']}> ;
                        qb4o:childLevel ?c ; qb4o:parentLevel ?p ; qb4o:rollup ?r ; qb4o:pcCardinality ?card }} }}
                        ORDER BY ?c ?p""")
                    dims.append(DimensionInfo(d["p"], d["base"], sorted(k["k"] for k in kinds),
                                              [StepInfo(s["c"], s["p"], s["r"], s["card"].endswith("ManyToMany")) for s in steps]))
                cubes.append(CubeInfo(
                    kg, ds, r["fc"], r.get("label") or local_name(r["fc"]),
                    [MeasureInfo(m["m"], m.get("label") or local_name(m["m"]), local_name(m["agg"]),
                                 m.get("add") or "additive", m.get("unit")) for m in ms],
                    dims))
        return cls(cubes, len(store.identity) // 2)

    # -- aliases ----------------------------------------------------------------------
    def alias(self, iri: str) -> str:
        for p, ns in self.prefixes.items():
            if iri.startswith(ns) and re.fullmatch(r"[A-Za-z0-9_\-]+", iri[len(ns):]):
                return f"{p}:{iri[len(ns):]}"
        return f"<{iri}>"

    def alias_map(self) -> dict[str, str]:
        return {self.alias(i): i for i in sorted(self.known_iris) if not self.alias(i).startswith("<")}

    def prefix_block(self) -> str:
        lines = [f"PREFIX {p}: <{ns}>" for p, ns in {**STANDARD, **self.prefixes}.items()]
        return "\n".join(lines)

    def cube_for(self, kg: str) -> CubeInfo | None:
        return next((c for c in self.cubes if c.kg == kg), None)

    def prompt_context(self) -> str:
        """Grounded schema text for the LLM prompt (appendix B.1)."""
        out = ["=== ACTIVE SCHEMA CATALOGUE ===", "Datasets:"]
        for c in self.cubes:
            out.append(f"- {self.alias(c.dataset)} (Graph: <{c.graph}>)  fact class {self.alias(c.fact_class)}")
            out.append("  Measures: [" + ", ".join(f"{self.alias(m.iri)} ({m.aggregate})" for m in c.measures) + "]")
            out.append("  Dimensions: [" + ", ".join(self.alias(d.prop) for d in c.dimensions) + "]")
            for d in c.dimensions:
                for s in d.steps:
                    out.append(f"    roll-up: {self.alias(s.child)} --{self.alias(s.prop)}--> {self.alias(s.parent)}")
        out.append(f"- Inter-KG Identity Graph: <{IDENTITY_GRAPH}> (Predicate: owl:sameAs)")
        out.append("\n=== COMPACT ALIASES ===")
        for p, ns in {**self.prefixes, **STANDARD}.items():
            out.append(f"{p}: -> <{ns}>")
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "identity_links": self.identity_links,
            "prefixes": self.prefixes,
            "cubes": [{
                "kg": c.kg, "dataset": c.dataset, "alias": self.alias(c.dataset), "fact_class": c.fact_class,
                "label": c.label, "graph": c.graph,
                "measures": [m.__dict__ | {"alias": self.alias(m.iri)} for m in c.measures],
                "dimensions": [{"prop": d.prop, "alias": self.alias(d.prop), "base_level": d.base_level,
                                "kinds": d.kinds, "levels": d.levels,
                                "steps": [s.__dict__ for s in d.steps]} for d in c.dimensions],
            } for c in self.cubes],
        }


def alias_prefix(kg: str) -> str:
    special = {"supplychain": "SupplyChain", "building": "Building"}
    return special.get(kg, kg[:1].upper() + kg[1:])
