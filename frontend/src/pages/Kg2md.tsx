import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/api/client";
import { useStatus } from "@/api/hooks";
import { Card, Chip, DataTable, Empty, ErrorBox, Kpi, PageHeader, Select, SignedChip, Spinner } from "@/components/ui";
import { SERIES } from "@/lib/format";

export default function Kg2mdPage() {
  const { data: st } = useStatus();
  const kgs = st?.kgs ?? [];
  const [kg, setKg] = useState("");
  useEffect(() => { if (!kg && kgs.length) setKg(kgs[0]); }, [kgs, kg]);
  const { data: r, isLoading, error } = useQuery({ queryKey: ["phase1", kg], queryFn: () => api.phase1(kg), enabled: !!kg });

  return (
    <>
      <PageHeader title="Phase I · KG2MD" description="RDFS closure → class profiling → fact probability → Otsu threshold (maximises between-class variance) → measure additivity with SHAP & LIME → ADW4 hierarchy discovery → QB4OLAP cube + preservation audit.">
        <Select label="Knowledge graph" value={kg} onChange={setKg} options={kgs.map((k) => ({ value: k, label: k }))} />
      </PageHeader>
      {!kgs.length && <Empty>Load a KG on the Workspace page first.</Empty>}
      {isLoading && <Spinner label="loading report…" />}
      <ErrorBox error={error} />
      {r && (
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Otsu fact-class selection" subtitle={<>Scorer <b>{r.scorer}</b> · RDFS closure added {r.closure_added_triples} triples · τ* = <b>{r.otsu_threshold}</b> · {r.classes.filter((c) => c.selected).length} of {r.classes.length} classes become cubes</>}>
            <div className="h-72">
              <ResponsiveContainer>
                <ScatterChart margin={{ top: 10, right: 30, bottom: 60, left: 0 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="rank" type="category" allowDuplicatedCategory={false} interval={0} angle={-40} textAnchor="end"
                    tickFormatter={(i: number) => r.classes[i]?.label ?? ""} />
                  <YAxis dataKey="probability" domain={[0, 1]} tickCount={6} width={40} />
                  <Tooltip cursor={false} content={({ payload }) => {
                    const c = payload?.[0]?.payload as (typeof r.classes)[number] | undefined;
                    return c ? <div className="card px-3 py-2 text-xs"><b>{c.label}</b><br />p = {c.probability}<br />{c.selected ? "fact class" : "dimension level"}</div> : null;
                  }} />
                  <ReferenceLine y={r.otsu_threshold} stroke={SERIES[1]} strokeWidth={2} strokeDasharray="5 4"
                    label={{ value: `τ* = ${r.otsu_threshold.toFixed(4)}`, position: "insideTopRight", fill: "var(--c-ink-2)", fontSize: 11 }} />
                  <Scatter isAnimationActive={false} data={r.classes.map((c, i) => ({ ...c, rank: i }))} shape="circle">
                    {r.classes.map((c) => <Cell key={c.iri} fill={c.selected ? SERIES[0] : "var(--c-ink-3)"} />)}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className="flex gap-4 text-xs text-ink-2">
              <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: SERIES[0] }} />fact class (p ≥ τ*)</span>
              <span className="flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-ink-3" />dimension level</span>
            </div>
          </Card>

          <Card title="Class profiles" subtitle="Per-feature contributions to the fact logit: every decision is explainable.">
            <DataTable rows={r.classes} columns={[
              { key: "label", header: "class" },
              { key: "instances", header: "instances", numeric: true },
              { key: "probability", header: "p(fact)", numeric: true, decimals: 4 },
              { key: "selected", header: "status", render: (c) => c.selected ? <Chip tone="good">fact</Chip> : <Chip>dimension</Chip> },
              { key: "contributions", header: "logit contributions", render: (c) => <div className="flex flex-wrap gap-1">{Object.entries(c.contributions).map(([k, v]) => <SignedChip key={k} name={k} value={v} />)}</div> },
            ]} />
          </Card>

          {r.cubes.map((c) => (
            <Card key={c.dataset} title={`Cube · ${c.label}`} subtitle={<span className="mono">{c.dataset}</span>}>
              <div className="mb-4 flex flex-wrap gap-3">
                <Kpi value={c.audit.observations} label={`observations (${c.audit.source_facts} source facts)`} />
                <Kpi value={`${(c.audit.fact_preservation * 100).toFixed(1)}%`} label="fact preservation" tone={c.audit.fact_preservation === 1 ? "good" : "bad"} />
                <Kpi value={`${(c.audit.measure_fidelity * 100).toFixed(1)}%`} label={`measure fidelity · ${c.audit.measure_cells_checked} cells`} tone={c.audit.measure_fidelity === 1 ? "good" : "bad"} />
                <Kpi value={`${c.audit.ghost_observations} / ${c.audit.dropped_facts}`} label="ghost / dropped" />
              </div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Measures · additivity classifier (SHAP φ and LIME weights)</h4>
              <DataTable rows={c.measures} columns={[
                { key: "name", header: "measure", render: (m) => <span className="font-medium">{m.name}</span> },
                { key: "unit", header: "unit" },
                { key: "additivity", header: "additivity", render: (m) => <Chip tone={m.additivity === "additive" ? "good" : "warn"}>{m.additivity}</Chip> },
                { key: "p_additive", header: "p(additive)", numeric: true, decimals: 3 },
                { key: "aggregate", header: "aggregate", render: (m) => <span className="mono">qb4o:{m.aggregate}</span> },
                { key: "shap", header: "SHAP", render: (m) => <div className="flex max-w-md flex-wrap gap-1">{m.shap.map(([t, v]) => <SignedChip key={t} name={t} value={v} />)}</div> },
                { key: "lime", header: "LIME", render: (m) => <div className="flex max-w-xs flex-wrap gap-1">{m.lime.slice(0, 4).map(([t, v]) => <SignedChip key={t} name={t} value={v} />)}</div> },
              ]} />
              <h4 className="mt-4 mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Dimensions · ADW4 hierarchy patterns</h4>
              <DataTable rows={c.dimensions} columns={[
                { key: "name", header: "dimension", render: (d) => <span className="font-medium">{d.name}</span> },
                { key: "base_level", header: "base level" },
                { key: "kinds", header: "patterns", render: (d) => <div className="flex flex-wrap gap-1">{d.kinds.map((k) => <Chip key={k} tone="accent">{k}</Chip>)}</div> },
                { key: "paths", header: "roll-up paths", render: (d) => d.paths.map((p, i) => <div key={i}>{p.join(" → ")}</div>) },
                { key: "steps", header: "steps", render: (d) => d.steps.map((s, i) => (
                  <div key={i} className="whitespace-nowrap">{s.child} <span className="text-ink-3">—{s.prop}→</span> {s.parent} <span className="text-ink-3">cov {s.coverage}{s.many_to_many && ", many-to-many"}</span></div>)) },
              ]} />
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
