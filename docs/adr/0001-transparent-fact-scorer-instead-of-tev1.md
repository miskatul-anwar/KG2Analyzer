# Transparent topological fact scorer as the default instead of the Tev1 LLM

_Status: superseded by [0008](0008-build-runs-the-kg2md-notebook.md) for Build. The scorer remains in the built-in engine (`run_kg2md`), which the thesis-table tests use._

The notebook scores fact classes with the 0.8B-parameter Tev1 checkpoint from Hugging Face, which needs torch, a download, and ideally a GPU. KG2Analyzer defaults to a fixed-weight logistic scorer over the profiler's topological features (numeric measures, outgoing links, referenced ratio, incoming link types, instance count). It returns per-feature logit contributions, so every decision can be explained. It also runs anywhere in milliseconds. Otsu thresholding stays unchanged. `FactScorer` is a Protocol, so Tev1 can be plugged back in as an adapter.

## Consequences

On Northwind the scorer selects only `Sales`. The thesis' Table 4.1 reports seven Tev1-selected classes (including Time, Year, Country). Results for that table therefore differ by design.
