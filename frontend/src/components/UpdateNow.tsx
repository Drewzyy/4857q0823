import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../lib/api";

/** One click next to the version: checks for an update and installs it as soon as it's downloaded. */
export default function UpdateNow() {
  const qc = useQueryClient();
  const [want, setWant] = useState(false);
  const { data: u } = useQuery({
    queryKey: ["app-update"], queryFn: api.appUpdate,
    refetchInterval: (q) => (want || ["checking", "downloading", "installing"].includes(q.state.data?.state ?? "") ? 1500 : 30_000),
  });
  useEffect(() => {
    if (!want || !u) return;
    if (u.state === "ready") api.installUpdate().then(() => qc.invalidateQueries({ queryKey: ["app-update"] })).catch(() => setWant(false));
    else if (["none", "error"].includes(u.state) && !u.check_requested) setWant(false);
  }, [want, u, qc]);
  if (!u?.available) return null;
  const busy = want || u.check_requested || ["checking", "downloading", "installing"].includes(u.state);
  const title = u.state === "ready" ? `Install Vyral ${u.version} now` : u.state === "downloading" ? `Downloading ${u.version}…`
    : u.state === "none" ? "Up to date. Click to check again" : u.state === "error" ? (u.error ?? "Couldn't check") : "Check for updates and install";
  return (
    <button className="btn ghost sm" aria-label="Update Vyral" title={title} disabled={busy && u.state !== "ready"}
      onClick={() => { setWant(true); if (u.state !== "ready") api.checkForUpdates().then((r) => qc.setQueryData(["app-update"], { ...r, available: true })).catch(() => setWant(false)); }}
      style={{ padding: 4, color: u.state === "ready" ? "var(--accent-hi)" : undefined }}>
      <RefreshCw size={14} style={busy ? { animation: "spin .8s linear infinite" } : undefined} />
    </button>
  );
}
