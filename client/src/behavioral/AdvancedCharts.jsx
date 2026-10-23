import { useMemo, useState } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ScatterChart, Scatter, Cell, LineChart, Line, ReferenceLine, Area, AreaChart,
} from 'recharts';

/* ---------- palette ---------------------------------------------------- */
const ALGO_COLORS = {
  louvain: '#2563eb',
  leiden: '#7c3aed',
  lpa: '#059669',
};
const ALGO_LABELS = { louvain: 'Louvain', leiden: 'Leiden', lpa: 'Label Propagation' };
const nice = (v, d = 3) => (v == null ? '—' : typeof v === 'number' ? v.toFixed(d) : v);

const Tip = ({ title, lines }) => (
  <div className="vtip"><b>{title}</b>{lines.filter(Boolean).map((l, i) => <div key={i}>{l}</div>)}</div>
);

/* ======================================================================== */
/* 1.  ALGORITHM COMPARISON — Louvain vs Leiden vs LPA full breakdown        */
/* ======================================================================== */
export function AlgorithmComparisonCharts({ algorithmComparison, benchmark }) {
  const [tab, setTab] = useState('overview');
  if (!algorithmComparison?.length) return (
    <div className="emptyviz">Run the analysis with multiple algorithms selected to see this comparison.</div>
  );

  /* overview bar: modularity + num_communities */
  const overviewData = algorithmComparison.map((a) => {
    const brow = (benchmark || []).find((b) => b.key === a.algorithm) || {};
    return {
      algo: ALGO_LABELS[a.algorithm] || a.algorithm,
      key: a.algorithm,
      modularity: a.modularity ?? brow.modularity ?? 0,
      num_communities: a.num_communities,
      avg_intra_density: a.intra_density?.mean ?? 0,
      avg_conductance: a.conductance?.mean ?? 0,
      nmi: brow.nmi ?? null,
    };
  });

  /* radar: normalised [0-1] across metrics */
  const maxMod = Math.max(...overviewData.map((d) => d.modularity || 0)) || 1;
  const maxDen = Math.max(...overviewData.map((d) => d.avg_intra_density || 0)) || 1;
  const maxComm = Math.max(...overviewData.map((d) => d.num_communities || 0)) || 1;
  const radarData = [
    { metric: 'Modularity' },
    { metric: 'Intra-density' },
    { metric: 'Communities (norm)' },
    { metric: '1-Conductance' },
  ];
  algorithmComparison.forEach((a) => {
    radarData[0][ALGO_LABELS[a.algorithm]] = (a.modularity || 0) / maxMod;
    radarData[1][ALGO_LABELS[a.algorithm]] = (a.intra_density?.mean || 0) / maxDen;
    radarData[2][ALGO_LABELS[a.algorithm]] = (a.num_communities || 0) / maxComm;
    radarData[3][ALGO_LABELS[a.algorithm]] = 1 - (a.conductance?.mean || 0);
  });

  /* size-distribution histograms */
  const TABS = [['overview', 'Overview'], ['radar', 'Radar'], ['size', 'Size distribution'], ['density', 'Intra-density']];

  return (
    <div>
      <div className="adv-tabs">
        {TABS.map(([k, l]) => <button key={k} className={`adv-tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>

      {tab === 'overview' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Key quality metrics for each community detection algorithm run on the same graph.
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={overviewData} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="algo" />
              <YAxis yAxisId="left" domain={[0, 1]} label={{ value: 'Modularity / Density', angle: -90, position: 'insideLeft', fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" label={{ value: '# Communities', angle: 90, position: 'insideRight', fontSize: 11 }} />
              <Tooltip content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                return <Tip title={d.algo} lines={[
                  `Modularity: ${nice(d.modularity)}`,
                  `Intra-density: ${nice(d.avg_intra_density)}`,
                  `Conductance: ${nice(d.avg_conductance)}`,
                  `Communities: ${d.num_communities}`,
                  d.nmi != null ? `NMI vs label: ${nice(d.nmi)}` : null,
                ]} />;
              }} />
              <Legend />
              <Bar yAxisId="left" dataKey="modularity" name="Modularity" radius={[4, 4, 0, 0]}>
                {overviewData.map((d) => <Cell key={d.key} fill={ALGO_COLORS[d.key] || '#94a3b8'} />)}
              </Bar>
              <Bar yAxisId="left" dataKey="avg_intra_density" name="Avg intra-density" fill="#f59e0b" opacity={0.7} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>

          {/* metric table */}
          <div className="tablewrap" style={{ marginTop: 10, maxHeight: 200 }}>
            <table>
              <thead><tr><th>Algorithm</th><th>Communities</th><th>Modularity</th><th>Avg intra-density</th><th>Avg conductance</th><th>NMI vs label</th></tr></thead>
              <tbody>
                {overviewData.map((d) => (
                  <tr key={d.key}>
                    <td><span className="dot-algo" style={{ background: ALGO_COLORS[d.key] || '#94a3b8' }} />{d.algo}</td>
                    <td>{d.num_communities}</td>
                    <td>{nice(d.modularity)}</td>
                    <td>{nice(d.avg_intra_density)}</td>
                    <td>{nice(d.avg_conductance)}</td>
                    <td>{d.nmi != null ? nice(d.nmi) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'radar' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Normalised radar — the further a vertex is from the centre, the better the algorithm on that metric (conductance inverted: higher = better separation).
          </div>
          <ResponsiveContainer width="100%" height={340}>
            <RadarChart outerRadius={120} data={radarData}>
              <PolarGrid />
              <PolarAngleAxis dataKey="metric" tick={{ fontSize: 12 }} />
              <PolarRadiusAxis angle={90} domain={[0, 1]} tick={false} />
              {algorithmComparison.map((a) => (
                <Radar key={a.algorithm} name={ALGO_LABELS[a.algorithm] || a.algorithm}
                  dataKey={ALGO_LABELS[a.algorithm] || a.algorithm}
                  stroke={ALGO_COLORS[a.algorithm] || '#94a3b8'}
                  fill={ALGO_COLORS[a.algorithm] || '#94a3b8'} fillOpacity={0.15} />
              ))}
              <Legend />
              <Tooltip />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}

      {tab === 'size' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Community size distribution for each algorithm — how many communities of each size does each algorithm find?
          </div>
          <div className="grid g2" style={{ gap: 12 }}>
            {algorithmComparison.map((a) => {
              const hist = a.size_distribution?.histogram;
              if (!hist?.counts?.length) return null;
              const data = hist.counts.map((c, i) => ({
                x: `${hist.bins[i]}–${hist.bins[i + 1]}`,
                count: c,
              }));
              return (
                <div key={a.algorithm} style={{ background: '#f8fafc', borderRadius: 10, padding: 12 }}>
                  <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6, color: ALGO_COLORS[a.algorithm] || '#0f172a' }}>
                    {ALGO_LABELS[a.algorithm] || a.algorithm}
                    <span className="muted small" style={{ marginLeft: 8 }}>
                      {a.num_communities} communities · mean size {nice(a.size_distribution?.mean, 1)}
                    </span>
                  </div>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={data} margin={{ top: 4, right: 8, bottom: 16, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="x" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" interval={0} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                      <Tooltip formatter={(v) => [v, 'communities']} />
                      <Bar dataKey="count" fill={ALGO_COLORS[a.algorithm] || '#94a3b8'} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {tab === 'density' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Intra-community density per community for each algorithm. Higher density = more tightly connected cluster.
          </div>
          {algorithmComparison.map((a) => {
            const rows = (a.community_density_profile || []).map((r, i) => ({
              id: `C${r.community_id}`,
              density: r.intra_density,
              conductance: r.conductance,
              size: r.size,
            }));
            if (!rows.length) return null;
            return (
              <div key={a.algorithm} style={{ marginBottom: 20 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6, color: ALGO_COLORS[a.algorithm] || '#0f172a' }}>
                  {ALGO_LABELS[a.algorithm] || a.algorithm}
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 20, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="id" tick={{ fontSize: 10 }} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} label={{ value: 'Intra-density', angle: -90, position: 'insideLeft', fontSize: 10 }} />
                    <Tooltip content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0]?.payload;
                      return <Tip title={d.id} lines={[`Density: ${nice(d.density)}`, `Conductance: ${nice(d.conductance)}`, `Size: ${d.size}`]} />;
                    }} />
                    <Bar dataKey="density" name="Intra-density" fill={ALGO_COLORS[a.algorithm] || '#94a3b8'} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


/* ======================================================================== */
/* 2.  NMI ANALYSIS                                                          */
/* ======================================================================== */
export function NMIAnalysisChart({ nmiAnalysis, benchmark }) {
  if (!nmiAnalysis || !nmiAnalysis.available) {
    return (
      <div className="emptyviz">
        {nmiAnalysis?.reason ||
          'NMI analysis requires a label column. Add a label file in the behavioral wizard (Step 1 → Label column).'}
      </div>
    );
  }

  const algoData = Object.entries(nmiAnalysis.nmi_by_algorithm || {}).map(([k, v]) => ({
    algo: ALGO_LABELS[k] || k,
    key: k,
    nmi: v ?? 0,
  }));

  const sweepData = nmiAnalysis.nmi_vs_min_community_size || [];

  const labelDist = Object.entries(nmiAnalysis.label_distribution || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([name, count]) => ({ name, count }));

  return (
    <div>
      <div className="muted small" style={{ marginBottom: 12 }}>
        Normalised Mutual Information (NMI) measures agreement between detected communities and the ground-truth label column.
        A score of 1 means perfect agreement; near-0 is typical because community detection finds <em>behavioral patterns</em>, not label categories.
      </div>

      <div className="grid g2" style={{ gap: 16, alignItems: 'start' }}>
        {/* NMI by algorithm */}
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>NMI per algorithm</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={algoData} margin={{ top: 8, right: 16, bottom: 16, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="algo" tick={{ fontSize: 12 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} label={{ value: 'NMI', angle: -90, position: 'insideLeft', fontSize: 11 }} />
              <Tooltip formatter={(v) => [nice(v, 4), 'NMI']} />
              <Bar dataKey="nmi" name="NMI" radius={[4, 4, 0, 0]}>
                {algoData.map((d) => <Cell key={d.key} fill={ALGO_COLORS[d.key] || '#94a3b8'} />)}
              </Bar>
              <ReferenceLine y={0.3} stroke="#f59e0b" strokeDasharray="5 4" label={{ value: '0.3 = meaningful', position: 'insideTopRight', fontSize: 10, fill: '#92400e' }} />
            </BarChart>
          </ResponsiveContainer>
          <p className="muted small">Values above 0.3 indicate the communities align meaningfully with the label.</p>
        </div>

        {/* Label distribution */}
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>Label class distribution</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={labelDist} margin={{ top: 8, right: 8, bottom: 30, left: 10 }} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={80} />
              <Tooltip formatter={(v) => [v, 'entities']} />
              <Bar dataKey="count" fill="#2563eb" opacity={0.75} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* NMI vs min community size sweep */}
      {sweepData.length > 1 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
            NMI vs minimum community size (primary algorithm)
          </div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            How does NMI change if we only score entities in communities larger than a threshold? Helps identify whether small outlier communities drag NMI down.
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={sweepData} margin={{ top: 8, right: 24, bottom: 20, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="min_size" label={{ value: 'Min community size', position: 'insideBottom', offset: -10, fontSize: 12 }} />
              <YAxis yAxisId="nmi" domain={[0, 1]} label={{ value: 'NMI', angle: -90, position: 'insideLeft', fontSize: 11 }} />
              <YAxis yAxisId="covered" orientation="right" label={{ value: 'Nodes covered', angle: 90, position: 'insideRight', fontSize: 11 }} />
              <Tooltip content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return <Tip title={`Min size ≥ ${label}`} lines={payload.map((p) => `${p.name}: ${nice(p.value, p.name === 'NMI' ? 4 : 0)}`)} />;
              }} />
              <Legend />
              <Line yAxisId="nmi" type="monotone" dataKey="nmi" name="NMI" stroke="#2563eb" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
              <Line yAxisId="covered" type="monotone" dataKey="nodes_covered" name="Nodes covered" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}


/* ======================================================================== */
/* 3.  DENSITY ANALYSIS                                                      */
/* ======================================================================== */
export function DensityAnalysisCharts({ graphMetrics, communities }) {
  const [tab, setTab] = useState('topology');

  if (!graphMetrics || !graphMetrics.n_nodes) {
    return <div className="emptyviz">Graph metrics not available. Re-run the analysis.</div>;
  }

  const gm = graphMetrics;

  /* Key stats cards */
  const stats = [
    { v: nice(gm.density, 4), l: 'Graph density' },
    { v: nice(gm.avg_degree, 2), l: 'Avg degree' },
    { v: nice(gm.global_clustering_coeff, 4), l: 'Global clustering coeff' },
    { v: nice(gm.avg_clustering_coeff, 4), l: 'Avg clustering coeff' },
    { v: gm.diameter ?? '—', l: 'Diameter (LCC)' },
    { v: nice(gm.avg_path_length, 3), l: 'Avg path length (LCC)' },
    { v: gm.n_components, l: 'Components' },
    { v: `${(gm.lcc_fraction * 100).toFixed(0)}%`, l: `Largest comp (${gm.lcc_size} nodes)` },
  ];

  /* Degree distribution */
  const degHist = gm.degree_distribution || { bins: [], counts: [] };
  const degData = degHist.counts.map((c, i) => ({
    x: `${Math.round(degHist.bins[i])}`,
    count: c,
  }));

  /* Weight distribution */
  const wHist = gm.weight_distribution || { bins: [], counts: [] };
  const wData = wHist.counts.map((c, i) => ({
    x: nice(wHist.bins[i], 2),
    count: c,
  }));

  /* Community intra-density vs size scatter */
  const commScatter = (communities || [])
    .filter((c) => c.intra_density != null)
    .map((c) => ({ size: c.size, density: c.intra_density, conductance: c.conductance ?? 0, id: c.community_id, tier: c.tier }));

  const TABS = [['topology', 'Graph topology'], ['degree', 'Degree distribution'], ['weight', 'Edge weights'], ['community', 'Community density']];

  return (
    <div>
      <div className="adv-tabs">
        {TABS.map(([k, l]) => <button key={k} className={`adv-tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>

      {tab === 'topology' && (
        <div>
          <div className="adv-stat-grid">
            {stats.map((s) => (
              <div key={s.l} className="adv-stat">
                <div className="adv-stat-v">{s.v}</div>
                <div className="adv-stat-l">{s.l}</div>
              </div>
            ))}
          </div>
          {/* Topology gauge bars */}
          <div style={{ marginTop: 16 }}>
            {[
              { label: 'Density', value: gm.density, max: 1, color: '#2563eb', help: '0 = no edges, 1 = fully connected' },
              { label: 'Global clustering', value: gm.global_clustering_coeff, max: 1, color: '#7c3aed', help: 'Probability that two neighbours of a node are also connected' },
              { label: 'Avg clustering', value: gm.avg_clustering_coeff, max: 1, color: '#059669', help: 'Average over all nodes' },
              { label: 'LCC fraction', value: gm.lcc_fraction, max: 1, color: '#f59e0b', help: 'Fraction of nodes in the largest connected component' },
            ].map(({ label, value, max, color, help }) => (
              <div key={label} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 3 }}>
                  <span style={{ fontWeight: 600 }}>{label}</span>
                  <span className="muted">{nice(value, 4)} <span title={help} style={{ cursor: 'help' }}>ⓘ</span></span>
                </div>
                <div style={{ background: '#e2e8f0', borderRadius: 6, height: 12, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, (value / max) * 100)}%`, height: '100%', background: color, borderRadius: 6, transition: 'width .5s' }} />
                </div>
              </div>
            ))}
          </div>
          {gm.assortativity != null && (
            <div className="adv-info-box" style={{ marginTop: 12 }}>
              <b>Degree assortativity:</b> {nice(gm.assortativity, 4)} —{' '}
              {gm.assortativity > 0.1 ? 'high-degree nodes tend to connect to other high-degree nodes (assortative).'
                : gm.assortativity < -0.1 ? 'high-degree nodes tend to connect to low-degree nodes (disassortative).'
                  : 'no strong preference (neutral).'}
            </div>
          )}
        </div>
      )}

      {tab === 'degree' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Degree distribution of the similarity graph. Most behavioral networks follow a right-skewed distribution — a few hub entities are similar to many others.
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={degData} margin={{ top: 8, right: 16, bottom: 20, left: 10 }}>
              <defs>
                <linearGradient id="degGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="x" label={{ value: 'Degree (number of edges)', position: 'insideBottom', offset: -10, fontSize: 12 }} tick={{ fontSize: 10 }} />
              <YAxis label={{ value: 'Entities', angle: -90, position: 'insideLeft', fontSize: 12 }} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => [v, 'entities']} />
              <Area type="monotone" dataKey="count" name="Entities" stroke="#2563eb" strokeWidth={2} fill="url(#degGrad)" />
            </AreaChart>
          </ResponsiveContainer>
          <div className="adv-info-box" style={{ marginTop: 10 }}>
            <b>Max degree:</b> {gm.max_degree} · <b>Avg degree:</b> {nice(gm.avg_degree, 2)} ·{' '}
            {gm.avg_betweenness != null && <><b>Avg betweenness centrality:</b> {nice(gm.avg_betweenness, 4)} · <b>Max:</b> {nice(gm.max_betweenness, 4)}</>}
          </div>
        </div>
      )}

      {tab === 'weight' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Distribution of cosine similarity values (edge weights). The chosen threshold keeps only edges to the right of the cutoff.
          </div>
          {wData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={wData} margin={{ top: 8, right: 16, bottom: 20, left: 10 }}>
                <defs>
                  <linearGradient id="wGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#059669" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#059669" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="x" label={{ value: 'Cosine similarity (edge weight)', position: 'insideBottom', offset: -10, fontSize: 12 }} tick={{ fontSize: 10 }} />
                <YAxis label={{ value: 'Edges', angle: -90, position: 'insideLeft', fontSize: 12 }} tick={{ fontSize: 10 }} />
                <Tooltip formatter={(v) => [v, 'edges']} />
                <Area type="monotone" dataKey="count" name="Edges" stroke="#059669" strokeWidth={2} fill="url(#wGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="emptyviz">Weight distribution not available in this result. Re-run the analysis.</div>
          )}
          <div className="adv-info-box" style={{ marginTop: 10 }}>
            <b>Avg edge weight:</b> {nice(gm.avg_edge_weight, 4)}
          </div>
        </div>
      )}

      {tab === 'community' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Intra-community density vs community size. Dense communities (top of chart) are tightly knit; low-density communities are loosely connected.
          </div>
          {commScatter.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={320}>
                <ScatterChart margin={{ top: 16, right: 20, bottom: 24, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="size" name="Size" label={{ value: 'Community size', position: 'insideBottom', offset: -10, fontSize: 12 }} tick={{ fontSize: 10 }} />
                  <YAxis type="number" dataKey="density" name="Intra-density" domain={[0, 1]}
                    label={{ value: 'Intra-density', angle: -90, position: 'insideLeft', fontSize: 12 }} tick={{ fontSize: 10 }} />
                  <Tooltip content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0]?.payload;
                    return <Tip title={`Community ${d.id} (${d.tier})`} lines={[
                      `Size: ${d.size} members`,
                      `Intra-density: ${nice(d.density)}`,
                      `Conductance: ${nice(d.conductance)}`,
                    ]} />;
                  }} />
                  <Scatter data={commScatter} name="Communities">
                    {commScatter.map((d, i) => (
                      <Cell key={i} fill="#2563eb" fillOpacity={0.65} stroke="#1d4ed8" strokeWidth={1} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
              <div className="adv-info-box" style={{ marginTop: 10 }}>
                Smaller communities often have higher density (every member knows every other member). Large communities naturally have lower density.
              </div>

              {/* conductance bar */}
              <div style={{ marginTop: 16 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
                  Conductance per community
                  <span className="muted small" style={{ marginLeft: 8, fontWeight: 400 }}>
                    Lower conductance = better separation from the rest of the graph
                  </span>
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={commScatter.sort((a, b) => a.conductance - b.conductance)}
                    margin={{ top: 4, right: 16, bottom: 20, left: 10 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="id" tickFormatter={(v) => `C${v}`} tick={{ fontSize: 10 }} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} label={{ value: 'Conductance', angle: -90, position: 'insideLeft', fontSize: 11 }} />
                    <Tooltip formatter={(v, _, p) => [nice(v), 'Conductance']} labelFormatter={(v) => `Community ${v}`} />
                    <Bar dataKey="conductance" name="Conductance" fill="#7c3aed" opacity={0.7} radius={[3, 3, 0, 0]} />
                    <ReferenceLine y={0.5} stroke="#f59e0b" strokeDasharray="5 4" label={{ value: '0.5 threshold', position: 'insideTopRight', fontSize: 10, fill: '#92400e' }} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <div className="emptyviz">Per-community density data not available. Re-run the analysis.</div>
          )}
        </div>
      )}
    </div>
  );
}
