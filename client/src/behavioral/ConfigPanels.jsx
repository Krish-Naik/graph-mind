import { useEffect, useState } from 'react';
import { api } from '../api.js';

/* Presentation helpers for the behavioral workflow. Nothing here talks to a new endpoint:
   - ProfilePanel      renders the profile the API already returns for a file
   - validateParams    mirrors the parameter limits the engine enforces (schemas.py / profile.validate_params)
   - ConfigSummary     explains the request that will be / was sent (mapping + params, exactly as the API receives them)
   - MetricGuide       explains the metrics of a finished run using that run's own numbers */

const ALGO = { louvain: 'Louvain', leiden: 'Leiden', lpa: 'Label Propagation', best_modularity: 'best modularity (automatic)' };
const fmtInt = (v) => Number(v).toLocaleString();

export const colHint = (c) => `${c.name} (${c.type}${c.approx_distinct != null ? `, ~${fmtInt(c.approx_distinct)} distinct` : ''})`;

/* ---------- 1. dataset profile ---------- */
export function ProfilePanel({ file, profile }) {
  if (!profile) return <div className="muted small row" style={{ marginBottom: 12 }}><span className="spinner" /> Profiling {file?.originalName || 'file'}...</div>;
  const numeric = profile.columns.filter((c) => c.numeric).length;
  return (
    <details open style={{ marginBottom: 14 }}>
      <summary style={{ cursor: 'pointer', fontSize: 14 }}>
        <b>Profile of {file?.originalName}</b>: {fmtInt(profile.rows)} rows, {profile.columns.length} columns ({numeric} numeric)
      </summary>
      <div className="tablewrap" style={{ maxHeight: 220, marginTop: 8 }}>
        <table>
          <thead><tr><th>column</th><th>type</th><th>distinct (approx)</th><th>nulls (sample)</th><th>example values</th></tr></thead>
          <tbody>{profile.columns.map((c) => (
            <tr key={c.name}><td><b>{c.name}</b></td><td>{c.type}</td><td>{c.approx_distinct != null ? fmtInt(c.approx_distinct) : ''}</td><td>{c.nulls_in_sample}</td>
              <td>{(c.top_values || []).slice(0, 3).map((t) => String(t.value)).join(', ')}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="muted small" style={{ marginTop: 4 }}>Use this to choose: an entity ID has many distinct values repeated over many rows; a behavior category has few distinct values; a value column is numeric.</div>
    </details>
  );
}

/* ---------- 2. parameter validation (same limits as the engine) ---------- */
const toNum = (v) => (v === '' || v == null ? NaN : Number(v));
export function validateParams(p) {
  const errors = [], warnings = [];
  if (p.sample_size !== '' && p.sample_size != null) {
    const s = toNum(p.sample_size);
    if (!Number.isInteger(s) || s < 10 || s > 5000) errors.push('Sample size must be a whole number from 10 to 5000, or empty to use all entities (capped at 5000).');
  }
  if (p.graph_method === 'knn') {
    const k = toNum(p.knn_k);
    if (!Number.isInteger(k) || k < 1 || k > 100) errors.push('k must be a whole number from 1 to 100.');
  } else {
    const t = toNum(p.threshold);
    if (!(t >= 0 && t <= 1)) errors.push('The similarity threshold must be between 0 and 1.');
    else if (t >= 1) warnings.push('Threshold 1.0 links only entities with identical behavior shape; expect very few edges.');
  }
  if (!p.algorithms.length) errors.push('Select at least one community detection algorithm.');
  else if (p.primary_algorithm !== 'best_modularity' && !p.algorithms.includes(p.primary_algorithm)) {
    warnings.push(`'${ALGO[p.primary_algorithm]}' is used for the tiers but is not selected above; the first algorithm that succeeds will be used instead.`);
  }
  if (p.algorithms.includes('leiden')) {
    const g = toNum(p.leiden_resolution);
    if (!(g >= 0.1 && g <= 5)) errors.push('Leiden resolution must be between 0.1 and 5.');
  }
  const mcs = toNum(p.min_community_size);
  if (!Number.isInteger(mcs) || mcs < 1) errors.push('Minimum community size must be a whole number of at least 1.');
  const names = p.tier_labels.map((t) => String(t).trim());
  if (names.some((t) => !t)) errors.push('Tier labels must not be empty.');
  else if (new Set(names).size < 3) errors.push('Tier labels must be different from each other.');
  if (p.tier_method === 'thresholds') {
    const lo = toNum(p.low_cut), hi = toNum(p.high_cut);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) errors.push('Custom tier cut-offs need both numbers.');
    else if (lo > hi) errors.push(`The Moderate cut-off (${lo}) must not be greater than the High cut-off (${hi}).`);
  }
  return { errors, warnings };
}

/* ---------- 3. effective configuration ---------- */
const nameOf = (files, id) => files?.find((f) => f.id === id)?.originalName || id || '?';

/** mapping/params are request bodies (what toMapping/toParams return, or what a stored job holds) */
export function effectiveConfig(mapping, params, files) {
  const m = mapping, p = params, long = m.format !== 'wide';
  const data = [['Main file', nameOf(files, m.mainFileId)], ['Layout', long ? 'Long: one row per event (entity, behavior, value)' : 'Wide: one row per entity, one column per behavior'], ['Entity ID', m.entity_col]];
  if (long) {
    data.push(['Behavior category', m.behavior_col + (m.lookup ? ` (column of ${nameOf(files, m.lookup.fileId)})` : '')]);
    data.push(['Magnitude', m.agg === 'count' ? 'number of rows (count)' : `${m.agg} of ${m.value_col}`]);
    data.push(['Lookup join', m.lookup ? `${m.lookup.source_key} in main file = ${m.lookup.lookup_key} in ${nameOf(files, m.lookup.fileId)}${m.lookup.split_delimiter ? `; cells split on "${m.lookup.split_delimiter}"` : ''}` : 'none']);
  } else {
    const f = m.feature_cols || [];
    data.push(['Behavior columns', `${f.length}: ${f.slice(0, 8).join(', ')}${f.length > 8 ? ', ...' : ''}`]);
  }
  data.push(['Reference label', m.label ? `${m.label.label_col} (${nameOf(files, m.label.fileId)}, matched on ${m.label.entity_col}). Used only to score the communities, never to build them.` : 'none: NMI will be reported as unavailable']);
  const graph = [['Entities analysed', p.sample_size == null ? 'all (engine cap 5,000)' : `${fmtInt(p.sample_size)} sampled at random`],
    ['Graph', p.graph_method === 'knn' ? `${p.knn_k} nearest neighbours per entity` : `link entities with cosine similarity >= ${p.threshold}`]];
  const algos = (p.algorithms || []).map((a) => ALGO[a] + (a === 'leiden' ? ` (resolution ${p.leiden_resolution})` : '')).join(', ');
  const comm = [['Algorithms compared', algos], ['Algorithm used for tiers', ALGO[p.primary_algorithm] || p.primary_algorithm],
    ['Tier split', p.tier_method === 'thresholds' ? `custom: ${p.tier_labels?.[1]} from ${p.low_cut}, ${p.tier_labels?.[2]} from ${p.high_cut} (average activity per community)` : 'three equal groups of communities, ranked by average activity'],
    ['Tier names (low / middle / high)', (p.tier_labels || []).join('  |  ')],
    ['Minimum community size', p.min_community_size <= 1 ? '1 (keep all)' : `${p.min_community_size} (smaller ones are left out of the tiers)`]];
  const defaults = [['Engine defaults (not set on this screen)', 'random seed 42, 8 stability re-runs, at most 20,000 edges returned to the browser']];
  return [['Data', data], ['Similarity graph', graph], ['Communities and tiers', comm], ['Defaults', defaults]];
}

function ConfigTable({ mapping, params, files }) {
  const sections = effectiveConfig(mapping, params, files);
  return (
    <>
      <div className="tablewrap" style={{ maxHeight: 'none' }}>
        <table><tbody>
          {sections.map(([title, rows]) => [
            <tr key={title}><th colSpan={2}>{title}</th></tr>,
            ...rows.map(([k, v]) => <tr key={title + k}><td style={{ whiteSpace: 'normal', width: '32%' }}>{k}</td><td style={{ whiteSpace: 'normal' }}><b>{v}</b></td></tr>),
          ])}
        </tbody></table>
      </div>
      <details style={{ marginTop: 8 }}>
        <summary className="muted small" style={{ cursor: 'pointer' }}>Exact request body sent to the API</summary>
        <pre className="small" style={{ background: '#f8fafc', border: '1px solid var(--line)', borderRadius: 8, padding: 10, overflow: 'auto', maxHeight: 260 }}>{JSON.stringify({ mapping, params }, null, 2)}</pre>
      </details>
    </>
  );
}

/** Wizard preview, before running */
export function ConfigPreview({ mapping, params, files }) {
  return (
    <div style={{ marginTop: 14 }}>
      <h3>Effective configuration</h3>
      <div className="muted small" style={{ marginBottom: 6 }}>This is exactly what will be analysed. Go back to change anything.</div>
      <ConfigTable mapping={mapping} params={params} files={files} />
    </div>
  );
}

/** Same table for a finished job (mapping/params are stored on the job) */
export function RunConfig({ job }) {
  const [files, setFiles] = useState(null);
  useEffect(() => {
    let live = true;
    if (job.datasetId && api.dataset) api.dataset(job.datasetId).then((d) => live && setFiles(d.files)).catch(() => {});
    return () => { live = false; };
  }, [job.datasetId]);
  if (!job.mapping || !job.params) return null;
  return (
    <details className="card" style={{ marginTop: 16 }}>
      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Configuration used for this run</summary>
      <div style={{ marginTop: 10 }}><ConfigTable mapping={job.mapping} params={job.params} files={files} /></div>
    </details>
  );
}

/* ---------- 4. metric explanations ---------- */
export function metricNotes(r) {
  const s = r.summary, bench = r.benchmark || [];
  const primary = bench.find((b) => b.algorithm === s.primary_algorithm) || bench.find((b) => b.modularity != null);
  const out = [];
  const q = primary?.modularity;
  if (q != null) {
    const band = q >= 0.5 ? 'strong' : q >= 0.3 ? 'meaningful' : 'weak';
    out.push(['Modularity', q.toFixed(3), `${band} community structure`,
      `${primary.algorithm}: how much denser the links are inside communities than chance would give. Above 0.3 is meaningful, above 0.5 strong. It describes the graph, not whether the groups are useful.`]);
  }
  if (r.has_label && primary?.nmi != null) {
    const n = primary.nmi;
    out.push(['NMI vs reference label', n.toFixed(3), n < 0.1 ? 'communities barely follow the label' : n < 0.3 ? 'weak agreement with the label' : n < 0.6 ? 'moderate agreement with the label' : 'strong agreement with the label',
      '0 = unrelated, 1 = identical grouping. Communities are built from behavior only, so a low value means behavior and the label differ, not that the analysis failed.']);
  } else {
    out.push(['NMI vs reference label', 'not available', r.has_label ? 'could not be computed for this algorithm' : 'no reference label was selected',
      'Pick a label column in step 1 to see how well the communities line up with a known grouping. Without one, only the agreement between algorithms is shown.']);
  }
  out.push(['Coverage', `${s.connected_nodes} of ${s.sampled_entities}`, `${s.kept_pct_of_sample}% of the sample is in the graph`,
    'Entities with no link at this setting are left out. If coverage is low, lower the threshold or use the kNN graph.']);
  const tc = Object.entries(s.tier_counts || {}).map(([t, c]) => `${t}: ${c}`).join(', ');
  out.push(['Tiers', `${s.communities} communities`, tc, 'Communities are ranked by average total activity and split into three tiers. A tier describes relative activity inside this sample, not an outcome or a prediction.']);
  return out;
}

const GLOSSARY = [
  ['Cosine similarity', 'Compares the shape of two entities\' behavior (what they do), not how much they do it.'],
  ['Cohesion', 'Average similarity between members of one community (1 = identical behavior).'],
  ['Intra-density', 'Share of possible links that exist inside a community.'],
  ['Conductance', 'Share of a community\'s links that leave it. Lower means better separated.'],
  ['Average total activity', 'Mean of the summed magnitude per member; this is what ranks communities into tiers.'],
];

export function MetricGuide({ result }) {
  const notes = metricNotes(result);
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3>What the headline numbers mean for this run</h3>
      <div className="tablewrap" style={{ maxHeight: 'none' }}>
        <table><tbody>{notes.map(([name, value, verdict, text]) => (
          <tr key={name}><td style={{ width: '20%' }}><b>{name}</b></td><td style={{ width: '16%' }}><b>{value}</b></td>
            <td style={{ whiteSpace: 'normal' }}><b>{verdict}.</b> <span className="muted">{text}</span></td></tr>
        ))}</tbody></table>
      </div>
      <details style={{ marginTop: 8 }}>
        <summary className="muted small" style={{ cursor: 'pointer' }}>Glossary of the other metrics</summary>
        <ul className="small" style={{ margin: '6px 0 0', paddingLeft: 18 }}>{GLOSSARY.map(([k, v]) => <li key={k}><b>{k}:</b> {v}</li>)}</ul>
      </details>
    </div>
  );
}