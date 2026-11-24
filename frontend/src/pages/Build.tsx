import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { PiCubeFocusDuotone } from "react-icons/pi";
import { TbAlertTriangle, TbCircleCheck, TbDeviceFloppy, TbDownload, TbLink, TbPlus, TbRefresh, TbSearch, TbTrash, TbX } from "react-icons/tb";
import { toast } from "sonner";
import { api, type IdentityLink, type OverviewKg, type PipelineReport } from "@/api/client";
import { useCatalog, useOverview, useRefreshStore } from "@/api/hooks";
import { DotBackdrop, GlowCard, Reveal, Spotlight } from "@/components/fx";
import { Card, Chip, DataTable, ErrorBox, IconAction, Kpi, LoadingBlock, Select, Spinner } from "@/components/kit";
import { MdkgDetails } from "@/components/MdkgDetails";
import { MdkgMap } from "@/components/MdkgMap";
import { Pipeline } from "@/components/Pipeline";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { localName } from "@/lib/format";
import { saveAllMdkgs, saveOneMdkg } from "@/lib/save";
import { useUi } from "@/store";

async function save(kgs: string[]) {
  try {
    const where = await saveAllMdkgs(kgs);
    if (where) toast.success("MDKGs saved", { description: `${where}. Load them in Query or Ask.` });
  } catch (e) {
    toast.error("Could not save", { description: e instanceof Error ? e.message : String(e) });
  }
}

function announce(r: PipelineReport, all: string[]) {
  toast.success(`Built ${r.kgs.length} MDKG${r.kgs.length === 1 ? "" : "s"} in ${r.seconds.total}s`, {
    description: r.identity.auto_link ? `${r.identity.links_added} identity link${r.identity.links_added === 1 ? "" : "s"}` : undefined,
    action: { label: "Save", onClick: () => void save(all.length ? all : r.kgs.map((k) => k.kg)) },
    duration: 10000,
  });
}

export default function BuildPage() {
  const { data: ov, isLoading } = useOverview();
  const { data: cat } = useCatalog("build");
  const [panel, setPanel] = useState<"" | "add" | "replace">("");
  const openKg = useUi((s) => s.openKg);
  const setOpenKg = useUi((s) => s.setOpenKg);

  if (isLoading || !ov) return <LoadingBlock rows={6} />;

  if (!ov.kgs.length) {
    return (
      <div className="relative isolate mx-auto max-w-3xl pt-6">
        <DotBackdrop />
        <Spotlight className="left-1/2 top-0 h-80 w-[36rem] -translate-x-1/2" />
        <div className="rounded-2xl border border-border bg-card/80 p-5 shadow-xl shadow-black/5 backdrop-blur">
          <Pipeline replace hero onDone={(r) => announce(r, [])} />
        </div>
      </div>
    );
  }

  const cubes = ov.kgs.flatMap((k) => k.cubes);
  const open = ov.kgs.find((k) => k.kg === openKg);
  return (
    <>
      <div className="mb-4 flex justify-end gap-1.5">
        <IconAction label="Add KGs" icon={<TbPlus />} variant="outline" onClick={() => setPanel("add")} />
        <IconAction label="Start over" icon={<TbRefresh />} variant="outline" onClick={() => setPanel("replace")} />
        <IconAction label="Download mdkg.zip" icon={<TbDownload />} variant="outline" href={api.mdkgZipUrl()} download="mdkg.zip" />
        <IconAction label="Save MDKGs" icon={<TbDeviceFloppy />} variant="default" onClick={() => void save(ov.kgs.map((k) => k.kg))} />
      </div>

      <div className="mb-5 flex flex-wrap gap-3">
        <Kpi value={ov.kgs.length} label="MDKGs" />
        <Kpi value={cubes.length} label="fact cubes" />
        <Kpi value={cubes.reduce((n, c) => n + c.observations, 0)} label="observations" />
        <Kpi value={ov.identity.links.length} label="identity links" />
        <Kpi value={ov.identity.clusters} label="entities shared across KGs" />
      </div>

      <Reveal deps={[ov.kgs.length]} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {ov.kgs.map((k) => <MdkgCard key={k.kg} k={k} active={openKg === k.kg} onOpen={() => setOpenKg(k.kg)} />)}
      </Reveal>

      {cat && cat.cubes.length > 0 && (
        <Card className="mt-5">
          <MdkgMap cat={cat} links={ov.identity.links} />
        </Card>
      )}

      <IdentityLinks kgs={ov.kgs.map((k) => k.kg)} links={ov.identity.links} />

      <Sheet open={!!open} onOpenChange={(o) => !o && setOpenKg("")}>
        <SheetContent side="right" className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-4xl">
          <SheetHeader>
            <SheetTitle className="text-brand">{openKg}</SheetTitle>
            <SheetDescription className="sr-only">KG2MD run details</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{open && <MdkgDetails kg={open.kg} />}</div>
        </SheetContent>
      </Sheet>

      <Dialog open={!!panel} onOpenChange={(o) => !o && setPanel("")}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{panel === "add" ? "Add KGs" : "Start over"}</DialogTitle>
            <DialogDescription className="sr-only">{panel === "replace" ? "Replace" : "Add"}</DialogDescription>
          </DialogHeader>
          <Pipeline replace={panel === "replace"} onDone={(r) => { announce(r, panel === "add" ? [...ov.kgs.map((k) => k.kg), ...r.kgs.map((k) => k.kg)] : []); setPanel(""); }} />
        </DialogContent>
      </Dialog>
    </>
  );
}

function MdkgCard({ k, active, onOpen }: { k: OverviewKg; active: boolean; onOpen: () => void }) {
  const refresh = useRefreshStore("build");
  const del = useMutation({ mutationFn: () => api.deleteKg("build", k.kg), onSuccess: () => { void refresh(); toast(`Removed ${k.kg}`); } });
  const ok = k.cubes.length > 0 && k.cubes.every((c) => c.fact_preservation === 1 && c.measure_fidelity === 1);
  return (
    <GlowCard data-reveal active={active} className="flex cursor-pointer flex-col gap-3" onClick={onOpen}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-brand/10 text-brand"><PiCubeFocusDuotone className="size-5" /></span>
          <div>
            <div className="font-semibold">{k.kg}</div>
            <div className="text-xs text-ink-3">TBox {k.tbox_triples.toLocaleString()} · ABox {k.abox_triples.toLocaleString()} triples · {k.classes} classes{k.otsu_threshold !== null && <> · τ* {k.otsu_threshold}</>}</div>
          </div>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="text-ink-3 hover:text-bad" onClick={(e) => { e.stopPropagation(); del.mutate(); }} disabled={del.isPending} aria-label={`Remove ${k.kg}`}><TbTrash /></Button>
          </TooltipTrigger>
          <TooltipContent>Remove {k.kg}</TooltipContent>
        </Tooltip>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {k.cubes.length ? k.cubes.map((c) => <Chip key={c.dataset} tone="accent">{c.fact_class} · {c.observations} obs · {c.measures} measures</Chip>)
          : <Chip tone="warn">no fact class found</Chip>}
      </div>
      {k.warnings.length > 0 && (
        <Tooltip>
          <TooltipTrigger asChild><span className="inline-flex w-fit items-center gap-1 text-xs text-warn"><TbAlertTriangle className="size-3.5" />{k.warnings.length}</span></TooltipTrigger>
          <TooltipContent className="max-w-xs">{k.warnings.map((w) => <div key={w}>{w}</div>)}</TooltipContent>
        </Tooltip>
      )}
      <div className="mt-auto flex items-center gap-2 text-xs">
        {ok ? <span className="inline-flex items-center gap-1 text-good"><TbCircleCheck className="size-3.5" />100%</span>
          : k.cubes.length ? <span className="text-bad">audit failed</span> : null}
        <IconAction label={`Save ${k.kg}`} icon={<TbDeviceFloppy />} className="ml-auto text-ink-2" onClick={(e) => {
          e.stopPropagation();
          saveOneMdkg(k.kg).then((w) => w && toast.success(w)).catch((err) => toast.error(String(err)));
        }} />
      </div>
    </GlowCard>
  );
}

function IdentityLinks({ kgs, links }: { kgs: string[]; links: IdentityLink[] }) {
  const [finding, setFinding] = useState(false);
  return (
    <Card className="mt-5" title={<span className="flex items-center gap-2"><TbLink className="size-4 text-brand" />{links.length}</span>}
      actions={kgs.length > 1 && <IconAction label={finding ? "Done" : "Find links"} icon={finding ? <TbX /> : <TbSearch />} variant="outline" onClick={() => setFinding(!finding)} />}>
      {finding && <FindLinks kgs={kgs} />}
      {links.length ? (
        <DataTable rows={links} max={100} columns={[
          { key: "left", header: "entity", render: (l) => <span>{l.left_label ?? localName(l.left)} <span className="text-xs text-ink-3">in {l.left_kg}</span></span> },
          { key: "right", header: "same as", render: (l) => <span>{l.right_label ?? localName(l.right)} <span className="text-xs text-ink-3">in {l.right_kg}</span></span> },
        ]} />
      ) : <p className="text-sm text-ink-3">No links</p>}
    </Card>
  );
}

function FindLinks({ kgs }: { kgs: string[] }) {
  const [a, setA] = useState(kgs[0]);
  const [b, setB] = useState(kgs[1] ?? kgs[0]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const refresh = useRefreshStore("build");
  const discover = useMutation({
    mutationFn: () => api.discover({ kg_a: a, kg_b: b, threshold: 0.5 }),
    onSuccess: (r) => setPicked(new Set(r.candidates.map((c, i) => (c.score >= 0.5 && !c.known ? i : -1)).filter((i) => i >= 0))),
  });
  const accept = useMutation({ mutationFn: api.addLinks, onSuccess: (r) => { discover.reset(); void refresh(); toast.success(`${r.links_added} link(s) added`); } });
  const opts = kgs.map((k) => ({ value: k, label: k }));
  const cands = (discover.data?.candidates ?? []).map((c, i) => ({ ...c, i })).filter((c) => !c.known);
  return (
    <div className="mb-4 rounded-xl bg-raised/60 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="w-40"><Select label="Between" value={a} onChange={setA} options={opts} /></div>
        <div className="w-40"><Select label="and" value={b} onChange={setB} options={opts} /></div>
        <Button disabled={a === b || discover.isPending} onClick={() => discover.mutate()}><TbSearch />Find candidates</Button>
        {discover.isPending && <Spinner />}
      </div>
      <ErrorBox error={discover.error} />
      {discover.data && (cands.length ? (
        <div className="mt-3">
          <DataTable rows={cands} max={30} columns={[
            { key: "i", header: "", render: (c) => <input type="checkbox" className="accent-[var(--c-brand)]" checked={picked.has(c.i)} onChange={() => {
              const s = new Set(picked); if (s.has(c.i)) s.delete(c.i); else s.add(c.i); setPicked(s); }} /> },
            { key: "left", header: a, render: (c) => c.left_label ?? localName(c.left) },
            { key: "right", header: b, render: (c) => c.right_label ?? localName(c.right) },
            { key: "score", header: "confidence", numeric: true, decimals: 2 },
          ]} />
          <Button className="mt-2" disabled={!picked.size || accept.isPending}
            onClick={() => accept.mutate([...picked].map((i) => [discover.data!.candidates[i].left, discover.data!.candidates[i].right] as [string, string]))}>
            <TbLink />Link {picked.size} selected
          </Button>
        </div>
      ) : <p className="mt-2 text-sm text-ink-3">No new candidates between {a} and {b}.</p>)}
    </div>
  );
}
