"""Reproduce the thesis' results tables from the running system.

    python -m kg2analyzer.benchmark.evaluate            # deterministic grounded parser
    KG2A_TRANSLATOR=ollama python -m kg2analyzer.benchmark.evaluate   # local LLM (qwen2.5-coder:3b)
"""
from __future__ import annotations

import json
import statistics
import sys
import time
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


def run(az: KG2Analyzer | None = None) -> dict:
    az = az or KG2Analyzer()
    t0 = time.perf_counter()
    az.load_benchmark()
    load_s = time.perf_counter() - t0
    report: dict = {"load_seconds": round(load_s, 2)}

    # Table 4.4: seven-domain telemetry
    tel = []
    for kg, res in az.results.items():
        for c in res.cubes:
            tel.append({"domain": kg, "fact_class": local_name(c.fact_class),
                        "fact_score": round(res.selection.scores[c.fact_class], 3),
                        "otsu_tau": round(res.selection.threshold, 4), "observations": c.observations,
                        "measures": len(c.measures), "fact_preservation": c.audit["fact_preservation"],
                        "measure_fidelity": c.audit["measure_fidelity"]})
    report["domain_telemetry"] = tel

    # Table 4.5: Query 23 audit
    q23 = {}
    for strat in ("naive", "pushdown"):
        for mode in ("integrated", "federated"):
            r = az.cross_cube(("retail", "customer", "saleTotalAmount"), ("finance", "trader", "tradeAmount"), "identity", strat, mode)
            q23[f"{strat}/{mode}"] = {local_name(x["left_entity"]): {"retail": str(x["left_total"]), "finance": str(x["right_total"])}
                                      for x in r.rows} | {"seconds": round(r.seconds, 4)}
    report["query23"] = q23

    # 4.2.4: identity communities
    com = az.communities("identity")
    report["identity_communities"] = {"count": len(com["communities"]), "sizes": [c["size"] for c in com["communities"]],
                                      "modularity": com["modularity"]}

    # Table 4.6: NL benchmark
    outcomes, lat = [], []
    for qid, q, expect in NL_QUESTIONS:
        a = az.ask(q)
        lat.append(a.seconds)
        ok = (a.status in ("executed", "fallback") and bool(a.rows)) if expect == "answer" else a.status == "rejected"
        outcomes.append({"id": qid, "question": q, "expected": expect, "status": a.status, "rows": len(a.rows),
                         "correct_outcome": ok, "seconds": round(a.seconds, 3)})
    executed = sum(1 for o in outcomes if o["status"] in ("executed", "fallback") and o["rows"])
    report["nl_benchmark"] = {
        "translator": az.nl.translator.name,
        "questions": len(outcomes),
        "model_generated_executed": sum(1 for o in outcomes if o["status"] == "executed" and o["rows"]),
        "fallback_executed": sum(1 for o in outcomes if o["status"] == "fallback" and o["rows"]),
        "rejected": sum(1 for o in outcomes if o["status"] == "rejected"),
        "execution_rate": round(executed / len(outcomes), 4),
        "correct_outcome_rate": round(sum(o["correct_outcome"] for o in outcomes) / len(outcomes), 4),
        "mean_latency_seconds": round(statistics.mean(lat), 3),
        "outcomes": outcomes,
    }
    return report


def main() -> None:
    rep = run()
    json.dump(rep, sys.stdout, indent=2, default=lambda o: str(o) if isinstance(o, Decimal) else o)
    print()


if __name__ == "__main__":
    main()
