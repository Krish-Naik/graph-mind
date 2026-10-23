import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, ScatterChart, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { PALETTE, num } from '../util.js';

function Heatmap({ columns, matrix }) {
  const color = (v) => (v == null ? '#f1f5f9' : v >= 0 ? `rgba(37,99,235,${Math.abs(v)})` : `rgba(220,38,38,${Math.abs(v)})`);
  return (
    <div className="tablewrap">
      <table className="heat">
        <thead><tr><th />{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={i}>
              <th>{columns[i]}</th>
              {row.map((v, j) => <td key={j} style={{ background: color(v), color: Math.abs(v ?? 0) > 0.55 ? '#fff' : '#0f172a' }}>{v == null ? '-' : v.toFixed(2)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Renders any chart object returned by the engine ({kind, rows, groups, x, y, agg}). */
export default function ChartView({ chart, height = 280 }) {
  const { kind, rows, groups } = chart;
  if (kind === 'correlation') return <Heatmap columns={chart.columns} matrix={chart.matrix} />;
  if (!rows?.length) return <p className="muted">No data to show.</p>;
  const yLabel = chart.agg === 'count' || !chart.y ? 'count' : `${chart.agg}(${chart.y})`;
  const keys = groups?.length ? groups : ['value'];
  const stack = chart.agg === 'count' || chart.agg === 'sum' ? 's' : undefined;

  let body;
  if (kind === 'pie') {
    body = (
      <PieChart>
        <Pie data={rows.slice(0, 10)} dataKey="value" nameKey="x" outerRadius="80%" label>
          {rows.slice(0, 10).map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
        </Pie>
        <Tooltip formatter={(v) => num(v)} /><Legend />
      </PieChart>
    );
  } else if (kind === 'scatter') {
    body = (
      <ScatterChart margin={{ left: 8, right: 16, top: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="x" type="number" name={chart.x} domain={['auto', 'auto']} tickFormatter={(v) => num(v, 1)} />
        <YAxis dataKey="y" type="number" name={chart.y} domain={['auto', 'auto']} tickFormatter={(v) => num(v, 1)} />
        <Tooltip cursor={{ strokeDasharray: '3 3' }} />
        <Scatter data={rows} fill={PALETTE[0]} fillOpacity={0.55} />
      </ScatterChart>
    );
  } else if (kind === 'line') {
    body = (
      <LineChart data={rows} margin={{ left: 8, right: 16, top: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="x" minTickGap={30} /><YAxis tickFormatter={(v) => num(v, 1)} />
        <Tooltip formatter={(v) => num(v)} />{groups?.length ? <Legend /> : null}
        {keys.map((k, i) => <Line key={k} type="monotone" dataKey={k} name={groups?.length ? k : yLabel} stroke={PALETTE[i % PALETTE.length]} dot={rows.length < 40} strokeWidth={2} connectNulls />)}
      </LineChart>
    );
  } else { // bar + histogram
    const hist = kind === 'histogram';
    body = (
      <BarChart data={rows} margin={{ left: 8, right: 16, top: 8, bottom: rows.length > 8 ? 30 : 0 }} barCategoryGap={hist ? 1 : '20%'}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="x" interval={rows.length > 24 ? 'preserveStartEnd' : 0} angle={rows.length > 8 && !hist ? -30 : 0} textAnchor={rows.length > 8 && !hist ? 'end' : 'middle'} height={rows.length > 8 && !hist ? 60 : 30} />
        <YAxis tickFormatter={(v) => num(v, 1)} />
        <Tooltip formatter={(v) => num(v)} />{groups?.length ? <Legend /> : null}
        {keys.map((k, i) => <Bar key={k} dataKey={k} name={groups?.length ? k : (hist ? 'rows' : yLabel)} stackId={stack} fill={PALETTE[i % PALETTE.length]} />)}
      </BarChart>
    );
  }
  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>{body}</ResponsiveContainer>
      {chart.note && <div className="muted small">{chart.note}</div>}
    </div>
  );
}
