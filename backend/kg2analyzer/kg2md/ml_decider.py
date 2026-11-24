"""ML decider: trained classifiers that answer KG2MD's four questions when Tev1 is switched off.

Same interface and result shape as the notebook's ``Tev1FactDecider`` (``decide``, ``decide_aggregate``,
``decide_unit_property``, ``decide_level_attribute``), so the notebook runs unchanged with it.

Each question has a logistic-regression classifier (scikit-learn) over
* the **meaning** of the names: model2vec embeddings (``minishlab/potion-base-8M``) of the class or
  property name and of its context (its links and measures, or its unit and datatype);
* the **spelling** of the names: hashed character n-grams (offline; ``-ment``, ``-tion``, ``reading``);
* the **structure**: instance, link and measure counts, values in [0, 1].
Without the embedding model (offline) a spelling-and-structure model of the same kind is used.

Every answer carries ``explanation``: how much the name, the context and the structure pushed the
decision (logit contributions), so it can be shown and checked. Training: ``uv run kg2analyzer
train-decider`` on the generated corpus (``decider_corpus``); the models ship in ``models/decider.joblib``.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import HashingVectorizer

MODEL_PATH = Path(os.environ.get("KG2A_DECIDER_MODEL", Path(__file__).resolve().parents[2] / "models" / "decider.joblib"))
CHAR = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=2 ** 12, alternate_sign=False, norm="l2")
WORD = HashingVectorizer(analyzer="word", ngram_range=(1, 2), n_features=2 ** 11, alternate_sign=False, norm="l2")
TASKS = {"fact_class": ("fact_class", "dimension_class"), "aggregate": ("sum", "avg", "min", "max"),
         "unit": ("unit_property", "other_property"), "level_attribute": ("attribute", "metadata")}
UNIT_THRESHOLD = 0.3  # the notebook's cut-off on P(unit)


def _words(text: Any) -> str:
    from kg2analyzer.kg2md.decider_corpus import split_words

    return split_words(text)


def parts(task: str, p: dict) -> tuple[str, str, list[float]]:
    """(name text, context text, structural features) of one profile."""
    if task == "fact_class":
        links = " ".join(_words(o.get("name", "")) for o in p.get("object_properties", []))
        measures = " ".join(_words(m.get("name", "")) for m in p.get("numeric_properties", []))
        n_obj, n_num = p.get("object_property_count", 0), p.get("numeric_property_count", 0)
        ctx = f"links {links} measures {measures}"
        return _words(p.get("class_name", "")), ctx, [
            math.log1p(p.get("instance_count", 0)) / 10, min(n_obj, 6) / 6, min(n_num, 6) / 6,
            float(n_obj >= 2), float(n_num > 0), float(n_obj == 0)]
    if task == "aggregate":
        dt = str(p.get("datatype", "")).rsplit("#", 1)[-1].lower()
        return _words(p.get("measure_name", "")), f"unit {_words(p.get('unit', ''))} type {dt}", [
            float(bool(p.get("values_between_0_and_1"))), float(dt in ("integer", "int", "long", "short", "nonnegativeinteger"))]
    if task == "unit":
        values = " ".join(_words(v) for v in p.get("example_values", []))
        return (_words(p.get("property_name", "")) + " " + _words(p.get("label", ""))).strip(), \
            f"values {values} range {_words(p.get('range', ''))}", []
    if task == "level_attribute":
        return _words(p.get("property_name", "")), f"type {_words(p.get('datatype', ''))}", []
    raise ValueError(task)


def _embedder():
    from kg2analyzer.nl.semantic import MODEL_ID, _model

    m = _model()
    return (m, MODEL_ID) if m is not None else (None, None)


def features(task: str, profiles: list[dict], embed) -> tuple[sparse.csr_matrix, list[tuple[str, int, int]]]:
    """Feature matrix and its column groups [(group, start, end)]."""
    rows = [parts(task, p) for p in profiles]
    names, ctxs, nums = [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]
    blocks, groups, col = [], [], 0

    def add(group: str, m) -> None:
        nonlocal col
        m = sparse.csr_matrix(m)
        blocks.append(m)
        groups.append((group, col, col + m.shape[1]))
        col += m.shape[1]

    if embed is not None:
        add("name (meaning)", np.asarray(embed.encode(names), dtype=float))
        add("context (meaning)", np.asarray(embed.encode(ctxs), dtype=float))
    add("name (spelling)", CHAR.transform(names))
    add("context (words)", WORD.transform(ctxs))
    if nums and nums[0]:
        add("structure", np.asarray(nums, dtype=float))
    return sparse.hstack(blocks).tocsr(), groups


class MLDecider:
    """KG2MD's decision questions answered by the trained classifiers (not Tev1)."""

    def __init__(self, path: Path | None = None):
        import joblib

        self.bundle = joblib.load(path or MODEL_PATH)
        embed, model_id = _embedder()
        self.variant = "embedding" if embed is not None and model_id == self.bundle["embedding_model"] else "spelling"
        self.embed = embed if self.variant == "embedding" else None
        self.model_id = f"ML classifiers ({self.variant} + structure; not Tev1)"

    def _ask(self, task: str, profile: dict) -> dict:
        clf = self.bundle["models"][task][self.variant]
        x, groups = features(task, [profile], self.embed)
        proba = clf.predict_proba(x)[0]
        probs = {str(c): float(p) for c, p in zip(clf.classes_, proba)}
        probs = {k: probs.get(k, 0.0) for k in TASKS[task]}
        pred = max(probs, key=lambda k: probs[k])
        # logit contributions of each feature group towards the predicted class
        k = list(clf.classes_).index(pred)
        coef = clf.coef_[0] * (1 if k == 1 else -1) if clf.coef_.shape[0] == 1 else clf.coef_[k]
        row = x.toarray()[0]
        explanation = {g: round(float(row[a:b] @ coef[a:b]), 3) for g, a, b in groups}
        return {"prediction": pred, "confidence": probs[pred], "probabilities": probs, "backend": "sklearn",
                "model": self.model_id, "explanation": explanation}

    def decide(self, profile: dict) -> dict:
        return self._ask("fact_class", profile)

    def decide_aggregate(self, profile: dict) -> dict:
        return self._ask("aggregate", profile)

    def decide_unit_property(self, profile: dict, threshold: float | None = None) -> dict:
        res = self._ask("unit", profile)
        cut = threshold if threshold is not None else float(os.environ.get("KG2MD_UNIT_THRESHOLD", UNIT_THRESHOLD))
        res["prediction"] = "unit_property" if res["probabilities"]["unit_property"] >= cut else "other_property"
        res["confidence"] = res["probabilities"][res["prediction"]]
        return res

    def decide_level_attribute(self, profile: dict) -> dict:
        return self._ask("level_attribute", profile)


def train(path: Path | None = None, seed: int = 7, report: bool = True) -> dict:
    """Train every classifier (both variants) on the generated corpus and save them. Returns held-out scores."""
    import random

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    from kg2analyzer.kg2md import decider_corpus as dc

    embed, model_id = _embedder()
    if embed is None:
        raise RuntimeError("training needs the model2vec embedding model (network access on first use)")
    data = dc.corpus(seed)
    # generalisation check for the fact question: classes whose base names were never seen in training
    rng = random.Random(seed)
    ev, en = dc.EVENTS[:], dc.ENTITIES[:]
    rng.shuffle(ev)
    rng.shuffle(en)
    seen = (ev[: int(len(ev) * 0.75)], en[: int(len(en) * 0.75)])
    unseen = (ev[int(len(ev) * 0.75):], en[int(len(en) * 0.75):])
    fact_seen = dc.fact_examples(random.Random(seed + 1), 3000, seen)
    fact_unseen = dc.fact_examples(random.Random(seed + 2), 800, unseen)

    models, scores = {}, {}
    for task, rows in data.items():
        profiles, labels = [r[0] for r in rows], [r[1] for r in rows]
        models[task] = {}
        for variant, emb in (("embedding", embed), ("spelling", None)):
            def fit(ps, ys, emb=emb):
                x, _ = features(task, ps, emb)
                return LogisticRegression(C=2.0, max_iter=4000).fit(x, ys)

            if task == "fact_class":
                held = fit([r[0] for r in fact_seen], [r[1] for r in fact_seen])
                xu, _ = features(task, [r[0] for r in fact_unseen], emb)
                scores[f"{task}/{variant}/unseen-names"] = round(float(held.score(xu, [r[1] for r in fact_unseen])), 4)
            ptr, pte, ytr, yte = train_test_split(profiles, labels, test_size=0.2, random_state=seed, stratify=labels)
            held = fit(ptr, ytr)
            xt, _ = features(task, pte, emb)
            scores[f"{task}/{variant}/held-out"] = round(float(held.score(xt, yte)), 4)
            models[task][variant] = fit(profiles, labels)
    bundle = {"models": models, "embedding_model": model_id, "seed": seed, "scores": scores}
    out = path or MODEL_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out, compress=3)
    if report:
        for k, v in scores.items():
            print(f"{k:45} {v:.4f}")
        print(f"saved {out} ({out.stat().st_size / 1024:.0f} KB)")
    return scores
