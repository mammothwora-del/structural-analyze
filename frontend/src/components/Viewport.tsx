import { GizmoHelper, GizmoViewport, OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import { BoxSelectOverlay, SelectProbe } from "../three/BoxSelect";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { combinedResult } from "../lib/combine";
import { displayValues } from "../lib/display";
import { modelBounds } from "../lib/geometry";
import { computeFlows } from "../lib/loadpath";
import type { Mode } from "../lib/types";
import { useStore } from "../store";
import { ForceDiagrams } from "../three/Diagrams";
import { FlowParticles, PathLabels, TributaryPanels } from "../three/LoadPath";
import { Members } from "../three/Members";
import { Footings, FootingPressure, GridLines, LoadsLayer, NodesLayer, ReactionsLayer, Slabs } from "../three/Overlays";
import { ShellFlowArrows, ShellSurfaces, WallPanels } from "../three/Shells";
import { Hinges } from "../three/Hinges";
import { shellScale } from "../lib/shells";
import { Legend } from "./Legend";
import { StabilityPanel } from "./StabilityPanel";
import { DesignPanel, deflDisplay, designDisplay } from "./DesignPanel";
import { BucklingShape } from "../three/BucklingShape";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

export const MODES: { id: Mode; label: string; needs?: boolean; key: string }[] = [
  { id: "model", label: "Model", key: "1" },
  { id: "loads", label: "Loads", key: "2" },
  { id: "loadpath", label: "Load Path", needs: true, key: "3" },
  { id: "stress", label: "Stress", needs: true, key: "4" },
  { id: "deformation", label: "Deformation", needs: true, key: "5" },
  { id: "forces", label: "Internal Forces", needs: true, key: "6" },
  { id: "reactions", label: "Foundation Reactions", needs: true, key: "7" },
  { id: "stability", label: "Stability", key: "8" },
  { id: "design", label: "Design", key: "9" },
];

type ViewName = "iso" | "top" | "front" | "right";

function CameraRig({ view, nonce }: { view: ViewName; nonce: number }) {
  const { camera, controls } = useThree() as unknown as { camera: THREE.Camera & { zoom: number; updateProjectionMatrix: () => void }; controls: { target: THREE.Vector3; update: () => void } | null };
  const model = useStore((s) => s.model);
  useEffect(() => {
    if (!model) return;
    const b = modelBounds(model);
    const c = new THREE.Vector3(...b.center);
    const d = b.size * 2.3;
    const dirs: Record<ViewName, THREE.Vector3> = {
      iso: new THREE.Vector3(-0.9, -1.25, 0.8), top: new THREE.Vector3(0, -0.001, 1), front: new THREE.Vector3(0, -1, 0.0001), right: new THREE.Vector3(1, 0, 0.0001),
    };
    camera.position.copy(c.clone().addScaledVector(dirs[view].normalize(), d));
    camera.up.set(0, 0, 1);
    if ((camera as THREE.OrthographicCamera).isOrthographicCamera) { camera.zoom = 900 / (b.size * 1.5); camera.updateProjectionMatrix(); }
    if (controls) { controls.target.copy(c); controls.update(); }
    else camera.lookAt(c);
  }, [view, nonce, model?.name, model?.nodes.length, controls]);
  return null;
}

export function Viewport() {
  const s = useStore();
  const { model, results, mode, loadSel, forceComp, deformScale, pathDir, trace, ortho, showLabels, selection, colorTransform, shellComp } = s;
  const [cam, setCam] = useState<{ view: ViewName; nonce: number }>({ view: "iso", nonce: 0 });
  const wrap = useRef<HTMLDivElement>(null);

  const stale = s.resultsStale;
  const usable = results && !stale ? results : null;
  const flows = useMemo(() => (model && usable && (mode === "loadpath") ? computeFlows(model, usable, loadSel, pathDir) : null), [model, usable, loadSel, pathDir, mode]);
  const display = useMemo(() => (model ? displayValues(mode, model, usable, loadSel, forceComp, flows, colorTransform) : null), [mode, model, usable, loadSel, forceComp, flows, colorTransform]);
  const res = useMemo(() => (model && usable ? combinedResult(model, usable, loadSel) : null), [model, usable, loadSel]);
  const hasMesh = !!usable?.mesh;
  const shellSlabs = usable?.slab_model === "shell";
  const sScale = useMemo(() => (usable && res && hasMesh && mode === "stress" ? shellScale(res, usable, shellComp) : null), [usable, res, hasMesh, mode, shellComp]);
  // slabs/walls drawn as plain panels when there is no shell mesh to show
  const panels = (op?: number) => (<>{s.showSlabs && <Slabs model={model!} opacity={op} />}<WallPanels model={model!} /></>);

  const setView = (v: ViewName) => setCam((c) => ({ view: v, nonce: c.nonce + 1 }));

  if (!model) return <div className="flex-1 grid place-items-center text-ink-400">Generate or open a model to start.</div>;

  const needsResults = MODES.find((m) => m.id === mode)?.needs;
  const showResults = needsResults && usable && res;
  const trMax = trace ? Math.max(...Object.values(trace.elements)) : 1;
  const bMode = mode === "stability" ? s.buckling?.modes[s.bucklingMode] ?? null : null;
  const dDisplay = mode === "design" ? (s.designTab === "defl" ? deflDisplay(s.defl) : designDisplay(s.designTab === "rc" ? s.rc : s.steel)) : null;

  return (
    <div ref={wrap} className="relative flex-1 min-h-0 bg-[radial-gradient(ellipse_at_center,_#16202b_0%,_#0b0f14_75%)]">
      <Canvas dpr={[1, 2]} gl={{ antialias: true, preserveDrawingBuffer: true }} onPointerMissed={() => useStore.setState({ selection: null, multi: [] })}>
        {ortho ? <OrthographicCamera makeDefault near={-1000} far={5000} /> : <PerspectiveCamera makeDefault fov={40} near={0.1} far={5000} />}
        <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
        <CameraRig view={cam.view} nonce={cam.nonce + (ortho ? 1000 : 0)} />
        <ambientLight intensity={0.55} />
        <directionalLight position={[-30, -40, 60]} intensity={1.1} />
        <directionalLight position={[40, 30, 20]} intensity={0.35} />
        <hemisphereLight args={["#bcd3ff", "#1a1f26", 0.35]} />

        <GridLines model={model} />
        <SelectProbe model={model} />

        {/* MODEL & LOADS */}
        {mode === "stability" && (
          <>
            <Members model={model} results={null} display={null} deform={0} colorMode="neutral" opacity={bMode ? 0.4 : 1} />
            {panels(0.06)}
            {bMode && <BucklingShape mode={bMode} scale={modelBounds(model).size * 0.1 * deformScale / 50} />}
          </>
        )}

        {mode === "design" && (
          <>
            <Members model={model} results={null} display={dDisplay} deform={0} colorMode={dDisplay ? "values" : "type"} />
            {panels(0.06)}
            <Hinges model={model} />
          </>
        )}

        {mode !== "stability" && mode !== "design" && (mode === "model" || mode === "loads" || !showResults) && (
          <>
            <Members model={model} results={usable} display={null} deform={0} colorMode={mode === "loads" ? "neutral" : "type"} />
            {panels()}
            <Footings model={model} results={usable} res={null} />
            {mode === "model" && <NodesLayer model={model} />}
            {(mode === "model" || mode === "loads") && <Hinges model={model} />}
            {mode === "loads" && <LoadsLayer model={model} results={usable} />}
          </>
        )}

        {/* LOAD PATH */}
        {showResults && mode === "loadpath" && flows && display && (
          <>
            <Members model={model} results={usable} display={display} deform={0} colorMode="values" highlight={trace?.elements ?? null} highlightMax={trMax} opacity={0.55} />
            {!shellSlabs && s.showSlabs && <TributaryPanels model={model} results={usable!} highlightSlab={selection?.kind === "slab" ? selection.id : null} />}
            {hasMesh && <ShellSurfaces model={model} results={usable!} res={res} colorMode="type" opacity={0.3} edges={false} />}
            {hasMesh && <ShellFlowArrows model={model} results={usable!} res={res!} d={flows.d} />}
            {!hasMesh && <WallPanels model={model} />}
            <FlowParticles model={model} results={usable!} flows={flows} trace={trace} />
            <Footings model={model} results={usable} res={res} />
            <ReactionsLayer model={model} res={res!} labels={false} />
            {showLabels && <PathLabels model={model} results={usable!} flows={flows} trace={trace} res={res!} />}
          </>
        )}

        {showResults && mode === "stress" && (
          <>
            <Members model={model} results={usable} display={display} deform={0} colorMode="values" />
            {hasMesh ? <ShellSurfaces model={model} results={usable!} res={res} colorMode="values" comp={shellComp} scale={sScale} /> : panels(0.12)}
            <Footings model={model} results={usable} res={res} />
          </>
        )}

        {showResults && mode === "deformation" && (
          <>
            <Members model={model} results={usable} display={null} deform={0} colorMode="neutral" opacity={0.18} />
            <Members model={model} results={usable} display={display} deform={deformScale} colorMode="values" />
            {hasMesh ? <ShellSurfaces model={model} results={usable!} res={res} colorMode="disp" scale={display?.scale} deform={deformScale} /> : panels(0.08)}
            <Footings model={model} results={usable} res={res} />
          </>
        )}

        {showResults && mode === "forces" && (
          <>
            <Members model={model} results={usable} display={null} deform={0} colorMode="neutral" />
            <ForceDiagrams model={model} results={usable!} res={res!} comp={forceComp} />
            <Hinges model={model} />
            {hasMesh ? <ShellSurfaces model={model} results={usable!} res={res} colorMode="type" opacity={0.18} edges={false} /> : panels(0.1)}
            <Footings model={model} results={usable} res={res} />
          </>
        )}

        {showResults && mode === "reactions" && (
          <>
            <Members model={model} results={usable} display={null} deform={0} colorMode="neutral" opacity={0.35} />
            {hasMesh ? <ShellSurfaces model={model} results={usable!} res={res} colorMode="neutral" opacity={0.2} edges={false} /> : panels(0.1)}
            <Footings model={model} results={usable} res={res} colorBy="pressure" />
            <ReactionsLayer model={model} res={res!} labels={showLabels} />
            <FootingPressure model={model} res={res!} />
          </>
        )}

        <GizmoHelper alignment="bottom-left" margin={[64, 64]}>
          <GizmoViewport axisColors={["#ff5a5f", "#3ddc84", "#4ea8ff"]} labelColor="#0b0f14" />
        </GizmoHelper>
      </Canvas>

      <BoxSelectOverlay />
      <ModeBar />
      <ViewTools onView={setView} wrap={wrap} />
      {showResults && display && <Legend display={display} flows={flows} shellScale={sScale} />}
      {needsResults && !usable && (
        <div className="absolute inset-x-0 top-16 mx-auto w-fit rounded border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-amber-200 text-xs">
          {stale ? "The model changed since the last analysis. Run ANALYZE to update results." : "Run ANALYZE to calculate results for this mode."}
        </div>
      )}
      {showResults && mode === "loadpath" && <LoadPathBadge />}
      {mode === "loads" && <LoadsInfo />}
      {mode === "stability" && <StabilityPanel />}
      {mode === "design" && <DesignPanel model={model} />}
      {bMode && (
        <div className="absolute left-1/2 -translate-x-1/2 bottom-3 rounded-md border border-ink-700 bg-ink-900/90 px-3 py-1.5 text-[11px] text-ink-300 backdrop-blur">
          <b className="text-emerald-300">CALCULATED</b> buckling mode {s.bucklingMode + 1}, α<sub>cr</sub> = <b className="text-ink-100 num">{bMode.factor.toFixed(3)}</b>
          <span className="text-ink-600"> | </span>shape scaled for display (a mode has no size); colour = relative amplitude
        </div>
      )}
    </div>
  );
}

function ModeBar() {
  const { mode, set, results } = useStore();
  return (
    <div className="absolute left-1/2 -translate-x-1/2 top-2 flex gap-0.5 rounded-md border border-ink-700 bg-ink-900/90 p-0.5 backdrop-blur shadow-lg">
      {MODES.map((m) => (
        <button key={m.id} title={`${m.label} (${m.key})`} onClick={() => set({ mode: m.id })}
          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${mode === m.id ? "bg-accent text-ink-950 font-semibold" : "text-ink-300 hover:bg-ink-700"} ${m.needs && !results ? "opacity-50" : ""}`}>
          {m.label}
        </button>
      ))}
    </div>
  );
}

function ViewTools({ onView, wrap }: { onView: (v: ViewName) => void; wrap: React.RefObject<HTMLDivElement> }) {
  const { ortho, set, showLabels, animate, showSlabs, showDims, labelSize, boxSelect } = useStore();
  const setSize = (v: number) => { set({ labelSize: v }); try { localStorage.setItem("labelSize", String(v)); } catch { /* storage unavailable */ } };
  const B = ({ on, children, onClick, title }: { on?: boolean; children: React.ReactNode; onClick: () => void; title: string }) => (
    <button title={title} onClick={onClick} className={`w-full px-2 py-1 rounded text-[11px] text-left ${on ? "bg-accent/20 text-accent" : "text-ink-300 hover:bg-ink-700"}`}>{children}</button>
  );
  return (
    <div className="absolute left-2 top-2 w-[92px] flex flex-col gap-0.5 rounded-md border border-ink-700 bg-ink-900/90 p-1 backdrop-blur">
      <div className="panel-title px-1 pb-0.5">View</div>
      <B title="Isometric" onClick={() => onView("iso")}>Iso</B>
      <B title="Plan view" onClick={() => onView("top")}>Top</B>
      <B title="Front elevation (XZ)" onClick={() => onView("front")}>Front</B>
      <B title="Side elevation (YZ)" onClick={() => onView("right")}>Right</B>
      <div className="h-px bg-ink-700 my-0.5" />
      <B title="Orthographic / perspective" on={ortho} onClick={() => set({ ortho: !ortho })}>{ortho ? "Ortho" : "Persp."}</B>
      <B title="Numeric labels" on={showLabels} onClick={() => set({ showLabels: !showLabels })}>Labels</B>
      <B title="Animate loads / flow / deformation" on={animate} onClick={() => set({ animate: !animate })}>Animate</B>
      <B title="Show slabs" on={showSlabs} onClick={() => set({ showSlabs: !showSlabs })}>Slabs</B>
      <B title="Dimensions between grid lines" on={showDims} onClick={() => set({ showDims: !showDims })}>Dims</B>
      <B title="Drag a box to select members (B)" on={boxSelect} onClick={() => set({ boxSelect: !boxSelect })}>Box select</B>
      <label className="px-1 pt-0.5 text-[10px] text-ink-400" title="Size of grid names and dimension text">
        <div className="flex justify-between"><span>Text size</span><span>{Math.round(labelSize * 100)}%</span></div>
        <input type="range" min={0.6} max={3} step={0.1} value={labelSize} aria-label="Grid and dimension text size"
          className="w-full accent-sky-400" onChange={(e) => setSize(+e.target.value)} />
      </label>
      <B title="Fullscreen" onClick={() => { if (document.fullscreenElement) document.exitFullscreen(); else wrap.current?.requestFullscreen(); }}>Fullscreen</B>
    </div>
  );
}

function LoadPathBadge() {
  const { trace, set, results } = useStore();
  return (
    <div className="absolute left-1/2 -translate-x-1/2 bottom-3 flex items-center gap-3 rounded-md border border-ink-700 bg-ink-900/90 px-3 py-1.5 text-[11px] text-ink-300 backdrop-blur">
      <span><b className="text-emerald-300">CALCULATED</b> member flows from FEM internal forces</span>
      <span className="text-ink-600">|</span>
      {results?.slab_model === "shell"
        ? <span><b className="text-emerald-300">CALCULATED</b> slab → beam transfer and slab/wall load flux (shell FEM)</span>
        : <span><b className="text-amber-300">ASSUMED</b> slab → beam tributary areas (slab analysis = tributary)</span>}
      {trace && (<>
        <span className="text-ink-600">|</span>
        <span>Tracing {trace.direction === "down" ? "down from" : "up to"} <b className="text-accent">{trace.start}</b> ({trace.total.toFixed(1)} kN, proportional sharing)</span>
        <button className="btn" onClick={() => set({ trace: null })}>Clear trace</button>
      </>)}
    </div>
  );
}

function LoadsInfo() {
  const { model, loadSel, results } = useStore();
  if (!model) return null;
  const combo = model.combinations.find((c) => c.id === loadSel);
  const factors = combo ? combo.factors : { [loadSel]: 1 };
  return (
    <div className="absolute right-2 top-12 w-[230px] rounded-md border border-ink-700 bg-ink-900/92 p-2.5 text-[11px] backdrop-blur">
      <div className="panel-title mb-1">Applied loads — {loadSel}</div>
      {Object.entries(factors).map(([c, f]) => {
        const lc = model.load_cases.find((x) => x.id === c);
        const r = results?.cases[c];
        return (
          <div key={c} className="py-1 border-b border-ink-800">
            <div className="flex justify-between"><span className="font-mono text-ink-200">{f} × {c}</span><span className="num text-ink-300">{r ? `ΣFz ${(f * r.equilibrium.applied[2]).toFixed(0)} kN` : ""}</span></div>
            <div className="text-ink-400">{lc?.name}{lc?.self_weight ? " · incl. self-weight (members, slabs, walls)" : ""} · {model.loads.filter((l) => l.case === c).length} load items</div>
          </div>
        );
      })}
      <div className="mt-1.5 space-y-0.5 text-ink-400">
        <div><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: "#ff9d3b" }} />Area loads on slabs (kN/m²)</div>
        <div><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: "#ff4d6d" }} />Nodal / point loads (kN)</div>
        <div><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: "#ffd166" }} />Member line loads (kN/m)</div>
        <div>Turn on Labels to show magnitudes.</div>
      </div>
    </div>
  );
}
