import { Activity, BarChart3, Clapperboard, Download, GitFork, LayoutDashboard, Settings, Upload, Users, type LucideIcon } from "lucide-react";

export interface ModuleDef {
  path: string; label: string; icon: LucideIcon; group: "Overview" | "Accounts" | "Coming next" | "";
  status: "ready" | "planned"; milestone?: number; summary?: string; scope?: string[];
}

// Single source of truth for navigation and for what is actually built.
export const MODULES: ModuleDef[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, group: "Overview", status: "ready" },
  { path: "/ready", label: "Ready to Upload", icon: Download, group: "Overview", status: "ready" },
  { path: "/activity", label: "Activity", icon: Activity, group: "Overview", status: "ready" },
  { path: "/sources", label: "Source Accounts", icon: Users, group: "Accounts", status: "ready" },
  { path: "/destinations", label: "Destinations", icon: Upload, group: "Accounts", status: "ready" },
  { path: "/funnel", label: "Account Funnel", icon: GitFork, group: "Accounts", status: "ready" },
  { path: "/editor", label: "Video Editor", icon: Clapperboard, group: "Coming next", status: "planned", milestone: 3,
    summary: "Fine-tune a clip before you download it: captions, trims, zoom and text.",
    scope: ["Bold orange/white word-synced captions, fully customizable", "Trim, split, speed, zoom and text overlays", "Undo/redo, autosave, presets"] },
  { path: "/analytics", label: "Analytics", icon: BarChart3, group: "Coming next", status: "planned", milestone: 7,
    summary: "How your uploaded clips perform across platforms, creators and pages.",
    scope: ["Views, likes, comments and shares per clip", "Which creators, lengths and styles work best", "Unavailable metrics shown as unavailable, never as zero"] },
  { path: "/settings", label: "Settings", icon: Settings, group: "", status: "ready" },
];
