import { create } from "zustand";
import { api } from "./lib/api";
import type { PathDir, TraceResult } from "./lib/loadpath";
import type { ShellComp } from "./lib/shells";
import type { BucklingResult, ForceComp, Load, Mode, Model, PDeltaResult, Results, SteelDesignResult } from "./lib/types";
import { U, type UnitSystem } from "./lib/units";

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
  forceComp: ForceComp;
  shellComp: ShellComp;
  deformScale: number;
  animate: boolean;
  showLabels: boolean;
  showSlabs: boolean;
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
  set: (p: Partial<State>) => void;
  setModel: (m: Model, keepResults?: boolean) => void;
  editModel: (fn: (m: Model) => void) => void;
  undo: () => void;
  generate: (params: Record<string, unknown>) => Promise<void>;
  analyze: () => Promise<void>;
  addLoad: (l: Load) => void;
  runBuckling: (nSeg: number, nModes: number) => Promise<void>;
  runPDelta: () => Promise<void>;
  runSteel: () => Promise<void>;
}

/** Id under which a P-Delta result is added to the result cases (selectable like a load case). */
export const pdeltaId = (load: string) => `PD:${load}`;
/** The load case or combination behind a selection (a P-Delta result id maps back to its load). */
export const baseLoad = (sel: string) => (sel.startsWith("PD:") ? sel.slice(3) : sel);
const NO_STAB = { buckling: null, pdelta: null, stabError: null, steel: null, steelError: null };

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export const useStore = create<State>((set, get) => ({
  model: null, results: null, resultsStale: false, busy: false, error: null, backendOk: null,
  mode: "model", view: "3d", loadSel: "DL", selection: null, multi: [],
  forceComp: "My", shellComp: "vm", deformScale: 50, animate: true, showLabels: false, showSlabs: true,
  hiddenTypes: {}, maxLevel: null, exploded: 0, ortho: false, pathDir: "auto", trace: null, isolated: null,
  bottomTab: "log", log: [], history: [], buckling: null, pdelta: null, bucklingMode: 0, stabBusy: false, stabError: null, steel: null, steelCode: "", steelBusy: false, steelError: null, colorTransform: "sqrt", units: (() => { try { return (localStorage.getItem("units") as UnitSystem) || "SI"; } catch { return "SI"; } })(),
  set: (p) => set(p),
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
    set({ steelBusy: true, steelError: null, mode: "design" });
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
