"""Module A support: profile any uploaded CSV and suggest a behavioral mapping."""
from __future__ import annotations
import re
import duckdb
from .matrix import csv, q

NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "UBIGINT", "UINTEGER")
ID_HINT = re.compile(r"(^|_)(id|user|student|customer|client|member|person|account)(_|$)|id$", re.I)
VAL_HINT = re.compile(r"(click|count|qty|quantity|amount|total|plays?|views?|visits?|spend|duration|score|num)", re.I)


def profile_file(path: str, preview_rows: int = 20, sample_rows: int = 500_000) -> dict:
    con = duckdb.connect()
    src = csv(path)
    n_rows = con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
    desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    sample = f"(SELECT * FROM {src} LIMIT {sample_rows})"
    cols = []
    for name, dtype, *_ in desc:
        base = dtype.split("(")[0]
        is_num = base in NUMERIC
        row = con.execute(
            f"SELECT COUNT(*) - COUNT({q(name)}), APPROX_COUNT_DISTINCT({q(name)}) FROM {sample}"
        ).fetchone()
        info = {"name": name, "type": dtype, "numeric": is_num,
                "nulls_in_sample": int(row[0]), "approx_distinct": int(row[1])}
        if is_num:
            s = con.execute(f"SELECT MIN({q(name)}), MAX({q(name)}), AVG({q(name)}), STDDEV({q(name)}) FROM {sample}").fetchone()
            info.update({"min": s[0], "max": s[1], "mean": None if s[2] is None else round(float(s[2]), 4),
                         "std": None if s[3] is None else round(float(s[3]), 4)})
        elif info["approx_distinct"] <= 60:
            top = con.execute(
                f"SELECT CAST({q(name)} AS VARCHAR), COUNT(*) c FROM {sample} WHERE {q(name)} IS NOT NULL "
                f"GROUP BY 1 ORDER BY c DESC LIMIT 10").fetchall()
            info["top_values"] = [{"value": v, "count": int(c)} for v, c in top]
        cols.append(info)
    preview = con.execute(f"SELECT * FROM {src} LIMIT {preview_rows}").df().astype(object)
    preview = preview.where(preview.notna(), None).to_dict("records")
    return {"rows": int(n_rows), "columns": cols, "preview": preview,
            "behavioral_suggestion": suggest_mapping(cols, n_rows)}


def suggest_mapping(cols: list[dict], n_rows: int) -> dict:
    """Heuristic guess of entity / behavior / value columns. The UI pre-fills these; users can override."""
    entity = behavior = value = None
    best = -1
    for c in cols:
        score = 0
        if ID_HINT.search(c["name"]):
            score += 2
        if 1 < c["approx_distinct"] < max(2, n_rows * 0.9):
            score += 1                      # repeats -> multiple rows per entity
        if c["approx_distinct"] > 30:
            score += 1
        if score > best:
            best, entity = score, c["name"]
    cats = [c for c in cols if not c["numeric"] and 3 <= c["approx_distinct"] <= 200 and c["name"] != entity]
    if cats:
        behavior = min(cats, key=lambda c: abs(c["approx_distinct"] - 12))["name"]
    nums = [c for c in cols if c["numeric"] and c["name"] != entity]
    hinted = [c for c in nums if VAL_HINT.search(c["name"])]
    if hinted or nums:
        value = (hinted or nums)[0]["name"]
    confidence = "high" if entity and behavior and value and best >= 3 else ("low" if entity else "none")
    return {"entity_col": entity, "behavior_col": behavior, "value_col": value, "confidence": confidence,
            "note": "No categorical behavior column here: it may live in a separate lookup file (e.g. OULAD vle.csv)."
                    if not behavior else None}
