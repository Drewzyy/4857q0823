import {
  BarChart3, Brain, Clapperboard, Compass, GitFork, LayoutDashboard, Library, Send, Settings, Sparkles, Upload, Users,
  type LucideIcon,
} from "lucide-react";

export interface ModuleDef {
  path: string; label: string; icon: LucideIcon; group: "Overview" | "Accounts" | "Create" | "Distribute" | "Improve" | "";
  status: "ready" | "planned"; milestone?: number; summary?: string; scope?: string[];
}

// Single source of truth for navigation and for what is actually built.
export const MODULES: ModuleDef[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, group: "Overview", status: "ready" },
  { path: "/discovery", label: "Content Discovery", icon: Compass, group: "Overview", status: "planned", milestone: 5,
    summary: "A feed of reference clips from your source accounts with their metrics, filters and AI/matching status.",
    scope: ["Reference video import by URL (TikTok oEmbed) and file", "Video lists + metrics for TikTok accounts you authorize", "Filters by creator, account, views, engagement, duration, date, AI score", "Bookmarks, tags, remove"] },
  { path: "/sources", label: "Source Accounts", icon: Users, group: "Accounts", status: "ready" },
  { path: "/destinations", label: "Destination Accounts", icon: Upload, group: "Accounts", status: "ready" },
  { path: "/funnel", label: "Account Funnel", icon: GitFork, group: "Accounts", status: "ready" },
  { path: "/library", label: "Content Library", icon: Library, group: "Create", status: "planned", milestone: 2,
    summary: "Your imported VODs and clips, stored once and deduplicated by content hash.",
    scope: ["Drag-and-drop video import", "FFmpeg metadata, thumbnails and previews", "Local transcription with word timestamps", "Storage usage and cleanup"] },
  { path: "/clipper", label: "AI Clipper", icon: Sparkles, group: "Create", status: "planned", milestone: 4,
    summary: "Finds the original VOD moment behind a viral clip and proposes new clip candidates from long-form footage.",
    scope: ["Transcript + audio fingerprint + visual matching with confidence scores", "Side-by-side reference vs VOD with manual timestamp correction", "Moment detection and ranked clip candidates", "Titles and hooks grounded in the transcript"] },
  { path: "/editor", label: "Video Editor", icon: Clapperboard, group: "Create", status: "planned", milestone: 3,
    summary: "Multi-track 9:16 editor with blurred-background framing and word-synced captions.",
    scope: ["Sharp centered video over a blurred, darkened copy", "Bold orange/white word-highlight captions, fully customizable", "Timeline: trim, split, speed, keyframes, text, audio", "Undo/redo, autosave, presets, H.264/H.265 export"] },
  { path: "/publishing", label: "Publishing Queue", icon: Send, group: "Distribute", status: "planned", milestone: 6,
    summary: "Review, approve and schedule clips to the destinations your funnel routes them to.",
    scope: ["Approval queue (nothing posts without your approval)", "Per-platform captions, scheduling, retries", "Duplicate-upload prevention and full history"] },
  { path: "/analytics", label: "Analytics", icon: BarChart3, group: "Improve", status: "planned", milestone: 7,
    summary: "Performance across platforms, creators, accounts, styles and durations.",
    scope: ["Views, likes, comments, shares, retention where the platform provides it", "Predicted vs actual performance", "Unavailable metrics shown as unavailable, never as zero"] },
  { path: "/learning", label: "AI Learning", icon: Brain, group: "Improve", status: "planned", milestone: 7,
    summary: "The research agent: learns from approvals, edits and results to improve future recommendations.",
    scope: ["Training dataset built from day one", "Pattern reports (hooks, lengths, emotions, styles)", "Versioned models with evaluation and rollback"] },
  { path: "/settings", label: "Settings", icon: Settings, group: "", status: "ready" },
];
