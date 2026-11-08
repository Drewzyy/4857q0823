import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, FolderPlus, Import, Pause, Pencil, Play, Plus, RefreshCw, Search, Trash2, UserPlus, Users } from "lucide-react";
import { api, type Creator, type Folder, type ImportResult, type Platform, type Source } from "../lib/api";
import { Avatar, ConfirmModal, CREATOR_COLORS, Empty, ErrorNote, Loading, Modal, relTime, Toggle, useToast } from "../components/ui";

const SOURCE_PLATFORMS: Platform[] = ["tiktok", "youtube", "twitch", "instagram"];
type Filter = { kind: "all" } | { kind: "creator"; id: number } | { kind: "folder"; id: number } | { kind: "nocreator" };

export default function Sources() {
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>({ kind: "all" });
  const [q, setQ] = useState("");
  const [monitoring, setMonitoring] = useState<"" | "active" | "paused">("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [modal, setModal] = useState<null | "add" | "import" | "creator" | "folder">(null);
  const [editCreator, setEditCreator] = useState<Creator | null>(null);
  const [confirm, setConfirm] = useState<null | { title: string; message: string; run: () => Promise<unknown> }>(null);

  const params = {
    q, monitoring: monitoring || undefined,
    creator_id: filter.kind === "creator" ? filter.id : filter.kind === "nocreator" ? 0 : undefined,
    folder_id: filter.kind === "folder" ? filter.id : undefined,
  };
  const sources = useQuery({ queryKey: ["sources", params], queryFn: () => api.sources(params) });
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const folders = useQuery({ queryKey: ["folders"], queryFn: api.folders });
  const allCount = useQuery({ queryKey: ["sources", {}], queryFn: () => api.sources() });

  const refresh = () => ["sources", "creators", "folders", "dashboard", "funnel"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const onErr = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));
  const update = useMutation({ mutationFn: ({ id, b }: { id: number; b: Parameters<typeof api.updateSource>[1] }) => api.updateSource(id, b), onSuccess: refresh, onError: onErr });
  const bulk = useMutation({ mutationFn: api.bulkSources, onSuccess: (r) => { toast("ok", `Updated ${r.updated} account(s)`); setSelected(new Set()); refresh(); }, onError: onErr });

  const rows = sources.data ?? [];
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const ids = [...selected];

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Source Accounts</h1><p>Clipping accounts Vyral watches. When one posts, Vyral finds that moment in the creator's full stream and makes your own clip. Each account needs a creator, and each creator needs their stream channel.</p></div>
        <div className="row">
          <button className="btn" onClick={() => setModal("import")}><Import size={14} />Import</button>
          <button className="btn primary" onClick={() => setModal("add")}><Plus size={14} />Add account</button>
        </div>
      </div>

      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <aside className="side-panel stack" aria-label="Filters">
          <div>
            <button className={`filter-btn${filter.kind === "all" ? " on" : ""}`} onClick={() => setFilter({ kind: "all" })}><Users size={14} />All accounts<span className="count">{allCount.data?.length ?? ""}</span></button>
          </div>
          <div>
            <div className="row" style={{ padding: "0 8px 4px" }}><span className="label-text">Creators</span><span className="spacer" />
              <button className="btn ghost icon" aria-label="New creator" onClick={() => { setEditCreator(null); setModal("creator"); }}><UserPlus size={14} /></button></div>
            {(creators.data ?? []).map((c) => (
              <div key={c.id} className="row" style={{ gap: 0 }}>
                <button className={`filter-btn${filter.kind === "creator" && filter.id === c.id ? " on" : ""}`} onClick={() => setFilter({ kind: "creator", id: c.id })}>
                  <span className="chip" style={{ padding: 0, background: "none" }}><span className="dot" style={{ background: c.color }} /></span>
                  <span className="ellipsis">{c.name}</span><span className="count">{c.sources}</span>
                </button>
                <button className="btn ghost icon" aria-label={`Edit ${c.name}`} onClick={() => { setEditCreator(c); setModal("creator"); }}><Pencil size={12} /></button>
              </div>
            ))}
            <button className={`filter-btn${filter.kind === "nocreator" ? " on" : ""}`} onClick={() => setFilter({ kind: "nocreator" })}><span className="faint">No creator</span></button>
          </div>
          <div>
            <div className="row" style={{ padding: "0 8px 4px" }}><span className="label-text">Folders</span><span className="spacer" />
              <button className="btn ghost icon" aria-label="New folder" onClick={() => setModal("folder")}><FolderPlus size={14} /></button></div>
            {(folders.data ?? []).length === 0 && <p className="small faint" style={{ padding: "0 8px" }}>No folders</p>}
            {(folders.data ?? []).map((f) => (
              <div key={f.id} className="row" style={{ gap: 0 }}>
                <button className={`filter-btn${filter.kind === "folder" && filter.id === f.id ? " on" : ""}`} onClick={() => setFilter({ kind: "folder", id: f.id })}>
                  <span className="ellipsis">{f.name}</span><span className="count">{f.sources}</span></button>
                <button className="btn ghost icon" aria-label={`Delete folder ${f.name}`} onClick={() => setConfirm({ title: "Delete folder?", message: `"${f.name}" will be removed. Its accounts stay, just unfiled.`,
                  run: () => api.deleteFolder(f.id).then(() => { if (filter.kind === "folder" && filter.id === f.id) setFilter({ kind: "all" }); }) })}><Trash2 size={12} /></button>
              </div>
            ))}
          </div>
        </aside>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row" style={{ marginBottom: 12 }}>
            <div style={{ position: "relative", flex: 1, maxWidth: 360 }}>
              <Search size={14} style={{ position: "absolute", left: 10, top: 10, color: "var(--faint)" }} />
              <input className="input" style={{ paddingLeft: 30 }} placeholder="Search accounts" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search accounts" />
            </div>
            <div className="seg" role="group" aria-label="Monitoring filter">
              {([["", "All"], ["active", "Monitoring"], ["paused", "Paused"]] as const).map(([v, l]) => (
                <button key={v} className={monitoring === v ? "on" : ""} onClick={() => setMonitoring(v)}>{l}</button>
              ))}
            </div>
          </div>

          {sources.error && <ErrorNote error={sources.error} />}
          {sources.isLoading ? <Loading /> : rows.length === 0 ? (
            <div className="card"><Empty icon={<Users size={28} />} title={q || filter.kind !== "all" || monitoring ? "No accounts match" : "No source accounts yet"}>
              <p className="small">Add clipping accounts by @handle or profile link, or import a CSV.</p>
              <button className="btn primary" onClick={() => setModal("add")}><Plus size={14} />Add account</button>
            </Empty></div>
          ) : (
            <div className="card" style={{ padding: 0, overflowX: "auto" }}>
              <table className="table">
                <thead><tr>
                  <th style={{ width: 32 }}><input type="checkbox" aria-label="Select all" checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))} /></th>
                  <th>Account</th><th>Creator</th><th>Folder</th><th title="New posts seen / clips made">Posts · clips</th><th>Routes</th><th>Last check</th><th>Watch</th><th />
                </tr></thead>
                <tbody>
                  {rows.map((s) => <SourceRow key={s.id} s={s} creators={creators.data ?? []} folders={folders.data ?? []}
                    selected={selected.has(s.id)} onSelect={(v) => { const n = new Set(selected); if (v) n.add(s.id); else n.delete(s.id); setSelected(n); }}
                    onUpdate={(b) => update.mutate({ id: s.id, b })}
                    onCheck={() => api.checkSource(s.id).then(() => { toast("ok", `Checking @${s.username} now`); setTimeout(refresh, 4000); }).catch(onErr)}
                    onDelete={() => setConfirm({ title: "Remove account?", message: `@${s.username} and its funnel routes will be removed.`, run: () => api.deleteSource(s.id) })} />)}
                </tbody>
              </table>
            </div>
          )}

          {selected.size > 0 && (
            <div className="bulkbar row wrap">
              <strong>{selected.size} selected</strong><span className="spacer" />
              <button className="btn sm" onClick={() => bulk.mutate({ ids, action: "pause" })}><Pause size={12} />Pause</button>
              <button className="btn sm" onClick={() => bulk.mutate({ ids, action: "resume" })}><Play size={12} />Resume</button>
              <select className="select" style={{ width: 170 }} aria-label="Assign creator to selected" value="" onChange={(e) =>
                bulk.mutate({ ids, action: "assign", creator_id: e.target.value === "none" ? null : Number(e.target.value), folder_id: undefined })}>
                <option value="" disabled>Assign creator…</option><option value="none">No creator</option>
                {(creators.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <button className="btn sm danger" onClick={() => setConfirm({ title: `Remove ${selected.size} accounts?`, message: "Their funnel routes are removed too.", run: () => api.bulkSources({ ids, action: "delete" }).then(() => setSelected(new Set())) })}><Trash2 size={12} />Remove</button>
              <button className="btn sm ghost" onClick={() => setSelected(new Set())}>Clear</button>
            </div>
          )}
        </div>
      </div>

      {modal === "add" && <AddSourceModal creators={creators.data ?? []} folders={folders.data ?? []} defaults={filter} onClose={() => setModal(null)} onDone={refresh} />}
      {modal === "import" && <ImportModal creators={creators.data ?? []} onClose={() => setModal(null)} onDone={refresh} />}
      {modal === "creator" && <CreatorModal creator={editCreator} onClose={() => setModal(null)} onDone={refresh}
        onDelete={editCreator ? () => { setModal(null); setConfirm({ title: `Delete ${editCreator.name}?`, message: "Accounts assigned to this creator are kept but become unassigned.",
          run: () => api.deleteCreator(editCreator.id).then(() => setFilter({ kind: "all" })) }); } : undefined} />}
      {modal === "folder" && <FolderModal onClose={() => setModal(null)} onDone={refresh} />}
      <ConfirmModal open={!!confirm} title={confirm?.title ?? ""} message={confirm?.message} confirmLabel="Remove" danger onClose={() => setConfirm(null)}
        onConfirm={async () => { try { await confirm?.run(); refresh(); } catch (e) { onErr(e); } setConfirm(null); }} />
    </div>
  );
}

function SourceRow({ s, creators, folders, selected, onSelect, onUpdate, onDelete, onCheck }: {
  s: Source; creators: Creator[]; folders: Folder[]; selected: boolean; onSelect: (v: boolean) => void;
  onUpdate: (b: Parameters<typeof api.updateSource>[1]) => void; onDelete: () => void; onCheck: () => void;
}) {
  return (
    <tr>
      <td><input type="checkbox" aria-label={`Select ${s.username}`} checked={selected} onChange={(e) => onSelect(e.target.checked)} /></td>
      <td><div className="row" style={{ minWidth: 200 }}>
        <Avatar url={s.avatar_url} platform={s.platform} />
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}><strong className="ellipsis">@{s.username}</strong>{s.authorized && <span className="pill ok nodot" title="You authorized this account">Authorized</span>}</div>
          <div className="small faint ellipsis">{s.display_name || s.platform}</div>
          {!s.watching_supported && <div className="small faint">Vyral can't watch {s.platform} accounts yet</div>}
          {s.creator && (!s.creator.clip_permission || s.creator.vod_channels.length === 0) && (
            <div className="small" style={{ color: "var(--warn)" }}><AlertTriangle size={11} /> {s.creator.vod_channels.length === 0 ? `Add ${s.creator.name}'s stream channel` : `Confirm permission for ${s.creator.name}`}</div>)}
          {!s.creator && <div className="small" style={{ color: "var(--warn)" }}><AlertTriangle size={11} /> Pick a creator</div>}
          {s.last_error && <div className="small" style={{ color: "#ff8a8d" }} title={s.last_error}>{s.last_error.slice(0, 70)}</div>}
        </div>
      </div></td>
      <td><select className="select" style={{ minWidth: 130 }} aria-label={`Creator for @${s.username}`} value={s.creator?.id ?? ""} onChange={(e) => onUpdate({ creator_id: e.target.value ? Number(e.target.value) : null })}>
        <option value="">None</option>{creators.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></td>
      <td><select className="select" style={{ minWidth: 110 }} aria-label={`Folder for @${s.username}`} value={s.folder?.id ?? ""} onChange={(e) => onUpdate({ folder_id: e.target.value ? Number(e.target.value) : null })}>
        <option value="">None</option>{folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></td>
      <td title={s.baseline_done ? "" : "Not checked yet"}>{s.videos_discovered === null ? <span className="faint">—</span> : `${s.videos_discovered} · ${s.videos_analyzed}`}</td>
      <td>{s.route_count}</td>
      <td className="small muted" title={s.next_check_at ? `Next check ${relTime(s.next_check_at)}` : ""}>{relTime(s.last_synced_at)}</td>
      <td><div className="row"><Toggle label={`Monitor ${s.username}`} checked={s.monitoring === "active"} onChange={(v) => onUpdate({ monitoring: v ? "active" : "paused" })} /></div></td>
      <td><div className="row" style={{ justifyContent: "flex-end" }}>
        {s.watching_supported && <button className="btn ghost icon" aria-label={`Check @${s.username} now`} title="Check now" onClick={onCheck}><RefreshCw size={14} /></button>}
        {s.profile_url && <a className="btn ghost icon" href={s.profile_url} target="_blank" rel="noopener noreferrer" aria-label="Open profile"><ExternalLink size={14} /></a>}
        <button className="btn ghost icon" aria-label={`Remove ${s.username}`} onClick={onDelete}><Trash2 size={14} /></button>
      </div></td>
    </tr>
  );
}

function AddSourceModal({ creators, folders, defaults, onClose, onDone }: { creators: Creator[]; folders: Folder[]; defaults: Filter; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [input, setInput] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [creatorId, setCreatorId] = useState<number | null>(defaults.kind === "creator" ? defaults.id : null);
  const [folderId, setFolderId] = useState<number | null>(defaults.kind === "folder" ? defaults.id : null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Detect the platform from pasted links so the user doesn't have to.
  const detected = useMemo(() => {
    const m = input.match(/(tiktok|youtube|youtu\.be|twitch|instagram)\./i);
    return m ? (m[1].toLowerCase().startsWith("you") ? "youtube" : m[1].toLowerCase()) as Platform : null;
  }, [input]);
  const submit = async (keepOpen: boolean) => {
    setBusy(true); setError(null);
    try {
      const s = await api.addSource({ input, platform: detected ?? platform, creator_id: creatorId, folder_id: folderId });
      toast("ok", `Added @${s.username}`); onDone();
      if (keepOpen) setInput(""); else onClose();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title="Add source account" footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!input.trim() || busy} onClick={() => submit(true)}>Add another</button>
      <button className="btn primary" disabled={!input.trim() || busy} onClick={() => submit(false)}>{busy && <span className="spinner" />}Add</button>
    </>}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); if (input.trim()) void submit(false); }}>
        <div className="field">
          <label htmlFor="src-input">Username or profile link</label>
          <input id="src-input" className={`input${error ? " invalid" : ""}`} autoFocus placeholder="@streamerclips or https://www.tiktok.com/@streamerclips" value={input} onChange={(e) => { setInput(e.target.value); setError(null); }} />
          {error ? <span className="error">{error}</span> : detected ? <span className="hint">Detected a {detected} link.</span> : null}
        </div>
        <div className="grid cols-2">
          <div className="field"><label htmlFor="src-plat">Platform</label>
            <select id="src-plat" className="select" value={detected ?? platform} disabled={!!detected} onChange={(e) => setPlatform(e.target.value as Platform)}>
              {SOURCE_PLATFORMS.map((p) => <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}</select></div>
          <div className="field"><label htmlFor="src-creator">Creator</label>
            <select id="src-creator" className="select" value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">None</option>{creators.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
          <div className="field"><label htmlFor="src-folder">Folder</label>
            <select id="src-folder" className="select" value={folderId ?? ""} onChange={(e) => setFolderId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">None</option>{folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></div>
        </div>
        <p className="small faint">Vyral never reposts this account's videos. It uses their posts to find moments, then cuts your clip from the creator's original stream.</p>
      </form>
    </Modal>
  );
}

function ImportModal({ creators, onClose, onDone }: { creators: Creator[]; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const [creatorId, setCreatorId] = useState<number | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const run = async (p: Promise<ImportResult>) => {
    setBusy(true); setError(null);
    try { setResult(await p); onDone(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title="Import source accounts" wide footer={<>
      <button className="btn ghost" onClick={onClose}>{result ? "Done" : "Cancel"}</button>
      <button className="btn primary" disabled={!text.trim() || busy} onClick={() => run(api.importSourcesText({ text, platform: "tiktok", creator_id: creatorId }))}>{busy && <span className="spinner" />}Import list</button>
    </>}>
      <div className="field"><label htmlFor="imp-text">Paste handles or profile links, one per line</label>
        <textarea id="imp-text" className="textarea mono" rows={7} placeholder={"@streamera.clips\nhttps://www.tiktok.com/@streamera.highlights\nhttps://www.twitch.tv/streamera"} value={text} onChange={(e) => setText(e.target.value)} /></div>
      <div className="row wrap">
        <div className="field" style={{ width: 220 }}><label htmlFor="imp-creator">Assign to creator</label>
          <select id="imp-creator" className="select" value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">None</option>{creators.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
        <span className="spacer" />
        <button className="btn" onClick={() => fileRef.current?.click()}><Import size={14} />Upload CSV</button>
        <input ref={fileRef} type="file" accept=".csv,text/csv,text/plain" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void run(api.importSourcesFile(f)); e.target.value = ""; }} />
      </div>
      <p className="small faint">CSV columns: <span className="mono">username</span> or <span className="mono">url</span>, plus optional <span className="mono">creator</span>, <span className="mono">folder</span>, <span className="mono">platform</span>. New creators and folders are created automatically. Duplicates are skipped.</p>
      {error && <ErrorNote error={error} />}
      {result && (
        <div className="banner"><div>
          <strong>{result.added} added</strong>, {result.skipped_duplicates} already present{result.errors.length ? `, ${result.errors.length} skipped` : ""}.
          {result.errors.length > 0 && <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {result.errors.slice(0, 8).map((e) => <li key={e.line}>Line {e.line} ({e.input || "empty"}): {e.message}</li>)}</ul>}
        </div></div>
      )}
    </Modal>
  );
}

function CreatorModal({ creator, onClose, onDone, onDelete }: { creator: Creator | null; onClose: () => void; onDone: () => void; onDelete?: () => void }) {
  const [name, setName] = useState(creator?.name ?? "");
  const [color, setColor] = useState(creator?.color ?? CREATOR_COLORS[Math.floor(Math.random() * CREATOR_COLORS.length)]);
  const [channels, setChannels] = useState((creator?.vod_channels ?? []).join("\n"));
  const [permission, setPermission] = useState(creator?.clip_permission ?? false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    const vod_channels = channels.split(/\n+/).map((x) => x.trim()).filter(Boolean);
    try {
      if (creator) await api.updateCreator(creator.id, { name, color, vod_channels, clip_permission: permission });
      else await api.createCreatorFull({ name, color, vod_channels, clip_permission: permission });
      onDone(); onClose();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Modal open wide onClose={onClose} title={creator ? "Edit creator" : "New creator"} footer={<>
      {onDelete && <button className="btn danger" onClick={onDelete} style={{ marginRight: "auto" }}><Trash2 size={14} />Delete</button>}
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={!name.trim()} onClick={save}>Save</button>
    </>}>
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }} className="stack">
        <div className="field"><label htmlFor="cr-name">Streamer / creator name</label>
          <input id="cr-name" className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Streamer A" /></div>
        <div className="field"><label htmlFor="cr-ch">Where their full streams are (one per line)</label>
          <textarea id="cr-ch" className="textarea mono" rows={3} value={channels} onChange={(e) => setChannels(e.target.value)} placeholder={"https://www.twitch.tv/streamera\nhttps://www.youtube.com/@streamera\nhttps://kick.com/streamera"} />
          <span className="hint">Twitch, YouTube or Kick channel links (all of them if they multistream). Vyral searches the latest streams on each for every new post.</span></div>
        <label className="check"><input type="checkbox" checked={permission} onChange={(e) => setPermission(e.target.checked)} />I have permission to clip this creator's streams (for example, I'm in their clipping program)</label>
        {error && <span className="error small" style={{ color: "#ff8a8d" }}>{error}</span>}
        <div className="field"><span className="label-text">Color</span><div className="row">
          {CREATOR_COLORS.map((c) => <button type="button" key={c} aria-label={`Color ${c}`} onClick={() => setColor(c)}
            style={{ width: 24, height: 24, borderRadius: 7, background: c, border: color === c ? "2px solid white" : "2px solid transparent", cursor: "pointer" }} />)}
        </div></div>
      </form>
    </Modal>
  );
}

function FolderModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = async () => { try { await api.createFolder(name); onDone(); onClose(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } };
  return (
    <Modal open onClose={onClose} title="New folder" footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!name.trim()} onClick={save}>Create</button></>}>
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) void save(); }}>
        <div className="field"><label htmlFor="fd-name">Folder name</label><input id="fd-name" className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Gaming" />{error && <span className="error">{error}</span>}</div>
      </form>
    </Modal>
  );
}
