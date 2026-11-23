"""Phase III seam: KG2Analyzer.ask(question) -> Answer (validator, retry loop, fallback)."""
from decimal import Decimal

import pytest

from fixtures import load_enterprise
from kg2analyzer.analyzer import KG2Analyzer

ALICE = "http://example.org/retail#cust_1001"


class ScriptedLLM:
    """Stands in for the LLM at the translator seam: replays drafts, records prompts."""

    name = "scripted-llm"

    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.prompts = []

    def translate(self, question, prompt):
        self.prompts.append(prompt)
        return self.drafts.pop(0) if self.drafts else ""


@pytest.fixture(scope="module")
def az():
    a = KG2Analyzer(translator="rules")
    load_enterprise(a)
    return a


def test_alex_question_returns_the_true_combined_totals(az):
    ans = az.ask("Show total retail sales and investment trade volume for our shared corporate clients")
    assert ans.status == "executed"
    rows = {r["left_entity"]: r for r in ans.rows}
    assert Decimal(str(rows[ALICE]["left_total"])) == Decimal("1499.70")
    assert Decimal(str(rows[ALICE]["right_total"])) == Decimal("52620.00")


def test_rollup_question_groups_by_the_requested_level(az):
    ans = az.ask("What is the total sale amount by product category?")
    assert ans.status == "executed"
    assert sum(Decimal(str(r["total"])) for r in ans.rows) == Decimal("2999.40")
    assert len(ans.rows) == 3


def test_average_question_uses_avg(az):
    ans = az.ask("Average turnaround hours per lab in healthcare")
    assert ans.status == "executed" and "AVG(" in ans.sparql and len(ans.rows) == 2


def test_member_filter_slices_the_cube(az):
    ans = az.ask("Total retail sales for Alice")
    assert Decimal(str(ans.rows[0]["total"])) == Decimal("1499.70")


def test_out_of_scope_question_is_rejected_without_execution(az):
    ans = az.ask("Who won the football world cup in 2022?")
    assert ans.status == "rejected" and ans.rows == []


def test_llm_draft_with_mutation_is_rejected_then_corrected_on_retry(az):
    good = """```sparql
SELECT (SUM(?v) AS ?total) WHERE { GRAPH <http://example.org/graphs/energy> {
  ?o qb:dataSet Energy:dataset-MeterReading ; Energy:energyConsumedKwh ?v } }
```"""
    llm = ScriptedLLM("DELETE WHERE { ?s ?p ?o }", good)
    az.set_translator(llm)
    try:
        ans = az.ask("Total energy consumed")
    finally:
        az.set_translator("rules")
    assert ans.status == "executed"
    assert [a.ok for a in ans.attempts] == [False, True]
    assert "safety" in llm.prompts[1] or "syntax" in llm.prompts[1]  # diagnostics fed back into the retry prompt
    assert "Energy:energyConsumedKwh" in llm.prompts[0]  # grounded catalogue with compact aliases


def test_hallucinated_prefix_and_missing_graph_scope_are_intercepted(az):
    hallucinated = "SELECT ?x WHERE { ?x ConsumerSite:revenue ?v }"
    no_scope = ("SELECT (SUM(?v) AS ?t) WHERE { GRAPH <http://example.org/graphs/retail> { "
                "?o <http://example.org/retail#saleTotalAmount> ?v } }")
    az.set_translator(ScriptedLLM(hallucinated, no_scope))
    try:
        ans = az.ask("Join retail sales with finance trades for clients")
    finally:
        az.set_translator("rules")
    rules_failed = [{c.rule for c in a.checks if not c.ok} for a in ans.attempts[:2]]
    assert rules_failed == [{"syntax"}, {"scope"}]
    # after K_max = 2 failures the deterministic grounded parser answers the identity intent
    assert ans.status == "fallback" and ans.rows


def test_ungrounded_predicate_is_caught_by_the_grounding_rule(az):
    checks = az.nl.validator.validate(
        "PREFIX Retail: <http://example.org/retail#> SELECT ?v WHERE { GRAPH <http://example.org/graphs/retail> "
        "{ ?o Retail:totalTurnover ?v } }", "retail turnover")
    assert {c.rule: c.ok for c in checks} == {"syntax": True, "grounding": False, "scope": True, "safety": True}
