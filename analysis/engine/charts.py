"""Module A: chart data for ANY tabular file. Everything is aggregated in DuckDB;
the browser only receives small, ready-to-plot rows."""
from __future__ import annotations
import re
from typing import Literal, Optional
import duckdb
from pydantic import BaseModel
from .matrix import csv, q

NUM = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "UBIGINT", "UINTEGER", "UINTEGER", "USMALLINT", "UTINYINT")
ID_LIKE = re.compile(r"(^|_)(id|uuid|key|index)(_|$)|id$", re.I)
AGG = {"sum": "SUM", "mean": "AVG", "min": "MIN", "max": "MAX"}


class ChartSpec(BaseModel):
    kind: Literal["bar", "line", "pie", "scatter", "histogram"]
    x: str
    y: Optional[str] = None
    agg: Literal["count", "sum", "mean", "min", "max"] = "count"
    group: Optional[str] = None
    bins: int = 20
    limit: int = 30


def _open(path: str, max_rows: int | None = None):
    con = duckdb.connect()
    if max_rows:
        con.execute(f"CREATE TEMP TABLE t AS SELECT * FROM {csv(path)} LIMIT {int(max_rows)}")
    else:
        con.execute(f"CREATE VIEW t AS SELECT * FROM {csv(path)}")
    types = {r[0]: r[1] for r in con.execute("DESCRIBE t").fetchall()}
    return con, types


def _isnum(t): return t.split("(")[0] in NUM
def _istemp(t): return t.startswith("DATE") or t.startswith("TIMESTAMP")
def _lab(v): return None if v is None else (v.isoformat()[:10] if hasattr(v, "isoformat") else str(v))
def _num(v): return None if v is None else (float(v) if not isinstance(v, int) else v)


def _need(types, *cols):
    for c in cols:
        if c and c not in types:
            raise ValueError(f"Column '{c}' not found. Available: {list(types)[:30]}")


def histogram(con, types, col, bins=20) -> dict:
    _need(types, col)
    if not _isnum(types[col]):
        raise ValueError(f"Histogram needs a numeric column; '{col}' is {types[col]}.")
    lo, hi, n = con.execute(f"SELECT MIN({q(col)}), MAX({q(col)}), COUNT({q(col)}) FROM t").fetchone()
    if n == 0:
        return {"rows": []}
    lo, hi = float(lo), float(hi)
    if lo == hi:
        return {"rows": [{"x": f"{lo:g}", "value": int(n)}]}
    w = (hi - lo) / bins
    got = dict(con.execute(
        f"SELECT LEAST(CAST(FLOOR(({q(col)} - {lo}) / {w}) AS INTEGER), {bins - 1}) b, COUNT(*) "
        f"FROM t WHERE {q(col)} IS NOT NULL GROUP BY 1").fetchall())
    return {"rows": [{"x": f"{lo + i * w:.4g}", "value": int(got.get(i, 0))} for i in range(bins)]}


def query(path: str, spec: ChartSpec, max_rows: int | None = None) -> dict:
    con, types = _open(path, max_rows)
    return _query(con, types, spec)


def _query(con, types, s: ChartSpec) -> dict:
    _need(types, s.x, s.y, s.group)
    base = {"kind": s.kind, "x": s.x, "y": s.y, "agg": s.agg, "group": s.group}
    if s.kind == "histogram":
        return {**base, **histogram(con, types, s.x, s.bins)}
    if s.kind == "scatter":
        if not s.y:
            raise ValueError("Scatter needs both X and Y.")
        rows = con.execute(
            f"SELECT TRY_CAST({q(s.x)} AS DOUBLE), TRY_CAST({q(s.y)} AS DOUBLE) FROM t "
            f"WHERE {q(s.x)} IS NOT NULL AND {q(s.y)} IS NOT NULL USING SAMPLE 2000 ROWS").fetchall()
        return {**base, "rows": [{"x": a, "y": b} for a, b in rows if a is not None and b is not None],
                "note": "Random sample of up to 2,000 points."}
    if s.agg != "count":
        if not s.y:
            raise ValueError(f"Aggregation '{s.agg}' needs a Y column.")
        if not _isnum(types[s.y]):
            raise ValueError(f"Y column '{s.y}' must be numeric for '{s.agg}'.")
        val = f"{AGG[s.agg]}(TRY_CAST({q(s.y)} AS DOUBLE))"
    else:
        val = "COUNT(*)"
    xt = types[s.x]
    if _istemp(xt):
        span = con.execute(f"SELECT DATE_DIFF('day', MIN({q(s.x)}), MAX({q(s.x)})) FROM t").fetchone()[0] or 0
        xe = f"DATE_TRUNC('{'month' if span > 180 else 'day'}', {q(s.x)})"
    elif _isnum(xt) and s.kind == "line":
        xe = q(s.x)
    else:
        xe = f"CAST({q(s.x)} AS VARCHAR)"
    order = "x" if (s.kind == "line") else "total DESC"
    limit = max(1, min(s.limit, 200))
    note = None
    if not s.group:
        rows = con.execute(
            f"SELECT {xe} AS x, {val} AS value, {val} AS total FROM t WHERE {q(s.x)} IS NOT NULL "
            f"GROUP BY 1 ORDER BY {order} LIMIT {limit}").fetchall()
        if s.kind == "line":
            rows.sort(key=lambda r: (r[0] is None, r[0]))
        return {**base, "rows": [{"x": _lab(r[0]), "value": _num(r[1])} for r in rows], "groups": None,
                "note": f"Top {limit} categories." if len(rows) == limit and s.kind != "line" else note}
    top_g = [r[0] for r in con.execute(
        f"SELECT CAST({q(s.group)} AS VARCHAR) g, COUNT(*) c FROM t WHERE {q(s.group)} IS NOT NULL "
        f"GROUP BY 1 ORDER BY c DESC LIMIT 8").fetchall()]
    glist = ", ".join("'" + g.replace("'", "''") + "'" for g in top_g)
    rows = con.execute(
        f"SELECT {xe} AS x, CAST({q(s.group)} AS VARCHAR) AS g, {val} AS value FROM t "
        f"WHERE {q(s.x)} IS NOT NULL AND CAST({q(s.group)} AS VARCHAR) IN ({glist}) GROUP BY 1, 2").fetchall()
    pivot: dict = {}
    for x, g, v in rows:
        pivot.setdefault(_lab(x), {"x": _lab(x)})[g] = _num(v)
    out = list(pivot.values())
    if s.kind == "line":
        out.sort(key=lambda r: (r["x"] is None, r["x"]))
    else:
        out.sort(key=lambda r: -sum(v for k, v in r.items() if k != "x" and v is not None))
        out = out[:limit]
    return {**base, "rows": out, "groups": top_g, "note": "Top 8 groups shown." if len(top_g) == 8 else None}


def correlation(con, types, cols) -> dict:
    pairs = [(a, b) for i, a in enumerate(cols) for b in cols[i + 1:]]
    sel = ", ".join(f"CORR({q(a)}, {q(b)})" for a, b in pairs)
    vals = con.execute(f"SELECT {sel} FROM t").fetchone() if pairs else ()
    n = len(cols)
    mat = [[1.0 if i == j else None for j in range(n)] for i in range(n)]
    for (a, b), v in zip(pairs, vals):
        i, j = cols.index(a), cols.index(b)
        mat[i][j] = mat[j][i] = None if v is None else round(float(v), 3)
    return {"columns": cols, "matrix": mat}


def auto(path: str, max_rows: int = 1_000_000) -> dict:
    """A sensible default dashboard for any file."""
    con, types = _open(path, max_rows)
    n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    charts = []
    nums, cats, temps = [], [], []
    for c, t in types.items():
        d = con.execute(f"SELECT APPROX_COUNT_DISTINCT({q(c)}) FROM t").fetchone()[0]
        if _istemp(t):
            temps.append(c)
        elif _isnum(t):
            is_float = t.split('(')[0] in ('FLOAT', 'DOUBLE', 'DECIMAL')
            if not (ID_LIKE.search(c) or (not is_float and d > 0.9 * n and n > 50)):
                nums.append(c)
        elif 2 <= d <= 60:
            cats.append((c, d))
    for c in nums[:6]:
        spec = ChartSpec(kind="histogram", x=c)
        charts.append({"id": f"hist:{c}", "title": f"Distribution of {c}", **_query(con, types, spec)})
    for c, _ in sorted(cats, key=lambda z: z[1])[:4]:
        spec = ChartSpec(kind="bar", x=c, agg="count", limit=15)
        charts.append({"id": f"bar:{c}", "title": f"Rows by {c}", **_query(con, types, spec)})
    if temps:
        spec = ChartSpec(kind="line", x=temps[0], agg="count")
        charts.append({"id": f"line:{temps[0]}", "title": f"Rows over time ({temps[0]})", **_query(con, types, spec)})
    if len(nums) >= 2:
        cols = nums[:12]
        charts.append({"id": "corr", "title": "Correlation between numeric columns", "kind": "correlation",
                       **correlation(con, types, cols)})
    return {"rows_analysed": int(n), "partial": n >= max_rows, "charts": charts}
