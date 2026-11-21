import { useMutation } from "@tanstack/react-query";
import { Building2, Link2, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import { useCatalog, useRefreshStore, useStatus } from "@/api/hooks";
import { Pipeline } from "@/components/Pipeline";
import { Card, Chip, DataTable, Empty, ErrorBox, Kpi, PageHeader, Spinner } from "@/components/ui";
import { localName } from "@/lib/format";

export default function WorkspacePage() {
  const { data: st } = useStatus();
  const { data: cat } = useCatalog();
  const refresh = useRefreshStore();
  const [msg, setMsg] = useState<string>();

  const bench = useMutation({ mutationFn: api.loadBenchmark, onSuccess: (r) => { setMsg(`Benchmark loaded and materialised in ${r.seconds}s`); refresh(); } });
  const identity = useMutation({ mutationFn: api.uploadIdentity, onSuccess: (r) => { setMsg(`${r.links_added} owl:sameAs links added`); refresh(); } });
  const remote = useMutation({ mutationFn: ({ name, url }: { name: string; url: string }) => api.attachRemote(name, url), onSuccess: () => { setMsg("Remote endpoint attached"); refresh(); } });
  const del = useMutation({ mutationFn: api.deleteKg, onSuccess: refresh });

  const busy = bench.isPending;

  return (
    <>
      <PageHeader title="Workspace" description="Input: a set of raw knowledge graphs. Output: one MDKG (QB4OLAP cube) per KG, an identity graph linking them, and every analysis on the other pages: OLAP, cross-KG queries, communities and plain-English questions.">
        {msg && <Chip tone="good">{msg}</Chip>}
      </PageHeader>

      <div className="mb-4 flex flex-wrap gap-3">
        <Kpi value={st?.kgs.length ?? "–"} label="knowledge graphs" />
        <Kpi value={st?.cubes ?? "–"} label="QB4OLAP cubes" />
        <Kpi value={st?.graphs.filter((g) => g.triples).length ?? "–"} label="named graphs" />
        <Kpi value={st?.identity_links ?? "–"} label="identity triples (owl:sameAs)" />
      </div>

      <div className="mb-4"><Pipeline /></div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="No KGs at hand? Try a benchmark" subtitle="Generated raw KGs with the thesis numbers; cubes are discovered, not hand-made.">
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary" disabled={busy} onClick={() => bench.mutate("enterprise")}><Building2 className="size-4" />7-domain enterprise benchmark</button>
              <button className="btn" disabled={busy} onClick={() => bench.mutate("northwind")}>Northwind corpus</button>
              {bench.isPending && <Spinner label="materialising…" />}
            </div>
            <ErrorBox error={bench.error} />
          </Card>

          <Card title="Identity links & federation">
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); identity.mutate(new FormData(e.currentTarget)); }}>
              <label className="label grow">owl:sameAs graph<input className="input" name="file" type="file" required /></label>
              <button className="btn"><Link2 className="size-4" />Upload</button>
            </form>
            <ErrorBox error={identity.error} />
            <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => {
              e.preventDefault(); const f = new FormData(e.currentTarget);
              remote.mutate({ name: String(f.get("name")), url: String(f.get("url")) });
            }}>
              <label className="label">Remote KG name<input className="input w-32" name="name" required /></label>
              <label className="label grow">SPARQL 1.1 endpoint<input className="input" name="url" required placeholder="https://host/sparql/finance" /></label>
              <button className="btn">Attach</button>
            </form>
            <ErrorBox error={remote.error} />
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Named graphs" actions={<a className="btn" href="/api/export.nq" download="kg2analyzer.nq">Export N-Quads</a>}>
            {st?.graphs.length ? (
              <DataTable rows={st.graphs} columns={[
                { key: "kg", header: "KG", render: (g) => g.kg === "_identity" ? <Chip tone="accent">identity</Chip> : g.kg },
                { key: "graph", header: "graph IRI", render: (g) => <span className="mono">{g.graph}</span> },
                { key: "triples", header: "triples", numeric: true },
              ]} />
            ) : <Empty>Nothing loaded yet.</Empty>}
          </Card>
          <Card title="Schema catalogue" subtitle="Built at runtime from each source's schema graph: the only vocabulary the NL interface may use.">
            {cat?.cubes.length ? (
              <DataTable rows={cat.cubes} columns={[
                { key: "kg", header: "KG", render: (c) => (
                  <div className="flex items-center gap-2"><span className="font-medium">{c.kg}</span>
                    <button className="text-ink-3 hover:text-bad" title="Remove KG" onClick={() => del.mutate(c.kg)}><Trash2 className="size-3.5" /></button></div>) },
                { key: "label", header: "fact class", render: (c) => <span className="mono">{c.alias}</span> },
                { key: "measures", header: "measures", render: (c) => <div className="flex flex-wrap gap-1">{c.measures.map((m) => <Chip key={m.iri} tone={m.additivity === "additive" ? undefined : "warn"}>{localName(m.iri)} · {m.aggregate}</Chip>)}</div> },
                { key: "dimensions", header: "dimensions", render: (c) => c.dimensions.map((d) => localName(d.prop)).join(", ") },
              ]} />
            ) : <Empty>No cubes yet: load a benchmark or upload a KG.</Empty>}
          </Card>
        </div>
      </div>
    </>
  );
}
