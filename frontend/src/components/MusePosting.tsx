import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, ShieldAlert } from "lucide-react";
import { api, type AppSettings } from "../lib/api";
import { ErrorNote, Loading, Toggle, useToast } from "./ui";

const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

/** Settings > Muse & posting: the local bridge Muse connects to, the kill switch and the safety blocklist. */
export function MusePosting() {
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const bridge = useQuery({ queryKey: ["bridge"], queryFn: api.bridge });
  const [s, setS] = useState<AppSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [portText, setPortText] = useState("");
  const [host, setHost] = useState("");
  useEffect(() => {
    if (!settings.data) return;
    setS(structuredClone(settings.data));
    setPortText(String(settings.data.posting.mcp_port));
    if (settings.data.posting.mcp_host !== "127.0.0.1") setHost(settings.data.posting.mcp_host);
  }, [settings.data]);
  if (!s || !bridge.data) return settings.error || bridge.error ? <ErrorNote error={settings.error ?? bridge.error} /> : <Loading />;
  const b = bridge.data;
  const fail = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));
  const dirty = JSON.stringify(s) !== JSON.stringify(settings.data);
  const save = async () => {
    setBusy(true);
    try {
      const restart = s.posting.mcp_port !== settings.data!.posting.mcp_port || s.posting.mcp_enabled !== settings.data!.posting.mcp_enabled
        || s.posting.mcp_host !== settings.data!.posting.mcp_host;
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
        <p className="small faint" style={{ marginTop: 0 }}>Lets Muse see your clips, review and fix them, approve them and post them itself.
          It answers only on the address picked below (this computer, or your Tailscale address for Muse on your other devices) and only with the token.</p>
        {b.mcp.error && <div className="banner warn small">{b.mcp.error}</div>}
        <div className="row wrap" style={{ gap: 12 }}>
          <Toggle label="MCP bridge on" checked={s.posting.mcp_enabled} onChange={(v) => P({ mcp_enabled: v })} />
          <label className="small" htmlFor="mcp-host">Listen on</label>
          <select id="mcp-host" className="select" style={{ width: 190 }} value={s.posting.mcp_host === "127.0.0.1" ? "local" : "tailscale"}
            onChange={(e) => P({ mcp_host: e.target.value === "local" ? "127.0.0.1" : (host.startsWith("100.") ? host : "") })}>
            <option value="local">This computer only</option><option value="tailscale">My Tailscale address</option></select>
          {s.posting.mcp_host !== "127.0.0.1" && <input className="input" aria-label="Tailscale address" style={{ width: 150 }} placeholder="100.115.250.79"
            value={s.posting.mcp_host} onChange={(e) => { setHost(e.target.value.trim()); P({ mcp_host: e.target.value.trim() }); }} />}
          <label className="small" htmlFor="mcp-port">Port</label>
          <input id="mcp-port" className="input" inputMode="numeric" style={{ width: 90 }} value={portText}
            onChange={(e) => { setPortText(e.target.value); if (/^\d{4,5}$/.test(e.target.value)) P({ mcp_port: Number(e.target.value) }); }} />
        </div>
        {portText.includes(".") && <div className="banner warn small">That looks like an address. Put it under Listen on (My Tailscale address); the port is a single number like 47821.</div>}
        {!portText.includes(".") && !/^\d{4,5}$/.test(portText) && <div className="banner warn small">The port is a whole number from 1024 to 65535, like 47821.</div>}
        <div className="field"><span className="label-text">Address for Muse</span>
          <div className="row"><code className="mono small">{b.mcp.url}</code>
            <button className="btn ghost icon" aria-label="Copy address" onClick={() => void navigator.clipboard.writeText(b.mcp.url)}><Copy size={13} /></button></div></div>
        <div className="field"><span className="label-text">Token (send as Authorization: Bearer …)</span>
          <div className="row"><code className="mono small" style={{ filter: "blur(4px)" }} title="Copy it; it's hidden on screen">{b.mcp.token.slice(0, 24)}…</code>
            <button className="btn sm" onClick={() => { void navigator.clipboard.writeText(b.mcp.token); toast("ok", "Token copied"); }}><Copy size={13} />Copy token</button></div></div>
      </div>

      <div className="card stack">
        <div className="row"><ShieldAlert size={16} /><h2>Posting rules</h2></div>
        <label className="check"><input type="checkbox" checked={s.posting.auto_post_kill_switch} onChange={(e) => P({ auto_post_kill_switch: e.target.checked })} />
          Kill switch: nothing posts by itself, whatever each page's Auto-post says</label>
        <div className="field"><label htmlFor="min-viral">Minimum virality score to reach review: {s.posting.min_virality}</label>
          <input id="min-viral" type="range" min={0} max={100} value={s.posting.min_virality} onChange={(e) => P({ min_virality: Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor="per-day">Best clips per streamer per day: {s.posting.per_streamer_day || "no limit"}</label>
          <input id="per-day" type="range" min={0} max={20} value={s.posting.per_streamer_day} onChange={(e) => P({ per_streamer_day: Number(e.target.value) })} />
          <span className="hint">Each day only a streamer's highest-scoring clips go to review and Muse; the rest stay in Ready to Upload with why.</span></div>
        <div className="field"><label>Posting hours (this computer's clock): {s.posting.post_from}:00 to {s.posting.post_until}:00</label>
          <div className="row">
            <input aria-label="Post from (hour)" className="input" type="number" min={0} max={23} style={{ width: 80 }} value={s.posting.post_from}
              onChange={(e) => P({ post_from: Number(e.target.value) })} />
            <span className="small">to</span>
            <input aria-label="Post until (hour)" className="input" type="number" min={1} max={24} style={{ width: 80 }} value={s.posting.post_until}
              onChange={(e) => P({ post_until: Number(e.target.value) })} /></div>
          <span className="hint">Muse is told not to post outside these hours: noon to 10 pm by default, never in the middle of the night.</span></div>
        <div className="field"><label htmlFor="spacing">Space posts on a page at least {s.posting.spacing_minutes} minutes apart</label>
          <input id="spacing" type="range" min={0} max={360} step={15} value={s.posting.spacing_minutes} onChange={(e) => P({ spacing_minutes: Number(e.target.value) })} />
          <span className="hint">Muse gets a "post after" time with each approved clip, so a batch doesn't go up at once.</span></div>
        <p className="small faint">Auto-post is set per page (Destinations). It stays off until you turn it on, and unlocks only after 5 reviewed posts on that page were posted. It lets Muse post approved clips that passed the safety check without asking you first.</p>
      </div>

      <div className="card stack">
        <h2>Safety blocklist</h2>
        <p className="small faint" style={{ marginTop: 0 }}>Added to the built-in checks on every new clip. A match quarantines the clip: it never reaches review or gets posted. One per line.</p>
        {([["banned_words", "Banned words"], ["banned_scenes", "Banned scenes (phrases said or in titles)"], ["banned_games", "Banned games"]] as const).map(([k, label]) => (
          <div key={k} className="field"><label htmlFor={`bl-${k}`}>{label}</label>
            <textarea id={`bl-${k}`} className="input" rows={3} defaultValue={s.safety[k].join("\n")} onBlur={(e) => B({ [k]: lines(e.target.value) })} /></div>
        ))}
      </div>
      <div className="row"><span className="spacer" /><button className="btn primary" disabled={!dirty || busy} onClick={save}>Save</button></div>
    </div>
  );
}
