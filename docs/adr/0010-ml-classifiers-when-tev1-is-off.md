# ML classifiers decide when Tev1 is switched off

The structural stand-in scored fact classes by counting numeric properties and links. A richly described class of people (age, income, where they live and work), mostly not referenced by any event, then looked like a fact table and became a cube. Tev1 does not make that mistake because it reads what the classes are called.

With Tev1 off, Build now uses trained classifiers (`kg2md/ml_decider.py`), one per KG2MD question, with the notebook's decider interface:

- **Features:** model2vec embeddings of the class or property name and of its context (meaning), hashed character n-grams of the name (spelling), and the structural counts the notebook already passes.
- **Model:** scikit-learn logistic regression. Each answer reports the logit contribution of each feature group, and the Build report shows it.
- **Data:** a seeded, generated corpus (`kg2md/decider_corpus.py`) of profiles shaped exactly like the notebook's, labelled by construction. Half of the class examples share one structure between events and entities, so the name has to decide.
- **Offline:** without the embedding model, a spelling-and-structure variant of each classifier is used.

## Consequences

- On names absent from training and with deliberately uninformative structure, 81/100 event classes and 100/112 entity classes were classified correctly. Real KGs add structure and the notebook's structural guard.
- The whole test suite, including the thesis benchmark (7/7 fact classes, the Query 23 totals), passes with the classifiers deciding. `tests/test_ml_decider.py` keeps the people case: rules select Person, the classifiers select only Purchase.
- The models are 175 KB in `models/decider.joblib`, retrained with `uv run kg2analyzer train-decider`. The corpus is a hand-made vocabulary, so unusual domain words can still be misread. Tev1 remains the KG2MD decision model.
