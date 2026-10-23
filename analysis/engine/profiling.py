"""Steps 6-7: profile each community and assign the 3 tiers."""
from __future__ import annotations
import numpy as np
import pandas as pd

OUTLIER = "Outlier group (too small)"


def profile_communities(communities, raw_matrix: pd.DataFrame) -> pd.DataFrame:
    totals = raw_matrix.sum(axis=1)
    rows = []
    for cid, members in enumerate(communities):
        members = list(members)
        sub = raw_matrix.loc[members]
        rows.append({
            "community_id": cid,
            "community_size": len(members),
            "avg_total_activity": float(totals.loc[members].mean()),
            "top_behavior": str(sub.mean().idxmax()),
            "members": members,
        })
    return pd.DataFrame(rows)


def assign_tiers(df: pd.DataFrame, labels: list[str], method: str = "quantile",
                 low_cut: float | None = None, high_cut: float | None = None,
                 min_size: int = 1) -> pd.DataFrame:
    """labels = [low, moderate, high]. Quantile = three equal-count bins over communities
    (same as the original pd.qcut), robust to ties."""
    df = df.copy()
    eligible = df["community_size"] >= min_size
    df["tier"] = OUTLIER
    sub = df[eligible]
    if sub.empty:
        return df
    if method == "thresholds":
        if low_cut is None or high_cut is None:
            raise ValueError("tier_method='thresholds' needs low_cut and high_cut.")
        v = sub["avg_total_activity"]
        df.loc[sub.index, "tier"] = np.where(v >= high_cut, labels[2],
                                             np.where(v >= low_cut, labels[1], labels[0]))
    else:
        n = len(sub)
        rank = sub["avg_total_activity"].rank(method="first")          # 1..n, ties broken
        bucket = np.minimum(((rank - 1) * 3 / n).astype(int), 2)       # 0,1,2
        df.loc[sub.index, "tier"] = [labels[b] for b in bucket]
    return df


def behavior_profile(communities, raw_matrix: pd.DataFrame) -> dict:
    """Mean raw activity per behavior for every community: the 'what do they actually do' table.
    Returns {community_index: {behavior: mean}}."""
    out = {}
    for cid, members in enumerate(communities):
        out[cid] = raw_matrix.loc[list(members)].mean().to_dict()
    return out


def community_stats(communities, raw_matrix: pd.DataFrame, sim: np.ndarray, ids: list) -> dict:
    """Spread + cohesion per community.
    cohesion = mean pairwise cosine similarity INSIDE the community (1 = identical behavior)."""
    pos = {n: i for i, n in enumerate(ids)}
    totals = raw_matrix.sum(axis=1)
    out = {}
    for cid, members in enumerate(communities):
        members = list(members)
        t = totals.loc[members]
        idx = [pos[m] for m in members]
        if len(idx) > 1:
            sub = sim[np.ix_(idx, idx)]
            cohesion = float(sub[np.triu_indices(len(idx), k=1)].mean())
        else:
            cohesion = None
        out[cid] = {"median_total": float(t.median()), "std_total": float(t.std(ddof=0)),
                    "min_total": float(t.min()), "max_total": float(t.max()), "cohesion": cohesion}
    return out