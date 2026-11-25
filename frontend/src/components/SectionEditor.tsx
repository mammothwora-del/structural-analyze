import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CatalogEntry, Model, Section, SteelCatalog } from "../lib/types";
import { useU } from "../store";

let catalogPromise: Promise<SteelCatalog> | null = null;

/** Standard steel sizes from the backend, fetched once. */
export function useCatalog() {
  const [cat, setCat] = useState<SteelCatalog | null>(null);
  useEffect(() => {
    catalogPromise ??= api.catalog().catch((e) => { catalogPromise = null; throw e; });
    catalogPromise.then(setCat).catch(() => setCat(null));
  }, []);
  return cat;
}

const DIMS: Record<string, [keyof Section, string][]> = {
  I: [["h", "h"], ["bf", "bf"], ["tw", "tw"], ["tf", "tf"]],
  box: [["h", "h"], ["b", "b"], ["t", "t"]],
  pipe: [["d", "d"], ["t", "t"]],
  channel: [["h", "h"], ["b", "b"], ["tw", "tw"], ["tf", "tf"]],
  angle: [["b", "leg b"], ["t", "t"]],
  lipchannel: [["h", "h"], ["b", "b"], ["c", "lip c"], ["t", "t"]],
  rect: [["b", "b"], ["h", "h"]],
  circle: [["d", "d"]],
};
const SHAPE_LABEL: Record<string, string> = { I: "I / H section", box: "Box (SHS / RHS)", pipe: "Tube (CHS)", channel: "Channel (C)",
  angle: "Equal angle (L)", lipchannel: "Lip channel (LC, cold-formed)", rect: "Rectangle (solid)", circle: "Circle (solid)" };
const DEFAULT_FAMILY: Record<string, string> = { I: "H", box: "SHS", pipe: "CHS", channel: "C", angle: "L", lipchannel: "LC" };
const DEFAULTS: Record<string, Partial<Section>> = {
  I: { h: 0.3, bf: 0.15, tw: 0.0065, tf: 0.009 }, box: { h: 0.15, b: 0.15, t: 0.006 }, pipe: { d: 0.1143, t: 0.0045 },
  channel: { h: 0.15, b: 0.075, tw: 0.0065, tf: 0.01 }, angle: { b: 0.065, t: 0.006 }, lipchannel: { h: 0.1, b: 0.05, c: 0.02, t: 0.0023 },
  rect: { b: 0.3, h: 0.5 }, circle: { d: 0.3 },
};

export function sectionName(s: Section, unit: (si: number) => string): string {
  if (s.catalog) return `${s.catalog} ${s.material}`;
  const d = (k: keyof Section) => unit(s[k] as number);
  switch (s.shape) {
    case "I": return `I ${d("h")}x${d("bf")}x${d("tw")}x${d("tf")} ${s.material}`;
    case "box": return `RHS ${d("h")}x${d("b")}x${d("t")} ${s.material}`;
    case "pipe": return `CHS ${d("d")}x${d("t")} ${s.material}`;
    case "channel": return `C ${d("h")}x${d("b")}x${d("tw")}x${d("tf")} ${s.material}`;
    case "angle": return `L ${d("b")}x${d("b")}x${d("t")} ${s.material}`;
    case "lipchannel": return `LC ${d("h")}x${d("b")}x${d("c")}x${d("t")} ${s.material}`;
    case "rect": return `${d("b")}x${d("h")} ${s.material}`;
    case "circle": return `Ø${d("d")} ${s.material}`;
    default: return s.name ?? "section";
  }
}

/** Shape, size and material of one section: a standard size from the tables, or your own dimensions. */
export function SectionEditor({ model, value, onSave, onCancel, saveLabel = "Save", onSaveRedesign }: {
  model: Model; value: Section; onSave: (s: Section) => void; onCancel?: () => void; saveLabel?: string;
  /** second action: save, then analyse and re-run the steel design */
  onSaveRedesign?: (s: Section) => void;
}) {
  const u = useU();
  const cat = useCatalog();
  const [s, setS] = useState<Section>(value);
  const steel = model.materials[s.material]?.kind === "steel";
  const fromCat = cat?.sections.find((c) => c.name === s.catalog);
  const [fam, setFam] = useState<string>(fromCat?.family ?? DEFAULT_FAMILY[s.shape] ?? "H");
  const [mode, setMode] = useState<"std" | "custom">(s.catalog || (value.shape !== "rect" && value.shape !== "circle" && steel) ? "std" : "custom");
  useEffect(() => { if (fromCat) setFam(fromCat.family); }, [fromCat?.family]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (c: CatalogEntry) => {
    const { family: _f, name, A: _a, mass: _m, source: _s, ...dims } = c;
    setS({ material: s.material, ...dims, catalog: name } as Section);
  };
  const D = u.u("dim");
  const fmtDim = (si: number) => String(+u.c("dim", si).toFixed(2));
  const list = cat?.sections.filter((c) => c.family === fam) ?? [];
  const valid = (DIMS[s.shape] ?? []).every(([k]) => (s[k] as number) > 0)
    && !(s.shape === "pipe" && 2 * (s.t ?? 0) >= (s.d ?? 0)) && !(s.shape === "box" && 2 * (s.t ?? 0) >= Math.min(s.b ?? 0, s.h ?? 0))
    && !(s.shape === "I" && 2 * (s.tf ?? 0) >= (s.h ?? 0))
    && !(s.shape === "channel" && (2 * (s.tf ?? 0) >= (s.h ?? 0) || (s.tw ?? 0) >= (s.b ?? 0)))
    && !(s.shape === "angle" && (s.t ?? 0) >= (s.b ?? 0))
    && !(s.shape === "lipchannel" && (2 * (s.t ?? 0) >= Math.min(s.b ?? 0, s.c ?? 0) || 2 * (s.c ?? 0) >= (s.h ?? 0)));
  return (
    <div className="rounded border border-ink-700 bg-ink-950/60 p-2 my-1">
      <div className="flex rounded border border-ink-700 overflow-hidden text-[11px] mb-1.5">
        {([["std", "Standard size"], ["custom", "Own dimensions"]] as const).map(([k, l]) => (
          <button key={k} type="button" disabled={k === "std" && !steel} onClick={() => setMode(k)}
            className={`flex-1 py-0.5 ${mode === k ? "bg-accent text-ink-950 font-semibold" : "text-ink-300 hover:bg-ink-800"} disabled:opacity-40`}>{l}</button>
        ))}
      </div>
      {mode === "std" && steel ? (
        <>
          <select className="input mb-1" value={fam} onChange={(e) => setFam(e.target.value)}>
            {Object.entries(cat?.families ?? { H: "H sections" }).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <select className="input mb-1" value={s.catalog && list.some((c) => c.name === s.catalog) ? s.catalog : ""}
            onChange={(e) => { const c = list.find((x) => x.name === e.target.value); if (c) pick(c); }}>
            <option value="" disabled>{cat ? "Pick a size…" : "Loading sizes…"}</option>
            {list.map((c) => <option key={c.name} value={c.name}>{c.name} — {c.mass.toFixed(1)} kg/m</option>)}
          </select>
          <div className="text-[10px] text-ink-500 mb-1">
            {fromCat?.source === "nominal"
              ? "Nominal size: properties calculated from the dimensions without root radii (slightly below the supplier's table)."
              : "Sizes from the supplier's tables use the table's area, inertia and section moduli."}
            {fam === "LC" && <span className="text-amber-400"> Lip channels are cold-formed: used in the analysis, but no steel design check is done for them.</span>}
            {fam === "L" && " Angles are analysed and checked about their principal axes (local y = major axis)."}
          </div>
        </>
      ) : (
        <>
          <select className="input mb-1" value={s.shape} onChange={(e) => {
            const shape = e.target.value as Section["shape"];
            setS({ material: s.material, shape, ...DEFAULTS[shape] });
          }}>
            {Object.entries(SHAPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-1 mb-1">
            {(DIMS[s.shape] ?? []).map(([k, l]) => (
              <label key={k} className="text-[10px] text-ink-400">{l} ({D})
                <input className="input" type="number" min="0" step="any" value={s[k] != null ? +u.c("dim", s[k] as number).toFixed(3) : ""}
                  onChange={(e) => setS({ ...s, catalog: undefined, [k]: u.si("dim", +e.target.value) })} />
              </label>
            ))}
          </div>
        </>
      )}
      <select className="input mb-1.5" value={s.material} onChange={(e) => setS({ ...s, material: e.target.value })}>
        {Object.entries(model.materials).map(([k, m]) => <option key={k} value={k}>{m.name}</option>)}
      </select>
      <div className="text-[10px] text-ink-300 mb-1.5 font-mono">{valid ? sectionName(s, fmtDim) : "Check the dimensions"}</div>
      <div className="flex gap-1">
        {onCancel && <button className="btn flex-1" onClick={onCancel}>Cancel</button>}
        <button className="btn-primary flex-1" disabled={!valid} onClick={() => onSave({ ...s, name: sectionName(s, fmtDim) })}>{saveLabel}</button>
      </div>
      {onSaveRedesign && (
        <button className="btn w-full mt-1" disabled={!valid} onClick={() => onSaveRedesign({ ...s, name: sectionName(s, fmtDim) })}>Save, analyse and re-design</button>
      )}
    </div>
  );
}
