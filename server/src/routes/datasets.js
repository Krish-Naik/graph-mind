import { Router } from 'express';
import multer from 'multer';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { config } from '../config.js';
import { HttpError } from '../errors.js';
import { engine } from '../engine.js';

const ALLOWED = new Set(['.csv', '.tsv', '.txt', '.xlsx', '.xls', '.zip', '.gz', '.tgz']);
const isArchive = (n) => /\.(zip|tar\.gz|tgz)$/i.test(n);
const safeName = (n) => path.basename(n).replace(/[^\w.\-]+/g, '_') || 'file';

export function datasetRoutes(store) {
  const r = Router();

  // ---------- upload plumbing (streams straight to disk; never buffered in memory) ----------
  const storage = multer.diskStorage({
    destination(req, _file, cb) {
      const dir = path.join(config.dataDir, req.datasetId);
      fs.mkdirSync(dir, { recursive: true });
      cb(null, dir);
    },
    filename(req, file, cb) {
      const dir = path.join(config.dataDir, req.datasetId);
      let name = safeName(file.originalname), n = 1;
      const { name: stem, ext } = path.parse(name);
      while (fs.existsSync(path.join(dir, name))) name = `${stem}_${n++}${ext}`;
      cb(null, name);
    },
  });
  const upload = multer({
    storage,
    limits: { fileSize: config.maxUploadBytes, files: 20 },
    fileFilter(_req, file, cb) {
      const ext = path.extname(file.originalname).toLowerCase();
      (ALLOWED.has(ext) && (ext !== '.gz' || isArchive(file.originalname))) ? cb(null, true) : cb(new HttpError(400, `Unsupported file type '${ext}'. Use CSV, TSV, TXT, XLSX, XLS, ZIP or TAR.GZ.`));
    },
  });

  async function toFileRecords(uploaded) {
    const files = [];
    const addOne = async (p, displayName) => {
      if (['.xlsx', '.xls'].includes(path.extname(p).toLowerCase())) p = (await engine.convert(p)).path;  // engine reads CSV only
      files.push({ id: randomUUID().slice(0, 8), originalName: displayName || path.basename(p), path: p, size: fs.statSync(p).size, profile: null });
    };
    for (const f of uploaded) {
      if (isArchive(f.originalname)) {
        for (const p of (await engine.unzip(f.path)).paths) await addOne(p);   // every data file inside becomes a dataset file
      } else {
        await addOne(f.path, f.originalname);
      }
    }
    return files;
  }

  const pub = (d) => ({
    id: d.id, name: d.name, createdAt: d.createdAt,
    files: d.files.map((f) => ({ id: f.id, originalName: f.originalName, size: f.size, profiled: !!f.profile }))
  });

  // ---------- routes ----------
  r.get('/', async (_req, res) => res.json((await store.datasets.list()).map(pub)));

  r.post('/', (req, res, next) => {
    req.datasetId = randomUUID();
    upload.array('files')(req, res, async (err) => {
      const dir = path.join(config.dataDir, req.datasetId);
      try {
        if (err) throw err;
        if (!req.files?.length) throw new HttpError(400, 'No files uploaded.');
        const files = await toFileRecords(req.files);
        const name = (req.body?.name || '').trim() || path.parse(files[0].originalName).name;
        res.status(201).json(pub(await store.datasets.create({ id: req.datasetId, name, files })));
      } catch (e) {
        fs.rmSync(dir, { recursive: true, force: true });
        next(e);
      }
    });
  });

  r.get('/:id', async (req, res) => res.json(pub(await getDataset(req.params.id))));

  r.post('/:id/files', async (req, res, next) => {
    const ds = await getDataset(req.params.id);
    req.datasetId = ds.id;
    upload.array('files')(req, res, async (err) => {
      try {
        if (err) throw err;
        if (!req.files?.length) throw new HttpError(400, 'No files uploaded.');
        const files = await toFileRecords(req.files);
        res.status(201).json(pub(await store.datasets.update(ds.id, { files: [...ds.files, ...files] })));
      } catch (e) { next(e); }
    });
  });

  r.delete('/:id', async (req, res) => {
    const ds = await getDataset(req.params.id);
    fs.rmSync(path.join(config.dataDir, ds.id), { recursive: true, force: true });
    for (const j of await store.jobs.list({ datasetId: ds.id })) await store.jobs.remove(j.id);
    await store.datasets.remove(ds.id);
    res.status(204).end();
  });

  r.get('/:id/files/:fileId/profile', async (req, res) => {
    const ds = await getDataset(req.params.id);
    const file = findFile(ds, req.params.fileId);
    if (!file.profile) {
      file.profile = await engine.profile(file.path);
      await store.datasets.update(ds.id, { files: ds.files });
    }
    res.json(file.profile);
  });

  r.post('/:id/files/:fileId/charts/auto', async (req, res) => {
    const file = findFile(await getDataset(req.params.id), req.params.fileId);
    res.json(await engine.autoCharts(file.path));
  });

  const specSchema = z.object({
    kind: z.enum(['bar', 'line', 'pie', 'scatter', 'histogram']),
    x: z.string().min(1),
    y: z.string().nullish(),
    agg: z.enum(['count', 'sum', 'mean', 'min', 'max']).default('count'),
    group: z.string().nullish(),
    bins: z.number().int().min(2).max(100).default(20),
    limit: z.number().int().min(1).max(200).default(30),
  });
  r.post('/:id/files/:fileId/charts/query', async (req, res) => {
    const spec = specSchema.parse(req.body);
    const file = findFile(await getDataset(req.params.id), req.params.fileId);
    res.json(await engine.chartQuery(file.path, spec));
  });

  async function getDataset(id) {
    const ds = await store.datasets.get(id);
    if (!ds) throw new HttpError(404, 'Dataset not found.');
    return ds;
  }
  const findFile = (ds, fileId) => {
    const f = ds.files.find((x) => x.id === fileId);
    if (!f) throw new HttpError(404, 'File not found in this dataset.');
    return f;
  };
  return r;
}
