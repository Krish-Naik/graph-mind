"""Tests for the extra data the dashboard charts need. Run: pytest -q"""
import json
import numpy as np, pandas as pd, pytest
from engine.schemas import RunRequest, Mapping, LookupSpec, Params
from engine import runner
from engine.graph import build_graph, similarity, threshold_sweep


@pytest.fixture
def res(tmp_path):
    rng = np.random.default_rng(0)
    rows = []
    protos = {"hi": [50, 5, 5, 1], "mid": [5, 20, 3, 1], "lo": [1, 1, 8, 2]}
    for g, (name, base) in enumerate(protos.items()):
        for i in range(60):
            for site, b in enumerate(base):
                rows.append((g * 1000 + i, site, max(0, int(rng.normal(b * (g + 1), 1.5)))))
    pd.DataFrame(rows, columns=["uid", "site_id", "clicks"]).to_csv(tmp_path / "log.csv", index=False)
    pd.DataFrame({"site_id": range(4), "kind": ["video", "forum", "quiz", "home"]}).to_csv(tmp_path / "s.csv", index=False)
    m = Mapping(path=str(tmp_path / "log.csv"), entity_col="uid", behavior_col="kind", value_col="clicks",
                lookup=LookupSpec(path=str(tmp_path / "s.csv"), source_key="site_id", lookup_key="site_id"))
    return runner.run(RunRequest(mapping=m, params=Params(sample_size=None, threshold=0.9)))


def test_payload_is_json_safe(res):
    json.dumps(res)          # must not raise (numpy types would)


def test_community_fingerprints(res):
    for c in res["communities"]:
        assert set(c["profile"]) <= {b["name"] for b in res["behaviors"]}
        assert c["top_behaviors"] and c["top_behaviors"][0]["name"] == c["top_behavior"]
        assert c["min_total_activity"] <= c["median_total_activity"] <= c["max_total_activity"]
        if c["size"] > 1:
            assert 0.0 <= c["cohesion"] <= 1.0001


def test_sweep_is_monotonic(res):
    edges = [s["edges"] for s in res["sweep"]]
    assert edges == sorted(edges, reverse=True)       # higher tau can only remove edges
    conn = [s["connected"] for s in res["sweep"]]
    assert conn == sorted(conn, reverse=True)


def test_sweep_matches_real_graph(res):
    row = min(res["sweep"], key=lambda s: abs(s["tau"] - 0.9))
    assert row["edges"] == res["summary"]["edges"]


def test_nodes_have_pca_coordinates(res):
    assert all("x" in n and "y" in n for n in res["graph"]["nodes"])
    assert len(res["pca"]["explained"]) == 2
    assert len(res["pipeline"]) == 5


def test_knn_has_no_self_loops():
    rng = np.random.default_rng(0)
    X = np.zeros((40, 5)); X[15:] = rng.random((25, 5))      # 15 all-zero entities -> similarity 0 to everyone
    G = build_graph(similarity(X), list(range(40)), "knn", k=10)
    assert nx_selfloops(G) == 0


def nx_selfloops(G):
    return sum(1 for u, v in G.edges() if u == v)


def test_heatmap_baseline_matches_communities(res):
    """Communities partition the connected entities, so size-weighted community means must equal the baseline."""
    total = sum(c["size"] for c in res["communities"])
    for b in res["behaviors"]:
        weighted = sum(c["size"] * c["profile"][b["name"]] for c in res["communities"]) / total
        assert weighted == pytest.approx(b["overall_mean"], abs=0.02)