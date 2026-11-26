import { useState, type ReactNode } from "react";
import { BoqDialog } from "./BoqDialog";
import { WindDialog } from "./WindDialog";
import { api, type DxfOptions } from "../lib/api";
import { download } from "../lib/download";
import { safeName } from "../lib/project";
import { useStore } from "../store";
import { CODE_OPTIONS } from "./DesignPanel";

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label={title} className={`${wide ? "w-[640px]" : "w-[440px]"} max-w-[94vw] max-h-[90vh] overflow-y-auto rounded-lg border border-ink-700 bg-ink-900 p-4 text-xs text-ink-200 shadow-2xl`}>
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold">{title}</div>
          <button className="text-ink-400 hover:text-ink-100" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="block text-ink-400">{label}<div className="mt-0.5">{children}</div></label>
);

export function FileDialogs() {
  const dialog = useStore((s) => s.dialog);
  const close = () => useStore.setState({ dialog: null });
  if (dialog === "dxf") return <Modal title="Import DXF wireframe" onClose={close}><DxfDialog onDone={close} /></Modal>;
  if (dialog === "wind") return <Modal title="Wind loads: DPT 1311-50 (low-rise buildings)" onClose={close} wide><WindDialog onDone={close} /></Modal>;
  if (dialog === "boq") return <Modal title="Quantities and cost (BOQ)" onClose={close} wide><BoqDialog onDone={close} /></Modal>;
  if (dialog === "report") return <Modal title="PDF calculation report" onClose={close}><ReportDialog onDone={close} /></Modal>;
  return null;
}

function DxfDialog({ onDone }: { onDone: () => void }) {
  const s = useStore();
  const [file, setFile] = useState<File | null>(null);
  const [opt, setOpt] = useState<Omit<DxfOptions, "name" | "tol"> & { tolMm: number }>({
    units: "auto", material: "steel", support: "fixed", standard: s.model?.settings.standard ?? "EN1990", tolMm: 5, connect_crossings: true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const text = await file.text();
      const { tolMm, ...rest } = opt;
      const m = await api.importDxf(text, { ...rest, tol: Math.max(tolMm, 0.1) / 1000, name: file.name.replace(/\.dxf$/i, "") });
      s.setModel(m);
      s.set({ history: [], isolated: null, maxLevel: null, mode: "model", view: "3d", loadSel: m.load_cases[0]?.id ?? "DL",
        log: [...useStore.getState().log, `— DXF import (${file.name}) —`, ...(m.notes ?? [])] });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const set = (k: string, v: string | number | boolean) => setOpt({ ...opt, [k]: v });
  return (
    <>
      <p className="text-ink-400 mb-3">
        Reads LINE and POLYLINE entities of an ASCII DXF and turns every straight segment into a member. Draw the frame in 3D
        (or as an elevation in the X-Z plane) with Z up. Layer names containing COL, BEAM, BRAC or TRUSS set the member type;
        otherwise vertical lines become columns, horizontal lines beams and inclined lines pinned braces.
      </p>
      <input type="file" accept=".dxf" className="mb-3 block w-full text-ink-300 file:mr-2 file:rounded file:border-0 file:bg-ink-700 file:px-2 file:py-1 file:text-ink-100"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <div className="grid grid-cols-2 gap-2 mb-3">
        <Field label="Drawing units">
          <select className="input" value={opt.units} onChange={(e) => set("units", e.target.value)}>
            {[["auto", "From the file ($INSUNITS)"], ["mm", "mm"], ["cm", "cm"], ["m", "m"], ["in", "inch"], ["ft", "foot"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Merge tolerance (mm)"><input className="input" type="number" min="0.1" step="1" value={opt.tolMm} onChange={(e) => set("tolMm", +e.target.value)} /></Field>
        <Field label="Material">
          <select className="input" value={opt.material} onChange={(e) => set("material", e.target.value)}><option value="steel">Steel</option><option value="concrete">Reinforced concrete</option></select>
        </Field>
        <Field label="Supports at the lowest nodes">
          <select className="input" value={opt.support} onChange={(e) => set("support", e.target.value)}><option value="fixed">Fixed</option><option value="pinned">Pinned</option></select>
        </Field>
        <Field label="Design standard">
          <select className="input" value={opt.standard} onChange={(e) => set("standard", e.target.value)}>
            <option value="EN1990">Eurocode (EN 1990)</option><option value="ASCE7">ASCE 7</option><option value="TH">Thai (DPT / EIT)</option>
          </select>
        </Field>
      </div>
      <label className="mb-3 flex items-start gap-2 cursor-pointer">
        <input type="checkbox" className="mt-0.5" checked={opt.connect_crossings} onChange={(e) => set("connect_crossings", e.target.checked)} />
        <span>Connect members that cross in 3D (for beams drawn continuous through grid lines and X-bracing). Lines that only
          cross in a 2D view never meet in 3D and stay apart. A member is always split where another member ends on it.</span>
      </label>
      <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-amber-200">
        ASSUMED after import: default sections, supports and a self-weight load case only. Assign the real sections, supports and
        loads before using any result. The current model is replaced (save it first if needed).
      </div>
      {err && <div className="mb-3 rounded border border-red-500/40 bg-red-500/10 p-2 text-red-200">{err}</div>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onDone}>Cancel</button>
        <button className="btn-primary" disabled={!file || busy} onClick={run}>{busy ? "Importing…" : "Import"}</button>
      </div>
    </>
  );
}

const PARTS: [string, string, boolean][] = [
  ["model", "Model: materials, sections, supports", true],
  ["loads", "Load cases and combinations", true],
  ["analysis", "Analysis: equilibrium check, reactions, extreme forces", true],
  ["members", "Member force envelope (table per member)", true],
  ["stability", "Elastic critical buckling", false],
  ["steel", "Steel member design", true],
  ["rc", "RC beam and column design", true],
  ["deflection", "Deflection and drift (serviceability)", true],
  ["boq", "Quantities and cost (BOQ)", true],
];

function ReportDialog({ onDone }: { onDone: () => void }) {
  const s = useStore();
  const model = s.model!;
  const [inc, setInc] = useState<Record<string, boolean>>(Object.fromEntries(PARTS.map(([k, , v]) => [k, v])));
  const [title, setTitle] = useState(model.name);
  const [info, setInfo] = useState({ ...s.reportInfo, lang: s.reportInfo.lang ?? (model.settings.standard === "TH" ? "th" as const : "en" as const) });
  const [image, setImage] = useState(s.view === "3d");
  const ulsCombos = model.combinations.filter((c) => !/sls|serv|characteristic|ths/i.test(`${c.id} ${c.name}`));
  const [stabLoad, setStabLoad] = useState(ulsCombos[0]?.id ?? model.load_cases[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    s.set({ reportInfo: info });
    try {
      const canvas = image ? document.querySelector<HTMLCanvasElement>("main canvas") : null;
      const pdf = await api.report({
        model, include: inc, steel_code: s.steelCode || undefined, rc_options: s.rcOptions, stability_load: stabLoad || undefined,
        image: canvas ? canvas.toDataURL("image/png") : undefined, project: { title, project: info.project, engineer: info.engineer }, lang: info.lang,
        deflection: s.deflSettings, boq: s.boqSettings,
      });
      download(`${safeName(title)}-report${info.lang === "th" ? "-th" : ""}.pdf`, pdf);
      s.set({ log: [...useStore.getState().log, `PDF calculation report created (${(pdf.size / 1024).toFixed(0)} kB). The server re-ran the analysis${inc.steel || inc.rc ? " and the designs" : ""} for it.`] });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const code = CODE_OPTIONS.find(([k]) => k === s.steelCode)?.[1] ?? "from the model's standard";
  return (
    <>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="col-span-2"><Field label="Report title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field></div>
        <Field label="Project"><input className="input" value={info.project} placeholder={model.name} onChange={(e) => setInfo({ ...info, project: e.target.value })} /></Field>
        <Field label="Engineer"><input className="input" value={info.engineer} onChange={(e) => setInfo({ ...info, engineer: e.target.value })} /></Field>
        <div className="col-span-2">
          <Field label="Language">
            <div className="flex rounded border border-ink-700 overflow-hidden">
              {([["en", "English"], ["th", "ภาษาไทย (Thai)"]] as const).map(([k, l]) => (
                <button key={k} type="button" onClick={() => setInfo({ ...info, lang: k })}
                  className={`flex-1 py-1 ${info.lang === k ? "bg-accent text-ink-950 font-semibold" : "text-ink-300 hover:bg-ink-800"}`}>{l}</button>
              ))}
            </div>
          </Field>
          {info.lang === "th" && <div className="mt-1 text-ink-500">Headings, tables and check names in Thai (Sarabun font). Numbers, clause numbers and the design notes stay as calculated, in English.</div>}
        </div>
      </div>
      <div className="panel-title mb-1">Contents</div>
      <div className="space-y-1 mb-2">
        {PARTS.map(([k, label]) => (
          <label key={k} className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={inc[k]} onChange={(e) => setInc({ ...inc, [k]: e.target.checked })} />
            <span>{label}</span>
            {k === "steel" && inc.steel && <span className="text-ink-500 truncate">({code})</span>}
            {k === "deflection" && inc.deflection && <span className="text-ink-500">(limits from the Deflection tab)</span>}
            {k === "boq" && inc.boq && <span className="text-ink-500">(prices from Export → Quantities)</span>}
            {k === "rc" && inc.rc && <span className="text-ink-500">({s.rcOptions.main_grade} / {s.rcOptions.tie_grade}, cover {(s.rcOptions.cover * 100).toFixed(1)} cm)</span>}
          </label>
        ))}
        {inc.stability && (
          <div className="pl-6"><Field label="Buckling load">
            <select className="input" value={stabLoad} onChange={(e) => setStabLoad(e.target.value)}>
              {[...model.combinations, ...model.load_cases].map((c) => <option key={c.id} value={c.id}>{c.id} – {c.name}</option>)}
            </select>
          </Field></div>
        )}
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={image} disabled={s.view !== "3d"} onChange={(e) => setImage(e.target.checked)} />
          <span>Picture of the 3D view as it is on screen{s.view !== "3d" ? " (switch to 3D View first)" : ""}</span>
        </label>
      </div>
      <p className="text-ink-500 mb-3">
        The server re-runs the analysis and the selected designs from the current model, so every number in the report is
        calculated at the time of printing. Each part is labelled INPUT, ASSUMED or CALCULATED. The report does not state that
        the structure is safe or code-compliant. Steel code and RC options are the ones set in Design mode.
      </p>
      {err && <div className="mb-3 rounded border border-red-500/40 bg-red-500/10 p-2 text-red-200">{err}</div>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onDone}>Cancel</button>
        <button className="btn-primary" disabled={busy} onClick={run}>{busy ? "Calculating and writing the PDF…" : "Create PDF"}</button>
      </div>
    </>
  );
}
