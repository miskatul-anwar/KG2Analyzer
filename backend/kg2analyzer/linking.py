"""Cross-KG node linking: discover owl:sameAs candidates between two KGs.

Blocking on shared label tokens / literal values, then each candidate pair is
scored from four signals:

* ``label_trigram``  character-trigram Jaccard of rdfs:labels
* ``label_tokens``   token Jaccard of rdfs:labels
* ``literal_overlap`` Jaccard of the other literal values (e-mails, codes ...)
* ``sgc_cosine``     cosine of SGC graph-neural embeddings (attributes + neighbourhood)

Two distinct IRIs from the same namespace are never paired (unique-name
assumption: one authority does not mint two IRIs for one entity), and IRIs
present in both KGs (conformed members such as shared dates) need no link.

With at least ``min_training_links`` existing sameAs links between the two
KGs a logistic regression is trained on them (positives) against blocked
non-links (negatives); otherwise a fixed, documented weighting is used.
Accepted links are never inferred silently: callers add them to the identity
graph explicitly (explicit identity invariant, thesis section 3.2).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
import numpy as np

from kg2analyzer.graphml import sgc_embeddings, tokens

FEATURES = ("label_trigram", "label_tokens", "literal_overlap", "sgc_cosine")
HEURISTIC_WEIGHTS = np.array([0.40, 0.20, 0.25, 0.15])


@dataclass
class LinkCandidate:
    left: str
    right: str
    left_label: str | None
    right_label: str | None
    score: float
    features: dict[str, float]
    known: bool = False


def _namespace(iri: str) -> str:
    """Minting authority: scheme + host + first path segment (``http://example.org/time``)."""
    m = re.match(r"^([a-z]+://[^/#]+/?[^/#]*)", iri)
    return m.group(1) if m else iri


def _trigrams(s: str) -> set[str]:
    s = f"  {s.lower()} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def discover_links(G: nx.Graph, kg_a: str, kg_b: str, known: set[tuple[str, str]] | None = None,
                   threshold: float = 0.5, one_to_one: bool = True, min_training_links: int = 3,
                   limit: int = 200) -> tuple[list[LinkCandidate], dict]:
    known = known or set()
    a_nodes = [n for n, d in G.nodes(data=True) if d.get("kg") == kg_a and not d.get("observation") and not d.get("shared") and (d.get("label") or d.get("literals"))]
    b_nodes = [n for n, d in G.nodes(data=True) if d.get("kg") == kg_b and not d.get("observation") and not d.get("shared") and (d.get("label") or d.get("literals"))]
    # blocking index
    index: dict[str, set[str]] = defaultdict(set)
    for n in b_nodes:
        d = G.nodes[n]
        for t in tokens(d.get("label") or ""):
            if len(t) > 2:
                index["t:" + t].add(n)
        for lit in d.get("literals", ()):
            index["l:" + lit.lower()].add(n)
    pairs = set()
    for n in a_nodes:
        d = G.nodes[n]
        keys = {"t:" + t for t in tokens(d.get("label") or "") if len(t) > 2} | {"l:" + x.lower() for x in d.get("literals", ())}
        for k in keys:
            for m in index.get(k, ()):
                if m != n and _namespace(m) != _namespace(n):  # unique-name assumption within a namespace
                    pairs.add((n, m))
    pairs |= {(a, b) for a, b in known if a in G and b in G}
    if not pairs:
        return [], {"model": "none", "pairs_scored": 0}
    nodes, H = sgc_embeddings(G, k=2)
    pos = {n: i for i, n in enumerate(nodes)}
    feats = []
    plist = sorted(pairs)
    for a, b in plist:
        da, db = G.nodes[a], G.nodes[b]
        la, lb = da.get("label") or "", db.get("label") or ""
        feats.append([
            _jac(_trigrams(la), _trigrams(lb)) if la and lb else 0.0,
            _jac(set(tokens(la)), set(tokens(lb))),
            _jac({x.lower() for x in da.get("literals", ())}, {x.lower() for x in db.get("literals", ())}),
            float(H[pos[a]] @ H[pos[b]]),
        ])
    X = np.array(feats)
    y_known = np.array([(a, b) in known or (b, a) in known for a, b in plist])
    info: dict = {"pairs_scored": len(plist), "blocked_from": len(a_nodes) * len(b_nodes)}
    if y_known.sum() >= min_training_links and (~y_known).sum() >= min_training_links:
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(class_weight="balanced", max_iter=1000).fit(X, y_known)
        scores = clf.predict_proba(X)[:, 1]
        info.update(model="logistic-regression (trained on existing sameAs links)",
                    weights=dict(zip(FEATURES, np.round(clf.coef_[0], 3).tolist())))
    else:
        scores = X @ HEURISTIC_WEIGHTS / HEURISTIC_WEIGHTS.sum()
        info.update(model="weighted heuristic (no training links)", weights=dict(zip(FEATURES, HEURISTIC_WEIGHTS.tolist())))
    cands = [LinkCandidate(a, b, G.nodes[a].get("label"), G.nodes[b].get("label"), round(float(s), 4),
                           dict(zip(FEATURES, np.round(x, 4).tolist())), bool(k))
             for (a, b), s, x, k in zip(plist, scores, X, y_known)]
    cands.sort(key=lambda c: -c.score)
    if one_to_one:
        used_a, used_b, kept = set(), set(), []
        for c in cands:
            if c.left in used_a or c.right in used_b:
                continue
            kept.append(c)
            if c.score >= threshold:
                used_a.add(c.left)
                used_b.add(c.right)
        cands = kept
    return cands[:limit], info


def evaluate(cands: list[LinkCandidate], gold: set[tuple[str, str]], threshold: float = 0.5) -> dict:
    """Precision/recall against the *transitive closure* of the gold links.

    owl:sameAs is transitive: with gold a=b and b=c, predicting a=c is correct, not a false positive.
    """
    import networkx as nx

    G = nx.Graph()
    G.add_edges_from(gold)
    closure = {frozenset((x, y)) for comp in nx.connected_components(G) for x in comp for y in comp if x < y}
    nodes = {c.left for c in cands} | {c.right for c in cands}
    pred = {frozenset((c.left, c.right)) for c in cands if c.score >= threshold}
    tp = len(pred & closure)
    relevant = {p for p in closure if p <= nodes}  # gold pairs between the two KGs that were compared
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(relevant) if relevant else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"predicted": len(pred), "gold": len(relevant), "true_positives": tp,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
