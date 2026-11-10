import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Creator } from "../lib/api";

export interface PickItem { id: number; name: string; color?: string; sub?: string }

/** A dropdown of checkboxes: pick any number of items (streamers, pages). */
export function Picker({ items, value, onChange, label, empty = "None", hint }:
  { items: PickItem[]; value: number[]; onChange: (ids: number[]) => void; label: string; empty?: string; hint?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);
  const chosen = items.filter((c) => value.includes(c.id));
  return (
    <div ref={ref} style={{ position: "relative", minWidth: 150 }}>
      <button type="button" className="select" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}
        style={{ textAlign: "left", display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center", minHeight: 30, backgroundImage: "none" }}>
        {chosen.length === 0 ? <span className="faint">{empty}</span> : chosen.map((c) => (
          <span key={c.id} className="chip" style={{ padding: "0 6px" }}>{c.color && <span className="dot" style={{ background: c.color }} />}{c.name}</span>))}
        <ChevronDown size={12} style={{ marginLeft: "auto" }} />
      </button>
      {open && (
        <div className="card" style={{ position: "absolute", zIndex: 30, top: "calc(100% + 4px)", left: 0, minWidth: 220, padding: 8, boxShadow: "var(--shadow)" }}>
          {items.length === 0 && <p className="small faint" style={{ padding: 4 }}>Nothing to pick yet</p>}
          {items.map((c) => (
            <label key={c.id} className="check" style={{ display: "flex", padding: "5px 6px", gap: 6 }}>
              <input type="checkbox" checked={value.includes(c.id)}
                onChange={(e) => onChange(e.target.checked ? [...value, c.id] : value.filter((x) => x !== c.id))} />
              {c.color && <span className="dot" style={{ width: 8, height: 8, borderRadius: 3, background: c.color }} />}{c.name}
              {c.sub && <span className="faint small">{c.sub}</span>}
            </label>
          ))}
          {hint && <p className="small faint" style={{ padding: "4px 6px 0" }}>{hint}</p>}
        </div>
      )}
    </div>
  );
}

/** Pick one or more streamers. */
export default function CreatorPicker({ creators, ...rest }: { creators: Creator[]; value: number[]; onChange: (ids: number[]) => void; label: string; empty?: string; hint?: string }) {
  return <Picker items={creators} {...rest} />;
}
