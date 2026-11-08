import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider,
  useEdgesState, useNodesState, type Connection, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, GitFork, LayoutGrid, Trash2, Wand2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api, ApiError, PLATFORM_LABEL, type Destination, type Funnel, type Route, type Source } from "../lib/api";
import { Avatar, ConfirmModal, CreatorChip, Empty, Loading, StatusPill, Toggle, useToast } from "../components/ui";

type SrcData = { kind: "source"; item: Source; dim: boolean };
type DstData = { kind: "dest"; item: Destination; dim: boolean };

const SourceNode = memo(({ data }: NodeProps<Node<SrcData>>) => (
  <div className={`fnode${data.dim ? " dim" : ""}`}>
    <span className="strip" style={{ background: data.item.creator?.color ?? "var(--card-3)" }} />
    <Avatar url={data.item.avatar_url} platform={data.item.platform} />
    <div className="meta"><div className="name ellipsis">@{data.item.username}</div>
      <div className="sub ellipsis">{data.item.creator?.name ?? "No creator"} · {PLATFORM_LABEL[data.item.platform]}{data.item.monitoring === "paused" ? " · paused" : ""}</div></div>
    <Handle type="source" position={Position.Right} aria-label={`Drag from @${data.item.username} to a destination`} />
  </div>
));

const DestNode = memo(({ data }: NodeProps<Node<DstData>>) => (
  <div className={`fnode${data.dim ? " dim" : ""}`}>
    <Handle type="target" position={Position.Left} />
    <span className="strip" style={{ background: data.item.creator?.color ?? "var(--card-3)" }} />
    <Avatar url={data.item.avatar_url} platform={data.item.platform} />
    <div className="meta"><div className="name ellipsis">{data.item.display_name}</div>
      <div className="sub ellipsis">{PLATFORM_LABEL[data.item.platform]} · {data.item.status === "connected" ? (data.item.creator?.name ?? "No creator") : data.item.status === "draft" ? "planned" : data.item.status}</div></div>
  </div>
));

const nodeTypes = { source: SourceNode, dest: DestNode };

function defaultLayout(f: Funnel): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  const order = (c: { name: string } | null) => c?.name ?? "￿";
  const place = (items: { id: number; creator: { name: string } | null; key: string }[], x: number, prefix: string) => {
    let y = 50; let last: string | null = null;
    [...items].sort((a, b) => order(a.creator).localeCompare(order(b.creator)) || a.key.localeCompare(b.key)).forEach((it) => {
      const g = order(it.creator);
      if (last !== null && g !== last) y += 26;
      last = g; out[`${prefix}-${it.id}`] = { x, y }; y += 78;
    });
  };
  place(f.sources.map((s) => ({ id: s.id, creator: s.creator, key: s.username })), 40, "s");
  place(f.destinations.map((d) => ({ id: d.id, creator: d.creator, key: d.display_name })), 560, "d");
  return out;
}

function edgeFor(r: Route, selected: boolean): Edge {
  const color = r.blocked ? "var(--err)" : r.allow_cross_creator ? "var(--orange)" : "var(--accent)";
  return {
    id: `r-${r.id}`, source: `s-${r.source_id}`, target: `d-${r.destination_id}`, selected,
    data: { route: r },
    style: { stroke: color, strokeWidth: selected ? 3 : 2, strokeDasharray: r.enabled ? undefined : "6 5", opacity: r.enabled ? 1 : 0.55 },
    markerEnd: { type: MarkerType.ArrowClosed, color },
  };
}

function Canvas() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({ queryKey: ["funnel"], queryFn: api.funnel });
  const creators = useQuery({ queryKey: ["creators"], queryFn: api.creators });
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<SrcData | DstData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [focusCreator, setFocusCreator] = useState<number | null>(null);
  const [selRoute, setSelRoute] = useState<number | null>(null);
  const [selSource, setSelSource] = useState<number | null>(null);
  const [cross, setCross] = useState<{ source: Source; dest: Destination } | null>(null);
  const saveTimer = useRef<number | undefined>(undefined);
  const refresh = useCallback(() => ["funnel", "dashboard", "sources", "destinations"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })), [qc]);
  const err = useCallback((e: unknown) => toast("err", e instanceof Error ? e.message : String(e)), [toast]);

  // Rebuild nodes from server data, keeping on-screen positions for nodes that already exist.
  useEffect(() => {
    if (!data) return;
    const fallback = defaultLayout(data);
    setNodes((prev) => {
      const pos = new Map(prev.map((n) => [n.id, n.position]));
      const dim = (cid: number | undefined) => focusCreator !== null && cid !== focusCreator;
      return [
        ...data.sources.map((s) => ({ id: `s-${s.id}`, type: "source", position: pos.get(`s-${s.id}`) ?? data.layout[`s-${s.id}`] ?? fallback[`s-${s.id}`],
          data: { kind: "source" as const, item: s, dim: dim(s.creator?.id) } })),
        ...data.destinations.map((d) => ({ id: `d-${d.id}`, type: "dest", position: pos.get(`d-${d.id}`) ?? data.layout[`d-${d.id}`] ?? fallback[`d-${d.id}`],
          data: { kind: "dest" as const, item: d, dim: dim(d.creator?.id) } })),
      ];
    });
  }, [data, focusCreator, setNodes]);

  useEffect(() => { if (data) setEdges(data.routes.map((r) => edgeFor(r, r.id === selRoute))); }, [data, selRoute, setEdges]);

  const persistLayout = useCallback((ns: Node[]) => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      api.saveLayout(Object.fromEntries(ns.map((n) => [n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) }]))).catch(err);
    }, 400);
  }, [err]);

  const createRoute = useCallback(async (sourceId: number, destId: number, allowCross = false) => {
    try { await api.addRoute({ source_id: sourceId, destination_id: destId, allow_cross_creator: allowCross }); refresh(); }
    catch (e) {
      if (e instanceof ApiError && e.code === "cross_creator" && data) {
        const source = data.sources.find((s) => s.id === sourceId); const dest = data.destinations.find((d) => d.id === destId);
        if (source && dest) { setCross({ source, dest }); return; }
      }
      err(e);
    }
  }, [data, refresh, err]);

  const onConnect = useCallback((c: Connection) => {
    if (!c.source?.startsWith("s-") || !c.target?.startsWith("d-")) return;
    void createRoute(Number(c.source.slice(2)), Number(c.target.slice(2)));
  }, [createRoute]);

  const onEdgesDelete = useCallback(async (removed: Edge[]) => {
    try { await Promise.all(removed.map((e) => api.deleteRoute(Number(e.id.slice(2))))); setSelRoute(null); refresh(); } catch (e) { err(e); }
  }, [refresh, err]);

  const resetLayout = async () => {
    if (!data) return;
    const l = defaultLayout(data);
    setNodes((ns) => ns.map((n) => ({ ...n, position: l[n.id] ?? n.position })));
    await api.saveLayout(l).catch(err);
  };

  const autoRoute = async () => {
    try { const r = await api.autoRoute(focusCreator); toast("ok", r.created ? `Created ${r.created} route(s) matching creators` : "Every creator's sources already feed their destinations"); refresh(); }
    catch (e) { err(e); }
  };

  const route = data?.routes.find((r) => r.id === selRoute) ?? null;
  const resolved = useQuery({ queryKey: ["resolve", selSource, data?.routes.length], queryFn: () => api.resolve(selSource!), enabled: selSource !== null });

  if (isLoading || !data) return <Loading />;
  const empty = data.sources.length === 0 || data.destinations.length === 0;
  const srcName = (id: number) => data.sources.find((s) => s.id === id)?.username ?? "?";
  const dstName = (id: number) => data.destinations.find((d) => d.id === id)?.display_name ?? "?";

  return (
    <div className="funnel-wrap">
      <div className="funnel-canvas">
        {empty ? (
          <Empty icon={<GitFork size={28} />} title="Add accounts to build your funnel">
            <p className="small">You need at least one <Link to="/sources">source</Link> and one <Link to="/destinations">destination</Link>.</p>
          </Empty>
        ) : (
          <>
            <span className="col-label" style={{ left: 40 }}>Sources</span>
            <span className="col-label" style={{ left: 560 }}>Destinations</span>
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onEdgesDelete={onEdgesDelete} deleteKeyCode={["Backspace", "Delete"]}
              isValidConnection={(c) => !!c.source?.startsWith("s-") && !!c.target?.startsWith("d-")}
              onNodeDragStop={(_, __, all) => persistLayout(nodes.map((n) => all.find((a) => a.id === n.id) ?? n))}
              onEdgeClick={(_, e) => { setSelRoute(Number(e.id.slice(2))); setSelSource(null); }}
              onNodeClick={(_, n) => { if (n.id.startsWith("s-")) { setSelSource(Number(n.id.slice(2))); setSelRoute(null); } }}
              onPaneClick={() => { setSelRoute(null); setSelSource(null); }}
              fitView fitViewOptions={{ padding: 0.2, maxZoom: 1 }} minZoom={0.3} maxZoom={1.6} proOptions={{ hideAttribution: true }}
              colorMode="dark" connectionLineStyle={{ stroke: "var(--accent-hi)", strokeWidth: 2 }}>
              <Background color="#2a2a31" gap={22} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </>
        )}
      </div>

      <aside className="funnel-side" aria-label="Funnel details">
        <div className="stack">
          <button className="btn primary" onClick={autoRoute} disabled={empty}><Wand2 size={14} />Auto-route by creator</button>
          <p className="small faint">Connects every {focusCreator ? "selected creator's" : "creator's"} sources to that creator's destinations. Unassigned accounts are left alone.</p>
          <div className="field"><label htmlFor="fc">Focus creator</label>
            <select id="fc" className="select" value={focusCreator ?? ""} onChange={(e) => setFocusCreator(e.target.value ? Number(e.target.value) : null)}>
              <option value="">All creators</option>{(creators.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
          <button className="btn" onClick={resetLayout} disabled={empty}><LayoutGrid size={14} />Tidy layout</button>
        </div>

        {route && (
          <div className="card stack" style={{ background: "var(--card-2)" }}>
            <h3>Route</h3>
            <div className="row small"><strong className="ellipsis">@{srcName(route.source_id)}</strong><ArrowRight size={12} /><strong className="ellipsis">{dstName(route.destination_id)}</strong></div>
            {route.blocked && <div className="banner warn small"><AlertTriangle size={14} />The creators no longer match, so this route is paused until you confirm it.</div>}
            {route.allow_cross_creator && !route.blocked && <span className="pill orange">Mixes creators (confirmed)</span>}
            <label className="row"><Toggle label="Route enabled" checked={route.enabled} onChange={(v) => api.updateRoute(route.id, { enabled: v }).then(refresh).catch(err)} />Enabled</label>
            {route.blocked && <button className="btn sm" onClick={() => api.updateRoute(route.id, { allow_cross_creator: true }).then(refresh).catch(err)}>Allow mixing creators</button>}
            <button className="btn danger sm" onClick={() => onEdgesDelete([{ id: `r-${route.id}` } as Edge])}><Trash2 size={12} />Delete route</button>
          </div>
        )}

        {selSource !== null && (
          <div className="card stack" style={{ background: "var(--card-2)" }}>
            <h3>Clips from @{srcName(selSource)} go to</h3>
            {resolved.isLoading ? <Loading /> : (resolved.data ?? []).length === 0 ? <p className="small faint">Nowhere yet. Drag from its handle to a destination.</p> :
              (resolved.data ?? []).map((d) => <div key={d.id} className="list-row small"><span className="ellipsis">{d.display_name}</span><span className="spacer" /><StatusPill status={d.status} /></div>)}
          </div>
        )}

        <div>
          <div className="row" style={{ marginBottom: 6 }}><h3>All routes</h3><span className="faint small">{data.routes.length}</span></div>
          {data.routes.length === 0 ? <p className="small faint">Drag from the dot on a source to a destination to create a route. Select a line and press Delete to remove it.</p> :
            data.routes.map((r) => (
              <button key={r.id} className={`filter-btn${selRoute === r.id ? " on" : ""}`} onClick={() => { setSelRoute(r.id); setSelSource(null); }}>
                <span className="ellipsis" style={{ flex: 1 }}>@{srcName(r.source_id)} → {dstName(r.destination_id)}</span>
                {!r.enabled && <span className="count">off</span>}{r.blocked && <AlertTriangle size={12} color="var(--err)" />}
              </button>
            ))}
        </div>
        <div className="small faint stack" style={{ gap: 4 }}>
          <span><span style={{ color: "var(--accent)" }}>━</span> active · <span style={{ color: "var(--orange)" }}>━</span> confirmed creator mix · <span style={{ color: "var(--err)" }}>━</span> paused (creator mismatch) · ┅ disabled</span>
        </div>
      </aside>

      <ConfirmModal open={!!cross} title="Mix creators?" confirmLabel="Route anyway"
        message={cross && <div className="stack"><span>
          <strong>@{cross.source.username}</strong> is assigned to <CreatorChip creator={cross.source.creator} /> but <strong>{cross.dest.display_name}</strong> is assigned to <CreatorChip creator={cross.dest.creator} />.
        </span><span>Clips from one streamer would be posted on another streamer's page. Only do this if it's intentional.</span></div>}
        onClose={() => setCross(null)} onConfirm={() => { if (cross) void createRoute(cross.source.id, cross.dest.id, true); setCross(null); }} />
    </div>
  );
}

export default function FunnelPage() {
  return (
    <div className="page-full">
      <div className="page" style={{ paddingBottom: 14, width: "100%", maxWidth: "none" }}>
        <div className="page-head" style={{ marginBottom: 0 }}><div><h1>Account Funnel</h1>
          <p>Drag from a source account to a destination to route its clips there. One source can feed many destinations and many sources can feed one. Creators are never mixed unless you confirm it.</p></div></div>
      </div>
      <div style={{ flex: 1, minHeight: 0, borderTop: "1px solid var(--line)", display: "flex" }}>
        <ReactFlowProvider><Canvas /></ReactFlowProvider>
      </div>
    </div>
  );
}
