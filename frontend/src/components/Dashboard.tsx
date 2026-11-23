import { useMemo } from "react";
import { combinedResult } from "../lib/combine";
import { cssColorAt } from "../lib/colormap";
import { fmt, stressLimit } from "../lib/display";
import { useStore } from "../store";

const Card = ({ title, value, unit, sub, tone }: { title: string; value: string; unit?: string; sub?: React.ReactNode; tone?: "ok" | "bad" }) => (
  <div className="rounded-lg border border-ink-700 bg-ink-850 p-3">
    <div className="panel-title">{title}</div>
    <div className={`mt-1 text-2xl font-semibold num ${tone === "ok" ? "text-emerald-300" : tone === "bad" ? "text-red-300" : "text-ink-200"}`}>{value}<span className="text-sm text-ink-400 font-normal"> {unit}</span></div>
    {sub && <div className="text-[11px] text-ink-400 mt-0.5">{sub}</div>}
  </div>
);

function HBar({ rows, unit, color }: { rows: { label: string; value: number; t?: number }[]; unit: string; color?: string }) {
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-[11px]">
          <span className="w-20 shrink-0 text-ink-400 truncate">{r.label}</span>
          <div className="flex-1 h-4 bg-ink-800 rounded-sm overflow-hidden">
            <div className="h-full rounded-sm" style={{ width: `${(Math.abs(r.value) / max) * 100}%`, background: color ?? cssColorAt(r.t ?? Math.abs(r.value) / max) }} />
          </div>
          <span className="w-24 text-right num text-ink-200">{fmt(r.value, 1)} {unit}</span>
        </div>
      ))}
    </div>
  );
}

export function Dashboard() {
  const { model, results, loadSel, set, resultsStale } = useStore();
  const data = useMemo(() => {
    if (!model || !results) return null;
    const res = combinedResult(model, results, loadSel)!;
    const caseTotal = (id: string) => (results.cases[id] ? -results.cases[id].equilibrium.applied[2] : 0);
    let maxU = { v: 0, n: "" };
    for (const [n, d] of Object.entries(res.displacements)) { const u = Math.hypot(d[0], d[1], d[2]); if (u > maxU.v) maxU = { v: u, n }; }
    const ext = (k: "N" | "Vz" | "Vy" | "My" | "Mz") => {
      let best = { v: 0, id: "" };
      for (const [id, st] of Object.entries(res.elements)) for (const v of st[k]) if (Math.abs(v) > Math.abs(best.v)) best = { v, id };
      return best;
    };
    const M = [ext("My"), ext("Mz")].sort((a, b) => Math.abs(b.v) - Math.abs(a.v))[0];
    const V = [ext("Vz"), ext("Vy")].sort((a, b) => Math.abs(b.v) - Math.abs(a.v))[0];
    const N = ext("N");
    const crit = Object.entries(res.elements).map(([id, st]) => ({ id, r: Math.max(...st.sigma_max.map(Math.abs), ...st.sigma_min.map(Math.abs)) / stressLimit(model, results, id) }))
      .sort((a, b) => b.r - a.r).slice(0, 10);
    // storey load accumulation: sum of column axial force at the bottom of each storey
    const levels = Math.max(0, ...model.elements.map((e) => e.level ?? 0));
    const storey = Array.from({ length: levels }, (_, k) => k + 1).reverse().map((lv) => {
      const cols = model.elements.filter((e) => e.type === "column" && e.level === lv);
      const s = cols.reduce((acc, e) => acc + -(res.elements[e.id]?.N[0] ?? 0), 0);
      return { label: `Storey ${lv}`, value: s };
    });
    const reactions = Object.entries(res.reactions).map(([n, r]) => ({ label: `${n} ${model.nodes.find((x) => x.id === n)?.grid ?? ""}`, value: r[2] }));
    const sumR = Object.values(res.reactions).reduce((s, r) => s + r[2], 0);
    const slabSW = model.slabs.reduce((s, sl) => {
      const t = results.tributary[sl.id];
      return s + (t ? t.area * sl.thickness * 25 : 0);
    }, 0);
    const frameSW = Object.entries(results.elements).reduce((s, [, i]) => s + i.props.A * (model.materials[i.material]?.density ?? 0) * i.L, 0);
    const eq = [...model.load_cases.map((c) => ({ id: c.id, eq: results.cases[c.id]?.equilibrium })),
      ...model.combinations.map((c) => ({ id: c.id, eq: combinedResult(model, results, c.id)?.equilibrium }))];
    return { res, caseTotal, maxU, M, V, N, crit, storey, reactions, sumR, slabSW, frameSW, eq };
  }, [model, results, loadSel]);

  if (!model) return null;
  if (!data) return <div className="flex-1 grid place-items-center text-ink-400">Run ANALYZE to populate the dashboard.</div>;
  const eqOk = data.eq.every((e) => e.eq?.ok);
  const goto = (id: string) => set({ selection: { kind: "element", id }, view: "3d" });
  return (
    <div className="flex-1 overflow-y-auto p-4 bg-ink-950">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div className="text-lg font-semibold">Engineering dashboard</div>
          <div className="text-ink-400 text-xs">Results for <b className="text-ink-200">{loadSel}</b> · {results!.solver.type} · {results!.solver.ndof} DOF · solved in {fmt(results!.solver.time_ms, 0)} ms {resultsStale && <span className="text-amber-300">· model changed since analysis</span>}</div>
        </div>
        <span className="tag bg-amber-500/15 text-amber-300">No design code checks implemented — no safety or compliance claim</span>
      </div>
      <div className="grid grid-cols-5 gap-3">
        <Card title="Total dead load (DL)" value={fmt(data.caseTotal("DL"), 0)} unit="kN" sub="Members + slab self-weight" />
        <Card title="Superimposed dead (SDL)" value={fmt(data.caseTotal("SDL"), 0)} unit="kN" />
        <Card title="Total live load (LL)" value={fmt(data.caseTotal("LL"), 0)} unit="kN" />
        <Card title="Structural weight" value={fmt(data.frameSW + data.slabSW, 0)} unit="kN" sub={`Frame ${fmt(data.frameSW, 0)} + slabs ${fmt(data.slabSW, 0)} kN (footings excl.)`} />
        <Card title={`Σ support reactions Rz (${loadSel})`} value={fmt(data.sumR, 0)} unit="kN" sub={`Σ applied Fz ${fmt(data.res.equilibrium.applied[2], 1)} kN`} />
        <Card title="Max displacement" value={fmt(data.maxU.v * 1000, 2)} unit="mm" sub={<>at node {data.maxU.n}</>} />
        <Card title="Max bending moment" value={fmt(Math.abs(data.M.v), 1)} unit="kN·m" sub={<button className="text-accent" onClick={() => goto(data.M.id)}>{data.M.id}</button>} />
        <Card title="Max axial force" value={fmt(data.N.v, 1)} unit="kN" sub={<>{data.N.v < 0 ? "compression" : "tension"} · <button className="text-accent" onClick={() => goto(data.N.id)}>{data.N.id}</button></>} />
        <Card title="Max shear force" value={fmt(Math.abs(data.V.v), 1)} unit="kN" sub={<button className="text-accent" onClick={() => goto(data.V.id)}>{data.V.id}</button>} />
        <Card title="Equilibrium status" value={eqOk ? "BALANCED" : "CHECK"} tone={eqOk ? "ok" : "bad"} sub={`${data.eq.length} cases/combos · max error ${Math.max(...data.eq.map((e) => e.eq?.force_error ?? 0)).toExponential(1)} kN`} />
      </div>
      <div className="grid grid-cols-3 gap-3 mt-3">
        <div className="rounded-lg border border-ink-700 bg-ink-850 p-3">
          <div className="panel-title mb-2">Load accumulation — Σ column axial per storey</div>
          <HBar rows={data.storey} unit="kN" />
          <div className="text-[10px] text-ink-400 mt-2">Compression at the bottom of each storey's columns. The roof-to-foundation build-up of the vertical load path.</div>
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-850 p-3">
          <div className="panel-title mb-2">Critical members — |σ| / user limit</div>
          <HBar rows={data.crit.map((c) => ({ label: c.id, value: c.r, t: Math.min(1, c.r) }))} unit="" />
          <div className="text-[10px] text-ink-400 mt-2">Elastic extreme-fibre stress vs. user-defined limit (settings). Not a design check.</div>
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-850 p-3 max-h-[340px] overflow-y-auto">
          <div className="panel-title mb-2">Support reactions Rz</div>
          <HBar rows={data.reactions} unit="kN" color="#3fb6ff" />
        </div>
      </div>
      <div className="rounded-lg border border-ink-700 bg-ink-850 p-3 mt-3">
        <div className="panel-title mb-2">Equilibrium check per case / combination (Σ applied + Σ reactions = 0)</div>
        <div className="grid grid-cols-4 gap-x-6 gap-y-1 text-[11px]">
          {data.eq.map((e) => (
            <div key={e.id} className="flex justify-between border-b border-ink-800 py-0.5">
              <span className="font-mono">{e.id}</span>
              <span className={e.eq?.ok ? "text-emerald-300" : "text-red-300"}>{e.eq ? `${e.eq.ok ? "OK" : "FAIL"} · ${e.eq.force_error.toExponential(1)} kN · ${e.eq.moment_error.toExponential(1)} kN·m` : "–"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
