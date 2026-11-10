import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bot } from "lucide-react";
import { api, type Agent, type NeedsYou } from "../lib/api";
import { ErrorNote, Loading, relTime } from "../components/ui";

const STATE: Record<Agent["state"], [string, string]> = { working: ["accent", "Working"], waiting: ["", "Queued"], idle: ["", "Idle"] };

export function NeedsYouList({ items }: { items: NeedsYou[] }) {
  if (items.length === 0) return <p className="small faint">Nothing needs you right now.</p>;
  return (
    <div className="stack" style={{ gap: 0 }}>
      {items.map((n) => (
        <Link key={n.kind} to={n.link} className="list-row small" style={{ color: "inherit" }}>
          <AlertTriangle size={14} color={n.kind === "upload" ? "var(--accent-hi)" : "var(--warn)"} />
          <span>{n.title}</span><span className="spacer" /><span className="btn sm ghost">Open</span>
        </Link>
      ))}
    </div>
  );
}

function AgentCard({ a }: { a: Agent }) {
  const [cls, label] = STATE[a.state];
  return (
    <div className="card stack" style={{ gap: 8 }}>
      <div className="row"><Bot size={16} /><strong>{a.name}</strong><span className="spacer" />
        <span className={`pill ${cls}`}>{label}{a.queued ? ` · ${a.queued} waiting` : ""}</span></div>
      <p className="small faint" style={{ margin: 0 }}>{a.does}</p>
      {a.running.map((j) => (
        <div key={j.id} className="small" style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
          <span className="spinner" style={{ width: 10, height: 10, flex: "none" }} />
          <span className="ellipsis" title={j.detail}>{j.detail}</span>
          <span className="faint" style={{ flex: "none" }}>{relTime(j.started_at)}</span>
        </div>
      ))}
      <div className="row small faint"><span>Last 24 hours: {a.done_24h} done</span>
        {a.failed_24h > 0 && <span style={{ color: "#ff8a8d" }}>· {a.failed_24h} failed</span>}</div>
    </div>
  );
}

export default function AgentsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["intelligence"], queryFn: api.intelligence, refetchInterval: 4000 });
  return (
    <div className="page">
      <div className="page-head"><div><h1>Agents</h1>
        <p>What each part of Vyral is doing right now, what it finished and what needs you. This is live: an agent with nothing to do shows as idle.</p></div></div>
      {error && <ErrorNote error={error} />}
      {isLoading || !data ? <Loading /> : (
        <div className="stack" style={{ gap: 14 }}>
          <div className="card"><h2 style={{ marginBottom: 8 }}>Needs you</h2><NeedsYouList items={data.needs_you} /></div>
          <div className="grid cols-3">{data.agents.map((a) => <AgentCard key={a.key} a={a} />)}</div>
          <div className="card">
            <h2 style={{ marginBottom: 8 }}>Recently finished</h2>
            {data.recent.length === 0 ? <p className="small faint">Nothing yet.</p> : (
              <table className="table"><thead><tr><th>Agent</th><th>Task</th><th>Result</th><th>When</th></tr></thead><tbody>
                {data.recent.map((j) => (
                  <tr key={j.id}>
                    <td className="small">{data.agents.find((a) => a.key === j.agent)?.name ?? j.agent}</td>
                    <td className="small"><div className="ellipsis" style={{ maxWidth: 460 }} title={j.error ?? j.detail}>{j.detail}</div></td>
                    <td className="small" style={{ color: j.status === "failed" ? "#ff8a8d" : undefined }} title={j.error ?? undefined}>
                      {j.status === "succeeded" ? "Done" : j.status === "failed" ? "Failed" : "Stopped"}</td>
                    <td className="small faint" style={{ whiteSpace: "nowrap" }}>{relTime(j.finished_at)}</td>
                  </tr>
                ))}</tbody></table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
