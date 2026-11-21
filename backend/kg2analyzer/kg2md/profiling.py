"""RDFS closure, class profiling, fact scoring and Otsu fact selection.

Thesis sections 3.5 and 3.6.1 (Algorithm 1).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

NUMERIC_XSD = {
    XSD.decimal, XSD.integer, XSD.int, XSD.long, XSD.short, XSD.float, XSD.double,
    XSD.nonNegativeInteger, XSD.positiveInteger, XSD.unsignedInt, XSD.unsignedLong,
}
SCHEMA_TYPES = {OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property,
                OWL.AnnotationProperty, OWL.Ontology, OWL.Restriction}


def rdfs_closure(graph: Graph) -> Graph:
    """Forward-chaining RDFS closure (rdfs2, rdfs3, rdfs7, rdfs9, rdfs11) over a copy.

    Schema entities (classes, properties) are protected from instance-level
    entailment so ``rdfs:domain`` on annotation properties cannot type them.
    """
    g = Graph()
    for t in graph:
        g.add(t)
    for prefix, uri in graph.namespaces():
        g.bind(prefix, uri, override=False)
    schema = {s for s, _, o in graph.triples((None, RDF.type, None)) if o in SCHEMA_TYPES}
    while True:
        new = set()
        # rdfs11 / rdfs5: transitivity
        for rel in (RDFS.subClassOf, RDFS.subPropertyOf):
            for a, _, b in g.triples((None, rel, None)):
                for _, _, c in g.triples((b, rel, None)):
                    if (a, rel, c) not in g:
                        new.add((a, rel, c))
        # rdfs7: subPropertyOf
        for p, _, q in g.triples((None, RDFS.subPropertyOf, None)):
            for s, _, o in g.triples((None, p, None)):
                if (s, q, o) not in g:
                    new.add((s, q, o))
        # rdfs2 / rdfs3: domain and range typing
        for p, _, c in g.triples((None, RDFS.domain, None)):
            for s, _, _ in g.triples((None, p, None)):
                if s not in schema and isinstance(s, URIRef) and (s, RDF.type, c) not in g:
                    new.add((s, RDF.type, c))
        for p, _, c in g.triples((None, RDFS.range, None)):
            if (p, RDF.type, OWL.DatatypeProperty) in g or c in NUMERIC_XSD or str(c).startswith(str(XSD)):
                continue
            for _, _, o in g.triples((None, p, None)):
                if isinstance(o, URIRef) and o not in schema and (o, RDF.type, c) not in g:
                    new.add((o, RDF.type, c))
        # rdfs9: subClassOf typing
        for a, _, b in g.triples((None, RDFS.subClassOf, None)):
            for s, _, _ in g.triples((None, RDF.type, a)):
                if (s, RDF.type, b) not in g:
                    new.add((s, RDF.type, b))
        if not new:
            return g
        for t in new:
            g.add(t)


def local_name(iri) -> str:
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def is_numeric_literal(o) -> bool:
    return isinstance(o, Literal) and (o.datatype in NUMERIC_XSD or (
        o.datatype is None and isinstance(o.toPython(), (int, float)) and not isinstance(o.toPython(), bool)))


@dataclass
class ClassProfile:
    """Structural metrics of one candidate class (thesis section 3.5)."""

    iri: URIRef
    label: str
    instance_count: int
    numeric_props: list[URIRef]  # datatype properties with numeric values on >=50% of instances
    out_object_props: list[URIRef]  # object properties to typed instances on >=50% of instances
    in_object_props: list[URIRef]
    referenced_ratio: float  # fraction of instances that are the object of a link from another instance
    self_links: bool

    def features(self) -> dict[str, float]:
        return {
            "numeric_measures": float(min(len(self.numeric_props), 6)),
            "outgoing_links": float(min(len(self.out_object_props), 8)),
            "referenced_ratio": self.referenced_ratio,
            "incoming_link_types": float(min(len(self.in_object_props), 6)),
            "log_instances": math.log10(1 + self.instance_count),
        }


def instance_classes(g: Graph) -> dict[URIRef, set[URIRef]]:
    schema = {s for s, _, o in g.triples((None, RDF.type, None)) if o in SCHEMA_TYPES}
    out: dict[URIRef, set[URIRef]] = defaultdict(set)
    for s, _, c in g.triples((None, RDF.type, None)):
        if isinstance(s, URIRef) and s not in schema and c not in SCHEMA_TYPES and isinstance(c, URIRef):
            out[s].add(c)
    return out


def profile_classes(g: Graph) -> list[ClassProfile]:
    """Profile every class that has instances."""
    types = instance_classes(g)
    members: dict[URIRef, set[URIRef]] = defaultdict(set)
    for s, cs in types.items():
        for c in cs:
            members[c].add(s)
    referenced: set[URIRef] = set()
    in_props: dict[URIRef, set[URIRef]] = defaultdict(set)
    for s, p, o in g:
        if p == RDF.type or not isinstance(o, URIRef) or o not in types or s not in types or s == o:
            continue
        referenced.add(o)
        for c in types[o]:
            in_props[c].add(p)
    profiles = []
    for c, inst in members.items():
        n = len(inst)
        numeric: Counter = Counter()
        out_obj: Counter = Counter()
        self_links = False
        for s in inst:
            seen_num, seen_obj = set(), set()
            for _, p, o in g.triples((s, None, None)):
                if p == RDF.type:
                    continue
                if is_numeric_literal(o):
                    seen_num.add(p)
                elif isinstance(o, URIRef) and o in types and o != s:
                    seen_obj.add(p)
                    if c in types[o]:
                        self_links = True
            numeric.update(seen_num)
            out_obj.update(seen_obj)
        half = max(1, math.ceil(n / 2))
        label = g.value(c, RDFS.label)
        profiles.append(ClassProfile(
            iri=c,
            label=str(label) if label else local_name(c),
            instance_count=n,
            numeric_props=sorted(p for p, k in numeric.items() if k >= half),
            out_object_props=sorted(p for p, k in out_obj.items() if k >= half),
            in_object_props=sorted(in_props.get(c, ())),
            referenced_ratio=sum(1 for s in inst if s in referenced) / n,
            self_links=self_links,
        ))
    return sorted(profiles, key=lambda p: str(p.iri))


class FactScorer(Protocol):
    """Assigns an empirical fact probability p_c in [0, 1] to a class profile."""

    name: str

    def score(self, profile: ClassProfile) -> tuple[float, dict[str, float]]:
        """Return (probability, per-feature contribution to the logit)."""


class TopologicalFactScorer:
    """Transparent logistic scorer over topological features (default Tev1 stand-in).

    Facts are events: they carry numeric measures, fan out to several
    dimensions, and are rarely the target of links. Weights are fixed and
    the per-feature logit contributions are returned so every decision is
    explainable.
    """

    name = "topological-logistic"
    WEIGHTS = {
        "numeric_measures": 1.1,
        "outgoing_links": 0.55,
        "referenced_ratio": -3.2,
        "incoming_link_types": -0.35,
        "log_instances": 0.4,
    }
    BIAS = -1.4

    def score(self, profile: ClassProfile) -> tuple[float, dict[str, float]]:
        feats = profile.features()
        contrib = {k: self.WEIGHTS[k] * v for k, v in feats.items()}
        z = self.BIAS + sum(contrib.values())
        return 1.0 / (1.0 + math.exp(-z)), contrib


@dataclass
class OtsuResult:
    threshold: float
    between_class_variance: list[tuple[float, float]] = field(default_factory=list)  # (candidate tau, sigma_B^2)


def otsu_threshold(values: Iterable[float], bins: int | None = None) -> OtsuResult:
    """Otsu's between-class variance maximisation (thesis eq. 2.3-2.5).

    With ``bins=None`` the exact variant is used: every gap between consecutive
    sorted values is a candidate and tau* is the midpoint of the best gap.
    With ``bins=K`` the histogram variant of Algorithm 1 is used and tau* is
    the upper edge of the best background bin.
    """
    xs = sorted(float(v) for v in values)
    if not xs:
        raise ValueError("otsu_threshold needs at least one value")
    if len(xs) == 1 or xs[0] == xs[-1]:
        return OtsuResult(threshold=xs[-1])
    curve: list[tuple[float, float]] = []
    if bins is None:
        n = len(xs)
        best, tau = -1.0, xs[-1]
        for i in range(1, n):
            if xs[i] == xs[i - 1]:
                continue
            w0, w1 = i / n, (n - i) / n
            mu0, mu1 = sum(xs[:i]) / i, sum(xs[i:]) / (n - i)
            var = w0 * w1 * (mu0 - mu1) ** 2
            cand = (xs[i - 1] + xs[i]) / 2
            curve.append((cand, var))
            if var > best:
                best, tau = var, cand
        return OtsuResult(threshold=tau, between_class_variance=curve)
    lo, hi = xs[0], xs[-1]
    width = (hi - lo) / bins
    hist = [0] * bins
    for x in xs:
        hist[min(bins - 1, int((x - lo) / width))] += 1
    p = [h / len(xs) for h in hist]
    best, tau = -1.0, lo + width
    for t in range(1, bins):
        w0 = sum(p[:t])
        w1 = 1 - w0
        if w0 == 0 or w1 == 0:
            continue
        mu0 = sum((i + 0.5) * p[i] for i in range(t)) / w0
        mu1 = sum((i + 0.5) * p[i] for i in range(t, bins)) / w1
        var = w0 * w1 * (mu0 - mu1) ** 2
        cand = lo + t * width
        curve.append((cand, var))
        if var > best:
            best, tau = var, cand
    return OtsuResult(threshold=tau, between_class_variance=curve)


@dataclass
class FactSelection:
    """Outcome of Algorithm 1 over one KG."""

    scorer: str
    threshold: float
    scores: dict[URIRef, float]
    contributions: dict[URIRef, dict[str, float]]
    selected: list[URIRef]
    curve: list[tuple[float, float]]


def select_fact_classes(profiles: list[ClassProfile], scorer: FactScorer | None = None,
                        bins: int | None = None, max_facts: int | None = None,
                        eligible: Callable[[ClassProfile], bool] | None = None) -> FactSelection:
    scorer = scorer or TopologicalFactScorer()
    eligible = eligible or (lambda p: p.instance_count > 0)
    scores, contribs = {}, {}
    for p in profiles:
        if eligible(p):
            scores[p.iri], contribs[p.iri] = scorer.score(p)
    if not scores:
        return FactSelection(scorer.name, 1.0, {}, {}, [], [])
    otsu = otsu_threshold(scores.values(), bins=bins)
    if len(set(scores.values())) == 1:  # degenerate: deterministic single pick
        chosen = [min(scores, key=str)]
    else:
        chosen = [c for c, s in scores.items() if s >= otsu.threshold]
    chosen.sort(key=lambda c: (-scores[c], str(c)))
    if max_facts:
        chosen = chosen[:max_facts]
    return FactSelection(scorer.name, otsu.threshold, scores, contribs, chosen, otsu.between_class_variance)
