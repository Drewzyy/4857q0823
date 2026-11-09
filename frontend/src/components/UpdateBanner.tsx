import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpCircle } from "lucide-react";
import { api } from "../lib/api";
import { useToast } from "./ui";

/** Shown at the top of every page once a new version has downloaded. */
export default function UpdateBanner() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: u } = useQuery({
    queryKey: ["app-update"], queryFn: api.appUpdate,
    refetchInterval: (q) => (["checking", "downloading", "installing"].includes(q.state.data?.state ?? "") || q.state.data?.check_requested ? 2000 : 30_000),
  });
  if (!u?.available || (u.state !== "ready" && u.state !== "installing")) return null;
  return (
    <div className="update-banner" role="status">
      <ArrowUpCircle size={18} />
      <span><strong>Vyral {u.version}</strong> is ready.{u.state === "installing" ? " Installing and restarting…" : " It installs by itself when you're not using Vyral, or restart now."}</span>
      <span className="spacer" />
      {u.state === "ready" && (
        <button className="btn primary sm" onClick={async () => {
          try { await api.installUpdate(); qc.invalidateQueries({ queryKey: ["app-update"] }); } catch (e) { toast("err", e instanceof Error ? e.message : String(e)); }
        }}>Restart to update</button>
      )}
      {u.state === "installing" && <span className="spinner" />}
    </div>
  );
}
