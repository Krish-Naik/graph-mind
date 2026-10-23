import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { PRESETS } from '../presets.js';
import { DEFAULT_TIERS } from '../util.js';
import DataTable from '../components/DataTable.jsx';
import SimilarityChart from './SimilarityChart.jsx';
import Results from './Results.jsx';

const STEPS = ['1. Map your data', '2. Check suitability', '3. Parameters', '4. Run & results'];

const initialMapping = (fileId) => ({
  mainFileId: fileId, format: 'long', entity_col: '', behavior_col: '', value_col: '', agg: 'sum', feature_cols: [],
  useLookup: false, lookup: { fileId: '', source_key: '', lookup_key: '', split_delimiter: '' },
  useLabel: false, label: { fileId: '', entity_col: '', label_col: '' },
});
const initialParams = () => ({
  sample_size: 300, graph_method: 'threshold', threshold: 0.85, knn_k: 10, algorithms: ['louvain', 'leiden', 'lpa'],
  primary_algorithm: 'louvain', tier_method: 'quantile', tier_labels: [...DEFAULT_TIERS], low_cut: '', high_cut: '', min_community_size: 1,
});

/** UI state -> body the server expects */
export function toMapping(m) {
  const long = m.format === 'long';
  return {
    mainFileId: m.mainFileId, format: m.format, entity_col: m.entity_col,
    behavior_col: long ? m.behavior_col || null : null,
    value_col: long && m.agg !== 'count' ? m.value_col || null : null,
    agg: long ? m.agg : 'sum',
    feature_cols: long ? null : m.feature_cols,
    lookup: long && m.useLookup ? { ...m.lookup, split_delimiter: m.lookup.split_delimiter || null } : null,
    label: m.useLabel ? m.label : null,
  };
}
export function toParams(p) {
  const out = {
    sample_size: p.sample_size === '' || p.sample_size == null ? null : Number(p.sample_size),
    graph_method: p.graph_method, threshold: Number(p.threshold), knn_k: Number(p.knn_k),
    algorithms: p.algorithms, primary_algorithm: p.primary_algorithm, tier_method: p.tier_method,
    tier_labels: p.tier_labels, min_community_size: Number(p.min_community_size),
  };
  if (p.tier_method === 'thresholds') { out.low_cut = Number(p.low_cut); out.high_cut = Number(p.high_cut); }
  return out;
}
export function mappingReady(m) {
  if (!m.mainFileId || !m.entity_col) return false;
  if (m.format === 'wide') return m.feature_cols.length >= 2;
  if (!m.behavior_col) return false;
  if (m.agg !== 'count' && !m.value_col) return false;
  if (m.useLookup && !(m.lookup.fileId && m.lookup.source_key && m.lookup.lookup_key)) return false;
  if (m.useLabel && !(m.label.fileId && m.label.entity_col && m.label.label_col)) return false;
  return true;
}

function Select({ value, onChange, options, blank = 'choose...' }) {
  return (
    <select value={value || ''} onChange={(e) => onChange(e.target.value)}>
      <option value="">{blank}</option>
      {options.map((o) => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
    </select>
  );
}
const Field = ({ label, children, hint }) => <div className="field"><label>{label}</label>{children}{hint && <div className="muted small">{hint}</div>}</div>;

export default function Wizard({ datasetId, files, profiles, activeFileId, onFinished }) {
  const [step, setStep] = useState(1);
  const [m, setM] = useState(() => initialMapping(activeFileId || files[0]?.id));
  const [params, setParams] = useState(initialParams);
  const [check, setCheck] = useState(null);
  const [checking, setChecking] = useState(false);
  const [checkErr, setCheckErr] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [runErr, setRunErr] = useState(null);

  const setMap = (patch) => setM((x) => ({ ...x, ...patch }));
  const cols = (fid) => profiles[fid]?.columns || [];
  const names = (fid) => cols(fid).map((c) => c.name);
  const fileOpts = files.map((f) => ({ value: f.id, label: f.originalName }));
  const presets = PRESETS.filter((p) => p.match(files));

  // pre-fill entity/behavior/value from the engine's suggestion for the chosen main file
  useEffect(() => {
    const p = profiles[m.mainFileId];
    if (!p || m.entity_col) return;
    const s = p.behavioral_suggestion || {};
    setM((x) => ({ ...x, entity_col: s.entity_col || '', behavior_col: s.behavior_col || '', value_col: s.value_col || '' }));
  }, [profiles, m.mainFileId, m.entity_col]);

  const behaviorCols = m.useLookup ? names(m.lookup.fileId) : names(m.mainFileId);
  const numericCols = cols(m.mainFileId).filter((c) => c.numeric).map((c) => c.name);

  function applyPreset(p) {
    const built = p.build(files);
    setM(built.mapping); setParams((x) => ({ ...x, ...built.params })); setCheck(null);
  }

  async function goCheck() {
    setStep(2); setChecking(true); setCheckErr(null); setCheck(null);
    try { setCheck(await api.check(datasetId, toMapping(m), Number(params.sample_size) || null)); }
    catch (e) { setCheckErr(e.message); } finally { setChecking(false); }
  }

  async function run() {
    setStep(4); setRunErr(null); setJobId(null);
    try { setJobId((await api.createJob(datasetId, toMapping(m), toParams(params))).id); }
    catch (e) { setRunErr(e.message); }
  }

  const setP = (patch) => setParams((x) => ({ ...x, ...patch }));
  const toggleAlgo = (a) => setP({ algorithms: params.algorithms.includes(a) ? params.algorithms.filter((x) => x !== a) : [...params.algorithms, a] });
  const paramsOk = params.algorithms.length > 0 && (params.tier_method !== 'thresholds' || (params.low_cut !== '' && params.high_cut !== ''));

  return (
    <>
      <div className="alert info">
        Behavioral analysis groups entities (students, customers, users...) by <b>what they do</b>. Your data needs three things:
        an <b>entity ID</b>, a <b>behavior category</b> (type of action), and a <b>magnitude</b> (count/amount). Step 2 tells you if the data is suitable.
      </div>
      <div className="stepper">{STEPS.map((s, i) => <div key={s} className={`step ${step === i + 1 ? 'on' : step > i + 1 ? 'done' : ''}`}>{s}</div>)}</div>

      {step === 1 && (
        <div className="card">
          {presets.map((p) => (
            <div className="alert ok row between" key={p.id}>
              <span>Recognised <b>{p.name}</b>: {p.description}.</span>
              <button onClick={() => applyPreset(p)}>Apply preset</button>
            </div>
          ))}
          <div className="grid g2">
            <div>
              <h3>Main data file</h3>
              <Field label="File"><Select value={m.mainFileId} onChange={(v) => setMap({ mainFileId: v, entity_col: '', behavior_col: '', value_col: '', feature_cols: [] })} options={fileOpts} /></Field>
              <Field label="Layout" hint={m.format === 'long' ? 'One row per event/record (e.g. a click log).' : 'One row per entity, one numeric column per behavior.'}>
                <Select value={m.format} onChange={(v) => setMap({ format: v })} blank="" options={[{ value: 'long', label: 'Long: event log (entity, behavior, value)' }, { value: 'wide', label: 'Wide: ready-made matrix' }]} />
              </Field>
              <Field label="Entity ID column" hint="Who is being grouped, e.g. student, customer, user id."><Select value={m.entity_col} onChange={(v) => setMap({ entity_col: v })} options={names(m.mainFileId)} /></Field>
              {m.format === 'wide' ? (
                <Field label="Behavior columns (pick at least 2)">
                  <div className="tablewrap" style={{ maxHeight: 180, padding: 8 }}>
                    {numericCols.filter((c) => c !== m.entity_col).map((c) => (
                      <div className="inline" key={c}><input type="checkbox" id={`f-${c}`} checked={m.feature_cols.includes(c)}
                        onChange={() => setMap({ feature_cols: m.feature_cols.includes(c) ? m.feature_cols.filter((x) => x !== c) : [...m.feature_cols, c] })} /><label htmlFor={`f-${c}`}>{c}</label></div>
                    ))}
                  </div>
                </Field>
              ) : (
                <>
                  <Field label="Behavior category column" hint={m.useLookup ? 'Taken from the lookup file.' : 'The type of action, e.g. activity type, product category, genre.'}>
                    <Select value={m.behavior_col} onChange={(v) => setMap({ behavior_col: v })} options={behaviorCols} /></Field>
                  <div className="grid g2">
                    <Field label="Aggregation"><Select value={m.agg} onChange={(v) => setMap({ agg: v })} blank="" options={['sum', 'count', 'mean', 'max']} /></Field>
                    {m.agg !== 'count' && <Field label="Value column (numeric)"><Select value={m.value_col} onChange={(v) => setMap({ value_col: v })} options={numericCols} /></Field>}
                  </div>
                </>
              )}
            </div>
            <div>
              {m.format === 'long' && (
                <>
                  <h3>Lookup file (optional)</h3>
                  <div className="inline" style={{ marginBottom: 10 }}><input type="checkbox" id="ul" checked={m.useLookup} onChange={(e) => setMap({ useLookup: e.target.checked, behavior_col: '' })} />
                    <label htmlFor="ul">The behavior category is in a different file (join needed)</label></div>
                  {m.useLookup && (
                    <>
                      <Field label="Lookup file"><Select value={m.lookup.fileId} onChange={(v) => setMap({ lookup: { ...m.lookup, fileId: v }, behavior_col: '' })} options={fileOpts} /></Field>
                      <div className="grid g2">
                        <Field label="Key in main file"><Select value={m.lookup.source_key} onChange={(v) => setMap({ lookup: { ...m.lookup, source_key: v } })} options={names(m.mainFileId)} /></Field>
                        <Field label="Key in lookup file"><Select value={m.lookup.lookup_key} onChange={(v) => setMap({ lookup: { ...m.lookup, lookup_key: v } })} options={names(m.lookup.fileId)} /></Field>
                      </div>
                      <Field label="Multi-value separator (optional)" hint="Use | if one cell holds several categories, like Action|Comedy.">
                        <input type="text" value={m.lookup.split_delimiter} placeholder="e.g. |" onChange={(e) => setMap({ lookup: { ...m.lookup, split_delimiter: e.target.value } })} /></Field>
                    </>
                  )}
                </>
              )}
              <h3 style={{ marginTop: 8 }}>Ground-truth label (optional)</h3>
              <div className="inline" style={{ marginBottom: 10 }}><input type="checkbox" id="ulab" checked={m.useLabel} onChange={(e) => setMap({ useLabel: e.target.checked })} />
                <label htmlFor="ulab">Compare communities with a known label (adds NMI)</label></div>
              {m.useLabel && (
                <>
                  <Field label="Label file"><Select value={m.label.fileId} onChange={(v) => setMap({ label: { ...m.label, fileId: v } })} options={fileOpts} /></Field>
                  <div className="grid g2">
                    <Field label="Entity column"><Select value={m.label.entity_col} onChange={(v) => setMap({ label: { ...m.label, entity_col: v } })} options={names(m.label.fileId)} /></Field>
                    <Field label="Label column"><Select value={m.label.label_col} onChange={(v) => setMap({ label: { ...m.label, label_col: v } })} options={names(m.label.fileId)} /></Field>
                  </div>
                </>
              )}
            </div>
          </div>
          <button onClick={goCheck} disabled={!mappingReady(m)}>Check if this data is suitable &rarr;</button>
        </div>
      )}

      {step === 2 && (
        <div className="card">
          {checking && <div className="row"><span className="spinner" /> Building the matrix and checking suitability... (large files can take a few seconds)</div>}
          {checkErr && <div className="alert err">{checkErr}</div>}
          {check && (
            <>
              {check.ok ? <div className="alert ok"><b>Suitable.</b> This data can be analysed.</div>
                : <div className="alert err"><b>Not suitable for behavioral analysis.</b></div>}
              {check.errors.map((e, i) => <div key={i} className="alert err">{e}</div>)}
              {check.warnings.map((e, i) => <div key={i} className="alert warn">{e}</div>)}
              <div className="grid g4" style={{ margin: '12px 0' }}>
                <div className="card stat"><div className="v">{check.stats.entities.toLocaleString()}</div><div className="l">entities</div></div>
                <div className="card stat"><div className="v">{check.stats.behaviors}</div><div className="l">behavior categories</div></div>
                <div className="card stat"><div className="v">{(check.stats.sparsity * 100).toFixed(0)}%</div><div className="l">zeros in matrix</div></div>
                <div className="card stat"><div className="v">{check.stats.varying_behaviors}</div><div className="l">columns that vary</div></div>
              </div>
              <div style={{ marginBottom: 12 }}>{check.stats.behavior_names.map((b) => <span className="chip" key={b}>{b}</span>)}</div>
              {check.stats.preview && <><h3>Matrix preview</h3><DataTable rows={check.stats.preview} /></>}
            </>
          )}
          <div className="row" style={{ marginTop: 14 }}>
            <button className="ghost" onClick={() => setStep(1)}>&larr; Back</button>
            <button onClick={() => setStep(3)} disabled={!check?.ok}>Continue &rarr;</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="card">
          <div className="grid g2">
            <div>
              <h3>Similarity graph</h3>
              <Field label="Sample size (entities)" hint="Pairwise similarity grows with the square of this. Empty = all (max 5000).">
                <input type="number" min="10" max="5000" value={params.sample_size ?? ''} onChange={(e) => setP({ sample_size: e.target.value })} /></Field>
              <Field label="How to connect entities">
                <Select value={params.graph_method} onChange={(v) => setP({ graph_method: v })} blank="" options={[{ value: 'threshold', label: 'Similarity threshold' }, { value: 'knn', label: 'k nearest neighbours (no isolated nodes)' }]} /></Field>
              {params.graph_method === 'threshold' ? (
                <Field label={`Threshold tau = ${params.threshold}`} hint="Higher = fewer, stronger links. Use the histogram to choose.">
                  <input type="range" min="0.5" max="0.99" step="0.01" value={params.threshold} onChange={(e) => setP({ threshold: Number(e.target.value) })} style={{ width: '100%' }} /></Field>
              ) : (
                <Field label="k (neighbours per entity)"><input type="number" min="1" max="100" value={params.knn_k} onChange={(e) => setP({ knn_k: e.target.value })} /></Field>
              )}
              {check?.similarity && <SimilarityChart hist={check.similarity} threshold={params.graph_method === 'threshold' ? params.threshold : null} />}
            </div>
            <div>
              <h3>Communities</h3>
              <Field label="Algorithms to compare">
                {[['louvain', 'Louvain'], ['leiden', 'Leiden'], ['lpa', 'Label Propagation']].map(([k, l]) => (
                  <div className="inline" key={k}><input type="checkbox" id={`a-${k}`} checked={params.algorithms.includes(k)} onChange={() => toggleAlgo(k)} /><label htmlFor={`a-${k}`}>{l}</label></div>
                ))}</Field>
              <Field label="Algorithm used for the tiers">
                <Select value={params.primary_algorithm} onChange={(v) => setP({ primary_algorithm: v })} blank="" options={[{ value: 'louvain', label: 'Louvain' }, { value: 'leiden', label: 'Leiden' }, { value: 'lpa', label: 'Label Propagation' }, { value: 'best_modularity', label: 'Best modularity (automatic)' }]} /></Field>
              <h3>Tiers</h3>
              <Field label="How to split communities into 3 tiers">
                <Select value={params.tier_method} onChange={(v) => setP({ tier_method: v })} blank="" options={[{ value: 'quantile', label: 'Three equal groups by average activity' }, { value: 'thresholds', label: 'Custom cut-offs on average activity' }]} /></Field>
              {params.tier_method === 'thresholds' && (
                <div className="grid g2">
                  <Field label="Moderate starts at"><input type="number" value={params.low_cut} onChange={(e) => setP({ low_cut: e.target.value })} /></Field>
                  <Field label="High starts at"><input type="number" value={params.high_cut} onChange={(e) => setP({ high_cut: e.target.value })} /></Field>
                </div>
              )}
              <div className="grid g3">
                {['Lowest tier', 'Middle tier', 'Highest tier'].map((l, i) => (
                  <Field key={l} label={l}><input type="text" value={params.tier_labels[i]} onChange={(e) => { const t = [...params.tier_labels]; t[i] = e.target.value; setP({ tier_labels: t }); }} /></Field>
                ))}
              </div>
              <Field label="Minimum community size" hint="Smaller communities are flagged as outliers and left out of the tiering. 1 = keep all.">
                <input type="number" min="1" value={params.min_community_size} onChange={(e) => setP({ min_community_size: e.target.value })} /></Field>
            </div>
          </div>
          <div className="row">
            <button className="ghost" onClick={() => setStep(2)}>&larr; Back</button>
            <button onClick={run} disabled={!paramsOk}>Run analysis</button>
          </div>
        </div>
      )}

      {step === 4 && (
        <>
          {runErr && <div className="alert err">{runErr}</div>}
          {jobId && <Results jobId={jobId} onBack={() => setStep(3)} onFinished={onFinished} />}
          <div className="row" style={{ marginTop: 14 }}>
            <button className="ghost" onClick={() => setStep(3)}>&larr; Change parameters</button>
            <button className="ghost" onClick={() => { setStep(1); setJobId(null); }}>Start over</button>
          </div>
        </>
      )}
    </>
  );
}
