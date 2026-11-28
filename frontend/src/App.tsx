import LongformPage from "./pages/Longform";
import CampaignsPage from "./pages/Campaigns";
import { useEffect, useRef } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./lib/api";
import { MODULES } from "./lib/modules";
import Dashboard from "./pages/Dashboard";
import Sources from "./pages/Sources";
import Destinations from "./pages/Destinations";
import SettingsPage from "./pages/Settings";
import Planned from "./pages/Planned";
import Ready from "./pages/Ready";
import ActivityPage from "./pages/Activity";
import UpdateBanner from "./components/UpdateBanner";
import UpdateNow from "./components/UpdateNow";
import AnalyticsPage from "./pages/AnalyticsPage";
import EditorPage from "./pages/Editor";
import { useToast } from "./components/ui";

const PAGES: Record<string, JSX.Element> = {
  "/": <Dashboard />, "/ready": <Ready />, "/activity": <ActivityPage />, "/sources": <Sources />, "/destinations": <Destinations />,
  "/settings": <SettingsPage />, "/analytics": <AnalyticsPage />, "/editor": <EditorPage />, "/longform": <LongformPage />, "/campaigns": <CampaignsPage />,
};

/** A short "ding" (two sine tones), made in code: no sound file to ship. Browsers allow it after you've clicked the app. */
function ding() {
  try {
    const ac = new AudioContext();
    for (const [f, at] of [[880, 0], [1320, 0.12]] as const) {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = "sine"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, ac.currentTime + at);
      g.gain.exponentialRampToValueAtTime(0.3, ac.currentTime + at + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + at + 0.5);
      o.connect(g).connect(ac.destination); o.start(ac.currentTime + at); o.stop(ac.currentTime + at + 0.55);
    }
    setTimeout(() => void ac.close(), 1000);
  } catch { /* no audio here: the toast still shows */ }
}

/** Pings when a video goes out (the extension posted it, Muse reported it or you saved its link). */
function PostedPing() {
  const toast = useToast();
  const seen = useRef<Set<number> | null>(null);
  const { data } = useQuery({ queryKey: ["posted-ping"], queryFn: () => api.clips("uploaded"), refetchInterval: 10_000 });
  useEffect(() => {
    if (!data) return;
    const up = data.flatMap((c) => c.outputs.filter((o) => o.status === "uploaded"));
    if (seen.current) {
      const fresh = up.filter((o) => !seen.current!.has(o.id));
      if (fresh.length) ding();
      for (const o of fresh) toast("ok", `Posted to ${o.destination?.display_name || o.destination?.handle || o.platform}`);
    }
    seen.current = new Set(up.map((o) => o.id));
  }, [data, toast]);
  return null;
}

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
          {health && <span className="row" style={{ gap: 4 }}>v{health.version}<UpdateNow /></span>}
        </div>
      </aside>
      <main className="main">
        <UpdateBanner />
        <PostedPing />
        <Routes>
          {MODULES.map((m) => (
            <Route key={m.path} path={m.path} element={PAGES[m.path] ?? <Planned module={m} />} />
          ))}
          <Route path="/editor/:clipId" element={<EditorPage />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
