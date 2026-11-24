"""OLAP operators over materialised cubes: roll-up, slice and dice.

Roll-up paths come from the catalogue (the concrete predicates that KG2MD
materialised), never from an assumed ontology; this is the lesson of the
blank Queries 21/22 in the thesis (section 5.3.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from kg2analyzer.catalog import Catalog, CubeInfo, DimensionInfo
from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.store import MultiKGStore

AGG = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "count": "COUNT"}
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


@dataclass
class Axis:
    """Group by ``level`` of dimension ``dimension`` (short names or IRIs)."""

    dimension: str
    level: str | None = None  # default: the dimension's base level


@dataclass
class Filter:
    """Slice/dice: keep observations whose ``dimension`` member at ``level`` has this IRI or label."""

    dimension: str
    value: str
    level: str | None = None


@dataclass
class OlapResult:
    sparql: str
    columns: list[str]
    rows: list[dict]
    warnings: list[str] = field(default_factory=list)


def _resolve_level(d: DimensionInfo, level: str | None) -> str:
    if level is None:
        return d.base_level
    for lv in d.levels:
        if lv == level or local_name(lv).lower() == level.lower() or d.level_name(lv).lower() == level.lower():
            return lv
    raise KeyError(f"level {level!r} not in dimension {d.name} (levels: {[d.level_name(x) for x in d.levels]})")


def _path(d: DimensionInfo, level: str, warnings: list[str]) -> str:
    if level == d.base_level:
        return f"<{d.prop}>"
    chains = d.paths_to(level)
    if not chains:
        raise KeyError(f"no roll-up path from {d.level_name(d.base_level)} to {d.level_name(level)}")
    many = {s.prop for s in d.steps if s.many_to_many}
    if any(p in many for c in chains for p in c):
        warnings.append(f"Roll-up to {d.level_name(level)} crosses a nonstrict (many-to-many) step: members with several "
                        "parents are counted once per parent.")
    if len(chains) > 1:
        warnings.append(f"{d.level_name(level)} is reached by {len(chains)} paths (ragged/alternative); all are unioned.")
    alts = "|".join("(" + "/".join(f"<{p}>" for p in c) + ")" for c in chains)
    return f"<{d.prop}>/({alts})"


def rollup(store: MultiKGStore, cat: Catalog, kg: str, measure: str, axes: list[Axis],
           filters: list[Filter] | None = None, aggregate: str | None = None, limit: int = 200) -> OlapResult:
    """Run a roll-up/slice/dice query and return labelled rows."""
    res = build_rollup(cat, kg, measure, axes, filters, aggregate, limit)
    res.rows = store.query(res.sparql).rows
    return res


def build_rollup(cat: Catalog, kg: str, measure: str, axes: list[Axis], filters: list[Filter] | None = None,
                 aggregate: str | None = None, limit: int = 200) -> OlapResult:
    """Build (without running) the roll-up SPARQL; ``rows`` is empty."""
    cube: CubeInfo | None = cat.cube_for(kg)
    if cube is None:
        raise KeyError(f"no cube for KG {kg!r}")
    m = cube.measure(measure)
    if m is None:
        raise KeyError(f"unknown measure {measure!r}; measures: {[local_name(x.iri) for x in cube.measures]}")
    agg = (aggregate or m.aggregate).lower()
    warnings: list[str] = []
    if agg == "sum" and m.additivity == "non-additive":
        warnings.append(f"{local_name(m.iri)} is non-additive; SUM is not summarizable. Use {m.aggregate.upper()}.")
    lines = [f"?o <http://purl.org/linked-data/cube#dataSet> <{cube.dataset}> ; <{m.iri}> ?value ."]
    select, group, cols = [], [], []
    for i, ax in enumerate(axes):
        d = cube.dimension(ax.dimension)
        if d is None:
            raise KeyError(f"unknown dimension {ax.dimension!r}")
        lvl = _resolve_level(d, ax.level)
        v = re.sub(r"[^A-Za-z0-9]", "_", d.level_name(lvl)).lower() or f"a{i}"
        if f"?{v}" in select or v in ("value", "total", "observations", "o"):
            v = f"{v}_{i}"
        lines.append(f"?o {_path(d, lvl, warnings)} ?{v} . OPTIONAL {{ ?{v} <{RDFS_LABEL}> ?{v}_label }}")
        select += [f"?{v}", f"?{v}_label"]
        group += [f"?{v}", f"?{v}_label"]
        cols += [v, f"{v}_label"]
    for j, f in enumerate(filters or []):
        d = cube.dimension(f.dimension)
        if d is None:
            raise KeyError(f"unknown dimension {f.dimension!r}")
        lvl = _resolve_level(d, f.level)
        v = f"f{j}"
        val = f.value.replace('"', '\\"')
        lines.append(f"?o {_path(d, lvl, warnings)} ?{v} . OPTIONAL {{ ?{v} <{RDFS_LABEL}> ?{v}_l }}")
        if val.startswith("http"):
            lines.append(f"FILTER(?{v} = <{val}>)")
        else:
            lines.append(f'FILTER(LCASE(STR(?{v}_l)) = LCASE("{val}") || STRENDS(STR(?{v}), "{val}"))')
    body = "\n    ".join(lines)
    sparql = (f"SELECT {' '.join(select)} ({AGG[agg]}(?value) AS ?total) (COUNT(?o) AS ?observations) WHERE {{\n"
              f"  GRAPH <{cube.graph}> {{\n    {body}\n  }}\n}}"
              + (f" GROUP BY {' '.join(group)}" if group else "")
              + f" ORDER BY DESC(?total) LIMIT {int(limit)}")
    return OlapResult(sparql, cols + ["total", "observations"], [], sorted(set(warnings)))
