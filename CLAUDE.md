# KG2Analyzer

Monorepo: `backend/` (FastAPI + the `kg2analyzer` Python package) and `frontend/` (React 19 + TypeScript + Vite + Tailwind v4).

## Backend (`backend/`)

- `KG2Analyzer` in `kg2analyzer/analyzer.py` is the one entry point; `server.py`, `__main__.py` and the tests all go through it.
  - Phase I `kg2md/` (profiling + Otsu, measures + SHAP/LIME, ADW4 hierarchies, QB4OLAP pipeline)
  - Phase II `store.py`, `catalog.py`, `planner.py`, `olap.py`; graph analytics `graphml.py`, `linking.py`
  - Phase III `nl/` (validator, translators, interface)
- `models/*.joblib` are the trained measure classifiers; `kg2md/features.py` must stay compatible with how they were trained (keep its tag join sorted: unsorted set order made results depend on the hash seed).
- Input is a *set* of raw KGs: `ingest.py` groups files (single files, TBox/ABox pairs, per-KG folders, zips, owl:sameAs files) and `KG2Analyzer.ingest` builds one MDKG per KG and auto-links them.
- `server.py` serves `frontend/dist` (SPA fallback) when it exists.

## Frontend (`frontend/`)

- Three steps only: **Build** (KGs → MDKGs, `pages/Build.tsx`), **Query** across MDKGs (`pages/Query.tsx`), **Ask** in NL (`pages/Ask.tsx`). Community detection stays API-only (`/api/communities`).
- UI stack: shadcn/ui in `src/components/ui/` (generated, keep edits minimal), app wrappers in `src/components/kit.tsx`, motion/GSAP/Aceternity-style effects in `src/components/fx.tsx`, react-icons for icons, Sigma.js 3 + graphology for graphs (`MdkgMap.tsx`; Sigma 4 is a different API, see ADR 0006).
- UI state that must survive reloads (query selections, chat, open panel, theme) lives in the Zustand store `src/store.ts`; server data lives in TanStack Query with `staleTime: Infinity` (mutations invalidate everything).
- The brand colour token is `brand` (`text-brand`, `bg-brand`); `accent` is shadcn's subtle hover grey.

- `src/api/client.ts` holds the typed API surface: change it together with `server.py`.
- Data fetching goes through TanStack Query (`src/api/hooks.ts`); after a mutation that changes the store, call `useRefreshStore()`.
- Colours are semantic tokens in `src/index.css` (`bg-surface`, `text-ink-2`, series `--s1..--s8`); never hard-code hex in components. Categorical series follow the fixed palette order.

## Commands

Python is managed with **uv** (never pip): add dependencies with `uv add <pkg>` (dev: `uv add --dev <pkg>`) and commit `uv.lock`.

- Backend setup: `cd backend && uv sync`
- Backend tests: `cd backend && uv run pytest -q` (all must pass before committing)
- Frontend checks: `cd frontend && npm run typecheck && npm run build`
- Build MDKGs: `cd backend && uv run kg2analyzer build <kgs...> --out mdkg`
- Dev: `cd backend && uv run kg2analyzer serve --kgs <kgs...>` (starts empty without `--kgs`), then `cd frontend && npm run dev`
- Thesis tables: `cd backend && uv run pytest tests/test_thesis_tables.py -q`

## Conventions

- Test only at the agreed seams (the `KG2Analyzer` incl. `ingest`, `run_kg2md`, `otsu_threshold` and HTTP interfaces). Expected values come from the thesis, never recomputed by the code under test.
- Use `GLOSSARY.md` terms in code, UI copy, tests and issues.
- The store is read-only to every query path; never add an update route.
- The app ships no sample or placeholder KGs: benchmark KGs are test fixtures only (`backend/tests/fixtures/`), and UI defaults and example questions come from the loaded catalogue (`/api/suggestions`).
- Build paths with `fileURLToPath` / `pathlib`, never `URL.pathname`: the app must run on Windows.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `miskatul-anwar/KG2Analyzer` (use `gh api` REST routes in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
