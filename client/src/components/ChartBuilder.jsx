import { useState } from 'react';
import { api } from '../api.js';
import ChartView from './ChartView.jsx';

const KINDS = [['bar', 'Bar'], ['line', 'Line'], ['pie', 'Pie'], ['histogram', 'Histogram'], ['scatter', 'Scatter']];
const AGGS = ['count', 'sum', 'mean', 'min', 'max'];

export default function ChartBuilder({ datasetId, fileId, columns }) {
  const names = columns.map((c) => c.name);
  const nums = columns.filter((c) => c.numeric).map((c) => c.name);
  const [spec, setSpec] = useState({ kind: 'bar', x: names[0] || '', y: '', agg: 'count', group: '', bins: 20, limit: 20 });
  const [chart, setChart] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k, v) => setSpec((s) => ({ ...s, [k]: v }));
  const needsY = spec.kind === 'scatter' || (['bar', 'line', 'pie'].includes(spec.kind) && spec.agg !== 'count');

  async function draw() {
    setBusy(true); setError(null);
    try {
      const body = { ...spec, y: spec.y || null, group: spec.group || null, bins: Number(spec.bins), limit: Number(spec.limit) };
      if (!needsY) body.y = null;
      setChart(await api.chartQuery(datasetId, fileId, body));
    } catch (e) { setError(e.message); setChart(null); } finally { setBusy(false); }
  }

  const Sel = ({ k, options, blank }) => (
    <select value={spec[k]} onChange={(e) => set(k, e.target.value)}>
      {blank && <option value="">{blank}</option>}
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
  return (
    <div className="card">
      <h2>Chart builder</h2>
      <div className="grid g4">
        <div className="field"><label>Chart type</label>
          <select value={spec.kind} onChange={(e) => set('kind', e.target.value)}>{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
        <div className="field"><label>X axis</label><Sel k="x" options={spec.kind === 'histogram' ? nums : names} /></div>
        {['bar', 'line', 'pie'].includes(spec.kind) && <div className="field"><label>Aggregation</label><Sel k="agg" options={AGGS} /></div>}
        {needsY && <div className="field"><label>Y axis (numeric)</label><Sel k="y" options={nums} blank="choose..." /></div>}
        {['bar', 'line'].includes(spec.kind) && <div className="field"><label>Split by (optional)</label><Sel k="group" options={names} blank="none" /></div>}
        {spec.kind === 'histogram' && <div className="field"><label>Bins</label><input type="number" min="2" max="100" value={spec.bins} onChange={(e) => set('bins', e.target.value)} /></div>}
        {['bar', 'pie'].includes(spec.kind) && <div className="field"><label>Max categories</label><input type="number" min="1" max="200" value={spec.limit} onChange={(e) => set('limit', e.target.value)} /></div>}
      </div>
      <button onClick={draw} disabled={busy || !spec.x || (needsY && !spec.y)}>{busy ? 'Drawing...' : 'Draw chart'}</button>
      {error && <div className="alert err" style={{ marginTop: 12 }}>{error}</div>}
      {chart && <div style={{ marginTop: 16 }}><ChartView chart={chart} height={340} /></div>}
    </div>
  );
}
