export type Vec3 = [number, number, number];

export interface Node { id: string; x: number; y: number; z: number; level?: number; grid?: string }
export interface Section { name?: string; shape: "rect" | "I" | "circle" | "pipe" | "box" | "general"; material: string; b?: number; h?: number; bf?: number; tf?: number; tw?: number; d?: number; t?: number; A?: number; Iy?: number; Iz?: number; J?: number;
  /** "rolled" | "welded" (I) or "cold" | "hot" (hollow); catalog = standard size name when picked from the tables */
  fab?: string; catalog?: string }
export interface Material { name: string; kind: string; E: number; nu: number; density: number; fck?: number; fy?: number }
/** End releases: 6 flags per end in local axes [ux, uy, uz, rx, ry, rz], 1 = released (only rotations allowed). */
export interface Releases { i?: number[]; j?: number[] }
export interface Element { id: string; type: "column" | "beam" | "brace" | "truss"; role?: string; i: string; j: string; section: string; level?: number; label?: string; roll?: number; truss?: boolean; releases?: Releases;
  /** steel design settings: effective length factors, unbraced length for LTB (m), moment gradient factor */
  design?: { Ky?: number; Kz?: number; Lb?: number; Cb?: number } }
export interface Slab { id: string; corners: string[]; thickness: number; density?: number; material?: string; span_type?: string; level?: number; label?: string }
export interface Wall { id: string; corners: string[]; thickness: number; density?: number; material?: string; level?: number; base_support?: string | null; label?: string }
export interface Footing { B: number; L: number; t: number; type?: string; label?: string }
export interface Support { node: string; type?: "fixed" | "pinned" | "roller"; dofs?: number[]; footing?: Footing; lateral?: boolean }
export interface LoadCase { id: string; name: string; type: string; self_weight?: boolean }
export interface Load {
  case: string; kind: "nodal" | "dist" | "point" | "area"; label?: string;
  node?: string; values?: number[];
  element?: string; direction?: number[]; points?: number[][]; a?: number; P?: number;
  slab?: string; slabs?: string[]; q?: number; relative?: boolean;
  source?: { type: string; slab: string; edge: number; q: number };
}
export interface Combination { id: string; name: string; factors: Record<string, number> }
export interface Model {
  name: string;
  settings: { standard: string; allowable_bearing: number; stress_limit_concrete: number; stress_limit_steel: number; slab_model?: "shell" | "tributary"; mesh_size?: number };
  grid?: { x: { name: string; pos: number }[]; y: { name: string; pos: number }[]; levels: { name: string; z: number }[] };
  materials: Record<string, Material>;
  sections: Record<string, Section>;
  nodes: Node[]; elements: Element[]; slabs: Slab[]; walls?: Wall[]; supports: Support[];
  load_cases: LoadCase[]; loads: Load[]; combinations: Combination[];
  generator?: Record<string, unknown>;
  notes?: string[];
}

export interface Stations {
  x: number[]; N: number[]; Vy: number[]; Vz: number[]; T: number[]; My: number[]; Mz: number[];
  disp: number[][]; sigma_max: number[]; sigma_min: number[];
  end_i: number[]; end_j: number[];
}
export interface CaseResult {
  case: string;
  displacements: Record<string, number[]>;
  reactions: Record<string, number[]>;
  elements: Record<string, Stations>;
  equilibrium: { applied: number[]; reactions: number[]; force_error: number; moment_error: number; ok: boolean; residual: number };
  warnings: Warning[];
  /** per slab/wall panel, per panel node: nodal-averaged [Nx, Ny, Nxy, Mx, My, Mxy, Qx, Qy] (local axes) */
  panel_results?: Record<string, number[][]>;
  /** force (global, kN) each panel delivers to a member along its length: member -> panel -> [Fx, Fy, Fz] */
  panel_transfer?: Record<string, Record<string, number[]>>;
  /** force (global) the shells exert on each node of the user's model */
  shell_node_force?: Record<string, number[]>;
}
export interface MeshGroup { kind: "slab" | "wall"; t: number; nodes: string[]; quads: number[][]; axes: number[][] }
export interface Mesh { size: number; nodes: Record<string, number[]>; groups: Record<string, MeshGroup> }
export interface Warning { level: "info" | "warning" | "error"; code: string; message: string; case?: string; nodes?: string[]; dofs?: string[] }
export interface ElementInfo { L: number; axes: number[][]; releases?: number[][]; props: { A: number; Iy: number; Iz: number; J: number; Sy: number; Sz: number; b: number; h: number }; E: number; G: number; material: string }
export interface TribEdge { edge: number; length: number; tributary_area: number; fraction: number; polygon: number[][]; segments: { element: string; s0: number; s1: number; points: number[][] }[]; lost_area: number }
export interface Tributary { mode: string; area: number; lx: number; ly: number; effective_area: number; edges: TribEdge[]; z: number }
export interface Results {
  ok: boolean; warnings: Warning[]; log: string[];
  elements: Record<string, ElementInfo>;
  unstable_dofs: number[];
  tributary: Record<string, Tributary>;
  member_loads: Record<string, Load[]>;
  nodal_loads: Load[];
  cases: Record<string, CaseResult>;
  mesh?: Mesh | null;
  slab_model?: "shell" | "tributary";
  solver: { type: string; ndof: number; nnz: number; time_ms: number };
}

export type Mode = "model" | "loads" | "loadpath" | "stress" | "deformation" | "forces" | "reactions" | "stability" | "design";
export type ForceComp = "N" | "Vy" | "Vz" | "T" | "My" | "Mz";

export interface BucklingMode {
  factor: number;
  /** normalised mode displacement (max translation = 1) per node */
  nodes: Record<string, number[]>;
  /** per member, points from end i to end j: [x, y, z, ux, uy, uz] */
  members: Record<string, number[][]>;
}
export interface BucklingResult { kind: "buckling"; load: string; load_name: string; factors: Record<string, number>; n_seg: number; modes: BucklingMode[]; notes: string[]; warnings: Warning[]; ndof: number; time_ms: number }
export interface PDeltaResult {
  kind: "pdelta"; load: string; load_name: string; factors: Record<string, number>; converged: boolean; iterations: number; history: number[];
  amplification: number; max_disp_linear: number; max_disp_pdelta: number; result: CaseResult; warnings: Warning[]; notes: string[]; time_ms: number;
}

export interface SteelCheck { id: string; name: string; clause: string; demand: number; capacity: number; unit: "force" | "moment" | "ratio"; ratio: number; combo: string; x: number; detail: Record<string, number | string> }
export interface SteelMember {
  id: string; section: string; material: string; status: "ok" | "fail" | "not_covered" | "skipped"; util: number | null;
  reason?: string; governing?: SteelCheck | null; checks?: SteelCheck[]; notes?: string[];
  params?: { L: number; Ky: number; Kz: number; Lb: number; Cb: number | null; fy: number };
  props?: Record<string, number | string | null>;
}
export interface SteelDesignResult {
  code: "AISC360" | "EC3" | "EIT"; code_name: string; combinations: string[]; members: Record<string, SteelMember>;
  summary: { ok: number; fail: number; not_covered: number; skipped: number; max_util: number | null; n_checked: number };
  notes: string[];
}

export interface RcMember extends Omit<SteelMember, "params" | "props"> {
  kind?: "beam" | "column";
  params?: { fc_ksc: number; fy_ksc: number; fyt_ksc: number; L: number };
  /** beams: bottom/top/stirrups/side; columns: bars/layout/rho_percent/ties. sketch = [y, z, db] in m from the centre */
  rebar?: Record<string, string | number> & { sketch?: number[][] };
}
export interface RcDesignResult {
  code: "EIT1008"; code_name: string; combinations: string[]; members: Record<string, RcMember>;
  options: { main_grade: string; tie_grade: string; cover: number };
  summary: SteelDesignResult["summary"]; notes: string[];
}

/** Standard steel size (nominal dimensions in m, A in m², mass in kg/m). */
export interface CatalogEntry { family: "H" | "SHS" | "RHS" | "CHS"; name: string; shape: "I" | "box" | "pipe"; fab: string; h?: number; bf?: number; tw?: number; tf?: number; b?: number; t?: number; d?: number; A: number; mass: number }
export interface SteelCatalog { families: Record<string, string>; sections: CatalogEntry[] }
export interface SuggestGroup {
  section: string; locked: boolean; families: string[]; from: string; to: string; changed: boolean; n_members: number;
  max_util: number | null; n_fail: number; mass_before: number | null; mass_after: number | null; largest_too_small: boolean;
}
export interface SuggestResult {
  code: string; code_name: string; target: number; converged: boolean; limit_slenderness: boolean; iterations: number; groups: SuggestGroup[];
  sections: Record<string, Section>; design: SteelDesignResult; notes: string[];
}
