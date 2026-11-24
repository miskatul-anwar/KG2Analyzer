# Tev1 and the LLM can be switched off, with fast paths for demos

Reviewers should not wait minutes for a demo. On 4 CPU cores Tev1 needs about 3 s per question (a small KG asks 10 to 25 questions), and a 3B LLM on CPU takes seconds per query.

- **Build** takes a `decider` per request (`tev1` | `structural`), set by a switch in the UI. Off, the structural stand-in decides; reports say "not Tev1". Asking for Tev1 when it is not installed is a 400 with the install command.
- **Tev1 answers are cached on disk** (`CachedDecider`, keyed by model, question and profile). Tev1 is deterministic for a profile, so a cached answer is the answer it would give. Rebuilding the tiny demo KGs takes 0.3 s instead of 72 s. `KG2A_TEV1_CACHE=off` disables the cache.
- **Ask** has an LLM switch. Off, only the grounded parser answers. When its exact-word matching misses, it now matches by meaning (model2vec static embeddings, `minishlab/potion-base-8M`: about 30 MB, no PyTorch, milliseconds per question) and by spelling (character n-gram TF-IDF, offline). We chose model2vec over sentence-transformers so that the embedding path needs no PyTorch. It can choose a KG only from what a question measures, and only for analytic requests, so out-of-scope questions are still rejected.
- Tev1 and the embedding model **preload** in one background thread at server start (one after the other: importing them concurrently failed). Answers are remembered per question until the MDKGs or the translator change.
