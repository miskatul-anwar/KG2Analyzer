export const localName = (iri: unknown): string => {
  const s = String(iri ?? "");
  return s.startsWith("http") ? (s.split(/[#/]/).pop() ?? s) : s;
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
