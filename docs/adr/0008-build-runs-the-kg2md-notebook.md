# Build runs the KG2MD notebook itself

The KG2MD notebook (miskatul-anwar/KG2MD) moved on from the thesis-era pipeline that KG2Analyzer had reimplemented: Tev1 now makes four decisions (fact class, aggregate function, unit property, level attribute), measured records that reuse a subject IRI are separated before parsing, a hierarchy engine classifies hierarchies, established vocabularies are used (`prov:wasDerivedFrom`, `skos:broader`, `mdkg:` only for gaps), and each cube is written as `fact_classes/<FactClass>_<hash>/` with a self-contained N-Quads bundle.

Build now executes the notebook's own code cells (`backend/kg2analyzer/kg2md/notebook/KG2MD.ipynb`, a verbatim copy) once per KG, with the TBox and ABox passed through the notebook's `KG2MD_TBOX_PATH` / `KG2MD_ABOX_PATH` / `KG2MD_OUTPUT_DIR` variables, and keeps the output folder unchanged as the MDKG files. We chose this over porting the logic into the package because a port drifts each time the notebook changes. Refreshing it is `uv run kg2analyzer sync-notebook <path>`.

Two cells do not run: the `%pip install` cell and the cell that loads Tev1. Tev1 is loaded once per process and injected as the notebook's `fact_decider` (the notebook's own `Tev1FactDecider` class), wrapped so every answer is recorded for the Build report. Cells compile without inheriting this package's `__future__` flags, in a registered module namespace, so they behave as in Jupyter.

## Consequences

- Tev1 needs `uv sync --extra tev1` (PyTorch, transformers ≥ 5.3, accelerate) and a 1.8 GB download on first use. Without it, Build fails with that instruction unless `KG2A_DECIDER=structural` selects the structural stand-in, which the report flags as "not Tev1". Tests use the stand-in at this seam. `tests/test_tev1.py` runs the real model (`KG2A_TEST_TEV1=1`): on CPU, Tev1 builds the seven benchmark MDKGs in about 100 s with the thesis' Query 23 totals.
- Query and Ask read the notebook layout: the catalogue finds the dataset in the data graph via `qb:structure` → bottom cuboid → `qb4o:isCuboidOf`, uses the `qb:DimensionProperty` IRIs on observations, follows `qb4o:HierarchyStep`s (except `mdkg:rollupToAll`), recovers each measure's source property from the bundle's source graph (the notebook lowercases it into `<name>_measure`), and identifies the fact class by the hash in the cube namespace.
- When an MDKG is loaded, its level members' literal descriptions (labels, names) are joined from the source graph into the hosted data graph, so results show member names and linking can compare them. The saved files are not changed.
- The notebook runs one KG at a time (it reads process-wide environment variables), under a lock. Each workspace has its own server lock, so a long Build does not block Query or Ask.
- The built-in engine (`run_kg2md`, `load_kg`, `engine="builtin"`) stays for the thesis-table reproduction tests.
