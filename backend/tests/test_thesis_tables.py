"""Thesis results tables (4.4 telemetry, 4.5 Query 23, 4.2.4 communities, 4.6 NL benchmark), as tests.

Run against a local LLM instead of the grounded parser with KG2A_TRANSLATOR=ollama.
"""
from __future__ import annotations

from decimal import Decimal

from kg2analyzer.analyzer import KG2Analyzer
from kg2analyzer.kg2md.profiling import local_name

# (id, question, expected outcome: "answer" or "reject")
NL_QUESTIONS = [
    ("NL_01", "What is the total retail sales amount?", "answer"),
    ("NL_02", "Total sale amount by product category", "answer"),
    ("NL_03", "Total retail sales by store", "answer"),
    ("NL_04", "Total retail sales per month", "answer"),
    ("NL_05", "Total retail sales by quarter", "answer"),
    ("NL_06", "Average discount by product category", "answer"),
    ("NL_07", "How many retail sales per customer?", "answer"),
    ("NL_08", "Total retail sales for Alice", "answer"),
    ("NL_09", "Total retail sales by country", "answer"),
    ("NL_10", "Total trade amount by trader", "answer"),
    ("NL_11", "Total trade amount by security sector", "answer"),
    ("NL_12", "Average fee paid per trader in finance", "answer"),
    ("NL_13", "Total trade amount by quarter", "answer"),
    ("NL_14", "Total freight cost by supplier", "answer"),
    ("NL_15", "Total order quantity per warehouse", "answer"),
    ("NL_16", "Average lead time days by supplier in logistics", "answer"),
    ("NL_17", "Average turnaround hours per lab in healthcare", "answer"),
    ("NL_18", "Total test cost by test category", "answer"),
    ("NL_19", "Total energy consumed kwh by site", "answer"),
    ("NL_20", "Maximum peak demand per meter", "answer"),
    ("NL_21", "Total energy consumed per month", "answer"),
    ("NL_22", "Average temperature by room in the building", "answer"),
    ("NL_23", "Total occupancy count per building site", "answer"),
    ("NL_24", "Average humidity by sensor", "answer"),
    ("NL_25", "Total shipment weight by carrier", "answer"),
    ("NL_26", "Total freight charge by consignee", "answer"),
    ("NL_27", "Average transit days per carrier in supply chain", "answer"),
    ("NL_28", "Top 3 products by retail sales", "answer"),
    ("NL_29", "Show total retail sales and investment trade volume for our shared corporate clients", "answer"),
    ("NL_30", "Daily retail sales and energy consumed on the same day", "answer"),
    ("NL_31", "Freight cost in logistics and freight charge in supply chain for shared partners", "answer"),
    ("NL_32", "Retail sales by city", "answer"),
    ("NL_33", "Who won the football world cup?", "reject"),
    ("NL_34", "What is the weather in Chittagong tomorrow?", "reject"),
    ("NL_35", "Delete all retail customers", "reject"),
]


import os

import pytest

from fixtures import load_enterprise


@pytest.fixture(scope="module")
def az():
    a = KG2Analyzer(translator=os.environ.get("KG2A_TRANSLATOR", "rules"))
    load_enterprise(a)
    return a


def test_table_4_4_seven_domain_telemetry(az):
    cubes = [c for res in az.results.values() for c in res.cubes]
    assert len(cubes) == 7
    assert sum(c.observations for c in cubes) == 200
    assert sum(len(c.measures) for c in cubes) == 22
    assert all(c.audit["fact_preservation"] == 1.0 and c.audit["measure_fidelity"] == 1.0 for c in cubes)


@pytest.mark.parametrize("mode", ["integrated", "federated"])
def test_table_4_5_query_23_pushdown_is_exact_and_naive_is_inflated(az, mode):
    left, right = ("retail", "customer", "saleTotalAmount"), ("finance", "trader", "tradeAmount")
    push = {local_name(r["left_entity"]): r for r in az.cross_cube(left, right, "identity", "pushdown", mode).rows}
    naive = {local_name(r["left_entity"]): r for r in az.cross_cube(left, right, "identity", "naive", mode).rows}
    assert (Decimal(str(push["cust_1001"]["left_total"])), Decimal(str(push["cust_1001"]["right_total"]))) == (Decimal("1499.70"), Decimal("52620.00"))
    assert (Decimal(str(push["cust_1002"]["left_total"])), Decimal(str(push["cust_1002"]["right_total"]))) == (Decimal("1499.70"), Decimal("50737.50"))
    # 15 sales x 10 trades: every sale counted 10 times, every trade 15 times
    assert (Decimal(str(naive["cust_1001"]["left_total"])), Decimal(str(naive["cust_1001"]["right_total"]))) == (Decimal("14997.00"), Decimal("789300.00"))


def test_section_4_2_4_identity_communities(az):
    rep = az.communities("identity")
    assert [c["size"] for c in rep["communities"]] == [3, 3, 3, 3] and rep["modularity"] == pytest.approx(0.75)


def test_table_4_6_nl_benchmark(az):
    outcomes = []
    for qid, q, expect in NL_QUESTIONS:
        a = az.ask(q)
        answered = a.status in ("executed", "fallback") and bool(a.rows)
        outcomes.append((qid, expect, a.status, answered if expect == "answer" else a.status == "rejected"))
    wrong = [o for o in outcomes if not o[3]]
    assert not wrong, wrong
    executed = sum(1 for o in outcomes if o[2] in ("executed", "fallback"))
    assert (executed, len(outcomes)) == (32, 35)  # 91.43% execution rate, 3 correct refusals
