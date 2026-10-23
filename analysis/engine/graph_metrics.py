"""Graph density, topology metrics, and per-algorithm analysis for the results dashboard."""
from __future__ import annotations
import numpy as np
import networkx as nx
import networkx.algorithms.community as nx_comm


# ---------------------------------------------------------------------------
# Graph-level density / topology
# ---------------------------------------------------------------------------

def graph_density_metrics(G: nx.Graph, sim: np.ndarray, ids: list) -> dict:
    """
    Compute comprehensive graph topology / density metrics.
    All values are JSON-serialisable (floats / ints / lists of dicts).
    """
    n = G.number_of_nodes()
    m = G.number_of_edges()
    if n == 0:
        return {}

    weights = [d["weight"] for _, _, d in G.edges(data=True)]

    # Basic
    density = nx.density(G)
    avg_degree = (2 * m / n) if n else 0.0
    degrees = [d for _, d in G.degree()]

    # Clustering (global + avg)
    global_cc = nx.transitivity(G)
    avg_cc = nx.average_clustering(G, weight="weight")

    # Connected components
    components = list(nx.connected_components(G))
    n_components = len(components)
    lcc_size = max(len(c) for c in components) if components else 0
    lcc_frac = lcc_size / n if n else 0.0

    # Diameter (on LCC only – full graph may be disconnected)
    try:
        lcc = G.subgraph(max(components, key=len)).copy()
        diameter = nx.diameter(lcc) if len(lcc) > 1 else 1
        avg_path = nx.average_shortest_path_length(lcc) if len(lcc) > 1 else 0.0
    except Exception:
        diameter = None
        avg_path = None

    # Degree distribution (for histogram)
    max_deg = max(degrees) if degrees else 0
    deg_hist, deg_bins = np.histogram(degrees, bins=min(30, max_deg + 1), range=(0, max_deg + 1))

    # Weight distribution
    w_hist, w_bins = np.histogram(weights, bins=30, range=(0.0, 1.0)) if weights else ([], [])

    # Assortativity
    try:
        assortativity = nx.degree_assortativity_coefficient(G)
    except Exception:
        assortativity = None

    # Centrality (computed only on LCC if large)
    target = lcc if lcc_size < 1000 else G
    try:
        bc_vals = list(nx.betweenness_centrality(target, weight="weight", normalized=True).values())
        avg_betweenness = float(np.mean(bc_vals))
        max_betweenness = float(np.max(bc_vals))
    except Exception:
        avg_betweenness = max_betweenness = None

    return {
        "n_nodes": int(n),
        "n_edges": int(m),
        "density": round(float(density), 6),
        "avg_degree": round(float(avg_degree), 3),
        "max_degree": int(max_deg),
        "global_clustering_coeff": round(float(global_cc), 6),
        "avg_clustering_coeff": round(float(avg_cc), 6),
        "n_components": int(n_components),
        "lcc_size": int(lcc_size),
        "lcc_fraction": round(float(lcc_frac), 4),
        "diameter": diameter,
        "avg_path_length": round(float(avg_path), 4) if avg_path is not None else None,
        "assortativity": round(float(assortativity), 6) if assortativity is not None else None,
        "avg_betweenness": round(float(avg_betweenness), 6) if avg_betweenness is not None else None,
        "max_betweenness": round(float(max_betweenness), 6) if max_betweenness is not None else None,
        "avg_edge_weight": round(float(np.mean(weights)), 4) if weights else None,
        "weight_distribution": {
            "bins": [round(float(b), 3) for b in w_bins],
            "counts": w_hist.astype(int).tolist() if len(w_hist) else [],
        },
        "degree_distribution": {
            "bins": [round(float(b), 1) for b in deg_bins],
            "counts": deg_hist.astype(int).tolist() if len(deg_hist) else [],
        },
    }


# ---------------------------------------------------------------------------
# Per-community density / cohesion for each algorithm
# ---------------------------------------------------------------------------

def community_density_profile(G: nx.Graph, communities: list[set]) -> list[dict]:
    """
    For each community: intra-community density, inter-community edge count,
    average internal edge weight, and cohesion vs. separation ratio.
    """
    node_to_comm = {n: i for i, c in enumerate(communities) for n in c}
    rows = []
    for cid, members in enumerate(communities):
        members = list(members)
        if not members:
            continue
        sub = G.subgraph(members)
        n = len(members)
        intra_edges = sub.number_of_edges()
        intra_density = nx.density(sub)
        intra_weights = [d["weight"] for _, _, d in sub.edges(data=True)]
        avg_intra_w = float(np.mean(intra_weights)) if intra_weights else 0.0

        # inter edges
        inter_edges = sum(
            1 for u in members for v in G.neighbors(u) if node_to_comm.get(v, cid) != cid
        )
        inter_weight = sum(
            G[u][v].get("weight", 0) for u in members for v in G.neighbors(u)
            if node_to_comm.get(v, cid) != cid
        )
        # conductance-like: inter / (inter + intra * 2)
        denom = inter_edges + 2 * intra_edges
        conductance = inter_edges / denom if denom else 0.0

        rows.append({
            "community_id": int(cid),
            "size": int(n),
            "intra_edges": int(intra_edges),
            "intra_density": round(float(intra_density), 6),
            "avg_intra_weight": round(float(avg_intra_w), 4),
            "inter_edges": int(inter_edges),
            "avg_inter_weight": round(float(inter_weight / max(inter_edges, 1)), 4),
            "conductance": round(float(conductance), 6),
        })
    return rows


# ---------------------------------------------------------------------------
# Algorithm-level comparison: full community stats for every algorithm run
# ---------------------------------------------------------------------------

def algorithm_comparison(results: dict, G: nx.Graph) -> list[dict]:
    """
    For every algorithm that produced communities, compute a richer profile:
    modularity, size stats, cohesion distribution, density profile.
    Returned list is ready for the front-end comparison charts.
    """
    out = []
    for algo_key, communities in results.items():
        try:
            mod = float(nx_comm.modularity(G, communities, weight="weight"))
        except Exception:
            mod = None

        sizes = [len(c) for c in communities]
        density_rows = community_density_profile(G, communities)
        intra_densities = [r["intra_density"] for r in density_rows]
        conductances = [r["conductance"] for r in density_rows]

        out.append({
            "algorithm": algo_key,
            "num_communities": len(communities),
            "modularity": round(mod, 6) if mod is not None else None,
            "size_distribution": {
                "min": int(min(sizes)) if sizes else 0,
                "max": int(max(sizes)) if sizes else 0,
                "mean": round(float(np.mean(sizes)), 2) if sizes else 0,
                "std": round(float(np.std(sizes)), 2) if sizes else 0,
                "histogram": _size_hist(sizes),
            },
            "intra_density": {
                "mean": round(float(np.mean(intra_densities)), 6) if intra_densities else None,
                "std": round(float(np.std(intra_densities)), 6) if intra_densities else None,
                "per_community": intra_densities,
            },
            "conductance": {
                "mean": round(float(np.mean(conductances)), 6) if conductances else None,
                "per_community": conductances,
            },
            "community_density_profile": density_rows,
        })
    return out


def _size_hist(sizes: list[int], bins: int = 10) -> dict:
    if not sizes:
        return {"bins": [], "counts": []}
    lo, hi = min(sizes), max(sizes)
    if lo == hi:
        return {"bins": [lo, hi + 1], "counts": [len(sizes)]}
    counts, edges = np.histogram(sizes, bins=min(bins, hi - lo + 1), range=(lo, hi + 1))
    return {
        "bins": [int(e) for e in edges],
        "counts": counts.astype(int).tolist(),
    }


# ---------------------------------------------------------------------------
# Modularity: the full calculation, per algorithm
# ---------------------------------------------------------------------------

def _strength(q: float) -> str:
    if q >= 0.5:
        return "strong"
    if q >= 0.3:
        return "moderate"
    if q > 0.0:
        return "weak"
    return "none"


def _arrays(G: nx.Graph):
    nodes = list(G.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    u = np.array([idx[a] for a, _ in G.edges()], dtype=int)
    v = np.array([idx[b] for _, b in G.edges()], dtype=int)
    w = np.array([d.get("weight", 1.0) for _, _, d in G.edges(data=True)], dtype=float)
    deg = np.zeros(len(nodes))
    np.add.at(deg, u, w)
    np.add.at(deg, v, w)
    return nodes, idx, u, v, w, deg


def _q_from_labels(lab, u, v, w, deg, m):
    """Weighted modularity Q = sum_c [ L_c/m - (d_c/2m)^2 ] for integer labels `lab`."""
    intra = w[lab[u] == lab[v]].sum()
    dc = np.bincount(lab, weights=deg)
    return float(intra / m - ((dc / (2 * m)) ** 2).sum())


def modularity_analysis(results: dict, G: nx.Graph, seed: int = 42, n_random: int = 50,
                        resolutions=None) -> dict:
    """Everything needed to SHOW how modularity was calculated.

    For each algorithm:
      Q (and a check against networkx), per-community terms
        L_c/m   = share of all edge weight that lies INSIDE community c (observed)
        (d_c/2m)^2 = share expected if edges were wired at random with the same degrees
        contribution = observed - expected     ->  Q is the sum of the contributions
      a random-label baseline (same community sizes, labels shuffled) so Q can be judged
    Plus a resolution sweep (Louvain) = how Q and the number of communities react to gamma.
    """
    if G.number_of_edges() == 0:
        return {"available": False}
    nodes, idx, u, v, w, deg = _arrays(G)
    m = float(w.sum())
    rng = np.random.default_rng(seed)

    algos = []
    for key, comms in results.items():
        lab = np.zeros(len(nodes), dtype=int)
        for ci, c in enumerate(comms):
            for n in c:
                lab[idx[n]] = ci
        n_c = len(comms)
        intra_c = np.zeros(n_c)
        same = lab[u] == lab[v]
        np.add.at(intra_c, lab[u][same], w[same])
        dc = np.bincount(lab, minlength=n_c, weights=deg)
        sizes = np.bincount(lab, minlength=n_c)
        q = float((intra_c / m - (dc / (2 * m)) ** 2).sum())
        rows = [{
            "community_id": int(c), "size": int(sizes[c]),
            "intra_weight": round(float(intra_c[c]), 4),
            "degree_sum": round(float(dc[c]), 4),
            "observed": round(float(intra_c[c] / m), 6),
            "expected": round(float((dc[c] / (2 * m)) ** 2), 6),
            "contribution": round(float(intra_c[c] / m - (dc[c] / (2 * m)) ** 2), 6),
        } for c in range(n_c)]
        # random baseline
        rq = []
        for _ in range(n_random):
            rq.append(_q_from_labels(rng.permutation(lab), u, v, w, deg, m))
        rq = np.array(rq)
        try:
            q_nx = float(nx_comm.modularity(G, comms, weight="weight"))
        except Exception:
            q_nx = None
        algos.append({
            "algorithm": key, "modularity": round(q, 6), "modularity_networkx": None if q_nx is None else round(q_nx, 6),
            "strength": _strength(q), "num_communities": n_c,
            "intra_weight_share": round(float(intra_c.sum() / m), 4),
            "expected_share": round(float(((dc / (2 * m)) ** 2).sum()), 4),
            "random_baseline": {"mean": round(float(rq.mean()), 6), "std": round(float(rq.std()), 6),
                                "max": round(float(rq.max()), 6), "n": int(n_random)},
            "communities": rows,
        })

    # --- resolution sweep (Louvain; fewer points on big graphs to keep the run fast) ---
    if resolutions is None:
        resolutions = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0] if G.number_of_edges() < 60000 else [0.5, 1.0, 2.0]
    sweep = []
    for g in resolutions:
        try:
            comms = nx_comm.louvain_communities(G, weight="weight", resolution=g, seed=seed)
            lab = np.zeros(len(nodes), dtype=int)
            for ci, c in enumerate(comms):
                for n in c:
                    lab[idx[n]] = ci
            sweep.append({"resolution": float(g), "num_communities": len(comms),
                          "modularity": round(_q_from_labels(lab, u, v, w, deg, m), 6)})
        except Exception:
            continue

    return {"available": True, "total_weight": round(m, 4), "n_edges": int(len(w)),
            "algorithms": algos, "resolution_sweep": sweep}


# ---------------------------------------------------------------------------
# NMI: against the label (when there is one) AND between the algorithms (always)
# ---------------------------------------------------------------------------

def _labels_of(communities, nodes):
    node_to_c = {n: i for i, c in enumerate(communities) for n in c}
    return [node_to_c[n] for n in nodes]


def nmi_analysis(results: dict, G: nx.Graph, true_labels: dict | None, primary: str | None = None) -> dict:
    """
    - pairwise_agreement : NMI between every pair of algorithms. ALWAYS available (needs no label),
                           so the NMI view is never empty.
    - nmi_by_algorithm   : NMI of each algorithm vs the label column (needs a label)
    - nmi_vs_min_community_size : NMI as small communities are excluded (primary algorithm)
    - contingency        : community x label counts for the primary algorithm
    - label_distribution : entities per label class
    """
    from sklearn.metrics import normalized_mutual_info_score as nmi

    out: dict = {"available": False}
    nodes = list(G.nodes())

    # ---- between algorithms (no label needed) ----
    keys = list(results.keys())
    if len(keys) >= 1:
        parts = {k: _labels_of(results[k], nodes) for k in keys}
        mat = [[1.0 if a == b else round(float(nmi(parts[a], parts[b])), 4) for b in keys] for a in keys]
        out["pairwise_agreement"] = {"keys": keys, "matrix": mat}

    if true_labels is None:
        out["reason"] = ("No label column was used, so NMI against a ground truth cannot be computed. "
                         "Tick \"Compare communities with a known label\" in step 1 of the wizard "
                         "(e.g. final_result in studentInfo.csv).")
        return out

    order = [n for n in nodes if true_labels.get(n) is not None and str(true_labels.get(n)) != "nan"]
    if len(order) < 5 or len(set(true_labels[n] for n in order)) < 2:
        out["reason"] = "Not enough labelled entities, or the label has only one class."
        return out

    label_dist = {}
    for n in order:
        label_dist[str(true_labels[n])] = label_dist.get(str(true_labels[n]), 0) + 1

    nmi_by_algo = {}
    for key, communities in results.items():
        node_to_c = {n: i for i, c in enumerate(communities) for n in c}
        y_true = [true_labels[n] for n in order if n in node_to_c]
        y_pred = [node_to_c[n] for n in order if n in node_to_c]
        try:
            nmi_by_algo[key] = round(float(nmi(y_true, y_pred)), 6) if len(set(y_true)) >= 2 else None
        except Exception:
            nmi_by_algo[key] = None

    base = primary if primary in results else (next(iter(results)) if results else None)
    sweep, cont = [], None
    if base:
        communities = results[base]
        node_to_c = {n: i for i, c in enumerate(communities) for n in c}
        all_sizes = sorted(set(len(c) for c in communities))
        for min_sz in sorted(set([1, 2, 3, 5, 10, 20] + all_sizes))[:20]:
            nodes_in = {n for c in communities if len(c) >= min_sz for n in c}
            yt = [true_labels[n] for n in order if n in nodes_in]
            yp = [node_to_c[n] for n in order if n in nodes_in]
            if len(set(yt)) >= 2 and len(yp) >= 5:
                try:
                    sweep.append({"min_size": int(min_sz), "nodes_covered": int(len(yp)),
                                  "nmi": round(float(nmi(yt, yp)), 6)})
                except Exception:
                    pass
        table = {}
        for n in order:
            table.setdefault(node_to_c[n], {})
            lab = str(true_labels[n])
            table[node_to_c[n]][lab] = table[node_to_c[n]].get(lab, 0) + 1
        cont = {"algorithm": base, "labels": sorted(label_dist, key=lambda x: -label_dist[x]),
                "rows": [{"community_id": int(c), "counts": cnt, "total": int(sum(cnt.values()))}
                         for c, cnt in sorted(table.items(), key=lambda kv: -sum(kv[1].values()))]}

    out.update({"available": True, "primary": base, "nmi_by_algorithm": nmi_by_algo,
                "nmi_vs_min_community_size": sweep, "label_distribution": label_dist,
                "contingency": cont})
    out.pop("reason", None)
    return out