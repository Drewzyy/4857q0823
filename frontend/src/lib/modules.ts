import { Activity, BarChart3, Bot, Clapperboard, Download, GitFork, LayoutDashboard, Settings, Upload, Users, type LucideIcon } from "lucide-react";

export interface ModuleDef {
  path: string; label: string; icon: LucideIcon; group: "Overview" | "Accounts" | "Coming next" | "";
  status: "ready" | "planned"; milestone?: number; summary?: string; scope?: string[];
}

// Single source of truth for navigation and for what is actually built.
export const MODULES: ModuleDef[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, group: "Overview", status: "ready" },
  { path: "/agents", label: "Agents", icon: Bot, group: "Overview", status: "ready" },
  { path: "/ready", label: "Ready to Upload", icon: Download, group: "Overview", status: "ready" },
  { path: "/editor", label: "Video Editor", icon: Clapperboard, group: "Overview", status: "ready" },
  { path: "/activity", label: "Activity", icon: Activity, group: "Overview", status: "ready" },
  { path: "/analytics", label: "Analytics", icon: BarChart3, group: "Overview", status: "ready" },
  { path: "/sources", label: "Source Accounts", icon: Users, group: "Accounts", status: "ready" },
  { path: "/destinations", label: "Destinations", icon: Upload, group: "Accounts", status: "ready" },
  { path: "/funnel", label: "Account Funnel", icon: GitFork, group: "Accounts", status: "ready" },

  { path: "/settings", label: "Settings", icon: Settings, group: "", status: "ready" },
];
