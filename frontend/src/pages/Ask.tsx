import { useMutation, useQuery } from "@tanstack/react-query";
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
import { Chip, Code, ErrorBox, GroupSelect, RowsTable } from "@/components/kit";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fmtNum, localName, SERIES } from "@/lib/format";
import { useUi } from "@/store";

export default function AskPage() {
  return (
    <MdkgLoader ws="ask">
      <AskBody />
    </MdkgLoader>
  );
}

/** LLM on/off and the model, chosen among those installed in Ollama. */
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

  return (
    <div className="flex items-center gap-1.5">
      {useLlm && ol?.reachable && installed.length > 0 && (
        <div className="w-56">
          <GroupSelect value={chosen ?? ""} onChange={(v) => v && setModel(v)} placeholder="Model" className="h-8 rounded-full text-xs"
            options={installed.map((m) => ({
              value: m.name,
              label: <span className="flex items-center gap-1.5">{m.name}
                <span className="text-ink-3">{m.parameters}</span>{m.loaded && <span className="size-1.5 rounded-full bg-good" />}</span>,
            }))} />
        </div>
      )}
      {useLlm && ol && (!ol.reachable || !installed.length) && (
        <button className="flex items-center gap-1 text-xs text-warn" onClick={() => void refetch()}>
          <TbRefresh className={clsx("size-3.5", isFetching && "animate-spin")} />{ol.reachable ? "no models" : "Ollama offline"}
        </button>
      )}
      <label className={clsx("flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-sm transition-colors",
        useLlm ? "border-brand/40 bg-brand/5 text-ink" : "border-border bg-card text-ink-2")}>
        <Switch checked={useLlm} onCheckedChange={setUseLlm} disabled={tr.isPending} />LLM
      </label>
      {tr.error && <span className="text-xs text-bad">{String((tr.error as Error).message)}</span>}
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
      <div className="mb-4 flex justify-end">
        <div className="flex items-center gap-2">
          <LlmPicker />
          {chat.length > 0 && <Button variant="ghost" size="icon-sm" onClick={clear} aria-label="Clear the chat"><TbTrash /></Button>}
        </div>
      </div>

        <>
          <div className="flex flex-col gap-4 pb-4">
            <AnimatePresence initial={false}>
              {chat.map((a, i) => (
                <motion.div key={`${i}-${a.question}`} layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}
                  className="flex flex-col gap-2">
                  <div className="self-end rounded-2xl rounded-br-md bg-brand px-4 py-2 text-white shadow-sm">{a.question}</div>
                  <AnswerBubble a={a} index={i} animate={i === fresh} />
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
                  {usingLlm && st!.translator.replace(/^ollama:/, "")}
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
                placeholder="Ask…"
                className="max-h-40 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0" />
              <Button type="submit" size="icon" className="size-10 shrink-0 rounded-xl" disabled={!q.trim() || ask.isPending} aria-label="Ask"><TbArrowUp className="size-5" /></Button>
            </form>
          </div>
        </>
    </div>
  );
}

/** While the chosen LLM is still drafting in the background, poll it; its answer replaces the parser's. */
function useLlmUpgrade(a: Answer, index: number) {
  const replace = useUi((s) => s.replaceAnswer);
  const job = a.trace?.llm_job;
  const { data, error } = useQuery({
    queryKey: ["ask", "job", job], queryFn: () => api.askJob(job!), enabled: !!job, staleTime: Infinity, retry: false,
    refetchInterval: (q) => (q.state.data?.state === "running" ? 1500 : false),
  });
  useEffect(() => {
    if (!job) return;
    const strip = { ...a.trace, llm_job: undefined };
    if (error) replace(index, { ...a, trace: strip });  // the server restarted or the model changed
    else if (data?.state === "done" && data.answer) replace(index, { ...data.answer, question: a.question });
    else if (data && (data.state === "invalid" || data.state === "timeout")) replace(index, { ...a, trace: { ...strip, llm_result: data.state } });
  }, [data, error]); // eslint-disable-line react-hooks/exhaustive-deps
  return job ? (data?.seconds ?? 0) : null;
}

function AnswerBubble({ a, index, animate }: { a: Answer; index: number; animate: boolean }) {
  const waiting = useLlmUpgrade(a, index);
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
        <Chip tone={a.status === "fallback" || a.trace?.llm_result ? "warn" : undefined}>{answeredBy(a)}</Chip>
        {waiting !== null && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/30 bg-brand/5 px-2 py-0.5 text-brand">
            <span className="size-1.5 animate-pulse rounded-full bg-brand" />{a.trace?.llm?.replace(/^ollama:/, "")} {waiting > 0 && `${Math.round(waiting)} s`}
          </span>
        )}
        {a.trace?.intent && <span>{a.trace.intent}</span>}
        {a.trace?.matches?.map((m) => <Chip key={m}>{m}</Chip>)}
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
  const short = (t: string) => t.replace(/^ollama:/, "");
  const ok = a.attempts.find((t) => t.ok);
  if (ok && ok.translator !== "grounded-parser") return `via ${short(ok.translator)}`;
  const llm = a.trace?.llm ?? a.attempts.find((t) => t.translator !== "grounded-parser")?.translator;
  if (llm && a.trace?.llm_result === "timeout") return `${short(llm)} timed out → grounded parser`;
  if (llm && (a.trace?.llm_result === "invalid" || a.status === "fallback")) return `${short(llm)} invalid → grounded parser`;
  return "via grounded parser";
}
