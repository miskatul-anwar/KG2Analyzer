import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Decision } from "@/api/client";
import { Card, Chip, DataTable, ErrorBox, Kpi, SignedChip, Spinner } from "@/components/kit";
import { localName, SERIES } from "@/lib/format";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const QUESTION: Record<Decision["question"], string> = {
  fact_class: "fact class?", aggregate: "aggregate", unit: "unit of measure?", level_attribute: "level attribute?",
};
const subject = (d: Decision) =>
  String(d.profile.class_name ?? d.profile.measure_name ?? d.profile.property_name ?? d.profile.name ?? "");

/** What the KG2MD notebook decided and built for one KG: Tev1 fact scores and Otsu split, measures, hierarchies, audit. */
export function MdkgDetails({ kg }: { kg: string }) {
  const { data: r, isLoading, error } = useQuery({ queryKey: ["phase1", kg], queryFn: () => api.phase1(kg), staleTime: Infinity });
  if (isLoading) return <Spinner label="loading…" />;
  if (error) return <ErrorBox error={error} />;
  if (!r) return null;
  const tau = r.otsu_threshold;
  const who = r.decider.includes("not Tev1") ? (r.decider.startsWith("ML") ? "the ML classifiers" : "the rules") : "Tev1";
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card title={`Fact classes · ${r.decider.includes("not Tev1") ? "ML classifiers" : "Tev1"} + Otsu`}
        subtitle={<>Decided by <b>{r.decider}</b> in {r.seconds}s · {tau === null ? "τ* —" : <>τ* = <b>{tau.toFixed(4)}</b></>} · {r.classes.filter((c) => c.selected).length} of {r.classes.length} eligible classes become cubes{r.separated_records ? ` · ${r.separated_records} reused record IRIs separated` : ""}</>}>
        <div className="h-72">
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 10, right: 30, bottom: 60, left: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="rank" type="category" allowDuplicatedCategory={false} interval={0} angle={-40} textAnchor="end"
                tickFormatter={(i: number) => r.classes[i]?.label ?? ""} />
              <YAxis dataKey="probability" domain={[0, 1]} tickCount={6} width={40} />
              <Tooltip cursor={false} content={({ payload }) => {
                const c = payload?.[0]?.payload as (typeof r.classes)[number] | undefined;
                return c ? <div className="card px-3 py-2 text-xs"><b>{c.label}</b><br />P(fact) = {c.probability.toFixed(4)}<br />
                  {c.selected ? "fact class" : c.excluded_by_guard ? "excluded by the structural guard" : "dimension"}</div> : null;
              }} />
              {tau !== null && <ReferenceLine y={tau} stroke={SERIES[1]} strokeWidth={2} strokeDasharray="5 4"
                label={{ value: `τ* = ${tau.toFixed(4)}`, position: "insideTopRight", fill: "var(--c-ink-2)", fontSize: 11 }} />}
              <Scatter isAnimationActive={false} data={r.classes.map((c, i) => ({ ...c, rank: i }))} shape="circle">
                {r.classes.map((c) => <Cell key={c.iri} fill={c.selected ? SERIES[0] : "var(--c-ink-3)"} />)}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
        <DataTable rows={r.classes} columns={[
          { key: "label", header: "class" },
          { key: "instances", header: "instances", numeric: true },
          { key: "numeric_properties", header: "numeric", numeric: true },
          { key: "object_properties", header: "links", numeric: true },
          { key: "referenced_ratio", header: "referenced", render: (c) => pct(c.referenced_ratio) },
          { key: "probability", header: "P(fact)", numeric: true, decimals: 4 },
          { key: "selected", header: "status", render: (c) => c.selected ? <Chip tone="good">fact</Chip>
            : c.excluded_by_guard ? <Chip tone="warn">guarded</Chip> : <Chip>dimension</Chip> },
        ]} />
      </Card>

      {r.cubes.map((c) => (
        <Card key={c.dataset} title={`Cube · ${c.label}`} subtitle={<span className="mono">{c.key ? `fact_classes/${c.key}/` : c.dataset}</span>}>
          <div className="mb-4 flex flex-wrap gap-3">
            <Kpi value={c.audit.observations} label={`observations${c.audit.source_facts !== null ? ` (${c.audit.source_facts} measured facts)` : ""}`} />
            <Kpi value={pct(c.audit.fact_preservation)} label="fact preservation" tone={c.audit.fact_preservation === 1 ? "good" : "bad"} />
            <Kpi value={pct(c.audit.measure_fidelity)} label={`measure fidelity · ${c.audit.measure_cells_checked} cells`} tone={c.audit.measure_fidelity === 1 ? "good" : "bad"} />
            <Kpi value={`${c.audit.ghost_observations ?? "—"} / ${c.audit.dropped_facts ?? "—"}`} label="ghost / dropped" />
          </div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Measures</h4>
          <DataTable rows={c.measures} columns={[
            { key: "name", header: "measure", render: (m) => <span className="font-medium">{m.name}</span> },
            { key: "aggregate", header: "aggregate", render: (m) => <span className="mono">qb4o:{m.aggregate}</span> },
            { key: "additivity", header: "additivity", render: (m) => <Chip tone={m.additivity === "additive" ? "good" : "warn"}>{m.additivity}</Chip> },
            { key: "decision", header: `${who} probabilities`, render: (m) => m.decision
              ? <div className="flex flex-wrap gap-1">{Object.entries(m.decision.probabilities).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
                  <Chip key={k} tone={k === m.aggregate ? "accent" : undefined}>{k} {(v * 100).toFixed(0)}%</Chip>)}</div>
              : <span className="text-ink-3">{m.source ? "declared qb4o:aggregateFunction" : "synthetic count"}</span> },
            { key: "unit", header: "unit", render: (m) => (m.unit ? localName(m.unit) : "—") },
          ]} />
          <h4 className="mt-4 mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Dimensions</h4>
          <DataTable rows={c.dimensions} columns={[
            { key: "label", header: "dimension", render: (d) => <span className="font-medium">{d.label.replace(/ Dimension$/, "")}</span> },
            { key: "base_level", header: "base level", render: (d) => localName(d.base_level ?? "") },
            { key: "hierarchies", header: "hierarchies", render: (d) => d.hierarchies.map((h, i) => (
              <div key={i} className="flex flex-wrap items-center gap-1 py-0.5">
                <span className="mr-1">{h.levels.map((l) => l.replace(/ Level$/, "")).join(" → ")}</span>
                {h.types.map((t) => <Chip key={t} tone="accent">{t}</Chip>)}
              </div>)) },
          ]} />
        </Card>
      ))}

      <Card title={`Every decision · ${r.decider}`} >
        <DataTable rows={r.decisions} max={400} columns={[
          { key: "question", header: "question", render: (d) => QUESTION[d.question] },
          { key: "profile", header: "about", render: (d) => <span className="font-medium">{subject(d)}</span> },
          { key: "prediction", header: "answer", render: (d) => <Chip tone="accent">{d.prediction}</Chip> },
          { key: "confidence", header: "p", numeric: true, decimals: 3 },
          ...(r.decisions.some((d) => d.explanation) ? [{ key: "explanation" as const, header: "why", render: (d: Decision) => (
            <div className="flex flex-wrap gap-1">{Object.entries(d.explanation ?? {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 3).map(([k, v]) =>
              <SignedChip key={k} name={k} value={v} />)}</div>) }] : []),
        ]} />
      </Card>

      <Card title="Notebook log" >
        <pre className="mono max-h-96 overflow-auto whitespace-pre text-[11px] leading-snug text-ink-2">{r.log}</pre>
      </Card>
    </div>
  );
}
