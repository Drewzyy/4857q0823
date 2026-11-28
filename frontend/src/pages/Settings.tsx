import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Bell, ExternalLink, Send, ShieldCheck, Trash2 } from "lucide-react";
import { DropboxSettings } from "../components/DropboxSettings";
import { MusePosting } from "../components/MusePosting";
import { ObsidianSettings } from "../components/ObsidianSettings";
import { api, type AppSettings, type Learned, type NotifyCategory, type NotifyState } from "../lib/api";
import { ErrorNote, Loading, relTime, Toggle, useToast } from "../components/ui";

type Tab = "general" | "muse" | "dropbox" | "obsidian" | "notifications" | "security" | "shortcuts";

export default function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "general";
  return (
    <div className="page">
      <div className="page-head"><div><h1>Settings</h1><p>Everything is stored on this computer.</p></div></div>
      <div className="tabs" role="tablist">
        {([["general", "Monitoring & storage"], ["muse", "Muse & posting"], ["dropbox", "Dropbox"], ["obsidian", "Obsidian"], ["notifications", "Notifications"], ["security", "Security & data"], ["shortcuts", "Shortcuts"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setParams({ tab: k })}>{l}</button>
        ))}
      </div>
      {tab === "general" && <General />}
      {tab === "muse" && <><MusePosting /><CompanionCard /><StyleCard /><TunedCard /><LearnedCard /></>}
      {tab === "dropbox" && <DropboxSettings />}
      {tab === "obsidian" && <ObsidianSettings />}
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
              <button className={s.processing.hardware_encoding ? "on" : ""} onClick={() => up("processing", { hardware_encoding: true })}>Graphics card + processor (fast)</button>
              <button className={s.processing.hardware_encoding ? "" : "on"} onClick={() => up("processing", { hardware_encoding: false })}>Processor only</button></div>
            <span className="hint">Clips render on the graphics card (NVIDIA, Intel or AMD on Windows, Apple on Mac) two at a time, and on the processor at the same time when the card is busy. If videos come out wrong (sound out of step, glitches), switch to Processor only and re-render.</span></div>
          <div className="field"><span className="label-text">Viral pre-edit</span>
            <div className="seg" role="group" aria-label="Viral pre-edit" style={{ alignSelf: "flex-start" }}>
              <button className={s.processing.viral_preedit ? "on" : ""} onClick={() => up("processing", { viral_preedit: true })}>On</button>
              <button className={s.processing.viral_preedit ? "" : "on"} onClick={() => up("processing", { viral_preedit: false })}>Off</button></div>
            <span className="hint">Every new clip gets a headline for the whole clip, is trimmed to its strongest stretch (45 seconds at most), and opens on sound, matching clips that passed 200k views. You can change any of it in the editor.</span></div>
          <div className="field"><span className="label-text">Hook first</span>
            <div className="seg" role="group" aria-label="Hook first" style={{ alignSelf: "flex-start" }}>
              <button className={s.processing.hook_first ? "on" : ""} onClick={() => up("processing", { hook_first: true })}>On</button>
              <button className={s.processing.hook_first ? "" : "on"} onClick={() => up("processing", { hook_first: false })}>Off</button></div>
            <span className="hint">Vyral finds the clip's best few seconds and plays them first, then the clip from its start. Clips that already open on their best part are left as they are.</span></div>
          <div className="field"><span className="label-text">Sound effects</span>
            <div className="seg" role="group" aria-label="Sound effects" style={{ alignSelf: "flex-start" }}>
              <button className={s.processing.sound_effects === "auto" ? "on" : ""} onClick={() => up("processing", { sound_effects: "auto" })}>One on the big moment</button>
              <button className={s.processing.sound_effects === "off" ? "on" : ""} onClick={() => up("processing", { sound_effects: "off" })}>None</button></div>
            <span className="hint">Vyral adds at most one, on the clip's biggest reaction, and only when something clearly stands out. More than that tends to feel forced. Add, move or remove sounds in the editor.</span></div>
          {s.processing.sound_effects === "auto" && <SoundChoice value={s.processing.auto_sound} onChange={(v) => up("processing", { auto_sound: v })} />}
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
          <div className="field" style={{ gridColumn: "1 / -1" }}><label htmlFor="fixes">Name fixes (one per line)</label>
            <textarea id="fixes" className="textarea" rows={3} placeholder="asian jeff => Jason Levine" value={s.captions.fixes.join("\n")}
              onChange={(e) => up("captions", { fixes: e.target.value.split("\n") })} />
            <span className="hint">What the speech model keeps hearing wrong, and what it should say. Fixed in captions and titles, new clips and waiting ones.</span></div>
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
        <div className="field"><label htmlFor="savef">Save to computer puts videos in</label>
          <div className="row"><input id="savef" className="input" style={{ flex: 1 }} value={s.storage.save_folder} placeholder="Downloads/Vyral" onChange={(e) => up("storage", { save_folder: e.target.value })} />
            <ChooseFolder onPick={(p) => up("storage", { save_folder: p })} /></div>
          <span className="hint">A full folder path. Leave empty to use Downloads/Vyral. Vyral creates the folder if it's missing.</span></div>
        <div className="field"><label htmlFor="mediaf">Keep new clips in</label>
          <div className="row"><input id="mediaf" className="input" style={{ flex: 1 }} value={s.storage.media_folder} placeholder="Vyral's own data folder" onChange={(e) => up("storage", { media_folder: e.target.value })} />
            <ChooseFolder onPick={(p) => up("storage", { media_folder: p })} /></div>
          <span className="hint">A full folder path with room for your clips. Clips already made stay where they are.</span></div>
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
        <div className="small faint">Emoji on videos: Twemoji by Twitter and contributors, CC-BY 4.0. Fonts: SIL Open Font License. Nudity check: open_nsfw by Yahoo, BSD 2-clause.</div>
      </div>
      <ClearAllClips />
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

function SoundChoice({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const sounds = useQuery({ queryKey: ["sounds"], queryFn: api.sounds });
  return (
    <div className="field"><label htmlFor="auto-sound">Sound for big moments</label>
      <select id="auto-sound" className="select" style={{ width: 260 }} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Vyral picks by the moment</option>
        <optgroup label="Vyral's">{(sounds.data ?? []).filter((x) => !x.mine).map((x) => <option key={x.name} value={x.name}>{x.label}</option>)}</optgroup>
        {(sounds.data ?? []).some((x) => x.mine) && <optgroup label="Yours">{(sounds.data ?? []).filter((x) => x.mine).map((x) => <option key={x.name} value={x.name}>{x.label}</option>)}</optgroup>}
      </select>
      <span className="hint">Add your own sounds from the Sound effects card in the editor; they show up here.</span></div>
  );
}

/** Opens this computer's own folder picker (through the Vyral service) and fills the field with the folder chosen. */
function ChooseFolder({ onPick }: { onPick: (path: string) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="btn" disabled={busy} onClick={async () => {
      setBusy(true);
      try { const r = await api.pickFolder(); if (r.path) onPick(r.path); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
      finally { setBusy(false); }
    }}>{busy ? <span className="spinner" /> : null}Choose folder</button>
  );
}

const LABELS: Record<string, string> = { min_seconds: "Shortest clip (s)", max_seconds: "Longest clip (s)", min_words: "Words said (besides laughing and filler)",
  setup_words: "Words of setup before the halfway point", min_score: "Lowest virality score" };

/** What the screener learned from review notes (yours and Muse's), with the note behind each change. */
function LearnedCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["learned"], queryFn: api.learned });
  if (!data) return null;
  return (
    <div className="card stack" style={{ maxWidth: 820, marginTop: 16 }}>
      <h2>What Vyral learned from your reviews</h2>
      <p className="small muted">When you or Muse reject a clip and say why ("too short", "boring", "no context", "just screaming"), these limits move a step,
        and the next clips are cut and screened to them. Clips that don't meet them are held back from review with the reason.</p>
      {data.auto_after != null && <p className="small">{(data.your_reviews ?? 0) >= data.auto_after
        ? "Vyral now approves clips you would have and sends them to the extension (posted by itself where Auto-post is on, otherwise a Discord ping to press Post). Reject any it gets wrong, with a note."
        : `Vyral starts approving clips by itself after ${data.auto_after} of your reviews: ${data.your_reviews ?? 0} so far.`}</p>}
      <div className="grid cols-2 small">{Object.entries(LABELS).map(([k, l]) => <div key={k}>{l}: <strong>{String(data[k as Exclude<keyof Learned, "history">])}</strong></div>)}</div>
      {data.history.length > 0 && <ul className="small faint" style={{ margin: 0, paddingLeft: 18 }}>{data.history.slice(-8).reverse().map((h, i) => (
        <li key={i}>{relTime(h.at)}: "{h.note}": {Object.entries(h.changed).map(([k, [a, b]]) => `${LABELS[k] ?? k} ${a} → ${b}`).join(", ")}</li>))}</ul>}
      <div><button className="btn ghost sm" onClick={async () => { qc.setQueryData(["learned"], await api.resetLearned()); toast("ok", "Back to the defaults"); }}>Reset to defaults</button></div>
    </div>
  );
}

/** Deletes every clip and its videos from this computer, after the phrase is typed. */
function ClearAllClips() {
  const qc = useQueryClient();
  const toast = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const PHRASE = "DELETE ALL CLIPS";
  return (
    <div className="card stack">
      <h2>Clear all clips</h2>
      <p className="small muted">Deletes every clip and its videos from this computer. Your sources, pages, campaigns and settings stay, and so do copies already
        in Dropbox. This can't be undone. Type <code>{PHRASE}</code> to confirm.</p>
      <div className="row">
        <input className="input" aria-label="Type the phrase to confirm" value={text} onChange={(e) => setText(e.target.value)} placeholder={PHRASE} />
        <button className="btn danger" disabled={text !== PHRASE || busy} onClick={async () => {
          setBusy(true);
          try { const r = await api.clearAllClips(text); toast("ok", `${r.deleted} clips deleted`); setText(""); qc.invalidateQueries(); }
          catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
        }}>{busy && <span className="spinner" />}Delete all clips</button>
      </div>
      <p className="small muted">Or clear only the clips that are too short for the current rules. Posted ones stay in your history.</p>
      <div><button className="btn ghost" disabled={busy} onClick={async () => {
        if (!window.confirm("Delete every clip that's too short, with its videos? Posted clips stay.")) return;
        setBusy(true);
        try {
          const r = await api.clearShortClips();
          toast("ok", `${r.deleted} clips under ${r.under} s deleted` + (r.kept_posted ? `, ${r.kept_posted} posted ones kept` : ""));
          qc.invalidateQueries();
        } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
      }}>Clear too-short clips</button></div>
    </div>
  );
}

const LAYOUT_NAMES: Record<string, string> = { stacked: "facecam on top, game under it", two: "two people, one above the other",
  face: "the streamer's face filling the frame", full: "the whole picture" };
const pct = (x: number) => `${Math.round(x * 100)}%`;

/** Your style: Vyral measures the clips you send and cuts new ones the same way. */
function StyleCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["style"], queryFn: api.style, refetchInterval: 20_000 });
  const [url, setUrl] = useState("");
  if (!data) return null;
  const p = data.profile, done = data.examples.filter((e) => e.features).length;
  const run = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast("ok", msg); qc.invalidateQueries({ queryKey: ["style"] }); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="card stack" style={{ maxWidth: 820, marginTop: 16 }}>
      <h2>Your style</h2>
      <p className="small muted">Every clip you post in the Discord inbox (or add here) is downloaded and measured: its length, whether it opens on the climax and
        for how long, how often it cuts, its layout, captions, the headline and how long it stays, sound effects (and which one), and zoom-ins. Clips with more views count for more. Once {data.needed} are in, new clips are cut
        the same way. It copies what can be measured, not taste.</p>
      <div className="row">
        <input className="input" aria-label="Link to one of your clips" placeholder="https://www.tiktok.com/@you/video/..." value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="btn" disabled={url.trim().length < 12} onClick={() => run(async () => { await api.learnStyle(url.trim()); setUrl(""); }, "Measuring it now")}>Learn from it</button>
      </div>
      {!p ? <p className="small faint">{done} of {data.needed} clips measured. Until then Vyral's own defaults apply.</p> : (
        <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          <li>Length: usually {Math.round(p.length)} s ({Math.round(p.length_low)} to {Math.round(p.length_high)} s)</li>
          <li>Hook (the climax first): {pct(p.hook_rate)} of your clips{p.hook_seconds ? `, about ${p.hook_seconds} s` : ""}</li>
          <li>Headline at the top: {pct(p.headline_rate)}{p.headline_seconds ? `, for about ${Math.round(p.headline_seconds)} s` : ""}</li>
          <li>Layout: mostly {LAYOUT_NAMES[p.layout] ?? p.layout}</li>
          <li>Captions: {pct(p.captions_rate)} · sound effects: {pct(p.sfx_rate)}{p.sound ? ` (mostly ${p.sound.replace("_", " ")})` : ""}
            · zoom-ins: {pct(p.zoom_rate ?? 0)} · cuts: about {p.cuts_per_min} a minute</li>
          {p.peak_share != null && p.tail != null && <li>Cut from the stream: the big moment about {Math.round(p.peak_share * 100)}% of the way in, then {Math.round(p.tail)} s after it</li>}
          {!!p.hashtags?.length && <li>Hashtags you use (added to captions): {p.hashtags.join(" ")}</li>}
          {!!p.songs?.length && <li>Songs on your TikToks (Muse adds the first when posting): {p.songs.join(", ")}</li>}
          <li className="faint">Clips with more views count for more; their views are read again every 12 hours.</li>
        </ul>)}
      <div className="row wrap">
        {p && <button className="btn primary sm" onClick={() => run(api.applyStyle, "Re-cutting waiting clips to your style")}>Apply to waiting clips</button>}
        {data.examples.length > 0 && <button className="btn ghost sm" onClick={() => { if (window.confirm("Forget every measured clip?")) void run(() => api.forgetStyle(), "Forgotten"); }}>Reset</button>}
      </div>
      {data.examples.length > 0 && <details><summary className="small">{data.examples.length} clips</summary>
        <ul className="small faint" style={{ margin: "6px 0 0", paddingLeft: 18 }}>{data.examples.slice(0, 50).map((e) => (
          <li key={e.url}><a href={e.url} target="_blank" rel="noopener noreferrer">{e.url.replace(/^https:\/\/(www\.)?/, "").slice(0, 60)}</a>{" "}
            {e.features ? `${Math.round(e.features.length)} s, ${e.features.hook ? `${e.features.hook} s hook` : "no hook"}, ${LAYOUT_NAMES[e.features.layout] ?? e.features.layout}${e.features.headline ? ", headline" : ""}${e.features.sfx ? `, sound effects${e.features.sound ? ` (${e.features.sound})` : ""}` : ""}${e.features.zooms ? ", zoom-ins" : ""}${e.views ? `, ${e.views.toLocaleString()} views` : ""}`
              : `couldn't be measured: ${e.error ?? "waiting"}`}</li>))}</ul></details>}
    </div>
  );
}

/** What Vyral is testing on its own clips, and what it found gets more views on your pages. */
function TunedCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["tuned"], queryFn: api.tuned, refetchInterval: 60_000 });
  if (!data) return null;
  const label = (v: string) => v === "true" ? "on" : v === "false" ? "off" : Number(v) > 0 ? `+${v} s` : Number(v) < 0 ? `${v} s` : "usual";
  return (
    <div className="card stack" style={{ maxWidth: 820, marginTop: 16 }}>
      <h2>What Vyral is testing</h2>
      <p className="small muted">About one clip in four tries a different choice (a hook or not, a headline or not, a sound effect, a zoom-in, 10 s shorter or longer).
        Every 6 hours, posts up 12 hours or more are compared by views an hour against what's normal for their page. Once an option has {data.min_posts}+ posts
        and clearly wins, it becomes the default; testing carries on.</p>
      <table className="table small"><thead><tr><th>Choice</th><th>Options (posts, views an hour vs the page's normal)</th><th>Now</th></tr></thead><tbody>
        {Object.entries(data.names).map(([k, name]) => (
          <tr key={k}><td>{name}</td>
            <td>{Object.entries(data.results?.[k] ?? {}).map(([o, r]) => `${label(o)}: ${r.posts}${r.lift != null ? ` (${r.lift >= 0 ? "+" : ""}${Math.round((10 ** r.lift - 1) * 100)}%)` : ""}`).join(" · ") || "no posts yet"}</td>
            <td>{k in data.best ? <strong>{label(String(data.best[k]))}</strong> : <span className="faint">testing</span>}</td></tr>))}
      </tbody></table>
      <div className="row small faint">{data.updated ? `Last compared ${relTime(data.updated)} on ${data.posts ?? 0} posts.` : "Nothing compared yet: it needs posts with views."}
        <span className="spacer" /><button className="btn ghost sm" onClick={async () => { qc.setQueryData(["tuned"], await api.resetTuned()); }}>Reset</button></div>
    </div>
  );
}

const LOGOS: Record<string, JSX.Element> = { // our own fixed SVGs, no remote images
  tiktok: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><rect width="24" height="24" rx="5" fill="#000" /><path d="M14 5v9.2a2.8 2.8 0 1 1-2.4-2.8V9a5.3 5.3 0 1 0 4.9 5.3V9.6a6 6 0 0 0 3 1V8.2A3.4 3.4 0 0 1 16.4 5z" fill="#fff" /></svg>,
  instagram: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><rect width="24" height="24" rx="6" fill="#d62976" /><rect x="5" y="5" width="14" height="14" rx="4" fill="none" stroke="#fff" strokeWidth="1.8" /><circle cx="12" cy="12" r="3.3" fill="none" stroke="#fff" strokeWidth="1.8" /><circle cx="16.3" cy="7.7" r="1" fill="#fff" /></svg>,
  youtube: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><rect y="4" width="24" height="16" rx="5" fill="#f00" /><path d="M10 8.5v7l6-3.5z" fill="#fff" /></svg>,
};
const LIGHT = { green: "var(--ok)", amber: "var(--warn)", grey: "var(--faint)" };

/** Posting without Muse: the Vyral Companion extension, in your own browser. */
function CompanionCard() {
  const toast = useToast();
  const { data, error } = useQuery({ queryKey: ["companion"], queryFn: api.companion, refetchInterval: 20000 });
  const folder = async () => { try { await api.companionFolder(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } };
  const on = !!data?.connected;
  return (
    <div className="card stack" style={{ maxWidth: 820, marginTop: 16 }}>
      <h2>Chrome extension: Vyral Companion</h2>
      {error ? <ErrorNote error={error} /> : (
        <div className="row" role="status" aria-label="Chrome extension status">
          <span style={{ width: 14, height: 14, borderRadius: 7, background: on ? "var(--ok)" : "var(--err)" }} />
          <strong style={{ fontSize: 20, color: on ? "var(--ok)" : "var(--err)" }}>{on ? "Connected" : "Not connected"}</strong>
          <span className="small muted">{on ? `Version ${data?.version}${data?.enabled ? ", posting on" : ", posting off (tick Post approved videos in the extension)"}`
            : data?.last_seen ? `Last heard from ${relTime(data.last_seen)}` : "Not heard from since Vyral started"}</span>
        </div>)}
      {data && data.accounts.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          {data.accounts.map((a) => (
            <div key={a.id} className="row small" data-testid="companion-account">
              <span title={a.text} style={{ width: 10, height: 10, borderRadius: 5, background: on ? LIGHT[a.light] : LIGHT.grey }} />
              <span title={a.site}>{LOGOS[a.platform]}</span>
              <strong>{a.display_name}</strong><span className="muted">{a.handle}</span>
              <span className="muted">{on ? a.text : "Extension not connected"}</span>
            </div>))}
        </div>)}
      {data && !data.accounts.length && <p className="small muted">No TikTok, Instagram or YouTube pages yet (Destinations).</p>}
      <p className="small muted">The extension posts the videos you approved, on the TikTok, Instagram and YouTube websites in your own browser, where you're
        logged in. It waits for each video's time (spacing and posting hours), opens the upload page, puts the video in and fills in the caption (and the title on
        YouTube). You press Post, unless that page's Auto-post is on, then it does. A captcha, a login or any check stops it and asks you; it never gets around
        them. The sites' rules don't allow automated posting, so Auto-post can get an account flagged: it's off unless you turn it on, page by page.</p>
      <p className="small">Once only:</p>
      <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
        <li>In Chrome, open <code>chrome://extensions</code> and turn on <strong>Developer mode</strong>.</li>
        <li>Press <strong>Load unpacked</strong> and pick this folder: {data?.folder ? <code>{data.folder}</code> : "loading"}</li>
        <li>In the extension's settings, paste the bridge token (Copy token, above) and tick <strong>Post approved videos</strong>.</li>
        <li>Stay logged in to TikTok, Instagram and YouTube Studio in that browser. Approve videos in Ready to Upload as usual.</li>
      </ol>
      <div className="row wrap">
        <button className="btn sm" disabled={!data?.folder} onClick={async () => { await navigator.clipboard.writeText(data?.folder || ""); toast("ok", "Folder path copied"); }}>Copy path</button>
        <button className="btn sm" onClick={folder}>Show folder</button>
      </div>
      <p className="small muted">Updates: Vyral keeps this folder up to date when it updates, and the extension reloads itself with the new version when
        nothing is posting. When Vyral starts it opens the upload page of each site you post to; the extension doesn't open a second tab for a site already open.</p>
      <p className="small muted">From your phone: with the bridge on your Tailscale address (above), each "Post ready" Discord ping has a link. Open it on your
        phone (Tailscale on), check the clip and caption, tap <strong>Post it</strong>, and the waiting upload page on your computer posts it. Each link works
        once, for 3 hours. Keep the computer on with Vyral and Chrome running.</p>
    </div>
  );
}
