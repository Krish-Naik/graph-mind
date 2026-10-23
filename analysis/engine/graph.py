"""Steps 2-4: scale -> cosine similarity -> graph."""
from __future__ import annotations
import numpy as np
import pandas as pd
import networkx as nx
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler


def scale(matrix: pd.DataFrame) -> np.ndarray:
    return MinMaxScaler().fit_transform(matrix.values)


def similarity(scaled: np.ndarray) -> np.ndarray:
    sim = cosine_similarity(scaled)
    np.fill_diagonal(sim, 0.0)
    return sim


def similarity_histogram(sim: np.ndarray, bins: int = 40) -> dict:
    """Distribution of pairwise similarities -> lets the UI help users pick a threshold."""
    iu = np.triu_indices_from(sim, k=1)
    vals = sim[iu]
    counts, edges = np.histogram(vals, bins=bins, range=(0.0, 1.0))
    return {
        "bins": [round(float(e), 3) for e in edges],
        "counts": counts.astype(int).tolist(),
        "percentiles": {str(p): round(float(np.percentile(vals, p)), 4) for p in (50, 75, 90, 95, 99)},
    }


def build_graph(sim: np.ndarray, ids: list, method: str = "threshold",
                threshold: float = 0.85, k: int = 10) -> nx.Graph:
    n = len(ids)
    G = nx.Graph()
    G.add_nodes_from(ids)
    if method == "threshold":
        rows, cols = np.where(np.triu(sim >= threshold, k=1))
    else:  # kNN: connect each node to its k most similar nodes (symmetrised)
        k = min(k, n - 1)
        masked = sim.copy()
        np.fill_diagonal(masked, -1.0)          # a node must never pick itself as a neighbour
        nbrs = np.argpartition(-masked, k - 1, axis=1)[:, :k]
        r = np.repeat(np.arange(n), k)
        c = nbrs.ravel()
        a, b = np.minimum(r, c), np.maximum(r, c)
        pairs = np.unique(np.stack([a, b], axis=1), axis=0)
        rows, cols = pairs[:, 0], pairs[:, 1]
    for i, j in zip(rows, cols):
        G.add_edge(ids[i], ids[j], weight=float(sim[i, j]))
    G.remove_nodes_from(list(nx.isolates(G)))
    return G


def threshold_sweep(sim: np.ndarray, taus=None) -> list[dict]:
    """For many candidate thresholds: how many edges / connected entities would the graph have?
    Lets the UI show the trade-off behind the chosen tau instead of a blind guess."""
    n = sim.shape[0]
    if taus is None:
        taus = [round(t, 2) for t in np.arange(0.30, 1.0, 0.025)]
    vals = sim[np.triu_indices(n, k=1)]
    row_max = sim.max(axis=1) if n else np.array([])
    out = []
    for t in taus:
        out.append({"tau": float(t), "edges": int((vals >= t).sum()),
                    "connected": int((row_max >= t).sum()),
                    "connected_pct": round(100 * float((row_max >= t).mean()), 1) if n else 0.0})
    return out


def embed_2d(scaled: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """PCA to 2-D so every entity can be drawn as a point (no edges needed).
    Returns (n x 2 coordinates, explained-variance ratio of the 2 axes)."""
    n, d = scaled.shape
    if n < 3 or d < 2:
        return np.zeros((n, 2)), [0.0, 0.0]
    pca = PCA(n_components=2, random_state=0)
    xy = pca.fit_transform(scaled)
    return xy, [round(float(v), 4) for v in pca.explained_variance_ratio_]