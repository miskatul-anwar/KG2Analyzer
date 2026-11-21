import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import { useStatus } from "@/api/hooks";
import { Card, ErrorBox, PageHeader, RowsTable, Select, Spinner } from "@/components/ui";

const DEFAULT = `PREFIX qb: <http://purl.org/linked-data/cube#>
SELECT ?g (COUNT(?o) AS ?observations)
WHERE { GRAPH ?g { ?o a qb:Observation } }
GROUP BY ?g ORDER BY DESC(?observations)`;

export default function SparqlPage() {
  const { data: st } = useStatus();
  const [query, setQuery] = useState(DEFAULT);
  const [kg, setKg] = useState("");
  const run = useMutation({ mutationFn: () => api.sparql(query, kg || null) });
  return (
    <>
      <PageHeader title="SPARQL console" description="Read-only SPARQL 1.1 over the integrated named-graph store, or over one source's own endpoint. Update verbs are rejected. The same store is exposed at /sparql and /sparql/{kg} via the SPARQL 1.1 Protocol." />
      <Card>
        <textarea className="input mono min-h-48 w-full" spellCheck={false} value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run.mutate(); }} />
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Select label="Run on" value={kg} onChange={setKg} options={[{ value: "", label: "integrated store" }, ...(st?.kgs ?? []).map((k) => ({ value: k, label: `source: ${k}` }))]} />
          <button className="btn-primary" onClick={() => run.mutate()} disabled={run.isPending}><Play className="size-4" />Run <span className="text-white/70">⌘↵</span></button>
          {run.isPending && <Spinner />}
        </div>
      </Card>
      <ErrorBox error={run.error} />
      {run.data && (
        <Card className="mt-4" title={`${run.data.rows.length} row(s)`} subtitle={`${(run.data.seconds * 1000).toFixed(1)} ms`}>
          <RowsTable columns={run.data.columns} rows={run.data.rows} />
        </Card>
      )}
    </>
  );
}
