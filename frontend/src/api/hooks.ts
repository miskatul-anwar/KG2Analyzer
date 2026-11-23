import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CatalogCube } from "./client";

// Store-derived data only changes after a mutation, which invalidates everything: never refetch on a timer.
const forever = { staleTime: Infinity, gcTime: Infinity } as const;
export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: api.status, ...forever });
export const useCatalog = () => useQuery({ queryKey: ["catalog"], queryFn: api.catalog, ...forever });
export const useOverview = () => useQuery({ queryKey: ["overview"], queryFn: api.overview, ...forever });
export const useSuggestions = () => useQuery({ queryKey: ["suggestions"], queryFn: api.suggestions, ...forever });
export const useMembers = (kg: string, dim: string, level: string | null) =>
  useQuery({ queryKey: ["members", kg, dim, level], queryFn: () => api.members(kg, dim, level), enabled: !!(kg && dim), ...forever });
export const useJoins = (a: string, b: string) =>
  useQuery({ queryKey: ["joins", a, b], queryFn: () => api.joins(a, b), enabled: !!(a && b), ...forever });

export function useCube(kg: string): CatalogCube | undefined {
  const { data } = useCatalog();
  return data?.cubes.find((c) => c.kg === kg);
}

/** Invalidate everything derived from the store after it changes. */
export function useRefreshStore() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}
