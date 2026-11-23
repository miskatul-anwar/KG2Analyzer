import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Download, FileArchive, FileCode2, Link2, UploadCloud, Workflow, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { api, type PipelineReport } from "@/api/client";
import { useRefreshStore } from "@/api/hooks";
import { Card, Chip, DataTable, ErrorBox, Kpi, Spinner } from "@/components/ui";
import { localName } from "@/lib/format";

const RDF = /\.(ttl|nt|n3|rdf|owl|xml|jsonld|json-ld|nq|trig|zip)$/i;
const ROLE_SUFFIX = /[-_. ]*(tbox|abox|schema|ontology|onto|data|instances|kg)$/i;
const ROLE_ONLY = /^(tbox|abox|schema|ontology|onto|data|instances)$/i;

/** Mirror of backend `ingest.kg_name` so users see the grouping before uploading. */
function kgOf(f: File): string {
  const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
  const parts = rel.split("/");
  if (parts.length > 2) return parts[parts.length - 2].toLowerCase().replace(/[^a-z0-9]/g, "");
  const stem = parts[parts.length - 1].split(".")[0];
  if (/\.zip$/i.test(f.name)) return `${stem.replace(ROLE_SUFFIX, "").toLowerCase().replace(/[^a-z0-9]/g, "") || "kg"} (zip)`;
  if (ROLE_ONLY.test(stem)) return "kg";
  return stem.replace(ROLE_SUFFIX, "").toLowerCase().replace(/[^a-z0-9]/g, "") || "kg";
}

export function Pipeline() {
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [autoLink, setAutoLink] = useState(true);
  const [threshold, setThreshold] = useState(0.6);
  const [reset, setReset] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const refresh = useRefreshStore();
  const last = useQuery({ queryKey: ["pipelineReport"], queryFn: api.pipelineReport });
  const run = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name));
      fd.append("auto_link", String(autoLink));
      fd.append("threshold", String(threshold));
      fd.append("reset", String(reset));
      return api.pipeline(fd);
    },
    onSuccess: () => { setFiles([]); refresh(); },
  });

  const add = (list: FileList | null) => {
    if (!list) return;
    const incoming = [...list].filter((f) => RDF.test(f.name));
    setFiles((cur) => [...cur, ...incoming.filter((f) => !cur.some((c) => c.name === f.name && c.size === f.size))]);
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); };
  const groups = files.reduce<Record<string, File[]>>((acc, f) => ((acc[kgOf(f)] ??= []).push(f), acc), {});
  const report = run.data ?? (last.data && "kgs" in last.data ? (last.data as PipelineReport) : undefined);

  return (
    <Card title={<span className="flex items-center gap-2"><Workflow className="size-4 text-accent" />Build MDKGs from your knowledge graphs</span>}
      subtitle="Drop the whole set: one file per KG, TBox + ABox pairs (sales_tbox.ttl + sales_abox.ttl), one folder per KG, zip archives, and optionally owl:sameAs files. Every KG becomes an MDKG; links between KGs are discovered automatically.">
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        onClick={() => input.current?.click()}
        className={clsx("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition",
          drag ? "border-accent bg-accent/5" : "border-line hover:border-accent/60")}>
        <UploadCloud className="size-8 text-accent" />
        <div className="font-medium">Drop KG files, folders or .zip archives here</div>
        <div className="text-xs text-ink-3">Turtle · N-Triples · RDF/XML · OWL · JSON-LD · N-Quads · TriG · zip</div>
        <input ref={input} type="file" multiple hidden accept=".ttl,.nt,.n3,.rdf,.owl,.xml,.jsonld,.nq,.trig,.zip"
          onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>

      {files.length > 0 && (
        <div className="mt-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">{Object.keys(groups).length} KG(s) detected from {files.length} file(s)</div>
          <div className="flex flex-col gap-1.5">
            {Object.entries(groups).map(([kg, fs]) => (
              <div key={kg} className="flex flex-wrap items-center gap-2 rounded-lg bg-raised px-3 py-1.5">
                <span className="min-w-24 font-medium">{kg}</span>
                <ArrowRight className="size-3.5 text-ink-3" />
                {fs.map((f) => (
                  <span key={f.name + f.size} className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs">
                    {/\.zip$/i.test(f.name) ? <FileArchive className="size-3" /> : <FileCode2 className="size-3" />}{f.name}
                    <button onClick={() => setFiles(files.filter((x) => x !== f))} aria-label={`remove ${f.name}`}><X className="size-3 text-ink-3 hover:text-bad" /></button>
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={autoLink} onChange={(e) => setAutoLink(e.target.checked)} />Discover owl:sameAs links between KGs</label>
        <label className="flex items-center gap-2 text-sm text-ink-2">threshold
          <input className="input w-20" type="number" min={0} max={1} step={0.05} value={threshold} disabled={!autoLink} onChange={(e) => setThreshold(Number(e.target.value))} /></label>
        <label className="flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={reset} onChange={(e) => setReset(e.target.checked)} />Replace loaded KGs</label>
        <button className="btn-primary ml-auto" disabled={!files.length || run.isPending} onClick={() => run.mutate()}>
          <Workflow className="size-4" />Build {Object.keys(groups).length || ""} MDKG{Object.keys(groups).length === 1 ? "" : "s"}
        </button>
        {run.isPending && <Spinner label="profiling · Otsu · measures · hierarchies · QB4OLAP · linking…" />}
      </div>
      <ErrorBox error={run.error} />
      {report && <Report r={report} />}
    </Card>
  );
}

function Report({ r }: { r: PipelineReport }) {
  const links = r.identity.pairs.flatMap((p) => p.links.map((l) => ({ ...l, kgs: `${p.kg_a} ↔ ${p.kg_b}` })));
  return (
    <div className="mt-5 border-t border-line pt-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold">Pipeline result</h4>
        <a className="btn" href="/api/mdkg.zip" download="mdkg.zip"><Download className="size-4" />Download all MDKGs (.zip)</a>
      </div>
      <div className="mb-4 flex flex-wrap gap-3">
        <Kpi value={r.kgs.length} label="KGs in" />
        <Kpi value={r.kgs.reduce((n, k) => n + k.cubes.length, 0)} label="fact cubes (MDKG)" />
        <Kpi value={r.kgs.reduce((n, k) => n + k.cubes.reduce((m, c) => m + c.observations, 0), 0)} label="observations" />
        <Kpi value={r.identity.supplied_links + r.identity.links_added} label={`identity links (${r.identity.links_added} discovered)`} />
        <Kpi value={r.identity.clusters} label="cross-KG entity clusters" />
        <Kpi value={`${r.seconds.total}s`} label={`KG2MD ${r.seconds.kg2md}s · linking ${r.seconds.linking}s`} />
      </div>
      <DataTable rows={r.kgs} columns={[
        { key: "kg", header: "KG", render: (k) => <span className="font-medium">{k.kg}</span> },
        { key: "files", header: "input files", render: (k) => <span className="text-xs text-ink-2">{k.files.join(", ")}</span> },
        { key: "triples", header: "triples", numeric: true },
        { key: "otsu_threshold", header: "τ*", numeric: true, decimals: 4 },
        { key: "cubes", header: "fact cubes", render: (k) => k.cubes.length
          ? <div className="flex flex-wrap gap-1">{k.cubes.map((c) => <Chip key={c.dataset} tone={c.fact_preservation === 1 && c.measure_fidelity === 1 ? "good" : "bad"}>{c.fact_class} · {c.observations} obs · {c.measures} measures</Chip>)}</div>
          : <Chip tone="warn">no fact class found</Chip> },
        { key: "mdkg", header: "MDKG", render: (k) => <a className="inline-flex items-center gap-1 text-accent hover:underline" href={`/api/kgs/${k.kg}/mdkg.trig`} download><Download className="size-3.5" />.trig</a> },
      ]} />
      {links.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-3"><Link2 className="size-3.5" />Discovered identity links (score ≥ {r.identity.threshold})</h4>
          <DataTable rows={links} max={50} columns={[
            { key: "kgs", header: "KGs" },
            { key: "left", header: "entity", render: (l) => <span>{l.left_label ?? localName(l.left)} <span className="mono text-ink-3">{localName(l.left)}</span></span> },
            { key: "right", header: "same as", render: (l) => <span>{l.right_label ?? localName(l.right)} <span className="mono text-ink-3">{localName(l.right)}</span></span> },
            { key: "score", header: "score", numeric: true, decimals: 3 },
          ]} />
          <p className="mt-2 text-xs text-ink-3">Review these on <b>Links &amp; Communities</b>; links are only ever added explicitly to the identity graph, never inferred silently at query time.</p>
        </div>
      )}
    </div>
  );
}
