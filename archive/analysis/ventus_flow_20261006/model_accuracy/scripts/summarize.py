"""Compare frozen runs and independently derive an operand-dependent delta."""

import json
import sys
from pathlib import Path

evidence = Path(sys.argv[1])
parameters = json.loads(Path(sys.argv[2]).read_text())
datasets = ["accuracy-pairs", "accuracy-resources", "accuracy-negative", "accuracy-operands"]
results = [
    row
    for dataset in datasets
    for row in json.loads((evidence / dataset / "results.json").read_text())
]
by_case = {}
for row in results:
    by_case.setdefault(row["case"], {})[row["backend"]] = row
for pair in by_case.values():
    assert pair["rtl"]["input_sha256"] == pair["systemc"]["input_sha256"]

increments = []
for family in ["scalar_add", "vector_add", "vector_fadd", "vector_div", "repeat_load"]:
    delta = {}
    for backend in ["rtl", "systemc"]:
        values = {
            n: by_case[f"{family}-{n}"][backend]["dispatch_to_finish_cycles"] for n in [16, 64, 192]
        }
        delta[backend] = values[192] - values[64]
    increments.append(
        {
            "family": family,
            "repeat_count_delta": 128,
            "cycle_increments": delta,
            "relative_difference_percent": 100 * (delta["systemc"] / delta["rtl"] - 1),
        }
    )


# These parameters are generated from the RTL, not inferred from elapsed cycles.
# The iter expression and group sequencing are recorded in source_rules.json.
def division_iterations(a, d, bits):
    a_leading_zeros = bits - a.bit_length()
    d_leading_zeros = bits - d.bit_length()
    return 0 if a_leading_zeros > d_leading_zeros else d_leading_zeros - a_leading_zeros + 1


low = division_iterations(1, 1, parameters["xLen"])
high = division_iterations(0x7FFFFFFF, 1, parameters["xLen"])
assert parameters["num_thread"] % parameters["num_sfu"] == 0
groups = parameters["num_thread"] // parameters["num_sfu"]
predicted_delta = 16 * groups * (high - low)
observed_delta = (
    by_case["div-maxint-by-1"]["rtl"]["dispatch_to_finish_cycles"]
    - by_case["div-1-by-1"]["rtl"]["dispatch_to_finish_cycles"]
)
assert predicted_delta == observed_delta == 1920
assert all(
    row["output_correct"]
    for case in ["div-maxint-by-1", "div-1-by-1"]
    for row in by_case[case].values()
)
summary = {
    "case_count": len(by_case),
    "backend_run_count": len(results),
    "both_backends_output_correct_case_count": sum(
        all(r["output_correct"] for r in pair.values()) for pair in by_case.values()
    ),
    "increments": increments,
    "operand_delta_from_source": {
        "instructions": 16,
        "active_threads": parameters["num_thread"],
        "physical_sfu_lanes": parameters["num_sfu"],
        "groups": groups,
        "low_iterations": low,
        "high_iterations": high,
        "derived_cycles": predicted_delta,
        "observed_rtl_cycles": observed_delta,
        "uses_fitted_parameters": False,
        "scope": "operand-dependent differential for this fixed full-mask dependent division program; not a full-kernel performance model",
    },
    "pairs": by_case,
}
output = evidence / "summary.json"
if "--verify" in sys.argv[3:]:
    assert json.loads(output.read_text()) == summary
else:
    with output.open("x") as file:
        file.write(json.dumps(summary, indent=2) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "pairs"}, indent=2))
