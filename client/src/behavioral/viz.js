// Small helpers shared by the behavioral charts.
export const commColor = (id) => `hsl(${Math.round((id * 137.508) % 360)} 62% 48%)`;

export const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));

export function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function boxStats(values) {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  return {
    n: v.length, min: v[0], q1: quantile(v, 0.25), median: quantile(v, 0.5), q3: quantile(v, 0.75),
    max: v[v.length - 1], mean: v.reduce((a, b) => a + b, 0) / v.length,
  };
}

/** Is a node/community faded out by the current selection? (community selection wins over tier selection) */
export function isDimmed(item, selComm, selTier) {
  const comm = item.community ?? item.community_id;
  if (selComm != null) return comm !== selComm;
  if (selTier) return item.tier !== selTier;
  return false;
}

/** Tier boundaries on the "avg activity" axis, derived from the communities themselves. */
export function tierCutoffs(communities, labels) {
  const [low, mid, high] = labels;
  const by = (t) => communities.filter((c) => c.tier === t).map((c) => c.avg_total_activity);
  const L = by(low), M = by(mid), H = by(high);
  const out = {};
  if (L.length && M.length) out.low = (Math.max(...L) + Math.min(...M)) / 2;
  if (M.length && H.length) out.high = (Math.max(...M) + Math.min(...H)) / 2;
  else if (L.length && H.length) out.high = (Math.max(...L) + Math.min(...H)) / 2;
  return out;
}

/** Diverging colour for "lift vs average" (1 = same as everyone). Blue = more, orange = less. */
export function liftColor(lift) {
  if (lift == null || !Number.isFinite(lift)) return '#f1f5f9';
  const t = Math.max(-1, Math.min(1, Math.log2(Math.max(lift, 0.01)) / 2)); // 0.25x..4x -> -1..1
  const a = Math.abs(t) * 0.9;
  return t >= 0 ? `rgba(37,99,235,${a})` : `rgba(234,88,12,${a})`;
}
export const shareColor = (s) => `rgba(37,99,235,${Math.min(1, s * 1.6)})`;

/** Readable ticks (1, 2, 5, 10, 20, 50 ...) for a log axis between min and max. */
export function logTicks(min, max) {
  const out = [];
  if (!(min > 0) || !(max > min)) return out;
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e += 1) {
    for (const m of [1, 2, 5]) { const v = m * 10 ** e; if (v >= min && v <= max) out.push(v); }
  }
  return out;
}