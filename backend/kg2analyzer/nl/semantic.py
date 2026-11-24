"""Embedding matcher for the grounded parser: maps the words of a question onto catalogue vocabulary
(KGs, measures, dimensions, levels) when they are not spelled the way the MDKG names them.

* **model2vec** static embeddings (``minishlab/potion-base-8M``, about 30 MB, no PyTorch, a few
  milliseconds per question): "money sent" ~ transferAmount, "charges" ~ fee, "town" ~ City.
* **character n-gram TF-IDF** (scikit-learn), always available and offline: catches typos and partial
  names ("catagory", "transfer amt").

A phrase matches an item when either similarity clears its threshold. Matching only ever returns
catalogue items, so the parser still cannot invent vocabulary.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

import numpy as np

MODEL_ID = os.environ.get("KG2A_EMBEDDING_MODEL", "minishlab/potion-base-8M")
SEMANTIC_MIN = float(os.environ.get("KG2A_EMBEDDING_MIN", "0.4"))
CHAR_MIN = 0.5
_LOCK = threading.Lock()
_STATE: dict = {"model": None, "failed": False}
STOP = {"the", "a", "an", "of", "in", "for", "by", "per", "and", "or", "to", "at", "on", "with", "what", "which",
        "is", "are", "was", "were", "show", "me", "give", "list", "each", "all", "how", "much", "many", "total",
        "sum", "average", "avg", "mean", "max", "maximum", "min", "minimum", "count", "number", "top", "their",
        "our", "my", "from", "between", "across", "both", "shared", "same", "who", "did", "do", "does", "has",
        "have", "it", "its", "this", "that", "these", "those", "please", "overall", "combined", "grouped",
        "broken", "down", "only", "highest", "lowest", "biggest", "smallest", "most", "least", "value", "values"}


def _model():
    """The model2vec model, loaded once; None when unavailable (not installed, offline, or disabled).
    A failed load is retried after a minute (e.g. the network came back)."""
    import time

    if _STATE["model"] is not None:
        return _STATE["model"]
    if _STATE["failed"] and time.time() - _STATE.get("failed_at", 0) < 60:
        return None
    with _LOCK:
        if _STATE["model"] is None:
            if os.environ.get("KG2A_EMBEDDINGS", "on").lower() in ("off", "0", "false", "no"):
                _STATE.update(failed=True, failed_at=float("inf"), error="switched off (KG2A_EMBEDDINGS=off)")
            else:
                try:
                    from model2vec import StaticModel

                    _STATE.update(model=StaticModel.from_pretrained(MODEL_ID), failed=False, error=None)
                except Exception as e:  # noqa: BLE001 - offline or missing: character n-grams still work
                    _STATE.update(failed=True, failed_at=time.time(), error=f"{type(e).__name__}: {e}"[:200])
    return _STATE["model"]


def preload() -> None:
    threading.Thread(target=_model, name="embedding-preload", daemon=True).start()


def embedding_backend() -> str:
    if _STATE["model"] is not None:
        return f"model2vec:{MODEL_ID} + char n-grams"
    return "char n-grams" if _STATE["failed"] else f"model2vec:{MODEL_ID} (loading) + char n-grams"


def words(text: str) -> str:
    """'transferAmount' / 'Category_..._level' -> 'transfer amount' / 'category'."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return " ".join(t for t in re.split(r"[^a-z0-9]+", text.lower()) if t)


def phrases(question: str, max_len: int = 3) -> list[str]:
    """Content n-grams of a question (stop words and aggregate words removed)."""
    toks = [t for t in re.split(r"[^a-z0-9]+", question.lower()) if t]
    out: list[str] = []
    for n in range(1, max_len + 1):
        for i in range(len(toks) - n + 1):
            gram = toks[i:i + n]
            if gram[0] in STOP or gram[-1] in STOP or (n == 1 and len(gram[0]) < 3):
                continue
            out.append(" ".join(gram))
    return out


@dataclass
class Match:
    key: object
    text: str
    phrase: str
    score: float
    how: str  # "embedding" | "spelling"

    def describe(self) -> str:
        return f"“{self.phrase}” ≈ {self.text} ({self.how} {self.score:.2f})"


class SemanticIndex:
    """Items (key, text) that phrases are matched against."""

    def __init__(self, items: list[tuple[object, str]]):
        self.items = [(k, words(t)) for k, t in items if words(t)]
        self._emb = None
        self._char = None

    def _embeddings(self, texts: list[str]):
        m = _model()
        if m is None:
            return None
        e = np.asarray(m.encode(texts), dtype=float)
        n = np.linalg.norm(e, axis=1, keepdims=True)
        n[n == 0] = 1
        return e / n

    def match(self, candidates: list[str], keys: set | None = None) -> Match | None:
        """The best (item, phrase) pair over ``candidates`` (phrases), or None below the thresholds."""
        items = [(k, t) for k, t in self.items if keys is None or k in keys]
        candidates = [c for c in dict.fromkeys(candidates) if c]
        if not items or not candidates:
            return None
        texts = [t for _, t in items]
        best: Match | None = None
        ie, pe = self._embeddings(texts), self._embeddings(candidates)
        if ie is not None and pe is not None:
            sim = pe @ ie.T
            i, j = np.unravel_index(int(np.argmax(sim)), sim.shape)
            if sim[i, j] >= SEMANTIC_MIN:
                best = Match(items[j][0], texts[j], candidates[i], float(sim[i, j]), "embedding")
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3)).fit(texts + candidates)
        a, b = vec.transform(candidates), vec.transform(texts)
        sim = (a @ b.T).toarray()
        i, j = np.unravel_index(int(np.argmax(sim)), sim.shape)
        if sim[i, j] >= CHAR_MIN and (best is None or sim[i, j] > best.score):
            best = Match(items[j][0], texts[j], candidates[i], float(sim[i, j]), "spelling")
        return best
