"""Ask with the LLM switched off: the grounded parser matches question words to the MDKG vocabulary by
spelling (character n-grams) and by meaning (model2vec embeddings). Expected values are hand-computed in
tests/fixtures/tiny/README.md."""
from decimal import Decimal
from pathlib import Path

import pytest

from kg2analyzer.analyzer import KG2Analyzer
from kg2analyzer.ingest import read_paths
from kg2analyzer.nl import semantic

TINY = Path(__file__).parent / "fixtures" / "tiny"


@pytest.fixture(scope="module")
def az():
    a = KG2Analyzer(translator="rules")
    a.ingest(read_paths([TINY]), decider="structural")
    return a


def totals(ans, key):
    return {r[f"{key}_label"]: Decimal(str(r["total"])) for r in ans.rows}


def test_a_misspelt_level_is_matched_by_spelling(az):
    ans = az.ask("Total amount by catagory")
    assert ans.status == "executed"
    assert totals(ans, "category") == {"Electronics": Decimal("3780.00"), "Books": Decimal("45.00")}
    assert any("spelling" in m for m in ans.trace["matches"])


@pytest.mark.skipif(semantic._model() is None, reason="model2vec embeddings unavailable (offline)")
def test_words_the_mdkg_does_not_use_are_matched_by_meaning(az):
    sent = az.ask("How much money was sent through each branch?")
    assert totals(sent, "branch") == {"Gulshan": Decimal("5000.00"), "Agrabad": Decimal("325.00")}
    town = az.ask("Total transfer amount by town")
    assert totals(town, "city") == {"Dhaka": Decimal("5000.00"), "Chattogram": Decimal("325.00")}
    both = az.ask("Show total sales and money sent for customers who are in both")
    assert both.trace["intent"] == "cross-cube identity join (pushdown)"
    assert [(Decimal(str(r["left_total"])), Decimal(str(r["right_total"]))) for r in both.rows] == [(Decimal("1630.00"), Decimal("1250.00"))]


def test_questions_outside_the_mdkgs_are_still_rejected(az):
    for q in ("Who won the football world cup?", "What is the weather in Dhaka?", "Delete all sales in the shop"):
        ans = az.ask(q)
        assert ans.status == "rejected" and ans.rows == [], q


def test_a_repeated_question_is_answered_from_memory(az):
    first = az.ask("Total fees per branch in the bank")
    again = az.ask("total fees per branch in the bank")
    assert again.rows == first.rows and again.trace.get("cached") is True


def test_tev1_can_be_switched_off_per_build_over_http(monkeypatch):
    from fastapi.testclient import TestClient

    from kg2analyzer import server
    from kg2analyzer.kg2md import notebook

    c = TestClient(server.app)
    files = [("files", (str(p.relative_to(TINY)), p.read_bytes(), "text/turtle")) for p in sorted(TINY.rglob("*.ttl"))]
    off = c.post("/api/pipeline", data={"reset": "true", "decider": "structural"}, files=files)
    assert off.status_code == 200, off.text
    assert all("not by Tev1" in " ".join(k["warnings"]) for k in off.json()["kgs"])
    monkeypatch.setattr(notebook, "tev1_available", lambda: False)
    on = c.post("/api/pipeline", data={"reset": "true", "decider": "tev1"}, files=files)
    assert on.status_code == 400 and "uv sync --extra tev1" in on.json()["detail"]


def test_reset_all_returns_every_section_to_empty():
    from fastapi.testclient import TestClient

    from kg2analyzer import server

    c = TestClient(server.app)
    files = [("files", (str(p.relative_to(TINY)), p.read_bytes(), "text/turtle")) for p in sorted(TINY.rglob("*.ttl"))]
    assert c.post("/api/pipeline", data={"reset": "true", "decider": "structural"}, files=files).status_code == 200
    saved = c.get("/api/mdkg.zip", params={"ws": "build"}).content
    for ws in ("query", "ask"):
        assert c.post("/api/mdkgs", params={"ws": ws}, files=[("files", ("mdkg.zip", saved, "application/zip"))]).status_code == 200
    c.post("/api/translator", params={"ws": "ask"}, json={"spec": "rules"})
    assert c.post("/api/reset-all").status_code == 200
    for ws in ("build", "query", "ask"):
        st = c.get("/api/status", params={"ws": ws}).json()
        assert st["kgs"] == [] and st["cubes"] == 0 and st["identity_links"] == 0, ws
    assert c.get("/api/overview").json()["kgs"] == []
