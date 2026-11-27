import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { relTime, useToast } from "./ui";

/** Settings > Obsidian: your vault as Vyral's memory. What it learns goes into notes there; your rules come back. */
export function ObsidianSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["obsidian"], queryFn: api.obsidian, refetchInterval: 30_000 });
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  if (!data) return null;

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { qc.setQueryData(["obsidian"], await fn()); toast("ok", done); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card stack" style={{ maxWidth: 820 }}>
      <h2>Obsidian</h2>
      <p className="small muted">Use an Obsidian vault as Vyral's memory. Every clip you send to learn from gets a note in the vault's <code>Vyral/Learned</code> folder
        saying what kind of moment it is and which edits, sound effects and text it uses. <code>Vyral/Playbook.md</code> sums up what to do in each situation,
        and the rules you write in it are used when Vyral makes clips. It all stays on this computer.</p>
      {data.connected ? (
        <>
          <div className="row wrap small">
            <span className="pill ok">Connected: {data.name}</span>
            <span>{data.notes} learned notes{data.synced ? `, synced ${relTime(data.synced)}` : ""}</span>
            <span className="spacer" />
            <button className="btn" disabled={busy} onClick={() => run(api.syncObsidian, "Synced with Obsidian")}>Sync now</button>
            <button className="btn ghost sm" disabled={busy} onClick={() => run(api.disconnectObsidian, "Obsidian disconnected")}>Disconnect</button>
          </div>
          <span className="small faint">{data.vault}</span>
          {data.error && <div className="banner err small" role="alert">{data.error}</div>}
          <div className="small">
            <strong>Your rules</strong>{Object.keys(data.rules).length === 0 && <span className="muted"> (none yet)</span>}
            <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
              {Object.entries(data.rules).map(([where, r]) => (
                <li key={where}>{where}: {Object.entries(r).map(([k, v]) => `${k}=${v === true ? "on" : v === false ? "off" : v}`).join(", ")}</li>
              ))}
            </ul>
          </div>
          {data.warnings.length > 0 && <div className="banner warn small" role="status" style={{ flexDirection: "column", gap: 2 }}>
            <strong>Some lines in My rules were ignored:</strong>{data.warnings.map((w) => <span key={w}>{w}</span>)}</div>}
          <details className="small">
            <summary>How to write rules</summary>
            <p>Open <code>Vyral/Playbook.md</code> in Obsidian and add lines under <strong>My rules</strong>, one situation per line:</p>
            <pre style={{ margin: 0 }}>{"- laugh: sound=ding, zoom=on, headline=off\n- shock: hook=on\n- any: max_length=60"}</pre>
            <p>Situations: any, laugh, shock, anger, fear, hype, plain. A clip's own situation wins over "any".
              You can use hook, headline, sfx, zoom and captions (on or off), sound (a sound's name, or off), length (seconds longer or shorter than usual)
              and max_length (seconds). Vyral never changes this section.</p>
          </details>
        </>
      ) : (
        <>
          <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            <li>Install Obsidian from <a href="https://obsidian.md" target="_blank" rel="noopener noreferrer">obsidian.md</a> and open it.</li>
            <li>Create a new vault, or open one you already have.</li>
            <li>Copy the vault folder's path. On a Mac, find the folder in Finder, right-click it, hold <strong>Option</strong> and choose <strong>Copy as Pathname</strong>.
              On Windows, hold <strong>Shift</strong>, right-click the folder in File Explorer and choose <strong>Copy as path</strong>.</li>
            <li>Paste it below and press <strong>Connect</strong>.</li>
          </ol>
          <div className="row">
            <input className="input" aria-label="Obsidian vault folder" placeholder="/Users/you/Documents/My vault" autoComplete="off" value={path} onChange={(e) => setPath(e.target.value)} />
            <button className="btn primary" disabled={!path.trim() || busy} onClick={() => run(() => api.connectObsidian(path), "Obsidian connected")}>{busy && <span className="spinner" />}Connect</button>
          </div>
        </>
      )}
    </div>
  );
}
