import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, RotateCcw, Trash2, Upload, Wand2 } from "lucide-react";
import { api, type LongformT } from "../lib/api";
import { Empty, ErrorNote, Loading, relTime, useToast } from "../components/ui";

const hms = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return `${h ? `${h}:` : ""}${h ? String(m).padStart(2, "0") : m}:${String(sec).padStart(2, "0")}`;
};
const STATUS: Record<LongformT["status"], string> = { new: "Queued", processing: "Working", ready: "Done", failed: "Needs you" };

export default function LongformPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: ["longform"], queryFn: api.longform, refetchInterval: 4000 });
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const [url, setUrl] = useState("");
  const [creatorId, setCreatorId] = useState<number | null>(null);
  const [count, setCount] = useState(6);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["longform"] });
  const fail = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));

  const addLink = async () => {
    setBusy(true);
    try { await api.addLongform({ url: url.trim(), creator_id: creatorId, clips_wanted: count }); setUrl(""); toast("ok", "Added. Vyral is finding the best moments."); refresh(); }
    catch (e) { fail(e); } finally { setBusy(false); }
  };
  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      for (const f of Array.from(files)) await api.uploadLongform(f, creatorId, count);
      toast("ok", files.length === 1 ? "Added. Vyral is finding the best moments." : `Added ${files.length} videos.`);
      refresh();
    } catch (e) { fail(e); } finally { setBusy(false); if (file.current) file.current.value = ""; }
  };

  return (
    <div className="page">
      <div className="page-head"><div><h1>Long-form</h1>
        <p>Paste a long video or drop in a file. Vyral listens through all of it, picks the moments most likely to do well as short clips, and makes each one for your pages, graded like every other clip.</p></div></div>

      <div className={`card stack${dragging ? " drop-on" : ""}`} style={{ marginBottom: 16 }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void addFiles(e.dataTransfer.files); }}>
        <form className="row wrap" onSubmit={(e) => { e.preventDefault(); if (url.trim()) void addLink(); }}>
          <Wand2 size={16} color="var(--accent-hi)" />
          <input className="input" style={{ flex: 1, minWidth: 260 }} aria-label="Long video link" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="YouTube video, Twitch or Kick past broadcast, podcast link…" />
          <button className="btn primary" disabled={!url.trim() || busy}>{busy && <span className="spinner" />}Find clips</button>
        </form>
        <div className="row wrap">
          <input ref={file} type="file" hidden multiple accept="video/*,.mkv,.flv,.ts" aria-label="Video files" onChange={(e) => void addFiles(e.target.files)} />
          <button className="btn" disabled={busy} onClick={() => file.current?.click()}><Upload size={14} />Or choose a video file</button>
          <span className="small faint">or drop it anywhere in this box</span><span className="spacer" />
          <label className="small" htmlFor="lf-streamer">Streamer</label>
          <select id="lf-streamer" className="select" style={{ width: 200 }} value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">None (post to all my pages)</option>{(creators.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <label className="small" htmlFor="lf-count">Clips: {count}</label>
          <input id="lf-count" type="range" min={1} max={20} value={count} onChange={(e) => setCount(Number(e.target.value))} style={{ width: 120 }} />
        </div>
      </div>

      {list.error && <ErrorNote error={list.error} />}
      {list.isLoading ? <Loading /> : (list.data ?? []).length === 0 ? (
        <div className="card"><Empty icon={<Film size={28} />} title="No long videos yet">
          <p className="small">Streams, podcasts and YouTube videos all work. On YouTube, the parts viewers replay most count the most.</p></Empty></div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          {list.data!.map((v) => <LongformCard key={v.id} v={v} onChange={refresh} fail={fail} />)}
        </div>
      )}
    </div>
  );
}

function LongformCard({ v, onChange, fail }: { v: LongformT; onChange: () => void; fail: (e: unknown) => void }) {
  const working = v.status === "new" || v.status === "processing";
  return (
    <div className="card stack" style={{ gap: 10 }}>
      <div className="row">
        <Film size={16} />
        <strong className="ellipsis" style={{ flex: 1, minWidth: 0 }} title={v.url ?? v.title}>{v.title || v.url}</strong>
        {v.creator && <span className="chip">{v.creator.name}</span>}
        {v.duration ? <span className="small faint">{hms(v.duration)}</span> : null}
        <span className={`pill ${v.status === "ready" ? "ok" : v.status === "failed" ? "warn" : "accent"}`}>{STATUS[v.status]}</span>
        {v.status === "failed" && <button className="btn sm" onClick={async () => { try { await api.retryLongform(v.id); onChange(); } catch (e) { fail(e); } }}><RotateCcw size={12} />Retry</button>}
        <button className="btn ghost icon" aria-label={`Remove ${v.title}`} title="Remove (clips already made stay)"
          onClick={async () => { try { await api.removeLongform(v.id); onChange(); } catch (e) { fail(e); } }}><Trash2 size={14} /></button>
      </div>
      <div className="row small faint">{working && <span className="spinner" style={{ width: 12, height: 12 }} />}<span>{v.status_detail}</span>
        <span className="spacer" /><span>{relTime(v.created_at)}</span></div>
      {v.moments.length > 0 && (
        <table className="table"><thead><tr><th>Moment</th><th>Score</th><th>Why</th><th>Clip</th></tr></thead><tbody>
          {v.moments.map((m, i) => (
            <tr key={i}>
              <td className="small mono" style={{ whiteSpace: "nowrap" }}>{hms(m.start)} to {hms(m.end)}</td>
              <td className="small">{m.score}{m.tier ? <span className="faint"> · {m.tier} tier</span> : null}</td>
              <td className="small"><div className="ellipsis" style={{ maxWidth: 420 }} title={m.text}>{m.why.length ? m.why.join(", ") : "A clear peak in the sound"}</div></td>
              <td className="small">{m.clip_id ? <Link to={`/editor/${m.clip_id}`}>{m.clip_title ?? "Open"}</Link> : <span className="faint">Making…</span>}</td>
            </tr>
          ))}</tbody></table>
      )}
    </div>
  );
}
