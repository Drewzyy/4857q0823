import { useEffect } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./lib/api";
import { MODULES } from "./lib/modules";
import Dashboard from "./pages/Dashboard";
import Sources from "./pages/Sources";
import Destinations from "./pages/Destinations";
import FunnelPage from "./pages/Funnel";
import SettingsPage from "./pages/Settings";
import Planned from "./pages/Planned";
import Ready from "./pages/Ready";
import ActivityPage from "./pages/Activity";
import UpdateBanner from "./components/UpdateBanner";
import AnalyticsPage from "./pages/AnalyticsPage";

const PAGES: Record<string, JSX.Element> = {
  "/": <Dashboard />, "/ready": <Ready />, "/activity": <ActivityPage />, "/sources": <Sources />, "/destinations": <Destinations />,
  "/funnel": <FunnelPage />, "/settings": <SettingsPage />, "/analytics": <AnalyticsPage />,
};

export default function App() {
  const nav = useNavigate();
  const { data: health, isError } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: Infinity, retry: 3 });
  const { data: dash } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 15_000 });
  const readyCount = dash?.pipeline.ready_to_upload ?? 0;

  // ⌘1…⌘9 jump between sections, ⌘, opens Settings.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      if (e.key === ",") { e.preventDefault(); nav("/settings"); return; }
      const n = Number(e.key);
      if (n >= 1 && n <= 9 && MODULES[n - 1]) { e.preventDefault(); nav(MODULES[n - 1].path); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav]);

  let lastGroup = "";
  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand"><img className="brand-logo" src="/vyral-logo.png" alt="" />Vyral</div>
        <nav>
          {MODULES.map((m, i) => {
            const header = m.group && m.group !== lastGroup ? <div className="nav-group">{m.group}</div> : m.group === "" && lastGroup !== "" ? <div style={{ height: 14 }} /> : null;
            lastGroup = m.group;
            const Icon = m.icon;
            return (
              <div key={m.path}>
                {header}
                <NavLink to={m.path} end={m.path === "/"} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
                  title={i < 9 ? `⌘${i + 1}` : m.path === "/settings" ? "⌘," : undefined}>
                  <Icon size={16} />{m.label}{m.status === "planned" && <span className="soon">Soon</span>}
                  {m.path === "/ready" && readyCount > 0 && <span className="pill accent nodot" style={{ marginLeft: "auto" }}>{readyCount}</span>}
                </NavLink>
              </div>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <span className={`pill ${isError ? "err" : health ? "ok" : ""}`}>{isError ? "Service offline" : health ? (dash?.monitoring.enabled ? "Watching" : "Paused") : "Starting…"}</span>
          {health && <span>v{health.version}</span>}
        </div>
      </aside>
      <main className="main">
        <UpdateBanner />
        <Routes>
          {MODULES.map((m) => (
            <Route key={m.path} path={m.path} element={PAGES[m.path] ?? <Planned module={m} />} />
          ))}
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
