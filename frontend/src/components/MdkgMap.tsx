/**
 * WebGL map of all MDKGs (Sigma.js + graphology + ForceAtlas2):
 * each fact cube is a hub, its dimension levels hang off it along the roll-up steps,
 * and shared entities are tied across MDKGs with owl:sameAs edges.
 */
import { ControlsContainer, FullScreenControl, SigmaContainer, useLoadGraph, useRegisterEvents, useSetSettings, useSigma, ZoomControl } from "@react-sigma/core";
import "@react-sigma/core/lib/style.css";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Catalog, IdentityLink } from "@/api/client";
import { cssVar, localName, SERIES } from "@/lib/format";
import { useTheme } from "@/lib/theme";

type Kind = "cube" | "level" | "entity";
interface NodeAttrs { label: string; kind: Kind; kg: string; size: number; color: string; x: number; y: number; detail: string }

function buildGraph(cat: Catalog, links: IdentityLink[], colors: Record<string, string>): Graph<NodeAttrs> {
  const g = new Graph<NodeAttrs>({ multi: false, type: "undirected" });
  const n = cat.cubes.length;
  cat.cubes.forEach((c, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, n);
    const cx = Math.cos(angle) * 10, cy = Math.sin(angle) * 10;
    const cube = `cube:${c.kg}`;
    g.mergeNode(cube, { label: `${c.kg} · ${localName(c.fact_class)}`, kind: "cube", kg: c.kg, size: 16, color: colors[c.kg], x: cx, y: cy,
      detail: `${c.measures.length} measures · ${c.dimensions.length} dimensions` });
    for (const d of c.dimensions) {
      for (const lvl of d.levels) {
        const id = `lvl:${c.kg}:${lvl}`;
        if (!g.hasNode(id)) {
          g.addNode(id, { label: localName(lvl), kind: "level", kg: c.kg, size: lvl === d.base_level ? 7 : 5, color: colors[c.kg],
            x: cx + (Math.random() - 0.5) * 4, y: cy + (Math.random() - 0.5) * 4, detail: `level of ${localName(d.prop)}` });
        }
      }
      g.mergeEdge(cube, `lvl:${c.kg}:${d.base_level}`, { size: 1.5, kind: "dimension" });
      for (const s of d.steps) {
        const a = `lvl:${c.kg}:${s.child}`, b = `lvl:${c.kg}:${s.parent}`;
        if (a !== b && g.hasNode(a) && g.hasNode(b)) g.mergeEdge(a, b, { size: 1, kind: "rollup" });
      }
    }
  });
  for (const l of links) {
    for (const [iri, label, kg] of [[l.left, l.left_label, l.left_kg], [l.right, l.right_label, l.right_kg]] as const) {
      if (!g.hasNode(iri)) {
        const hub = g.hasNode(`cube:${kg}`) ? g.getNodeAttributes(`cube:${kg}`) : { x: 0, y: 0 };
        g.addNode(iri, { label: label ?? localName(iri), kind: "entity", kg, size: 6, color: colors[kg] ?? cssVar("--c-ink-3"),
          x: hub.x + (Math.random() - 0.5) * 6, y: hub.y + (Math.random() - 0.5) * 6, detail: `entity in ${kg}` });
        if (g.hasNode(`cube:${kg}`)) g.mergeEdge(iri, `cube:${kg}`, { size: 0.5, kind: "member" });
      }
    }
    g.mergeEdge(l.left, l.right, { size: 2.5, kind: "sameAs" });
  }
  if (g.order > 1) forceAtlas2.assign(g, { iterations: 300, settings: { ...forceAtlas2.inferSettings(g), gravity: 1.2, scalingRatio: 6, barnesHutOptimize: g.order > 400 } });
  return g;
}

function Loader({ graph, onHover }: { graph: Graph<NodeAttrs>; onHover: (n: string | null) => void }) {
  const load = useLoadGraph();
  const register = useRegisterEvents();
  const setSettings = useSetSettings();
  const sigma = useSigma();
  const [hovered, setHovered] = useState<string | null>(null);
  useEffect(() => { load(graph); }, [graph, load]);
  useEffect(() => {
    register({
      enterNode: (e) => { setHovered(e.node); onHover(e.node); },
      leaveNode: () => { setHovered(null); onHover(null); },
    });
  }, [register, onHover]);
  useEffect(() => {
    const dim = cssVar("--c-line");
    const brand = cssVar("--c-brand");
    const sameAs = cssVar("--s2");
    setSettings({
      nodeReducer: (node, data) => {
        if (!hovered || node === hovered || sigma.getGraph().areNeighbors(node, hovered)) return { ...data, zIndex: 1, highlighted: node === hovered };
        return { ...data, color: dim, label: "", zIndex: 0 };
      },
      edgeReducer: (edge, data) => {
        const g = sigma.getGraph();
        const kind = g.getEdgeAttribute(edge, "kind");
        const base = { ...data, color: kind === "sameAs" ? sameAs : kind === "member" ? dim : cssVar("--c-ink-3") };
        if (hovered && !g.hasExtremity(edge, hovered)) return { ...base, hidden: kind !== "sameAs", color: dim };
        return hovered ? { ...base, color: kind === "sameAs" ? sameAs : brand, size: (data.size ?? 1) + 0.5 } : base;
      },
    });
  }, [hovered, setSettings, sigma]);
  return null;
}

export function MdkgMap({ cat, links, height = 460 }: { cat: Catalog; links: IdentityLink[]; height?: number }) {
  const [theme] = useTheme();
  const [hover, setHover] = useState<string | null>(null);
  // Sigma needs a laid-out container: mount it only once the box has a width (not mid page-transition).
  const box = useRef<HTMLDivElement>(null);
  const [sized, setSized] = useState(false);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSized(e.contentRect.width > 0 && e.contentRect.height > 0));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const colors = useMemo(() => Object.fromEntries(cat.cubes.map((c, i) => [c.kg, cssVar(SERIES[i % SERIES.length])])), [cat, theme]); // eslint-disable-line react-hooks/exhaustive-deps
  const graph = useMemo(() => buildGraph(cat, links, colors), [cat, links, colors]);
  const info = hover && graph.hasNode(hover) ? graph.getNodeAttributes(hover) : null;
  const settings = useMemo(() => ({
    labelColor: { color: cssVar("--c-ink-2") }, labelSize: 12, labelWeight: "500", labelFont: "Geist Variable, sans-serif",
    defaultEdgeColor: cssVar("--c-ink-3"), labelRenderedSizeThreshold: 6, zIndex: true, renderEdgeLabels: false, allowInvalidContainer: true,
  }), [theme]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={box} className="relative overflow-hidden rounded-xl border border-border bg-[radial-gradient(circle_at_center,var(--c-surface),var(--c-canvas))]" style={{ height }}>
      {/* The loader imports `graph` into Sigma's own instance; passing it here too would make the loader clear its own source. */}
      {sized && (
        <SigmaContainer key={theme} settings={settings} style={{ height: "100%", background: "transparent" }}>
          <Loader graph={graph} onHover={setHover} />
          <ControlsContainer position="bottom-right"><ZoomControl /><FullScreenControl /></ControlsContainer>
        </SigmaContainer>
      )}
      <div className="pointer-events-none absolute left-3 top-3 flex max-w-[70%] flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
        {cat.cubes.map((c) => (
          <span key={c.kg} className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: colors[c.kg] }} />{c.kg}</span>
        ))}
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded" style={{ background: "var(--s2)" }} />same entity (owl:sameAs)</span>
      </div>
      {info && (
        <div className="pointer-events-none absolute bottom-3 left-3 rounded-lg border border-border bg-card/95 px-3 py-2 text-xs shadow-md backdrop-blur">
          <div className="font-semibold text-ink">{info.label}</div>
          <div className="text-ink-3">{info.kind === "cube" ? "fact cube" : info.kind} · {info.detail}</div>
        </div>
      )}
    </div>
  );
}
