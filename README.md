# KG2Analyzer

**A framework for multidimensional analytics and natural-language querying across knowledge graphs.**

KG2Analyzer turns raw RDF/OWL knowledge graphs into QB4OLAP cubes and hosts them as source-aware named graphs. You can analyse them across KGs, physically integrated or federated, without the Cartesian multiplication trap, from a React dashboard, a typed REST API, SPARQL endpoints, or plain-English questions.

**Stack:** React 19 · TypeScript · Vite · Tailwind CSS v4 · TanStack Query · React Router · Recharts · react-force-graph on the frontend; FastAPI · RDFLib · NetworkX · scikit-learn on the backend, managed with uv.

| Thesis phase | What it does | Where |
|---|---|---|
| **I · KG2MD** | RDFS closure → class profiling → explainable fact scoring → **Otsu** fact selection → measure **additivity** (trained models + **SHAP/LIME**) → **ADW4 hierarchies** (balanced, recursive, ragged, alternative, parallel, nonstrict) → QB4OLAP schema + observation graphs → fact/measure preservation audit | `backend/kg2analyzer/kg2md/` · UI *KG2MD* |
| **II · Multi-KG** | Named-graph store with **integrated** and **federated** execution (in-process or remote SPARQL 1.1 endpoints), `owl:sameAs` identity graph, **pushdown pre-aggregation** planner + Cartesian guard, OLAP roll-up / slice / dice | `store.py`, `planner.py`, `olap.py` · UI *Cross-KG*, *OLAP* |
| **Graph analytics** | **Cross-KG node linking** (blocking + label / literal / **SGC graph-neural-embedding** similarity; logistic model when links exist) and **community detection** (CNM, Louvain, label propagation, SGC + k-means) scored by modularity | `linking.py`, `graphml.py` · UI *Links & Communities* |
| **III · NL interface** | Dynamic schema catalogue + compact aliases → translator (Ollama `qwen2.5-coder:3b`, any OpenAI-compatible server, or the offline grounded parser) → 4-rule validation (syntax, grounding, scope, safety) → error-fed retry → deterministic fallback | `backend/kg2analyzer/nl/` · UI *Ask* |

## Run it

Python tooling is [uv](https://docs.astral.sh/uv/): `backend/pyproject.toml` + `backend/uv.lock` pin everything (Python 3.12 via `.python-version`).

**Development** (hot reload; Vite proxies `/api` and `/sparql` to FastAPI):

```bash
cd backend && uv sync && uv run kg2analyzer serve --benchmark enterprise
```
```bash
cd frontend && npm install && npm run dev        # http://localhost:5173
```

**Production** (FastAPI serves the built UI at http://127.0.0.1:8000):

```bash
cd frontend && npm ci && npm run build
```
```bash
cd backend && uv run kg2analyzer serve --benchmark enterprise
```

**Docker**:

```bash
docker build -t kg2analyzer . && docker run -p 8000:8000 kg2analyzer
```

**Local LLM for Phase III** (optional; without it the grounded parser answers):

```bash
ollama pull qwen2.5-coder:3b
```
```bash
cd backend && KG2A_TRANSLATOR=ollama uv run kg2analyzer serve --benchmark enterprise
```

## Developer API

```python
# cd backend && uv run python
from kg2analyzer.analyzer import KG2Analyzer

az = KG2Analyzer()
az.load_kg("sales", "sales.ttl")            # runs KG2MD
az.load_kg("finance", "finance.ttl")
az.discover_links("sales", "finance")      # candidates → az.add_links([...])
az.cross_cube(("sales", "customer", "amount"), ("finance", "trader", "tradeAmount"))   # pushdown
az.olap("sales", "amount", group_by=[("product", "Category")])
az.communities("identity", "louvain")
az.ask("Total sales by product category")
```

REST docs are at `/docs`. `/sparql` and `/sparql/{kg}` implement the SPARQL 1.1 Protocol, so one KG2Analyzer can federate another (`POST /api/remote`).

## Reproducing the thesis results

Run `uv run kg2analyzer evaluate` in `backend/`, or use the **Evaluate** page. On the enterprise benchmark:

| Result | Value |
|---|---|
| Domain cubes | 7/7 fact classes found by Otsu · 200 observations · 22 measures · 100% fact preservation and measure fidelity |
| Store | 15 named graphs (7 schema + 7 data + identity) · 16 directed `owl:sameAs` |
| Query 23, pushdown (integrated = federated) | Alice 1,499.70 / 52,620.00 · Bob 1,499.70 / 50,737.50 |
| Query 23, naive join | Alice 14,997.00 / 789,300.00 (×10 / ×15) |
| Identity communities | 4 × 3 entities · Q = 0.75 |
| NL benchmark, 35 questions | 32 executed (91.43%) · 3 correctly refused |
| Northwind | 10/10 facts · 60/60 measure cells · category roll-up 4,607.89 |

## Repository layout

```
backend/
  kg2analyzer/      Python package: analyzer.py (entry point), kg2md/, nl/, store, planner, olap, linking, graphml, server
  models/           trained measure-classifier pipelines (joblib)
  tests/            39 seam tests (Phase I, multi-KG, NL, HTTP + federation)
frontend/
  src/api/          typed API client + TanStack Query hooks
  src/pages/        Workspace, KG2MD, OLAP, Cross-KG, Links & Communities, Ask, SPARQL, Evaluate
  src/components/   UI kit (Card, DataTable, Chip, ...) and CubePicker
docs/adr/           architecture decisions        GLOSSARY.md   domain language
.claude/skills/     Matt Pocock's engineering skills (tdd, code-review, to-spec, ...)
```

The Phase I research notebook lives in [miskatul-anwar/KG2MD](https://github.com/miskatul-anwar/KG2MD).
