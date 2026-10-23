export default function DataTable({ rows, columns }) {
  if (!rows?.length) return <p className="muted">No rows.</p>;
  const cols = columns || Object.keys(rows[0]);
  return (
    <div className="tablewrap">
      <table>
        <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{r[c] == null ? <span className="muted">null</span> : String(r[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
