import { useEffect, useMemo, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, Cell } from 'recharts';
import { api } from '../api.js';
import { DEFAULT_TIERS, OUTLIER, num, tierColors } from '../util.js';
import GraphView from './GraphView.jsx';
import SimilarityChart from './SimilarityChart.jsx';
import CommunityGraphs from './CommunityGraphs.jsx';
import ModularityAnalysis from './ModularityAnalysis.jsx';
import { CommunityBubble, CommunityDetail, EntityMap, PipelineFlow, ProfileHeatmap, TierBox, TierDonut } from './charts.jsx';
import { AlgorithmComparisonCharts, NMIAnalysisChart, DensityAnalysisCharts } from './AdvancedCharts.jsx';
import { isDimmed } from './viz.js';
import './behavioral.css';

const Stat = ({ v, l }) => <div className="card stat" style={{ marginBottom: 0 }}><div className="v">{v}</div><div className="l">{l}</div></div>;
const Section = ({ title, sub, how, children, right }) => (
  <div className="card viz-section">
    <div className="row between"><h2>{title}</h2>{right}</div>
    {sub && <p className="viz-sub">{sub}</p>}
    {how && <div className="viz-how"><b>How to read it:</b> {how}</div>}
    {children}
  </div>
);

function CommunityTable({ communities, colors, selComm, selTier, onPickComm }) {
  const [sort, setSort] = useState({ key: 'avg_total_activity', dir: -1 });
  const rows = useMemo(() => {
    const r = communities.filter((c) => !selTier || c.tier === selTier);
    return r.sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sort.dir;
    });
  }, [communities, sort, selTier]);
  const maxAvg = Math.max(1, ...communities.map((c) => c.avg_total_activity));
  const head = (key, label) => (
    <th onClick={() => setSort((s) => ({ key, dir: s.key === key ? -s.dir : -1 }))}>{label}{sort.key === key ? (sort.dir < 0 ? ' ▼' : ' ▲') : ''}</th>
  );
  return (
    <div className="tablewrap"><table className="ctable">
      <thead><tr>{head('community_id', 'community')}{head('size', 'members')}{head('avg_total_activity', 'avg total activity')}{head('median_total_activity', 'median')}{head('cohesion', 'cohesion')}{head('intra_density', 'intra-density')}{head('conductance', 'conductance')}<th>what they do most</th>{head('tier', 'tier')}</tr></thead>
      <tbody>{rows.map((c) => (
        <tr key={c.community_id} className={`crow ${selComm === c.community_id ? 'sel' : ''}`} onClick={() => onPickComm(c.community_id)}>
          <td>{c.community_id}</td><td>{c.size}</td>
          <td>{num(c.avg_total_activity)}<span className="minibar" style={{ width: `${Math.max(2, (60 * c.avg_total_activity) / maxAvg)}px` }} /></td>
          <td>{num(c.median_total_activity)}</td><td>{num(c.cohesion)}</td>
          <td>{c.intra_density != null ? c.intra_density.toFixed(4) : '\u2014'}</td>
          <td>{c.conductance != null ? c.conductance.toFixed(4) : '\u2014'}</td>
          <td>{c.top_behaviors ? c.top_behaviors.map((t) => <span className="chip" key={t.name}>{t.name} {Math.round(t.share_pct)}%</span>) : c.top_behavior}</td>
          <td><span className="badge" style={{ background: colors[c.tier] || '#64748b' }}>{c.tier}</span></td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

function Dashboard({ job }) {
  const r = job.result, s = r.summary;
  const labels = job.params?.tier_labels || DEFAULT_TIERS;
  const colors = useMemo(() => tierColors(labels), [labels.join('|')]); // eslint-disable-line
  const tiers = [...labels].reverse().concat(OUTLIER).filter((t) => s.tier_counts[t]);

  // one shared selection drives every chart
  const [selComm, setSelComm] = useState(null);
  const [selTier, setSelTier] = useState(null);
  const [colorBy, setColorBy] = useState('tier');
  const [mode, setMode] = useState('entities');
  const pickComm = (id) => { setSelComm((cur) => (cur === id ? null : id)); };
  const pickTier = (t) => { setSelComm(null); setSelTier((cur) => (cur === t ? null : t)); };
  const clear = () => { setSelComm(null); setSelTier(null); };

  const selected = r.communities.find((c) => c.community_id === selComm) || null;
  const bench = r.benchmark.filter((b) => b.modularity != null);
  const graphNodes = mode === 'entities' ? r.graph.nodes : r.macro_graph.nodes;
  const graphEdges = mode === 'entities' ? r.graph.edges : r.macro_graph.edges;
  const primaryKey = bench.find((b) => b.algorithm === s.primary_algorithm)?.key;

  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Results</h2>
        <div className="row">
          {(selComm != null || selTier) && <span className="selchip">{selComm != null ? `Community ${selComm}` : selTier}<button onClick={clear}>clear</button></span>}
          <a className="btn" href={api.downloadUrl(job.id)}>Download classified CSV</a>
        </div>
      </div>

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat v={s.connected_nodes} l={`connected entities (of ${s.sampled_entities} sampled, ${s.total_entities_in_data.toLocaleString()} in data)`} />
        <Stat v={s.edges.toLocaleString()} l={s.graph_method === 'knn' ? 'similarity edges (kNN graph)' : `similarity edges (threshold ${s.threshold})`} />
        <Stat v={s.communities} l={`communities (${s.primary_algorithm})`} />
        <Stat v={`${s.runtime_sec}s`} l={`runtime, ${s.kept_pct_of_sample}% of sample kept`} />
      </div>

      {r.diagnostics.length > 0 && (
        <div className="card"><h3>Things to keep in mind</h3>
          {r.diagnostics.map((d, i) => <div key={i} className={`alert ${d.level === 'warn' ? 'warn' : 'info'}`}>{d.text}</div>)}
        </div>
      )}

      <Section title="How this result was produced" sub="The pipeline, with the real numbers of this run.">
        <PipelineFlow result={r} />
      </Section>

      <Section title="Tier classification" sub="Who ended up in High, Moderate and Low engagement."
        how="The donut shows how many entities each tier holds. The box plot shows how much activity the entities in each tier actually have: if the boxes barely overlap the tiers are well separated.">
        <div className="grid g2" style={{ alignItems: 'start' }}>
          <TierDonut tiers={tiers} counts={s.tier_counts} communities={r.communities} colors={colors} selTier={selTier} onPickTier={pickTier} />
          <TierBox nodes={r.graph.nodes} tiers={tiers} colors={colors} selTier={selTier} />
        </div>
      </Section>

      <Section title="Communities: size vs. activity" sub="Each community is a group of entities with a similar behavior pattern."
        how="Up = more active on average, right = more members. The dashed lines are the tier boundaries. Click a bubble to select a community everywhere on this page.">
        <div className="grid g2" style={{ alignItems: 'start' }}>
          <CommunityBubble communities={r.communities} tiers={tiers} colors={colors} labels={labels} selComm={selComm} selTier={selTier} onPickComm={pickComm} />
          <CommunityDetail c={selected} behaviors={r.behaviors} colors={colors} onClear={() => setSelComm(null)} />
        </div>
      </Section>

      <Section title="What does each community do?" sub="The behavior fingerprint of every community."
        how="A blue cell means that community does that behavior MORE than the average entity (2.0 = twice as much); orange means less. Switch to 'share' to see how each community's own activity is split.">
        <ProfileHeatmap communities={r.communities} behaviors={r.behaviors} colors={colors} selComm={selComm} selTier={selTier} onPickComm={pickComm} />
      </Section>

      <Section title="Entity map" sub="Every entity as a dot, placed by behavior."
        how="Dots close together behave alike. If the communities form separate clouds, the grouping is meaningful; heavy overlap means the communities differ more in volume than in pattern.">
        <EntityMap nodes={r.graph.nodes} pca={r.pca} colors={colors} colorBy={colorBy} setColorBy={setColorBy} selComm={selComm} selTier={selTier} onPickComm={pickComm} />
      </Section>

      <Section title="Similarity graph" sub="The network the communities were found in."
        how="Entity graph: dots are entities and lines are pairs that are similar enough. Community graph: each bubble is a community; thick lines mean many cross-links, so those communities behave similarly."
        right={<div className="seg"><button className={mode === 'entities' ? 'on' : ''} onClick={() => setMode('entities')}>Entity graph</button><button className={mode === 'communities' ? 'on' : ''} onClick={() => setMode('communities')}>Community graph</button></div>}>
        <div className="legend">{tiers.map((t) => <span key={t}><i style={{ background: colors[t] }} />{t}</span>)}</div>
        {r.graph.truncated && mode === 'entities' && <div className="alert info">Showing only the strongest edges for readability.</div>}
        <GraphView nodes={graphNodes} edges={graphEdges} colors={colors} mode={mode} colorBy={colorBy} selComm={selComm} selTier={selTier} onPickComm={pickComm} />
      </Section>

      <Section title="All communities" sub="Click a header to sort, click a row to select."
        how="Intra-density: how densely connected members of this community are internally. Conductance: ratio of edges that cross the community boundary (lower = better separation).">
        <CommunityTable communities={r.communities} colors={colors} selComm={selComm} selTier={selTier} onPickComm={pickComm} />
        <p className="muted small">Cohesion = average similarity between members of the same community (1 = identical behavior). Intra-density = edge density within the community. Conductance: lower = better separated from the rest.</p>
      </Section>

      <div className="grid g2" style={{ marginTop: 22 }}>
        <div className="card"><h2>Choosing the threshold</h2>
          <SimilarityChart hist={r.similarity} threshold={s.threshold} sweep={r.sweep} />
        </div>
        <div className="card"><h2>Algorithm comparison</h2>
          <table><thead><tr><th>algorithm</th><th>communities</th><th>modularity (γ=1)</th><th>NMI vs label</th></tr></thead>
            <tbody>{r.benchmark.map((b) => (
              <tr key={b.key}><td>{b.algorithm}{(b.backend || b.key === 'leiden') && <span className="muted small"> ({[b.backend, b.key === 'leiden' && b.resolution != null ? `γ=${b.resolution}` : null].filter(Boolean).join(', ')})</span>}</td><td>{b.num_communities ?? '-'}</td>
                <td>{b.modularity ?? <span className="muted" title={b.error}>unavailable</span>}</td>
                <td>{b.nmi ?? <span className="muted" title={r.has_label ? 'Not computable for this algorithm' : 'No label column used'}>{b.error ? '-' : r.has_label ? 'n/a' : 'no label'}</span>}</td></tr>
            ))}</tbody></table>
          {bench.length > 0 && (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={bench} margin={{ top: 12 }}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="algorithm" /><YAxis domain={[0, 1]} /><Tooltip /><Legend />
                <Bar dataKey="modularity" fill="#2563eb">{bench.map((b) => <Cell key={b.key} fillOpacity={b.key === primaryKey ? 1 : 0.5} />)}</Bar>
                <Bar dataKey="nmi" fill="#f59e0b" /></BarChart>
            </ResponsiveContainer>
          )}
          {bench.length < r.benchmark.length && <div className="alert warn" style={{ marginTop: 8 }}>{r.benchmark.filter((b) => b.error).map((b) => `${b.algorithm}: ${b.error}`).join(' · ')}</div>}
          <p className="muted small">Modularity: how well-separated the communities are (above 0.3 is meaningful, higher is better). NMI: agreement with the label column, if one was supplied; low values are normal because communities follow behavior, not the label. The darker bar is the algorithm used for the tiers.</p>
        </div>
      </div>

      <Section
        title="Community detection graphs"
        sub="The same similarity network, divided into communities by Louvain, Leiden and Label Propagation."
        how="Each dot is an entity and each line a similarity link. Colour = community. With 'Clustered by community' every community is drawn as its own cluster, with the communities that are linked most placed next to each other. Colours are matched across algorithms: a cluster that keeps its colour in all three was found by every method.">
        <CommunityGraphs result={r} />
      </Section>

      <Section
        title="Modularity"
        sub="How much more densely connected the communities are inside than chance would give, for each algorithm."
        how="Q above 0.3 means real community structure, above 0.5 strong. The grey bars show what a random labelling of the same graph scores. 'Per community' shows which communities contribute most; 'Resolution sweep' shows how stable the result is.">
        <ModularityAnalysis modularity={r.modularity_analysis} benchmark={r.benchmark} />
      </Section>

      {/* ---- ADVANCED SECTIONS ---- */}
      <Section
        title="Louvain vs Leiden vs Label Propagation"
        sub="Deep comparison of all community detection algorithms run on this graph."
        how="Overview: modularity and intra-density bars; Radar: normalised quality across four metrics; Size: how many communities of each size each algorithm found; Intra-density: per-community density profile.">
        <AlgorithmComparisonCharts algorithmComparison={r.algorithm_comparison} benchmark={r.benchmark} />
      </Section>

      <Section
        title="NMI Analysis"
        sub="How well do the detected communities agree with a label column, and with each other?"
        how="NMI (Normalised Mutual Information) = 1 means perfect agreement, 0 means unrelated. Against a label such as final_result, ~0.05-0.1 is typical because communities group by behavior shape, not by outcome. The algorithm-vs-algorithm matrix needs no label and tells you how consistent the detection is.">
        <NMIAnalysisChart nmiAnalysis={r.nmi_analysis} benchmark={r.benchmark} />
      </Section>

      <Section
        title="Graph Density Analysis"
        sub="Topology of the similarity graph and density profile of each community."
        how="Topology: global graph metrics. Degree distribution: how many edges each entity has. Edge weights: distribution of cosine similarities. Community density: intra-density vs size scatter and conductance bars.">
        <DensityAnalysisCharts graphMetrics={r.graph_metrics} communities={r.communities} />
      </Section>
    </>
  );
}

export default function Results({ jobId, onBack, onFinished }) {
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [secs, setSecs] = useState(0);

  useEffect(() => {
    let live = true, timer;
    const poll = async () => {
      try {
        const j = await api.job(jobId);
        if (!live) return;
        setJob(j);
        if (j.status === 'queued' || j.status === 'running') timer = setTimeout(poll, 1000);
        else onFinished?.(j);
      } catch (e) { if (live) setErr(e.message); }
    };
    poll();
    const t = setInterval(() => setSecs((x) => x + 1), 1000);
    return () => { live = false; clearTimeout(timer); clearInterval(t); };
  }, [jobId]); // eslint-disable-line

  if (err) return <div className="alert err">{err}</div>;
  if (!job) return <div className="row"><span className="spinner" /> Loading...</div>;
  if (job.status === 'queued' || job.status === 'running') {
    return <div className="card row"><span className="spinner" /><div><b>{job.status === 'queued' ? 'Waiting in queue...' : 'Running analysis...'}</b>
      <div className="muted small">Building the matrix, similarity graph and communities. {secs}s elapsed. Large files can take a minute.</div></div></div>;
  }
  if (job.status === 'failed') {
    return <div><div className="alert err"><b>The analysis could not be completed.</b><br />{job.error}</div>{onBack && <button className="ghost" onClick={onBack}>Change settings</button>}</div>;
  }
  return <Dashboard job={job} />;
}