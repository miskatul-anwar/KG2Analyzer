"""HTTP seam: the JSON API and the SPARQL 1.1 Protocol endpoint, incl. federating to a remote endpoint."""
import pytest
from fastapi.testclient import TestClient

from kg2analyzer import server


@pytest.fixture(scope="module")
def client():
    from fixtures.enterprise import build_enterprise_benchmark

    c = TestClient(server.app)
    bm = build_enterprise_benchmark()
    files = [("files", (f"{n}.ttl", g.serialize(format="turtle").encode(), "text/turtle")) for n, g in bm.graphs.items()]
    files.append(("files", ("links.ttl", bm.identity.serialize(format="turtle").encode(), "text/turtle")))
    assert c.post("/api/pipeline", data={"reset": "true", "auto_link": "false"}, files=files).status_code == 200
    return c


def test_status_and_catalog_report_the_seven_cubes(client):
    assert client.get("/api/status").json()["cubes"] == 7
    cat = client.get("/api/catalog").json()
    retail = next(c for c in cat["cubes"] if c["kg"] == "retail")
    sale = next(m for m in retail["measures"] if m["label"] == "saleTotalAmount")  # grounded in the KG's own property
    assert sale["aggregate"] == "sum" and sale["alias"] in cat["prompt_context"]


def test_ask_endpoint_answers_alex(client):
    r = client.post("/api/ask", json={"question": "Show total retail sales and investment trade volume for our shared corporate clients"}).json()
    alice = next(x for x in r["rows"] if x["left_entity"].endswith("cust_1001"))
    assert alice["left_total"] == pytest.approx(1499.70) and alice["right_total"] == pytest.approx(52620.00)


def test_sparql_protocol_endpoint_rejects_updates_and_serves_selects(client):
    assert client.post("/sparql", data={"query": "DROP ALL"}).status_code == 403
    r = client.get("/sparql/retail", params={"query": "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"})
    assert r.headers["content-type"].startswith("application/sparql-results+json")
    assert int(r.json()["results"]["bindings"][0]["n"]["value"]) > 0


def test_upload_runs_kg2md_on_a_user_kg(client):
    ttl = b"""@prefix ex: <http://example.org/shop#> . @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    ex:o1 a ex:Order ; ex:buyer ex:c1 ; ex:total "10.5"^^xsd:decimal ; ex:items 2 .
    ex:o2 a ex:Order ; ex:buyer ex:c2 ; ex:total "4.0"^^xsd:decimal ; ex:items 1 .
    ex:o3 a ex:Order ; ex:buyer ex:c1 ; ex:total "7.0"^^xsd:decimal ; ex:items 3 .
    ex:c1 a ex:Client ; ex:city ex:dhaka . ex:c2 a ex:Client ; ex:city ex:ctg .
    ex:dhaka a ex:City . ex:ctg a ex:City ."""
    r = client.post("/api/kgs", data={"name": "shop"}, files={"file": ("shop.ttl", ttl, "text/turtle")})
    assert r.status_code == 200, r.text
    cube = r.json()["cubes"][0]
    assert cube["fact_class"].endswith("#Order") and cube["audit"]["observations"] == 3
    ol = client.post("/api/olap", json={"kg": "shop", "measure": "total", "group_by": [["buyer", None]]}).json()
    assert sorted(x["total"] for x in ol["rows"]) == [4.0, 17.5]
    client.delete("/api/kgs/shop")


def test_federation_over_http_to_a_remote_kg2analyzer(client, monkeypatch):
    """Attach this server's own /sparql/finance as a *remote* source and run the pushdown join federated."""
    import httpx

    from kg2analyzer.analyzer import KG2Analyzer
    from fixtures.enterprise import build_enterprise_benchmark

    def post(url, data=None, timeout=None, headers=None):
        return client.post(url.replace("http://testserver", ""), data=data, headers=headers)

    monkeypatch.setattr(httpx, "post", post)
    bm = build_enterprise_benchmark()
    az = KG2Analyzer(translator="rules")
    az.load_kg("retail", bm.graphs["retail"])
    az.attach_remote("finance", "http://testserver/sparql/finance")
    az.load_identity(bm.identity)
    res = az.cross_cube(("retail", "customer", "saleTotalAmount"), ("finance", "trader", "tradeAmount"), mode="federated")
    alice = next(x for x in res.rows if x["left_entity"].endswith("cust_1001"))
    assert float(alice["right_total"]) == pytest.approx(52620.00)


def test_members_endpoint_lists_level_members_with_labels(client):
    r = client.get("/api/members", params={"kg": "retail", "dim": "product", "level": "Category"}).json()
    assert sorted(m["label"] for m in r["members"]) == ["Apparel", "Beverages", "Electronics"]


def test_join_options_offer_identity_and_conformed_date_joins(client):
    retail_finance = client.get("/api/joins", params={"a": "retail", "b": "finance"}).json()["options"]
    assert any(o["link"] == "identity" and o["label"].startswith("Customer ↔ Trader") for o in retail_finance)
    assert any(o["link"] == "shared" for o in retail_finance)  # both cubes have the conformed calendar
    assert retail_finance[0]["link"] == "identity" and retail_finance[0]["aligned"] >= 2  # best option first


def test_build_query_and_ask_are_separate_workspaces_connected_only_by_files(client):
    # `client` built the benchmark in the default (build) workspace
    saved = client.get("/api/mdkg.zip", params={"ws": "build"}).content
    for ws in ("query", "ask"):
        client.post("/api/reset", params={"ws": ws})
        assert client.get("/api/mdkgs", params={"ws": ws}).json()["mdkgs"] == []
    r = client.post("/api/mdkgs", params={"ws": "query"}, files=[("files", ("my-mdkgs.zip", saved, "application/zip"))])
    assert r.status_code == 200, r.text
    assert len(r.json()["mdkgs"]) == 7
    assert client.get("/api/mdkgs", params={"ws": "ask"}).json()["mdkgs"] == []  # Ask has its own MDKGs
    olap = client.post("/api/olap", params={"ws": "query"},
                       json={"kg": "retail", "measure": "saleTotalAmount", "group_by": [["product", "Category"]]}).json()
    assert round(sum(x["total"] for x in olap["rows"]), 2) == 2999.40
    picked = [("files", (n, c, "application/n-quads")) for n, c in _zip_members(saved, {"retail", "finance"})]
    assert picked
    assert client.post("/api/mdkgs", params={"ws": "ask"}, files=picked).status_code == 200
    a = client.post("/api/ask", params={"ws": "ask"},
                    json={"question": "Show total retail sales and investment trade volume for our shared corporate clients"}).json()
    assert a["status"] == "executed" and len(a["rows"]) == 2
    assert client.get("/api/x", params={"ws": "nope"}).status_code in (404, 200)  # SPA fallback may serve unknown paths
    assert client.get("/api/mdkgs", params={"ws": "nope"}).status_code == 404


def _zip_members(blob, names):
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(blob))
    return [(n, z.read(n)) for n in z.namelist() if n.split("/")[0] in names and n.endswith("mdkg_dataset.nq")]
