import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Pause, Play, Plus, Redo2, RotateCcw, Trash2, Undo2 } from "lucide-react";
import { api, type ClipEditT, type EditorData, type FontKey, type Overlay, type TextOverlayT, type TextStyle } from "../lib/api";
import { Empty, ErrorNote, Loading, relTime, useToast } from "../components/ui";

const FONTS: [FontKey, string][] = [["montserrat", "Montserrat Black"], ["anton", "Anton"], ["bebas", "Bebas Neue"], ["poppins", "Poppins ExtraBold"]];
const SWATCHES = ["#FFFFFF", "#FFE500", "#F97316", "#22C55E", "#38BDF8", "#EC4899", "#000000"];
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const PREVIEW_W = 330;
const r1 = (v: number) => Math.round(v * 10) / 10;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const fmt = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${(Math.max(0, s) % 60).toFixed(1).padStart(4, "0")}`;

export default function EditorPage() {
  const { clipId } = useParams();
  return clipId ? <ClipEditor key={clipId} clipId={Number(clipId)} /> : <ClipList />;
}

function ClipList() {
  const { data, isLoading, error } = useQuery({ queryKey: ["clips", "all"], queryFn: () => api.clips("all") });
  const clips = (data ?? []).filter((c) => c.editable && c.status !== "expired");
  return (
    <div className="page">
      <div className="page-head"><div><h1>Video Editor</h1>
        <p>Pick a clip to trim it, zoom in, change the speed or add your own text. Saving re-renders the clip for every page it's going to.</p></div></div>
      {error && <ErrorNote error={error} />}
      {isLoading ? <Loading /> : clips.length === 0 ? (
        <div className="card"><Empty icon={<Clapperboard size={28} />} title="No clips to edit yet">
          <p className="small">Clips show up here once Vyral makes them. You can also open one from <Link to="/ready">Ready to Upload</Link>.</p></Empty></div>
      ) : (
        <div className="card stack" style={{ gap: 0 }}>
          {clips.map((c) => (
            <Link key={c.id} to={`/editor/${c.id}`} className="list-row" style={{ color: "inherit" }}>
              <span className="ellipsis" style={{ flex: 1 }}>{c.title}</span>
              {c.creator && <span className="chip"><span className="dot" style={{ background: c.creator.color }} />{c.creator.name}</span>}
              <span className="small faint">made {relTime(c.created_at)}</span>
              <span className="btn sm">Edit</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/** A number box you can type into freely; the value applies on Enter or when you leave the box. */
function NumField({ id, value, onCommit, min, max }: { id: string; value: number; onCommit: (v: number) => void; min?: number; max?: number }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null && draft.trim() !== "" && Number.isFinite(Number(draft))) onCommit(Number(draft));
    setDraft(null);
  };
  return <input id={id} className="input" type="number" step={0.1} min={min} max={max} value={draft ?? r1(value)}
    onChange={(ev) => setDraft(ev.target.value)} onBlur={commit}
    onKeyDown={(ev) => { if (ev.key === "Enter") commit(); else if (ev.key === "Escape") setDraft(null); }} />;
}

/** Undo/redo history. Rapid changes to the same control (dragging a slider) merge into one step. */
function useHistory(initial: ClipEditT) {
  const [state, setState] = useState({ past: [] as ClipEditT[], now: initial, future: [] as ClipEditT[] });
  const last = useRef({ key: "", at: 0 });
  const set = useCallback((next: ClipEditT, key = "") => {
    const t = Date.now();
    const merge = key !== "" && key === last.current.key && t - last.current.at < 700;
    last.current = { key, at: t };
    setState((h) => (JSON.stringify(next) === JSON.stringify(h.now) ? h : { past: merge ? h.past : [...h.past.slice(-99), h.now], now: next, future: [] }));
  }, []);
  const undo = useCallback(() => { last.current.key = ""; setState((h) => (h.past.length ? { past: h.past.slice(0, -1), now: h.past[h.past.length - 1], future: [h.now, ...h.future] } : h)); }, []);
  const redo = useCallback(() => { last.current.key = ""; setState((h) => (h.future.length ? { past: [...h.past, h.now], now: h.future[0], future: h.future.slice(1) } : h)); }, []);
  return { edit: state.now, set, undo, redo, canUndo: state.past.length > 0, canRedo: state.future.length > 0 };
}

function ClipEditor({ clipId }: { clipId: number }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["editor", clipId], queryFn: () => api.editor(clipId), staleTime: Infinity, retry: false });
  if (error) return <div className="page"><div className="page-head"><h1>Video Editor</h1></div><ErrorNote error={error} /><Link to="/editor">Back to clips</Link></div>;
  if (isLoading || !data) return <div className="page"><Loading /></div>;
  return <EditorBody data={data} />;
}

function EditorBody({ data }: { data: EditorData }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const h = useHistory(data.edit);
  const e = h.edit;
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState(data.edit.start);
  const [playing, setPlaying] = useState(false);
  const [selText, setSelText] = useState<number | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const bg = useRef<HTMLCanvasElement>(null);
  const [aspect, setAspect] = useState(16 / 9);
  // Share of the 9:16 frame's height the stream fills when it spans the full width (about 32% for 16:9).
  const fullWidth = Math.round((9 / 16 / aspect) * 100) / 100;
  // video_height 0 is "fit to frame": the whole stream across the full width, as clips used to look.
  const zoomedIn = e.video_height > 0;
  const stacked = e.layout === "stacked" && !!e.cam;
  const boxHeight = zoomedIn ? Math.max(e.video_height, fullWidth) : fullWidth;
  const total = data.section_duration;
  const first = data.outputs[0];
  const overlay: Overlay | null = first?.overlay ?? null;
  const dirty = JSON.stringify(e) !== JSON.stringify(data.edit);
  const len = e.end - e.start;
  const outLen = len / e.speed;
  const out = clamp((t - e.start) / e.speed, 0, outLen); // where the playhead is in the finished clip

  const patch = (p: Partial<ClipEditT>, key = "") => h.set({ ...e, ...p }, key);
  const setText = (i: number, p: Partial<TextOverlayT>, key = "") => patch({ texts: e.texts.map((x, j) => (j === i ? { ...x, ...p } : x)) }, `text${i}${key}`);

  // Keep playback inside the trimmed range and at the chosen speed; draw the blurred background.
  useEffect(() => { if (video.current) video.current.playbackRate = e.speed; }, [e.speed]);
  useEffect(() => {
    let raf = 0, drawn = -1;
    const tick = () => {
      const v = video.current;
      if (v) {
        if (!v.paused && v.currentTime >= e.end) { v.pause(); v.currentTime = e.start; }
        setT(v.currentTime);
        const c = bg.current?.getContext("2d");
        if (c && v.readyState >= 2 && v.currentTime !== drawn) {
          drawn = v.currentTime;
          c.filter = "blur(6px) brightness(0.88) saturate(1.15)";
          const cw = c.canvas.width, ch = c.canvas.height, s = Math.max(cw / v.videoWidth, ch / v.videoHeight);
          c.drawImage(v, (cw - v.videoWidth * s) / 2, (ch - v.videoHeight * s) / 2, v.videoWidth * s, v.videoHeight * s);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [e.start, e.end]);

  const seek = (s: number) => { if (video.current) video.current.currentTime = clamp(s, 0, total); setT(clamp(s, 0, total)); };
  const toggle = useCallback(() => {
    const v = video.current;
    if (!v) return;
    if (v.paused) { if (v.currentTime < e.start || v.currentTime >= e.end - 0.05) v.currentTime = e.start; void v.play(); } else v.pause();
  }, [e.start, e.end]);
  const setStart = (s: number) => patch({ start: r1(clamp(s, 0, e.end - 1)) }, "start");
  const setEnd = (s: number) => patch({ end: r1(clamp(s, e.start + 1, total)) }, "end");

  // Shortcuts. The handler is refreshed each render through a ref so the listener is attached once.
  const onKey = useRef<(ev: KeyboardEvent) => void>(() => {});
  onKey.current = (ev) => {
    if (ev.target instanceof HTMLElement && ev.target.closest("input, textarea, select")) return; // let fields keep their own undo
    const mod = ev.metaKey || ev.ctrlKey, key = ev.key.toLowerCase();
    if (mod && (key === "z" || key === "y")) { ev.preventDefault(); if (key === "y" || ev.shiftKey) h.redo(); else h.undo(); }
    else if (mod) return;
    else if (key === " ") { ev.preventDefault(); toggle(); }
    else if (key === "[") setStart(t);
    else if (key === "]") setEnd(t);
  };
  useEffect(() => {
    const listener = (ev: KeyboardEvent) => onKey.current(ev);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.saveEdit(data.id, e);
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["editor", data.id] });
      toast("ok", `Saved. Re-rendering ${r.rendering} video${r.rendering === 1 ? "" : "s"} with your edits.`);
      nav("/ready");
    } catch (err) { toast("err", String(err instanceof Error ? err.message : err)); }
    finally { setBusy(false); }
  };

  // Captions and texts in finished-clip time.
  const shift = data.original_start - e.start;
  const words = useMemo(() => data.words.map((w) => ({ start: (w.start + shift) / e.speed, end: (w.end + shift) / e.speed, text: w.text }))
    .filter((w) => w.end > 0 && w.start < outLen), [data.words, shift, e.speed, outLen]);
  const chunks = useMemo(() => {
    const per = overlay?.captions.words_per_caption ?? 3, res: { start: number; end: number; text: string }[] = [];
    let cur: typeof words = [];
    const flush = () => { if (cur.length) res.push({ start: cur[0].start, end: cur[cur.length - 1].end, text: cur.map((x) => x.text).join(" ") }); cur = []; };
    for (const w of words) {
      if (cur.length && (cur.length >= per || w.start - cur[cur.length - 1].end > 0.6)) flush();
      cur.push(w);
      if (/[.!?]$/.test(w.text)) flush();
    }
    flush();
    return res;
  }, [words, overlay]);
  const inRange = t >= e.start - 0.01 && t <= e.end + 0.01;
  const caption = inRange ? chunks.find((c) => out >= c.start && out < c.end + 0.3) : undefined;
  const k = PREVIEW_W / 1080;
  const css = (s: Pick<TextStyle, "y_percent" | "font" | "size" | "color" | "outline" | "all_caps"> & { outline_color?: string }) => ({
    top: `${s.y_percent}%`, fontFamily: `"V-${s.font}", sans-serif`, fontSize: `${Math.max(6, s.size * k)}px`, color: s.color,
    WebkitTextStroke: s.outline ? `${Math.max(1, s.outline * k * 2)}px ${s.outline_color ?? "#000000"}` : undefined,
    textTransform: s.all_caps ? ("uppercase" as const) : ("none" as const),
  });

  // Timeline: the whole downloaded section, with the kept part highlighted.
  const bar = useRef<HTMLDivElement>(null);
  const pct = (s: number) => `${(s / total) * 100}%`;
  const atX = (x: number) => { const r = bar.current!.getBoundingClientRect(); return clamp(((x - r.left) / r.width) * total, 0, total); };
  const drag = (which: "start" | "end") => (ev: React.PointerEvent) => {
    ev.preventDefault(); ev.stopPropagation();
    const move = (m: PointerEvent) => { const s = atX(m.clientX); which === "start" ? setStart(s) : setEnd(s); seek(s); };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const secOf = (o: number) => e.start + o * e.speed; // finished-clip time back to section time

  const addText = () => {
    const at = clamp(r1(inRange ? out : 0), 0, Math.max(0, outLen - 1));
    const nt: TextOverlayT = { text: "NEW TEXT", start: at, end: r1(Math.min(outLen, at + 3)), y_percent: 45, size: 80, color: "#FFFFFF", font: "montserrat", all_caps: true, outline: 6 };
    h.set({ ...e, texts: [...e.texts, nt] });
    setSelText(e.texts.length);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div style={{ minWidth: 0 }}><h1 className="ellipsis">Edit: {data.title}</h1>
          <p>Changes apply to every page this clip goes to. The preview is close to the final video; the exact one is rendered when you save.</p></div>
        <div className="row">
          <button className="btn ghost icon" aria-label="Undo" title="Undo (⌘Z)" disabled={!h.canUndo} onClick={h.undo}><Undo2 size={15} /></button>
          <button className="btn ghost icon" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!h.canRedo} onClick={h.redo}><Redo2 size={15} /></button>
          <Link className="btn" to="/ready">Cancel</Link>
          <button className="btn primary" disabled={!dirty || busy} onClick={save}>{busy ? <span className="spinner" /> : null}Save &amp; render</button>
        </div>
      </div>

      <div className="editor-layout">
        <div className="stack" style={{ alignItems: "center" }}>
          <div className="ed-preview" style={{ width: PREVIEW_W }} onClick={toggle} aria-label="Video preview">
            <canvas ref={bg} width={108} height={192} className="ed-bg" />
            <div className="ed-fg" style={{ height: `${boxHeight * 100}%` }}>
              <video ref={video} src={api.sourceUrl(data.id)} preload="auto" playsInline
                onLoadedMetadata={(ev) => { const v = ev.currentTarget; if (v.videoWidth) setAspect(v.videoWidth / v.videoHeight); v.currentTime = e.start; v.playbackRate = e.speed; }}
                onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
                style={{ objectPosition: `${e.pan_x * 100}% ${e.pan_y * 100}%`, transform: `scale(${e.zoom})`, transformOrigin: `${e.pan_x * 100}% ${e.pan_y * 100}%` }} />
            </div>
            {inRange && overlay?.title.enabled && first.video_title.trim() && out < overlay.title.duration &&
              <div className="ov-text" style={css(overlay.title)}>{first.video_title.replace(/\p{Extended_Pictographic}/gu, "")}</div>}
            {overlay?.captions.enabled && caption && <div className="ov-text" style={css(overlay.captions)}>{caption.text}</div>}
            {inRange && e.texts.map((x, i) => out >= x.start && out < x.end &&
              <div key={i} className="ov-text" style={css(x)}>{x.text}</div>)}
            {!inRange && <div className="ed-outside">Outside the kept part</div>}
          </div>
          <div className="row" style={{ width: PREVIEW_W }}>
            <button className="btn icon" aria-label={playing ? "Pause" : "Play"} onClick={toggle}>{playing ? <Pause size={15} /> : <Play size={15} />}</button>
            <span className="small mono">{fmt(out)} / {fmt(outLen)}</span>
            <span className="spacer" />
            <span className="small faint">Space plays · [ ] set start/end</span>
          </div>
        </div>

        <div className="stack" style={{ minWidth: 0, gap: 14 }}>
          <div className="card stack">
            <div className="row"><h2>Trim</h2><span className="spacer" />
              <button className="btn ghost sm" onClick={() => patch({ start: r1(data.original_start), end: r1(data.original_start + data.original_duration) })}><RotateCcw size={12} />Vyral's cut</button></div>
            <div className="ed-timeline" ref={bar} onPointerDown={(ev) => seek(atX(ev.clientX))} role="slider" aria-label="Playhead"
              onKeyDown={(ev) => {
                const d = ev.key === "ArrowLeft" ? -1 : ev.key === "ArrowRight" ? 1 : 0;
                if (d) { ev.preventDefault(); seek(t + d * (ev.shiftKey ? 5 : 0.5)); }
              }}
              aria-valuemin={0} aria-valuemax={total} aria-valuenow={r1(t)} tabIndex={0}>
              <div className="ed-orig" style={{ left: pct(data.original_start), width: pct(data.original_duration) }} title="The part Vyral matched" />
              <div className="ed-keep" style={{ left: pct(e.start), width: pct(len) }} />
              <div className="ed-handle" style={{ left: pct(e.start) }} onPointerDown={drag("start")} title="Drag to change the start" />
              <div className="ed-handle" style={{ left: pct(e.end) }} onPointerDown={drag("end")} title="Drag to change the end" />
              <div className="ed-head" style={{ left: pct(t) }} />
            </div>
            <div className="ed-track" aria-label="Captions">
              {chunks.map((c, i) => <div key={i} className="ed-chip cap" style={{ left: pct(secOf(Math.max(0, c.start))), width: pct((Math.min(c.end, outLen) - Math.max(0, c.start)) * e.speed) }} title={c.text} />)}
            </div>
            {e.texts.length > 0 && <div className="ed-track" aria-label="Text overlays">
              {e.texts.map((x, i) => <div key={i} className={`ed-chip txt${selText === i ? " sel" : ""}`} onClick={() => setSelText(i)}
                style={{ left: pct(secOf(x.start)), width: pct((Math.min(x.end, outLen) - x.start) * e.speed) }} title={x.text}>{x.text}</div>)}
            </div>}
            <div className="ov-grid">
              <div className="field"><label htmlFor="ed-start">Start (s)</label>
                <NumField id="ed-start" min={0} value={e.start} onCommit={setStart} /></div>
              <div className="field"><label htmlFor="ed-end">End (s)</label>
                <NumField id="ed-end" max={r1(total)} value={e.end} onCommit={setEnd} /></div>
              <div className="field"><span className="label-text">At the playhead</span>
                <div className="row"><button className="btn sm" onClick={() => setStart(t)}>Set start</button><button className="btn sm" onClick={() => setEnd(t)}>Set end</button></div></div>
            </div>
            <p className="small faint">Kept {len.toFixed(1)} s of the {total.toFixed(0)} s that was downloaded. The shaded band is the part Vyral matched to the post.</p>
          </div>

          <div className="card stack">
            <div className="row"><h2>Framing, zoom and speed</h2><span className="spacer" />
              <button className="btn ghost sm" onClick={() => patch({ video_height: data.default_video_height, zoom: 1, pan_x: 0.5, pan_y: 0.5, layout: data.edit.cam ? "stacked" : "normal" })}>
                <RotateCcw size={12} />Reset to default</button></div>
            <div className="field"><span className="label-text">Framing</span>
              <div className="seg" role="group" aria-label="Framing" style={{ alignSelf: "flex-start" }}>
                <button className={!stacked && zoomedIn ? "on" : ""} onClick={() => patch({ layout: "normal", video_height: zoomedIn ? e.video_height : data.default_video_height })}>Zoomed in</button>
                <button className={!stacked && !zoomedIn ? "on" : ""} onClick={() => patch({ layout: "normal", video_height: 0 })}>Fit to frame</button>
                {e.cam && <button className={stacked ? "on" : ""} onClick={() => patch({ layout: "stacked" })}>Facecam on bottom</button>}
              </div>
              <span className="hint">{stacked ? "Vyral found the streamer's facecam: the content fills the top and the facecam is scaled up underneath. The preview here shows the normal framing; the rendered video uses this layout. Left / right picks which part of the content stays in view."
                : zoomedIn ? "The stream is scaled up and its sides trimmed so the speaker is bigger on a phone. Left / right picks what stays in view."
                : "The whole stream across the width of the frame, with blurred footage above and below."}</span></div>
            {zoomedIn && !stacked && (
              <div className="field"><label htmlFor="ed-size">Video size: {Math.round(boxHeight * 100)}% of the frame's height</label>
                <input id="ed-size" type="range" min={Math.min(1, fullWidth + 0.01)} max={1} step={0.01} value={boxHeight}
                  onChange={(ev) => patch({ video_height: Number(ev.target.value) }, "size")} /></div>
            )}
            <div className="ov-grid">
              <div className="field"><label htmlFor="ed-zoom">Zoom: {e.zoom.toFixed(2)}x</label>
                <input id="ed-zoom" type="range" min={1} max={3} step={0.05} value={e.zoom} onChange={(ev) => patch({ zoom: Number(ev.target.value) }, "zoom")} /></div>
              <div className="field"><label htmlFor="ed-px">Left / right</label>
                <input id="ed-px" type="range" min={0} max={1} step={0.01} value={e.pan_x} disabled={e.zoom <= 1 && boxHeight <= fullWidth} onChange={(ev) => patch({ pan_x: Number(ev.target.value) }, "px")} /></div>
              <div className="field"><label htmlFor="ed-py">Up / down{e.zoom <= 1 ? " (zoom in to use)" : ""}</label>
                <input id="ed-py" type="range" min={0} max={1} step={0.01} value={e.pan_y} disabled={e.zoom <= 1} onChange={(ev) => patch({ pan_y: Number(ev.target.value) }, "py")} /></div>
            </div>
            <div className="field"><span className="label-text">Speed</span>
              <div className="seg" role="group" aria-label="Speed" style={{ alignSelf: "flex-start" }}>
                {SPEEDS.map((s) => <button key={s} className={e.speed === s ? "on" : ""} onClick={() => patch({ speed: s })}>{s}x</button>)}</div></div>
            {e.gaps.length > 0 && (
              <div className="field"><span className="label-text">Dead air</span>
                <div className="seg" role="group" aria-label="Dead air" style={{ alignSelf: "flex-start" }}>
                  <button className={e.cut_dead_air ? "on" : ""} onClick={() => patch({ cut_dead_air: true })}>Cut out</button>
                  <button className={e.cut_dead_air ? "" : "on"} onClick={() => patch({ cut_dead_air: false })}>Keep</button></div>
                <span className="hint">{`${e.gaps.length} silent stretch${e.gaps.length === 1 ? "" : "es"} (${e.gaps.reduce((n, [a, b]) => n + b - a, 0).toFixed(1)}s). `}
                  The preview plays them; the rendered video skips them, so your own text may land a little earlier than shown.</span></div>
            )}
          </div>

          <div className="card stack">
            <div className="row"><h2>Thumbnail</h2><span className="spacer" />
              {e.thumb_at !== null && <button className="btn ghost sm" onClick={() => seek(e.thumb_at!)}>Show it</button>}
              <button className="btn sm" onClick={() => patch({ thumb_at: Math.round(t * 100) / 100 })}>Use this frame</button></div>
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              {first?.has_thumbnail && <img src={api.thumbUrl(first.id, false, first.version)} alt="Current thumbnail"
                style={{ width: 72, height: 128, objectFit: "cover", borderRadius: 6, background: "var(--card-3)", flex: "none" }} />}
              <p className="small faint" style={{ margin: 0 }}>{e.thumb_at === null ? "Vyral uses the frame one second in. " : `Cover frame: ${fmt(e.thumb_at - e.start)} into the clip. `}
                Pause the video where you want, then Use this frame. It's saved as a JPG next to each video and set as the video's cover. Saving re-renders, and the picture here updates when it's done.</p></div>
          </div>

          <div className="card stack">
            <div className="row"><h2>Text</h2><span className="spacer" /><button className="btn sm" disabled={e.texts.length >= 20} onClick={addText}><Plus size={13} />Add text</button></div>
            <p className="small faint">Extra text on top of the title and captions. Times are in the finished clip. To change the title or caption style, use Edit text in Ready to Upload.</p>
            {e.texts.map((x, i) => (
              <fieldset key={i} className={`ed-textrow${selText === i ? " sel" : ""}`} onFocus={() => setSelText(i)}>
                <div className="row">
                  <input className="input" aria-label={`Text ${i + 1}`} value={x.text} maxLength={200} onChange={(ev) => setText(i, { text: ev.target.value }, "t")} />
                  <button className="btn ghost icon" aria-label={`Remove text ${i + 1}`} onClick={() => { h.set({ ...e, texts: e.texts.filter((_, j) => j !== i) }); setSelText(null); }}><Trash2 size={14} /></button>
                </div>
                <div className="ov-grid">
                  <div className="field"><label htmlFor={`tx${i}-s`}>From (s)</label>
                    <NumField id={`tx${i}-s`} min={0} value={x.start} onCommit={(v) => setText(i, { start: r1(clamp(v, 0, x.end - 0.1)) })} /></div>
                  <div className="field"><label htmlFor={`tx${i}-e`}>To (s)</label>
                    <NumField id={`tx${i}-e`} min={0} value={x.end} onCommit={(v) => setText(i, { end: r1(Math.max(x.start + 0.1, v)) })} /></div>
                  <div className="field"><label htmlFor={`tx${i}-f`}>Font</label>
                    <select id={`tx${i}-f`} className="select" value={x.font} onChange={(ev) => setText(i, { font: ev.target.value as FontKey })}>
                      {FONTS.map(([kk, nn]) => <option key={kk} value={kk}>{nn}</option>)}</select></div>
                  <div className="field"><label htmlFor={`tx${i}-z`}>Size: {x.size}</label>
                    <input id={`tx${i}-z`} type="range" min={30} max={160} value={x.size} onChange={(ev) => setText(i, { size: Number(ev.target.value) }, "z")} /></div>
                  <div className="field"><label htmlFor={`tx${i}-y`}>Position: {x.y_percent}% from top</label>
                    <input id={`tx${i}-y`} type="range" min={5} max={95} value={x.y_percent} onChange={(ev) => setText(i, { y_percent: Number(ev.target.value) }, "y")} /></div>
                  <div className="field"><span className="label-text">Color</span>
                    <div className="ov-color">
                      <input type="color" aria-label={`Text ${i + 1} color`} value={x.color} onChange={(ev) => setText(i, { color: ev.target.value.toUpperCase() }, "c")} />
                      {SWATCHES.map((c) => <button key={c} type="button" aria-label={`Text ${i + 1} color ${c}`} onClick={() => setText(i, { color: c })}
                        style={{ width: 18, height: 18, borderRadius: 5, background: c, border: x.color.toUpperCase() === c ? "2px solid var(--accent-hi)" : "1px solid var(--line-2)", cursor: "pointer" }} />)}
                    </div></div>
                  <label className="check" style={{ alignSelf: "end" }}><input type="checkbox" checked={x.all_caps} onChange={(ev) => setText(i, { all_caps: ev.target.checked })} />ALL CAPS</label>
                </div>
              </fieldset>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
