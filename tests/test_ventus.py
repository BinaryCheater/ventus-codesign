"""Independent timing/resource contracts for the experimental Ventus model."""

from dataclasses import replace

import pytest

from codesign.ventus.__main__ import read_candidate
from codesign.ventus.coalescer import shared_service_intervals
from codesign.ventus.config import Hardware
from codesign.ventus.graph import TimingGraph, execute
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.mip import Candidate, optimize
from codesign.ventus.program import fp32_word, packed_gemm
from codesign.ventus.timing import build_graph, simulate
from codesign.ventus.workloads import chain, gemm


@pytest.mark.parametrize("steps", [1, 7, 24, 32])
def test_executable_gemm_against_dense_reference(steps):
    import struct

    import numpy as np

    program = packed_gemm(steps)
    decode = lambda words: np.array(  # noqa: E731
        [struct.unpack("<f", struct.pack("<I", word))[0] for word in words]
    ).reshape(steps, 4, 8)
    # Reconstruct full matrices from emitted input buffers, independently of IR.
    a = np.concatenate(list(decode(program.panels_a)), axis=1)
    b = np.concatenate(list(decode(program.panels_b)), axis=1).T
    expected = tuple(fp32_word(x) for x in (a @ b).ravel()) + (0,) * 16
    assert program.expected == expected
    for strategy in ["reload", "resident", "shared"]:
        assert packed_gemm(steps, strategy=strategy).expected == expected


@pytest.mark.parametrize(
    "strategy,steps,conflict,stride,rtl_compute,rtl_visible",
    [
        ("stream", 4, False, 1, 192, 220),
        ("stream", 16, False, 1, 624, 652),
        ("resident", 16, False, 1, 320, 348),
        ("resident", 16, True, 1, 352, 380),
        ("shared", 4, False, 1, 304, 332),
        ("shared", 4, False, 4, 361, 389),
    ],
)
def test_mixed_program_rtl_timing_regression(
    strategy, steps, conflict, stride, rtl_compute, rtl_visible
):
    # Independent original-DUT observations, kernel-warm-v3. Full mixed spans,
    # starting at collector admission; launch/reset sweeps are separate.
    program = packed_gemm(steps, strategy=strategy, rf_conflict=conflict, lds_stride=stride)
    graph = build_graph(program.workload, Hardware())
    result = execute(graph)
    predicted = result["times"][graph.names.index(f"pc{program.final_tensor_pc:08x}.writeback")]
    visible = result["times"][graph.names.index("outputs.visible")]
    assert abs(predicted / rtl_compute - 1) <= 0.04
    assert abs(visible / rtl_visible - 1) <= 0.04


def test_global_write_miss_reads_but_does_not_allocate_l2_tag():
    work = Workload(
        (
            Operation("store", "store", sources=("v1",), addresses=(0x90000000,)),
            Operation(
                "load", "load", destination="v2", addresses=(0x90000000,), dependencies=("store",)
            ),
        )
    )
    graph = build_graph(work, Hardware())
    result = execute(graph)
    assert result["counters"]["l2_miss"] == 2
    assert result["counters"]["memory_read_bytes"] == 256
    # Local acknowledgement must not be confused with final output visibility.
    assert (
        result["times"][graph.names.index("store.memory.done")]
        < result["times"][graph.names.index("outputs.visible")]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sms", 0),
        ("sms", True),
        ("memory_latency", float("nan")),
        ("rf_banks", 3),
        ("tensor_n", 3),
        ("tensor_m", 32),
        ("vgpr_slots", 1025),
        ("line_bytes", 64),
        ("blocks_per_sm", 9),
    ],
)
def test_invalid_hardware(field, value):
    with pytest.raises(ValueError):
        replace(Hardware(), **{field: value}).validate()


def test_tensor_structure_and_unbinding():
    h = Hardware().validate()
    assert h.tensor_latency == 12
    assert h.tensor_flops_per_instruction == 256
    assert h.rtl_bindings() == {}
    smaller = h.with_changes(tensor_n=4)
    assert smaller.tensor_latency == 10
    assert smaller.tensor_flops_per_instruction == 128
    assert smaller.rtl_bindings()["tensor_n"] == {"model": 4, "rtl": 8}


def test_register_read_ports_are_real_timing_inputs():
    work = chain("tensor", 9, conflicts=True)
    hw = Hardware().with_changes(rf_read_ports=2)
    assert simulate(work, hw)["cycles"] == 9 * 17 - 1
    assert "rf_read_ports" in hw.rtl_bindings()


@pytest.mark.parametrize(
    "kind,conflict,period",
    [
        ("scalar", False, 5),
        ("vector", False, 5),
        ("fadd", False, 7),
        ("tensor", False, 16),
        ("tensor", True, 18),
    ],
)
def test_source_pipeline_chain(kind, conflict, period):
    # Absolute segment span follows the independently derived stage recurrence.
    result = simulate(chain(kind, 9, conflicts=conflict), Hardware())
    assert result["cycles"] == 9 * period - 1


@pytest.mark.parametrize("conflict", [1, 2, 4, 8, 16, 32])
def test_lds_no_broadcast_and_bank_rounds(conflict):
    result = simulate(chain("load", 5, lds_conflict=conflict), Hardware())
    assert result["counters"]["lds_rounds"] == 5 * conflict
    assert result["cycles"] == 5 * (10 + conflict) - 1


def test_shared_coalescer_control_and_saturated_service():
    assert shared_service_intervals(8) == (4,)
    work = chain("load", 64).operations
    from dataclasses import replace

    def duration(count):
        operations = tuple(
            replace(op, name=f"w{warp}.{op.name}", warp=warp)
            for op in work[:count]
            for warp in range(8)
        )
        return simulate(Workload(operations, warps_per_block=8), Hardware())["cycles"]

    # Fresh RTL's 48 extra iterations: eight requests per iteration, four cycles each.
    assert duration(64) - duration(16) == 48 * 8 * 4


def loads(addresses):
    return Workload(
        tuple(
            Operation(f"load{i}", "load", sources=("v10",), destination="v1", addresses=(a,))
            for i, a in enumerate(addresses)
        )
    )


def test_finite_l1_and_retained_l2():
    hw = Hardware().with_changes(l1_sets=1, l1_ways=1, l2_sets=8, l2_ways=2)
    result = simulate(loads([0x90000000, 0x90000200, 0x90000000]), hw)
    assert result["counters"]["l1_read_miss"] == 3
    assert result["counters"]["l2_miss"] == 2
    assert result["counters"]["l2_hit"] == 1
    assert result["counters"]["memory_read_bytes"] == 256


def test_repeated_load_hits_and_coalescing():
    result = simulate(loads([0x90000000] * 4), Hardware())
    assert result["counters"]["l1_read_miss"] == 1
    assert result["counters"]["l1_hit"] == 3
    wide = Workload(
        (
            Operation(
                "wide",
                "load",
                destination="v1",
                addresses=tuple(0x90000000 + i * 4 for i in range(32)),
            ),
        )
    )
    scattered = Workload(
        (replace(wide.operations[0], addresses=tuple(0x90000000 + i * 128 for i in range(32))),)
    )
    assert simulate(wide, Hardware())["counters"]["memory_read_bytes"] == 128
    assert simulate(scattered, Hardware())["counters"]["memory_read_bytes"] == 4096


def test_early_compute_can_write_back_before_older_cache_miss():
    work = Workload(
        (
            Operation("load", "load", sources=("v10",), destination="v1", addresses=(0x90000000,)),
            Operation("advance", "vector", sources=("v10", "x6"), destination="v10"),
        )
    )
    graph = build_graph(work, Hardware())
    result = execute(graph)
    times = dict(zip(graph.names, result["times"], strict=True))
    assert times["advance.writeback"] < times["load.writeback"]


def test_public_candidate_defaults_and_override_validation():
    raw = {
        "workload": {
            "operations": [
                {"name": "a", "kind": "tensor", "sources": ["v1", "v2", "v3"], "destination": "v1"}
            ]
        }
    }
    candidate = read_candidate(raw)
    assert simulate(candidate.workload, candidate.hardware)["cycles"] == 15
    raw["hardware"] = {"rf_banks": 3}
    with pytest.raises(ValueError, match="power of two"):
        read_candidate(raw)


def test_dirty_eviction_and_draining():
    operations = [
        Operation("read", "load", destination="v1", addresses=(0x90000000,)),
        Operation("write", "store", sources=("v1",), addresses=(0x90000000,)),
        Operation("evict", "load", destination="v1", addresses=(0x90000100,)),
    ]
    result = simulate(Workload(tuple(operations)), Hardware().with_changes(l1_sets=1, l1_ways=1))
    assert result["counters"]["memory_write_bytes"] == 128


def test_capacity_and_explicit_dependency_validation():
    with pytest.raises(ValueError, match="does not fit"):
        Workload(chain("tensor", 1).operations, lds_per_block=999999).validate(Hardware())
    with pytest.raises(ValueError, match="precede"):
        Workload((Operation("a", "vector", dependencies=("b",)),)).validate(Hardware())
    with pytest.raises(ValueError, match="aligned"):
        loads([3]).validate(Hardware())
    with pytest.raises(ValueError, match="unsupported"):
        Workload((Operation("div", "division"),)).validate(Hardware())


def test_small_graph_longest_path_and_mip():
    graph = TimingGraph()
    a = graph.node("a", [(0, 3)])
    b = graph.node("b", [(0, 7)])
    graph.terminal = graph.node("join", [(a, 8), (b, 2)])
    assert execute(graph)["cycles"] == 11
    hw = Hardware()
    menu = [
        Candidate("baseline", hw, chain("tensor", 7)),
        Candidate("smaller", hw.with_changes(tensor_n=4), chain("tensor", 7)),
        Candidate("conflicts", hw, chain("tensor", 7, conflicts=True)),
    ]
    exhaustive = {c.name: simulate(c.workload, c.hardware)["cycles"] for c in menu}
    selected = optimize(menu, budgets=hw.resources())
    assert selected["optimal"]
    assert selected["cycles"] == min(exhaustive.values()) == 97
    assert selected["candidate"] == "smaller"
    assert selected["objective_bound"] == selected["cycles"]


def test_mip_resource_budget_filters_fast_hardware():
    hw = Hardware()
    menu = [
        Candidate("two_sm", hw, chain("tensor", 4)),
        Candidate("one_sm", hw.with_changes(sms=1), chain("tensor", 4)),
    ]
    selected = optimize(
        menu, budgets={"storage_bytes": hw.with_changes(sms=1).resources()["storage_bytes"]}
    )
    assert selected["candidate"] == "one_sm"
    assert optimize(menu, budgets={"storage_bytes": 1})["candidate"] is None


@pytest.mark.parametrize("shape", [(8, 8, 16), (8, 16, 32), (16, 8, 16)])
def test_gemm_menu_mip_matches_independent_enumeration(shape):
    hw = Hardware()
    menu = [
        Candidate(
            f"w{w}-b{t}", hw, gemm(hw, m=shape[0], n=shape[1], k=shape[2], warps=w, transpose_b=t)
        )
        for w in [1, 2]
        for t in [False, True]
    ]
    best = min(simulate(c.workload, c.hardware)["cycles"] for c in menu)
    result = optimize(menu, budgets=hw.resources())
    assert result["optimal"] and result["cycles"] == best


def test_relu_uses_source_compare_pipeline():
    # FCMP has two pipeline registers; unlike FADD, no FMA output queue.
    work = Workload((Operation("relu", "fmax", sources=("v1", "v2"), destination="v1"),))
    graph = build_graph(work, Hardware())
    times = dict(zip(graph.names, execute(graph)["times"], strict=True))
    assert times["relu.writeback"] - times["relu.issue"] == 2


@pytest.mark.parametrize("depth,hidden", [(8, 8), (16, 16), (24, 8), (32, 16)])
def test_ffn_tensor_packing_and_intermediate_lifetime(depth, hidden):
    from codesign.ventus.operators import fused_operator, reference
    from codesign.ventus.program import fp32_word

    lds = fused_operator(depth=depth, hidden=hidden, residual=True)
    global_mem = fused_operator(depth=depth, hidden=hidden, residual=True, intermediate="global")
    x, w1, bias1, h, w2, bias2, skip, expected = reference(depth, hidden, True, 1)
    # Reconstruct all first/second Tensor inputs from emitted constant buffers;
    # scatter destinations must provide every intermediate load element.
    pa, pb = lds.program.panels_a, lds.program.panels_b
    ops = lds.program.workload.operations
    stores, seen = [], set()
    tensors = 0
    first_a, first_b = [], []
    for op in ops:
        if op.kind == "load" and op.destination == "v2" and op.addresses[0] >= 0x90000000:
            pos = (op.addresses[0] - 0x90000000) // 4
            first_a.append(pa[pos : pos + 32])
        if op.kind == "load" and op.destination == "v3":
            pos = (op.addresses[0] - 0x90001000) // 4
            first_b.append(pb[pos : pos + 32])
        if op.kind == "tensor":
            tensors += 1
        if op.kind == "store" and 0x70000000 <= op.addresses[0] < 0x80000000:
            stores.append(op)
            assert not (seen & set(op.addresses))
            seen.update(op.addresses)
        if op.kind == "load" and 0x70000000 <= op.addresses[0] < 0x80000000:
            assert set(op.addresses) <= seen
    assert len(stores) == hidden // 4
    assert tensors == hidden // 4 * (depth // 8) + hidden // 8
    expected_a, expected_b = [], []
    for col in range(0, hidden, 4):
        for start in range(0, depth, 8):
            expected_a.append(
                tuple(fp32_word(x[r][k]) for r in range(4) for k in range(start, start + 8))
            )
            expected_b.append(
                tuple(
                    fp32_word(w1[k][j])
                    for j in range(col, col + 4)
                    for k in range(start, start + 8)
                )
            )
    for start in range(0, hidden, 8):
        expected_b.append(
            tuple(fp32_word(w2[k][j]) for j in range(4) for k in range(start, start + 8))
        )
    assert first_a == expected_a
    assert first_b == expected_b
    assert any(v == 0 for row in h for v in row)
    assert any(v > 0 for row in h for v in row)
    assert (
        lds.program.expected
        == global_mem.program.expected
        == tuple(fp32_word(v) for row in expected for v in row) + (0,) * 16
    )
    assert lds.stages[-1][0] == "residual"


@pytest.mark.parametrize(
    "config", [dict(depth=7), dict(hidden=4), dict(kind="epilogue", hidden=8), dict(seed=-1)]
)
def test_complex_operator_rejects_invalid_public_config(config):
    from codesign.ventus.operators import fused_operator

    with pytest.raises(ValueError):
        fused_operator(**config)


@pytest.mark.parametrize(
    "latency,first,last,minimum,maximum,stalls",
    [
        (8, 11, 124, 8, 16, 11),
        (10, 11, 125, 10, 19, 10),
        (12, 12, 132, 12, 22, 10),
        (14, 14, 133, 14, 27, 8),
    ],
)
def test_elastic_pipeline_matches_frozen_tensor_rtl_backpressure(
    latency, first, last, minimum, maximum, stalls
):
    from codesign.ventus.elastic import ElasticPipeline

    # Independent vTCexe Verilator observations, six shapes / four tree depths.
    pipe = ElasticPipeline(latency)
    accepted, output, blocked = [], [], 0
    for cycle in range(200):
        valid = len(accepted) < 64 and cycle % 3 != 1
        token = len(accepted) if valid else None
        fire, result = pipe.advance(token, cycle % 11 < 6)
        blocked += int(valid and not fire)
        if fire:
            accepted.append(cycle)
        if result is not None:
            output.append((cycle, result, cycle - accepted[result]))
        if len(output) == 64:
            break
    assert [token for _, token, _ in output] == list(range(64))
    assert (output[0][0], output[-1][0]) == (first, last)
    assert (min(x[2] for x in output), max(x[2] for x in output)) == (minimum, maximum)
    assert blocked == stalls


def test_ready_memory_does_not_wait_for_future_slow_warp():
    from dataclasses import replace

    slow = tuple(replace(op, name=f"slow.{op.name}") for op in chain("tensor", 10).operations)
    operations = slow + (
        Operation("slowA", "load", sources=("v10",), destination="v4", addresses=(0x90000000,)),
        Operation(
            "fastB", "load", warp=1, sources=("v10",), destination="v4", addresses=(0x90001000,)
        ),
        Operation(
            "fastA",
            "load",
            warp=1,
            sources=("v10",),
            destination="v5",
            addresses=(0x90000000,),
            dependencies=("fastB",),
        ),
    )
    graph = build_graph(
        Workload(operations, warps_per_block=2), Hardware().with_changes(l1_sets=1, l1_ways=1)
    )
    times = dict(zip(graph.names, execute(graph)["times"], strict=True))
    assert times["fastB.address"] < times["fastA.address"] < times["slowA.address"]
    assert times["fastB.writeback"] < times["slowA.issue"]


def test_finished_block_releases_only_its_own_sm():
    from dataclasses import replace

    operations = tuple(
        replace(op, name=f"b{block}.{op.name}", block=block)
        for block, count in enumerate([100, 1, 100])
        for op in chain("tensor", count).operations
    )
    hw = Hardware().with_changes(blocks_per_sm=1)
    graph = build_graph(Workload(operations), hw)
    result = execute(graph)
    times = dict(zip(graph.names, result["times"], strict=True))
    assert times["b2.i0.collect"] == times["b1.i0.writeback"]
    assert times["b2.i0.collect"] < times["b0.i99.writeback"]
    assert result["cycles"] < simulate(Workload(operations), hw.with_changes(sms=1))["cycles"]


def test_collective_ir_fence_waits_for_other_warp_and_blocks_successors():
    operations = (
        Operation("slow", "tensor", warp=1, sources=("v1",), destination="v2"),
        Operation("fence", "barrier"),
        Operation("after0", "vector", destination="v1"),
        Operation("after1", "vector", warp=1, destination="v3"),
    )
    graph = build_graph(Workload(operations, warps_per_block=2), Hardware())
    times = dict(zip(graph.names, execute(graph)["times"], strict=True))
    assert times["fence.collect"] > times["slow.writeback"]
    assert min(times["after0.collect"], times["after1.collect"]) > times["fence.barrier"]


def test_lsu_global_slots_hold_until_load_writeback():
    operations = tuple(
        Operation(
            f"load{warp}", "load", warp=warp, destination="v1", addresses=(0x90000000 + warp * 128,)
        )
        for warp in range(4)
    )
    graph = build_graph(
        Workload(operations, warps_per_block=4), Hardware().with_changes(lsu_entries=1)
    )
    times = dict(zip(graph.names, execute(graph)["times"], strict=True))
    spans = sorted(
        (times[f"load{warp}.lsu.dequeue"], times[f"load{warp}.writeback"]) for warp in range(4)
    )
    assert all(left[1] <= right[0] for left, right in zip(spans, spans[1:]))


def test_online_menu_mip_matches_all_24_candidates_without_large_clock_coefficients():
    from codesign.ventus.__main__ import menu

    candidates = menu()
    budgets = Hardware().resources()
    feasible = [
        candidate
        for candidate in candidates
        if all(candidate.hardware.resources()[name] <= limit for name, limit in budgets.items())
    ]
    best = min(simulate(candidate.workload, candidate.hardware)["cycles"] for candidate in feasible)
    result = optimize(candidates, budgets=budgets)
    assert result["optimal"] and result["cycles"] == result["objective"] == best
