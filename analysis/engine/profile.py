"""Module A support: profile any uploaded CSV, suggest a behavioral mapping, and validate a requested
configuration BEFORE any analysis runs.

Two public entry points:

* ``profile_file(path)``      what is in this file? types, missingness, duplicates, constant columns,
                              sparsity, and ranked candidates for entity id / behavior features /
                              reference label. Every key of the previous profile is kept.
* ``validate_config(m, p)``   is this mapping + parameter set usable? Returns issues with an explicit
                              level: ``error`` blocks the analysis, ``warning`` / ``info`` never do.

Nothing here reads a dataset-specific column name; heuristics use only types, cardinalities and generic
naming hints (id / label-like words).
"""
from __future__ import annotations
import math
import re
from decimal import Decimal
import duckdb
from .matrix import csv, q, column_types, key_sql, validate_mapping
from .schemas import Mapping, Params

NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "REAL", "DECIMAL",
           "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT")
FLOATING = ("FLOAT", "DOUBLE", "REAL")
INTEGER_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                 "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT")
ID_HINT = re.compile(r"(^|_)(id|user|student|customer|client|member|person|account)(_|$)|id$", re.I)
VAL_HINT = re.compile(r"(click|count|qty|quantity|amount|total|plays?|views?|visits?|spend|duration|score|num)", re.I)
# stricter than ID_HINT: used to keep identifiers OUT of the behavioral feature candidates
ID_NAME = re.compile(r"(^|[_\s.-])(id|uid|uuid|guid|key|idx|index)($|[_\s.-])|[a-z0-9](Id|ID)$")
ID_NAME_CI = re.compile(r"^(user|student|customer|client|member|person|account)[_\s-]?(no|num|number|code)$", re.I)
LABEL_HINT = re.compile(r"(label|class|result|outcome|target|status|segment|group|category|grade|cluster|tier|"
                        r"type|gender|region|disability|age_band)", re.I)

MAX_PROFILE_FEATURES = 200        # cap on per-column distinct counting in validate_config (wide files)


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _base(dtype: str) -> str:
    return str(dtype).split("(")[0].upper()


def _json_num(x):
    """DuckDB number -> JSON-safe python number (None for NaN / inf / missing)."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        x = float(x)
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _round(x, nd=4):
    x = _json_num(x)
    return None if x is None else round(float(x), nd)


def _issue(level: str, code: str, message: str, **extra) -> dict:
    return {"level": level, "code": code, "message": message, **extra}


# ---------------------------------------------------------------------------------------------
# profiling
# ---------------------------------------------------------------------------------------------
def profile_file(path: str, preview_rows: int = 20, sample_rows: int = 500_000) -> dict:
    con = duckdb.connect()
    src = csv(path)
    n_rows = int(con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0])
    desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    # materialise the sample ONCE: every per-column statistic below then reads memory, not the CSV again
    con.execute(f"CREATE TEMP TABLE smp AS SELECT * FROM {src} LIMIT {int(sample_rows)}")
    n_sample = int(con.execute("SELECT COUNT(*) FROM smp").fetchone()[0])

    cols = []
    for name, dtype, *_ in desc:
        c = q(name)
        base = _base(dtype)
        is_num = base in NUMERIC
        is_float = base in FLOATING
        sel = [f"COUNT(*) - COUNT({c})", f"APPROX_COUNT_DISTINCT({c})"]
        if is_num:
            flt = f" FILTER (WHERE isfinite({c}))" if is_float else ""
            sel += [f"SUM(CASE WHEN {c} = 0 THEN 1 ELSE 0 END)",
                    f"SUM(CASE WHEN NOT isfinite({c}) THEN 1 ELSE 0 END)" if is_float else "0",
                    f"MIN({c}){flt}", f"MAX({c}){flt}", f"AVG({c}){flt}", f"STDDEV({c}){flt}"]
        else:
            sel += [f"SUM(CASE WHEN TRIM(CAST({c} AS VARCHAR)) = '' THEN 1 ELSE 0 END)"]
        row = con.execute(f"SELECT {', '.join(sel)} FROM smp").fetchone()
        nulls, distinct = int(row[0] or 0), int(row[1] or 0)
        non_null = n_sample - nulls
        info = {"name": name, "type": dtype, "numeric": is_num,
                "nulls_in_sample": nulls, "approx_distinct": distinct,
                "missing_ratio": round(nulls / n_sample, 4) if n_sample else 0.0,
                "unique_ratio": round(min(1.0, distinct / non_null), 4) if non_null else 0.0,
                "constant": bool(non_null > 0 and distinct <= 1),
                "all_missing": bool(n_sample > 0 and non_null == 0)}
        if is_num:
            zeros, nonfinite = int(row[2] or 0), int(row[3] or 0)
            info.update({"min": _json_num(row[4]), "max": _json_num(row[5]), "mean": _round(row[6]), "std": _round(row[7]),
                         "zero_ratio": round(zeros / n_sample, 4) if n_sample else 0.0,
                         # share of cells that carry no activity (0 or missing): the per-column sparsity
                         "sparsity": round((zeros + nulls) / n_sample, 4) if n_sample else 0.0,
                         "non_finite_in_sample": nonfinite})
        else:
            info["blank_in_sample"] = int(row[2] or 0)
            if info["approx_distinct"] <= 60:
                top = con.execute(
                    f"SELECT CAST({c} AS VARCHAR), COUNT(*) n FROM smp WHERE {c} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY n DESC LIMIT 10").fetchall()
                info["top_values"] = [{"value": v, "count": int(n)} for v, n in top]
        info["id_like"] = _id_like(info, n_sample)
        cols.append(info)

    dup = 0
    if n_sample:
        dup = int(con.execute("SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM smp)) FROM smp").fetchone()[0])
    preview = con.execute(f"SELECT * FROM {src} LIMIT {int(preview_rows)}").df().astype(object)
    preview = [{k: _json_num(v) if isinstance(v, (float, Decimal)) else v for k, v in r.items()}
               for r in preview.where(preview.notna(), None).to_dict("records")]

    candidates = find_candidates(cols, n_sample)
    feats = set(candidates["behavior_features"])
    spars = [c["sparsity"] for c in cols if c["name"] in feats]
    return {"rows": n_rows, "sample_rows": n_sample, "columns": cols, "preview": preview,
            "duplicate_rows_in_sample": dup,
            "constant_columns": [c["name"] for c in cols if c["constant"]],
            "all_missing_columns": [c["name"] for c in cols if c["all_missing"]],
            "numeric_sparsity": round(sum(spars) / len(spars), 4) if spars else None,
            "candidates": candidates,
            "issues": file_issues(cols, n_rows, n_sample, dup, candidates),
            "behavioral_suggestion": suggest_mapping(cols, n_rows)}


def _id_like(c: dict, n_sample: int) -> bool:
    """A column that identifies rows/entities rather than describing behavior: id-like name, or an integer /
    text column that is (nearly) unique per row."""
    if c["all_missing"]:
        return False
    if ID_NAME.search(c["name"]) or ID_NAME_CI.search(c["name"]):
        return True
    near_unique = n_sample >= 20 and c["unique_ratio"] >= 0.99
    base = _base(c["type"])
    return bool(near_unique and (base in INTEGER_TYPES or base == "VARCHAR"))


def find_candidates(cols: list[dict], n_sample: int) -> dict:
    """Ranked, explained candidates by role. Heuristic only: the UI/user always has the last word."""
    usable = [c for c in cols if not c["all_missing"] and not c["constant"]]

    entity = []
    for c in usable:
        if c["missing_ratio"] > 0.5:
            continue
        score, why = 0, []
        if c["id_like"] or ID_HINT.search(c["name"]):
            score += 3
            why.append("id-like name or values")
        repeats = 1 < c["approx_distinct"] < max(2, n_sample * 0.9)
        if repeats:
            score += 1
            why.append("repeats across rows (event log)")
        if c["approx_distinct"] > 30:
            score += 1
            why.append("many distinct values")
        if c["unique_ratio"] >= 0.9 and (c["id_like"] or ID_HINT.search(c["name"])):
            why.append("one row per entity (wide matrix)")
        if _base(c["type"]) in FLOATING and not c["id_like"]:
            score -= 2                      # a fractional measure is not an identifier
        if score >= 3 or (score >= 2 and repeats and c["approx_distinct"] > 30):
            entity.append({"name": c["name"], "score": score,
                           "layout": "wide" if c["unique_ratio"] >= 0.9 else "long", "reason": "; ".join(why)})
    entity.sort(key=lambda e: (-e["score"], e["name"]))

    labels = []
    for c in usable:
        if c["id_like"] or c["missing_ratio"] > 0.5:
            continue
        base = _base(c["type"])
        if base in FLOATING or base == "DECIMAL":
            continue
        if 2 <= c["approx_distinct"] <= min(50, max(2, int(n_sample * 0.2))):
            labels.append({"name": c["name"], "n_classes": c["approx_distinct"], "missing_ratio": c["missing_ratio"],
                           "name_hint": bool(LABEL_HINT.search(c["name"]))})
    labels.sort(key=lambda l: (not l["name_hint"], l["missing_ratio"], l["name"]))
    label_hint_names = {l["name"] for l in labels if l["name_hint"]}

    # numeric behavior features: never ids, never constants, never an obvious reference label
    features = [c["name"] for c in usable
                if c["numeric"] and not c["id_like"] and c["name"] not in label_hint_names]
    categories = [c["name"] for c in usable
                  if not c["numeric"] and 3 <= c["approx_distinct"] <= 200 and not c["id_like"]]
    return {"entity_ids": entity[:5], "behavior_features": features, "behavior_categories": categories,
            "reference_labels": labels[:8],
            "excluded": {"id_like": [c["name"] for c in cols if c["id_like"]],
                         "constant": [c["name"] for c in cols if c["constant"]],
                         "all_missing": [c["name"] for c in cols if c["all_missing"]]}}


def file_issues(cols: list[dict], n_rows: int, n_sample: int, dup: int, cand: dict) -> list[dict]:
    out = []
    if n_rows == 0:
        out.append(_issue("error", "empty_file", "The file has no data rows."))
        return out
    if not cols:
        out.append(_issue("error", "no_columns", "The file has no columns."))
        return out
    if n_rows > n_sample:
        out.append(_issue("info", "sampled", f"Column statistics use the first {n_sample:,} of {n_rows:,} rows."))
    allm = [c["name"] for c in cols if c["all_missing"]]
    if allm:
        out.append(_issue("warning", "all_missing", f"Column(s) with no values at all: {', '.join(allm[:8])}.", columns=allm))
    const = [c["name"] for c in cols if c["constant"]]
    if const:
        out.append(_issue("warning", "constant", f"Constant column(s) (one value everywhere, no use as a behavior): "
                          f"{', '.join(const[:8])}.", columns=const))
    heavy = [c["name"] for c in cols if c["missing_ratio"] > 0.3 and not c["all_missing"]]
    if heavy:
        out.append(_issue("warning", "high_missing", f"More than 30% missing values in: {', '.join(heavy[:8])}.", columns=heavy))
    nonfin = [c["name"] for c in cols if c.get("non_finite_in_sample")]
    if nonfin:
        out.append(_issue("warning", "non_finite", f"NaN / infinite numbers in: {', '.join(nonfin[:8])}.", columns=nonfin))
    if dup:
        out.append(_issue("warning", "duplicate_rows", f"{dup:,} fully duplicated row(s) in the sample "
                          f"({dup / n_sample:.1%}). Repeated events are only counted twice if they are really repeated."))
    if not cand["entity_ids"]:
        out.append(_issue("warning", "no_entity_candidate", "No column looks like an entity id; choose it manually."))
    if len(cand["behavior_features"]) < 2 and not cand["behavior_categories"]:
        out.append(_issue("warning", "few_behaviors", "Fewer than 2 numeric features and no category column: the file "
                          "may need a lookup file to define behaviors."))
    return out


def suggest_mapping(cols: list[dict], n_rows: int) -> dict:
    """Heuristic guess of entity / behavior / value columns. The UI pre-fills these; users can override."""
    entity = behavior = value = None
    best = -1
    live = [c for c in cols if not c.get("all_missing")]
    for c in live:
        score = 0
        if ID_HINT.search(c["name"]):
            score += 2
        if 1 < c["approx_distinct"] < max(2, n_rows * 0.9):
            score += 1                      # repeats -> multiple rows per entity
        if c["approx_distinct"] > 30:
            score += 1
        if score > best:
            best, entity = score, c["name"]
    cats = [c for c in live if not c["numeric"] and 3 <= c["approx_distinct"] <= 200 and c["name"] != entity]
    if cats:
        behavior = min(cats, key=lambda c: abs(c["approx_distinct"] - 12))["name"]
    nums = [c for c in live if c["numeric"] and c["name"] != entity]
    nums = [c for c in nums if not c.get("constant")] or nums         # prefer a column that actually varies
    hinted = [c for c in nums if VAL_HINT.search(c["name"])]
    if hinted or nums:
        value = (hinted or nums)[0]["name"]
    confidence = "high" if entity and behavior and value and best >= 3 else ("low" if entity else "none")
    return {"entity_col": entity, "behavior_col": behavior, "value_col": value, "confidence": confidence,
            "note": "No categorical behavior column here: it may live in a separate lookup file (e.g. OULAD vle.csv)."
                    if not behavior else None}


# ---------------------------------------------------------------------------------------------
# configuration validation (before any analysis)
# ---------------------------------------------------------------------------------------------
def _result(issues: list[dict], **extra) -> dict:
    errors = [i["message"] for i in issues if i["level"] == "error"]
    warnings = [i["message"] for i in issues if i["level"] == "warning"]
    return {"ok": not errors, "errors": errors, "warnings": warnings, "issues": issues, **extra}


def validate_params(p: Params, n_entities: int | None = None) -> list[dict]:
    """Cross-field checks that the per-field ranges of `Params` cannot express."""
    out = []
    if not p.algorithms:
        out.append(_issue("error", "no_algorithm", "Select at least one community detection algorithm."))
    elif len(set(p.algorithms)) != len(p.algorithms):
        out.append(_issue("warning", "duplicate_algorithms", "An algorithm was listed more than once; it runs once."))
    if p.algorithms and p.primary_algorithm not in ("best_modularity", *p.algorithms):
        out.append(_issue("warning", "primary_not_selected",
                          f"Primary algorithm '{p.primary_algorithm}' is not among the selected algorithms; "
                          "the first algorithm that succeeds will be used instead."))
    if len(p.tier_labels) != 3:
        out.append(_issue("error", "tier_labels", f"Exactly 3 tier labels are needed (low, moderate, high); got {len(p.tier_labels)}."))
    else:
        names = [str(t).strip() for t in p.tier_labels]
        if any(not t for t in names):
            out.append(_issue("error", "tier_labels", "Tier labels must not be empty."))
        elif len(set(names)) < 3:
            out.append(_issue("error", "tier_labels", "Tier labels must be different from each other."))
    if p.tier_method == "thresholds":
        if p.low_cut is None or p.high_cut is None:
            out.append(_issue("error", "tier_cuts", "tier_method 'thresholds' needs both low_cut and high_cut."))
        elif not (math.isfinite(p.low_cut) and math.isfinite(p.high_cut)):
            out.append(_issue("error", "tier_cuts", "low_cut and high_cut must be finite numbers."))
        elif p.low_cut > p.high_cut:
            out.append(_issue("error", "tier_cuts", f"low_cut ({p.low_cut:g}) must not be greater than high_cut ({p.high_cut:g})."))
    if p.graph_method == "threshold":
        if p.threshold >= 1.0:
            out.append(_issue("warning", "threshold_max", "Threshold 1.0 links only entities with identical behavior shape; "
                              "expect very few edges."))
        elif p.threshold <= 0.0:
            out.append(_issue("warning", "threshold_zero", "Threshold 0 links every pair with non-negative similarity; "
                              "the graph will be almost complete and communities meaningless."))
    elif n_entities is not None:
        pool = min(n_entities, p.sample_size) if p.sample_size else n_entities
        if p.knn_k >= pool > 0:
            out.append(_issue("warning", "knn_k_large", f"k={p.knn_k} is not smaller than the {pool} entities analysed; "
                              f"it is reduced to {max(pool - 1, 1)}."))
    if p.stability_runs == 1:
        out.append(_issue("warning", "stability_runs", "stability_runs=1 cannot measure stability; use 0 (off) or at least 2."))
    return out


def validate_config(m: Mapping, p: Params | None = None) -> dict:
    """Validate a mapping (and optionally parameters) without building the matrix.

    Blocking (`error`): unknown columns, label leakage, ids used as features, no usable entity ids,
    non-numeric value / feature columns, contradictory parameters.
    Non-blocking (`warning` / `info`): missingness, constants, label coverage, label that looks like an id,
    a run without any reference label (evaluation metrics are then reported as unavailable, not 0).
    """
    issues: list[dict] = []
    con = duckdb.connect()
    try:
        validate_mapping(con, m)            # columns exist, label leakage, ids not used as behaviors
    except ValueError as e:
        issues.append(_issue("error", "mapping", str(e)))
        if p is not None:
            issues += validate_params(p)
        return _result(issues)

    types = column_types(con, m.path)
    ent = key_sql(q(m.entity_col), types[m.entity_col])
    n_rows, n_keyed, n_entities = (int(x) for x in con.execute(
        f"SELECT COUNT(*), COUNT({ent}), COUNT(DISTINCT {ent}) FROM {csv(m.path)}").fetchone())
    if n_rows == 0:
        issues.append(_issue("error", "empty_file", "The main file has no data rows."))
    elif n_keyed == 0:
        issues.append(_issue("error", "entity_all_missing", f"Entity column '{m.entity_col}' has no usable (non-blank) ids."))
    elif n_keyed < n_rows:
        issues.append(_issue("warning", "entity_missing", f"{n_rows - n_keyed:,} row(s) have a missing entity id and are skipped."))

    def numeric_check(col: str, role: str):
        t = _base(types[col])
        if t in NUMERIC or t == "BOOLEAN":
            return
        if t == "VARCHAR":
            issues.append(_issue("warning", "text_numeric", f"{role} '{col}' is stored as text; only cells that parse as "
                                 "finite numbers are used, the rest are ignored.", column=col))
        else:
            issues.append(_issue("error", "not_numeric", f"{role} '{col}' has type {types[col]}, which cannot be used as a number.", column=col))

    if n_keyed:
        if m.format == "wide":
            feats = list(dict.fromkeys(m.feature_cols or []))
            for col in feats:
                numeric_check(col, "Feature column")
            if len(feats) < len(m.feature_cols or []):
                issues.append(_issue("warning", "duplicate_features", "A feature column was listed more than once; it is counted once."))
            if n_entities < n_keyed:
                issues.append(_issue("warning", "duplicate_entities", f"{n_keyed - n_entities:,} row(s) repeat an entity id in a wide "
                                     "file; they will be summed into one row per entity."))
            shown = feats[:MAX_PROFILE_FEATURES]
            if shown:
                sel = ", ".join(f"COUNT(DISTINCT {q(c)})" for c in shown)
                counts = con.execute(f"SELECT {sel} FROM {csv(m.path)}").fetchone()
                const = [c for c, k in zip(shown, counts) if int(k) <= 1]
                if const:
                    issues.append(_issue("warning", "constant_features", "Constant feature column(s) cannot separate entities: "
                                         f"{', '.join(const[:8])}.", columns=const))
                if len(shown) - len(const) < 2:
                    issues.append(_issue("error", "no_varying_features", "Fewer than 2 of the selected features vary between rows; "
                                         "entities cannot be told apart."))
        else:
            if m.agg == "count":
                if m.value_col:
                    issues.append(_issue("info", "value_ignored", f"agg='count' ignores value column '{m.value_col}'."))
            else:
                numeric_check(m.value_col, "Value column")
            if n_entities == n_keyed and n_keyed > 1:
                issues.append(_issue("warning", "entity_once", "Every entity appears in exactly one row, so each has a single "
                                     "behavior. Did you pick a row id instead of an entity id?"))

    if m.label is None:
        issues.append(_issue("info", "no_label", "No reference label: communities are still found, but NMI / AMI against a "
                             "ground truth are reported as unavailable (not 0)."))
    elif n_keyed:
        issues += _label_issues(con, m, ent)

    if p is not None:
        issues += validate_params(p, n_entities)
    return _result(issues, entities=n_entities, rows=n_rows)


def _label_issues(con, m: Mapping, ent_sql: str) -> list[dict]:
    """How well does the optional label file cover the entities, and does the label look usable?"""
    out = []
    lab = m.label
    ltypes = column_types(con, lab.path)
    lkey = key_sql(q(lab.entity_col), ltypes[lab.entity_col])
    lval = f"NULLIF(TRIM(CAST({q(lab.label_col)} AS VARCHAR)), '')"
    usable = f"{lkey} IS NOT NULL AND {lval} IS NOT NULL AND LOWER({lval}) <> 'nan'"
    rows, classes, lab_entities = (int(x) for x in con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT {lval}), COUNT(DISTINCT {lkey}) FROM {csv(lab.path)} WHERE {usable}").fetchone())
    if rows == 0:
        out.append(_issue("warning", "label_empty", f"The label file has no usable (entity, '{lab.label_col}') pairs; "
                          "evaluation metrics will be unavailable."))
        return out
    if classes < 2:
        out.append(_issue("warning", "label_single_class", f"Label '{lab.label_col}' has a single class; NMI / AMI are undefined "
                          "and will be reported as unavailable."))
    elif classes > 50 and classes > 0.5 * lab_entities:
        out.append(_issue("warning", "label_id_like", f"Label '{lab.label_col}' has {classes:,} classes for {lab_entities:,} entities; "
                          "it looks like an identifier, and NMI against it would be inflated and meaningless."))
    cov = con.execute(
        f"WITH me AS (SELECT DISTINCT {ent_sql} AS k FROM {csv(m.path)} WHERE {ent_sql} IS NOT NULL), "
        f"le AS (SELECT DISTINCT {lkey} AS k FROM {csv(lab.path)} WHERE {usable}) "
        f"SELECT COUNT(*), COUNT(le.k) FROM me LEFT JOIN le ON me.k = le.k").fetchone()
    total, matched = int(cov[0]), int(cov[1])
    if matched == 0:
        out.append(_issue("warning", "label_no_overlap", "No entity of the behavior file appears in the label file (check id type / "
                          "formatting); evaluation metrics will be unavailable."))
    elif total and matched / total < 0.5:
        out.append(_issue("warning", "label_low_coverage", f"Only {matched / total:.0%} of the entities have a label; "
                          "NMI is computed on that subset only."))
    return out