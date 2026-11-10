import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Pencil, Plus, RefreshCw, Trash2, Users } from "lucide-react";
import { api, PLATFORM_LABEL, type Destination, type Source, type StreamerT } from "../lib/api";
import { Picker } from "../components/CreatorPicker";
import { ConfirmModal, Empty, ErrorNote, Loading, Modal, PlatformBadge, relTime, Toggle, useToast } from "../components/ui";

const pageItems = (pages: Destination[]) =>
  pages.map((d) => ({ id: d.id, name: d.display_name, sub: [PLATFORM_LABEL[d.platform], d.handle].filter(Boolean).join(" · ") }));
const linkPlatform = (url: string) => (/twitch\.tv/i.test(url) ? "twitch" : /kick\.com/i.test(url) ? "kick" : /youtu/i.test(url) ? "youtube" : "");

export default function Sources() {
  const qc = useQueryClient();
  const toast = useToast();
  const streamers = useQuery({ queryKey: ["streamers"], queryFn: api.streamers, refetchInterval: 15_000 });
  const pages = useQuery({ queryKey: ["destinations"], queryFn: () => api.destinations() });
  const legacy = useQuery({ queryKey: ["sources"], queryFn: () => api.sources() });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<StreamerT | null>(null);
  const [removing, setRemoving] = useState<StreamerT | null>(null);
  const refresh = () => ["streamers", "sources", "destinations", "creators", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const fail = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));
  const update = async (id: number, b: Parameters<typeof api.updateStreamer>[1]) => {
    try { await api.updateStreamer(id, b); refresh(); } catch (e) { fail(e); }
  };
  const checkNow = async (s: StreamerT) => {
    try { for (const ch of s.channels) await api.checkSource(ch.id); toast("ok", `Checking ${s.name}'s channel now.`); } catch (e) { fail(e); }
  };
  // Accounts added the old way (clipping accounts, or channels shared by several streamers).
  const mine = new Set((streamers.data ?? []).flatMap((s) => s.channels.map((c) => c.id)));
  const other = (legacy.data ?? []).filter((s) => !mine.has(s.id));

  return (
    <div className="page">
      <div className="page-head"><div><h1>Source Accounts</h1>
        <p>Each streamer you clip: their stream link, and the pages their clips get posted to. Vyral watches their channel and turns their most-watched new clips into videos.</p></div>
        <button className="btn primary" onClick={() => setAdding(true)}><Plus size={14} />Add streamer</button></div>

      {streamers.error && <ErrorNote error={streamers.error} />}
      {streamers.isLoading ? <Loading /> : (streamers.data ?? []).length === 0 ? (
        <div className="card"><Empty icon={<Users size={28} />} title="No streamers yet">
          <p className="small">Add a streamer with their Twitch or Kick link, then tick the pages to post their clips to.</p>
          <button className="btn primary" onClick={() => setAdding(true)}><Plus size={14} />Add streamer</button></Empty></div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "visible" }}>
          <table className="table"><thead><tr>
            <th>Streamer</th><th>Stream</th><th>Post to</th><th title="New clips seen · videos made">Clips · videos</th><th>Last check</th><th>Watch</th><th />
          </tr></thead><tbody>
            {streamers.data!.map((s) => {
              const last = s.channels.map((c) => c.last_check).filter(Boolean).sort().pop() ?? null;
              const watchable = s.links.some((l) => ["twitch", "kick"].includes(linkPlatform(l)));
              const error = s.channels.find((c) => c.error)?.error;
              return (
                <tr key={s.id}>
                  <td><div className="row" style={{ gap: 6 }}><span className="dot" style={{ background: s.color }} /><strong>{s.name}</strong></div></td>
                  <td><div className="row wrap" style={{ gap: 4 }}>{s.links.map((l) => (
                    <a key={l} href={l} target="_blank" rel="noreferrer" className="chip small" title={l} style={{ color: "inherit" }}>
                      {linkPlatform(l) && <PlatformBadge platform={linkPlatform(l)} />}{l.replace(/^https?:\/\/(www\.)?/, "").slice(0, 32)}</a>))}</div></td>
                  <td style={{ minWidth: 200 }}>
                    <Picker label={`Pages for ${s.name}`} items={pageItems(pages.data ?? [])} value={s.destination_ids} empty="No pages yet"
                      onChange={(ids) => update(s.id, { destination_ids: ids })} hint="Clips from this streamer go to every page ticked here." /></td>
                  <td className="small">{s.posts} · {s.clips}</td>
                  <td className="small muted" title={s.channels.map((c) => c.next_check ? `Next check ${relTime(c.next_check)}` : "").join(" ")}>
                    {s.channels.length ? relTime(last) : <span className="faint" title={watchable ? "Turn on Watch to pick up their new clips" : "YouTube links are searched for moments; there are no viewer clips to watch"}>Not watched</span>}
                    {error && <span title={error}> <AlertTriangle size={12} color="var(--warn)" /></span>}</td>
                  <td>{watchable && <Toggle label={`Watch ${s.name}`} checked={s.watching} onChange={(v) => update(s.id, { watching: v })} />}</td>
                  <td><div className="row" style={{ gap: 2, justifyContent: "flex-end" }}>
                    {s.channels.length > 0 && <button className="btn ghost icon" aria-label={`Check ${s.name} now`} title="Check now" onClick={() => checkNow(s)}><RefreshCw size={13} /></button>}
                    <button className="btn ghost icon" aria-label={`Edit ${s.name}`} onClick={() => setEditing(s)}><Pencil size={13} /></button>
                    <button className="btn ghost icon" aria-label={`Remove ${s.name}`} onClick={() => setRemoving(s)}><Trash2 size={13} /></button></div></td>
                </tr>
              );
            })}</tbody></table>
        </div>
      )}

      {other.length > 0 && <OtherAccounts list={other} onChange={refresh} fail={fail} />}

      {(adding || editing) && <StreamerModal streamer={editing} pages={pages.data ?? []}
        onClose={() => { setAdding(false); setEditing(null); }} onDone={() => { setAdding(false); setEditing(null); refresh(); }} />}
      <ConfirmModal open={!!removing} title={`Remove ${removing?.name}?`} danger confirmLabel="Remove"
        message="Vyral stops watching their channel and their pages stop getting their clips. Clips already made stay in Ready to Upload."
        onClose={() => setRemoving(null)}
        onConfirm={async () => { try { await api.removeStreamer(removing!.id); setRemoving(null); refresh(); } catch (e) { fail(e); } }} />
    </div>
  );
}

function StreamerModal({ streamer, pages, onClose, onDone }: { streamer: StreamerT | null; pages: Destination[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(streamer?.name ?? "");
  const [links, setLinks] = useState((streamer?.links ?? []).join("\n"));
  const [pageIds, setPageIds] = useState<number[]>(streamer?.destination_ids ?? []);
  const [permission, setPermission] = useState(!!streamer);
  const [busy, setBusy] = useState(false);
  const list = links.split(/\s+/).map((l) => l.trim()).filter(Boolean);
  const save = async () => {
    setBusy(true);
    try {
      if (streamer) await api.updateStreamer(streamer.id, { name: name.trim(), links: list, destination_ids: pageIds });
      else await api.addStreamer({ name: name.trim(), links: list, destination_ids: pageIds, permission });
      toast("ok", streamer ? "Saved" : `${name.trim()} added. Vyral is watching their channel.`);
      onDone();
    } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title={streamer ? `Edit ${streamer.name}` : "Add a streamer"}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || !name.trim() || list.length === 0 || !permission} onClick={save}>{busy && <span className="spinner" />}{streamer ? "Save" : "Add streamer"}</button></>}>
      <div className="stack">
        <div className="field"><label htmlFor="st-name">Name</label>
          <input id="st-name" className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Valkyrae" /></div>
        <div className="field"><label htmlFor="st-links">Stream link</label>
          <textarea id="st-links" className="input" rows={2} value={links} onChange={(e) => setLinks(e.target.value)} placeholder="https://www.twitch.tv/valkyrae" />
          <span className="hint">Their Twitch or Kick channel (Vyral watches its most-watched new clips), or YouTube (searched for moments). One per line if they stream in more than one place.</span></div>
        <div className="field"><span className="label-text">Post to</span>
          <Picker label="Pages for this streamer" items={pageItems(pages)} value={pageIds} onChange={setPageIds} empty="Pick pages"
            hint={pages.length ? "Clips from this streamer go to every page ticked here." : "Add your pages under Destinations first."} /></div>
        {!streamer && <label className="check"><input type="checkbox" checked={permission} onChange={(e) => setPermission(e.target.checked)} />
          I have permission to clip this streamer's content</label>}
      </div>
    </Modal>
  );
}

function OtherAccounts({ list, onChange, fail }: { list: Source[]; onChange: () => void; fail: (e: unknown) => void }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ marginBottom: 4 }}>Other watched accounts</h2>
      <p className="small faint" style={{ marginTop: 0 }}>Accounts added before streamers had their own setup. They keep working; pause or remove them here.</p>
      {list.map((s) => (
        <div key={s.id} className="list-row small">
          <PlatformBadge platform={s.platform} /><strong>@{s.username}</strong>
          <span className="faint">{s.creators.map((c) => c.name).join(", ") || "No streamer"}</span>
          <span className="spacer" /><span className="faint">{relTime(s.last_synced_at)}</span>
          <Toggle label={`Watch @${s.username}`} checked={s.monitoring === "active"}
            onChange={async (v) => { try { await api.updateSource(s.id, { monitoring: v ? "active" : "paused" }); onChange(); } catch (e) { fail(e); } }} />
          <button className="btn ghost icon" aria-label={`Remove @${s.username}`}
            onClick={async () => { try { await api.deleteSource(s.id); onChange(); } catch (e) { fail(e); } }}><Trash2 size={13} /></button>
        </div>
      ))}
    </div>
  );
}
