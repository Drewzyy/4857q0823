import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Settings2, Trash2, Upload, X } from "lucide-react";
import CreatorPicker from "../components/CreatorPicker";
import { api, PLATFORM_LABEL, type Creator, type Destination, type DestinationSettings, type Platform } from "../lib/api";
import { ConfirmModal, CreatorChip, Empty, ErrorNote, Loading, Modal, PlatformBadge, Toggle, useToast } from "../components/ui";
import { OverlayEditor } from "../components/OverlayEditor";

const DEST_PLATFORMS: Platform[] = ["tiktok", "instagram", "youtube", "facebook"];

export default function Destinations() {
  const qc = useQueryClient();
  const toast = useToast();
  const dests = useQuery({ queryKey: ["destinations"], queryFn: api.destinations });
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const [editing, setEditing] = useState<Destination | null>(null);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Destination | null>(null);
  const refresh = () => ["destinations", "dashboard", "funnel"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const err = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));
  const quick = useMutation({ mutationFn: ({ id, b }: { id: number; b: Parameters<typeof api.updateDestination>[1] }) => api.updateDestination(id, b), onSuccess: refresh, onError: err });

  const list = dests.data ?? [];
  const grouped = DEST_PLATFORMS.map((p) => [p, list.filter((d) => d.platform === p)] as const).filter(([, l]) => l.length);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Destinations</h1><p>The pages you post clips to. You upload yourself, so there's nothing to log in to: just a name and the handle so you know where each clip goes.</p></div>
        <button className="btn primary" onClick={() => setAdding(true)}><Plus size={14} />Add destination</button>
      </div>

      {dests.error && <ErrorNote error={dests.error} />}
      {dests.isLoading ? <Loading /> : list.length === 0 ? (
        <div className="card"><Empty icon={<Upload size={28} />} title="No destinations yet">
          <p className="small">Add each page you post to, for example "Streamer A TikTok" with handle @streamera.clips.</p>
          <button className="btn primary" onClick={() => setAdding(true)}><Plus size={14} />Add destination</button></Empty></div>
      ) : grouped.map(([plat, items]) => (
        <section key={plat} style={{ marginBottom: 22 }}>
          <div className="row" style={{ marginBottom: 10 }}><PlatformBadge platform={plat} /><h2>{PLATFORM_LABEL[plat]}</h2><span className="faint small">{items.length}</span></div>
          <div className="grid cols-3">
            {items.map((d) => (
              <div className="card" key={d.id} style={{ opacity: d.enabled ? 1 : 0.6 }}>
                <InlineNames d={d} onSave={(b) => quick.mutateAsync({ id: d.id, b })} />
                <div className="row wrap small" style={{ marginTop: 12, gap: 10 }}>
                  {d.creator_ids.length === 0 ? <span className="faint small">Any streamer</span>
                    : d.creator_ids.map((id) => <CreatorChip key={id} creator={(creators.data ?? []).find((c) => c.id === id) ?? null} />)}
                  <span className="faint">{d.route_count} source{d.route_count === 1 ? "" : "s"} feeding it</span>
                  <span className="faint">{d.settings.format.resolution} · {d.settings.format.fps} fps max</span>
                </div>
                <div className="row" style={{ marginTop: 14 }}>
                  <button className="btn sm" onClick={() => setEditing(d)}><Settings2 size={12} />Text, caption & format</button>
                  <span className="spacer" />
                  <Toggle label={`Make clips for ${d.display_name}`} checked={d.enabled} onChange={(v) => quick.mutate({ id: d.id, b: { enabled: v } })} />
                  <button className="btn ghost icon" aria-label={`Remove ${d.display_name}`} onClick={() => setRemoving(d)}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      {editing && <SettingsModal dest={editing} creators={creators.data ?? []} onClose={() => setEditing(null)} onSaved={() => { refresh(); setEditing(null); toast("ok", "Saved"); }} />}
      {adding && <AddModal creators={creators.data ?? []} onClose={() => setAdding(false)} onDone={refresh} />}
      <ConfirmModal open={!!removing} title="Remove destination?" danger confirmLabel="Remove"
        message={<>{removing?.display_name} and its funnel routes will be removed. Clips already made for it stay in Ready to Upload.</>}
        onClose={() => setRemoving(null)} onConfirm={async () => {
          try { if (removing) await api.deleteDestination(removing.id); refresh(); } catch (e) { err(e); } setRemoving(null);
        }} />
    </div>
  );
}

function InlineNames({ d, onSave }: { d: Destination; onSave: (b: { display_name: string; handle: string }) => Promise<unknown> }) {
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(d.display_name);
  const [handle, setHandle] = useState(d.handle);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try { await onSave({ display_name: name, handle }); setEdit(false); setError(null); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  if (!edit) return (
    <div className="row">
      <PlatformBadge platform={d.platform} large />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="ellipsis" style={{ fontWeight: 600 }}>{d.display_name}</div>
        <div className="small faint ellipsis">{d.handle || "No handle set"}</div>
      </div>
      <button className="btn ghost icon" aria-label={`Rename ${d.display_name}`} onClick={() => { setName(d.display_name); setHandle(d.handle); setEdit(true); }}><Pencil size={14} /></button>
    </div>
  );
  return (
    <form className="stack" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }}>
      <input className="input" aria-label="Destination name" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Streamer A TikTok" />
      <input className="input" aria-label="Destination handle" value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@handle or profile link" />
      {error && <span className="small" style={{ color: "#ff8a8d" }}>{error}</span>}
      <div className="row"><button className="btn primary sm" disabled={!name.trim()}><Check size={12} />Save</button>
        <button type="button" className="btn ghost sm" onClick={() => setEdit(false)}><X size={12} />Cancel</button></div>
    </form>
  );
}

function AddModal({ creators, onClose, onDone }: { creators: Creator[]; onClose: () => void; onDone: () => void }) {
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [name, setName] = useState("");
  const [handle, setHandle] = useState("");
  const [creatorIds, setCreatorIds] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try { await api.addDestination({ platform, display_name: name, handle, creator_ids: creatorIds }); onDone(); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Modal open onClose={onClose} title="Add destination" footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!name.trim()} onClick={save}>Add</button></>}>
      <form className="grid cols-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }}>
        <div className="field"><label htmlFor="ad-plat">Platform</label>
          <select id="ad-plat" className="select" value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
            {DEST_PLATFORMS.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</select></div>
        <div className="field"><span className="label-text">Streamers whose clips go here</span>
          <CreatorPicker label="Streamers for this page" creators={creators} value={creatorIds} onChange={setCreatorIds} empty="Any streamer" hint="Clips of any streamer picked here go to this page. Pick none to take every streamer's clips." /></div>
        <div className="field"><label htmlFor="ad-name">Name</label><input id="ad-name" className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Streamer A TikTok" /></div>
        <div className="field"><label htmlFor="ad-handle">Handle</label><input id="ad-handle" className="input" value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@streamera.clips" /></div>
      </form>
      {error && <ErrorNote error={error} />}
    </Modal>
  );
}

function SettingsModal({ dest, creators, onClose, onSaved }: { dest: Destination; creators: Creator[]; onClose: () => void; onSaved: () => void }) {
  const [creatorIds, setCreatorIds] = useState<number[]>(dest.creator_ids ?? []);
  const [s, setS] = useState<DestinationSettings>(structuredClone(dest.settings));
  const [hashtags, setHashtags] = useState(dest.settings.hashtags.join(" "));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true); setError(null);
    const tags = hashtags.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`));
    try { await api.updateDestination(dest.id, { creator_ids: creatorIds, settings: { default_caption: s.default_caption, hashtags: tags, format: s.format, overlay: s.overlay } }); onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const resolutions: Record<string, string[]> = { "9:16": ["1080x1920", "720x1280"], "16:9": ["1920x1080"], "1:1": ["1080x1080"] };
  const fmt = (v: Partial<DestinationSettings["format"]>) => setS({ ...s, format: { ...s.format, ...v } });

  return (
    <Modal open wide onClose={onClose} title={<span className="row"><PlatformBadge platform={dest.platform} />{dest.display_name}</span>}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save} disabled={busy}>{busy && <span className="spinner" />}Save</button></>}>
      <div className="field"><span className="label-text">Streamers whose clips go here</span>
        <CreatorPicker label="Streamers for this page" creators={creators} value={creatorIds} onChange={setCreatorIds} empty="Any streamer" hint="Clips of any streamer picked here go to this page. Pick none to take every streamer's clips." /></div>
      <h3>Caption added to every clip</h3>
      <div className="field"><label htmlFor="ds-cap">Extra caption text</label>
        <textarea id="ds-cap" className="textarea" rows={2} maxLength={2200} value={s.default_caption} onChange={(e) => setS({ ...s, default_caption: e.target.value })} placeholder="Follow for daily clips" /></div>
      <div className="field"><label htmlFor="ds-tags">Hashtags</label><input id="ds-tags" className="input" value={hashtags} onChange={(e) => setHashtags(e.target.value)} placeholder="#gaming #streamer" />
        <span className="hint">Every caption gets the source post's own hashtags, these, and #vyralclips (YouTube also gets #shorts). @mentions from the post are removed.</span></div>
      <h3>Text on the video</h3>
      <p className="small faint" style={{ marginTop: -6 }}>The title shows at the top for the first seconds. Captions follow what's being said. These are the defaults for this page; you can still change any single clip before downloading it.</p>
      <OverlayEditor value={s.overlay} onChange={(overlay) => setS({ ...s, overlay })} title="He did NOT just say that" />
      <h3>Video format</h3>
      <div className="grid cols-4">
        <div className="field"><label htmlFor="ds-asp">Shape</label>
          <select id="ds-asp" className="select" value={s.format.aspect} onChange={(e) => { const aspect = e.target.value as DestinationSettings["format"]["aspect"]; fmt({ aspect, resolution: resolutions[aspect][0] }); }}>
            <option value="9:16">9:16 vertical</option><option value="16:9">16:9 horizontal</option><option value="1:1">1:1 square</option></select></div>
        <div className="field"><label htmlFor="ds-res">Resolution</label>
          <select id="ds-res" className="select" value={s.format.resolution} onChange={(e) => fmt({ resolution: e.target.value })}>
            {resolutions[s.format.aspect].map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
        <div className="field"><label htmlFor="ds-fps">Max frame rate</label>
          <select id="ds-fps" className="select" value={s.format.fps} onChange={(e) => fmt({ fps: Number(e.target.value) })}>
            <option value={60}>60 fps (highest platforms accept)</option><option value={30}>30 fps</option></select>
          <span className="hint">Clips keep the stream's own frame rate up to this. 60 fps streams stay 60.</span></div>
        <div className="field"><label htmlFor="ds-codec">Codec</label>
          <select id="ds-codec" className="select" value={s.format.codec} onChange={(e) => fmt({ codec: e.target.value as "h264" | "h265" })}>
            <option value="h264">H.264 (works everywhere)</option><option value="h265">H.265 (smaller file)</option></select></div>
      </div>
      <div className="field"><label htmlFor="ds-br">Quality ceiling: {s.format.bitrate_mbps} Mbps</label>
        <input id="ds-br" type="range" min={6} max={40} step={1} value={s.format.bitrate_mbps} onChange={(e) => fmt({ bitrate_mbps: Number(e.target.value) })} />
        <span className="hint">Vyral encodes at near-lossless quality up to this rate. It never upscales: if the stream is 720p the clip is honest 720p detail on a 1080p canvas.</span></div>
      {error && <ErrorNote error={error} />}
    </Modal>
  );
}
