"""Phase I: Knowledge Graph -> Multidimensional Knowledge Graph (KG2MD).

``run_kg2md`` is the single entry point: closure, profiling, Otsu fact
selection, measure classification, hierarchy discovery, QB4OLAP
materialisation and the observation-to-fact audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kg2analyzer.kg2md.hierarchies import Dimension, discover_dimensions
from kg2analyzer.kg2md.measures import AGG_IRIS, MeasureClassifier, MeasureDecision
from kg2analyzer.kg2md.profiling import (
    ClassProfile, FactScorer, FactSelection, instance_classes, is_numeric_literal, local_name,
    profile_classes, rdfs_closure, select_fact_classes,
)

QB = Namespace("http://purl.org/linked-data/cube#")
QB4O = Namespace("http://purl.org/qb4olap/cubes#")
KG2A = Namespace("http://example.org/kg2a#")
UNIT_PROPS = (URIRef("http://example.org/vocab#unit"),
              URIRef("http://purl.org/linked-data/sdmx/2009/attribute#unitMeasure"),
              URIRef("http://www.ontology-of-units-of-measure.org/resource/om-2/hasUnit"))


@dataclass
class Measure:
    iri: URIRef
    label: str
    datatype: str
    unit: str | None
    decision: MeasureDecision

    @property
    def aggregate(self) -> str:
        return self.decision.aggregate


@dataclass
class Cube:
    """One materialised QB4OLAP cube."""

    fact_class: URIRef
    dataset: URIRef
    label: str
    measures: list[Measure]
    dimensions: list[Dimension]
    observations: int
    audit: dict = field(default_factory=dict)


@dataclass
class KG2MDResult:
    profiles: list[ClassProfile]
    selection: FactSelection
    cubes: list[Cube]
    schema: Graph  # QB4OLAP structure (datasets, DSDs, levels, hierarchies)
    data: Graph  # observations + level members with their roll-up links
    closure_added: int
    tbox_triples: int = 0
    abox_triples: int = 0
    undeclared_properties: list[str] = field(default_factory=list)  # ABox predicates the TBox does not declare


def _ns_of(iri: URIRef) -> str:
    s = str(iri)
    return s[: s.rfind("#") + 1] if "#" in s else s[: s.rfind("/") + 1]


STANDARD_NS = (str(RDF), str(RDFS), str(OWL), str(XSD))
DECLARED_PROPERTY_TYPES = (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, RDF.Property)


def run_kg2md(graph: Graph, classifier: MeasureClassifier | None = None, scorer: FactScorer | None = None,
              otsu_bins: int | None = None, max_facts: int | None = None, explain: bool = True,
              tbox: Graph | None = None) -> KG2MDResult:
    """KG -> MDKG. With ``tbox`` given, ``graph`` is the ABox: TBox entities are protected from
    instance inference and ABox properties that the TBox does not declare are reported (still profiled)."""
    abox_triples, tbox_triples, undeclared, protected = len(graph), 0, [], set()
    if tbox is not None:
        tbox_triples = len(tbox)
        protected = {s for s in tbox.subjects() if isinstance(s, URIRef)}
        declared = {p for t in DECLARED_PROPERTY_TYPES for p in tbox.subjects(RDF.type, t)}
        used = {p for _, p, _ in graph if isinstance(p, URIRef) and not str(p).startswith(STANDARD_NS)}
        undeclared = sorted(str(p) for p in used - declared)
        merged = Graph()
        for src in (tbox, graph):
            for t in src:
                merged.add(t)
            for prefix, uri in src.namespaces():
                merged.bind(prefix, uri, override=False)
        graph = merged
    g = rdfs_closure(graph, protected)
    profiles = profile_classes(g)
    selection = select_fact_classes(profiles, scorer, bins=otsu_bins, max_facts=max_facts)
    classifier = classifier or MeasureClassifier()
    types = instance_classes(g)
    schema, data = Graph(), Graph()
    for gg in (schema, data):
        gg.bind("qb", QB)
        gg.bind("qb4o", QB4O)
        gg.bind("kg2a", KG2A)
        for prefix, uri in graph.namespaces():
            gg.bind(prefix, uri, override=False)
    prof = {p.iri: p for p in profiles}
    cubes = [_materialise(g, graph, fc, prof[fc], types, classifier, schema, data, explain)
             for fc in selection.selected]
    return KG2MDResult(profiles, selection, cubes, schema, data, len(g) - len(graph), tbox_triples, abox_triples, undeclared)


def _unit(g: Graph, prop: URIRef) -> str | None:
    for up in UNIT_PROPS:
        v = g.value(prop, up)
        if v is not None:
            return local_name(v) if isinstance(v, URIRef) else str(v)
    return None


def _materialise(g: Graph, source: Graph, fact_class: URIRef, profile: ClassProfile, types, classifier,
                 schema: Graph, data: Graph, explain: bool) -> Cube:
    facts = {s for s, cs in types.items() if fact_class in cs}
    name = local_name(fact_class)
    ns = _ns_of(fact_class)
    dataset = URIRef(f"{ns}dataset-{name}")
    dsd = URIRef(f"{ns}dsd-{name}")

    # --- measures -------------------------------------------------------------
    measures: list[Measure] = []
    for p in profile.numeric_props:
        vals = [o.toPython() for f in facts for o in g.objects(f, p) if is_numeric_literal(o)]
        dts = {o.datatype for f in facts for o in g.objects(f, p) if isinstance(o, Literal)}
        dt = "xsd:" + local_name(next(iter(dts))) if dts and None not in dts else "xsd:decimal"
        bounded = bool(vals) and all(0 <= float(v) <= 1 for v in vals)
        unit = _unit(g, p)
        dec = classifier.classify(local_name(p), dt, unit, bounded, explain=explain)
        label = g.value(p, RDFS.label)
        measures.append(Measure(p, str(label) if label else local_name(p), dt, unit, dec))

    dims = discover_dimensions(g, fact_class, facts, types)

    # --- schema graph -----------------------------------------------------------
    S = schema
    S.add((dataset, RDF.type, QB.DataSet))
    S.add((dataset, RDFS.label, Literal(f"{name} cube")))
    S.add((dataset, QB.structure, dsd))
    S.add((dataset, KG2A.factClass, fact_class))
    S.add((dsd, RDF.type, QB.DataStructureDefinition))
    for d in dims:
        comp = BNode()
        S.add((dsd, QB.component, comp))
        S.add((comp, QB4O.level, d.prop))
        S.add((d.prop, RDF.type, QB4O.LevelProperty))
        S.add((d.prop, KG2A.memberClass, d.base_level))
        S.add((d.prop, RDFS.label, Literal(local_name(d.prop))))
        dim_iri = URIRef(f"{ns}dim-{local_name(d.prop)}")
        S.add((dim_iri, RDF.type, QB.DimensionProperty))
        S.add((dim_iri, KG2A.factProperty, d.prop))
        for k in d.kinds:
            S.add((dim_iri, KG2A.hierarchyKind, Literal(k)))
        for i, path in enumerate(d.paths):
            h = URIRef(f"{ns}hier-{local_name(d.prop)}-{i + 1}")
            S.add((dim_iri, QB4O.hasHierarchy, h))
            S.add((h, RDF.type, QB4O.Hierarchy))
            S.add((h, QB4O.inDimension, dim_iri))
            S.add((h, RDFS.label, Literal(" -> ".join(local_name(x) for x in path))))
            for lvl in path:
                S.add((h, QB4O.hasLevel, lvl))
                S.add((lvl, RDF.type, QB4O.LevelProperty))
        for st in d.steps:
            step = BNode()
            S.add((step, RDF.type, QB4O.HierarchyStep))
            S.add((step, KG2A.dimension, dim_iri))
            S.add((step, QB4O.childLevel, st.child))
            S.add((step, QB4O.parentLevel, st.parent))
            S.add((step, QB4O.rollup, st.prop))
            S.add((step, QB4O.pcCardinality, QB4O.ManyToMany if st.many_to_many else QB4O.ManyToOne))
            S.add((step, KG2A.coverage, Literal(round(st.coverage, 4), datatype=XSD.decimal)))
    for m in measures:
        comp = BNode()
        S.add((dsd, QB.component, comp))
        S.add((comp, QB.measure, m.iri))
        S.add((comp, QB4O.aggregateFunction, URIRef(AGG_IRIS[m.aggregate])))
        S.add((m.iri, RDF.type, QB.MeasureProperty))
        S.add((m.iri, RDFS.label, Literal(m.label)))
        S.add((m.iri, KG2A.additivity, Literal(m.decision.additivity)))
        S.add((m.iri, KG2A.additiveProbability, Literal(m.decision.additive_probability, datatype=XSD.decimal)))
        if m.unit:
            S.add((m.iri, KG2A.unit, Literal(m.unit)))

    # --- data graph: observations + level members ---------------------------------
    D = data
    dim_props = {d.prop for d in dims}
    mprops = {m.iri for m in measures}
    members: set[URIRef] = set()
    for f in facts:
        D.add((f, RDF.type, QB.Observation))
        D.add((f, QB.dataSet, dataset))
        for _, p, o in g.triples((f, None, None)):
            if p in dim_props or p in mprops:
                D.add((f, p, o))
                if p in dim_props:
                    members.add(o)
    level_classes = {lvl for d in dims for lvl in d.levels}
    rollups = {st.prop for d in dims for st in d.steps}
    frontier = set(members)
    while frontier:
        nxt = set()
        for mbr in frontier:
            for _, p, o in g.triples((mbr, None, None)):
                if p == RDF.type:
                    if o in level_classes:
                        D.add((mbr, RDF.type, o))
                        D.add((mbr, QB4O.memberOf, o))
                elif p in rollups:
                    D.add((mbr, p, o))
                    if o not in members:
                        members.add(o)
                        nxt.add(o)
                elif isinstance(o, Literal):
                    D.add((mbr, p, o))  # level attributes (labels, e-mails, ...)
        frontier = nxt

    # --- audit: observation-to-fact grounding invariant ---------------------------
    obs = set(D.subjects(QB.dataSet, dataset))
    checked = mismatched = 0
    for f in facts:
        for m in measures:
            src = [o for o in source.objects(f, m.iri)]
            dst = [o for o in D.objects(f, m.iri)]
            for a, b in zip(sorted(src), sorted(dst)):
                checked += 1
                if Decimal(str(a.toPython())) != Decimal(str(b.toPython())):
                    mismatched += 1
            if len(src) != len(dst):
                mismatched += abs(len(src) - len(dst))
    audit = {
        "source_facts": len(facts),
        "observations": len(obs),
        "ghost_observations": len(obs - facts),
        "dropped_facts": len(facts - obs),
        "measure_cells_checked": checked,
        "measure_cells_mismatched": mismatched,
        "fact_preservation": len(obs & facts) / max(1, len(facts)),
        "measure_fidelity": (checked - mismatched) / max(1, checked),
    }
    return Cube(fact_class, dataset, profile.label, measures, dims, len(obs), audit)
