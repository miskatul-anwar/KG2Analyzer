import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, FileArchive, FileCode2, Settings2, UploadCloud, Workflow, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { api, type PipelineReport } from "@/api/client";
import { useRefreshStore } from "@/api/hooks";
import { ShimmerButton } from "@/components/fx";
import { ErrorBox } from "@/components/kit";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useUi } from "@/store";

const RDF = /\.(ttl|nt|n3|rdf|owl|xml|jsonld|json-ld|nq|trig|zip)$/i;
const ROLE_SUFFIX = /[-_. ]*(tbox|abox|schema|ontology|onto|data|instances|kg)$/i;
const ROLE_ONLY = /^(tbox|abox|schema|ontology|onto|data|instances)$/i;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
const relPath = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;

/** Mirror of backend `ingest.kg_name`, so users see the grouping before uploading. */
function kgOf(f: File): string {
  const parts = relPath(f).split("/");
  if (parts.length > 2) return slug(parts[parts.length - 2]) || "kg";
  const stem = parts[parts.length - 1].split(".")[0];
  if (/\.zip$/i.test(f.name)) return `${slug(stem.replace(ROLE_SUFFIX, "")) || "kg"} (zip)`;
  if (ROLE_ONLY.test(stem)) return "kg";
  return slug(stem.replace(ROLE_SUFFIX, "")) || slug(stem) || "kg";
}

/** Drop a set of KGs; builds one MDKG per KG and links them. `replace` starts a new set, otherwise KGs are added. */
export function Pipeline({ replace, hero, onDone }: { replace: boolean; hero?: boolean; onDone?: (r: PipelineReport) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [autoLink, setAutoLink] = useState(true);
  const [threshold, setThreshold] = useState(0.6);
  const input = useRef<HTMLInputElement>(null);
  const refresh = useRefreshStore();
  const resetUi = useUi((s) => s.resetForNewData);

  const run = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f, relPath(f)));
      fd.append("auto_link", String(autoLink));
      fd.append("threshold", String(threshold));
      fd.append("reset", String(replace));
      return api.pipeline(fd);
    },
    onSuccess: (r) => {
      setFiles([]);
      if (replace) resetUi();
      void refresh();
      onDone?.(r);
    },
  });

  const add = (list: FileList | null) => {
    if (!list) return;
    const incoming = [...list].filter((f) => RDF.test(f.name));
    setFiles((cur) => [...cur, ...incoming.filter((f) => !cur.some((c) => relPath(c) === relPath(f) && c.size === f.size))]);
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); };
  const groups = files.reduce<Record<string, File[]>>((acc, f) => ((acc[kgOf(f)] ??= []).push(f), acc), {});
  const n = Object.keys(groups).length;

  return (
    <div>
      <div
        role="button" tabIndex={0}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        className={clsx("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-4 text-center transition",
          hero ? "py-16" : "py-8", drag ? "border-brand bg-brand/5" : "border-line hover:border-brand/60 hover:bg-raised/40")}>
        <UploadCloud className={clsx("text-brand", hero ? "size-12" : "size-8")} />
        <div className={clsx("font-semibold", hero && "text-lg")}>Drop your knowledge graphs here</div>
        <div className="max-w-xl text-xs text-ink-3">
          Any mix of RDF files (Turtle, N-Triples, RDF/XML, OWL, JSON-LD, N-Quads, TriG), TBox + ABox pairs such as
          <span className="mono"> sales_tbox.ttl</span> + <span className="mono">sales_abox.ttl</span>, folders, .zip archives, and optional owl:sameAs files.
        </div>
        <span className="mt-1 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium shadow-xs">or browse files</span>
        <input ref={input} type="file" multiple hidden accept=".ttl,.nt,.n3,.rdf,.owl,.xml,.jsonld,.nq,.trig,.zip"
          onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>

      {files.length > 0 && (
        <div className="mt-4 flex flex-col gap-1.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-ink-3">{n} knowledge graph{n === 1 ? "" : "s"} detected</div>
          {Object.entries(groups).map(([kg, fs]) => (
            <div key={kg} className="flex flex-wrap items-center gap-2 rounded-lg bg-raised px-3 py-1.5">
              <span className="min-w-24 font-medium">{kg}</span>
              <ArrowRight className="size-3.5 text-ink-3" />
              {fs.map((f) => (
                <span key={relPath(f) + f.size} className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs">
                  {/\.zip$/i.test(f.name) ? <FileArchive className="size-3" /> : <FileCode2 className="size-3" />}{f.name}
                  <button onClick={() => setFiles(files.filter((x) => x !== f))} aria-label={`remove ${f.name}`}><X className="size-3 text-ink-3 hover:text-bad" /></button>
                </span>
              ))}
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <ShimmerButton disabled={!files.length || run.isPending} onClick={() => run.mutate()}>
          <Workflow className={clsx("size-4", run.isPending && "animate-spin")} />{run.isPending ? "Building…" : `Build ${n || ""} MDKG${n === 1 ? "" : "s"}`}
        </ShimmerButton>
        {run.isPending && <span className="text-xs text-ink-3">profiling · Otsu · measures · hierarchies · QB4OLAP · linking</span>}
        <button className="ml-auto inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink" onClick={() => setShowOptions(!showOptions)}>
          <Settings2 className="size-3.5" />Options
        </button>
      </div>
      {showOptions && (
        <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg bg-raised px-3 py-2.5 text-sm text-ink-2">
          <div className="flex items-center gap-2">
            <Switch id="autolink" checked={autoLink} onCheckedChange={setAutoLink} />
            <Label htmlFor="autolink">Discover owl:sameAs links between the KGs</Label>
          </div>
          <div className="flex min-w-56 items-center gap-3">
            <span className={clsx(!autoLink && "opacity-50")}>confidence ≥ <b className="tabular-nums text-ink">{threshold.toFixed(2)}</b></span>
            <Slider className="w-32" min={0.3} max={0.95} step={0.05} value={[threshold]} disabled={!autoLink} onValueChange={([v]) => setThreshold(v)} />
          </div>
        </div>
      )}
      <ErrorBox error={run.error} />
    </div>
  );
}
