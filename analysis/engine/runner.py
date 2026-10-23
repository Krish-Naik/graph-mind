"""Runs the full behavioral pipeline and returns one JSON-serialisable result."""
from __future__ import annotations
import os
import time
from collections import Counter
import numpy as np
import pandas as pd

from .schemas import RunRequest, Mapping
from .matrix import build_matrix, load_labels
from .graph import scale, similarity, similarity_histogram, build_graph, threshold_sweep, embed_2d
from .communities import detect, NAMES
from .profiling import profile_communities, assign_tiers, OUTLIER, behavior_profile, community_stats
from .eligibility import check_matrix
from .graph_metrics import (graph_density_metrics, algorithm_comparison, nmi_analysis,
                            community_density_profile, modularity_analysis)


MAX_BEHAVIORS_SHOWN = 25


def check(mapping: Mapping, sample_size: int | None = 300, random_state: int = 42) -> dict:
    mat = build_matrix(mapping)
    rep = check_matrix(mat)
    if rep["ok"]:
        sm = mat.sample(n=sample_size, random_state=random_state) if sample_size and len(mat) > sample_size else mat
        rep["similarity"] = similarity_histogram(similarity(scale(sm)))
    rep["stats"]["preview"] = mat.head(5).round(2).reset_index().astype(object).where(
        lambda d: d.notna(), None).to_dict("records")
    return rep


def run(req: RunRequest) -> dict:
    t0 = time.time()
    m, p = req.mapping, req.params

    # 1. matrix
    full = build_matrix(m)
    report = check_matrix(full)
    if not report["ok"]:
        return {"status": "ineligible", "eligibility": report}
    n_total = len(full)

    # sampling (pandas .sample so results are reproducible vs. the original notebook)
    mat = full
    if p.sample_size and n_total > p.sample_size:
        mat = full.sample(n=p.sample_size, random_state=p.random_state)
    ids = mat.index.tolist()

    # 2-4. scale -> cosine -> graph
    scaled = scale(mat)
    sim = similarity(scaled)
    hist = similarity_histogram(sim)
    sweep = threshold_sweep(sim)
    G = build_graph(sim, ids, p.graph_method, p.threshold, p.knn_k)
    if G.number_of_nodes() < 3:
        return {"status": "empty_graph", "eligibility": report, "similarity": hist,
                "message": "Too few connected entities. Lower the threshold or use kNN graph."}

    labels = load_labels(m, mat.index) if m.label else None
    label_map = labels.to_dict() if labels is not None else None

    # 5. community detection + benchmark
    results, bench = detect(G, p.algorithms, p.random_state, label_map)
    if not results:
        return {"status": "error", "message": "All community algorithms failed.", "benchmark": bench}
    ok_rows = [r for r in bench if "modularity" in r]
    if p.primary_algorithm == "best_modularity":
        primary = max(ok_rows, key=lambda r: r["modularity"])["key"]
    else:
        primary = p.primary_algorithm if p.primary_algorithm in results else ok_rows[0]["key"]
    comms = results[primary]

    # 6-7. profile + tier
    prof = profile_communities(comms, mat)
    prof = assign_tiers(prof, p.tier_labels, p.tier_method, p.low_cut, p.high_cut, p.min_community_size)
    prof = prof.sort_values("avg_total_activity", ascending=False).reset_index(drop=True)

    node_comm, node_tier = {}, {}
    for _, r in prof.iterrows():
        for n in r["members"]:
            node_comm[n], node_tier[n] = int(r["community_id"]), r["tier"]
    totals = mat.sum(axis=1)
    bprof = behavior_profile(comms, mat)
    cstats = community_stats(comms, mat, sim, ids)
    xy, pca_var = embed_2d(scaled)
    xy_of = {ids[i]: (float(xy[i, 0]), float(xy[i, 1])) for i in range(len(ids))}

    # behaviors shown in the profile heatmap: the busiest ones overall (capped so it stays readable)
    # baseline = the entities that actually got a community/tier (isolated ones would distort the averages)
    overall = mat.loc[list(node_comm.keys())].mean().sort_values(ascending=False)
    shown = [str(b) for b in overall.index[:MAX_BEHAVIORS_SHOWN]]

    classified = pd.DataFrame({
        "entity": list(node_comm.keys()),
        "community_id": [node_comm[n] for n in node_comm],
        "avg_community_activity": [float(prof.loc[prof.community_id == node_comm[n], "avg_total_activity"].iloc[0]) for n in node_comm],
        "tier": [node_tier[n] for n in node_comm],
        "total_activity": [float(totals[n]) for n in node_comm],
    })
    csv_path = None
    if req.out_dir:
        os.makedirs(req.out_dir, exist_ok=True)
        csv_path = os.path.join(req.out_dir, "classified_entities.csv")
        classified.to_csv(csv_path, index=False)

    # graph payload for the front-end (edges capped by weight so huge graphs stay renderable)
    edges = sorted(G.edges(data="weight"), key=lambda e: -e[2])
    truncated = len(edges) > p.max_edges_returned
    edges = edges[: p.max_edges_returned]
    nodes_payload = [{"id": str(n), "community": node_comm[n], "tier": node_tier[n],
                      "total": round(float(totals[n]), 2),
                      "x": round(xy_of[n][0], 4), "y": round(xy_of[n][1], 4)} for n in G.nodes()]

    # macro graph: communities as nodes, edge weight = number of cross-community edges
    cross = Counter()
    for u, v in G.edges():
        a, b = node_comm[u], node_comm[v]
        if a != b:
            cross[tuple(sorted((a, b)))] += 1

    tier_counts = Counter(node_tier.values())

    # ---- NEW: graph density, algorithm comparison, NMI analysis ----
    density = graph_density_metrics(G, sim, ids)
    algo_cmp = algorithm_comparison(results, G)
    nmi_ext = nmi_analysis(results, G, label_map, primary)
    modu = modularity_analysis(results, G, p.random_state)
    primary_density_profile = {r["community_id"]: r for r in community_density_profile(G, comms)}

    return {
        "status": "ok",
        "eligibility": report,
        "summary": {
            "total_entities_in_data": int(n_total),
            "sampled_entities": len(ids),
            "connected_nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "kept_pct_of_sample": round(100 * G.number_of_nodes() / len(ids), 1),
            "communities": len(comms),
            "primary_algorithm": NAMES[primary],
            "graph_method": p.graph_method,
            "threshold": p.threshold if p.graph_method == "threshold" else None,
            "tier_counts": dict(tier_counts),
            "runtime_sec": round(time.time() - t0, 2),
        },
        "similarity": hist,
        "benchmark": bench,
        "communities": [community_row(r, bprof[int(r.community_id)], cstats[int(r.community_id)],
                                      primary_density_profile.get(int(r.community_id), {}))
                        for r in prof.itertuples()],
        "behaviors": [{"name": b, "overall_mean": round(float(overall[b]), 3)} for b in shown],
        "sweep": sweep,
        "pca": {"explained": pca_var},
        "pipeline": pipeline_steps(n_total, len(ids), G, comms, p, tier_counts, primary),
        "graph": {"nodes": nodes_payload,
                  "edges": [{"source": str(u), "target": str(v), "weight": round(w, 4)} for u, v, w in edges],
                  "truncated": truncated},
        "macro_graph": {
            "nodes": [{"id": int(r.community_id), "size": int(r.community_size), "tier": r.tier} for r in prof.itertuples()],
            "edges": [{"source": a, "target": b, "weight": w} for (a, b), w in cross.items()]},
        "diagnostics": diagnostics(prof, report, bool(label_map), bench, primary, tier_counts, p),
        "outputs": {"classified_csv": csv_path},
        # ---- new analytics sections ----
        "graph_metrics": density,
        "algorithm_comparison": algo_cmp,
        "nmi_analysis": nmi_ext,
        "modularity_analysis": modu,
        # community id of every node, per algorithm, in the same order as graph.nodes
        # (lets the UI draw a real community-detection graph for Louvain, Leiden and LPA)
        "partitions": partitions_payload(results, G, bench),
        "has_label": bool(label_map),
    }


def partitions_payload(results: dict, G, bench: list) -> dict:
    """{algorithm: {name, num_communities, modularity, nmi, backend, membership[]}} aligned with G.nodes()."""
    nodes = list(G.nodes())
    info = {b["key"]: b for b in bench if "modularity" in b}
    out = {}
    for key, comms in results.items():
        node_to_c = {n: i for i, c in enumerate(comms) for n in c}
        b = info.get(key, {})
        out[key] = {"name": NAMES[key], "num_communities": len(comms), "modularity": b.get("modularity"),
                    "nmi": b.get("nmi"), "backend": b.get("backend"),
                    "membership": [int(node_to_c[n]) for n in nodes]}
    return out


def community_row(r, profile: dict, stats: dict, density_row: dict = None) -> dict:
    """One community as sent to the UI: size, activity, spread, cohesion and its behavior fingerprint."""
    total_mean = sum(profile.values()) or 1.0
    top = sorted(profile.items(), key=lambda kv: -kv[1])[:3]
    out = {
        "community_id": int(r.community_id), "size": int(r.community_size),
        "avg_total_activity": round(float(r.avg_total_activity), 3),
        "median_total_activity": round(stats["median_total"], 3),
        "std_total_activity": round(stats["std_total"], 3),
        "min_total_activity": round(stats["min_total"], 3),
        "max_total_activity": round(stats["max_total"], 3),
        "cohesion": None if stats["cohesion"] is None else round(stats["cohesion"], 4),
        "top_behavior": r.top_behavior, "tier": r.tier,
        "top_behaviors": [{"name": str(k), "share_pct": round(100 * v / total_mean, 1)} for k, v in top],
        "profile": {str(k): round(float(v), 3) for k, v in profile.items()},
    }
    if density_row:
        out["intra_density"] = density_row.get("intra_density")
        out["conductance"] = density_row.get("conductance")
        out["intra_edges"] = density_row.get("intra_edges")
    return out


def pipeline_steps(n_total, n_sampled, G, comms, p, tier_counts, primary) -> list[dict]:
    """The pipeline in plain language with the real numbers of THIS run (drives the 'how it worked' view)."""
    gm = (f"similarity >= {p.threshold}" if p.graph_method == "threshold"
          else f"each entity linked to its {p.knn_k} most similar")
    return [
        {"key": "matrix", "title": "1. Entity x behavior matrix", "value": n_total,
         "text": f"{n_total:,} entities, one row each; columns are behavior categories; cells are total activity."},
        {"key": "sample", "title": "2. Sample", "value": n_sampled,
         "text": f"{n_sampled:,} entities analysed (seed {p.random_state}); the rest of the data is not scored."},
        {"key": "graph", "title": "3. Similarity graph", "value": G.number_of_nodes(),
         "text": f"Min-max scale, cosine similarity, keep pairs with {gm}: {G.number_of_edges():,} edges. "
                 f"Entities with no edge are dropped."},
        {"key": "communities", "title": "4. Communities", "value": len(comms),
         "text": f"{NAMES[primary]} groups entities that are densely connected to each other."},
        {"key": "tiers", "title": "5. Tiers", "value": len([t for t in tier_counts if t != OUTLIER]),
         "text": "Communities are ranked by average total activity and split into 3 tiers "
                 f"({'equal number of communities per tier' if p.tier_method == 'quantile' else 'custom cut-offs'}). "
                 "Every entity inherits its community's tier."},
    ]


def diagnostics(prof, report, has_labels, bench, primary, tier_counts=None, p=None) -> list[dict]:
    """Plain-language caveats shown in the UI so results are interpreted honestly."""
    out = []
    small = int((prof["community_size"] <= 2).sum())
    if small:
        out.append({"level": "warn", "text": f"{small} community(ies) have 2 or fewer members. "
                    "Tiny groups can skew tiers; consider raising 'min community size'."})
    # does a tiny community sit in an extreme tier? (the weakness visible in the OULAD run)
    if p is not None and p.tier_method == "quantile" and len(prof) >= 3:
        labels = p.tier_labels
        for t in (labels[2], labels[0]):
            members = prof[(prof["tier"] == t)]
            tiny = members[members["community_size"] <= 2]
            if len(tiny):
                out.append({"level": "warn", "text":
                            f"{len(tiny)} tiny community(ies) (<=2 members) landed in the '{t}' tier. "
                            "Tiers are formed from communities, not entities, so a 2-person group counts as much as a 40-person one."})
                break
    if tier_counts and p is not None:
        counts = [tier_counts.get(t, 0) for t in p.tier_labels]
        total = sum(counts) or 1
        if max(counts) / total > 0.6:
            big = p.tier_labels[int(np.argmax(counts))]
            out.append({"level": "info", "text":
                        f"{100 * max(counts) / total:.0f}% of entities fall in '{big}'. Tiers split communities evenly, "
                        "not entities, so entity counts per tier can be very uneven."})
    out.append({"level": "info", "text":
                "Similarity uses cosine on min-max scaled values, so it compares the SHAPE of behavior (what people do), "
                "while tiers use the MAGNITUDE (how much they do). A community can be 'similar' yet differ in volume."})
    row = next((r for r in bench if r.get("key") == primary), None)
    if row and has_labels and row.get("nmi") is not None and row["nmi"] < 0.2:
        out.append({"level": "info", "text": f"NMI vs. the label is low ({row['nmi']:.2f}). Communities group entities by "
                    "behavior pattern, which need not coincide with the label (e.g. final result)."})
    if row and row["modularity"] < 0.3:
        out.append({"level": "warn", "text": "Modularity is below 0.3: the graph has weak community structure. "
                    "Try a different threshold or the kNN graph."})
    out.extend({"level": "warn", "text": w} for w in report.get("warnings", []))
    return out