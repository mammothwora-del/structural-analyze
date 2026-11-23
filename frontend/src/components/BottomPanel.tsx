import { useEffect, useRef, useState } from "react";
import { combinedResult } from "../lib/combine";
import { fmt } from "../lib/display";
import { useStore, useU } from "../store";

const TABS = [["log", "Analysis log"], ["warnings", "Warnings"], ["cases", "Load cases"], ["combos", "Combinations"], ["reactions", "Reactions"], ["members", "Member results"]] as const;

export function BottomPanel() {
  const { bottomTab, set, results } = useStore();
  const nWarn = results?.warnings.filter((w) => w.level !== "info").length ?? 0;
  return (
    <div className="h-[200px] shrink-0 border-t border-ink-800 bg-ink-900 flex flex-col min-h-0">
      <div className="flex border-b border-ink-800 px-2">
        {TABS.map(([k, l]) => (
          <button key={k} onClick={() => set({ bottomTab: k })} className={`px-3 py-1.5 text-[11px] ${bottomTab === k ? "text-accent border-b-2 border-accent" : "text-ink-400 hover:text-ink-200"}`}>
            {l}{k === "warnings" && nWarn > 0 && <span className="ml-1 tag bg-amber-500/20 text-amber-300">{nWarn}</span>}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-auto px-3 py-2 text-[11.5px]">
        {bottomTab === "log" && <Log />}
        {bottomTab === "warnings" && <Warnings />}
        {bottomTab === "cases" && <Cases />}
        {bottomTab === "combos" && <Combos />}
        {bottomTab === "reactions" && <Reactions />}
        {bottomTab === "members" && <Members />}
      </div>
    </div>
  );
}

function Log() {
  const log = useStore((s) => s.log);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [log.length]);
  return (
    <div className="font-mono text-[11px] leading-relaxed">
      {log.length === 0 && <div className="text-ink-400">No messages yet.</div>}
      {log.map((l, k) => <div key={k} className={l.includes("ERROR") || l.includes("FAILED") ? "text-red-300" : l.includes("WARNING") ? "text-amber-300" : l.includes("EQUILIBRIUM OK") ? "text-emerald-300" : "text-ink-300"}>{l}</div>)}
      <div ref={end} />
    </div>
  );
}

function Warnings() {
  const { results } = useStore();
  if (!results) return <div className="text-ink-400">Run the analysis to see stability and model warnings.</div>;
  if (!results.warnings.length) return <div className="text-emerald-300">No warnings. Structure is stable, connected and supported; equilibrium satisfied for all load cases.</div>;
  return (
    <div className="space-y-1">
      {results.warnings.map((w, k) => (
        <div key={k} className={`rounded px-2 py-1 border ${w.level === "error" ? "border-red-500/40 bg-red-500/10 text-red-200" : w.level === "warning" ? "border-amber-500/40 bg-amber-500/10 text-amber-200" : "border-ink-700 text-ink-300"}`}>
          <b className="uppercase mr-2">{w.level}</b>{w.case && <span className="mr-2">[{w.case}]</span>}{w.message}
          {w.nodes && <span className="text-ink-400"> — nodes: {w.nodes.slice(0, 12).join(", ")}</span>}
        </div>
      ))}
    </div>
  );
}

function Cases() {
  const u = useU();
  const { model, results, set, loadSel, editModel } = useStore();
  if (!model) return null;
  return (
    <table className="w-full">
      <thead className="text-ink-400 text-left"><tr><th className="font-medium">ID</th><th className="font-medium">Name</th><th className="font-medium">Type</th><th className="font-medium">Self-wt</th><th className="font-medium">Loads</th><th className="text-right font-medium">ΣFx</th><th className="text-right font-medium">ΣFz ({u.u("force")})</th><th className="text-right font-medium">Equilibrium</th></tr></thead>
      <tbody>
        {model.load_cases.map((c) => {
          const r = results?.cases[c.id];
          return (
            <tr key={c.id} onClick={() => set({ loadSel: c.id })} className={`cursor-pointer border-t border-ink-800 ${loadSel === c.id ? "bg-accent/10" : "hover:bg-ink-800"}`}>
              <td className="font-mono">{c.id}</td><td>{c.name}</td><td>{c.type}</td>
              <td><input type="checkbox" checked={!!c.self_weight} onChange={(e) => { e.stopPropagation(); editModel((m) => { m.load_cases.find((x) => x.id === c.id)!.self_weight = e.target.checked; }); }} /></td>
              <td className="num">{model.loads.filter((l) => l.case === c.id).length}</td>
              <td className="text-right num">{r ? u.f("force", r.equilibrium.applied[0], 1) : "–"}</td>
              <td className="text-right num">{r ? u.f("force", r.equilibrium.applied[2], 1) : "–"}</td>
              <td className="text-right">{r ? (r.equilibrium.ok ? <span className="text-emerald-300">OK ({r.equilibrium.force_error.toExponential(1)} kN)</span> : <span className="text-red-300">FAILED</span>) : "–"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Combos() {
  const { model, set, loadSel, editModel } = useStore();
  const [txt, setTxt] = useState("");
  if (!model) return null;
  const cases = model.load_cases.map((c) => c.id);
  return (
    <div>
      <table className="w-full">
        <thead className="text-ink-400 text-left"><tr><th className="font-medium">ID</th><th className="font-medium">Name</th>{cases.map((c) => <th key={c} className="text-right font-medium font-mono">{c}</th>)}<th></th></tr></thead>
        <tbody>
          {model.combinations.map((c) => (
            <tr key={c.id} onClick={() => set({ loadSel: c.id })} className={`cursor-pointer border-t border-ink-800 ${loadSel === c.id ? "bg-accent/10" : "hover:bg-ink-800"}`}>
              <td className="font-mono">{c.id}</td><td>{c.name}</td>
              {cases.map((k) => (
                <td key={k} className="text-right">
                  <input className="input !w-14 text-right num" type="number" step={0.05} value={c.factors[k] ?? 0} onClick={(e) => e.stopPropagation()}
                    onChange={(e) => editModel((m) => { const cc = m.combinations.find((x) => x.id === c.id)!; const v = +e.target.value; if (v) cc.factors[k] = v; else delete cc.factors[k]; })} />
                </td>
              ))}
              <td className="text-right"><button className="text-red-300 px-1" onClick={(e) => { e.stopPropagation(); editModel((m) => { m.combinations = m.combinations.filter((x) => x.id !== c.id); }); }}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex gap-1 items-center">
        <input className="input !w-40" placeholder="New combination id" value={txt} onChange={(e) => setTxt(e.target.value)} />
        <button className="btn" disabled={!txt || model.combinations.some((c) => c.id === txt) || cases.includes(txt)} onClick={() => { editModel((m) => { m.combinations.push({ id: txt, name: txt, factors: { DL: 1 } }); }); setTxt(""); }}>Add</button>
        <span className="text-ink-400 ml-2">Combinations are evaluated by exact linear superposition of the case results.</span>
      </div>
    </div>
  );
}

function Reactions() {
  const u = useU();
  const { model, results, loadSel, set } = useStore();
  if (!model || !results) return <div className="text-ink-400">Run the analysis first.</div>;
  const res = combinedResult(model, results, loadSel);
  if (!res) return null;
  const rows = Object.entries(res.reactions);
  const sum = [0, 1, 2, 3, 4, 5].map((k) => rows.reduce((s, [, r]) => s + r[k], 0));
  return (
    <table className="w-full num">
      <thead className="text-ink-400"><tr><th className="text-left font-medium">Support ({loadSel})</th>{["Rx", "Ry", `Rz (${u.u("force")})`, "Mx", "My", `Mz (${u.u("moment")})`].map((h) => <th key={h} className="text-right font-medium">{h}</th>)}</tr></thead>
      <tbody>
        {rows.map(([n, r]) => (
          <tr key={n} className="border-t border-ink-800 hover:bg-ink-800 cursor-pointer" onClick={() => set({ selection: { kind: "node", id: n } })}>
            <td>{n} {model.nodes.find((x) => x.id === n)?.grid}</td>{r.map((v, k) => <td key={k} className="text-right">{u.f(k < 3 ? "force" : "moment", v)}</td>)}
          </tr>
        ))}
        <tr className="border-t-2 border-ink-600 font-semibold"><td>Σ reactions</td>{sum.map((v, k) => <td key={k} className="text-right">{k < 3 ? u.f("force", v) : ""}</td>)}</tr>
        <tr className="text-ink-400"><td>Σ applied</td>{res.equilibrium.applied.map((v, k) => <td key={k} className="text-right">{k < 3 ? u.f("force", v) : ""}</td>)}</tr>
      </tbody>
    </table>
  );
}

function Members() {
  const u = useU();
  const { model, results, loadSel, set } = useStore();
  const [sort, setSort] = useState<"N" | "V" | "M" | "id">("M");
  if (!model || !results) return <div className="text-ink-400">Run the analysis first.</div>;
  const res = combinedResult(model, results, loadSel);
  if (!res) return null;
  const rows = model.elements.map((e) => {
    const st = res.elements[e.id];
    const mx = (a: number[]) => a.reduce((m, v) => (Math.abs(v) > Math.abs(m) ? v : m), 0);
    return { e, N: mx(st.N), V: Math.max(Math.abs(mx(st.Vy)), Math.abs(mx(st.Vz))), M: Math.max(Math.abs(mx(st.My)), Math.abs(mx(st.Mz))), T: mx(st.T),
      s: Math.max(...st.sigma_max.map(Math.abs), ...st.sigma_min.map(Math.abs)) / 1000, u: Math.max(...st.disp.map((d) => Math.hypot(d[0], d[1], d[2]))) * 1000 };
  }).sort((a, b) => (sort === "id" ? 0 : Math.abs(b[sort]) - Math.abs(a[sort])));
  return (
    <table className="w-full num">
      <thead className="text-ink-400"><tr>
        <th className="text-left font-medium cursor-pointer" onClick={() => setSort("id")}>Member</th><th className="text-left font-medium">Type</th>
        <th className="text-right font-medium cursor-pointer" onClick={() => setSort("N")}>N max ({u.u("force")})</th>
        <th className="text-right font-medium cursor-pointer" onClick={() => setSort("V")}>V max ({u.u("force")})</th>
        <th className="text-right font-medium cursor-pointer" onClick={() => setSort("M")}>M max ({u.u("moment")})</th>
        <th className="text-right font-medium">T ({u.u("moment")})</th><th className="text-right font-medium">|σ| max ({u.u("stress")})</th><th className="text-right font-medium">|u| max ({u.u("disp")})</th>
      </tr></thead>
      <tbody>
        {rows.slice(0, 300).map((r) => (
          <tr key={r.e.id} className="border-t border-ink-800 hover:bg-ink-800 cursor-pointer" onClick={() => set({ selection: { kind: "element", id: r.e.id } })}>
            <td>{r.e.id}</td><td className="font-sans text-ink-400">{r.e.label}</td>
            <td className="text-right">{u.f("force", r.N)}</td><td className="text-right">{u.f("force", r.V)}</td><td className="text-right">{u.f("moment", r.M)}</td>
            <td className="text-right">{u.f("moment", r.T)}</td><td className="text-right">{u.f("stress", r.s)}</td><td className="text-right">{u.f("disp", r.u / 1000)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
