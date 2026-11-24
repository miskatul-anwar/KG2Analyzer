import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useRef, useState, type DragEvent } from "react";
import { PiDatabaseDuotone, PiTreeStructureDuotone } from "react-icons/pi";
import { TbFileZip, TbPlus, TbSettings, TbTrash, TbUpload, TbX } from "react-icons/tb";
import { api, type PipelineReport } from "@/api/client";
import { useRefreshStore, useStatus } from "@/api/hooks";
import { ShimmerButton } from "@/components/fx";
import { ErrorBox } from "@/components/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useUi } from "@/store";

const RDF = /\.(ttl|nt|n3|rdf|owl|xml|jsonld|json-ld|nq|trig)$/i;
const ROLE_SUFFIX = /[-_. ]*(tbox|abox|schema|ontology|onto|data|instances|kg)$/i;
const ROLE_ONLY = /^(tbox|abox|schema|ontology|onto|data|instances)$/i;
const TBOX = /(?:^|[-_. ])(tbox|schema|ontology|onto)(?:$|[-_. ])/i;
const ABOX = /(?:^|[-_. ])(abox|data|instances)(?:$|[-_. ])/i;
const IDENTITY = /(sameas|identity|links)/i;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
const relPath = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;

type Role = "tbox" | "abox" | "both";
interface Row { id: number; name: string; tbox: File[]; abox: File[]; both: File[] }

/** Mirrors backend `ingest.kg_name` / `ingest.file_role`, so the user sees the assignment before uploading. */
function classify(f: File): { kg: string; role: Role } {
  const parts = relPath(f).split("/");
  const folders = parts.slice(0, -1).filter((d) => !ROLE_ONLY.test(d));
  const stem = parts[parts.length - 1].split(".")[0];
  const roleFolder = parts.slice(0, -1).reverse().find((d) => ROLE_ONLY.test(d));
  const role: Role = roleFolder ? (/^(tbox|schema|ontology|onto)$/i.test(roleFolder) ? "tbox" : "abox")
    : TBOX.test(stem) ? "tbox" : ABOX.test(stem) ? "abox" : "both";
  const kg = folders.length ? slug(folders[folders.length - 1]) : ROLE_ONLY.test(stem) ? "" : slug(stem.replace(ROLE_SUFFIX, "")) || slug(stem);
  return { kg, role };
}

let nextId = 1;
const newRow = (name = ""): Row => ({ id: nextId++, name, tbox: [], abox: [], both: [] });
const filled = (r: Row) => r.tbox.length + r.abox.length + r.both.length > 0;

/** Build input: one row per KG with a TBox slot and an ABox slot. `replace` starts a new set, otherwise KGs are added. */
export function Pipeline({ replace, hero, onDone }: { replace: boolean; hero?: boolean; onDone?: (r: PipelineReport) => void }) {
  const [rows, setRows] = useState<Row[]>([newRow()]);
  const [extras, setExtras] = useState<File[]>([]); // zips and owl:sameAs files, grouped by the backend
  const [drag, setDrag] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [autoLink, setAutoLink] = useState(true);
  const [threshold, setThreshold] = useState(0.6);
  const bulk = useRef<HTMLInputElement>(null);
  const refresh = useRefreshStore("build");
  const qc = useQueryClient();
  const { data: st } = useStatus("build");
  const pref = useUi((s) => s.useTev1);
  const setPref = useUi((s) => s.setUseTev1);
  const tev1Installed = st?.tev1_available ?? false;
  const tev1 = tev1Installed && (pref ?? true);

  const ready = rows.filter(filled);
  const incomplete = ready.filter((r) => !r.both.length && (!r.tbox.length || !r.abox.length));
  const unnamed = ready.filter((r) => !slug(r.name));
  const canBuild = (ready.length > 0 || extras.length > 0) && !incomplete.length && !unnamed.length;

  const run = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      for (const r of ready) {
        const kg = slug(r.name);
        r.tbox.forEach((f) => fd.append("files", f, `${kg}/tbox/${f.name}`));
        r.abox.forEach((f) => fd.append("files", f, `${kg}/abox/${f.name}`));
        r.both.forEach((f) => fd.append("files", f, `${kg}/${f.name}`));
      }
      extras.forEach((f) => fd.append("files", f, relPath(f)));
      fd.append("auto_link", String(autoLink));
      fd.append("threshold", String(threshold));
      fd.append("reset", String(replace));
      fd.append("decider", tev1 ? "tev1" : "structural");
      return api.pipeline(fd);
    },
    onSuccess: async (r) => {
      setRows([newRow()]); setExtras([]); void refresh(); onDone?.(r);
      // hand the new MDKGs to Query and Ask straight away (as the files Build saves; nothing to pick)
      await Promise.allSettled((["query", "ask"] as const).map((ws) => api.fromBuild(ws)));
      void qc.invalidateQueries({ queryKey: ["query"] });
      void qc.invalidateQueries({ queryKey: ["ask"] });
    },
  });

  /** Bulk drop: assign each file to a KG row and a role by its name/folder. */
  const assign = (list: FileList | File[]) => {
    const files = [...list];
    setExtras((cur) => [...cur, ...files.filter((f) => /\.zip$/i.test(f.name) || (RDF.test(f.name) && IDENTITY.test(f.name)))]);
    setRows((cur) => {
      const out = cur.filter((r) => r.name || filled(r)).map((r) => ({ ...r }));
      for (const f of files) {
        if (!RDF.test(f.name) || IDENTITY.test(f.name)) continue;
        const { kg, role } = classify(f);
        let row = kg ? out.find((r) => slug(r.name) === kg) : undefined;
        if (!row) { row = newRow(kg); out.push(row); }
        row[role] = [...row[role], f];
      }
      return out.length ? out : [newRow()];
    });
  };
  const setSlot = (id: number, role: Role, files: File[]) => setRows((cur) => cur.map((r) => (r.id === id ? { ...r, [role]: files } : r)));
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); assign(e.dataTransfer.files); };

  return (
    <div>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        className={clsx("rounded-2xl border-2 border-dashed p-3 transition", drag ? "border-brand bg-brand/5" : "border-border")}>
        <div className={clsx("flex flex-wrap items-center justify-between gap-2 px-1", hero ? "pb-3" : "pb-2")}>
          <div className="text-sm text-ink-2">
            Give each knowledge graph its <b className="text-ink">TBox</b> (schema) and <b className="text-ink">ABox</b> (instances).
            <span className="text-ink-3"> Drop many files here to assign them by name.</span>
          </div>
          <Button variant="outline" size="sm" onClick={() => bulk.current?.click()}><TbUpload />Add files…</Button>
          <input ref={bulk} type="file" multiple hidden accept=".ttl,.nt,.n3,.rdf,.owl,.xml,.jsonld,.nq,.trig,.zip"
            onChange={(e) => { if (e.target.files) assign(e.target.files); e.target.value = ""; }} />
        </div>

        <div className="flex flex-col gap-2">
          {rows.map((r) => (
            <div key={r.id} data-kg-row className="grid gap-2 rounded-xl border border-border bg-card p-2.5 md:grid-cols-[170px_1fr_1fr_auto] md:items-center">
              <Input value={r.name} placeholder="KG name" aria-label="KG name" className={clsx(!slug(r.name) && filled(r) && "border-bad")}
                onChange={(e) => setRows((cur) => cur.map((x) => (x.id === r.id ? { ...x, name: e.target.value } : x)))} />
              {r.both.length ? (
                <div className="flex items-center gap-2 rounded-lg bg-raised px-3 py-2 text-xs text-ink-2 md:col-span-2">
                  <TbFileZip className="size-4 shrink-0 text-brand" /><span className="truncate">{r.both.map((f) => f.name).join(", ")}</span>
                  <span className="hidden text-ink-3 lg:inline">· combined file, split into TBox and ABox automatically</span>
                  <button className="ml-auto text-ink-3 hover:text-bad" onClick={() => setSlot(r.id, "both", [])} aria-label="remove"><TbX /></button>
                </div>
              ) : (
                <>
                  <Slot label="TBox" hint="schema / ontology" icon={<PiTreeStructureDuotone className="size-4" />} files={r.tbox} onFiles={(f) => setSlot(r.id, "tbox", f)} />
                  <Slot label="ABox" hint="instances / data" icon={<PiDatabaseDuotone className="size-4" />} files={r.abox} onFiles={(f) => setSlot(r.id, "abox", f)} />
                </>
              )}
              <Button variant="ghost" size="icon-sm" className="justify-self-end text-ink-3 hover:text-bad" aria-label="Remove KG"
                onClick={() => setRows((cur) => (cur.length > 1 ? cur.filter((x) => x.id !== r.id) : [newRow()]))}><TbTrash /></Button>
            </div>
          ))}
          {extras.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs text-ink-2">
              <TbFileZip className="size-4 text-brand" />Also uploading: {extras.map((f) => f.name).join(", ")}
              <span className="text-ink-3">(archives are unpacked; owl:sameAs files become identity links)</span>
              <button className="ml-auto text-ink-3 hover:text-bad" onClick={() => setExtras([])} aria-label="remove"><TbX /></button>
            </div>
          )}
          <button className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-border py-2 text-sm text-ink-2 transition hover:border-brand hover:text-brand"
            onClick={() => setRows((cur) => [...cur, newRow()])}><TbPlus />Add another knowledge graph</button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <ShimmerButton disabled={!canBuild || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? "Building…" : extras.some((f) => /\.zip$/i.test(f.name)) ? "Build MDKGs" : `Build ${ready.length || ""} MDKG${ready.length === 1 ? "" : "s"}`}
        </ShimmerButton>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-sm">
              <Switch id="tev1" checked={tev1} disabled={!tev1Installed || run.isPending} onCheckedChange={setPref} />
              <Label htmlFor="tev1" className={clsx(!tev1Installed && "text-ink-3")}>Tev1</Label>
              <span className="text-xs text-ink-3">{!tev1Installed ? "not installed" : tev1 ? (st?.tev1_loaded ? "ready" : "loading…") : "off · structural"}</span>
            </div>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            {tev1Installed
              ? tev1 ? "KG2MD's decision model answers the fact-class, aggregate, unit and level-attribute questions. Answers are cached, so rebuilding the same KGs is quick."
                : "Off: the structural stand-in decides from the class structure and property names in milliseconds. Results are marked “not Tev1”."
              : "Install Tev1 with `uv sync --extra tev1` (PyTorch + transformers; the model downloads on first use). Until then, builds use the structural stand-in."}
          </TooltipContent>
        </Tooltip>
        {run.isPending && <span className="text-xs text-ink-3">running the KG2MD notebook ({tev1 ? "Tev1 decisions" : "structural decisions"} · Otsu · hierarchies · QB4OLAP · audit), then linking.{tev1 && " With Tev1 on a CPU, a new KG takes up to a minute."}</span>}
        {!run.isPending && incomplete.length > 0 && <span className="text-xs text-warn">{incomplete.map((r) => r.name || "a KG").join(", ")}: add both a TBox and an ABox</span>}
        {!run.isPending && unnamed.length > 0 && <span className="text-xs text-warn">Name every knowledge graph</span>}
        <button className="ml-auto inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink" onClick={() => setShowOptions(!showOptions)}>
          <TbSettings className="size-3.5" />Options
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

/** One TBox or ABox drop slot. */
function Slot({ label, hint, icon, files, onFiles }: { label: string; hint: string; icon: React.ReactNode; files: File[]; onFiles: (f: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const add = (list: FileList | null) => { if (list?.length) onFiles([...files, ...[...list].filter((f) => RDF.test(f.name))]); };
  return (
    <div role="button" tabIndex={0} data-slot={label} onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); e.stopPropagation(); setDrag(false); add(e.dataTransfer.files); }}
      className={clsx("flex min-h-11 min-w-0 cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition",
        files.length ? "border-good/40 bg-good/5" : drag ? "border-brand bg-brand/5" : "border-dashed border-border hover:border-brand/60")}>
      <span className={clsx("shrink-0", files.length ? "text-good" : "text-brand")}>{icon}</span>
      {files.length ? (
        <>
          <span className="font-semibold text-ink">{label}</span>
          <span className="truncate text-ink-2">{files.map((f) => f.name).join(", ")}</span>
          <button className="ml-auto text-ink-3 hover:text-bad" aria-label={`clear ${label}`} onClick={(e) => { e.stopPropagation(); onFiles([]); }}><TbX /></button>
        </>
      ) : (
        <span className="truncate"><b className="text-ink">{label}</b> <span className="text-ink-3">· {hint} · drop or click</span></span>
      )}
      <input ref={input} type="file" multiple hidden accept=".ttl,.nt,.n3,.rdf,.owl,.xml,.jsonld,.nq,.trig" onClick={(e) => e.stopPropagation()}
        onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
    </div>
  );
}
