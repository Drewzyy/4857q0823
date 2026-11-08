import { Link } from "react-router-dom";
import { CircleDashed } from "lucide-react";
import type { ModuleDef } from "../lib/modules";

// Honest placeholder: says exactly what is not built yet instead of showing a fake screen.
export default function Planned({ module: m }: { module: ModuleDef }) {
  const Icon = m.icon;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="row"><Icon size={20} color="var(--accent-hi)" /><h1>{m.label}</h1><span className="pill nodot">Coming next</span></div>
          <p>{m.summary}</p>
        </div>
      </div>
      <div className="card" style={{ maxWidth: 720 }}>
        <div className="row" style={{ marginBottom: 10 }}><CircleDashed size={16} color="var(--faint)" /><h3>Planned scope</h3></div>
        <ul className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>{m.scope?.map((s) => <li key={s}>{s}</li>)}</ul>
        <p className="small faint" style={{ marginTop: 14 }}>
          This isn't built yet, so it shows no controls. Clips are already made automatically and are waiting in <Link to="/ready">Ready to Upload</Link>.
        </p>
      </div>
    </div>
  );
}
