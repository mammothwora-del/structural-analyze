import type { Element, Model } from "./types";

/** Members shown in the 3D view (component filter, section cut and isolation applied). */
export function visibleMembers(model: Model, hiddenTypes: Record<string, boolean>, maxLevel: number | null, isolated: string[] | null,
  colorKey: (e: Element) => string): Element[] {
  const iso = isolated ? new Set(isolated) : null;
  return model.elements.filter((e) => {
    if (hiddenTypes[colorKey(e)]) return false;
    if (maxLevel !== null && (e.level ?? 0) > maxLevel) return false;
    if (iso && !iso.has(e.id)) return false;
    return true;
  });
}

/** Section ids used by these members, most used first, with counts (selected / all members of that section). */
export function sectionsOf(model: Model, ids: string[]) {
  const set = new Set(ids);
  const sel: Record<string, number> = {}, all: Record<string, number> = {};
  for (const e of model.elements) {
    all[e.section] = (all[e.section] ?? 0) + 1;
    if (set.has(e.id)) sel[e.section] = (sel[e.section] ?? 0) + 1;
  }
  return Object.entries(sel).sort((a, b) => b[1] - a[1]).map(([id, n]) => ({ id, n, total: all[id] }));
}

const DIM_KEYS = ["shape", "material", "h", "b", "bf", "tw", "tf", "t", "d", "c", "fab", "catalog"] as const;

/** Two sections with the same shape, dimensions, material and table size. */
export function sameSection(a: Record<string, unknown>, b: Record<string, unknown>) {
  return DIM_KEYS.every((k) => (a[k] ?? null) === (b[k] ?? null) || (typeof a[k] === "number" && typeof b[k] === "number" && Math.abs((a[k] as number) - (b[k] as number)) < 1e-12));
}

/** A free section id based on `base`: base-2, base-3, ... */
export function freeSectionId(model: Model, base: string) {
  const root = base.replace(/-\d+$/, "");
  for (let k = 2; ; k++) if (!model.sections[`${root}-${k}`]) return `${root}-${k}`;
}
