# KG2Analyzer

Multidimensional analytics and natural-language querying across knowledge graphs: raw RDF KGs are turned into QB4OLAP cubes, hosted as source-aware named graphs, joined across KGs without measure inflation, and queried in plain English.

## Language

### Phase I: KG2MD

**Raw KG**:
An input RDF/OWL knowledge graph with no multidimensional markup, given as a TBox and an ABox.
_Avoid_: source data, input graph

**TBox**:
The schema part of a raw KG: classes, properties and axioms (domain, range, subclass).
_Avoid_: ontology file, schema file (when the role is meant)

**ABox**:
The instance part of a raw KG: individuals, their types, links and literal values.
_Avoid_: data file, instances file (when the role is meant)

**Fact class**:
A class whose instances are measured events (sales, trades, readings); each instance becomes one observation.
_Avoid_: fact table, event class

**Decider**:
The model that answers KG2MD's four multiple-choice questions (fact class? aggregate function? unit of measure? level attribute?). In Build it is **Tev1** (`togethercomputer/Tev1-0.8B-experimental`), read from the next-token probabilities of the option letters. With Tev1 switched off, the **ML classifiers** decide (`ml`): logistic regressions over the meaning and spelling of class and property names and their structure, trained on a generated corpus, each answer explained. The **structural stand-in** (`structural`) uses simple rules only. Neither is ever presented as Tev1.
_Avoid_: classifier, LLM (for the decider)

**Fact probability** (p_c):
The decider's probability that a class is a fact class (Tev1's P(option A)), from the class profile the notebook shows it.
_Avoid_: fact score, confidence

**Structural guard**:
The notebook's check that keeps a class from becoming a fact class when most of its instances are referenced by other instances (dimension-like) or it has no measure and no link.

**Otsu threshold** (τ*):
The cut on fact probabilities that maximises between-class variance; classes with p_c ≥ τ* become cubes.

**Measure**:
A numeric datatype property of a fact class, with an additivity and an aggregate function.
_Avoid_: metric, KPI

**Additivity**:
Whether summing a measure across any dimension is meaningful (`additive`) or not (`non-additive`: rates, prices, temperatures).

**Level**:
A class whose members group observations (Customer, City, Month). The base level is the one observations link to directly.
_Avoid_: attribute, category

**Roll-up step**:
An object property mapping members of a child level to a parent level (City → Country).

**Hierarchy kind**:
One of the ADW4 patterns: balanced, recursive, ragged, alternative, parallel, nonstrict (plus unbalanced).

**Cube**:
A materialised QB4OLAP dataset: observations, measures, dimensions and hierarchies of one fact class.
_Avoid_: data cube

**MDKG**:
The multidimensional knowledge graph built from one raw KG: its QB4OLAP schema graph plus its observation graph, holding one cube per fact class.
_Avoid_: output graph, cube (a cube is one fact class inside an MDKG)

**MDKG file** (MDKG folder):
A saved MDKG, exactly as the KG2MD notebook writes it: `<kg>/factclass_selection.json`, `<kg>/kg2md.log` and per cube `<kg>/fact_classes/<FactClass>_<hash>/` with `mdkg_schema.ttl`, `mdkg_data.ttl` and the self-contained bundle `mdkg_dataset.nq` (source, schema and cube graphs). Optionally zipped with `identity.ttl`. The only thing the three sections exchange.
_Avoid_: export, dump

**Notebook run**:
One execution of the vendored KG2MD notebook's code cells on one KG's TBox + ABox (`kg2md.notebook.run_notebook`). Build is a notebook run per KG.

**Workspace**:
One section's own store (build, query or ask); workspaces never share state.
_Avoid_: session, project

**Delivery**:
The set of input files handed to the pipeline; it is grouped into raw KGs (one file, a TBox/ABox pair, a folder, or a zip) plus optional identity files.
_Avoid_: upload, batch

### Phase II: Multi-KG store

**Source**:
One KG's own endpoint (in-process or remote SPARQL), holding its schema graph and data graph.
_Avoid_: endpoint (when the KG is meant), silo

**Integrated mode**:
All sources' named graphs physically co-located in one Dataset and answered by one engine.

**Federated mode**:
Sub-queries shipped to each source; a mediator joins the partial results.

**Identity graph**:
The named graph of explicit `owl:sameAs` links between entities of different KGs.
_Avoid_: linkset, alignment

**Identity cluster**:
A connected component of the identity graph: one real-world entity across KGs.

**Cross-cube query**:
A query that combines measures from two cubes via the identity graph or a conformed dimension.

**Cartesian multiplication trap**:
Joining observations before aggregating, so an entity with m and n observations yields m × n rows and inflated totals.

**Pushdown pre-aggregation**:
Aggregating each cube at its native grain in an isolated sub-query before the join.

**Conformed dimension**:
A dimension whose members use the same IRIs in several KGs (the shared calendar), joinable without identity links.

### Graph analytics

**Projection**:
The graph a community algorithm runs on: `identity`, `members` (level members + sameAs) or `entities` (incl. observations).

**Link candidate**:
A scored pair of entities from two KGs that may denote the same thing; it becomes an identity link only when accepted.

### Phase III: NL interface

**Schema catalogue**:
The runtime inventory of datasets, measures, dimensions and roll-up steps read from the schema graphs.

**Compact alias**:
A short prefixed name for a catalogue IRI (`Retail:saleTotalAmount`).

**Translator**:
Anything that turns a question into a draft SPARQL query: an LLM (Ollama, OpenAI-compatible) or the grounded parser.

**Grounded parser**:
The deterministic translator that can only emit catalogue vocabulary; used offline and as the fallback after LLM retries.

**Embedding matcher**:
The grounded parser's fallback when a question's words are not the MDKG's own (`nl/semantic.py`): it matches phrases to catalogue measures, levels and KGs by meaning (model2vec embeddings) or by spelling (character n-grams), and only ever returns catalogue items. Used whenever the LLM is switched off or fails.

**Validation rules**:
Syntax, grounding, scope, safety; a draft runs only if all four pass.
