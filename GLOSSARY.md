# KG2Analyzer

Multidimensional analytics and natural-language querying across knowledge graphs: raw RDF KGs are turned into QB4OLAP cubes, hosted as source-aware named graphs, joined across KGs without measure inflation, and queried in plain English.

## Language

### Phase I: KG2MD

**Raw KG**:
An input RDF/OWL graph (TBox + ABox) with no multidimensional markup.
_Avoid_: source data, input graph

**Fact class**:
A class whose instances are measured events (sales, trades, readings); each instance becomes one observation.
_Avoid_: fact table, event class

**Fact probability** (p_c):
The scorer's probability that a class is a fact class, from its topological profile.
_Avoid_: fact score, confidence

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
_Avoid_: MDKG (use for the whole output), data cube

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

**Validation rules**:
Syntax, grounding, scope, safety; a draft runs only if all four pass.
