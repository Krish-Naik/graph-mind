"""Run the pipeline on real OULAD data and print the evidence needed to interpret NMI.

Usage (from analysis/):  python tests/oulad_repro.py /path/to/oulad_dir
Needs studentVle.csv, vle.csv and studentInfo.csv in that directory. This is a diagnostic script,
not a test: the OULAD files are not part of the repository.

What to look at
  * summary.graph_construction : how many sampled entities actually made it into the graph
  * evaluation.label_report    : label coverage, and entities with CONFLICTING final_result rows
  * benchmark[*]               : modularity, NMI, AMI and the NMI obtained with shuffled labels
  * stability                  : does the partition change with the random seed?
"""
import sys, json, time
sys.path.insert(0, ".")
from engine.schemas import RunRequest, Mapping, LookupSpec, LabelSpec, Params
from engine import runner

d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/oulad"
mapping = Mapping(path=f"{d}/studentVle.csv", entity_col="id_student", behavior_col="activity_type",
                  value_col="sum_click", agg="sum",
                  lookup=LookupSpec(path=f"{d}/vle.csv", source_key="id_site", lookup_key="id_site"),
                  label=LabelSpec(path=f"{d}/studentInfo.csv", entity_col="id_student", label_col="final_result"))
t = time.time()
res = runner.run(RunRequest(mapping=mapping, params=Params(sample_size=300, threshold=0.85), out_dir="/tmp/out"))
print("status:", res["status"], "| seconds:", round(time.time() - t, 1))
if res["status"] != "ok":
    print(json.dumps({k: v for k, v in res.items() if k not in ("similarity", "sweep")}, indent=1, default=str))
    sys.exit(1)
print("summary:", json.dumps(res["summary"], indent=1))
print("label report:", json.dumps(res["evaluation"]["label_report"], indent=1))
print("evaluation population:", json.dumps(res["evaluation"]["population"], indent=1))
print("benchmark:", json.dumps(res["benchmark"], indent=1))
print("stability:", json.dumps(res["stability"], indent=1))
for c in res["communities"]:
    print(c["community_id"], c["size"], c["top_behavior"], c["tier"])
for dgn in res["diagnostics"]:
    print(f"[{dgn['level']}] {dgn['text']}")