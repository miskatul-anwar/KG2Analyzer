"""Measure additivity classification with SHAP and LIME explanations (thesis 3.6.1, eq. 3.3-3.4).

Wraps the four trained scikit-learn pipelines shipped in ``models/``. The
pipelines are TF-IDF + logistic regression, so exact Shapley values are
available in closed form (linear SHAP with an all-zero background):
phi_j = w_j * x_j. LIME is implemented directly (token-dropout perturbations
plus a locally weighted ridge surrogate) so no extra dependency is needed.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from kg2analyzer.kg2md.features import build_text_representation, split_identifier_tokens

DEFAULT_MODELS_DIR = Path(os.environ.get("KG2MD_MODELS_DIR", Path(__file__).resolve().parents[2] / "models"))
AGG_IRIS = {
    "sum": "http://purl.org/qb4olap/cubes#sum",
    "avg": "http://purl.org/qb4olap/cubes#avg",
    "min": "http://purl.org/qb4olap/cubes#min",
    "max": "http://purl.org/qb4olap/cubes#max",
    "count": "http://purl.org/qb4olap/cubes#count",
}


@dataclass
class MeasureDecision:
    name: str
    representation: str
    additivity: str  # "additive" | "non-additive"
    additive_probability: float
    aggregate: str  # sum | avg | min | max | count
    shap: list[tuple[str, float]] = field(default_factory=list)  # top features, + pushes towards additive
    lime: list[tuple[str, float]] = field(default_factory=list)


class MeasureClassifier:
    """Loads the trained pipelines once; ``classify`` returns an explained decision."""

    def __init__(self, models_dir: str | Path | None = None):
        import joblib

        d = Path(models_dir) if models_dir else DEFAULT_MODELS_DIR
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.additivity = joblib.load(d / "measure_additivity_model.joblib")
            self.aggregate = joblib.load(d / "agg_func_model.joblib")
        for m in (self.additivity, self.aggregate):
            for _, step in m.steps:
                if not hasattr(step, "multi_class"):
                    step.multi_class = "auto"
        self._tfidf = self.additivity.named_steps["tfidf"]
        self._clf = self.additivity.named_steps["clf"]
        self._vocab_inv = {i: t for t, i in self._tfidf.vocabulary_.items()}
        # class index of "additive" (label 1)
        self._add_idx = list(self._clf.classes_).index(1)

    def _p_additive(self, reps: list[str]) -> np.ndarray:
        return self.additivity.predict_proba(reps)[:, self._add_idx]

    def classify(self, name: str, datatype: str = "xsd:decimal", unit: str | None = None,
                 bounded_0_1: bool = False, explain: bool = True) -> MeasureDecision:
        rep = build_text_representation(name, datatype=datatype, unit=unit or "none", is_bounded_0_1=int(bounded_0_1))
        p_add = float(self._p_additive([rep])[0])
        additive = p_add >= 0.5
        toks = " ".join(split_identifier_tokens(name))
        dt = str(datatype).replace(":", "_").lower()
        agg_rep = f"{toks} {toks} dt_{dt} unit_{(unit or 'none').lower()} {'bounded_interval' if bounded_0_1 else 'unbounded'}"
        agg = str(self.aggregate.predict([agg_rep])[0])
        if additive:
            agg = "sum"
        elif agg in ("sum", "count"):
            agg = "avg"  # summarizability: never sum a non-additive measure
        dec = MeasureDecision(name, rep, "additive" if additive else "non-additive", round(p_add, 4), agg)
        if explain:
            dec.shap = self.shap(rep)
            dec.lime = self.lime(rep)
        return dec

    def shap(self, rep: str, top: int = 6) -> list[tuple[str, float]]:
        """Exact linear SHAP values of the additive logit (zero background)."""
        x = self._tfidf.transform([rep])
        w = self._clf.coef_[0] * (1 if self._add_idx == 1 else -1)
        contrib = [(self._vocab_inv[j], float(w[j] * v)) for j, v in zip(x.indices, x.data)]
        contrib.sort(key=lambda t: -abs(t[1]))
        return [(t, round(v, 4)) for t, v in contrib[:top]]

    def lime(self, rep: str, samples: int = 300, top: int = 6, seed: int = 0) -> list[tuple[str, float]]:
        """LIME: drop random tokens, fit a proximity-weighted ridge surrogate on p(additive)."""
        tokens = rep.split()
        uniq = sorted(set(tokens))
        if not uniq:
            return []
        rng = np.random.default_rng(seed)
        z = rng.integers(0, 2, size=(samples, len(uniq)))
        z[0] = 1
        texts = [" ".join(t for t in tokens if row[uniq.index(t)]) for row in z]
        y = self._p_additive(texts)
        dist = 1 - z.sum(1) / len(uniq)
        wts = np.exp(-(dist ** 2) / 0.25)
        X = np.hstack([z, np.ones((samples, 1))])
        A = X.T @ (X * wts[:, None]) + 1e-2 * np.eye(X.shape[1])
        coef = np.linalg.solve(A, X.T @ (wts * y))[:-1]
        order = np.argsort(-np.abs(coef))[:top]
        return [(uniq[i], round(float(coef[i]), 4)) for i in order]
