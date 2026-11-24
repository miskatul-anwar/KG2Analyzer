"""Tev1 switched off: the ML classifiers decide. The case that motivated them: people who are richly
described (age, income, where they live and work) and mostly not referenced by any event look like a
fact table to structure-only rules. The classifiers also read what the classes are called."""
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kg2analyzer.analyzer import KG2Analyzer
from kg2analyzer.ingest import RdfFile

EX = Namespace("http://example.org/people#")


def people_kg() -> tuple[bytes, bytes]:
    t, a = Graph(), Graph()
    for c in ("Person", "City", "Company", "Product", "Purchase"):
        t.add((EX[c], RDF.type, OWL.Class))
    for p, d, r in (("livesIn", "Person", "City"), ("worksFor", "Person", "Company"), ("buyer", "Purchase", "Person"),
                    ("item", "Purchase", "Product")):
        t += [(EX[p], RDF.type, OWL.ObjectProperty), (EX[p], RDFS.domain, EX[d]), (EX[p], RDFS.range, EX[r])]
    for p, d, r in (("age", "Person", XSD.integer), ("annualIncome", "Person", XSD.decimal), ("amount", "Purchase", XSD.decimal)):
        t += [(EX[p], RDF.type, OWL.DatatypeProperty), (EX[p], RDFS.domain, EX[d]), (EX[p], RDFS.range, r)]
    for i, c in enumerate(("Dhaka", "Sylhet", "Khulna")):
        a.add((EX[f"city{i}"], RDF.type, EX.City))
    for i in range(3):
        a.add((EX[f"co{i}"], RDF.type, EX.Company))
        a.add((EX[f"prod{i}"], RDF.type, EX.Product))
    for i in range(40):  # 40 people, only 3 of them ever buy anything
        p = EX[f"person{i}"]
        a += [(p, RDF.type, EX.Person), (p, EX.age, Literal(20 + i, datatype=XSD.integer)),
              (p, EX.annualIncome, Literal(f"{30000 + 997 * i}.00", datatype=XSD.decimal)),
              (p, EX.livesIn, EX[f"city{i % 3}"]), (p, EX.worksFor, EX[f"co{i % 3}"])]
    for i in range(6):
        s = EX[f"purchase{i}"]
        a += [(s, RDF.type, EX.Purchase), (s, EX.buyer, EX[f"person{i % 3}"]), (s, EX.item, EX[f"prod{i % 3}"]),
              (s, EX.amount, Literal(f"{10 * (i + 1)}.00", datatype=XSD.decimal))]
    return t.serialize(format="turtle").encode(), a.serialize(format="turtle").encode()


def build(decider: str) -> list[str]:
    tbox, abox = people_kg()
    az = KG2Analyzer(translator="rules")
    rep = az.ingest([RdfFile("people/tbox/t.ttl", tbox), RdfFile("people/abox/a.ttl", abox)], auto_link=False, decider=decider)
    return [c["fact_class"] for c in rep["kgs"][0]["cubes"]]


def test_people_are_not_fact_classes_when_the_classifiers_decide():
    assert build("ml") == ["Purchase"]


def test_structure_only_rules_take_people_for_facts():
    # why the classifiers exist: the rule-based stand-in sees age, income and two links and says "fact"
    assert "Person" in build("structural")


def test_every_ml_decision_is_explained():
    from kg2analyzer.kg2md.ml_decider import MLDecider

    r = MLDecider().decide({"class_name": "Person", "instance_count": 40, "object_property_count": 2, "numeric_property_count": 2,
                            "object_properties": [{"name": "livesIn", "range": "City"}, {"name": "worksFor", "range": "Company"}],
                            "numeric_properties": [{"name": "age", "datatype": "integer"}, {"name": "annualIncome", "datatype": "decimal"}]})
    assert r["prediction"] == "dimension_class" and r["explanation"] and abs(sum(r["probabilities"].values()) - 1) < 1e-9
