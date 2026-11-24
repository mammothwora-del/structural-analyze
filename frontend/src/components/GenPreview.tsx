import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Model } from "../lib/types";
import { useU } from "../store";
import { elementColorKey, TYPE_COLORS, TYPE_LABELS } from "../three/Members";

/** Generated models by request, so the picture buttons and repeated previews don't refetch. */
const cache = new Map<string, Model>();

function useGenerated(params: Record<string, unknown>, delay: number) {
  const key = JSON.stringify(params);
  const [state, setState] = useState<{ key: string; model: Model | null; error: string | null }>(() => ({ key, model: cache.get(key) ?? null, error: null }));
  useEffect(() => {
    if (cache.has(key)) { setState({ key, model: cache.get(key)!, error: null }); return; }
    let live = true;
    const t = setTimeout(() => {
      api.generate(JSON.parse(key))
        .then((m) => { if (cache.size > 60) cache.clear(); cache.set(key, m); if (live) setState({ key, model: m, error: null }); })
        .catch((e) => { if (live) setState((s) => ({ key, model: s.model, error: String((e as Error).message) })); });
    }, delay);
    return () => { live = false; clearTimeout(t); };
  }, [key, delay]);
  return state;
}

type View = "front" | "iso";
const COS30 = Math.cos(Math.PI / 6);
const project = (view: View, x: number, y: number, z: number): [number, number] =>
  view === "front" ? [x, -z] : [(x - y) * COS30, -(x + y) * 0.5 - z];

interface Props {
  params: Record<string, unknown>;
  view?: View;
  /** Small picture without caption, for the truss type buttons. */
  compact?: boolean;
  height?: number;
}

/** Line drawing of the structure the generator will create, from the backend generator itself (no analysis). */
export function GenPreview({ params, view = "iso", compact = false, height = 150 }: Props) {
  const u = useU();
  const { model, error, key } = useGenerated(params, compact ? 0 : 250);
  const stale = key !== JSON.stringify(params);

  const drawing = useMemo(() => {
    if (!model) return null;
    const pos = new Map(model.nodes.map((n) => [n.id, n]));
    const P = new Map(model.nodes.map((n) => [n.id, project(view, n.x, n.y, n.z)]));
    const xs = [...P.values()].map((p) => p[0]), ys = [...P.values()].map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const w = Math.max(maxX - minX, 1e-6), h = Math.max(maxY - minY, 1e-6);
    const pad = Math.max(w, h) * (compact ? 0.06 : 0.08);
    const depth = (id: string) => { const n = pos.get(id)!; return view === "front" ? -n.y : n.x + n.y - 0.01 * n.z; };
    const lines = model.elements
      .filter((e) => P.has(e.i) && P.has(e.j))
      .map((e) => ({ id: e.id, a: P.get(e.i)!, b: P.get(e.j)!, key: elementColorKey(e), d: (depth(e.i) + depth(e.j)) / 2 }))
      .sort((p, q) => q.d - p.d);
    const panels = [...model.slabs, ...(model.walls ?? [])]
      .map((s) => s.corners.map((c) => P.get(c)).filter(Boolean) as [number, number][])
      .filter((c) => c.length >= 3);
    const supports = model.supports.filter((s) => !s.lateral && P.has(s.node)).map((s) => P.get(s.node)!);
    const keys = [...new Set(lines.map((l) => l.key))];
    const ext = (k: "x" | "y" | "z") => { const v = model.nodes.map((n) => n[k]); return Math.max(...v) - Math.min(...v); };
    return { lines, panels, supports, keys, vb: [minX - pad, minY - pad, w + 2 * pad, h + 2 * pad], size: Math.max(w, h), dims: { x: ext("x"), y: ext("y"), z: ext("z") } };
  }, [model, view, compact]);

  const stroke = drawing ? drawing.size / (compact ? 70 : 160) : 0;
  return (
    <div className={compact ? "" : "mb-3"}>
      <div className={`relative rounded border border-ink-800 bg-ink-950/60 ${stale && !compact ? "opacity-70" : ""}`} style={{ height }}>
        {drawing ? (
          <svg viewBox={drawing.vb.join(" ")} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
            {drawing.panels.map((c, k) => <polygon key={k} points={c.map((p) => p.join(",")).join(" ")} fill="#8fa3b8" fillOpacity={0.12} stroke="none" />)}
            {drawing.lines.map((l) => (
              <line key={l.id} x1={l.a[0]} y1={l.a[1]} x2={l.b[0]} y2={l.b[1]} stroke={TYPE_COLORS[l.key] ?? "#9fb7c9"} strokeWidth={stroke} strokeLinecap="round" />
            ))}
            {!compact && drawing.supports.map((p, k) => (
              <polygon key={k} points={`${p[0]},${p[1]} ${p[0] - 2.2 * stroke},${p[1] + 3.5 * stroke} ${p[0] + 2.2 * stroke},${p[1] + 3.5 * stroke}`} fill="#6b7a8c" />
            ))}
          </svg>
        ) : (
          <div className="h-full flex items-center justify-center text-[10px] text-ink-600">{error ? "" : "…"}</div>
        )}
        {!compact && error && <div className="absolute inset-x-0 bottom-0 p-1 text-[10px] text-amber-300 bg-ink-950/80">Can't preview: {error}</div>}
      </div>
      {!compact && drawing && (
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-ink-400">
          {drawing.keys.map((k) => (
            <span key={k} className="flex items-center gap-1"><span className="w-2.5 h-[3px] rounded" style={{ background: TYPE_COLORS[k] }} />{TYPE_LABELS[k] ?? k}</span>
          ))}
          <span className="ml-auto num">
            {view === "front" ? `${u.f("length", drawing.dims.x, 1)} × ${u.f("length", drawing.dims.z, 1)}` : `${u.f("length", drawing.dims.x, 1)} × ${u.f("length", drawing.dims.y, 1)} × ${u.f("length", drawing.dims.z, 1)}`} {u.u("length")}
          </span>
          <span className="w-full text-ink-600">Preview of the geometry that will be generated. Not analysed.</span>
        </div>
      )}
    </div>
  );
}

const TRUSS_TYPES: { key: string; label: string; hint: string }[] = [
  { key: "pratt", label: "Pratt", hint: "diagonals in tension" },
  { key: "howe", label: "Howe", hint: "diagonals in compression" },
  { key: "warren", label: "Warren", hint: "no verticals" },
  { key: "pitched", label: "Pitched", hint: "gable roof truss" },
];

/** Picture buttons for choosing the truss type. */
export function TrussTypePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="grid grid-cols-2 gap-1.5 mb-2">
      {TRUSS_TYPES.map((t) => (
        <button key={t.key} type="button" onClick={() => onChange(t.key)} title={`${t.label}: ${t.hint}`}
          className={`rounded border p-1 text-left transition-colors ${value === t.key ? "border-accent bg-accent/10" : "border-ink-800 hover:border-ink-600"}`}>
          <GenPreview compact view="front" height={34} params={{ type: "truss2d", truss_type: t.key, span: 12, height: t.key === "pitched" ? 3 : 2, panels: 6 }} />
          <div className={`text-[11px] mt-0.5 ${value === t.key ? "text-accent" : "text-ink-200"}`}>{t.label}</div>
          <div className="text-[9px] text-ink-400 leading-tight">{t.hint}</div>
        </button>
      ))}
    </div>
  );
}
