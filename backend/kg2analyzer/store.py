"""Source-aware multi-KG store (thesis section 3.6.2).

Every KG keeps its own *source* (an endpoint holding that KG's named graphs).
The store can answer queries two ways:

* **integrated**: all named graphs physically co-located in one RDFLib
  ``Dataset`` (default union graph + ``GRAPH ?g`` provenance);
* **federated**: each KG stays behind its own endpoint (in-process or a
  remote SPARQL 1.1 HTTP endpoint) and a mediator combines sub-results.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx
from rdflib import BNode, Dataset, Graph, Literal, URIRef
from rdflib.namespace import OWL

GRAPHS = "http://example.org/graphs/"
IDENTITY_GRAPH = URIRef(GRAPHS + "identities")


def data_graph(kg: str) -> URIRef:
    return URIRef(f"{GRAPHS}{kg}")


def schema_graph(kg: str) -> URIRef:
    return URIRef(f"{GRAPHS}{kg}/schema")


def source_graph(kg: str) -> URIRef:
    return URIRef(f"{GRAPHS}{kg}/source")


Row = dict[str, Any]


def to_py(term) -> Any:
    if term is None:
        return None
    if isinstance(term, Literal):
        v = term.toPython()
        return v if not isinstance(v, Literal) else str(v)
    return str(term)


def result_rows(result) -> tuple[list[str], list[Row]]:
    vars_ = [str(v) for v in result.vars or []]
    rows = [{v: to_py(r[v]) for v in vars_} for r in result]
    return vars_, rows


class Endpoint(Protocol):
    """A SPARQL source that answers SELECT queries."""

    name: str

    def select(self, query: str) -> tuple[list[str], list[Row]]: ...


class LocalEndpoint:
    """In-process endpoint over an RDFLib Dataset (one autonomous KG)."""

    def __init__(self, name: str, dataset: Dataset | None = None):
        self.name = name
        self.dataset = dataset if dataset is not None else Dataset(default_union=True)

    def select(self, query: str) -> tuple[list[str], list[Row]]:
        return result_rows(self.dataset.query(query))


class RemoteEndpoint:
    """SPARQL 1.1 Protocol endpoint over HTTP (e.g. Fuseki, GraphDB, Virtuoso, or another KG2Analyzer)."""

    def __init__(self, name: str, url: str, timeout: float = 30.0):
        self.name, self.url, self.timeout = name, url, timeout

    def select(self, query: str) -> tuple[list[str], list[Row]]:
        r = httpx.post(self.url, data={"query": query}, timeout=self.timeout,
                       headers={"Accept": "application/sparql-results+json"})
        r.raise_for_status()
        js = r.json()
        vars_ = js["head"]["vars"]
        rows = []
        for b in js["results"]["bindings"]:
            row = {}
            for v in vars_:
                t = b.get(v)
                if t is None:
                    row[v] = None
                elif t["type"] == "uri":
                    row[v] = t["value"]
                else:
                    dt = t.get("datatype", "")
                    val = t["value"]
                    if dt.endswith(("#decimal", "#double", "#float")):
                        row[v] = Decimal(val)
                    elif dt.endswith(("#integer", "#int", "#long")):
                        row[v] = int(val)
                    else:
                        row[v] = val
            rows.append(row)
        return vars_, rows


@dataclass
class QueryOutcome:
    vars: list[str]
    rows: list[Row]
    seconds: float


class MultiKGStore:
    """Named-graph store: one source endpoint per KG plus the identity graph."""

    def __init__(self):
        self.sources: dict[str, Endpoint] = {}
        self.identity = Graph()
        self.identity.bind("owl", OWL)
        self._integrated: Dataset | None = None

    # -- loading ----------------------------------------------------------------
    def put(self, kg: str, graph_iri: URIRef, graph: Graph) -> None:
        ep = self.sources.setdefault(kg, LocalEndpoint(kg))
        if not isinstance(ep, LocalEndpoint):
            raise ValueError(f"{kg} is a remote endpoint; it cannot hold local graphs")
        g = ep.dataset.graph(graph_iri)
        g.remove((None, None, None))
        for t in graph:
            g.add(t)
        for prefix, uri in graph.namespaces():
            ep.dataset.bind(prefix, uri, override=False)
        self._integrated = None

    def attach_remote(self, kg: str, url: str) -> None:
        self.sources[kg] = RemoteEndpoint(kg, url)
        self._integrated = None

    def add_identity(self, a: str, b: str) -> None:
        self.identity.add((URIRef(a), OWL.sameAs, URIRef(b)))
        self.identity.add((URIRef(b), OWL.sameAs, URIRef(a)))
        self._integrated = None

    def remove_kg(self, kg: str) -> None:
        self.sources.pop(kg, None)
        self._integrated = None

    # -- integrated view ----------------------------------------------------------
    @property
    def integrated(self) -> Dataset:
        """Physical integration: every local named graph + the identity graph in one Dataset."""
        if self._integrated is None:
            ds = Dataset(default_union=True)
            for ep in self.sources.values():
                if isinstance(ep, LocalEndpoint):
                    for prefix, uri in ep.dataset.namespaces():
                        ds.bind(prefix, uri, override=False)
                    for ctx in ep.dataset.graphs():
                        if isinstance(ctx.identifier, BNode) or str(ctx.identifier).startswith("urn:x-rdflib:"):
                            continue
                        tgt = ds.graph(ctx.identifier)
                        for t in ctx:
                            tgt.add(t)
            idg = ds.graph(IDENTITY_GRAPH)
            for t in self.identity:
                idg.add(t)
            ds.bind("owl", OWL)
            self._integrated = ds
        return self._integrated

    def graph_stats(self) -> list[dict]:
        out = []
        for kg, ep in self.sources.items():
            if isinstance(ep, LocalEndpoint):
                for ctx in ep.dataset.graphs():
                    if str(ctx.identifier).startswith(GRAPHS):
                        out.append({"kg": kg, "graph": str(ctx.identifier), "triples": len(ctx)})
            else:
                out.append({"kg": kg, "graph": ep.url, "triples": None, "remote": True})
        out.append({"kg": "_identity", "graph": str(IDENTITY_GRAPH), "triples": len(self.identity)})
        return out

    def query(self, sparql: str, kg: str | None = None) -> QueryOutcome:
        """Run SELECT over the integrated dataset, or over one KG's own endpoint."""
        t0 = time.perf_counter()
        if kg is None:
            vars_, rows = result_rows(self.integrated.query(sparql))
        else:
            vars_, rows = self.sources[kg].select(sparql)
        return QueryOutcome(vars_, rows, time.perf_counter() - t0)

    def identity_clusters(self) -> dict[str, int]:
        """Union-find over owl:sameAs: entity IRI -> cluster id (transitive, symmetric)."""
        parent: dict[str, str] = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, _, b in self.identity.triples((None, OWL.sameAs, None)):
            ra, rb = find(str(a)), find(str(b))
            if ra != rb:
                parent[ra] = rb
        roots = {}
        return {x: roots.setdefault(find(x), len(roots)) for x in list(parent)}
