import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api, type AppSettings } from "../lib/api";
import { Toggle, useToast } from "./ui";

/** Settings > Dropbox: connect your own Dropbox, where videos go, auto-upload on or off, and Sync all. */
export function DropboxSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const { data } = useQuery({ queryKey: ["dropbox"], queryFn: api.dropbox, refetchInterval: (q) => (q.state.data?.connecting ? 2_000 : 10_000) });
  const [key, setKey] = useState("");
  const [folder, setFolder] = useState("/Vyral");
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cfg = settings.data?.dropbox;
  useEffect(() => { if (cfg) { setKey(cfg.app_key); setFolder(cfg.folder); } }, [cfg]);
  useEffect(() => { if (data?.connected) setLink(null); }, [data?.connected]);
  if (!data || !cfg) return null;

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try { await fn(); if (done) toast("ok", done); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); qc.invalidateQueries({ queryKey: ["dropbox"] }); }
  };
  const saveCfg = (b: Partial<AppSettings["dropbox"]>) => run(async () => qc.setQueryData(["settings"], await api.saveSettings({ dropbox: { ...cfg, ...b } })), "Saved");
  const connect = () => run(async () => {
    if (key.trim() !== cfg.app_key) qc.setQueryData(["settings"], await api.saveSettings({ dropbox: { ...cfg, app_key: key.trim() } }));
    setLink((await api.connectDropbox()).url);
  });
  const c = data.counts;

  return (
    <div className="card stack" style={{ maxWidth: 820 }}>
      <h2>Dropbox</h2>
      <p className="small muted">Each finished video goes to your Dropbox by itself, exactly as Vyral rendered it (nothing is re-encoded), and is checked
        against the file on this computer before it counts as uploaded. Muse can then take it from there.</p>
      {data.connected && !data.needs_reconnect ? (
        <>
          <div className="row wrap small">
            <span className="pill ok">Connected: {data.account}</span>
            <span>{c.uploaded} uploaded{c.queued + c.uploading ? `, ${c.queued + c.uploading} waiting` : ""}{c.failed ? `, ${c.failed} failed` : ""}</span>
            <span className="spacer" />
            <button className="btn ghost sm" disabled={busy} onClick={() => run(api.disconnectDropbox, "Dropbox disconnected")}>Disconnect</button>
          </div>
          <label className="row"><Toggle label="Upload to Dropbox automatically" checked={cfg.auto_upload} disabled={busy} onChange={(v) => saveCfg({ auto_upload: v })} />
            Upload each new video to Dropbox when it's ready</label>
          <div className="field"><label htmlFor="dbx-folder">Dropbox folder</label>
            <div className="row"><input id="dbx-folder" className="input" value={folder} maxLength={300} onChange={(e) => setFolder(e.target.value)} />
              <button className="btn" disabled={busy || folder === cfg.folder} onClick={() => saveCfg({ folder })}>Save</button></div>
            <span className="hint">Videos are named after their clip, like ref31-1795094064762.mp4. A file already there is never overwritten.</span></div>
          <div className="row wrap">
            <button className="btn" disabled={busy} onClick={() => run(async () => toast("ok", `${(await api.syncAllToDropbox()).queued} videos queued for Dropbox`))}>
              Sync all clips to Dropbox</button>
            <span className="small faint">Sends every video on this computer that isn't in Dropbox yet, including ones made before you connected.</span>
          </div>
        </>
      ) : (
        <>
          {data.needs_reconnect && <div className="banner warn small" role="status">{data.error ?? "Dropbox needs to be connected again."} Uploads wait until it is.</div>}
          <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            <li>Open <a href="https://www.dropbox.com/developers/apps" target="_blank" rel="noopener noreferrer">dropbox.com/developers/apps</a> and click <strong>Create app</strong>:
              <strong> Scoped access</strong>, <strong>Full Dropbox</strong>, any name.</li>
            <li>In <strong>Permissions</strong>, tick <strong>files.metadata.read</strong>, <strong>files.content.write</strong> and <strong>files.content.read</strong>, then <strong>Submit</strong>.</li>
            <li>In <strong>Settings</strong>, under OAuth 2 Redirect URIs, add <code>{data.redirect_uri}</code>.</li>
            <li>Copy the <strong>App key</strong> (the secret isn't needed) and paste it here.</li>
          </ol>
          <div className="row">
            <input className="input" aria-label="Dropbox app key" placeholder="App key" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
            <button className="btn primary" disabled={!/^[A-Za-z0-9]{5,40}$/.test(key.trim()) || busy} onClick={connect}>{busy && <span className="spinner" />}Connect</button>
          </div>
          {link && <p className="small">{data.connecting ? <span className="spinner" /> : null} Finish signing in on Dropbox's page in your browser.
            If it didn't open, <a href={link} target="_blank" rel="noopener noreferrer">open it here <ExternalLink size={11} /></a>.</p>}
          {(c.queued > 0 || c.failed > 0) && <p className="small faint">{c.queued + c.failed} videos are waiting to go up once Dropbox is connected.</p>}
        </>
      )}
    </div>
  );
}
