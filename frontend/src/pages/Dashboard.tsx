import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, HardDrive, KeyRound, PlugZap } from "lucide-react";
import { api, PLATFORM_LABEL } from "../lib/api";
import { useConnect } from "../components/ConnectFlow";
import { Avatar, bytes, ErrorNote, Loading, PlatformBadge, relTime, StatusPill } from "../components/ui";

function Stat({ label, value, sub, to }: { label: string; value: number | null; sub?: string; to?: string }) {
  const body = (
    <div className="card stat" style={{ height: "100%" }}>
      <div className="label">{label}</div>
      <div className={`value${value === null ? " na" : ""}`}>{value === null ? "—" : value.toLocaleString()}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
  return to ? <Link to={to} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link> : body;
}

export default function Dashboard() {
  const { data: d, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 10_000 });
  const { openSetup } = useConnect();
  if (isLoading) return <div className="page"><Loading /></div>;
  if (!d) return <div className="page"><ErrorNote error={error} /></div>;
  const a = d.accounts;
  const unconfigured = d.platforms.filter((p) => !p.configured);
  const usedPct = d.storage.disk_total_bytes ? (1 - d.storage.disk_free_bytes / d.storage.disk_total_bytes) * 100 : 0;
  const jobTotal = Object.values(d.jobs.by_status).reduce((x, y) => x + y, 0);

  return (
    <div className="page">
      <div className="page-head"><div><h1>Dashboard</h1><p>Everything here is read live from your local database. A dash means the number isn't tracked yet, not zero.</p></div></div>

      {a.sources_total === 0 && a.destinations_total === 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h2>Get started</h2>
          <div className="grid cols-3" style={{ marginTop: 12 }}>
            {[["1", "Add source accounts", "Clipping accounts to learn from, by @handle, link or CSV.", "/sources"],
              ["2", "Connect where you post", "Log in to TikTok, YouTube, Instagram or Facebook.", "/destinations"],
              ["3", "Wire the funnel", "Drag sources onto the pages they should feed.", "/funnel"]].map(([n, t, s, to]) => (
              <Link key={n} to={to} className="card" style={{ background: "var(--card-2)", color: "inherit", textDecoration: "none" }}>
                <div className="row"><span className="pill accent nodot">{n}</span><strong>{t}</strong><span className="spacer" /><ArrowRight size={14} /></div>
                <p className="muted small" style={{ marginTop: 6 }}>{s}</p>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="grid cols-4">
        <Stat label="Connected destinations" value={a.destinations_connected} sub={`${a.destinations_total} total, ${a.destinations_total - a.destinations_connected} not connected`} to="/destinations" />
        <Stat label="Active monitors" value={a.sources_monitoring} sub={`${a.sources_total} source accounts, ${a.sources_authorized} authorized`} to="/sources" />
        <Stat label="Creators" value={a.creators} sub="Separate content pipelines" to="/sources" />
        <Stat label="Active routes" value={a.routes} sub="Source → destination links" to="/funnel" />
        <Stat label="Videos collected" value={d.pipeline.videos_collected} sub={`Tracked from ${d.pipeline.tracked_from.videos_collected}`} />
        <Stat label="Clips generated" value={d.pipeline.clips_generated} sub={`Tracked from ${d.pipeline.tracked_from.clips_generated}`} />
        <Stat label="Awaiting approval" value={d.pipeline.clips_awaiting_approval} sub={`Tracked from ${d.pipeline.tracked_from.clips_awaiting_approval}`} />
        <Stat label="Published clips" value={d.pipeline.clips_published} sub={`Tracked from ${d.pipeline.tracked_from.clips_published}`} />
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <div className="card-head"><div className="row"><PlugZap size={16} /><h2>Connection health</h2></div><Link to="/destinations" className="small">Manage</Link></div>
          {unconfigured.length > 0 && (
            <div className="stack" style={{ marginBottom: d.connections.length ? 12 : 0 }}>
              {unconfigured.map((p) => (
                <div className="list-row" key={p.key}>
                  <PlatformBadge platform={p.key} /><span>{p.label}</span><span className="pill nodot">One-time setup needed</span>
                  <span className="spacer" /><button className="btn sm" onClick={() => openSetup(p.key)}>Set up</button>
                </div>
              ))}
            </div>
          )}
          {d.connections.length === 0 ? <p className="muted small">No accounts connected yet.</p> : d.connections.map((c) => (
            <div className="list-row" key={c.id}>
              <Avatar url={c.avatar_url} platform={c.platform} />
              <div style={{ minWidth: 0 }}><div className="ellipsis">{c.display_name}</div><div className="small faint">{PLATFORM_LABEL[c.platform]} · checked {relTime(c.last_checked_at)}</div></div>
              <span className="spacer" /><StatusPill status={c.status} />
            </div>
          ))}
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><div className="row"><Activity size={16} /><h2>Background jobs</h2></div><span className="small faint">{jobTotal} total</span></div>
            <div className="row wrap" style={{ marginBottom: 8 }}>
              {["queued", "running", "succeeded", "failed"].map((s) => <span key={s} className="row small" style={{ opacity: d.jobs.by_status[s] ? 1 : 0.45 }}><StatusPill status={s} />{d.jobs.by_status[s] ?? 0}</span>)}
            </div>
            {d.jobs.recent.length === 0 ? <p className="muted small">No jobs have run yet. Token refresh checks run every 10 minutes.</p> :
              d.jobs.recent.map((j) => (
                <div className="list-row small" key={j.id}><span className="mono">{j.kind}</span><span className="spacer" /><span className="faint">{relTime(j.created_at)}</span><StatusPill status={j.status} /></div>
              ))}
          </div>
          <div className="card">
            <div className="card-head"><div className="row"><HardDrive size={16} /><h2>Storage</h2></div><span className="small faint">{bytes(d.storage.used_bytes)} used by AI Clipper</span></div>
            <div className="bar" aria-label="Disk usage"><div style={{ width: `${usedPct}%` }} /></div>
            <div className="row small muted" style={{ marginTop: 8 }}><span>{bytes(d.storage.disk_free_bytes)} free of {bytes(d.storage.disk_total_bytes)}</span><span className="spacer" />
              <KeyRound size={12} />{d.secret_backend === "os-keychain" ? "Credentials in Keychain" : "Credentials in encrypted file"}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
