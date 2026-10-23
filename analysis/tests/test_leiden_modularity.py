"""Leiden fallback, modularity decomposition, NMI between algorithms."""
import networkx as nx
import networkx.algorithms.community as nx_comm
import numpy as np

from engine.communities import leiden_pure, detect
from engine.graph_metrics import modularity_analysis, nmi_analysis


def planted(n_groups=4, size=20, p_in=0.5, p_out=0.02, seed=1):
    rng = np.random.default_rng(seed)
    G = nx.Graph()
    truth = {}
    for g in range(n_groups):
        for i in range(size):
            truth[g * size + i] = g
    nodes = list(truth)
    G.add_nodes_from(nodes)
    for a in nodes:
        for b in nodes:
            if a < b and rng.random() < (p_in if truth[a] == truth[b] else p_out):
                G.add_edge(a, b, weight=float(0.6 + 0.4 * rng.random()))
    return G, truth


def test_pure_leiden_recovers_planted_communities_and_they_are_connected():
    G, truth = planted()
    comms = leiden_pure(G, seed=42)
    assert sum(len(c) for c in comms) == G.number_of_nodes()
    assert all(nx.is_connected(G.subgraph(c)) for c in comms)        # Leiden's guarantee
    assert nx_comm.modularity(G, comms, weight="weight") > 0.55
    assert len(comms) == 4


def test_leiden_is_always_in_the_benchmark_even_without_leidenalg(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "leidenalg", None)              # simulate: not installed
    monkeypatch.setitem(sys.modules, "igraph", None)
    G, truth = planted()
    results, rows = detect(G, ["louvain", "leiden", "lpa"], 42, truth)
    leiden = next(r for r in rows if r["key"] == "leiden")
    assert "error" not in leiden and leiden["modularity"] > 0.5
    assert leiden["nmi"] is not None and leiden["backend"] == "built-in Python"


def test_modularity_decomposition_matches_networkx_and_sums_up():
    G, _ = planted()
    results, _ = detect(G, ["louvain", "leiden", "lpa"], 42)
    out = modularity_analysis(results, G, seed=1, n_random=10)
    assert out["available"] and len(out["algorithms"]) == 3
    for a in out["algorithms"]:
        assert abs(a["modularity"] - a["modularity_networkx"]) < 1e-5
        assert abs(sum(c["contribution"] for c in a["communities"]) - a["modularity"]) < 1e-4
        assert a["random_baseline"]["max"] < a["modularity"]          # real structure beats shuffled labels
    assert len(out["resolution_sweep"]) >= 3


def test_nmi_between_algorithms_needs_no_label():
    G, truth = planted()
    results, _ = detect(G, ["louvain", "leiden", "lpa"], 42)
    out = nmi_analysis(results, G, None)                              # no label at all
    assert out["available"] is False and "reason" in out
    m = out["pairwise_agreement"]["matrix"]
    assert len(m) == 3 and all(m[i][i] == 1.0 for i in range(3)) and m[0][1] > 0.8


def test_nmi_with_label_covers_every_algorithm():
    G, truth = planted()
    results, _ = detect(G, ["louvain", "leiden", "lpa"], 42)
    out = nmi_analysis(results, G, {n: str(g) for n, g in truth.items()}, "leiden")
    assert out["available"] and set(out["nmi_by_algorithm"]) == {"louvain", "leiden", "lpa"}
    assert all(v is not None and v > 0.7 for v in out["nmi_by_algorithm"].values())
    assert out["contingency"]["algorithm"] == "leiden"

def _fuzzy_graph(seed=3):
    """Overlapping groups, so finer / coarser partitions both exist (like real behavior data)."""
    return planted(n_groups=6, size=25, p_in=0.35, p_out=0.06, seed=seed)[0]


def test_leiden_resolution_is_respected_and_changes_the_result(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "leidenalg", None)              # test the built-in path (Python 3.14 users)
    monkeypatch.setitem(sys.modules, "igraph", None)
    G = _fuzzy_graph()
    res, rows = detect(G, ["louvain", "leiden"], 42, None, leiden_resolution=2.5)
    leiden = next(r for r in rows if r["key"] == "leiden")
    louvain = next(r for r in rows if r["key"] == "louvain")
    assert leiden["resolution"] == 2.5 and louvain["resolution"] == 1.0
    assert leiden["num_communities"] > louvain["num_communities"]        # finer communities
    assert leiden["modularity"] != louvain["modularity"]                 # figures are not a copy
    # modularity is always reported at gamma=1, so it must match networkx on the Leiden partition
    assert abs(leiden["modularity"] - nx_comm.modularity(G, res["leiden"], weight="weight")) < 1e-5


def test_default_leiden_resolution_differs_from_louvain_on_real_style_data():
    G, _ = planted(n_groups=5, size=30, p_in=0.3, p_out=0.07, seed=11)
    res, rows = detect(G, ["louvain", "leiden"], 42)                     # default gamma (1.5)
    a = {frozenset(c) for c in res["louvain"]}
    b = {frozenset(c) for c in res["leiden"]}
    assert a != b


def test_louvain_is_unchanged_by_the_leiden_setting():
    G = _fuzzy_graph()
    r1, _ = detect(G, ["louvain", "leiden"], 42, None, leiden_resolution=1.0)
    r2, _ = detect(G, ["louvain", "leiden"], 42, None, leiden_resolution=3.0)
    assert {frozenset(c) for c in r1["louvain"]} == {frozenset(c) for c in r2["louvain"]}