"""Evaluation of detected communities against reference labels.

This module is the ONE place where the conventions for external cluster validation live, so that
the benchmark table, the NMI dashboard and the tests can never disagree with each other.

Conventions
-----------
* Alignment is ALWAYS by entity id (dict / Series keys), never by row position.
* Evaluation population = entities that (a) are nodes of the analysed graph, (b) belong to a
  detected community and (c) carry a usable (non-missing, non-ambiguous) reference label.
  Entities that were dropped from the graph (no similar peer) or have no label are NOT scored;
  they are counted and reported as `coverage` instead of being silently ignored.
* NMI = sklearn.metrics.normalized_mutual_info_score (arithmetic normalisation, natural log).
  It is invariant to renaming communities / label classes and to the order of entities.
* NMI is `None` (unavailable), never 0.0, when it is mathematically undefined or meaningless:
  no labels supplied, fewer than MIN_EVALUATED evaluated entities, or a single label class.
  A real 0.0 means "the partition carries no information about the label".
* NMI is biased upwards when the number of communities is large relative to the number of
  entities, so AMI (chance-adjusted) and the mean NMI obtained after shuffling the labels
  (`nmi_null_mean`) are reported next to it. Use them to tell "genuinely unrelated" from
  "looks low but is above chance".
"""
from __future__ import annotations

from typing import Iterable, Mapping as MappingT

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_mutual_info_score, normalized_mutual_info_score

MIN_EVALUATED = 5                      # fewer scored entities than this -> metric unavailable
_MISSING_TOKENS = {"", "nan"}          # what a missing value looks like after CAST(... AS VARCHAR)

REASONS = {
    "no_labels": "No reference label was supplied, so NMI against a ground truth is not defined.",
    "too_few_labeled": f"Fewer than {MIN_EVALUATED} graph entities have a usable reference label.",
    "single_label_class": "The evaluated entities all share ONE label class, so NMI is undefined.",
    "no_partition": "No community partition is available.",
}


# ---------------------------------------------------------------------------------------------
# label / id canonicalisation
# ---------------------------------------------------------------------------------------------
def canonical_label(value) -> str | None:
    """Return the label as a stripped string, or None when it is missing.

    Real nulls, float NaN and the empty string are missing. The literal text "nan" is also treated
    as missing (that is what a numeric NaN looks like after CAST AS VARCHAR). Other tokens such as
    "None" or "null" are kept: they can be genuine class names (e.g. disability = "None").
    """
    try:
        if value is None or bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return None if s.lower() in _MISSING_TOKENS else s


def canonical_id(value) -> str:
    """Canonical text key for an entity id so that 7, 7.0, np.int64(7) and ' 7 ' all match."""
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer():
        return str(int(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value).strip()


def membership(communities: Iterable[Iterable]) -> dict:
    """node -> community index. Raises if a node appears in more than one community."""
    out: dict = {}
    for i, c in enumerate(communities):
        for n in c:
            if n in out:
                raise ValueError(f"Node {n!r} appears in more than one community; not a partition.")
            out[n] = i
    return out


# ---------------------------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------------------------
def nmi_score(y_true, y_pred) -> float:
    """Plain NMI (sklearn, arithmetic average). Inputs must already be aligned element by element."""
    return float(normalized_mutual_info_score(y_true, y_pred))


def evaluate_partition(communities, labels: MappingT | pd.Series | None, population: Iterable | None = None,
                       *, null_permutations: int = 10, seed: int = 0) -> dict:
    """Score one partition against reference labels on a clearly defined population.

    communities : list of node collections (a partition of the graph nodes)
    labels      : {entity id: label}; missing / ambiguous entities may be absent, None or NaN.
                  None means "no label file was supplied at all".
    population  : the clustering universe (normally G.nodes()). Defaults to the partitioned nodes.

    Returns a dict with: available, nmi, ami, nmi_null_mean, nmi_null_std, reason_code, reason,
    n_nodes, n_labeled, n_evaluated, coverage (n_evaluated / n_nodes), n_label_classes,
    n_communities_evaluated.
    """
    node_to_c = membership(communities) if communities is not None else {}
    nodes = list(population) if population is not None else list(node_to_c)
    in_partition = [n for n in nodes if n in node_to_c]
    out = {"available": False, "nmi": None, "ami": None, "nmi_null_mean": None, "nmi_null_std": None,
           "reason_code": None, "reason": None, "n_nodes": len(nodes), "n_labeled": 0,
           "n_evaluated": 0, "coverage": None, "n_label_classes": 0, "n_communities_evaluated": 0}

    def fail(code):
        out["reason_code"], out["reason"] = code, REASONS[code]
        return out

    if not node_to_c:
        return fail("no_partition")
    if labels is None:
        return fail("no_labels")

    get = labels.get if hasattr(labels, "get") else (lambda k, d=None: d)
    pairs = []
    for n in in_partition:
        lab = canonical_label(get(n))
        if lab is not None:
            pairs.append((lab, node_to_c[n]))
    out["n_labeled"] = len(pairs)
    out["n_evaluated"] = len(pairs)
    out["coverage"] = round(len(pairs) / len(nodes), 4) if nodes else None
    if len(pairs) < MIN_EVALUATED:
        return fail("too_few_labeled")
    y_true = [p[0] for p in pairs]
    y_pred = [p[1] for p in pairs]
    out["n_label_classes"] = len(set(y_true))
    out["n_communities_evaluated"] = len(set(y_pred))
    if out["n_label_classes"] < 2:
        return fail("single_label_class")

    out["nmi"] = round(nmi_score(y_true, y_pred), 6)
    out["ami"] = round(float(adjusted_mutual_info_score(y_true, y_pred)), 6)
    out["available"] = True
    if null_permutations and null_permutations > 0:
        rng = np.random.default_rng(seed)
        arr = np.asarray(y_true, dtype=object)
        vals = [nmi_score(rng.permutation(arr).tolist(), y_pred) for _ in range(int(null_permutations))]
        out["nmi_null_mean"] = round(float(np.mean(vals)), 6)
        out["nmi_null_std"] = round(float(np.std(vals)), 6)
    return out