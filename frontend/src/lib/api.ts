// Typed client for the local backend. Every request carries the per-launch app token.

export type Platform = "tiktok" | "youtube" | "instagram" | "facebook" | "twitch";

export interface Creator { id: number; name: string; color: string; notes: string; vod_channels: string[]; clip_permission: boolean; sources?: number; destinations?: number }
export interface Folder { id: number; name: string; sources?: number }

export interface Source {
  id: number; platform: Platform; username: string; display_name: string; profile_url: string; avatar_url: string | null;
  monitoring: "active" | "paused"; notes: string; creator: Creator | null; creators: Creator[]; folder: Folder | null;
  last_synced_at: string | null; next_check_at: string | null;
  last_error: string | null; watching_supported: boolean; baseline_done: boolean; created_at: string;
  route_count: number; videos_discovered: number | null; videos_analyzed: number | null;
}

export type FontKey = "montserrat" | "anton" | "bebas" | "poppins";
export interface TextStyle { enabled: boolean; font: FontKey; size: number; color: string; outline_color: string; outline: number; all_caps: boolean; y_percent: number }
export interface Overlay { title: TextStyle & { duration: number }; captions: TextStyle & { words_per_caption: number } }
export interface DestinationSettings {
  overlay: Overlay;
  default_caption: string; hashtags: string[];
  format: { aspect: "9:16" | "16:9" | "1:1"; resolution: string; fps: number; codec: "h264" | "h265"; bitrate_mbps: number };
}
export interface Destination {
  id: number; platform: Platform; external_id: string | null; handle: string; display_name: string; avatar_url: string | null;
  creator: Creator | null; settings: DestinationSettings; enabled: boolean;
  status: "manual"; route_count: number; created_at: string;
}
export interface Route { id: number; source_id: number; destination_id: number; enabled: boolean; allow_cross_creator: boolean; blocked: boolean }
export interface Funnel { sources: Source[]; destinations: Destination[]; routes: Route[]; layout: Record<string, { x: number; y: number }> }

export interface Job { id: number; kind: string; status: string; attempts: number; max_attempts: number; error: string | null; created_at: string; finished_at: string | null }

export interface Dashboard {
  accounts: { sources_total: number; sources_monitoring: number; destinations_total: number; creators: number; routes: number };
  pipeline: { posts_detected: number; in_progress: number; needs_attention: number; ready_to_upload: number; uploaded: number; clips_made: number };
  monitoring: { enabled: boolean; interval_minutes: number; watching: number; last_check: string | null; errors: number; retention_days: number };
  jobs: { by_status: Record<string, number>; recent: Job[] };
  storage: { data_dir: string; used_bytes: number; disk_free_bytes: number; disk_total_bytes: number };
  secret_backend: string;
}

export interface AppSettings {
  captions: { accuracy: "fast" | "accurate" | "best"; language: string };
  monitoring: { enabled: boolean; interval_minutes: number; streams_to_search: number; max_clip_seconds: number; twitch_min_views: number; twitch_clips_per_check: number };
  storage: { retention_days: number };
  processing: { max_concurrent_jobs: number };
  intake: { clipboard: boolean };
}
export interface RefPost {
  id: number; platform: string; url: string; title: string; thumbnail_url: string | null; posted_at: string | null;
  status: "new" | "processing" | "ready" | "no_match" | "needs_setup" | "failed" | "baseline" | "duplicate"; status_detail: string;
  source: { id: number; username: string } | null; creator: { id: number; name: string; color: string } | null;
  vod_url: string | null; vod_start: number | null; vod_end: number | null; match_confidence: number | null;
  views: number | null; likes: number | null; created_at: string; updated_at: string;
}
export interface ClipOutputT {
  id: number; platform: Platform; title: string; description: string; status: "ready" | "uploaded" | "expired";
  destination: { id: number; display_name: string; handle: string } | null;
  width: number | null; height: number | null; fps: number | null; size_bytes: number | null; available: boolean; uploaded_at: string | null;
  video_title: string; overlay: Overlay; post_url: string | null; render_state: "ready" | "rendering" | "failed"; render_error: string | null; version: string | null;
}
export interface ClipT {
  id: number; title: string; status: string; created_at: string; expires_at: string;
  creator: { id: number; name: string; color: string } | null; vod_url: string | null; vod_start: number | null; vod_end: number | null;
  stream_date: string | null; captions_text: string; has_captions: boolean; captions_note: string; editable: boolean;
  reference: RefPost | null; outputs: ClipOutputT[];
}
export interface TextOverlayT { text: string; start: number; end: number; y_percent: number; size: number; color: string; font: FontKey; all_caps: boolean; outline: number }
export interface ClipEditT { start: number; end: number; video_height: number; zoom: number; pan_x: number; pan_y: number; speed: number; texts: TextOverlayT[] }
export interface EditorData {
  id: number; title: string; section_duration: number; original_start: number; original_duration: number;
  edit: ClipEditT; words: { start: number; end: number; text: string }[]; outputs: ClipOutputT[];
}
export interface DiscordInbox { configured: boolean; channel_id: string | null; channel_name: string | null; server: string | null; bot: string | null; last_error: string | null; last_checked: number | null; last_unrecognized: string | null }
export interface NotifyState { configured: boolean; webhook_hint: string | null; on_new_post: boolean; on_clip_ready: boolean; on_problem: boolean }

export interface AppUpdate {
  available: boolean; state: "idle" | "checking" | "none" | "downloading" | "ready" | "installing" | "error";
  current: string; version: string | null; notes: string; error: string | null; progress: number | null; checked_at: string | null;
  check_requested: boolean; install_requested: boolean; busy: boolean;
}

export interface Totals { views: number | null; likes: number | null; comments: number | null; shares: number | null; engagement_rate: number | null; avg_views: number | null }
export interface GroupRow extends Totals { key: string | number | null; label: string; posts: number; tracked: number }
export interface Analytics {
  range_days: number; clips_made: number; uploaded: number; tracked: number; totals: Totals;
  untracked: { output_id: number; title: string; platform: Platform; has_link: boolean }[];
  by_platform: GroupRow[]; by_creator: GroupRow[]; by_destination: GroupRow[]; by_length: GroupRow[];
  top: { output_id: number; title: string; platform: Platform; post_url: string | null; destination: string | null; duration: number | null;
    uploaded_at: string; views: number | null; likes: number | null; comments: number | null; shares: number | null; updated: string }[];
  timeline: { day: string; posts: number; views: number }[];
}

export interface Health { ok: boolean; version: string; secret_backend: string; worker_running: boolean; desktop_mode: boolean; ffmpeg: boolean }
export interface AuditEntry { id: number; ts: string; action: string; entity: string; entity_id: string; details: Record<string, unknown> }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

function token(): string {
  const meta = document.querySelector('meta[name="clippr-token"]') as HTMLMetaElement | null;
  return meta?.content || (import.meta.env.VITE_CLIPPR_TOKEN as string | undefined) || "";
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Clippr-Token": token() };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "offline", "Can't reach the Vyral background service. It may be restarting.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.error?.code ?? "error", data?.error?.message ?? `Request failed (${res.status})`);
  return data as T;
}

const qs = (p: Record<string, string | number | undefined | null>) => {
  const e = Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? "?" + new URLSearchParams(e.map(([k, v]) => [k, String(v)])).toString() : "";
};

export const api = {
  health: () => request<Health>("GET", "/health"),
  dashboard: () => request<Dashboard>("GET", "/dashboard"),
  creators: () => request<Creator[]>("GET", "/creators"),
  createCreatorFull: (b: { name: string; color?: string; vod_channels: string[]; clip_permission: boolean }) => request<Creator>("POST", "/creators", b),
  updateCreator: (id: number, b: Partial<Creator>) => request<Creator>("PATCH", `/creators/${id}`, b),
  deleteCreator: (id: number) => request<void>("DELETE", `/creators/${id}`),
  folders: () => request<Folder[]>("GET", "/folders"),
  createFolder: (name: string) => request<Folder>("POST", "/folders", { name }),
  deleteFolder: (id: number) => request<void>("DELETE", `/folders/${id}`),
  sources: (f: { q?: string; creator_id?: number | null; folder_id?: number | null; monitoring?: string; platform?: string } = {}) =>
    request<Source[]>("GET", "/sources" + qs(f)),
  addSource: (b: { input: string; platform: Platform; creator_ids?: number[]; folder_id?: number | null }) => request<Source>("POST", "/sources", b),
  updateSource: (id: number, b: Partial<{ creator_id: number | null; creator_ids: number[]; folder_id: number | null; monitoring: string; notes: string }>) =>
    request<Source>("PATCH", `/sources/${id}`, b),
  deleteSource: (id: number) => request<void>("DELETE", `/sources/${id}`),
  bulkSources: (b: { ids: number[]; action: "pause" | "resume" | "delete" | "assign"; creator_id?: number | null; folder_id?: number | null }) =>
    request<{ updated: number }>("POST", "/sources/bulk", b),
  importSourcesFile: (file: File) => { const fd = new FormData(); fd.append("file", file); return request<ImportResult>("POST", "/sources/import", fd); },
  importSourcesText: (b: { text: string; platform: Platform; creator_id?: number | null; folder_id?: number | null }) =>
    request<ImportResult>("POST", "/sources/import-text", b),
  destinations: () => request<Destination[]>("GET", "/destinations"),
  addDestination: (b: { platform: Platform; display_name: string; handle?: string; creator_id?: number | null }) => request<Destination>("POST", "/destinations", b),
  updateDestination: (id: number, b: Partial<{ display_name: string; handle: string; creator_id: number | null; enabled: boolean; settings: Partial<DestinationSettings> }>) =>
    request<Destination>("PATCH", `/destinations/${id}`, b),
  deleteDestination: (id: number) => request<void>("DELETE", `/destinations/${id}`),
  funnel: () => request<Funnel>("GET", "/funnel"),
  addRoute: (b: { source_id: number; destination_id: number; allow_cross_creator?: boolean }) => request<Route>("POST", "/funnel/routes", b),
  updateRoute: (id: number, b: Partial<{ enabled: boolean; allow_cross_creator: boolean }>) => request<Route>("PATCH", `/funnel/routes/${id}`, b),
  deleteRoute: (id: number) => request<void>("DELETE", `/funnel/routes/${id}`),
  autoRoute: (creator_id?: number | null) => request<{ created: number }>("POST", "/funnel/auto-route", { creator_id: creator_id ?? null }),
  saveLayout: (positions: Record<string, { x: number; y: number }>) => request<{ saved: number }>("PUT", "/funnel/layout", { positions }),
  resolve: (sourceId: number) => request<(Destination & { route_id: number })[]>("GET", `/funnel/resolve/${sourceId}`),
  settings: () => request<AppSettings>("GET", "/settings"),
  saveSettings: (b: Partial<{ [K in keyof AppSettings]: Partial<AppSettings[K]> }>) => request<AppSettings>("PUT", "/settings", b),
  audit: () => request<AuditEntry[]>("GET", "/audit"),
  clips: (status: "ready" | "uploaded" | "expired" | "all") => request<ClipT[]>("GET", `/clips?status=${status}`),
  updateOutput: (id: number, b: Partial<{ title: string; description: string; status: "ready" | "uploaded" }>) => request<ClipOutputT>("PATCH", `/outputs/${id}`, b),
  saveOutput: (id: number) => request<{ path: string }>("POST", `/outputs/${id}/save`),
  deleteClip: (id: number) => request<void>("DELETE", `/clips/${id}`),
  mediaUrl: (id: number, download = false, version?: string | null) =>
    `/api/media/outputs/${id}?t=${encodeURIComponent(token())}${download ? "&download=true" : ""}${version ? `&v=${encodeURIComponent(version)}` : ""}`,
  editVideoText: (id: number, b: { video_title?: string; overlay?: Partial<Overlay>; apply_style_to_all?: boolean }) => request<ClipOutputT>("PATCH", `/outputs/${id}/video`, b),
  editCaptions: (clipId: number, text: string) => request<{ captions_text: string; rendering: number }>("PATCH", `/clips/${clipId}/captions`, { text }),
  editor: (clipId: number) => request<EditorData>("GET", `/clips/${clipId}/editor`),
  saveEdit: (clipId: number, e: ClipEditT) => request<{ rendering: number }>("PUT", `/clips/${clipId}/edit`, e),
  sourceUrl: (clipId: number) => `/api/media/clips/${clipId}/source?t=${encodeURIComponent(token())}`,
  references: () => request<RefPost[]>("GET", "/references"),
  intake: (urls: string[]) => request<{ queued: number; ignored: number }>("POST", "/intake", { urls }),
  addReference: (b: { url: string; creator_id?: number | null; source_id?: number | null }) => request<{ id: number }>("POST", "/references", b),
  stopReference: (id: number) => request<RefPost>("POST", `/references/${id}/stop`),
  retryReference: (id: number, vod_url?: string) => request<RefPost>("POST", `/references/${id}/retry`, { vod_url: vod_url || null }),
  analytics: (f: { days: number; platform?: string; creator_id?: number | null }) => request<Analytics>("GET", "/analytics" + qs(f)),
  setPostLink: (id: number, post_url: string) => request<{ post_url: string; auto: boolean }>("PUT", `/outputs/${id}/post`, { post_url }),
  addMetrics: (id: number, b: { views?: number | null; likes?: number | null; comments?: number | null; shares?: number | null }) =>
    request<{ ok: boolean }>("POST", `/outputs/${id}/metrics`, b),
  appUpdate: () => request<AppUpdate>("GET", "/app-update"),
  checkForUpdates: () => request<AppUpdate>("POST", "/app-update/check"),
  installUpdate: () => request<AppUpdate>("POST", "/app-update/install"),
  checkSource: (id: number) => request<{ queued: boolean }>("POST", `/sources/${id}/check`),
  notifications: () => request<NotifyState>("GET", "/notifications"),
  saveNotifications: (b: Partial<{ webhook_url: string; on_new_post: boolean; on_clip_ready: boolean; on_problem: boolean }>) => request<NotifyState>("PUT", "/notifications", b),
  discordInbox: () => request<DiscordInbox>("GET", "/discord-inbox"),
  discordInboxChannels: () => request<{ id: string; name: string; server: string }[]>("GET", "/discord-inbox/channels"),
  setDiscordInbox: (b: { token?: string; channel_id?: string }) => request<DiscordInbox>("PUT", "/discord-inbox", b),
  removeDiscordInbox: () => request<void>("DELETE", "/discord-inbox"),
  removeWebhook: () => request<void>("DELETE", "/notifications/webhook"),
  testNotification: () => request<{ sent: boolean }>("POST", "/notifications/test"),
};

export interface ImportResult { added: number; skipped_duplicates: number; errors: { line: number; input: string; message: string }[] }

export const PLATFORM_LABEL: Record<string, string> = {
  tiktok: "TikTok", youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", twitch: "Twitch", kick: "Kick",
};
