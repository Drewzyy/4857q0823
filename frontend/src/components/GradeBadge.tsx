import type { GradeT } from "../lib/api";

const COLORS: Record<GradeT["tier"], string> = { S: "#f5b301", A: "#3fb67a", B: "#38bdf8", C: "#a1a1aa", D: "#e5484d" };

/** The clip's grade as a small tier badge; the score and reasons show on hover. */
export function GradeBadge({ grade }: { grade: GradeT | null }) {
  if (!grade) return null;
  return (
    <span className="grade-badge" style={{ background: COLORS[grade.tier] }}
      title={`${grade.tier} tier, ${grade.score}/100.${grade.tier === "D" ? " Probably not worth posting as it is." : ""} ${grade.tips.length ? "To improve: " + grade.tips.join(" ") : "Every signal is strong."}`}>
      {grade.tier}<span>{grade.score}</span>{grade.tier === "D" && <span style={{ fontWeight: 600, marginLeft: 2 }}>· skip?</span>}
    </span>
  );
}

/** The full breakdown: each part's points and what it saw, and the fixes worth the most. */
export function GradeCard({ grade }: { grade: GradeT | null }) {
  if (!grade) return null;
  return (
    <div className="card stack">
      <div className="row"><h2>Grade</h2><GradeBadge grade={grade} /><span className="spacer" />
        <span className="small faint">A prediction from what Vyral can measure, not a promise.</span></div>
      {grade.parts.map((p) => (
        <div key={p.name} className="stack" style={{ gap: 3 }}>
          <div className="row small"><strong>{p.name}</strong><span className="spacer" /><span className="mono">{p.points}/{p.max}</span></div>
          <div className="bar" aria-label={`${p.name}: ${p.points} of ${p.max}`}><div style={{ width: `${(p.points / p.max) * 100}%` }} /></div>
          <span className="small faint">{p.note}</span>
        </div>
      ))}
      {grade.tips.length > 0 && (
        <div className="stack" style={{ gap: 4 }}><span className="label-text">Biggest improvements</span>
          {grade.tips.map((t) => <span key={t} className="small">• {t}</span>)}</div>
      )}
      <span className="small faint">The grade updates after you save an edit and it finishes rendering.</span>
    </div>
  );
}
