import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, FileJson, Info, Lock, XCircle } from "lucide-react";
import { api, ApiError, type Attempt, type ConnectorKey, type PlatformStatus } from "../lib/api";
import { CopyBox, Modal, PlatformBadge, useToast } from "./ui";

type ConnectOpts = { purpose?: "destination" | "source"; linkDestinationId?: number | null };
type Ctx = { connect: (key: ConnectorKey, opts?: ConnectOpts) => void; openSetup: (key: ConnectorKey) => void; platforms: PlatformStatus[] };
const ConnectCtx = createContext<Ctx>({ connect: () => {}, openSetup: () => {}, platforms: [] });
export const useConnect = () => useContext(ConnectCtx);

export function ConnectProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: platforms = [] } = useQuery({ queryKey: ["platforms"], queryFn: api.platforms });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: Infinity });
  const [setupKey, setSetupKey] = useState<ConnectorKey | null>(null);
  const [pendingAfterSetup, setPendingAfterSetup] = useState<{ key: ConnectorKey; opts: ConnectOpts } | null>(null);
  const [waiting, setWaiting] = useState<{ key: ConnectorKey; opts: ConnectOpts; attempt?: Attempt; url?: string; error?: string } | null>(null);
  const desktop = !!health?.desktop_mode;

  const begin = useCallback(async (key: ConnectorKey, opts: ConnectOpts, win: Window | null) => {
    setWaiting({ key, opts });
    try {
      const r = await api.startConnect({ platform: key, purpose: opts.purpose ?? "destination", link_destination_id: opts.linkDestinationId ?? null });
      if (win) { win.opener = null; win.location.href = r.authorize_url; }
      setWaiting({ key, opts, attempt: r.attempt, url: r.authorize_url });
    } catch (e) {
      win?.close();
      if (e instanceof ApiError && e.code === "setup_required") { setWaiting(null); setPendingAfterSetup({ key, opts }); setSetupKey(key); return; }
      setWaiting({ key, opts, error: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const connect = useCallback((key: ConnectorKey, opts: ConnectOpts = {}) => {
    const p = platforms.find((x) => x.key === key);
    if (!p?.configured) { setPendingAfterSetup({ key, opts }); setSetupKey(key); return; }
    // Open the tab inside the click so popup blockers allow it; the desktop app opens the system browser itself.
    const win = desktop ? null : window.open("about:blank", "_blank");
    void begin(key, opts, win);
  }, [platforms, desktop, begin]);

  // Poll the sign-in attempt while the user is on the platform's login page.
  const attemptId = waiting?.attempt?.id;
  const attemptStatus = waiting?.attempt?.status;
  useEffect(() => {
    if (!attemptId || (attemptStatus !== "pending" && attemptStatus !== "processing")) return;
    const t = setInterval(async () => {
      try {
        const a = await api.attempt(attemptId);
        setWaiting((w) => (w && w.attempt?.id === a.id ? { ...w, attempt: a } : w));
        if (a.status === "succeeded") {
          ["destinations", "sources", "connections", "dashboard", "funnel", "platforms"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
          toast("ok", a.message || "Connected");
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) setWaiting((w) => (w ? { ...w, error: "The sign-in window expired. Start again." } : w));
      }
    }, 1500);
    return () => clearInterval(t);
  }, [attemptId, attemptStatus, qc, toast]);

  const label = (k: ConnectorKey) => platforms.find((p) => p.key === k)?.label ?? k;
  const w = waiting;
  const done = w?.attempt?.status === "succeeded";
  const failed = w?.attempt?.status === "failed" || !!w?.error;

  return (
    <ConnectCtx.Provider value={{ connect, openSetup: (k) => { setPendingAfterSetup(null); setSetupKey(k); }, platforms }}>
      {children}
      {setupKey && (
        <SetupWizard platform={platforms.find((p) => p.key === setupKey)} secretBackend={health?.secret_backend} onClose={() => { setSetupKey(null); setPendingAfterSetup(null); }}
          continueLabel={pendingAfterSetup ? `Continue to ${label(setupKey)} login` : undefined}
          onConfigured={() => {
            qc.invalidateQueries({ queryKey: ["platforms"] });
            qc.invalidateQueries({ queryKey: ["dashboard"] });
            const next = pendingAfterSetup;
            setSetupKey(null); setPendingAfterSetup(null);
            if (next) setWaiting({ key: next.key, opts: next.opts, url: undefined });
            else toast("ok", `${label(setupKey)} is ready. You can connect accounts now.`);
          }} />
      )}
      <Modal open={!!w} onClose={() => setWaiting(null)} title={<span className="row"><PlatformBadge platform={w?.key ?? "meta"} />{done ? "Connected" : `Connect ${w ? label(w.key) : ""}`}</span>}
        footer={done || failed ? <button className="btn primary" onClick={() => setWaiting(null)} autoFocus>Done</button> : <button className="btn ghost" onClick={() => setWaiting(null)}>Cancel</button>}>
        {w && !w.attempt && !w.error && !w.url && (
          <div className="stack">
            <p className="muted">Setup is done. The next step opens {label(w.key)}'s own login page, where you approve access. AI Clipper never sees your password.</p>
            <button className="btn primary" style={{ alignSelf: "flex-start" }} onClick={() => {
              const win = desktop ? null : window.open("about:blank", "_blank");
              void begin(w.key, w.opts, win);
            }}><ExternalLink size={14} />Open {label(w.key)} login</button>
          </div>
        )}
        {w?.attempt && (w.attempt.status === "pending" || w.attempt.status === "processing") && (
          <div className="stack">
            <div className="row"><span className="spinner" /><strong>Waiting for you to approve access in your browser…</strong></div>
            <p className="muted">Log in on the {label(w.key)} page that just opened and click Allow. This window updates by itself.</p>
            {w.url && <a href={w.url} target="_blank" rel="noopener noreferrer" className="row small"><ExternalLink size={13} />Login page didn't open? Open it again</a>}
          </div>
        )}
        {done && (
          <div className="row"><CheckCircle2 color="var(--ok)" /><div><strong>{w?.attempt?.message}</strong>
            <p className="muted">{w?.attempt?.accounts_added ? `${w.attempt.accounts_added} new account(s) added.` : "Existing accounts were refreshed."}</p></div></div>
        )}
        {failed && (
          <div className="stack">
            <div className="row"><XCircle color="var(--err)" /><strong>{w?.error || w?.attempt?.message}</strong></div>
            <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => w && connect(w.key, w.opts)}>Try again</button>
          </div>
        )}
      </Modal>
    </ConnectCtx.Provider>
  );
}

function SetupWizard({ platform, onClose, onConfigured, continueLabel, secretBackend }: {
  platform?: PlatformStatus; secretBackend?: string; onClose: () => void; onConfigured: () => void; continueLabel?: string;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [relay, setRelay] = useState(platform?.custom_redirect ? platform.redirect_uri : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  if (!platform) return null;
  const isGoogle = platform.key === "youtube";

  const save = async () => {
    setBusy(true); setError(null);
    try { await api.setApp(platform.key, { client_id: values.client_id ?? "", client_secret: values.client_secret ?? "", redirect_uri: platform.key === "meta" ? relay.trim() || null : null }); onConfigured(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const uploadFile = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true); setError(null);
    try { await api.uploadGoogleClient(f); onConfigured(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const complete = platform.credential_fields.every((f) => (values[f.name] ?? "").trim());

  return (
    <Modal open onClose={onClose} wide title={<span className="row"><PlatformBadge platform={platform.key} />{platform.configured ? `${platform.label} setup` : `One-time ${platform.label} setup`}</span>}
      footer={<>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={!complete || busy} onClick={save}>{busy && <span className="spinner" />}{continueLabel ?? "Check & save"}</button>
      </>}>
      <div className="banner"><Info size={16} color="var(--accent-hi)" /><div className="small">
        {platform.label} only lets apps it knows about request access, so it needs to know AI Clipper exists. That's a one-time registration in your own
        developer account (about 5 minutes, free). After this you only ever click <strong>Connect</strong> and log in. Builds that ship with
        their own registration skip this screen entirely.
      </div></div>
      <ol className="steps">
        {platform.setup_steps.map((s, i) => (
          <li key={i}><div>
            <div className="row"><strong>{s.title}</strong>{s.url && <a href={s.url} target="_blank" rel="noopener noreferrer" className="row small"><ExternalLink size={12} />Open</a>}</div>
            <div className="muted small">{s.detail}</div>
            {s.copy_value && <CopyBox value={s.copy_value} />}
          </div></li>
        ))}
      </ol>
      {isGoogle && (
        <div className={`dropzone${over ? " over" : ""}`} role="button" tabIndex={0}
          onClick={() => fileRef.current?.click()} onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); void uploadFile(e.dataTransfer.files[0]); }}>
          <FileJson size={20} style={{ verticalAlign: "middle" }} /> Drop the <span className="mono">client_secret_….json</span> file here, or click to choose it
          <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => void uploadFile(e.target.files?.[0])} />
        </div>
      )}
      <div className="grid cols-2">
        {platform.credential_fields.map((f) => (
          <div className="field" key={f.name}>
            <label htmlFor={`cred-${f.name}`}>{f.label}</label>
            <input id={`cred-${f.name}`} className="input" type={f.secret ? "password" : "text"} autoComplete="off" spellCheck={false}
              placeholder={f.placeholder} value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
          </div>
        ))}
      </div>
      {platform.key === "meta" && (
        <details><summary className="small muted" style={{ cursor: "pointer" }}>Advanced: HTTPS relay redirect</summary>
          <div className="field" style={{ marginTop: 8 }}><label htmlFor="relay">Relay URL (leave empty to use localhost)</label>
            <input id="relay" className="input" placeholder="https://yourname.github.io/ai-clipper-relay/" value={relay} onChange={(e) => setRelay(e.target.value)} />
            <span className="hint">Only needed if Meta refuses the localhost address. The relay page just sends your browser back to this app.</span></div>
        </details>
      )}
      <div className="row small faint"><Lock size={12} />{secretBackend === "os-keychain" ? "Stored in your Mac's Keychain" : "Stored encrypted on this computer"}, checked with {platform.label} before saving, never shown again.</div>
      {error && <div className="banner warn"><XCircle size={16} /><span>{error}</span></div>}
      {platform.notes.length > 0 && (
        <details><summary className="small muted" style={{ cursor: "pointer" }}>Good to know about {platform.label}</summary>
          <ul className="small muted" style={{ margin: "8px 0 0", paddingLeft: 18 }}>{platform.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </details>
      )}
    </Modal>
  );
}
