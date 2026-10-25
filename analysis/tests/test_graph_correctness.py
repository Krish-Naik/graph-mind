"""Correctness tests for similarity + graph construction. Run: pytest -q tests/test_graph_correctness.py

Every test uses tiny synthetic input with a known right answer.
"""
import numpy as np
import pandas as pd
import networkx as nx
import pytest

from engine.graph import (scale, similarity, similarity_histogram, build_graph, threshold_sweep,
                          suggest_threshold, graph_construction_report)
from engine.matrix import _finalize


def edge_set(G):
    return {frozenset((u, v)) for u, v in G.edges()}


# ----------------------------------------------------------------------------------------------
# similarity
# ----------------------------------------------------------------------------------------------
def test_zero_vector_has_zero_similarity_and_no_nan():
    X = np.array([[0, 0, 0], [1, 2, 3], [1, 2, 3]], dtype=float)
    S = similarity(X)
    assert np.isfinite(S).all()
    assert S[0].tolist() == [0.0, 0.0, 0.0] and S[:, 0].tolist() == [0.0, 0.0, 0.0]


def test_constant_feature_is_ignored_after_scaling():
    X = pd.DataFrame({"const": [5, 5, 5, 5], "a": [0, 1, 0, 1], "b": [1, 0, 1, 0]}, dtype=float)
    Z = scale(X)
    assert (Z[:, 0] == 0).all()                       # constant column carries no information
    S = similarity(Z)
    assert S[0, 2] == pytest.approx(1.0) and S[0, 1] == pytest.approx(0.0)


def test_duplicate_vectors_are_exactly_similar_and_never_exceed_one():
    rng = np.random.default_rng(0)
    X = rng.random((40, 7)); X[1] = X[0]; X[5] = X[4]
    S = similarity(scale(pd.DataFrame(X)))
    assert S.max() <= 1.0 and S.min() >= -1.0
    assert S[0, 1] == pytest.approx(1.0, abs=1e-12) and S[4, 5] == pytest.approx(1.0, abs=1e-12)
    assert np.allclose(S, S.T, atol=0) and (np.diag(S) == 0).all()


def test_histogram_counts_every_pair_even_with_float_noise():
    rng = np.random.default_rng(0)
    X = rng.random((40, 7)); X[1] = X[0]; X[5] = X[4]
    h = similarity_histogram(similarity(scale(pd.DataFrame(X))))
    assert sum(h["counts"]) == 40 * 39 // 2            # the old range=(0,1) silently dropped values > 1.0


def test_histogram_handles_tiny_input():
    h = similarity_histogram(np.zeros((1, 1)))
    assert sum(h["counts"]) == 0 and h["percentiles"]["50"] == 0.0


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_input_is_rejected_with_a_clear_message(bad):
    X = np.random.default_rng(0).random((10, 4)); X[2, 1] = bad
    with pytest.raises(ValueError, match="NaN or infinite"):
        scale(X)
    with pytest.raises(ValueError, match="NaN or infinite"):
        similarity(X)


def test_matrix_finalize_replaces_non_finite_and_reports_count():
    df = pd.DataFrame({"a": [1.0, np.inf, 3.0], "b": [np.nan, 2.0, -np.inf]}, index=[10, 11, 12])
    out = _finalize(df)
    assert np.isfinite(out.values).all() and out.attrs["non_finite_replaced"] == 3
    assert out.loc[11, "a"] == 0.0 and out.index.tolist() == [10, 11, 12]


# ----------------------------------------------------------------------------------------------
# graph construction
# ----------------------------------------------------------------------------------------------
def test_threshold_graph_matches_definition_and_has_no_self_loops_or_zero_edges():
    S = np.array([[0, .9, .5, 0], [.9, 0, .86, 0], [.5, .86, 0, 0], [0, 0, 0, 0]], dtype=float)
    G = build_graph(S, list("abcd"), "threshold", 0.85)
    assert edge_set(G) == {frozenset("ab"), frozenset("bc")}
    assert G["a"]["b"]["weight"] == 0.9
    assert "d" not in G                                  # isolated -> dropped (and documented)
    assert nx.number_of_selfloops(G) == 0 and not G.is_directed()


def test_threshold_zero_does_not_create_zero_weight_edges():
    S = np.zeros((6, 6)); S[0, 1] = S[1, 0] = 0.4
    G = build_graph(S, list(range(6)), "threshold", 0.0)
    assert edge_set(G) == {frozenset((0, 1))}
    assert all(d["weight"] > 0 for *_, d in G.edges(data=True))


def test_threshold_one_keeps_identical_vectors_despite_float_noise():
    rng = np.random.default_rng(1)
    X = rng.random((30, 9)); X[3] = X[2]
    G = build_graph(similarity(scale(pd.DataFrame(X))), list(range(30)), "threshold", 1.0)
    assert edge_set(G) == {frozenset((2, 3))}


def test_knn_never_links_zero_vectors_with_zero_weight_edges():
    rng = np.random.default_rng(0)
    X = np.zeros((40, 5)); X[15:] = rng.random((25, 5))      # 15 all-zero entities
    G = build_graph(similarity(X), list(range(40)), "knn", k=5)
    assert set(G.nodes()) == set(range(15, 40))              # zero vectors must NOT look "connected"
    assert all(d["weight"] > 0 for *_, d in G.edges(data=True))
    assert nx.number_of_selfloops(G) == 0


def test_knn_is_independent_of_row_order():
    rng = np.random.default_rng(5)
    X = rng.random((30, 6)); X[10:14] = X[10]               # a tied group of 4 identical vectors
    ids = [f"e{i}" for i in range(30)]
    G1 = build_graph(similarity(scale(pd.DataFrame(X))), ids, "knn", k=3)
    perm = rng.permutation(30)
    G2 = build_graph(similarity(scale(pd.DataFrame(X[perm]))), [ids[i] for i in perm], "knn", k=3)
    assert edge_set(G1) == edge_set(G2)                      # ids, not positions, define the graph
    for u, v, d in G1.edges(data=True):
        assert G2[u][v]["weight"] == pytest.approx(d["weight"], abs=1e-12)


def test_knn_ties_form_a_clique_instead_of_hubs():
    X = np.vstack([np.tile([1.0, 0, 0], (6, 1)), np.eye(3)[[1, 2, 1, 2]]])
    G = build_graph(similarity(X), list(range(10)), "knn", k=2)
    assert {G.degree(i) for i in range(6)} == {5}            # all six identical nodes are mutual neighbours


def test_knn_small_inputs():
    assert build_graph(np.zeros((1, 1)), ["x"], "knn", k=5).number_of_nodes() == 0
    S = np.array([[0, .7], [.7, 0]])
    assert edge_set(build_graph(S, ["x", "y"], "knn", k=5)) == {frozenset("xy")}
    assert build_graph(np.zeros((0, 0)), [], "threshold").number_of_nodes() == 0


def test_every_sim_is_an_edge_weight_exactly_once():
    rng = np.random.default_rng(2)
    S = similarity(scale(pd.DataFrame(rng.random((25, 5)))))
    ids = list(range(25))
    G = build_graph(S, ids, "threshold", 0.9)
    assert G.number_of_edges() == int(np.triu(S >= 0.9, 1).sum())
    for u, v, d in G.edges(data=True):
        assert d["weight"] == S[u, v] == S[v, u]


def test_duplicate_or_mismatched_ids_are_rejected():
    S = np.ones((3, 3)) - np.eye(3)
    with pytest.raises(ValueError, match="unique"):
        build_graph(S, ["a", "a", "b"], "threshold", 0.5)
    with pytest.raises(ValueError, match="shape"):
        build_graph(S, ["a", "b"], "threshold", 0.5)
    with pytest.raises(ValueError, match="Unknown graph method"):
        build_graph(S, ["a", "b", "c"], "mutual")
    S2 = S.copy(); S2[0, 1] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        build_graph(S2, ["a", "b", "c"], "threshold", 0.5)


def test_keep_isolates_option_preserves_all_node_ids():
    S = np.zeros((5, 5)); S[0, 1] = S[1, 0] = 0.9
    G = build_graph(S, list("abcde"), "threshold", 0.5, drop_isolates=False)
    assert list(G.nodes()) == list("abcde") and G.number_of_edges() == 1


def test_sweep_uses_the_same_rule_as_build_graph():
    rng = np.random.default_rng(3)
    X = rng.integers(0, 3, (60, 4)).astype(float)            # lots of exact ties and zero vectors
    S = similarity(scale(pd.DataFrame(X)))
    ids = list(range(60))
    for row in threshold_sweep(S, taus=[0.0, 0.3, 0.5, 0.9, 1.0]):
        G = build_graph(S, ids, "threshold", row["tau"])
        assert row["edges"] == G.number_of_edges()
        assert row["connected"] == G.number_of_nodes()


def test_suggest_threshold_and_construction_report():
    rng = np.random.default_rng(4)
    X = np.zeros((30, 4)); X[3:] = rng.random((27, 4))       # 3 zero vectors
    S = similarity(X); ids = list(range(30))
    sweep = threshold_sweep(S)
    assert suggest_threshold(sweep, 80.0) is not None
    G = build_graph(S, ids, "threshold", 0.99)
    rep = graph_construction_report(G, ids, S)
    assert rep["entities_in"] == 30 and rep["entities_in_graph"] == G.number_of_nodes()
    assert rep["dropped_no_positive_similarity"] == 3
    assert rep["entities_dropped"] == rep["dropped_no_positive_similarity"] + rep["dropped_below_threshold"]
    assert rep["self_loops"] == 0