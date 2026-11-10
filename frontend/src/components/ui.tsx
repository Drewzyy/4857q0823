import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { siFacebook, siInstagram, siKick, siTiktok, siTwitch, siYoutube } from "simple-icons";
import { PLATFORM_LABEL, type Creator } from "../lib/api";

/* ---------- toasts ---------- */
type Toast = { id: number; kind: "ok" | "err" | "info"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === "err" ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- modal (native <dialog>: focus trap + Esc for free) ---------- */
export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`modal${wide ? " wide" : ""}`} onClose={onClose} onCancel={(e) => { e.preventDefault(); onClose(); }}>
      {open && (
        <>
          <div className="modal-head">
            <h2>{title}</h2>
            <button className="btn ghost icon" onClick={onClose} aria-label="Close"><X size={16} /></button>
          </div>
          <div className="modal-body">{children}</div>
          {footer && <div className="modal-foot">{footer}</div>}
        </>
      )}
    </dialog>
  );
}

export function ConfirmModal({ open, title, message, confirmLabel = "Confirm", danger, onConfirm, onClose, busy }: {
  open: boolean; title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; busy?: boolean;
  onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className={`btn ${danger ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy} autoFocus>{busy && <span className="spinner" />}{confirmLabel}</button>
    </>}>
      <div className="muted">{message}</div>
    </Modal>
  );
}

/* ---------- small pieces ---------- */
// Official brand marks (Simple Icons, CC0) used to label each platform.
const BRANDS: Record<string, { path: string; bg: string; fg: string }> = {
  tiktok: { path: siTiktok.path, bg: "#000000", fg: "#FFFFFF" },
  instagram: { path: siInstagram.path, bg: "linear-gradient(45deg,#F58529,#DD2A7B 45%,#8134AF 75%,#515BD4)", fg: "#FFFFFF" },
  youtube: { path: siYoutube.path, bg: "#FFFFFF", fg: "#FF0000" },
  facebook: { path: siFacebook.path, bg: "#0866FF", fg: "#FFFFFF" },
  meta: { path: siFacebook.path, bg: "#0866FF", fg: "#FFFFFF" },
  twitch: { path: siTwitch.path, bg: "#9146FF", fg: "#FFFFFF" },
  kick: { path: siKick.path, bg: "#000000", fg: "#53FC19" },
};

export function PlatformBadge({ platform, large }: { platform: string; large?: boolean }) {
  const b = BRANDS[platform];
  const label = PLATFORM_LABEL[platform] ?? platform;
  if (!b) return <span className={`plat${large ? " lg" : ""}`} aria-label={label}>?</span>;
  return (
    <span className={`plat${large ? " lg" : ""}`} style={{ background: b.bg }} title={label} aria-label={label} role="img">
      <svg viewBox="0 0 24 24" width="62%" height="62%" fill={b.fg} aria-hidden="true"><path d={b.path} /></svg>
    </span>
  );
}

export function Avatar({ url, platform }: { url: string | null; platform: string }) {
  const [broken, setBroken] = useState(false);
  if (!url || broken) return <PlatformBadge platform={platform} large />;
  return <img className="avatar" src={url} alt="" onError={() => setBroken(true)} referrerPolicy="no-referrer" />;
}

const STATUS: Record<string, [string, string]> = {
  connected: ["ok", "Connected"], expiring: ["warn", "Expires soon"], expired: ["err", "Sign-in expired"], error: ["err", "Error"],
  revoked: ["err", "Revoked"], disconnected: ["", "Not connected"], draft: ["accent", "Planned"],
  active: ["ok", "Monitoring"], paused: ["", "Paused"],
  queued: ["", "Queued"], running: ["accent", "Running"], succeeded: ["ok", "Done"], failed: ["err", "Failed"], cancelled: ["", "Cancelled"],
};
export function StatusPill({ status }: { status: string }) {
  const [cls, label] = STATUS[status] ?? ["", status];
  return <span className={`pill ${cls}`}>{label}</span>;
}

export function CreatorChip({ creator }: { creator: Creator | null }) {
  if (!creator) return <span className="faint small">No creator</span>;
  return <span className="chip"><span className="dot" style={{ background: creator.color }} />{creator.name}</span>;
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <span className="toggle">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span />
    </span>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return <div className="empty">{icon}<h3 style={{ color: "var(--text)" }}>{title}</h3>{children}</div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="row muted" style={{ padding: 24 }}><span className="spinner" />{label}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="banner warn"><AlertCircle size={16} /><span>{error instanceof Error ? error.message : String(error)}</span></div>;
}

export function relTime(iso: string | null): string {
  if (!iso) return "Never";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  const fut = d < 0; const a = Math.abs(d);
  const s = a < 60 ? "just now" : a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} d`;
  if (s === "just now") return s;
  return fut ? `in ${s}` : `${s} ago`;
}

export function bytes(n: number): string {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

export const CREATOR_COLORS = ["#8b5cf6", "#f97316", "#22c55e", "#3b82f6", "#ec4899", "#eab308", "#14b8a6", "#ef4444"];
