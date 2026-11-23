"""KG2Analyzer: the single entry point (developer-facing interface).

    az = KG2Analyzer()
    az.ingest_paths(["my_kgs/"])                          # every KG -> MDKG, identity links discovered
    az.cross_cube(("retail", "customer", "saleTotalAmount"),
                  ("finance", "trader", "tradeAmount"))   # pushdown, Cartesian-safe
    az.communities("identity")
    az.ask("Show total retail sales and investment trade volume for our shared corporate clients")
"""
from __future__ import annotations

import io
import time
from dataclasses import asdict
from pathlib import Path

import networkx as nx
from rdflib import Graph, URIRef
from rdflib.namespace import OWL

from kg2analyzer import planner
from kg2analyzer.catalog import Catalog
from kg2analyzer.graphml import detect_communities, entity_graph
from kg2analyzer.ingest import RdfFile, group, read_paths
from kg2analyzer.kg2md.measures import MeasureClassifier
from kg2analyzer.kg2md.pipeline import KG2MDResult, run_kg2md
from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.linking import discover_links, evaluate
from kg2analyzer.nl.interface import Answer, NLInterface
from kg2analyzer.nl.translators import OllamaTranslator, OpenAICompatibleTranslator, Translator
from kg2analyzer.olap import Axis, Filter, OlapResult, rollup
from kg2analyzer.store import MultiKGStore, data_graph, schema_graph

FORMATS = {".ttl": "turtle", ".nt": "nt", ".n3": "n3", ".rdf": "xml", ".owl": "xml", ".xml": "xml",
           ".jsonld": "json-ld", ".nq": "nquads", ".trig": "trig"}


class KG2Analyzer:
    def __init__(self, models_dir: str | Path | None = None, translator: Translator | str | None = None):
        self.store = MultiKGStore()
        self.results: dict[str, KG2MDResult] = {}
        self.raw: dict[str, Graph] = {}
        self._classifier: MeasureClassifier | None = None
        self._models_dir = models_dir
        self._catalog: Catalog | None = None
        self._translator_spec = translator
        self._nl: NLInterface | None = None
        self.last_report: dict = {}
        self._suggestions: list[str] | None = None

    # ---------------------------------------------------------------- loading / Phase I
    @property
    def classifier(self) -> MeasureClassifier:
        if self._classifier is None:
            self._classifier = MeasureClassifier(self._models_dir)
        return self._classifier

    def load_kg(self, name: str, source: Graph | str | Path | bytes, fmt: str | None = None,
                materialize: bool = True, max_facts: int | None = None) -> KG2MDResult | None:
        """Load a raw KG (Graph, file path, or RDF text) and run KG2MD on it."""
        name = _slug(name)
        g = _as_graph(source, fmt)
        self.raw[name] = g
        if not materialize:
            self.store.put(name, data_graph(name), g)
            self._invalidate()
            return None
        res = run_kg2md(g, classifier=self.classifier, max_facts=max_facts)
        self.results[name] = res
        self.store.put(name, schema_graph(name), res.schema)
        self.store.put(name, data_graph(name), res.data)
        self._invalidate()
        return res

    # ---------------------------------------------------------------- batch pipeline
    def ingest(self, files: list[RdfFile], auto_link: bool = True, link_threshold: float = 0.6,
               reset: bool = False, max_facts: int | None = None) -> dict:
        """A delivery of raw KGs -> one MDKG per KG -> identity graph (supplied and/or discovered).

        ``files`` may mix single-file KGs, TBox/ABox pairs, per-KG folders, zip archives and
        owl:sameAs files (see ``kg2analyzer.ingest``). Returns a JSON-ready pipeline report.
        """
        t0 = time.perf_counter()
        kgs, identity_files = group(files)
        if not kgs:
            raise ValueError("no RDF knowledge graphs found in the upload")
        if reset:
            for kg in list(self.store.sources):
                self.remove_kg(kg)
            self.store.identity.remove((None, None, None))
        t_parse = time.perf_counter()
        report_kgs = []
        for name, (g, paths) in kgs.items():
            res = self.load_kg(name, g, max_facts=max_facts)
            report_kgs.append({
                "kg": name, "files": paths, "triples": len(g), "otsu_threshold": round(res.selection.threshold, 4),
                "classes": len(res.profiles),
                "cubes": [{"fact_class": local_name(c.fact_class), "dataset": str(c.dataset),
                           "observations": c.observations, "measures": len(c.measures), "dimensions": len(c.dimensions),
                           "fact_preservation": c.audit["fact_preservation"], "measure_fidelity": c.audit["measure_fidelity"]}
                          for c in res.cubes],
            })
        t_mdkg = time.perf_counter()
        supplied = sum(self.load_identity(g) for _, g in identity_files)
        pairs, added = [], 0
        if auto_link:
            names = sorted(self.results)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    out = self.discover_links(a, b, threshold=link_threshold)
                    new = [(c["left"], c["right"]) for c in out["candidates"] if c["score"] >= link_threshold and not c["known"]]
                    self.add_links(new)
                    added += len(new)
                    if new:
                        pairs.append({"kg_a": a, "kg_b": b, "links": [
                            {"left": c["left"], "right": c["right"], "left_label": c["left_label"],
                             "right_label": c["right_label"], "score": c["score"]}
                            for c in out["candidates"] if (c["left"], c["right"]) in new]})
        t_link = time.perf_counter()
        self.last_report = {
            "kgs": report_kgs,
            "identity": {"supplied_files": [p for p, _ in identity_files], "supplied_links": supplied,
                         "auto_link": auto_link, "threshold": link_threshold, "links_added": added, "pairs": pairs,
                         "clusters": len(set(self.store.identity_clusters().values()))},
            "named_graphs": len([g for g in self.store.graph_stats() if g["triples"]]),
            "seconds": {"parse": round(t_parse - t0, 3), "kg2md": round(t_mdkg - t_parse, 3),
                        "linking": round(t_link - t_mdkg, 3), "total": round(t_link - t0, 3)},
        }
        return self.last_report

    def ingest_paths(self, paths: list[str | Path], **kw) -> dict:
        """``ingest`` from files, folders or zip archives on disk."""
        return self.ingest(read_paths(paths), **kw)

    def mdkg_trig(self, kg: str) -> str:
        """One KG's MDKG (QB4OLAP schema graph + observation graph) as TriG."""
        ep = self.store.sources.get(kg)
        if ep is None or not hasattr(ep, "dataset"):
            raise KeyError(f"no local MDKG for {kg!r}")
        return ep.dataset.serialize(format="trig")

    def mdkg_zip(self) -> bytes:
        """All MDKGs (one TriG each), the identity graph and the last pipeline report, zipped."""
        import json
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for kg in self.results:
                z.writestr(f"{kg}.mdkg.trig", self.mdkg_trig(kg))
            z.writestr("identity.ttl", self.store.identity.serialize(format="turtle"))
            z.writestr("report.json", json.dumps(getattr(self, "last_report", {}) or {}, indent=2, default=str))
        return buf.getvalue()

    def attach_remote(self, name: str, url: str) -> None:
        """Register a remote SPARQL endpoint as a federated source (its schema graph must follow KG2MD's layout)."""
        self.store.attach_remote(_slug(name), url)
        self._invalidate()

    def load_identity(self, source: Graph | str | Path | bytes, fmt: str | None = None) -> int:
        g = _as_graph(source, fmt)
        n = 0
        for a, _, b in g.triples((None, OWL.sameAs, None)):
            self.store.add_identity(str(a), str(b))
            n += 1
        self._invalidate()
        return n

    def add_links(self, pairs: list[tuple[str, str]]) -> int:
        for a, b in pairs:
            self.store.add_identity(a, b)
        self._invalidate()
        return len(pairs)

    def remove_kg(self, name: str) -> None:
        self.store.remove_kg(name)
        self.results.pop(name, None)
        self.raw.pop(name, None)
        self._invalidate()

    def _invalidate(self):
        self._catalog = None
        self._nl = None
        self._suggestions = None

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            self._catalog = Catalog.build(self.store)
        return self._catalog

    # ---------------------------------------------------------------- Phase II
    def sparql(self, query: str, kg: str | None = None) -> dict:
        from kg2analyzer.nl.validator import MUTATION, SERVICE, _strip_literals

        if MUTATION.search(_strip_literals(query)):
            raise PermissionError("the store is read-only: update verbs are rejected")
        if SERVICE.search(_strip_literals(query)) and kg is None:
            raise PermissionError("SERVICE is disabled on the integrated store; use federated mode")
        out = self.store.query(query, kg)
        return {"columns": out.vars, "rows": out.rows, "seconds": round(out.seconds, 4)}

    def cross_cube(self, left: tuple[str, str, str], right: tuple[str, str, str], link: str = "identity",
                   strategy: str = "pushdown", mode: str = "integrated") -> planner.CrossCubeResult:
        """left/right = (kg, entity dimension, measure) using short names or IRIs."""
        q = planner.CrossCubeQuery(planner.side_from_catalog(self.catalog, *left),
                                   planner.side_from_catalog(self.catalog, *right), link)
        return planner.execute(self.store, q, strategy, mode)

    def compare_strategies(self, left, right, link: str = "identity") -> dict:
        """Naive vs pushdown, integrated vs federated: the Query-23 audit in one call."""
        out = {}
        for mode in ("integrated", "federated"):
            for strat in ("naive", "pushdown"):
                r = self.cross_cube(left, right, link, strat, mode)
                out[f"{mode}/{strat}"] = asdict(r)
        return out

    def olap(self, kg: str, measure: str, group_by: list[tuple[str, str | None]] | None = None,
             filters: list[tuple[str, str, str | None]] | None = None, aggregate: str | None = None) -> OlapResult:
        return rollup(self.store, self.catalog, kg, measure,
                      [Axis(d, lv) for d, lv in (group_by or [])],
                      [Filter(d, v, lv) for d, v, lv in (filters or [])], aggregate)

    # ---------------------------------------------------------------- graph analytics
    def _graphs(self, kgs: list[str] | None = None) -> dict[str, Graph]:
        out = {}
        for kg in kgs or list(self.store.sources):
            ep = self.store.sources.get(kg)
            if ep is not None and hasattr(ep, "dataset"):
                out[kg] = ep.dataset.graph(data_graph(kg))
        return out

    def _kg_of(self, iri: str) -> str:
        for c in self.catalog.cubes:
            if iri.startswith(self.catalog.prefixes[_prefix(c.kg)]):
                return c.kg
        return "?"

    def projection(self, kind: str = "identity", kgs: list[str] | None = None) -> nx.Graph:
        if kind == "identity":
            labels = {}
            for g in self._graphs().values():
                for s, o in g.subject_objects(URIRef("http://www.w3.org/2000/01/rdf-schema#label")):
                    labels[str(s)] = str(o)
            G = nx.Graph()
            for a, _, b in self.store.identity.triples((None, OWL.sameAs, None)):
                for x in (str(a), str(b)):
                    G.add_node(x, kg=self._kg_of(x), label=labels.get(x), literals=set(), observation=False)
                if str(a) != str(b):
                    G.add_edge(str(a), str(b), kind="sameAs")
            return G
        if kind == "members":
            return entity_graph(self._graphs(kgs), self.store.identity, members_only=True)
        if kind == "entities":
            return entity_graph(self._graphs(kgs), self.store.identity)
        raise ValueError("projection must be identity | members | entities")

    def communities(self, projection: str = "identity", algorithm: str = "greedy_modularity",
                    kgs: list[str] | None = None, k: int | None = None) -> dict:
        G = self.projection(projection, kgs)
        rep = detect_communities(G, algorithm, projection, k=k)
        d = asdict(rep)
        d["graph"] = graph_json(G, rep.communities)
        return d

    def discover_links(self, kg_a: str, kg_b: str, threshold: float = 0.5) -> dict:
        G = entity_graph(self._graphs([kg_a, kg_b]), members_only=True)
        known = {(str(a), str(b)) for a, _, b in self.store.identity.triples((None, OWL.sameAs, None))
                 if str(a) in G and str(b) in G and G.nodes[str(a)]["kg"] == kg_a and G.nodes[str(b)]["kg"] == kg_b}
        cands, info = discover_links(G, kg_a, kg_b, known=known, threshold=threshold)
        out = {"kg_a": kg_a, "kg_b": kg_b, "threshold": threshold, "model": info,
               "candidates": [asdict(c) for c in cands]}
        if known:
            out["evaluation_vs_identity_graph"] = evaluate(cands, known, threshold)
        return out

    # ---------------------------------------------------------------- Phase III
    @property
    def nl(self) -> NLInterface:
        if self._nl is None:
            self._nl = NLInterface(self.store, self.catalog, _make_translator(self._translator_spec))
        return self._nl

    def set_translator(self, spec: Translator | str | None) -> str:
        self._translator_spec = spec
        self._nl = None
        return self.nl.translator.name

    def ask(self, question: str) -> Answer:
        return self.nl.ask(question)

    def suggest_questions(self, limit: int = 6) -> list[str]:
        """Example questions built from the loaded MDKGs' own vocabulary.

        Each candidate is run through the grounded parser and the four validation rules (nothing is
        executed), and only those that pass are returned, so every suggestion is answerable.
        """
        import re

        from kg2analyzer.nl.interface import expand_aliases

        if self._suggestions is not None:
            return self._suggestions[:limit]
        cat = self.catalog
        if not cat.cubes:
            return []

        def words(iri: str) -> str:
            return re.sub(r"[_\-]+", " ", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", local_name(iri))).lower()

        def measure(c, additive=True):
            return next((m for m in c.measures if (m.additivity == "additive") == additive), None)

        candidates: list[str] = []
        for c in cat.cubes:
            m = measure(c) or (c.measures[0] if c.measures else None)
            if m is None:
                continue
            for d in c.dimensions[:2]:
                candidates.append(f"Total {words(m.iri)} by {words(d.levels[1] if len(d.levels) > 1 else d.levels[0])} in {c.kg}")
            na = measure(c, additive=False)
            if na and c.dimensions:
                candidates.append(f"Average {words(na.iri)} per {words(c.dimensions[0].prop)} in {c.kg}")
        if len(self.store.identity):
            for i, a in enumerate(cat.cubes):
                for b in cat.cubes[i + 1:]:
                    ma, mb = measure(a), measure(b)
                    if ma and mb:
                        candidates.append(f"Total {a.kg} {words(ma.iri)} and {b.kg} {words(mb.iri)} for shared entities")
        parser, validator = self.nl.parser, self.nl.validator
        ok, seen_kinds = [], set()
        for q in candidates:
            sparql = parser.translate(q)
            if not sparql:
                continue
            sparql = expand_aliases(sparql, cat)
            if not all(c.ok for c in validator.validate(sparql, q)) or not self.store.query(sparql).rows:
                continue  # invalid, or valid but empty (e.g. two KGs with no entity in common)
            kind = ("join" if " and " in q else "avg" if q.startswith("Average") else "total", parser.last_trace.cubes[0])
            if kind in seen_kinds:
                continue  # variety: one question of each kind per KG
            seen_kinds.add(kind)
            ok.append(q)
        joins = [q for q in ok if " and " in q][:2]
        self._suggestions = joins + [q for q in ok if " and " not in q]
        return self._suggestions[:limit]

    # ---------------------------------------------------------------- reporting
    def phase1_report(self, kg: str) -> dict:
        res = self.results[kg]
        sel = res.selection
        return {
            "kg": kg,
            "closure_added_triples": res.closure_added,
            "scorer": sel.scorer,
            "otsu_threshold": round(sel.threshold, 6),
            "otsu_curve": [(round(t, 4), round(v, 6)) for t, v in sel.curve],
            "classes": sorted([{
                "iri": str(p.iri), "label": p.label, "instances": p.instance_count,
                "probability": round(sel.scores.get(p.iri, 0.0), 4),
                "selected": p.iri in sel.selected,
                "features": p.features(),
                "contributions": {k: round(v, 3) for k, v in sel.contributions.get(p.iri, {}).items()},
            } for p in res.profiles], key=lambda c: -c["probability"]),
            "cubes": [{
                "fact_class": str(c.fact_class), "dataset": str(c.dataset), "label": c.label,
                "observations": c.observations, "audit": c.audit,
                "measures": [{"iri": str(m.iri), "name": local_name(m.iri), "unit": m.unit, "datatype": m.datatype,
                              "additivity": m.decision.additivity, "p_additive": m.decision.additive_probability,
                              "aggregate": m.aggregate, "shap": m.decision.shap, "lime": m.decision.lime}
                             for m in c.measures],
                "dimensions": [{"prop": str(d.prop), "name": local_name(d.prop), "base_level": local_name(d.base_level),
                                "kinds": d.kinds, "paths": [[local_name(x) for x in p] for p in d.paths],
                                "steps": [{"child": local_name(s.child), "parent": local_name(s.parent),
                                           "prop": local_name(s.prop), "coverage": round(s.coverage, 3),
                                           "many_to_many": s.many_to_many} for s in d.steps]}
                               for d in c.dimensions],
            } for c in res.cubes],
        }

    def export_nquads(self) -> str:
        return self.store.integrated.serialize(format="nquads")


def graph_json(G: nx.Graph, communities: list[dict] | None = None, max_nodes: int = 600) -> dict:
    comm_of = {}
    for c in communities or []:
        for m in c["members"]:
            comm_of[m["iri"]] = c["id"]
    nodes = list(G.nodes)[:max_nodes]
    keep = set(nodes)
    return {
        "nodes": [{"id": n, "label": G.nodes[n].get("label") or local_name(n), "kg": G.nodes[n].get("kg"),
                   "community": comm_of.get(n), "observation": G.nodes[n].get("observation", False)} for n in nodes],
        "edges": [{"source": a, "target": b, "kind": d.get("kind", "link")} for a, b, d in G.edges(data=True)
                  if a in keep and b in keep],
        "truncated": G.number_of_nodes() > max_nodes,
    }


def _slug(name: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "", name.lower())
    if not s:
        raise ValueError("KG name must contain letters or digits")
    return s


def _prefix(kg: str) -> str:
    from kg2analyzer.catalog import alias_prefix

    return alias_prefix(kg)


def _as_graph(source, fmt: str | None) -> Graph:
    if isinstance(source, Graph):
        return source
    g = Graph()
    if isinstance(source, (bytes, bytearray)):
        g.parse(data=source.decode("utf-8"), format=fmt or "turtle")
    elif isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).exists()):
        p = Path(source)
        g.parse(p, format=fmt or FORMATS.get(p.suffix.lower(), "turtle"))
    else:
        g.parse(data=str(source), format=fmt or "turtle")
    return g


def _make_translator(spec) -> Translator | None:
    import os

    if spec is None:
        spec = os.environ.get("KG2A_TRANSLATOR", "auto")
    if not isinstance(spec, str):
        return spec
    if spec in ("rules", "grounded", "grounded-parser"):
        return None
    if spec == "openai":
        return OpenAICompatibleTranslator()
    if spec.startswith("ollama"):
        model = spec.split(":", 1)[1] if ":" in spec else None
        return OllamaTranslator(model)
    if spec == "auto":
        o = OllamaTranslator()
        return o if o.available() else None
    raise ValueError(f"unknown translator {spec!r}")
