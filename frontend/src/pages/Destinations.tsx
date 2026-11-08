import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, LogIn, Plus, RefreshCw, Settings2, Trash2, Upload, X } from "lucide-react";
import { api, CONNECTOR_FOR, PLATFORM_LABEL, type Creator, type Destination, type DestinationSettings, type Platform } from "../lib/api";
import { useConnect } from "../components/ConnectFlow";
import { Avatar, ConfirmModal, CreatorChip, Empty, ErrorNote, Loading, Modal, PlatformBadge, StatusPill, Toggle, useToast } from "../components/ui";

const DEST_PLATFORMS: Platform[] = ["tiktok", "instagram", "youtube", "facebook"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function Destinations() {
  const qc = useQueryClient();
  const toast = useToast();
  const { connect, platforms, openSetup } = useConnect();
  const dests = useQuery({ queryKey: ["destinations"], queryFn: api.destinations });
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const [editing, setEditing] = useState<Destination | null>(null);
  const [planning, setPlanning] = useState(false);
  const [removing, setRemoving] = useState<Destination | null>(null);
  const refresh = () => ["destinations", "dashboard", "funnel", "connections"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const quick = useMutation({ mutationFn: ({ id, b }: { id: number; b: Parameters<typeof api.updateDestination>[1] }) => api.updateDestination(id, b),
    onSuccess: refresh, onError: (e) => toast("err", e instanceof Error ? e.message : String(e)) });

  const list = dests.data ?? [];
  const grouped = DEST_PLATFORMS.map((p) => [p, list.filter((d) => d.platform === p)] as const).filter(([, l]) => l.length);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Destination Accounts</h1><p>Where your clips get published. Click Connect and log in on the platform's own page. One Facebook login brings in every Page you manage and the Instagram accounts linked to them.</p></div>
        <button className="btn" onClick={() => setPlanning(true)}><Plus size={14} />Plan without logging in</button>
      </div>

      <div className="grid cols-3" style={{ marginBottom: 22 }}>
        {platforms.map((p) => (
          <div className="card" key={p.key}>
            <div className="row"><PlatformBadge platform={p.key} large /><div style={{ flex: 1 }}><h3>{p.label}</h3>
              <div className="small faint">{p.connections ? `${p.connections} login${p.connections > 1 ? "s" : ""} connected` : p.configured ? "Ready to connect" : "One-time setup needed"}</div></div></div>
            <div className="row" style={{ marginTop: 14 }}>
              <button className="btn primary" onClick={() => connect(p.key)}><LogIn size={14} />{p.connections ? "Connect another" : "Connect"}</button>
              {p.configured && <button className="btn ghost sm" onClick={() => openSetup(p.key)}>Setup</button>}
            </div>
          </div>
        ))}
      </div>

      {dests.error && <ErrorNote error={dests.error} />}
      {dests.isLoading ? <Loading /> : list.length === 0 ? (
        <div className="card"><Empty icon={<Upload size={28} />} title="No destination accounts yet">
          <p className="small">Connect an account above, or plan one now and log in later.</p></Empty></div>
      ) : grouped.map(([plat, items]) => (
        <section key={plat} style={{ marginBottom: 22 }}>
          <div className="row" style={{ marginBottom: 10 }}><PlatformBadge platform={plat} /><h2>{PLATFORM_LABEL[plat]}</h2><span className="faint small">{items.length}</span></div>
          <div className="grid cols-3">
            {items.map((d) => (
              <div className="card" key={d.id} style={{ opacity: d.enabled ? 1 : 0.6 }}>
                <div className="row">
                  <Avatar url={d.avatar_url} platform={d.platform} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="ellipsis" style={{ fontWeight: 600 }}>{d.display_name}</div>
                    <div className="small faint ellipsis">{d.handle ? (d.handle.startsWith("@") ? d.handle : `@${d.handle}`) : PLATFORM_LABEL[d.platform]}</div>
                  </div>
                  <StatusPill status={d.status} />
                </div>
                <div className="row wrap small" style={{ marginTop: 12, gap: 10 }}>
                  <CreatorChip creator={d.creator} />
                  <span className="faint">{d.route_count} source{d.route_count === 1 ? "" : "s"}</span>
                  <span className="faint">{d.settings.approval_required ? "Approval required" : "Auto-publish rule"}</span>
                  <span className="faint">{d.settings.visibility}</span>
                </div>
                {d.last_error && d.status !== "connected" && <p className="small" style={{ color: "#ff8a8d", marginTop: 8 }}>{d.last_error}</p>}
                <div className="row" style={{ marginTop: 14 }}>
                  {(d.status === "draft" || d.status === "disconnected" || d.status === "expired" || d.status === "error" || d.status === "expiring") && (
                    <button className="btn primary sm" onClick={() => connect(CONNECTOR_FOR[d.platform], { linkDestinationId: d.status === "draft" ? d.id : null })}>
                      {d.status === "draft" ? <><LogIn size={12} />Connect</> : <><RefreshCw size={12} />Reconnect</>}</button>
                  )}
                  <button className="btn sm" onClick={() => setEditing(d)}><Settings2 size={12} />Settings</button>
                  <span className="spacer" />
                  <Toggle label={`Enable ${d.display_name}`} checked={d.enabled} onChange={(v) => quick.mutate({ id: d.id, b: { enabled: v } })} />
                  <button className="btn ghost icon" aria-label={`Remove ${d.display_name}`} onClick={() => setRemoving(d)}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      {editing && <SettingsModal dest={editing} creators={creators.data ?? []} onClose={() => setEditing(null)} onSaved={() => { refresh(); setEditing(null); toast("ok", "Settings saved"); }} />}
      {planning && <PlanModal creators={creators.data ?? []} onClose={() => setPlanning(false)} onDone={refresh} />}
      <ConfirmModal open={!!removing} title="Remove destination?" danger confirmLabel="Remove"
        message={<>{removing?.display_name} and its routes will be removed from AI Clipper. Nothing changes on {removing ? PLATFORM_LABEL[removing.platform] : ""}.</>}
        onClose={() => setRemoving(null)} onConfirm={async () => {
          try { if (removing) await api.deleteDestination(removing.id); refresh(); } catch (e) { toast("err", String(e)); } setRemoving(null);
        }} />
    </div>
  );
}

function PlanModal({ creators, onClose, onDone }: { creators: Creator[]; onClose: () => void; onDone: () => void }) {
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [name, setName] = useState("");
  const [creatorId, setCreatorId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try { await api.addDestinationDraft({ platform, display_name: name, creator_id: creatorId }); onDone(); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Modal open onClose={onClose} title="Plan a destination" footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!name.trim()} onClick={save}>Add</button></>}>
      <p className="muted small">Set up routing and settings now. When you connect it later, the real account fills in and everything you configured is kept.</p>
      <form className="grid cols-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }}>
        <div className="field"><label htmlFor="pl-plat">Platform</label>
          <select id="pl-plat" className="select" value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
            {DEST_PLATFORMS.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</select></div>
        <div className="field"><label htmlFor="pl-name">Name</label><input id="pl-name" className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Streamer A TikTok" /></div>
        <div className="field"><label htmlFor="pl-creator">Creator</label>
          <select id="pl-creator" className="select" value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">None</option>{creators.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
      </form>
      {error && <ErrorNote error={error} />}
    </Modal>
  );
}

function SettingsModal({ dest, creators, onClose, onSaved }: { dest: Destination; creators: Creator[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(dest.display_name);
  const [creatorId, setCreatorId] = useState<number | null>(dest.creator?.id ?? null);
  const [s, setS] = useState<DestinationSettings>(structuredClone(dest.settings));
  const [hashtags, setHashtags] = useState(dest.settings.hashtags.join(" "));
  const [categories, setCategories] = useState(dest.settings.categories.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof DestinationSettings>(k: K, v: DestinationSettings[K]) => setS({ ...s, [k]: v });

  const save = async () => {
    setBusy(true); setError(null);
    const tags = hashtags.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`));
    const cats = categories.split(",").map((c) => c.trim()).filter(Boolean);
    try { await api.updateDestination(dest.id, { display_name: name, creator_id: creatorId, settings: { ...s, hashtags: tags, categories: cats } }); onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const resolutions: Record<string, string[]> = { "9:16": ["1080x1920", "720x1280"], "16:9": ["1920x1080"], "1:1": ["1080x1080"] };

  return (
    <Modal open wide onClose={onClose} title={<span className="row"><PlatformBadge platform={dest.platform} />{dest.display_name} settings</span>}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save} disabled={busy || !name.trim()}>{busy && <span className="spinner" />}Save</button></>}>
      <div className="grid cols-2">
        <div className="field"><label htmlFor="ds-name">Display name</label><input id="ds-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field"><label htmlFor="ds-creator">Creator</label>
          <select id="ds-creator" className="select" value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">None</option>{creators.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <span className="hint">Clips from other creators are never routed here unless you confirm it in the funnel.</span></div>
      </div>

      <h3>Publishing</h3>
      <div className="grid cols-2">
        <label className="check"><input type="checkbox" checked={s.approval_required} onChange={(e) => set("approval_required", e.target.checked)} />Require my approval before posting</label>
        <div className="field"><label htmlFor="ds-vis">Visibility</label>
          <select id="ds-vis" className="select" value={s.visibility} onChange={(e) => set("visibility", e.target.value as DestinationSettings["visibility"])}>
            {["public", "private", "unlisted", "friends"].map((v) => <option key={v} value={v}>{v[0].toUpperCase() + v.slice(1)}</option>)}</select>
          {(dest.platform === "tiktok" || dest.platform === "youtube") && <span className="hint">Until {PLATFORM_LABEL[dest.platform]} audits your app, posts are forced to private by the platform.</span>}</div>
      </div>
      <div className="field"><label htmlFor="ds-cap">Default caption</label><textarea id="ds-cap" className="textarea" rows={2} maxLength={2200} value={s.default_caption} onChange={(e) => set("default_caption", e.target.value)} placeholder="Added to every clip's AI caption" /></div>
      <div className="grid cols-2">
        <div className="field"><label htmlFor="ds-tags">Hashtags</label><input id="ds-tags" className="input" value={hashtags} onChange={(e) => setHashtags(e.target.value)} placeholder="#gaming #streamer" /></div>
        <div className="field"><label htmlFor="ds-cats">Content categories</label><input id="ds-cats" className="input" value={categories} onChange={(e) => setCategories(e.target.value)} placeholder="Gaming, Reactions" /></div>
      </div>

      <div>
        <div className="row" style={{ marginBottom: 8 }}><CalendarClock size={14} /><h3>Posting schedule</h3><span className="spacer" />
          <button className="btn sm" onClick={() => set("schedule", [...s.schedule, { weekday: 0, time: "18:00" }])}><Plus size={12} />Add slot</button></div>
        {s.schedule.length === 0 ? <p className="small faint">No fixed slots. Approved clips publish when you choose.</p> : (
          <div className="row wrap">{s.schedule.map((slot, i) => (
            <div key={i} className="row" style={{ background: "var(--bg-2)", padding: 4, borderRadius: 8 }}>
              <select className="select" style={{ width: 80 }} aria-label="Weekday" value={slot.weekday} onChange={(e) => set("schedule", s.schedule.map((x, j) => j === i ? { ...x, weekday: Number(e.target.value) } : x))}>
                {WEEKDAYS.map((w, j) => <option key={w} value={j}>{w}</option>)}</select>
              <input className="input" style={{ width: 100 }} type="time" aria-label="Time" value={slot.time} onChange={(e) => set("schedule", s.schedule.map((x, j) => j === i ? { ...x, time: e.target.value } : x))} />
              <button className="btn ghost icon" aria-label="Remove slot" onClick={() => set("schedule", s.schedule.filter((_, j) => j !== i))}><X size={12} /></button>
            </div>))}</div>
        )}
      </div>

      <h3>Format & style</h3>
      <div className="grid cols-4">
        <div className="field"><label htmlFor="ds-asp">Aspect</label>
          <select id="ds-asp" className="select" value={s.format.aspect} onChange={(e) => { const aspect = e.target.value as DestinationSettings["format"]["aspect"]; set("format", { ...s.format, aspect, resolution: resolutions[aspect][0] }); }}>
            <option value="9:16">9:16 vertical</option><option value="16:9">16:9 horizontal</option><option value="1:1">1:1 square</option></select></div>
        <div className="field"><label htmlFor="ds-res">Resolution</label>
          <select id="ds-res" className="select" value={s.format.resolution} onChange={(e) => set("format", { ...s.format, resolution: e.target.value })}>
            {resolutions[s.format.aspect].map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
        <div className="field"><label htmlFor="ds-fps">Frame rate</label>
          <select id="ds-fps" className="select" value={s.format.fps} onChange={(e) => set("format", { ...s.format, fps: Number(e.target.value) })}>
            {[24, 25, 30, 50, 60].map((f) => <option key={f} value={f}>{f} fps</option>)}</select></div>
        <div className="field"><label htmlFor="ds-codec">Codec</label>
          <select id="ds-codec" className="select" value={s.format.codec} onChange={(e) => set("format", { ...s.format, codec: e.target.value as "h264" | "h265" })}>
            <option value="h264">H.264</option><option value="h265">H.265 (HEVC)</option></select></div>
        <div className="field"><label htmlFor="ds-br">Bitrate: {s.format.bitrate_mbps} Mbps</label>
          <input id="ds-br" type="range" min={4} max={40} step={1} value={s.format.bitrate_mbps} onChange={(e) => set("format", { ...s.format, bitrate_mbps: Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor="ds-title">Title style</label>
          <select id="ds-title" className="select" value={s.title_style} onChange={(e) => set("title_style", e.target.value)}>
            {["curiosity", "reaction", "funny", "dramatic", "question"].map((t) => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}</select></div>
        <div className="field"><label htmlFor="ds-wm">Watermark text</label><input id="ds-wm" className="input" maxLength={60} value={s.branding.watermark_text} onChange={(e) => set("branding", { ...s.branding, watermark_text: e.target.value })} placeholder="@yourpage" /></div>
        <div className="field"><label htmlFor="ds-wmp">Watermark position</label>
          <select id="ds-wmp" className="select" value={s.branding.watermark_position} onChange={(e) => set("branding", { ...s.branding, watermark_position: e.target.value })}>
            {["top-left", "top-right", "bottom-left", "bottom-right"].map((p) => <option key={p} value={p}>{p}</option>)}</select></div>
      </div>
      {error && <ErrorNote error={error} />}
    </Modal>
  );
}
