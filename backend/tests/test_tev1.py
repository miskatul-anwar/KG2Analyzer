"""The real KG2MD decision model (Tev1) at the decider seam. Opt-in: it needs `uv sync --extra tev1` and
downloads the 1.8 GB checkpoint on first use. Run with KG2A_TEST_TEV1=1."""
import os
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("KG2A_TEST_TEV1") != "1", reason="set KG2A_TEST_TEV1=1 to run Tev1")


def test_tev1_builds_the_northwind_mdkg():
    from fixtures.northwind import CATEGORY_TOTALS, build_northwind
    from kg2analyzer.analyzer import KG2Analyzer
    from kg2analyzer.ingest import RdfFile
    from kg2analyzer.kg2md.notebook import tev1_decider

    az = KG2Analyzer(translator="rules", decider=tev1_decider("cpu"))
    rep = az.ingest([RdfFile("northwind.ttl", build_northwind().serialize(format="turtle").encode())], auto_link=False)
    nw = rep["kgs"][0]
    assert nw["decider"] == "togethercomputer/Tev1-0.8B-experimental"
    assert [c["fact_class"] for c in nw["cubes"]] == ["Sales"]
    assert nw["cubes"][0]["fact_preservation"] == nw["cubes"][0]["measure_fidelity"] == 1.0
    olap = az.olap("northwind", "salesTotalAmount", group_by=[("product", "Category")])
    assert {r["category_label"]: Decimal(str(r["total"])) for r in olap.rows} == CATEGORY_TOTALS
