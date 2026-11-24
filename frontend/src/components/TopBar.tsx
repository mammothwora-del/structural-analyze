import { useRef, useState } from "react";
import { combinedResult } from "../lib/combine";
import type { Model } from "../lib/types";
import { useStore } from "../store";
import { MODES } from "./Viewport";
import { SYSTEM_LABEL, type UnitSystem } from "../lib/units";

function download(name: string, data: string | Blob, type = "application/json") {
  const blob = typeof data === "string" ? new Blob([data], { type }) : data;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function exportCsv() {
  const { model, results, loadSel } = useStore.getState();
  if (!model || !results) return;
  const res = combinedResult(model, results, loadSel)!;
  const lines = [`# Structural Analyze results - ${loadSel} - units kN, m`, "", "REACTIONS", "node,Rx,Ry,Rz,Mx,My,Mz"];
  for (const [n, r] of Object.entries(res.reactions)) lines.push([n, ...r.map((v) => v.toFixed(4))].join(","));
  lines.push("", "MEMBER STATIONS", "element,x,N,Vy,Vz,T,My,Mz,ux_mm,uy_mm,uz_mm,sigma_max_MPa,sigma_min_MPa");
  for (const [id, st] of Object.entries(res.elements)) {
    st.x.forEach((x, k) => lines.push([id, x.toFixed(4), st.N[k], st.Vy[k], st.Vz[k], st.T[k], st.My[k], st.Mz[k], ...st.disp[k].map((d) => d * 1000), st.sigma_max[k] / 1000, st.sigma_min[k] / 1000].map((v) => (typeof v === "number" ? +v.toFixed(5) : v)).join(",")));
  }
  lines.push("", "NODE DISPLACEMENTS (mm, mrad)", "node,ux,uy,uz,rx,ry,rz");
  for (const [n, d] of Object.entries(res.displacements)) lines.push([n, ...d.map((v) => (v * 1000).toFixed(5))].join(","));
  download(`results_${loadSel}.csv`, lines.join("\n"), "text/csv");
}

export function TopBar() {
  const s = useStore();
  const { model, results, loadSel, set, analyze, busy, view, resultsStale, backendOk } = s;
  const [open, setOpen] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const menus: Record<string, [string, () => void, boolean?][]> = {
    File: [
      ["New building (default)", () => s.generate({})],
      ["Open model (.json)…", () => file.current?.click()],
      ["Save model (.json)", () => model && download(`${model.name.replace(/\s+/g, "_")}.json`, JSON.stringify(model, null, 1)), !model],
    ],
    Edit: [
      ["Undo  (Ctrl+Z)", () => s.undo(), !s.history.length],
      ["Clear selection  (Esc)", () => set({ selection: null, multi: [] })],
      ["Show all (end isolation)", () => set({ isolated: null, maxLevel: null })],
    ],
    Model: [
      ["Building generator", () => set({ view: "3d" })],
      ["Model mode", () => set({ mode: "model", view: "3d" })],
    ],
    Loads: [
      ["Load visualisation", () => set({ mode: "loads", view: "3d" })],
      ["Load cases", () => set({ bottomTab: "cases" })],
      ["Combinations", () => set({ bottomTab: "combos" })],
    ],
    Analyze: [["Run linear static analysis  (F5)", () => analyze(), !model], ["Stability: buckling and P-Delta  (8)", () => set({ mode: "stability", view: "3d" }), !model]],
    Results: [...MODES.filter((m) => m.needs).map((m) => [m.label, () => set({ mode: m.id, view: "3d" }), !results] as [string, () => void, boolean]),
      ["Dashboard", () => set({ view: "dashboard" }), !results], ["Reactions table", () => set({ bottomTab: "reactions" }), !results], ["Member results table", () => set({ bottomTab: "members" }), !results]],
    Export: [
      ["Results (.csv)", exportCsv, !results],
      ["Viewport image (.png)", () => { const c = document.querySelector("canvas"); if (c) c.toBlob((b) => b && download("viewport.png", b)); }],
      ["Model (.json)", () => model && download("model.json", JSON.stringify(model, null, 1)), !model],
    ],
  };
  const options = model ? [...model.load_cases.map((c) => ({ id: c.id, label: `${c.id} – ${c.name}`, grp: "Load cases" })), ...model.combinations.map((c) => ({ id: c.id, label: `${c.id} – ${c.name}`, grp: "Combinations" })),
    ...Object.keys(results?.cases ?? {}).filter((k) => k.startsWith("PD:")).map((k) => ({ id: k, label: `${k.slice(3)} – P-Delta (2nd order)`, grp: "P-Delta results" }))] : [];
  return (
    <header className="h-11 shrink-0 flex items-center gap-1 border-b border-ink-800 bg-ink-900 px-3" onMouseLeave={() => setOpen(null)}>
      <div className="flex items-center gap-2 mr-3">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M3 21h18M5 21V9l7-5 7 5v12M9 21v-6h6v6" stroke="#3fb6ff" strokeWidth="1.8" strokeLinejoin="round" /></svg>
        <div className="leading-tight"><div className="font-semibold text-[13px]">Structural Analyze</div><div className="text-[10px] text-ink-400">3D frame FEM · load path</div></div>
      </div>
      {Object.entries(menus).map(([name, items]) => (
        <div key={name} className="relative">
          <button className={`px-2.5 py-1 rounded text-xs ${open === name ? "bg-ink-700" : "hover:bg-ink-800"} text-ink-300`} onClick={() => setOpen(open === name ? null : name)} onMouseEnter={() => open && setOpen(name)}>{name}</button>
          {open === name && (
            <div className="absolute left-0 top-full z-50 mt-0.5 min-w-[220px] rounded-md border border-ink-700 bg-ink-850 py-1 shadow-2xl">
              {items.map(([label, fn, dis]) => (
                <button key={label} disabled={dis} onClick={() => { setOpen(null); fn(); }} className="block w-full text-left px-3 py-1.5 text-xs text-ink-200 hover:bg-ink-700 disabled:opacity-40">{label}</button>
              ))}
            </div>
          )}
        </div>
      ))}
      <input ref={file} type="file" accept=".json" className="hidden" onChange={async (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        try { s.setModel(JSON.parse(await f.text()) as Model); } catch (err) { set({ error: `Could not read model: ${err}` }); }
        e.target.value = "";
      }} />
      <div className="flex-1" />
      {model && (
        <>
          <span className="text-[11px] text-ink-400">Units</span>
          <select className="input !w-40" value={s.units} onChange={(e) => { const v = e.target.value as UnitSystem; try { localStorage.setItem("units", v); } catch { /* ignore */ } set({ units: v }); }}>
            {(Object.keys(SYSTEM_LABEL) as UnitSystem[]).map((k) => <option key={k} value={k}>{SYSTEM_LABEL[k]}</option>)}
          </select>
          <span className="text-[11px] text-ink-400 ml-2">Load</span>
          <select className="input !w-52" value={loadSel} onChange={(e) => set({ loadSel: e.target.value, trace: null })}>
            {["Load cases", "Combinations", "P-Delta results"].filter((g) => options.some((o) => o.grp === g)).map((g) => (
              <optgroup key={g} label={g}>{options.filter((o) => o.grp === g).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</optgroup>
            ))}
          </select>
          <div className="ml-2 flex rounded border border-ink-700 overflow-hidden">
            {(["3d", "dashboard"] as const).map((v) => (
              <button key={v} onClick={() => set({ view: v })} className={`px-2.5 py-1 text-xs ${view === v ? "bg-ink-700 text-ink-200" : "text-ink-400 hover:bg-ink-800"}`}>{v === "3d" ? "3D View" : "Dashboard"}</button>
            ))}
          </div>
        </>
      )}
      <button className="btn-primary ml-2 flex items-center gap-1.5" disabled={!model || busy} onClick={() => analyze()}>
        {busy ? <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-ink-950 border-t-transparent" /> : <span>▶</span>}
        ANALYZE
      </button>
      {results && (
        <span className={`ml-1 tag ${resultsStale ? "bg-amber-500/15 text-amber-300" : results.ok ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"}`}>
          {resultsStale ? "STALE" : results.ok ? "SOLVED" : "UNSTABLE"}
        </span>
      )}
      <span title={backendOk ? "Solver backend connected" : "Solver backend not reachable"} className={`ml-2 h-2 w-2 rounded-full ${backendOk ? "bg-emerald-400" : backendOk === false ? "bg-red-500" : "bg-ink-600"}`} />
    </header>
  );
}
