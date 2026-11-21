import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CatalogCube } from "./client";

export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: api.status });
export const useCatalog = () => useQuery({ queryKey: ["catalog"], queryFn: api.catalog });

export function useCube(kg: string): CatalogCube | undefined {
  const { data } = useCatalog();
  return data?.cubes.find((c) => c.kg === kg);
}

/** Invalidate everything derived from the store after it changes. */
export function useRefreshStore() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}
