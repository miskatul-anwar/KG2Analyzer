"""Batch pipeline seam: a set of raw KGs in -> one MDKG per KG + identity graph -> analytics.

Inputs mimic real deliveries: TBox/ABox split files, one file per KG, folders and zip archives,
with no identity links supplied. Expected values come from the thesis.
"""
import io
import zipfile
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from rdflib import Dataset
from rdflib.namespace import OWL, RDF, RDFS

from kg2analyzer.analyzer import KG2Analyzer
from fixtures.enterprise import build_enterprise_benchmark

SCHEMA_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty}


def split_tbox_abox(g):
    """Serialise a KG as the TBox.ttl / ABox.ttl pair the notebook expects."""
    schema = {s for s, _, o in g.triples((None, RDF.type, None)) if o in SCHEMA_TYPES}
    tbox = "\n".join(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in g if s in schema)
    abox = "\n".join(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in g if s not in schema)
    return tbox.encode(), abox.encode()


@pytest.fixture(scope="module")
def bench():
    return build_enterprise_benchmark()


@pytest.fixture(scope="module")
def kg_dir(tmp_path_factory, bench):
    """retail/ as a TBox+ABox folder, finance as one file, the rest as *_tbox/*_abox pairs."""
    root = tmp_path_factory.mktemp("kgs")
    for name, g in bench.graphs.items():
        tbox, abox = split_tbox_abox(g)
        if name == "retail":
            (root / "retail").mkdir()
            (root / "retail" / "TBox.ttl").write_bytes(tbox)
            (root / "retail" / "ABox.ttl").write_bytes(abox)
        elif name == "finance":
            (root / "finance.ttl").write_text(g.serialize(format="turtle"))
        else:
            (root / f"{name}_tbox.nt").write_bytes(tbox)
            (root / f"{name}_abox.nt").write_bytes(abox)
    return root


@pytest.fixture(scope="module")
def built(kg_dir):
    az = KG2Analyzer(translator="rules")
    report = az.ingest_paths([kg_dir])
    return az, report


def test_every_input_kg_becomes_an_mdkg_with_its_fact_cube(built):
    _, report = built
    cubes = {k["kg"]: [c["fact_class"] for c in k["cubes"]] for k in report["kgs"]}
    assert cubes == {
        "retail": ["SaleTransaction"], "finance": ["InvestmentTrade"], "logistics": ["SupplierPurchaseOrder"],
        "healthcare": ["DiagnosticLabTest"], "energy": ["MeterReading"], "building": ["SensorReading"],
        "supplychain": ["FreightShipment"],
    }
    assert sum(c["observations"] for k in report["kgs"] for c in k["cubes"]) == 200
    assert all(c["fact_preservation"] == 1.0 for k in report["kgs"] for c in k["cubes"])


def test_identity_links_are_discovered_automatically_into_four_entity_clusters(built):
    az, report = built
    assert report["identity"]["clusters"] == 4
    rep = az.communities("identity")
    assert [c["size"] for c in rep["communities"]] == [3, 3, 3, 3]
    assert rep["modularity"] == pytest.approx(0.75)


def test_cross_kg_analytics_work_on_the_auto_built_mdkgs(built):
    az, _ = built
    res = az.cross_cube(("retail", "customer", "saleTotalAmount"), ("finance", "trader", "tradeAmount"))
    alice = next(r for r in res.rows if r["left_entity"].endswith("cust_1001"))
    assert Decimal(str(alice["left_total"])) == Decimal("1499.70")
    assert Decimal(str(alice["right_total"])) == Decimal("52620.00")
    ans = az.ask("Show total retail sales and investment trade volume for our shared corporate clients")
    assert ans.status == "executed" and len(ans.rows) == 2


def test_mdkg_export_holds_schema_and_data_graphs(built):
    az, _ = built
    ds = Dataset()
    ds.parse(data=az.mdkg_trig("retail"), format="trig")
    graphs = {str(g.identifier) for g in ds.graphs() if len(g)}
    assert graphs == {"http://example.org/graphs/retail", "http://example.org/graphs/retail/schema"}
    archive = zipfile.ZipFile(io.BytesIO(az.mdkg_zip()))
    assert set(archive.namelist()) >= {"retail.mdkg.trig", "finance.mdkg.trig", "identity.ttl", "report.json"}


def test_supplied_identity_file_is_recognised_and_kept(bench, tmp_path):
    for name in ("retail", "finance"):
        (tmp_path / f"{name}.ttl").write_text(bench.graphs[name].serialize(format="turtle"))
    (tmp_path / "links.ttl").write_text(bench.identity.serialize(format="turtle"))
    az = KG2Analyzer(translator="rules")
    report = az.ingest_paths([tmp_path], auto_link=False)
    assert [k["kg"] for k in report["kgs"]] == ["finance", "retail"]
    assert report["identity"]["supplied_links"] == 16


def test_pipeline_endpoint_accepts_many_files_and_zip_archives(bench):
    from kg2analyzer import server

    client = TestClient(server.app)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        tbox, abox = split_tbox_abox(bench.graphs["finance"])
        z.writestr("finance/TBox.ttl", tbox)
        z.writestr("finance/ABox.ttl", abox)
    files = [("files", ("retail.ttl", bench.graphs["retail"].serialize(format="turtle").encode(), "text/turtle")),
             ("files", ("finance_kg.zip", buf.getvalue(), "application/zip"))]
    r = client.post("/api/pipeline", data={"reset": "true", "auto_link": "true"}, files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(k["kg"] for k in body["kgs"]) == ["finance", "retail"]
    assert body["identity"]["links_added"] == 2  # Alice and Bob
    assert client.get("/api/kgs/retail/mdkg.trig").status_code == 200
    assert client.get("/api/mdkg.zip").headers["content-type"] == "application/zip"


def test_suggested_questions_are_all_answerable_on_the_users_kgs(built):
    az, _ = built
    suggestions = az.suggest_questions()
    assert len(suggestions) >= 4
    assert any(" and " in q and "shared" in q for q in suggestions)  # at least one cross-KG join
    for q in suggestions:
        ans = az.ask(q)
        assert ans.status == "executed" and ans.rows, (q, ans.insight)


def test_no_suggestions_without_kgs():
    assert KG2Analyzer(translator="rules").suggest_questions() == []


def test_overview_reflects_every_loaded_mdkg_and_identity_link(built):
    az, _ = built
    ov = az.overview()
    assert sorted(k["kg"] for k in ov["kgs"]) == ["building", "energy", "finance", "healthcare", "logistics", "retail", "supplychain"]
    retail = next(k for k in ov["kgs"] if k["kg"] == "retail")
    assert retail["cubes"][0]["fact_class"] == "SaleTransaction" and retail["files"] == ["retail/ABox.ttl", "retail/TBox.ttl"]
    assert ov["identity"]["clusters"] == 4
    alice = next(l for l in ov["identity"]["links"] if {l["left"], l["right"]} == {
        "http://example.org/retail#cust_1001", "http://example.org/finance#trader_Alice"})
    assert alice["left_label"] == alice["right_label"] == "Alice Johnson"
