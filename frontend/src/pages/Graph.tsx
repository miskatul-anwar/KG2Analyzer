import { useMutation } from "@tanstack/react-query";
import { Check, Network, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { api, type CommunityReport } from "@/api/client";
import { useRefreshStore, useStatus } from "@/api/hooks";
import { Card, Chip, DataTable, Empty, ErrorBox, Kpi, PageHeader, Select, Spinner } from "@/components/ui";
import { cssVar, localName, SERIES } from "@/lib/format";

const ALGORITHMS = [
  { value: "greedy_modularity", label: "Greedy modularity (Clauset–Newman–Moore)" },
  { value: "louvain", label: "Louvain" },
  { value: "label_propagation", label: "Label propagation" },
  { value: "sgc_kmeans", label: "SGC graph-neural embedding + k-means" },
];
const PROJECTIONS = [
  { value: "identity", label: "Identity graph (owl:sameAs)" },
  { value: "members", label: "Level members + sameAs" },
  { value: "entities", label: "All entities incl. observations" },
];

export default function GraphPage() {
  const { data: st } = useStatus();
  const kgs = st?.kgs ?? [];
  const refresh = useRefreshStore();
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  useEffect(() => {
    if (!kgs.includes(a) && kgs[0]) setA(kgs[0]);
    if (!kgs.includes(b) && kgs.length) setB(kgs[1] ?? kgs[0]);
  }, [kgs, a, b]);
  const [threshold, setThreshold] = useState(0.5);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [proj, setProj] = useState("identity");
  const [alg, setAlg] = useState("greedy_modularity");
  const [scope, setScope] = useState<string[]>([]);

  const discover = useMutation({
    mutationFn: api.discover,
    onSuccess: (r) => setPicked(new Set(r.candidates.map((c, i) => (c.score >= r.threshold && !c.known ? i : -1)).filter((i) => i >= 0))),
  });
  const accept = useMutation({ mutationFn: api.addLinks, onSuccess: refresh });
  const comm = useMutation({ mutationFn: api.communities });
  const kgOpts = kgs.map((k) => ({ value: k, label: k }));

  return (
    <>
      <PageHeader title="Links & communities" description="Discover owl:sameAs candidates between two KGs (blocking + label, literal and SGC graph-neural-embedding similarity; a logistic model is trained when links already exist), then partition the cross-KG graph into communities and score them by Newman modularity Q." />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Cross-KG node linking">
          <div className="flex flex-wrap items-end gap-2">
            <Select label="KG A" value={a} onChange={setA} options={kgOpts} />
            <Select label="KG B" value={b} onChange={setB} options={kgOpts} />
            <label className="label">Threshold<input className="input w-20" type="number" step={0.05} min={0} max={1} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} /></label>
            <button className="btn-primary" disabled={discover.isPending} onClick={() => discover.mutate({ kg_a: a, kg_b: b, threshold })}><Search className="size-4" />Discover</button>
            {discover.isPending && <Spinner />}
          </div>
          <ErrorBox error={discover.error} />
          {discover.data && (
            <div className="mt-3">
              <p className="mb-2 text-xs text-ink-3">
                {discover.data.model.model} · {discover.data.model.pairs_scored} blocked pairs of {discover.data.model.blocked_from}
                {discover.data.evaluation_vs_identity_graph && <> · vs identity graph P {discover.data.evaluation_vs_identity_graph.precision} R {discover.data.evaluation_vs_identity_graph.recall} F1 {discover.data.evaluation_vs_identity_graph.f1}</>}
              </p>
              <DataTable rows={discover.data.candidates.map((c, i) => ({ ...c, i }))} max={40} columns={[
                { key: "i", header: "", render: (c) => <input type="checkbox" disabled={c.known} checked={picked.has(c.i)} onChange={() => {
                  const n = new Set(picked); if (n.has(c.i)) n.delete(c.i); else n.add(c.i); setPicked(n); }} /> },
                { key: "left", header: a, render: (c) => <div><div>{c.left_label ?? localName(c.left)}</div><div className="mono text-ink-3">{localName(c.left)}</div></div> },
                { key: "right", header: b, render: (c) => <div><div>{c.right_label ?? localName(c.right)}</div><div className="mono text-ink-3">{localName(c.right)}</div></div> },
                { key: "score", header: "score", numeric: true, decimals: 3 },
                { key: "features", header: "signals", render: (c) => <div className="flex flex-wrap gap-1">{Object.entries(c.features).map(([k, v]) => <Chip key={k}>{k} {v}</Chip>)}</div> },
                { key: "known", header: "", render: (c) => c.known ? <Chip tone="good">linked</Chip> : null },
              ]} />
              <button className="btn-primary mt-3" disabled={!picked.size || accept.isPending}
                onClick={() => accept.mutate([...picked].map((i) => [discover.data!.candidates[i].left, discover.data!.candidates[i].right] as [string, string]))}>
                <Check className="size-4" />Add {picked.size} link(s) to the identity graph
              </button>
              {accept.data && <Chip tone="good">{accept.data.links_added} added</Chip>}
            </div>
          )}
        </Card>

        <Card title="Community detection">
          <div className="flex flex-wrap items-end gap-2">
            <Select label="Projection" value={proj} onChange={setProj} options={PROJECTIONS} />
            <Select label="Algorithm" value={alg} onChange={setAlg} options={ALGORITHMS} />
            <button className="btn-primary" disabled={comm.isPending} onClick={() => comm.mutate({ projection: proj, algorithm: alg, kgs: scope.length ? scope : null })}><Network className="size-4" />Detect</button>
            {comm.isPending && <Spinner />}
          </div>
          {proj !== "identity" && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="text-xs text-ink-3">KGs:</span>
              {kgs.map((k) => (
                <button key={k} onClick={() => setScope(scope.includes(k) ? scope.filter((x) => x !== k) : [...scope, k])}>
                  <Chip tone={scope.includes(k) ? "accent" : undefined}>{k}</Chip>
                </button>
              ))}
              <span className="text-xs text-ink-3">{scope.length ? "" : "(all)"}</span>
            </div>
          )}
          <ErrorBox error={comm.error} />
          {comm.data && <CommunityStats r={comm.data} />}
        </Card>
      </div>
      <Card className="mt-4" title="Graph" subtitle="Colour = community (or KG when there are more than 8 communities); dashed edges are owl:sameAs.">
        {comm.data ? <GraphView r={comm.data} /> : <Empty>Run community detection to draw the graph.</Empty>}
      </Card>
    </>
  );
}

function CommunityStats({ r }: { r: CommunityReport }) {
  return (
    <div className="mt-3">
      <div className="mb-3 flex flex-wrap gap-3">
        <Kpi value={r.communities.length} label="communities" />
        <Kpi value={r.modularity} label="modularity Q" />
        <Kpi value={r.communities.filter((c) => c.cross_kg).length} label="span several KGs" />
        <Kpi value={`${r.nodes} / ${r.edges}`} label="nodes / edges" />
      </div>
      <DataTable rows={r.communities} max={30} columns={[
        { key: "id", header: "#", numeric: true },
        { key: "size", header: "size", numeric: true },
        { key: "kgs", header: "KGs", render: (c) => <div className="flex flex-wrap gap-1">{Object.entries(c.kgs).map(([k, v]) => <Chip key={k}>{k}: {v}</Chip>)}</div> },
        { key: "members", header: "members", render: (c) => c.members.slice(0, 6).map((m) => m.label ?? localName(m.iri)).join(", ") + (c.size > 6 ? " …" : "") },
      ]} />
    </div>
  );
}

function GraphView({ r }: { r: CommunityReport }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    const el = box.current; if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth)); ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const byCommunity = r.communities.length <= 8;
  const kgs = useMemo(() => [...new Set(r.graph.nodes.map((n) => n.kg))], [r]);
  const colors = useMemo(() => SERIES.map(cssVar), [r]);
  const data = useMemo(() => ({
    nodes: r.graph.nodes.map((n) => ({ ...n })),
    links: r.graph.edges.map((e) => ({ ...e })),
  }), [r]);
  const ink = cssVar("--c-ink-2");
  const line = cssVar("--c-line");
  return (
    <div ref={box}>
      <ForceGraph2D graphData={data} width={width} height={520} backgroundColor="rgba(0,0,0,0)"
        nodeId="id" cooldownTicks={120}
        nodeLabel={(n) => `${n.label} · ${n.kg} · community ${n.community ?? "–"}`}
        linkColor={(l) => (l.kind === "sameAs" ? colors[1] : line)}
        linkLineDash={(l) => (l.kind === "sameAs" ? [4, 3] : null)}
        linkWidth={(l) => (l.kind === "sameAs" ? 2 : 1)}
        nodeCanvasObject={(n, ctx, scale) => {
          const r0 = n.observation ? 3 : 6;
          const c = colors[(byCommunity ? (n.community ?? 0) : kgs.indexOf(n.kg)) % 8];
          ctx.beginPath(); ctx.arc(n.x ?? 0, n.y ?? 0, r0, 0, 2 * Math.PI);
          ctx.fillStyle = c; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = cssVar("--c-surface"); ctx.stroke();
          if (!n.observation && scale > 0.9) {
            ctx.font = `${11 / scale}px sans-serif`; ctx.fillStyle = ink; ctx.textAlign = "center";
            ctx.fillText(n.label.slice(0, 24), n.x ?? 0, (n.y ?? 0) + r0 + 11 / scale);
          }
        }}
      />
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink-2">
        {(byCommunity ? r.communities.map((c) => `community ${c.id}`) : kgs).map((label, i) => (
          <span key={label} className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: SERIES[i % 8] }} />{label}</span>
        ))}
        <span>- - owl:sameAs</span>
        {r.graph.truncated && <span>(first 600 nodes)</span>}
      </div>
    </div>
  );
}
