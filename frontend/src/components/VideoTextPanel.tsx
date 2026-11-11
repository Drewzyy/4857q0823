import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, type ClipOutputT, type Overlay } from "../lib/api";
import { OverlayEditor } from "./OverlayEditor";
import type { useToast } from "./ui";

export interface TextClip { id: number; outputs: ClipOutputT[]; has_captions: boolean; captions_text: string }

/** The title burned into the video, its style and the caption style, and the caption words. */
export function VideoTextPanel({ o, clip, onChange, toast }: { o: ClipOutputT; clip: TextClip; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const [title, setTitle] = useState(o.video_title);
  const [overlay, setOverlay] = useState<Overlay>(structuredClone(o.overlay));
  const [all, setAll] = useState(true);
  const [captions, setCaptions] = useState(clip.captions_text);
  const [busy, setBusy] = useState(false);
  const styleDirty = JSON.stringify(overlay) !== JSON.stringify(o.overlay) || title !== o.video_title;
  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try { await fn(); toast("ok", msg); onChange(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="stack">
      <div className="field"><label htmlFor={`vt-${o.id}`}>Title on the video</label>
        <input id={`vt-${o.id}`} className="input" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Leave empty for no title" /></div>
      <OverlayEditor value={overlay} onChange={setOverlay} title={title} />
      <div className="row wrap">
        {clip.outputs.length > 1 && <label className="check small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Use this style for every page of this clip</label>}
        <span className="spacer" />
        <button className="btn primary" disabled={!styleDirty || busy || o.render_state === "rendering"}
          onClick={() => run(() => api.editVideoText(o.id, { video_title: title, overlay, apply_style_to_all: all }), "Re-rendering. The new version appears in a moment.")}>
          <RefreshCw size={14} />Re-render with changes</button>
      </div>
      {clip.has_captions && (
        <div className="field"><label htmlFor={`cap-${clip.id}`}>Caption words (fix anything misheard; timing is kept)</label>
          <textarea id={`cap-${clip.id}`} className="textarea" rows={3} value={captions} onChange={(e) => setCaptions(e.target.value)} />
          <div className="row"><span className="hint">Changes the captions on every page of this clip.</span><span className="spacer" />
            <button className="btn" disabled={captions === clip.captions_text || busy}
              onClick={() => run(() => api.editCaptions(clip.id, captions), "Captions updated. Re-rendering every page.")}>Save captions</button></div>
        </div>
      )}
      {o.render_state === "failed" && <div className="banner warn small">Re-render failed: {o.render_error}</div>}
    </div>
  );
}

