/** App UI kit: thin, opinionated wrappers over shadcn/ui primitives. */
import clsx from "clsx";
import { AlertTriangle, ChevronRight, Loader2, OctagonX } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Row } from "@/api/client";
import { NumberTicker } from "@/components/fx";
import { Badge } from "@/components/ui/badge";
import { Card as UiCard, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Select as UiSelect, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fmtCell } from "@/lib/format";

export function Card({ title, subtitle, actions, children, className }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <UiCard className={clsx("min-w-0 gap-3", className)}>
      {(title || subtitle || actions) && (
        <CardHeader>
          {title && <CardTitle className="text-[15px]">{title}</CardTitle>}
          {subtitle && <CardDescription>{subtitle}</CardDescription>}
          {actions && <CardAction>{actions}</CardAction>}
        </CardHeader>
      )}
      <CardContent className="min-w-0">{children}</CardContent>
    </UiCard>
  );
}

export function PageHeader({ title, description, children }: { title: string; description: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>
      </div>
      {children}
    </div>
  );
}

export function Kpi({ value, label, tone, decimals }: { value: ReactNode; label: ReactNode; tone?: "good" | "warn" | "bad"; decimals?: number }) {
  return (
    <div className="min-w-[130px] rounded-xl border border-border bg-card px-3.5 py-2.5 shadow-xs">
      <div className={clsx("text-2xl font-semibold tracking-tight", tone === "good" && "text-good", tone === "warn" && "text-warn", tone === "bad" && "text-bad")}>
        {typeof value === "number" ? <NumberTicker value={value} decimals={decimals} /> : value}
      </div>
      <div className="text-xs text-ink-2">{label}</div>
    </div>
  );
}

export function Chip({ children, tone, title, wrap }: { children: ReactNode; tone?: "good" | "warn" | "bad" | "accent"; title?: string; wrap?: boolean }) {
  return (
    <Badge variant="outline" title={title} className={clsx(
      "font-medium", wrap ? "h-auto whitespace-normal text-left" : "whitespace-nowrap",
      !tone && "bg-raised text-ink-2",
      tone === "good" && "border-good/40 text-good",
      tone === "warn" && "border-warn/50 text-warn",
      tone === "bad" && "border-bad/40 text-bad",
      tone === "accent" && "border-brand/40 bg-brand/5 text-brand",
    )}>{children}</Badge>
  );
}

export function SignedChip({ name, value }: { name: string; value: number }) {
  return <Chip tone={value >= 0 ? "good" : "bad"}>{name} {value >= 0 ? "+" : ""}{value}</Chip>;
}

export function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="my-2 flex items-start gap-2 rounded-lg border border-warn/50 bg-warn/5 px-3 py-2 text-sm text-warn">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" /><div>{children}</div>
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="my-2 flex items-start gap-2 rounded-lg border border-bad/40 bg-bad/5 px-3 py-2 text-sm text-bad">
      <OctagonX className="mt-0.5 size-4 shrink-0" /><div>{error instanceof Error ? error.message : String(error)}</div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <span className="inline-flex items-center gap-2 text-sm text-ink-3"><Loader2 className="size-4 animate-spin" />{label}</span>;
}

export function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return <div className="flex flex-col gap-2">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-8 w-full" style={{ opacity: 1 - i * 0.15 }} />)}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-border px-4 py-10 text-center text-sm text-ink-3">{children}</div>;
}

export function Code({ children, title }: { children: string; title: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-3">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink">
        <ChevronRight className={clsx("size-3.5 transition-transform", open && "rotate-90")} />{title}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="mono mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-raised p-3">{children}</pre>
      </CollapsibleContent>
    </Collapsible>
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
    <div className="overflow-hidden rounded-lg border border-border">
      <Table className="text-[13px]">
        <TableHeader className="bg-raised/70">
          <TableRow>{columns.map((c) => <TableHead key={c.key} className={clsx("h-9 text-xs font-semibold text-ink-2", c.numeric && "text-right")}>{c.header}</TableHead>)}</TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, max).map((r, i) => (
            <TableRow key={i} className="align-top">
              {columns.map((c) => {
                const v = (r as Record<string, unknown>)[c.key];
                return (
                  <TableCell key={c.key} className={clsx("py-1.5 whitespace-normal", (c.numeric || typeof v === "number") && "text-right tabular-nums")}
                    title={typeof v === "string" ? v : undefined}>
                    {c.render ? c.render(r) : fmtCell(v, dec.get(c.key))}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length > max && <p className="border-t border-border px-3 py-2 text-xs text-ink-3">Showing {max} of {rows.length} rows.</p>}
    </div>
  );
}

export function RowsTable({ columns, rows }: { columns: string[]; rows: Row[] }) {
  return <DataTable columns={columns.map((c) => ({ key: c, header: c }))} rows={rows} />;
}

/** Radix select needs non-empty item values; "" is mapped to this sentinel. */
const NONE = "__none__";
export interface Option { value: string; label: ReactNode; text?: string }
export interface OptionGroup { label: string; options: Option[] }

/** Select with optional groups and an optional "none" choice. */
export function GroupSelect({ value, onChange, groups, options, none, placeholder, label, className }: {
  value: string; onChange: (v: string) => void; groups?: OptionGroup[]; options?: Option[];
  none?: string; placeholder?: string; label?: string; className?: string;
}) {
  const el = (
    <UiSelect value={value === "" ? (none ? NONE : undefined) : value} onValueChange={(v) => onChange(v === NONE ? "" : v)}>
      <SelectTrigger className={clsx("w-full bg-card", className)}><SelectValue placeholder={placeholder ?? "Choose…"} /></SelectTrigger>
      <SelectContent position="popper" className="max-h-80">
        {none && <><SelectItem value={NONE}>{none}</SelectItem><SelectSeparator /></>}
        {options?.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        {groups?.map((g, i) => (
          <SelectGroup key={g.label}>
            {i > 0 && <SelectSeparator />}
            <SelectLabel>{g.label}</SelectLabel>
            {g.options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectGroup>
        ))}
      </SelectContent>
    </UiSelect>
  );
  return label ? <label className="label">{label}{el}</label> : el;
}

/** Back-compat simple select. */
export function Select({ label, value, onChange, options, className }: {
  label?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string;
}) {
  return <GroupSelect label={label} value={value} onChange={onChange} options={options} className={className} />;
}

/** Segmented control (shadcn ToggleGroup) that never allows deselecting. */
export function Segmented<T extends string>({ value, onChange, options, small }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; small?: boolean;
}) {
  return (
    <ToggleGroup type="single" variant="outline" size={small ? "sm" : "default"} value={value || "__auto__"}
      onValueChange={(v) => v && onChange((v === "__auto__" ? "" : v) as T)} className="flex-wrap bg-card" spacing={small ? 1 : 0}>
      {options.map((o) => <ToggleGroupItem key={o.value || "__auto__"} value={o.value || "__auto__"} className="px-3 data-[state=on]:bg-brand/10 data-[state=on]:text-brand">{o.label}</ToggleGroupItem>)}
    </ToggleGroup>
  );
}
