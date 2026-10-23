"""Step 1 of the pipeline: raw data -> entity x behavior matrix.

Uses DuckDB so a 450 MB / 10M-row log is aggregated out-of-core and only the small
matrix ever lands in pandas.
"""
from __future__ import annotations
import duckdb
import pandas as pd
from .schemas import Mapping

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


def validate_mapping(con, m: Mapping) -> None:
    """Raise ValueError with a human message if a mapped column does not exist."""
    main_cols = columns_of(con, m.path)

    def need(col, cols, where):
        if col not in cols:
            raise ValueError(f"Column '{col}' not found in {where}. Available: {cols[:30]}")

    need(m.entity_col, main_cols, "main file")
    if m.format == "wide":
        if not m.feature_cols or len(m.feature_cols) < 2:
            raise ValueError("Wide format needs at least 2 feature columns.")
        for c in m.feature_cols:
            need(c, main_cols, "main file")
        return
    if not m.behavior_col:
        raise ValueError("behavior_col is required for long format.")
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


def build_matrix(m: Mapping) -> pd.DataFrame:
    """Return DataFrame: index = entity, columns = behaviors, values >= 0 numbers."""
    con = duckdb.connect()
    validate_mapping(con, m)

    if m.format == "wide":
        cols = ", ".join(f"TRY_CAST({q(c)} AS DOUBLE) AS {q(c)}" for c in m.feature_cols)
        df = con.execute(
            f"SELECT {q(m.entity_col)} AS __entity, {cols} FROM {csv(m.path)} "
            f"WHERE {q(m.entity_col)} IS NOT NULL"
        ).df()
        df = df.groupby("__entity").sum(numeric_only=True)
        df.index.name = "entity"
        return df.fillna(0.0)

    if m.agg == "count":
        value_expr = "COUNT(*)"
    else:
        value_expr = f"{AGG_SQL[m.agg]}(TRY_CAST(s.{q(m.value_col)} AS DOUBLE))"

    if m.lookup:
        # de-duplicate lookup keys so a messy lookup can never multiply rows
        # (except deliberately, when one lookup row holds several categories: split_delimiter)
        if m.lookup.split_delimiter:
            d = lit(m.lookup.split_delimiter)
            lk_sql = (f"SELECT k, TRIM(UNNEST(string_split(CAST(b AS VARCHAR), {d}))) AS b FROM lk0")
        else:
            lk_sql = "SELECT k, b FROM lk0"
        sql = f"""
        WITH lk0 AS (
            SELECT CAST({q(m.lookup.lookup_key)} AS VARCHAR) AS k,
                   ANY_VALUE({q(m.behavior_col)}) AS b
            FROM {csv(m.lookup.path)}
            WHERE {q(m.behavior_col)} IS NOT NULL
            GROUP BY 1
        ),
        lk AS ({lk_sql})
        SELECT s.{q(m.entity_col)} AS entity, lk.b AS behavior, {value_expr} AS val
        FROM {csv(m.path)} s
        JOIN lk ON CAST(s.{q(m.lookup.source_key)} AS VARCHAR) = lk.k
        WHERE s.{q(m.entity_col)} IS NOT NULL AND lk.b <> ''
        GROUP BY 1, 2
        """
    else:
        sql = f"""
        SELECT s.{q(m.entity_col)} AS entity, CAST(s.{q(m.behavior_col)} AS VARCHAR) AS behavior,
               {value_expr} AS val
        FROM {csv(m.path)} s
        WHERE s.{q(m.entity_col)} IS NOT NULL AND s.{q(m.behavior_col)} IS NOT NULL
        GROUP BY 1, 2
        """
    long_df = con.execute(sql).df()
    if long_df.empty:
        raise ValueError("No rows after joining/grouping. Check the column mapping and join keys.")
    mat = long_df.pivot_table(index="entity", columns="behavior", values="val",
                              aggfunc="sum", fill_value=0.0)
    mat.columns.name = None
    return mat.sort_index()


def load_labels(m: Mapping, entities) -> pd.Series | None:
    if not m.label:
        return None
    con = duckdb.connect()
    df = con.execute(
        f"SELECT {q(m.label.entity_col)} AS entity, ANY_VALUE(CAST({q(m.label.label_col)} AS VARCHAR)) AS label "
        f"FROM {csv(m.label.path)} GROUP BY 1"
    ).df().set_index("entity")["label"]
    return df.reindex(entities)
