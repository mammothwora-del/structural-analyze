import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { download } from "../lib/download";
import { safeName } from "../lib/project";
import type { BoqOptions, BoqResult, Model } from "../lib/types";
import { useStore } from "../store";

const kg = (v: number) => (v >= 10000 ? `${(v / 1000).toFixed(2)} t` : `${v.toFixed(0)} kg`);
const money = (v: number | null | undefined) => (v == null ? "–" : v.toLocaleString(undefined, { maximumFractionDigits: 0 }));

/** Steel mass and concrete volume per section, with optional prices; Excel export with live formulas. */
export function BoqDialog({ onDone }: { onDone: () => void }) {
  const s = useStore();
  const model = s.model as Model;
  const [o, setO] = useState<BoqOptions>(s.boqSettings);
  const [res, setRes] = useState<BoqResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    const t = setTimeout(async () => {
      try { const r = await api.boq(model, o); if (live) { setRes(r); setErr(null); } } catch (e) { if (live) setErr((e as Error).message); }
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [o, model]);
  const update = (p: Partial<BoqOptions>) => { const next = { ...o, ...p }; setO(next); s.set({ boqSettings: next }); };
  const setPrice = (k: string, v: string) => {
    const prices = { ...o.prices };
    if (v === "" || !(+v >= 0)) delete prices[k]; else prices[k] = +v;
    update({ prices });
  };
  const excel = async () => {
    setBusy(true);
    try {
      download(`${safeName(model.name)}-BOQ.xlsx`, await api.boqXlsx(model, o));
      s.set({ log: [...useStore.getState().log, `Quantities exported to Excel${res ? `: steel ${kg(res.totals.steel_mass)}${o.allowance ? ` (+${o.allowance}% allowance)` : ""}` : ""}.`] });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const steel = res?.rows.filter((r) => r.kind === "steel") ?? [];
  const conc = res?.rows.filter((r) => r.kind === "concrete") ?? [];
  const cur = o.currency || "";
  return (
    <>
      <div className="grid grid-cols-4 gap-2 mb-2">
        <label className="text-ink-400">Allowance (%)<input className="input mt-0.5" type="number" min={0} max={100} step={1} value={o.allowance} onChange={(e) => update({ allowance: Math.min(100, Math.max(0, +e.target.value || 0)) })} /></label>
        <label className="text-ink-400">Currency<input className="input mt-0.5" value={o.currency} maxLength={8} onChange={(e) => update({ currency: e.target.value })} /></label>
        <label className="text-ink-400">Steel price / kg<input className="input mt-0.5" type="number" min={0} step={0.5} placeholder="none" value={o.prices.steel ?? ""} onChange={(e) => setPrice("steel", e.target.value)} /></label>
        <label className="text-ink-400">Concrete / m³<input className="input mt-0.5" type="number" min={0} step={100} placeholder="none" value={o.concrete_price ?? ""} onChange={(e) => update({ concrete_price: e.target.value === "" ? null : Math.max(0, +e.target.value) })} /></label>
      </div>
      <div className="text-ink-500 mb-2">The allowance covers connections, plates, bolts and waste, which are not in the model. Prices are your own figures: nothing is assumed, so costs stay empty until you enter them. A price per family below replaces the steel price for that family.</div>
      {err && <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 p-1.5 text-red-200">{err}</div>}
      {res && (
        <>
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-ink-200">Steel {kg(res.totals.steel_mass)}{res.allowance ? `, ${kg(res.totals.steel_mass_total)} with allowance` : ""}{res.totals.concrete_volume ? ` · concrete ${res.totals.concrete_volume.toFixed(2)} m³` : ""}</span>
            <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>
          </div>
          {steel.length > 0 && (
            <table className="w-full mb-2">
              <thead><tr className="text-ink-500 text-[10px]"><th className="text-left font-normal">Section</th><th className="text-left font-normal">Size</th><th className="text-right font-normal">No.</th><th className="text-right font-normal">Length m</th><th className="text-right font-normal">kg/m</th><th className="text-right font-normal">{o.allowance ? `kg +${o.allowance}%` : "Mass kg"}</th><th className="text-right font-normal">Cost {cur}</th></tr></thead>
              <tbody>
                {steel.map((r) => (
                  <tr key={r.section} className="border-t border-ink-800" title={`kg/m from ${r.mass_source}; ${r.roles.join(", ")}`}>
                    <td className="font-mono text-ink-200">{r.section}</td><td className="text-ink-300">{r.description}</td>
                    <td className="num text-right text-ink-400">{r.n}</td><td className="num text-right text-ink-300">{r.length.toFixed(1)}</td>
                    <td className="num text-right text-ink-400">{r.kg_per_m.toFixed(2)}</td><td className="num text-right text-ink-200">{(r.mass_total ?? 0).toFixed(0)}</td>
                    <td className="num text-right text-ink-200">{money(r.cost)}</td>
                  </tr>
                ))}
                <tr className="border-t border-ink-600 font-semibold">
                  <td className="text-ink-200" colSpan={3}>Total steel</td><td className="num text-right">{res.totals.steel_length.toFixed(1)}</td><td />
                  <td className="num text-right">{res.totals.steel_mass_total.toFixed(0)}</td><td className="num text-right">{money(steel.every((r) => r.cost != null) ? steel.reduce((a, r) => a + (r.cost ?? 0), 0) : null)}</td>
                </tr>
              </tbody>
            </table>
          )}
          {res.families.length > 1 && (
            <div className="grid grid-cols-4 gap-1.5 mb-2">
              {res.families.map((f) => (
                <label key={f.family} className="text-ink-400">{f.family} ({kg(f.mass_total)}) / kg
                  <input className="input mt-0.5 !py-0" type="number" min={0} step={0.5} placeholder={o.prices.steel != null ? String(o.prices.steel) : "none"} value={o.prices[f.family] ?? ""} onChange={(e) => setPrice(f.family, e.target.value)} />
                </label>
              ))}
            </div>
          )}
          {conc.length > 0 && (
            <table className="w-full mb-2">
              <thead><tr className="text-ink-500 text-[10px]"><th className="text-left font-normal">Concrete</th><th className="text-left font-normal">Section</th><th className="text-right font-normal">No.</th><th className="text-right font-normal">Length m</th><th className="text-right font-normal">Volume m³</th><th className="text-right font-normal">Cost {cur}</th></tr></thead>
              <tbody>
                {conc.map((r) => (
                  <tr key={r.section} className="border-t border-ink-800">
                    <td className="font-mono text-ink-200">{r.section}</td><td className="text-ink-300">{r.description}</td><td className="num text-right text-ink-400">{r.n}</td>
                    <td className="num text-right text-ink-300">{r.length.toFixed(1)}</td><td className="num text-right text-ink-200">{(r.volume ?? 0).toFixed(2)}</td><td className="num text-right text-ink-200">{money(r.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {res.by_type.length > 0 && <div className="text-ink-400 mb-2">By member type: {res.by_type.map((t) => `${t.role} ${kg(t.mass)}`).join(" · ")}</div>}
          {res.totals.cost != null && <div className="text-ink-200 mb-2">Total cost: <b>{money(res.totals.cost)} {cur}</b>{!res.totals.complete && <span className="text-amber-300"> (some sections have no price)</span>}</div>}
          <ul className="list-disc pl-4 space-y-0.5 text-ink-500 mb-2">{res.notes.map((n, k) => <li key={k}>{n}</li>)}</ul>
        </>
      )}
      <div className="flex gap-2">
        <button className="btn flex-1" onClick={onDone}>Close</button>
        <button className="btn-primary flex-1" disabled={!res || busy} onClick={excel}>{busy ? "Preparing…" : "Download Excel (.xlsx)"}</button>
      </div>
    </>
  );
}
