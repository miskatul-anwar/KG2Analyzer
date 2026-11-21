import { useMutation } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { api } from "@/api/client";
import { Card, Chip, DataTable, ErrorBox, Kpi, PageHeader, Spinner } from "@/components/ui";

export default function EvaluatePage() {
  const run = useMutation({ mutationFn: api.evaluate });
  const r = run.data;
  const q23 = r ? Object.entries(r.query23).flatMap(([plan, v]) =>
    Object.entries(v).filter(([k]) => k !== "seconds").map(([ent, x]) => {
      const t = x as { retail: string; finance: string };
      return { plan, entity: ent, retail: Number(t.retail), finance: Number(t.finance), ms: Number(v.seconds) * 1000 };
    })) : [];
  return (
    <>
      <PageHeader title="Evaluate" description="Regenerates the thesis' results tables from a fresh instance of the running system: seven-domain telemetry (Table 4.4), the Query-23 audit (Table 4.5), identity communities (§4.2.4) and the 35-question NL benchmark (Table 4.6).">
        <button className="btn-primary" onClick={() => run.mutate()} disabled={run.isPending}><FlaskConical className="size-4" />Run evaluation</button>
      </PageHeader>
      {run.isPending && <Spinner label="loading benchmark and running all suites…" />}
      <ErrorBox error={run.error} />
      {r && (
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="NL benchmark" subtitle={`translator: ${r.nl_benchmark.translator}`}>
            <div className="mb-3 flex flex-wrap gap-3">
              <Kpi value={`${(r.nl_benchmark.execution_rate * 100).toFixed(2)}%`} label={`execution rate (${r.nl_benchmark.model_generated_executed + r.nl_benchmark.fallback_executed}/${r.nl_benchmark.questions})`} />
              <Kpi value={`${(r.nl_benchmark.correct_outcome_rate * 100).toFixed(2)}%`} label="correct outcome (answer or refusal)" tone="good" />
              <Kpi value={r.nl_benchmark.fallback_executed} label="fallback executed" />
              <Kpi value={r.nl_benchmark.rejected} label="rejected" />
              <Kpi value={`${(r.nl_benchmark.mean_latency_seconds * 1000).toFixed(0)} ms`} label="mean latency" />
            </div>
            <DataTable rows={r.nl_benchmark.outcomes} columns={[
              { key: "id", header: "id" }, { key: "question", header: "question" },
              { key: "expected", header: "expected" },
              { key: "status", header: "status", render: (o) => <Chip tone={o.status === "rejected" ? "bad" : o.status === "fallback" ? "warn" : "good"}>{o.status}</Chip> },
              { key: "rows", header: "rows", numeric: true },
              { key: "correct_outcome", header: "correct", render: (o) => o.correct_outcome ? <Chip tone="good">yes</Chip> : <Chip tone="bad">no</Chip> },
            ]} />
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Query 23 audit" subtitle="Naive join vs pushdown pre-aggregation, integrated and federated.">
              <DataTable rows={q23} columns={[
                { key: "plan", header: "plan", render: (x) => <span className={x.plan.startsWith("naive") ? "text-bad" : "text-good"}>{x.plan}</span> },
                { key: "entity", header: "entity" },
                { key: "retail", header: "retail", numeric: true, decimals: 2 },
                { key: "finance", header: "finance", numeric: true, decimals: 2 },
                { key: "ms", header: "ms", numeric: true, decimals: 1 },
              ]} />
            </Card>
            <Card title="Identity communities">
              <div className="flex flex-wrap gap-3">
                <Kpi value={r.identity_communities.count} label="communities" />
                <Kpi value={r.identity_communities.sizes.join(" · ")} label="sizes" />
                <Kpi value={r.identity_communities.modularity} label="modularity Q" />
                <Kpi value={`${r.load_seconds}s`} label="benchmark load + KG2MD" />
              </div>
            </Card>
          </div>
          <Card title="Seven-domain telemetry">
            <DataTable rows={r.domain_telemetry} columns={[
              { key: "domain", header: "domain" }, { key: "fact_class", header: "fact class" },
              { key: "fact_score", header: "p(fact)", numeric: true, decimals: 3 },
              { key: "otsu_tau", header: "τ*", numeric: true, decimals: 4 },
              { key: "observations", header: "observations", numeric: true },
              { key: "measures", header: "measures", numeric: true },
              { key: "fact_preservation", header: "fact preservation", numeric: true, decimals: 2 },
              { key: "measure_fidelity", header: "measure fidelity", numeric: true, decimals: 2 },
            ]} />
          </Card>
        </div>
      )}
    </>
  );
}
