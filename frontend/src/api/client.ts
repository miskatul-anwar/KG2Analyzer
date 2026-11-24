// Typed client for the KG2Analyzer FastAPI backend.

export type Row = Record<string, string | number | null>;

export interface Status {
  kgs: string[];
  graphs: { kg: string; graph: string; triples: number | null; remote?: boolean }[];
  cubes: number;
  identity_links: number;
  translator: string;
  decider: string;
  tev1_available: boolean;
  tev1_loaded: boolean;
  embeddings: string;
  llm: { server: string; model: string; reachable: boolean };
}

export interface CatalogMeasure { iri: string; label: string; aggregate: string; additivity: string; unit: string | null; source: string | null; alias: string }
export interface CatalogStep { child: string; parent: string; prop: string; many_to_many: boolean }
export interface CatalogDimension {
  prop: string; alias: string; name: string; base_level: string; kinds: string[]; levels: string[];
  level_names: Record<string, string>; steps: CatalogStep[];
}
export interface CatalogCube {
  kg: string; dataset: string; alias: string; fact_class: string; label: string; graph: string;
  measures: CatalogMeasure[]; dimensions: CatalogDimension[];
}
export interface Catalog { identity_links: number; prefixes: Record<string, string>; cubes: CatalogCube[]; prompt_context: string }

/** One answer of KG2MD's decision model (Tev1) to one of its four multiple-choice questions. */
export interface Decision {
  question: "fact_class" | "aggregate" | "unit" | "level_attribute";
  profile: Record<string, unknown>; prediction: string; confidence: number; probabilities: Record<string, number>;
  /** ML classifiers only: logit contribution of each feature group (name meaning, spelling, context, structure). */
  explanation?: Record<string, number>;
}
export interface ClassScore {
  iri: string; label: string; instances: number; probability: number; selected: boolean; excluded_by_guard: boolean;
  referenced_ratio: number; object_properties: number; numeric_properties: number;
}
export interface Audit {
  observations: number; source_facts: number | null; ghost_observations: number | null; dropped_facts: number | null;
  measure_cells_checked: number; measure_cells_mismatched: number; fact_preservation: number | null; measure_fidelity: number | null;
}
export interface MeasureReport {
  iri: string; name: string; unit: string | null; aggregate: string; additivity: string; source: string | null; decision: Decision | null;
}
export interface HierarchyReport { label: string | null; types: string[]; semantics: string | null; levels: string[]; steps: number }
export interface DimensionReport { uri: string; label: string; base_level: string | null; degenerate: boolean; hierarchies: HierarchyReport[] }
export interface CubeReport {
  fact_class: string; dataset: string; label: string; key: string | null; observations: number; audit: Audit;
  measures: MeasureReport[]; dimensions: DimensionReport[];
}
/** What the KG2MD notebook decided and built for one KG. */
export interface Phase1Report {
  kg: string; decider: string; seconds: number; otsu_threshold: number | null; classes: ClassScore[]; cubes: CubeReport[];
  decisions: Decision[]; undeclared_properties: string[]; separated_records: number; log: string;
}

export interface OlapResult { sparql: string; columns: string[]; rows: Row[]; warnings: string[] }

export interface GuardPair {
  left_entity: string; right_entity: string; left_observations?: number; right_observations?: number;
  naive_joined_rows: number; left_inflation?: number; right_inflation?: number;
}
export interface CrossResult {
  strategy: string; mode: string; rows: Row[]; seconds: number;
  plan: { sparql?: string; engine?: string; mediator?: string; subqueries?: Record<string, string>; transferred_rows?: Record<string, number> };
  guard: { cartesian_risk: boolean; pairs: GuardPair[]; max_inflation?: number };
}
export type CrossCompare = Record<"integrated/naive" | "integrated/pushdown" | "federated/naive" | "federated/pushdown", CrossResult>;

export interface Community { id: number; size: number; kgs: Record<string, number>; cross_kg: boolean; members: { iri: string; label: string | null; kg: string }[] }
export interface GraphNode { id: string; label: string; kg: string; community: number | null; observation: boolean }
export interface GraphEdge { source: string; target: string; kind: string }
export interface CommunityReport {
  algorithm: string; projection: string; modularity: number; communities: Community[]; nodes: number; edges: number;
  graph: { nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean };
}

export interface LinkCandidate {
  left: string; right: string; left_label: string | null; right_label: string | null; score: number;
  features: Record<string, number>; known: boolean;
}
export interface DiscoverResult {
  kg_a: string; kg_b: string; threshold: number;
  model: { model: string; pairs_scored: number; blocked_from: number; weights?: Record<string, number> };
  candidates: LinkCandidate[];
  evaluation_vs_identity_graph?: { precision: number; recall: number; f1: number; true_positives: number; predicted: number; gold: number };
}

export interface Check { rule: string; ok: boolean; message: string }
export interface Answer {
  question: string; status: "executed" | "fallback" | "rejected" | "error"; sparql: string; columns: string[]; rows: Row[];
  insight: string; seconds: number;
  attempts: { translator: string; sparql: string; ok: boolean; checks: Check[] }[];
  trace: { cubes?: string[]; measures?: string[]; aggregate?: string | null; group_by?: string[]; filters?: string[]; intent?: string;
    matches?: string[]; cached?: boolean };
}

export interface SparqlResult { columns: string[]; rows: Row[]; seconds: number }

export interface PipelineReport {
  kgs: {
    kg: string; files: string[]; triples: number; otsu_threshold: number | null; classes: number; decider?: string; seconds?: number;
    cubes: { fact_class: string; dataset: string; observations: number; measures: number; dimensions: number; fact_preservation: number | null; measure_fidelity: number | null }[];
  }[];
  identity: {
    supplied_files: string[]; supplied_links: number; auto_link: boolean; threshold: number; links_added: number; clusters: number;
    pairs: { kg_a: string; kg_b: string; links: { left: string; right: string; left_label: string | null; right_label: string | null; score: number }[] }[];
  };
  named_graphs: number;
  seconds: { parse: number; kg2md: number; linking: number; total: number };
}

export interface OverviewKg {
  kg: string; files: string[]; triples: number; otsu_threshold: number | null; classes: number; decider?: string; seconds?: number;
  tbox_files: string[]; abox_files: string[]; tbox_triples: number; abox_triples: number;
  undeclared_properties: string[]; warnings: string[];
  cubes: PipelineReport["kgs"][number]["cubes"];
}
export interface IdentityLink { left: string; right: string; left_label: string | null; right_label: string | null; left_kg: string; right_kg: string }
export interface Overview { kgs: OverviewKg[]; remote: string[]; identity: { links: IdentityLink[]; clusters: number } }
export interface Member { iri: string; label: string }
export interface JoinOption { left_dim: string; right_dim: string; link: "identity" | "shared"; aligned: number; label: string }

export interface LlmModel { name: string; size_gb: number; parameters: string | null; family: string | null; quantization: string | null; loaded: boolean }
export interface LlmModels { server: string; reachable: boolean; models: LlmModel[]; error: string | null; current: string }

export class ApiError extends Error {}

/** The three sections are independent backend workspaces. */
export type Ws = "build" | "query" | "ask";

export interface LoadedMdkg {
  kg: string; files: string[];
  cubes: { fact_class: string; dataset: string; observations: number; measures: number; dimensions: number }[];
}
export interface MdkgList { mdkgs: LoadedMdkg[]; identity_links: number; clusters: number }
export interface MdkgLoadReport {
  mdkgs: LoadedMdkg[];
  identity: { supplied_files: string[]; supplied_links: number; auto_link: boolean; links_added: number; total_links: number; clusters: number };
}

/** Append `ws=` to an API path (which may already carry a query string). */
export const withWs = (path: string, ws: Ws) => `${path}${path.includes("?") ? "&" : "?"}ws=${ws}`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (body as { detail?: unknown }).detail;
    throw new ApiError(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`);
  }
  return body as T;
}
const get = <T>(ws: Ws, path: string) => request<T>(withWs(path, ws));
const post = <T>(ws: Ws, path: string, body: unknown) =>
  request<T>(withWs(path, ws), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const upload = <T>(ws: Ws, path: string, form: FormData) => request<T>(withWs(path, ws), { method: "POST", body: form });

export const api = {
  status: (ws: Ws) => get<Status>(ws, "/api/status"),
  catalog: (ws: Ws) => get<Catalog>(ws, "/api/catalog"),
  reset: (ws: Ws) => post<{ reset: boolean }>(ws, "/api/reset", {}),
  /** Every section back to empty, as when the app was first opened. */
  resetAll: () => request<{ reset: Ws[] }>("/api/reset-all", { method: "POST" }),
  deleteKg: (ws: Ws, kg: string) => request<{ removed: string }>(withWs(`/api/kgs/${encodeURIComponent(kg)}`, ws), { method: "DELETE" }),
  // Build: raw KGs (TBox + ABox) -> MDKGs
  pipeline: (form: FormData) => upload<PipelineReport>("build", "/api/pipeline", form),
  overview: () => get<Overview>("build", "/api/overview"),
  phase1: (kg: string) => get<Phase1Report>("build", `/api/kgs/${encodeURIComponent(kg)}/phase1`),
  discover: (body: { kg_a: string; kg_b: string; threshold: number }) => post<DiscoverResult>("build", "/api/links/discover", body),
  addLinks: (pairs: [string, string][]) => post<{ links_added: number }>("build", "/api/links", { pairs }),
  mdkgFiles: (kg?: string) => get<{ files: { path: string; size: number }[] }>("build", `/api/mdkg/files${kg ? `?kg=${encodeURIComponent(kg)}` : ""}`),
  mdkgFileUrl: (path: string) => withWs(`/api/mdkg/file?path=${encodeURIComponent(path)}`, "build"),
  mdkgZipUrl: () => withWs("/api/mdkg.zip", "build"),
  identityUrl: () => withWs("/api/identity.ttl", "build"),
  // Query / Ask: load saved MDKG files, then analyse them
  loadMdkgs: (ws: Ws, form: FormData) => upload<MdkgLoadReport>(ws, "/api/mdkgs", form),
  mdkgs: (ws: Ws) => get<MdkgList>(ws, "/api/mdkgs"),
  /** Load the MDKGs currently built in Build into Query or Ask (no files to pick). */
  fromBuild: (ws: Exclude<Ws, "build">) => post<MdkgLoadReport>(ws, "/api/mdkgs/from-build", {}),
  olap: (body: { kg: string; measure: string; group_by: [string, string | null][]; filters: [string, string, string | null][]; aggregate: string | null }) =>
    post<OlapResult>("query", "/api/olap", body),
  compare: (body: { left: [string, string, string]; right: [string, string, string]; link: string }) =>
    post<CrossCompare>("query", "/api/crosscube/compare", body),
  members: (kg: string, dim: string, level: string | null) =>
    get<{ members: Member[] }>("query", `/api/members?${new URLSearchParams({ kg, dim, ...(level ? { level } : {}) })}`),
  joins: (a: string, b: string) => get<{ options: JoinOption[] }>("query", `/api/joins?${new URLSearchParams({ a, b })}`),
  sparql: (query: string, kg: string | null) => post<SparqlResult>("query", "/api/sparql", { query, kg }),
  ask: (question: string) => post<Answer>("ask", "/api/ask", { question }),
  suggestions: () => get<{ questions: string[] }>("ask", "/api/suggestions"),
  setTranslator: (spec: string) => post<{ translator: string }>("ask", "/api/translator", { spec }),
  /** The models installed in the Ollama server Ask uses. */
  llmModels: () => get<LlmModels>("ask", "/api/llm/models"),
};
