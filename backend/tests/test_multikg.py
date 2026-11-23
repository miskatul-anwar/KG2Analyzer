"""Phase II seams: cross-cube planner (both modes), store layout, communities, linking.

Expected values are the thesis' audit numbers (tables 4.5, section 4.2.4, 3.3.2).
"""
from decimal import Decimal

import pytest

from fixtures import load_enterprise
from kg2analyzer.analyzer import KG2Analyzer

ALICE = "http://example.org/retail#cust_1001"
BOB = "http://example.org/retail#cust_1002"
RETAIL = ("retail", "customer", "saleTotalAmount")
FINANCE = ("finance", "trader", "tradeAmount")


@pytest.fixture(scope="module")
def az():
    a = KG2Analyzer(translator="rules")
    load_enterprise(a)
    return a


def _by_left(rows):
    return {r["left_entity"]: r for r in rows}


def test_benchmark_store_has_15_named_graphs_200_observations_and_16_identity_links(az):
    graphs = [g for g in az.store.graph_stats() if g["triples"]]
    assert len(graphs) == 15
    assert len(az.store.identity) == 16
    n = az.sparql("SELECT (COUNT(?o) AS ?n) WHERE { ?o a <http://purl.org/linked-data/cube#Observation> }")
    assert n["rows"][0]["n"] == 200


@pytest.mark.parametrize("mode", ["integrated", "federated"])
def test_pushdown_join_returns_the_true_totals(az, mode):
    res = az.cross_cube(RETAIL, FINANCE, strategy="pushdown", mode=mode)
    rows = _by_left(res.rows)
    assert Decimal(str(rows[ALICE]["left_total"])) == Decimal("1499.70")
    assert Decimal(str(rows[ALICE]["right_total"])) == Decimal("52620.00")
    assert Decimal(str(rows[BOB]["left_total"])) == Decimal("1499.70")
    assert Decimal(str(rows[BOB]["right_total"])) == Decimal("50737.50")
    assert res.guard["cartesian_risk"] is True  # the guard knows a naive plan would inflate 10x / 15x


@pytest.mark.parametrize("mode", ["integrated", "federated"])
def test_naive_join_reproduces_the_query_23_cartesian_inflation(az, mode):
    rows = _by_left(az.cross_cube(RETAIL, FINANCE, strategy="naive", mode=mode).rows)
    assert Decimal(str(rows[ALICE]["left_total"])) == Decimal("14997.00")  # 1,499.70 x 10 trades
    assert Decimal(str(rows[ALICE]["right_total"])) == Decimal("789300.00")  # 52,620.00 x 15 sales
    assert int(rows[ALICE]["joined_rows"]) == 150


def test_conformed_date_join_preserves_each_domains_daily_totals(az):
    res = az.cross_cube(("retail", "date", "saleTotalAmount"), ("energy", "readingDate", "energyConsumedKwh"),
                        link="shared")
    retail_total = az.sparql("""SELECT (SUM(?v) AS ?t) WHERE { ?o <http://example.org/retail#date> ?d ;
        <http://example.org/retail#saleTotalAmount> ?v . ?e <http://example.org/energy#readingDate> ?d }""")
    # every shared day appears once and its retail total is not multiplied by the energy readings
    assert len({r["left_entity"] for r in res.rows}) == len(res.rows)
    assert sum(Decimal(str(r["left_total"])) for r in res.rows) <= Decimal("2999.40")
    assert retail_total["rows"]  # sanity: the naive pattern does match something


def test_identity_graph_partitions_into_four_communities_of_three_with_q_075(az):
    rep = az.communities("identity", "greedy_modularity")
    assert [c["size"] for c in rep["communities"]] == [3, 3, 3, 3]
    assert rep["modularity"] == pytest.approx(0.75)
    assert all(c["cross_kg"] for c in rep["communities"])


@pytest.mark.parametrize("algorithm", ["louvain", "label_propagation", "sgc_kmeans"])
def test_other_community_algorithms_run_on_the_member_graph(az, algorithm):
    rep = az.communities("members", algorithm, kgs=["retail", "finance"])
    assert rep["communities"] and -0.5 <= rep["modularity"] <= 1


def test_link_discovery_recovers_the_retail_finance_identity_pairs():
    a = KG2Analyzer(translator="rules")
    load_enterprise(a, domains=["retail", "finance"])
    a.store.identity.remove((None, None, None))  # start without any known links
    a._invalidate()
    out = a.discover_links("retail", "finance")
    accepted = {(c["left"], c["right"]) for c in out["candidates"] if c["score"] >= 0.5}
    assert accepted == {(ALICE, "http://example.org/finance#trader_Alice"),
                        (BOB, "http://example.org/finance#trader_Bob")}


def test_olap_rollup_by_category_sums_to_the_cube_total(az):
    res = az.olap("retail", "saleTotalAmount", [("product", "Category")])
    assert sum(Decimal(str(r["total"])) for r in res.rows) == Decimal("2999.40")
    assert {r["category_label"] for r in res.rows} == {"Beverages", "Electronics", "Apparel"}


def test_olap_warns_when_summing_a_non_additive_measure(az):
    res = az.olap("retail", "discount", [("store", None)], aggregate="sum")
    assert any("non-additive" in w for w in res.warnings)


def test_store_is_read_only(az):
    with pytest.raises(PermissionError):
        az.sparql("DELETE WHERE { ?s ?p ?o }")
