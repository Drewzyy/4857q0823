import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity as ActivityIcon, ExternalLink, Link2, RotateCw, Square, Wand2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type RefPost } from "../lib/api";
import { Empty, ErrorNote, Loading, Modal, PlatformBadge, relTime, useToast } from "../components/ui";
import { hms } from "./Ready";

const STATUS: Record<RefPost["status"], [string, string]> = {
  new: ["", "Queued"], processing: ["accent", "Working"], ready: ["ok", "Clip ready"], no_match: ["warn", "Moment not found"], duplicate: ["", "Already clipped"],
  needs_setup: ["warn", "Needs setup"], failed: ["err", "Failed"], baseline: ["", "Existing post"],
};

export default function ActivityPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const refs = useQuery({ queryKey: ["references"], queryFn: api.references, refetchInterval: 5_000 });
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const [url, setUrl] = useState("");
  const [creatorId, setCreatorId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState<RefPost | null>(null);
  const refresh = () => ["references", "clips", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  const submit = async () => {
    setBusy(true);
    try {
      // Any paste works: one link, many (on separate lines or not), or links mixed in with other text.
      const r = await api.intake(url, creatorId);
      if (!r.queued) throw new Error("No TikTok or YouTube Shorts video links found in that. Paste the video's share link.");
      toast("ok", `Working on ${r.queued} link${r.queued === 1 ? "" : "s"}. ${r.queued === 1 ? "It" : "They"}'ll show up below.${r.ignored ? ` Skipped ${r.ignored} other link${r.ignored === 1 ? "" : "s"}.` : ""}`);
      setUrl(""); refresh();
    }
    catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head"><div><h1>Activity</h1>
        <p>New posts from your source accounts and what Vyral did with each one. Updates live.</p></div></div>

      <form className="card row wrap" style={{ marginBottom: 16 }} onSubmit={(e) => { e.preventDefault(); if (url.trim()) void submit(); }}>
        <Wand2 size={16} color="var(--accent-hi)" />
        <textarea className="input" rows={Math.min(6, Math.max(1, url.split("\n").length))} style={{ flex: 1, minWidth: 260, resize: "vertical" }} aria-label="Video links"
          placeholder="Paste TikTok or YouTube Shorts links (one or many) to clip them now"
          value={url} onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (url.trim() && !busy) void submit(); } }} />
        <select className="select" style={{ width: 230 }} aria-label="Creator for pasted link" value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)}>
          <option value="">Any streamer (from the caption)</option>{(creators.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        <button className="btn primary" disabled={!url.trim() || busy}>{busy && <span className="spinner" />}Make clip</button>
      </form>

      {refs.error && <ErrorNote error={refs.error} />}
      {refs.isLoading ? <Loading /> : (refs.data ?? []).length === 0 ? (
        <div className="card"><Empty icon={<ActivityIcon size={28} />} title="No new posts yet">
          <p className="small">Vyral checks your <Link to="/sources">source accounts</Link> automatically while it's running. Posts that existed before you added an account are skipped.</p>
        </Empty></div>
      ) : (
        <div className="card" style={{ padding: "4px 18px" }}>
          {(refs.data ?? []).map((r) => {
            const [cls, label] = STATUS[r.status];
            return (
              <div className="list-row" key={r.id} style={{ alignItems: "flex-start" }}>
                {r.thumbnail_url ? <img src={r.thumbnail_url} alt="" referrerPolicy="no-referrer" style={{ width: 44, height: 60, objectFit: "cover", borderRadius: 6, background: "var(--card-3)" }} />
                  : <PlatformBadge platform={r.platform} large />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <strong className="ellipsis">{r.source ? `@${r.source.username}` : "Pasted link"}</strong>
                    {r.creator && <span className="chip"><span className="dot" style={{ background: r.creator.color }} />{r.creator.name}</span>}
                    <span className="small faint">{relTime(r.created_at)}</span>
                  </div>
                  <div className="small muted ellipsis">{r.title || r.url}</div>
                  <div className="small" style={{ marginTop: 4, color: r.status === "failed" ? "#ff8a8d" : "var(--muted)" }}>
                    {r.status === "processing" && <span className="spinner" style={{ width: 11, height: 11, display: "inline-block", verticalAlign: "-1px", marginRight: 6 }} />}
                    {r.status_detail}
                    {r.vod_url && r.status === "ready" && <> · found at <a href={r.vod_url} target="_blank" rel="noopener noreferrer">{hms(r.vod_start)}</a></>}
                  </div>
                </div>
                <span className={`pill ${cls}`}>{label}</span>
                <a className="btn ghost icon" href={r.url} target="_blank" rel="noopener noreferrer" aria-label="Open post"><ExternalLink size={14} /></a>
                {r.status === "ready" ? <Link className="btn sm" to="/ready">Open</Link>
                  : r.status === "processing" || r.status === "new" ?
                    <button className="btn sm ghost" onClick={async () => { await api.stopReference(r.id); refresh(); }}><Square size={11} />Stop</button>
                  : (r.status === "no_match" || r.status === "needs_setup" || r.status === "failed") &&
                    <button className="btn sm" onClick={() => setRetry(r)}><RotateCw size={12} />Retry</button>}
              </div>
            );
          })}
        </div>
      )}
      {retry && <RetryModal post={retry} onClose={() => setRetry(null)} onDone={refresh} />}
    </div>
  );
}

function RetryModal({ post, onClose, onDone }: { post: RefPost; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [vod, setVod] = useState("");
  const go = async () => {
    try { await api.retryReference(post.id, vod.trim() || undefined); toast("ok", "Retrying"); onDone(); onClose(); }
    catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Modal open onClose={onClose} title="Try again" footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" onClick={go}>Retry</button></>}>
      <p className="muted small">{post.status_detail}</p>
      {post.status === "needs_setup" && <p className="small">Fix the setup above first (Source Accounts, Creators or Destinations), then retry.</p>}
      <div className="field"><label htmlFor="vod">Specific stream link (optional)</label>
        <div className="row"><Link2 size={14} /><input id="vod" className="input" placeholder="https://www.twitch.tv/videos/… or a YouTube video link" value={vod} onChange={(e) => setVod(e.target.value)} /></div>
        <span className="hint">If you know which stream the moment is from, paste it and Vyral searches only that one.</span></div>
    </Modal>
  );
}
