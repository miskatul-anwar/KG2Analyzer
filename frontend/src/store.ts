import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { Answer, JoinOption } from "@/api/client";

/** UI state that survives navigation and reloads (per browser). Data itself lives in TanStack Query. */
export interface QuerySel {
  kg: string;
  measure: string; // IRI
  groupBy: string; // `${dimIRI}|${levelIRI}` or "" for a grand total
  aggregate: string; // "" = catalogue default
  filterLevel: string; // `${dimIRI}|${levelIRI}` or ""
  filterMember: string; // member IRI or ""
  compareKg: string; // "" = no comparison
  compareMeasure: string;
  join: JoinOption | null;
  mode: "integrated" | "federated";
}

export const EMPTY_QUERY: QuerySel = {
  kg: "", measure: "", groupBy: "", aggregate: "", filterLevel: "", filterMember: "",
  compareKg: "", compareMeasure: "", join: null, mode: "integrated",
};

const DEFAULT_SPARQL = "PREFIX qb: <http://purl.org/linked-data/cube#>\nSELECT ?g (COUNT(?o) AS ?observations)\nWHERE { GRAPH ?g { ?o a qb:Observation } }\nGROUP BY ?g ORDER BY DESC(?observations)";

interface UiState {
  theme: "light" | "dark" | null; // null = follow the OS
  setTheme: (t: "light" | "dark") => void;
  query: QuerySel;
  setQuery: (patch: Partial<QuerySel>) => void;
  queryTab: "builder" | "sparql";
  setQueryTab: (t: "builder" | "sparql") => void;
  sparql: string;
  setSparql: (q: string) => void;
  openKg: string;
  setOpenKg: (kg: string) => void;
  chat: Answer[];
  pushAnswer: (a: Answer) => void;
  clearChat: () => void;
  resetForNewData: () => void;
  /** Everything back to the first-visit defaults (the theme is kept). */
  resetAll: () => void;
  /** Build: decide with Tev1 (true) or the structural stand-in (false). null = Tev1 when installed. */
  useTev1: boolean | null;
  setUseTev1: (v: boolean) => void;
  /** Ask: try the LLM first (true) or only the grounded parser with embeddings (false). */
  useLlm: boolean;
  setUseLlm: (v: boolean) => void;
}

const safeStorage = createJSONStorage(() => {
  try {
    const k = "__kg2a_probe__";
    localStorage.setItem(k, "1");
    localStorage.removeItem(k);
    return localStorage;
  } catch {
    const mem = new Map<string, string>();
    return { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => void mem.set(k, v), removeItem: (k) => void mem.delete(k) };
  }
});

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      theme: null,
      setTheme: (theme) => set({ theme }),
      query: EMPTY_QUERY,
      setQuery: (patch) => set((s) => ({ query: { ...s.query, ...patch } })),
      queryTab: "builder",
      setQueryTab: (queryTab) => set({ queryTab }),
      sparql: DEFAULT_SPARQL,
      setSparql: (sparql) => set({ sparql }),
      openKg: "",
      setOpenKg: (openKg) => set({ openKg }),
      chat: [],
      pushAnswer: (a) => set((s) => ({ chat: [...s.chat, a].slice(-30) })),
      clearChat: () => set({ chat: [] }),
      resetForNewData: () => set({ query: EMPTY_QUERY, openKg: "", chat: [] }),
      useTev1: null,
      setUseTev1: (useTev1) => set({ useTev1 }),
      useLlm: false,
      setUseLlm: (useLlm) => set({ useLlm }),
      resetAll: () => set({ query: EMPTY_QUERY, queryTab: "builder", sparql: DEFAULT_SPARQL, openKg: "", chat: [], useTev1: null, useLlm: false }),
    }),
    { name: "kg2analyzer-ui", version: 1, storage: safeStorage },
  ),
);
