import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, Send, ShieldAlert } from "lucide-react";
import { api, type AppSettings } from "../lib/api";
import { ErrorNote, Loading, Toggle, useToast } from "./ui";

const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

/** Settings > Muse & posting: the local bridge Muse connects to, Postiz, the kill switch and the safety blocklist. */
export function MusePosting() {
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const bridge = useQuery({ queryKey: ["bridge"], queryFn: api.bridge });
  const [s, setS] = useState<AppSettings | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (settings.data) setS(structuredClone(settings.data)); }, [settings.data]);
  if (!s || !bridge.data) return settings.error || bridge.error ? <ErrorNote error={settings.error ?? bridge.error} /> : <Loading />;
  const b = bridge.data;
  const fail = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));
  const dirty = JSON.stringify(s) !== JSON.stringify(settings.data);
  const save = async () => {
    setBusy(true);
    try {
      const restart = s.posting.mcp_port !== settings.data!.posting.mcp_port || s.posting.mcp_enabled !== settings.data!.posting.mcp_enabled;
      qc.setQueryData(["settings"], await api.saveSettings({ posting: s.posting, safety: s.safety }));
      if (restart) await api.restartBridge();
      await qc.invalidateQueries({ queryKey: ["bridge"] });
      toast("ok", "Saved");
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const P = (v: Partial<AppSettings["posting"]>) => setS({ ...s, posting: { ...s.posting, ...v } });
  const B = (v: Partial<AppSettings["safety"]>) => setS({ ...s, safety: { ...s.safety, ...v } });

  return (
    <div className="stack" style={{ maxWidth: 820, gap: 16 }}>
      <div className="card stack">
        <div className="row"><Bot size={16} /><h2>Muse (MCP bridge)</h2><span className="spacer" />
          {b.mcp.running ? <span className="pill ok">Running</span> : <span className="pill warn nodot">{b.mcp.enabled ? "Not running" : "Off"}</span>}</div>
        <p className="small faint" style={{ marginTop: 0 }}>Lets Muse, on this computer, see your clips, review and fix them, approve them and send them to Postiz.
          It only answers on this computer (127.0.0.1) and only with the token below.</p>
        {b.mcp.error && <div className="banner warn small">{b.mcp.error}</div>}
        <div className="row wrap" style={{ gap: 12 }}>
          <Toggle label="MCP bridge on" checked={s.posting.mcp_enabled} onChange={(v) => P({ mcp_enabled: v })} />
          <label className="small" htmlFor="mcp-port">Port</label>
          <input id="mcp-port" className="input" type="number" min={1024} max={65535} style={{ width: 110 }} value={s.posting.mcp_port}
            onChange={(e) => P({ mcp_port: Number(e.target.value) })} />
        </div>
        <div className="field"><span className="label-text">Address for Muse</span>
          <div className="row"><code className="mono small">{b.mcp.url}</code>
            <button className="btn ghost icon" aria-label="Copy address" onClick={() => void navigator.clipboard.writeText(b.mcp.url)}><Copy size={13} /></button></div></div>
        <div className="field"><span className="label-text">Token (send as Authorization: Bearer …)</span>
          <div className="row"><code className="mono small" style={{ filter: "blur(4px)" }} title="Copy it; it's hidden on screen">{b.mcp.token.slice(0, 24)}…</code>
            <button className="btn sm" onClick={() => { void navigator.clipboard.writeText(b.mcp.token); toast("ok", "Token copied"); }}><Copy size={13} />Copy token</button></div></div>
      </div>

      <div className="card stack">
        <div className="row"><Send size={16} /><h2>Postiz</h2><span className="spacer" />
          {b.postiz.connected ? <span className="pill ok">Connected</span> : <span className="pill nodot">Not connected</span>}</div>
        <p className="small faint" style={{ marginTop: 0 }}>Approved videos go to each page's Postiz channel (pick it on the page, under Destinations).
          The key is kept in this computer's keychain, never in the database or logs.</p>
        <div className="row wrap">
          <input className="input" type="password" autoComplete="off" style={{ flex: 1, minWidth: 240 }} aria-label="Postiz API key" value={key}
            placeholder={b.postiz.connected ? "Connected. Paste a new key to replace it" : "Postiz API key (Postiz > Settings > Public API)"} onChange={(e) => setKey(e.target.value)} />
          <button className="btn primary" disabled={key.trim().length < 8 || busy} onClick={async () => {
            setBusy(true);
            try { const r = await api.connectPostiz(key.trim()); setKey(""); await qc.invalidateQueries({ queryKey: ["bridge"] }); toast("ok", `Connected: ${r.channels.length} channel${r.channels.length === 1 ? "" : "s"}`); }
            catch (e) { fail(e); } finally { setBusy(false); }
          }}>Connect</button>
          {b.postiz.connected && <button className="btn ghost" onClick={async () => { try { await api.disconnectPostiz(); await qc.invalidateQueries({ queryKey: ["bridge"] }); } catch (e) { fail(e); } }}>Disconnect</button>}
        </div>
        <div className="field"><label htmlFor="postiz-url">Postiz address</label>
          <input id="postiz-url" className="input" value={s.posting.postiz_url} onChange={(e) => P({ postiz_url: e.target.value })} />
          <span className="hint">https://api.postiz.com for Postiz's own service, or your own Postiz's backend address.</span></div>
      </div>

      <div className="card stack">
        <div className="row"><ShieldAlert size={16} /><h2>Posting rules</h2></div>
        <label className="check"><input type="checkbox" checked={s.posting.auto_post_kill_switch} onChange={(e) => P({ auto_post_kill_switch: e.target.checked })} />
          Kill switch: nothing posts by itself, whatever each page's Auto-post says</label>
        <div className="field"><label htmlFor="min-viral">Minimum virality score to reach review: {s.posting.min_virality}</label>
          <input id="min-viral" type="range" min={0} max={100} value={s.posting.min_virality} onChange={(e) => P({ min_virality: Number(e.target.value) })} /></div>
        <p className="small faint">Auto-post is set per page (Destinations). It stays off until you turn it on, and unlocks only after 5 reviewed posts on that page went out.</p>
      </div>

      <div className="card stack">
        <h2>Safety blocklist</h2>
        <p className="small faint" style={{ marginTop: 0 }}>Added to the built-in checks on every new clip. A match quarantines the clip: it never reaches review or Postiz. One per line.</p>
        {([["banned_words", "Banned words"], ["banned_scenes", "Banned scenes (phrases said or in titles)"], ["banned_games", "Banned games"]] as const).map(([k, label]) => (
          <div key={k} className="field"><label htmlFor={`bl-${k}`}>{label}</label>
            <textarea id={`bl-${k}`} className="input" rows={3} defaultValue={s.safety[k].join("\n")} onBlur={(e) => B({ [k]: lines(e.target.value) })} /></div>
        ))}
      </div>
      <div className="row"><span className="spacer" /><button className="btn primary" disabled={!dirty || busy} onClick={save}>Save</button></div>
    </div>
  );
}
