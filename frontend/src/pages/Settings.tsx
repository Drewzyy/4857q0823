import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Bell, ExternalLink, Send, ShieldCheck, Trash2 } from "lucide-react";
import { api, type AppSettings } from "../lib/api";
import { ErrorNote, Loading, relTime, Toggle, useToast } from "../components/ui";

type Tab = "general" | "notifications" | "security" | "shortcuts";

export default function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "general";
  return (
    <div className="page">
      <div className="page-head"><div><h1>Settings</h1><p>Everything is stored on this computer.</p></div></div>
      <div className="tabs" role="tablist">
        {([["general", "Monitoring & storage"], ["notifications", "Notifications"], ["security", "Security & data"], ["shortcuts", "Shortcuts"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setParams({ tab: k })}>{l}</button>
        ))}
      </div>
      {tab === "general" && <General />}
      {tab === "notifications" && <Notifications />}
      {tab === "security" && <Security />}
      {tab === "shortcuts" && <Shortcuts />}
    </div>
  );
}

function General() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [s, setS] = useState<AppSettings | null>(null);
  useEffect(() => { if (data) setS(structuredClone(data)); }, [data]);
  const save = useMutation({ mutationFn: api.saveSettings, onSuccess: (r) => { qc.setQueryData(["settings"], r); qc.invalidateQueries({ queryKey: ["dashboard"] }); toast("ok", "Settings saved"); },
    onError: (e) => toast("err", e instanceof Error ? e.message : String(e)) });
  if (isLoading || !s) return error ? <ErrorNote error={error} /> : <Loading />;
  const dirty = JSON.stringify(s) !== JSON.stringify(data);
  const up = <K extends keyof AppSettings>(k: K, v: Partial<AppSettings[K]>) => setS({ ...s, [k]: { ...s[k], ...v } });

  return (
    <div className="stack" style={{ maxWidth: 820, gap: 16 }}>
      <div className="card stack">
        <h2>Monitoring</h2>
        <label className="row"><Toggle label="Watch source accounts" checked={s.monitoring.enabled} onChange={(v) => up("monitoring", { enabled: v })} />Watch source accounts and make clips automatically</label>
        <div className="grid cols-2">
          <div className="field"><label htmlFor="int">Check each account every {s.monitoring.interval_minutes} minutes</label>
            <input id="int" type="range" min={5} max={60} step={5} value={s.monitoring.interval_minutes} onChange={(e) => up("monitoring", { interval_minutes: Number(e.target.value) })} />
            <span className="hint">Faster checks catch posts sooner but make it more likely TikTok temporarily blocks checks. 10 minutes is a safe default.</span></div>
          <div className="field"><label htmlFor="streams">Search the latest {s.monitoring.streams_to_search} streams</label>
            <input id="streams" type="range" min={1} max={10} value={s.monitoring.streams_to_search} onChange={(e) => up("monitoring", { streams_to_search: Number(e.target.value) })} />
            <span className="hint">Each stream is analysed once and remembered, so searching more mostly costs time on the first clip.</span></div>
          <div className="field"><label htmlFor="maxlen">Longest clip: {s.monitoring.max_clip_seconds} seconds</label>
            <input id="maxlen" type="range" min={15} max={300} step={15} value={s.monitoring.max_clip_seconds} onChange={(e) => up("monitoring", { max_clip_seconds: Number(e.target.value) })} /></div>
          <div className="field"><label htmlFor="conc">Clips rendered at the same time: {s.processing.max_concurrent_jobs}</label>
            <input id="conc" type="range" min={1} max={4} value={s.processing.max_concurrent_jobs} onChange={(e) => up("processing", { max_concurrent_jobs: Number(e.target.value) })} />
            <span className="hint">1 keeps your computer responsive. Raise it on a fast machine.</span></div>
        </div>
      </div>

      <div className="card stack">
        <h2>Storage</h2>
        <div className="field" style={{ maxWidth: 380 }}><label htmlFor="ret">Delete clips after {s.storage.retention_days} days</label>
          <input id="ret" type="range" min={7} max={90} step={1} value={s.storage.retention_days} onChange={(e) => up("storage", { retention_days: Number(e.target.value) })} />
          <span className="hint">Applies to videos inside Vyral and its cached stream data. Files you saved to your computer are never touched. Changing this affects new clips.</span></div>
      </div>

      <div className="row" style={{ position: "sticky", bottom: 12 }}>
        <span className="spacer" />
        <button className="btn ghost" disabled={!dirty} onClick={() => data && setS(structuredClone(data))}>Discard</button>
        <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(s)}>{save.isPending && <span className="spinner" />}Save changes</button>
      </div>
    </div>
  );
}

function Notifications() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({ queryKey: ["notifications"], queryFn: api.notifications });
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const set = (d: Awaited<ReturnType<typeof api.notifications>>) => { qc.setQueryData(["notifications"], d); qc.invalidateQueries({ queryKey: ["dashboard"] }); };
  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } finally { setBusy(null); }
  };
  if (isLoading || !data) return <Loading />;

  return (
    <div className="stack" style={{ maxWidth: 820, gap: 16 }}>
      <div className="card stack">
        <div className="row"><Bell size={16} /><h2>Discord</h2><span className="spacer" />{data.configured ? <span className="pill ok">Connected {data.webhook_hint}</span> : <span className="pill nodot">Not set up</span>}</div>
        <ol className="steps small">
          <li><div>In Discord, open the channel's settings (gear icon) › <strong>Integrations</strong> › <strong>Webhooks</strong> › <strong>New Webhook</strong>.</div></li>
          <li><div>Click <strong>Copy Webhook URL</strong> and paste it here.</div></li>
        </ol>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void run("save", async () => { set(await api.saveNotifications({ webhook_url: url })); setUrl(""); await api.testNotification(); toast("ok", "Connected. Check Discord for a test message."); }); }}>
          <input className="input" aria-label="Discord webhook URL" type="password" autoComplete="off" placeholder={data.configured ? "Paste a new webhook to replace the current one" : "https://discord.com/api/webhooks/…"}
            value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className="btn primary" disabled={!url.trim() || busy !== null}>{busy === "save" && <span className="spinner" />}Save & test</button>
        </form>
        {data.configured && (
          <div className="row">
            <button className="btn" disabled={busy !== null} onClick={() => run("test", async () => { await api.testNotification(); toast("ok", "Test message sent"); })}>{busy === "test" ? <span className="spinner" /> : <Send size={14} />}Send test</button>
            <button className="btn ghost" onClick={() => run("rm", async () => { await api.removeWebhook(); qc.invalidateQueries({ queryKey: ["notifications"] }); toast("ok", "Webhook removed"); })}><Trash2 size={14} />Remove</button>
            <a className="small" href="https://support.discord.com/hc/en-us/articles/228383668" target="_blank" rel="noopener noreferrer">Discord help <ExternalLink size={11} /></a>
          </div>
        )}
      </div>
      <div className="card stack">
        <h2>Ping me when</h2>
        {([["on_new_post", "A source account posts a new video", "Says which account posted, with a link."],
          ["on_clip_ready", "A clip is ready to upload", "Says which pages and platforms it's for."],
          ["on_problem", "Vyral couldn't make a clip", "For example the moment wasn't in the recent streams, or setup is missing."]] as const).map(([k, l, h]) => (
          <label key={k} className="row" style={{ alignItems: "flex-start" }}>
            <Toggle label={l} checked={data[k]} onChange={(v) => run(k, async () => set(await api.saveNotifications({ [k]: v })))} />
            <span><span>{l}</span><br /><span className="small faint">{h}</span></span>
          </label>
        ))}
      </div>
    </div>
  );
}

function Security() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const audit = useQuery({ queryKey: ["audit"], queryFn: api.audit });
  return (
    <div className="stack" style={{ maxWidth: 900, gap: 16 }}>
      <div className="card stack">
        <div className="row"><ShieldCheck size={16} color="var(--ok)" /><h2>Protection in place</h2></div>
        <ul className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
          <li>Your Discord webhook is stored in {health.data?.secret_backend === "os-keychain" ? "your system's secure credential store (Keychain / Windows Credential Manager)" : "an encrypted file on this computer"}, never in logs.</li>
          <li>Vyral's background service only answers this app on this computer. Other apps and websites can't use it.</li>
          <li>Vyral never logs in to TikTok, YouTube or Twitch as you and never reads your browser's cookies or passwords.</li>
        </ul>
        <div className="small faint">Data folder: <span className="mono">{dash.data?.storage.data_dir}</span></div>
      </div>
      <div className="card">
        <h2 style={{ marginBottom: 8 }}>Activity log</h2>
        {audit.isLoading ? <Loading /> : (audit.data ?? []).length === 0 ? <p className="muted small">Nothing yet.</p> : (
          <table className="table"><thead><tr><th>When</th><th>Action</th><th>Details</th></tr></thead><tbody>
            {(audit.data ?? []).slice(0, 60).map((a) => (
              <tr key={a.id}><td className="small muted" style={{ whiteSpace: "nowrap" }}>{relTime(a.ts)}</td><td className="mono">{a.action}</td>
                <td className="small faint ellipsis" style={{ maxWidth: 420 }}>{Object.entries(a.details).map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}</td></tr>
            ))}</tbody></table>
        )}
      </div>
    </div>
  );
}

function Shortcuts() {
  const mod = navigator.userAgent.includes("Mac") ? "⌘" : "Ctrl+";
  const rows = [[`${mod}1 … ${mod}9`, "Jump to sidebar sections"], [`${mod},`, "Settings"], ["Esc", "Close a dialog"], ["Delete / Backspace", "Remove the selected route in the funnel"], ["Enter", "Submit the open form"]];
  return (
    <div className="card" style={{ maxWidth: 520 }}>
      {rows.map(([k, d]) => <div key={k} className="list-row"><span className="kbd">{k}</span><span className="muted">{d}</span></div>)}
    </div>
  );
}
