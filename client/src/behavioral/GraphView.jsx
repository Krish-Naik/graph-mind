import { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import { commColor } from './viz.js';

/**
 * mode='entities'    : one node per entity (size = total activity), optionally grouped in boxes per community.
 * mode='communities' : one node per community (size = members), edge width = cross-community links.
 * selComm / selTier fade everything else; clicking a node reports its community upward.
 */
export default function GraphView({ nodes, edges, colors, mode, colorBy = 'tier', selComm = null, selTier = null, onPickComm }) {
  const ref = useRef(null);
  const cyRef = useRef(null);
  const [tip, setTip] = useState(null);
  const [grouped, setGrouped] = useState(false);
  const [layoutKey, setLayoutKey] = useState(0);
  const [query, setQuery] = useState('');
  const [msg, setMsg] = useState('');

  const maxLog = useMemo(() => Math.max(1, ...nodes.map((n) => Math.log10(1 + (n.total || 0)))), [nodes]);

  useEffect(() => {
    if (!ref.current) return undefined;
    const maxW = Math.max(1, ...edges.map((e) => e.weight));
    const comms = mode === 'entities' && grouped ? [...new Set(nodes.map((n) => n.community))] : [];
    const els = [
      ...comms.map((c) => ({ data: { id: `grp${c}`, label: `C${c}`, isGroup: 1 } })),
      ...nodes.map((n) => ({ data: {
        id: String(n.id), raw: n, comm: mode === 'communities' ? n.id : n.community, tier: n.tier,
        color: mode === 'communities' || colorBy === 'tier' ? (colors[n.tier] || '#64748b') : commColor(n.community),
        label: mode === 'communities' ? `C${n.id}` : '',
        size: mode === 'communities' ? 18 + Math.sqrt(n.size) * 7 : 6 + 12 * (Math.log10(1 + (n.total || 0)) / maxLog),
        ...(comms.length ? { parent: `grp${n.community}` } : {}) } })),
      ...edges.map((e, i) => ({ data: { id: `e${i}`, source: String(e.source), target: String(e.target), w: e.weight } })),
    ];
    const cy = cytoscape({
      container: ref.current, elements: els, minZoom: 0.1, maxZoom: 6, wheelSensitivity: 0.3,
      style: [
        { selector: 'node[color]', style: { 'background-color': 'data(color)', width: 'data(size)', height: 'data(size)', label: 'data(label)', 'font-size': 10, 'font-weight': 700, color: '#0f172a', 'text-valign': 'center', 'border-width': 1, 'border-color': '#fff' } },
        { selector: 'node[isGroup]', style: { 'background-color': '#f1f5f9', 'background-opacity': 0.5, 'border-color': '#cbd5e1', 'border-width': 1, shape: 'round-rectangle', label: 'data(label)', 'text-valign': 'top', 'font-size': 11, color: '#475569', padding: 10 } },
        { selector: 'edge', style: { 'line-color': '#94a3b8', opacity: mode === 'communities' ? 0.6 : 0.16, width: mode === 'communities' ? `mapData(w, 0, ${maxW}, 1, 9)` : 1, 'curve-style': 'haystack' } },
        { selector: '.dim', style: { opacity: 0.07 } },
        { selector: 'edge.hl', style: { opacity: 0.55, 'line-color': '#334155' } },
        { selector: 'node.hl', style: { 'border-width': 3, 'border-color': '#0f172a' } },
        { selector: 'node.found', style: { 'border-width': 4, 'border-color': '#f59e0b', 'z-index': 99 } },
      ],
      layout: { name: 'cose', animate: false, randomize: true, numIter: 1000, nodeRepulsion: () => 9000, idealEdgeLength: () => 55, gravity: grouped ? 0.4 : 0.6, nestingFactor: 1.2 },
    });
    cy.on('tap', 'node', (ev) => { const d = ev.target.data(); const c = d.isGroup ? Number(String(d.id).slice(3)) : d.comm; if (c != null && onPickComm) onPickComm(c); });
    cy.on('mouseover', 'node', (ev) => {
      const d = ev.target.data(); if (d.isGroup) return;
      const p = ev.renderedPosition;
      setTip({ x: p.x, y: p.y, raw: d.raw });
    });
    cy.on('mouseout', 'node', () => setTip(null));
    cy.on('pan zoom', () => setTip(null));
    cyRef.current = cy;
    return () => { cyRef.current = null; cy.destroy(); };
  }, [nodes, edges, mode, grouped, layoutKey]); // eslint-disable-line

  // colours + selection fading, without rebuilding the layout
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !cy.nodes) return;
    const dimmed = (comm, tier) => (selComm != null ? comm !== selComm : selTier ? tier !== selTier : false);
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const d = n.data(); if (d.isGroup) { n.toggleClass('dim', selComm != null && d.id !== `grp${selComm}`); return; }
        n.data('color', mode === 'communities' || colorBy === 'tier' ? (colors[d.tier] || '#64748b') : commColor(d.comm));
        n.toggleClass('dim', dimmed(d.comm, d.tier));
        n.toggleClass('hl', selComm != null && d.comm === selComm);
      });
      cy.edges().forEach((e) => {
        const a = e.source().data(), b = e.target().data();
        const off = dimmed(a.comm, a.tier) || dimmed(b.comm, b.tier);
        e.toggleClass('dim', off); e.toggleClass('hl', selComm != null && !off);
      });
    });
  }, [nodes, edges, mode, grouped, layoutKey, colors, colorBy, selComm, selTier]);

  const find = (e) => {
    e.preventDefault();
    const cy = cyRef.current; if (!cy || !cy.getElementById) return;
    const n = cy.getElementById(query.trim());
    if (!n || n.empty()) { setMsg(`No entity "${query}" in this graph (it may have been sampled out or have no edges).`); return; }
    setMsg(''); cy.nodes().removeClass('found'); n.addClass('found');
    cy.animate({ center: { eles: n }, zoom: 2.5 }, { duration: 350 });
    if (onPickComm) onPickComm(n.data('comm'));
  };

  return (
    <div>
      <div className="toolbar">
        {mode === 'entities' && (
          <div className="seg">
            <button className={!grouped ? 'on' : ''} onClick={() => setGrouped(false)}>force layout</button>
            <button className={grouped ? 'on' : ''} onClick={() => setGrouped(true)}>boxes per community</button>
          </div>
        )}
        <button className="ghost" onClick={() => cyRef.current?.fit?.(undefined, 30)}>fit to screen</button>
        <button className="ghost" onClick={() => setLayoutKey((k) => k + 1)}>re-layout</button>
        {mode === 'entities' && (
          <form onSubmit={find} className="row" style={{ gap: 6 }}>
            <input type="text" placeholder="find entity id…" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button type="submit" className="ghost">find</button>
          </form>
        )}
      </div>
      {msg && <div className="alert warn">{msg}</div>}
      <div className="graphwrap">
        <div ref={ref} className="graph" />
        {tip && (
          <div className="graphtip vtip" style={{ left: tip.x, top: tip.y }}>
            {mode === 'communities'
              ? <><b>Community {tip.raw.id}</b><div>{tip.raw.size} members</div><div>{tip.raw.tier}</div></>
              : <><b>Entity {tip.raw.id}</b><div>community {tip.raw.community}</div><div>{tip.raw.tier}</div><div>total activity {tip.raw.total}</div></>}
          </div>
        )}
      </div>
      <div className="muted small" style={{ marginTop: 6 }}>
        Scroll to zoom, drag to pan, hover for details, click a node to select its community. Dot size = total activity. Lines = similarity above the threshold.
      </div>
    </div>
  );
}