import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Creator } from "../lib/api";

/** Pick one or more streamers (a general clipping account can cover several). */
export default function CreatorPicker({ creators, value, onChange, label, empty = "None", hint = "Pick several if this account clips more than one streamer." }:
  { creators: Creator[]; value: number[]; onChange: (ids: number[]) => void; label: string; empty?: string; hint?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const chosen = creators.filter((c) => value.includes(c.id));
  return (
    <div ref={ref} style={{ position: "relative", minWidth: 150 }}>
      <button type="button" className="select" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}
        style={{ textAlign: "left", display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center", minHeight: 30, backgroundImage: "none" }}>
        {chosen.length === 0 ? <span className="faint">{empty}</span> : chosen.map((c) => (
          <span key={c.id} className="chip" style={{ padding: "0 6px" }}><span className="dot" style={{ background: c.color }} />{c.name}</span>))}
        <ChevronDown size={12} style={{ marginLeft: "auto" }} />
      </button>
      {open && (
        <div className="card" style={{ position: "absolute", zIndex: 30, top: "calc(100% + 4px)", left: 0, minWidth: 200, padding: 8, boxShadow: "var(--shadow)" }}>
          {creators.length === 0 && <p className="small faint" style={{ padding: 4 }}>No creators yet</p>}
          {creators.map((c) => (
            <label key={c.id} className="check" style={{ display: "flex", padding: "5px 6px" }}>
              <input type="checkbox" checked={value.includes(c.id)}
                onChange={(e) => onChange(e.target.checked ? [...value, c.id] : value.filter((x) => x !== c.id))} />
              <span className="dot" style={{ width: 8, height: 8, borderRadius: 3, background: c.color }} />{c.name}
            </label>
          ))}
          <p className="small faint" style={{ padding: "4px 6px 0" }}>{hint}</p>
        </div>
      )}
    </div>
  );
}
