"""Sections are independent: Build writes MDKG files; Query and Ask load MDKG files (no KG2MD re-run)."""
import io
import zipfile
from decimal import Decimal

import pytest

from fixtures.enterprise import build_enterprise_benchmark
from kg2analyzer.analyzer import KG2Analyzer
from kg2analyzer.ingest import RdfFile

ALICE = "http://example.org/retail#cust_1001"


@pytest.fixture(scope="module")
def saved():
    """What a user saves from Build: one KG2MD output folder per KG plus identity.ttl (here: the zip)."""
    bm = build_enterprise_benchmark()
    builder = KG2Analyzer(translator="rules")
    builder.ingest([RdfFile(f"{n}.ttl", g.serialize(format="turtle").encode()) for n, g in bm.graphs.items()]
                   + [RdfFile("links.ttl", bm.identity.serialize(format="turtle").encode())], auto_link=False)
    return builder.mdkg_zip()


def files_from_zip(blob: bytes, keep=lambda n: True) -> list[RdfFile]:
    z = zipfile.ZipFile(io.BytesIO(blob))
    return [RdfFile(n, z.read(n)) for n in z.namelist() if keep(n)]


def test_loading_saved_mdkgs_restores_cubes_and_answers_queries(saved):
    az = KG2Analyzer(translator="rules")
    rep = az.load_mdkgs(files_from_zip(saved, lambda n: n.endswith("mdkg_dataset.nq") or n == "identity.ttl"))
    assert sorted(k["kg"] for k in rep["mdkgs"]) == ["building", "energy", "finance", "healthcare", "logistics", "retail", "supplychain"]
    assert rep["identity"]["supplied_links"] == 16
    res = az.cross_cube(("retail", "customer", "saleTotalAmount"), ("finance", "trader", "tradeAmount"))
    alice = next(r for r in res.rows if r["left_entity"] == ALICE)
    assert (Decimal(str(alice["left_total"])), Decimal(str(alice["right_total"]))) == (Decimal("1499.70"), Decimal("52620.00"))
    assert az.ask("Total retail sales for Alice").rows[0]["total"] == Decimal("1499.70")


def test_a_selection_of_mdkgs_without_identity_file_is_auto_linked(saved):
    az = KG2Analyzer(translator="rules")
    picked = files_from_zip(saved, lambda n: n.split("/")[0] in ("retail", "finance"))  # two folders
    rep = az.load_mdkgs(picked)
    assert [k["kg"] for k in rep["mdkgs"]] == ["finance", "retail"]
    assert rep["identity"]["links_added"] == 2  # Alice and Bob


def test_the_whole_saved_zip_can_be_loaded_at_once(saved):
    az = KG2Analyzer(translator="rules")
    assert len(az.load_mdkgs([RdfFile("my-mdkgs.zip", saved)])["mdkgs"]) == 7


def test_a_raw_kg_is_refused_with_a_hint(saved):
    az = KG2Analyzer(translator="rules")
    raw = b'<http://x/a> <http://x/p> "1" .'
    with pytest.raises(ValueError, match="not an MDKG"):
        az.load_mdkgs([RdfFile("raw.nt", raw)])


def test_a_cube_folder_with_schema_and_data_but_no_bundle_loads(saved):
    az = KG2Analyzer(translator="rules")
    files = files_from_zip(saved, lambda n: n.startswith("retail/") and n.endswith(("mdkg_schema.ttl", "mdkg_data.ttl")))
    rep = az.load_mdkgs(files, auto_link=False)
    assert rep["mdkgs"][0]["kg"] == "retail" and rep["mdkgs"][0]["cubes"][0]["fact_class"] == "SaleTransaction"
    olap = az.olap("retail", "saleTotalAmount", group_by=[("product", "Category")])
    assert round(sum(r["total"] for r in olap.rows), 2) == Decimal("2999.40")
