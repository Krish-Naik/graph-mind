"""Fast synthetic tests (no big dataset needed). Run: pytest -q"""
import numpy as np, pandas as pd, pytest
from engine.schemas import RunRequest, Mapping, LookupSpec, Params
from engine import runner
from engine.profiling import assign_tiers, OUTLIER


@pytest.fixture
def long_csv(tmp_path):
    """3 behavior archetypes x 60 entities each, as an event log + a lookup file."""
    rng = np.random.default_rng(0)
    rows = []
    protos = {"hi": [50, 5, 5, 1], "mid": [5, 20, 3, 1], "lo": [1, 1, 8, 2]}
    for g, (name, base) in enumerate(protos.items()):
        for i in range(60):
            uid = g * 1000 + i
            for site, b in enumerate(base):
                rows.append((uid, site, max(0, int(rng.normal(b * (g + 1), 1.5)))))
    pd.DataFrame(rows, columns=["uid", "site_id", "clicks"]).to_csv(tmp_path / "log.csv", index=False)
    pd.DataFrame({"site_id": range(4), "kind": ["video", "forum", "quiz", "home"]}).to_csv(tmp_path / "sites.csv", index=False)
    return tmp_path


def mapping(d):
    return Mapping(path=str(d / "log.csv"), entity_col="uid", behavior_col="kind", value_col="clicks",
                   lookup=LookupSpec(path=str(d / "sites.csv"), source_key="site_id", lookup_key="site_id"))


def test_end_to_end(long_csv):
    res = runner.run(RunRequest(mapping=mapping(long_csv), params=Params(sample_size=None, threshold=0.9),
                                out_dir=None))
    assert res["status"] == "ok"
    assert res["summary"]["communities"] >= 2
    assert set(res["summary"]["tier_counts"]) <= {"Low Engagement / At-Risk", "Moderate Engagement", "High Engagement", OUTLIER}
    assert len(res["graph"]["nodes"]) == res["summary"]["connected_nodes"]


def test_knn_graph_has_no_isolates(long_csv):
    res = runner.run(RunRequest(mapping=mapping(long_csv),
                                params=Params(sample_size=None, graph_method="knn", knn_k=5)))
    assert res["status"] == "ok"
    assert res["summary"]["connected_nodes"] == 180


def test_ineligible_dataset(tmp_path):
    pd.DataFrame({"u": range(100), "b": ["x"] * 100, "v": 1}).to_csv(tmp_path / "d.csv", index=False)
    res = runner.run(RunRequest(mapping=Mapping(path=str(tmp_path / "d.csv"), entity_col="u",
                                                behavior_col="b", value_col="v")))
    assert res["status"] == "ineligible"
    assert any("behavior categories" in e for e in res["eligibility"]["errors"])


def test_bad_column_gives_clear_error(long_csv):
    m = mapping(long_csv); m.value_col = "nope"
    with pytest.raises(ValueError, match="nope"):
        runner.check(m)


def test_wide_format(tmp_path):
    rng = np.random.default_rng(1)
    df = pd.DataFrame(rng.integers(0, 50, (80, 4)), columns=list("abcd")); df.insert(0, "id", range(80))
    df.to_csv(tmp_path / "w.csv", index=False)
    res = runner.run(RunRequest(mapping=Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id",
                                                feature_cols=list("abcd")), params=Params(sample_size=None, threshold=0.6)))
    assert res["status"] in ("ok", "empty_graph")


def test_tiers_quantile_and_min_size():
    df = pd.DataFrame({"community_id": range(6), "community_size": [10, 10, 10, 10, 10, 1],
                       "avg_total_activity": [1, 2, 3, 4, 5, 999.0]})
    out = assign_tiers(df, ["L", "M", "H"], "quantile", min_size=2)
    assert out.tier.tolist() == ["L", "L", "M", "H", "H", OUTLIER] or out.tier.iloc[5] == OUTLIER
    assert sorted(out.tier[:5].tolist()).count("H") >= 1


def test_tiers_custom_thresholds():
    df = pd.DataFrame({"community_id": range(3), "community_size": [5] * 3, "avg_total_activity": [10, 100, 1000.0]})
    out = assign_tiers(df, ["L", "M", "H"], "thresholds", low_cut=50, high_cut=500)
    assert out.tier.tolist() == ["L", "M", "H"]


def test_movielens_style_split_lookup(tmp_path):
    rng = np.random.default_rng(3)
    pd.DataFrame({"movieId": range(10), "genres": ["Action|Comedy", "Drama", "Comedy|Romance", "Action", "Drama|Romance",
                  "Horror", "Horror|Action", "Comedy", "Romance", "Drama"]}).to_csv(tmp_path / "movies.csv", index=False)
    pd.DataFrame({"userId": rng.integers(0, 80, 3000), "movieId": rng.integers(0, 10, 3000),
                  "rating": rng.integers(1, 6, 3000)}).to_csv(tmp_path / "ratings.csv", index=False)
    from engine.matrix import build_matrix
    mat = build_matrix(Mapping(path=str(tmp_path / "ratings.csv"), entity_col="userId", behavior_col="genres", agg="count",
                               lookup=LookupSpec(path=str(tmp_path / "movies.csv"), source_key="movieId",
                                                 lookup_key="movieId", split_delimiter="|")))
    assert set(mat.columns) == {"Action", "Comedy", "Romance", "Drama", "Horror"}
    assert mat.shape[0] >= 70
