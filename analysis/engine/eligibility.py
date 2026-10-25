"""Answers: 'is this dataset suitable for behavioral analysis?' with reasons."""
from __future__ import annotations
import numpy as np
import pandas as pd

MIN_ENTITIES, MIN_BEHAVIORS = 30, 3


def check_matrix(mat: pd.DataFrame) -> dict:
    errors, warnings = [], []
    n_ent, n_beh = mat.shape
    if n_ent < MIN_ENTITIES:
        errors.append(f"Only {n_ent} entities found; at least {MIN_ENTITIES} are needed to form communities.")
    if n_beh < MIN_BEHAVIORS:
        errors.append(f"Only {n_beh} behavior categories found; at least {MIN_BEHAVIORS} are needed "
                      "(cosine similarity on 1-2 dimensions is meaningless).")
    if (mat.values < 0).any():
        warnings.append("Negative values found; cosine similarity expects non-negative activity counts.")
    varying = int((mat.std(axis=0) > 0).sum())
    if varying < 2:
        errors.append("Fewer than 2 behavior columns vary between entities, so nobody can be told apart.")
    sparsity = float((mat.values == 0).mean()) if mat.size else 1.0
    if sparsity > 0.9:
        warnings.append(f"Matrix is {sparsity:.0%} zeros; similarity edges will be sparse.")
    flat = int((mat.values == mat.values.min(axis=0)).all(axis=1).sum()) if mat.size else 0
    if flat:
        warnings.append(f"{flat} entities have the minimum value in every behavior, so after min-max scaling they have "
                        "no direction (zero vector) and cannot be linked to anyone; they will be left out of the graph.")
    bad = int(mat.attrs.get("non_finite_replaced", 0))
    if bad:
        warnings.append(f"{bad} non-finite cell(s) (NaN / infinity) were replaced by 0 before analysis.")
    dup = int(mat.attrs.get("duplicate_entity_rows_aggregated", 0))
    if dup:
        warnings.append(f"{dup} duplicate entity row(s) in the wide file were summed into one row per entity.")
    unusable = int(mat.attrs.get("unusable_value_cells", 0))
    if unusable:
        warnings.append(f"{unusable} value cell(s) were not usable numbers (text, NaN or infinity) and were ignored.")
    unmapped, events = int(mat.attrs.get("unmapped_rows", 0)), int(mat.attrs.get("event_rows", 0))
    if unmapped:
        share = f" ({unmapped / events:.0%} of all rows)" if events else ""
        warnings.append(f"{unmapped} row(s){share} could not be assigned to a behavior (blank category or no matching "
                        "lookup key) and were left out.")
    conflicts = int(mat.attrs.get("lookup_conflicting_keys", 0))
    if conflicts:
        warnings.append(f"{conflicts} lookup key(s) map to several different categories; the alphabetically first "
                        "category was used for each. Use a split delimiter if one key really has several categories.")
    dup_feat = int(mat.attrs.get("duplicate_feature_cols_ignored", 0))
    if dup_feat:
        warnings.append(f"{dup_feat} repeated feature column(s) were counted once.")
    zero = int(mat.attrs.get("all_zero_columns_dropped_count", 0))
    if zero:
        names = ", ".join(map(str, mat.attrs.get("all_zero_columns_dropped", [])[:5]))
        warnings.append(f"{zero} behavior column(s) were zero for every entity and were removed ({names}"
                        f"{', ...' if zero > 5 else ''}).")
    constant = n_beh - varying
    if constant > 0 and varying >= 2:
        warnings.append(f"{constant} behavior column(s) have the same value for every entity; they cannot separate "
                        "entities (they still count toward total activity).")
    if n_beh > 500:
        warnings.append(f"{n_beh} behavior columns is very wide; consider grouping into broader categories.")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {"entities": int(n_ent), "behaviors": int(n_beh),
                  "sparsity": round(sparsity, 4), "varying_behaviors": varying,
                  "zero_vector_entities": flat,
                  "behavior_names": [str(c) for c in mat.columns[:100]]},
    }