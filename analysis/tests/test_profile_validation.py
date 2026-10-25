"""Dataset profiling + pre-analysis configuration validation (engine.profile, main.py wiring)."""
import importlib
import json

import numpy as np
import pandas as pd
import pytest

from engine.profile import profile_file, validate_config, validate_params
from engine.schemas import LabelSpec, LookupSpec, Mapping, Params


# ---------------------------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def wide_csv(tmp_path):
    rng = np.random.default_rng(0)
    n = 60
    df = pd.DataFrame({
        "student_id": range(1000, 1000 + n),
        "clicks": rng.integers(0, 50, n), "views": rng.integers(0, 9, n),
        "quizzes": np.where(rng.random(n) < 0.7, 0, rng.integers(1, 5, n)),     # sparse
        "constant_col": 7, "empty_col": np.nan,
        "final_result": rng.choice(["Pass", "Fail", "Distinction"], n),
        "note": [None if i % 4 == 0 else "x" for i in range(n)],
    })
    df.loc[5, "views"] = np.nan
    df = pd.concat([df, df.iloc[[0, 1]]], ignore_index=True)                      # 2 fully duplicated rows
    p = tmp_path / "wide.csv"
    df.to_csv(p, index=False)
    return p


def col(prof, name):
    return next(c for c in prof["columns"] if c["name"] == name)


# ---------------------------------------------------------------------------------------------
# profiling
# ---------------------------------------------------------------------------------------------
def test_profile_keeps_old_keys_and_reports_quality(wide_csv):
    prof = profile_file(str(wide_csv))
    assert prof["rows"] == 62 and {"columns", "preview", "behavioral_suggestion"} <= set(prof)
    c = col(prof, "clicks")                                    # all keys the UI already reads
    assert {"name", "type", "numeric", "nulls_in_sample", "approx_distinct", "min", "max", "mean", "std"} <= set(c)
    assert col(prof, "views")["nulls_in_sample"] == 1
    assert col(prof, "note")["missing_ratio"] == pytest.approx(16 / 62, abs=0.01)
    assert col(prof, "quizzes")["sparsity"] > 0.5              # share of zero-or-missing cells
    assert prof["duplicate_rows_in_sample"] == 2
    assert "constant_col" in prof["constant_columns"] and "empty_col" in prof["all_missing_columns"]
    codes = {i["code"] for i in prof["issues"]}
    assert {"constant", "all_missing", "duplicate_rows"} <= codes
    json.dumps(prof, allow_nan=False)                          # JSON-safe (no NaN / inf / Decimal)


def test_candidates_separate_ids_features_and_labels(wide_csv):
    cand = profile_file(str(wide_csv))["candidates"]
    assert cand["entity_ids"] and cand["entity_ids"][0]["name"] == "student_id"
    assert {"clicks", "views", "quizzes"} <= set(cand["behavior_features"])
    assert not {"student_id", "constant_col", "empty_col", "final_result"} & set(cand["behavior_features"])
    assert "final_result" in [l["name"] for l in cand["reference_labels"]]
    assert "student_id" in cand["excluded"]["id_like"] and "constant_col" in cand["excluded"]["constant"]


def test_profile_non_finite_numbers_stay_json_safe(tmp_path):
    pd.DataFrame({"u": range(30), "a": [1.0, np.inf] + [2.0] * 28, "b": range(30)}).to_csv(tmp_path / "f.csv", index=False)
    prof = profile_file(str(tmp_path / "f.csv"))
    json.dumps(prof, allow_nan=False)
    assert col(prof, "a")["non_finite_in_sample"] >= 0


def test_suggestion_unchanged_for_event_log(tmp_path):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"user_id": np.repeat(range(60), 4), "category": ["a", "b", "c", "d"] * 60,
                       "clicks": rng.integers(0, 40, 240)})
    df.to_csv(tmp_path / "x.csv", index=False)
    s = profile_file(str(tmp_path / "x.csv"))["behavioral_suggestion"]
    assert (s["entity_col"], s["behavior_col"], s["value_col"]) == ("user_id", "category", "clicks")


# ---------------------------------------------------------------------------------------------
# configuration validation
# ---------------------------------------------------------------------------------------------
def wide_map(path, feats, **kw):
    return Mapping(path=str(path), format="wide", entity_col="student_id", feature_cols=feats, **kw)


def test_blocking_errors_vs_warnings(wide_csv):
    ok = validate_config(wide_map(wide_csv, ["clicks", "views", "quizzes"]))
    assert ok["ok"] and not ok["errors"]
    assert any(i["code"] == "no_label" and i["level"] == "info" for i in ok["issues"])   # info, not a warning
    assert not any("no_label" == i["code"] for i in ok["issues"] if i["level"] != "info")

    bad_col = validate_config(wide_map(wide_csv, ["clicks", "nope"]))
    assert not bad_col["ok"] and "nope" in bad_col["errors"][0]
    id_feat = validate_config(wide_map(wide_csv, ["student_id", "clicks"]))
    assert not id_feat["ok"] and "entity id" in id_feat["errors"][0]
    const = validate_config(wide_map(wide_csv, ["clicks", "constant_col"]))
    assert not const["ok"] and any(i["code"] == "no_varying_features" for i in const["issues"])
    one_const = validate_config(wide_map(wide_csv, ["clicks", "views", "constant_col"]))
    assert one_const["ok"] and any(i["code"] == "constant_features" for i in one_const["issues"])


def test_label_leakage_is_a_blocking_error(wide_csv):
    lab = LabelSpec(path=str(wide_csv), entity_col="student_id", label_col="clicks")
    res = validate_config(wide_map(wide_csv, ["clicks", "views"], label=lab))
    assert not res["ok"] and "leakage" in res["errors"][0].lower()


def test_non_numeric_value_column(tmp_path):
    pd.DataFrame({"u": range(40), "b": ["x", "y"] * 20, "d": pd.date_range("2024-01-01", periods=40)}
                 ).to_csv(tmp_path / "d.csv", index=False)
    pd.DataFrame({"u": range(40), "b": ["x", "y"] * 20, "t": [str(i) if i % 7 else "oops" for i in range(40)]}
                 ).to_csv(tmp_path / "t.csv", index=False)
    r = validate_config(Mapping(path=str(tmp_path / "d.csv"), entity_col="u", behavior_col="b", value_col="d"))
    assert not r["ok"] and any(i["code"] == "not_numeric" for i in r["issues"])
    r = validate_config(Mapping(path=str(tmp_path / "t.csv"), entity_col="u", behavior_col="b", value_col="t"))
    assert r["ok"] and any(i["code"] == "text_numeric" for i in r["issues"])


def test_label_coverage_and_quality_warnings(tmp_path):
    ids = list(range(100))
    pd.DataFrame({"u": np.repeat(ids, 2), "b": ["x", "y"] * 100, "v": 1}).to_csv(tmp_path / "ev.csv", index=False)
    mp = lambda lab: Mapping(path=str(tmp_path / "ev.csv"), entity_col="u", behavior_col="b", value_col="v", label=lab)
    spec = LabelSpec(path=str(tmp_path / "lab.csv"), entity_col="id", label_col="g")

    pd.DataFrame({"id": [500, 501, 502], "g": list("abc")}).to_csv(tmp_path / "lab.csv", index=False)
    assert any(i["code"] == "label_no_overlap" for i in validate_config(mp(spec))["issues"])

    pd.DataFrame({"id": ids[:20], "g": ["a", "b"] * 10}).to_csv(tmp_path / "lab.csv", index=False)
    r = validate_config(mp(spec))
    assert r["ok"] and any(i["code"] == "label_low_coverage" for i in r["issues"])

    pd.DataFrame({"id": ids, "g": ["same"] * 100}).to_csv(tmp_path / "lab.csv", index=False)
    assert any(i["code"] == "label_single_class" for i in validate_config(mp(spec))["issues"])

    pd.DataFrame({"id": ids, "g": [f"c{i}" for i in ids]}).to_csv(tmp_path / "lab.csv", index=False)
    assert any(i["code"] == "label_id_like" for i in validate_config(mp(spec))["issues"])

    pd.DataFrame({"id": [float(i) for i in ids] + [np.nan], "g": ["a", "b"] * 50 + ["a"]}).to_csv(tmp_path / "lab.csv", index=False)
    r = validate_config(mp(spec))                                   # float ids still match int ids: no coverage warning
    assert r["ok"] and not any(i["code"].startswith("label_") and i["level"] == "warning" for i in r["issues"])


def test_parameter_cross_checks():
    codes = lambda p, n=None: {i["code"]: i["level"] for i in validate_params(p, n)}
    assert codes(Params(algorithms=[])) == {"no_algorithm": "error"}
    assert codes(Params(tier_method="thresholds")) == {"tier_cuts": "error"}
    assert codes(Params(tier_method="thresholds", low_cut=10, high_cut=5))["tier_cuts"] == "error"
    assert not codes(Params(tier_method="thresholds", low_cut=5, high_cut=10))
    assert codes(Params(tier_labels=["a", "a", "b"]))["tier_labels"] == "error"
    assert codes(Params(tier_labels=["a", "b"]))["tier_labels"] == "error"
    assert codes(Params(algorithms=["lpa"], primary_algorithm="louvain"))["primary_not_selected"] == "warning"
    assert codes(Params(threshold=1.0))["threshold_max"] == "warning"
    assert codes(Params(graph_method="knn", knn_k=50, sample_size=None), 20)["knn_k_large"] == "warning"
    assert not validate_params(Params())                         # defaults are clean


# ---------------------------------------------------------------------------------------------
# API wiring + explicit "unavailable" evaluation
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture
def event_log(tmp_path):
    rng = np.random.default_rng(0)
    rows = []
    for g, base in enumerate([[50, 5, 5, 1], [5, 20, 3, 1], [1, 1, 8, 2]]):
        for i in range(60):
            for s, b in enumerate(base):
                rows.append((g * 1000 + i, ["video", "forum", "quiz", "home"][s], max(0, int(rng.normal(b * (g + 1), 1.5)))))
    pd.DataFrame(rows, columns=["uid", "kind", "clicks"]).to_csv(tmp_path / "log.csv", index=False)
    return {"path": str(tmp_path / "log.csv"), "entity_col": "uid", "behavior_col": "kind", "value_col": "clicks"}


def test_api_profile_validate_check_run(client, event_log):
    prof = client.post("/profile", json={"path": event_log["path"]}).json()
    assert prof["candidates"]["entity_ids"][0]["name"] == "uid"

    v = client.post("/behavioral/validate", json={"mapping": event_log, "params": {"threshold": 0.9}}).json()
    assert v["ok"] and any(i["code"] == "no_label" for i in v["issues"])

    chk = client.post("/behavioral/check", json={"mapping": event_log}).json()
    assert chk["ok"] and chk["config"]["errors"] == []

    run = client.post("/behavioral/run", json={"mapping": event_log, "params": {"sample_size": None, "threshold": 0.9}})
    res = run.json()
    assert run.status_code == 200 and res["status"] == "ok" and res["config"]["errors"] == []
    # no reference label: evaluation metrics are explicitly unavailable, never 0
    assert res["has_label"] is False and res["evaluation"]["primary"]["available"] is False
    assert res["evaluation"]["primary"]["nmi"] is None and res["evaluation"]["primary"]["reason_code"] == "no_labels"
    assert all(b["nmi"] is None and b["ami"] is None for b in res["benchmark"])
    assert res["nmi_analysis"]["available"] is False


def test_api_blocking_errors_are_readable_422(client, event_log):
    bad = {**event_log, "value_col": "nope"}
    r = client.post("/behavioral/check", json={"mapping": bad})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str) and "nope" in r.json()["detail"]

    r = client.post("/behavioral/run", json={"mapping": event_log, "params": {"algorithms": []}})
    assert r.status_code == 422 and "algorithm" in r.json()["detail"].lower()

    r = client.post("/behavioral/run", json={"mapping": event_log, "params": {"tier_method": "thresholds", "low_cut": 9, "high_cut": 1}})
    assert r.status_code == 422 and "low_cut" in r.json()["detail"]

    # request-body problems (pydantic) also come back as ONE string, which is what Express displays
    r = client.post("/behavioral/run", json={"mapping": event_log, "params": {"threshold": 5}})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str) and "threshold" in r.json()["detail"]

    r = client.post("/behavioral/run", json={"mapping": {**event_log, "behavior_col": "uid"}})
    assert r.status_code == 422 and "entity id" in r.json()["detail"]
    assert client.post("/profile", json={}).status_code == 422


def test_api_label_leakage_blocked_before_analysis(client, event_log):
    m = {**event_log, "label": {"path": event_log["path"], "entity_col": "uid", "label_col": "kind"}}
    r = client.post("/behavioral/run", json={"mapping": m, "params": {"sample_size": None}})
    assert r.status_code == 422 and "leakage" in r.json()["detail"].lower()