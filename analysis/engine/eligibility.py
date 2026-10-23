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
    if n_beh > 500:
        warnings.append(f"{n_beh} behavior columns is very wide; consider grouping into broader categories.")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {"entities": int(n_ent), "behaviors": int(n_beh),
                  "sparsity": round(sparsity, 4), "varying_behaviors": varying,
                  "behavior_names": [str(c) for c in mat.columns[:100]]},
    }
