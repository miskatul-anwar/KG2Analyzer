import { useMutation } from "@tanstack/react-query";
import { GitMerge } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type CrossCompare } from "@/api/client";
import { CubePicker, type CubeSel } from "@/components/CubePicker";
import { Card, Code, DataTable, ErrorBox, Kpi, PageHeader, Select, Spinner, Warning } from "@/components/ui";
import { fmtNum, localName, SERIES } from "@/lib/format";

const COMBOS = ["integrated/naive", "integrated/pushdown", "federated/naive", "federated/pushdown"] as const;

export default function CrossPage() {
  const [left, setLeft] = useState<CubeSel>({ kg: "", dim: "", measure: "" });
  const [right, setRight] = useState<CubeSel>({ kg: "", dim: "", measure: "" });
  const [link, setLink] = useState("identity");
  const run = useMutation({ mutationFn: api.compare });
  const r = run.data;

  return (
    <>
      <PageHeader title="Cross-KG query" description="Combine measures of two cubes, joined through the owl:sameAs identity graph or a conformed (shared-IRI) dimension. A naive join multiplies each side by the other's observation count; pushdown pre-aggregates each cube at its native grain first." />
      <Card>
        <div className="grid gap-4 lg:grid-cols-2">
          <CubePicker label="Left cube" value={left} onChange={setLeft} />
          <CubePicker label="Right cube" value={right} onChange={setRight} defaultIndex={1} />
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Select label="Join" value={link} onChange={setLink} options={[
            { value: "identity", label: "identity graph (owl:sameAs, transitive)" },
            { value: "shared", label: "shared IRI (conformed dimension)" },
          ]} />
          <button className="btn-primary" disabled={!left.measure || !right.measure || run.isPending}
            onClick={() => run.mutate({ left: [left.kg, left.dim, left.measure], right: [right.kg, right.dim, right.measure], link })}>
            <GitMerge className="size-4" />Compare naive vs pushdown × integrated vs federated
          </button>
          {run.isPending && <Spinner />}
        </div>
      </Card>
      <ErrorBox error={run.error} />
      {r && <Results r={r} lm={localName(left.measure)} rm={localName(right.measure)} />}
    </>
  );
}

function Results({ r, lm, rm }: { r: CrossCompare; lm: string; rm: string }) {
  const guard = r["integrated/pushdown"].guard;
  const keys = [...new Set(COMBOS.flatMap((k) => r[k].rows.map((x) => `${x.left_entity}|${x.right_entity}`)))];
  const rows = keys.map((k) => {
    const [l, rt] = k.split("|");
    const o: Record<string, string | number | null> = { left: localName(l), right: localName(rt) };
    for (const c of COMBOS) {
      const x = r[c].rows.find((y) => y.left_entity === l && y.right_entity === rt);
      o[`${c}:L`] = x ? Number(x.left_total) : null;
      o[`${c}:R`] = x ? Number(x.right_total) : null;
    }
    return o;
  });
  const chart = rows.slice(0, 8).map((o) => ({
    entity: `${o.left} ↔ ${o.right}`,
    [`naive ${lm}`]: o["integrated/naive:L"], [`pushdown ${lm}`]: o["integrated/pushdown:L"],
  }));
  return (
    <div className="mt-4 flex flex-col gap-4">
      <Card title="Execution">
        <div className="flex flex-wrap gap-3">
          {COMBOS.map((k) => <Kpi key={k} value={`${(r[k].seconds * 1000).toFixed(1)} ms`} label={k} />)}
          <Kpi value={`${guard.max_inflation ?? 1}×`} label="max inflation of a naive join" tone={guard.cartesian_risk ? "warn" : "good"} />
        </div>
        {guard.cartesian_risk && <Warning>Cartesian guard: aligned entities have several observations on both sides, so join-then-aggregate multiplies their measures. KG2Analyzer pre-aggregates each cube before joining.</Warning>}
      </Card>

      <Card title={`Totals per aligned entity · L = ${lm}, R = ${rm}`} subtitle="Pushdown totals are identical in both modes; naive totals are inflated.">
        <DataTable rows={rows} columns={[
          { key: "left", header: "left entity" }, { key: "right", header: "right entity" },
          ...COMBOS.flatMap((c) => [
            { key: `${c}:L`, header: <span className={c.endsWith("naive") ? "text-bad" : "text-good"}>{c} L</span>, numeric: true, decimals: 2 },
            { key: `${c}:R`, header: <span className={c.endsWith("naive") ? "text-bad" : "text-good"}>{c} R</span>, numeric: true, decimals: 2 },
          ]),
        ]} />
        <div className="mt-4 h-64">
          <ResponsiveContainer>
            <BarChart data={chart} margin={{ left: 10, right: 10 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="entity" />
              <YAxis tickFormatter={(v: number) => fmtNum(v)} width={70} />
              <Tooltip cursor={{ fill: "var(--c-raised)" }} formatter={(v) => fmtNum(Number(v), 2)} />
              <Legend />
              <Bar isAnimationActive={false} dataKey={`naive ${lm}`} fill={SERIES[1]} radius={[4, 4, 0, 0]} />
              <Bar isAnimationActive={false} dataKey={`pushdown ${lm}`} fill={SERIES[0]} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Cartesian factors" subtitle="What a naive plan multiplies each side by (m × n joined rows per entity).">
        <DataTable rows={guard.pairs} columns={[
          { key: "left_entity", header: "left" }, { key: "right_entity", header: "right" },
          { key: "left_observations", header: "m (left obs)", numeric: true }, { key: "right_observations", header: "n (right obs)", numeric: true },
          { key: "naive_joined_rows", header: "m × n", numeric: true },
          { key: "left_inflation", header: "left ×", numeric: true }, { key: "right_inflation", header: "right ×", numeric: true },
        ]} />
        <Code title="Pushdown SPARQL (integrated)">{r["integrated/pushdown"].plan.sparql ?? ""}</Code>
        <Code title="Naive SPARQL (the Query-23 shape)">{r["integrated/naive"].plan.sparql ?? ""}</Code>
        <Code title="Federated plan (sub-queries shipped to each source)">{JSON.stringify(r["federated/pushdown"].plan, null, 2)}</Code>
      </Card>
    </div>
  );
}
