import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { PiCubeFocusDuotone, PiGraphDuotone, PiTreeStructureDuotone } from "react-icons/pi";
import { TbArrowRight, TbCircleCheck, TbDownload, TbLink, TbPlus, TbRefresh, TbSearch, TbTrash } from "react-icons/tb";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, type IdentityLink, type OverviewKg, type PipelineReport } from "@/api/client";
import { useCatalog, useOverview, useRefreshStore } from "@/api/hooks";
import { DotBackdrop, GlowCard, Reveal, Spotlight } from "@/components/fx";
import { Card, Chip, DataTable, ErrorBox, Kpi, LoadingBlock, PageHeader, Select, Spinner } from "@/components/kit";
import { MdkgDetails } from "@/components/MdkgDetails";
import { MdkgMap } from "@/components/MdkgMap";
import { Pipeline } from "@/components/Pipeline";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { localName } from "@/lib/format";
import { useUi } from "@/store";

function announce(r: PipelineReport) {
  toast.success(`Built ${r.kgs.length} MDKG${r.kgs.length === 1 ? "" : "s"} in ${r.seconds.total}s`, {
    description: r.identity.auto_link ? `${r.identity.links_added} identity link${r.identity.links_added === 1 ? "" : "s"} discovered · ${r.identity.clusters} shared entities` : undefined,
  });
}

export default function BuildPage() {
  const { data: ov, isLoading } = useOverview();
  const { data: cat } = useCatalog();
  const [panel, setPanel] = useState<"" | "add" | "replace">("");
  const openKg = useUi((s) => s.openKg);
  const setOpenKg = useUi((s) => s.setOpenKg);

  if (isLoading || !ov) return <LoadingBlock rows={6} />;

  if (!ov.kgs.length) {
    return (
      <div className="relative isolate mx-auto max-w-3xl pt-6">
        <DotBackdrop />
        <Spotlight className="left-1/2 top-0 h-80 w-[36rem] -translate-x-1/2" />
        <div className="mb-8 text-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3 py-1 text-xs text-ink-2 backdrop-blur">
            <PiCubeFocusDuotone className="size-4 text-brand" />Step 1 of 3
          </span>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight">Turn your knowledge graphs into <span className="bg-gradient-to-r from-brand to-[var(--s7)] bg-clip-text text-transparent">MDKGs</span></h1>
          <p className="mx-auto mt-3 max-w-xl text-ink-2">Drop the whole set. Each KG becomes a multidimensional KG with cubes, measures and hierarchies, and the KGs are linked so you can query and ask across all of them.</p>
        </div>
        <div className="rounded-2xl border border-border bg-card/80 p-5 shadow-xl shadow-black/5 backdrop-blur">
          <Pipeline replace hero onDone={announce} />
        </div>
        <Reveal className="mt-8 grid gap-3 sm:grid-cols-3">
          {([[PiCubeFocusDuotone, "Build", "Fact classes, measures and hierarchies are found automatically."],
            [PiTreeStructureDuotone, "Query", "Pick a measure and a level; results appear instantly."],
            [PiGraphDuotone, "Ask", "Type a question in plain language."]] as const).map(([Icon, t, d], i) => (
            <div key={t} data-reveal className="rounded-xl border border-border bg-card/70 p-4 backdrop-blur">
              <Icon className="size-6 text-brand" /><div className="mt-2 font-semibold">{i + 1} · {t}</div>
              <div className="text-sm text-ink-2">{d}</div>
            </div>
          ))}
        </Reveal>
      </div>
    );
  }

  const cubes = ov.kgs.flatMap((k) => k.cubes);
  const open = ov.kgs.find((k) => k.kg === openKg);
  return (
    <>
      <PageHeader title="Your MDKGs" description="One multidimensional KG per input KG, linked through shared entities. Open a card to see how it was built.">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setPanel("add")}><TbPlus />Add KGs</Button>
          <Button variant="outline" onClick={() => setPanel("replace")}><TbRefresh />Start over</Button>
          <Button variant="outline" asChild><a href="/api/mdkg.zip" download="mdkg.zip"><TbDownload />Download all</a></Button>
          <Button asChild><Link to="/query">Query them<TbArrowRight /></Link></Button>
        </div>
      </PageHeader>

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
        <Card className="mt-5" title={<span className="flex items-center gap-2"><PiGraphDuotone className="size-5 text-brand" />Map of your MDKGs</span>}
          subtitle="Each cube with its dimension levels; orange edges join the same entity across MDKGs. Hover to focus, scroll to zoom.">
          <MdkgMap cat={cat} links={ov.identity.links} />
        </Card>
      )}

      <IdentityLinks kgs={ov.kgs.map((k) => k.kg)} links={ov.identity.links} />

      <Sheet open={!!open} onOpenChange={(o) => !o && setOpenKg("")}>
        <SheetContent side="right" className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-4xl">
          <SheetHeader>
            <SheetTitle>How <span className="text-brand">{openKg}</span> became an MDKG</SheetTitle>
            <SheetDescription>Otsu fact selection, measure additivity with SHAP/LIME, ADW4 hierarchies and the preservation audit.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{open && <MdkgDetails kg={open.kg} />}</div>
        </SheetContent>
      </Sheet>

      <Dialog open={!!panel} onOpenChange={(o) => !o && setPanel("")}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{panel === "add" ? "Add knowledge graphs to this set" : "Start over with a new set"}</DialogTitle>
            <DialogDescription>{panel === "replace" ? "The current MDKGs and identity links will be replaced." : "New KGs are built and linked to the ones already loaded."}</DialogDescription>
          </DialogHeader>
          <Pipeline replace={panel === "replace"} onDone={(r) => { announce(r); setPanel(""); }} />
        </DialogContent>
      </Dialog>
    </>
  );
}

function MdkgCard({ k, active, onOpen }: { k: OverviewKg; active: boolean; onOpen: () => void }) {
  const refresh = useRefreshStore();
  const del = useMutation({ mutationFn: () => api.deleteKg(k.kg), onSuccess: () => { void refresh(); toast(`Removed ${k.kg}`); } });
  const ok = k.cubes.length > 0 && k.cubes.every((c) => c.fact_preservation === 1 && c.measure_fidelity === 1);
  return (
    <GlowCard data-reveal active={active} className="flex cursor-pointer flex-col gap-3" onClick={onOpen}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-brand/10 text-brand"><PiCubeFocusDuotone className="size-5" /></span>
          <div>
            <div className="font-semibold">{k.kg}</div>
            <div className="text-xs text-ink-3">{k.triples.toLocaleString()} triples · {k.classes} classes · τ* {k.otsu_threshold}</div>
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
      <div className="mt-auto flex items-center gap-2 text-xs">
        {ok ? <span className="inline-flex items-center gap-1 text-good"><TbCircleCheck className="size-3.5" />all facts &amp; measures preserved</span>
          : k.cubes.length ? <span className="text-bad">audit: values not preserved</span> : null}
        <a className="ml-auto inline-flex items-center gap-1 text-ink-2 hover:text-brand" href={`/api/kgs/${k.kg}/mdkg.trig`} download onClick={(e) => e.stopPropagation()}><TbDownload className="size-3.5" />.trig</a>
      </div>
    </GlowCard>
  );
}

function IdentityLinks({ kgs, links }: { kgs: string[]; links: IdentityLink[] }) {
  const [finding, setFinding] = useState(false);
  return (
    <Card className="mt-5" title={<span className="flex items-center gap-2"><TbLink className="size-4 text-brand" />Identity links ({links.length})</span>}
      subtitle="The same real-world entity in different KGs (owl:sameAs). Queries that combine MDKGs join through these."
      actions={kgs.length > 1 && <Button variant="outline" size="sm" onClick={() => setFinding(!finding)}><TbSearch />{finding ? "Done" : "Find more links"}</Button>}>
      {finding && <FindLinks kgs={kgs} />}
      {links.length ? (
        <DataTable rows={links} max={100} columns={[
          { key: "left", header: "entity", render: (l) => <span>{l.left_label ?? localName(l.left)} <span className="text-xs text-ink-3">in {l.left_kg}</span></span> },
          { key: "right", header: "same as", render: (l) => <span>{l.right_label ?? localName(l.right)} <span className="text-xs text-ink-3">in {l.right_kg}</span></span> },
        ]} />
      ) : <p className="text-sm text-ink-3">No links yet{kgs.length > 1 ? ". Use “Find more links” to discover some." : ". Add a second KG to link them."}</p>}
    </Card>
  );
}

function FindLinks({ kgs }: { kgs: string[] }) {
  const [a, setA] = useState(kgs[0]);
  const [b, setB] = useState(kgs[1] ?? kgs[0]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const refresh = useRefreshStore();
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
