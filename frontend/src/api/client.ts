// Typed client for the KG2Analyzer FastAPI backend.

export type Row = Record<string, string | number | null>;

export interface Status {
  kgs: string[];
  graphs: { kg: string; graph: string; triples: number | null; remote?: boolean }[];
  cubes: number;
  identity_links: number;
  translator: string;
}

export interface CatalogMeasure { iri: string; label: string; aggregate: string; additivity: string; unit: string | null; alias: string }
export interface CatalogStep { child: string; parent: string; prop: string; many_to_many: boolean }
export interface CatalogDimension { prop: string; alias: string; base_level: string; kinds: string[]; levels: string[]; steps: CatalogStep[] }
export interface CatalogCube {
  kg: string; dataset: string; alias: string; fact_class: string; label: string; graph: string;
  measures: CatalogMeasure[]; dimensions: CatalogDimension[];
}
export interface Catalog { identity_links: number; prefixes: Record<string, string>; cubes: CatalogCube[]; prompt_context: string }

export interface ClassScore {
  iri: string; label: string; instances: number; probability: number; selected: boolean;
  features: Record<string, number>; contributions: Record<string, number>;
}
export interface MeasureReport {
  iri: string; name: string; unit: string | null; datatype: string; additivity: string; p_additive: number;
  aggregate: string; shap: [string, number][]; lime: [string, number][];
}
export interface DimensionReport {
  prop: string; name: string; base_level: string; kinds: string[]; paths: string[][];
  steps: { child: string; parent: string; prop: string; coverage: number; many_to_many: boolean }[];
}
export interface CubeReport {
  fact_class: string; dataset: string; label: string; observations: number;
  audit: { source_facts: number; observations: number; ghost_observations: number; dropped_facts: number;
    measure_cells_checked: number; measure_cells_mismatched: number; fact_preservation: number; measure_fidelity: number };
  measures: MeasureReport[]; dimensions: DimensionReport[];
}
export interface Phase1Report {
  kg: string; closure_added_triples: number; scorer: string; otsu_threshold: number;
  otsu_curve: [number, number][]; classes: ClassScore[]; cubes: CubeReport[];
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
  trace: { cubes?: string[]; measures?: string[]; aggregate?: string | null; group_by?: string[]; filters?: string[]; intent?: string };
}

export interface SparqlResult { columns: string[]; rows: Row[]; seconds: number }

export interface EvalReport {
  load_seconds: number;
  domain_telemetry: { domain: string; fact_class: string; fact_score: number; otsu_tau: number; observations: number; measures: number; fact_preservation: number; measure_fidelity: number }[];
  query23: Record<string, Record<string, { retail: string; finance: string } | number>>;
  identity_communities: { count: number; sizes: number[]; modularity: number };
  nl_benchmark: {
    translator: string; questions: number; model_generated_executed: number; fallback_executed: number; rejected: number;
    execution_rate: number; correct_outcome_rate: number; mean_latency_seconds: number;
    outcomes: { id: string; question: string; expected: string; status: string; rows: number; correct_outcome: boolean; seconds: number }[];
  };
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (body as { detail?: unknown }).detail;
    throw new ApiError(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`);
  }
  return body as T;
}
const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  status: () => request<Status>("/api/status"),
  catalog: () => request<Catalog>("/api/catalog"),
  loadBenchmark: (which: "enterprise" | "northwind") => post<{ seconds: number }>("/api/benchmark", { which, reset: true }),
  uploadKg: (form: FormData) => request<Phase1Report>("/api/kgs", { method: "POST", body: form }),
  deleteKg: (kg: string) => request<{ removed: string }>(`/api/kgs/${encodeURIComponent(kg)}`, { method: "DELETE" }),
  uploadIdentity: (form: FormData) => request<{ links_added: number }>("/api/identity", { method: "POST", body: form }),
  attachRemote: (name: string, url: string) => post<{ attached: string }>("/api/remote", { name, url }),
  phase1: (kg: string) => request<Phase1Report>(`/api/kgs/${encodeURIComponent(kg)}/phase1`),
  olap: (body: { kg: string; measure: string; group_by: [string, string | null][]; filters: [string, string, string | null][]; aggregate: string | null }) =>
    post<OlapResult>("/api/olap", body),
  compare: (body: { left: [string, string, string]; right: [string, string, string]; link: string }) =>
    post<CrossCompare>("/api/crosscube/compare", body),
  communities: (body: { projection: string; algorithm: string; kgs: string[] | null }) => post<CommunityReport>("/api/communities", body),
  discover: (body: { kg_a: string; kg_b: string; threshold: number }) => post<DiscoverResult>("/api/links/discover", body),
  addLinks: (pairs: [string, string][]) => post<{ links_added: number }>("/api/links", { pairs }),
  ask: (question: string) => post<Answer>("/api/ask", { question }),
  setTranslator: (spec: string) => post<{ translator: string }>("/api/translator", { spec }),
  sparql: (query: string, kg: string | null) => post<SparqlResult>("/api/sparql", { query, kg }),
  evaluate: () => post<EvalReport>("/api/evaluate", {}),
};
