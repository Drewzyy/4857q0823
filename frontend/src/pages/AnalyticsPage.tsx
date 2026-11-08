import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, ExternalLink } from "lucide-react";
import { api, PLATFORM_LABEL, type GroupRow } from "../lib/api";
import { Empty, ErrorNote, Loading, PlatformBadge, relTime } from "../components/ui";

const n = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e4 ? `${(v / 1e3).toFixed(1)}K` : v.toLocaleString());

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="card stat"><div className="label">{label}</div><div className={`value${value === "—" ? " na" : ""}`}>{value}</div>{sub && <div className="sub">{sub}</div>}</div>;
}

function Breakdown({ title, rows, platform }: { title: string; rows: GroupRow[]; platform?: boolean }) {
  const max = Math.max(1, ...rows.map((r) => r.views ?? 0));
  return (
    <div className="card">
      <h2 style={{ marginBottom: 10 }}>{title}</h2>
      {rows.length === 0 ? <p className="small faint">No uploads in this period.</p> : rows.map((r) => (
        <div key={String(r.key)} style={{ marginBottom: 10 }}>
          <div className="row small" style={{ marginBottom: 4 }}>
            {platform && <PlatformBadge platform={String(r.key)} />}
            <strong className="ellipsis">{platform ? PLATFORM_LABEL[String(r.key)] : r.label}</strong>
            <span className="faint">{r.posts} post{r.posts === 1 ? "" : "s"}{r.tracked < r.posts ? `, ${r.posts - r.tracked} without numbers` : ""}</span>
            <span className="spacer" />
            <span>{n(r.views)} views</span>
            <span className="faint">{r.avg_views !== null ? `${n(r.avg_views)} avg` : ""}</span>
          </div>
          <div className="bar"><div style={{ width: `${((r.views ?? 0) / max) * 100}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [platform, setPlatform] = useState("");
  const [creator, setCreator] = useState<number | null>(null);
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const { data: a, isLoading, error } = useQuery({
    queryKey: ["analytics", days, platform, creator],
    queryFn: () => api.analytics({ days, platform: platform || undefined, creator_id: creator }),
    refetchInterval: 60_000,
  });
  const maxDay = Math.max(1, ...(a?.timeline ?? []).map((d) => d.views));

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Analytics</h1>
          <p>How the clips you uploaded are doing. Add each post's link in Ready to Upload after you upload it: Vyral reads TikTok and YouTube numbers every few hours, and you can type Instagram and Facebook numbers in. A dash means no numbers yet, not zero.</p></div>
      </div>
      <div className="row wrap" style={{ marginBottom: 16 }}>
        <div className="seg" role="group" aria-label="Time range">
          {[[7, "7 days"], [30, "30 days"], [90, "90 days"], [3650, "All time"]].map(([d, l]) => (
            <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(Number(d))}>{l}</button>))}
        </div>
        <select className="select" style={{ width: 160 }} aria-label="Platform filter" value={platform} onChange={(e) => setPlatform(e.target.value)}>
          <option value="">All platforms</option>{["tiktok", "youtube", "instagram", "facebook"].map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</select>
        <select className="select" style={{ width: 180 }} aria-label="Streamer filter" value={creator ?? ""} onChange={(e) => setCreator(e.target.value ? Number(e.target.value) : null)}>
          <option value="">All streamers</option>{(creators.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
      </div>

      {error && <ErrorNote error={error} />}
      {isLoading || !a ? <Loading /> : (
        <div className="stack" style={{ gap: 14 }}>
          <div className="grid cols-4">
            <Card label="Total views" value={n(a.totals.views)} sub={`${a.tracked} of ${a.uploaded} uploads have numbers`} />
            <Card label="Likes" value={n(a.totals.likes)} sub={a.totals.comments !== null ? `${n(a.totals.comments)} comments` : undefined} />
            <Card label="Engagement" value={a.totals.engagement_rate === null ? "—" : `${a.totals.engagement_rate}%`} sub="(likes + comments + shares) / views" />
            <Card label="Clips" value={String(a.uploaded)} sub={`uploaded · ${a.clips_made} made`} />
          </div>

          {a.uploaded === 0 ? (
            <div className="card"><Empty icon={<BarChart3 size={28} />} title="No uploads tracked yet">
              <p className="small">After you upload a clip, open it in <Link to="/ready">Ready to Upload</Link> and paste the post's link. Its numbers show up here.</p>
            </Empty></div>
          ) : (
            <>
              <div className="card">
                <h2 style={{ marginBottom: 10 }}>Views by upload day</h2>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 140 }} role="img" aria-label="Views by upload day">
                  {a.timeline.map((d) => (
                    <div key={d.day} title={`${d.day}: ${d.views.toLocaleString()} views from ${d.posts} upload(s)`}
                      style={{ flex: 1, minWidth: 6, height: `${Math.max(2, (d.views / maxDay) * 100)}%`, background: "var(--accent)", borderRadius: "4px 4px 0 0", opacity: d.views ? 1 : 0.3 }} />
                  ))}
                </div>
                <div className="row small faint" style={{ marginTop: 6 }}><span>{a.timeline[0]?.day}</span><span className="spacer" /><span>{a.timeline[a.timeline.length - 1]?.day}</span></div>
              </div>
              <div className="grid cols-2">
                <Breakdown title="By platform" rows={a.by_platform} platform />
                <Breakdown title="By streamer" rows={a.by_creator} />
                <Breakdown title="By page" rows={a.by_destination} />
                <Breakdown title="By clip length" rows={a.by_length} />
              </div>
              <div className="card">
                <h2 style={{ marginBottom: 8 }}>Top clips</h2>
                {a.top.length === 0 ? <p className="small faint">No numbers yet.</p> : (
                  <table className="table"><thead><tr><th>Clip</th><th>Page</th><th>Views</th><th>Likes</th><th>Comments</th><th>Shares</th><th>Updated</th></tr></thead>
                    <tbody>{a.top.map((t) => (
                      <tr key={t.output_id}>
                        <td><div className="row" style={{ minWidth: 0 }}><PlatformBadge platform={t.platform} /><span className="ellipsis" style={{ maxWidth: 320 }}>{t.title}</span>
                          {t.post_url && <a href={t.post_url} target="_blank" rel="noopener noreferrer" aria-label="Open post"><ExternalLink size={12} /></a>}</div></td>
                        <td className="small">{t.destination ?? "—"}</td><td>{n(t.views)}</td><td>{n(t.likes)}</td><td>{n(t.comments)}</td><td>{n(t.shares)}</td>
                        <td className="small faint">{relTime(t.updated)}</td>
                      </tr>))}</tbody></table>
                )}
              </div>
              {a.untracked.length > 0 && (
                <div className="card">
                  <h2 style={{ marginBottom: 8 }}>Uploads without numbers</h2>
                  {a.untracked.map((u) => (
                    <div key={u.output_id} className="list-row small"><PlatformBadge platform={u.platform} /><span className="ellipsis">{u.title}</span><span className="spacer" />
                      <span className="faint">{!u.has_link ? "Add the post link in Ready to Upload > Uploaded" : u.platform === "tiktok" || u.platform === "youtube" ? "Reading numbers…" : "Type the numbers in on the clip"}</span></div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
