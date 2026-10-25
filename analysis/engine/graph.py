"""Steps 2-4: scale -> cosine similarity -> graph.

Conventions (all covered by tests/test_graph_correctness.py)
---------------------------------------------------------
* Features are min-max scaled per column. A constant column becomes all zeros (it carries no
  information). An entity that has the column-minimum in EVERY behavior becomes the zero vector.
* Cosine similarity of a zero vector with anything is 0 (not NaN). Non-finite input is rejected.
* Similarities are clipped to [-1, 1] (floating point noise can give 1.0000000000000002 for
  identical vectors, which would otherwise fall outside histogram bins and thresholds of 1.0).
* The diagonal is set to 0; the graph never has self loops, duplicate edges or direction
  (it is a simple undirected `networkx.Graph`; the edge weight is the cosine similarity).
* An edge ONLY exists when its similarity is > 0. A zero-weight edge says "no similarity" and must
  not make an entity look connected.
* Threshold graph: edge (i, j) iff sim >= threshold (within SIM_EPS).
* kNN graph: every entity proposes its k most similar OTHER entities with sim > 0; the union is
  taken (symmetrised). Ties at the k-th similarity are all kept, so the result does not depend on
  the row order of the data (a node can therefore end up with degree > k when vectors are tied).
* Entities that end up with no edge are removed from the graph (as before) and reported via
  `graph_construction_report`, never silently.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import networkx as nx
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

SIM_EPS = 1e-12          # tolerance when comparing a similarity with a threshold / with a tie
_KNN_BLOCK = 2_000_000   # max (rows x n) cells held at once while selecting neighbours


def _as_float_matrix(x, name: str) -> np.ndarray:
    X = np.asarray(x.values if hasattr(x, "values") else x, dtype=float)
    if X.ndim != 2:
        raise ValueError(f"{name}: expected a 2-D array, got shape {X.shape}.")
    if not np.isfinite(X).all():
        raise ValueError(f"{name}: contains NaN or infinite values; clean or impute them first.")
    return X


def scale(matrix: pd.DataFrame | np.ndarray) -> np.ndarray:
    return MinMaxScaler().fit_transform(_as_float_matrix(matrix, "scale"))


def similarity(scaled: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity, symmetric, in [-1, 1], zero diagonal, zero vectors -> 0."""
    X = _as_float_matrix(scaled, "similarity")
    if X.shape[0] == 0:
        return np.zeros((0, 0))
    sim = cosine_similarity(X)
    sim = (sim + sim.T) * 0.5            # remove floating point asymmetry
    np.clip(sim, -1.0, 1.0, out=sim)
    np.fill_diagonal(sim, 0.0)
    return sim


def similarity_histogram(sim: np.ndarray, bins: int = 40) -> dict:
    """Distribution of pairwise similarities -> lets the UI help users pick a threshold.
    Every pair is counted: values are clipped into [0, 1] so float noise cannot drop pairs."""
    iu = np.triu_indices_from(sim, k=1)
    vals = sim[iu]
    counts, edges = np.histogram(np.clip(vals, 0.0, 1.0), bins=bins, range=(0.0, 1.0))
    pct = {str(p): (round(float(np.percentile(vals, p)), 4) if vals.size else 0.0) for p in (50, 75, 90, 95, 99)}
    return {
        "bins": [round(float(e), 3) for e in edges],
        "counts": counts.astype(int).tolist(),
        "percentiles": pct,
    }


def _check_inputs(sim: np.ndarray, ids: list, method: str) -> np.ndarray:
    sim = np.asarray(sim, dtype=float)
    n = len(ids)
    if sim.ndim != 2 or sim.shape != (n, n):
        raise ValueError(f"similarity matrix shape {sim.shape} does not match {n} entity ids.")
    if len(set(ids)) != n:
        raise ValueError("Entity ids must be unique; duplicates would silently merge graph nodes.")
    if method not in ("threshold", "knn"):
        raise ValueError(f"Unknown graph method {method!r} (use 'threshold' or 'knn').")
    if n and not np.isfinite(sim).all():
        raise ValueError("similarity matrix contains NaN or infinite values.")
    return sim


def _threshold_pairs(sim: np.ndarray, threshold: float):
    mask = np.triu((sim >= threshold - SIM_EPS) & (sim > 0.0), k=1)
    return np.nonzero(mask)


def _knn_pairs(sim: np.ndarray, k: int):
    n = sim.shape[0]
    k = max(1, min(int(k), n - 1))
    block_rows = max(1, _KNN_BLOCK // max(n, 1))
    chunks = []
    for start in range(0, n, block_rows):
        stop = min(start + block_rows, n)
        block = sim[start:stop].copy()
        block[np.arange(stop - start), np.arange(start, stop)] = -np.inf     # never pick itself
        rounded = np.round(block, 12)                                          # make float-noise ties real ties
        kth = np.partition(rounded, n - k, axis=1)[:, n - k]                   # k-th largest per row
        sel = (rounded >= kth[:, None]) & (block > 0.0)
        r, c = np.nonzero(sel)
        chunks.append(np.stack([r + start, c], axis=1))
    pairs = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, 2), dtype=int)
    if not len(pairs):
        return np.array([], dtype=int), np.array([], dtype=int)
    a, b = np.minimum(pairs[:, 0], pairs[:, 1]), np.maximum(pairs[:, 0], pairs[:, 1])
    uniq = np.unique(np.stack([a, b], axis=1), axis=0)
    return uniq[:, 0], uniq[:, 1]


def build_graph(sim: np.ndarray, ids: list, method: str = "threshold",
                threshold: float = 0.85, k: int = 10, drop_isolates: bool = True) -> nx.Graph:
    """Build the undirected similarity graph. Node ids are exactly `ids` (unique); weights are sim[i, j].

    With drop_isolates=True (the pipeline default) entities without any edge are removed.
    """
    ids = list(ids)
    sim = _check_inputs(sim, ids, method)
    n = len(ids)
    G = nx.Graph()
    G.add_nodes_from(ids)
    if n >= 2:
        rows, cols = _threshold_pairs(sim, threshold) if method == "threshold" else _knn_pairs(sim, k)
        G.add_weighted_edges_from((ids[i], ids[j], float(sim[i, j])) for i, j in zip(rows, cols))
    if drop_isolates:
        G.remove_nodes_from(list(nx.isolates(G)))
    return G


def threshold_sweep(sim: np.ndarray, taus=None) -> list[dict]:
    """For many candidate thresholds: how many edges / connected entities would the graph have?
    Lets the UI show the trade-off behind the chosen tau instead of a blind guess.
    Uses exactly the same edge rule as build_graph(method='threshold')."""
    n = sim.shape[0]
    if taus is None:
        taus = [round(t, 2) for t in np.arange(0.30, 1.0, 0.025)]
    vals = sim[np.triu_indices(n, k=1)] if n else np.array([])
    row_max = sim.max(axis=1) if n else np.array([])
    out = []
    for t in taus:
        edges = int(((vals >= t - SIM_EPS) & (vals > 0.0)).sum())
        conn = (row_max >= t - SIM_EPS) & (row_max > 0.0)
        out.append({"tau": float(t), "edges": edges, "connected": int(conn.sum()),
                    "connected_pct": round(100 * float(conn.mean()), 1) if n else 0.0})
    return out


def suggest_threshold(sweep: list[dict], min_connected_pct: float = 90.0) -> float | None:
    """Highest swept tau that still keeps at least `min_connected_pct` % of entities connected."""
    ok = [s["tau"] for s in sweep if s["connected_pct"] >= min_connected_pct and s["edges"] > 0]
    return max(ok) if ok else None


def graph_construction_report(G: nx.Graph, ids: list, sim: np.ndarray) -> dict:
    """Plain numbers about what graph construction did to the entity population."""
    n_in = len(ids)
    n_graph = G.number_of_nodes()
    has_peer = (sim > 0.0).any(axis=1) if n_in else np.array([], dtype=bool)
    in_graph = {n for n in G.nodes()}
    dropped = [i for i, e in enumerate(ids) if e not in in_graph]
    return {
        "entities_in": int(n_in),
        "entities_in_graph": int(n_graph),
        "entities_dropped": int(n_in - n_graph),
        # no positive similarity to anyone: zero vectors / fully orthogonal behaviour
        "dropped_no_positive_similarity": int(sum(1 for i in dropped if not has_peer[i])),
        # have some similar peer, but none reaches the threshold
        "dropped_below_threshold": int(sum(1 for i in dropped if has_peer[i])),
        "edges": int(G.number_of_edges()),
        "density": round(float(nx.density(G)), 6) if n_graph > 1 else 0.0,
        "components": int(nx.number_connected_components(G)) if n_graph else 0,
        "self_loops": int(nx.number_of_selfloops(G)),
    }


def embed_2d(scaled: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """PCA to 2-D so every entity can be drawn as a point (no edges needed).
    Returns (n x 2 coordinates, explained-variance ratio of the 2 axes)."""
    n, d = scaled.shape
    if n < 3 or d < 2:
        return np.zeros((n, 2)), [0.0, 0.0]
    pca = PCA(n_components=2, random_state=0)
    xy = pca.fit_transform(scaled)
    return xy, [round(float(v), 4) for v in pca.explained_variance_ratio_]