import { useMemo, useState } from 'react';
import {
  ResponsiveContainer, PieChart, Pie, Cell, ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid,
  Tooltip, ReferenceLine,
} from 'recharts';
import { OUTLIER } from '../util.js';
import { boxStats, commColor, fmt, isDimmed, liftColor, logTicks, shareColor, tierCutoffs } from './viz.js';

const Tip = ({ title, lines }) => (
  <div className="vtip"><b>{title}</b>{lines.map((l, i) => <div key={i}>{l}</div>)}</div>
);

/* ------------------------------------------------------------------ pipeline: what happened, in numbers */
export function PipelineFlow({ result }) {
  const s = result.summary;
  const steps = result.pipeline || [
    { key: 'matrix', title: '1. Entity x behavior matrix', text: `${s.total_entities_in_data.toLocaleString()} entities, one row each; columns are behavior categories; cells are total activity.` },
    { key: 'sample', title: '2. Sample', text: `${s.sampled_entities.toLocaleString()} entities analysed.` },
    { key: 'graph', title: '3. Similarity graph', text: `Cosine similarity on scaled values: ${s.edges.toLocaleString()} edges; unconnected entities dropped.` },
    { key: 'communities', title: '4. Communities', text: `${s.primary_algorithm} found ${s.communities} groups.` },
    { key: 'tiers', title: '5. Tiers', text: 'Communities ranked by average total activity, split into 3 tiers; entities inherit their community tier.' },
  ];
  const max = s.total_entities_in_data || 1;
  const funnel = [
    ['In the data', s.total_entities_in_data],
    ['Analysed (sample)', s.sampled_entities],
    ['Connected in graph', s.connected_nodes],
  ];
  return (
    <>
      <div className="flow">{steps.map((st) => <div className="stepbox" key={st.key}><b>{st.title}</b>{st.text}</div>)}</div>
      <div className="funnel">
        {funnel.map(([l, v]) => (
          <div key={l} className="bar" style={{ width: `${Math.max(8, (100 * v) / max)}%` }}>{`${l}: ${v.toLocaleString()}`}</div>
        ))}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ tiers: donut + clickable legend */
export function TierDonut({ tiers, counts, communities, colors, selTier, onPickTier }) {
  const total = tiers.reduce((a, t) => a + (counts[t] || 0), 0) || 1;
  const data = tiers.map((t) => ({ name: t, value: counts[t] || 0 }));
  const commCount = (t) => communities.filter((c) => c.tier === t).length;
  return (
    <div className="grid g2" style={{ alignItems: 'center' }}>
      <div style={{ position: 'relative' }}>
        <ResponsiveContainer width="100%" height={230}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="90%" paddingAngle={2}
              onClick={(d) => onPickTier(d.name)} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.name} fill={colors[d.name] || '#64748b'} cursor="pointer"
                  fillOpacity={selTier && selTier !== d.name ? 0.25 : 1} />
              ))}
            </Pie>
            <Tooltip content={({ active, payload }) => active && payload?.length ? (
              <Tip title={payload[0].name} lines={[`${payload[0].value} entities (${((100 * payload[0].value) / total).toFixed(1)}%)`, `${commCount(payload[0].name)} communities`, 'Click to filter all charts']} />) : null} />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', flexDirection: 'column' }}>
          <div style={{ fontSize: 15, fontWeight: 700, textAlign: 'center' }}>{`${total.toLocaleString()} entities`}</div>
          <div className="muted small">tiered</div>
        </div>
      </div>
      <div className="tierlist">
        {tiers.map((t) => (
          <div key={t} className={`tieritem ${selTier === t ? 'on' : ''} ${selTier && selTier !== t ? 'dim' : ''}`} onClick={() => onPickTier(t)}>
            <span className="dotc" style={{ background: colors[t] || '#64748b' }} />
            <span className="nm">{t}</span>
            <span className="ct"><b>{counts[t] || 0}</b> entities ({((100 * (counts[t] || 0)) / total).toFixed(0)}%)<br />{commCount(t)} communities</span>
          </div>
        ))}
        <div className="muted small">Click a tier to filter every chart below.</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ tier distribution (box plot, hand-drawn SVG) */
export function TierBox({ nodes, tiers, colors, selTier }) {
  const [log, setLog] = useState(true);
  const [hover, setHover] = useState(null);
  const rows = useMemo(() => tiers.map((t) => ({ t, st: boxStats(nodes.filter((n) => n.tier === t).map((n) => n.total)) })).filter((r) => r.st), [nodes, tiers]);
  if (!rows.length) return null;
  const W = 640, L = 170, R = 34, rowH = 46, H = rows.length * rowH + 40;
  const lo = Math.min(...rows.map((r) => r.st.min)), hi = Math.max(...rows.map((r) => r.st.max));
  const f = (v) => (log ? Math.log10(Math.max(v, 1)) : v);
  const a = f(Math.max(lo, log ? 1 : 0)), b = f(hi) || 1;
  const x = (v) => L + ((f(Math.max(v, log ? 1 : 0)) - a) / (b - a || 1)) * (W - L - R);
  const ticks = log ? logTicks(Math.max(lo, 1), hi).filter((_, i, arr) => arr.length < 8 || i % 2 === 0)
    : [0, 0.25, 0.5, 0.75, 1].map((q) => lo + q * (hi - lo));
  return (
    <div>
      <div className="row between" style={{ marginBottom: 6 }}>
        <span className="muted small">Total activity of each entity, grouped by tier. Box = middle 50%, line = median, dot = mean.</span>
        <div className="seg"><button className={log ? 'on' : ''} onClick={() => setLog(true)}>log scale</button><button className={!log ? 'on' : ''} onClick={() => setLog(false)}>linear</button></div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
        {ticks.map((tv) => (<g key={tv}><line x1={x(tv)} x2={x(tv)} y1={6} y2={H - 28} stroke="#e2e8f0" /><text x={x(tv)} y={H - 12} fontSize="10" textAnchor="middle" fill="#64748b">{fmt(tv, 0)}</text></g>))}
        {rows.map(({ t, st }, i) => {
          const y = 14 + i * rowH, c = colors[t] || '#64748b', dim = selTier && selTier !== t;
          return (
            <g key={t} opacity={dim ? 0.25 : 1} onMouseEnter={() => setHover({ t, st })} onMouseLeave={() => setHover(null)}>
              <text x={L - 10} y={y + 14} fontSize="12" textAnchor="end" fill="#0f172a" fontWeight="600">{t.length > 24 ? `${t.slice(0, 23)}…` : t}</text>
              <line x1={x(st.min)} x2={x(st.max)} y1={y + 10} y2={y + 10} stroke={c} strokeWidth="2" />
              <rect x={x(st.q1)} y={y} width={Math.max(2, x(st.q3) - x(st.q1))} height={20} fill={c} fillOpacity=".25" stroke={c} rx="3" />
              <line x1={x(st.median)} x2={x(st.median)} y1={y} y2={y + 20} stroke={c} strokeWidth="3" />
              <circle cx={x(st.mean)} cy={y + 10} r="3.5" fill="#fff" stroke={c} strokeWidth="2" />
              <rect x={L} y={y - 6} width={W - L - R} height={32} fill="transparent" />
            </g>
          );
        })}
      </svg>
      <div className="hminfo">{hover ? <><b>{hover.t}</b>: min {fmt(hover.st.min, 0)} · median {fmt(hover.st.median, 0)} · mean {fmt(hover.st.mean, 0)} · max {fmt(hover.st.max, 0)} ({hover.st.n} entities)</> : <span className="muted">Hover a row for exact values.</span>}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ community bubble chart: size vs activity */
export function CommunityBubble({ communities, tiers, colors, labels, selComm, selTier, onPickComm }) {
  const cut = useMemo(() => tierCutoffs(communities, labels), [communities, labels]);
  const pts = communities.map((c) => ({ ...c, y: Math.max(c.avg_total_activity, 0.1) }));
  const ys = pts.map((p) => p.y), xs = pts.map((p) => p.size);
  const yd = [Math.min(...ys) / 1.6, Math.max(...ys) * 1.6], xd = [Math.max(0.7, Math.min(...xs) / 1.6), Math.max(...xs) * 1.6];
  return (
    <div>
      <ResponsiveContainer width="100%" height={340}>
        <ScatterChart margin={{ left: 8, right: 24, top: 12, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" dataKey="size" name="members" scale="log" domain={xd} ticks={logTicks(xd[0], xd[1])} allowDataOverflow tickFormatter={(v) => fmt(v, 0)}
            label={{ value: 'community size (members, log scale)', position: 'insideBottom', offset: -12, fontSize: 12 }} />
          <YAxis type="number" dataKey="y" name="avg activity" scale="log" domain={yd} ticks={logTicks(yd[0], yd[1])} allowDataOverflow tickFormatter={(v) => fmt(v, 0)}
            label={{ value: 'average total activity (log)', angle: -90, position: 'insideLeft', fontSize: 12 }} />
          <ZAxis type="number" dataKey="size" range={[90, 900]} />
          {cut.low != null && <ReferenceLine y={cut.low} stroke="#94a3b8" strokeDasharray="5 4" label={{ value: 'low | moderate', position: 'insideTopLeft', fontSize: 10, fill: '#64748b' }} />}
          {cut.high != null && <ReferenceLine y={cut.high} stroke="#94a3b8" strokeDasharray="5 4" label={{ value: 'moderate | high', position: 'insideTopLeft', fontSize: 10, fill: '#64748b' }} />}
          <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ active, payload }) => {
            const c = active && payload?.[0]?.payload; if (!c) return null;
            return <Tip title={`Community ${c.community_id} · ${c.tier}`} lines={[`${c.size} members`, `avg activity ${fmt(c.avg_total_activity, 0)}`, c.cohesion != null ? `cohesion ${fmt(c.cohesion, 2)}` : null, `top: ${c.top_behavior}`, 'Click to select'].filter(Boolean)} />;
          }} />
          <Scatter data={pts} isAnimationActive={false}>
            {pts.map((p) => (
              <Cell key={p.community_id} cursor="pointer" fill={colors[p.tier] || '#64748b'} fillOpacity={isDimmed(p, selComm, selTier) ? 0.12 : 0.7}
                stroke={selComm === p.community_id ? '#0f172a' : colors[p.tier]} strokeWidth={selComm === p.community_id ? 3 : 1}
                onClick={() => onPickComm(p.community_id)} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="muted small">Each bubble is a community (bubble area = members). Dashed lines show where the tier boundaries fall. A small bubble far from the others is an outlier group whose tier rests on very few entities.</div>
    </div>
  );
}

/* ------------------------------------------------------------------ community x behavior heatmap */
export function ProfileHeatmap({ communities, behaviors, colors, selComm, selTier, onPickComm }) {
  const [mode, setMode] = useState('lift');
  const [hover, setHover] = useState(null);
  if (!behaviors?.length || !communities.some((c) => c.profile)) {
    return <div className="emptyviz">Behavior fingerprints are not in this result. Re-run the analysis to see what each community actually does.</div>;
  }
  const overall = Object.fromEntries(behaviors.map((b) => [b.name, b.overall_mean]));
  const rows = [...communities].sort((a, b) => b.avg_total_activity - a.avg_total_activity);
  const cell = (c, b) => {
    const v = c.profile?.[b.name] ?? 0;
    if (mode === 'lift') { const lift = overall[b.name] > 0 ? v / overall[b.name] : null; return { v, lift, color: liftColor(lift), label: lift == null ? '' : lift >= 10 ? Math.round(lift) : lift.toFixed(1) }; }
    const tot = Object.values(c.profile).reduce((a, x) => a + x, 0) || 1; const share = v / tot;
    return { v, share, color: shareColor(share), label: share >= 0.05 ? `${Math.round(share * 100)}` : '' };
  };
  return (
    <div>
      <div className="row between" style={{ marginBottom: 8 }}>
        <span className="muted small">Rows = communities (busiest first), columns = behaviors. Click a row to select the community.</span>
        <div className="seg">
          <button className={mode === 'lift' ? 'on' : ''} onClick={() => setMode('lift')}>vs. average (×)</button>
          <button className={mode === 'share' ? 'on' : ''} onClick={() => setMode('share')}>share of activity (%)</button>
        </div>
      </div>
      <div className="tablewrap" style={{ maxHeight: 520 }}>
        <table className="hm">
          <thead><tr><th />{behaviors.map((b) => <th key={b.name} title={b.name}><span>{b.name}</span></th>)}</tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.community_id} className={`${selComm === c.community_id ? 'sel' : ''} ${isDimmed(c, selComm, selTier) ? 'dim' : ''}`}>
                <th onClick={() => onPickComm(c.community_id)}>
                  <span className="dotc" style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: colors[c.tier] || '#64748b', marginRight: 6 }} />
                  C{c.community_id} <span className="muted small">n={c.size}</span>
                </th>
                {behaviors.map((b) => {
                  const d = cell(c, b);
                  return <td key={b.name} className="cell" style={{ background: d.color, color: (d.lift ?? 0) > 2.2 || (d.share ?? 0) > 0.4 ? '#fff' : '#0f172a' }}
                    onMouseEnter={() => setHover({ c, b, d })} onMouseLeave={() => setHover(null)} onClick={() => onPickComm(c.community_id)}>{d.label}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="hminfo">
        {hover ? <><b>Community {hover.c.community_id}</b> · {hover.b.name}: {fmt(hover.d.v, 1)} per entity on average
          {hover.d.lift != null && <> = <b>{hover.d.lift.toFixed(2)}×</b> the overall average ({fmt(hover.b.overall_mean, 1)})</>}
          {hover.d.share != null && <> = <b>{(hover.d.share * 100).toFixed(1)}%</b> of this community's activity</>}</> : <span className="muted">Hover a cell for the exact number.</span>}
      </div>
      <div className="hmscale">{mode === 'lift' ? <><span>0.25× less</span><i /><span>4× more than average</span></> : <><span>0%</span><i className="share" /><span>100% of the community's activity</span></>}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ PCA entity map */
export function EntityMap({ nodes, pca, colors, colorBy, setColorBy, selComm, selTier, onPickComm }) {
  const has = nodes.length && nodes[0].x != null;
  if (!has) return <div className="emptyviz">The entity map needs a newer result. Re-run the analysis.</div>;
  const ev = pca?.explained || [0, 0];
  const color = (n) => (colorBy === 'tier' ? colors[n.tier] || '#64748b' : commColor(n.community));
  return (
    <div>
      <div className="row between" style={{ marginBottom: 6 }}>
        <span className="muted small">Every dot is one entity placed by how it behaves (PCA of its scaled activity). Close dots behave alike.</span>
        <div className="seg"><button className={colorBy === 'tier' ? 'on' : ''} onClick={() => setColorBy('tier')}>colour by tier</button><button className={colorBy === 'community' ? 'on' : ''} onClick={() => setColorBy('community')}>colour by community</button></div>
      </div>
      <ResponsiveContainer width="100%" height={380}>
        <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" dataKey="x" tick={false} domain={['auto', 'auto']} label={{ value: `PC1 (${(ev[0] * 100).toFixed(0)}% of variation)`, position: 'insideBottom', offset: -8, fontSize: 12 }} />
          <YAxis type="number" dataKey="y" tick={false} domain={['auto', 'auto']} label={{ value: `PC2 (${(ev[1] * 100).toFixed(0)}%)`, angle: -90, position: 'insideLeft', fontSize: 12 }} />
          <ZAxis range={[36, 36]} />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ active, payload }) => {
            const n = active && payload?.[0]?.payload; if (!n) return null;
            return <Tip title={`Entity ${n.id}`} lines={[`community ${n.community}`, n.tier, `total activity ${fmt(n.total, 0)}`]} />;
          }} />
          <Scatter data={nodes} isAnimationActive={nodes.length < 1500}>
            {nodes.map((n) => <Cell key={n.id} cursor="pointer" fill={color(n)} fillOpacity={isDimmed(n, selComm, selTier) ? 0.08 : 0.75} onClick={() => onPickComm(n.community)} />)}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="muted small">The two axes capture {((ev[0] + ev[1]) * 100).toFixed(0)}% of all variation, so some overlap between communities is normal in a flat 2-D picture.</div>
    </div>
  );
}

/* ------------------------------------------------------------------ community detail panel */
export function CommunityDetail({ c, behaviors, colors, onClear }) {
  if (!c) return <div className="emptyviz">Select a community (click a bubble, a dot, a heatmap row, a table row or a graph node) to see what defines it.</div>;
  const overall = Object.fromEntries((behaviors || []).map((b) => [b.name, b.overall_mean]));
  const prof = c.profile ? Object.entries(c.profile).sort((a, b) => b[1] - a[1]).slice(0, 8) : [];
  const maxV = prof.length ? prof[0][1] || 1 : 1;
  const coh = c.cohesion;
  const cohText = coh == null ? 'single member' : coh >= 0.9 ? 'very tight' : coh >= 0.75 ? 'tight' : coh >= 0.5 ? 'mixed' : 'loose';
  return (
    <div className="detail">
      <div className="row between"><h3><span className="badge" style={{ background: colors[c.tier] || '#64748b' }}>{c.tier}</span> Community {c.community_id}</h3><button className="ghost" onClick={onClear}>Clear selection</button></div>
      <div className="kv">
        <div><b>{c.size}</b><span>members</span></div>
        <div><b>{fmt(c.avg_total_activity, 0)}</b><span>average total activity</span></div>
        <div><b>{c.median_total_activity != null ? fmt(c.median_total_activity, 0) : '-'}</b><span>median total activity</span></div>
        <div><b>{c.min_total_activity != null ? `${fmt(c.min_total_activity, 0)} – ${fmt(c.max_total_activity, 0)}` : '-'}</b><span>activity range</span></div>
        <div><b>{coh != null ? fmt(coh, 2) : '-'}</b><span>cohesion ({cohText})</span></div>
        <div><b>{c.top_behavior}</b><span>top behavior</span></div>
      </div>
      {prof.length > 0 && (<>
        <div className="muted small" style={{ marginBottom: 4 }}>What members do (average per entity; × = compared with everyone)</div>
        {prof.map(([name, v]) => (
          <div className="hbar" key={name}>
            <span className="nm" title={name}>{name}</span>
            <div className="track"><div className="fill" style={{ width: `${(100 * v) / maxV}%` }} /></div>
            <span>{fmt(v, 0)}{overall[name] > 0 ? ` · ${(v / overall[name]).toFixed(1)}×` : ''}</span>
          </div>
        ))}
      </>)}
      {c.size <= 2 && <div className="alert warn" style={{ marginTop: 10 }}>Only {c.size} member(s): this tier is based on very few entities.</div>}
    </div>
  );
}

export { OUTLIER };