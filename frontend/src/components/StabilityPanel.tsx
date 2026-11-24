import { useState } from "react";
import { baseLoad, pdeltaId, useStore, useU } from "../store";

const Calc = () => <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>;

/** Linear buckling and P-Delta for the load case or combination chosen in the top bar. */
export function StabilityPanel() {
  const s = useStore();
  const u = useU();
  const { model, buckling, pdelta, bucklingMode, stabBusy, stabError, set } = s;
  const [nSeg, setNSeg] = useState(4);
  const [nModes, setNModes] = useState(4);
  if (!model) return null;
  const load = baseLoad(s.loadSel);
  const loadName = model.combinations.find((c) => c.id === load)?.name ?? model.load_cases.find((c) => c.id === load)?.name ?? "";
  const isCombo = model.combinations.some((c) => c.id === load);
  const showPd = (m: "forces" | "deformation" | "stress") => set({ loadSel: pdeltaId(pdelta!.load), mode: m });

  return (
    <div className="absolute z-20 right-2 top-12 bottom-2 w-[280px] overflow-y-auto rounded-md border border-ink-700 bg-ink-900/92 p-2.5 text-[11px] backdrop-blur">
      <div className="panel-title mb-1">Stability</div>
      <div className="text-ink-400 mb-2">
        Load: <b className="text-ink-200 font-mono">{load}</b> {loadName && <span>– {loadName}</span>}
        <div className="text-ink-600">Change it with Load in the top bar.{!isCombo && " A factored (ULS) combination is the usual choice."}</div>
      </div>

      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-ink-400">Segments / member</span>
        <select className="input !w-14" value={nSeg} onChange={(e) => setNSeg(+e.target.value)}>{[2, 4, 6, 8].map((n) => <option key={n}>{n}</option>)}</select>
        <span className="text-ink-400 ml-1">Modes</span>
        <select className="input !w-12" value={nModes} onChange={(e) => setNModes(+e.target.value)}>{[1, 2, 4, 6, 10].map((n) => <option key={n}>{n}</option>)}</select>
      </div>
      <div className="flex gap-1 mb-2">
        <button className="btn-primary flex-1" disabled={stabBusy} onClick={() => s.runBuckling(nSeg, nModes)} title="Elastic critical load factors (eigenvalue buckling)">Buckling</button>
        <button className="btn-primary flex-1" disabled={stabBusy} onClick={() => s.runPDelta()} title="Second-order analysis on the deformed shape">P-Delta</button>
      </div>
      {stabBusy && <div className="text-ink-400 mb-2">Solving…</div>}
      {stabError && <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{stabError}</div>}

      {buckling && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1"><span className="font-semibold text-ink-200">Buckling – {buckling.load}</span><Calc /></div>
          {buckling.modes.length ? (
            <table className="w-full num">
              <thead className="text-ink-400"><tr><th className="text-left font-medium">Mode</th><th className="text-right font-medium">Load factor α<sub>cr</sub></th><th /></tr></thead>
              <tbody>
                {buckling.modes.map((m, k) => (
                  <tr key={k} onClick={() => set({ bucklingMode: k, mode: "stability" })} className={`cursor-pointer border-t border-ink-800 ${bucklingMode === k ? "bg-accent/10" : "hover:bg-ink-800"}`}>
                    <td className="py-0.5">{k + 1}</td>
                    <td className={`text-right ${m.factor < 1 ? "text-red-300" : m.factor < 10 ? "text-amber-200" : "text-ink-200"}`}>{m.factor.toFixed(3)}</td>
                    <td className="text-right text-ink-500">{m.factor < 1 ? "below load" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="text-ink-400">No buckling mode (no compression under this load).</div>}
          {buckling.modes.length > 0 && (
            <div className="mt-1 text-ink-400">
              α<sub>cr</sub> = multiple of this load at which the ideal elastic structure buckles.
              {buckling.modes[0].factor < 10 && " Below 10, EN 1993-1-1 §5.2.1 asks for second-order effects (P-Delta)."}
            </div>
          )}
          <ScaleSlider />
          <Notes notes={buckling.notes} />
        </div>
      )}

      {pdelta && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1"><span className="font-semibold text-ink-200">P-Delta – {pdelta.load}</span><Calc /></div>
          <table className="w-full">
            <tbody>
              <Row k="Converged" v={pdelta.converged ? `yes, ${pdelta.iterations} iterations` : `NO (${pdelta.iterations} iterations)`} bad={!pdelta.converged} />
              <Row k="Max displacement, linear" v={u.w("disp", pdelta.max_disp_linear, 1)} />
              <Row k="Max displacement, P-Delta" v={u.w("disp", pdelta.max_disp_pdelta, 1)} />
              <Row k="Amplification" v={`× ${pdelta.amplification.toFixed(3)}`} bad={pdelta.amplification > 1.5} />
            </tbody>
          </table>
          <div className="mt-1.5 text-ink-400">View the second-order results (selectable as <span className="font-mono">{pdeltaId(pdelta.load)}</span> in the Load list):</div>
          <div className="flex gap-1 mt-1">
            <button className="btn flex-1" onClick={() => showPd("forces")}>Forces</button>
            <button className="btn flex-1" onClick={() => showPd("deformation")}>Deformation</button>
            <button className="btn flex-1" onClick={() => showPd("stress")}>Stress</button>
          </div>
          {pdelta.warnings.filter((w) => w.level !== "info").map((w, k) => <div key={k} className="mt-1 text-amber-300">{w.message}</div>)}
          <Notes notes={pdelta.notes} />
        </div>
      )}

      <div className="border-t border-ink-800 pt-1.5 text-ink-500">
        Elastic analysis of the perfect geometry: no imperfections, residual stresses or yielding. These results feed design
        checks; they are not a design check themselves and do not show that the structure is safe.
      </div>
    </div>
  );
}

function Row({ k, v, bad }: { k: string; v: string; bad?: boolean }) {
  return <tr className="border-t border-ink-800"><td className="py-0.5 text-ink-400">{k}</td><td className={`num text-right whitespace-nowrap ${bad ? "text-amber-300" : "text-ink-200"}`}>{v}</td></tr>;
}

function Notes({ notes }: { notes: string[] }) {
  return <ul className="mt-1.5 list-disc pl-4 space-y-0.5 text-ink-500">{notes.map((n, k) => <li key={k}>{n}</li>)}</ul>;
}

function ScaleSlider() {
  const { deformScale, set } = useStore();
  return (
    <label className="mt-1.5 flex items-center gap-2 text-ink-400">
      Shape scale
      <input type="range" min={5} max={300} value={deformScale} onChange={(e) => set({ deformScale: +e.target.value })} className="flex-1" />
    </label>
  );
}
