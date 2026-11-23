import clsx from "clsx";
import {
  Boxes, Database, GitMerge, Layers, MessageSquareText, Moon, Network, Sun, Terminal,
} from "lucide-react";
import { lazy, Suspense } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useStatus } from "@/api/hooks";
import { Spinner } from "@/components/ui";
import { useTheme } from "@/lib/theme";
const AskPage = lazy(() => import("@/pages/Ask"));
const CrossPage = lazy(() => import("@/pages/Cross"));
const GraphPage = lazy(() => import("@/pages/Graph"));
const Kg2mdPage = lazy(() => import("@/pages/Kg2md"));
const OlapPage = lazy(() => import("@/pages/Olap"));
const SparqlPage = lazy(() => import("@/pages/Sparql"));
const WorkspacePage = lazy(() => import("@/pages/Workspace"));

const NAV = [
  { to: "/workspace", label: "Workspace", icon: Database, hint: "Load KGs" },
  { to: "/kg2md", label: "KG2MD", icon: Boxes, hint: "Phase I · cubes" },
  { to: "/olap", label: "OLAP", icon: Layers, hint: "Roll-up · slice · dice" },
  { to: "/cross", label: "Cross-KG", icon: GitMerge, hint: "Phase II · pushdown" },
  { to: "/graph", label: "Links & Communities", icon: Network, hint: "Graph analytics" },
  { to: "/ask", label: "Ask", icon: MessageSquareText, hint: "Phase III · NL" },
  { to: "/sparql", label: "SPARQL", icon: Terminal, hint: "Console" },
];

export default function App() {
  const [theme, toggle] = useTheme();
  const { data: st } = useStatus();
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:w-60 md:border-r md:border-b-0">
        <div className="flex items-center justify-between gap-2 px-4 py-4">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-8" />
            <div>
              <div className="text-[15px] font-bold leading-tight">KG2Analyzer</div>
              <div className="text-[11px] text-ink-3">analytics across KGs</div>
            </div>
          </div>
          <button className="btn px-2" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
          {NAV.map(({ to, label, icon: Icon, hint }) => (
            <NavLink key={to} to={to} className={({ isActive }) => clsx(
              "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 transition",
              isActive ? "bg-accent/10 text-accent" : "text-ink-2 hover:bg-raised hover:text-ink",
            )}>
              <Icon className="size-4" />
              <span className="flex flex-col leading-tight">
                <span className="font-medium">{label}</span>
                <span className="hidden text-[11px] text-ink-3 md:block">{hint}</span>
              </span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-line px-4 py-3 text-[11px] leading-relaxed text-ink-3 md:block">
          {st ? (<>
            <div><b className="text-ink-2">{st.kgs.length}</b> KGs · <b className="text-ink-2">{st.cubes}</b> cubes</div>
            <div><b className="text-ink-2">{st.identity_links}</b> identity triples</div>
            <div className="truncate" title={st.translator}>translator: {st.translator}</div>
          </>) : "connecting…"}
          <a className="mt-1 block text-accent hover:underline" href="/docs" target="_blank" rel="noreferrer">API docs ↗</a>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <div className="mx-auto max-w-7xl">
          <Suspense fallback={<Spinner label="loading…" />}>
          <Routes>
            <Route path="/" element={<Navigate to="/workspace" replace />} />
            <Route path="/workspace" element={<WorkspacePage />} />
            <Route path="/kg2md" element={<Kg2mdPage />} />
            <Route path="/olap" element={<OlapPage />} />
            <Route path="/cross" element={<CrossPage />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/sparql" element={<SparqlPage />} />
            <Route path="*" element={<Navigate to="/workspace" replace />} />
          </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
