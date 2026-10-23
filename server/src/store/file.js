// Zero-setup store: one JSON file on disk. Used when MONGO_URI is not set.
import fs from 'node:fs';
import path from 'node:path';
import { config } from '../config.js';

const FILE = path.join(config.dataDir, '_store.json');
let db = { datasets: {}, jobs: {} };
try { db = JSON.parse(fs.readFileSync(FILE, 'utf8')); } catch { /* first run */ }

let timer = null;
function persist() {
  clearTimeout(timer);
  timer = setTimeout(() => fs.writeFileSync(FILE + '.tmp', JSON.stringify(db)) || fs.renameSync(FILE + '.tmp', FILE), 100);
}
const clone = (x) => (x ? structuredClone(x) : null);

function collection(name) {
  return {
    async create(doc) { db[name][doc.id] = { ...doc, createdAt: new Date().toISOString() }; persist(); return clone(db[name][doc.id]); },
    async get(id) { return clone(db[name][id]); },
    async update(id, patch) {
      if (!db[name][id]) return null;
      Object.assign(db[name][id], patch, { updatedAt: new Date().toISOString() }); persist(); return clone(db[name][id]);
    },
    async remove(id) { delete db[name][id]; persist(); },
    async list(filter = {}) {
      return Object.values(db[name]).filter((d) => Object.entries(filter).every(([k, v]) => d[k] === v))
        .sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1)).map(clone);
    },
  };
}

export async function createFileStore() {
  // jobs that were running when the server stopped can never finish
  for (const j of Object.values(db.jobs)) if (['queued', 'running'].includes(j.status)) { j.status = 'failed'; j.error = 'Server restarted'; }
  return { kind: 'json-file', datasets: collection('datasets'), jobs: collection('jobs'), async close() {} };
}
