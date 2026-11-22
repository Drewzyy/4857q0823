import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Check, CheckCircle2, Clapperboard, Clock, Copy, Download, ExternalLink, FolderDown, Play, Trash2, Type, Undo2 } from "lucide-react";
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

const TIERS = ["S", "A", "B", "C", "D"] as const;
const PAGE = 20;
const KINDS = [["gaming", "Gaming"], ["podcast", "Podcast"], ["irl", "IRL"], ["chatting", "Just chatting"]] as const;
const saved = <T,>(key: string, fallback: T): T => {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
};
const save = (key: string, v: unknown) => { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private window: just not remembered */ } };

export default function Ready() {
  const [tab, setTab] = useState<Tab>("ready");
  const qc = useQueryClient();
  const toast = useToast();
  const clips = useQuery({
    queryKey: ["clips", tab], queryFn: () => api.clips(tab), refetchOnWindowFocus: false,
    // A little faster while a video re-renders, so the new version shows up soon after it's done.
    refetchInterval: (q) => (q.state.data?.some((c) => c.outputs.some((o) => o.render_state === "rendering")) ? 5000 : 15_000),
  });
  const [removing, setRemoving] = useState<ClipT | null>(null);
  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["clips", tab], exact: true });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
  }, [qc, tab]);
  // Grades to show (none ticked = all) and whether the best come first. Remembered between visits.
  const [grades, setGrades] = useState<string[]>(() => saved("ready.grades", []));
  const [bestFirst, setBestFirst] = useState<boolean>(() => saved("ready.bestFirst", false));
  useEffect(() => save("ready.grades", grades), [grades]);
  useEffect(() => save("ready.bestFirst", bestFirst), [bestFirst]);
  // Clips made while you're reviewing wait behind a "new clips" button instead of pushing the page around.
  const [seen, setSeen] = useState<Set<number> | null>(null);
  useEffect(() => setSeen(null), [tab]);
  useEffect(() => { if (!seen && clips.data) setSeen(new Set(clips.data.map((c) => c.id))); }, [seen, clips.data]);
  const fresh = useMemo(() => (seen ? (clips.data ?? []).filter((c) => !seen.has(c.id)) : []), [seen, clips.data]);
  const showNew = () => { setSeen(new Set((clips.data ?? []).map((c) => c.id))); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const all = useMemo(() => (seen ? (clips.data ?? []).filter((c) => seen.has(c.id)) : clips.data ?? []), [seen, clips.data]);
  const counts = useMemo(() => Object.fromEntries([...TIERS, "none"].map((t) => [t, all.filter((c) => (c.grade?.tier ?? "none") === t).length])), [all]);
  const [kinds, setKinds] = useState<string[]>(() => saved("ready.kinds", []));
  useEffect(() => save("ready.kinds", kinds), [kinds]);
  const kindOf = (c: ClipT) => c.content?.kind ?? "unknown";
  const kindCounts = useMemo(() => Object.fromEntries(KINDS.map(([k]) => [k, all.filter((c) => kindOf(c) === k).length])), [all]);
  const list = useMemo(() => {
    const shown = all.filter((c) => (!grades.length || grades.includes(c.grade?.tier ?? "none")) && (!kinds.length || kinds.includes(kindOf(c))));
    return bestFirst ? [...shown].sort((a, b) => (b.grade?.score ?? -1) - (a.grade?.score ?? -1)) : shown;
  }, [all, grades, kinds, bestFirst]);
  // Only the first clips are drawn (each card has a cover image and its own panels); more on request. Keeps the
  // window light with hundreds of clips waiting.
  const [shown, setShown] = useState(PAGE);
  useEffect(() => setShown(PAGE), [tab, grades, kinds, bestFirst]);
  const toggle = (t: string) => setGrades((g) => (g.includes(t) ? g.filter((x) => x !== t) : [...g, t]));

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
      {all.length > 0 && (
        <div className="row wrap" style={{ gap: 6, marginBottom: 12 }} role="group" aria-label="Filter by grade">
          <span className="small faint">Grade</span>
          {[...TIERS, ...(counts.none ? ["none"] : [])].map((t) => (
            <button key={t} className={`filter-btn${grades.includes(t) ? " on" : ""}`} aria-pressed={grades.includes(t)}
              disabled={!counts[t] && !grades.includes(t)} onClick={() => toggle(t)}>
              {t === "none" ? "Not graded" : t} <span className="faint">{counts[t]}</span></button>))}
          {grades.length > 0 && <button className="btn ghost sm" onClick={() => setGrades([])}>Show all</button>}
          <span className="small faint" style={{ marginLeft: 12 }}>Kind</span>
          {KINDS.filter(([k]) => kindCounts[k] || kinds.includes(k)).map(([k, l]) => (
            <button key={k} className={`filter-btn${kinds.includes(k) ? " on" : ""}`} aria-pressed={kinds.includes(k)}
              onClick={() => setKinds((x) => (x.includes(k) ? x.filter((y) => y !== k) : [...x, k]))}>{l} <span className="faint">{kindCounts[k]}</span></button>))}
          {kinds.length > 0 && <button className="btn ghost sm" onClick={() => setKinds([])}>All kinds</button>}
          <span className="spacer" />
          <label className="check small"><input type="checkbox" checked={bestFirst} onChange={(e) => setBestFirst(e.target.checked)} />Best first</label>
        </div>
      )}
      {fresh.length > 0 && (
        <button className="btn primary sm" style={{ position: "sticky", top: 8, zIndex: 5, margin: "0 auto 12px", display: "flex" }} onClick={showNew}>
          <ArrowUp size={13} />{fresh.length} new clip{fresh.length === 1 ? "" : "s"}</button>
      )}
      {clips.error && <ErrorNote error={clips.error} />}
      {clips.isLoading ? <Loading /> : all.length > 0 && list.length === 0 ? (
        <div className="card"><Empty icon={<Download size={28} />} title="No clips with those grades">
          <button className="btn" onClick={() => setGrades([])}>Show all grades</button></Empty></div>
      ) : list.length === 0 ? (
        <div className="card"><Empty icon={<Download size={28} />} title={tab === "ready" ? "Nothing waiting" : tab === "uploaded" ? "Nothing marked uploaded yet" : "Nothing expired"}>
          {tab === "ready" && <p className="small">When a source account posts, Vyral finds the moment in the full stream, makes the clip and puts it here. Watch progress in <Link to="/activity">Activity</Link>.</p>}
        </Empty></div>
      ) : (
        <div className="stack" style={{ gap: 16 }}>
          {list.slice(0, shown).map((c) => <ClipCard key={c.id} clip={c} tab={tab} onChange={refresh} onRemove={setRemoving} toast={toast} />)}
          {list.length > shown && <button className="btn" style={{ alignSelf: "center" }} onClick={() => setShown(shown + PAGE)}>
            Show {Math.min(PAGE, list.length - shown)} more ({list.length - shown} left)</button>}
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

// Memoized: a new clip arriving or another card changing doesn't redraw this one.
const ClipCard = memo(function ClipCard({ clip, tab, onChange, onRemove, toast }: { clip: ClipT; tab: Tab; onChange: () => void; onRemove: (c: ClipT) => void; toast: ReturnType<typeof useToast> }) {
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
          <Preview key={`${current.id}-${current.version}`} o={current} />
        ) : (
          <div className="empty" style={{ aspectRatio: "9 / 16", background: "var(--bg-2)", borderRadius: 10, justifyContent: "center" }}>
            <Clock size={22} /><span className="small">Video deleted after {daysLeftLabel(clip)}</span></div>
        )}
      </div>
      <div className="stack" style={{ minWidth: 0 }}>
        <div className="row wrap">
          <GradeBadge grade={clip.grade} />
          {clip.content && <span className="chip small" title={`Detected: ${clip.content.why.join("; ")} (${Math.round(clip.content.confidence * 100)}% sure)`}>
            {KINDS.find(([k]) => k === clip.content!.kind)?.[1]}</span>}
          <h2 className="ellipsis" style={{ flex: 1, minWidth: 0 }}>{clip.title}</h2>
          {clip.creator && <span className="chip"><span className="dot" style={{ background: clip.creator.color }} />{clip.creator.name}</span>}
          {clip.editable && <Link className="btn sm" to={`/editor/${clip.id}`}><Clapperboard size={13} />Edit video</Link>}
          <button className="btn ghost icon" aria-label="Delete clip" onClick={() => onRemove(clip)}><Trash2 size={14} /></button>
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
        <SafetyNote safety={clip.safety} />
        {current && <OutputPanel key={current.id} o={current} clip={clip} onChange={onChange} toast={toast} />}
      </div>
    </div>
  );
});

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

/** A cover picture with a play button; the video player only loads when you press play. Loading a player for
 *  every clip at once is what made this page crawl. */
function Preview({ o }: { o: ClipOutputT }) {
  const [playing, setPlaying] = useState(false);
  const style = { width: "100%", aspectRatio: `${o.width ?? 9} / ${o.height ?? 16}`, background: "#000", borderRadius: 10 } as const;
  if (playing) return <video src={api.mediaUrl(o.id, false, o.version)} controls autoPlay playsInline style={style} />;
  return (
    <button className="preview-cover" aria-label="Play preview" onClick={() => setPlaying(true)}
      style={{ ...style, position: "relative", padding: 0, border: 0, cursor: "pointer", overflow: "hidden", display: "block" }}>
      {o.has_thumbnail && <img src={api.thumbUrl(o.id, false, o.version)} alt="" loading="lazy" decoding="async"
        style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
      <span style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
        <span style={{ background: "rgba(0,0,0,.55)", borderRadius: 999, padding: 14, display: "grid" }}><Play size={22} color="#fff" fill="#fff" /></span></span>
    </button>
  );
}

function OutputPanel({ o, clip, onChange, toast }: { o: ClipOutputT; clip: ClipT; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const [title, setTitle] = useState(o.title);
  const [desc, setDesc] = useState(o.description);
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: Infinity });
  const dirty = title !== o.title || desc !== o.description;
  // A background refresh never overwrites what you're typing: only take the saved text when you haven't changed it.
  const [base, setBase] = useState({ title: o.title, description: o.description });
  useEffect(() => {
    if (title === base.title && desc === base.description) { setTitle(o.title); setDesc(o.description); }
    setBase({ title: o.title, description: o.description });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [o.title, o.description]);

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
      <DropboxStatus o={o} onChange={onChange} toast={toast} />
      <ReviewBar o={o} clip={clip} onChange={onChange} toast={toast} />
      <PostLink o={o} onChange={onChange} toast={toast} />
      {clip.editable && <Link className="btn ghost sm" style={{ alignSelf: "flex-start" }} to={`/editor/${clip.id}`}>
        <Type size={13} />Edit the title, captions and text style in the Video Editor</Link>}
      <p className="small faint">Save to computer puts the full-quality file (and its thumbnail) in Downloads › Vyral and shows it in {navigator.userAgent.includes("Windows") ? "File Explorer" : "Finder"}.</p>
    </div>
  );
}

/** The safety check's result: what was flagged and when (seconds into the clip), and what a person has to look at. */
function SafetyNote({ safety }: { safety: ClipT["safety"] }) {
  if (!safety?.status || safety.status === "pass") return null;  // not checked yet, or clean
  const fail = safety.status === "fail";
  return (
    <div className={`banner ${fail ? "err" : "warn"} small`} role="status" style={{ flexDirection: "column", gap: 2 }}>
      <strong>{fail ? "Quarantined: this clip won't be reviewed or posted." : "Check before approving:"}</strong>
      <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>{(safety.flags ?? []).map((f, i) => (
        <li key={i}>{f.category}: {f.reason}{f.at !== null ? ` at ${f.at.toFixed(1)} s` : ""}</li>))}</ul>
    </div>
  );
}

/** Where this video is in Dropbox: queued, uploading, uploaded (with its path) or failed (with Retry). */
function DropboxStatus({ o, onChange, toast }: { o: ClipOutputT; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const box = useQuery({ queryKey: ["dropbox"], queryFn: api.dropbox, staleTime: 30_000 });
  const d = o.dropbox;
  if (!box.data?.connected && !d) return null;
  const pill = !d ? <span className="pill nodot">Not in Dropbox yet{box.data?.connected ? " (Sync all in Settings › Dropbox sends it)" : ""}</span>
    : d.status === "uploaded" ? <span className="pill ok">Uploaded to Dropbox</span>
    : d.status === "uploading" ? <span className="pill">Uploading to Dropbox{d.progress !== null ? ` ${d.progress}%` : ""}</span>
    : d.status === "failed" ? <span className="pill warn" title={d.error ?? ""}>Dropbox upload failed</span>
    : <span className="pill nodot">{box.data?.connected && !box.data.needs_reconnect ? "Queued for Dropbox" : "Waiting for Dropbox to be connected"}</span>;
  return (
    <div className="row wrap small" style={{ gap: 8 }}>
      {pill}
      {d?.status === "uploaded" && d.path && <code>{d.path}</code>}
      {d?.status === "failed" && <span className="faint">{d.error}{d.next_try_at ? ` Next try ${relTime(d.next_try_at)}.` : ""}</span>}
      {d?.status === "failed" && <button className="btn sm" onClick={async () => {
        try { await api.retryDropbox(d.id); toast("ok", "Retrying the Dropbox upload"); onChange(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
      }}>Retry</button>}
    </div>
  );
}

/** Approve or reject this page's video (yours or Muse's decision shows here). */
function ReviewBar({ o, clip, onChange, toast }: { o: ClipOutputT; clip: ClipT; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const [watched, setWatched] = useState(false);
  const [busy, setBusy] = useState(false);
  const go = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await fn(); toast("ok", done); onChange(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  if (clip.safety?.status === "fail" || o.status !== "ready") return null;
  if (o.quality?.status === "fail") return (
    <div className="banner warn small" role="status" style={{ flexDirection: "column", gap: 2 }}>
      <strong>This video didn't pass the quality check, so it's held back:</strong>
      <span>{o.quality.problems.join("; ")}. Fix it in the editor (saving re-renders and checks it again).</span>
    </div>
  );
  const by = o.reviewed_by === "muse" ? " by Muse" : o.reviewed_by === "auto" ? " (Auto-post)" : "";
  return (
    <div className="row wrap small" style={{ gap: 8, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
      {o.review === "approved" ? <span className="pill ok">Approved{by}</span>
        : o.review === "rejected" ? <span className="pill warn" title={o.review_note}>Rejected{by}{o.review_note ? `: ${o.review_note}` : ""}</span>
        : <span className="pill nodot">Waiting for review</span>}
      <span className="spacer" />
      {o.review !== "approved" && <>
        <label className="check"><input type="checkbox" checked={watched} onChange={(e) => setWatched(e.target.checked)} />I watched it</label>
        <button className="btn sm primary" disabled={busy || !watched} onClick={() => go(() => api.review(o.id, { decision: "approve", watched: true }), "Approved")}>Approve</button>
      </>}
      {o.review !== "rejected" && <button className="btn sm ghost" disabled={busy}
        onClick={() => { const reason = window.prompt("Why? (kept with the clip)", "Not good enough"); if (reason !== null) void go(() => api.review(o.id, { decision: "reject", reason }), "Rejected"); }}>Reject</button>}
    </div>
  );
}
