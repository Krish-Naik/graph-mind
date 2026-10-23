"""Step 5: community detection (+ benchmark metrics)."""
from __future__ import annotations
import networkx as nx
import networkx.algorithms.community as nx_comm
from sklearn.metrics import normalized_mutual_info_score

NAMES = {"louvain": "Louvain", "leiden": "Leiden", "lpa": "Label Propagation"}


def _louvain(G, seed):
    return [set(c) for c in nx_comm.louvain_communities(G, weight="weight", seed=seed)]


def _leiden(G, seed):
    import igraph as ig
    import leidenalg
    nodes = list(G.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    g = ig.Graph(n=len(nodes), edges=[(idx[u], idx[v]) for u, v in G.edges()])
    g.es["weight"] = [d["weight"] for _, _, d in G.edges(data=True)]
    part = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition,
                                    weights="weight", seed=seed)
    return [{nodes[i] for i in comm} for comm in part]


def _lpa(G, seed):
    # asyn_lpa with a seed is deterministic and honours edge weights
    return [set(c) for c in nx_comm.asyn_lpa_communities(G, weight="weight", seed=seed)]


RUNNERS = {"louvain": _louvain, "leiden": _leiden, "lpa": _lpa}


def detect(G: nx.Graph, algorithms: list[str], seed: int = 42, true_labels=None):
    """Return (results, benchmark_rows). results[name] = list[set(node)]."""
    results, rows = {}, []
    for name in algorithms:
        try:
            comms = RUNNERS[name](G, seed)
        except Exception as exc:  # one failing algorithm must not kill the run
            rows.append({"algorithm": NAMES[name], "key": name, "error": str(exc)})
            continue
        results[name] = comms
        row = {
            "algorithm": NAMES[name], "key": name,
            "num_communities": len(comms),
            "modularity": round(float(nx_comm.modularity(G, comms, weight="weight")), 6),
            "nmi": None,
        }
        if true_labels is not None:
            node_to_c = {n: i for i, c in enumerate(comms) for n in c}
            order = list(G.nodes())
            mask = [true_labels.get(n) is not None and str(true_labels.get(n)) != "nan" for n in order]
            y_true = [true_labels[n] for n, ok in zip(order, mask) if ok]
            y_pred = [node_to_c[n] for n, ok in zip(order, mask) if ok]
            if len(set(y_true)) > 1:
                row["nmi"] = round(float(normalized_mutual_info_score(y_true, y_pred)), 6)
        rows.append(row)
    return results, rows
