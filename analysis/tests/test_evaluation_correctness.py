"""Correctness tests for community detection, NMI / modularity and label alignment.
Run: pytest -q tests/test_evaluation_correctness.py
"""
import math

import networkx as nx
import networkx.algorithms.community as nx_comm
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import normalized_mutual_info_score

from engine.communities import detect, partition_stability, validate_graph, graph_modularity
from engine.evaluation import canonical_id, canonical_label, evaluate_partition, membership, MIN_EVALUATED
from engine.graph_metrics import graph_density_metrics, modularity_analysis, nmi_analysis
from engine.matrix import build_matrix, load_labels, load_labels_with_report, validate_mapping
from engine.runner import run
from engine.schemas import LabelSpec, LookupSpec, Mapping, Params, RunRequest


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def hand_nmi(a, b):
    """Independent NMI (arithmetic mean normalisation) straight from the contingency table."""
    a, b = list(a), list(b)
    n = len(a)
    ca, cb = sorted(set(a)), sorted(set(b))
    nij = np.array([[sum(1 for x, y in zip(a, b) if x == i and y == j) for j in cb] for i in ca], float)
    pi, pj, pij = nij.sum(1) / n, nij.sum(0) / n, nij / n
    mi = sum(pij[i, j] * math.log(pij[i, j] / (pi[i] * pj[j])) for i in range(len(ca)) for j in range(len(cb)) if pij[i, j] > 0)
    ha = -sum(p * math.log(p) for p in pi if p > 0)
    hb = -sum(p * math.log(p) for p in pj if p > 0)
    if ha == 0 and hb == 0:
        return 1.0
    return mi / ((ha + hb) / 2) if (ha + hb) > 0 else 0.0


def planted(n_groups=4, size=20, p_in=0.5, p_out=0.02, seed=1):
    rng = np.random.default_rng(seed)
    truth = {g * size + i: g for g in range(n_groups) for i in range(size)}
    G = nx.Graph(); G.add_nodes_from(truth)
    for a in truth:
        for b in truth:
            if a < b and rng.random() < (p_in if truth[a] == truth[b] else p_out):
                G.add_edge(a, b, weight=float(0.6 + 0.4 * rng.random()))
    return G, truth


def as_comms(assign: dict):
    out = {}
    for n, c in assign.items():
        out.setdefault(c, set()).add(n)
    return list(out.values())


# ---------------------------------------------------------------------------------------------
# NMI: known values, conventions, comparison with an independent implementation
# ---------------------------------------------------------------------------------------------
def test_nmi_perfect_match_is_one_even_with_different_names_and_order():
    nodes = list(range(12))
    truth = {n: "xyz"[n % 3] for n in nodes}
    comms = as_comms({n: 10 + (n % 3) for n in nodes})                   # same grouping, other ids
    ev = evaluate_partition(comms, dict(reversed(list(truth.items()))), nodes)
    assert ev["available"] and ev["nmi"] == pytest.approx(1.0) and ev["ami"] == pytest.approx(1.0)
    assert ev["coverage"] == 1.0 and ev["n_evaluated"] == 12


def test_nmi_independent_partitions_is_a_genuine_zero_not_unavailable():
    nodes = list(range(16))
    truth = {n: n % 2 for n in nodes}
    comms = as_comms({n: (n // 2) % 2 for n in nodes})                   # crosses the labels evenly
    ev = evaluate_partition(comms, truth, nodes)
    assert ev["available"] is True and ev["nmi"] == pytest.approx(0.0, abs=1e-12)


def test_nmi_partial_overlap_matches_hand_computation():
    nodes = list(range(8))
    truth = {n: "a" if n < 4 else "b" for n in nodes}
    assign = {0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1}          # one node on the wrong side
    ev = evaluate_partition(as_comms(assign), truth, nodes)
    expected = hand_nmi([truth[n] for n in nodes], [assign[n] for n in nodes])
    assert 0.0 < ev["nmi"] < 1.0
    assert ev["nmi"] == pytest.approx(expected, abs=1e-6)


def test_nmi_matches_independent_implementation_and_sklearn_on_random_partitions():
    rng = np.random.default_rng(0)
    for _ in range(25):
        n = int(rng.integers(20, 80))
        y = rng.integers(0, int(rng.integers(2, 5)), n).tolist()
        c = rng.integers(0, int(rng.integers(2, 9)), n).tolist()
        if len(set(y)) < 2:
            continue
        ev = evaluate_partition(as_comms(dict(enumerate(c))), dict(enumerate(y)), range(n), null_permutations=0)
        assert ev["nmi"] == pytest.approx(hand_nmi(y, c), abs=1e-5)
        assert ev["nmi"] == pytest.approx(normalized_mutual_info_score(y, c), abs=1e-5)


def test_alignment_is_by_entity_id_never_by_position():
    G, truth = planted()
    results, _ = detect(G, ["louvain"], 42)
    lab_dict = {n: str(g) for n, g in truth.items()}
    shuffled = dict(sorted(lab_dict.items(), key=lambda kv: (hash(kv[0]) * 7919) % 101))
    as_series = pd.Series(lab_dict).sample(frac=1.0, random_state=3)     # scrambled row order
    nodes = list(G.nodes())
    a = evaluate_partition(results["louvain"], lab_dict, nodes)["nmi"]
    b = evaluate_partition(results["louvain"], shuffled, nodes)["nmi"]
    c = evaluate_partition(results["louvain"], as_series, nodes)["nmi"]
    assert a == b == c and a > 0.8
    # and it is NOT what positional alignment would give if the label order were reversed
    vals = list(lab_dict.values())
    rotated = vals[7:] + vals[:7]                      # what a positional join with a shifted file would see
    wrong = normalized_mutual_info_score(rotated, [membership(results["louvain"])[n] for n in nodes])
    assert wrong < a


def test_unavailable_is_reported_as_none_with_a_reason_code():
    nodes = list(range(20)); comms = as_comms({n: n % 4 for n in nodes})
    assert evaluate_partition(comms, None, nodes)["reason_code"] == "no_labels"
    one_class = evaluate_partition(comms, {n: "same" for n in nodes}, nodes)
    assert one_class["nmi"] is None and one_class["reason_code"] == "single_label_class" and not one_class["available"]
    few = evaluate_partition(comms, {n: n % 2 for n in range(MIN_EVALUATED - 1)}, nodes)
    assert few["nmi"] is None and few["reason_code"] == "too_few_labeled"
    assert evaluate_partition([], {1: "a"}, [1])["reason_code"] == "no_partition"


def test_coverage_counts_missing_labels_and_ignores_labels_of_entities_outside_the_graph():
    nodes = list(range(10)); comms = as_comms({n: n % 2 for n in nodes})
    labels = {n: ("a" if n % 2 else "b") for n in range(6)}              # nodes 6..9 unlabeled
    labels[3] = None; labels[4] = float("nan"); labels[99] = "zzz"        # + missing values + a stranger
    ev = evaluate_partition(comms, labels, nodes)
    assert ev["n_nodes"] == 10 and ev["n_evaluated"] == 4 and ev["coverage"] == 0.4


def test_label_text_nan_is_missing_but_other_null_like_words_are_real_classes():
    assert canonical_label("nan") is None and canonical_label("") is None and canonical_label(None) is None
    assert canonical_label(float("nan")) is None and canonical_label(pd.NA) is None
    assert canonical_label("None") == "None" and canonical_label(" Pass ") == "Pass" and canonical_label(0) == "0"


def test_canonical_id_matches_equivalent_representations():
    assert {canonical_id(x) for x in (7, 7.0, np.int64(7), np.float64(7.0), " 7 ", "7")} == {"7"}
    assert canonical_id("007") == "007" and canonical_id(7.5) == "7.5"


def test_membership_rejects_overlapping_communities():
    with pytest.raises(ValueError, match="more than one community"):
        membership([{1, 2}, {2, 3}])


def test_nmi_is_inflated_by_many_communities_but_ami_and_null_baseline_expose_it():
    """The situation behind a low NMI next to a high modularity: with random labels and many
    communities, NMI is NOT zero; AMI is, and the shuffled-label mean is at the same level as NMI."""
    rng = np.random.default_rng(0)
    n = 300
    labels = {i: str(rng.integers(0, 4)) for i in range(n)}
    comms = as_comms({i: int(rng.integers(0, 40)) for i in range(n)})
    ev = evaluate_partition(comms, labels, range(n), null_permutations=30)
    assert ev["nmi"] > 0.05 and abs(ev["ami"]) < 0.05
    assert abs(ev["nmi"] - ev["nmi_null_mean"]) < 0.05


# ---------------------------------------------------------------------------------------------
# modularity: known values and cross-check with networkx
# ---------------------------------------------------------------------------------------------
def two_triangles():
    G = nx.Graph()
    for a, b in [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5), (2, 3)]:
        G.add_edge(a, b, weight=1.0)
    return G


def test_modularity_two_triangles_with_bridge_is_5_over_14():
    G = two_triangles()
    comms = [{0, 1, 2}, {3, 4, 5}]
    assert graph_modularity(G, comms) == pytest.approx(5 / 14)
    mod = modularity_analysis({"x": comms}, G, n_random=5)["algorithms"][0]
    assert mod["modularity"] == pytest.approx(5 / 14, abs=1e-6)
    assert mod["modularity_networkx"] == pytest.approx(5 / 14, abs=1e-6)


def test_modularity_karate_club_matches_adjacency_matrix_definition():
    """Q = 1/2m * sum_ij (A_ij - k_i k_j / 2m) * [c_i == c_j], computed independently with plain numpy."""
    G = nx.karate_club_graph()
    for u, v in G.edges():
        G[u][v]["weight"] = 1.0
    nodes = list(G)
    comms = [{n for n in G if G.nodes[n]["club"] == c} for c in ("Mr. Hi", "Officer")]
    lab = np.array([0 if G.nodes[n]["club"] == "Mr. Hi" else 1 for n in nodes])
    A = nx.to_numpy_array(G, nodelist=nodes); k = A.sum(1); two_m = A.sum()
    q_def = sum(A[i, j] - k[i] * k[j] / two_m for i in range(34) for j in range(34) if lab[i] == lab[j]) / two_m
    out = modularity_analysis({"k": comms}, G, n_random=3)["algorithms"][0]
    assert out["modularity"] == pytest.approx(q_def, abs=1e-6) == pytest.approx(0.358235, abs=1e-6)
    assert graph_modularity(G, comms) == pytest.approx(q_def, abs=1e-9)


def test_custom_modularity_equals_networkx_on_random_weighted_graphs_and_partitions():
    rng = np.random.default_rng(7)
    for seed in range(5):
        G = nx.gnp_random_graph(40, 0.15, seed=seed)
        for u, v in G.edges():
            G[u][v]["weight"] = float(rng.uniform(0.1, 1.0))
        G.remove_nodes_from(list(nx.isolates(G)))
        nodes = list(G.nodes()); k = int(rng.integers(2, 6))
        comms = as_comms({n: int(rng.integers(0, k)) for n in nodes})
        out = modularity_analysis({"r": comms}, G, n_random=2)["algorithms"][0]
        assert out["modularity"] == pytest.approx(nx_comm.modularity(G, comms, weight="weight"), abs=1e-5)


def test_modularity_with_isolated_nodes_equals_modularity_without_them():
    G = two_triangles(); comms = [{0, 1, 2}, {3, 4, 5}]
    G2 = G.copy(); G2.add_nodes_from([90, 91])
    assert graph_modularity(G2, comms + [{90}, {91}]) == pytest.approx(graph_modularity(G, comms))


def test_modularity_is_undefined_not_zero_on_graphs_without_edges():
    G = nx.Graph(); G.add_nodes_from(range(4))
    assert graph_modularity(G, [{0}, {1}, {2}, {3}]) is None
    assert modularity_analysis({"x": [{0}, {1}, {2}, {3}]}, G) == {"available": False}
    results, rows = detect(G, ["louvain", "leiden", "lpa"], 1)
    assert all(len(c) == 1 for comms in results.values() for c in comms)
    assert all(r["modularity"] is None for r in rows)


# ---------------------------------------------------------------------------------------------
# community detection behaviour
# ---------------------------------------------------------------------------------------------
def test_disconnected_cliques_are_separated_and_isolated_nodes_stay_singletons():
    G = nx.Graph()
    for block in (range(0, 5), range(5, 10)):
        for a in block:
            for b in block:
                if a < b:
                    G.add_edge(a, b, weight=0.9)
    G.add_node(99)
    results, rows = detect(G, ["louvain", "leiden", "lpa"], 3)
    for name, comms in results.items():
        got = {frozenset(c) for c in comms}
        assert frozenset(range(5)) in got and frozenset(range(5, 10)) in got and frozenset({99}) in got, name
    assert all(r["modularity"] == pytest.approx(0.5) for r in rows)


def test_single_node_pendant_community_is_handled():
    G = two_triangles(); G.add_edge(5, 6, weight=0.01)
    results, rows = detect(G, ["louvain"], 1)
    assert sum(len(c) for c in results["louvain"]) == 7 and rows[0]["modularity"] is not None


def test_same_seed_is_deterministic_and_louvain_is_stable_across_seeds_on_clear_structure():
    G, _ = planted()
    a, _ = detect(G, ["louvain", "lpa"], 42); b, _ = detect(G, ["louvain", "lpa"], 42)
    for k in a:
        assert {frozenset(c) for c in a[k]} == {frozenset(c) for c in b[k]}
    st = partition_stability(G, "louvain", n_runs=6, seed=1)
    assert st["available"] and st["pairwise_nmi_mean"] > 0.95 and st["modularity_std"] < 0.02
    assert partition_stability(G, "louvain", n_runs=1)["available"] is False
    assert partition_stability(nx.empty_graph(3), "louvain", n_runs=5)["available"] is False


def test_invalid_edge_weights_are_rejected_before_detection():
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        G = nx.Graph(); G.add_edge(0, 1, weight=bad); G.add_edge(1, 2, weight=1.0)
        with pytest.raises(ValueError, match="invalid weight"):
            validate_graph(G)
        with pytest.raises(ValueError):
            detect(G, ["louvain"], 1)
    with pytest.raises(ValueError, match="undirected"):
        validate_graph(nx.DiGraph([(0, 1)]))


def test_weights_change_the_partition():
    """Louvain must honour weights: a heavy bridge pair outweighs light intra-group edges."""
    G = nx.Graph()
    for a, b in [(0, 1), (2, 3)]:
        G.add_edge(a, b, weight=1.0)
    G.add_edge(1, 2, weight=0.01)
    comms = detect(G, ["louvain"], 1)[0]["louvain"]
    assert {frozenset(c) for c in comms} == {frozenset({0, 1}), frozenset({2, 3})}


def test_betweenness_is_hop_based_not_similarity_as_distance():
    G = nx.Graph()
    G.add_edge(0, 2, weight=0.99); G.add_edge(0, 1, weight=0.10); G.add_edge(1, 2, weight=0.10)
    m = graph_density_metrics(G, None, [0, 1, 2])
    assert m["max_betweenness"] == 0.0        # 0-2 are directly linked; node 1 lies on no shortest path


def test_density_metrics_are_strict_json_even_for_regular_graphs():
    import json
    G = nx.complete_graph(5)
    for u, v in G.edges():
        G[u][v]["weight"] = 0.9
    m = graph_density_metrics(G, None, list(G))
    assert m["assortativity"] is None                       # undefined, not NaN
    json.dumps(m, allow_nan=False)                          # what FastAPI's JSONResponse enforces


def test_nmi_analysis_reports_coverage_and_chance_baselines():
    G, truth = planted()
    results, _ = detect(G, ["louvain", "leiden", "lpa"], 42)
    labels = {n: str(g) for n, g in truth.items() if n % 5}                # 20% unlabeled
    out = nmi_analysis(results, G, labels, "louvain")
    assert out["available"] and out["coverage"]["graph_nodes"] == 80 and out["coverage"]["evaluated"] == 64
    assert out["coverage"]["missing_label"] == 16 and out["coverage"]["coverage"] == 0.8
    assert set(out["ami_by_algorithm"]) == {"louvain", "leiden", "lpa"}
    assert out["nmi_by_algorithm"]["louvain"] > 0.7 > out["nmi_null_by_algorithm"]["louvain"] + 0.4
    assert nmi_analysis(results, G, {n: "same" for n in G})["reason_code"] == "single_label_class"
    assert nmi_analysis(results, G, {})["reason_code"] == "too_few_labeled"


def test_benchmark_row_distinguishes_zero_from_unavailable():
    G, truth = planted()
    _, rows = detect(G, ["louvain"], 42, {n: "same" for n in G})
    assert rows[0]["nmi"] is None and "ONE label class" in rows[0]["nmi_reason"]
    _, rows = detect(G, ["louvain"], 42, None)
    assert rows[0]["nmi"] is None and rows[0]["nmi_coverage"] is None
    _, rows = detect(G, ["louvain"], 42, {n: str(g) for n, g in truth.items()})
    assert rows[0]["nmi"] > 0.9 and rows[0]["nmi_coverage"] == 1.0


# ---------------------------------------------------------------------------------------------
# label loading / alignment (DuckDB) and leakage
# ---------------------------------------------------------------------------------------------
def label_mapping(tmp_path, **kw):
    return Mapping(path=str(tmp_path / "x.csv"), entity_col="id_student",
                   label=LabelSpec(path=str(tmp_path / "info.csv"), entity_col="id_student", label_col="final_result"), **kw)


def test_conflicting_duplicate_labels_are_ambiguous_not_arbitrary(tmp_path):
    pd.DataFrame({"id_student": [1, 1, 2, 3, 3, 3, 4, 5, 5],
                  "final_result": ["Pass", "Fail", "Pass", "Withdrawn", "Pass", "Fail", "Pass", "Pass", "Pass"]}
                 ).to_csv(tmp_path / "info.csv", index=False)
    s, rep = load_labels_with_report(label_mapping(tmp_path), pd.Index([1, 2, 3, 4, 5, 6]))
    assert s[2] == "Pass" and s[4] == "Pass" and s[5] == "Pass"           # 5: repeated but consistent
    assert s[1] is None and s[3] is None and s[6] is None                  # conflicting / absent: no label
    assert rep["entities_labeled"] == 3 and rep["entities_ambiguous"] == 2
    assert rep["entities_not_in_label_file"] == 1 and rep["label_file_entities_repeated_but_consistent"] == 1
    assert set(rep["ambiguous_examples"]) == {"1", "3"}


def test_label_alignment_ignores_file_order_and_matches_equivalent_id_types(tmp_path):
    pd.DataFrame({"id_student": [3.0, 1.0, 2.0], "final_result": ["c", "a", "b"]}).to_csv(tmp_path / "info.csv", index=False)
    s = load_labels(label_mapping(tmp_path), pd.Index([1, 2, 3, 4]))
    assert s[1] == "a" and s[2] == "b" and s[3] == "c" and s[4] is None
    assert s.index.tolist() == [1, 2, 3, 4]                                # result follows the REQUESTED order


def test_missing_label_values_are_not_classes(tmp_path):
    pd.DataFrame({"id_student": [1, 2, 3], "final_result": ["a", None, "b"]}).to_csv(tmp_path / "info.csv", index=False)
    s, rep = load_labels_with_report(label_mapping(tmp_path), pd.Index([1, 2, 3]))
    assert s[2] is None and rep["entities_in_file_without_label_value"] == 1 and rep["entities_labeled"] == 2


def test_no_match_at_all_is_flagged(tmp_path):
    pd.DataFrame({"id_student": ["x1", "x2"], "final_result": ["a", "b"]}).to_csv(tmp_path / "info.csv", index=False)
    s, rep = load_labels_with_report(label_mapping(tmp_path), pd.Index([1, 2]))
    assert rep["entities_labeled"] == 0 and "warning" in rep


def test_label_file_columns_are_validated(tmp_path):
    import duckdb
    pd.DataFrame({"id_student": [1], "other": ["a"]}).to_csv(tmp_path / "info.csv", index=False)
    pd.DataFrame({"id_student": [1, 2], "a": [1, 2], "b": [2, 1]}).to_csv(tmp_path / "x.csv", index=False)
    m = Mapping(path=str(tmp_path / "x.csv"), format="wide", entity_col="id_student", feature_cols=["a", "b"],
                label=LabelSpec(path=str(tmp_path / "info.csv"), entity_col="id_student", label_col="final_result"))
    with pytest.raises(ValueError, match="final_result"):
        validate_mapping(duckdb.connect(), m)


def test_label_used_as_feature_is_rejected_as_leakage(tmp_path):
    import duckdb
    pd.DataFrame({"id": range(40), "a": range(40), "b": range(40, 0, -1), "grp": [i % 3 for i in range(40)]}
                 ).to_csv(tmp_path / "w.csv", index=False)
    lab = LabelSpec(path=str(tmp_path / "w.csv"), entity_col="id", label_col="grp")
    wide = Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=["a", "b", "grp"], label=lab)
    with pytest.raises(ValueError, match="leakage"):
        validate_mapping(duckdb.connect(), wide)
    with pytest.raises(ValueError, match="leakage"):
        build_matrix(wide)
    long_same = Mapping(path=str(tmp_path / "w.csv"), entity_col="id", behavior_col="grp", value_col="a", label=lab)
    with pytest.raises(ValueError, match="leakage"):
        validate_mapping(duckdb.connect(), long_same)
    ok = Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=["a", "b"], label=lab)
    validate_mapping(duckdb.connect(), ok)                                 # label in same file but NOT a feature: fine
    same_col = LabelSpec(path=str(tmp_path / "w.csv"), entity_col="id", label_col="id")
    with pytest.raises(ValueError, match="same column"):
        validate_mapping(duckdb.connect(), Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id",
                                                   feature_cols=["a", "b"], label=same_col))


# ---------------------------------------------------------------------------------------------
# end-to-end pipeline
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def archetypes(tmp_path):
    """3 behavior archetypes x 50 entities (long event log + lookup + label file)."""
    rng = np.random.default_rng(0)
    rows, lab = [], []
    protos = {"A": [50, 4, 2, 1], "B": [2, 40, 3, 1], "C": [1, 2, 30, 20]}
    for g, (name, base) in enumerate(protos.items()):
        for i in range(50):
            uid = g * 1000 + i
            lab.append((uid, name))
            for site, b in enumerate(base):
                rows.append((uid, site, max(1, int(rng.normal(b, 0.15 * b + 1)))))
    pd.DataFrame(rows, columns=["uid", "site_id", "clicks"]).to_csv(tmp_path / "log.csv", index=False)
    pd.DataFrame({"site_id": range(4), "kind": ["video", "forum", "quiz", "home"]}).to_csv(tmp_path / "sites.csv", index=False)
    pd.DataFrame(lab, columns=["uid", "grp"]).to_csv(tmp_path / "labels.csv", index=False)
    return tmp_path


def mp(d, label=True, label_file="labels.csv"):
    return Mapping(path=str(d / "log.csv"), entity_col="uid", behavior_col="kind", value_col="clicks",
                   lookup=LookupSpec(path=str(d / "sites.csv"), source_key="site_id", lookup_key="site_id"),
                   label=LabelSpec(path=str(d / label_file), entity_col="uid", label_col="grp") if label else None)


PARAMS = Params(sample_size=None, threshold=0.95, algorithms=["louvain"], stability_runs=4)


def test_labels_never_influence_graph_or_partition(archetypes):
    with_lab = run(RunRequest(mapping=mp(archetypes, True), params=PARAMS))
    no_lab = run(RunRequest(mapping=mp(archetypes, False), params=PARAMS))
    assert with_lab["status"] == no_lab["status"] == "ok"
    assert with_lab["graph"]["nodes"] == no_lab["graph"]["nodes"]
    assert with_lab["graph"]["edges"] == no_lab["graph"]["edges"]
    assert with_lab["partitions"]["louvain"]["membership"] == no_lab["partitions"]["louvain"]["membership"]
    assert no_lab["has_label"] is False and no_lab["evaluation"]["primary"]["reason_code"] == "no_labels"
    assert no_lab["benchmark"][0]["nmi"] is None


def test_end_to_end_nmi_equals_independent_id_join(archetypes):
    res = run(RunRequest(mapping=mp(archetypes), params=PARAMS))
    lab = pd.read_csv(archetypes / "labels.csv").set_index("uid")["grp"]
    ids = [int(n["id"]) for n in res["graph"]["nodes"]]
    member = res["partitions"]["louvain"]["membership"]
    expected = normalized_mutual_info_score([lab[i] for i in ids], member)
    assert res["benchmark"][0]["nmi"] == pytest.approx(expected, abs=1e-5)
    assert expected > 0.9                                                  # real structure -> NMI really is high
    ev = res["evaluation"]
    assert ev["population"]["evaluated"] == len(ids) and ev["population"]["coverage"] == 1.0


def test_partial_and_ambiguous_labels_are_counted_on_a_common_population(archetypes):
    lab = pd.read_csv(archetypes / "labels.csv")
    keep = lab[lab.uid % 5 != 0]                                           # drop 20% of the entities
    dup = pd.DataFrame({"uid": [1, 1001], "grp": ["B", "C"]})              # conflicting rows for 2 entities
    pd.concat([keep, dup]).sample(frac=1, random_state=1).to_csv(archetypes / "partial.csv", index=False)
    res = run(RunRequest(mapping=mp(archetypes, label_file="partial.csv"), params=PARAMS))
    rep, pop = res["evaluation"]["label_report"], res["evaluation"]["population"]
    assert rep["entities_ambiguous"] == 2 and rep["label_file_entities_with_conflicting_labels"] == 2
    n_graph = res["summary"]["connected_nodes"]
    unlabeled = len([n for n in res["graph"]["nodes"] if int(n["id"]) % 5 == 0 or int(n["id"]) in (1, 1001)])
    assert pop["graph_entities"] == n_graph and pop["evaluated"] == n_graph - unlabeled
    assert pop["coverage"] == pytest.approx((n_graph - unlabeled) / n_graph, abs=1e-3)
    assert res["benchmark"][0]["nmi_evaluated"] == pop["evaluated"]
    assert any("conflicting labels" in d["text"] for d in res["diagnostics"])


def test_random_labels_give_chance_level_nmi_and_ami_near_zero(archetypes):
    lab = pd.read_csv(archetypes / "labels.csv")
    lab["grp"] = np.random.default_rng(1).permutation(lab["grp"].values)
    lab.to_csv(archetypes / "shuffled.csv", index=False)
    res = run(RunRequest(mapping=mp(archetypes, label_file="shuffled.csv"), params=PARAMS))
    row = res["benchmark"][0]
    assert row["nmi"] < 0.15 and abs(row["ami"]) < 0.1                     # a genuine (not a buggy) low NMI
    assert res["summary"]["connected_nodes"] > 100 and row["modularity"] > 0.4   # ...even with real graph structure


def test_full_payload_is_strict_json_with_and_without_labels(archetypes):
    import json
    for with_label in (True, False):
        res = run(RunRequest(mapping=mp(archetypes, with_label), params=Params(sample_size=None, threshold=0.95)))
        json.dumps(res, allow_nan=False)              # FastAPI refuses NaN / Infinity


def test_run_is_reproducible_and_reports_stability(archetypes):
    a = run(RunRequest(mapping=mp(archetypes), params=PARAMS))
    b = run(RunRequest(mapping=mp(archetypes), params=PARAMS))
    assert a["partitions"] == b["partitions"] and a["benchmark"] == b["benchmark"]
    assert a["stability"]["available"] and a["stability"]["runs"] == 4
    off = run(RunRequest(mapping=mp(archetypes), params=Params(sample_size=None, threshold=0.95, stability_runs=0)))
    assert off["stability"] == {"available": False}


def test_too_high_threshold_gives_empty_graph_with_a_suggested_threshold(tmp_path):
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.random((60, 5)), columns=list("abcde")); df.insert(0, "id", range(60))
    df.to_csv(tmp_path / "w.csv", index=False)
    m = Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=list("abcde"))
    res = run(RunRequest(mapping=m, params=Params(sample_size=None, threshold=1.0)))
    assert res["status"] == "empty_graph" and res["graph_construction"]["entities_in_graph"] == 0
    assert res["suggested_threshold"] is not None and "threshold of about" in res["message"]
    ok = run(RunRequest(mapping=m, params=Params(sample_size=None, threshold=res["suggested_threshold"])))
    assert ok["status"] == "ok" and ok["summary"]["kept_pct_of_sample"] >= 90


def test_summary_reports_what_graph_construction_dropped(tmp_path):
    rng = np.random.default_rng(0)
    X = rng.random((60, 4)); X[:6] = 0                                    # 6 identical zero-activity entities
    df = pd.DataFrame(X, columns=list("abcd")); df.insert(0, "id", range(60)); df.to_csv(tmp_path / "w.csv", index=False)
    m = Mapping(path=str(tmp_path / "w.csv"), format="wide", entity_col="id", feature_cols=list("abcd"))
    res = run(RunRequest(mapping=m, params=Params(sample_size=None, graph_method="knn", knn_k=5, algorithms=["louvain"])))
    gc = res["summary"]["graph_construction"]
    assert res["status"] == "ok" and gc["dropped_no_positive_similarity"] >= 6
    assert res["summary"]["dropped_entities"] == gc["entities_dropped"]
    assert res["summary"]["connected_nodes"] + res["summary"]["dropped_entities"] == res["summary"]["sampled_entities"]
    assert any("zero vector" in w or "minimum value in every behavior" in w for w in res["eligibility"]["warnings"])