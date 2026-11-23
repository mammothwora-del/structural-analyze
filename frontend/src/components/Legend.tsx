import { BANDS, cssColorAt, normalize, valueAt, type Scale } from "../lib/colormap";
import { SHELL_COMPS, SHELL_LABEL, type ShellComp } from "../lib/shells";
import { COMP_LABEL, fmt, type Display } from "../lib/display";
import type { FlowData, PathDir } from "../lib/loadpath";
import type { ForceComp } from "../lib/types";
import { useStore, useU } from "../store";

/** Dynamic legend ("control panel") with value bands and share of members in each band. */
export function Legend({ display, flows, shellScale }: { display: Display; flows: FlowData | null; shellScale?: Scale | null }) {
  const { mode, forceComp, set, deformScale, pathDir, colorTransform, animate } = useStore();
  const shellSlabs = useStore((s) => s.results?.slab_model === "shell");
  const hasMesh = useStore((s) => !!s.results?.mesh);
  const { scale, values } = display;
  const u = useU();
  const show = (v: number) => (scale.kind ? u.f(scale.kind, v) : fmt(v, scale.max < 10 ? 2 : 0));
  // share of members (by their max value) in each band
  const counts = new Array(BANDS).fill(0);
  const ids = Object.keys(values);
  for (const id of ids) {
    const v = Math.max(...values[id]);
    const t = normalize(v, scale);
    counts[Math.min(BANDS - 1, Math.max(0, Math.floor(t * BANDS)))]++;
  }
  const bands = Array.from({ length: BANDS }, (_, k) => BANDS - 1 - k);
  return (
    <div className="absolute right-2 top-12 w-[212px] max-h-[calc(100%-60px)] overflow-y-auto rounded-md border border-ink-700 bg-ink-900/92 p-2.5 text-[11px] shadow-xl backdrop-blur">
      <div className="flex items-center justify-between">
        <div className="panel-title">Control Panel</div>
        <span className="tag bg-emerald-500/15 text-emerald-300">FEM</span>
      </div>
      <div className="mt-1 font-semibold text-ink-200">{scale.label}</div>
      <div className="text-ink-400">[{scale.kind ? u.u(scale.kind) : scale.unit}]</div>

      {mode === "forces" && (
        <div className="mt-2 grid grid-cols-3 gap-0.5">
          {(["N", "Vy", "Vz", "T", "My", "Mz"] as ForceComp[]).map((c) => (
            <button key={c} title={COMP_LABEL[c]} onClick={() => set({ forceComp: c })}
              className={`rounded px-1 py-0.5 font-mono ${forceComp === c ? "bg-accent text-ink-950" : "bg-ink-800 text-ink-300 hover:bg-ink-700"}`}>{c}</button>
          ))}
        </div>
      )}
      {mode === "deformation" && (
        <div className="mt-2">
          <div className="flex justify-between text-ink-400"><span>Scale</span><span className="num">×{deformScale}</span></div>
          <input type="range" min={1} max={500} value={deformScale} onChange={(e) => set({ deformScale: +e.target.value })} className="w-full accent-sky-400" />
          <button className={`mt-1 w-full rounded px-1 py-0.5 ${animate ? "bg-accent/20 text-accent" : "bg-ink-800 text-ink-300"}`} onClick={() => set({ animate: !animate })}>{animate ? "❚❚ Pause animation" : "▶ Animate deformation"}</button>
        </div>
      )}
      {mode === "loadpath" && flows && (
        <div className="mt-2">
          <div className="text-ink-400 mb-0.5">Path direction d</div>
          <select className="input" value={pathDir} onChange={(e) => set({ pathDir: e.target.value as PathDir, trace: null })}>
            <option value="auto">Auto (resultant / gravity)</option>
            <option value="-Z">Gravity −Z</option>
            <option value="+X">+X</option><option value="-X">−X</option>
            <option value="+Y">+Y</option><option value="-Y">−Y</option>
          </select>
          <div className="text-ink-400 mt-0.5 num">d = [{flows.d.map((v) => v.toFixed(2)).join(", ")}]</div>
        </div>
      )}

      {mode !== "reactions" && (
        <div className="mt-2 flex gap-0.5">
          {(["linear", "sqrt"] as const).map((t) => (
            <button key={t} onClick={() => set({ colorTransform: t })} className={`flex-1 rounded px-1 py-0.5 ${colorTransform === t ? "bg-ink-600 text-ink-200" : "bg-ink-800 text-ink-400"}`}>{t === "linear" ? "Linear" : "√ scale"}</button>
          ))}
        </div>
      )}
      {mode !== "reactions" && (
        <div className="mt-2 space-y-px">
          {bands.map((k) => {
            const hi = valueAt((k + 1) / BANDS, scale);
            const pct = ids.length ? (counts[k] / ids.length) * 100 : 0;
            return (
              <div key={k} className="flex items-center gap-1.5">
                <span className="w-12 text-right num text-ink-300">{show(hi)}</span>
                <span className="h-3.5 w-9 rounded-sm" style={{ background: cssColorAt((k + 0.5) / BANDS) }} />
                <span className="num text-ink-400">{pct.toFixed(1)} %</span>
              </div>
            );
          })}
          <div className="flex items-center gap-1.5"><span className="w-12 text-right num text-ink-300">{show(scale.min)}</span></div>
        </div>
      )}
      {mode === "reactions" && <ReactionLegend />}
      {mode === "stress" && shellScale && <ShellSection scale={shellScale} />}
      {mode === "deformation" && hasMesh && <div className="mt-1 text-[10px] text-ink-400">Slabs and walls use the same |u| scale (shell FEM nodal displacements).</div>}
      {scale.note && <div className="mt-2 text-[10px] leading-snug text-ink-400">{scale.note}</div>}
      {mode === "loadpath" && <div className="mt-1 text-[10px] leading-snug text-ink-400">Particles move in the direction the load travels; density ∝ magnitude. {shellSlabs
        ? "Arrows in slabs and walls show the load flux along d from the shell forces (FEM): φ = −(traction on a cut)·d, colour ∝ |φ| (kN/m)."
        : "Arrows on slabs show the assumed tributary transfer."}{hasMesh && !shellSlabs ? " Arrows in walls: shell FEM load flux." : ""}</div>}
    </div>
  );
}

function ReactionLegend() {
  const u = useU();
  const model = useStore((s) => s.model)!;
  const qa = model.settings.allowable_bearing;
  return (
    <div className="mt-2 space-y-1">
      <div className="h-3 rounded" style={{ background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1].map((t) => cssColorAt(t)).join(",")})` }} />
      <div className="flex justify-between num text-ink-400"><span>0</span><span>q_allow = {u.w("soil", qa, 0)}</span></div>
      <div className="text-[10px] text-ink-400 leading-snug">Footing colour = q_max / q_allow (user input). Surfaces below footings show the linear contact pressure of a rigid footing, full contact assumed. Magenta = uplift (assumption invalid). Not a geotechnical design check.</div>
    </div>
  );
}

function ShellSection({ scale }: { scale: Scale }) {
  const u = useU();
  const { shellComp, set } = useStore();
  const k = scale.kind!;
  const ticks = [1, 0.75, 0.5, 0.25, 0];
  return (
    <div className="mt-3 border-t border-ink-700 pt-2">
      <div className="flex items-center justify-between"><div className="panel-title">Slabs & walls</div><span className="tag bg-emerald-500/15 text-emerald-300">SHELL FEM</span></div>
      <div className="mt-1 grid grid-cols-3 gap-0.5">
        {SHELL_COMPS.map((c) => (
          <button key={c} title={SHELL_LABEL[c]} onClick={() => set({ shellComp: c as ShellComp })}
            className={`rounded px-1 py-0.5 font-mono ${shellComp === c ? "bg-accent text-ink-950" : "bg-ink-800 text-ink-300 hover:bg-ink-700"}`}>{c === "vm" ? "σv" : c.toLowerCase()}</button>
        ))}
      </div>
      <div className="mt-1 font-semibold text-ink-200">{scale.label}</div>
      <div className="text-ink-400">[{u.u(k)}]</div>
      <div className="mt-1 flex gap-1.5">
        <div className="w-4 h-28 rounded-sm" style={{ background: `linear-gradient(0deg, ${Array.from({ length: 11 }, (_, i) => cssColorAt(i / 10)).join(",")})` }} />
        <div className="flex flex-col justify-between h-28 num text-ink-300">
          {ticks.map((t) => <span key={t}>{u.f(k, scale.min + t * (scale.max - scale.min))}</span>)}
        </div>
      </div>
      <div className="mt-1 text-[10px] leading-snug text-ink-400">{scale.signed ? "Signed: blue = negative, red = positive. " : ""}Moments: + = tension at the panel's −z face (slab bottom). Elastic surface stresses, no cracking, no design check.</div>
    </div>
  );
}
