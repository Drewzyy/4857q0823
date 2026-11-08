import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, Bell, Eye, HardDrive } from "lucide-react";
import { api } from "../lib/api";
import { bytes, ErrorNote, Loading, relTime, StatusPill } from "../components/ui";

const JOB_LABEL: Record<string, string> = {
  "clip.build": "Making a clip", "source.check": "Checking an account for new posts", "notify.discord": "Discord ping",
  "storage.cleanup": "Deleting expired clips", "connections.refresh_due": "Housekeeping",
};

function Stat({ label, value, sub, to, accent }: { label: string; value: number; sub?: string; to?: string; accent?: boolean }) {
  const body = (
    <div className="card stat" style={{ height: "100%", borderColor: accent && value ? "rgba(139,92,246,.45)" : undefined }}>
      <div className="label">{label}</div>
      <div className="value" style={{ color: accent && value ? "var(--accent-hi)" : undefined }}>{value.toLocaleString()}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
  return to ? <Link to={to} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link> : body;
}

export default function Dashboard() {
  const { data: d, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 10_000 });
  const notif = useQuery({ queryKey: ["notifications"], queryFn: api.notifications });
  if (isLoading) return <div className="page"><Loading /></div>;
  if (!d) return <div className="page"><ErrorNote error={error} /></div>;
  const a = d.accounts, p = d.pipeline, m = d.monitoring;
  const usedPct = d.storage.disk_total_bytes ? (1 - d.storage.disk_free_bytes / d.storage.disk_total_bytes) * 100 : 0;
  const setupDone = a.sources_total > 0 && a.destinations_total > 0 && a.routes > 0;

  return (
    <div className="page">
      <div className="page-head"><div><h1>Dashboard</h1><p>Vyral keeps watching your source accounts and making clips as long as it's running, even with this window closed.</p></div></div>

      {!setupDone && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h2>Set up in 4 steps</h2>
          <div className="grid cols-4" style={{ marginTop: 12 }}>
            {[["1", "Add creators + sources", "The clipping accounts to watch, and whose streams they clip.", "/sources", a.sources_total > 0],
              ["2", "Add destinations", "Your pages, with their handles.", "/destinations", a.destinations_total > 0],
              ["3", "Wire the funnel", "Which sources feed which pages.", "/funnel", a.routes > 0],
              ["4", "Discord pings", "Optional: get notified.", "/settings?tab=notifications", !!notif.data?.configured]].map(([n, t, s, to, done]) => (
              <Link key={String(n)} to={String(to)} className="card" style={{ background: "var(--card-2)", color: "inherit", textDecoration: "none" }}>
                <div className="row"><span className={`pill ${done ? "ok" : "accent"} nodot`}>{done ? "Done" : String(n)}</span><strong>{t}</strong><span className="spacer" /><ArrowRight size={14} /></div>
                <p className="muted small" style={{ marginTop: 6 }}>{s}</p>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="grid cols-4">
        <Stat label="Ready to upload" value={p.ready_to_upload} sub="Clip + caption per page" to="/ready" accent />
        <Stat label="Being made now" value={p.in_progress} sub="Finding the moment and rendering" to="/activity" />
        <Stat label="New posts detected" value={p.posts_detected} sub={`From ${m.watching} watched account${m.watching === 1 ? "" : "s"}`} to="/activity" />
        <Stat label="Uploaded" value={p.uploaded} sub={`${p.clips_made} clip${p.clips_made === 1 ? "" : "s"} made in total`} to="/ready" />
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <div className="card-head"><div className="row"><Eye size={16} /><h2>Monitoring</h2></div>
            <span className={`pill ${m.enabled ? "ok" : ""}`}>{m.enabled ? "On" : "Paused"}</span></div>
          <div className="list-row small"><span className="muted">Accounts watched</span><span className="spacer" />{m.watching}</div>
          <div className="list-row small"><span className="muted">Check frequency</span><span className="spacer" />Every {m.interval_minutes} minutes</div>
          <div className="list-row small"><span className="muted">Last check</span><span className="spacer" />{relTime(m.last_check)}</div>
          <div className="list-row small"><span className="muted">Accounts with check problems</span><span className="spacer" />
            {m.errors ? <Link to="/sources" style={{ color: "#ff8a8d" }}>{m.errors}</Link> : 0}</div>
          <div className="list-row small"><span className="muted">Needs your attention (7 days)</span><span className="spacer" />
            {p.needs_attention ? <Link to="/activity" style={{ color: "var(--warn)" }}>{p.needs_attention}</Link> : 0}</div>
          <div className="list-row small"><Bell size={13} /><span className="muted">Discord</span><span className="spacer" />
            {notif.data?.configured ? <span className="pill ok">Connected</span> : <Link to="/settings?tab=notifications">Set up</Link>}</div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><div className="row"><Activity size={16} /><h2>Background work</h2></div></div>
            {d.jobs.recent.length === 0 ? <p className="muted small">Nothing yet.</p> :
              d.jobs.recent.map((j) => (
                <div className="list-row small" key={j.id}><span>{JOB_LABEL[j.kind] ?? j.kind}</span><span className="spacer" /><span className="faint">{relTime(j.created_at)}</span><StatusPill status={j.status} /></div>
              ))}
          </div>
          <div className="card">
            <div className="card-head"><div className="row"><HardDrive size={16} /><h2>Storage</h2></div><span className="small faint">{bytes(d.storage.used_bytes)} used by Vyral</span></div>
            <div className="bar" aria-label="Disk usage"><div style={{ width: `${usedPct}%` }} /></div>
            <div className="row small muted" style={{ marginTop: 8 }}><span>{bytes(d.storage.disk_free_bytes)} free of {bytes(d.storage.disk_total_bytes)}</span><span className="spacer" />
              <span>Clips auto-delete after {m.retention_days} days</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}
