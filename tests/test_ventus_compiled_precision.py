"""Compiled grouped MMA, masked tails, width-aware traffic and complete launch graphs."""

import json
from pathlib import Path

import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.elf import ELFProgram
from codesign.ventus.model_program import TARGET, qwen_manifest
from codesign.ventus.rust import KINDS, PreparedProgram, RustSession

FIXTURE = Path(__file__).parent / "fixtures/compiled-transformer"


def records(buffer):
    data = list(buffer.data)
    at = 6
    assert data[0] in (0x56545338, 0x56545339)
    for _ in range(data[1]):
        kind, block, warp, nw, ns, na, nd, width = data[at : at + 8]
        at += 8
        mask = data[at] if data[0] == 0x56545339 else 0xFFFFFFFF
        at += int(data[0] == 0x56545339)
        dests = data[at : at + nw]
        at += nw
        sources = data[at : at + ns]
        at += ns
        addresses = data[at : at + na]
        at += na
        at += nd
        yield dict(
            kind=KINDS[kind],
            block=block,
            warp=warp,
            dests=dests,
            sources=sources,
            addresses=addresses,
            width=width,
            active_mask=mask,
        )
    assert at == len(data)


def test_actual_mma_group_and_tail_memory_coverage():
    elf = ELFProgram.read(FIXTURE / "mma.elf")
    m, n, k = 3, 17, 19
    args = [0x90000000, 0x90010000, 0, 0x90030000, m, n, k, k, 1, 0, n, 1, 0, n, 1, 0, 1, 0, 0]
    launch = elf.launch("addmm_mma_bf16", args, global_size=(64, 1, 1))
    hw = Hardware(memory_latency=100, memory_bytes_per_cycle=64)
    with (
        RustSession(hw, instruction_target=TARGET) as expanded,
        RustSession(hw, instruction_target=TARGET) as streamed,
    ):
        compact = expanded.generate(elf.words, launch)
        ops = list(records(compact))
        mma = [o for o in ops if o["kind"] == "mma_bf16"]
        assert len(mma) == 4
        for op in mma:
            assert len(op["sources"]) == 16 and len(op["dests"]) == 8
            assert op["dests"] == list(range(op["dests"][0], op["dests"][0] + 8))
            assert op["sources"][-8:] == op["dests"]
        stores = [
            a
            for o in ops
            if o["kind"] == "store"
            for a in o["addresses"]
            if 0x90030000 <= a < 0x90040000
        ]
        assert sorted(stores) == list(range(0x90030000, 0x90030000 + m * n * 2, 2))
        for o in ops:
            if any(0x90000000 <= a < 0x90020000 for a in o["addresses"]):
                assert o["width"] == 2
        a = expanded.dispatch(compact)
        b = streamed.dispatch(PreparedProgram.from_elf(elf, launch))
        for key in ("cycles", "counters", "instructions", "requested_bytes"):
            assert a[key] == b[key]
        assert expanded.cache_state() == streamed.cache_state()
        assert launch[8] % 128 == 0 and launch[-1] == 56


def test_packed_mma_tensor_and_rf_resources_are_effective():
    elf = ELFProgram.read(FIXTURE / "packed.elf")
    launch = elf.launch(
        "mma_packed_bf16",
        [0x10000000, 0x90000000, 0, 0x10010000, 16, 16, 256, 0],
        global_size=(32, 1, 1),
    )
    results = []
    for changes in (
        {},
        {"tensor_n": 4},
        {"rf_read_ports": 2, "rf_write_ports": 2, "writeback_ports": 2},
    ):
        with RustSession(Hardware().with_changes(**changes), instruction_target=TARGET) as session:
            results.append(session.dispatch(PreparedProgram.from_elf(elf, launch)))
    assert all(r["counters"]["mma_bf16"] == 16 for r in results)
    assert results[1]["cycles"] > results[0]["cycles"]
    assert results[2]["cycles"] < results[0]["cycles"]
    assert (
        results[2]["counters"].get("writeback_stall_cycles", 0)
        < results[0]["counters"]["writeback_stall_cycles"]
    )
    with RustSession(Hardware()) as session:
        with pytest.raises(ValueError, match="explicit target"):
            session.dispatch(PreparedProgram.from_elf(elf, launch))


@pytest.mark.parametrize(
    "phase,context,steps",
    [("prefill", 128, 1), ("prefill", 512, 1), ("decode", 128, 16), ("decode", 512, 16)],
)
def test_full_qwen_shape_bias_tying_kv_launches(tmp_path, phase, context, steps):
    out = tmp_path / "program"
    qwen_manifest(FIXTURE / "bundle.json", out, phase=phase, context=context, steps=steps)
    raw = json.loads((out / "program.json").read_text())
    s = raw["scenario"]
    cfg = s["configuration"]
    ds = raw["dispatches"]
    assert (
        cfg["num_hidden_layers"],
        cfg["hidden_size"],
        cfg["intermediate_size"],
        cfg["vocab_size"],
    ) == (24, 896, 4864, 151936)
    weights = s["weights"]
    buffers = s["buffers"]
    embed = next(b for b in weights if b["name"] == "embedding=lm_head")
    assert sum(b["bytes"] for b in weights) == 988065664
    assert len([b for b in buffers if b["name"].endswith(".K")]) == 24
    assert s["kv_initial_bytes"] == (0 if phase == "prefill" else 24 * 2 * 2 * context * 64 * 2)
    assert (
        s["kv_appended_bytes"] == 24 * 2 * 2 * (context if phase == "prefill" else steps) * 64 * 2
    )
    for i, d in enumerate(ds):
        assert d["previous_dispatch"] == (ds[i - 1]["name"] if i else None)
    lm = [d for d in ds if d["name"].endswith(".lm_head")]
    assert len(lm) == (1 if phase == "prefill" else steps)
    assert all(
        d["arguments"][1] == embed["address"]
        and d["arguments"][4:7] == [1, 151936, 896]
        and d["arguments"][-1] == 0
        for d in lm
    )
    assert len([d for d in ds if d["name"].endswith(".logits_cast")]) == len(lm)
    for d in ds:
        if d["name"].endswith((".q", ".k", ".v")):
            assert d["arguments"][-1] == 1
        if d["name"].endswith((".gate", ".up", ".down", ".o")):
            assert d["arguments"][-1] == 0
    first = [d for d in ds if ".layer00.head" in d["name"] and d["name"].endswith(".qk")][:14]
    assert len(first) == 14
    assert len({d["arguments"][1] for d in first[:7]}) == 1
    assert len({d["arguments"][1] for d in first[7:]}) == 1
    assert first[0]["arguments"][1] != first[7]["arguments"][1]
    if phase == "decode":
        append = [d for d in ds if ".layer00.rope_k_append" in d["name"]]
        assert [d["arguments"][-1] for d in append] == list(range(context, context + steps))
        assert [d["arguments"][4] for d in first] == [1] * 14


@pytest.mark.parametrize("mapping", ["packed", "packed64"])
def test_small_actual_model_completes_and_declared_ranges_cover_traffic(tmp_path, mapping):
    from codesign.ventus.instruction_cli import prepare, run

    program = tmp_path / "program"
    out = tmp_path / "run"
    qwen_manifest(
        FIXTURE / "bundle.json",
        program,
        phase="decode",
        context=3,
        steps=2,
        small=True,
        mapping=mapping,
    )
    raw = json.loads((program / "program.json").read_text())
    hw = Hardware(**raw["hardware"])
    spans = [
        (b["address"], b["end"]) for b in raw["scenario"]["weights"] + raw["scenario"]["buffers"]
    ]
    with RustSession(hw, instruction_target=TARGET) as session:
        for name, p in prepare(raw, program, hw, session):
            compact = session.generate(p.words, p.launch)
            for o in records(compact):
                for a in o["addresses"]:
                    if 0x10000000 <= a < 0x50000000 or 0x90000000 <= a < 0xF0000000:
                        assert any(lo <= a and a + o["width"] <= hi for lo, hi in spans), (name, a)
    result = run(program / "program.json", out, budget=300)
    assert result["completed"] and result["cycles"] > 0
    assert set(result["phase_totals"]) == {"decode00", "decode01"}
    assert result["counters"]["shuffle"] > 0 and result["counters"]["mma_bf16"] > 0


@pytest.mark.parametrize(
    "dtype,kernel,width,kstep", [("f16", "addmm_mma_f16", 2, 16), ("tf32", "gemm_tf32", 4, 8)]
)
def test_other_official_precision_programs_use_same_core(dtype, kernel, width, kstep):
    elf = ELFProgram.read(FIXTURE / (dtype + ".elf"))
    m, n, k = 3, 17, 19
    args = [0x90000000, 0x90010000, 0, 0x90030000, m, n, k, k, 1, 0, n, 1, 0, n, 1, 0, 1, 0, 0]
    launch = elf.launch(kernel, args, global_size=(64, 1, 1))
    with RustSession(Hardware(), instruction_target=TARGET) as session:
        compact = session.generate(elf.words, launch)
        ops = list(records(compact))
        mma = [o for o in ops if o["kind"] == "mma_" + dtype]
        assert len(mma) == 2 * ((k + kstep - 1) // kstep)
        stores = [
            a
            for o in ops
            if o["kind"] == "store"
            for a in o["addresses"]
            if 0x90030000 <= a < 0x90040000
        ]
        assert sorted(stores) == list(range(0x90030000, 0x90030000 + m * n * width, width))
        for o in ops:
            if any(0x90000000 <= a < 0x90020000 for a in o["addresses"]):
                assert o["width"] == width
        result = session.dispatch(PreparedProgram.from_elf(elf, launch))
        assert result["counters"]["mma_" + dtype] == len(mma)


@pytest.mark.parametrize("mapping", ["packed", "packed64"])
@pytest.mark.parametrize(
    "changes", [{}, {"l1_sets": 4, "l1_ways": 1}, {"rf_banks": 8, "rf_read_ports": 2}]
)
def test_event_jump_matches_per_cycle_compiled_program(tmp_path, mapping, changes):
    from codesign.ventus.instruction_cli import prepare

    program = tmp_path / "program"
    qwen_manifest(
        FIXTURE / "bundle.json", program, phase="prefill", context=3, small=True, mapping=mapping
    )
    raw = json.loads((program / "program.json").read_text())
    hw = Hardware(**raw["hardware"]).with_changes(**changes)
    with (
        RustSession(hw, instruction_target=TARGET, event_jumps=True) as fast,
        RustSession(hw, instruction_target=TARGET, event_jumps=False) as reference,
    ):
        for _, compiled in prepare(raw, program, hw, fast):
            a = fast.dispatch(compiled)
            b = reference.dispatch(compiled)
            assert {k: v for k, v in a.items() if k not in ("host_ticks", "idle_skipped")} == {
                k: v for k, v in b.items() if k not in ("host_ticks", "idle_skipped")
            }
            assert fast.cache_state() == reference.cache_state()
        compact = fast.generate(compiled.words, compiled.launch)
        ops = list(records(compact))
        assert all(0 <= op["active_mask"] <= 0xFFFFFFFF for op in ops)


def test_simt_tail_preserves_mask_in_compact_input():
    elf = ELFProgram.read(FIXTURE / "generic.elf")
    # Three BF16 inputs; the final warp has three active lanes.
    launch = elf.launch("cast_bf16_f32", [0x10000000, 0x10010000, 3], global_size=(32, 1, 1))
    with (
        RustSession(Hardware(), instruction_target=TARGET) as session,
        RustSession(Hardware(), instruction_target=TARGET) as streamed,
    ):
        compact = session.generate(elf.words, launch)
        ops = list(records(compact))
        memory = [
            op
            for op in ops
            if op["kind"] in ("load", "store")
            and op["addresses"]
            and op["addresses"][0] < 0x50000000
        ]
        assert memory and all(op["active_mask"] == 7 for op in memory)
        assert session.dispatch(compact) == streamed.dispatch(PreparedProgram.from_elf(elf, launch))


@pytest.mark.parametrize(
    "phase,context", [("prefill", 128), ("prefill", 512), ("decode", 128), ("decode", 512)]
)
def test_full_shape_first_and_last_blocks_stay_in_declared_buffers(tmp_path, phase, context):
    from codesign.ventus.instruction_cli import prepare

    root = tmp_path / "program"
    qwen_manifest(
        FIXTURE / "bundle.json", root, phase=phase, context=context, steps=16, mapping="packed64"
    )
    raw = json.loads((root / "program.json").read_text())
    hw = Hardware(**raw["hardware"])
    spans = [
        (b["address"], b["end"]) for b in raw["scenario"]["weights"] + raw["scenario"]["buffers"]
    ]
    # Probe each distinct kernel/argument shape, including first/last decode
    # append positions, without expanding the entire model into Python objects.
    selected = []
    seen = set()
    for d in raw["dispatches"]:
        if phase == "decode" and not d["name"].startswith(("decode00.", "decode15.")):
            continue
        if ".layer" in d["name"] and ".layer00." not in d["name"]:
            continue
        signature = (d["kernel"], tuple(d["arguments"]), tuple(d["global_size"]))
        if signature not in seen:
            seen.add(signature)
            selected.append(d)
    with RustSession(hw, instruction_target=TARGET) as session:
        for name, program in prepare({**raw, "dispatches": selected}, root, hw, session):
            for block in {0, int(program.launch[3]) - 1}:
                launch = list(program.launch)
                launch[3], launch[16] = 1, block
                compact = session.generate(program.words, launch)
                for op in records(compact):
                    for a in op["addresses"]:
                        if 0x10000000 <= a < 0x50000000 or a >= 0x90000000:
                            assert any(lo <= a and a + op["width"] <= hi for lo, hi in spans), (
                                name,
                                block,
                                a,
                            )
