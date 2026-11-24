# KG2Analyzer

**A framework for multidimensional analytics and natural-language querying across knowledge graphs.**

KG2Analyzer turns raw RDF/OWL knowledge graphs into QB4OLAP cubes and hosts them as source-aware named graphs. You can analyse them across KGs, physically integrated or federated, without the Cartesian multiplication trap, from a React dashboard, a typed REST API, SPARQL endpoints, or plain-English questions.

**Stack:** React 19 · TypeScript · Vite · Tailwind CSS v4 · shadcn/ui (Radix) · Motion (Framer Motion) · GSAP · Aceternity-style effects · react-icons · Sigma.js + graphology (WebGL graph) · TanStack Query · Zustand · Recharts on the frontend; FastAPI · RDFLib · NetworkX · scikit-learn on the backend, managed with uv; Phase I is the [KG2MD notebook](https://github.com/miskatul-anwar/KG2MD) itself, deciding with Tev1 (PyTorch + transformers).

| Thesis phase | What it does | Where |
|---|---|---|
| **I · KG2MD** | The KG2MD notebook, run cell by cell per KG: ABox record identity → RDFS entailment → profiling → **Tev1** fact probabilities + structural guard → **Otsu** fact selection → Tev1 aggregate functions (additivity follows), units and level attributes → **hierarchy engine** (balanced, unbalanced, recursive, generalized, ragged, nonstrict, alternative/parallel) → QB4OLAP schema + data graphs → checks → N-Quads bundle | `backend/kg2analyzer/kg2md/notebook/` · UI *Build* |
| **II · Multi-KG** | Named-graph store with **integrated** and **federated** execution (in-process or remote SPARQL 1.1 endpoints), `owl:sameAs` identity graph, **pushdown pre-aggregation** planner + Cartesian guard, OLAP roll-up / slice / dice | `store.py`, `planner.py`, `olap.py` · UI *Cross-KG*, *OLAP* |
| **Graph analytics** | **Cross-KG node linking** (blocking + label / literal / **SGC graph-neural-embedding** similarity; logistic model when links exist) and **community detection** (CNM, Louvain, label propagation, SGC + k-means) scored by modularity | `linking.py`, `graphml.py` · UI *Links & Communities* |
| **III · NL interface** | Dynamic schema catalogue + compact aliases → translator (Ollama `qwen2.5-coder:3b`, any OpenAI-compatible server, or the offline grounded parser) → 4-rule validation (syntax, grounding, scope, safety) → error-fed retry → deterministic fallback | `backend/kg2analyzer/nl/` · UI *Ask* |

## Run it

Python tooling is [uv](https://docs.astral.sh/uv/): `backend/pyproject.toml` + `backend/uv.lock` pin everything (Python 3.12 via `.python-version`).

**Three independent steps, connected only by files you keep:**

1. **Build MDKGs**: give each knowledge graph its **TBox** (schema) and **ABox** (instances). The KG2MD notebook turns each into an MDKG, the KGs are linked, and you **save** the MDKGs to a folder of your choice, exactly as KG2MD writes them (or download `mdkg.zip`):
   ```
   <kg>/factclass_selection.json   <kg>/kg2md.log
   <kg>/fact_classes/<FactClass>_<hash>/mdkg_schema.ttl · mdkg_data.ttl · mdkg_dataset.nq
   identity.ttl
   ```
2. **Query**: query the MDKGs (roll-up, slice, cross-MDKG joins, SPARQL). After a build they are already there; you can also load saved MDKG folders instead.
3. **Ask**: ask in plain language, over the MDKGs just built or over saved folders you load (its own selection).

Folders written by the notebook on its own (`output_ml/`, e.g. from `run.sh` on a GPU server) load the same way.

TBox/ABox input: one row per KG with a TBox and an ABox slot. Bulk drops are assigned by name (`*_tbox` / `*_abox`, `schema`, `data`, `tbox/` and `abox/` folders, zips); a single combined file is split by content (schema triples to the TBox, the rest to the ABox). A single Turtle ABox file reaches the notebook byte for byte, so its record-identity repair sees the original text.

```bash
cd frontend && npm ci && npm run build
```
```bash
cd backend && uv sync --extra tev1 && uv run kg2analyzer serve
```

**Switches.** Build has a **Tev1** switch: on, KG2MD's decision model answers the notebook's questions; off, trained **ML classifiers** answer them in milliseconds (logistic regressions over name embeddings, name spelling and structure, each decision explained; reports say "not Tev1"; retrain with `uv run kg2analyzer train-decider`). Ask has an **LLM** switch and a **model picker** listing the models installed in your Ollama (size, parameters, which is loaded): on, the chosen model writes the SPARQL first, kept loaded between questions; if it has no valid query within `KG2A_LLM_BUDGET` seconds (default 30), the grounded parser's answer, computed in parallel, is shown; off, the grounded parser answers, matching question words to the MDKG vocabulary exactly, by meaning (model2vec `potion-base-8M` embeddings, ~30 MB, no PyTorch) and by spelling (character n-grams). Every query passes the same four validation rules either way.

**Fast demos.** Tev1 and the embedding model load in the background when the server starts. Every Tev1 answer is cached on disk (`~/.cache/kg2analyzer`, or `KG2A_CACHE_DIR`), so building the same KGs again takes under a second; build the demo KGs once beforehand. Answers to repeated questions are remembered too. The tiny shop/bank KGs in `backend/tests/fixtures/tiny/` come with example questions and expected answers.

`--extra tev1` installs PyTorch, transformers and accelerate; Tev1 (about 1.8 GB) downloads on the first build. It runs on a GPU when one works and otherwise on the CPU (`KG2MD_TEV1_DEVICE=auto|cpu|cuda`; about a minute per KG on 4 CPU cores). Without the extra, `uv sync` is enough for Query and Ask, and Build can use the structural stand-in, which is **not** Tev1 and is flagged as such in every report: `uv run kg2analyzer serve --decider structural`. The notebook's other options (`KG2MD_HIERARCHY_CONFIG`, `KG2MD_AS_OF`, `KG2MD_VIEW_CONFIG`, `KG2MD_FACT_GUARD`, `KG2MD_UNIT_THRESHOLD`, ...) are read from the environment as in the notebook.

Open http://127.0.0.1:8000. Optional preloading: `--kgs <raw KGs>` fills Build; `--mdkgs <saved MDKGs>` fills Query and Ask.

**Batch / CLI** (no UI): build writes one MDKG folder per KG plus `identity.ttl` and `report.json`; ask loads saved MDKGs:

```bash
cd backend && uv run kg2analyzer build /path/to/my_kgs --out mdkg
```
```bash
cd backend && uv run kg2analyzer ask "Total sales by product category" --mdkgs mdkg/
```

**UI development** (hot reload; Vite proxies `/api` and `/sparql` to the backend on :8000):

```bash
cd frontend && npm install && npm run dev        # or: bun install && bun run dev  -> http://localhost:5173
```

**Docker**:

```bash
docker build -t kg2analyzer .
```
```bash
docker run -p 8000:8000 -v "$PWD/my_kgs:/data" kg2analyzer --kgs /data   # Tev1 is cached in /data/.hf
```

**Local LLM for Phase III** (optional; without it the grounded parser answers):

```bash
ollama pull qwen2.5-coder:3b
```
```bash
cd backend && KG2A_TRANSLATOR=ollama uv run kg2analyzer serve --kgs /path/to/my_kgs
```

## Developer API

```python
# cd backend && uv run python
from kg2analyzer.analyzer import KG2Analyzer

builder = KG2Analyzer()
builder.ingest_paths(["my_kgs/"])          # KG2MD notebook per KG (Tev1) -> MDKG, identity links discovered
files = builder.mdkg_files()               # {"sales/fact_classes/<cube>/mdkg_dataset.nq": b"...", ...}

az = KG2Analyzer()
az.load_mdkgs(read_paths(["mdkg/"]))       # from kg2analyzer.ingest import read_paths
az.cross_cube(("sales", "customer", "amount"), ("finance", "trader", "tradeAmount"))   # pushdown
az.olap("sales", "amount", group_by=[("product", "Category")])
az.communities("identity", "louvain")
az.ask("Total sales by product category")
```

REST docs are at `/docs`. Every endpoint takes `?ws=build|query|ask` (default `build`): the three sections are separate workspaces. `/sparql` and `/sparql/{kg}` implement the SPARQL 1.1 Protocol, so one KG2Analyzer can federate another (`POST /api/remote`).

## Reproducing the thesis results

The thesis benchmark KGs live in `backend/tests/fixtures/` (test data only; the app never loads them). `cd backend && uv run pytest tests/test_thesis_tables.py -q` checks these results with the built-in engine; the notebook-built MDKGs reach the same cross-KG numbers (`tests/test_mdkg_files.py`, and with real Tev1 `KG2A_TEST_TEV1=1 uv run pytest tests/test_tev1.py`; on CPU, Tev1 selects 7/7 fact classes with 200 observations, 22 measures and 100% preservation in about 100 s):

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
  kg2analyzer/      Python package: analyzer.py (entry point), kg2md/notebook/ (the KG2MD notebook + runner),
                    mdkg_files.py (reads its output), kg2md/ (built-in engine), nl/, store, planner, olap, linking, graphml, server
  models/           trained measure-classifier pipelines of the built-in engine (joblib)
  tests/            seam tests incl. the thesis tables; fixtures/ holds the thesis benchmark KGs
frontend/
  src/api/          typed API client + TanStack Query hooks
  src/pages/        the three steps: Build (KGs → MDKGs), Query (builder + SPARQL), Ask (NL chat)
  src/components/   ui/ (shadcn), kit.tsx (app wrappers), fx.tsx (motion/GSAP effects), MdkgMap (Sigma), Pipeline
docs/adr/           architecture decisions        GLOSSARY.md   domain language
.claude/skills/     Matt Pocock's engineering skills (tdd, code-review, to-spec, ...)
```

The Phase I research notebook lives in [miskatul-anwar/KG2MD](https://github.com/miskatul-anwar/KG2MD); refresh the bundled copy with `cd backend && uv run kg2analyzer sync-notebook /path/to/KG2MD_ML_Explainable_Otsu_MultiFact.ipynb`.
