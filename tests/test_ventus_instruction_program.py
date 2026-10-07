"""Real compiled kernels use the same scheduler for software/hardware variants."""

import json
from pathlib import Path

import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.elf import ELFProgram
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.rust import ABI, KINDS, PreparedInstructions, PreparedProgram, RustSession
from codesign.ventus.session import TimingSession

FIXTURE = Path(__file__).parent / "fixtures/compiled-vecadd"


def workload(buffer):
    data, at, ops = list(buffer.data), 6, []
    for i in range(data[1]):
        kind, block, warp, dest, ns, na, nd = data[at : at + 7]
        at += 7
        regs = tuple(f"{'x' if n >= 256 else 'v'}{n % 256}" for n in data[at : at + ns])
        at += ns
        addresses = tuple(data[at : at + na])
        at += na
        deps = tuple(str(n) for n in data[at : at + nd])
        at += nd
        ops.append(
            Operation(
                str(i),
                KINDS[kind],
                block,
                warp,
                regs,
                None if dest == 2**64 - 1 else f"{'x' if dest >= 256 else 'v'}{dest % 256}",
                addresses,
                deps,
            )
        )
    assert at == len(data)
    return Workload(tuple(ops), *data[2:6])


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"rf_banks": 8},
        {"rf_read_ports": 2},
        {"sms": 1},
        {"memory_latency": 100, "memory_bytes_per_cycle": 64},
        {"lsu_entries": 2, "lsu_per_warp": 1},
        {"l1_sets": 4, "l1_ways": 1},
    ],
)
@pytest.mark.parametrize(
    "variant,kernel,size", [("single", "vecadd_f32", 128), ("pairs", "vecadd_f32_pairs", 64)]
)
def test_compiled_variants_streaming_expanded_and_python(changes, variant, kernel, size):
    elf = ELFProgram.read(FIXTURE / (variant + ".elf"))
    hashes = json.loads((FIXTURE / "source.json").read_text())["elf_sha256"]
    assert elf.sha256 == hashes[variant + ".elf"]
    launch = elf.launch(kernel, [0x90000000, 0x90001000, 0x90002000], global_size=(size, 1, 1))
    hw = Hardware().with_changes(**changes)
    with RustSession(hw) as expanded, RustSession(hw) as streamed:
        buffer = expanded.generate(elf.words, launch)
        program = PreparedProgram.from_elf(elf, launch)
        py = TimingSession(hw, mode="detailed")
        for _ in range(2):
            a = expanded.dispatch(buffer)
            b = streamed.dispatch(program)
            c = py.dispatch(workload(buffer))
            assert a == b
            assert a["cycles"] == c["cycles"]
            assert a["counters"] == c["counters"]
            assert expanded.cache_state() == streamed.cache_state()
        # Exactly 128 additions and input/output words, independently of mapping.
        assert b["counters"]["fadd"] == 4
        output = [
            o
            for o in workload(buffer).operations
            if o.kind == "store" and o.addresses[0] >= 0x90000000
        ]
        addresses = sorted(a for o in output for a in o.addresses)
        assert addresses == list(range(0x90002000, 0x90002200, 4))


def test_decoder_propagates_unknown_values_to_control_failure():
    # lw x5,0(x10); beq x5,x0,+4: the global payload is unknown.
    words = [0x00052283, 0x00028263, 0x00008067]
    launch = [
        0x80000000,
        0x80000000,
        0xFFFFFFF0,
        1,
        1,
        32,
        8,
        32,
        0,
        0x90000000,
        32,
        1,
        1,
        32,
        1,
        1,
        0,
        0,
        0,
        0,
    ]
    with RustSession(Hardware()) as session:
        with pytest.raises(ValueError, match="numerical payload required"):
            session.generate(words, launch)
        assert session.cycles == 0


def test_native_compact_rejects_invalid_memory_not_silently_truncated():
    values = [ABI, 1, 1, 8, 8, 0, 8, 0, 0, 1, 0, 1, 0, 0x90000001]
    import struct

    raw = PreparedInstructions.from_bytes(struct.pack(f"<{len(values)}Q", *values))
    with RustSession(Hardware()) as session:
        with pytest.raises(ValueError, match="rejected"):
            session.dispatch(raw)
        with pytest.raises(ValueError, match="closed"):
            session.dispatch(raw)


def test_checkpoint_identity_and_corrupt_state_are_rejected():
    with RustSession(Hardware()) as session:
        checkpoint = session.checkpoint()
        checkpoint["cycles"] = -1
        with pytest.raises(ValueError, match="counters"):
            session.restore(checkpoint)
        with pytest.raises(ValueError, match="cache checkpoint"):
            session.restore_cache([ABI, 0, 1, 0, 0, 1, 3, 0, 0])
        assert session.cache_state() == [ABI, 0, 0, 0]


def test_cli_resume_retains_cache_and_rejects_changed_hardware(tmp_path, monkeypatch):
    from dataclasses import asdict

    from codesign.ventus import instruction_cli
    from codesign.ventus.workloads import gemm

    raw = {
        "schema": "ventus-dispatches-v1",
        "dispatches": [
            {"name": f"dispatch-{i}", "workload": asdict(gemm(Hardware(), m=4, n=4, k=8))}
            for i in range(3)
        ],
    }
    path = tmp_path / "program.json"
    path.write_text(json.dumps(raw))
    fake = {"time": 0}
    original = RustSession.dispatch

    def dispatch(session, workload):
        result = original(session, workload)
        fake["time"] += 1
        return result

    monkeypatch.setattr(RustSession, "dispatch", dispatch)
    monkeypatch.setattr(instruction_cli, "perf_counter", lambda: fake["time"])
    first, resumed, whole = (tmp_path / n for n in ("first", "resumed", "whole"))
    instruction_cli.run(path, first, budget=0.5)
    assert json.loads((first / "checkpoint.json").read_text())["next_dispatch"] == 1
    instruction_cli.run(path, resumed, budget=100, resume=first / "checkpoint.json")
    instruction_cli.run(path, whole, budget=100)
    a, b = [json.loads((p / "experiment.json").read_text()) for p in (resumed, whole)]
    for key in ("completed", "cycles", "counters", "instructions", "program_sha256"):
        assert a[key] == b[key]
    sa, sb = [json.loads((p / "checkpoint.json").read_text())["session"] for p in (resumed, whole)]
    assert sa == sb
    changed = tmp_path / "hardware.json"
    changed.write_text('{"rf_banks": 8}')
    with pytest.raises(ValueError, match="identity"):
        instruction_cli.run(
            path, tmp_path / "bad", resume=first / "checkpoint.json", hardware_path=changed
        )
