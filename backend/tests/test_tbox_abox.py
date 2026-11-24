"""TBox and ABox are separate inputs (as in the KG2MD notebook): roles are kept, checked and reported."""
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF

from fixtures.enterprise import build_enterprise_benchmark, ns
from kg2analyzer.analyzer import KG2Analyzer
from kg2analyzer.ingest import RdfFile
from kg2analyzer.store import source_graph

SCHEMA_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty}


def split(g: Graph) -> tuple[bytes, bytes]:
    schema = {s for s, _, o in g.triples((None, RDF.type, None)) if o in SCHEMA_TYPES}
    nt = lambda keep: "\n".join(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in g if keep(s)).encode()  # noqa: E731
    return nt(lambda s: s in schema), nt(lambda s: s not in schema)


def kg(report, name):
    return next(k for k in report["kgs"] if k["kg"] == name)


def test_explicit_tbox_and_abox_slots_build_one_mdkg():
    tbox, abox = split(build_enterprise_benchmark().graphs["retail"])
    az = KG2Analyzer(translator="rules")
    rep = az.ingest([RdfFile("retail/tbox/retail-ontology.nt", tbox), RdfFile("retail/abox/retail-data.nt", abox)], auto_link=False)
    r = kg(rep, "retail")
    assert r["tbox_files"] == ["retail/tbox/retail-ontology.nt"] and r["abox_files"] == ["retail/abox/retail-data.nt"]
    assert r["tbox_triples"] > 0 and r["abox_triples"] > 0
    assert [c["fact_class"] for c in r["cubes"]] == ["SaleTransaction"]
    assert r["undeclared_properties"] == []


def test_a_combined_file_is_split_into_tbox_and_abox_by_content():
    g = build_enterprise_benchmark().graphs["finance"]
    az = KG2Analyzer(translator="rules")
    rep = az.ingest([RdfFile("finance.ttl", g.serialize(format="turtle").encode())], auto_link=False)
    f = kg(rep, "finance")
    assert f["tbox_files"] == f["abox_files"] == ["finance.ttl"]
    declared = {s for s, _, o in g.triples((None, RDF.type, None)) if o in SCHEMA_TYPES}
    assert f["tbox_triples"] == sum(1 for s, _, _ in g if s in declared)
    assert f["tbox_triples"] + f["abox_triples"] == len(g)


def test_abox_properties_missing_from_the_tbox_are_reported_and_still_profiled():
    tbox, abox = split(build_enterprise_benchmark().graphs["retail"])
    extra = f'<{ns("retail")}sale_001> <{ns("retail")}loyaltyPoints> "12"^^<http://www.w3.org/2001/XMLSchema#integer> .'
    az = KG2Analyzer(translator="rules")
    rep = az.ingest([RdfFile("retail_tbox.nt", tbox), RdfFile("retail_abox.nt", abox + b"\n" + extra.encode())], auto_link=False)
    r = kg(rep, "retail")
    assert r["undeclared_properties"] == [str(ns("retail").loyaltyPoints)]
    assert r["cubes"][0]["fact_class"] == "SaleTransaction"


def test_a_kg_without_a_tbox_is_flagged():
    _, abox = split(build_enterprise_benchmark().graphs["retail"])
    az = KG2Analyzer(translator="rules")
    rep = az.ingest([RdfFile("retail/abox/data.nt", abox)], auto_link=False)
    r = kg(rep, "retail")
    assert r["tbox_triples"] == 0 and any("TBox" in w for w in r["warnings"])


def test_tbox_entities_are_protected_from_instance_inference():
    tbox, abox = split(build_enterprise_benchmark().graphs["retail"])
    # an annotation on a TBox property whose rdfs:domain would wrongly type the property itself
    tbox += b'\n<http://example.org/retail#customer> <http://example.org/vocab#note> "x" .\n<http://example.org/vocab#note> <http://www.w3.org/2000/01/rdf-schema#domain> <http://example.org/retail#Customer> .'
    az = KG2Analyzer(translator="rules")
    rep = az.ingest([RdfFile("retail/tbox/o.nt", tbox), RdfFile("retail/abox/d.nt", abox)], auto_link=False)
    source = az.store.sources["retail"].dataset.graph(source_graph("retail"))  # the notebook's inferred source graph
    customer_prop, customer = URIRef("http://example.org/retail#customer"), URIRef("http://example.org/retail#Customer")
    assert (customer_prop, RDF.type, customer) not in source
    assert any(True for _ in source.subjects(RDF.type, customer))  # real customers are still typed
    assert kg(rep, "retail")["cubes"][0]["fact_class"] == "SaleTransaction"
