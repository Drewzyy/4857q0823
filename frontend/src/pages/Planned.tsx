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
          <div className="row"><Icon size={20} color="var(--accent-hi)" /><h1>{m.label}</h1><span className="pill nodot">Not started · Milestone {m.milestone}</span></div>
          <p>{m.summary}</p>
        </div>
      </div>
      <div className="card" style={{ maxWidth: 720 }}>
        <div className="row" style={{ marginBottom: 10 }}><CircleDashed size={16} color="var(--faint)" /><h3>Planned scope</h3></div>
        <ul className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>{m.scope?.map((s) => <li key={s}>{s}</li>)}</ul>
        <p className="small faint" style={{ marginTop: 14 }}>
          Nothing on this page is functional yet, so it shows no controls. The accounts and routing you set up in
          {" "}<Link to="/sources">Source Accounts</Link>, <Link to="/destinations">Destinations</Link> and <Link to="/funnel">Account Funnel</Link> are what this module will use.
        </p>
      </div>
    </div>
  );
}
