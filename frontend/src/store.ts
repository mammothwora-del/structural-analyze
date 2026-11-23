import { create } from "zustand";
import { api } from "./lib/api";
import type { PathDir, TraceResult } from "./lib/loadpath";
import type { ForceComp, Load, Mode, Model, Results } from "./lib/types";
import { U, type UnitSystem } from "./lib/units";

export type Selection = { kind: "element" | "node" | "slab"; id: string } | null;

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
  set: (p: Partial<State>) => void;
  setModel: (m: Model, keepResults?: boolean) => void;
  editModel: (fn: (m: Model) => void) => void;
  undo: () => void;
  generate: (params: Record<string, unknown>) => Promise<void>;
  analyze: () => Promise<void>;
  addLoad: (l: Load) => void;
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export const useStore = create<State>((set, get) => ({
  model: null, results: null, resultsStale: false, busy: false, error: null, backendOk: null,
  mode: "model", view: "3d", loadSel: "DL", selection: null, multi: [],
  forceComp: "My", deformScale: 50, animate: true, showLabels: false, showSlabs: true,
  hiddenTypes: {}, maxLevel: null, exploded: 0, ortho: false, pathDir: "auto", trace: null, isolated: null,
  bottomTab: "log", log: [], history: [], colorTransform: "sqrt", units: (() => { try { return (localStorage.getItem("units") as UnitSystem) || "SI"; } catch { return "SI"; } })(),
  set: (p) => set(p),
  setModel: (m, keepResults = false) => set({ model: m, results: keepResults ? get().results : null, resultsStale: false, trace: null, selection: null }),
  editModel: (fn) => {
    const m = get().model;
    if (!m) return;
    const next = clone(m);
    fn(next);
    set({ model: next, history: [...get().history.slice(-30), m], resultsStale: !!get().results, trace: null });
  },
  undo: () => {
    const h = get().history;
    if (!h.length) return;
    set({ model: h[h.length - 1], history: h.slice(0, -1), resultsStale: !!get().results });
  },
  generate: async (params) => {
    set({ busy: true, error: null });
    try {
      const m = await api.generate(params);
      set({ model: m, results: null, resultsStale: false, selection: null, trace: null, isolated: null, mode: "model", history: [],
        log: [...get().log, `Generated building: ${m.elements.length} members, ${m.slabs.length} slab panels, ${m.supports.length} supports.`] });
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
      const loadSel = r.cases[get().loadSel] || m.combinations.some((c) => c.id === get().loadSel) ? get().loadSel : m.load_cases[0]?.id;
      set({ results: r, resultsStale: false, loadSel, trace: null, log: [...get().log, "— Analysis —", ...r.log, ...r.warnings.map((w) => `[${w.level.toUpperCase()}] ${w.case ? w.case + ": " : ""}${w.message}`)],
        mode: get().mode === "model" || get().mode === "loads" ? "loadpath" : get().mode, bottomTab: r.warnings.length ? "warnings" : get().bottomTab });
    } catch (e) {
      const msg = String((e as Error).message);
      set({ error: msg, log: [...get().log, `[ERROR] Analysis failed: ${msg}`], bottomTab: "log" });
    } finally {
      set({ busy: false });
    }
  },
  addLoad: (l) => get().editModel((m) => { m.loads.push(l); }),
}));

/** Unit formatter bound to the selected display system. */
export const useU = () => U(useStore((s) => s.units));
