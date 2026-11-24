import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { PiCubeFocusDuotone, PiFolderOpenDuotone } from "react-icons/pi";
import { TbArrowBarToRight, TbFile, TbFolderOpen, TbLink, TbTrash, TbX } from "react-icons/tb";
import { toast } from "sonner";
import { api, type Ws } from "@/api/client";
import { useMdkgs, useOverview, useRefreshStore } from "@/api/hooks";
import { DotBackdrop, ShimmerButton, Spotlight } from "@/components/fx";
import { ErrorBox, IconAction, LoadingBlock } from "@/components/kit";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const ACCEPT = ".nq,.ttl,.zip,.json,.nt";
const relPath = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;

/**
 * Loads MDKG files saved from step 1 into one section's own workspace (Query or Ask) and shows what is loaded.
 * Renders `children` only once at least one MDKG is loaded.
 */
export function MdkgLoader({ ws, children }: { ws: Exclude<Ws, "build">; children: ReactNode }) {
  const { data, isLoading } = useMdkgs(ws);
  const refresh = useRefreshStore(ws);
  const input = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [autoLink, setAutoLink] = useState(true);

  const load = useMutation({
    mutationFn: (files: File[]) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f, relPath(f)));
      fd.append("auto_link", String(autoLink));
      return api.loadMdkgs(ws, fd);
    },
    onSuccess: (r) => {
      void refresh();
      const links = r.identity.total_links;
      toast.success(`${r.mdkgs.length} MDKG${r.mdkgs.length === 1 ? "" : "s"} ready`, { description: links ? `${links} identity links · ${r.identity.clusters} shared entities` : undefined });
    },
  });
  const { data: built } = useOverview();
  const builtKgs = (built?.kgs ?? []).filter((k) => k.cubes.length).map((k) => k.kg);
  const fromBuild = useMutation({
    mutationFn: () => api.fromBuild(ws),
    onSuccess: (r) => {
      void refresh();
      toast.success(`Using ${r.mdkgs.length} MDKG${r.mdkgs.length === 1 ? "" : "s"} from Build`, { description: r.identity.total_links ? `${r.identity.total_links} identity links` : undefined });
    },
  });
  const remove = useMutation({ mutationFn: (kg: string) => api.deleteKg(ws, kg), onSuccess: () => void refresh() });
  const clear = useMutation({ mutationFn: () => api.reset(ws), onSuccess: () => void refresh() });
  const pick = (list: FileList | null) => { if (list?.length) load.mutate([...list]); };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files); };
  const fileInput = (
    <>
      <input ref={input} type="file" multiple hidden accept={ACCEPT} onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
      {/* a whole saved folder: <kg>/fact_classes/<cube>/mdkg_*.ttl|nq (webkitdirectory keeps the relative paths) */}
      <input ref={folder} type="file" multiple hidden {...{ webkitdirectory: "" }} onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
    </>
  );

  if (isLoading) return <LoadingBlock rows={4} />;
  const mdkgs = data?.mdkgs ?? [];

  if (!mdkgs.length) {
    return (
      <div className="relative isolate mx-auto max-w-3xl pt-4">
        <DotBackdrop />
        <Spotlight className="left-1/2 top-0 h-72 w-[32rem] -translate-x-1/2" />
        {builtKgs.length > 0 && (
          <div className="mt-5 flex flex-col items-center gap-2">
            <ShimmerButton disabled={fromBuild.isPending} onClick={() => fromBuild.mutate()}>
              <TbArrowBarToRight className="size-4" />
              {fromBuild.isPending ? "Loading…" : `Use ${builtKgs.join(", ")}`}
            </ShimmerButton>
            <ErrorBox error={fromBuild.error} />
          </div>
        )}
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
          onClick={() => input.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          className={clsx("mt-6 flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed bg-card/80 px-4 py-14 text-center backdrop-blur transition",
            drag ? "border-brand bg-brand/5" : "border-border hover:border-brand/60")}>
          <PiFolderOpenDuotone className="size-12 text-brand" />
          <div className="mt-2 flex flex-wrap justify-center gap-2">
            <ShimmerButton disabled={load.isPending} onClick={(e) => { e.stopPropagation(); folder.current?.click(); }}>
              {load.isPending ? "Loading…" : "Folder"}
            </ShimmerButton>
            <Button variant="outline" disabled={load.isPending} onClick={(e) => { e.stopPropagation(); input.current?.click(); }}>Files</Button>
          </div>
          {fileInput}
        </div>
        <div className="mt-3 flex items-center gap-2 text-sm text-ink-2">
          <Switch id={`al-${ws}`} checked={autoLink} onCheckedChange={setAutoLink} />
          <Label htmlFor={`al-${ws}`}>Auto-link</Label>
        </div>
        <ErrorBox error={load.error} />
      </div>
    );
  }

  return (
    <>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        className={clsx("mb-5 flex flex-wrap items-center gap-2 rounded-2xl border bg-card px-3 py-2.5 shadow-xs transition",
          drag ? "border-brand bg-brand/5" : "border-border")}>
        {mdkgs.map((m) => (
          <Tooltip key={m.kg}>
            <TooltipTrigger asChild>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/30 bg-brand/5 py-0.5 pl-2 pr-1 text-xs text-brand">
                <PiCubeFocusDuotone className="size-3.5" />{m.kg}
                <span className="text-ink-3">· {m.cubes.map((c) => c.fact_class).join(", ") || "no cube"}</span>
                <button className="rounded-full p-0.5 text-ink-3 hover:bg-bad/10 hover:text-bad" aria-label={`Unload ${m.kg}`} onClick={() => remove.mutate(m.kg)}><TbX className="size-3" /></button>
              </span>
            </TooltipTrigger>
            <TooltipContent>{m.cubes.reduce((n, c) => n + c.observations, 0).toLocaleString()} observations · from {m.files.join(", ") || "upload"}</TooltipContent>
          </Tooltip>
        ))}
        {(data?.identity_links ?? 0) > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-ink-3"><TbLink className="size-3.5" />{data!.identity_links} links · {data!.clusters} shared entities</span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {load.isPending && <span className="text-xs text-ink-3">loading…</span>}
          {builtKgs.length > 0 && <IconAction label={`Use built MDKGs (${builtKgs.join(", ")})`} icon={<TbArrowBarToRight />} disabled={fromBuild.isPending} onClick={() => fromBuild.mutate()} />}
          <IconAction label="Load a folder" icon={<TbFolderOpen />} onClick={() => folder.current?.click()} />
          <IconAction label="Load files" icon={<TbFile />} onClick={() => input.current?.click()} />
          <IconAction label="Unload all" icon={<TbTrash />} className="text-ink-3 hover:text-bad" onClick={() => clear.mutate()} />
          {fileInput}
        </div>
      </div>
      <ErrorBox error={load.error} />
      {children}
    </>
  );
}
