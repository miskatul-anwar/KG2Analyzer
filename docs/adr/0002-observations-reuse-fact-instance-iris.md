# Observations reuse the fact instance IRI and the source predicates

Each materialised `qb:Observation` uses its source fact instance's IRI and keeps the original dimension/measure predicates (e.g. `retail#customer`, `retail#saleTotalAmount`), rather than minting new observation IRIs and `mdkg:*_measure` properties as the notebook does. Two benefits follow. The observation-to-fact bijection becomes trivially auditable. And queries written against the source vocabulary (the thesis' Listings 3.1 and A.3) run unchanged. The QB4OLAP structure lives in a separate schema graph per KG.
