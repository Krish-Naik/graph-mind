import { Router } from 'express';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { config } from '../config.js';
import { HttpError } from '../errors.js';
import { engine } from '../engine.js';
import { enqueue } from '../queue.js';

const mappingSchema = z.object({
  mainFileId: z.string(),
  format: z.enum(['long', 'wide']).default('long'),
  entity_col: z.string().min(1),
  behavior_col: z.string().nullish(),
  value_col: z.string().nullish(),
  agg: z.enum(['sum', 'count', 'mean', 'max']).default('sum'),
  feature_cols: z.array(z.string()).nullish(),
  lookup: z.object({ fileId: z.string(), source_key: z.string(), lookup_key: z.string(),
    split_delimiter: z.string().nullish() }).nullish(),
  label: z.object({ fileId: z.string(), entity_col: z.string(), label_col: z.string() }).nullish(),
});

const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== undefined && v !== ''));

/** file ids (what the browser knows) -> absolute paths (what the engine needs) */
function resolveMapping(ds, m) {
  const p = (id) => {
    const f = ds.files.find((x) => x.id === id);
    if (!f) throw new HttpError(422, `Unknown file id '${id}' in mapping.`);
    return f.path;
  };
  return clean({
    path: p(m.mainFileId), format: m.format, entity_col: m.entity_col, behavior_col: m.behavior_col,
    value_col: m.value_col, agg: m.agg, feature_cols: m.feature_cols,
    lookup: m.lookup ? clean({ path: p(m.lookup.fileId), source_key: m.lookup.source_key,
      lookup_key: m.lookup.lookup_key, split_delimiter: m.lookup.split_delimiter }) : undefined,
    label: m.label ? { path: p(m.label.fileId), entity_col: m.label.entity_col, label_col: m.label.label_col } : undefined,
  });
}

const publicJob = ({ csvPath, ...j }) => j;

export function behavioralRoutes(store) {
  const r = Router();
  const dataset = async (id) => {
    const ds = await store.datasets.get(id);
    if (!ds) throw new HttpError(404, 'Dataset not found.');
    return ds;
  };

  r.post('/datasets/:id/behavioral/check', async (req, res) => {
    const ds = await dataset(req.params.id);
    const body = z.object({ mapping: mappingSchema, sampleSize: z.number().int().min(10).max(5000).nullish() }).parse(req.body);
    res.json(await engine.check(resolveMapping(ds, body.mapping), body.sampleSize ?? 300, 42));
  });

  r.post('/datasets/:id/jobs', async (req, res) => {
    const ds = await dataset(req.params.id);
    const body = z.object({ mapping: mappingSchema, params: z.record(z.string(), z.any()).default({}) }).parse(req.body);
    const engineMapping = resolveMapping(ds, body.mapping);          // fail fast on bad ids
    const job = await store.jobs.create({
      id: randomUUID(), datasetId: ds.id, status: 'queued', mapping: body.mapping, params: body.params,
      result: null, summary: null, error: null, csvPath: null,
    });
    const outDir = path.join(config.dataDir, ds.id, 'jobs', job.id);

    enqueue(async () => {
      await store.jobs.update(job.id, { status: 'running', startedAt: new Date().toISOString() });
      try {
        const result = await engine.run(engineMapping, body.params, outDir);
        const csvPath = result.outputs?.classified_csv ?? null;
        delete result.outputs;
        if (result.status === 'ok') {
          await store.jobs.update(job.id, { status: 'done', result, summary: result.summary, csvPath, finishedAt: new Date().toISOString() });
        } else {
          const why = result.status === 'ineligible' ? (result.eligibility?.errors || []).join(' ')
            : result.message || 'The analysis did not produce a result.';
          await store.jobs.update(job.id, { status: 'failed', error: why, result, finishedAt: new Date().toISOString() });
        }
      } catch (e) {
        await store.jobs.update(job.id, { status: 'failed', error: e.message, finishedAt: new Date().toISOString() });
      }
    });
    res.status(202).json(publicJob(job));
  });

  r.get('/datasets/:id/jobs', async (req, res) => {
    const jobs = await store.jobs.list({ datasetId: (await dataset(req.params.id)).id });
    res.json(jobs.map(({ result, csvPath, mapping, ...j }) => j));
  });

  r.get('/jobs/:jobId', async (req, res) => {
    const job = await store.jobs.get(req.params.jobId);
    if (!job) throw new HttpError(404, 'Job not found.');
    res.json(publicJob(job));
  });

  r.get('/jobs/:jobId/download', async (req, res) => {
    const job = await store.jobs.get(req.params.jobId);
    if (!job?.csvPath) throw new HttpError(404, 'No result file for this job.');
    res.download(job.csvPath, 'classified_entities.csv');
  });

  return r;
}
