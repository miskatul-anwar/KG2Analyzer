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
from kg2analyzer.ingest import KgInput, RdfFile, group, read_paths
from kg2analyzer.kg2md.measures import MeasureClassifier
from kg2analyzer.kg2md.pipeline import KG2MDResult, run_kg2md
from kg2analyzer.kg2md.profiling import local_name
from kg2analyzer.linking import discover_links, evaluate
from kg2analyzer.mdkg_files import HINT, Mdkg, read_mdkgs, with_member_descriptions
from kg2analyzer.nl.interface import Answer, NLInterface
from kg2analyzer.nl.translators import OllamaTranslator, OpenAICompatibleTranslator, Translator
from kg2analyzer.olap import Axis, Filter, OlapResult, rollup
from kg2analyzer.store import MultiKGStore, data_graph, schema_graph, source_graph

_STANDARD_NS = ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "http://www.w3.org/2000/01/rdf-schema#",
                "http://www.w3.org/2002/07/owl#", "http://www.w3.org/2001/XMLSchema#")
FORMATS = {".ttl": "turtle", ".nt": "nt", ".n3": "n3", ".rdf": "xml", ".owl": "xml", ".xml": "xml",
           ".jsonld": "json-ld", ".nq": "nquads", ".trig": "trig"}


class KG2Analyzer:
    def __init__(self, models_dir: str | Path | None = None, translator: Translator | str | None = None,
                 decider=None):
        """``decider`` answers KG2MD's four questions (default: Tev1, see ``kg2md.notebook.default_decider``)."""
        self.store = MultiKGStore()
        self.decider = decider
        self.runs: dict[str, dict] = {}                 # kg -> KG2MD notebook run (decisions, log, timings)
        self.mdkg_raw: dict[str, dict[str, bytes]] = {}  # kg -> the MDKG files, path -> bytes
        self._audits: dict[tuple[str, str], dict] = {}
        self.results: dict[str, KG2MDResult] = {}
        self.raw: dict[str, Graph] = {}
        self._classifier: MeasureClassifier | None = None
        self._models_dir = models_dir
        self._catalog: Catalog | None = None
        self._translator_spec = translator
        self._nl: NLInterface | None = None
        self.last_report: dict = {}
        self.inputs: dict[str, dict] = {}  # kg -> {"tbox_files": [...], "abox_files": [...]}
        self._suggestions: list[str] | None = None

    # ---------------------------------------------------------------- loading / Phase I
    @property
    def classifier(self) -> MeasureClassifier:
        if self._classifier is None:
            self._classifier = MeasureClassifier(self._models_dir)
        return self._classifier

    def load_kg(self, name: str, source: Graph | str | Path | bytes, fmt: str | None = None,
                materialize: bool = True, max_facts: int | None = None,
                tbox: Graph | str | Path | bytes | None = None) -> KG2MDResult | None:
        """Load a raw KG and run KG2MD on it. ``source`` is the ABox when ``tbox`` is given,
        otherwise a combined KG (Graph, file path, or RDF text)."""
        name = _slug(name)
        g = _as_graph(source, fmt)
        tb = _as_graph(tbox, fmt) if tbox is not None else None
        self.raw[name] = g
        self.inputs.setdefault(name, {"tbox_files": [], "abox_files": []})
        if not materialize:
            self.store.put(name, data_graph(name), g)
            self._invalidate()
            return None
        res = run_kg2md(g, classifier=self.classifier, max_facts=max_facts, tbox=tb)
        self.results[name] = res
        self.store.put(name, schema_graph(name), res.schema)
        self.store.put(name, data_graph(name), res.data)
        self._invalidate()
        return res

    # ---------------------------------------------------------------- batch pipeline
    def ingest(self, files: list[RdfFile], auto_link: bool = True, link_threshold: float = 0.6,
               reset: bool = False, max_facts: int | None = None, engine: str = "notebook",
               env: dict[str, str] | None = None, decider: str | None = None) -> dict:
        """A delivery of raw KGs -> one MDKG per KG -> identity graph (supplied and/or discovered).

        ``files`` may mix single-file KGs, TBox/ABox pairs, per-KG folders, zip archives and
        owl:sameAs files (see ``kg2analyzer.ingest``). Returns a JSON-ready pipeline report.
        ``engine="notebook"`` (default) runs the KG2MD notebook on each KG; ``"builtin"`` runs the
        thesis-era reimplementation (``run_kg2md``). ``env`` passes KG2MD_* options to the notebook.
        ``decider`` is ``"tev1"`` or ``"structural"`` for this build (default: the analyzer's decider / KG2A_DECIDER).
        """
        if engine not in ("notebook", "builtin"):
            raise ValueError("engine must be notebook or builtin")
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
        for name, kg in kgs.items():
            if engine == "notebook":
                self.build_mdkg(name, kg, env, decider)
            else:
                self.load_kg(name, kg.abox, max_facts=max_facts, tbox=kg.tbox)
            self.inputs[name] = {"tbox_files": kg.tbox_files, "abox_files": kg.abox_files}
            report_kgs.append(self._kg_summary(name))
        t_mdkg = time.perf_counter()
        supplied = sum(self.load_identity(g) for _, g in identity_files)
        pairs, added = self._auto_link(link_threshold) if auto_link else ([], 0)
        t_link = time.perf_counter()
        if not reset:  # adding to an existing set: keep earlier KGs in the report
            new_names = {k["kg"] for k in report_kgs}
            report_kgs = [k for k in (self.last_report or {}).get("kgs", [])
                          if k["kg"] in self._built() and k["kg"] not in new_names] + report_kgs
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

    def _auto_link(self, threshold: float) -> tuple[list[dict], int]:
        """Discover owl:sameAs links between every pair of local MDKGs; add those scoring >= threshold."""
        names = sorted(k for k, ep in self.store.sources.items() if hasattr(ep, "dataset"))
        pairs, added = [], 0
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                out = self.discover_links(a, b, threshold=threshold)
                new = [(c["left"], c["right"]) for c in out["candidates"] if c["score"] >= threshold and not c["known"]]
                self.add_links(new)
                added += len(new)
                if new:
                    pairs.append({"kg_a": a, "kg_b": b, "links": [
                        {"left": c["left"], "right": c["right"], "left_label": c["left_label"],
                         "right_label": c["right_label"], "score": c["score"]}
                        for c in out["candidates"] if (c["left"], c["right"]) in new]})
        return pairs, added

    def build_mdkg(self, name: str, kg: KgInput, env: dict[str, str] | None = None, decider: str | None = None) -> dict:
        """Run the KG2MD notebook on one KG's TBox + ABox and host the MDKG it writes."""
        from kg2analyzer.kg2md.notebook import resolve_decider, run_notebook

        chosen = resolve_decider(decider) if decider else (self.decider or resolve_decider(None))
        run = run_notebook(kg.turtle("tbox"), kg.turtle("abox"), decider=chosen, env=env)
        files = [RdfFile(f"{name}/{p}", b) for p, b in run.files.items()]
        if name in self.store.sources:
            self.remove_kg(name)
        if run.summary.get("cubes"):
            mdkgs, _ = read_mdkgs(files)  # the same reader Query and Ask use
            self._put_mdkg(mdkgs[name])
        self.mdkg_raw[name] = {f.path: f.data for f in files}
        self.runs[name] = {**run.summary, "decider": run.decider, "seconds": run.seconds, "log": run.log}
        self._invalidate()
        return self.runs[name]

    def _put_mdkg(self, m: Mdkg) -> None:
        self.store.put(m.name, schema_graph(m.name), m.schema)
        self.store.put(m.name, data_graph(m.name), with_member_descriptions(m.data, m.source))
        if len(m.source):
            self.store.put(m.name, source_graph(m.name), m.source)
        self.mdkg_raw[m.name] = dict(m.raw)
        self._invalidate()

    def _built(self) -> set[str]:
        return set(self.results) | set(self.runs)

    def load_mdkgs(self, files: list[RdfFile], auto_link: bool = True, link_threshold: float = 0.6,
                   reset: bool = False) -> dict:
        """Load MDKGs as the KG2MD notebook saves them (per KG: ``fact_classes/<cube>/mdkg_dataset.nq`` or
        ``mdkg_schema.ttl`` + ``mdkg_data.ttl``; folders or a zip) plus optional owl:sameAs files.
        Nothing is re-run: the QB4OLAP schema and data graphs are used as saved."""
        found, identity_files = read_mdkgs(files)
        if not found and not identity_files:
            raise ValueError(f"The upload {HINT}")
        if reset:
            for kg in list(self.store.sources):
                self.remove_kg(kg)
            self.store.identity.remove((None, None, None))
        for kg, m in sorted(found.items()):
            if kg in self.store.sources:
                self.remove_kg(kg)
            self._put_mdkg(m)
            self.inputs[kg] = {"mdkg_files": m.files}
        self._invalidate()
        supplied = sum(self.load_identity(g) for _, g in identity_files)
        pairs, added = self._auto_link(link_threshold) if auto_link else ([], 0)
        return {"mdkgs": self.loaded_mdkgs(),
                "identity": {"supplied_files": [p for p, _ in identity_files], "supplied_links": supplied,
                             "auto_link": auto_link, "links_added": added, "pairs": pairs,
                             "total_links": len(self.store.identity) // 2,
                             "clusters": len(set(self.store.identity_clusters().values()))}}

    def loaded_mdkgs(self) -> list[dict]:
        """The MDKGs available for querying: cubes, measures, dimensions and observation counts."""
        out = []
        for kg in sorted(k for k, ep in self.store.sources.items() if hasattr(ep, "dataset")):
            cubes = []
            for c in (c for c in self.catalog.cubes if c.kg == kg):
                n = self.store.query(f"SELECT (COUNT(?o) AS ?n) WHERE {{ GRAPH <{c.graph}> {{ ?o "
                                     f"<http://purl.org/linked-data/cube#dataSet> <{c.dataset}> }} }}").rows[0]["n"]
                cubes.append({"fact_class": c.label, "dataset": c.dataset, "observations": int(n or 0),
                              "measures": len(c.measures), "dimensions": len(c.dimensions)})
            inp = self.inputs.get(kg, {})
            out.append({"kg": kg, "files": inp.get("mdkg_files") or inp.get("abox_files") or [], "cubes": cubes})
        return out

    def _kg_summary(self, name: str) -> dict:
        """One MDKG as reported to callers: TBox/ABox inputs, Otsu threshold, cubes and audit, warnings."""
        if name in self.runs:
            return self._run_summary(name)
        res = self.results[name]
        inp = self.inputs.get(name, {"tbox_files": [], "abox_files": []})
        warnings = []
        if not res.tbox_triples:
            warnings.append("No TBox supplied: classes and properties were inferred from the ABox alone.")
        if res.undeclared_properties:
            warnings.append(f"{len(res.undeclared_properties)} ABox propert{'y is' if len(res.undeclared_properties) == 1 else 'ies are'} "
                            "not declared in the TBox (still profiled).")
        if not res.cubes:
            warnings.append("No fact class found: no class has instances that carry numeric measures and link to others.")
        return {
            "kg": name, "files": sorted(set(inp["tbox_files"]) | set(inp["abox_files"])),
            "tbox_files": inp["tbox_files"], "abox_files": inp["abox_files"],
            "tbox_triples": res.tbox_triples, "abox_triples": res.abox_triples or len(self.raw.get(name, ())),
            "triples": res.tbox_triples + (res.abox_triples or len(self.raw.get(name, ()))),
            "undeclared_properties": res.undeclared_properties, "warnings": warnings,
            "otsu_threshold": round(res.selection.threshold, 4), "classes": len(res.profiles),
            "cubes": [{"fact_class": local_name(c.fact_class), "dataset": str(c.dataset),
                       "observations": c.observations, "measures": len(c.measures), "dimensions": len(c.dimensions),
                       "fact_preservation": c.audit["fact_preservation"], "measure_fidelity": c.audit["measure_fidelity"]}
                      for c in res.cubes],
        }

    def _run_summary(self, name: str) -> dict:
        run = self.runs[name]
        inp = self.inputs.get(name, {"tbox_files": [], "abox_files": []})
        warnings = []
        if "Tev1" not in run["decider"] or "not Tev1" in run["decider"]:
            warnings.append(f"Decided by {run['decider'].replace('; not Tev1', '').replace(' (not Tev1)', '')}, not by Tev1.")
        if not run["tbox_triples"]:
            warnings.append("No TBox supplied: classes and properties were inferred from the ABox alone.")
        undeclared = [p for p in run["undeclared_properties"] if not p.startswith(_STANDARD_NS)]
        if undeclared:
            n = len(undeclared)
            warnings.append(f"{n} ABox propert{'y is' if n == 1 else 'ies are'} not declared in the TBox (still profiled).")
        if run["separated_records"]:
            warnings.append(f"{run['separated_records']} measured records that reused a subject IRI were separated (record identity).")
        if not run["cubes"]:
            warnings.append("No fact class was selected.")
        cubes = [c for c in self.catalog.cubes if c.kg == name]
        thr = run["otsu_threshold"]
        return {
            "kg": name, "files": sorted(set(inp.get("tbox_files", [])) | set(inp.get("abox_files", []))),
            "tbox_files": inp.get("tbox_files", []), "abox_files": inp.get("abox_files", []),
            "tbox_triples": run["tbox_triples"], "abox_triples": run["abox_triples"],
            "triples": run["tbox_triples"] + run["abox_triples"],
            "undeclared_properties": undeclared, "warnings": warnings,
            "otsu_threshold": round(thr, 4) if thr is not None else None, "classes": len(run["classes"]),
            "decider": run["decider"], "seconds": run["seconds"],
            "cubes": [{"fact_class": c.label, "dataset": c.dataset, "measures": len(c.measures), "dimensions": len(c.dimensions),
                       **{k: a[k] for k in ("observations", "fact_preservation", "measure_fidelity")}}
                      for c in cubes for a in [self.audit(c)]],
        }

    def audit(self, cube) -> dict:
        """Observation-to-fact audit of one loaded cube, recomputed from its own graphs: every observation
        derives from a source fact (prov:wasDerivedFrom) and carries that fact's measure values."""
        from decimal import Decimal, InvalidOperation

        from rdflib.namespace import PROV, RDF

        key = (cube.kg, cube.dataset)
        if key in self._audits:
            return self._audits[key]
        ds = self.store.sources[cube.kg].dataset
        data, src = ds.graph(data_graph(cube.kg)), ds.graph(source_graph(cube.kg))
        obs = set(data.subjects(URIRef("http://purl.org/linked-data/cube#dataSet"), URIRef(cube.dataset)))
        derived = {data.value(o, PROV.wasDerivedFrom): o for o in obs}
        derived.pop(None, None)
        out = {"observations": len(obs), "source_facts": None, "ghost_observations": None, "dropped_facts": None,
               "measure_cells_checked": 0, "measure_cells_mismatched": 0, "fact_preservation": None, "measure_fidelity": None}
        if len(src):
            msrc = {URIRef(m.iri): URIRef(m.source) for m in cube.measures if m.source}
            facts = set(src.subjects(RDF.type, URIRef(cube.fact_class)))
            if msrc:
                facts = {f for f in facts if any(src.value(f, p) is not None for p in msrc.values())}

            def nums(values):
                out = []
                for v in values:
                    try:
                        out.append(Decimal(str(v)))
                    except InvalidOperation:
                        out.append(str(v))
                return sorted(out, key=str)

            cells = bad = 0
            for f, o in derived.items():
                for m, p in msrc.items():
                    cells += 1
                    bad += nums(data.objects(o, m)) != nums(src.objects(f, p))
            out.update(source_facts=len(facts), ghost_observations=len(set(derived) - facts),
                       dropped_facts=len(facts - set(derived)), measure_cells_checked=cells, measure_cells_mismatched=bad,
                       fact_preservation=round(len(facts & set(derived)) / len(facts), 4) if facts else 1.0,
                       measure_fidelity=round(1 - bad / cells, 4) if cells else 1.0)
        self._audits[key] = out
        return out

    def overview(self) -> dict:
        """Every loaded MDKG (fact cubes, audit, input files) and the current identity links, labelled."""
        labels: dict[str, str] = {}
        for g in self._graphs().values():
            for s, o in g.subject_objects(URIRef("http://www.w3.org/2000/01/rdf-schema#label")):
                labels.setdefault(str(s), str(o))
        kgs = [self._kg_summary(name) for name in sorted(self._built())]
        pairs = sorted({tuple(sorted((str(a), str(b)))) for a, _, b in self.store.identity.triples((None, OWL.sameAs, None))
                        if str(a) != str(b)})
        links = [{"left": a, "right": b, "left_label": labels.get(a), "right_label": labels.get(b),
                  "left_kg": self._kg_of(a), "right_kg": self._kg_of(b)} for a, b in pairs]
        return {"kgs": kgs, "remote": [k for k in self.store.sources if k not in self._built()],
                "identity": {"links": links, "clusters": len(set(self.store.identity_clusters().values()))}}

    def ingest_paths(self, paths: list[str | Path], **kw) -> dict:
        """``ingest`` from files, folders or zip archives on disk."""
        return self.ingest(read_paths(paths), **kw)

    def mdkg_files(self, kg: str | None = None) -> dict[str, bytes]:
        """The MDKG files as KG2MD wrote them (``<kg>/fact_classes/<cube>/...``), plus identity.ttl."""
        out: dict[str, bytes] = {}
        for name in sorted(self.mdkg_raw):
            if kg is None or name == kg:
                out.update(self.mdkg_raw[name])
        if kg is None and len(self.store.identity):
            out["identity.ttl"] = self.store.identity.serialize(format="turtle").encode("utf-8")
        if kg is not None and not out:
            raise KeyError(f"no MDKG files for {kg!r}")
        return out

    def mdkg_zip(self) -> bytes:
        """All MDKG folders, the identity graph and the last pipeline report, zipped."""
        import json
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for path, data in self.mdkg_files().items():
                z.writestr(path, data)
            if "identity.ttl" not in self.mdkg_files():
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
        self.runs.pop(name, None)
        self.mdkg_raw.pop(name, None)
        self.raw.pop(name, None)
        self.inputs.pop(name, None)
        self._invalidate()

    def _invalidate(self):
        self._audits = {}
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

    def members(self, kg: str, dim: str, level: str | None = None, limit: int = 1000) -> list[dict]:
        """Labelled members of one level of a dimension (for filter pickers)."""
        from kg2analyzer.olap import _resolve_level

        cube = self.catalog.cube_for(kg)
        d = cube.dimension(dim) if cube else None
        if d is None:
            raise KeyError(f"unknown dimension {dim!r} in {kg!r}")
        lvl = _resolve_level(d, level)
        q = (f"SELECT DISTINCT ?m ?l WHERE {{ GRAPH <{cube.graph}> {{ {Catalog.member_pattern('m', lvl)} . "
             f"OPTIONAL {{ ?m <http://www.w3.org/2000/01/rdf-schema#label> ?l }} }} }} ORDER BY ?l ?m LIMIT {int(limit)}")
        return [{"iri": r["m"], "label": r["l"] or local_name(r["m"])} for r in self.store.query(q).rows]

    def join_options(self, kg_a: str, kg_b: str) -> list[dict]:
        """Dimension pairs on which two MDKGs can be combined, best first.

        ``identity``: members of the two dimensions fall in the same owl:sameAs cluster.
        ``shared``: the two dimensions use the same member IRIs (a conformed dimension such as a calendar).
        ``aligned`` counts the entities that would actually join.
        """
        ca, cb = self.catalog.cube_for(kg_a), self.catalog.cube_for(kg_b)
        if ca is None or cb is None:
            raise KeyError("both KGs need an MDKG")

        def used(cube, d):
            q = f"SELECT DISTINCT ?m WHERE {{ GRAPH <{cube.graph}> {{ ?o <{d.prop}> ?m }} }}"
            return {r["m"] for r in self.store.query(q).rows}

        clusters = self.store.identity_clusters()
        out = []
        for da in ca.dimensions:
            ma = used(ca, da)
            for db in cb.dimensions:
                mb = used(cb, db)
                shared = len(ma & mb)
                ids_a = {clusters[x] for x in ma if x in clusters}
                ids_b = {clusters[x] for x in mb if x in clusters}
                for link, n in (("identity", len(ids_a & ids_b)), ("shared", shared)):
                    if n:
                        out.append({"left_dim": da.prop, "right_dim": db.prop, "link": link, "aligned": n,
                                    "label": f"{da.name} ↔ {db.name} "
                                             f"({'same entity' if link == 'identity' else 'same value'}, {n} aligned)"})
        out.sort(key=lambda o: (o["link"] != "identity", -o["aligned"]))
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

        def words(name: str) -> str:
            return re.sub(r"[_\-]+", " ", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)).lower()

        def measure(c, additive=True):
            return next((m for m in c.measures if (m.additivity == "additive") == additive), None)

        candidates: list[str] = []
        for c in cat.cubes:
            m = measure(c) or (c.measures[0] if c.measures else None)
            if m is None:
                continue
            for d in c.dimensions[:2]:
                verb = "Total" if m.additivity == "additive" else "Average"
                candidates.append(f"{verb} {words(m.label)} by {words(d.level_name(d.levels[1] if len(d.levels) > 1 else d.levels[0]))} in {c.kg}")
            na = measure(c, additive=False)
            if na and c.dimensions:
                candidates.append(f"Average {words(na.label)} per {words(c.dimensions[0].name)} in {c.kg}")
        if len(self.store.identity):
            for i, a in enumerate(cat.cubes):
                for b in cat.cubes[i + 1:]:
                    ma, mb = measure(a), measure(b)
                    if ma and mb:
                        candidates.append(f"Total {a.kg} {words(ma.label)} and {b.kg} {words(mb.label)} for shared entities")
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
        if kg in self.runs:
            return self._run_report(kg)
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

    def _run_report(self, kg: str) -> dict:
        """Every decision the KG2MD notebook made for one KG, and what it built."""
        run = self.runs[kg]
        agg_decisions = {str(d["profile"].get("measure_name", "")).lower(): d
                         for d in run["decisions"] if d["question"] == "aggregate"}
        cubes = []
        for c in (c for c in self.catalog.cubes if c.kg == kg):
            built = next((b for b in run["cubes"] if b["fact_class"] == c.fact_class), {})
            cubes.append({
                "fact_class": c.fact_class, "dataset": c.dataset, "label": c.label, "key": built.get("key"),
                "audit": self.audit(c), "observations": self.audit(c)["observations"],
                "measures": [{"iri": m.iri, "name": m.label, "unit": m.unit, "aggregate": m.aggregate,
                              "additivity": m.additivity, "source": m.source,
                              "decision": agg_decisions.get(m.label.lower())} for m in c.measures],
                "dimensions": built.get("dimensions", []),
            })
        return {"kg": kg, "decider": run["decider"], "seconds": run["seconds"],
                "otsu_threshold": run["otsu_threshold"], "classes": run["classes"], "cubes": cubes,
                "decisions": run["decisions"], "undeclared_properties": run["undeclared_properties"],
                "separated_records": run["separated_records"], "log": run["log"]}

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
