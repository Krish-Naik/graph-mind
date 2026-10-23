import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ZodError } from 'zod';
import { config } from './config.js';
import { createStore } from './store/index.js';
import { engine } from './engine.js';
import { datasetRoutes } from './routes/datasets.js';
import { behavioralRoutes } from './routes/behavioral.js';
import { errorHandler, HttpError } from './errors.js';

const store = await createStore();
const app = express();
app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '10mb' }));

app.get('/api/health', async (_req, res) =>
  res.json({ server: 'ok', engine: await engine.health(), store: store.kind, dataDir: config.dataDir }));
app.use('/api/datasets', datasetRoutes(store));
app.use('/api', behavioralRoutes(store));

// production: serve the built React app from the same port
const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../client/dist');
if (fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.use((req, res, next) => (req.method === 'GET' && !req.path.startsWith('/api') ? res.sendFile(path.join(dist, 'index.html')) : next()));
}

app.use('/api', (_req, _res, next) => next(new HttpError(404, 'Route not found.')));
app.use((err, req, res, next) => {
  if (err instanceof ZodError) {
    err = new HttpError(400, err.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; '));
  }
  errorHandler(err, req, res, next);
});

const server = app.listen(config.port, () => {
  console.log(`API on http://localhost:${config.port}  | store: ${store.kind} | data: ${config.dataDir}`);
});
const stop = () => { server.close(); store.close().finally(() => process.exit(0)); };
process.on('SIGINT', stop); process.on('SIGTERM', stop);
