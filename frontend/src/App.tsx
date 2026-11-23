import { useEffect } from "react";
import { BottomPanel } from "./components/BottomPanel";
import { Dashboard } from "./components/Dashboard";
import { Inspector } from "./components/Inspector";
import { LeftSidebar } from "./components/LeftSidebar";
import { TopBar } from "./components/TopBar";
import { MODES, Viewport } from "./components/Viewport";
import { api } from "./lib/api";
import { useStore } from "./store";

export default function App() {
  const { view, error, set } = useStore();
  useEffect(() => {
    api.health().then((ok) => {
      set({ backendOk: ok });
      if (ok && !useStore.getState().model && !useStore.getState().busy) useStore.getState().generate({});
    });
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const st = useStore.getState();
      const m = MODES.find((x) => x.key === e.key);
      if (m && !e.ctrlKey && !e.metaKey) st.set({ mode: m.id, view: "3d" });
      if (e.key === "F5") { e.preventDefault(); st.analyze(); }
      if (e.key === "Escape") st.set({ selection: null, multi: [], trace: null });
      if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); st.undo(); }
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
    </div>
  );
}
