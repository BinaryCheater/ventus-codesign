"""Extract a bounded set of RTL expressions and source-backed behavior rules.

This is a model input inventory, not an implemented performance predictor.
Expressions remain Scala text; no simulation measurements enter the extraction.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

rtl = Path(sys.argv[1])
output = Path(sys.argv[2])
parameters_path = "ventus/src/top/parameters.scala"
names = set(
    "num_sm num_warp num_thread num_bank num_collectorUnit num_vgpr num_sgpr depth_regBank num_lane num_sfu num_block num_fetch size_ibuffer num_icachebuf lsu_num_entry_each_warp lsu_nMshrEntry dcache_NSets dcache_NWays dcache_BlockWords dcache_wshr_entry dcache_MshrEntry dcache_MshrSubEntry sharedmem_depth sharedmem_BlockWords sharemem_size l2cache_NSets l2cache_NWays l2cache_BlockWords l2cache_writeBytes l2cache_memCycles num_cluster num_sm_in_cluster".split()
)
declarations = []
for number, line in enumerate((rtl / parameters_path).read_text().splitlines(), 1):
    match = re.match(r"\s*(?:def|val|var)\s+(\w+)\s*(?::[^=]+)?=\s*(.+)", line)
    if match and match[1] in names:
        expression = match[2].split("//")[0].strip()
        declarations.append(
            {
                "name": match[1],
                "scala_expression": expression,
                "source": parameters_path,
                "line": number,
            }
        )
assert {x["name"] for x in declarations} == names

# Behavior statements were read from the named implementations; source expressions
# are retained below so that reviews can check each statement independently.
rules = [
    (
        "rf_bank_mapping",
        "ventus/src/pipeline/operandCollector.scala",
        "// bankID = (wid + regIdx) % num_bank",
        "register bank is (warp id + logical register index) modulo num_bank; address also uses per-warp allocated base",
    ),
    (
        "rf_storage",
        "ventus/src/pipeline/regfile.scala",
        "val regs = SyncReadMem(NUMBER_VGPR_SLOTS/num_bank",
        "vector banks have NUMBER_VGPR_SLOTS/num_bank rows of num_thread words; scalar banks use NUMBER_SGPR_SLOTS/num_bank rows",
    ),
    (
        "rf_read_arbitration",
        "ventus/src/pipeline/operandCollector.scala",
        "val x = Module(new RRArbiter(new CU2Arbiter, 4*num_collectorUnit))",
        "round-robin operand requests compete separately per scalar/vector bank",
    ),
    (
        "scalar_alu_output_queue",
        "ventus/src/pipeline/execution.scala",
        "val result=Module(new Queue(new WriteScalarCtrl,1,pipe=true))",
        "scalar ALU has a one-entry pipelined output queue; this stage cannot be removed from timing",
    ),
    (
        "lane_divisibility",
        "ventus/src/pipeline/execution.scala",
        "assert(softThread % hardThread == 0)",
        "vector ALU and MUL process softThread/hardThread groups; derive group sequencing from their send/receive state machines",
    ),
    (
        "fpu_lane_divisibility",
        "dependencies/fpuv2/src/main/scala/FPU.scala",
        "assert(softThread % hardThread == 0)",
        "VectorFPU requires divisibility, softThread>2, hardThread>1; different arithmetic operations use different internal routes",
    ),
    (
        "fpu_add_stage",
        "dependencies/fpuv2/src/main/scala/FMA.scala",
        "override def latency: Int = 1",
        "FADDPipe has one arithmetic stage; its input queues, shared arbitration and outer writeback add further cycles",
    ),
    (
        "sfu_groups",
        "ventus/src/pipeline/execution.scala",
        "val num_grp = num_thread/num_sfu",
        "SFU processes active groups sequentially through num_sfu integer/float division units, then enqueues the vector result",
    ),
    (
        "integer_division_state",
        "ventus/src/pipeline/IntDivMod.scala",
        "val iter = Mux(aLez > dLez, 0.U, dLez - aLez + 1.U)",
        "integer division iterations depend on operand leading zeros; special operands take separate transitions",
    ),
    (
        "lds_bank_count",
        "ventus/src/L1Cache/ShareMem/ShareMemParameters.scala",
        "def NBanks = NLanes",
        "current LDS bank count is tied to lane count; bank index selects word-address bits; changing this tie requires RTL work",
    ),
    (
        "lds_broadcast_absence",
        "ventus/src/L1Cache/ShareMem/BankConflictArbiter.scala",
        "This version cant merge READ req to the same exact addr",
        "same-address reads are serialized in this arbiter; do not introduce a broadcast shortcut without changing the hardware",
    ),
    (
        "cta_resource_pools",
        "ventus/src/cta/resource_table.scala",
        "val handler_vgpr = Seq.fill(NUM_HANDLER)",
        "CTA allocation uses separate LDS, SGPR and VGPR allocation state machines and contiguous resource segments; a minimum of capacity ratios is only an occupancy upper bound",
    ),
    (
        "scalar_writeback_priority",
        "ventus/src/pipeline/writeback.scala",
        "val arbiter_x=Module(new Arbiter(new WriteScalarCtrl(),num_x))",
        "scalar writeback uses fixed-priority arbitration; input ordering determines priority",
    ),
    (
        "vector_writeback_priority",
        "ventus/src/pipeline/writeback.scala",
        "val arbiter_v=Module(new Arbiter(new WriteVecCtrl(),num_v))",
        "vector writeback uses fixed-priority arbitration; retain contention and output backpressure",
    ),
]
behavior = []
source_hashes = {}
for name, source, needle, statement in rules:
    path = rtl / source
    contents = path.read_text()
    lines = contents.splitlines()
    matches = [number for number, line in enumerate(lines, 1) if needle in line]
    assert matches, (name, needle)
    source_hashes[source] = hashlib.sha256(path.read_bytes()).hexdigest()
    behavior.append(
        {
            "name": name,
            "statement": statement,
            "source": source,
            "lines": matches,
            "matched_source": [lines[number - 1].strip() for number in matches],
        }
    )
source_hashes[parameters_path] = hashlib.sha256((rtl / parameters_path).read_bytes()).hexdigest()
result = {
    "scope": "partial source-backed model inputs, not a complete simulator or free-variable count",
    "source_of_parameters": "RTL and its pinned FPUv2 implementation",
    "uses_profiling_or_fitted_parameters": False,
    "declarations": declarations,
    "behavior_rules": behavior,
    "source_sha256": source_hashes,
}
if "--verify" in sys.argv[3:]:
    assert json.loads(output.read_text()) == result
else:
    with output.open("x") as file:
        file.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
