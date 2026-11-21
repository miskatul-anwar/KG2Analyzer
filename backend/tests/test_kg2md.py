"""Phase I seam: run_kg2md(raw KG) -> cubes. Expected values come from the thesis."""
from decimal import Decimal

import pytest
from rdflib import URIRef

from kg2analyzer.benchmark.enterprise import build_enterprise_benchmark, ns
from kg2analyzer.benchmark.northwind import NW, build_northwind
from kg2analyzer.kg2md.pipeline import run_kg2md
from kg2analyzer.kg2md.profiling import otsu_threshold


def test_otsu_splits_a_bimodal_distribution_at_the_valley():
    # Thesis table 4.1: lowest selected 0.6514, highest rejected 0.6225 -> tau* = 0.6369
    scores = [0.9770, 0.8520, 0.7311, 0.7311, 0.6792, 0.6792, 0.6514,
              0.6225, 0.6225, 0.5622, 0.5312, 0.5312, 0.5312, 0.5, 0.5, 0.5, 0.4688, 0.4378]
    assert otsu_threshold(scores).threshold == pytest.approx(0.63695, abs=1e-4)


@pytest.fixture(scope="module")
def bench():
    return build_enterprise_benchmark()


@pytest.mark.parametrize("domain,fact,n_obs", [
    ("retail", "SaleTransaction", 30), ("logistics", "SupplierPurchaseOrder", 25),
    ("healthcare", "DiagnosticLabTest", 25), ("energy", "MeterReading", 30),
    ("finance", "InvestmentTrade", 30), ("building", "SensorReading", 30),
    ("supplychain", "FreightShipment", 30),
])
def test_each_domain_yields_its_fact_cube_with_every_fact_preserved(bench, domain, fact, n_obs):
    res = run_kg2md(bench.graphs[domain], explain=False)
    assert [c.fact_class for c in res.cubes] == [ns(domain)[fact]]
    audit = res.cubes[0].audit
    assert audit["observations"] == n_obs
    assert audit["ghost_observations"] == 0 and audit["dropped_facts"] == 0
    assert audit["measure_fidelity"] == 1.0


def test_retail_discount_is_non_additive_and_amount_is_summed(bench):
    cube = run_kg2md(bench.graphs["retail"]).cubes[0]
    by_name = {m.iri: m for m in cube.measures}
    amount = by_name[ns("retail").saleTotalAmount]
    discount = by_name[ns("retail").discount]
    assert amount.decision.additivity == "additive" and amount.aggregate == "sum"
    assert discount.decision.additivity == "non-additive" and discount.aggregate != "sum"
    assert amount.decision.shap and amount.decision.lime


def test_retail_hierarchies_cover_the_adw4_patterns(bench):
    cube = run_kg2md(bench.graphs["retail"], explain=False).cubes[0]
    kinds = {d.prop: set(d.kinds) for d in cube.dimensions}
    r = ns("retail")
    assert "alternative" in kinds[r.date]  # Day -> Month -> Year and Day -> Quarter -> Year
    assert "parallel" in kinds[r.product]  # Product -> Category, Product -> Distributor
    assert "ragged" in kinds[r.store]  # City -> Country skips State for Berlin


def test_finance_broker_chain_is_recursive_and_logistics_regions_are_nonstrict(bench):
    fin = run_kg2md(bench.graphs["finance"], explain=False).cubes[0]
    assert "recursive" in {k for d in fin.dimensions for k in d.kinds}
    log = run_kg2md(bench.graphs["logistics"], explain=False).cubes[0]
    assert "nonstrict" in {k for d in log.dimensions for k in d.kinds}


def test_northwind_product_to_category_rollup_matches_relational_ground_truth():
    res = run_kg2md(build_northwind(), explain=False)
    assert NW.Sales in [c.fact_class for c in res.cubes]
    q = f"""
    SELECT ?cat (SUM(?amt) AS ?total) WHERE {{
      ?o <http://purl.org/linked-data/cube#dataSet> <{NW}dataset-Sales> ;
         <{NW}product> ?p ; <{NW}salesTotalAmount> ?amt .
      ?p <{NW}category> ?c . ?c <http://www.w3.org/2000/01/rdf-schema#label> ?cat .
    }} GROUP BY ?cat"""
    totals = {str(r.cat): Decimal(str(r.total)) for r in res.data.query(q)}
    assert totals == {"Beverages": Decimal("541.00"), "Condiments": Decimal("2865.69"),
                      "Meat/Poultry": Decimal("388.00"), "Produce": Decimal("342.00"),
                      "Seafood": Decimal("471.20")}
    assert sum(totals.values()) == Decimal("4607.89")


def test_measure_classification_is_deterministic_across_processes():
    """Same KG, same MDKG: additivity must not depend on Python's per-process hash seed."""
    import os
    import subprocess
    import sys

    code = ("import warnings; warnings.filterwarnings('ignore');"
            "from kg2analyzer.kg2md.measures import MeasureClassifier;"
            "d = MeasureClassifier().classify('unitPrice', 'xsd:decimal', 'USD', False, explain=False);"
            "print(d.additivity, d.aggregate)")
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                           env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout.strip() for seed in range(6)}
    # a unit price is an intensive (non-additive) measure: thesis section 1.2
    assert outs == {"non-additive avg"}
