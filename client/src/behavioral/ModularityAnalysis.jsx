import { useMemo, useState } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid,
  LineChart, Line, ReferenceLine, Cell,
} from 'recharts';
import { modularityStrength } from './viz.js';

const ALGO_COLORS = { louvain: '#2563eb', leiden: '#7c3aed', lpa: '#059669' };
const ALGO_LABELS = { louvain: 'Louvain', leiden: 'Leiden', lpa: 'Label Propagation' };
const f = (v, d = 4) => (v == null ? '—' : Number(v).toFixed(d));

const Tip = ({ title, lines }) => (
  <div className="vtip"><b>{title}</b>{lines.filter(Boolean).map((l, i) => <div key={i}>{l}</div>)}</div>
);

/** horizontal 0..1 scale with the 0.3 / 0.5 guide lines, the random baseline and the measured Q */
function QScale({ q, baseline, color }) {
  const pos = (v) => `${Math.max(0, Math.min(1, v)) * 100}%`;
  return (
    <div className="qscale">
      <div className="qtrack">
        <i className="qband weak" /><i className="qband mod" /><i className="qband strong" />
        <span className="qmark base" style={{ left: pos(baseline) }} title={`random labelling ≈ ${f(baseline)}`} />
        <span className="qmark val" style={{ left: pos(q), background: color }} title={`Q = ${f(q)}`} />
      </div>
      <div className="qticks"><span>0</span><span style={{ left: '30%' }}>0.3</span><span style={{ left: '50%' }}>0.5</span><span style={{ left: '100%' }}>1</span></div>
    </div>
  );
}

export default function ModularityAnalysis({ modularity, benchmark }) {
  const [tab, setTab] = useState('overview');
  const algos = modularity?.available ? modularity.algorithms : [];
  const [sel, setSel] = useState(algos[0]?.algorithm);
  const cur = algos.find((a) => a.algorithm === sel) || algos[0];

  const barData = useMemo(() => algos.map((a) => ({
    key: a.algorithm, algo: ALGO_LABELS[a.algorithm] || a.algorithm,
    Q: a.modularity, random: a.random_baseline.mean, randomMax: a.random_baseline.max,
  })), [algos]);

  const commData = useMemo(() => (cur ? [...cur.communities].sort((a, b) => b.contribution - a.contribution)
    .map((c) => ({ ...c, id: `C${c.community_id}` })) : []), [cur]);

  // an algorithm that failed has no modularity: say so instead of showing nothing
  const failed = (benchmark || []).filter((b) => b.error);

  if (!modularity?.available || !algos.length) {
    return <div className="emptyviz">Modularity details are not in this result. Re-run the analysis to calculate them.</div>;
  }

  const TABS = [['overview', 'Overview'], ['communities', 'Per community'], ['resolution', 'Resolution sweep'], ['how', 'How it is calculated']];

  return (
    <div>
      {failed.map((b) => <div key={b.key} className="alert warn"><b>{b.algorithm}</b> has no modularity because it could not run: {b.error}</div>)}
      <div className="adv-tabs">{TABS.map(([k, l]) => <button key={k} className={`adv-tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>

      {tab === 'overview' && (
        <div>
          <div className="mod-cards">
            {algos.map((a) => {
              const s = modularityStrength(a.modularity);
              return (
                <div key={a.algorithm} className="mod-card" style={{ borderTopColor: ALGO_COLORS[a.algorithm] }}>
                  <div className="mod-name">{ALGO_LABELS[a.algorithm] || a.algorithm}</div>
                  <div className="mod-q">{f(a.modularity)}</div>
                  <div className="mod-badge" style={{ background: s.color }}>{s.label} community structure</div>
                  <QScale q={a.modularity} baseline={a.random_baseline.mean} color={ALGO_COLORS[a.algorithm]} />
                  <div className="muted small">{a.num_communities} communities · random labelling gives {f(a.random_baseline.mean, 3)} (best of {a.random_baseline.n}: {f(a.random_baseline.max, 3)})</div>
                </div>
              );
            })}
          </div>

          <div style={{ fontWeight: 700, fontSize: 13, margin: '16px 0 6px' }}>Modularity by algorithm</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={barData} margin={{ top: 10, right: 20, bottom: 10, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="algo" />
              <YAxis domain={[0, 1]} label={{ value: 'Modularity Q', angle: -90, position: 'insideLeft', fontSize: 11 }} />
              <Tooltip content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload;
                return <Tip title={d.algo} lines={[`Q = ${f(d.Q)}`, `random labelling: ${f(d.random, 4)} (max ${f(d.randomMax, 4)})`]} />;
              }} />
              <Legend />
              <ReferenceLine y={0.3} stroke="#f59e0b" strokeDasharray="5 4" label={{ value: '0.3 = meaningful', position: 'insideTopRight', fontSize: 10, fill: '#92400e' }} />
              <ReferenceLine y={0.5} stroke="#16a34a" strokeDasharray="5 4" label={{ value: '0.5 = strong', position: 'insideTopRight', fontSize: 10, fill: '#166534' }} />
              <Bar dataKey="Q" name="Detected communities" radius={[4, 4, 0, 0]}>{barData.map((d) => <Cell key={d.key} fill={ALGO_COLORS[d.key] || '#94a3b8'} />)}</Bar>
              <Bar dataKey="random" name="Random labelling (same sizes)" fill="#cbd5e1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>

          <div className="tablewrap" style={{ marginTop: 10, maxHeight: 240 }}>
            <table>
              <thead><tr><th>Algorithm</th><th>Communities</th><th>Inside-community weight share</th><th>Expected by chance</th><th>Q = observed − expected</th><th>networkx check</th></tr></thead>
              <tbody>{algos.map((a) => (
                <tr key={a.algorithm}>
                  <td><span className="dot-algo" style={{ background: ALGO_COLORS[a.algorithm] }} />{ALGO_LABELS[a.algorithm] || a.algorithm}</td>
                  <td>{a.num_communities}</td><td>{f(a.intra_weight_share)}</td><td>{f(a.expected_share)}</td>
                  <td><b>{f(a.modularity)}</b></td>
                  <td>{a.modularity_networkx == null ? '—' : Math.abs(a.modularity_networkx - a.modularity) < 1e-5 ? `✓ ${f(a.modularity_networkx, 6)}` : f(a.modularity_networkx, 6)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'communities' && cur && (
        <div>
          <div className="toolbar">
            <div className="seg">{algos.map((a) => <button key={a.algorithm} className={cur.algorithm === a.algorithm ? 'on' : ''} onClick={() => setSel(a.algorithm)}>{ALGO_LABELS[a.algorithm] || a.algorithm}</button>)}</div>
            <span className="muted small">Q = {f(cur.modularity)} = sum of the contributions below</span>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={commData} margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="id" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} label={{ value: 'share of all edge weight', angle: -90, position: 'insideLeft', fontSize: 11 }} />
              <Tooltip content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload;
                return <Tip title={`Community ${d.community_id} (${d.size} members)`} lines={[`Observed inside: ${f(d.observed)}`, `Expected by chance: ${f(d.expected)}`, `Contribution to Q: ${f(d.contribution)}`]} />;
              }} />
              <Legend />
              <Bar dataKey="observed" name="Observed (L_c / m)" fill={ALGO_COLORS[cur.algorithm]} radius={[3, 3, 0, 0]} />
              <Bar dataKey="expected" name="Expected by chance" fill="#cbd5e1" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="tablewrap" style={{ marginTop: 10, maxHeight: 320 }}>
            <table>
              <thead><tr><th>Community</th><th>Members</th><th>L_c (inside weight)</th><th>d_c (degree sum)</th><th>L_c / m</th><th>(d_c / 2m)²</th><th>Contribution</th></tr></thead>
              <tbody>
                {commData.map((c) => (
                  <tr key={c.community_id}><td>{c.community_id}</td><td>{c.size}</td><td>{f(c.intra_weight, 2)}</td><td>{f(c.degree_sum, 2)}</td><td>{f(c.observed, 5)}</td><td>{f(c.expected, 5)}</td><td><b>{f(c.contribution, 5)}</b></td></tr>
                ))}
                <tr className="totalrow"><td colSpan={6}><b>Q (sum of contributions)</b></td><td><b>{f(cur.modularity, 5)}</b></td></tr>
              </tbody>
            </table>
          </div>
          <p className="muted small">A community with a large positive contribution is much denser inside than a random network with the same degrees would be.
            A contribution near zero (usually a tiny community) adds nothing to the overall structure.</p>
        </div>
      )}

      {tab === 'resolution' && (
        <div>
          <div className="muted small" style={{ marginBottom: 8 }}>
            Louvain re-run with different resolution γ: a higher γ favours more, smaller communities. Q is always measured at γ = 1 so the points are comparable.
            A flat, high peak around γ = 1 means the community structure does not depend on one lucky setting.
          </div>
          {modularity.resolution_sweep?.length > 1 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={modularity.resolution_sweep} margin={{ top: 8, right: 24, bottom: 20, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="resolution" label={{ value: 'resolution γ', position: 'insideBottom', offset: -10, fontSize: 12 }} />
                <YAxis yAxisId="q" domain={[0, 1]} label={{ value: 'Modularity Q', angle: -90, position: 'insideLeft', fontSize: 11 }} />
                <YAxis yAxisId="n" orientation="right" allowDecimals={false} label={{ value: '# communities', angle: 90, position: 'insideRight', fontSize: 11 }} />
                <Tooltip />
                <Legend verticalAlign="top" />
                <ReferenceLine yAxisId="q" x={1} stroke="#94a3b8" strokeDasharray="4 4" />
                <ReferenceLine yAxisId="q" y={0.3} stroke="#f59e0b" strokeDasharray="5 4" />
                <Line yAxisId="q" type="monotone" dataKey="modularity" name="Modularity Q" stroke="#2563eb" strokeWidth={2} dot={{ r: 4 }} />
                <Line yAxisId="n" type="monotone" dataKey="num_communities" name="Communities" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : <div className="emptyviz">Resolution sweep not available for this graph.</div>}
        </div>
      )}

      {tab === 'how' && (
        <div className="adv-info-box" style={{ lineHeight: 1.7 }}>
          <b>Modularity</b> measures how much better a division into communities is than chance. For this graph, total edge weight <b>m = {f(modularity.total_weight, 2)}</b> ({modularity.n_edges.toLocaleString()} edges):
          <div className="formula">Q = Σ<sub>c</sub> [ L<sub>c</sub> / m − ( d<sub>c</sub> / 2m )² ]</div>
          <ul style={{ margin: '4px 0 8px 18px' }}>
            <li><b>L<sub>c</sub></b>: total similarity (edge weight) of the links that stay inside community c.</li>
            <li><b>d<sub>c</sub></b>: sum of the weighted degrees of the members of c.</li>
            <li><b>L<sub>c</sub>/m</b> is what the communities actually capture; <b>(d<sub>c</sub>/2m)²</b> is what a random network with the same degrees would capture.</li>
          </ul>
          Q near 0 means no better than chance; above about 0.3 is meaningful community structure and above 0.5 is strong. The random baseline shown on the Overview
          shuffles the community labels (same sizes) to show what "no structure" looks like on this very graph.
          {cur && <div style={{ marginTop: 8 }}><b>Worked example ({ALGO_LABELS[cur.algorithm] || cur.algorithm}):</b> inside-community share {f(cur.intra_weight_share)} − expected {f(cur.expected_share)} = <b>Q {f(cur.modularity)}</b>.</div>}
        </div>
      )}
    </div>
  );
}