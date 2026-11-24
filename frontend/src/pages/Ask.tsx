import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { TbArrowUp, TbCircleCheck, TbCircleX, TbRefresh, TbShieldX, TbTrash } from "react-icons/tb";
import { useLocation, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Answer } from "@/api/client";
import { useLlmModels, useRefreshStore, useStatus } from "@/api/hooks";
import { MdkgLoader } from "@/components/MdkgLoader";
import { DotBackdrop, TextGenerate } from "@/components/fx";
import { Chip, Code, ErrorBox, GroupSelect, RowsTable, Spinner } from "@/components/kit";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tooltip as Tip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fmtNum, localName, SERIES } from "@/lib/format";
import { useUi } from "@/store";

export default function AskPage() {
  return (
    <MdkgLoader ws="ask" title="Load MDKGs to ask about">
      <AskBody />
    </MdkgLoader>
  );
}

/** LLM on/off and the choice of model among those installed in Ollama. Off: grounded parser + embeddings. */
function LlmPicker() {
  const { data: st } = useStatus("ask");
  const useLlm = useUi((s) => s.useLlm);
  const setUseLlm = useUi((s) => s.setUseLlm);
  const model = useUi((s) => s.llmModel);
  const setModel = useUi((s) => s.setLlmModel);
  const refresh = useRefreshStore("ask");
  const { data: ol, isFetching, refetch } = useLlmModels(useLlm);
  const tr = useMutation({ mutationFn: api.setTranslator, onSuccess: () => void refresh() });
  const installed = ol?.models ?? [];
  const chosen = model && installed.some((m) => m.name === model) ? model : null;
  // nothing picked yet: a coder model if there is one, else whatever is already loaded, else the first
  useEffect(() => {
    if (useLlm && !chosen && installed.length) {
      setModel((installed.find((m) => /coder/i.test(m.name)) ?? installed.find((m) => m.loaded) ?? installed[0]).name);
    }
  }, [useLlm, chosen, installed, setModel]);
  // keep the server's translator in line with the choice (the server forgets it when restarted)
  const want = useLlm && ol?.reachable && chosen ? `ollama:${chosen}` : "rules";
  const have = st?.translator === "grounded-parser" ? "rules" : st?.translator;
  useEffect(() => {
    if (st && !tr.isPending && have !== want) tr.mutate(want);
  }, [want, have]); // eslint-disable-line react-hooks/exhaustive-deps
  const live = have !== "rules";

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card/80 px-3 py-2 text-sm backdrop-blur">
      <div className="flex items-center gap-2">
        <Switch id="llm" checked={useLlm} onCheckedChange={setUseLlm} disabled={tr.isPending} />
        <Label htmlFor="llm" className="font-medium">LLM</Label>
      </div>
      {!useLlm ? (
        <span className="text-xs text-ink-3">
          off: the grounded parser answers instantly, matching your words exactly, by meaning
          ({st?.embeddings.startsWith("model2vec") ? "embeddings" : "embeddings offline"}) and by spelling
        </span>
      ) : !ol ? (
        <Spinner label="looking for Ollama…" />
      ) : !ol.reachable ? (
        <span className="text-xs text-warn">
          Ollama isn't running at <span className="mono">{ol.server}</span>. Start it with <span className="mono">ollama serve</span>, then
          <button className="ml-1 underline" onClick={() => void refetch()}>check again</button>. Meanwhile the grounded parser answers.
        </span>
      ) : !installed.length ? (
        <span className="text-xs text-warn">
          No models installed in Ollama. Get one with <span className="mono">ollama pull qwen2.5-coder:3b</span>, then
          <button className="ml-1 underline" onClick={() => void refetch()}>check again</button>.
        </span>
      ) : (
        <>
          <div className="w-80 max-w-full">
            <GroupSelect value={chosen ?? ""} onChange={(v) => v && setModel(v)} placeholder="Choose a model…" options={installed.map((m) => ({
              value: m.name,
              label: <span className="flex items-center gap-1.5">
                <span className="font-medium">{m.name}</span>
                <span className="text-xs text-ink-3">{[m.parameters, `${m.size_gb} GB`, m.quantization].filter(Boolean).join(" · ")}</span>
                {m.loaded && <span className="size-1.5 rounded-full bg-good" title="loaded in memory" />}
              </span>,
            }))} />
          </div>
          <Tip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => void refetch()} aria-label="Refresh the model list"><TbRefresh className={clsx(isFetching && "animate-spin")} /></Button>
            </TooltipTrigger>
            <TooltipContent>Refresh the list of models installed in Ollama</TooltipContent>
          </Tip>
          <span className="text-xs text-ink-3">
            {tr.isPending ? "loading the model…" : live ? <>writes the SPARQL; checked by the validator; the grounded parser answers if it is slow or wrong</> : null}
          </span>
        </>
      )}
      {tr.error && <span className="w-full text-xs text-bad">{String((tr.error as Error).message)}</span>}
    </div>
  );
}

function AskBody() {
  const chat = useUi((s) => s.chat);
  const push = useUi((s) => s.pushAnswer);
  const clear = useUi((s) => s.clearChat);
  const [q, setQ] = useState("");
  const [fresh, setFresh] = useState<number>(-1);
  const { data: st } = useStatus("ask");
  const end = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const nav = useNavigate();

  const ask = useMutation({
    mutationFn: api.ask,
    onSuccess: (a) => { push(a); setFresh(useUi.getState().chat.length - 1); setQ(""); },
  });
  const usingLlm = !!st && st.translator !== "grounded-parser";
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
        {chat.length > 0 && <Button variant="outline" onClick={clear}><TbTrash />Clear</Button>}
      </div>
      <LlmPicker />

        <>
          <div className="flex flex-col gap-4 pb-4">
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
                  {usingLlm ? <>asking {st!.translator.replace(/^ollama:/, "")} · validating · the grounded parser stands by</> : "matching your words to the MDKGs · validating · executing"}
                </div>
              </motion.div>
            )}
            <ErrorBox error={ask.error} />
            <div ref={end} />
          </div>

          <div className="sticky bottom-0 -mx-4 border-t border-border/60 bg-background/90 px-4 pb-4 pt-3 backdrop-blur-xl">
            <form className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-lg shadow-black/5 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20"
              onSubmit={(e) => { e.preventDefault(); submit(q); }}>
              <Textarea value={q} onChange={(e) => setQ(e.target.value)} rows={1} autoFocus
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(q); } }}
                placeholder="Ask a question about your MDKGs…"
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
        <Chip tone={a.status === "fallback" ? "warn" : undefined}>{answeredBy(a)}</Chip>
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

/** Who wrote the query that ran: the chosen LLM, or the grounded parser (alone, or because the LLM failed or was slow). */
function answeredBy(a: Answer): string {
  const ok = a.attempts.find((t) => t.ok);
  const llm = a.attempts.find((t) => t.translator !== "grounded-parser")?.translator.replace(/^ollama:/, "");
  if (ok && ok.translator !== "grounded-parser") return `via ${ok.translator.replace(/^ollama:/, "")}`;
  if (llm) return `${llm} missed → grounded parser`;
  return "via grounded parser";
}
