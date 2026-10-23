// Thin client for the Python engine. The browser never talks to it directly.
import { config } from './config.js';
import { HttpError } from './errors.js';

async function call(route, body, timeoutMs = 60_000) {
  let res;
  try {
    res = await fetch(config.engineUrl + route, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new HttpError(502, `Analysis engine unreachable (${config.engineUrl}). Is it running? ${e.message}`);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    let msg = data.detail ?? `Engine error ${res.status}`;
    if (Array.isArray(msg)) msg = msg.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    throw new HttpError(res.status === 422 || res.status === 400 ? 422 : 502, String(msg));
  }
  return res.json();
}

export const engine = {
  profile: (path) => call('/profile', { path }, 120_000),
  autoCharts: (path) => call('/charts/auto', { path }, 120_000),
  chartQuery: (path, spec) => call('/charts/query', { path, spec }, 120_000),
  unzip: (path) => call('/unzip', { path }, 15 * 60_000),
  convert: (path) => call('/convert', { path }, 300_000),
  check: (mapping, sample_size, random_state) => call('/behavioral/check', { mapping, sample_size, random_state }, 300_000),
  run: (mapping, params, out_dir) => call('/behavioral/run', { mapping, params, out_dir }, 20 * 60_000),
  async health() {
    try { return (await fetch(config.engineUrl + '/health', { signal: AbortSignal.timeout(2000) })).ok; }
    catch { return false; }
  },
};
