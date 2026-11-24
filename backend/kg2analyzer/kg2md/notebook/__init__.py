"""Phase I as the KG2MD research notebook itself.

``KG2MD.ipynb`` is a verbatim copy of the notebook from miskatul-anwar/KG2MD (refresh it with
``uv run python -m kg2analyzer.kg2md.notebook sync <path-to-notebook>``). ``run_notebook`` executes
the notebook's own code cells, in order, for one TBox + ABox, so Build produces exactly the
notebook's MDKGs: Tev1 decisions, ABox record identity, the hierarchy engine, the QB4OLAP schema and
data graphs, the audit checks and the self-contained N-Quads bundle per fact class.

Only two cells are not executed: the ``%pip install`` cell and the cell that loads Tev1. The decider
is loaded once per process instead (``tev1_decider``) and injected as the notebook's ``fact_decider``.
The notebook reads its inputs and options from environment variables (``KG2MD_TBOX_PATH``,
``KG2MD_ABOX_PATH``, ``KG2MD_OUTPUT_DIR``, ``KG2MD_*``); a run sets them under a lock.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NOTEBOOK = Path(__file__).with_name("KG2MD.ipynb")
TEV1_MODEL_ID = "togethercomputer/Tev1-0.8B-experimental"  # the notebook's TEV1_MODEL_ID
_RUN_LOCK = threading.Lock()
_DECIDER_LOCK = threading.Lock()
_DECIDERS: dict[str, Any] = {}


def _module_namespace(name: str) -> dict[str, Any]:
    """A fresh module (registered, so dataclasses and pickling can resolve it) whose namespace the cells share."""
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod.__dict__


def code_cells(path: Path = NOTEBOOK) -> list[tuple[int, str]]:
    """(cell index, source) of every code cell."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, c in enumerate(nb["cells"]):
        if c.get("cell_type") == "code":
            src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            out.append((i, src))
    return out


def _is_install(src: str) -> bool:
    return src.lstrip().startswith(("%pip", "!pip", "%conda"))


def _is_decider_init(src: str) -> bool:
    return "Tev1FactDecider(" in src and "class Tev1FactDecider" not in src


def _decider_definition_cells(cells: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The cells up to and including the one that defines ``Tev1FactDecider``."""
    out = []
    for i, src in cells:
        if _is_install(src):
            continue
        out.append((i, src))
        if "class Tev1FactDecider" in src:
            return out
    raise RuntimeError("the notebook no longer defines Tev1FactDecider")


# ------------------------------------------------------------------ deciders
def tev1_decider(device: str | None = None) -> Any:
    """The notebook's own ``Tev1FactDecider``, loaded once per process (needs the ``tev1`` extra)."""
    device = device or os.environ.get("KG2MD_TEV1_DEVICE", "auto")
    with _DECIDER_LOCK:
        if device not in _DECIDERS:
            ns = _module_namespace("kg2md_notebook_decider")
            for i, src in _decider_definition_cells(code_cells()):
                exec(compile(src, f"<KG2MD cell {i}>", "exec", dont_inherit=True), ns)  # noqa: S102 - the vendored notebook
            _DECIDERS[device] = ns["Tev1FactDecider"](device=device)
        return _DECIDERS[device]


class StructuralDecider:
    """A deterministic stand-in for Tev1 that answers the four questions from structure and names.

    It is NOT the KG2MD decision model: use it only where Tev1 cannot run (tests, machines without
    the ``tev1`` extra) and say so (``KG2A_DECIDER=structural``). Same interface and result shape.
    """

    model_id = "structural (not Tev1)"

    def _result(self, probabilities: dict[str, float]) -> dict:
        k = max(probabilities, key=lambda x: probabilities[x])
        return {"prediction": k, "confidence": probabilities[k], "probabilities": probabilities,
                "backend": "structural", "model": self.model_id}

    def decide(self, profile: dict) -> dict:
        numeric = min(profile.get("numeric_property_count", 0), 2)
        links = min(profile.get("object_property_count", 0), 4)
        p = round(min(0.05 + 0.25 * numeric + 0.1 * links, 0.95), 4)
        return self._result({"fact_class": p, "dimension_class": round(1 - p, 4)})

    def decide_aggregate(self, profile: dict) -> dict:
        name = str(profile.get("measure_name", "")).lower()
        if profile.get("values_between_0_and_1") or any(w in name for w in (
                "rate", "ratio", "percent", "pct", "price", "avg", "average", "mean", "score", "index",
                "temperature", "temp", "occupancy", "humidity", "level", "discount", "yield", "margin")):
            k = "avg"
        elif any(w in name for w in ("min", "lowest", "earliest", "floor")):
            k = "min"
        elif any(w in name for w in ("max", "peak", "highest", "capacity", "ceiling")):
            k = "max"
        else:
            k = "sum"
        return self._result({x: (0.85 if x == k else 0.05) for x in ("sum", "avg", "min", "max")})

    def decide_unit_property(self, profile: dict, threshold: float | None = None) -> dict:
        text = json.dumps(profile).lower()
        unit = any(w in text for w in ("unitofmeasure", "unit_of_measure", "currency", "\"unit\"", "measureunit"))
        return self._result({"unit_property": 0.9 if unit else 0.05, "other_property": 0.1 if unit else 0.95})

    def decide_level_attribute(self, profile: dict) -> dict:
        name = str(profile.get("property_name", "")).lower()
        meta = any(w in name for w in ("created", "modified", "updated", "version", "batch", "checksum",
                                       "sync", "deleted", "steward", "sourcesystem", "source_file", "etl"))
        return self._result({"attribute": 0.1 if meta else 0.9, "metadata": 0.9 if meta else 0.1})


def default_decider() -> Any:
    """Tev1 unless ``KG2A_DECIDER=structural``."""
    choice = os.environ.get("KG2A_DECIDER", "tev1").lower()
    if choice == "structural":
        return StructuralDecider()
    if choice != "tev1":
        raise ValueError("KG2A_DECIDER must be tev1 or structural")
    try:
        return tev1_decider()
    except ImportError as e:
        raise RuntimeError(
            "KG2MD decides with Tev1, which needs PyTorch and transformers: run `uv sync --extra tev1` "
            "(the model, about 1.8 GB, downloads on first use). To build without Tev1 for testing, set "
            "KG2A_DECIDER=structural (not the KG2MD decision model).") from e


# ------------------------------------------------------------------ one run
@dataclass
class NotebookRun:
    """What one notebook run produced for one KG."""

    files: dict[str, bytes]                 # output path (relative to the output folder) -> bytes
    log: str                                # everything the cells printed
    seconds: float
    decider: str
    summary: dict = field(default_factory=dict)


class RecordingDecider:
    """Passes every question to the real decider and keeps (question, profile, answer) for the report."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.model_id = getattr(inner, "model_id", type(inner).__name__)
        self.decisions: list[dict] = []

    def __getattr__(self, name: str) -> Any:  # e.g. the notebook reading fact_decider.model
        return getattr(self.inner, name)

    def _ask(self, kind: str, fn: str, profile: dict, *a: Any) -> dict:
        res = getattr(self.inner, fn)(profile, *a)
        self.decisions.append({"question": kind, "profile": json.loads(json.dumps(profile, default=str)),
                               "prediction": res["prediction"], "confidence": round(float(res["confidence"]), 6),
                               "probabilities": {k: round(float(v), 6) for k, v in res["probabilities"].items()}})
        return res

    def decide(self, profile: dict) -> dict:
        return self._ask("fact_class", "decide", profile)

    def decide_aggregate(self, profile: dict) -> dict:
        return self._ask("aggregate", "decide_aggregate", profile)

    def decide_unit_property(self, profile: dict, threshold: float | None = None) -> dict:
        return self._ask("unit", "decide_unit_property", profile, threshold)

    def decide_level_attribute(self, profile: dict) -> dict:
        return self._ask("level_attribute", "decide_level_attribute", profile)


def run_notebook(tbox: bytes, abox: bytes, decider: Any | None = None, env: dict[str, str] | None = None) -> NotebookRun:
    """Run every KG2MD code cell on one TBox + ABox (Turtle) and collect the output folder."""
    decider = RecordingDecider(decider if decider is not None else default_decider())
    cells = code_cells()
    with _RUN_LOCK, tempfile.TemporaryDirectory(prefix="kg2md-") as tmp:
        root = Path(tmp)
        (root / "input").mkdir()
        (root / "input" / "TBox.ttl").write_bytes(tbox)
        (root / "input" / "ABox.ttl").write_bytes(abox)
        out_dir = root / "output"
        settings = {"KG2MD_TBOX_PATH": str(root / "input" / "TBox.ttl"),
                    "KG2MD_ABOX_PATH": str(root / "input" / "ABox.ttl"),
                    "KG2MD_OUTPUT_DIR": str(out_dir), **(env or {})}
        saved = {k: os.environ.get(k) for k in settings}
        os.environ.update(settings)
        ns = _module_namespace("kg2md_notebook_run")
        buf = io.StringIO()
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(buf):
                for i, src in cells:
                    if _is_install(src):
                        continue
                    if _is_decider_init(src):
                        ns["fact_decider"] = decider
                        continue
                    try:
                        exec(compile(src, f"<KG2MD cell {i}>", "exec", dont_inherit=True), ns)  # noqa: S102
                    except Exception as e:
                        raise NotebookError(i, e, buf.getvalue()) from e
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        seconds = time.perf_counter() - t0
        files = {p.relative_to(out_dir).as_posix(): p.read_bytes()
                 for p in sorted(out_dir.rglob("*")) if p.is_file() and p.name != "abox_unique_records.ttl"}
        log = buf.getvalue()
        files["kg2md.log"] = log.encode("utf-8")
        summary = _summary(ns)
        summary["decisions"] = decider.decisions
        return NotebookRun(files, log, round(seconds, 3), decider.model_id, summary)


class NotebookError(RuntimeError):
    def __init__(self, cell: int, error: Exception, log: str):
        tail = "\n".join(log.strip().splitlines()[-8:])
        super().__init__(f"KG2MD notebook cell {cell} failed: {type(error).__name__}: {error}"
                         + (f"\nLast output:\n{tail}" if tail else ""))
        self.cell, self.error, self.log = cell, error, log


def _local(iri: Any) -> str:
    return str(iri).split("/")[-1].split("#")[-1]


def _summary(ns: dict[str, Any]) -> dict:
    """The decisions the notebook made, read from its own variables (JSON-ready)."""
    scores = ns.get("ml_fact_scores", {})
    details = ns.get("ml_fact_details", {})
    raw = ns.get("raw_class_scores", {})
    classes = ns.get("classes", {})
    selected = [str(u) for u in ns.get("selected_fact_classes", [])]
    excluded = {str(u) for u in ns.get("excluded_by_guard", [])}
    referenced = ns.get("fact_referenced_ratio", {})
    out_classes = []
    for uri in sorted(scores, key=lambda u: (-scores[u], str(u))):
        r = raw.get(uri, {})
        out_classes.append({
            "iri": str(uri), "label": _local(uri), "instances": int(r.get("c3", classes.get(uri, {}).get("instance_count", 0))),
            "probability": round(float(scores[uri]), 6), "selected": str(uri) in selected,
            "excluded_by_guard": str(uri) in excluded, "referenced_ratio": round(float(referenced.get(uri, 0.0)), 4),
            "object_properties": int(r.get("c1", 0)), "numeric_properties": int(r.get("c2", 0)),
            "decision": {k: details[uri].get(k) for k in ("prediction", "confidence", "backend", "model")} if uri in details else {},
        })
    cubes = []
    for fact, res in (ns.get("mdkg_results") or {}).items():
        data, schema = res["data_graph"], res["schema_graph"]
        from rdflib import URIRef
        from rdflib.namespace import RDF
        QB = "http://purl.org/linked-data/cube#"
        obs = len(set(data.subjects(RDF.type, URIRef(QB + "Observation"))))
        cubes.append({
            "fact_class": str(fact), "key": Path(str(res["output_dir"])).name, "score": round(float(res["score"]), 6),
            "observations": obs, "schema_triples": len(schema), "data_triples": len(data),
            "dimensions": [{
                "uri": str(d["uri"]), "label": d.get("label") or _local(d["uri"]),
                "base_level": _local(d["base_level"]["uri"]) if d.get("base_level") else None,
                "degenerate": bool(d.get("degenerate")),
                "hierarchies": [{"label": h.get("label"), "types": list(h.get("types", [])),
                                 "semantics": h.get("semantics"),
                                 "levels": [lv.get("label") or _local(lv["uri"]) for lv in h.get("levels", [])],
                                 "steps": len(h.get("steps", []))} for h in d.get("hierarchies", [])],
            } for d in res.get("dimensions", [])],
        })
    return {
        "otsu_threshold": ns.get("fact_threshold"),
        "classes": out_classes,
        "selected": selected,
        "cubes": cubes,
        "tbox_triples": len(ns["tbox_graph"]) if "tbox_graph" in ns else 0,
        "source_triples": len(ns["source_graph"]) if "source_graph" in ns else 0,
        "abox_subjects": len(ns.get("abox_subjects", ())),
        "abox_triples": len(ns["abox_graph"]) - len(ns["tbox_graph"]) if "abox_graph" in ns and "tbox_graph" in ns else 0,
        "inferred_type_triples": len(ns.get("inferred_type_triples", ()) or ()),
        "undeclared_properties": [str(p) for p in ns.get("undeclared_properties", ()) or ()],
        "separated_records": len(ns.get("rewritten_fact_origins", {}) or {}),
    }
