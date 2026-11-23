export type Vec3 = [number, number, number];

export interface Node { id: string; x: number; y: number; z: number; level?: number; grid?: string }
export interface Section { name?: string; shape: "rect" | "I" | "circle" | "general"; material: string; b?: number; h?: number; bf?: number; tf?: number; tw?: number; d?: number; A?: number; Iy?: number; Iz?: number; J?: number }
export interface Material { name: string; kind: string; E: number; nu: number; density: number; fck?: number; fy?: number }
export interface Element { id: string; type: "column" | "beam" | "brace"; role?: string; i: string; j: string; section: string; level?: number; label?: string; roll?: number }
export interface Slab { id: string; corners: string[]; thickness: number; span_type?: string; level?: number; label?: string }
export interface Footing { B: number; L: number; t: number; type?: string; label?: string }
export interface Support { node: string; type?: "fixed" | "pinned" | "roller"; dofs?: number[]; footing?: Footing }
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
  settings: { standard: string; allowable_bearing: number; stress_limit_concrete: number; stress_limit_steel: number };
  grid?: { x: { name: string; pos: number }[]; y: { name: string; pos: number }[]; levels: { name: string; z: number }[] };
  materials: Record<string, Material>;
  sections: Record<string, Section>;
  nodes: Node[]; elements: Element[]; slabs: Slab[]; supports: Support[];
  load_cases: LoadCase[]; loads: Load[]; combinations: Combination[];
  generator?: Record<string, unknown>;
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
}
export interface Warning { level: "info" | "warning" | "error"; code: string; message: string; case?: string; nodes?: string[]; dofs?: string[] }
export interface ElementInfo { L: number; axes: number[][]; props: { A: number; Iy: number; Iz: number; J: number; Sy: number; Sz: number; b: number; h: number }; E: number; G: number; material: string }
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
  solver: { type: string; ndof: number; nnz: number; time_ms: number };
}

export type Mode = "model" | "loads" | "loadpath" | "stress" | "deformation" | "forces" | "reactions";
export type ForceComp = "N" | "Vy" | "Vz" | "T" | "My" | "Mz";
