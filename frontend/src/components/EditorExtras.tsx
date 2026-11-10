import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Image as ImageIcon, Layers, Plus, Save, Trash2, Upload } from "lucide-react";
import { api, type ClipEditT, type LayerT, type MediaItemT } from "../lib/api";

const r1 = (v: number) => Math.round(v * 10) / 10;

/** The media library and presets: gameplay to split the screen with, and animations or clips on top. */
export function useLibrary() {
  const library = useQuery({ queryKey: ["library"], queryFn: api.library });
  const presets = useQuery({ queryKey: ["presets"], queryFn: api.presets });
  return { items: library.data ?? [], presets: presets.data ?? [] };
}

/** A library layer as it looks in the preview, while it's on screen. */
export function LayerPreview({ layer, item, at }: { layer: LayerT; item?: MediaItemT; at: number }) {
  if (!item || at < layer.start || at >= layer.end) return null;
  const style = { position: "absolute" as const, left: `${layer.x * 100}%`, top: `${layer.y * 100}%`, width: `${layer.width * 100}%`,
    transform: "translate(-50%, -50%)", pointerEvents: "none" as const, zIndex: 2 };
  return item.kind === "video"
    ? <video src={api.libraryUrl(item.id)} muted autoPlay loop playsInline style={style} />
    : <img src={api.libraryUrl(item.id)} alt="" style={style} />;
}

export function EditorExtras({ e, patch, at, outLen, toast }: {
  e: ClipEditT; patch: (p: Partial<ClipEditT>, key?: string) => void; at: number; outLen: number;
  toast: (kind: "ok" | "err", text: string) => void;
}) {
  const qc = useQueryClient();
  const { items, presets } = useLibrary();
  const file = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [presetName, setPresetName] = useState("");
  const byId = new Map(items.map((m) => [m.id, m]));
  const fail = (err: unknown) => toast("err", err instanceof Error ? err.message : String(err));

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) await api.addToLibrary(f);
      await qc.invalidateQueries({ queryKey: ["library"] });
      toast("ok", files.length === 1 ? "Added to your library." : `Added ${files.length} files to your library.`);
    } catch (err) { fail(err); }
    finally { setUploading(false); if (file.current) file.current.value = ""; }
  };
  const setLayer = (i: number, p: Partial<LayerT>, key = "") => patch({ layers: e.layers.map((x, j) => (j === i ? { ...x, ...p } : x)) }, `layer${i}${key}`);
  const addLayer = (m: MediaItemT) => {
    const start = r1(Math.min(at, Math.max(0, outLen - 1)));
    const end = r1(Math.min(outLen, start + Math.min(m.duration ?? 2, 3)));
    patch({ layers: [...e.layers, { media_id: m.id, start, end: Math.max(end, start + 0.5), x: 0.5, y: 0.3, width: 0.4 }] });
  };
  const applyPreset = (id: number) => {
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    const fit = <T extends { start: number; end: number }>(xs: T[]) => xs.filter((x) => x.start < outLen).map((x) => ({ ...x, end: Math.min(x.end, outLen) }));
    patch({
      texts: [...e.texts, ...fit(p.data.texts)].slice(0, 20), layers: [...e.layers, ...fit(p.data.layers)].slice(0, 20),
      ...(p.data.bottom_media ? { layout: "split" as const, bottom_media: p.data.bottom_media } : {}),
    });
    toast("ok", `Added "${p.name}". Save to render it.`);
  };
  const savePreset = async () => {
    if (!presetName.trim()) return;
    try {
      await api.addPreset(presetName.trim(), { texts: e.texts, layers: e.layers, bottom_media: e.layout === "split" ? e.bottom_media : null });
      await qc.invalidateQueries({ queryKey: ["presets"] });
      setPresetName("");
      toast("ok", "Preset saved. Apply it to any clip from here.");
    } catch (err) { fail(err); }
  };
  const removePreset = async (id: number) => {
    try { await api.removePreset(id); await qc.invalidateQueries({ queryKey: ["presets"] }); } catch (err) { fail(err); }
  };
  const removeItem = async (m: MediaItemT) => {
    try {
      await api.removeFromLibrary(m.id);
      await qc.invalidateQueries({ queryKey: ["library"] });
      patch({ layers: e.layers.filter((x) => x.media_id !== m.id), ...(e.bottom_media === m.id ? { bottom_media: null, layout: "normal" as const } : {}) });
    } catch (err) { fail(err); }
  };

  return (
    <div className="card stack">
      <div className="row"><Layers size={16} /><h2>Presets and overlays</h2></div>
      <p className="small faint" style={{ margin: 0 }}>
        Put animations, reaction clips or stickers on top for part of the clip, or gameplay under the stream (Framing &gt; Gameplay on bottom).
        Save the mix as a preset to drop it on any clip in one click.</p>

      <div className="stack" style={{ gap: 6 }}>
        <span className="label-text">Presets</span>
        {presets.length === 0 ? <p className="small faint" style={{ margin: 0 }}>No presets yet. Set up texts and overlays on this clip, then save them below.</p> : (
          <div className="row wrap" style={{ gap: 6 }}>
            {presets.map((p) => (
              <span key={p.id} className="chip" style={{ gap: 4 }}>
                <button className="btn sm ghost" style={{ padding: "0 4px" }} onClick={() => applyPreset(p.id)} title={`${p.data.layers.length} overlays, ${p.data.texts.length} texts${p.data.bottom_media ? ", gameplay" : ""}`}>
                  <Plus size={12} />{p.name}</button>
                <button className="btn ghost icon" aria-label={`Delete preset ${p.name}`} onClick={() => removePreset(p.id)}><Trash2 size={12} /></button>
              </span>
            ))}
          </div>
        )}
        <div className="row">
          <input className="input" aria-label="New preset name" placeholder="Name this clip's texts and overlays as a preset" value={presetName} maxLength={120}
            onChange={(ev) => setPresetName(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter") void savePreset(); }} />
          <button className="btn sm" disabled={!presetName.trim() || (e.texts.length === 0 && e.layers.length === 0 && e.layout !== "split")} onClick={savePreset}>
            <Save size={13} />Save preset</button>
        </div>
      </div>

      <div className="stack" style={{ gap: 6 }}>
        <div className="row"><span className="label-text">Library</span><span className="spacer" />
          <input ref={file} type="file" hidden multiple accept="video/mp4,video/quicktime,video/webm,.mkv,image/png,image/jpeg,image/gif,image/webp"
            aria-label="Add files to library" onChange={(ev) => void upload(ev.target.files)} />
          <button className="btn sm" disabled={uploading} onClick={() => file.current?.click()}>{uploading ? <span className="spinner" /> : <Upload size={13} />}Add videos or pictures</button></div>
        {items.length === 0 ? <p className="small faint" style={{ margin: 0 }}>Add gameplay footage (for split screen), animations, or PNG stickers with transparent backgrounds.</p> : (
          <div className="stack" style={{ gap: 4 }}>
            {items.map((m) => (
              <div key={m.id} className="list-row small">
                {m.kind === "video" ? <Film size={14} /> : <ImageIcon size={14} />}
                <span className="ellipsis" style={{ maxWidth: 220 }} title={m.name}>{m.name}</span>
                {m.duration ? <span className="faint">{m.duration.toFixed(1)}s</span> : null}
                <span className="spacer" />
                <button className="btn sm" onClick={() => addLayer(m)}>Put on top</button>
                {m.kind === "video" && <button className={`btn sm${e.layout === "split" && e.bottom_media === m.id ? " primary" : ""}`}
                  onClick={() => patch({ layout: "split", bottom_media: m.id })}>Gameplay on bottom</button>}
                <button className="btn ghost icon" aria-label={`Remove ${m.name} from library`} onClick={() => removeItem(m)}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      {e.layers.map((ly, i) => {
        const m = byId.get(ly.media_id);
        return (
          <fieldset key={i} className="ed-textrow">
            <div className="row"><strong className="small ellipsis">{m?.name ?? "Removed from library"}</strong><span className="spacer" />
              <button className="btn ghost icon" aria-label={`Remove overlay ${i + 1}`} onClick={() => patch({ layers: e.layers.filter((_, j) => j !== i) })}><Trash2 size={14} /></button></div>
            <div className="ov-grid">
              <div className="field"><label htmlFor={`ly${i}-s`}>From (s)</label>
                <input id={`ly${i}-s`} className="input" type="number" step={0.1} min={0} value={ly.start}
                  onChange={(ev) => setLayer(i, { start: r1(Math.max(0, Math.min(Number(ev.target.value), ly.end - 0.1))) }, "s")} /></div>
              <div className="field"><label htmlFor={`ly${i}-e`}>To (s)</label>
                <input id={`ly${i}-e`} className="input" type="number" step={0.1} min={0} value={ly.end}
                  onChange={(ev) => setLayer(i, { end: r1(Math.max(ly.start + 0.1, Number(ev.target.value))) }, "e")} /></div>
              <div className="field"><label htmlFor={`ly${i}-w`}>Size: {Math.round(ly.width * 100)}% of the width</label>
                <input id={`ly${i}-w`} type="range" min={0.05} max={1} step={0.01} value={ly.width} onChange={(ev) => setLayer(i, { width: Number(ev.target.value) }, "w")} /></div>
              <div className="field"><label htmlFor={`ly${i}-x`}>Left / right</label>
                <input id={`ly${i}-x`} type="range" min={0} max={1} step={0.01} value={ly.x} onChange={(ev) => setLayer(i, { x: Number(ev.target.value) }, "x")} /></div>
              <div className="field"><label htmlFor={`ly${i}-y`}>Up / down</label>
                <input id={`ly${i}-y`} type="range" min={0} max={1} step={0.01} value={ly.y} onChange={(ev) => setLayer(i, { y: Number(ev.target.value) }, "y")} /></div>
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
