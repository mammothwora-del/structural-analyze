import { create } from "zustand";
import { api } from "./lib/api";
import type { PathDir, TraceResult } from "./lib/loadpath";
import type { ShellComp } from "./lib/shells";
import type { BucklingResult, ForceComp, Load, Mode, Model, PDeltaResult, RcDesignResult, Results, SteelDesignResult } from "./lib/types";
import { U, type UnitSystem } from "./lib/units";
import { download } from "./lib/download";
import { projectFile, readProjectFile, safeName } from "./lib/project";

export type Selection = { kind: "element" | "node" | "slab" | "wall"; id: string } | null;

interface State {
  model: Model | null;
  results: Results | null;
  resultsStale: boolean;
  busy: boolean;
  error: string | null;
  backendOk: boolean | null;
  mode: Mode;
  view: "3d" | "dashboard";
  loadSel: string;              // case or combination id
  selection: Selection;
  multi: string[];              // multi-selected element ids
  boxSelect: boolean;           // drag a box in the 3D view to select members
  forceComp: ForceComp;
  shellComp: ShellComp;
  deformScale: number;
  animate: boolean;
  showLabels: boolean;
  showSlabs: boolean;
  showDims: boolean;            // dimension lines between grid lines
  labelSize: number;            // scale of grid names and dimension text (1 = default)
  hiddenTypes: Record<string, boolean>;
  maxLevel: number | null;      // section cut: show up to this level
  exploded: number;             // exploded view factor (m per level)
  ortho: boolean;
  pathDir: PathDir;
  trace: TraceResult | null;
  isolated: string[] | null;
  bottomTab: string;
  colorTransform: "linear" | "sqrt";
  units: UnitSystem;
  log: string[];
  history: Model[];
  /** stability results, cleared whenever the model changes */
  buckling: BucklingResult | null;
  pdelta: PDeltaResult | null;
  bucklingMode: number;
  stabBusy: boolean;
  stabError: string | null;
  steel: SteelDesignResult | null;
  steelCode: string;            // "" = from the model's standard
  steelBusy: boolean;
  steelError: string | null;
  designTab: "steel" | "rc";
  rc: RcDesignResult | null;
  rcOptions: { main_grade: string; tie_grade: string; cover: number };
  rcBusy: boolean;
  rcError: string | null;
  dialog: null | "dxf" | "report";
  reportInfo: { engineer: string; project: string; lang?: "en" | "th" };
  set: (p: Partial<State>) => void;
  /** select these members (replacing the selection, or added to it) */
  selectMembers: (ids: string[], add?: boolean) => void;
  setModel: (m: Model, keepResults?: boolean) => void;
  editModel: (fn: (m: Model) => void) => void;
  undo: () => void;
  generate: (params: Record<string, unknown>) => Promise<void>;
  analyze: () => Promise<void>;
  addLoad: (l: Load) => void;
  runBuckling: (nSeg: number, nModes: number) => Promise<void>;
  runPDelta: () => Promise<void>;
  runSteel: () => Promise<void>;
  runRc: () => Promise<void>;
  /** analyse, then re-run the steel design (and the RC design if it was shown) */
  redesign: () => Promise<void>;
  saveProject: () => void;
  openProject: (text: string, fileName: string) => void;
}

/** Id under which a P-Delta result is added to the result cases (selectable like a load case). */
export const pdeltaId = (load: string) => `PD:${load}`;
/** The load case or combination behind a selection (a P-Delta result id maps back to its load). */
export const baseLoad = (sel: string) => (sel.startsWith("PD:") ? sel.slice(3) : sel);
const NO_STAB = { buckling: null, pdelta: null, stabError: null, steel: null, steelError: null, rc: null, rcError: null };

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export const useStore = create<State>((set, get) => ({
  model: null, results: null, resultsStale: false, busy: false, error: null, backendOk: null,
  mode: "model", view: "3d", loadSel: "DL", selection: null, multi: [], boxSelect: false,
  forceComp: "My", shellComp: "vm", deformScale: 50, animate: true, showLabels: false, showSlabs: true,
  showDims: true, labelSize: (() => { try { return Math.min(3, Math.max(0.6, +(localStorage.getItem("labelSize") ?? 1) || 1)); } catch { return 1; } })(),
  hiddenTypes: {}, maxLevel: null, exploded: 0, ortho: false, pathDir: "auto", trace: null, isolated: null,
  bottomTab: "log", log: [], history: [], buckling: null, pdelta: null, bucklingMode: 0, stabBusy: false, stabError: null, steel: null, steelCode: "", steelBusy: false, steelError: null,
  designTab: "steel", rc: null, rcOptions: { main_grade: "SD40", tie_grade: "SR24", cover: 0.04 }, rcBusy: false, rcError: null, dialog: null, reportInfo: { engineer: "", project: "" }, colorTransform: "sqrt", units: (() => { try { return (localStorage.getItem("units") as UnitSystem) || "SI"; } catch { return "SI"; } })(),
  set: (p) => set(p),
  selectMembers: (ids, add = false) => {
    const st = get();
    const prev = add ? [...(st.selection?.kind === "element" ? [st.selection.id] : []), ...st.multi.filter((x) => st.model?.elements.some((e) => e.id === x))] : [];
    const all = [...new Set([...prev, ...ids])];
    if (all.length === 1) set({ selection: { kind: "element", id: all[0] }, multi: [] });
    else set({ selection: null, multi: all });
  },
  setModel: (m, keepResults = false) => set({ ...NO_STAB, model: m, results: keepResults ? get().results : null, resultsStale: false, trace: null, selection: null }),
  editModel: (fn) => {
    const m = get().model;
    if (!m) return;
    const next = clone(m);
    fn(next);
    set({ ...NO_STAB, model: next, history: [...get().history.slice(-30), m], resultsStale: !!get().results, trace: null });
  },
  undo: () => {
    const h = get().history;
    if (!h.length) return;
    set({ ...NO_STAB, model: h[h.length - 1], history: h.slice(0, -1), resultsStale: !!get().results });
  },
  generate: async (params) => {
    set({ busy: true, error: null });
    try {
      const m = await api.generate(params);
      set({ ...NO_STAB, model: m, results: null, resultsStale: false, selection: null, trace: null, isolated: null, mode: "model", history: [],
        log: [...get().log, `New model "${m.name}": ${m.elements.length} members${m.slabs.length ? `, ${m.slabs.length} slab panels` : ""}${m.walls?.length ? `, ${m.walls.length} walls` : ""}, ${m.supports.length} supports.`] });
    } catch (e) {
      set({ error: String((e as Error).message) });
    } finally {
      set({ busy: false });
    }
  },
  analyze: async () => {
    const m = get().model;
    if (!m) return;
    set({ busy: true, error: null });
    try {
      const r = await api.analyze(m);
      const want = baseLoad(get().loadSel);
      const loadSel = r.cases[want] || m.combinations.some((c) => c.id === want) ? want : m.load_cases[0]?.id;
      set({ results: r, resultsStale: false, loadSel, trace: null, pdelta: null, log: [...get().log, "— Analysis —", ...r.log, ...r.warnings.map((w) => `[${w.level.toUpperCase()}] ${w.case ? w.case + ": " : ""}${w.message}`)],
        mode: get().mode === "model" || get().mode === "loads" ? "loadpath" : get().mode, bottomTab: r.warnings.length ? "warnings" : get().bottomTab });
    } catch (e) {
      const msg = String((e as Error).message);
      set({ error: msg, log: [...get().log, `[ERROR] Analysis failed: ${msg}`], bottomTab: "log" });
    } finally {
      set({ busy: false });
    }
  },
  addLoad: (l) => get().editModel((m) => { m.loads.push(l); }),
  runBuckling: async (nSeg, nModes) => {
    const m = get().model;
    if (!m) return;
    const load = baseLoad(get().loadSel);
    set({ stabBusy: true, stabError: null });
    try {
      const r = await api.buckling(m, load, nModes, nSeg);
      set({ buckling: r, bucklingMode: 0, log: [...get().log, `— Buckling (${load}) —`, r.modes.length
        ? `Elastic critical load factors: ${r.modes.map((x) => x.factor.toFixed(3)).join(", ")} (${r.ndof} DOF, ${r.time_ms.toFixed(0)} ms)`
        : "No buckling mode found (no compression)."] });
    } catch (e) {
      const msg = String((e as Error).message);
      set({ stabError: msg, log: [...get().log, `[ERROR] Buckling failed: ${msg}`] });
    } finally {
      set({ stabBusy: false });
    }
  },
  runSteel: async () => {
    const m = get().model;
    if (!m) return;
    set({ steelBusy: true, steelError: null, mode: "design", designTab: "steel" });
    try {
      const r = await api.steelDesign(m, get().steelCode || undefined);
      const s = r.summary;
      set({ steel: r, log: [...get().log, `— Steel design (${r.code_name}) —`,
        `${s.n_checked} members checked for ${r.combinations.join(", ")}: ${s.ok} OK, ${s.fail} over 1.0, ${s.not_covered} not covered${s.skipped ? `, ${s.skipped} not steel` : ""}.${s.max_util != null ? ` Max utilisation ${s.max_util.toFixed(2)}.` : ""}`] });
    } catch (e) {
      const msg = String((e as Error).message);
      set({ steelError: msg, log: [...get().log, `[ERROR] Steel design failed: ${msg}`] });
    } finally {
      set({ steelBusy: false });
    }
  },
  redesign: async () => {
    const hadRc = get().designTab === "rc";
    await get().analyze();
    if (get().error) return;
    if (hadRc) await get().runRc(); else await get().runSteel();
  },
  runRc: async () => {
    const m = get().model;
    if (!m) return;
    set({ rcBusy: true, rcError: null, mode: "design", designTab: "rc" });
    try {
      const r = await api.rcDesign(m, get().rcOptions);
      const s = r.summary;
      set({ rc: r, log: [...get().log, `— RC design (${r.code_name}) —`,
        `${s.n_checked} members designed for ${r.combinations.join(", ")}: ${s.ok} OK, ${s.fail} over 1.0, ${s.not_covered} not covered${s.skipped ? `, ${s.skipped} not concrete` : ""}.${s.max_util != null ? ` Max utilisation ${s.max_util.toFixed(2)}.` : ""}`] });
    } catch (e) {
      const msg = String((e as Error).message);
      set({ rcError: msg, log: [...get().log, `[ERROR] RC design failed: ${msg}`] });
    } finally {
      set({ rcBusy: false });
    }
  },
  saveProject: () => {
    const { model, units, steelCode, rcOptions, reportInfo, log } = get();
    if (!model) return;
    const name = `${safeName(model.name)}.sproj`;
    download(name, projectFile(model, { units, steelCode, rcOptions, report: reportInfo }));
    set({ log: [...log, `Project saved as ${name} (model and settings; results are recalculated after opening).`] });
  },
  openProject: (text, fileName) => {
    try {
      const { model, settings, savedAt } = readProjectFile(text);
      get().setModel(model);
      set({
        history: [], isolated: null, maxLevel: null, mode: "model", view: "3d", loadSel: model.load_cases[0]?.id ?? "DL", error: null,
        ...(settings.units ? { units: settings.units } : {}),
        ...(settings.steelCode != null ? { steelCode: settings.steelCode } : {}),
        ...(settings.rcOptions ? { rcOptions: settings.rcOptions } : {}),
        reportInfo: { engineer: settings.report?.engineer ?? "", project: settings.report?.project ?? "", lang: settings.report?.lang },
        log: [...get().log, `Opened ${fileName}: "${model.name}", ${model.elements.length} members, ${model.nodes.length} nodes${savedAt ? ` (saved ${new Date(savedAt).toLocaleString()})` : ""}. Run the analysis to calculate results.`],
      });
    } catch (e) {
      set({ error: `Could not open ${fileName}: ${(e as Error).message}` });
    }
  },
  runPDelta: async () => {
    const m = get().model;
    if (!m) return;
    const load = baseLoad(get().loadSel);
    if (!get().results || get().resultsStale) await get().analyze();
    if (!get().results) return;
    set({ stabBusy: true, stabError: null, mode: "stability", loadSel: load });
    try {
      const r = await api.pdelta(m, load);
      const results = get().results!;
      set({ pdelta: r, results: { ...results, cases: { ...results.cases, [pdeltaId(load)]: { ...r.result, case: pdeltaId(load) } } },
        log: [...get().log, `— P-Delta (${load}) —`, `${r.converged ? "Converged" : "NOT converged"} in ${r.iterations} iterations; max displacement × ${r.amplification.toFixed(3)} vs linear.`,
          ...r.warnings.filter((w) => w.level !== "info").map((w) => `[${w.level.toUpperCase()}] ${w.message}`)] });
    } catch (e) {
      const msg = String((e as Error).message);
      set({ stabError: msg, log: [...get().log, `[ERROR] P-Delta failed: ${msg}`] });
    } finally {
      set({ stabBusy: false });
    }
  },
}));

/** Unit formatter bound to the selected display system. */
export const useU = () => U(useStore((s) => s.units));
