# KG2Analyzer

Monorepo: `backend/` (FastAPI + the `kg2analyzer` Python package) and `frontend/` (React 19 + TypeScript + Vite + Tailwind v4).

## Backend (`backend/`)

- `KG2Analyzer` in `kg2analyzer/analyzer.py` is the one entry point; `server.py`, `__main__.py` and the tests all go through it.
  - Phase I is the KG2MD notebook itself: `kg2md/notebook/KG2MD.ipynb` (verbatim copy; refresh with `kg2analyzer sync-notebook`) run cell by cell by `run_notebook` with Tev1 injected as `fact_decider` (ADR 0008). Never edit the vendored notebook here; change it in miskatul-anwar/KG2MD.
  - `mdkg_files.py` reads the notebook's output folders; the catalogue reads its QB4OLAP layout (`catalog._notebook_cubes`).
  - The built-in engine `kg2md/` (`run_kg2md`: profiling + Otsu, measures + SHAP/LIME, ADW4 hierarchies) stays for the thesis-table tests (`load_kg`, `engine="builtin"`).
  - Phase II `store.py`, `catalog.py`, `planner.py`, `olap.py`; graph analytics `graphml.py`, `linking.py`
  - Phase III `nl/` (validator, translators, interface; `semantic.py` is the embedding/spelling matcher the grounded parser falls back to when exact words miss)
- Ask's LLM: `GET /api/llm/models` lists Ollama's installed models (`KG2A_OLLAMA_URL`); `POST /api/translator {"spec": "ollama:<model>"}` selects and preloads one. The LLM drafts in a worker while the grounded parser answers; after `KG2A_LLM_BUDGET` s the parser's answer is used. Tests use a fake Ollama HTTP server (`tests/test_ask_llm.py`).
- Speed for demos: Tev1 answers are cached on disk (`CachedDecider`, `KG2A_CACHE_DIR`), Tev1 and the embedding model preload at server start (`KG2A_PRELOAD=0` disables), and `NLInterface` remembers answers until the MDKGs or translator change.
- Tev1 needs `uv sync --extra tev1`. With Tev1 off, `kg2md/ml_decider.py` answers (trained classifiers in `models/decider.joblib`, corpus in `kg2md/decider_corpus.py`, retrain with `kg2analyzer train-decider`); `structural` (simple rules) remains for comparison. Tests set `KG2A_DECIDER=ml` (tests/conftest.py); `tests/test_tev1.py` runs real Tev1 with `KG2A_TEST_TEV1=1`. Never present ML or rule results as Tev1.
- `models/*.joblib` are the built-in engine's measure classifiers; `kg2md/features.py` must stay compatible with how they were trained (keep its tag join sorted: unsorted set order made results depend on the hash seed).
- Input is a *set* of raw KGs, each with a **TBox and an ABox**: `ingest.py` assigns files to KGs and roles (explicit `<kg>/tbox|abox/` paths, name patterns, or a content split of combined files) and `KG2Analyzer.ingest` builds one MDKG per KG (`build_mdkg` → `run_notebook(tbox, abox)`) and auto-links them.
- The three sections are **separate workspaces** (`server.WORKSPACES`, `?ws=build|query|ask` on every endpoint). They share files, never state: Build saves MDKG folders as the notebook writes them (`mdkg_files`, `mdkg_zip`, identity.ttl); Query and Ask load them with `KG2Analyzer.load_mdkgs` (no KG2MD re-run), either from saved files or straight from Build (`/api/mdkgs/from-build`, which passes Build's files, not its state; the UI does it after every build). See ADR 0007.
- `server.py` serves `frontend/dist` (SPA fallback) when it exists.

## Frontend (`frontend/`)

- Three independent steps: **Build** (TBox + ABox per KG → MDKGs, saved via `lib/save.ts`), **Query** and **Ask**, each loading its own MDKG files through `components/MdkgLoader.tsx`. Every `api.*` call names its workspace. Community detection stays API-only (`/api/communities`).
- UI stack: shadcn/ui in `src/components/ui/` (generated, keep edits minimal), app wrappers in `src/components/kit.tsx`, motion/GSAP/Aceternity-style effects in `src/components/fx.tsx`, react-icons for icons, Sigma.js 3 + graphology for graphs (`MdkgMap.tsx`; Sigma 4 is a different API, see ADR 0006).
- UI state that must survive reloads (query selections, chat, open panel, theme) lives in the Zustand store `src/store.ts`; server data lives in TanStack Query with `staleTime: Infinity` (mutations invalidate everything).
- The brand colour token is `brand` (`text-brand`, `bg-brand`); `accent` is shadcn's subtle hover grey.

- `src/api/client.ts` holds the typed API surface: change it together with `server.py`.
- Data fetching goes through TanStack Query (`src/api/hooks.ts`); after a mutation that changes the store, call `useRefreshStore()`.
- Colours are semantic tokens in `src/index.css` (`bg-surface`, `text-ink-2`, series `--s1..--s8`); never hard-code hex in components. Categorical series follow the fixed palette order.

## Commands

Python is managed with **uv** (never pip): add dependencies with `uv add <pkg>` (dev: `uv add --dev <pkg>`) and commit `uv.lock`.

- Backend setup: `cd backend && uv sync --extra tev1` (without the extra: Query/Ask, and Build with `--decider structural`)
- Backend tests: `cd backend && uv run pytest -q` (all must pass before committing)
- Frontend checks: `cd frontend && npm run typecheck && npm run build`
- Build MDKGs: `cd backend && uv run kg2analyzer build <kgs...> --out mdkg`
- Dev: `cd backend && uv run kg2analyzer serve [--kgs <raw KGs>] [--mdkgs <saved MDKGs>]` (starts empty), then `cd frontend && npm run dev`
- Thesis tables: `cd backend && uv run pytest tests/test_thesis_tables.py -q`

## Conventions

- Test only at the agreed seams (the `KG2Analyzer` incl. `ingest`, `run_kg2md`, `otsu_threshold` and HTTP interfaces). Expected values come from the thesis, never recomputed by the code under test.
- Use `GLOSSARY.md` terms in code, UI copy, tests and issues.
- The store is read-only to every query path; never add an update route.
- The app ships no sample or placeholder KGs: benchmark KGs are test fixtures only (`backend/tests/fixtures/`), and UI defaults come from the loaded catalogue. The UI shows no example questions (keep Ask and ⌘K clean); `/api/suggestions` stays API-only.
- Build paths with `fileURLToPath` / `pathlib`, never `URL.pathname`: the app must run on Windows.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `miskatul-anwar/KG2Analyzer` (use `gh api` REST routes in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
