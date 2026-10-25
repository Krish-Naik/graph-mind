"""Step 1 of the pipeline: raw data -> entity x behavior matrix.

Uses DuckDB so a 450 MB / 10M-row log is aggregated out-of-core and only the small
matrix ever lands in pandas.
"""
from __future__ import annotations
import os
import re
import duckdb
import numpy as np
import pandas as pd
from .schemas import Mapping
from .evaluation import canonical_id, canonical_label

AGG_SQL = {"sum": "SUM", "mean": "AVG", "max": "MAX"}


def q(name: str) -> str:
    """Quote an identifier safely."""
    return '"' + name.replace('"', '""') + '"'


def lit(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def csv(path: str) -> str:
    return f"read_csv_auto({lit(path)}, header=true, sample_size=20000)"


def columns_of(con, path: str) -> list[str]:
    return [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {csv(path)}").fetchall()]


def column_types(con, path: str) -> dict[str, str]:
    return {r[0]: str(r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM {csv(path)}").fetchall()}


_FLOATING = {"FLOAT", "DOUBLE", "REAL", "DECIMAL"}


def key_sql(expr: str, dtype: str | None) -> str:
    """SQL for a canonical text key of an id / join-key column (NULL when missing or blank).

    Whitespace is trimmed, and for floating point columns a trailing '.0' is removed, so the same
    entity is one entity whether the column was read as 7, 7.0 or ' 7 ' (a single blank row is enough
    for the CSV reader to turn an integer id column into DOUBLE).
    """
    v = f"TRIM(CAST({expr} AS VARCHAR))"
    if dtype and dtype.split("(")[0].upper() in _FLOATING:
        v = f"regexp_replace({v}, '\\.0+$', '')"
    return f"NULLIF({v}, '')"


def finite_sql(expr: str) -> str:
    """Numeric value of a cell, or NULL when it is missing, not a number, NaN or +-infinity."""
    c = f"TRY_CAST({expr} AS DOUBLE)"
    return f"CASE WHEN isfinite({c}) THEN {c} END"


def restore_id_index(keys, name: str = "entity") -> pd.Index:
    """Canonical text keys -> index. Integer-looking ids come back as int64 (as before), everything else
    stays text. '007' is NOT turned into 7: ids are only converted when that is lossless."""
    vals = [str(k) for k in keys]
    if vals and all(re.fullmatch(r"-?\d{1,18}", v) and str(int(v)) == v for v in vals):
        return pd.Index([int(v) for v in vals], dtype="int64", name=name)
    return pd.Index(vals, dtype=object, name=name)


def _same_file(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def check_label_leakage(m: Mapping) -> None:
    """The label is for EVALUATION only. Refuse mappings where it would also feed the graph.

    Leakage exists when the label column is (part of) what the behavior matrix is built from:
    a feature column (wide), the behavior / value column (long, same file) or the lookup category.
    """
    lab = m.label
    if lab is None:
        return
    if lab.label_col == lab.entity_col:
        raise ValueError("Label column and label entity column are the same column; the label would just be the id.")
    if _same_file(lab.path, m.path):
        if m.format == "wide":
            feeding = set(m.feature_cols or [])
        else:
            feeding = {m.value_col, m.lookup.source_key if m.lookup else m.behavior_col}
        feeding.add(m.entity_col)                      # the label must not be the entity id either
        feeding.discard(None)
        if lab.label_col in feeding:
            raise ValueError(
                f"Label leakage: column '{lab.label_col}' is used to build the behavior matrix AND as the "
                "reference label. Choose a label column that is not one of the behavior features.")
    if m.lookup and m.format == "long" and _same_file(lab.path, m.lookup.path) and lab.label_col == m.behavior_col:
        raise ValueError(
            f"Label leakage: lookup category column '{m.behavior_col}' is also the reference label column.")


def validate_mapping(con, m: Mapping) -> None:
    """Raise ValueError with a human message if a mapped column does not exist."""
    _validate_structure(con, m)
    if m.label:
        lab_cols = columns_of(con, m.label.path)
        for c in (m.label.entity_col, m.label.label_col):
            if c not in lab_cols:
                raise ValueError(f"Column '{c}' not found in label file. Available: {lab_cols[:30]}")
        check_label_leakage(m)


def _validate_structure(con, m: Mapping) -> None:
    main_cols = columns_of(con, m.path)

    def need(col, cols, where):
        if col not in cols:
            raise ValueError(f"Column '{col}' not found in {where}. Available: {cols[:30]}")

    need(m.entity_col, main_cols, "main file")
    id_cols = {m.entity_col}
    if m.label and _same_file(m.label.path, m.path):
        id_cols.add(m.label.entity_col)               # an id column of the label table is an id here too
    if m.format == "wide":
        feats = unique_features(m.feature_cols)
        if len(feats) < 2:
            raise ValueError("Wide format needs at least 2 distinct feature columns.")
        for c in feats:
            need(c, main_cols, "main file")
        as_feature = [c for c in feats if c in id_cols]
        if as_feature:
            raise ValueError(f"Column '{as_feature[0]}' is an entity id, not a behavior; remove it from the feature "
                             "columns (an id would be scored as activity and distort similarity).")
        return
    if not m.behavior_col:
        raise ValueError("behavior_col is required for long format.")
    for role, col in (("behavior_col", m.behavior_col if not m.lookup else None), ("value_col", m.value_col)):
        if col is not None and col in id_cols:
            raise ValueError(f"{role} '{col}' is an entity id column; an id cannot be a behavior or an activity value.")
    if m.agg != "count" and not m.value_col:
        raise ValueError("value_col is required unless agg='count'.")
    if m.value_col:
        need(m.value_col, main_cols, "main file")
    if m.lookup:
        lk_cols = columns_of(con, m.lookup.path)
        need(m.lookup.source_key, main_cols, "main file")
        need(m.lookup.lookup_key, lk_cols, "lookup file")
        need(m.behavior_col, lk_cols, "lookup file (behavior column lives there)")
    else:
        need(m.behavior_col, main_cols, "main file")


def unique_features(cols) -> list[str]:
    """feature_cols without repeats (order kept): a repeated column would silently be counted twice."""
    return list(dict.fromkeys(cols or []))


def _finalize(mat: pd.DataFrame, duplicate_rows: int = 0, pre_replaced: int = 0) -> pd.DataFrame:
    """Replace NaN / +-inf by 0 (and say how many), so one bad cell can never crash or poison similarity."""
    vals = mat.to_numpy(dtype=float, copy=True)
    bad = ~np.isfinite(vals)
    n_bad = int(bad.sum())
    if n_bad:
        vals[bad] = 0.0
        mat = pd.DataFrame(vals, index=mat.index, columns=mat.columns)
    mat.attrs["non_finite_replaced"] = n_bad + int(pre_replaced)
    mat.attrs["duplicate_entity_rows_aggregated"] = int(duplicate_rows)
    return mat


def _finish(mat: pd.DataFrame, duplicate_rows: int, pre_replaced: int, notes: dict) -> pd.DataFrame:
    """Final clean-up shared by both layouts: finite values, no all-zero behavior columns, audit attrs."""
    mat = _finalize(mat, duplicate_rows=duplicate_rows, pre_replaced=pre_replaced)
    replaced = mat.attrs["non_finite_replaced"]
    # a behavior nobody performed carries no information and would only add an empty column to every view
    zero = [str(c) for c in mat.columns if not (mat[c].to_numpy() != 0).any()]
    if zero and len(zero) < mat.shape[1]:
        mat = mat.drop(columns=[c for c in mat.columns if str(c) in set(zero)])
    else:
        zero = []
    mat = mat.sort_index()
    mat.attrs.update({"non_finite_replaced": replaced, "duplicate_entity_rows_aggregated": int(duplicate_rows),
                      "all_zero_columns_dropped": zero[:50], "all_zero_columns_dropped_count": len(zero)})
    mat.attrs.update(notes)
    return mat


def build_matrix(m: Mapping) -> pd.DataFrame:
    """Return DataFrame: index = entity, columns = behaviors, values = finite numbers.

    Entity ids are canonicalised once, here (trimmed; 7 == 7.0 == ' 7 '), and are the DataFrame index for
    the rest of the pipeline. Integer-looking ids stay int64, other ids stay text.
    Audit counters are left in `mat.attrs` and surfaced by eligibility.check_matrix.
    """
    con = duckdb.connect()
    validate_mapping(con, m)
    types = column_types(con, m.path)
    ent = key_sql(q(m.entity_col), types[m.entity_col])

    if m.format == "wide":
        feats = unique_features(m.feature_cols)
        stats_sql = ", ".join(f"COUNT({q(c)}), COUNT({finite_sql(q(c))})" for c in feats)
        st = con.execute(f"SELECT {stats_sql} FROM {csv(m.path)} WHERE {ent} IS NOT NULL").fetchone()
        unusable = 0
        for i, c in enumerate(feats):
            raw, fin = int(st[2 * i]), int(st[2 * i + 1])
            if raw > 0 and fin == 0:
                raise ValueError(f"Feature column '{c}' has no numeric values; it cannot be used as a behavior.")
            unusable += raw - fin
        cols = ", ".join(f"{finite_sql(q(c))} AS {q(c)}" for c in feats)
        df = con.execute(f"SELECT {ent} AS __entity, {cols} FROM {csv(m.path)} WHERE {ent} IS NOT NULL").df()
        n_rows = len(df)
        if n_rows == 0:
            raise ValueError("No rows with a usable entity id. Check the entity column.")
        n_missing = int(df[feats].isna().sum().sum())     # blank, non-numeric, NaN or infinite cells
        df[feats] = df[feats].fillna(0.0)
        df = df.groupby("__entity").sum(numeric_only=True)
        df.index = restore_id_index(df.index)
        notes = {"unusable_value_cells": unusable,
                 "duplicate_feature_cols_ignored": len(m.feature_cols or []) - len(feats)}
        return _finish(df, n_rows - len(df), n_missing, notes)

    if m.agg == "count":
        value_expr = "COUNT(*)"
        tot = con.execute(f"SELECT COUNT(*) FROM {csv(m.path)} s WHERE {ent} IS NOT NULL").fetchone()
        n_total, n_raw, n_fin = int(tot[0]), 0, 0
    else:
        fin = finite_sql(f"s.{q(m.value_col)}")
        value_expr = f"{AGG_SQL[m.agg]}({fin})"
        tot = con.execute(f"SELECT COUNT(*), COUNT(s.{q(m.value_col)}), COUNT({fin}) FROM {csv(m.path)} s "
                          f"WHERE {ent} IS NOT NULL").fetchone()
        n_total, n_raw, n_fin = int(tot[0]), int(tot[1]), int(tot[2])
        if n_fin == 0 and n_total > 0:
            raise ValueError(f"Value column '{m.value_col}' has no numeric values; use agg='count' or pick a numeric column.")

    notes = {"event_rows": n_total, "unusable_value_cells": n_raw - n_fin, "lookup_conflicting_keys": 0}
    if m.lookup:
        lk_types = column_types(con, m.lookup.path)
        lkey = key_sql(q(m.lookup.lookup_key), lk_types[m.lookup.lookup_key])
        skey = key_sql(f"s.{q(m.lookup.source_key)}", types[m.lookup.source_key])
        cat = f"NULLIF(TRIM(CAST({q(m.behavior_col)} AS VARCHAR)), '')"
        # one category per lookup key (deterministic MIN, conflicts are counted), so a messy lookup
        # can never multiply rows -- except deliberately via split_delimiter (de-duplicated per key)
        notes["lookup_conflicting_keys"] = int(con.execute(
            f"SELECT COUNT(*) FROM (SELECT {lkey} AS k FROM {csv(m.lookup.path)} WHERE {lkey} IS NOT NULL "
            f"AND {cat} IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT {cat}) > 1)").fetchone()[0])
        if m.lookup.split_delimiter:
            d = lit(m.lookup.split_delimiter)
            lk_sql = (f"SELECT DISTINCT k, NULLIF(TRIM(x), '') AS b FROM "
                      f"(SELECT k, UNNEST(string_split(b, {d})) AS x FROM lk0)")
        else:
            lk_sql = "SELECT k, b FROM lk0"
        sql = f"""
        WITH lk0 AS (
            SELECT {lkey} AS k, MIN({cat}) AS b
            FROM {csv(m.lookup.path)}
            WHERE {lkey} IS NOT NULL AND {cat} IS NOT NULL
            GROUP BY 1
        ),
        lk AS ({lk_sql})
        SELECT {ent} AS entity, lk.b AS behavior, COUNT(*) AS n_rows, {value_expr} AS val
        FROM {csv(m.path)} s
        LEFT JOIN lk ON {skey} = lk.k AND lk.b IS NOT NULL
        WHERE {ent} IS NOT NULL
        GROUP BY 1, 2
        """
    else:
        beh = f"NULLIF(TRIM(CAST(s.{q(m.behavior_col)} AS VARCHAR)), '')"
        sql = f"""
        SELECT {ent} AS entity, {beh} AS behavior, COUNT(*) AS n_rows, {value_expr} AS val
        FROM {csv(m.path)} s
        WHERE {ent} IS NOT NULL
        GROUP BY 1, 2
        """
    long_df = con.execute(sql).df()
    # rows without a usable behavior (blank category, or no matching lookup key) never reach the matrix
    no_beh = long_df["behavior"].isna()
    notes["unmapped_rows"] = int(long_df.loc[no_beh, "n_rows"].sum())
    long_df = long_df[~no_beh]
    if long_df.empty:
        raise ValueError("No rows after joining/grouping. Check the column mapping and join keys.")
    long_df = long_df.assign(val=long_df["val"].astype(float).fillna(0.0))   # entity had rows but no usable value
    mat = long_df.pivot_table(index="entity", columns="behavior", values="val", aggfunc="sum", fill_value=0.0)
    mat.columns.name = None
    mat.index = restore_id_index(mat.index)
    return _finish(mat, 0, 0, notes)


def load_labels_with_report(m: Mapping, entities) -> tuple[pd.Series | None, dict | None]:
    """Reference label per entity, aligned BY ENTITY ID, plus an audit report.

    * ids are matched through `canonical_id` (7, 7.0 and "7" are the same entity);
    * a missing label (null / NaN / empty) is missing, never a class;
    * an entity with SEVERAL label rows that all agree gets that label;
    * an entity with CONFLICTING label rows (e.g. OULAD students enrolled in several modules with
      different final_result) is AMBIGUOUS and gets no label. The old `ANY_VALUE` silently picked
      an arbitrary one of them, which injects label noise that no algorithm can recover.
    Returns (object Series indexed exactly like `entities`, None where unlabeled; report dict).
    """
    if not m.label:
        return None, None
    con = duckdb.connect()
    df = con.execute(
        f"SELECT {q(m.label.entity_col)} AS entity, CAST({q(m.label.label_col)} AS VARCHAR) AS label "
        f"FROM {csv(m.label.path)} WHERE {q(m.label.entity_col)} IS NOT NULL"
    ).df()
    df["key"] = df["entity"].map(canonical_id)
    df["label"] = df["label"].map(canonical_label)
    n_rows = len(df)
    labeled = df.dropna(subset=["label"]).drop_duplicates(["key", "label"])
    n_classes_per_entity = labeled.groupby("key")["label"].nunique()
    conflicting = set(n_classes_per_entity[n_classes_per_entity > 1].index)
    resolved = labeled[~labeled["key"].isin(conflicting)].set_index("key")["label"].to_dict()
    entity_rows = df.groupby("key").size()
    repeated_consistent = int(((entity_rows > 1) & ~entity_rows.index.isin(list(conflicting))).sum())

    ents = list(entities)
    keys = [canonical_id(e) for e in ents]
    in_file = set(entity_rows.index)
    values = [resolved.get(k) for k in keys]
    series = pd.Series(values, index=pd.Index(ents), dtype=object)

    n_labeled = sum(v is not None for v in values)
    n_ambiguous = sum(k in conflicting for k in keys)
    n_not_in_file = sum(k not in in_file for k in keys)
    report = {
        "label_file_rows": int(n_rows),
        "label_file_entities": int(len(in_file)),
        "label_file_entities_with_conflicting_labels": int(len(conflicting)),
        "label_file_entities_repeated_but_consistent": repeated_consistent,
        "entities_requested": int(len(ents)),
        "entities_labeled": int(n_labeled),
        "entities_ambiguous": int(n_ambiguous),
        "entities_not_in_label_file": int(n_not_in_file),
        "entities_in_file_without_label_value": int(len(ents) - n_labeled - n_ambiguous - n_not_in_file),
        "ambiguous_examples": [str(k) for k in keys if k in conflicting][:5],
    }
    if ents and n_labeled == 0:
        report["warning"] = ("No entity received a label. Check that the label file's entity column holds the "
                             "same ids as the behavior file (type / formatting).")
    return series, report


def load_labels(m: Mapping, entities) -> pd.Series | None:
    """Backwards compatible wrapper: just the aligned label Series (see load_labels_with_report)."""
    return load_labels_with_report(m, entities)[0]