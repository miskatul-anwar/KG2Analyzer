"""Dynamic schema catalogue and compact aliases (thesis section 3.6.3, appendix B).

Built at runtime by querying every source's QB4OLAP schema graph, so it only
ever contains vocabulary that really exists in the store.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from hashlib import sha256

from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.store import IDENTITY_GRAPH, MultiKGStore, data_graph, schema_graph, source_graph

PFX = """PREFIX qb: <http://purl.org/linked-data/cube#>
PREFIX qb4o: <http://purl.org/qb4olap/cubes#>
PREFIX kg2a: <http://example.org/kg2a#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX sdmx: <http://purl.org/linked-data/sdmx/2009/attribute#>
"""
ROLLUP_TO_ALL = "http://example.org/mdkg/rollupToAll"
_SUFFIX = re.compile(r"(?:_[0-9a-f]{12,})?_(?:level|dimension)(?:_hierarchy_[0-9a-f]+|_all)?$|_measure$")


def display_name(iri: str, label: str | None = None) -> str:
    """A readable name: the label without a trailing ' Level'/' Dimension', else the local name without
    the KG2MD notebook's hash suffixes (``City_eaf6..._level`` -> ``City``)."""
    if label:
        return re.sub(r"\s+(Level|Dimension|measure)$", "", str(label)).strip() or str(label)
    n = local_name(iri)
    return _SUFFIX.sub("", n) or n

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
    source: str | None = None  # the source property the measure was built from (KG2MD notebook cubes)


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
    label: str | None = None
    level_labels: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return display_name(self.prop, self.label)

    def level_name(self, level: str) -> str:
        return display_name(level, self.level_labels.get(level))

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
        key = iri_or_name.lower()
        return (next((m for m in self.measures if m.iri == iri_or_name or local_name(m.iri) == iri_or_name), None)
                or next((m for m in self.measures if m.label.lower() == key or display_name(m.iri).lower() == key), None))

    def dimension(self, iri_or_name: str) -> DimensionInfo | None:
        key = iri_or_name.lower()
        return (next((d for d in self.dimensions if d.prop == iri_or_name or local_name(d.prop) == iri_or_name), None)
                or next((d for d in self.dimensions if d.name.lower() == key), None))


class Catalog:
    def __init__(self, cubes: list[CubeInfo], identity_links: int = 0):
        self.cubes = cubes
        self.identity_links = identity_links
        self.prefixes: dict[str, str] = {}  # alias prefix -> namespace
        for c in cubes:
            ns = c.fact_class[: c.fact_class.rfind("#") + 1] if "#" in c.fact_class else c.fact_class.rsplit("/", 1)[0] + "/"
            self.prefixes.setdefault(alias_prefix(c.kg), ns)
            cube_ns = c.dataset.rsplit("/", 1)[0] + "/"
            if "/fact_classes/" in c.dataset and cube_ns != ns:  # KG2MD notebook cube namespace
                self.prefixes.setdefault(alias_prefix(c.kg) + "Cube", cube_ns)
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
            if not ds_rows:
                cubes += _notebook_cubes(kg, ep)
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

    @staticmethod
    def member_pattern(var: str, level: str) -> str:
        """SPARQL pattern binding ``?var`` to the members of ``level`` (class-typed or qb4o:memberOf)."""
        return (f"{{ ?{var} a <{level}> }} UNION "
                f"{{ ?{var} <http://purl.org/qb4olap/cubes#memberOf> <{level}> }}")

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
                                "name": d.name, "level_names": {lv: d.level_name(lv) for lv in d.levels},
                                "kinds": d.kinds, "levels": d.levels,
                                "steps": [s.__dict__ for s in d.steps]} for d in c.dimensions],
            } for c in self.cubes],
        }


def alias_prefix(kg: str) -> str:
    special = {"supplychain": "SupplyChain", "building": "Building"}
    return special.get(kg, kg[:1].upper() + kg[1:])


def _notebook_cubes(kg: str, ep) -> list[CubeInfo]:
    """Cubes written by the KG2MD notebook: the dataset lives in the data graph and points at its bottom
    cuboid; levels are qb4o:LevelProperty IRIs; members roll up through the source properties."""
    sg, dg, src = schema_graph(kg), data_graph(kg), source_graph(kg)
    try:
        _, ds_rows = ep.select(PFX + f"""SELECT ?ds ?cuboid ?cube ?label WHERE {{
            GRAPH <{dg}> {{ ?ds a qb:DataSet ; qb:structure ?cuboid }}
            GRAPH <{sg}> {{ ?cuboid qb4o:isCuboidOf ?cube . OPTIONAL {{ ?cube rdfs:label ?label }} }} }} ORDER BY ?ds""")
    except Exception:
        return []
    try:
        _, preds = ep.select(f"SELECT DISTINCT ?p WHERE {{ GRAPH <{src}> {{ ?s ?p ?o }} }}")
    except Exception:
        preds = []
    by_lower = {}
    for r in preds:
        by_lower.setdefault(local_name(r["p"]).lower(), r["p"])
    out = []
    for r in ds_rows:
        cuboid, ds = r["cuboid"], r["ds"]
        _, ms = ep.select(PFX + f"""SELECT ?m ?agg ?unit WHERE {{ GRAPH <{sg}> {{
            <{cuboid}> qb:component ?c . ?c qb:measure ?m ; qb4o:aggregateFunction ?agg .
            OPTIONAL {{ ?m sdmx:unitMeasure ?unit }} }} }} ORDER BY ?m""")
        measures = []
        for m in ms:
            agg = local_name(m["agg"]).lower()
            stem = local_name(m["m"]).removesuffix("_measure")
            source = by_lower.get(stem.lower())
            measures.append(MeasureInfo(m["m"], local_name(source) if source else stem, agg,
                                        "additive" if agg in ("sum", "count") else "non-additive", m.get("unit"), source))
        _, ds_dims = ep.select(PFX + f"""SELECT ?dim ?base ?dl ?bl WHERE {{ GRAPH <{sg}> {{
            <{cuboid}> qb:component ?c . ?c qb:dimension ?dim ; qb4o:level ?base .
            OPTIONAL {{ ?dim rdfs:label ?dl }} OPTIONAL {{ ?base rdfs:label ?bl }} }} }} ORDER BY ?dim""")
        dims = []
        for d in ds_dims:
            _, steps = ep.select(PFX + f"""SELECT DISTINCT ?h ?c ?p ?r ?card ?cl ?pl WHERE {{ GRAPH <{sg}> {{
                <{d['dim']}> qb4o:hasHierarchy ?h . ?s qb4o:inHierarchy ?h ; qb4o:childLevel ?c ; qb4o:parentLevel ?p ;
                qb4o:rollup ?r ; qb4o:pcCardinality ?card . OPTIONAL {{ ?c rdfs:label ?cl }} OPTIONAL {{ ?p rdfs:label ?pl }}
                FILTER(?r != <{ROLLUP_TO_ALL}>) }} }} ORDER BY ?c ?p ?r""")
            labels = {d["base"]: d.get("bl")} if d.get("bl") else {}
            seen, infos, hierarchies = set(), [], set()
            for st in steps:
                hierarchies.add(st["h"])
                for lv, lb in ((st["c"], st.get("cl")), (st["p"], st.get("pl"))):
                    if lb:
                        labels[lv] = lb
                key = (st["c"], st["p"], st["r"])
                if key not in seen:
                    seen.add(key)
                    infos.append(StepInfo(st["c"], st["p"], st["r"], st["card"].endswith("ManyToMany")))
            kinds = set()
            if any(s.child == s.parent for s in infos):
                kinds.add("recursive")
            if any(s.many_to_many for s in infos):
                kinds.add("nonstrict")
            if len(hierarchies) > 1:
                kinds.add("multiple")
            dims.append(DimensionInfo(d["dim"], d["base"], sorted(kinds) or ["balanced"], infos, d.get("dl"), labels))
        fact = _fact_class(ep, dg, src, ds)
        out.append(CubeInfo(kg, ds, fact, local_name(fact), measures, dims))
    return out


def _fact_class(ep, dg, src, ds: str) -> str:
    """The class whose instances the observations derive from. The notebook names each cube's namespace
    ``fact_classes/<name>_<sha256(fact class)[:12]>/``, which identifies the class exactly."""
    key = ds.rsplit("/fact_classes/", 1)[-1].split("/", 1)[0] if "/fact_classes/" in ds else ""
    digest = key.rsplit("_", 1)[-1] if "_" in key else ""
    try:
        _, rows = ep.select(f"""SELECT ?t (COUNT(?o) AS ?n) WHERE {{
            GRAPH <{dg}> {{ ?o <http://purl.org/linked-data/cube#dataSet> <{ds}> ;
                             <http://www.w3.org/ns/prov#wasDerivedFrom> ?f }}
            GRAPH <{src}> {{ ?f a ?t }} }} GROUP BY ?t ORDER BY DESC(?n) ?t""")
    except Exception:
        rows = []
    for r in rows:
        if digest and sha256(str(r["t"]).encode()).hexdigest()[:12] == digest:
            return r["t"]
    if rows:
        return rows[0]["t"]
    base = key.rsplit("_", 1)[0] if key else local_name(ds).removesuffix("_Dataset")
    return ds.rsplit("/", 1)[0] + "/" + base
