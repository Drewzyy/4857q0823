import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Clapperboard, Clock, Copy, Download, ExternalLink, FolderDown, Trash2, Type, Undo2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api, PLATFORM_LABEL, type ClipOutputT, type ClipT } from "../lib/api";
import { bytes, ConfirmModal, Empty, ErrorNote, Loading, PlatformBadge, relTime, useToast } from "../components/ui";
import { GradeBadge } from "../components/GradeBadge";

type Tab = "ready" | "uploaded" | "expired";

export function hms(sec: number | null): string {
  if (sec === null) return "";
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function daysLeft(iso: string): string {
  const d = Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
  return d <= 0 ? "Deleting soon" : d === 1 ? "Deletes tomorrow" : `Deletes in ${d} days`;
}

export default function Ready() {
  const [tab, setTab] = useState<Tab>("ready");
  const qc = useQueryClient();
  const toast = useToast();
  const clips = useQuery({
    queryKey: ["clips", tab], queryFn: () => api.clips(tab),
    // Poll quickly while a video is being re-rendered so the new version appears right away.
    refetchInterval: (q) => (q.state.data?.some((c) => c.outputs.some((o) => o.render_state === "rendering")) ? 2500 : 15_000),
  });
  const [removing, setRemoving] = useState<ClipT | null>(null);
  const refresh = () => ["clips", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const list = clips.data ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Ready to Upload</h1>
          <p>Every clip Vyral made, with a caption ready for each page that takes it. Save the video in full quality, paste the caption, upload it yourself, then mark it uploaded.</p></div>
      </div>
      <div className="tabs" role="tablist">
        {([["ready", "Ready"], ["uploaded", "Uploaded"], ["expired", "Expired"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {clips.error && <ErrorNote error={clips.error} />}
      {clips.isLoading ? <Loading /> : list.length === 0 ? (
        <div className="card"><Empty icon={<Download size={28} />} title={tab === "ready" ? "Nothing waiting" : tab === "uploaded" ? "Nothing marked uploaded yet" : "Nothing expired"}>
          {tab === "ready" && <p className="small">When a source account posts, Vyral finds the moment in the full stream, makes the clip and puts it here. Watch progress in <Link to="/activity">Activity</Link>.</p>}
        </Empty></div>
      ) : (
        <div className="stack" style={{ gap: 16 }}>
          {list.map((c) => <ClipCard key={c.id} clip={c} tab={tab} onChange={refresh} onRemove={() => setRemoving(c)} toast={toast} />)}
        </div>
      )}
      <ConfirmModal open={!!removing} title="Delete this clip?" danger confirmLabel="Delete"
        message="The video files are deleted from Vyral. Copies you already saved to your computer are kept."
        onClose={() => setRemoving(null)} onConfirm={async () => {
          try { if (removing) await api.deleteClip(removing.id); refresh(); } catch (e) { toast("err", String(e)); }
          setRemoving(null);
        }} />
    </div>
  );
}

function ClipCard({ clip, tab, onChange, onRemove, toast }: { clip: ClipT; tab: Tab; onChange: () => void; onRemove: () => void; toast: ReturnType<typeof useToast> }) {
  const outputs = clip.outputs.filter((o) => tab === "expired" || o.status === tab);
  const [active, setActive] = useState(outputs[0]?.id);
  const current = outputs.find((o) => o.id === active) ?? outputs[0];
  const ref = clip.reference;
  return (
    <div className="card" style={{ display: "grid", gridTemplateColumns: "minmax(200px, 270px) 1fr", gap: 20 }}>
      <div>
        {current?.render_state === "rendering" ? (
          <div className="empty" style={{ aspectRatio: "9 / 16", background: "var(--bg-2)", borderRadius: 10, justifyContent: "center" }}>
            <span className="spinner" /><span className="small">Re-rendering with your changes…</span></div>
        ) : current?.available ? (
          <video key={`${current.id}-${current.version}`} src={api.mediaUrl(current.id, false, current.version)} controls preload="metadata" playsInline
            style={{ width: "100%", aspectRatio: `${current.width ?? 9} / ${current.height ?? 16}`, background: "#000", borderRadius: 10 }} />
        ) : (
          <div className="empty" style={{ aspectRatio: "9 / 16", background: "var(--bg-2)", borderRadius: 10, justifyContent: "center" }}>
            <Clock size={22} /><span className="small">Video deleted after {daysLeftLabel(clip)}</span></div>
        )}
      </div>
      <div className="stack" style={{ minWidth: 0 }}>
        <div className="row wrap">
          <GradeBadge grade={clip.grade} />
          <h2 className="ellipsis" style={{ flex: 1, minWidth: 0 }}>{clip.title}</h2>
          {clip.creator && <span className="chip"><span className="dot" style={{ background: clip.creator.color }} />{clip.creator.name}</span>}
          {clip.editable && <Link className="btn sm" to={`/editor/${clip.id}`}><Clapperboard size={13} />Edit video</Link>}
          <button className="btn ghost icon" aria-label="Delete clip" onClick={onRemove}><Trash2 size={14} /></button>
        </div>
        <div className="row wrap small muted" style={{ gap: 14 }}>
          {ref?.source && <span>From <a href={ref.url} target="_blank" rel="noopener noreferrer">@{ref.source.username}'s post <ExternalLink size={11} /></a></span>}
          {!ref?.source && ref && <a href={ref.url} target="_blank" rel="noopener noreferrer">Original post <ExternalLink size={11} /></a>}
          {clip.vod_url && <span>Cut from <a href={clip.vod_url} target="_blank" rel="noopener noreferrer">the stream</a> at {hms(clip.vod_start)} to {hms(clip.vod_end)}</span>}
          {clip.stream_date && <span>Streamed {new Date(clip.stream_date).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</span>}
          <span>Made {relTime(clip.created_at)}</span>
          {clip.status === "ready" && <span className="pill warn nodot">{daysLeft(clip.expires_at)}</span>}
        </div>

        <div className="row wrap" role="tablist" aria-label="Destinations">
          {outputs.map((o) => (
            <button key={o.id} role="tab" aria-selected={o.id === current?.id} className={`filter-btn${o.id === current?.id ? " on" : ""}`}
              style={{ width: "auto", border: "1px solid var(--line-2)" }} onClick={() => setActive(o.id)}>
              <PlatformBadge platform={o.platform} />{o.destination?.display_name ?? PLATFORM_LABEL[o.platform]}
              {o.destination?.handle && <span className="faint">{o.destination.handle}</span>}
              {o.status === "uploaded" && <CheckCircle2 size={13} color="var(--ok)" />}
            </button>
          ))}
        </div>
        {clip.captions_note && <div className="banner warn small">{clip.captions_note}</div>}
        {current && <OutputPanel key={current.id} o={current} clip={clip} onChange={onChange} toast={toast} />}
      </div>
    </div>
  );
}

function daysLeftLabel(c: ClipT) {
  const days = Math.round((new Date(c.expires_at).getTime() - new Date(c.created_at).getTime()) / 86400000);
  return `${days} days`;
}

function PostLink({ o, onChange, toast }: { o: ClipOutputT; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const [url, setUrl] = useState(o.post_url ?? "");
  const [nums, setNums] = useState({ views: "", likes: "", comments: "", shares: "" });
  const auto = o.platform === "tiktok" || o.platform === "youtube";
  const saveLink = async () => {
    try { const r = await api.setPostLink(o.id, url.trim()); toast("ok", r.auto ? "Saved. Vyral will read its views and likes every few hours." : "Saved. Add its numbers below whenever you like."); onChange(); }
    catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
  };
  const saveNums = async () => {
    const v = (x: string) => (x.trim() === "" ? null : Number(x.replace(/[,\s]/g, "")));
    try { await api.addMetrics(o.id, { views: v(nums.views), likes: v(nums.likes), comments: v(nums.comments), shares: v(nums.shares) });
      toast("ok", "Numbers saved to Analytics"); setNums({ views: "", likes: "", comments: "", shares: "" }); }
    catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="field">
      <label htmlFor={`post-${o.id}`} className="label-text">Link to your post (after uploading, for Analytics)</label>
      <div className="row">
        <input id={`post-${o.id}`} className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={`https://www.${o.platform === "youtube" ? "youtube.com/shorts/…" : o.platform + ".com/…"}`} />
        <button className="btn" disabled={!url.trim() || url.trim() === (o.post_url ?? "")} onClick={saveLink}>Save link</button>
      </div>
      {o.post_url && !auto && (
        <div className="row wrap" style={{ marginTop: 6 }}>
          {(["views", "likes", "comments", "shares"] as const).map((k) => (
            <input key={k} className="input" style={{ width: 110 }} inputMode="numeric" aria-label={`${k} on ${o.platform}`} placeholder={k[0].toUpperCase() + k.slice(1)}
              value={nums[k]} onChange={(e) => setNums({ ...nums, [k]: e.target.value })} />))}
          <button className="btn sm" disabled={Object.values(nums).every((x) => !x.trim())} onClick={saveNums}>Save numbers</button>
          <span className="hint">{o.platform === "instagram" ? "Instagram" : "Facebook"} only shows numbers when logged in, so type them from the app.</span>
        </div>
      )}
    </div>
  );
}

function OutputPanel({ o, clip, onChange, toast }: { o: ClipOutputT; clip: ClipT; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const [title, setTitle] = useState(o.title);
  const [desc, setDesc] = useState(o.description);
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: Infinity });
  const dirty = title !== o.title || desc !== o.description;
  useEffect(() => { setTitle(o.title); setDesc(o.description); }, [o.title, o.description]);

  const copy = async (text: string, what: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(what); setTimeout(() => setCopied(null), 1500); }
    catch { toast("err", "Couldn't copy. Select the text and copy it manually."); }
  };
  const persist = async () => {
    if (!dirty) return;
    try { await api.updateOutput(o.id, { title, description: desc }); onChange(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
  };
  const save = async () => {
    setBusy(true);
    try { await persist(); const r = await api.saveOutput(o.id); toast("ok", `Saved to ${r.path}`); }
    catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const mark = async (status: "uploaded" | "ready") => {
    try { await persist(); await api.updateOutput(o.id, { status }); toast("ok", status === "uploaded" ? "Marked as uploaded" : "Moved back to Ready"); onChange(); }
    catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
  };
  const isYT = o.platform === "youtube";

  return (
    <div className="stack" style={{ background: "var(--bg-2)", borderRadius: 10, padding: 14 }}>
      <div className="row small faint" style={{ gap: 12 }}>
        <span>{PLATFORM_LABEL[o.platform]}</span>
        {o.width && <span>{o.width}×{o.height}{o.fps ? ` · ${Math.round(o.fps)} fps` : ""}</span>}
        {o.size_bytes && <span>{bytes(o.size_bytes)}</span>}
      </div>
      {isYT && (
        <div className="field">
          <div className="row"><label htmlFor={`t-${o.id}`} className="label-text">Title</label><span className="spacer" />
            <button className="btn sm" onClick={() => copy(title, "title")}>{copied === "title" ? <Check size={12} /> : <Copy size={12} />}{copied === "title" ? "Copied" : "Copy title"}</button></div>
          <input id={`t-${o.id}`} className="input" maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} onBlur={persist} />
        </div>
      )}
      <div className="field">
        <div className="row"><label htmlFor={`d-${o.id}`} className="label-text">{isYT ? "Description" : "Caption"}</label><span className="spacer" />
          <span className="small faint">{desc.length}/{isYT ? 5000 : 2200}</span>
          <button className="btn sm" onClick={() => copy(desc, "desc")}>{copied === "desc" ? <Check size={12} /> : <Copy size={12} />}{copied === "desc" ? "Copied" : "Copy caption"}</button></div>
        <textarea id={`d-${o.id}`} className="textarea" rows={8} maxLength={5000} value={desc} onChange={(e) => setDesc(e.target.value)} onBlur={persist} />
      </div>
      <div className="row wrap">
        <button className="btn primary" disabled={!o.available || busy || o.render_state === "rendering"} onClick={save}>{busy ? <span className="spinner" /> : <FolderDown size={14} />}Save to computer</button>
        {o.available && !health?.desktop_mode && o.render_state !== "rendering" && <a className="btn" href={api.mediaUrl(o.id, true, o.version)} download><Download size={14} />Download</a>}
        {o.has_thumbnail && o.render_state !== "rendering" && <a className="btn" href={api.thumbUrl(o.id, true, o.version)} download title="The cover image you picked in the editor">
          <img src={api.thumbUrl(o.id, false, o.version)} alt="" style={{ width: 18, height: 32, objectFit: "cover", borderRadius: 3 }} />Thumbnail</a>}
        <span className="spacer" />
        {o.status === "ready" && <button className="btn" onClick={() => mark("uploaded")}><CheckCircle2 size={14} />Mark uploaded</button>}
        {o.status === "uploaded" && <button className="btn ghost" onClick={() => mark("ready")}><Undo2 size={14} />Not uploaded</button>}
      </div>
      <PostLink o={o} onChange={onChange} toast={toast} />
      {clip.editable && <Link className="btn ghost sm" style={{ alignSelf: "flex-start" }} to={`/editor/${clip.id}`}>
        <Type size={13} />Edit the title, captions and text style in the Video Editor</Link>}
      <p className="small faint">Save to computer puts the full-quality file (and its thumbnail) in Downloads › Vyral and shows it in {navigator.userAgent.includes("Windows") ? "File Explorer" : "Finder"}.</p>
    </div>
  );
}
