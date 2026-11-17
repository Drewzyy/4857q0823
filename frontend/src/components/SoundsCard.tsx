import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Music, Play, Plus, Trash2, Upload } from "lucide-react";
import { api, type ClipEditT } from "../lib/api";

/** Sound effects on the clip. Times are in the downloaded footage, like the trim, so moving the trim keeps them on their moment. */
export function SoundsCard({ e, patch, at, seek, toast }: { e: ClipEditT; patch: (p: Partial<ClipEditT>, key?: string) => void; at: number; seek: (s: number) => void;
  toast: (kind: "ok" | "err", text: string) => void }) {
  const qc = useQueryClient();
  const sounds = useQuery({ queryKey: ["sounds"], queryFn: api.sounds, staleTime: Infinity });
  const file = useRef<HTMLInputElement>(null);
  const [pick, setPick] = useState("boom");
  const [uploading, setUploading] = useState(false);
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      let last = "";
      for (const f of Array.from(files)) last = `lib:${(await api.addToLibrary(f)).id}`;
      await qc.invalidateQueries({ queryKey: ["sounds"] });
      setPick(last);
      toast("ok", files.length === 1 ? "Sound added. It's in the list for every clip." : `Added ${files.length} sounds.`);
    } catch (err) { toast("err", err instanceof Error ? err.message : String(err)); }
    finally { setUploading(false); if (file.current) file.current.value = ""; }
  };
  const player = useRef<HTMLAudioElement | null>(null);
  const list = e.sounds ?? [];
  const label = (n: string) => sounds.data?.find((x) => x.name === n)?.label ?? n;
  const preview = (name: string) => {
    player.current?.pause();
    player.current = new Audio(api.soundUrl(name));
    void player.current.play().catch(() => undefined);
  };
  const set = (i: number, p: Partial<ClipEditT["sounds"][number]>, key = "") => patch({ sounds: list.map((x, j) => (j === i ? { ...x, ...p } : x)) }, `snd${i}${key}`);
  const inClip = at >= e.start && at < e.end;
  return (
    <div className="card stack">
      <div className="row"><h2>Sound effects</h2><span className="spacer" />
        <select className="select" aria-label="Sound to add" value={pick} onChange={(ev) => setPick(ev.target.value)} style={{ width: 150 }}>
          <optgroup label="Vyral's">{(sounds.data ?? []).filter((s) => !s.mine).map((s) => <option key={s.name} value={s.name} title={s.use}>{s.label}</option>)}</optgroup>
          {(sounds.data ?? []).some((s) => s.mine) && <optgroup label="Yours">{(sounds.data ?? []).filter((s) => s.mine).map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}</optgroup>}</select>
        <button className="btn ghost icon" aria-label="Hear it" title="Hear it" onClick={() => preview(pick)}><Play size={13} /></button>
        <button className="btn sm" disabled={list.length >= 20 || !inClip} title={inClip ? "Adds it where the playhead is" : "Move the playhead inside the kept part"}
          onClick={() => patch({ sounds: [...list, { name: pick, at: Math.round(at * 100) / 100, volume: 0.6 }].sort((a, b) => a.at - b.at) })}><Plus size={13} />Add at playhead</button>
      </div>
      <div className="row wrap small faint" style={{ gap: 8 }}>
        <span style={{ flex: 1, minWidth: 220 }}>{sounds.data?.find((x) => x.name === pick)?.use ?? ""}. One sound on the biggest moment lands; several in a short clip usually feel forced.</span>
        <input ref={file} type="file" hidden multiple accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.opus,.flac" aria-label="Sound files" onChange={(ev) => void upload(ev.target.files)} />
        <button className="btn sm" disabled={uploading} onClick={() => file.current?.click()}>{uploading ? <span className="spinner" /> : <Upload size={13} />}Add your own sound</button>
      </div>
      {list.length === 0 ? <p className="small faint">No sound effects on this clip.</p> : list.map((s, i) => (
        <div key={i} className="row small" style={{ gap: 8 }}>
          <Music size={13} /><strong style={{ width: 110 }}>{label(s.name)}</strong>
          <button className="btn ghost sm" title="Jump to it" onClick={() => seek(s.at)}>{(s.at - e.start).toFixed(1)} s</button>
          <button className="btn ghost sm" title="Move it to the playhead" disabled={!inClip} onClick={() => set(i, { at: Math.round(at * 100) / 100 })}>Move here</button>
          <label className="small" htmlFor={`snd-vol-${i}`}>Volume</label>
          <input id={`snd-vol-${i}`} type="range" min={0.05} max={1.5} step={0.05} value={s.volume} style={{ width: 90 }} onChange={(ev) => set(i, { volume: Number(ev.target.value) }, "v")} />
          <span className="spacer" />
          <button className="btn ghost icon" aria-label={`Hear ${label(s.name)}`} onClick={() => preview(s.name)}><Play size={13} /></button>
          <button className="btn ghost icon" aria-label={`Remove ${label(s.name)}`} onClick={() => patch({ sounds: list.filter((_, j) => j !== i) })}><Trash2 size={13} /></button>
        </div>
      ))}
    </div>
  );
}
