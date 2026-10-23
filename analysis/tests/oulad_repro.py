"""Reproduce the notebook on real OULAD data. Usage: python tests/oulad_repro.py /path/to/oulad_dir"""
import sys, json, time
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
print(json.dumps(res["summary"], indent=1))
print("benchmark:", json.dumps(res["benchmark"], indent=1))
for c in res["communities"]:
    print(c)
print("diagnostics:", res["diagnostics"])
