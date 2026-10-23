import { useEffect, useState } from 'react';
import { api } from '../api.js';
import ChartView from './ChartView.jsx';

export default function AutoCharts({ datasetId, fileId }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ loading: true, data: null, error: null });
    api.autoCharts(datasetId, fileId)
      .then((data) => live && setState({ loading: false, data, error: null }))
      .catch((e) => live && setState({ loading: false, data: null, error: e.message }));
    return () => { live = false; };
  }, [datasetId, fileId]);

  if (state.loading) return <div className="card row"><span className="spinner" /> Analysing the file...</div>;
  if (state.error) return <div className="alert err">{state.error}</div>;
  const { charts, rows_analysed, partial } = state.data;
  return (
    <div>
      {partial && <div className="alert info">Large file: automatic charts use the first {rows_analysed.toLocaleString()} rows. Use the chart builder below for full-file aggregations.</div>}
      {charts.length === 0 && <div className="alert warn">No automatic charts could be made for this file. Try the chart builder below.</div>}
      <div className="grid g2">
        {charts.map((c) => (
          <div className="card" key={c.id} style={c.kind === 'correlation' ? { gridColumn: '1 / -1' } : undefined}>
            <h3>{c.title}</h3><ChartView chart={c} />
          </div>
        ))}
      </div>
    </div>
  );
}
