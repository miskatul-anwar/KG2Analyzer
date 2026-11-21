"""ADW4 dimension hierarchy discovery (thesis section 2.5.2 and figure 3.2).

From each dimension property of a fact class, walks outgoing object
properties between level members, builds the level graph, and flags the six
structural patterns: balanced, recursive, ragged, alternative, parallel and
nonstrict (plus unbalanced when some members lack a parent).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import networkx as nx
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

KINDS = ("balanced", "recursive", "ragged", "alternative", "parallel", "nonstrict", "unbalanced")


@dataclass
class RollupStep:
    child: URIRef
    parent: URIRef
    prop: URIRef
    coverage: float  # fraction of child members with at least one parent
    many_to_many: bool  # some child has several parents (nonstrict)
    weights: dict[str, dict[str, float]] = field(default_factory=dict)  # nonstrict allocation weights


@dataclass
class Dimension:
    prop: URIRef  # fact -> base-level member
    base_level: URIRef
    levels: list[URIRef]
    steps: list[RollupStep]
    kinds: list[str]
    paths: list[list[URIRef]]  # level chains from base to each top level

    def step(self, child: URIRef, parent: URIRef) -> RollupStep | None:
        return next((s for s in self.steps if s.child == child and s.parent == parent), None)


def _majority_class(members, types) -> URIRef | None:
    c = Counter(cl for m in members for cl in types.get(m, ()))
    return c.most_common(1)[0][0] if c else None


def discover_dimensions(g: Graph, fact_class: URIRef, facts: set[URIRef],
                        types: dict[URIRef, set[URIRef]]) -> list[Dimension]:
    dim_props: dict[URIRef, set[URIRef]] = defaultdict(set)
    for f in facts:
        for _, p, o in g.triples((f, None, None)):
            if p != RDF.type and isinstance(o, URIRef) and o in types:
                dim_props[p].add(o)
    dims = []
    for prop in sorted(dim_props):
        base = _majority_class(dim_props[prop], types)
        if base is None or base == fact_class:
            continue
        dims.append(_walk(g, prop, base, fact_class, types))
    return dims


def _members(types, cls):
    return {s for s, cs in types.items() if cls in cs}


def _walk(g: Graph, prop: URIRef, base: URIRef, fact_class: URIRef, types) -> Dimension:
    levels = [base]
    steps: list[RollupStep] = []
    seen = {base}
    queue = [base]
    while queue:
        lvl = queue.pop(0)
        mem = _members(types, lvl)
        edges: dict[tuple[URIRef, URIRef], dict[URIRef, set[URIRef]]] = defaultdict(lambda: defaultdict(set))
        for m in mem:
            for _, p, o in g.triples((m, None, None)):
                if p == RDF.type or not isinstance(o, URIRef) or o not in types or o == m:
                    continue
                parent_cls = _majority_class([o], types)
                if parent_cls in (None, fact_class):
                    continue
                edges[(p, parent_cls)][m].add(o)
        for (p, parent_cls), mapping in sorted(edges.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            many = any(len(v) > 1 for v in mapping.values())
            weights = {}
            if many:
                weights = {str(c): {str(par): round(1 / len(ps), 4) for par in ps} for c, ps in mapping.items()}
            steps.append(RollupStep(lvl, parent_cls, p, len(mapping) / max(1, len(mem)), many, weights))
            if parent_cls not in seen:
                seen.add(parent_cls)
                levels.append(parent_cls)
                queue.append(parent_cls)
    kinds, paths = _classify(base, levels, steps)
    return Dimension(prop, base, levels, steps, kinds, paths)


def _classify(base, levels, steps) -> tuple[list[str], list[list[URIRef]]]:
    dag = nx.DiGraph()
    dag.add_nodes_from(levels)
    kinds: set[str] = set()
    for s in steps:
        if s.child == s.parent:
            kinds.add("recursive")
        else:
            dag.add_edge(s.child, s.parent)
        if s.many_to_many:
            kinds.add("nonstrict")
    skip_edges = set()
    for s in steps:
        if s.child == s.parent:
            continue
        # ragged: a direct edge that shortcuts a longer path (City -> Country beside City -> State -> Country)
        h = dag.copy()
        h.remove_edge(s.child, s.parent)
        if nx.has_path(h, s.child, s.parent):
            kinds.add("ragged")
            skip_edges.add((s.child, s.parent))
    for lvl in levels:
        outs = [p for p in dag.successors(lvl) if (lvl, p) not in skip_edges]
        if len(outs) >= 2:
            anc = [nx.descendants(dag, o) | {o} for o in outs]
            converge = any(anc[i] & anc[j] for i in range(len(anc)) for j in range(i + 1, len(anc)))
            kinds.add("alternative" if converge else "parallel")
    for s in steps:
        if s.child != s.parent and s.coverage < 1 and (s.child, s.parent) not in skip_edges:
            # a member without parent that is not explained by a ragged skip
            sibling_skip = any(c == s.child for c, _ in skip_edges)
            if not sibling_skip:
                kinds.add("unbalanced")
    if not kinds and dag.number_of_edges():
        kinds.add("balanced")
    tops = [n for n in dag.nodes if dag.out_degree(n) == 0 and n != base]
    paths = []
    for t in tops:
        paths.extend(nx.all_simple_paths(dag, base, t))
    if not paths:
        paths = [[base]]
    return [k for k in KINDS if k in kinds], paths
