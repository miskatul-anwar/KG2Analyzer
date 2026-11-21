"""Graph learning over KGs: entity graphs, SGC graph-neural embeddings, community detection.

The embedding is a Simplified Graph Convolution (Wu et al., ICML 2019):
X_k = A_hat^k X with A_hat = D^-1/2 (A + I) D^-1/2 and X a hashed bag of the
entity's label/literal tokens. It is the linear core of a GCN, needs no
labels or GPU, and is fully inspectable, which suits auditable pipelines
(thesis section 2.1.5).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import networkx as nx
import numpy as np
from networkx.algorithms import community as nxc
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from scipy import sparse

QB_DATASET = URIRef("http://purl.org/linked-data/cube#dataSet")
QB4O_MEMBER_OF = URIRef("http://purl.org/qb4olap/cubes#memberOf")
SKIP = {RDF.type, QB_DATASET, QB4O_MEMBER_OF}


def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def entity_graph(graphs: dict[str, Graph], identity: Graph | None = None, members_only: bool = False) -> nx.Graph:
    """Undirected entity graph across KGs. Node attrs: kg, label, literals (set of str), observation flag."""
    G = nx.Graph()

    def node(iri, kg, obs):
        key = str(iri)
        if key not in G:
            G.add_node(key, kg=kg, kgs={kg}, label=None, literals=set(), observation=obs)
        else:
            G.nodes[key]["kgs"].add(kg)
        return G.nodes[key]

    for kg, g in graphs.items():
        observations = set(g.subjects(QB_DATASET, None))
        for s, p, o in g:
            if not isinstance(s, URIRef):
                continue
            if members_only and s in observations:
                continue
            n = node(s, kg, s in observations)
            if p == RDFS.label:
                n["label"] = str(o)
            elif isinstance(o, Literal):
                n["literals"].add(str(o))
            elif isinstance(o, URIRef) and p not in SKIP:
                if members_only and o in observations:
                    continue
                node(o, kg, o in observations)
                G.add_edge(str(s), str(o), predicate=str(p), kind="link")
    for _, d in G.nodes(data=True):
        d["shared"] = len(d["kgs"]) > 1  # conformed members (same IRI in several KGs): no linking needed
    if identity is not None:
        for a, _, b in identity.triples((None, OWL.sameAs, None)):
            for x in (a, b):
                if str(x) not in G:
                    G.add_node(str(x), kg="?", kgs=set(), label=None, literals=set(), observation=False, shared=False)
            G.add_edge(str(a), str(b), predicate=str(OWL.sameAs), kind="sameAs")
    return G


def hashed_features(G: nx.Graph, nodes: list[str], dim: int = 512) -> np.ndarray:
    X = np.zeros((len(nodes), dim))
    for i, n in enumerate(nodes):
        attrs = G.nodes[n]
        toks = tokens(attrs.get("label") or "") * 2
        for lit in attrs.get("literals", ()):
            toks += tokens(lit) + ["lit:" + lit.lower()]
        for t in toks:
            h = int(hashlib.md5(t.encode()).hexdigest(), 16)
            X[i, h % dim] += 1 if (h >> 64) & 1 else -1
    norm = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.where(norm == 0, 1, norm)


def sgc_embeddings(G: nx.Graph, k: int = 2, dim: int = 512, nodes: list[str] | None = None) -> tuple[list[str], np.ndarray]:
    nodes = nodes or list(G.nodes)
    X = hashed_features(G, nodes, dim)
    A = nx.to_scipy_sparse_array(G, nodelist=nodes, format="csr", dtype=float)
    A = A + sparse.identity(len(nodes), format="csr")
    d = np.asarray(A.sum(axis=1)).ravel()
    Dm = sparse.diags(1 / np.sqrt(d))
    A_hat = Dm @ A @ Dm
    H = X
    for _ in range(k):
        H = A_hat @ H
    norm = np.linalg.norm(H, axis=1, keepdims=True)
    return nodes, H / np.where(norm == 0, 1, norm)


@dataclass
class CommunityReport:
    algorithm: str
    projection: str
    modularity: float
    communities: list[dict]
    nodes: int
    edges: int


def detect_communities(G: nx.Graph, algorithm: str = "greedy_modularity", projection: str = "", seed: int = 7,
                       k: int | None = None) -> CommunityReport:
    if G.number_of_nodes() == 0:
        return CommunityReport(algorithm, projection, 0.0, [], 0, 0)
    if algorithm == "greedy_modularity":
        parts = nxc.greedy_modularity_communities(G)
    elif algorithm == "louvain":
        parts = nxc.louvain_communities(G, seed=seed)
    elif algorithm == "label_propagation":
        parts = list(nxc.asyn_lpa_communities(G, seed=seed))
    elif algorithm == "sgc_kmeans":
        parts = _sgc_kmeans(G, k, seed)
    else:
        raise ValueError(f"unknown algorithm {algorithm!r}")
    parts = [set(p) for p in parts if p]
    q = nxc.modularity(G, parts) if G.number_of_edges() else 0.0
    comms = []
    for i, p in enumerate(sorted(parts, key=lambda s: (-len(s), sorted(s)[0]))):
        kgs: dict[str, int] = {}
        for n in p:
            kg = G.nodes[n].get("kg", "?")
            kgs[kg] = kgs.get(kg, 0) + 1
        comms.append({
            "id": i, "size": len(p), "kgs": kgs, "cross_kg": len(kgs) > 1,
            "members": [{"iri": n, "label": G.nodes[n].get("label"), "kg": G.nodes[n].get("kg")} for n in sorted(p)][:200],
        })
    return CommunityReport(algorithm, projection, round(q, 4), comms, G.number_of_nodes(), G.number_of_edges())


def _sgc_kmeans(G: nx.Graph, k: int | None, seed: int):
    """GNN-based clustering: SGC embeddings + k-means, k picked by modularity when not given."""
    from sklearn.cluster import KMeans

    nodes, H = sgc_embeddings(G, k=3)
    candidates = [k] if k else sorted({max(2, int(np.sqrt(len(nodes) / 2)) + d) for d in (-2, -1, 0, 1, 2)})
    best, best_q = None, -2.0
    for kk in candidates:
        if kk >= len(nodes):
            continue
        labels = KMeans(n_clusters=kk, n_init=10, random_state=seed).fit_predict(H)
        parts = [{nodes[i] for i in np.where(labels == c)[0]} for c in range(kk)]
        parts = [p for p in parts if p]
        q = nxc.modularity(G, parts) if G.number_of_edges() else 0
        if q > best_q:
            best, best_q = parts, q
    return best or [set(nodes)]
