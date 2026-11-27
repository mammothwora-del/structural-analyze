import { useEffect } from "react";
import { BottomPanel } from "./components/BottomPanel";
import { FileDialogs } from "./components/FileDialogs";
import { Dashboard } from "./components/Dashboard";
import { Inspector } from "./components/Inspector";
import { LeftSidebar } from "./components/LeftSidebar";
import { TopBar } from "./components/TopBar";
import { MODES, Viewport } from "./components/Viewport";
import { api } from "./lib/api";
import { useStore } from "./store";
import { visibleMembers } from "./lib/select";
import { elementColorKey } from "./three/Members";

export default function App() {
  const { view, error, set } = useStore();
  useEffect(() => {
    api.health().then((ok) => {
      set({ backendOk: ok });
      if (ok && !useStore.getState().model && !useStore.getState().busy) useStore.getState().generate({});
    });
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); useStore.getState().saveProject(); return; }
      if (useStore.getState().dialog) return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const st = useStore.getState();
      const m = MODES.find((x) => x.key === e.key);
      if (m && !e.ctrlKey && !e.metaKey) st.set({ mode: m.id, view: "3d" });
      if (e.key === "F5") { e.preventDefault(); st.analyze(); }
      if (e.key === "Escape") st.set({ selection: null, multi: [], trace: null, boxSelect: false });
      if ((e.key === "b" || e.key === "B") && !e.ctrlKey && !e.metaKey && st.view === "3d") st.set({ boxSelect: !st.boxSelect });
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && st.model && st.view === "3d") {
        e.preventDefault();
        st.selectMembers(visibleMembers(st.model, st.hiddenTypes, st.maxLevel, st.isolated, elementColorKey).map((x) => x.id));
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); st.undo(); }
      if (e.key === "Delete" && st.multi.length > 1 && !st.selection) {
        const ids = new Set(st.multi);
        if (st.model?.elements.some((x) => ids.has(x.id))) {
          st.editModel((md) => { md.elements = md.elements.filter((x) => !ids.has(x.id)); md.loads = md.loads.filter((l) => !l.element || !ids.has(l.element)); });
          st.set({ multi: [] });
        }
      }
      if (e.key === "Delete" && st.selection?.kind === "element") {
        const id = st.selection.id;
        st.editModel((md) => { md.elements = md.elements.filter((x) => x.id !== id); md.loads = md.loads.filter((l) => l.element !== id); });
        st.set({ selection: null });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="h-full flex flex-col">
      <TopBar />
      {error && (
        <div className="bg-red-500/15 border-b border-red-500/40 text-red-200 text-xs px-3 py-1.5 flex justify-between">
          <span>{error}</span><button onClick={() => set({ error: null })}>✕</button>
        </div>
      )}
      <div className="flex-1 flex min-h-0">
        <LeftSidebar />
        <main className="flex-1 flex flex-col min-w-0">
          {view === "3d" ? <Viewport /> : <Dashboard />}
          <BottomPanel />
        </main>
        <Inspector />
      </div>
      <FileDialogs />
    </div>
  );
}
