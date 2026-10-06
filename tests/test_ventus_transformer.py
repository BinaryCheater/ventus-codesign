"""Checks timing input conservation and summary/detailed execution equivalence."""

from dataclasses import replace

import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.session import TimingSession
from codesign.ventus.timing import build_graph
from codesign.ventus.transformer import (
    Software,
    TransformerSpec,
    census,
    execute_transformer,
    lower_transformer,
)


def tiny():
    return TransformerSpec(
        layers=1, width=8, heads=2, hidden=16, vocab=9, prefill=3, decode_steps=2
    )


@pytest.mark.parametrize("mode", ["summary", "detailed"])
def test_complete_graph_and_kv_steps(mode):
    program = lower_transformer(tiny(), Hardware())
    result = execute_transformer(program, mode=mode, time_budget=20)
    assert result["completed"]
    assert result["counters"]["tensor"] == census(program)["tensor_instructions"]
    assert result["census"]["issued_tensor_flops"] > result["census"]["effective_tensor_flops"]
    assert {k.kind for k in program.kernels} == {"add", "copy", "norm", "gemm", "gelu", "softmax"}
    assert result["counters"]["ftoi"] > 0 and result["counters"]["lds_rounds"] > 0
    k = next(a for a in program.allocations if a["name"] == "l0.K")
    appends = [kernel for kernel in program.kernels if kernel.name.endswith("K_append")]
    assert [a.output.base for a in appends] == [
        k["base"],
        k["base"] + 3 * 8 * 4,
        k["base"] + 4 * 8 * 4,
    ]
    assert program.describe()["kv_capacity_bytes"] == 2 * 5 * 8 * 4


def test_summary_exactly_matches_independent_dag_mode():
    program = lower_transformer(tiny(), Hardware(), Software(warps=2, dispatch_tiles=4))
    a = execute_transformer(program, mode="summary", time_budget=20)
    b = execute_transformer(program, mode="detailed", time_budget=20)
    for field in ("cycles", "counters", "instructions", "requested_bytes", "stages"):
        assert a[field] == b[field]


def test_all_kernel_output_addresses_written_and_all_global_accesses_allocated():
    program = lower_transformer(tiny(), Hardware())
    ranges = [(a["base"], a["base"] + a["bytes"]) for a in program.allocations]
    for kernel in program.kernels:
        writes = []
        for batch in program.batches(kernel):
            batch.validate(program.hardware)
            for op in batch.operations:
                for address in op.addresses:
                    if address < 0x80000000:
                        assert 0x70000000 <= address < 0x70000000 + program.hardware.lds_bytes
                    else:
                        assert any(start <= address < end for start, end in ranges)
                        if op.kind == "store":
                            writes.append(address)
        expected = {
            kernel.output.address(r, c)
            for r in range(kernel.output.rows)
            for c in range(kernel.output.cols)
        }
        assert set(writes) == expected
        assert len(writes) == len(expected)


@pytest.mark.parametrize(
    "changes",
    [{"dtype": "FP16"}, {"heads": 3}, {"decode_steps": -1}, {"prefill": True}, {"positions": 2}],
)
def test_invalid_specs_rejected(changes):
    with pytest.raises(ValueError):
        lower_transformer(replace(tiny(), **changes), Hardware())


def test_budget_exhaustion_never_reports_full_cycles():
    result = execute_transformer(lower_transformer(tiny(), Hardware()), time_budget=1e-12)
    assert not result["completed"] and result["cycles"] is None
    assert result["partial_cycles"] == 0


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf")])
def test_invalid_budget(budget):
    with pytest.raises(ValueError):
        execute_transformer(lower_transformer(tiny(), Hardware()), time_budget=budget)


def test_session_retains_read_tags_but_invalidates_written_lines():
    session = TimingSession(Hardware())
    load = Workload((Operation("read", "load", destination="v1", addresses=(0x90000000,)),))
    assert session.dispatch(load)["counters"]["l1_read_miss"] == 1
    assert session.dispatch(load)["counters"]["l1_hit"] == 1
    store = Workload((Operation("write", "store", sources=("v1",), addresses=(0x90000000,)),))
    session.dispatch(store)
    assert session.dispatch(load)["counters"]["l1_read_miss"] == 1
    assert session.counters["memory_write_bytes"] == 128


def test_tensor_tail_padding_and_masks_follow_hardware_shape():
    spec = tiny()
    a = lower_transformer(spec, Hardware())
    b = lower_transformer(spec, Hardware().with_changes(tensor_n=4))
    assert census(a)["effective_tensor_flops"] == census(b)["effective_tensor_flops"]
    assert census(a)["tensor_instructions"] != census(b)["tensor_instructions"]
    for program in (a, b):
        kernel = next(k for k in program.kernels if k.name == "decode1.lm_head")
        zero = next(a["base"] for a in program.allocations if a["name"] == "zero_panel")
        ops = [op for batch in program.batches(kernel) for op in batch.operations]
        assert any(zero in op.addresses for op in ops if op.kind == "load")
        assert all(op.active_lanes is None for op in ops if op.kind == "tensor")
        assert any(len(op.active_lanes) < 16 for op in ops if op.kind == "store")


def test_invalid_masks_rejected():
    for lanes in ((2, 1), (1, 1), (32,), (), (True,)):
        with pytest.raises(ValueError):
            Workload((Operation("masked", "vector", active_lanes=lanes),)).validate(Hardware())
    with pytest.raises(ValueError, match="Tensor masking"):
        Workload((Operation("tc", "tensor", active_lanes=(0,)),)).validate(Hardware())


def test_fpu_shared_adder_has_real_contention_with_fma_priority():
    # Four independent warp streams can present add and multiply results together.
    operations = tuple(
        Operation(
            f"w{warp}.{i}",
            "fma" if warp < 2 else "fadd",
            warp=warp,
            sources=("v2", "v3", "v4") if warp < 2 else ("v2", "v3"),
            destination=f"v{5 + i}",
        )
        for i in range(8)
        for warp in range(4)
    )
    graph = build_graph(Workload(operations, warps_per_block=4), Hardware())
    result = execute(graph)
    assert result["counters"].get("fpu_add_arbitration_stalls", 0) > 0
    adds = [
        result["times"][i] for i, name in enumerate(graph.names) if name.endswith(".shared_add")
    ]
    assert len(adds) == len(set(adds))


def test_cli_receipt_is_exclusive_and_read_only(tmp_path):
    import json

    from codesign.ventus.transformer_cli import run, verify

    source = tmp_path / "input.json"
    source.write_text(json.dumps({"spec": tiny().__dict__}))
    out = tmp_path / "result"
    run(out, input_path=source, budget=20)
    original = (out / "experiment.json").read_bytes()
    verify(out)
    assert (out / "experiment.json").read_bytes() == original
    with pytest.raises(FileExistsError):
        run(out, input_path=source, budget=20)


def test_gpt2_public_configuration_overrides_validated():
    assert TransformerSpec.gpt2().width == 768
    assert TransformerSpec.gpt2(width=64, heads=4).width == 64
    with pytest.raises(ValueError):
        TransformerSpec.gpt2(width=63)
