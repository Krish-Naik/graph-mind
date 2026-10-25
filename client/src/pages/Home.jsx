import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import Dropzone from '../components/Dropzone.jsx';
import { bytes } from '../util.js';

export default function Home() {
  const nav = useNavigate();
  const [datasets, setDatasets] = useState(null);
  const [picked, setPicked] = useState([]);
  const [name, setName] = useState('');
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  // Preset toggle. ON (default) = auto-run behavioral analysis after upload using
  // a matching preset or auto-detection. OFF = land on the dataset page with
  // the behavioral form open so the user picks mapping and parameters by hand.
  const [usePreset, setUsePreset] = useState(true);

  const load = () => api.datasets().then(setDatasets).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const onFiles = (files) =>
    setPicked((p) => [...p, ...files.filter((f) => !p.some((x) => x.name === f.name && x.size === f.size))]);

  async function upload() {
    setError(null); setProgress(0);
    try {
      const ds = await api.createDataset(picked, name, setProgress);
      // The dataset page reads these flags from the URL and decides whether
      // to kick off an automatic run (preset ON) or open the config form (preset OFF).
      const q = usePreset ? '?auto=1' : '?configure=1';
      nav(`/d/${ds.id}${q}`);
    } catch (e) { setError(e.message); setProgress(null); }
  }

  async function remove(id) {
    if (!confirm('Delete this dataset and all its analysis runs?')) return;
    await api.deleteDataset(id); load();
  }

  return (
    <>
      <h1>Analyse your data</h1>
      <p className="muted">
        Upload a dataset to explore it graphically, or run behavioral community analysis if it records what entities
        (students, customers, users) do.
      </p>

      <div className="card">
        {/* Preset vs. custom toggle. Appears above the dropzone so the user picks before uploading. */}
        <div
          className="row"
          style={{
            padding: '10px 12px', marginBottom: 12, borderRadius: 8,
            background: '#f8fafc', border: '1px solid #e2e8f0', alignItems: 'flex-start',
          }}
        >
          <input
            type="checkbox"
            id="use-preset"
            checked={usePreset}
            onChange={(e) => setUsePreset(e.target.checked)}
            disabled={progress !== null}
            style={{ marginTop: 3 }}
          />
          <label htmlFor="use-preset" style={{ flex: 1, cursor: 'pointer' }}>
            <b>Use a preset (recommended)</b>
            {usePreset ? (
              <div className="muted small" style={{ marginTop: 2 }}>
                We will recognise known datasets (OULAD, MovieLens, ...) or auto-detect the entity, behavior and
                value columns in a generic file, and run the behavioral analysis automatically after upload.
                You can still open the "Behavioral analysis" tab afterwards to tweak settings and re-run.
              </div>
            ) : (
              <div className="muted small" style={{ marginTop: 2 }}>
                Preset off: after upload you will be taken straight to the behavioral configuration form
                (<i>1. Map your data &rarr; 2. Check suitability &rarr; 3. Parameters &rarr; 4. Run &amp; results</i>),
                where you choose the algorithms and all other parameters by hand.
              </div>
            )}
          </label>
        </div>

        <Dropzone
          onFiles={onFiles}
          hint="One CSV is enough if it has an entity, a behavior and a value column. Multi-table data (e.g. OULAD) can be dropped as one ZIP."
        />
        {picked.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div className="tablewrap" style={{ maxHeight: 200 }}>
              <table><tbody>
                {picked.map((f, i) => (
                  <tr key={i}>
                    <td>{f.name}</td>
                    <td>{bytes(f.size)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="ghost"
                        disabled={progress !== null}
                        onClick={() => setPicked(picked.filter((_, j) => j !== i))}
                      >remove</button>
                    </td>
                  </tr>
                ))}
              </tbody></table>
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <input
                type="text"
                placeholder="Dataset name (optional)"
                value={name}
                onChange={(e) => setName(e.target.value)}
                style={{ maxWidth: 320 }}
                disabled={progress !== null}
              />
              <button onClick={upload} disabled={progress !== null}>
                {progress !== null
                  ? 'Uploading...'
                  : `Upload ${picked.length} file${picked.length > 1 ? 's' : ''}${usePreset ? ' and run' : ''}`}
              </button>
            </div>
            {progress !== null && (
              <div style={{ marginTop: 10 }}>
                <div className="progress"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
                <div className="muted small">
                  {Math.round(progress * 100)}% {progress >= 1 && '- processing on the server...'}
                </div>
              </div>
            )}
          </div>
        )}
        {error && <div className="alert err" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      <h2>Your datasets</h2>
      {datasets === null && !error && <div className="row"><span className="spinner" /> Loading...</div>}
      {datasets?.length === 0 && <p className="muted">Nothing here yet. Upload your first dataset above.</p>}
      <div className="grid g3">
        {datasets?.map((d) => (
          <div className="card" key={d.id}>
            <h3><Link to={`/d/${d.id}`}>{d.name}</Link></h3>
            <div className="muted small">
              {d.files.length} file(s) &middot; {bytes(d.files.reduce((a, f) => a + f.size, 0))}
            </div>
            <div style={{ margin: '8px 0' }}>
              {d.files.map((f) => <span className="chip" key={f.id}>{f.originalName}</span>)}
            </div>
            <div className="row">
              <Link className="btn" to={`/d/${d.id}`}>Open</Link>
              <button className="danger" onClick={() => remove(d.id)}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
