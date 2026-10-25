"""Synthetic tests for the behavior-matrix / preprocessing step (engine.matrix + engine.eligibility)."""
import duckdb
import numpy as np
import pandas as pd
import pytest

from engine.eligibility import check_matrix
from engine.matrix import build_matrix, load_labels, validate_mapping
from engine.schemas import LabelSpec, LookupSpec, Mapping


def long_map(path, **kw):
    return Mapping(path=str(path), entity_col="u", behavior_col="b", value_col="v", **kw)


def test_integer_ids_stay_integers_when_a_blank_row_makes_the_column_float(tmp_path):
    pd.DataFrame({"u": [1.0, 1.0, 2.0, np.nan, 3.0], "b": list("xyxyz"), "v": [1, 2, 3, 4, 5]}
                 ).to_csv(tmp_path / "a.csv", index=False)
    mat = build_matrix(long_map(tmp_path / "a.csv"))
    assert mat.index.tolist() == [1, 2, 3] and str(mat.index.dtype) == "int64"


def test_ids_and_behaviors_are_trimmed_and_leading_zeros_survive(tmp_path):
    pd.DataFrame({"u": ["007", " 007", "b", "b"], "b": ["x", " x", "y", "y "], "v": [1, 2, 3, 4]}
                 ).to_csv(tmp_path / "t.csv", index=False)
    mat = build_matrix(long_map(tmp_path / "t.csv"))
    assert mat.index.tolist() == ["007", "b"]            # '007' must not become 7
    assert sorted(mat.columns) == ["x", "y"]
    assert mat.loc["007", "x"] == 3 and mat.loc["b", "y"] == 7


def test_label_alignment_uses_the_same_canonical_ids(tmp_path):
    pd.DataFrame({"u": [1.0, 2.0, np.nan, 3.0], "b": list("xyzx"), "v": [1, 1, 1, 1]}).to_csv(tmp_path / "a.csv", index=False)
    pd.DataFrame({"id": [1.0, 2.0, 3.0, np.nan], "g": ["p", "q", "r", "s"]}).to_csv(tmp_path / "l.csv", index=False)
    m = long_map(tmp_path / "a.csv", label=LabelSpec(path=str(tmp_path / "l.csv"), entity_col="id", label_col="g"))
    lab = load_labels(m, build_matrix(m).index)
    assert lab.to_dict() == {1: "p", 2: "q", 3: "r"}


def test_non_numeric_value_column_is_an_error_not_a_zero_matrix(tmp_path):
    pd.DataFrame({"u": [1, 2, 3], "b": list("xyz"), "v": ["a", "b", "c"]}).to_csv(tmp_path / "d.csv", index=False)
    with pytest.raises(ValueError, match="no numeric values"):
        build_matrix(long_map(tmp_path / "d.csv"))


def test_bad_cells_are_ignored_and_reported_not_poisoning_the_group(tmp_path):
    pd.DataFrame({"u": [1, 1, 1, 2, 2], "b": ["x", "x", "y", "x", "y"], "v": ["5", "inf", "oops", "2", "3"]}
                 ).to_csv(tmp_path / "e.csv", index=False)
    mat = build_matrix(long_map(tmp_path / "e.csv"))
    assert np.isfinite(mat.to_numpy()).all()
    assert mat.loc[1, "x"] == 5 and mat.loc[1, "y"] == 0     # inf / text ignored, valid 5 kept
    assert mat.attrs["unusable_value_cells"] == 2
    rep = check_matrix(mat)
    assert any("not usable numbers" in w for w in rep["warnings"])


def test_split_lookup_counts_each_category_once_per_event(tmp_path):
    pd.DataFrame({"k": [1, 2], "g": ["A|A|B", "B"]}).to_csv(tmp_path / "lk.csv", index=False)
    pd.DataFrame({"u": [1, 1, 2], "k": [1, 2, 2]}).to_csv(tmp_path / "ev.csv", index=False)
    mat = build_matrix(Mapping(path=str(tmp_path / "ev.csv"), entity_col="u", behavior_col="g", agg="count",
                               lookup=LookupSpec(path=str(tmp_path / "lk.csv"), source_key="k", lookup_key="k",
                                                 split_delimiter="|")))
    assert mat.loc[1].to_dict() == {"A": 1.0, "B": 2.0} and mat.loc[2].to_dict() == {"A": 0.0, "B": 1.0}


def test_lookup_join_tolerates_int_vs_float_keys_and_reports_unmapped_rows(tmp_path):
    pd.DataFrame({"k": [1.0, 2.0, 3.0], "g": ["A", "B", "C"]}).to_csv(tmp_path / "lk.csv", index=False)
    pd.DataFrame({"u": [1, 1, 2, 2], "k": [1, 2, 2, 9]}).to_csv(tmp_path / "ev.csv", index=False)
    mat = build_matrix(Mapping(path=str(tmp_path / "ev.csv"), entity_col="u", behavior_col="g", agg="count",
                               lookup=LookupSpec(path=str(tmp_path / "lk.csv"), source_key="k", lookup_key="k")))
    assert mat.loc[1].to_dict() == {"A": 1.0, "B": 1.0} and mat.loc[2, "B"] == 1.0
    assert mat.attrs["unmapped_rows"] == 1 and mat.attrs["event_rows"] == 4
    assert any("could not be assigned" in w for w in check_matrix(mat)["warnings"])


def test_conflicting_lookup_keys_are_deterministic_and_reported(tmp_path):
    pd.DataFrame({"k": [1, 1, 2], "g": ["Z", "A", "B"]}).to_csv(tmp_path / "lk.csv", index=False)
    pd.DataFrame({"u": [1, 2], "k": [1, 2]}).to_csv(tmp_path / "ev.csv", index=False)
    m = Mapping(path=str(tmp_path / "ev.csv"), entity_col="u", behavior_col="g", agg="count",
                lookup=LookupSpec(path=str(tmp_path / "lk.csv"), source_key="k", lookup_key="k"))
    mat = build_matrix(m)
    assert "A" in mat.columns and "Z" not in mat.columns and mat.attrs["lookup_conflicting_keys"] == 1


def test_entity_with_only_unusable_values_is_kept_with_zeros(tmp_path):
    pd.DataFrame({"u": [1, 1, 2, 2, 3], "b": list("xyxyz"), "v": [1, 2, np.nan, np.nan, 5]}).to_csv(tmp_path / "c.csv", index=False)
    for agg in ("sum", "mean", "max"):
        mat = build_matrix(long_map(tmp_path / "c.csv", agg=agg))
        assert mat.index.tolist() == [1, 2, 3] and (mat.loc[2] == 0).all()


def test_wide_rejects_id_as_feature_and_counts_repeated_feature_once(tmp_path):
    pd.DataFrame({"id": range(5), "a": range(5), "b": [0, 1, 0, 1, 0]}).to_csv(tmp_path / "w.csv", index=False)
    with pytest.raises(ValueError, match="entity id"):
        build_matrix(Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=["id", "a", "b"]))
    mat = build_matrix(Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=["a", "a", "b"]))
    assert mat.columns.tolist() == ["a", "b"] and mat.attrs["duplicate_feature_cols_ignored"] == 1


def test_wide_label_entity_column_in_same_file_is_not_a_feature(tmp_path):
    pd.DataFrame({"id": range(5), "ref": range(5), "a": range(5), "b": range(5, 0, -1)}).to_csv(tmp_path / "w.csv", index=False)
    lab = LabelSpec(path=str(tmp_path / "w.csv"), entity_col="ref", label_col="a")
    with pytest.raises(ValueError):
        validate_mapping(duckdb.connect(), Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id",
                                                   feature_cols=["ref", "b"], label=lab))


def test_long_behavior_or_value_column_cannot_be_the_entity_id(tmp_path):
    pd.DataFrame({"u": range(4), "b": list("xyxy"), "v": range(4)}).to_csv(tmp_path / "x.csv", index=False)
    with pytest.raises(ValueError, match="entity id"):
        build_matrix(Mapping(path=str(tmp_path / "x.csv"), entity_col="u", behavior_col="u", value_col="v"))
    with pytest.raises(ValueError, match="entity id"):
        build_matrix(Mapping(path=str(tmp_path / "x.csv"), entity_col="u", behavior_col="b", value_col="u"))


def test_wide_missing_text_and_duplicates_are_cleaned_and_reported(tmp_path):
    pd.DataFrame({"id": [1, 1, 2, 3], "a": [1, np.nan, 3, 4], "b": ["2", "x", "5", "6"], "c": [0, 0, 0, 0]}
                 ).to_csv(tmp_path / "w.csv", index=False)
    mat = build_matrix(Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=["a", "b", "c"]))
    assert mat.loc[1, "a"] == 1 and mat.loc[1, "b"] == 2            # NaN / text cell treated as 0 before summing
    assert mat.attrs["duplicate_entity_rows_aggregated"] == 1 and mat.attrs["non_finite_replaced"] == 2
    assert mat.attrs["unusable_value_cells"] == 1
    assert "c" not in mat.columns and mat.attrs["all_zero_columns_dropped"] == ["c"]
    with pytest.raises(ValueError, match="no numeric values"):
        pd.DataFrame({"id": [1, 2], "a": ["p", "q"], "b": [1, 2]}).to_csv(tmp_path / "t.csv", index=False)
        build_matrix(Mapping(path=str(tmp_path / "t.csv"), format="wide", entity_col="id", feature_cols=["a", "b"]))


def test_constant_columns_are_flagged_by_eligibility():
    rng = np.random.default_rng(0)
    mat = pd.DataFrame(rng.integers(0, 9, (40, 3)), columns=list("abc"))
    mat["k"] = 5.0
    rep = check_matrix(mat)
    assert rep["ok"] and any("same value for every entity" in w for w in rep["warnings"])