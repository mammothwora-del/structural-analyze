import { useMemo, useState } from "react";
import { combinedResult, factorsFor } from "../lib/combine";
import { COMP_LABEL, fmt, stressLimit, UNITS } from "../lib/display";
import { footingPressure } from "../lib/footing";
import { computeFlows, elementTransfers, trace } from "../lib/loadpath";
import type { ForceComp, Load, Model, Results, Stations } from "../lib/types";
import { useStore } from "../store";

const Row = ({ k, v, unit }: { k: React.ReactNode; v: React.ReactNode; unit?: string }) => (
  <div className="flex justify-between gap-2 py-0.5 border-b border-ink-800/80">
    <span className="text-ink-400">{k}</span>
    <span className="num text-ink-200 text-right">{v}{unit && <span className="text-ink-400"> {unit}</span>}</span>
  </div>
);
const Section = ({ title, children, tag }: { title: string; children: React.ReactNode; tag?: React.ReactNode }) => (
  <div className="mt-3">
    <div className="flex items-center justify-between mb-1"><div className="panel-title">{title}</div>{tag}</div>
    {children}
  </div>
);
const Calc = () => <span className="tag bg-emerald-500/15 text-emerald-300">CALCULATED</span>;
const Assumed = ({ t = "ASSUMED" }: { t?: string }) => <span className="tag bg-amber-500/15 text-amber-300">{t}</span>;

export function Inspector() {
  const { model, results, selection, multi, resultsStale } = useStore();
  if (!model) return null;
  const usable = results && !resultsStale ? results : null;
  return (
    <aside className="w-[330px] shrink-0 border-l border-ink-800 bg-ink-900 overflow-y-auto p-3">
      {multi.length > 1 ? <MultiPanel model={model} /> :
        selection?.kind === "element" ? <ElementPanel model={model} results={usable} id={selection.id} /> :
        selection?.kind === "node" ? <NodePanel model={model} results={usable} id={selection.id} /> :
        selection?.kind === "slab" ? <SlabPanel model={model} results={usable} id={selection.id} /> :
        <EmptyPanel />}
    </aside>
  );
}

function EmptyPanel() {
  return (
    <div className="text-ink-400 text-xs leading-relaxed">
      <div className="panel-title mb-2">Properties & Results</div>
      <p>Click a member, node or slab in the 3D view to inspect it. Shift/Ctrl-click to multi-select members (or nodes, to add a member between two nodes).</p>
      <p className="mt-2">Keyboard: <span className="num">1–7</span> switch modes, <span className="num">Del</span> deletes the selected member, <span className="num">Ctrl+Z</span> undo, <span className="num">F5</span> analyze.</p>
    </div>
  );
}

function maxAbs(a: number[]) { let m = 0, k = 0; a.forEach((v, i) => { if (Math.abs(v) > Math.abs(m)) { m = v; k = i; } }); return { v: m, k }; }

function MiniDiagram({ st, comp }: { st: Stations; comp: ForceComp }) {
  const W = 300, H = 90, pad = 8;
  const L = st.x[st.x.length - 1];
  const vals = st[comp];
  const m = Math.max(1e-9, ...vals.map(Math.abs));
  const X = (x: number) => pad + (x / L) * (W - 2 * pad);
  const Y = (v: number) => H / 2 - (v / m) * (H / 2 - pad);
  const path = `M${X(0)},${H / 2} ` + st.x.map((x, k) => `L${X(x)},${Y(vals[k])}`).join(" ") + ` L${X(L)},${H / 2} Z`;
  const ext = maxAbs(vals);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded bg-ink-950 border border-ink-800">
      <line x1={pad} x2={W - pad} y1={H / 2} y2={H / 2} stroke="#33445a" />
      <path d={path} fill="rgba(63,182,255,0.25)" stroke="#3fb6ff" strokeWidth={1.4} />
      <text x={X(st.x[ext.k])} y={Y(ext.v) + (ext.v >= 0 ? -3 : 11)} fill="#d3dce6" fontSize={10} textAnchor="middle" fontFamily="JetBrains Mono">{fmt(ext.v, 1)}</text>
      <text x={pad} y={H - 2} fill="#7f93ab" fontSize={9}>i</text>
      <text x={W - pad - 4} y={H - 2} fill="#7f93ab" fontSize={9}>j</text>
    </svg>
  );
}

function ElementPanel({ model, results, id }: { model: Model; results: Results | null; id: string }) {
  const { loadSel, set, editModel, pathDir } = useStore();
  const [comp, setComp] = useState<ForceComp>("My");
  const el = model.elements.find((e) => e.id === id);
  const res = results ? combinedResult(model, results, loadSel) : null;
  const flows = useMemo(() => (results ? computeFlows(model, results, loadSel, pathDir) : null), [model, results, loadSel, pathDir]);
  if (!el) return null;
  const sec = model.sections[el.section];
  const info = results?.elements[id];
  const st = res?.elements[id];
  const connected = model.elements.filter((e) => e.id !== id && [e.i, e.j].some((n) => n === el.i || n === el.j));
  const tr = flows ? elementTransfers(model, flows, id) : null;
  const factors = factorsFor(model, loadSel);
  const mloads = (results?.member_loads[id] ?? []).filter((l) => l.case in factors);
  const loadTotal = (l: Load) => {
    if (l.kind === "point") return (l.P ?? 0) * factors[l.case];
    const p = l.points ?? [];
    let s = 0; for (let k = 1; k < p.length; k++) s += 0.5 * (p[k][1] + p[k - 1][1]) * (p[k][0] - p[k - 1][0]);
    return s * factors[l.case] * (l.relative && info ? info.L : 1);
  };
  const bySource: Record<string, number> = {};
  for (const l of mloads) { const k = l.source ? `${l.source.type === "slab_self_weight" ? "Slab self-weight" : "Area load"} (${l.case}) from ${l.source.slab}` : `${l.kind === "point" ? "Point" : "Line"} load ${l.case}`; bySource[k] = (bySource[k] ?? 0) + loadTotal(l); }
  const sw = model.load_cases.find((c) => c.self_weight && c.id in factors);
  const supports = [el.i, el.j].map((n) => model.supports.find((s) => s.node === n)).filter(Boolean);
  const lim = results ? stressLimit(model, results, id) : 1;

  return (
    <div>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-lg font-semibold text-ink-200">{el.id}</div>
          <div className="text-ink-400 text-xs">{el.label}</div>
        </div>
        <span className="tag bg-ink-700 text-ink-200 uppercase">{el.type}{el.role && el.type === "beam" ? ` · ${el.role}` : ""}</span>
      </div>
      <Section title="Properties">
        <Row k="Material" v={model.materials[sec?.material]?.name ?? sec?.material} />
        <div className="flex justify-between gap-2 py-0.5 border-b border-ink-800/80">
          <span className="text-ink-400">Section</span>
          <select className="input !w-40" value={el.section} onChange={(e) => editModel((m) => { m.elements.find((x) => x.id === id)!.section = e.target.value; })}>
            {Object.entries(model.sections).map(([k, s]) => <option key={k} value={k}>{k} – {s.name}</option>)}
          </select>
        </div>
        <Row k="Nodes" v={`${el.i} → ${el.j}`} />
        {info && <>
          <Row k="Length" v={fmt(info.L, 3)} unit="m" />
          <Row k="b × h" v={`${fmt(info.props.b * 1000, 0)} × ${fmt(info.props.h * 1000, 0)}`} unit="mm" />
          <Row k="A" v={fmt(info.props.A * 1e4, 1)} unit="cm²" />
          <Row k="Iy (major) / Iz" v={`${fmt(info.props.Iy * 1e8, 0)} / ${fmt(info.props.Iz * 1e8, 0)}`} unit="cm⁴" />
          <Row k="E" v={fmt(info.E / 1000, 0)} unit="MPa" />
        </>}
        <Row k="Supports at ends" v={supports.length ? supports.map((s) => `${s!.node} (${s!.type})`).join(", ") : "none"} />
      </Section>

      {!results && <div className="mt-4 text-xs text-ink-400">Run ANALYZE to see internal forces, stresses, displacements and load transfer.</div>}

      {results && st && info && (
        <>
          <Section title={`Applied loads (${loadSel})`}>
            {sw && <Row k={`Self-weight (${sw.id} × ${factors[sw.id]})`} v={fmt(-info.props.A * model.materials[info.material].density * info.L * factors[sw.id], 2)} unit="kN" />}
            {Object.entries(bySource).map(([k, v]) => <Row key={k} k={k} v={fmt(v, 2)} unit="kN" />)}
            {!sw && !Object.keys(bySource).length && <div className="text-ink-400 text-xs">No member loads in this case.</div>}
          </Section>

          <Section title="Internal forces (extremes)" tag={<Calc />}>
            <div className="grid grid-cols-6 gap-0.5 mb-1">
              {(["N", "Vy", "Vz", "T", "My", "Mz"] as ForceComp[]).map((c) => (
                <button key={c} onClick={() => setComp(c)} className={`rounded px-1 py-0.5 text-[11px] font-mono ${comp === c ? "bg-accent text-ink-950" : "bg-ink-800 text-ink-300"}`}>{c}</button>
              ))}
            </div>
            <MiniDiagram st={st} comp={comp} />
            <div className="text-[10px] text-ink-400 mt-0.5">{COMP_LABEL[comp]} [{UNITS[comp]}] along member, i → j</div>
            {(["N", "Vy", "Vz", "T", "My", "Mz"] as ForceComp[]).map((c) => {
              const m = maxAbs(st[c]);
              return <Row key={c} k={`${c} max |·| (at x=${fmt(st.x[m.k], 2)} m)`} v={fmt(m.v, 2)} unit={UNITS[c]} />;
            })}
          </Section>

          <Section title="Stress & displacement" tag={<Calc />}>
            <Row k="σ max (tension +)" v={fmt(Math.max(...st.sigma_max) / 1000, 2)} unit="MPa" />
            <Row k="σ min" v={fmt(Math.min(...st.sigma_min) / 1000, 2)} unit="MPa" />
            <Row k="|σ| / user limit" v={fmt(Math.max(...st.sigma_max.map(Math.abs), ...st.sigma_min.map(Math.abs)) / lim, 3)} />
            <Row k="Max displacement |u|" v={fmt(Math.max(...st.disp.map((d) => Math.hypot(d[0], d[1], d[2]))) * 1000, 2)} unit="mm" />
            <Row k="Design utilisation" v={<span className="text-amber-300">not implemented</span>} />
          </Section>

          {flows && tr && (
            <Section title="Load transfer along d" tag={<Calc />}>
              <Row k="Load carried (max |flow|)" v={fmt(flows.through[id], 2)} unit="kN" />
              <Row k="Applied directly on member" v={fmt(tr.memberLoad, 2)} unit="kN" />
              <Row k={`End i (${el.i}) ${flows.ti[id] >= 0 ? "delivers" : "receives"}`} v={fmt(Math.abs(flows.ti[id]), 2)} unit="kN" />
              <Row k={`End j (${el.j}) ${flows.tj[id] >= 0 ? "delivers" : "receives"}`} v={fmt(Math.abs(flows.tj[id]), 2)} unit="kN" />
              <div className="mt-2 text-ink-300 text-xs font-medium">Incoming <Assumed t="PROPORTIONAL SHARE" /></div>
              {tr.incoming.length ? tr.incoming.sort((a, b) => b.value - a.value).slice(0, 8).map((x, k) => (
                <Row key={k} k={<button className="text-accent hover:underline" onClick={() => x.kind === "element" && set({ selection: { kind: "element", id: x.from } })}>{x.from}</button>} v={`${fmt(x.value, 2)} via ${x.via}`} unit="kN" />
              )) : <div className="text-ink-400 text-xs">{tr.memberLoad > 0 ? "Load is applied directly on this member (see above)." : "—"}</div>}
              <div className="mt-2 text-ink-300 text-xs font-medium">Outgoing</div>
              {tr.outgoing.length ? tr.outgoing.sort((a, b) => b.value - a.value).slice(0, 8).map((x, k) => (
                <Row key={k} k={<button className="text-accent hover:underline" onClick={() => x.kind === "element" && set({ selection: { kind: "element", id: x.to } })}>{x.to.replace("support@", "Support ")}</button>} v={`${fmt(x.value, 2)} via ${x.via}`} unit="kN" />
              )) : <div className="text-ink-400 text-xs">—</div>}
              <div className="mt-2 flex gap-1.5">
                <button className="btn" onClick={() => set({ trace: trace(model, flows, id, "down"), mode: "loadpath" })}>Trace down ↓</button>
                <button className="btn" onClick={() => set({ trace: trace(model, flows, id, "up"), mode: "loadpath" })}>Trace up ↑</button>
                <button className="btn" onClick={() => { const t = useStore.getState().trace ?? trace(model, flows, id, "down"); set({ isolated: Object.keys(t.elements) }); }}>Isolate path</button>
              </div>
            </Section>
          )}

          <Section title="End forces (local, node on member)" tag={<Calc />}>
            <table className="w-full text-[11px] num">
              <thead><tr className="text-ink-400"><td></td>{["Fx", "Fy", "Fz", "Mx", "My", "Mz"].map((h) => <td key={h} className="text-right">{h}</td>)}</tr></thead>
              <tbody>
                {[["i", st.end_i], ["j", st.end_j]].map(([n, v]) => (
                  <tr key={n as string}><td className="text-ink-400">{n as string}</td>{(v as number[]).map((x, k) => <td key={k} className="text-right">{fmt(x, 1)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </Section>
        </>
      )}

      <Section title={`Connected elements (${connected.length})`}>
        <div className="flex flex-wrap gap-1">
          {connected.map((c) => <button key={c.id} className="tag bg-ink-800 text-ink-200 hover:bg-ink-700" onClick={() => set({ selection: { kind: "element", id: c.id } })}>{c.id}</button>)}
        </div>
      </Section>
      <AddMemberLoad ids={[id]} />
      <div className="mt-4 flex gap-1.5">
        <button className="btn" onClick={() => set({ isolated: [id, ...connected.map((c) => c.id)] })}>Isolate</button>
        <button className="btn text-red-300" onClick={() => { editModel((m) => { m.elements = m.elements.filter((e) => e.id !== id); m.loads = m.loads.filter((l) => l.element !== id); }); set({ selection: null }); }}>Delete</button>
      </div>
    </div>
  );
}

function AddMemberLoad({ ids }: { ids: string[] }) {
  const { model, addLoad, editModel } = useStore();
  const [c, setC] = useState(model!.load_cases.find((x) => !x.self_weight)?.id ?? model!.load_cases[0].id);
  const [w, setW] = useState(10);
  const [dir, setDir] = useState("-Z");
  const [kind, setKind] = useState<"dist" | "point">("dist");
  const dv: Record<string, number[]> = { "-Z": [0, 0, -1], "+X": [1, 0, 0], "+Y": [0, 1, 0], "-X": [-1, 0, 0], "-Y": [0, -1, 0] };
  return (
    <Section title={`Add load to ${ids.length > 1 ? ids.length + " members" : "member"}`}>
      <div className="grid grid-cols-2 gap-1">
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value as "dist" | "point")}><option value="dist">Uniform line load</option><option value="point">Point load @ midspan</option></select>
        <select className="input" value={c} onChange={(e) => setC(e.target.value)}>{model!.load_cases.map((x) => <option key={x.id} value={x.id}>{x.id}</option>)}</select>
        <input className="input" type="number" value={w} onChange={(e) => setW(+e.target.value)} />
        <select className="input" value={dir} onChange={(e) => setDir(e.target.value)}>{Object.keys(dv).map((d) => <option key={d}>{d}</option>)}</select>
      </div>
      <button className="btn mt-1" onClick={() => editModel((m) => {
        for (const id of ids) {
          if (kind === "dist") m.loads.push({ case: c, kind: "dist", element: id, direction: dv[dir], points: [[0, w], [1, w]], label: `UDL ${w} kN/m`, relative: true });
          else m.loads.push({ case: c, kind: "point", element: id, direction: dv[dir], a: 0.5, P: w, label: `Point ${w} kN`, relative: true });
        }
      })}>Add {kind === "dist" ? `${w} kN/m` : `${w} kN`}</button>
      <span className="hidden">{String(!!addLoad)}</span>
    </Section>
  );
}

function NodePanel({ model, results, id }: { model: Model; results: Results | null; id: string }) {
  const { loadSel, editModel, multi, set } = useStore();
  const n = model.nodes.find((x) => x.id === id)!;
  const sup = model.supports.find((s) => s.node === id);
  const res = results ? combinedResult(model, results, loadSel) : null;
  const d = res?.displacements[id];
  const r = res?.reactions[id];
  const dlf = factorsFor(model, loadSel)["DL"] ?? 0;
  const fp = r && sup?.footing ? footingPressure(r, sup.footing, 25 * sup.footing.B * sup.footing.L * sup.footing.t * dlf) : null;
  const [F, setF] = useState([0, 0, -50]);
  const [c, setC] = useState(model.load_cases.find((x) => !x.self_weight)?.id ?? "LL");
  return (
    <div>
      <div className="text-lg font-semibold">Node {id}</div>
      <div className="text-ink-400 text-xs">{n.grid ? `Grid ${n.grid}` : ""} {n.level !== undefined ? `· Level ${n.level}` : ""}</div>
      <Section title="Coordinates">
        <Row k="X, Y, Z" v={`${fmt(n.x, 3)}, ${fmt(n.y, 3)}, ${fmt(n.z, 3)}`} unit="m" />
        <div className="flex justify-between py-0.5 border-b border-ink-800/80"><span className="text-ink-400">Support</span>
          <select className="input !w-32" value={sup?.type ?? "none"} onChange={(e) => editModel((m) => {
            const v = e.target.value;
            m.supports = m.supports.filter((s) => s.node !== id || v !== "none");
            const s = m.supports.find((s) => s.node === id);
            if (s && v !== "none") s.type = v as "fixed";
            else if (!s && v !== "none") m.supports.push({ node: id, type: v as "fixed", footing: { B: 2, L: 2, t: 0.6 } });
          })}>
            <option value="none">none</option><option value="fixed">fixed</option><option value="pinned">pinned</option><option value="roller">roller</option>
          </select>
        </div>
      </Section>
      {d && <Section title="Displacement" tag={<Calc />}>
        {["ux", "uy", "uz"].map((k, i) => <Row key={k} k={k} v={fmt(d[i] * 1000, 3)} unit="mm" />)}
        {["rx", "ry", "rz"].map((k, i) => <Row key={k} k={k} v={fmt(d[i + 3] * 1000, 4)} unit="mrad" />)}
      </Section>}
      {r && <Section title="Support reaction" tag={<Calc />}>
        {["Rx", "Ry", "Rz"].map((k, i) => <Row key={k} k={k} v={fmt(r[i], 2)} unit="kN" />)}
        {["Mx", "My", "Mz"].map((k, i) => <Row key={k} k={k} v={fmt(r[i + 3], 2)} unit="kN·m" />)}
      </Section>}
      {fp && sup?.footing && <Section title={`Footing ${sup.footing.B}×${sup.footing.L}×${sup.footing.t} m`} tag={<Assumed t="RIGID FOOTING" />}>
        <Row k="N on soil (incl. footing wt.)" v={fmt(fp.N, 1)} unit="kN" />
        <Row k="q max / q min" v={`${fmt(fp.qmax, 1)} / ${fmt(fp.qmin, 1)}`} unit="kN/m²" />
        <Row k="Eccentricity ex / ey" v={`${fmt(fp.ex * 1000, 0)} / ${fmt(fp.ey * 1000, 0)}`} unit="mm" />
        <Row k="q max / q allow (user)" v={fmt(fp.qmax / model.settings.allowable_bearing, 3)} />
        {fp.uplift && <div className="text-xs text-fuchsia-300 mt-1">Uplift: part of the footing loses contact — the linear full-contact formula is not valid.</div>}
      </Section>}
      {multi.length === 2 && <Section title="Add member">
        <button className="btn" onClick={() => editModel((m) => { const k = m.elements.length + 1; m.elements.push({ id: `M${k}`, type: "beam", role: "main", i: multi[0], j: multi[1], section: Object.keys(m.sections)[1] ?? Object.keys(m.sections)[0], label: `User member ${multi[0]}-${multi[1]}` }); })}>Add beam {multi[0]} → {multi[1]}</button>
      </Section>}
      <Section title="Add nodal load">
        <div className="grid grid-cols-4 gap-1">
          {["Fx", "Fy", "Fz"].map((k, i) => <input key={k} className="input" type="number" value={F[i]} title={k} onChange={(e) => { const v = [...F]; v[i] = +e.target.value; setF(v); }} />)}
          <select className="input" value={c} onChange={(e) => setC(e.target.value)}>{model.load_cases.map((x) => <option key={x.id}>{x.id}</option>)}</select>
        </div>
        <button className="btn mt-1" onClick={() => editModel((m) => { m.loads.push({ case: c, kind: "nodal", node: id, values: [...F, 0, 0, 0], label: "User nodal load" }); })}>Add load (kN)</button>
      </Section>
      <span className="hidden">{String(!!set)}</span>
    </div>
  );
}

function SlabPanel({ model, results, id }: { model: Model; results: Results | null; id: string }) {
  const { editModel, loadSel, set } = useStore();
  const s = model.slabs.find((x) => x.id === id)!;
  const t = results?.tributary[id];
  const [q, setQ] = useState(5);
  const [c, setC] = useState("LL");
  return (
    <div>
      <div className="text-lg font-semibold">Slab {id}</div>
      <div className="text-ink-400 text-xs">{s.label}</div>
      <Section title="Properties">
        <Row k="Thickness" v={fmt(s.thickness * 1000, 0)} unit="mm" />
        <div className="flex justify-between py-0.5 border-b border-ink-800/80"><span className="text-ink-400">Span type</span>
          <select className="input !w-32" value={s.span_type ?? "auto"} onChange={(e) => editModel((m) => { m.slabs.find((x) => x.id === id)!.span_type = e.target.value; })}>
            <option value="auto">auto (ratio ≤ 2 → two-way)</option><option value="two-way">two-way</option><option value="one-way">one-way</option>
          </select>
        </div>
      </Section>
      {t && <Section title="Load distribution to beams" tag={<Assumed t="TRIBUTARY (NOT FEM)" />}>
        <Row k="Panel" v={`${fmt(t.lx, 2)} × ${fmt(t.ly, 2)} m — ${t.mode}`} />
        {t.edges.map((e) => (
          <Row key={e.edge} k={`Edge ${e.edge + 1} → ${e.segments.map((g) => g.element).join(", ") || "NO BEAM"}`} v={`${(e.fraction * 100).toFixed(1)} %`} />
        ))}
        <div className="text-[10px] text-ink-400 mt-1">45° yield-line tributary areas. Slab bending is not analysed in Phase 1; beam/column results are exact for these transferred loads.</div>
      </Section>}
      <Section title="Add area load">
        <div className="grid grid-cols-2 gap-1">
          <input className="input" type="number" value={q} onChange={(e) => setQ(+e.target.value)} />
          <select className="input" value={c} onChange={(e) => setC(e.target.value)}>{model.load_cases.map((x) => <option key={x.id}>{x.id}</option>)}</select>
        </div>
        <button className="btn mt-1" onClick={() => editModel((m) => { m.loads.push({ case: c, kind: "area", slab: id, q, label: `Area load ${q} kN/m²` }); })}>Add {q} kN/m² (downward)</button>
      </Section>
      <span className="hidden">{loadSel}{String(!!set)}</span>
    </div>
  );
}

function MultiPanel({ model }: { model: Model }) {
  const { multi, editModel, set } = useStore();
  const els = multi.filter((id) => model.elements.some((e) => e.id === id));
  const nodes = multi.filter((id) => model.nodes.some((n) => n.id === id));
  if (nodes.length === 2 && !els.length) return <NodePanel model={model} results={null} id={nodes[1]} />;
  return (
    <div>
      <div className="text-lg font-semibold">{els.length} members selected</div>
      <div className="flex flex-wrap gap-1 mt-2">{els.map((e) => <span key={e} className="tag bg-ink-800">{e}</span>)}</div>
      <Section title="Assign section">
        <select className="input" defaultValue="" onChange={(e) => e.target.value && editModel((m) => { for (const x of m.elements) if (els.includes(x.id)) x.section = e.target.value; })}>
          <option value="" disabled>Choose section…</option>
          {Object.entries(model.sections).map(([k, s]) => <option key={k} value={k}>{k} – {s.name}</option>)}
        </select>
      </Section>
      <AddMemberLoad ids={els} />
      <div className="mt-4 flex gap-1.5">
        <button className="btn" onClick={() => set({ isolated: els })}>Isolate</button>
        <button className="btn text-red-300" onClick={() => { editModel((m) => { m.elements = m.elements.filter((e) => !els.includes(e.id)); }); set({ multi: [] }); }}>Delete all</button>
      </div>
    </div>
  );
}
