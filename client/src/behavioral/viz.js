// Small helpers shared by the behavioral charts.
// comma syntax on purpose: Cytoscape rejects the space-separated hsl() form
export const commColor = (id) => `hsl(${Math.round((id * 137.508) % 360)}, 62%, 48%)`;

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

/* ======================================================================================
   Community-detection graph helpers (used by CommunityGraphs.jsx)
   ====================================================================================== */

// 20 clearly different colours; beyond that fall back to golden-angle hues.
const CATEGORICAL = ['#2563eb', '#f97316', '#16a34a', '#dc2626', '#9333ea', '#0891b2', '#db2777', '#65a30d', '#ca8a04', '#475569',
  '#60a5fa', '#fdba74', '#86efac', '#fca5a5', '#c4b5fd', '#67e8f9', '#f9a8d4', '#bef264', '#fde047', '#94a3b8'];
export const paletteColor = (i) => (i < CATEGORICAL.length ? CATEGORICAL[i] : `hsl(${Math.round((i * 137.508) % 360)}, 60%, 50%)`);

/**
 * Give every community of `membership` a colour index. Communities that mostly contain the same
 * entities as a community of the reference partition get the SAME colour, so Louvain / Leiden / LPA
 * can be compared by eye. Greedy matching by overlap size; the rest get fresh colours.
 * Returns { colorOf: number[] (per community id) }.
 */
export function alignColors(refMembership, membership) {
  const nComm = membership.length ? Math.max(...membership) + 1 : 0;
  if (!refMembership || refMembership === membership) {
    // reference itself: biggest community gets colour 0, next 1, ...
    const size = new Array(nComm).fill(0);
    membership.forEach((c) => { size[c] += 1; });
    const order = [...size.keys()].sort((a, b) => size[b] - size[a]);
    const colorOf = new Array(nComm).fill(0);
    order.forEach((c, rank) => { colorOf[c] = rank; });
    return { colorOf };
  }
  const nRef = Math.max(...refMembership) + 1;
  const overlap = new Map();
  membership.forEach((c, i) => { const key = c * (nRef + 1) + refMembership[i]; overlap.set(key, (overlap.get(key) || 0) + 1); });
  const pairs = [...overlap.entries()].map(([key, n]) => ({ c: Math.floor(key / (nRef + 1)), r: key % (nRef + 1), n })).sort((a, b) => b.n - a.n);
  // colour index of a reference community = its rank by size (same rule as above)
  const rsize = new Array(nRef).fill(0);
  refMembership.forEach((c) => { rsize[c] += 1; });
  const rorder = [...rsize.keys()].sort((a, b) => rsize[b] - rsize[a]);
  const rankOf = new Array(nRef).fill(0);
  rorder.forEach((c, rank) => { rankOf[c] = rank; });
  const colorOf = new Array(nComm).fill(-1);
  const usedRef = new Set();
  pairs.forEach(({ c, r }) => {
    if (colorOf[c] === -1 && !usedRef.has(r)) { colorOf[c] = rankOf[r]; usedRef.add(r); }
  });
  let next = nRef;
  for (let c = 0; c < nComm; c += 1) if (colorOf[c] === -1) { colorOf[c] = next; next += 1; }
  return { colorOf };
}

function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Deterministic "clustered" layout: every community becomes a compact disc (members on a
 * sunflower spiral, busiest entity in the centre), and the discs are arranged so that
 * communities that share many edges sit next to each other and no two discs overlap.
 * nodes: [{id,total}], membership: number[] aligned with nodes, edges: [{source,target,weight}].
 * Returns Map(id -> {x,y}).
 */
export function layoutClusters(nodes, membership, edges, spacing = 9) {
  const groups = new Map();
  nodes.forEach((n, i) => { const c = membership[i]; if (!groups.has(c)) groups.set(c, []); groups.get(c).push(i); });
  const ids = [...groups.keys()];
  const R = new Map(ids.map((c) => [c, spacing * Math.sqrt(groups.get(c).length) + 8]));
  const posIdx = new Map(nodes.map((n, i) => [String(n.id), i]));

  // cross-community link strength
  const link = new Map();
  edges.forEach((e) => {
    const a = membership[posIdx.get(String(e.source))], b = membership[posIdx.get(String(e.target))];
    if (a == null || b == null || a === b) return;
    const key = a < b ? `${a}|${b}` : `${b}|${a}`;
    link.set(key, (link.get(key) || 0) + 1);
  });
  const maxLink = Math.max(1, ...link.values());

  // initial: biggest first on a spiral
  const rnd = mulberry32(7);
  const order = [...ids].sort((a, b) => groups.get(b).length - groups.get(a).length);
  const P = new Map();
  order.forEach((c, i) => {
    const r = 60 * Math.sqrt(i + 0.3), t = i * 2.399963 + rnd() * 0.3;
    P.set(c, { x: r * Math.cos(t), y: r * Math.sin(t) });
  });

  for (let it = 0; it < 400; it += 1) {
    const cool = 1 - it / 400;
    const F = new Map(ids.map((c) => [c, { x: 0, y: 0 }]));
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        const a = ids[i], b = ids[j], pa = P.get(a), pb = P.get(b);
        let dx = pb.x - pa.x, dy = pb.y - pa.y;
        let d = Math.hypot(dx, dy);
        if (d < 1e-6) { dx = rnd() - 0.5; dy = rnd() - 0.5; d = Math.hypot(dx, dy); }
        const want = R.get(a) + R.get(b) + 14;
        const ux = dx / d, uy = dy / d;
        let f = 0;
        if (d < want) f = -(want - d) * 0.5;                          // push apart when overlapping
        else {
          const s = link.get(a < b ? `${a}|${b}` : `${b}|${a}`);
          if (s) f = Math.min(d - want, 220) * 0.06 * (0.3 + s / maxLink);  // pull linked communities together
          else f = -Math.min(2000 / (d * d) * 8, 1);                  // faint global repulsion
        }
        F.get(a).x += ux * f; F.get(a).y += uy * f;      // f > 0 pulls a toward b, f < 0 pushes apart
        F.get(b).x -= ux * f; F.get(b).y -= uy * f;
      }
    }
    ids.forEach((c) => {
      const p = P.get(c), f = F.get(c);
      p.x += (f.x - p.x * 0.004) * cool; p.y += (f.y - p.y * 0.004) * cool;  // tiny gravity keeps it compact
    });
  }

  const out = new Map();
  ids.forEach((c) => {
    const members = groups.get(c).slice().sort((a, b) => (nodes[b].total || 0) - (nodes[a].total || 0));
    const centre = P.get(c);
    members.forEach((idx, k) => {
      const r = spacing * Math.sqrt(k + 0.5), t = k * 2.399963;
      out.set(String(nodes[idx].id), { x: centre.x + r * Math.cos(t), y: centre.y + r * Math.sin(t) });
    });
  });
  return out;
}

/** Strength wording for a modularity value. */
export function modularityStrength(q) {
  if (q == null) return { label: 'n/a', color: '#94a3b8' };
  if (q >= 0.5) return { label: 'strong', color: '#16a34a' };
  if (q >= 0.3) return { label: 'moderate', color: '#f59e0b' };
  if (q > 0) return { label: 'weak', color: '#ea580c' };
  return { label: 'none', color: '#dc2626' };
}