import { useQuery, useQueryClient } from "@tanstack/react-query";
import { registerNames } from "@/lib/format";
import { api, type CatalogCube, type Ws } from "./client";

// Store-derived data only changes after a mutation, which invalidates its workspace: never refetch on a timer.
const forever = { staleTime: Infinity, gcTime: Infinity } as const;
export const useStatus = (ws: Ws) => useQuery({
  queryKey: [ws, "status"], queryFn: () => api.status(ws), ...forever,
  // while Tev1 is still loading in the background, look again every few seconds
  refetchInterval: (q) => (q.state.data?.tev1_available && !q.state.data.tev1_loaded ? 3000 : false),
});
export const useCatalog = (ws: Ws) =>
  useQuery({ queryKey: [ws, "catalog"], queryFn: () => api.catalog(ws).then((c) => { registerNames(c); return c; }), ...forever });
export const useMdkgs = (ws: Ws) => useQuery({ queryKey: [ws, "mdkgs"], queryFn: () => api.mdkgs(ws), ...forever });
export const useOverview = () => useQuery({ queryKey: ["build", "overview"], queryFn: api.overview, ...forever });
export const useLlmModels = (enabled: boolean) =>
  useQuery({ queryKey: ["ask", "llm-models"], queryFn: api.llmModels, enabled, staleTime: 15_000, refetchOnWindowFocus: true });
export const useMembers = (kg: string, dim: string, level: string | null) =>
  useQuery({ queryKey: ["query", "members", kg, dim, level], queryFn: () => api.members(kg, dim, level), enabled: !!(kg && dim), ...forever });
export const useJoins = (a: string, b: string) =>
  useQuery({ queryKey: ["query", "joins", a, b], queryFn: () => api.joins(a, b), enabled: !!(a && b), ...forever });

export function useCube(ws: Ws, kg: string): CatalogCube | undefined {
  const { data } = useCatalog(ws);
  return data?.cubes.find((c) => c.kg === kg);
}

/** Invalidate everything derived from one workspace's store after it changes. */
export function useRefreshStore(ws: Ws) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: [ws] });
}
