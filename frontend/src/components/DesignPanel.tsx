import { cssColorAt } from "../lib/colormap";
import type { Display } from "../lib/display";
import type { Model, SteelCheck, SteelDesignResult, SteelMember } from "../lib/types";
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
export function designDisplay(steel: SteelDesignResult | null): Display | null {
  if (!steel) return null;
  const values: Record<string, number[]> = {};
  for (const [id, m] of Object.entries(steel.members)) if (m.util != null) values[id] = [m.util, m.util];
  return { values, res: null, scale: { min: 0, max: 1, label: "Utilisation", unit: "–", limit: 1, note: steel.code_name } };
}

export const statusTag = (m: SteelMember) =>
  m.status === "ok" ? <span className="tag bg-emerald-500/15 text-emerald-300">OK</span>
    : m.status === "fail" ? <span className="tag bg-red-500/15 text-red-300">OVER 1.0</span>
      : m.status === "not_covered" ? <span className="tag bg-amber-500/15 text-amber-300">NOT COVERED</span>
        : <span className="tag bg-ink-700 text-ink-300">NOT STEEL</span>;

export function fmtCheck(c: SteelCheck, u: UnitsApi) {
  if (c.unit === "ratio") return { d: c.demand.toFixed(3), cap: "1.000", unit: "" };
  return { d: u.f(c.unit, Math.abs(c.demand)), cap: u.f(c.unit, c.capacity), unit: u.u(c.unit) };
}

/** Steel member design: code choice, summary, worst members. */
export function DesignPanel({ model }: { model: Model }) {
  const s = useStore();
  const u = useU();
  const { steel, steelBusy, steelError, steelCode, set } = s;
  const worst = steel ? Object.values(steel.members).filter((m) => m.util != null).sort((a, b) => b.util! - a.util!).slice(0, 12) : [];
  const nc = steel ? Object.values(steel.members).filter((m) => m.status === "not_covered") : [];
  const std = model.settings.standard;
  return (
    <div className="absolute z-20 right-2 top-12 bottom-2 w-[290px] overflow-y-auto rounded-md border border-ink-700 bg-ink-900/92 p-2.5 text-[11px] backdrop-blur">
      <div className="panel-title mb-1">Steel member design</div>
      <select className="input mb-1.5" value={steelCode} onChange={(e) => set({ steelCode: e.target.value, steel: null })}>
        {CODE_OPTIONS.map(([k, label]) => <option key={k} value={k}>{k ? label : `${label} (${std === "ASCE7" ? "AISC 360" : std === "TH" ? "Thai EIT" : "EN 1993"})`}</option>)}
      </select>
      <button className="btn-primary w-full mb-2" disabled={steelBusy} onClick={() => s.runSteel()}>{steelBusy ? "Checking…" : "Check steel members"}</button>
      {steelError && <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{steelError}</div>}
      {!steel && !steelBusy && <div className="text-ink-400">Checks every steel member for all ultimate (ULS) combinations of the model, from a fresh linear analysis. Concrete members are left for RC design.</div>}

      {steel && (
        <>
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-ink-200">{steel.code_name}</span>
            <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>
          </div>
          <div className="text-ink-400 mb-1.5">Combinations: <span className="font-mono text-ink-300">{steel.combinations.join(", ")}</span></div>
          <div className="grid grid-cols-4 gap-1 mb-2 text-center">
            {([["OK", steel.summary.ok, "text-emerald-300"], ["Over 1.0", steel.summary.fail, "text-red-300"], ["Not covered", steel.summary.not_covered, "text-amber-300"], ["Max", steel.summary.max_util != null ? steel.summary.max_util.toFixed(2) : "–", steel.summary.max_util != null && steel.summary.max_util > 1 ? "text-red-300" : "text-ink-100"]] as [string, number | string, string][]).map(([k, v, c]) => (
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
          <div className="text-ink-400">Click a member for every check, the clause, the governing combination and its design settings ({u.u("length")}).</div>
          <ul className="mt-1.5 list-disc pl-4 space-y-0.5 text-ink-500">{steel.notes.map((n, k) => <li key={k}>{n}</li>)}</ul>
        </>
      )}
      <div className="mt-2 border-t border-ink-800 pt-1.5 text-ink-500">
        A utilisation at or below 1.0 means the member passes the checks listed for it. It is not a statement that the
        structure is safe: connections, stability of the whole structure and the items in the notes must be checked separately.
      </div>
    </div>
  );
}
