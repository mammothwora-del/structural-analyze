import { cssColorAt } from "../lib/colormap";
import type { Display } from "../lib/display";
import { useState } from "react";
import { api } from "../lib/api";
import type { Model, RcDesignResult, SteelCheck, SteelDesignResult, SteelMember, SuggestResult } from "../lib/types";
import type { UnitsApi } from "../lib/units";
import { useStore, useU } from "../store";

export const CODE_OPTIONS: [string, string][] = [
  ["", "From the model's standard"],
  ["AISC360", "AISC 360-16 (LRFD)"],
  ["EC3", "EN 1993-1-1 (Eurocode 3)"],
  ["EIT", "Thai EIT (AISC-based LRFD)"],
];

const UTIL_STOPS = [0, 0.5, 0.75, 0.9, 1.0];

/** Colour members by utilisation (members not checked stay grey). */
export function designDisplay(steel: SteelDesignResult | RcDesignResult | null): Display | null {
  if (!steel) return null;
  const values: Record<string, number[]> = {};
  for (const [id, m] of Object.entries(steel.members)) if (m.util != null) values[id] = [m.util, m.util];
  return { values, res: null, scale: { min: 0, max: 1, label: "Utilisation", unit: "–", limit: 1, note: steel.code_name } };
}

export const statusTag = (m: Pick<SteelMember, "status">) =>
  m.status === "ok" ? <span className="tag bg-emerald-500/15 text-emerald-300">OK</span>
    : m.status === "fail" ? <span className="tag bg-red-500/15 text-red-300">OVER 1.0</span>
      : m.status === "not_covered" ? <span className="tag bg-amber-500/15 text-amber-300">NOT COVERED</span>
        : <span className="tag bg-ink-700 text-ink-300">SKIPPED</span>;

export function fmtCheck(c: SteelCheck, u: UnitsApi) {
  if (c.unit === "ratio") { const dg = c.capacity < 0.1 ? 4 : 3; return { d: c.demand.toFixed(dg), cap: c.capacity.toFixed(dg), unit: "" }; }
  return { d: u.f(c.unit, Math.abs(c.demand)), cap: u.f(c.unit, c.capacity), unit: u.u(c.unit) };
}

/** Design mode: steel members or RC beams and columns. */
export function DesignPanel({ model }: { model: Model }) {
  const { designTab, set } = useStore();
  return (
    <div className="absolute z-20 right-2 top-12 bottom-2 w-[290px] overflow-y-auto rounded-md border border-ink-700 bg-ink-900/92 p-2.5 text-[11px] backdrop-blur">
      <div className="flex mb-2 rounded border border-ink-700 overflow-hidden">
        {([["steel", "Steel members"], ["rc", "RC (Thai EIT)"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => set({ designTab: k })} className={`flex-1 py-1 ${designTab === k ? "bg-accent text-ink-950 font-semibold" : "text-ink-300 hover:bg-ink-800"}`}>{label}</button>
        ))}
      </div>
      {designTab === "steel" ? <SteelTab model={model} /> : <RcTab />}
      <div className="mt-2 border-t border-ink-800 pt-1.5 text-ink-500">
        A utilisation at or below 1.0 means the member passes the checks listed for it. It is not a statement that the
        structure is safe: connections, stability of the whole structure and the items in the notes must be checked separately.
      </div>
    </div>
  );
}

function Summary({ r }: { r: SteelDesignResult | RcDesignResult }) {
  const { set } = useStore();
  const worst = Object.values(r.members).filter((m) => m.util != null).sort((a, b) => b.util! - a.util!).slice(0, 12);
  const nc = Object.values(r.members).filter((m) => m.status === "not_covered");
  return (
    <>
      <div className="flex items-center justify-between mb-1">
        <span className="font-semibold text-ink-200">{r.code_name}</span>
        <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>
      </div>
      <div className="text-ink-400 mb-1.5">Combinations: <span className="font-mono text-ink-300">{r.combinations.join(", ")}</span></div>
      <div className="grid grid-cols-4 gap-1 mb-2 text-center">
        {([["OK", r.summary.ok, "text-emerald-300"], ["Over 1.0", r.summary.fail, "text-red-300"], ["Not covered", r.summary.not_covered, "text-amber-300"], ["Max", r.summary.max_util != null ? r.summary.max_util.toFixed(2) : "–", r.summary.max_util != null && r.summary.max_util > 1 ? "text-red-300" : "text-ink-100"]] as [string, number | string, string][]).map(([k, v, c]) => (
          <div key={k} className="rounded bg-ink-800/80 py-1"><div className={`num text-sm ${c}`}>{v}</div><div className="text-[10px] text-ink-400">{k}</div></div>
        ))}
      </div>
      <div className="flex items-center gap-0.5 mb-0.5">
        {UTIL_STOPS.slice(0, -1).map((a, k) => <div key={a} className="h-2 flex-1" style={{ background: `linear-gradient(90deg, ${cssColorAt(a)}, ${cssColorAt(UTIL_STOPS[k + 1])})` }} />)}
        <div className="h-2 w-6" style={{ background: cssColorAt(1) }} />
      </div>
      <div className="flex justify-between text-[10px] text-ink-500 num mb-2"><span>0</span><span>0.5</span><span>0.75</span><span>0.9</span><span>≥1.0</span></div>
      <div className="text-ink-300 mb-0.5">Highest utilisation</div>
      <table className="w-full mb-2">
        <tbody>
          {worst.map((m) => (
            <tr key={m.id} onClick={() => set({ selection: { kind: "element", id: m.id }, multi: [] })} className="cursor-pointer border-t border-ink-800 hover:bg-ink-800">
              <td className="py-0.5 font-mono text-ink-200">{m.id}</td>
              <td className="text-ink-400 truncate max-w-[120px]" title={m.governing ? `${m.governing.name}, ${m.governing.clause}, ${m.governing.combo}` : ""}>{m.governing?.name}</td>
              <td className={`num text-right ${m.util! > 1 ? "text-red-300" : m.util! > 0.9 ? "text-amber-200" : "text-ink-200"}`}>{m.util!.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {nc.length > 0 && (
        <div className="mb-2">
          <div className="text-amber-300 mb-0.5">Not covered ({nc.length}): outside the implemented clauses, check by hand</div>
          {nc.slice(0, 6).map((m) => (
            <div key={m.id} className="cursor-pointer text-ink-400 hover:text-ink-200" onClick={() => set({ selection: { kind: "element", id: m.id }, multi: [] })}>
              <span className="font-mono text-ink-300">{m.id}</span> {m.reason}
            </div>
          ))}
          {nc.length > 6 && <div className="text-ink-500">… and {nc.length - 6} more</div>}
        </div>
      )}
      <ul className="mt-1.5 list-disc pl-4 space-y-0.5 text-ink-500">{r.notes.map((n, k) => <li key={k}>{n}</li>)}</ul>
    </>
  );
}

function RcTab() {
  const s = useStore();
  const { rc, rcBusy, rcError, rcOptions, set } = s;
  const opt = (k: keyof typeof rcOptions, v: string | number) => set({ rcOptions: { ...rcOptions, [k]: v }, rc: null });
  return (
    <>
      <div className="grid grid-cols-3 gap-1 mb-1.5">
        <label className="text-ink-400">Main bars<select className="input" value={rcOptions.main_grade} onChange={(e) => opt("main_grade", e.target.value)}>{["SD30", "SD40", "SD50"].map((g) => <option key={g}>{g}</option>)}</select></label>
        <label className="text-ink-400">Stirrups<select className="input" value={rcOptions.tie_grade} onChange={(e) => opt("tie_grade", e.target.value)}>{["SR24", "SD30", "SD40"].map((g) => <option key={g}>{g}</option>)}</select></label>
        <label className="text-ink-400">Cover (cm)<input className="input" type="number" step="0.5" min="2" value={rcOptions.cover * 100} onChange={(e) => opt("cover", Math.max(+e.target.value, 1) / 100)} /></label>
      </div>
      <button className="btn-primary w-full mb-2" disabled={rcBusy} onClick={() => s.runRc()}>{rcBusy ? "Designing…" : "Design RC beams and columns"}</button>
      {rcError && <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{rcError}</div>}
      {!rc && !rcBusy && <div className="text-ink-400">Designs the longitudinal bars, stirrups and ties of every rectangular concrete beam and column to EIT 1008-38 (strength design) for all ultimate combinations, from a fresh linear analysis. Slabs, walls and footings are not designed.</div>}
      {rc && <Summary r={rc} />}
    </>
  );
}

/** Steel member design: code choice, summary, worst members. */
function SteelTab({ model }: { model: Model }) {
  const s = useStore();
  const { steel, steelBusy, steelError, steelCode, set } = s;
  const std = model.settings.standard;
  return (
    <>
      <select className="input mb-1.5" value={steelCode} onChange={(e) => set({ steelCode: e.target.value, steel: null })}>
        {CODE_OPTIONS.map(([k, label]) => <option key={k} value={k}>{k ? label : `${label} (${std === "ASCE7" ? "AISC 360" : std === "TH" ? "Thai EIT" : "EN 1993"})`}</option>)}
      </select>
      <button className="btn-primary w-full mb-2" disabled={steelBusy} onClick={() => s.runSteel()}>{steelBusy ? "Checking…" : "Check steel members"}</button>
      {steelError && <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{steelError}</div>}
      {!steel && !steelBusy && <div className="text-ink-400">Checks every steel member for all ultimate (ULS) combinations of the model, from a fresh linear analysis. Concrete members are left for RC design.</div>}

      <SuggestSizes model={model} />
      {steel && <Summary r={steel} />}
    </>
  );
}

const FAMILY_OPTIONS: [string, string][] = [["keep", "Same shape"], ["H", "H section"], ["I", "I-beam"], ["C", "Channel"], ["L", "Equal angle"],
  ["SHS", "SHS"], ["RHS", "RHS"], ["CHS", "CHS (pipe)"], ["lock", "Keep this size"]];

/** Lightest standard size per section group that passes, worked out on the server with fresh analyses. */
function SuggestSizes({ model }: { model: Model }) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState(1.0);
  const [slender, setSlender] = useState(true);
  const [groups, setGroups] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<SuggestResult | null>(null);
  const steelSecs = Object.entries(model.sections).filter(([k, sec]) => model.materials[sec.material]?.kind === "steel" && model.elements.some((e) => e.section === k));
  if (!steelSecs.length) return null;
  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api.suggestSteel(model, s.steelCode || undefined, target, groups, slender));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!res) return;
    const r = res;
    s.editModel((m) => { Object.assign(m.sections, r.sections); });
    s.set({ steel: r.design, log: [...useStore.getState().log, `— Suggested sizes applied (${r.code_name}, target ${r.target}) —`,
      ...r.groups.filter((g) => g.changed).map((g) => `${g.section}: ${g.from} → ${g.to} (max utilisation ${g.max_util?.toFixed(2) ?? "–"})`)] });
    setRes(null);
    await s.analyze();
    s.set({ mode: "design", designTab: "steel" });
  };
  const kg = (v: number | null) => (v == null ? "–" : v >= 10000 ? `${(v / 1000).toFixed(1)} t` : `${v.toFixed(0)} kg`);
  const tot = (k: "mass_before" | "mass_after") => res ? res.groups.reduce((a, g) => a + (g[k] ?? 0), 0) : 0;
  return (
    <div className="mb-2 rounded border border-ink-700 p-1.5">
      <button className="w-full flex justify-between items-center text-ink-200 font-semibold" onClick={() => setOpen(!open)}>
        <span>Suggest sizes</span><span className="text-ink-500">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="mt-1.5">
          <div className="text-ink-400 mb-1.5">For each section group, the lightest standard size that passes the steel checks. The server analyses again after every change until the sizes stop changing, then checks the final model.</div>
          <table className="w-full mb-1.5">
            <tbody>
              {steelSecs.map(([k, sec]) => (
                <tr key={k} className="border-t border-ink-800">
                  <td className="py-0.5 pr-1"><b className="text-ink-200">{k}</b> <span className="text-ink-500 truncate">{sec.catalog ?? sec.shape}</span></td>
                  <td className="w-[104px]">
                    <select className="input !py-0" value={groups[k] ?? "keep"} onChange={(e) => setGroups({ ...groups, [k]: e.target.value })}>
                      {FAMILY_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <label className="flex items-center justify-between gap-2 mb-1.5 text-ink-400">
            <span>Target utilisation</span>
            <input className="input !w-16 text-right" type="number" min={0.3} max={1} step={0.05} value={target} onChange={(e) => setTarget(Math.min(1, Math.max(0.3, +e.target.value || 1)))} />
          </label>
          <label className="flex items-start gap-1.5 mb-1.5 text-ink-400 cursor-pointer">
            <input type="checkbox" className="mt-0.5 accent-sky-400" checked={slender} onChange={(e) => setSlender(e.target.checked)} />
            <span>Limit slenderness: KL/r ≤ 200 in compression, L/r ≤ 300 in tension (AISC user notes)</span>
          </label>
          <button className="btn-primary w-full mb-1" disabled={busy || s.busy} onClick={run}>{busy ? "Sizing (analysing several times)…" : "Suggest sizes"}</button>
          {err && <div className="mb-1 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{err}</div>}
          {res && (
            <>
              <div className="flex items-center justify-between mt-1 mb-0.5">
                <span className="text-ink-300">{res.converged ? `Settled after ${res.iterations} passes` : `Still changing after ${res.iterations} passes`}</span>
                <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>
              </div>
              <table className="w-full mb-1">
                <thead><tr className="text-ink-500 text-[10px]"><th className="text-left font-normal">Group</th><th className="text-left font-normal">Suggested</th><th className="text-right font-normal">Util.</th></tr></thead>
                <tbody>
                  {res.groups.map((g) => (
                    <tr key={g.section} className="border-t border-ink-800 align-top" title={`was ${g.from}`}>
                      <td className="py-0.5 font-mono text-ink-200">{g.section}</td>
                      <td className={g.changed ? "text-accent" : "text-ink-400"}>{g.to.replace(/ \S+$/, "")}{g.locked ? " (kept)" : ""}{g.largest_too_small ? " ⚠ largest" : ""}
                        <div className="text-[10px] text-ink-500">was {g.from.replace(/ \S+$/, "")} · {kg(g.mass_before)} → {kg(g.mass_after)}</div></td>
                      <td className={`num text-right ${g.max_util != null && g.max_util > 1 ? "text-red-300" : "text-ink-200"}`}>{g.max_util?.toFixed(2) ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="text-ink-400 mb-1">Steel weight of these groups: {kg(tot("mass_before"))} → <b className="text-ink-200">{kg(tot("mass_after"))}</b>. Final check: {res.design.summary.ok} OK, {res.design.summary.fail} over 1.0, max {res.design.summary.max_util?.toFixed(2) ?? "–"}.</div>
              <ul className="list-disc pl-4 space-y-0.5 text-ink-500 mb-1.5">{res.notes.map((n, k) => <li key={k}>{n}</li>)}</ul>
              <div className="flex gap-1">
                <button className="btn flex-1" onClick={() => setRes(null)}>Discard</button>
                <button className="btn-primary flex-1" disabled={s.busy} onClick={apply}>Apply and re-design</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
