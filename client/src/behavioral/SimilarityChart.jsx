import { useMemo, useState } from 'react';
import { ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid, Legend } from 'recharts';
import { pairsAbove } from '../util.js';

/**
 * Two views that explain the threshold (tau):
 *  - Distribution: how similar are entity pairs? (area) and what share of pairs are >= x (line)
 *  - Trade-off: edges and connected entities for every possible tau (from the engine's sweep)
 * The red line is the tau used in the run, placed at its exact value.
 */
export default function SimilarityChart({ hist, threshold, sweep }) {
  const [view, setView] = useState('dist');
  const total = useMemo(() => hist.counts.reduce((a, b) => a + b, 0) || 1, [hist]);
  const dist = useMemo(() => {
    let rest = total;
    return hist.counts.map((c, i) => { const row = { x: hist.bins[i], count: c, pct_above: +((100 * rest) / total).toFixed(2) }; rest -= c; return row; });
  }, [hist, total]);
  const mark = threshold != null ? (
    <ReferenceLine yAxisId="l" x={threshold} stroke="#dc2626" strokeWidth={2} ifOverflow="extendDomain"
      label={{ value: `threshold ${threshold}`, fill: '#dc2626', position: 'insideTopLeft', fontSize: 11 }} />) : null;
  const tip = (rows) => ({ active, payload, label }) => (active && payload?.length ? (
    <div className="vtip"><b>{rows.title(label)}</b>{payload.map((p) => <div key={p.dataKey} style={{ color: p.color }}>{rows.name[p.dataKey] || p.dataKey}: {Number(p.value).toLocaleString()}{rows.unit[p.dataKey] || ''}</div>)}</div>) : null);

  return (
    <div>
      <div className="row between" style={{ marginBottom: 6 }}>
        <span className="muted small">{view === 'dist' ? 'How alike are pairs of entities?' : 'What does each threshold cost?'}</span>
        <div className="seg">
          <button className={view === 'dist' ? 'on' : ''} onClick={() => setView('dist')}>distribution</button>
          <button className={view === 'sweep' ? 'on' : ''} disabled={!sweep?.length} onClick={() => setView('sweep')}>threshold trade-off</button>
        </div>
      </div>
      {view === 'dist' ? (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={dist} margin={{ left: 8, right: 8, top: 14, bottom: 14 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" dataKey="x" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} label={{ value: 'cosine similarity between two entities', position: 'insideBottom', offset: -10, fontSize: 11 }} height={48} />
            <YAxis yAxisId="l" tickFormatter={(v) => v.toLocaleString()} />
            <YAxis yAxisId="r" orientation="right" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
            <Tooltip content={tip({ title: (l) => `similarity from ${Number(l).toFixed(3)}`, name: { count: 'entity pairs in this bin', pct_above: 'pairs at or above this similarity' }, unit: { pct_above: '%' } })} />
            <Legend verticalAlign="top" height={24} formatter={(v) => (v === 'count' ? 'pairs per bin' : '% of pairs at or above')} />
            <Area yAxisId="l" type="stepAfter" dataKey="count" stroke="#2563eb" fill="#93c5fd" fillOpacity={0.6} isAnimationActive={false} />
            <Line yAxisId="r" type="monotone" dataKey="pct_above" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
            {mark}
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={sweep} margin={{ left: 8, right: 8, top: 14, bottom: 14 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" dataKey="tau" domain={[0.3, 1]} label={{ value: 'threshold (tau)', position: 'insideBottom', offset: -10, fontSize: 11 }} height={48} />
            <YAxis yAxisId="l" tickFormatter={(v) => v.toLocaleString()} />
            <YAxis yAxisId="r" orientation="right" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
            <Tooltip content={tip({ title: (l) => `threshold ${l}`, name: { edges: 'edges in the graph', connected_pct: 'entities that keep at least one edge' }, unit: { connected_pct: '%' } })} />
            <Legend verticalAlign="top" height={24} formatter={(v) => (v === 'edges' ? 'edges' : '% entities still connected')} />
            <Line yAxisId="l" type="monotone" dataKey="edges" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line yAxisId="r" type="monotone" dataKey="connected_pct" stroke="#16a34a" strokeWidth={2} dot={false} isAnimationActive={false} />
            {mark}
          </ComposedChart>
        </ResponsiveContainer>
      )}
      <div className="muted small">
        {threshold != null && <>About {(pairsAbove(hist, threshold) * 100).toFixed(1)}% of all entity pairs have similarity at or above {threshold}. </>}
        {view === 'sweep' ? 'Raising the threshold removes edges and strands entities; lowering it blurs the communities together. Pick the point where most entities are still connected but the graph is not a hairball.'
          : `Percentiles: ${Object.entries(hist.percentiles).map(([p, v]) => `p${p}=${v}`).join(', ')}.`}
      </div>
    </div>
  );
}