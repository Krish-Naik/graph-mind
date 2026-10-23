import path from 'node:path';
import fs from 'node:fs';

export const config = {
  port: Number(process.env.PORT) || 4000,
  // MUST be the same folder the Python engine uses as DATA_DIR
  dataDir: path.resolve(process.env.DATA_DIR || '../data'),
  engineUrl: process.env.ENGINE_URL || 'http://127.0.0.1:8000',
  mongoUri: process.env.MONGO_URI || '',
  maxUploadBytes: Number(process.env.MAX_UPLOAD_MB || 2048) * 1024 * 1024,
};
fs.mkdirSync(config.dataDir, { recursive: true });
