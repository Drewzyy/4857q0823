import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogIn, RefreshCw, ShieldCheck, Unplug } from "lucide-react";
import { api, PLATFORM_LABEL, type AppSettings, type Connection } from "../lib/api";
import { useConnect } from "../components/ConnectFlow";
import { Avatar, ConfirmModal, ErrorNote, Loading, PlatformBadge, relTime, StatusPill, Toggle, useToast } from "../components/ui";

type Tab = "connections" | "general" | "security" | "shortcuts";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("connections");
  return (
    <div className="page">
      <div className="page-head"><div><h1>Settings</h1><p>Everything is stored on this computer.</p></div></div>
      <div className="tabs" role="tablist">
        {([["connections", "Connections"], ["general", "AI, costs & processing"], ["security", "Security & data"], ["shortcuts", "Shortcuts"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === "connections" && <Connections />}
      {tab === "general" && <General />}
      {tab === "security" && <Security />}
      {tab === "shortcuts" && <Shortcuts />}
    </div>
  );
}

function Connections() {
  const qc = useQueryClient();
  const toast = useToast();
  const { platforms, openSetup, connect } = useConnect();
  const conns = useQuery({ queryKey: ["connections"], queryFn: api.connections });
  const [removeApp, setRemoveApp] = useState<string | null>(null);
  const [disconnect, setDisconnect] = useState<Connection | null>(null);
  const refresh = () => ["connections", "platforms", "destinations", "dashboard", "sources"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const refreshOne = useMutation({ mutationFn: api.refreshConnection, onSuccess: (r) => { toast(r.status === "connected" ? "ok" : "err", r.status === "connected" ? "Login refreshed" : `Status: ${r.status}`); refresh(); },
    onError: (e) => toast("err", String(e)) });

  return (
    <div className="stack" style={{ gap: 20 }}>
      <section>
        <h2 style={{ marginBottom: 4 }}>Platforms</h2>
        <p className="muted small" style={{ marginBottom: 12 }}>Each platform needs to recognize AI Clipper once. After that, connecting an account is just a login.</p>
        <div className="grid cols-3">
          {platforms.map((p) => (
            <div className="card" key={p.key}>
              <div className="row"><PlatformBadge platform={p.key} large /><div style={{ flex: 1 }}><h3>{p.label}</h3>
                <div className="small faint">{p.configured ? (p.source === "bundled" ? "Built into this app" : `Verified ${relTime(p.validated_at)} · ${p.client_id_hint ?? ""}`) : "Not set up"}</div></div>
                {p.configured ? <span className="pill ok">Ready</span> : <span className="pill nodot">Setup needed</span>}</div>
              <div className="row" style={{ marginTop: 14 }}>
                {p.configured ? <button className="btn primary sm" onClick={() => connect(p.key)}><LogIn size={12} />Connect account</button>
                  : <button className="btn primary sm" onClick={() => openSetup(p.key)}>Set up</button>}
                {p.configured && p.source === "user" && <><button className="btn sm" onClick={() => openSetup(p.key)}>Replace keys</button>
                  <button className="btn ghost sm" onClick={() => setRemoveApp(p.key)}>Remove</button></>}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 style={{ marginBottom: 12 }}>Connected logins</h2>
        {conns.isLoading ? <Loading /> : (conns.data ?? []).length === 0 ? <p className="muted small">None yet.</p> : (
          <div className="card" style={{ padding: "4px 18px" }}>
            {(conns.data ?? []).map((c) => (
              <div className="list-row" key={c.id}>
                <Avatar url={c.avatar_url} platform={c.platform} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="ellipsis"><strong>{c.display_name}</strong> <span className="faint small">{PLATFORM_LABEL[c.platform]}</span></div>
                  <div className="small faint">Connected {relTime(c.created_at)} · access {c.access_expires_at ? `renews ${relTime(c.access_expires_at)}` : "no expiry"}{c.last_error ? ` · ${c.last_error}` : ""}</div>
                </div>
                <StatusPill status={c.status} />
                {(c.status === "expired" || c.status === "expiring") ? <button className="btn sm primary" onClick={() => connect(c.platform)}><LogIn size={12} />Sign in again</button>
                  : <button className="btn sm" onClick={() => refreshOne.mutate(c.id)} disabled={refreshOne.isPending}><RefreshCw size={12} />Check</button>}
                <button className="btn sm ghost" onClick={() => setDisconnect(c)}><Unplug size={12} />Disconnect</button>
              </div>
            ))}
          </div>
        )}
      </section>

      <ConfirmModal open={!!removeApp} title="Remove platform setup?" danger confirmLabel="Remove"
        message="Existing logins keep working until they need refreshing. New logins need the setup again."
        onClose={() => setRemoveApp(null)} onConfirm={async () => { try { await api.removeApp(removeApp as never); refresh(); } catch (e) { toast("err", String(e)); } setRemoveApp(null); }} />
      <ConfirmModal open={!!disconnect} title={`Disconnect ${disconnect?.display_name}?`} danger confirmLabel="Disconnect"
        message="AI Clipper revokes its access with the platform and deletes the stored login. The destination accounts and their settings stay, marked Not connected."
        onClose={() => setDisconnect(null)} onConfirm={async () => { try { if (disconnect) await api.disconnect(disconnect.id); refresh(); toast("ok", "Disconnected"); } catch (e) { toast("err", String(e)); } setDisconnect(null); }} />
    </div>
  );
}

function General() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [s, setS] = useState<AppSettings | null>(null);
  useEffect(() => { if (data) setS(structuredClone(data)); }, [data]);
  const save = useMutation({ mutationFn: api.saveSettings, onSuccess: (r) => { qc.setQueryData(["settings"], r); toast("ok", "Settings saved"); },
    onError: (e) => toast("err", e instanceof Error ? e.message : String(e)) });
  if (isLoading || !s) return error ? <ErrorNote error={error} /> : <Loading />;
  const dirty = JSON.stringify(s) !== JSON.stringify(data);
  const up = <K extends keyof AppSettings>(k: K, v: Partial<AppSettings[K]>) => setS({ ...s, [k]: { ...s[k], ...v } });

  return (
    <div className="stack" style={{ maxWidth: 820, gap: 16 }}>
      <div className="card stack">
        <h2>AI models & spending</h2>
        <p className="small faint">AI features arrive in Milestone 4. These limits are stored now and every AI call will be checked against them.</p>
        <div className="grid cols-2">
          <div className="field"><label htmlFor="budget">Monthly budget (USD)</label>
            <input id="budget" className="input" type="number" min={0} step={1} value={s.ai.monthly_budget_usd} onChange={(e) => up("ai", { monthly_budget_usd: Number(e.target.value) })} /></div>
          <div className="field"><label htmlFor="warn">Warn at {s.ai.warn_at_percent}% of budget</label>
            <input id="warn" type="range" min={10} max={100} step={5} value={s.ai.warn_at_percent} onChange={(e) => up("ai", { warn_at_percent: Number(e.target.value) })} /></div>
          <div className="field"><label htmlFor="tier">Default text model tier</label>
            <select id="tier" className="select" value={s.ai.text_model_tier} onChange={(e) => up("ai", { text_model_tier: e.target.value })}>
              <option value="economy">Economy (cheapest that works)</option><option value="balanced">Balanced</option><option value="best">Best quality</option></select></div>
          <div className="field"><label htmlFor="stt">Transcription</label>
            <select id="stt" className="select" value={s.ai.transcription} onChange={(e) => up("ai", { transcription: e.target.value })}>
              <option value="local-whisper">On this Mac (free, private)</option><option value="cloud">Cloud service</option></select></div>
        </div>
        <label className="row"><Toggle label="Prefer local models" checked={s.ai.prefer_local_models} onChange={(v) => up("ai", { prefer_local_models: v })} />Prefer local models when quality is good enough</label>
        <label className="row"><Toggle label="Hard stop at budget" checked={s.ai.hard_stop_at_budget} onChange={(v) => up("ai", { hard_stop_at_budget: v })} />Stop paid AI calls when the budget is reached (instead of only warning)</label>
      </div>

      <div className="card stack">
        <h2>Publishing & privacy</h2>
        <label className="row"><Toggle label="Require approval" checked={s.publishing.require_approval} onChange={(v) => up("publishing", { require_approval: v })} />Never publish without my approval</label>
        <label className="row"><Toggle label="Allow auto publish rules" checked={s.publishing.allow_auto_publish_rules} disabled={s.publishing.require_approval}
          onChange={(v) => up("publishing", { allow_auto_publish_rules: v })} />Allow per-destination automatic publishing rules</label>
        <label className="row"><Toggle label="Allow cloud upload" checked={s.privacy.allow_cloud_upload_of_footage} onChange={(v) => up("privacy", { allow_cloud_upload_of_footage: v })} />Allow sending footage to cloud AI services (off keeps video on this Mac)</label>
      </div>

      <div className="card stack">
        <h2>Processing & storage</h2>
        <div className="grid cols-2">
          <div className="field"><label htmlFor="conc">Parallel jobs: {s.processing.max_concurrent_jobs}</label>
            <input id="conc" type="range" min={1} max={8} value={s.processing.max_concurrent_jobs} onChange={(e) => up("processing", { max_concurrent_jobs: Number(e.target.value) })} /></div>
          <div className="field"><label htmlFor="qual">Processing quality</label>
            <select id="qual" className="select" value={s.processing.quality} onChange={(e) => up("processing", { quality: e.target.value })}>
              <option value="fast">Fast</option><option value="balanced">Balanced</option><option value="best">Best</option></select></div>
          <div className="field"><label htmlFor="cache">Cache limit (GB)</label>
            <input id="cache" className="input" type="number" min={1} value={s.storage.max_cache_gb} onChange={(e) => up("storage", { max_cache_gb: Number(e.target.value) })} /></div>
        </div>
        <label className="row"><Toggle label="Keep originals" checked={s.storage.keep_original_imports} onChange={(v) => up("storage", { keep_original_imports: v })} />Keep an untouched copy of every imported video</label>
      </div>

      <div className="row" style={{ position: "sticky", bottom: 12 }}>
        <span className="spacer" />
        <button className="btn ghost" disabled={!dirty} onClick={() => data && setS(structuredClone(data))}>Discard</button>
        <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(s)}>{save.isPending && <span className="spinner" />}Save changes</button>
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
          <li><KeyRound size={11} /> Logins and app keys: {health.data?.secret_backend === "os-keychain" ? "macOS Keychain" : "encrypted file on this computer (no Keychain detected)"}. Never written to the database or logs.</li>
          <li>The background service only listens on 127.0.0.1 and rejects requests without this window's private token, from other hosts, or from other websites.</li>
          <li>Sign-ins use each platform's official login page. AI Clipper never sees or stores your passwords or browser cookies.</li>
          <li>Every account, routing and settings change is recorded below.</li>
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
  const rows = [["⌘1 … ⌘9", "Jump to sidebar sections"], ["⌘,", "Settings"], ["Esc", "Close a dialog"], ["Delete / Backspace", "Remove the selected route in the funnel"], ["Enter", "Submit the open form"]];
  return (
    <div className="card" style={{ maxWidth: 520 }}>
      {rows.map(([k, d]) => <div key={k} className="list-row"><span className="kbd">{k}</span><span className="muted">{d}</span></div>)}
    </div>
  );
}
