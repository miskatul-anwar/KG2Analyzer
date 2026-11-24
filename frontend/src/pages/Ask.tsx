import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { PiSparkleDuotone } from "react-icons/pi";
import { TbArrowUp, TbCircleCheck, TbCircleX, TbShieldX, TbTrash } from "react-icons/tb";
import { useLocation, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Answer } from "@/api/client";
import { useRefreshStore, useStatus, useSuggestions } from "@/api/hooks";
import { MdkgLoader } from "@/components/MdkgLoader";
import { DotBackdrop, TextGenerate } from "@/components/fx";
import { Chip, Code, ErrorBox, RowsTable } from "@/components/kit";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tooltip as Tip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fmtNum, localName, SERIES } from "@/lib/format";
import { useUi } from "@/store";
import { toast } from "sonner";

export default function AskPage() {
  return (
    <MdkgLoader ws="ask" title="Load MDKGs to ask about">
      <AskBody />
    </MdkgLoader>
  );
}

function AskBody() {
  const chat = useUi((s) => s.chat);
  const push = useUi((s) => s.pushAnswer);
  const clear = useUi((s) => s.clearChat);
  const [q, setQ] = useState("");
  const [fresh, setFresh] = useState<number>(-1);
  const { data: st } = useStatus("ask");
  const { data: sug } = useSuggestions();
  const refresh = useRefreshStore("ask");
  const end = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const nav = useNavigate();
  const examples = sug?.questions ?? [];

  const ask = useMutation({
    mutationFn: api.ask,
    onSuccess: (a) => { push(a); setFresh(useUi.getState().chat.length - 1); setQ(""); },
  });
  const useLlm = useUi((s) => s.useLlm);
  const setUseLlm = useUi((s) => s.setUseLlm);
  const tr = useMutation({ mutationFn: api.setTranslator, onSuccess: () => void refresh() });
  const parserOnly = st?.translator === "grounded-parser";
  const llmReachable = st?.llm.reachable ?? false;
  // keep the server's translator in line with the switch (the server forgets it when restarted)
  useEffect(() => {
    if (!st || tr.isPending) return;
    if (useLlm && parserOnly && llmReachable) tr.mutate("auto");
    if (!useLlm && !parserOnly) tr.mutate("rules");
  }, [useLlm, st?.translator, llmReachable]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggleLlm = (on: boolean) => {
    setUseLlm(on);
    if (on && !llmReachable) toast.warning(`No LLM server at ${st?.llm.server ?? "localhost:11434"} with ${st?.llm.model ?? "the model"}; answering with embeddings until one is running.`);
  };
  const submit = (text: string) => { const t = text.trim(); if (t && !ask.isPending) ask.mutate(t); };

  // A question handed over from the ⌘K palette.
  useEffect(() => {
    const handed = (location.state as { ask?: string } | null)?.ask;
    if (handed) { nav(location.pathname, { replace: true, state: null }); submit(handed); }
  }, [location.state]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [chat.length, ask.isPending]);

  return (
    <div className="relative mx-auto flex max-w-4xl flex-col">
      <DotBackdrop />
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ask your MDKGs</h1>
          <p className="mt-1 text-sm text-ink-2">Plain-language questions become validated SPARQL. Nothing runs unless it passes syntax, grounding, scope and safety checks.</p>
        </div>
        <div className="flex items-end gap-2">
          <Tip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-sm">
                <Switch id="llm" checked={useLlm} onCheckedChange={toggleLlm} disabled={tr.isPending} />
                <Label htmlFor="llm">LLM</Label>
                <span className="text-xs text-ink-3">
                  {!st ? "…" : !parserOnly ? st.translator.replace(/^ollama:/, "") : useLlm && !llmReachable ? "no server · embeddings" : "off · embeddings"}
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              {!parserOnly
                ? `The LLM (${st?.translator}) writes the SPARQL; the validator checks it, and the grounded parser answers if it fails.`
                : <>The grounded parser answers: question words are matched to the MDKG vocabulary exactly, by meaning
                  ({st?.embeddings.startsWith("model2vec") ? "potion-base-8M embeddings" : "embedding model offline"}) and by spelling (character n-grams).
                  {useLlm && !llmReachable && <> No LLM server answers at {st?.llm.server} with {st?.llm.model}.</>}</>}
            </TooltipContent>
          </Tip>
          {chat.length > 0 && <Button variant="outline" onClick={clear}><TbTrash />Clear</Button>}
        </div>
      </div>
      <ErrorBox error={tr.error} />

        <>
          <div className="flex flex-col gap-4 pb-4">
            {chat.length === 0 && !ask.isPending && (
              <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl border border-border bg-card/80 p-6 text-center backdrop-blur">
                <PiSparkleDuotone className="mx-auto size-8 text-brand" />
                <div className="mt-2 font-medium">Try one of these. They are built from your own MDKGs and all have answers.</div>
              </motion.div>
            )}
            <AnimatePresence initial={false}>
              {chat.map((a, i) => (
                <motion.div key={`${i}-${a.question}`} layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}
                  className="flex flex-col gap-2">
                  <div className="self-end rounded-2xl rounded-br-md bg-brand px-4 py-2 text-white shadow-sm">{a.question}</div>
                  <AnswerBubble a={a} animate={i === fresh} />
                </motion.div>
              ))}
            </AnimatePresence>
            {ask.isPending && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col gap-2">
                <div className="self-end rounded-2xl rounded-br-md bg-brand/70 px-4 py-2 text-white">{ask.variables}</div>
                <div className="flex items-center gap-2 self-start rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3 text-sm text-ink-3">
                  <span className="flex gap-1">{[0, 1, 2].map((d) => (
                    <motion.i key={d} className="size-1.5 rounded-full bg-brand" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1, repeat: Infinity, delay: d * 0.15 }} />
                  ))}</span>
                  translating · validating · executing
                </div>
              </motion.div>
            )}
            <ErrorBox error={ask.error} />
            <div ref={end} />
          </div>

          <div className="sticky bottom-0 -mx-4 border-t border-border/60 bg-background/90 px-4 pb-4 pt-3 backdrop-blur-xl">
            {examples.length > 0 && (
              <div className={clsx("mb-2 flex gap-1.5", chat.length ? "overflow-x-auto pb-1 [scrollbar-width:thin]" : "flex-wrap")}>
                {examples.map((e) => (
                  <button key={e} className={clsx("rounded-full border border-border bg-card px-3 py-1 text-left text-xs text-ink-2 transition hover:border-brand hover:text-ink",
                    chat.length ? "shrink-0 whitespace-nowrap" : "max-w-full")} onClick={() => submit(e)}>{e}</button>
                ))}
              </div>
            )}
            <form className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-lg shadow-black/5 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20"
              onSubmit={(e) => { e.preventDefault(); submit(q); }}>
              <Textarea value={q} onChange={(e) => setQ(e.target.value)} rows={1} autoFocus
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(q); } }}
                placeholder={examples[0] ? `e.g. ${examples[0]}` : "Ask about your MDKGs…"}
                className="max-h-40 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0" />
              <Button type="submit" size="icon" className="size-10 shrink-0 rounded-xl" disabled={!q.trim() || ask.isPending} aria-label="Ask"><TbArrowUp className="size-5" /></Button>
            </form>
          </div>
        </>
    </div>
  );
}

function AnswerBubble({ a, animate }: { a: Answer; animate: boolean }) {
  const ok = a.status === "executed" || a.status === "fallback";
  const cols = a.columns.filter((c) => !c.endsWith("_n"));
  const numCols = cols.filter((c) => a.rows.length && a.rows.every((r) => r[c] === null || typeof r[c] === "number"));
  const labelCol = cols.find((c) => c.endsWith("_label")) ?? cols.find((c) => !numCols.includes(c));
  const valueCol = numCols.find((c) => c === "total") ?? numCols[0];
  const chartable = a.rows.length > 1 && labelCol && valueCol && numCols.length <= 2;
  const data = chartable ? a.rows.slice(0, 15).map((r) => ({ k: localName(r[labelCol]), v: Number(r[valueCol]) })) : [];
  return (
    <div className={clsx("self-start w-full rounded-2xl rounded-bl-md border bg-card p-4 shadow-sm",
      ok ? (a.status === "fallback" ? "border-warn/40" : "border-border") : "border-bad/40")}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">
        <Chip tone={a.status === "executed" ? "good" : a.status === "fallback" ? "warn" : "bad"}>{a.status}</Chip>
        {a.trace?.intent && <span>{a.trace.intent}</span>}
        {a.trace?.matches?.map((m) => <Chip key={m} title="matched by the embedding / spelling matcher">{m}</Chip>)}
        {a.trace?.cached && <Chip>answered from memory</Chip>}
        <span className="ml-auto tabular-nums">{(a.seconds * 1000).toFixed(0)} ms</span>
      </div>
      <div className={clsx("flex items-start gap-2 font-medium", !ok && "text-bad")}>
        {ok ? <TbCircleCheck className="mt-0.5 size-4 shrink-0 text-good" /> : <TbShieldX className="mt-0.5 size-4 shrink-0" />}
        {animate ? <TextGenerate text={a.insight} /> : <p>{a.insight}</p>}
      </div>
      {chartable && (
        <div className="mt-3" style={{ height: Math.max(120, data.length * 26 + 30) }}>
          <ResponsiveContainer>
            <BarChart data={data} layout="vertical" margin={{ left: 4, right: 40 }}>
              <CartesianGrid horizontal={false} />
              <XAxis type="number" tickFormatter={(v: number) => fmtNum(v)} />
              <YAxis type="category" dataKey="k" width={150} tickFormatter={(v: string) => (v.length > 20 ? v.slice(0, 19) + "…" : v)} />
              <Tooltip cursor={{ fill: "var(--c-raised)" }} formatter={(v) => fmtNum(Number(v), 2)} />
              <Bar isAnimationActive={false} dataKey="v" name={valueCol} fill={SERIES[0]} radius={[0, 4, 4, 0]} barSize={16} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {a.rows.length > 0 && <div className="mt-3"><RowsTable columns={cols} rows={a.rows.slice(0, 50)} /></div>}
      <Code title={`How this was answered · ${a.attempts.length} attempt${a.attempts.length === 1 ? "" : "s"}`}>
        {a.attempts.map((t, i) => [
          `Attempt ${i + 1} · ${t.translator}`,
          ...t.checks.map((c) => `  ${c.ok ? "✓" : "✗"} ${c.rule}: ${c.message}`),
          t.sparql ? `\n${t.sparql}` : "",
        ].join("\n")).join("\n\n")}
      </Code>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {a.attempts.at(-1)?.checks.map((c) => (
          <span key={c.rule} title={c.message} className={clsx("inline-flex items-center gap-1 text-xs", c.ok ? "text-good" : "text-bad")}>
            {c.ok ? <TbCircleCheck className="size-3.5" /> : <TbCircleX className="size-3.5" />}{c.rule}
          </span>
        ))}
      </div>
    </div>
  );
}
