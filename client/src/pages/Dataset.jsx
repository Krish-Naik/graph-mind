import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api.js';
import Dropzone from '../components/Dropzone.jsx';
import DataTable from '../components/DataTable.jsx';
import AutoCharts from '../components/AutoCharts.jsx';
import ChartBuilder from '../components/ChartBuilder.jsx';
import Wizard, { toMapping, toParams, guessLabel, guessLookup, mappingReady } from '../behavioral/Wizard.jsx';
import { RunCommunityGraphs } from '../behavioral/CommunityGraphs.jsx';
import Results from '../behavioral/Results.jsx';
import { PRESETS } from '../presets.js';
import { DEFAULT_TIERS, bytes, num } from '../util.js';

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

/**
 * Build a (mapping, params) pair from the available files and profiles without any user input:
 *   1. If a preset matches the files, use its mapping + params.
 *   2. Otherwise, fall back to the engine's behavioral_suggestion + guessLookup + guessLabel.
 * Returns null if no sensible mapping could be built.
 */
function autoBuildConfig(files, profiles) {
  const preset = PRESETS.find((p) => p.match(files));
  if (preset) {
    const built = preset.build(files);
    return {
      mapping: built.mapping,
      params: {
        sample_size: 300, graph_method: 'threshold', threshold: 0.85, knn_k: 10,
        algorithms: ['louvain', 'leiden', 'lpa'], leiden_resolution: 1.5, primary_algorithm: 'louvain',
        tier_method: 'quantile', tier_labels: [...DEFAULT_TIERS], low_cut: '', high_cut: '', min_community_size: 1,
        ...built.params,
      },
      source: `preset:${preset.id}`,
    };
  }
  // Generic auto-detection: pick the first file whose profile suggests an entity column.
  const mainFile = files.find((f) => profiles[f.id]?.behavioral_suggestion?.entity_col) || files[0];
  const prof = mainFile && profiles[mainFile.id];
  if (!prof) return null;
  const sug = prof.behavioral_suggestion || {};
  const mapping = {
    mainFileId: mainFile.id, format: 'long',
    entity_col: sug.entity_col || '', behavior_col: sug.behavior_col || '', value_col: sug.value_col || '',
    agg: sug.value_col ? 'sum' : 'count', feature_cols: [],
    useLookup: false, lookup: { fileId: '', source_key: '', lookup_key: '', split_delimiter: '' },
    useLabel: false, label: { fileId: '', entity_col: '', label_col: '' },
  };
  if (mapping.entity_col && !mapping.behavior_col) {
    const lk = guessLookup(files, profiles, mapping.mainFileId, mapping.entity_col);
    if (lk) {
      mapping.useLookup = true; mapping.behavior_col = lk.behavior;
      mapping.lookup = { fileId: lk.fileId, source_key: lk.key, lookup_key: lk.key, split_delimiter: '' };
    }
  }
  if (mapping.entity_col) {
    const lab = guessLabel(files, profiles, mapping.entity_col, mapping.mainFileId);
    if (lab) { mapping.useLabel = true; mapping.label = lab; }
  }
  if (!mappingReady(mapping)) return null;
  return {
    mapping,
    params: {
      sample_size: 300, graph_method: 'threshold', threshold: 0.85, knn_k: 10,
      algorithms: ['louvain', 'leiden', 'lpa'], leiden_resolution: 1.5, primary_algorithm: 'louvain',
      tier_method: 'quantile', tier_labels: [...DEFAULT_TIERS], low_cut: '', high_cut: '', min_community_size: 1,
    },
    source: 'auto-detected',
  };
}

export default function Dataset() {
  const { id } = useParams();
  const [search, setSearch] = useSearchParams();
  // URL flags coming from the Home page.
  //   ?auto=1       preset ON on the Home page: start on behavioral tab and auto-run.
  //   ?configure=1  preset OFF on the Home page: start on behavioral tab with the wizard open.
  const wantAuto = search.get('auto') === '1';
  const wantConfigure = search.get('configure') === '1';

  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);
  const [fileId, setFileId] = useState(null);
  const [tab, setTab] = useState(wantAuto || wantConfigure ? 'behavioral' : 'overview');
  const [profiles, setProfiles] = useState({});
  const [profErr, setProfErr] = useState(null);
  const [openJob, setOpenJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [adding, setAdding] = useState(false);

  // Auto-run bookkeeping. We only attempt a single auto-run per visit so a failed
  // auto-run does not spin forever, and reconfiguring is always an option.
  const [autoJobId, setAutoJobId] = useState(null);     // id of the job started by this visit
  const [autoErr, setAutoErr] = useState(null);
  const [autoConfig, setAutoConfig] = useState(null);   // {mapping, params, source}
  // When the user explicitly asks to reconfigure from the Behavioral tab,
  // override the "show latest job" default and surface the wizard instead.
  const [showWizard, setShowWizard] = useState(wantConfigure);
  const autoTried = useRef(false);

  const reload = useCallback(
    () => api.dataset(id).then((d) => { setDs(d); setFileId((f) => f || d.files[0]?.id); }).catch((e) => setError(e.message)),
    [id],
  );
  useEffect(() => { reload(); }, [reload]);
  const loadJobs = useCallback(() => api.jobs(id).then(setJobs).catch(() => {}), [id]);
  useEffect(() => { loadJobs(); }, [loadJobs, tab]);

  // Profile every file once (needed by the wizard, and by auto-run for column suggestions).
  useEffect(() => {
    if (!ds) return;
    ds.files.filter((f) => !profiles[f.id]).forEach((f) =>
      api.profile(id, f.id).then((p) => setProfiles((s) => ({ ...s, [f.id]: p }))).catch((e) => setProfErr(`${f.originalName}: ${e.message}`)));
  }, [ds, id]); // eslint-disable-line

  // Auto-run flow, only when the Home page sent us here with ?auto=1 AND there is no
  // existing finished job for this dataset. Needs every file to be profiled first.
  useEffect(() => {
    if (!wantAuto || autoTried.current) return;
    if (!ds || !ds.files.length) return;
    if (!ds.files.every((f) => profiles[f.id])) return;
    if (!jobs) return;
    const alreadyRan = jobs.some((j) => j.status === 'done' || j.status === 'running' || j.status === 'queued');
    if (alreadyRan) { autoTried.current = true; return; }
    autoTried.current = true;
    const cfg = autoBuildConfig(ds.files, profiles);
    if (!cfg) {
      setAutoErr('Could not auto-detect a usable configuration for this dataset. Please configure the analysis by hand.');
      setShowWizard(true);
      return;
    }
    setAutoConfig(cfg);
    api.createJob(id, toMapping(cfg.mapping), toParams(cfg.params))
      .then((j) => { setAutoJobId(j.id); loadJobs(); })
      .catch((e) => { setAutoErr(e.message); setShowWizard(true); });
  }, [wantAuto, ds, profiles, jobs, id, loadJobs]);

  // Once the auto-flow query strings have been consumed we scrub them from the URL
  // so a refresh does not re-trigger the auto-run and the back button behaves.
  useEffect(() => {
    if ((wantAuto || wantConfigure) && autoTried.current) {
      const next = new URLSearchParams(search);
      next.delete('auto'); next.delete('configure');
      setSearch(next, { replace: true });
    }
  }, [wantAuto, wantConfigure, autoTried.current]); // eslint-disable-line

  async function addFiles(files) {
    setAdding(true);
    try { setDs(await api.addFiles(id, files)); } catch (e) { setError(e.message); } finally { setAdding(false); }
  }

  if (error) return <div className="alert err">{error} <Link to="/">Back</Link></div>;
  if (!ds) return <div className="row"><span className="spinner" /> Loading...</div>;
  const file = ds.files.find((f) => f.id === fileId);
  const profile = profiles[fileId];
  const TABS = [
    ['overview', 'Overview'],
    ['explore', 'Graphical analysis'],
    ['behavioral', 'Behavioral analysis'],
    ['runs', `Past runs (${jobs.length})`],
  ];

  // The job to display in the Behavioral tab when the user has not asked for the wizard:
  // prefer the one this visit started, otherwise the most recent finished job.
  const doneJobs = jobs.filter((j) => j.status === 'done');
  const activeJob = jobs.find((j) => j.id === autoJobId)
    || doneJobs.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))[0]
    || null;

  return (
    <>
      <div className="row between"><div><Link to="/">&larr; All datasets</Link><h1>{ds.name}</h1></div></div>
      <div className="card">
        <div className="row">
          <div>
            <label>Active file</label>
            <select value={fileId} onChange={(e) => setFileId(e.target.value)} style={{ minWidth: 260 }}>
              {ds.files.map((f) => <option key={f.id} value={f.id}>{f.originalName} ({bytes(f.size)})</option>)}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 260 }}>
            <Dropzone compact onFiles={addFiles} hint={adding ? 'Uploading...' : 'Add more files to this dataset (lookup tables, labels...)'} />
          </div>
        </div>
      </div>
      {profErr && <div className="alert err">{profErr}</div>}
      <div className="tabs">{TABS.map(([k, l]) => (
        <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>
      ))}</div>

      {tab === 'overview' && (profile ? <Overview profile={profile} /> : <div className="row"><span className="spinner" /> Profiling {file?.originalName}...</div>)}

      {tab === 'explore' && (profile ? (
        <>
          <RunCommunityGraphs key={`cg${id}`} datasetId={id} onGoBehavioral={() => setTab('behavioral')} />
          <AutoCharts key={fileId} datasetId={id} fileId={fileId} />
          <ChartBuilder key={`b${fileId}`} datasetId={id} fileId={fileId} columns={profile.columns} />
        </>
      ) : <div className="row"><span className="spinner" /> Profiling...</div>)}

      {/* The Behavioral tab stays mounted so running jobs do not restart on tab switches. */}
      <div style={{ display: tab === 'behavioral' ? 'block' : 'none' }}>
        {autoErr && (
          <div className="alert err" style={{ marginBottom: 12 }}>
            <b>Auto-run failed.</b> {autoErr}
          </div>
        )}
        {!showWizard && autoJobId && !autoErr && autoConfig && (
          <div className="alert info" style={{ marginBottom: 12 }}>
            Automatic run started using {autoConfig.source === 'auto-detected'
              ? 'auto-detected column mapping'
              : <>the <b>{autoConfig.source.replace('preset:', '')}</b> preset</>}
            . Scroll down for the full dashboard once it finishes.
          </div>
        )}
        {!showWizard && activeJob ? (
          <>
            <div className="row between" style={{ marginBottom: 10 }}>
              <div className="muted small">
                Showing analysis from {new Date(activeJob.createdAt).toLocaleString()}
                {jobs.length > 1 && ` (${jobs.length - 1} earlier run${jobs.length - 1 === 1 ? '' : 's'} in Past runs)`}.
              </div>
              <button className="ghost" onClick={() => setShowWizard(true)}>Reconfigure and re-run</button>
            </div>
            <Results jobId={activeJob.id} onFinished={loadJobs} />
          </>
        ) : (!showWizard && wantAuto && !autoErr) ? (
          <div className="card row"><span className="spinner" />
            <div>
              <b>Preparing automatic analysis...</b>
              <div className="muted small">Profiling the files and starting the first run.</div>
            </div>
          </div>
        ) : (
          <>
            {showWizard && activeJob && (
              <div className="row" style={{ marginBottom: 10 }}>
                <button className="ghost" onClick={() => setShowWizard(false)}>
                  &larr; Back to latest analysis
                </button>
              </div>
            )}
            <Wizard
              datasetId={id}
              files={ds.files}
              profiles={profiles}
              activeFileId={fileId}
              onFinished={(j) => { loadJobs(); setAutoJobId(j?.id || null); setShowWizard(false); }}
            />
          </>
        )}
      </div>

      {tab === 'runs' && (
        openJob ? (
          <>
            <button className="ghost" onClick={() => setOpenJob(null)}>&larr; Back to list</button>
            <div style={{ marginTop: 12 }}><Results jobId={openJob} /></div>
          </>
        ) : (
          <div className="card">
            {jobs.length === 0 ? (
              <p className="muted">No runs yet. Use the Behavioral analysis tab.</p>
            ) : (
              <table>
                <thead><tr><th>when</th><th>status</th><th>communities</th><th>nodes</th><th>algorithm</th><th /></tr></thead>
                <tbody>{jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{new Date(j.createdAt).toLocaleString()}</td>
                    <td>{j.status}</td>
                    <td>{j.summary?.communities ?? '-'}</td>
                    <td>{j.summary?.connected_nodes ?? '-'}</td>
                    <td>{j.summary?.primary_algorithm ?? '-'}</td>
                    <td><button className="ghost" onClick={() => setOpenJob(j.id)}>Open</button></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        )
      )}
    </>
  );
}
