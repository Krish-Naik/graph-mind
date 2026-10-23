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
# NMI per algorithm AND per community-size bucket
# ---------------------------------------------------------------------------

def nmi_analysis(results: dict, G: nx.Graph, true_labels: dict | None) -> dict:
    """
    Extended NMI analysis:
    - nmi_by_algorithm: {algo -> nmi}
    - nmi_by_community_size: for the best algorithm, how NMI changes as we only consider
      communities above a size threshold (useful explainer)
    - label_distribution: how many nodes per true-label class
    """
    if true_labels is None:
        return {"available": False}

    order = [n for n in G.nodes() if true_labels.get(n) is not None and str(true_labels.get(n)) != "nan"]
    if len(order) < 5 or len(set(true_labels[n] for n in order)) < 2:
        return {"available": False, "reason": "Not enough labelled nodes or only one class."}

    from sklearn.metrics import normalized_mutual_info_score

    label_dist = {}
    for n in order:
        v = str(true_labels[n])
        label_dist[v] = label_dist.get(v, 0) + 1

    nmi_by_algo = {}
    for algo_key, communities in results.items():
        node_to_c = {n: i for i, c in enumerate(communities) for n in c}
        y_true = [true_labels[n] for n in order if n in node_to_c]
        y_pred = [node_to_c[n] for n in order if n in node_to_c]
        if len(set(y_true)) >= 2 and len(y_pred) >= 2:
            try:
                nmi_by_algo[algo_key] = round(float(normalized_mutual_info_score(y_true, y_pred)), 6)
            except Exception:
                nmi_by_algo[algo_key] = None

    # NMI vs minimum-community-size threshold (for the first valid algo)
    nmi_vs_min_size = []
    best_algo = next(iter(results)) if results else None
    if best_algo:
        communities = results[best_algo]
        node_to_c = {n: i for i, c in enumerate(communities) for n in c}
        all_sizes = sorted(set(len(c) for c in communities))
        for min_sz in sorted(set([1, 2, 3, 5, 10, 20] + all_sizes))[:20]:
            big_comms = [c for c in communities if len(c) >= min_sz]
            nodes_in = {n for c in big_comms for n in c}
            yt = [true_labels[n] for n in order if n in node_to_c and n in nodes_in]
            yp = [node_to_c[n] for n in order if n in node_to_c and n in nodes_in]
            if len(set(yt)) >= 2 and len(yp) >= 5:
                try:
                    nmi_vs_min_size.append({
                        "min_size": int(min_sz),
                        "nodes_covered": int(len(yp)),
                        "nmi": round(float(normalized_mutual_info_score(yt, yp)), 6),
                    })
                except Exception:
                    pass

    return {
        "available": True,
        "nmi_by_algorithm": nmi_by_algo,
        "nmi_vs_min_community_size": nmi_vs_min_size,
        "label_distribution": label_dist,
    }
