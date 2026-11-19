import { useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Megaphone, Pencil, Plus, Search, Trash2, Unlink, Wand2 } from "lucide-react";
import { api, PLATFORM_LABEL, type CampaignClips, type CampaignFields, type CampaignPlatform, type CampaignT } from "../lib/api";
import { ConfirmModal, Empty, ErrorNote, Loading, Modal, PlatformBadge, useToast } from "../components/ui";

const PLATFORMS: CampaignPlatform[] = ["tiktok", "instagram", "youtube", "x"];
const n = (v: number) => v.toLocaleString();

export default function CampaignsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<CampaignT | "new" | null>(null);
  const [removing, setRemoving] = useState<CampaignT | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const list = useQuery({ queryKey: ["campaigns", q], queryFn: () => api.campaigns(q.trim()), placeholderData: keepPreviousData });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["campaigns"] }); void qc.invalidateQueries({ queryKey: ["campaign-clips"] }); };

  return (
    <div className="page">
      <div className="page-head"><div><h1>Campaigns</h1>
        <p>Clipping campaigns for your streamers. Clips that fit one are tagged to it, get its hashtags, and you get a Discord message when a posted video qualifies.</p></div>
        <button className="btn primary" onClick={() => setEditing("new")}><Plus size={14} />Add campaign</button></div>

      <div className="row" style={{ marginBottom: 16 }}>
        <Search size={16} color="var(--muted)" />
        <input className="input" style={{ maxWidth: 420 }} aria-label="Search campaigns" placeholder="Search by tag or name" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {list.error && <ErrorNote error={list.error} />}
      {list.isLoading ? <Loading /> : (list.data ?? []).length === 0 ? (
        <div className="card"><Empty icon={<Megaphone size={28} />} title={q.trim() ? "No campaign matches that" : "No campaigns yet"}>
          {!q.trim() && <p className="small">Paste a campaign post and Vyral fills in the details.</p>}</Empty></div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          {list.data!.map((c) => (
            <CampaignCard key={c.id} c={c} open={openId === c.id} onToggle={() => setOpenId(openId === c.id ? null : c.id)}
              onEdit={() => setEditing(c)} onRemove={() => setRemoving(c)} onChange={refresh} />
          ))}
        </div>
      )}

      <CampaignModal campaign={editing === "new" ? null : editing} open={editing !== null} onClose={() => setEditing(null)} onSaved={refresh} />
      <ConfirmModal open={!!removing} danger title="Delete this campaign?" confirmLabel="Delete" onClose={() => setRemoving(null)}
        message={<>This removes {removing?.name} and its tags. Your clips stay.</>}
        onConfirm={async () => {
          try { await api.removeCampaign(removing!.id); refresh(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
          setRemoving(null);
        }} />
    </div>
  );
}

function CampaignCard({ c, open, onToggle, onEdit, onRemove, onChange }: {
  c: CampaignT; open: boolean; onToggle: () => void; onEdit: () => void; onRemove: () => void; onChange: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const links = [["Join Campaign", c.join_url], ["Discord", c.discord_url], ["Guidelines", c.guidelines_url]].filter(([, u]) => u);
  return (
    <div className="card stack" style={{ gap: 10 }}>
      <div className="row wrap">
        <strong style={{ fontSize: 15 }}>{c.name}</strong>
        <span className="pill">{c.tag}</span>
        <span className={`pill ${c.status === "live" ? "ok" : ""}`}>{c.status === "live" ? "Live" : "Ended"}</span>
        <span className="spacer" />
        {c.creator && (c.required_hashtags.length > 0 || c.must_mention.length > 0 || c.rules) && (
          <button className="btn sm" onClick={async () => {
            try { await api.applyCampaignRules(c.id); void qc.invalidateQueries({ queryKey: ["streamers"] }); toast("ok", `Added to ${c.creator!.name}'s caption rules`); }
            catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
          }}>Apply rules to {c.creator.name}</button>)}
        <button className="btn sm" aria-expanded={open} onClick={onToggle}>{open ? "Hide" : "Rules and clips"}</button>
        <button className="btn ghost icon" aria-label={`Edit ${c.name}`} onClick={onEdit}><Pencil size={14} /></button>
        <button className="btn ghost icon" aria-label={`Delete ${c.name}`} onClick={onRemove}><Trash2 size={14} /></button>
      </div>
      <div className="row wrap small">
        {c.creator && <span className="chip">{c.creator.name}</span>}
        {c.pool && <span><span className="faint">Pool</span> {c.pool}</span>}
        {c.min_views > 0 && <span><span className="faint">Minimum views</span> {n(c.min_views)}</span>}
        {c.audience && <span className="faint">{c.audience}</span>}
        {c.platforms.map((p) => <span key={p} className="pill">{PLATFORM_LABEL[p]}</span>)}
      </div>
      {c.min_views > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          <div className="bar" aria-hidden="true"><div style={{ width: `${Math.min(100, (c.views / c.min_views) * 100)}%` }} /></div>
          <span className="small muted">{n(c.views)} of {n(c.min_views)} views from videos that qualify</span>
        </div>
      )}
      {links.length > 0 && (
        <div className="row wrap">{links.map(([label, url]) => (
          <a key={label} className="btn sm" href={url} target="_blank" rel="noopener noreferrer">{label}<ExternalLink size={12} /></a>))}</div>
      )}
      {open && <CampaignDetail c={c} onChange={onChange} />}
    </div>
  );
}

function CampaignDetail({ c, onChange }: { c: CampaignT; onChange: () => void }) {
  const toast = useToast();
  const data = useQuery({ queryKey: ["campaign-clips", c.id], queryFn: () => api.campaignClips(c.id) });
  const run = async (job: Promise<unknown>) => { try { await job; onChange(); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); } };
  const d: CampaignClips | undefined = data.data;
  return (
    <div className="stack" style={{ gap: 12, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <div className="small muted">
        {c.required_hashtags.length > 0 && <div>Captions must use {c.required_hashtags.join(" ")}</div>}
        {c.must_mention.length > 0 && <div>Captions must mention {c.must_mention.join(", ")}</div>}
        {c.submit_within_minutes && <div>Submit within {c.submit_within_minutes} minutes of posting</div>}
        {c.footage_from && <div>Footage from {c.footage_from}{c.ends_at ? ` until ${c.ends_at}` : ""}</div>}
      </div>
      <details>
        <summary className="small">Full rules</summary>
        <pre className="small" style={{ whiteSpace: "pre-wrap", margin: "8px 0 0" }}>{c.rules || "No rules were saved."}</pre>
      </details>
      {data.error && <ErrorNote error={data.error} />}
      {data.isLoading && <Loading />}
      {d && (
        <>
          <strong className="small">Tagged clips</strong>
          {d.clips.length === 0 && <span className="small faint">None yet. Clips of {c.creator?.name ?? "this streamer"} that fit are tagged as they are made.</span>}
          {d.clips.map((x) => (
            <div key={x.clip_id} className="stack" style={{ gap: 6 }}>
              <div className="row">
                <Link to={`/editor/${x.clip_id}`} className="ellipsis" style={{ flex: 1, minWidth: 0 }}>{x.title || `Clip ${x.clip_id}`}</Link>
                <span className="small faint">{x.added_by === "auto" ? "Tagged by Vyral" : "Tagged by you"}</span>
                <button className="btn sm" onClick={() => run(api.unlinkCampaignClip(c.id, x.clip_id))}><Unlink size={12} />Unlink</button>
              </div>
              {x.outputs.map((o) => (
                <div key={o.output_id} className="row wrap small" style={{ paddingLeft: 12 }}>
                  <PlatformBadge platform={o.platform} />
                  <span>{o.page ?? PLATFORM_LABEL[o.platform]}</span>
                  <span className={`pill ${o.qualifies ? "ok" : "warn"}`}>{o.qualifies ? "Qualifies" : "Not yet"}</span>
                  {!o.qualifies && <span className="faint">{o.reasons.join(", ")}</span>}
                  {o.views != null && <span>{n(o.views)} views</span>}
                  {o.post_url && <a href={o.post_url} target="_blank" rel="noopener noreferrer">Post <ExternalLink size={11} /></a>}
                </div>
              ))}
            </div>
          ))}
          {d.suggested.length > 0 && (
            <>
              <strong className="small">Suggested</strong>
              {d.suggested.map((x) => (
                <div key={x.clip_id} className="row">
                  <Link to={`/editor/${x.clip_id}`} className="ellipsis" style={{ flex: 1, minWidth: 0 }}>{x.title || `Clip ${x.clip_id}`}</Link>
                  <button className="btn sm" onClick={() => run(api.linkCampaignClip(c.id, x.clip_id))}>Link</button>
                </div>
              ))}
            </>
          )}
        </>
      )}
    </div>
  );
}

type Form = Omit<CampaignFields, "creator_id" | "min_views" | "required_hashtags" | "must_mention" | "keywords" | "submit_within_minutes"> & {
  creator_id: string; min_views: string; hashtags: string; mention: string; keywords: string; submit: string;
};
const words = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const blank: Form = {
  name: "", tag: "", creator_id: "", status: "live", pool: "", min_views: "", platforms: [], audience: "", footage_from: null, ends_at: null, hashtags: "",
  mention: "", keywords: "", join_url: "", discord_url: "", guidelines_url: "", submit: "", destination_ids: [], rules: "",
};
const fromCampaign = (c: CampaignT): Form => ({
  ...c, creator_id: c.creator ? String(c.creator.id) : "", min_views: c.min_views ? String(c.min_views) : "", hashtags: c.required_hashtags.join(", "),
  mention: c.must_mention.join(", "), keywords: c.keywords.join(", "), submit: c.submit_within_minutes ? String(c.submit_within_minutes) : "",
});

function CampaignModal({ campaign, open, onClose, onSaved }: { campaign: CampaignT | null; open: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators, enabled: open });
  const pages = useQuery({ queryKey: ["destinations"], queryFn: api.destinations, enabled: open });
  const [f, setF] = useState<Form>(blank);
  const [post, setPost] = useState("");
  const [busy, setBusy] = useState(false);
  const [seen, setSeen] = useState<CampaignT | null | undefined>(undefined);
  const fail = (e: unknown) => toast("err", e instanceof Error ? e.message : String(e));
  // Start from the campaign being edited (or empty) each time the box opens.
  if (open && seen !== campaign) { setSeen(campaign); setF(campaign ? fromCampaign(campaign) : blank); setPost(""); }
  if (!open && seen !== undefined) setSeen(undefined);
  const text = (key: keyof Form, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <div className="field"><label htmlFor={`cp-${key}`}>{label}</label>
      <input id={`cp-${key}`} className="input" value={(f[key] as string | null) ?? ""} onChange={(e) => setF({ ...f, [key]: e.target.value })} {...props} /></div>
  );
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const fill = async () => {
    setBusy(true);
    try {
      const p = await api.parseCampaign(post);
      setF({ ...f, name: p.name || f.name, pool: p.pool || f.pool, creator_id: p.creator_id ? String(p.creator_id) : f.creator_id,
        platforms: p.platforms?.length ? p.platforms : f.platforms, min_views: p.min_views ? String(p.min_views) : f.min_views, audience: p.audience || f.audience,
        footage_from: p.footage_from || f.footage_from, hashtags: p.required_hashtags?.length ? p.required_hashtags.join(", ") : f.hashtags,
        mention: p.must_mention?.length ? p.must_mention.join(", ") : f.mention, submit: p.submit_within_minutes ? String(p.submit_within_minutes) : f.submit,
        join_url: p.join_url || f.join_url, discord_url: p.discord_url || f.discord_url, guidelines_url: p.guidelines_url || f.guidelines_url, rules: p.rules || f.rules });
      toast(p.creator && !p.creator_id ? "info" : "ok", p.creator && !p.creator_id
        ? `${p.creator} isn't one of your streamers yet. Pick one below.` : "Filled in. Check each field, then add a short tag.");
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const save = async () => {
    const body: CampaignFields = {
      name: f.name.trim(), tag: f.tag.trim(), creator_id: f.creator_id ? Number(f.creator_id) : null, status: f.status, pool: f.pool.trim(),
      min_views: Number(f.min_views) || 0, platforms: f.platforms, audience: f.audience.trim(), footage_from: f.footage_from || null, ends_at: f.ends_at || null,
      required_hashtags: words(f.hashtags), must_mention: words(f.mention), keywords: words(f.keywords), join_url: f.join_url.trim(), discord_url: f.discord_url.trim(),
      guidelines_url: f.guidelines_url.trim(), submit_within_minutes: Number(f.submit) || null, destination_ids: f.destination_ids, rules: f.rules,
    };
    setBusy(true);
    try {
      if (campaign) await api.updateCampaign(campaign.id, body); else await api.addCampaign(body);
      toast("ok", campaign ? "Campaign saved" : "Campaign added");
      onSaved(); onClose();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} wide title={campaign ? "Edit campaign" : "Add campaign"} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn primary" onClick={save} disabled={busy || !f.name.trim() || !/^[a-z0-9-]{2,40}$/.test(f.tag)}>{busy && <span className="spinner" />}Save</button>
    </>}>
      <div className="stack">
        {!campaign && (
          <div className="field"><label htmlFor="cp-post">Paste the campaign post</label>
            <textarea id="cp-post" className="textarea" rows={8} value={post} onChange={(e) => setPost(e.target.value)} placeholder="Paste the whole post, with its rules and links" />
            <div><button className="btn" onClick={fill} disabled={busy || !post.trim()}><Wand2 size={14} />Fill in from text</button></div></div>
        )}
        {text("name", "Name")}
        <div className="row wrap" style={{ alignItems: "flex-start" }}>
          <div style={{ flex: 1, minWidth: 200 }}>{text("tag", "Tag", { maxLength: 40, placeholder: "lacy-gta" })}
            <span className="small faint">Letters, numbers and dashes. You search and tag by it.</span></div>
          <div className="field" style={{ flex: 1, minWidth: 200 }}><label htmlFor="cp-creator">Streamer</label>
            <select id="cp-creator" className="select" value={f.creator_id} onChange={(e) => setF({ ...f, creator_id: e.target.value })}>
              <option value="">Pick a streamer</option>{(creators.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
        </div>
        <div className="field"><span className="label-text">Platforms</span>
          <div className="row wrap">{PLATFORMS.map((p) => (
            <label key={p} className="row small"><input type="checkbox" checked={f.platforms.includes(p)} onChange={() => setF({ ...f, platforms: toggle(f.platforms, p) })} />{PLATFORM_LABEL[p]}</label>))}</div></div>
        <div className="row wrap">{text("pool", "Pool")}{text("min_views", "Minimum views", { type: "number", min: 0 })}{text("audience", "Audience")}</div>
        <div className="row wrap">{text("footage_from", "Footage from", { type: "date" })}{text("ends_at", "Ends", { type: "date" })}{text("submit", "Submit within (minutes)", { type: "number", min: 1 })}</div>
        <div className="row wrap">{text("hashtags", "Required hashtags", { placeholder: "#LACY" })}{text("mention", "Must mention", { placeholder: "LACY" })}{text("keywords", "Keywords in the footage", { placeholder: "gta" })}</div>
        <div className="row wrap">{text("join_url", "Join Campaign link", { type: "url" })}{text("discord_url", "Discord link", { type: "url" })}{text("guidelines_url", "Guidelines link", { type: "url" })}</div>
        <div className="field"><span className="label-text">Your pages that post for it (none picked: any page)</span>
          <div className="row wrap">{(pages.data ?? []).map((d) => (
            <label key={d.id} className="row small"><input type="checkbox" checked={f.destination_ids.includes(d.id)}
              onChange={() => setF({ ...f, destination_ids: toggle(f.destination_ids, d.id) })} />{d.display_name}</label>))}</div></div>
        <div className="field"><label htmlFor="cp-rules">Rules</label>
          <textarea id="cp-rules" className="textarea" rows={5} value={f.rules} onChange={(e) => setF({ ...f, rules: e.target.value })} /></div>
        {campaign && <label className="row small"><input type="checkbox" checked={f.status === "ended"} onChange={(e) => setF({ ...f, status: e.target.checked ? "ended" : "live" })} />This campaign has ended</label>}
      </div>
    </Modal>
  );
}
