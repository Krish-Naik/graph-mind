import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api.js';
import Dropzone from '../components/Dropzone.jsx';
import DataTable from '../components/DataTable.jsx';
import AutoCharts from '../components/AutoCharts.jsx';
import ChartBuilder from '../components/ChartBuilder.jsx';
import Wizard from '../behavioral/Wizard.jsx';
import { RunCommunityGraphs } from '../behavioral/CommunityGraphs.jsx';
import Results from '../behavioral/Results.jsx';
import { bytes, num } from '../util.js';

function Overview({ profile }) {
  return (
    <>
      <div className="grid g3" style={{ marginBottom: 16 }}>
        <div className="card stat"><div className="v">{profile.rows.toLocaleString()}</div><div className="l">rows</div></div>
        <div className="card stat"><div className="v">{profile.columns.length}</div><div className="l">columns</div></div>
        <div className="card stat"><div className="v">{profile.columns.filter((c) => c.numeric).length}</div><div className="l">numeric columns</div></div>
      </div>
      <div className="card"><h2>Columns</h2>
        <div className="tablewrap"><table>
          <thead><tr><th>name</th><th>type</th><th>distinct (approx)</th><th>nulls (sample)</th><th>min</th><th>max</th><th>mean</th><th>top values</th></tr></thead>
          <tbody>{profile.columns.map((c) => (
            <tr key={c.name}><td><b>{c.name}</b></td><td>{c.type}</td><td>{c.approx_distinct.toLocaleString()}</td><td>{c.nulls_in_sample}</td>
              <td>{c.numeric ? num(c.min) : ''}</td><td>{c.numeric ? num(c.max) : ''}</td><td>{c.numeric ? num(c.mean) : ''}</td>
              <td>{c.top_values?.slice(0, 4).map((t) => `${t.value} (${t.count})`).join(', ')}</td></tr>
          ))}</tbody>
        </table></div></div>
      <div className="card"><h2>Preview (first rows)</h2><DataTable rows={profile.preview} columns={profile.columns.map((c) => c.name)} /></div>
    </>
  );
}

export default function Dataset() {
  const { id } = useParams();
  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);
  const [fileId, setFileId] = useState(null);
  const [tab, setTab] = useState('overview');
  const [profiles, setProfiles] = useState({});
  const [profErr, setProfErr] = useState(null);
  const [openJob, setOpenJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [adding, setAdding] = useState(false);

  const reload = useCallback(() => api.dataset(id).then((d) => { setDs(d); setFileId((f) => f || d.files[0]?.id); }).catch((e) => setError(e.message)), [id]);
  useEffect(() => { reload(); }, [reload]);
  const loadJobs = useCallback(() => api.jobs(id).then(setJobs).catch(() => {}), [id]);
  useEffect(() => { loadJobs(); }, [loadJobs, tab]);

  // profile every file once (needed by the wizard for column dropdowns)
  useEffect(() => {
    if (!ds) return;
    ds.files.filter((f) => !profiles[f.id]).forEach((f) =>
      api.profile(id, f.id).then((p) => setProfiles((s) => ({ ...s, [f.id]: p }))).catch((e) => setProfErr(`${f.originalName}: ${e.message}`)));
  }, [ds, id]); // eslint-disable-line

  async function addFiles(files) {
    setAdding(true);
    try { setDs(await api.addFiles(id, files)); } catch (e) { setError(e.message); } finally { setAdding(false); }
  }

  if (error) return <div className="alert err">{error} <Link to="/">Back</Link></div>;
  if (!ds) return <div className="row"><span className="spinner" /> Loading...</div>;
  const file = ds.files.find((f) => f.id === fileId);
  const profile = profiles[fileId];
  const TABS = [['overview', 'Overview'], ['explore', 'Graphical analysis'], ['behavioral', 'Behavioral analysis'], ['runs', `Past runs (${jobs.length})`]];

  return (
    <>
      <div className="row between"><div><Link to="/">&larr; All datasets</Link><h1>{ds.name}</h1></div></div>
      <div className="card">
        <div className="row">
          <div><label>Active file</label>
            <select value={fileId} onChange={(e) => setFileId(e.target.value)} style={{ minWidth: 260 }}>
              {ds.files.map((f) => <option key={f.id} value={f.id}>{f.originalName} ({bytes(f.size)})</option>)}
            </select></div>
          <div style={{ flex: 1, minWidth: 260 }}><Dropzone compact onFiles={addFiles} hint={adding ? 'Uploading...' : 'Add more files to this dataset (lookup tables, labels...)'} /></div>
        </div>
      </div>
      {profErr && <div className="alert err">{profErr}</div>}
      <div className="tabs">{TABS.map(([k, l]) => <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>

      {tab === 'overview' && (profile ? <Overview profile={profile} /> : <div className="row"><span className="spinner" /> Profiling {file?.originalName}...</div>)}
      {tab === 'explore' && (profile ? (
        <>
          <RunCommunityGraphs key={`cg${id}`} datasetId={id} onGoBehavioral={() => setTab('behavioral')} />
          <AutoCharts key={fileId} datasetId={id} fileId={fileId} />
          <ChartBuilder key={`b${fileId}`} datasetId={id} fileId={fileId} columns={profile.columns} />
        </>
      ) : <div className="row"><span className="spinner" /> Profiling...</div>)}
      <div style={{ display: tab === 'behavioral' ? 'block' : 'none' }}>
        <Wizard datasetId={id} files={ds.files} profiles={profiles} activeFileId={fileId} onFinished={loadJobs} />
      </div>
      {tab === 'runs' && (
        openJob ? (
          <><button className="ghost" onClick={() => setOpenJob(null)}>&larr; Back to list</button><div style={{ marginTop: 12 }}><Results jobId={openJob} /></div></>
        ) : (
          <div className="card">
            {jobs.length === 0 ? <p className="muted">No runs yet. Use the Behavioral analysis tab.</p> : (
              <table><thead><tr><th>when</th><th>status</th><th>communities</th><th>nodes</th><th>algorithm</th><th /></tr></thead>
                <tbody>{jobs.map((j) => (
                  <tr key={j.id}><td>{new Date(j.createdAt).toLocaleString()}</td><td>{j.status}</td>
                    <td>{j.summary?.communities ?? '-'}</td><td>{j.summary?.connected_nodes ?? '-'}</td><td>{j.summary?.primary_algorithm ?? '-'}</td>
                    <td><button className="ghost" onClick={() => setOpenJob(j.id)}>Open</button></td></tr>
                ))}</tbody></table>
            )}
          </div>
        )
      )}
    </>
  );
}