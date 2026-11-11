import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Bell, ExternalLink, Send, ShieldCheck, Trash2 } from "lucide-react";
import { api, type AppSettings, type NotifyCategory, type NotifyState } from "../lib/api";
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
      {tab === "notifications" && <><Notifications /><PhoneInbox /></>}
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
        <label className="row"><Toggle label="Clip copied links" checked={s.intake.clipboard} onChange={(v) => up("intake", { clipboard: v })} />
          Clip TikTok and YouTube Shorts links I copy (including from my iPhone through Universal Clipboard)</label>
        <div className="grid cols-2">
          <div className="field"><label htmlFor="int">Check each account every {s.monitoring.interval_minutes} minutes</label>
            <input id="int" type="range" min={5} max={60} step={5} value={s.monitoring.interval_minutes} onChange={(e) => up("monitoring", { interval_minutes: Number(e.target.value) })} />
            <span className="hint">Faster checks catch posts sooner but make it more likely TikTok temporarily blocks checks. 10 minutes is a safe default.</span></div>
          <div className="field"><label htmlFor="streams">Search the latest {s.monitoring.streams_to_search} streams</label>
            <input id="streams" type="range" min={1} max={10} value={s.monitoring.streams_to_search} onChange={(e) => up("monitoring", { streams_to_search: Number(e.target.value) })} />
            <span className="hint">Each stream is analysed once and remembered, so searching more mostly costs time on the first clip.</span></div>
          <div className="field"><label htmlFor="maxlen">Longest clip: {s.monitoring.max_clip_seconds} seconds</label>
            <input id="maxlen" type="range" min={15} max={300} step={15} value={s.monitoring.max_clip_seconds} onChange={(e) => up("monitoring", { max_clip_seconds: Number(e.target.value) })} /></div>
          <div className="field"><label htmlFor="tw-views">Twitch and Kick clips: make a video once {s.monitoring.twitch_min_views} people watched it</label>
            <input id="tw-views" type="range" min={0} max={1000} step={10} value={s.monitoring.twitch_min_views} onChange={(e) => up("monitoring", { twitch_min_views: Number(e.target.value) })} />
            <span className="hint">For Twitch channels added under Source Accounts: Vyral turns their most-watched new clips into videos.</span></div>
          <div className="field"><label htmlFor="tw-max">Up to {s.monitoring.twitch_clips_per_check} new Twitch or Kick clip{s.monitoring.twitch_clips_per_check === 1 ? "" : "s"} per channel each check</label>
            <input id="tw-max" type="range" min={1} max={10} value={s.monitoring.twitch_clips_per_check} onChange={(e) => up("monitoring", { twitch_clips_per_check: Number(e.target.value) })} /></div>
          <div className="field"><label htmlFor="conc">Clips rendered at the same time: {s.processing.max_concurrent_jobs}</label>
            <input id="conc" type="range" min={1} max={4} value={s.processing.max_concurrent_jobs} onChange={(e) => up("processing", { max_concurrent_jobs: Number(e.target.value) })} />
            <span className="hint">1 keeps your computer responsive. Raise it on a fast machine.</span></div>
          <div className="field"><span className="label-text">Dead air</span>
            <div className="seg" role="group" aria-label="Dead air" style={{ alignSelf: "flex-start" }}>
              <button className={s.processing.cut_dead_air ? "on" : ""} onClick={() => up("processing", { cut_dead_air: true })}>Cut it out</button>
              <button className={s.processing.cut_dead_air ? "" : "on"} onClick={() => up("processing", { cut_dead_air: false })}>Keep it</button></div>
            <span className="hint">Silent stretches of a second or more are cut out of new clips so they keep moving. Each clip can be switched back in the editor.</span></div>
          <div className="field"><span className="label-text">Render with</span>
            <div className="seg" role="group" aria-label="Render with" style={{ alignSelf: "flex-start" }}>
              <button className={s.processing.hardware_encoding ? "on" : ""} onClick={() => up("processing", { hardware_encoding: true })}>Graphics card (fast)</button>
              <button className={s.processing.hardware_encoding ? "" : "on"} onClick={() => up("processing", { hardware_encoding: false })}>Processor only</button></div>
            <span className="hint">The graphics card renders several times faster. If videos come out wrong (sound out of step, glitches), switch to Processor only and re-render.</span></div>
        </div>
      </div>

      <div className="card stack">
        <h2>Captions</h2>
        <p className="small faint">Speech is turned into captions on this computer. Nothing is uploaded. Each accuracy level downloads its speech model once, the first time it's used.</p>
        <div className="grid cols-2">
          <div className="field"><label htmlFor="acc">Accuracy</label>
            <select id="acc" className="select" value={s.captions.accuracy} onChange={(e) => up("captions", { accuracy: e.target.value as AppSettings["captions"]["accuracy"] })}>
              <option value="fast">Fast (about 480 MB download, misses more words)</option>
              <option value="accurate">Accurate, recommended (about 1.6 GB)</option>
              <option value="best">Best (about 3 GB, much slower)</option>
            </select>
            <span className="hint">Accurate handles fast talkers, slang and names much better than Fast. Best is for when Accurate still mishears.</span></div>
          <div className="field"><label htmlFor="lang">Language spoken on stream</label>
            <select id="lang" className="select" value={s.captions.language} onChange={(e) => up("captions", { language: e.target.value })}>
              {[["auto", "Detect automatically"], ["en", "English"], ["es", "Spanish"], ["pt", "Portuguese"], ["fr", "French"], ["de", "German"], ["it", "Italian"],
                ["ja", "Japanese"], ["ko", "Korean"], ["ru", "Russian"], ["ar", "Arabic"], ["hi", "Hindi"], ["tr", "Turkish"], ["pl", "Polish"], ["nl", "Dutch"]].map(([v, l]) =>
                <option key={v} value={v}>{l}</option>)}
            </select>
            <span className="hint">Setting it avoids short clips being misdetected as another language.</span></div>
        </div>
      </div>

      <Updates />

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

function Updates() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: u } = useQuery({
    queryKey: ["app-update"], queryFn: api.appUpdate,
    refetchInterval: (q) => (["checking", "downloading", "installing"].includes(q.state.data?.state ?? "") || q.state.data?.check_requested ? 1500 : 30_000),
  });
  if (!u) return null;
  const busy = u.check_requested || ["checking", "downloading", "installing"].includes(u.state);
  const line = !u.available ? "Updates are installed by the Vyral desktop app."
    : u.check_requested || u.state === "checking" ? "Checking for updates…"
    : u.state === "downloading" ? `Downloading Vyral ${u.version}${u.progress != null ? ` (${Math.round(u.progress * 100)}%)` : ""}…`
    : u.state === "ready" ? `Vyral ${u.version} is downloaded and ready to install.`
    : u.state === "installing" ? "Installing and restarting…"
    : u.state === "none" ? `You're on the latest version.${u.checked_at ? ` Checked ${relTime(u.checked_at)}.` : ""}`
    : u.state === "error" ? (u.error ?? "Couldn't check for updates.")
    : "Vyral checks for updates a minute after it starts and every hour.";
  return (
    <div className="card stack">
      <div className="row"><h2>Updates</h2><span className="spacer" /><span className="pill nodot">Version {u.current}</span></div>
      <p className={`small ${u.state === "error" ? "" : "muted"}`} style={u.state === "error" ? { color: "#ff8a8d" } : undefined}>{line}</p>
      <p className="small faint">New versions download in the background and install themselves when you're not using the Vyral window and no clip is rendering, then Vyral reopens on its own. Restart to update installs right away. Each update is checked against Vyral's signature before it's installed.</p>
      {u.available && (
        <div className="row">
          {u.state === "ready"
            ? <button className="btn primary" onClick={() => api.installUpdate().then(() => qc.invalidateQueries({ queryKey: ["app-update"] })).catch((e) => toast("err", String(e)))}>Restart to update</button>
            : <button className="btn" disabled={busy} onClick={() => api.checkForUpdates().then((r) => qc.setQueryData(["app-update"], { ...r, available: true })).catch((e) => toast("err", String(e)))}>
                {busy && <span className="spinner" />}Check for updates</button>}
        </div>
      )}
    </div>
  );
}

/** Post TikTok links in a Discord channel from your phone; Vyral reads the channel through a bot. */
function PhoneInbox() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["discord-inbox"], queryFn: api.discordInbox, refetchInterval: 15_000 });
  const channels = useQuery({ queryKey: ["discord-inbox-channels"], queryFn: api.discordInboxChannels, enabled: !!data?.configured, retry: false });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (b: { token?: string; channel_id?: string }) => {
    setBusy(true);
    try {
      qc.setQueryData(["discord-inbox"], await api.setDiscordInbox(b));
      if (b.token) { setToken(""); qc.invalidateQueries({ queryKey: ["discord-inbox-channels"] }); }
      toast("ok", b.token ? "Bot connected. Now pick the channel." : "Inbox channel set");
    } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  if (!data) return null;
  return (
    <div className="card stack" style={{ maxWidth: 820, marginTop: 16 }}>
      <h2>Phone inbox (Discord)</h2>
      <p className="small muted">Post a TikTok or YouTube Shorts link in a Discord channel from your phone, with the streamer's name if you like
        ("https://www.tiktok.com/@clips/video/123 jasontheween"). Vyral reads the channel while it's running, reacts ✅, and makes the clip.</p>
      {!data.configured ? (
        <>
          <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            <li>Open <a href="https://discord.com/developers/applications" target="_blank" rel="noopener noreferrer">discord.com/developers/applications</a>, click <strong>New Application</strong>, name it Vyral.</li>
            <li>In <strong>Bot</strong>: click <strong>Reset Token</strong> and copy it, then turn on <strong>Message Content Intent</strong> and save.</li>
            <li>In <strong>OAuth2 &gt; URL Generator</strong>: tick <strong>bot</strong>, then <strong>View Channels</strong>, <strong>Read Message History</strong> and <strong>Add Reactions</strong>. Open the link at the bottom and add the bot to your server.</li>
            <li>Paste the token here.</li>
          </ol>
          <div className="row">
            <input className="input" type="password" autoComplete="off" aria-label="Discord bot token" placeholder="Bot token" value={token} onChange={(e) => setToken(e.target.value)} />
            <button className="btn primary" disabled={token.trim().length < 20 || busy} onClick={() => save({ token: token.trim() })}>{busy && <span className="spinner" />}Connect</button>
          </div>
        </>
      ) : (
        <>
          <div className="row wrap small">
            <span className="pill ok">Bot: {data.bot ?? "connected"}</span>
            {data.channel_name ? <span>Reading <strong>#{data.channel_name}</strong> in {data.server}</span> : <span className="faint">Pick the channel you'll post links in:</span>}
            <span className="spacer" />
            <button className="btn ghost sm" onClick={async () => { await api.removeDiscordInbox(); qc.invalidateQueries({ queryKey: ["discord-inbox"] }); }}>Disconnect</button>
          </div>
          <select className="select" aria-label="Inbox channel" value={data.channel_id ?? ""} disabled={busy} onChange={(e) => e.target.value && save({ channel_id: e.target.value })}>
            <option value="">{channels.isLoading ? "Loading channels…" : "Choose a channel"}</option>
            {(channels.data ?? []).map((ch) => <option key={ch.id} value={ch.id}>#{ch.name} ({ch.server})</option>)}
          </select>
          {channels.error && <p className="small" style={{ color: "#ff8a8d" }}>{String(channels.error instanceof Error ? channels.error.message : channels.error)}</p>}
          {data.last_error && <p className="small" style={{ color: "#ff8a8d" }}>{data.last_error}</p>}
          {data.last_unrecognized && <p className="small faint">Last message without a video link Vyral recognizes (❓): <code>{data.last_unrecognized}</code></p>}
        </>
      )}
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
        <h2>What to send</h2>
        <p className="small faint">Each kind of update can go to its own Discord channel: paste that channel's webhook next to it. Kinds without one use the channel above.</p>
        {data.categories.map((cat) => <ChannelRow key={cat.key} cat={cat} busy={busy} run={run} set={set} />)}
        <div className="grid cols-2">
          <div className="field"><label htmlFor="minp">Only send</label>
            <select id="minp" className="select" value={data.min_priority} onChange={(e) => run("minp", async () => set(await api.saveNotifications({ min_priority: e.target.value as NotifyState["min_priority"] })))}>
              <option value="low">Everything</option><option value="normal">Skip minor updates (like each new post found)</option>
              <option value="high">Only important things</option><option value="urgent">Only urgent things</option></select></div>
          <div className="field"><span className="label-text">Quiet hours (this computer's time)</span>
            <QuietHours start={data.quiet_start} end={data.quiet_end} onSave={(start, end) => run("quiet", async () => set(await api.saveNotifications({ quiet_start: start, quiet_end: end })))} />
            <span className="hint">During quiet hours updates wait until the end. Urgent ones still come through.</span></div>
        </div>
      </div>
      <History />
    </div>
  );
}

function ChannelRow({ cat, busy, run, set }: { cat: NotifyCategory; busy: string | null; run: (k: string, fn: () => Promise<unknown>) => Promise<void>; set: (d: NotifyState) => void }) {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [open, setOpen] = useState(false);
  return (
    <div className="list-row" style={{ flexWrap: "wrap", alignItems: "center" }}>
      <Toggle label={cat.label} checked={cat.enabled} onChange={(v) => run(cat.key, async () => set(await api.saveNotifications({ categories: { [cat.key]: v } })))} />
      <span style={{ flex: 1 }}>{cat.label}</span>
      {cat.own_webhook_hint ? <span className="pill ok nodot">Own channel {cat.own_webhook_hint}</span> : <span className="small faint">Main channel</span>}
      <button className="btn ghost sm" onClick={() => setOpen(!open)}>{open ? "Close" : cat.own_webhook_hint ? "Change" : "Own channel"}</button>
      {open && (
        <form className="row" style={{ width: "100%", marginTop: 6 }} onSubmit={(e) => { e.preventDefault(); void run(`ch-${cat.key}`, async () => {
          set(await api.saveNotifications({ category_webhooks: { [cat.key]: url } })); setUrl(""); setOpen(false);
          if (url.trim()) { await api.testNotification(cat.key); toast("ok", `Test sent to the ${cat.label} channel`); } else toast("ok", "Back to the main channel");
        }); }}>
          <input className="input" type="password" autoComplete="off" aria-label={`Webhook for ${cat.label}`} placeholder="Paste this channel's webhook, or leave empty for the main channel"
            value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className="btn primary sm" disabled={busy !== null}>Save</button>
        </form>
      )}
    </div>
  );
}

function QuietHours({ start, end, onSave }: { start: string | null; end: string | null; onSave: (start: string, end: string) => void }) {
  const [s, setS] = useState(start ?? ""), [e, setE] = useState(end ?? "");
  return (
    <div className="row">
      <input className="input" type="time" aria-label="Quiet hours start" value={s} onChange={(ev) => setS(ev.target.value)} />
      <span className="small faint">to</span>
      <input className="input" type="time" aria-label="Quiet hours end" value={e} onChange={(ev) => setE(ev.target.value)} />
      <button className="btn sm" disabled={!!s !== !!e || (s === (start ?? "") && e === (end ?? ""))} onClick={() => onSave(s, e)}>Save</button>
      {start && <button className="btn ghost sm" onClick={() => { setS(""); setE(""); onSave("", ""); }}>Off</button>}
    </div>
  );
}

const DELIVERY: Record<string, string> = { sent: "Sent", queued: "Sending", held: "Waiting for quiet hours to end", failed: "Failed", off: "Not sent (turned off)", none: "Not sent (no channel)" };

function History() {
  const { data } = useQuery({ queryKey: ["events"], queryFn: () => api.events(), refetchInterval: 20_000 });
  return (
    <div className="card">
      <h2 style={{ marginBottom: 8 }}>Recent notifications</h2>
      {!data ? <Loading /> : data.length === 0 ? <p className="small faint">Nothing yet.</p> : (
        <table className="table"><thead><tr><th>When</th><th>What</th><th>Discord</th></tr></thead><tbody>
          {data.map((ev) => (
            <tr key={ev.id}><td className="small muted" style={{ whiteSpace: "nowrap" }}>{relTime(ev.ts)}</td>
              <td className="small"><div className="ellipsis" style={{ maxWidth: 440 }}>{ev.title}</div></td>
              <td className="small" title={ev.delivery_error ?? undefined} style={{ color: ev.delivery === "failed" ? "#ff8a8d" : undefined }}>{DELIVERY[ev.delivery] ?? ev.delivery}</td></tr>
          ))}</tbody></table>
      )}
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
        <div className="small faint">Emoji on videos: Twemoji by Twitter and contributors, CC-BY 4.0. Fonts: SIL Open Font License.</div>
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
  const rows = [[`${mod}1 … ${mod}9`, "Jump to sidebar sections"], [`${mod},`, "Settings"], ["Esc", "Close a dialog"], ["Enter", "Submit the open form"]];
  return (
    <div className="card" style={{ maxWidth: 520 }}>
      {rows.map(([k, d]) => <div key={k} className="list-row"><span className="kbd">{k}</span><span className="muted">{d}</span></div>)}
    </div>
  );
}
