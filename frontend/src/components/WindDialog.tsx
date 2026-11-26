import { useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import type { Model, WindParams, WindSummary } from "../lib/types";
import { useStore, useU } from "../store";

const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="block text-ink-400">{label}<div className="mt-0.5">{children}</div></label>
);

const ZONES: [WindParams["zone"], string][] = [
  ["1", "Zone 1: central (Bangkok), V50 25 m/s"], ["2", "Zone 2: lower north, east-west border, 27 m/s"],
  ["3", "Zone 3: upper north, 29 m/s"], ["4A", "Zone 4A: south, east coast, 25 m/s, TF 1.2"],
  ["4B", "Zone 4B: Phetchaburi, south west coast, 25 m/s, TF 1.08"],
];
const IMPORTANCE: [WindParams["importance"], string][] = [
  ["low", "Low: farm, temporary, minor storage (Iw 0.8)"], ["normal", "Normal (Iw 1.0)"],
  ["high", "High: assembly > 300, schools, hospitals (Iw 1.15)"], ["very_high", "Very high: essential facilities (Iw 1.15)"],
];
const INTERNAL: [WindParams["internal"], string][] = [
  ["1", "1: no large openings (Cpi −0.15 to 0)"], ["2", "2: openings closed in a storm (−0.45 to +0.3)"],
  ["3", "3: large openings, e.g. warehouse doors (−0.7 to +0.7)"],
];
const ZONE_ORDER = ["1", "1E", "2", "2E", "3", "3E", "4", "4E", "5", "5E", "6", "6E"];
const ZONE_ROLE: Record<string, string> = { "1": "windward wall", "2": "windward roof", "3": "leeward roof", "4": "leeward wall", "5": "windward end wall", "6": "leeward end wall" };
const ROLE2: Record<string, string> = { "1": "side wall (corner side)", "2": "roof half (corner side)", "3": "roof half (far side)", "4": "side wall (far side)", "5": "windward end wall", "6": "leeward end wall" };

/** Generate DPT 1311-50 wind load cases on the model (server: wind.py), with a preview of the pressures first. */
export function WindDialog({ onDone }: { onDone: () => void }) {
  const s = useStore();
  const u = useU();
  const model = s.model as Model;
  const prev = (model.wind?.params ?? {}) as Partial<WindParams>;
  const [p, setP] = useState<WindParams>({ zone: "1", importance: "normal", exposure: "A", internal: "1", use_tf: true, ridge: "auto",
    roof_slope: null, all_corners: false, replace: true, ...prev });
  const [res, setRes] = useState<{ model: Model; summary: WindSummary } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = <K extends keyof WindParams>(k: K, v: WindParams[K]) => { setP({ ...p, [k]: v }); setRes(null); };
  const preview = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.wind(model, p)); } catch (e) { setErr((e as Error).message); setRes(null); } finally { setBusy(false); }
  };
  useEffect(() => { preview(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const apply = () => {
    if (!res) return;
    const r = res.model;
    s.editModel((m) => { m.load_cases = r.load_cases; m.loads = r.loads; m.combinations = r.combinations; m.notes = r.notes; m.wind = r.wind; });
    const w = res.summary;
    s.set({ log: [...useStore.getState().log, "— Wind loads, DPT 1311-50 (low-rise method) —",
      `V = ${w.V.toFixed(1)} m/s, q = ${w.q.toFixed(3)} kN/m², Iw = ${w.Iw}, Ce = ${w.Ce.toFixed(3)} at h = ${w.h.toFixed(2)} m, roof slope ${w.slope.toFixed(1)}°.`,
      `${w.cases.length} wind load cases added (${w.cases.map((c) => c.id).join(", ")})${w.removed_cases.length ? `, replacing ${w.removed_cases.join(", ")}` : ""}. Combinations rebuilt for every wind case. Run the analysis.`] });
    onDone();
  };
  const w = res?.summary;
  const ext = w?.cases.filter((c, k, a) => a.findIndex((d) => d.case === c.case) === k) ?? [];
  return (
    <>
      <div className="grid grid-cols-2 gap-2 mb-2">
        <Field label="Wind zone"><select className="input" value={p.zone} onChange={(e) => set("zone", e.target.value as WindParams["zone"])}>{ZONES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Importance"><select className="input" value={p.importance} onChange={(e) => set("importance", e.target.value as WindParams["importance"])}>{IMPORTANCE.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Exposure"><select className="input" value={p.exposure} onChange={(e) => set("exposure", e.target.value as WindParams["exposure"])}>
          <option value="A">A: open terrain</option><option value="B">B: suburban, wooded, small town centre</option></select></Field>
        <Field label="Internal pressure"><select className="input" value={p.internal} onChange={(e) => set("internal", e.target.value as WindParams["internal"])}>{INTERNAL.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Ridge direction"><select className="input" value={p.ridge} onChange={(e) => set("ridge", e.target.value as WindParams["ridge"])}>
          <option value="auto">From the purlins (auto)</option><option value="x">Along X</option><option value="y">Along Y</option></select></Field>
        <Field label="Roof slope (°), empty = from the model"><input className="input" type="number" min={0} max={60} step={0.5} value={p.roof_slope ?? ""} placeholder={w ? w.slope.toFixed(1) : "auto"}
          onChange={(e) => set("roof_slope", e.target.value === "" ? null : +e.target.value)} /></Field>
      </div>
      <div className="space-y-1 mb-2">
        <label className="flex items-start gap-2 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={p.use_tf} onChange={(e) => set("use_tf", e.target.checked)} />
          <span>Apply the typhoon factor TF (zones 4A, 4B). The standard requires it for very-high importance and leaves it to the designer otherwise.</span></label>
        <label className="flex items-start gap-2 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={p.all_corners} onChange={(e) => set("all_corners", e.target.checked)} />
          <span>All four corners as the windward corner (8 directions instead of 4; for a structure that is not symmetric)</span></label>
        <label className="flex items-start gap-2 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={p.replace} onChange={(e) => set("replace", e.target.checked)} />
          <span>Replace the model's existing wind cases ({model.load_cases.filter((c) => c.type === "wind").map((c) => c.id).join(", ") || "none"}) and their combinations</span></label>
      </div>
      <button className="btn w-full mb-2" disabled={busy} onClick={preview}>{busy ? "Calculating…" : "Calculate pressures"}</button>
      {err && <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{err}</div>}
      {w && (
        <>
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-ink-200">{w.zone_name}</span>
            <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>
          </div>
          <div className="grid grid-cols-4 gap-1 mb-2 text-center">
            {([["V", `${w.V.toFixed(1)} m/s`], ["q", `${u.f("areaLoad", w.q)} ${u.u("areaLoad")}`], ["Iw · Ce", `${w.Iw} · ${w.Ce.toFixed(3)}`], ["h", `${w.h.toFixed(2)} m`],
              ["Roof slope", `${w.slope.toFixed(1)}°`], ["End zone y", `${w.y_end.toFixed(2)} m`], ["Edge z", `${w.z_edge.toFixed(2)} m`], ["SLS factor", w.sls_factor.toFixed(3)]] as [string, string][]).map(([k, v]) => (
              <div key={k} className="rounded bg-ink-800/80 py-1"><div className="num text-[12px] text-ink-100">{v}</div><div className="text-[10px] text-ink-400">{k}</div></div>
            ))}
          </div>
          {ext.map((c) => (
            <div key={c.case} className="mb-2">
              <div className="text-ink-300 mb-0.5">Load case {c.case}: wind {c.case === 1 ? "perpendicular" : "parallel"} to the ridge. CpCg (Figure ข.1, includes Cg) and net pressure p = Iw·q·Ce·(CpCg − 2.0·Cpi) for Cpi = {c.cpi.toFixed(2)}, positive towards the surface ({u.u("areaLoad")})</div>
              <table className="w-full">
                <thead><tr className="text-ink-500 text-[10px]"><th className="text-left font-normal">Zone</th><th className="text-left font-normal">Surface</th><th className="text-right font-normal">CpCg</th><th className="text-right font-normal">p</th></tr></thead>
                <tbody>
                  {ZONE_ORDER.filter((z) => c.zones[z]).map((z) => (
                    <tr key={z} className="border-t border-ink-800">
                      <td className="font-mono text-ink-200">{z}</td>
                      <td className="text-ink-400">{(c.case === 1 ? ZONE_ROLE : ROLE2)[z.replace("E", "")]}{z.endsWith("E") ? " (end zone)" : ""}</td>
                      <td className="num text-right text-ink-300">{c.zones[z].cpcg.toFixed(2)}</td>
                      <td className={`num text-right ${c.zones[z].p < 0 ? "text-sky-300" : "text-amber-200"}`}>{u.f("areaLoad", c.zones[z].p)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <div className="text-ink-300 mb-0.5">Load cases to add ({w.cases.length}) with the resultant of their loads ({u.u("force")})</div>
          <table className="w-full mb-2">
            <thead><tr className="text-ink-500 text-[10px]"><th className="text-left font-normal">Case</th><th className="text-left font-normal">Name</th><th className="text-right font-normal">Fx</th><th className="text-right font-normal">Fy</th><th className="text-right font-normal">Fz</th></tr></thead>
            <tbody>
              {w.cases.map((c) => (
                <tr key={c.id} className="border-t border-ink-800">
                  <td className="font-mono text-ink-200">{c.id}</td><td className="text-ink-400">{c.name.replace(/^Wind /, "")}</td>
                  {c.resultant.map((f, k) => <td key={k} className="num text-right text-ink-300">{u.f("force", f)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="list-disc pl-4 space-y-0.5 text-ink-500 mb-2">{w.notes.map((n, k) => <li key={k}>{n}</li>)}</ul>
        </>
      )}
      <div className="flex gap-2">
        <button className="btn flex-1" onClick={onDone}>Cancel</button>
        <button className="btn-primary flex-1" disabled={!res || busy} onClick={apply}>Add {w?.cases.length ?? ""} wind load cases</button>
      </div>
    </>
  );
}
