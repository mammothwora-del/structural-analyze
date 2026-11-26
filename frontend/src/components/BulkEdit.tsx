import { useMemo, useState } from "react";
import { freeSectionId, sameSection, sectionsOf, visibleMembers } from "../lib/select";
import type { Model, Section } from "../lib/types";
import { useStore, useU } from "../store";
import { elementColorKey, TYPE_COLORS, TYPE_LABELS } from "../three/Members";
import { SectionEditor } from "./SectionEditor";

const chip = "px-1.5 py-0.5 rounded border border-ink-700 text-[11px] hover:bg-ink-700 hover:text-ink-100 text-ink-300";

/** Select all members of a type, a section or a level (only members shown in the 3D view). */
export function QuickSelect({ model, compact = false }: { model: Model; compact?: boolean }) {
  const { hiddenTypes, maxLevel, isolated, selectMembers, set, boxSelect } = useStore();
  const [add, setAdd] = useState(false);
  const vis = useMemo(() => visibleMembers(model, hiddenTypes, maxLevel, isolated, elementColorKey), [model, hiddenTypes, maxLevel, isolated]);
  const byType = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const e of vis) (m[elementColorKey(e)] ??= []).push(e.id);
    return m;
  }, [vis]);
  const bySec = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const e of vis) (m[e.section] ??= []).push(e.id);
    return m;
  }, [vis]);
  const levels = useMemo(() => [...new Set(vis.map((e) => e.level ?? 0))].sort((a, b) => a - b), [vis]);
  const pick = (ids: string[], ev?: React.MouseEvent) => selectMembers(ids, add || !!ev?.shiftKey || !!ev?.ctrlKey);
  return (
    <div className="text-[11px]">
      {!compact && <div className="panel-title mb-1.5">Select members</div>}
      <div className="flex flex-wrap gap-1 mb-1.5">
        <button className={chip} onClick={(e) => pick(vis.map((x) => x.id), e)}>All ({vis.length})</button>
        {Object.entries(byType).map(([k, ids]) => (
          <button key={k} className={chip} onClick={(e) => pick(ids, e)} title={`Select every ${TYPE_LABELS[k]?.toLowerCase() ?? k} shown`}>
            <span className="inline-block w-2 h-2 rounded-sm mr-1 align-middle" style={{ background: TYPE_COLORS[k] }} />{TYPE_LABELS[k] ?? k} ({ids.length})
          </button>
        ))}
      </div>
      <div className="flex gap-1 mb-1.5">
        <select className="input flex-1" value="" onChange={(e) => e.target.value && pick(bySec[e.target.value])}>
          <option value="">By section…</option>
          {Object.entries(bySec).map(([k, ids]) => <option key={k} value={k}>{k} – {model.sections[k]?.name ?? k} ({ids.length})</option>)}
        </select>
        {levels.length > 1 && (
          <select className="input !w-24" value="" onChange={(e) => e.target.value !== "" && pick(vis.filter((x) => (x.level ?? 0) === +e.target.value).map((x) => x.id))}>
            <option value="">Level…</option>
            {levels.map((l) => <option key={l} value={l}>Level {l}</option>)}
          </select>
        )}
      </div>
      <div className="flex items-center justify-between gap-2">
        <label className="flex items-center gap-1.5 text-ink-400 cursor-pointer">
          <input type="checkbox" className="accent-sky-400" checked={add} onChange={(e) => setAdd(e.target.checked)} /> Add to the selection
        </label>
        <button className={`${chip} ${boxSelect ? "!bg-accent/20 !text-accent !border-accent/50" : ""}`} onClick={() => set({ boxSelect: !boxSelect })}
          title="Drag a box over the members in the 3D view (B)">Box select</button>
      </div>
      {!compact && (
        <div className="text-[10px] text-ink-500 mt-1.5">
          Only members shown in the 3D view are selected: hide components, use the section cut or isolate first to narrow it down.
          Shift-click a button (or tick the box) to add to the selection. In the 3D view: shift/ctrl-click members, or Box select
          (drag left to right = members fully inside, right to left = members touched). Ctrl+A selects every member shown.
        </div>
      )}
    </div>
  );
}

/** Change the shape, size and material of every selected member at once. */
export function BulkSection({ model, ids }: { model: Model; ids: string[] }) {
  const { editModel, redesign, busy, steelBusy, selectMembers } = useStore();
  const [open, setOpen] = useState(false);
  const secs = sectionsOf(model, ids);
  if (!secs.length) return null;
  const main = secs[0];
  // the selection is every member of one section: change that section itself
  const whole = secs.length === 1 && main.n === main.total;
  const start = model.sections[main.id];
  const apply = (sec: Section, rerun: boolean) => {
    let target = main.id;
    editModel((m) => {
      if (whole) {
        m.sections[main.id] = sec;
        return;
      }
      const same = Object.entries(m.sections).find(([, s]) => sameSection(s as unknown as Record<string, unknown>, sec as unknown as Record<string, unknown>));
      target = same ? same[0] : freeSectionId(m, main.id);
      if (!same) m.sections[target] = sec;
      const set = new Set(ids);
      for (const e of m.elements) if (set.has(e.id)) e.section = target;
    });
    setOpen(false);
    selectMembers(ids);
    if (rerun) redesign();
  };
  const others = secs.reduce((a, s) => a + (s.total - s.n), 0);
  return (
    <div>
      <div className="text-[11px] text-ink-300 mb-1">
        {secs.map((s) => (
          <div key={s.id} className="flex justify-between gap-2">
            <span className="truncate"><b className="text-ink-200">{s.id}</b> {model.sections[s.id]?.name}</span>
            <span className="shrink-0 text-ink-400">{s.n === s.total ? `all ${s.n}` : `${s.n} of ${s.total}`}</span>
          </div>
        ))}
      </div>
      {!open ? (
        <button className="btn-primary w-full" onClick={() => setOpen(true)}>Change size / shape / steel grade…</button>
      ) : (
        <>
          <div className="text-[10px] text-ink-400 mb-1">
            {whole
              ? <>Section <b className="text-ink-200">{main.id}</b> is changed: it is used only by these {ids.length} members.</>
              : <>The {ids.length} selected members get one section{others > 0 ? <> (the other {others} member{others > 1 ? "s" : ""} of {secs.map((s) => s.id).join(", ")} keep theirs)</> : null}. A new section id is made, or an existing one with the same size is reused.</>}
          </div>
          <SectionEditor model={model} value={start} onCancel={() => setOpen(false)} saveLabel={`Apply size to ${ids.length} members`}
            onSave={(s) => apply(s, false)} onSaveRedesign={busy || steelBusy ? undefined : (s) => apply(s, true)} />
        </>
      )}
    </div>
  );
}

type DKey = "Ky" | "Kz" | "Lb" | "Cb";

/** Steel design settings (effective length factors, unbraced length, Cb) for every selected member. */
export function BulkDesign({ model, ids }: { model: Model; ids: string[] }) {
  const u = useU();
  const { editModel } = useStore();
  const els = model.elements.filter((e) => ids.includes(e.id));
  const [vals, setVals] = useState<Record<DKey, string>>({ Ky: "", Kz: "", Lb: "", Cb: "" });
  const common = (k: DKey) => {
    const v = new Set(els.map((e) => e.design?.[k] ?? null));
    if (v.size !== 1) return "mixed";
    const x = [...v][0];
    return x == null ? (k === "Lb" ? "member" : k === "Cb" ? "auto" : "1.0") : k === "Lb" ? u.f("length", x, 3) : String(x);
  };
  const ok = (Object.keys(vals) as DKey[]).some((k) => vals[k] !== "" && isFinite(+vals[k]) && +vals[k] > 0);
  const apply = () => editModel((m) => {
    for (const e of m.elements) {
      if (!ids.includes(e.id)) continue;
      const nd = { ...(e.design ?? {}) };
      for (const k of Object.keys(vals) as DKey[]) {
        const v = vals[k];
        if (v !== "" && isFinite(+v) && +v > 0) nd[k] = k === "Lb" ? u.si("length", +v) : +v;
      }
      if (Object.keys(nd).length) e.design = nd; else delete e.design;
    }
  });
  const reset = () => editModel((m) => { for (const e of m.elements) if (ids.includes(e.id)) delete e.design; });
  const F = ({ k, label, unit }: { k: DKey; label: string; unit?: string }) => (
    <label className="flex items-center justify-between gap-2 py-0.5">
      <span className="text-ink-400">{label}</span>
      <span className="flex items-center gap-1">
        <input className="input !w-20 text-right" placeholder={common(k)} value={vals[k]} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} />
        <span className="w-6 text-ink-500">{unit}</span>
      </span>
    </label>
  );
  return (
    <div className="text-[11px]">
      <F k="Ky" label="K major axis (y)" />
      <F k="Kz" label="K minor axis (z)" />
      <F k="Lb" label="Unbraced length (LTB)" unit={u.u("length")} />
      <F k="Cb" label="Cb / C1" />
      <div className="text-[10px] text-ink-500 mb-1">The grey value is the current one ("mixed" when the members differ). Blank fields are left as they are.</div>
      <div className="flex gap-1">
        <button className="btn-primary flex-1" disabled={!ok} onClick={() => { apply(); setVals({ Ky: "", Kz: "", Lb: "", Cb: "" }); }}>Apply settings to {els.length} members</button>
        <button className="btn" onClick={reset} title="K = 1.0, unbraced length = member length, Cb from the moment diagram">Reset</button>
      </div>
    </div>
  );
}
