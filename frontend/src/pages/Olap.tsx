import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/api/client";
import { useCube } from "@/api/hooks";
import { CubePicker, type CubeSel } from "@/components/CubePicker";
import { Card, Code, DataTable, ErrorBox, PageHeader, Select, Spinner, Warning } from "@/components/ui";
import { fmtNum, localName, SERIES } from "@/lib/format";

export default function OlapPage() {
  const [sel, setSel] = useState<CubeSel>({ kg: "", dim: "", measure: "" });
  const [level, setLevel] = useState("");
  const [agg, setAgg] = useState("");
  const [fDim, setFDim] = useState("");
  const [fVal, setFVal] = useState("");
  const cube = useCube(sel.kg);
  const dim = cube?.dimensions.find((d) => d.prop === sel.dim);
  const levelValue = dim?.levels.includes(level) ? level : (dim?.levels[0] ?? "");
  const run = useMutation({ mutationFn: api.olap });

  const go = () => run.mutate({
    kg: sel.kg, measure: sel.measure, aggregate: agg || null, group_by: [[sel.dim, levelValue || null]],
    filters: fDim && fVal ? [[fDim, fVal, null]] : [],
  });
  const r = run.data;
  const labelCol = r?.columns[1] ?? "";
  const keyCol = r?.columns[0] ?? "";
  const chart = (r?.rows ?? []).slice(0, 25).map((x) => ({ label: String(x[labelCol] ?? localName(x[keyCol])), total: Number(x.total), n: x.observations }));

  return (
    <>
      <PageHeader title="OLAP" description="Roll up a cube along the hierarchy paths KG2MD discovered (ragged and alternative paths are unioned), then slice or dice by any member. Non-additive measures are guarded." />
      <Card>
        <div className="flex flex-wrap items-end gap-2">
          <CubePicker value={sel} onChange={setSel} />
          <Select label="Roll up to level" value={levelValue} onChange={setLevel} options={(dim?.levels ?? []).map((l) => ({ value: l, label: localName(l) }))} />
          <Select label="Aggregate" value={agg} onChange={setAgg} options={[{ value: "", label: "(catalogue)" }, ...["sum", "avg", "min", "max", "count"].map((a) => ({ value: a, label: a }))]} />
          <Select label="Slice dimension" value={fDim} onChange={setFDim} options={[{ value: "", label: "—" }, ...(cube?.dimensions ?? []).map((d) => ({ value: d.prop, label: localName(d.prop) }))]} />
          <label className="label">= member<input className="input w-40" value={fVal} onChange={(e) => setFVal(e.target.value)} placeholder="label or IRI" /></label>
          <button className="btn-primary" onClick={go} disabled={!sel.measure || run.isPending}><Play className="size-4" />Roll up</button>
          {run.isPending && <Spinner />}
        </div>
      </Card>
      <ErrorBox error={run.error} />
      {r && (
        <Card className="mt-4" title={`${localName(sel.measure)} by ${localName(levelValue)}`} subtitle={`${r.rows.length} group(s)`}>
          {r.warnings.map((w) => <Warning key={w}>{w}</Warning>)}
          <div style={{ height: Math.max(160, chart.length * 30 + 40) }}>
            <ResponsiveContainer>
              <BarChart data={chart} layout="vertical" margin={{ left: 10, right: 40 }}>
                <CartesianGrid horizontal={false} />
                <XAxis type="number" tickFormatter={(v: number) => fmtNum(v)} />
                <YAxis type="category" dataKey="label" width={170} />
                <Tooltip cursor={{ fill: "var(--c-raised)" }} formatter={(v) => fmtNum(Number(v), 2)} />
                <Bar isAnimationActive={false} dataKey="total" name={localName(sel.measure)} fill={SERIES[0]} radius={[0, 4, 4, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3"><DataTable rows={r.rows} columns={[
            { key: labelCol, header: localName(levelValue) },
            { key: "total", header: "total", numeric: true },
            { key: "observations", header: "observations", numeric: true },
          ]} /></div>
          <Code title="Generated SPARQL">{r.sparql}</Code>
        </Card>
      )}
    </>
  );
}
