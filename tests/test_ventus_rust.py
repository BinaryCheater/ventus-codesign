"""The native port must preserve resource service and fenced cache state."""

import random

import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.program import packed_gemm
from codesign.ventus.rust import RustSession, python_cache_state
from codesign.ventus.session import TimingSession
from codesign.ventus.transformer import Software, TransformerSpec, lower_transformer
from codesign.ventus.workloads import gemm


def compare(workloads, hw):
    py = TimingSession(hw, mode="detailed")
    with RustSession(hw) as rs:
        for w in workloads:
            a, b = py.dispatch(w), rs.dispatch(w)
            assert a["cycles"] == b["cycles"]
            assert a["counters"] == b["counters"]
            assert python_cache_state(py) == rs.cache_state()
        return rs.checkpoint()


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"rf_banks": 8},
        {"rf_read_ports": 2},
        {"writeback_ports": 2, "rf_write_ports": 2},
        {"tensor_units": 2},
        {"tensor_n": 4},
        {"sms": 1},
        {"lds_banks": 16},
        {"l1_sets": 4, "l1_ways": 1},
        {"memory_latency": 100, "memory_bytes_per_cycle": 64},
        {"lsu_entries": 2, "lsu_per_warp": 1},
    ],
)
def test_hardware_port_equivalence(changes):
    h = Hardware().with_changes(**changes)
    compare([gemm(h, m=8, n=8, k=16, warps=2, transpose_b=True)] * 2, h)


@pytest.mark.parametrize("strategy", ["stream", "resident", "shared", "reload"])
def test_machine_program_port_equivalence(strategy):
    w = packed_gemm(steps=8, strategy=strategy).workload
    compare([w, w], Hardware())


def test_complete_small_program_and_restore():
    p = lower_transformer(
        TransformerSpec(layers=1, width=8, heads=2, hidden=16, vocab=9, prefill=3, decode_steps=1),
        Hardware(),
        Software(dispatch_tiles=4),
    )
    batches = [w for k in p.kernels for w in p.batches(k)]
    checkpoint = compare(batches, p.hardware)
    with RustSession(p.hardware) as session:
        session.restore(checkpoint)
        assert session.checkpoint() == checkpoint
        expected = session.dispatch(batches[-1])
        session.restore(checkpoint)
        assert session.dispatch(batches[-1]) == expected


def test_random_mixed_dependencies_barriers_and_bank_pressure():
    rng = random.Random(737)
    for trial in range(12):
        ops = []
        for i in range(16):
            for warp in range(4):
                kind = rng.choice(
                    [
                        "vector",
                        "scalar",
                        "fadd",
                        "fma",
                        "fmax",
                        "ftoi",
                        "itof",
                        "tensor",
                        "load",
                        "store",
                    ]
                )
                dest = f"{'x' if kind == 'scalar' else 'v'}{rng.randrange(1, 8)}"
                sources = ("v1", "v5", "v9") if kind in {"fma", "tensor"} else ("v1", "v5")
                address = 0x90000000 + 128 * rng.randrange(8)
                ops.append(
                    Operation(
                        f"{trial}.{i}.{warp}",
                        kind,
                        warp=warp,
                        sources=sources,
                        destination=None if kind == "store" else dest,
                        addresses=tuple(address + 4 * j for j in range(8))
                        if kind in {"load", "store"}
                        else (),
                    )
                )
            if i == 7:
                ops.append(Operation(f"{trial}.fence", "barrier"))
        compare([Workload(tuple(ops), warps_per_block=4)], Hardware())
