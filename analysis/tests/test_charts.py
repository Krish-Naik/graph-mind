import numpy as np, pandas as pd, pytest
from engine import charts
from engine.charts import ChartSpec


@pytest.fixture
def f(tmp_path):
    rng = np.random.default_rng(0)
    n = 500
    df = pd.DataFrame({"id": range(n), "city": rng.choice(list("ABCD"), n), "kind": rng.choice(["x", "y"], n),
                       "price": rng.normal(100, 20, n).round(2), "qty": rng.integers(1, 9, n),
                       "day": pd.date_range("2024-01-01", periods=n, freq="D").astype(str)})
    p = tmp_path / "d.csv"; df.to_csv(p, index=False); return str(p)


def test_auto(f):
    r = charts.auto(f)
    kinds = {c["kind"] for c in r["charts"]}
    assert {"bar", "line", "correlation"} <= kinds
    assert not any(c["id"] == "hist:id" for c in r["charts"])      # id-like column skipped


def test_query_group_and_agg(f):
    r = charts.query(f, ChartSpec(kind="bar", x="city", y="price", agg="mean", group="kind"))
    assert r["groups"] and all("x" in row for row in r["rows"])
    r = charts.query(f, ChartSpec(kind="line", x="day", agg="count"))
    assert r["rows"][0]["x"] < r["rows"][-1]["x"]
    assert len(charts.query(f, ChartSpec(kind="scatter", x="price", y="qty"))["rows"]) > 100
    assert len(charts.query(f, ChartSpec(kind="histogram", x="price", bins=10))["rows"]) == 10


def test_query_errors(f):
    with pytest.raises(ValueError, match="numeric"):
        charts.query(f, ChartSpec(kind="bar", x="city", y="kind", agg="sum"))
    with pytest.raises(ValueError, match="not found"):
        charts.query(f, ChartSpec(kind="bar", x="nope"))
