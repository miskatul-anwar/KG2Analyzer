import clsx from "clsx";
import { AlertTriangle, ChevronRight, Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Row } from "@/api/client";
import { fmtCell } from "@/lib/format";

export function Card({ title, subtitle, actions, children, className }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={clsx("card min-w-0", className)}>
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h3 className="text-[15px] font-semibold">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, description, children }: { title: string; description: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>
      </div>
      {children}
    </div>
  );
}

export function Kpi({ value, label, tone }: { value: ReactNode; label: ReactNode; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className="min-w-[130px] rounded-lg bg-raised px-3 py-2">
      <div className={clsx("text-xl font-semibold tabular-nums", tone === "good" && "text-good", tone === "warn" && "text-warn", tone === "bad" && "text-bad")}>{value}</div>
      <div className="text-xs text-ink-2">{label}</div>
    </div>
  );
}

export function Chip({ children, tone, title, wrap }: { children: ReactNode; tone?: "good" | "warn" | "bad" | "accent"; title?: string; wrap?: boolean }) {
  return (
    <span title={title} className={clsx(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
      wrap ? "text-left" : "whitespace-nowrap",
      !tone && "border-line bg-raised text-ink-2",
      tone === "good" && "border-good/40 text-good",
      tone === "warn" && "border-warn/50 text-warn",
      tone === "bad" && "border-bad/40 text-bad",
      tone === "accent" && "border-accent/40 text-accent",
    )}>{children}</span>
  );
}

export function SignedChip({ name, value }: { name: string; value: number }) {
  return <Chip tone={value >= 0 ? "good" : "bad"}>{name} {value >= 0 ? "+" : ""}{value}</Chip>;
}

export function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="my-2 flex items-start gap-2 rounded-lg border border-warn/50 bg-warn/5 px-3 py-2 text-sm text-warn">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <div>{children}</div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <span className="inline-flex items-center gap-2 text-ink-3"><Loader2 className="size-4 animate-spin" />{label}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3">{children}</div>;
}

export function Code({ children, title }: { children: string; title: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button className="flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink" onClick={() => setOpen(!open)}>
        <ChevronRight className={clsx("size-3.5 transition", open && "rotate-90")} />{title}
      </button>
      {open && <pre className="mono mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-raised p-3">{children}</pre>}
    </div>
  );
}

export interface Column<T> { key: string; header: ReactNode; render?: (row: T) => ReactNode; numeric?: boolean; decimals?: number }

/** Data table: numeric columns are right-aligned tabular figures; decimals unify per column. */
export function DataTable<T extends object>({ columns, rows, max = 200 }: { columns: Column<T>[]; rows: T[]; max?: number }) {
  if (!rows.length) return <Empty>No rows.</Empty>;
  const dec = new Map<string, number | undefined>();
  for (const c of columns) {
    const vals = rows.map((r) => (r as Record<string, unknown>)[c.key]);
    const numeric = vals.every((v) => v === null || v === undefined || typeof v === "number");
    dec.set(c.key, c.decimals ?? (numeric && vals.some((v) => typeof v === "number" && !Number.isInteger(v)) ? 2 : undefined));
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-[13px]">
        <thead className="bg-raised text-left text-xs text-ink-2">
          <tr>{columns.map((c) => <th key={c.key} className={clsx("px-3 py-2 font-semibold", c.numeric && "text-right")}>{c.header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, max).map((r, i) => (
            <tr key={i} className="border-t border-grid align-top hover:bg-raised/50">
              {columns.map((c) => {
                const v = (r as Record<string, unknown>)[c.key];
                const isNum = typeof v === "number";
                return (
                  <td key={c.key} className={clsx("px-3 py-1.5", (c.numeric || isNum) && "text-right tabular-nums")} title={typeof v === "string" ? v : undefined}>
                    {c.render ? c.render(r) : fmtCell(v, dec.get(c.key))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > max && <p className="px-3 py-2 text-xs text-ink-3">Showing {max} of {rows.length} rows.</p>}
    </div>
  );
}

/** Generic table over SPARQL-style rows. */
export function RowsTable({ columns, rows }: { columns: string[]; rows: Row[] }) {
  return <DataTable columns={columns.map((c) => ({ key: c, header: c }))} rows={rows} />;
}

export function Select({ label, value, onChange, options, className }: {
  label?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string;
}) {
  const el = (
    <select className={clsx("input", className)} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return label ? <label className="label">{label}{el}</label> : el;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="my-2 rounded-lg border border-bad/40 bg-bad/5 px-3 py-2 text-sm text-bad">{error instanceof Error ? error.message : String(error)}</div>;
}
