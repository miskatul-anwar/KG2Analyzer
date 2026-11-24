import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense, useEffect, useState } from "react";
import { PiCubeFocusDuotone, PiGraphDuotone } from "react-icons/pi";
import { TbChecks, TbMessageChatbot, TbMoon, TbRestore, TbSearch, TbSun, TbTable } from "react-icons/tb";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, type Ws } from "@/api/client";
import { useCatalog, useStatus } from "@/api/hooks";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Page } from "@/components/fx";
import { Spinner } from "@/components/kit";
import { Button } from "@/components/ui/button";
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { Toaster } from "@/components/ui/sonner";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { localName } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { useUi } from "@/store";

const BuildPage = lazy(() => import("@/pages/Build"));
const QueryPage = lazy(() => import("@/pages/Query"));
const AskPage = lazy(() => import("@/pages/Ask"));

const STEPS = [
  { to: "/build", n: 1, label: "Build MDKGs", hint: "KGs → multidimensional KGs", icon: PiCubeFocusDuotone },
  { to: "/query", n: 2, label: "Query", hint: "across MDKGs", icon: TbTable },
  { to: "/ask", n: 3, label: "Ask", hint: "in plain language", icon: TbMessageChatbot },
];

export default function App() {
  const [theme, toggle] = useTheme();
  const location = useLocation();
  const section = (["query", "ask"].find((w) => location.pathname.startsWith(`/${w}`)) ?? "build") as Ws;
  const { data: built } = useStatus("build");
  const { data: st } = useStatus(section);
  const qc = useQueryClient();
  const [palette, setPalette] = useState(false);
  const ready = (built?.cubes ?? 0) > 0;

  // Warm the caches every step needs, so switching steps is instant.
  useEffect(() => {
    void qc.prefetchQuery({ queryKey: ["build", "overview"], queryFn: api.overview, staleTime: Infinity });
    for (const ws of ["query", "ask"] as const) void qc.prefetchQuery({ queryKey: [ws, "mdkgs"], queryFn: () => api.mdkgs(ws), staleTime: Infinity });
  }, [qc]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <TooltipProvider delayDuration={250}>
      <div className="min-h-full">
        <header className="sticky top-0 z-30 border-b border-border bg-card/75 backdrop-blur-xl">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 md:px-6">
            <NavLink to="/" className="flex items-center gap-2.5">
              <img src="/favicon.svg" alt="" className="size-8" />
              <span className="text-[15px] font-bold tracking-tight">KG2Analyzer</span>
            </NavLink>
            <nav className="order-3 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto">
              {STEPS.map((s) => {
                const active = location.pathname.startsWith(s.to);
                const done = s.n === 1 && ready;
                return (
                  <NavLink key={s.to} to={s.to} className={clsx("relative flex shrink-0 items-center gap-2.5 rounded-xl px-3 py-1.5 transition-colors",
                    active ? "text-brand" : "text-ink-2 hover:text-ink")}>
                    {active && <motion.span layoutId="step-pill" className="absolute inset-0 rounded-xl bg-brand/10 ring-1 ring-brand/20" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                    <span className={clsx("relative flex size-6 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                      done ? "bg-good text-white" : active ? "bg-brand text-white" : "bg-raised text-ink-2")}>
                      {done ? <TbChecks className="size-3.5" /> : s.n}
                    </span>
                    <span className="relative flex flex-col leading-tight">
                      <span className="font-medium">{s.label}</span>
                      <span className="hidden text-[11px] text-ink-3 lg:block">{s.hint}</span>
                    </span>
                  </NavLink>
                );
              })}
            </nav>
            <div className="ml-auto flex items-center gap-2">
              <Button variant="outline" size="sm" className="hidden gap-2 text-ink-3 sm:inline-flex" onClick={() => setPalette(true)}>
                <TbSearch className="size-3.5" />Jump to…<Kbd>⌘K</Kbd>
              </Button>
              {st && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="hidden items-center gap-1.5 rounded-full bg-raised px-2.5 py-1 text-xs text-ink-2 md:inline-flex">
                      <PiGraphDuotone className="size-3.5 text-brand" />{st.cubes} cube{st.cubes === 1 ? "" : "s"} · {Math.floor(st.identity_links / 2)} links
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>{section === "build" ? "Built in step 1" : `Loaded in ${section}`}: {st.kgs.length} MDKGs{section === "ask" ? ` · NL translator: ${st.translator}` : section === "build" ? ` · KG2MD decider: ${st.decider}` : ""}</TooltipContent>
                </Tooltip>
              )}
              <ResetAll />
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">{theme === "dark" ? <TbSun /> : <TbMoon />}</Button>
                </TooltipTrigger>
                <TooltipContent>{theme === "dark" ? "Light" : "Dark"} theme</TooltipContent>
              </Tooltip>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 md:px-6">
          <ErrorBoundary key={location.pathname}>
          <Suspense fallback={<Spinner label="loading…" />}>
            <AnimatePresence mode="wait">
              <Routes location={location} key={location.pathname.split("/")[1]}>
                <Route path="/" element={<Navigate to="/build" replace />} />
                <Route path="/build" element={<Page><BuildPage /></Page>} />
                <Route path="/query" element={<Page><QueryPage /></Page>} />
                <Route path="/ask" element={<Page><AskPage /></Page>} />
                <Route path="*" element={<Navigate to="/build" replace />} />
              </Routes>
            </AnimatePresence>
          </Suspense>
          </ErrorBoundary>
        </main>
        <ErrorBoundary quiet><CommandPalette open={palette} onOpenChange={setPalette} /></ErrorBoundary>
        <Toaster richColors position="bottom-right" />
      </div>
    </TooltipProvider>
  );
}

/** Back to the very first state: all three sections emptied, selections, chat and switches cleared. */
function ResetAll() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const reset = useMutation({
    mutationFn: api.resetAll,
    onSuccess: async () => {
      useUi.getState().resetAll();
      qc.clear();
      setOpen(false);
      nav("/build", { replace: true });
      toast.success("Back to a clean start", { description: "Build, Query and Ask are empty. Files you saved are untouched." });
    },
  });
  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon" onClick={() => setOpen(true)} aria-label="Reset everything"><TbRestore /></Button>
        </TooltipTrigger>
        <TooltipContent>Reset everything</TooltipContent>
      </Tooltip>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Reset everything?</DialogTitle>
            <DialogDescription>
              All three sections go back to empty: built MDKGs, loaded MDKGs, identity links, query selections, the Ask chat
              and the Tev1/LLM switches. MDKG files you saved stay where they are.
            </DialogDescription>
          </DialogHeader>
          {reset.error && <p className="text-sm text-bad">{String(reset.error)}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={reset.isPending} onClick={() => reset.mutate()}>
              <TbRestore />{reset.isPending ? "Resetting…" : "Reset everything"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** ⌘K: jump to a step or open a measure in the query builder. */
function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate();
  const { data: cat } = useCatalog("query");
  const setQuery = useUi((s) => s.setQuery);
  const go = (fn: () => void) => { fn(); onOpenChange(false); };
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Jump to" description="Steps and measures">
      <Command>
      <CommandInput placeholder="Search steps and measures…" />
      <CommandList>
        <CommandEmpty>Nothing found.</CommandEmpty>
        <CommandGroup heading="Steps">
          {STEPS.map((s) => <CommandItem key={s.to} onSelect={() => go(() => nav(s.to))}><s.icon />{s.n}. {s.label}</CommandItem>)}
        </CommandGroup>
        {!!cat?.cubes.length && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Query a measure">
              {cat.cubes.flatMap((c) => c.measures.map((m) => (
                <CommandItem key={m.iri} value={`${c.kg} ${localName(m.iri)}`} onSelect={() => go(() => {
                  const d = c.dimensions[0];
                  setQuery({ kg: c.kg, measure: m.iri, groupBy: d ? `${d.prop}|${d.base_level}` : "", filterLevel: "", filterMember: "", aggregate: "", compareKg: "", compareMeasure: "", join: null });
                  useUi.getState().setQueryTab("builder");
                  nav("/query");
                })}>
                  <TbTable />{localName(m.iri)}<span className="ml-auto text-xs text-ink-3">{c.kg}</span>
                </CommandItem>
              )))}
            </CommandGroup>
          </>
        )}

      </CommandList>
      </Command>
    </CommandDialog>
  );
}
