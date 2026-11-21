import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, SendHorizontal, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import { useState } from "react";
import { api, type Answer } from "@/api/client";
import { useRefreshStore, useStatus } from "@/api/hooks";
import { Card, Chip, Code, ErrorBox, PageHeader, RowsTable, Select, Spinner } from "@/components/ui";

const EXAMPLES = [
  "Show total retail sales and investment trade volume for our shared corporate clients",
  "Total sale amount by product category",
  "Average turnaround hours per lab in healthcare",
  "Daily retail sales and energy consumed on the same day",
  "Top 3 products by retail sales",
  "Total retail sales for Alice",
  "Delete all retail customers",
];

export default function AskPage() {
  const [q, setQ] = useState("");
  const [history, setHistory] = useState<Answer[]>([]);
  const { data: st } = useStatus();
  const refresh = useRefreshStore();
  const ask = useMutation({ mutationFn: api.ask, onSuccess: (a) => setHistory((h) => [a, ...h]) });
  const tr = useMutation({ mutationFn: api.setTranslator, onSuccess: refresh });
  const submit = (text: string) => { if (text.trim()) { setQ(text); ask.mutate(text.trim()); } };

  return (
    <>
      <PageHeader title="Ask in plain language" description="Questions are grounded in the live schema catalogue, translated to SPARQL, and must pass four validation rules (syntax, grounding, scope, safety) before anything runs. Failed drafts are retried with the diagnostics; a deterministic grounded parser is the final fallback.">
        <Select label={`Translator (now: ${st?.translator ?? "…"})`} value="" onChange={(v) => v && tr.mutate(v)} options={[
          { value: "", label: "change…" },
          { value: "rules", label: "Grounded parser (offline)" },
          { value: "auto", label: "Auto (Ollama if available)" },
          { value: "ollama", label: "Ollama · qwen2.5-coder:3b" },
          { value: "openai", label: "OpenAI-compatible server" },
        ]} />
      </PageHeader>
      <ErrorBox error={tr.error} />
      <Card>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); submit(q); }}>
          <input className="input grow text-[15px]" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Show total retail sales and investment trade volume for our shared corporate clients" autoFocus />
          <button className="btn-primary" disabled={ask.isPending}><SendHorizontal className="size-4" />Ask</button>
        </form>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((e) => <button key={e} className="max-w-full" onClick={() => submit(e)}><Chip wrap>{e}</Chip></button>)}
        </div>
      </Card>
      {ask.isPending && <div className="mt-4"><Spinner label="translating, validating, executing…" /></div>}
      <ErrorBox error={ask.error} />
      <div className="mt-4 flex flex-col gap-4">
        {history.map((a, i) => <AnswerCard key={history.length - i} a={a} />)}
      </div>
    </>
  );
}

function AnswerCard({ a }: { a: Answer }) {
  const ok = a.status === "executed" || a.status === "fallback";
  const cols = a.columns.filter((c) => !c.endsWith("_n"));
  return (
    <Card className={clsx("border-l-4", ok ? (a.status === "fallback" ? "border-l-warn" : "border-l-accent") : "border-l-bad")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-[15px] font-semibold">{a.question}</h3>
        <div className="flex items-center gap-2 text-xs text-ink-3">
          <Chip tone={a.status === "executed" ? "good" : a.status === "fallback" ? "warn" : "bad"}>{a.status}</Chip>
          {(a.seconds * 1000).toFixed(0)} ms · {a.attempts.length} attempt(s)
        </div>
      </div>
      {a.trace?.intent && <p className="mt-1 text-xs text-ink-3"><Sparkles className="mr-1 inline size-3.5" />intent: {a.trace.intent}{a.trace.group_by?.length ? ` · group by ${a.trace.group_by.join(", ")}` : ""}{a.trace.filters?.length ? ` · filter ${a.trace.filters.join(", ")}` : ""}</p>}
      <p className={clsx("my-3 flex items-start gap-2 font-medium", !ok && "text-bad")}>
        {ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" /> : <ShieldAlert className="mt-0.5 size-4 shrink-0" />}
        {a.insight}
      </p>
      {a.rows.length > 0 && <RowsTable columns={cols} rows={a.rows.slice(0, 50)} />}
      <div className="mt-2 rounded-lg bg-raised/60 p-3">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">Validation pipeline</div>
        {a.attempts.map((t, i) => (
          <div key={i} className="mb-2">
            <div className="text-xs font-medium">Attempt {i + 1} · <span className="mono">{t.translator}</span></div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {t.checks.map((c) => (
                <span key={c.rule} title={c.message} className={clsx("inline-flex items-center gap-1 text-xs", c.ok ? "text-good" : "text-bad")}>
                  {c.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}<b>{c.rule}</b>
                  {!c.ok && <span className="text-ink-2">: {c.message}</span>}
                </span>
              ))}
            </div>
            {t.sparql && <Code title="SPARQL">{t.sparql}</Code>}
          </div>
        ))}
      </div>
    </Card>
  );
}
