/** Display names from the loaded catalogue (measure labels, dimension and level names), by IRI. */
const NAMES = new Map<string, string>();
// KG2MD notebook IRIs carry hashes: City_eaf60b2430de57f8a034_level -> City, discount_measure -> discount
const SUFFIX = /(?:_[0-9a-f]{12,})?_(?:level|dimension)(?:_hierarchy_[0-9a-f]+|_all)?$|_measure$/;

export function registerNames(cat: { cubes: { measures: { iri: string; label: string }[];
  dimensions: { prop: string; name?: string; level_names?: Record<string, string> }[] }[] }) {
  for (const c of cat.cubes) {
    for (const m of c.measures) NAMES.set(m.iri, m.label);
    for (const d of c.dimensions) {
      if (d.name) NAMES.set(d.prop, d.name);
      for (const [lvl, n] of Object.entries(d.level_names ?? {})) NAMES.set(lvl, n);
    }
  }
}

export const localName = (iri: unknown): string => {
  const s = String(iri ?? "");
  if (!s.startsWith("http")) return s;
  const known = NAMES.get(s);
  if (known) return known;
  const n = s.split(/[#/]/).pop() ?? s;
  return n.replace(SUFFIX, "") || n;
};

export function fmtNum(v: number, decimals?: number): string {
  if (decimals !== undefined) return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export function fmtCell(v: unknown, decimals?: number): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return fmtNum(v, decimals);
  return localName(v);
}

/** Categorical series slots (validated palette, fixed order: identity follows the entity, never rank). */
export const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"].map((v) => `var(${v})`);

export const cssVar = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name.replace(/^var\((.*)\)$/, "$1")).trim();
