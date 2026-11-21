"""Cross-cube query planning with pushdown pre-aggregation (thesis 3.6.2, Algorithm 2).

A naive plan joins observations of two cubes before aggregating, so an
entity with m left and n right observations produces m x n joined rows and
every measure is inflated (the *Cartesian Multiplication Trap*). The pushdown
plan aggregates each cube at its native grain first: AGG(C1) |><| AGG(C2).
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal as Lit

from kg2analyzer.catalog import Catalog
from kg2analyzer.store import IDENTITY_GRAPH, LocalEndpoint, MultiKGStore, data_graph

QB = "http://purl.org/linked-data/cube#"
OWL_SAMEAS = "http://www.w3.org/2002/07/owl#sameAs"
AGG = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "count": "COUNT"}


@dataclass
class CubeSide:
    kg: str
    dataset: str
    entity_prop: str  # dimension property that identifies the joined entity (customer, trader, date...)
    measure: str
    aggregate: str = "sum"


@dataclass
class CrossCubeQuery:
    left: CubeSide
    right: CubeSide
    link: Lit["identity", "shared"] = "identity"  # owl:sameAs identity graph, or a conformed (shared-IRI) dimension


@dataclass
class CrossCubeResult:
    strategy: str
    mode: str
    rows: list[dict]
    seconds: float
    plan: dict
    guard: dict = field(default_factory=dict)


def _side_pattern(s: CubeSide, obs: str, ent: str, val: str, graph: bool = True) -> str:
    body = f"?{obs} <{QB}dataSet> <{s.dataset}> ; <{s.entity_prop}> ?{ent} ; <{s.measure}> ?{val} ."
    return f"GRAPH <{data_graph(s.kg)}> {{ {body} }}" if graph else body


def _subquery(s: CubeSide, ent: str, out: str, graph: bool = True) -> str:
    agg = AGG[s.aggregate]
    return (f"SELECT ?{ent} ({agg}(?v) AS ?{out}) (COUNT(?o) AS ?{out}_n) WHERE {{ "
            f"{_side_pattern(s, 'o', ent, 'v', graph)} }} GROUP BY ?{ent}")


def _link(q: CrossCubeQuery) -> str:
    if q.link == "shared":
        return "FILTER(?left_entity = ?right_entity)"
    return f"GRAPH <{IDENTITY_GRAPH}> {{ ?left_entity (<{OWL_SAMEAS}>|^<{OWL_SAMEAS}>)+ ?right_entity }}"


def pushdown_sparql(q: CrossCubeQuery) -> str:
    """Listing 3.1 / A.2: aggregate each cube in an isolated subquery, then join."""
    return f"""SELECT ?left_entity ?right_entity ?left_total ?right_total ?left_total_n ?right_total_n WHERE {{
  {{ {_subquery(q.left, 'left_entity', 'left_total')} }}
  {{ {_subquery(q.right, 'right_entity', 'right_total')} }}
  {_link(q)}
}} ORDER BY ?left_entity ?right_entity"""


def naive_sparql(q: CrossCubeQuery) -> str:
    """The archived Query-23 shape: join observations first, aggregate after (Cartesian trap)."""
    la, ra = AGG[q.left.aggregate], AGG[q.right.aggregate]
    return f"""SELECT ?left_entity ?right_entity ({la}(?lv) AS ?left_total) ({ra}(?rv) AS ?right_total) (COUNT(*) AS ?joined_rows) WHERE {{
  {_side_pattern(q.left, 'lo', 'left_entity', 'lv')}
  {_side_pattern(q.right, 'ro', 'right_entity', 'rv')}
  {_link(q)}
}} GROUP BY ?left_entity ?right_entity ORDER BY ?left_entity ?right_entity"""


def _guard(rows: list[dict]) -> dict:
    """Cartesian factor guard: what a naive join would multiply each side by."""
    pairs = []
    for r in rows:
        m, n = int(r.get("left_total_n") or 0), int(r.get("right_total_n") or 0)
        pairs.append({"left_entity": r["left_entity"], "right_entity": r["right_entity"],
                      "left_observations": m, "right_observations": n, "naive_joined_rows": m * n,
                      "left_inflation": n, "right_inflation": m})
    risky = [p for p in pairs if p["naive_joined_rows"] > 1 and p["left_observations"] > 0]
    return {"cartesian_risk": any(p["left_inflation"] > 1 or p["right_inflation"] > 1 for p in pairs),
            "pairs": pairs, "max_inflation": max([max(p["left_inflation"], p["right_inflation"]) for p in risky] or [1])}


def execute(store: MultiKGStore, q: CrossCubeQuery, strategy: str = "pushdown",
            mode: str = "integrated") -> CrossCubeResult:
    if strategy not in ("pushdown", "naive"):
        raise ValueError("strategy must be 'pushdown' or 'naive'")
    if mode == "integrated":
        sparql = pushdown_sparql(q) if strategy == "pushdown" else naive_sparql(q)
        t0 = time.perf_counter()
        out = store.query(sparql)
        rows = out.rows
        secs = time.perf_counter() - t0
        plan = {"sparql": sparql, "engine": "single RDFLib Dataset (physical named-graph integration)"}
    elif mode == "federated":
        rows, plan, secs = _federated(store, q, strategy)
    else:
        raise ValueError("mode must be 'integrated' or 'federated'")
    guard = {}
    if strategy == "pushdown":
        guard = _guard(rows)
    else:
        guard = {"cartesian_risk": any(int(r.get("joined_rows") or 1) > 1 for r in rows),
                 "pairs": [{"left_entity": r["left_entity"], "right_entity": r["right_entity"],
                            "naive_joined_rows": int(r.get("joined_rows") or 0)} for r in rows]}
    clean = [{k: v for k, v in r.items() if not k.endswith("_n")} for r in rows]
    return CrossCubeResult(strategy, mode, clean, secs, plan, guard)


def _federated(store: MultiKGStore, q: CrossCubeQuery, strategy: str):
    """Mediator plan: ship sub-queries to each autonomous source, join on identity clusters."""
    t0 = time.perf_counter()
    graph_l = isinstance(store.sources[q.left.kg], LocalEndpoint)
    graph_r = isinstance(store.sources[q.right.kg], LocalEndpoint)
    if strategy == "pushdown":
        sq_l = _subquery(q.left, "left_entity", "left_total", graph_l)
        sq_r = _subquery(q.right, "right_entity", "right_total", graph_r)
    else:
        sq_l = f"SELECT ?left_entity ?lv WHERE {{ {_side_pattern(q.left, 'lo', 'left_entity', 'lv', graph_l)} }}"
        sq_r = f"SELECT ?right_entity ?rv WHERE {{ {_side_pattern(q.right, 'ro', 'right_entity', 'rv', graph_r)} }}"
    _, left = store.sources[q.left.kg].select(sq_l)
    _, right = store.sources[q.right.kg].select(sq_r)
    if q.link == "shared":
        key = lambda x: ("k", x)  # noqa: E731
    else:
        clusters = store.identity_clusters()
        key = lambda x: ("c", clusters[x]) if x in clusters else None  # noqa: E731
    right_by_key = defaultdict(list)
    for r in right:
        k = key(r["right_entity"])
        if k is not None:
            right_by_key[k].append(r)
    rows = []
    if strategy == "pushdown":
        for l in left:
            k = key(l["left_entity"])
            for r in right_by_key.get(k, []) if k is not None else []:
                if q.link == "identity" and l["left_entity"] == r["right_entity"]:
                    continue
                rows.append({**l, **r})
    else:
        acc: dict[tuple, dict] = {}
        for l in left:
            k = key(l["left_entity"])
            for r in right_by_key.get(k, []) if k is not None else []:
                if q.link == "identity" and l["left_entity"] == r["right_entity"]:
                    continue
                a = acc.setdefault((l["left_entity"], r["right_entity"]),
                                   {"left_entity": l["left_entity"], "right_entity": r["right_entity"],
                                    "lv": [], "rv": []})
                a["lv"].append(Decimal(str(l["lv"])))
                a["rv"].append(Decimal(str(r["rv"])))
        for a in acc.values():
            rows.append({"left_entity": a["left_entity"], "right_entity": a["right_entity"],
                         "left_total": _agg(q.left.aggregate, a["lv"]), "right_total": _agg(q.right.aggregate, a["rv"]),
                         "joined_rows": len(a["lv"])})
    rows.sort(key=lambda r: (r["left_entity"], r["right_entity"]))
    plan = {"mediator": "KG2Analyzer federated mediator (identity union-find join)",
            "subqueries": {q.left.kg: sq_l, q.right.kg: sq_r},
            "transferred_rows": {q.left.kg: len(left), q.right.kg: len(right)}}
    return rows, plan, time.perf_counter() - t0


def _agg(name: str, vals: list[Decimal]):
    if name == "sum":
        return sum(vals)
    if name == "avg":
        return sum(vals) / len(vals)
    if name == "min":
        return min(vals)
    if name == "max":
        return max(vals)
    return len(vals)


def side_from_catalog(cat: Catalog, kg: str, entity: str, measure: str) -> CubeSide:
    """Resolve a cube side from short names (e.g. kg='retail', entity='customer', measure='saleTotalAmount')."""
    cube = cat.cube_for(kg)
    if cube is None:
        raise KeyError(f"no cube materialised for KG {kg!r}")
    d = cube.dimension(entity)
    m = cube.measure(measure)
    if d is None or m is None:
        raise KeyError(f"unknown dimension {entity!r} or measure {measure!r} in {kg}")
    return CubeSide(kg, cube.dataset, d.prop, m.iri, m.aggregate)
