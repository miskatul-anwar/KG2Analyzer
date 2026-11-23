import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, GitMerge, Play, ShieldCheck, Sigma, X } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Catalog, type CatalogCube, type CrossCompare } from "@/api/client";
import { useCatalog, useJoins, useMembers, useStatus } from "@/api/hooks";
import { Card, Chip, Code, DataTable, Empty, ErrorBox, GroupSelect, Kpi, LoadingBlock, RowsTable, Segmented, Spinner, Warning } from "@/components/kit";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fmtNum, localName, SERIES } from "@/lib/format";
import { EMPTY_QUERY, useUi, type QuerySel } from "@/store";

const human = (iri: string) => localName(iri).replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
const split = (v: string) => { const [a, b] = v.split("|"); return [a ?? "", b ?? ""] as const; };

export default function QueryPage() {
  const { data: cat, isLoading } = useCatalog();
  const tab = useUi((s) => s.queryTab);
  const setTab = useUi((s) => s.setQueryTab);
  if (isLoading) return <LoadingBlock rows={6} />;
  if (!cat?.cubes.length) {
    return (
      <Empty>
        <div className="flex flex-col items-center gap-3">
          <span>No MDKGs yet. Build them from your knowledge graphs first.</span>
          <Button asChild><Link to="/build">Go to Build MDKGs<ArrowRight className="size-4" /></Link></Button>
        </div>
      </Empty>
    );
  }
  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Query your MDKGs</h1>
          <p className="mt-1 text-sm text-ink-2">Pick a measure and how to break it down; results update as you choose. Combine two MDKGs to compare them per shared entity.</p>
        </div>
        <Segmented value={tab} onChange={setTab} options={[{ value: "builder", label: "Builder" }, { value: "sparql", label: "SPARQL" }]} />
      </div>
      {tab === "builder" ? <Builder cat={cat} /> : <SparqlTab />}
    </>
  );
}

/* ------------------------------------------------------------------------------------------- builder */

function Builder({ cat }: { cat: Catalog }) {
  const q = useUi((s) => s.query);
  const set = useUi((s) => s.setQuery);
  const cube = cat.cubes.find((c) => c.kg === q.kg);
  const compareCube = cat.cubes.find((c) => c.kg === q.compareKg);

  // Pick sensible defaults, and drop selections that point at MDKGs that no longer exist.
  useEffect(() => {
    if (!cube || !cube.measures.some((m) => m.iri === q.measure)) {
      const c = cube ?? cat.cubes[0];
      const m = c.measures.find((x) => x.additivity === "additive") ?? c.measures[0];
      const d = c.dimensions[0];
      set({ ...EMPTY_QUERY, mode: q.mode, kg: c.kg, measure: m?.iri ?? "", groupBy: d ? `${d.prop}|${d.base_level}` : "" });
    } else if (q.compareKg && !compareCube) {
      set({ compareKg: "", compareMeasure: "", join: null });
    }
  }, [cat, cube, compareCube, q.kg, q.measure, q.compareKg, q.mode, set]);

  const comparing = !!(q.compareKg && q.compareMeasure);
  return (
    <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
      <Card className="h-fit lg:sticky lg:top-24">
        <div className="flex flex-col gap-4">
          <Field n={1} label="Measure">
            <GroupSelect value={`${q.kg}|${q.measure}`} onChange={(v) => {
              const [kg, measure] = split(v);
              const c = cat.cubes.find((x) => x.kg === kg)!;
              const d = c.dimensions[0];
              set(kg === q.kg ? { measure } : { kg, measure, groupBy: d ? `${d.prop}|${d.base_level}` : "", filterLevel: "", filterMember: "", aggregate: "",
                ...(q.compareKg === kg ? { compareKg: "", compareMeasure: "", join: null } : {}) });
            }} groups={measureGroups(cat.cubes)} />
          </Field>

          {cube && !comparing && (
            <>
              <Field n={2} label="Break down by">
                <LevelSelect cube={cube} value={q.groupBy} onChange={(groupBy) => set({ groupBy })} allowNone="Grand total" />
              </Field>
              <Field n={3} label="How to aggregate" optional>
                <Segmented small value={q.aggregate} onChange={(aggregate) => set({ aggregate })}
                  options={[{ value: "", label: "auto" }, ...["sum", "avg", "min", "max", "count"].map((a) => ({ value: a, label: a }))]} />
              </Field>
              <Field n={4} label="Only for" optional>
                <LevelSelect cube={cube} value={q.filterLevel} onChange={(filterLevel) => set({ filterLevel, filterMember: "" })} allowNone="Everything" />
                {q.filterLevel && <MemberSelect kg={cube.kg} level={q.filterLevel} value={q.filterMember} onChange={(filterMember) => set({ filterMember })} />}
              </Field>
            </>
          )}

          <Field n={comparing ? 2 : 5} label="Compare with another MDKG" optional>
            <GroupSelect value={q.compareKg && q.compareMeasure ? `${q.compareKg}|${q.compareMeasure}` : ""} none="No comparison" onChange={(v) => {
              const [compareKg, compareMeasure] = split(v);
              set({ compareKg, compareMeasure, join: null });
            }} groups={measureGroups(cat.cubes.filter((c) => c.kg !== q.kg))} />
            {comparing && <JoinSelect a={q.kg} b={q.compareKg} />}
          </Field>
          {comparing && (
            <Field label="Run on">
              <Segmented value={q.mode} onChange={(mode) => set({ mode: mode as QuerySel["mode"] })}
                options={[{ value: "integrated", label: "one store" }, { value: "federated", label: "separate stores" }]} />
            </Field>
          )}
        </div>
      </Card>
      <div className="min-w-0">{comparing ? <CompareResult q={q} cube={cube} other={compareCube} /> : <OlapResult q={q} cube={cube} />}</div>
    </div>
  );
}

function Field({ n, label, optional, children }: { n?: number; label: string; optional?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-xs font-semibold text-ink-2">
        {n !== undefined && <span className="flex size-5 items-center justify-center rounded-full bg-raised text-[10px]">{n}</span>}
        {label}{optional && <span className="font-normal text-ink-3">· optional</span>}
      </div>
      {children}
    </div>
  );
}

function measureGroups(cubes: CatalogCube[]) {
  return cubes.map((c) => ({
    label: `${c.kg} · ${c.label}`,
    options: c.measures.map((m) => ({ value: `${c.kg}|${m.iri}`, label: <span>{human(m.iri)} <span className="text-ink-3">· {m.aggregate}{m.additivity === "non-additive" ? " · non-additive" : ""}</span></span> })),
  }));
}

function LevelSelect({ cube, value, onChange, allowNone }: { cube: CatalogCube; value: string; onChange: (v: string) => void; allowNone: string }) {
  return (
    <GroupSelect value={value} onChange={onChange} none={allowNone} groups={cube.dimensions.map((d) => ({
      label: human(d.prop),
      options: d.levels.map((l) => ({ value: `${d.prop}|${l}`, label: <span>{human(l)}{l !== d.base_level && <span className="text-ink-3"> · rolled up</span>}</span> })),
    }))} />
  );
}

function MemberSelect({ kg, level, value, onChange }: { kg: string; level: string; value: string; onChange: (v: string) => void }) {
  const [dim, lvl] = split(level);
  const { data, isLoading } = useMembers(kg, dim, lvl);
  if (isLoading) return <Spinner label="loading members…" />;
  return <GroupSelect value={value} onChange={onChange} placeholder={`Choose ${human(lvl).toLowerCase()}…`}
    options={(data?.members ?? []).map((m) => ({ value: m.iri, label: m.label }))} />;
}

function JoinSelect({ a, b }: { a: string; b: string }) {
  const join = useUi((s) => s.query.join);
  const set = useUi((s) => s.setQuery);
  const { data, isLoading } = useJoins(a, b);
  const options = data?.options ?? [];
  useEffect(() => {
    if (options.length && !options.some((o) => o.left_dim === join?.left_dim && o.right_dim === join?.right_dim && o.link === join?.link)) set({ join: options[0] });
  }, [options, join, set]);
  if (isLoading) return <Spinner label="finding shared entities…" />;
  if (!options.length) return <Warning>{a} and {b} share no entities or values, so they can't be combined. Link them on the Build page first.</Warning>;
  const idx = join ? options.findIndex((o) => o.left_dim === join.left_dim && o.right_dim === join.right_dim && o.link === join.link) : 0;
  return <GroupSelect value={String(Math.max(0, idx))} onChange={(v) => set({ join: options[Number(v)] })}
    options={options.map((o, i) => ({ value: String(i), label: `joined on ${o.label}` }))} />;
}

function OlapResult({ q, cube }: { q: QuerySel; cube?: CatalogCube }) {
  const [gDim, gLevel] = split(q.groupBy);
  const [fDim, fLevel] = split(q.filterLevel);
  const body = {
    kg: q.kg, measure: q.measure, aggregate: q.aggregate || null,
    group_by: q.groupBy ? [[gDim, gLevel || null]] as [string, string | null][] : [],
    filters: q.filterLevel && q.filterMember ? [[fDim, q.filterMember, fLevel || null]] as [string, string, string | null][] : [],
  };
  const { data: r, error, isFetching, isPlaceholderData } = useQuery({
    queryKey: ["olap", body], queryFn: () => api.olap(body), enabled: !!(q.kg && q.measure),
    placeholderData: keepPreviousData, staleTime: Infinity,
  });
  const measure = cube?.measures.find((m) => m.iri === q.measure);
  const agg = (q.aggregate || measure?.aggregate || "").toUpperCase();
  const keyCol = r?.columns.length && r.columns.length > 2 ? r.columns[0] : "";
  const labelCol = keyCol ? r!.columns[1] : "";
  const rows = (r?.rows ?? []).map((x) => ({ ...x, group: String(x[labelCol] ?? localName(x[keyCol]) ?? "total") }));
  const title = `${agg} of ${human(q.measure)}${q.groupBy ? ` by ${human(gLevel)}` : ""}`;

  return (
    <Card title={<span className="flex items-center gap-2"><Sigma className="size-4 text-brand" />{title}</span>}
      subtitle={<>{q.kg}{q.filterMember ? <> · only {localName(q.filterMember)}</> : null}</>}
      actions={isFetching && <Spinner />} className={clsx(isPlaceholderData && "opacity-60 transition-opacity")}>
      <ErrorBox error={error} />
      {r && (
        <>
          {r.warnings.map((w) => <Warning key={w}>{w}</Warning>)}
          {!keyCol ? (
            <div className="py-6 text-center">
              <div className="text-4xl font-semibold tabular-nums">{r.rows[0]?.total == null ? "—" : fmtNum(Number(r.rows[0].total), 2)}</div>
              <div className="mt-1 text-sm text-ink-3">{fmtNum(Number(r.rows[0]?.observations ?? 0))} observations</div>
            </div>
          ) : rows.length ? (
            <>
              <div style={{ height: Math.min(560, Math.max(140, rows.slice(0, 20).length * 30 + 40)) }}>
                <ResponsiveContainer>
                  <BarChart data={rows.slice(0, 20)} layout="vertical" margin={{ left: 8, right: 48 }}>
                    <CartesianGrid horizontal={false} />
                    <XAxis type="number" tickFormatter={(v: number) => fmtNum(v)} />
                    <YAxis type="category" dataKey="group" width={160} tickFormatter={(v: string) => (v.length > 22 ? v.slice(0, 21) + "…" : v)} />
                    <Tooltip cursor={{ fill: "var(--c-raised)" }} formatter={(v) => [fmtNum(Number(v), 2), human(q.measure)]} />
                    <Bar isAnimationActive={false} dataKey="total" fill={SERIES[0]} radius={[0, 4, 4, 0]} barSize={18} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {rows.length > 20 && <p className="text-xs text-ink-3">Chart shows the top 20 of {rows.length}; all rows are in the table.</p>}
              <div className="mt-3">
                <DataTable rows={rows} columns={[{ key: "group", header: human(gLevel) }, { key: "total", header: agg.toLowerCase(), numeric: true },
                  { key: "observations", header: "observations", numeric: true }]} />
              </div>
            </>
          ) : <Empty>No observations match.</Empty>}
          <Code title="SPARQL">{r.sparql}</Code>
        </>
      )}
    </Card>
  );
}

function CompareResult({ q, cube, other }: { q: QuerySel; cube?: CatalogCube; other?: CatalogCube }) {
  const body = q.join && {
    left: [q.kg, q.join.left_dim, q.measure] as [string, string, string],
    right: [q.compareKg, q.join.right_dim, q.compareMeasure] as [string, string, string],
    link: q.join.link,
  };
  const { data: r, error, isFetching, isPlaceholderData } = useQuery({
    queryKey: ["compare", body], queryFn: () => api.compare(body!), enabled: !!body,
    placeholderData: keepPreviousData, staleTime: Infinity,
  });
  if (!q.join) return <Card><Spinner label="choosing how to join…" /></Card>;
  return (
    <div className={clsx("flex flex-col gap-4", isPlaceholderData && "opacity-60 transition-opacity")}>
      <ErrorBox error={error} />
      {!r ? <Card><Spinner label="running…" /></Card> : <CompareView r={r} q={q} cube={cube} other={other} busy={isFetching} />}
    </div>
  );
}

function CompareView({ r, q, cube, other, busy }: { r: CrossCompare; q: QuerySel; cube?: CatalogCube; other?: CatalogCube; busy: boolean }) {
  const res = r[`${q.mode}/pushdown`];
  const naive = r[`${q.mode}/naive`];
  const lm = human(q.measure), rm = human(q.compareMeasure);
  const rows = useMemo(() => res.rows.map((x) => {
    const n = naive.rows.find((y) => y.left_entity === x.left_entity && y.right_entity === x.right_entity);
    const g = res.guard.pairs.find((p) => p.left_entity === x.left_entity && p.right_entity === x.right_entity);
    return {
      entity: localName(x.left_entity), match: localName(x.right_entity),
      left: Number(x.left_total), right: Number(x.right_total),
      naiveLeft: n ? Number(n.left_total) : null, naiveRight: n ? Number(n.right_total) : null,
      factor: g ? `×${g.left_inflation} / ×${g.right_inflation}` : "",
    };
  }), [res, naive]);
  const inflated = res.guard.cartesian_risk;
  const sameValue = q.join?.link === "shared";
  return (
    <>
      <Card title={<span className="flex items-center gap-2"><GitMerge className="size-4 text-brand" />{lm} ({q.kg}) vs {rm} ({q.compareKg})</span>}
        subtitle={`per ${sameValue ? "shared value" : "shared entity"} · ${q.mode === "integrated" ? "one store" : "separate stores (federated)"} · ${(res.seconds * 1000).toFixed(0)} ms`}
        actions={busy && <Spinner />}>
        {rows.length ? (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <MiniBars title={`${lm} · ${cube?.label ?? q.kg}`} data={rows.map((x) => ({ k: x.entity, v: x.left }))} color={SERIES[0]} />
              <MiniBars title={`${rm} · ${other?.label ?? q.compareKg}`} data={rows.map((x) => ({ k: x.entity, v: x.right }))} color={SERIES[1]} />
            </div>
            <div className="mt-3">
              <DataTable rows={rows} columns={[
                { key: "entity", header: q.kg }, { key: "match", header: q.compareKg },
                { key: "left", header: lm, numeric: true, decimals: 2 }, { key: "right", header: rm, numeric: true, decimals: 2 },
              ]} />
            </div>
          </>
        ) : <Empty>No aligned entities produced values.</Empty>}
      </Card>
      {rows.length > 0 && (
        <Card title={<span className="flex items-center gap-2"><ShieldCheck className="size-4 text-good" />Why these totals are correct</span>}
          subtitle="Each MDKG is aggregated on its own before joining (pushdown). Joining raw observations first multiplies every value by the other side's count.">
          {inflated && <div className="mb-3 flex flex-wrap gap-2"><Chip tone="good">pushdown: exact</Chip><Chip tone="bad">naive join would inflate up to ×{res.guard.max_inflation}</Chip></div>}
          <DataTable rows={rows} columns={[
            { key: "entity", header: "entity" },
            { key: "left", header: `${lm} (correct)`, numeric: true, decimals: 2 },
            { key: "naiveLeft", header: `${lm} (naive)`, numeric: true, decimals: 2, render: (x) => <span className={x.naiveLeft !== x.left ? "text-bad" : ""}>{x.naiveLeft == null ? "—" : fmtNum(x.naiveLeft, 2)}</span> },
            { key: "right", header: `${rm} (correct)`, numeric: true, decimals: 2 },
            { key: "naiveRight", header: `${rm} (naive)`, numeric: true, decimals: 2, render: (x) => <span className={x.naiveRight !== x.right ? "text-bad" : ""}>{x.naiveRight == null ? "—" : fmtNum(x.naiveRight, 2)}</span> },
            { key: "factor", header: "naive inflation" },
          ]} />
          <div className="mt-3 flex flex-wrap gap-3">
            {(["integrated/pushdown", "federated/pushdown", "integrated/naive", "federated/naive"] as const).map((k) => (
              <Kpi key={k} value={`${(r[k].seconds * 1000).toFixed(0)} ms`} label={k.replace("integrated", "one store").replace("federated", "separate stores")} />
            ))}
          </div>
          <Code title="SPARQL (pushdown)">{r["integrated/pushdown"].plan.sparql ?? ""}</Code>
          <Code title="Federated plan">{JSON.stringify(r["federated/pushdown"].plan, null, 2)}</Code>
        </Card>
      )}
    </>
  );
}

function MiniBars({ title, data, color }: { title: string; data: { k: string; v: number }[]; color: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-ink-2">{title}</div>
      <div style={{ height: Math.max(120, Math.min(12, data.length) * 28 + 30) }}>
        <ResponsiveContainer>
          <BarChart data={data.slice(0, 12)} layout="vertical" margin={{ left: 4, right: 40 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" tickFormatter={(v: number) => fmtNum(v)} />
            <YAxis type="category" dataKey="k" width={110} tickFormatter={(v: string) => (v.length > 15 ? v.slice(0, 14) + "…" : v)} />
            <Tooltip cursor={{ fill: "var(--c-raised)" }} formatter={(v) => fmtNum(Number(v), 2)} />
            <Bar isAnimationActive={false} dataKey="v" fill={color} radius={[0, 4, 4, 0]} barSize={16} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------- sparql */

function SparqlTab() {
  const { data: st } = useStatus();
  const query = useUi((s) => s.sparql);
  const setQuery = useUi((s) => s.setSparql);
  const run = useMutation({ mutationFn: ({ q, kg }: { q: string; kg: string | null }) => api.sparql(q, kg) });
  const kgs = st?.kgs ?? [];
  return (
    <div className="flex flex-col gap-4">
      <Card subtitle="Read-only SPARQL 1.1 over all MDKGs (one store) or a single MDKG. Each MDKG is a named graph; the identity links are in <http://example.org/graphs/identities>.">
        <Textarea className="mono min-h-56 w-full" spellCheck={false} value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run.mutate({ q: query, kg: null }); }} />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button disabled={run.isPending} onClick={() => run.mutate({ q: query, kg: null })}><Play className="size-4" />Run on all MDKGs</Button>
          {kgs.map((k) => <Button key={k} variant="outline" disabled={run.isPending} onClick={() => run.mutate({ q: query, kg: k })}>{k}</Button>)}
          <span className="ml-auto text-xs text-ink-3">Ctrl/⌘ + Enter</span>
          {run.isPending && <Spinner />}
        </div>
      </Card>
      <ErrorBox error={run.error} />
      {run.data && (
        <Card title={`${run.data.rows.length} row(s)`} subtitle={`${(run.data.seconds * 1000).toFixed(1)} ms`}
          actions={<button className="text-ink-3 hover:text-ink" onClick={() => run.reset()} aria-label="clear"><X className="size-4" /></button>}>
          <RowsTable columns={run.data.columns} rows={run.data.rows} />
        </Card>
      )}
    </div>
  );
}

