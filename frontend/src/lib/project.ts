import type { DeflectionLimits, Model } from "./types";
import type { UnitSystem } from "./units";

/** Project file (.sproj): the model plus the user's settings. Results are never saved: they are recalculated. */
export const PROJECT_FORMAT = "structural-analyze-project";
export const PROJECT_VERSION = 1;

export interface ProjectSettings {
  units?: UnitSystem;
  steelCode?: string;
  rcOptions?: { main_grade: string; tie_grade: string; cover: number };
  deflection?: { limits: Partial<DeflectionLimits>; wind_factor: number | null };
  report?: { engineer?: string; project?: string; lang?: "en" | "th" };
}

export interface ProjectFile {
  format: typeof PROJECT_FORMAT;
  version: number;
  saved_at: string;
  model: Model;
  settings: ProjectSettings;
}

export function projectFile(model: Model, settings: ProjectSettings): string {
  const f: ProjectFile = { format: PROJECT_FORMAT, version: PROJECT_VERSION, saved_at: new Date().toISOString(), model, settings };
  return JSON.stringify(f, null, 1);
}

function checkModel(m: unknown): Model {
  const x = m as Partial<Model> | null;
  if (!x || typeof x !== "object") throw new Error("the file does not contain a model");
  for (const k of ["nodes", "elements", "sections", "supports"] as const) {
    if (!x[k] || typeof x[k] !== "object") throw new Error(`the model has no "${k}"`);
  }
  const m2 = x as Model;
  // fill the optional lists so older or hand-written files open
  m2.slabs ??= []; m2.walls ??= []; m2.loads ??= []; m2.load_cases ??= []; m2.combinations ??= [];
  m2.name ??= "Model"; m2.settings ??= { standard: "EN1990" } as Model["settings"];
  return m2;
}

/** Read a .sproj project or a plain model .json. */
export function readProjectFile(text: string): { model: Model; settings: ProjectSettings; savedAt?: string } {
  let data: unknown;
  try { data = JSON.parse(text); } catch { throw new Error("not a JSON file"); }
  const d = data as Partial<ProjectFile>;
  if (d && d.format === PROJECT_FORMAT) {
    if ((d.version ?? 0) > PROJECT_VERSION) throw new Error(`project file version ${d.version} is newer than this program (${PROJECT_VERSION}); update the program`);
    return { model: checkModel(d.model), settings: d.settings ?? {}, savedAt: d.saved_at };
  }
  return { model: checkModel(data), settings: {} };
}

export const safeName = (s: string) => s.replace(/[^\w\-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "model";
