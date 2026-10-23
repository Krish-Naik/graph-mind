export const DEFAULT_TIERS = ['Low Engagement / At-Risk', 'Moderate Engagement', 'High Engagement'];
export const OUTLIER = 'Outlier group (too small)';
export const PALETTE = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#ea580c'];

/** labels = [low, moderate, high] -> color per tier name */
export function tierColors(labels = DEFAULT_TIERS) {
  return { [labels[2]]: '#16a34a', [labels[1]]: '#2563eb', [labels[0]]: '#dc2626', [OUTLIER]: '#94a3b8' };
}

export function bytes(n) {
  if (n == null) return '';
  const u = ['B', 'KB', 'MB', 'GB']; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

export const num = (v, d = 2) => (v == null ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));

/** bin index of a threshold in the 40-bin similarity histogram */
export const binOf = (hist, tau) => Math.min(hist.counts.length - 1, Math.floor(tau * hist.counts.length + 1e-9));
export function pairsAbove(hist, tau) {
  const total = hist.counts.reduce((a, b) => a + b, 0) || 1;
  return hist.counts.slice(binOf(hist, tau)).reduce((a, b) => a + b, 0) / total;
}
