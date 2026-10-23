import { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import { alignColors, layoutClusters, modularityStrength, paletteColor } from './viz.js';
import { api } from '../api.js';
import './behavioral.css';

const ALGO_ORDER = ['louvain', 'leiden', 'lpa'];
const ALGO_LABELS = { louvain: 'Louvain', leiden: 'Leiden', lpa: 'Label Propagation' };
const fmt = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d));

/** One partition drawn as a network: dots = entities, lines = similarity edges, colour = community. */
function PartitionGraph({ nodes, edges, membership, colorOf, positions, height = 460, selComm, onPick, nodeScale = 1 }) {
  const ref = useRef(null);
  const cyRef = useRef(null);
  const [tip, setTip] = useState(null);

  const maxLog = useMemo(() => Math.max(1, ...nodes.map((n) => Math.log10(1 + (n.total || 0)))), [nodes]);
  const index = useMemo(() => new Map(nodes.map((n, i) => [String(n.id), i])), [nodes]);

  useEffect(() => {
    if (!ref.current) return undefined;
    const els = [
      ...nodes.map((n, i) => ({
        data: {
          id: String(n.id), comm: membership[i], color: paletteColor(colorOf[membership[i]] ?? 0), raw: n,
          size: (5 + 9 * (Math.log10(1 + (n.total || 0)) / maxLog)) * nodeScale,
        },
      })),
      ...edges.map((e, i) => {
        const a = membership[index.get(String(e.source))];
        const b = membership[index.get(String(e.target))];
        return { data: { id: `e${i}`, source: String(e.source), target: String(e.target), inter: a !== b ? 1 : 0 } };
      }),
    ];
    const cy = cytoscape({
      container: ref.current, elements: els, minZoom: 0.15, maxZoom: 8, wheelSensitivity: 0.3,
      style: [
        { selector: 'node', style: { 'background-color': 'data(color)', width: 'data(size)', height: 'data(size)', 'border-width': 1, 'border-color': '#fff' } },
        { selector: 'edge', style: { 'line-color': '#94a3b8', width: 1, opacity: 0.18, 'curve-style': 'haystack' } },
        { selector: 'edge[inter = 1]', style: { opacity: 0.07, 'line-style': 'dashed' } },
        { selector: '.dim', style: { opacity: 0.06 } },
        { selector: 'node.hl', style: { 'border-width': 2.5, 'border-color': '#0f172a' } },
        { selector: 'edge.hl', style: { opacity: 0.55, 'line-color': '#334155' } },
      ],
      layout: positions
        ? { name: 'preset', positions: (n) => positions.get(n.id()) || { x: 0, y: 0 }, fit: true, padding: 24 }
        : { name: 'cose', animate: false, randomize: true, numIter: 800, nodeRepulsion: () => 9000, idealEdgeLength: () => 45, gravity: 0.7, fit: true, padding: 24 },
    });
    cy.on('tap', 'node', (ev) => { const c = ev.target.data('comm'); if (onPick) onPick(c); });
    cy.on('tap', (ev) => { if (ev.target === cy && onPick) onPick(null); });
    cy.on('mouseover', 'node', (ev) => { const p = ev.renderedPosition; setTip({ x: p.x, y: p.y, raw: ev.target.data('raw'), comm: ev.target.data('comm') }); });
    cy.on('mouseout', 'node', () => setTip(null));
    cy.on('pan zoom', () => setTip(null));
    cyRef.current = cy;
    return () => { cyRef.current = null; cy.destroy(); };
  }, [nodes, edges, membership, colorOf, positions]); // eslint-disable-line

  // highlight / fade without rebuilding the layout
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !cy.batch) return;
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const on = selComm != null && n.data('comm') === selComm;
        n.toggleClass('dim', selComm != null && !on);
        n.toggleClass('hl', on);
      });
      cy.edges().forEach((e) => {
        const a = e.source().data('comm'), b = e.target().data('comm');
        const off = selComm != null && (a !== selComm || b !== selComm);
        e.toggleClass('dim', off);
        e.toggleClass('hl', selComm != null && !off);
      });
    });
  }, [selComm, nodes, edges, membership, colorOf, positions]);

  return (
    <div className="graphwrap">
      <div ref={ref} className="cg-canvas" style={{ height }} />
      {tip && (
        <div className="graphtip vtip" style={{ left: tip.x, top: tip.y }}>
          <b>Entity {tip.raw.id}</b><div>community {tip.comm}</div><div>total activity {tip.raw.total}</div>
        </div>
      )}
    </div>
  );
}

function StatChips({ p }) {
  const q = modularityStrength(p.modularity);
  return (
    <div className="cg-chips">
      <span className="cg-chip"><b>{p.num_communities}</b> communities</span>
      <span className="cg-chip" title="Modularity Q: how much denser the links inside communities are than chance">
        Q = <b>{fmt(p.modularity)}</b> <i style={{ color: q.color }}>{q.label}</i>
      </span>
      <span className="cg-chip" title="Agreement with the label column (needs a label)">NMI = <b>{p.nmi == null ? '—' : fmt(p.nmi)}</b></span>
      {p.backend && <span className="cg-chip muted" title="Implementation used">{p.backend}</span>}
    </div>
  );
}

/**
 * Community-detection graphs for every algorithm of one run.
 *   result : the job result from the engine (needs graph.nodes/edges; partitions for all algorithms)
 */
export default function CommunityGraphs({ result, height = 520 }) {
  const nodes = result.graph.nodes;
  const edges = result.graph.edges;

  // all partitions; older saved results only carry the primary one (node.community)
  const partitions = useMemo(() => {
    if (result.partitions && Object.keys(result.partitions).length) return result.partitions;
    const key = Object.keys(ALGO_LABELS).find((k) => ALGO_LABELS[k] === result.summary?.primary_algorithm) || 'louvain';
    const b = (result.benchmark || []).find((x) => x.key === key) || {};
    return { [key]: { name: ALGO_LABELS[key], num_communities: result.summary?.communities, modularity: b.modularity, nmi: b.nmi, membership: nodes.map((n) => n.community) } };
  }, [result, nodes]);

  const keys = ALGO_ORDER.filter((k) => partitions[k]).concat(Object.keys(partitions).filter((k) => !ALGO_ORDER.includes(k)));
  const failed = (result.benchmark || []).filter((b) => b.error);
  const primaryKey = Object.keys(ALGO_LABELS).find((k) => ALGO_LABELS[k] === result.summary?.primary_algorithm) || keys[0];
  const refKey = partitions[primaryKey] ? primaryKey : keys[0];

  const [view, setView] = useState(keys.length > 1 ? 'compare' : 'single');
  const [algo, setAlgo] = useState(refKey);
  const [layout, setLayout] = useState('clustered');
  const [sel, setSel] = useState(null);

  // colours aligned to the reference algorithm so the same group of entities keeps its colour
  const colors = useMemo(() => {
    const out = {};
    keys.forEach((k) => { out[k] = alignColors(k === refKey ? null : partitions[refKey].membership, partitions[k].membership).colorOf; });
    return out;
  }, [partitions, refKey]); // eslint-disable-line

  // force-directed: computed ONCE and shared, so the three graphs are directly comparable (and it only costs one layout run)
  const forcePos = useMemo(() => {
    if (layout !== 'force') return null;
    const m = new Map();
    try {
      const cy = cytoscape({
        headless: true, styleEnabled: false,
        elements: [...nodes.map((n) => ({ data: { id: String(n.id) } })),
          ...edges.map((e, i) => ({ data: { id: `e${i}`, source: String(e.source), target: String(e.target) } }))],
        layout: { name: 'cose', animate: false, randomize: true, numIter: 250, nodeRepulsion: () => 9000, idealEdgeLength: () => 45, gravity: 0.7 },
      });
      cy.nodes().forEach((n) => m.set(n.id(), { ...n.position() }));
      cy.destroy();
    } catch { /* falls back to the clustered layout below */ }
    return m.size ? m : null;
  }, [layout, nodes, edges]);

  // clustered layout: one per partition (cheap, ~30 ms), only when it is the one being shown
  const clusterPos = useMemo(() => {
    if (layout === 'force' && forcePos) return {};
    const out = {};
    keys.forEach((k) => { out[k] = layoutClusters(nodes, partitions[k].membership, edges); });
    return out;
  }, [layout, forcePos, partitions, nodes, edges]); // eslint-disable-line
  const positionsFor = (k) => (layout === 'force' && forcePos ? forcePos : clusterPos[k]);

  const sizes = (k) => {
    const s = new Map();
    partitions[k].membership.forEach((c) => s.set(c, (s.get(c) || 0) + 1));
    return [...s.entries()].sort((a, b) => b[1] - a[1]);
  };

  const Legend = ({ k }) => (
    <div className="cg-legend">
      {sizes(k).slice(0, 24).map(([c, n]) => (
        <button key={c} type="button" className={`cg-leg ${sel?.k === k && sel.c === c ? 'on' : ''}`}
          onClick={() => setSel((cur) => (cur?.k === k && cur.c === c ? null : { k, c }))}>
          <i style={{ background: paletteColor(colors[k][c] ?? 0) }} />C{c}<span>{n}</span>
        </button>
      ))}
      {sizes(k).length > 24 && <span className="muted small">+{sizes(k).length - 24} smaller</span>}
    </div>
  );

  const graph = (k, h, scale = 1) => (
    <PartitionGraph nodes={nodes} edges={edges} membership={partitions[k].membership} colorOf={colors[k]}
      positions={positionsFor(k)} height={h} nodeScale={scale}
      selComm={sel && sel.k === k ? sel.c : null} onPick={(c) => setSel(c == null ? null : { k, c })} />
  );

  return (
    <div>
      {failed.map((f) => (
        <div key={f.key} className="alert warn"><b>{f.algorithm}</b> could not run: {f.error}</div>
      ))}
      <div className="toolbar">
        <div className="seg">
          <button className={view === 'compare' ? 'on' : ''} onClick={() => setView('compare')} disabled={keys.length < 2}>Side by side</button>
          <button className={view === 'single' ? 'on' : ''} onClick={() => setView('single')}>One algorithm</button>
        </div>
        {view === 'single' && (
          <div className="seg">{keys.map((k) => <button key={k} className={algo === k ? 'on' : ''} onClick={() => { setAlgo(k); setSel(null); }}>{partitions[k].name}</button>)}</div>
        )}
        <div className="seg" title="How the dots are positioned">
          <button className={layout === 'clustered' ? 'on' : ''} onClick={() => setLayout('clustered')}>Clustered by community</button>
          <button className={layout === 'force' ? 'on' : ''} onClick={() => setLayout('force')}>Force-directed</button>
        </div>
        {sel && <span className="selchip">{partitions[sel.k].name} · community {sel.c}<button onClick={() => setSel(null)}>clear</button></span>}
      </div>

      {view === 'single' || keys.length < 2 ? (
        <div className="cg-single">
          <div className="cg-title" style={{ borderColor: paletteColor(0) }}>{partitions[algo].name}</div>
          <StatChips p={partitions[algo]} />
          {graph(algo, height)}
          <Legend k={algo} />
        </div>
      ) : (
        <div className="cg-grid" style={{ gridTemplateColumns: `repeat(${Math.min(keys.length, 3)}, minmax(0, 1fr))` }}>
          {keys.map((k) => (
            <div key={k} className="cg-panel">
              <div className="cg-title">{partitions[k].name}</div>
              <StatChips p={partitions[k]} />
              {graph(k, 340, 0.85)}
              <Legend k={k} />
            </div>
          ))}
        </div>
      )}
      <div className="muted small" style={{ marginTop: 8 }}>
        Every dot is an entity (size = total activity); a line joins two entities whose behavior is similar enough. Colour = the community the
        algorithm put it in. Colours are matched across algorithms, so a group that keeps its colour was found by more than one of them.
        Click a dot or a legend chip to isolate a community; scroll to zoom and drag to pan.
        {Object.keys(partitions).length < 2 && ' Re-run the analysis with several algorithms ticked to compare them here.'}
        {!result.partitions && ' (This run was saved before multi-algorithm graphs existed: only the main algorithm is available. Re-run to see all of them.)'}
      </div>
    </div>
  );
}

/**
 * For the "Graphical analysis" tab: pick one of the finished behavioral runs of this dataset and
 * show its community-detection graphs there too.
 */
export function RunCommunityGraphs({ datasetId, onGoBehavioral }) {
  const [jobs, setJobs] = useState(null);
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    api.jobs(datasetId).then((list) => {
      if (!live) return;
      const done = list.filter((j) => j.status === 'done').sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
      setJobs(done);
      if (done.length) setJobId(done[0].id);
    }).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [datasetId]);

  useEffect(() => {
    if (!jobId) return undefined;
    let live = true;
    setJob(null);
    api.job(jobId).then((j) => live && setJob(j)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [jobId]);

  return (
    <div className="card viz-section" style={{ marginTop: 0, marginBottom: 16 }}>
      <div className="row between">
        <h2>Community detection graphs</h2>
        {jobs && jobs.length > 1 && (
          <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
            {jobs.map((j) => <option key={j.id} value={j.id}>{new Date(j.createdAt).toLocaleString()} · {j.summary?.communities} communities · {j.summary?.primary_algorithm}</option>)}
          </select>
        )}
      </div>
      <p className="viz-sub">The similarity network from your behavioral analysis, coloured by the communities Louvain, Leiden and Label Propagation found.</p>
      {err && <div className="alert err">{err}</div>}
      {!jobs && !err && <div className="row"><span className="spinner" /> Loading your runs...</div>}
      {jobs && jobs.length === 0 && (
        <div className="emptyviz">
          No finished behavioral analysis for this dataset yet.
          {onGoBehavioral && <div style={{ marginTop: 10 }}><button onClick={onGoBehavioral}>Run a behavioral analysis</button></div>}
        </div>
      )}
      {jobs && jobs.length > 0 && !job && !err && <div className="row"><span className="spinner" /> Loading graph...</div>}
      {job?.result?.graph && <CommunityGraphs result={job.result} />}
    </div>
  );
}