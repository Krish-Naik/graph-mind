"""Community detection (+ benchmark metrics).

Louvain           : networkx, resolution gamma = 1 (the standard modularity optimum; reproduces the notebook).
Leiden            : `leidenalg` when installed, otherwise the self-contained pure-Python Leiden below.
                    It has its OWN, visible resolution parameter (`leiden_resolution`). Why: at gamma = 1 Leiden
                    and Louvain maximise the very same function (modularity) and on well-separated graphs they land
                    on practically the same partition, so a side-by-side comparison would be a carbon copy.
                    A higher gamma makes Leiden look for finer communities, which gives a genuinely different
                    (and honestly labelled) result. Set it to 1.0 to get the textbook Leiden.
Label Propagation : networkx.

Every algorithm's modularity is reported at gamma = 1 so the numbers are directly comparable.
"""
from __future__ import annotations
import math
import random
import networkx as nx
import networkx.algorithms.community as nx_comm
from sklearn.metrics import normalized_mutual_info_score

NAMES = {"louvain": "Louvain", "leiden": "Leiden", "lpa": "Label Propagation"}
DEFAULT_LEIDEN_RESOLUTION = 1.5


# ---------------------------------------------------------------------------------------------
# Louvain / LPA
# ---------------------------------------------------------------------------------------------
def _louvain(G, seed):
    return [set(c) for c in nx_comm.louvain_communities(G, weight="weight", seed=seed)]


def _lpa(G, seed):
    # asyn_lpa with a seed is deterministic and honours edge weights
    return [set(c) for c in nx_comm.asyn_lpa_communities(G, weight="weight", seed=seed)]


# ---------------------------------------------------------------------------------------------
# Leiden
# ---------------------------------------------------------------------------------------------
def _leiden_leidenalg(G, seed, resolution: float = 1.0):
    import igraph as ig
    import leidenalg
    nodes = list(G.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    g = ig.Graph(n=len(nodes), edges=[(idx[u], idx[v]) for u, v in G.edges()])
    g.es["weight"] = [d["weight"] for _, _, d in G.edges(data=True)]
    # RBConfiguration gamma = 1 is modularity; gamma > 1 favours more, tighter communities.
    # n_iterations = -1: keep iterating until the partition no longer improves.
    part = leidenalg.find_partition(
        g, leidenalg.RBConfigurationVertexPartition,
        weights="weight", seed=seed, n_iterations=-1,
        resolution_parameter=float(resolution),
    )
    return [{nodes[i] for i in comm} for comm in part]


def leiden_pure(G, seed: int = 42, resolution: float = 1.0, theta: float = 0.01,
                max_levels: int = 50):
    """Leiden (Traag, Waltman & van Eck 2019) optimising weighted modularity.

    Three phases per level: fast local moving -> refinement (a node is only merged into a
    refined community when both sides are well connected to their parent community, which is
    what guarantees connected communities) -> aggregation on the refined partition.
    Self-contained, so it works on any Python version.
    """
    rng = random.Random(seed)
    nodes = list(G.nodes())
    n0 = len(nodes)
    if n0 == 0:
        return []
    idx = {n: i for i, n in enumerate(nodes)}

    adj = [dict() for _ in range(n0)]          # neighbour -> weight (no self loops)
    selfw = [0.0] * n0                          # weight of self loops (counted once)
    for u, v, d in G.edges(data=True):
        w = float(d.get("weight", 1.0))
        a, b = idx[u], idx[v]
        if a == b:
            selfw[a] += w
        else:
            adj[a][b] = adj[a].get(b, 0.0) + w
            adj[b][a] = adj[b].get(a, 0.0) + w

    def degrees(adj_, selfw_):
        return [sum(a.values()) + 2.0 * s for a, s in zip(adj_, selfw_)]

    k = degrees(adj, selfw)
    m2 = sum(k)                                  # 2m
    if m2 <= 0:
        return [{n} for n in nodes]

    orig_to_node = list(range(n0))               # original node -> node of the current aggregate graph
    part = list(range(n0))                       # community of every aggregate node

    for _ in range(max_levels):
        n = len(adj)

        # ---- phase 1: fast local moving -------------------------------------------------
        tot = {}
        for v in range(n):
            tot[part[v]] = tot.get(part[v], 0.0) + k[v]
        queue = list(range(n))
        rng.shuffle(queue)
        in_q = [True] * n
        qi = 0
        while qi < len(queue):
            v = queue[qi]
            qi += 1
            in_q[v] = False
            cur = part[v]
            w_to = {}
            for u, w in adj[v].items():
                w_to[part[u]] = w_to.get(part[u], 0.0) + w
            tot[cur] -= k[v]
            best_c, best_gain = cur, w_to.get(cur, 0.0) - resolution * k[v] * tot[cur] / m2
            for c, w in w_to.items():
                if c == cur:
                    continue
                gain = w - resolution * k[v] * tot[c] / m2
                if gain > best_gain + 1e-12:
                    best_c, best_gain = c, gain
            tot[best_c] = tot.get(best_c, 0.0) + k[v]
            if best_c != cur:
                part[v] = best_c
                for u in adj[v]:
                    if part[u] != best_c and not in_q[u]:
                        in_q[u] = True
                        queue.append(u)

        comms = {}
        for v in range(n):
            comms.setdefault(part[v], []).append(v)
        if len(comms) == n:                      # every community is a single node: converged
            break

        # ---- phase 2: refinement --------------------------------------------------------
        ref = list(range(n))                     # refined community id per node (starts as singletons)
        ref_members = {v: [v] for v in range(n)}
        ref_tot = {v: k[v] for v in range(n)}
        for members in comms.values():
            if len(members) == 1:
                continue
            k_c = sum(k[v] for v in members)
            mem = set(members)
            ext = {v: sum(w for u, w in adj[v].items() if u in mem) for v in members}
            ref_ext = dict(ext)                  # w(R, C \ R) for every refined group R inside C
            order = members[:]
            rng.shuffle(order)
            for v in order:
                if len(ref_members[ref[v]]) != 1:
                    continue                     # already part of a bigger refined community
                if ext[v] < resolution * k[v] * (k_c - k[v]) / m2 - 1e-12:
                    continue                     # v is not well connected to its community
                w_to = {}
                for u, w in adj[v].items():
                    if u in mem and ref[u] != ref[v]:
                        w_to[ref[u]] = w_to.get(ref[u], 0.0) + w
                cand, gains = [], []
                for r, w in w_to.items():
                    if ref_ext[r] < resolution * ref_tot[r] * (k_c - ref_tot[r]) / m2 - 1e-12:
                        continue                 # that refined group is not well connected either
                    dq = 2.0 * (w - resolution * k[v] * ref_tot[r] / m2) / m2   # modularity gain
                    if dq >= 0:
                        cand.append(r)
                        gains.append(dq)
                if not cand:
                    continue
                gmax = max(gains)
                probs = [math.exp((g - gmax) / theta) for g in gains]
                r = rng.choices(cand, weights=probs, k=1)[0]
                old, w_vr = ref[v], w_to[r]
                ref_ext[r] = ref_ext[r] + ext[v] - 2.0 * w_vr
                ref_tot[r] += k[v]
                ref_members[r].append(v)
                ref[v] = r
                del ref_members[old], ref_tot[old], ref_ext[old]

        # ---- phase 3: aggregation on the REFINED partition --------------------------------
        new_id = {r: i for i, r in enumerate(ref_members.keys())}
        agg_n = len(new_id)
        agg_adj = [dict() for _ in range(agg_n)]
        agg_self = [0.0] * agg_n
        agg_part = [0] * agg_n
        for v in range(n):
            a = new_id[ref[v]]
            agg_part[a] = part[v]                # initial partition = the phase-1 communities
            agg_self[a] += selfw[v]
            for u, w in adj[v].items():
                b = new_id[ref[u]]
                if a == b:
                    agg_self[a] += w / 2.0       # an internal edge is seen from both ends
                else:
                    agg_adj[a][b] = agg_adj[a].get(b, 0.0) + w
        orig_to_node = [new_id[ref[x]] for x in orig_to_node]
        adj, selfw, part = agg_adj, agg_self, agg_part
        k = degrees(adj, selfw)
        if agg_n == n:                           # refinement merged nothing: no further progress
            break

    groups = {}
    for i in range(n0):
        groups.setdefault(part[orig_to_node[i]], set()).add(nodes[i])
    return list(groups.values())


def _leiden(G, seed, resolution: float = DEFAULT_LEIDEN_RESOLUTION):
    """Return (communities, backend_name). leidenalg first, built-in Python otherwise."""
    try:
        return _leiden_leidenalg(G, seed, resolution), "leidenalg"
    except Exception:
        return leiden_pure(G, seed, resolution=resolution), "built-in Python"


def detect(G: nx.Graph, algorithms: list[str], seed: int = 42, true_labels=None,
           leiden_resolution: float = DEFAULT_LEIDEN_RESOLUTION):
    """Return (results, benchmark_rows). results[name] = list[set(node)]."""
    results, failed, meta = {}, [], {}
    for name in algorithms:
        try:
            if name == "leiden":
                results[name], backend = _leiden(G, seed, leiden_resolution)
                meta[name] = {"backend": backend, "resolution": float(leiden_resolution)}
            elif name == "louvain":
                results[name] = _louvain(G, seed)
                meta[name] = {"resolution": 1.0}
            else:
                results[name] = _lpa(G, seed)
        except Exception as exc:  # one failing algorithm must not kill the run
            failed.append({"algorithm": NAMES[name], "key": name, "error": str(exc)})
    rows = []
    for name in algorithms:
        hit = next((r for r in failed if r["key"] == name), None)
        if hit:
            rows.append(hit)
            continue
        if name not in results:
            continue
        comms = results[name]
        row = {
            "algorithm": NAMES[name], "key": name,
            "num_communities": len(comms),
            # always evaluated at gamma = 1 so Louvain / Leiden / LPA can be compared fairly
            "modularity": round(float(nx_comm.modularity(G, comms, weight="weight")), 6),
            "nmi": None,
        }
        row.update(meta.get(name, {}))
        if true_labels is not None:
            node_to_c = {n: i for i, c in enumerate(comms) for n in c}
            order_n = list(G.nodes())
            mask = [true_labels.get(n) is not None and str(true_labels.get(n)) != "nan" for n in order_n]
            y_true = [true_labels[n] for n, ok in zip(order_n, mask) if ok]
            y_pred = [node_to_c[n] for n, ok in zip(order_n, mask) if ok]
            if len(set(y_true)) > 1:
                row["nmi"] = round(float(normalized_mutual_info_score(y_true, y_pred)), 6)
        rows.append(row)
    return results, rows