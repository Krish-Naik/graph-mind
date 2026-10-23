// End-to-end test through the HTTP API. Needs the engine (:8000) and server (:4000) running.
// Usage: node test/e2e.mjs [/path/to/oulad_folder]
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const API = process.env.API || 'http://localhost:4000/api';
const assert = (c, m) => { if (!c) { console.error('FAIL:', m); process.exit(1); } console.log('  ok -', m); };
const j = async (r) => { const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(`${r.status} ${d.error}`); return d; };

async function upload(files, name) {
  const fd = new FormData();
  fd.append('name', name);
  for (const f of files) fd.append('files', await fs.openAsBlob(f), path.basename(f));
  return j(await fetch(`${API}/datasets`, { method: 'POST', body: fd }));
}
async function runJob(dsId, mapping, params) {
  const job = await j(await fetch(`${API}/datasets/${dsId}/jobs`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mapping, params }) }));
  for (;;) {
    await new Promise((r) => setTimeout(r, 700));
    const s = await j(await fetch(`${API}/jobs/${job.id}`));
    if (s.status === 'done' || s.status === 'failed') return s;
  }
}

const health = await j(await fetch(`${API}/health`));
console.log('health', health);
assert(health.engine, 'engine reachable through server');

// ---- synthetic MovieLens-style dataset (multi-genre lookup with "|") ----
console.log('\n[MovieLens-style]');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ml-'));
const genres = ['Action|Comedy', 'Drama', 'Comedy|Romance', 'Action', 'Drama|Romance', 'Horror', 'Horror|Action', 'Comedy', 'Romance', 'Drama|Thriller'];
fs.writeFileSync(`${tmp}/movies.csv`, 'movieId,title,genres\n' + genres.map((g, i) => `${i},Movie ${i},${g}`).join('\n'));
let rows = 'userId,movieId,rating,timestamp\n';
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
for (let u = 0; u < 150; u++) { const taste = u % 3; for (let k = 0; k < 60; k++) {
  const m = Math.floor((taste === 0 ? rnd() * 4 : taste === 1 ? 3 + rnd() * 4 : 6 + rnd() * 4)); rows += `${u},${m},${1 + Math.floor(rnd() * 5)},${1600000000 + k}\n`; } }
fs.writeFileSync(`${tmp}/ratings.csv`, rows);
const ml = await upload([`${tmp}/ratings.csv`, `${tmp}/movies.csv`], 'ml-test');
const [ratings, movies] = ml.files;
assert(ml.files.length === 2, 'uploaded 2 files');
const prof = await j(await fetch(`${API}/datasets/${ml.id}/files/${ratings.id}/profile`));
assert(prof.rows === 9000, 'profile row count');
const auto = await j(await fetch(`${API}/datasets/${ml.id}/files/${ratings.id}/charts/auto`, { method: 'POST' }));
assert(auto.charts.length >= 2, `auto charts (${auto.charts.map((c) => c.kind).join(',')})`);
const q = await j(await fetch(`${API}/datasets/${ml.id}/files/${ratings.id}/charts/query`, { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'bar', x: 'rating', agg: 'count' }) }));
assert(q.rows.length === 5, 'custom chart query');
const mlMap = { mainFileId: ratings.id, entity_col: 'userId', behavior_col: 'genres', agg: 'count',
  lookup: { fileId: movies.id, source_key: 'movieId', lookup_key: 'movieId', split_delimiter: '|' } };
const chk = await j(await fetch(`${API}/datasets/${ml.id}/behavioral/check`, { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mapping: mlMap }) }));
assert(chk.ok && chk.stats.behaviors === 6, `eligibility ok, 6 genres (${chk.stats.behaviors})`);
assert(chk.similarity?.counts?.length === 40, 'similarity histogram at check step');
const job = await runJob(ml.id, mlMap, { sample_size: 150, threshold: 0.9, primary_algorithm: 'best_modularity' });
assert(job.status === 'done', `job done (${job.error || ''})`);
assert(job.result.summary.communities >= 2, `communities: ${job.result.summary.communities}`);
const dl = await fetch(`${API}/jobs/${job.id}/download`);
assert(dl.ok && (await dl.text()).startsWith('entity,community_id'), 'CSV download');
// error path: unsuitable mapping gives a readable message, not a crash
const bad = await fetch(`${API}/datasets/${ml.id}/behavioral/check`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ mapping: { ...mlMap, value_col: 'nope', agg: 'sum' } }) });
assert(bad.status === 422, `bad column -> 422 (${(await bad.json()).error.slice(0, 50)}...)`);
assert((await fetch(`${API}/datasets/${ml.id}`, { method: 'DELETE' })).status === 204, 'delete dataset');

// ---- real OULAD (optional) ----
const dir = process.argv[2];
if (dir) {
  console.log('\n[OULAD]');
  const t0 = Date.now();
  const ds = await upload(['studentVle.csv', 'vle.csv', 'studentInfo.csv'].map((f) => path.join(dir, f)), 'OULAD');
  console.log(`  upload took ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  const id = (n) => ds.files.find((f) => f.originalName === n).id;
  const m = { mainFileId: id('studentVle.csv'), entity_col: 'id_student', behavior_col: 'activity_type', value_col: 'sum_click', agg: 'sum',
    lookup: { fileId: id('vle.csv'), source_key: 'id_site', lookup_key: 'id_site' },
    label: { fileId: id('studentInfo.csv'), entity_col: 'id_student', label_col: 'final_result' } };
  const o = await runJob(ds.id, m, { sample_size: 300, threshold: 0.85 });
  assert(o.status === 'done', 'OULAD job done');
  const s = o.result.summary;
  assert(s.connected_nodes === 297 && s.edges === 2544 && s.communities === 15, `reproduces notebook: ${s.connected_nodes} nodes, ${s.edges} edges, ${s.communities} communities`);
  const a = await j(await fetch(`${API}/datasets/${ds.id}/files/${id('studentVle.csv')}/charts/auto`, { method: 'POST' }));
  console.log('  auto charts on 10M-row file:', a.charts.map((c) => c.id).join(', '), '| partial:', a.partial);
}

// ---- ZIP upload (optional 2nd arg = path to the original dataset .zip) ----
const zipPath = process.argv[3];
if (zipPath) {
  console.log('\n[OULAD as one ZIP, no studentInfo/label file used]');
  const t0 = Date.now();
  const ds = await upload([zipPath], 'OULAD-zip');
  console.log(`  zip upload+extract took ${((Date.now() - t0) / 1000).toFixed(1)}s -> ${ds.files.length} files: ${ds.files.map((f) => f.originalName).join(', ')}`);
  const id = (n) => ds.files.find((f) => f.originalName === n)?.id;
  assert(id('studentVle.csv') && id('vle.csv'), 'zip expanded into separate dataset files');
  const m = { mainFileId: id('studentVle.csv'), entity_col: 'id_student', behavior_col: 'activity_type', value_col: 'sum_click', agg: 'sum',
    lookup: { fileId: id('vle.csv'), source_key: 'id_site', lookup_key: 'id_site' } };
  const o = await runJob(ds.id, m, { sample_size: 300, threshold: 0.85 });
  assert(o.status === 'done', `job done without label file (${o.error || ''})`);
  assert(o.result.summary.connected_nodes === 297 && o.result.summary.communities === 15, 'same 297 nodes / 15 communities from the zip');
}
console.log('\nALL PASSED');
