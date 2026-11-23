import { useEffect, useSyncExternalStore } from "react";
import { useUi } from "@/store";

export type Theme = "light" | "dark";

const media = () => window.matchMedia("(prefers-color-scheme: dark)");
const subscribe = (cb: () => void) => { const m = media(); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); };

/** Effective theme: the viewer's choice (persisted) or else the OS setting. Applies the `dark` class. */
export function useTheme(): [Theme, () => void] {
  const chosen = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const osDark = useSyncExternalStore(subscribe, () => media().matches, () => false);
  const theme: Theme = chosen ?? (osDark ? "dark" : "light");
  useEffect(() => { document.documentElement.classList.toggle("dark", theme === "dark"); }, [theme]);
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")];
}
