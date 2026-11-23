import { useEffect } from "react";
import { useCatalog } from "@/api/hooks";
import { Select } from "@/components/ui";
import { localName } from "@/lib/format";

export interface CubeSel { kg: string; dim: string; measure: string }

/** KG + dimension + measure selector driven by the live schema catalogue. */
export function CubePicker({ value, onChange, label, defaultIndex = 0 }: {
  value: CubeSel; onChange: (v: CubeSel) => void; label?: string; defaultIndex?: number;
}) {
  const { data: cat } = useCatalog();
  const cubes = cat?.cubes ?? [];
  const cube = cubes.find((c) => c.kg === value.kg);

  useEffect(() => {
    if (!cubes.length) return;
    const c = cube ?? cubes[Math.min(defaultIndex, cubes.length - 1)];
    const dimOk = c.dimensions.some((d) => d.prop === value.dim);
    const mOk = c.measures.some((m) => m.iri === value.measure);
    if (!cube || !dimOk || !mOk) {
      const dim = c.dimensions[0]?.prop ?? "";
      const measure = (c.measures.find((m) => m.additivity === "additive") ?? c.measures[0])?.iri ?? "";
      const next = { kg: c.kg, dim: dimOk && cube ? value.dim : dim, measure: mOk && cube ? value.measure : measure };
      if (next.kg !== value.kg || next.dim !== value.dim || next.measure !== value.measure) onChange(next);
    }
  }, [cubes, cube, value, onChange, defaultIndex]);

  return (
    <div className="flex flex-wrap items-end gap-2">
      {label && <span className="w-full text-xs font-semibold uppercase tracking-wide text-ink-3">{label}</span>}
      <Select label="Cube" value={value.kg} onChange={(kg) => onChange({ kg, dim: "", measure: "" })}
        options={cubes.map((c) => ({ value: c.kg, label: `${c.kg} · ${c.label}` }))} />
      <Select label="Dimension" value={value.dim} onChange={(dim) => onChange({ ...value, dim })}
        options={(cube?.dimensions ?? []).map((d) => ({ value: d.prop, label: localName(d.prop) }))} />
      <Select label="Measure" value={value.measure} onChange={(measure) => onChange({ ...value, measure })}
        options={(cube?.measures ?? []).map((m) => ({ value: m.iri, label: `${localName(m.iri)} · ${m.aggregate}${m.additivity === "non-additive" ? " · non-additive" : ""}` }))} />
    </div>
  );
}
