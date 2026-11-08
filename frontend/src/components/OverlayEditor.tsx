import type { FontKey, Overlay, TextStyle } from "../lib/api";
import { Toggle } from "./ui";

const FONTS: [FontKey, string][] = [["montserrat", "Montserrat Black"], ["anton", "Anton"], ["bebas", "Bebas Neue"], ["poppins", "Poppins ExtraBold"]];
const SWATCHES = ["#FFE500", "#FFFFFF", "#F97316", "#22C55E", "#38BDF8", "#EC4899", "#000000"];
const PREVIEW_W = 216;

function textCss(s: TextStyle) {
  const k = PREVIEW_W / 1080;
  return {
    top: `${s.y_percent}%`, fontFamily: `"V-${s.font}", sans-serif`, fontSize: `${Math.max(6, s.size * k)}px`, color: s.color,
    WebkitTextStroke: s.outline ? `${Math.max(1, s.outline * k * 2)}px ${s.outline_color}` : undefined,
    textTransform: s.all_caps ? ("uppercase" as const) : ("none" as const),
    textShadow: `0 ${2 * k}px ${3 * k}px rgba(0,0,0,.6)`,
  };
}

/** Approximate live preview of the text burned into the 9:16 video. */
export function OverlayPreview({ overlay, title, caption = "no way he actually" }: { overlay: Overlay; title: string; caption?: string }) {
  const words = caption.split(/\s+/).slice(0, overlay.captions.words_per_caption).join(" ");
  return (
    <div className="ov-preview" aria-label="Preview of text on the video">
      {overlay.title.enabled && title.trim() && <div className="ov-text" style={textCss(overlay.title)}>{title.replace(/\p{Extended_Pictographic}/gu, "")}</div>}
      {overlay.captions.enabled && <div className="ov-text" style={textCss(overlay.captions)}>{words}</div>}
    </div>
  );
}

function StyleFields({ label, s, onChange, extra }: { label: string; s: TextStyle; onChange: (v: Partial<TextStyle>) => void; extra?: React.ReactNode }) {
  const id = label.toLowerCase().replace(/\s+/g, "-");
  return (
    <fieldset className="stack" style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12, margin: 0 }}>
      <legend className="row" style={{ padding: "0 6px" }}>
        <Toggle label={`Show ${label}`} checked={s.enabled} onChange={(v) => onChange({ enabled: v })} /><strong>{label}</strong>
      </legend>
      <div className="ov-grid" style={{ opacity: s.enabled ? 1 : 0.45 }}>
        <div className="field"><label htmlFor={`${id}-font`}>Font</label>
          <select id={`${id}-font`} className="select" value={s.font} onChange={(e) => onChange({ font: e.target.value as FontKey })}>
            {FONTS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></div>
        <div className="field"><label htmlFor={`${id}-size`}>Size: {s.size}</label>
          <input id={`${id}-size`} type="range" min={30} max={160} value={s.size} onChange={(e) => onChange({ size: Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor={`${id}-y`}>Position: {s.y_percent}% from top</label>
          <input id={`${id}-y`} type="range" min={5} max={95} value={s.y_percent} onChange={(e) => onChange({ y_percent: Number(e.target.value) })} /></div>
        <div className="field"><span className="label-text">Color</span>
          <div className="ov-color">
            <input type="color" aria-label={`${label} color`} value={s.color} onChange={(e) => onChange({ color: e.target.value.toUpperCase() })} />
            {SWATCHES.map((c) => <button key={c} type="button" aria-label={`${label} color ${c}`} onClick={() => onChange({ color: c })}
              style={{ width: 18, height: 18, borderRadius: 5, background: c, border: s.color.toUpperCase() === c ? "2px solid var(--accent-hi)" : "1px solid var(--line-2)", cursor: "pointer" }} />)}
          </div></div>
        <div className="field"><label htmlFor={`${id}-outline`}>Outline: {s.outline}</label>
          <div className="ov-color"><input id={`${id}-outline`} type="range" min={0} max={14} value={s.outline} onChange={(e) => onChange({ outline: Number(e.target.value) })} />
            <input type="color" aria-label={`${label} outline color`} value={s.outline_color} onChange={(e) => onChange({ outline_color: e.target.value.toUpperCase() })} /></div></div>
        <label className="check" style={{ alignSelf: "end" }}><input type="checkbox" checked={s.all_caps} onChange={(e) => onChange({ all_caps: e.target.checked })} />ALL CAPS</label>
        {extra}
      </div>
    </fieldset>
  );
}

export function OverlayEditor({ value, onChange, title }: { value: Overlay; onChange: (o: Overlay) => void; title: string }) {
  const setT = (v: Partial<Overlay["title"]>) => onChange({ ...value, title: { ...value.title, ...v } });
  const setC = (v: Partial<Overlay["captions"]>) => onChange({ ...value, captions: { ...value.captions, ...v } });
  return (
    <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
      <OverlayPreview overlay={value} title={title} />
      <div className="stack" style={{ flex: 1, minWidth: 0 }}>
        <StyleFields label="Title" s={value.title} onChange={setT} extra={
          <div className="field"><label htmlFor="title-dur">Shows for {value.title.duration} s</label>
            <input id="title-dur" type="range" min={1} max={15} step={0.5} value={value.title.duration} onChange={(e) => setT({ duration: Number(e.target.value) })} /></div>} />
        <StyleFields label="Captions" s={value.captions} onChange={setC} extra={
          <div className="field"><label htmlFor="cap-words">Words at a time: {value.captions.words_per_caption}</label>
            <input id="cap-words" type="range" min={1} max={6} value={value.captions.words_per_caption} onChange={(e) => setC({ words_per_caption: Number(e.target.value) })} /></div>} />
        <p className="small faint">The preview is approximate. The video uses the same fonts, so the real result matches closely.</p>
      </div>
    </div>
  );
}
