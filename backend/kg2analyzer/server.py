"""FastAPI server: JSON API for the web UI and developers, plus SPARQL 1.1 Protocol endpoints.

    uv run kg2analyzer serve --port 8000          (or: uv run uvicorn kg2analyzer.server:app)

The three sections are independent workspaces, chosen per request with ``?ws=``:

* ``build``  raw KGs (TBox + ABox) -> MDKGs, which the user saves as files
* ``query``  MDKG files the user loads -> structured / cross-MDKG queries
* ``ask``    MDKG files the user loads -> natural-language questions

``/sparql`` (integrated) and ``/sparql/{kg}`` (one source) speak the SPARQL
1.1 Protocol, so another KG2Analyzer can attach this one as a federated remote.
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kg2analyzer.analyzer import KG2Analyzer
from kg2analyzer.store import result_rows

# Built React app (frontend/dist). Override with KG2A_WEB_DIST.
WEB_DIST = Path(os.environ.get("KG2A_WEB_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
app = FastAPI(title="KG2Analyzer", version="1.0.0",
              description="Multidimensional analytics and natural-language querying across knowledge graphs.")
LOCK = threading.RLock()
WORKSPACES: dict[str, KG2Analyzer] = {ws: KG2Analyzer(translator=os.environ.get("KG2A_TRANSLATOR"))
                                      for ws in ("build", "query", "ask")}
AZ = WORKSPACES["build"]  # back-compat alias


def workspace(ws: str = Query("build", description="build | query | ask")) -> KG2Analyzer:
    if ws not in WORKSPACES:
        raise HTTPException(404, f"unknown workspace {ws!r}; use build, query or ask")
    return WORKSPACES[ws]


W = Depends(workspace)


def _clean(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v) for v in o]
    return o


def ok(o) -> JSONResponse:
    return JSONResponse(_clean(o))


LOCKS: dict[int, threading.RLock] = {id(a): threading.RLock() for a in WORKSPACES.values()}


def guarded(a: KG2Analyzer, fn):
    """Run ``fn`` under the workspace's own lock (a long Build never blocks Query or Ask)."""
    try:
        with LOCKS.get(id(a), LOCK):
            return fn()
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e).strip("'\""))
    except PermissionError as e:
        raise HTTPException(403, str(e))


app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("KG2A_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ status / loading
@app.get("/api/status")
def status(a: KG2Analyzer = W):
    def f():
        return ok({"kgs": list(a.store.sources), "graphs": a.store.graph_stats(),
                   "cubes": len(a.catalog.cubes), "identity_links": len(a.store.identity),
                   "translator": a.nl.translator.name, "decider": _decider_name(a), **_engines()})
    return guarded(a, f)


def _engines() -> dict:
    """What can run here: Tev1 (installed? loaded?), the embedding model, the LLM server."""
    from kg2analyzer.kg2md.notebook import tev1_available, tev1_loaded
    from kg2analyzer.nl.semantic import embedding_backend
    from kg2analyzer.nl.translators import llm_available

    return {"tev1_available": tev1_available(), "tev1_loaded": tev1_loaded(),
            "embeddings": embedding_backend(), "llm": llm_available()}


@app.on_event("startup")
def _warm_up() -> None:
    """Load Tev1 and the embedding model in the background so the first build/question does not wait."""
    if os.environ.get("KG2A_PRELOAD", "1") != "0":
        from kg2analyzer.kg2md.notebook import preload_tev1
        from kg2analyzer.nl.semantic import _model

        def warm():  # one after the other: importing torch and model2vec concurrently can fail
            _model()
            preload_tev1()
        threading.Thread(target=warm, name="warm-up", daemon=True).start()


def _decider_name(a: KG2Analyzer) -> str:
    if a.decider is not None:
        return getattr(a.decider, "model_id", type(a.decider).__name__)
    from kg2analyzer.kg2md.notebook import TEV1_MODEL_ID

    return {"structural": "structural (not Tev1)", "ml": "ML classifiers (not Tev1)"}.get(
        os.environ.get("KG2A_DECIDER", "tev1").lower(), TEV1_MODEL_ID)


@app.post("/api/kgs")
async def upload_kg(name: str = Form(...), file: UploadFile = File(...), fmt: str | None = Form(None),
                    max_facts: int | None = Form(None), a: KG2Analyzer = W):
    data = await file.read()
    if not fmt and file.filename:
        from kg2analyzer.analyzer import FORMATS
        fmt = FORMATS.get(Path(file.filename).suffix.lower())

    def f():
        a.load_kg(name, data, fmt, max_facts=max_facts or None)
        kg = [k for k in a.results if k == name.lower() or k == "".join(c for c in name.lower() if c.isalnum())][0]
        return ok(a.phase1_report(kg))
    return guarded(a, f)


class RemoteReq(BaseModel):
    name: str
    url: str


@app.post("/api/remote")
def attach_remote(req: RemoteReq, a: KG2Analyzer = W):
    return guarded(a, lambda: (a.attach_remote(req.name, req.url), ok({"attached": req.name}))[1])


def _clear(a: KG2Analyzer) -> None:
    for kg in list(a.store.sources):
        a.remove_kg(kg)
    a.store.identity.remove((None, None, None))
    a.last_report = {}
    a._invalidate()


@app.post("/api/reset")
def reset_workspace(a: KG2Analyzer = W):
    return guarded(a, lambda: (_clear(a), ok({"reset": True}))[1])


@app.post("/api/reset-all")
def reset_all():
    """Back to the very first state: Build, Query and Ask emptied and the translator back to its default.
    Files the user saved are untouched, and so is the Tev1 answer cache (it only makes builds faster)."""
    for a in WORKSPACES.values():
        guarded(a, lambda a=a: (_clear(a), a.set_translator(os.environ.get("KG2A_TRANSLATOR"))))
    return ok({"reset": list(WORKSPACES)})


@app.delete("/api/kgs/{kg}")
def delete_kg(kg: str, a: KG2Analyzer = W):
    return guarded(a, lambda: (a.remove_kg(kg), ok({"removed": kg}))[1])


@app.post("/api/identity")
async def upload_identity(file: UploadFile = File(...), a: KG2Analyzer = W):
    data = await file.read()
    return guarded(a, lambda: ok({"links_added": a.load_identity(data)}))


class LinksReq(BaseModel):
    pairs: list[tuple[str, str]]


@app.post("/api/links")
def add_links(req: LinksReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok({"links_added": a.add_links(req.pairs), "identity_triples": len(a.store.identity)}))


@app.get("/api/catalog")
def catalog(a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.catalog.to_dict() | {"prompt_context": a.catalog.prompt_context()}))


@app.get("/api/kgs/{kg}/phase1")
def phase1(kg: str, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.phase1_report(kg)))


# ------------------------------------------------------------------ Phase II
class CrossReq(BaseModel):
    left: tuple[str, str, str]
    right: tuple[str, str, str]
    link: str = "identity"
    strategy: str = "pushdown"
    mode: str = "integrated"


@app.post("/api/crosscube")
def crosscube(req: CrossReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(asdict(a.cross_cube(req.left, req.right, req.link, req.strategy, req.mode))))


@app.post("/api/crosscube/compare")
def crosscube_compare(req: CrossReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.compare_strategies(req.left, req.right, req.link)))


class OlapReq(BaseModel):
    kg: str
    measure: str
    group_by: list[tuple[str, str | None]] = []
    filters: list[tuple[str, str, str | None]] = []
    aggregate: str | None = None


@app.post("/api/olap")
def olap(req: OlapReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(asdict(a.olap(req.kg, req.measure, req.group_by, req.filters, req.aggregate))))


class CommReq(BaseModel):
    projection: str = "identity"
    algorithm: str = "greedy_modularity"
    kgs: list[str] | None = None
    k: int | None = None


@app.post("/api/communities")
def communities(req: CommReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.communities(req.projection, req.algorithm, req.kgs, req.k)))


class DiscoverReq(BaseModel):
    kg_a: str
    kg_b: str
    threshold: float = 0.5


@app.post("/api/links/discover")
def discover(req: DiscoverReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.discover_links(req.kg_a, req.kg_b, req.threshold)))


class SparqlReq(BaseModel):
    query: str
    kg: str | None = None


@app.post("/api/sparql")
def sparql(req: SparqlReq, a: KG2Analyzer = W):
    def f():
        try:
            return ok(a.sparql(req.query, req.kg))
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001  (parse errors etc.)
            raise ValueError(f"query failed: {e}")
    return guarded(a, f)


# ------------------------------------------------------------------ Phase III
class AskReq(BaseModel):
    question: str


@app.post("/api/ask")
def ask(req: AskReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.ask(req.question).to_dict()))


@app.get("/api/overview")
def overview(a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.overview()))


@app.get("/api/members")
def members(kg: str, dim: str, level: str | None = None, a: KG2Analyzer = W):
    return guarded(a, lambda: ok({"members": a.members(kg, dim, level)}))


@app.get("/api/joins")
def joins(a: str, b: str, az: KG2Analyzer = W):
    return guarded(az, lambda: ok({"options": az.join_options(a, b)}))


@app.get("/api/suggestions")
def suggestions(a: KG2Analyzer = W):
    """Example questions over the loaded MDKGs; each one is validated and returns rows."""
    return guarded(a, lambda: ok({"questions": a.suggest_questions()}))


class TranslatorReq(BaseModel):
    spec: str  # rules | auto | ollama[:model] | openai


@app.post("/api/translator")
def translator(req: TranslatorReq, a: KG2Analyzer = W):
    return guarded(a, lambda: ok({"translator": a.set_translator(req.spec)}))


@app.get("/api/export.nq", response_class=PlainTextResponse)
def export(a: KG2Analyzer = W):
    return guarded(a, lambda: PlainTextResponse(a.export_nquads(), media_type="application/n-quads"))


# ------------------------------------------------------------------ SPARQL 1.1 Protocol
async def _protocol(request: Request, kg: str | None, a: KG2Analyzer):
    if request.method == "GET":
        q = request.query_params.get("query")
    else:
        ct = request.headers.get("content-type", "")
        if ct.startswith("application/sparql-query"):
            q = (await request.body()).decode()
        else:
            q = (await request.form()).get("query")
    if not q:
        raise HTTPException(400, "missing query")

    def f():
        from kg2analyzer.nl.validator import MUTATION, _strip_literals

        if MUTATION.search(_strip_literals(q)):
            raise PermissionError("read-only endpoint")
        res = (a.store.integrated if kg is None else a.store.sources[kg].dataset).query(q)
        vars_, _ = result_rows(res)
        bindings = []
        for r in res:
            b = {}
            for v in vars_:
                t = r[v]
                if t is None:
                    continue
                if t.__class__.__name__ == "URIRef":
                    b[v] = {"type": "uri", "value": str(t)}
                elif t.__class__.__name__ == "BNode":
                    b[v] = {"type": "bnode", "value": str(t)}
                else:
                    b[v] = {"type": "literal", "value": str(t)} | ({"datatype": str(t.datatype)} if t.datatype else {})
            bindings.append(b)
        return JSONResponse({"head": {"vars": vars_}, "results": {"bindings": bindings}},
                            media_type="application/sparql-results+json")
    return guarded(a, f)


@app.api_route("/sparql", methods=["GET", "POST"])
async def sparql_integrated(request: Request, a: KG2Analyzer = W):
    return await _protocol(request, None, a)


@app.api_route("/sparql/{kg}", methods=["GET", "POST"])
async def sparql_source(kg: str, request: Request, a: KG2Analyzer = W):
    if kg not in a.store.sources:
        raise HTTPException(404, f"unknown KG {kg}")
    return await _protocol(request, kg, a)


# ------------------------------------------------------------------ batch pipeline: KGs -> MDKGs
@app.post("/api/pipeline")
async def pipeline(files: list[UploadFile] = File(...), auto_link: bool = Form(True), threshold: float = Form(0.6),
                   reset: bool = Form(True), max_facts: int | None = Form(None),
                   decider: str | None = Form(None, description="tev1 | ml (Tev1 switched off) | structural"), a: KG2Analyzer = W):
    """Upload a set of raw KGs (files, TBox/ABox pairs, zips, owl:sameAs files): build every MDKG and link them."""
    from kg2analyzer.ingest import RdfFile

    from fastapi.concurrency import run_in_threadpool

    batch = [RdfFile(f.filename or "kg.ttl", await f.read()) for f in files]
    return await run_in_threadpool(guarded, a, lambda: ok(a.ingest(batch, auto_link=auto_link, link_threshold=threshold,
                                                                    reset=reset, max_facts=max_facts or None,
                                                                    decider=decider or None)))


@app.post("/api/mdkgs")
async def load_mdkgs(files: list[UploadFile] = File(...), auto_link: bool = Form(True), threshold: float = Form(0.6),
                     reset: bool = Form(False), a: KG2Analyzer = W):
    """Load MDKG folders saved from Build (<kg>/fact_classes/<cube>/mdkg_dataset.nq ..., a zip, owl:sameAs files)."""
    from fastapi.concurrency import run_in_threadpool

    from kg2analyzer.ingest import RdfFile

    batch = [RdfFile(f.filename or "mdkg_dataset.nq", await f.read()) for f in files]
    return await run_in_threadpool(guarded, a, lambda: ok(a.load_mdkgs(batch, auto_link=auto_link,
                                                                        link_threshold=threshold, reset=reset)))


@app.post("/api/mdkgs/from-build")
def mdkgs_from_build(a: KG2Analyzer = W):
    """Load the MDKGs currently built in Build into this workspace (Query or Ask), replacing what it had.

    They arrive as the files Build would save (the KG2MD output folders plus identity.ttl), read by the
    same ``load_mdkgs``, so the sections still share files, not state (ADR 0007)."""
    from kg2analyzer.ingest import RdfFile

    build = WORKSPACES["build"]
    if a is build:
        raise HTTPException(400, "choose the Query or Ask workspace (?ws=query or ?ws=ask)")
    files = guarded(build, build.mdkg_files)
    if not any(p != "identity.ttl" for p in files):
        raise HTTPException(400, "Build has no MDKGs yet: build them in step 1 first.")
    batch = [RdfFile(p, b) for p, b in files.items()]
    return guarded(a, lambda: ok(a.load_mdkgs(batch, auto_link="identity.ttl" not in files, reset=True)))


@app.get("/api/mdkgs")
def list_mdkgs(a: KG2Analyzer = W):
    return guarded(a, lambda: ok({"mdkgs": a.loaded_mdkgs(), "identity_links": len(a.store.identity) // 2,
                               "clusters": len(set(a.store.identity_clusters().values()))}))


@app.get("/api/pipeline/report")
def pipeline_report(a: KG2Analyzer = W):
    return guarded(a, lambda: ok(a.last_report))


@app.get("/api/mdkg/files")
def mdkg_files(kg: str | None = None, a: KG2Analyzer = W):
    """The MDKG files as KG2MD wrote them: ``<kg>/fact_classes/<cube>/mdkg_*.ttl|nq``, selection, log, identity.ttl."""
    return guarded(a, lambda: ok({"files": [{"path": p, "size": len(b)} for p, b in a.mdkg_files(kg).items()]}))


@app.get("/api/mdkg/file")
def mdkg_file(path: str, a: KG2Analyzer = W):
    from fastapi.responses import Response

    def f():
        files = a.mdkg_files()
        if path not in files:
            raise KeyError(f"no MDKG file {path!r}")
        name = path.rsplit("/", 1)[-1]
        media = {"nq": "application/n-quads", "ttl": "text/turtle", "json": "application/json"}.get(name.rsplit(".", 1)[-1], "text/plain")
        return Response(files[path], media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return guarded(a, f)


@app.get("/api/identity.ttl")
def identity_ttl(a: KG2Analyzer = W):
    return guarded(a, lambda: PlainTextResponse(a.store.identity.serialize(format="turtle"), media_type="text/turtle",
                                             headers={"Content-Disposition": 'attachment; filename="identity.ttl"'}))


@app.get("/api/mdkg.zip")
def mdkg_zip(a: KG2Analyzer = W):
    from fastapi.responses import Response

    return guarded(a, lambda: Response(a.mdkg_zip(), media_type="application/zip",
                                    headers={"Content-Disposition": 'attachment; filename="mdkg.zip"'}))


# ------------------------------------------------------------------ React single-page app
if (WEB_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith(("api/", "sparql/")):  # an unknown API path is a 404, never the web page
            raise HTTPException(404, f"no API route /{path}")
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")  # client-side routes (/olap, /ask, ...)
else:
    @app.get("/", include_in_schema=False)
    def no_ui():
        return JSONResponse({"message": "KG2Analyzer API is running. Build the UI with `cd frontend && npm run build`, "
                                        "or run `npm run dev` there. API docs: /docs"})
