"""FastAPI server: JSON API for the web UI and developers, plus SPARQL 1.1 Protocol endpoints.

    uv run kg2analyzer serve --port 8000          (or: uv run uvicorn kg2analyzer.server:app)

``/sparql`` (integrated) and ``/sparql/{kg}`` (one source) speak the SPARQL
1.1 Protocol, so another KG2Analyzer can attach this one as a federated remote.
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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
AZ = KG2Analyzer(translator=os.environ.get("KG2A_TRANSLATOR"))


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


def guarded(fn):
    try:
        with LOCK:
            return fn()
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e).strip("'\""))
    except PermissionError as e:
        raise HTTPException(403, str(e))


app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("KG2A_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ status / loading
@app.get("/api/status")
def status():
    def f():
        return ok({"kgs": list(AZ.store.sources), "graphs": AZ.store.graph_stats(),
                   "cubes": len(AZ.catalog.cubes), "identity_links": len(AZ.store.identity),
                   "translator": AZ.nl.translator.name})
    return guarded(f)


@app.post("/api/kgs")
async def upload_kg(name: str = Form(...), file: UploadFile = File(...), fmt: str | None = Form(None),
                    max_facts: int | None = Form(None)):
    data = await file.read()
    if not fmt and file.filename:
        from kg2analyzer.analyzer import FORMATS
        fmt = FORMATS.get(Path(file.filename).suffix.lower())

    def f():
        AZ.load_kg(name, data, fmt, max_facts=max_facts or None)
        kg = [k for k in AZ.results if k == name.lower() or k == "".join(c for c in name.lower() if c.isalnum())][0]
        return ok(AZ.phase1_report(kg))
    return guarded(f)


class RemoteReq(BaseModel):
    name: str
    url: str


@app.post("/api/remote")
def attach_remote(req: RemoteReq):
    return guarded(lambda: (AZ.attach_remote(req.name, req.url), ok({"attached": req.name}))[1])


@app.delete("/api/kgs/{kg}")
def delete_kg(kg: str):
    return guarded(lambda: (AZ.remove_kg(kg), ok({"removed": kg}))[1])


@app.post("/api/identity")
async def upload_identity(file: UploadFile = File(...)):
    data = await file.read()
    return guarded(lambda: ok({"links_added": AZ.load_identity(data)}))


class LinksReq(BaseModel):
    pairs: list[tuple[str, str]]


@app.post("/api/links")
def add_links(req: LinksReq):
    return guarded(lambda: ok({"links_added": AZ.add_links(req.pairs), "identity_triples": len(AZ.store.identity)}))


@app.get("/api/catalog")
def catalog():
    return guarded(lambda: ok(AZ.catalog.to_dict() | {"prompt_context": AZ.catalog.prompt_context()}))


@app.get("/api/kgs/{kg}/phase1")
def phase1(kg: str):
    return guarded(lambda: ok(AZ.phase1_report(kg)))


# ------------------------------------------------------------------ Phase II
class CrossReq(BaseModel):
    left: tuple[str, str, str]
    right: tuple[str, str, str]
    link: str = "identity"
    strategy: str = "pushdown"
    mode: str = "integrated"


@app.post("/api/crosscube")
def crosscube(req: CrossReq):
    return guarded(lambda: ok(asdict(AZ.cross_cube(req.left, req.right, req.link, req.strategy, req.mode))))


@app.post("/api/crosscube/compare")
def crosscube_compare(req: CrossReq):
    return guarded(lambda: ok(AZ.compare_strategies(req.left, req.right, req.link)))


class OlapReq(BaseModel):
    kg: str
    measure: str
    group_by: list[tuple[str, str | None]] = []
    filters: list[tuple[str, str, str | None]] = []
    aggregate: str | None = None


@app.post("/api/olap")
def olap(req: OlapReq):
    return guarded(lambda: ok(asdict(AZ.olap(req.kg, req.measure, req.group_by, req.filters, req.aggregate))))


class CommReq(BaseModel):
    projection: str = "identity"
    algorithm: str = "greedy_modularity"
    kgs: list[str] | None = None
    k: int | None = None


@app.post("/api/communities")
def communities(req: CommReq):
    return guarded(lambda: ok(AZ.communities(req.projection, req.algorithm, req.kgs, req.k)))


class DiscoverReq(BaseModel):
    kg_a: str
    kg_b: str
    threshold: float = 0.5


@app.post("/api/links/discover")
def discover(req: DiscoverReq):
    return guarded(lambda: ok(AZ.discover_links(req.kg_a, req.kg_b, req.threshold)))


class SparqlReq(BaseModel):
    query: str
    kg: str | None = None


@app.post("/api/sparql")
def sparql(req: SparqlReq):
    def f():
        try:
            return ok(AZ.sparql(req.query, req.kg))
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001  (parse errors etc.)
            raise ValueError(f"query failed: {e}")
    return guarded(f)


# ------------------------------------------------------------------ Phase III
class AskReq(BaseModel):
    question: str


@app.post("/api/ask")
def ask(req: AskReq):
    return guarded(lambda: ok(AZ.ask(req.question).to_dict()))


@app.get("/api/suggestions")
def suggestions():
    """Example questions over the loaded MDKGs; each one is validated and returns rows."""
    return guarded(lambda: ok({"questions": AZ.suggest_questions()}))


class TranslatorReq(BaseModel):
    spec: str  # rules | auto | ollama[:model] | openai


@app.post("/api/translator")
def translator(req: TranslatorReq):
    return guarded(lambda: ok({"translator": AZ.set_translator(req.spec)}))


@app.get("/api/export.nq", response_class=PlainTextResponse)
def export():
    return guarded(lambda: PlainTextResponse(AZ.export_nquads(), media_type="application/n-quads"))


# ------------------------------------------------------------------ SPARQL 1.1 Protocol
async def _protocol(request: Request, kg: str | None):
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
        res = (AZ.store.integrated if kg is None else AZ.store.sources[kg].dataset).query(q)
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
    return guarded(f)


@app.api_route("/sparql", methods=["GET", "POST"])
async def sparql_integrated(request: Request):
    return await _protocol(request, None)


@app.api_route("/sparql/{kg}", methods=["GET", "POST"])
async def sparql_source(kg: str, request: Request):
    if kg not in AZ.store.sources:
        raise HTTPException(404, f"unknown KG {kg}")
    return await _protocol(request, kg)


# ------------------------------------------------------------------ batch pipeline: KGs -> MDKGs
@app.post("/api/pipeline")
async def pipeline(files: list[UploadFile] = File(...), auto_link: bool = Form(True), threshold: float = Form(0.6),
                   reset: bool = Form(True), max_facts: int | None = Form(None)):
    """Upload a set of raw KGs (files, TBox/ABox pairs, zips, owl:sameAs files): build every MDKG and link them."""
    from kg2analyzer.ingest import RdfFile

    batch = [RdfFile(f.filename or "kg.ttl", await f.read()) for f in files]
    return guarded(lambda: ok(AZ.ingest(batch, auto_link=auto_link, link_threshold=threshold, reset=reset,
                                        max_facts=max_facts or None)))


@app.get("/api/pipeline/report")
def pipeline_report():
    return guarded(lambda: ok(AZ.last_report))


@app.get("/api/kgs/{kg}/mdkg.trig")
def mdkg_trig(kg: str):
    return guarded(lambda: PlainTextResponse(AZ.mdkg_trig(kg), media_type="application/trig",
                                             headers={"Content-Disposition": f'attachment; filename="{kg}.mdkg.trig"'}))


@app.get("/api/mdkg.zip")
def mdkg_zip():
    from fastapi.responses import Response

    return guarded(lambda: Response(AZ.mdkg_zip(), media_type="application/zip",
                                    headers={"Content-Disposition": 'attachment; filename="mdkg.zip"'}))


# ------------------------------------------------------------------ React single-page app
if (WEB_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")  # client-side routes (/olap, /ask, ...)
else:
    @app.get("/", include_in_schema=False)
    def no_ui():
        return JSONResponse({"message": "KG2Analyzer API is running. Build the UI with `cd frontend && npm run build`, "
                                        "or run `npm run dev` there. API docs: /docs"})
