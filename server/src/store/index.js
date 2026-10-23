import { config } from '../config.js';
import { createFileStore } from './file.js';

export async function createStore() {
  if (config.mongoUri) {
    const { createMongoStore } = await import('./mongo.js');
    return createMongoStore(config.mongoUri);
  }
  return createFileStore();
}
