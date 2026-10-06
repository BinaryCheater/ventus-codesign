"""Concrete LayerNorm ISA lowering, checked by independent instruction decoding."""

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "analysis/ventus_flow_20261006/layernorm_rtl_20261006"


def load(name):
    spec = importlib.util.spec_from_file_location(f"layernorm_{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def implementations():
    return load("generate"), load("isa_reference")


@pytest.mark.parametrize(
    "width,seed,constant", [(32, 1, False), (64, 2, False), (64, 3, False), (64, 0, True)]
)
def test_layernorm_machine_words_match_ir_addresses_and_dense(
    implementations, width, seed, constant
):
    emitter, decoder = implementations
    program, metadata = emitter.Emitter(width, seed, constant).build()
    output, addresses = decoder.execute(program)
    assert output == program.expected
    assert metadata["max_abs_error_vs_float64"] < 2e-6
    assert len(output) == width
    assert len(addresses) == sum(op.kind in {"load", "store"} for op in program.workload.operations)
    assert all(
        0x70000000 <= a < 0x70000200 or 0x90000000 <= a < 0x90003000
        for values in addresses
        for a in values
    )


def test_signed_vector_immediate_cannot_silently_match_timing_ir(implementations):
    emitter, decoder = implementations
    program, _ = emitter.Emitter(32, 1).build()
    # Replace the first +16 rotation from a scalar register by VI immediate 16.
    # Together with VI mask 31 (sign-extended to -1), this recreates the
    # original bad addresses. The decoder must reject the timing IR claim.
    from codesign.ventus.program import vector

    words = list(program.words)
    pos = next(
        i
        for i, w in enumerate(words)
        if w & 0x7F == 0x57 and w >> 26 == 0 and (w >> 12) & 7 == 4 and (w >> 15) & 31 == 7
    )
    words[pos] = vector(0, 10, 16, 3, 10)
    mask_pos = next(
        i for i in range(pos + 1, len(words)) if words[i] & 0x7F == 0x57 and words[i] >> 26 == 0x09
    )
    words[mask_pos] = vector(0x09, 10, 31, 3, 10)
    with pytest.raises(ValueError, match="addresses differ"):
        decoder.execute(replace(program, words=tuple(words)))


def test_subtraction_operand_order_is_checked_independently(implementations):
    emitter, decoder = implementations
    program, _ = emitter.Emitter(64, 2).build()
    words = list(program.words)
    pos = next(
        i for i, w in enumerate(words) if w & 0x7F == 0x57 and w >> 26 == 2 and (w >> 12) & 7 == 1
    )
    w = words[pos]
    rs1, rs2 = (w >> 15) & 31, (w >> 20) & 31
    words[pos] = (w & ~((31 << 15) | (31 << 20))) | rs1 << 20 | rs2 << 15
    output, _ = decoder.execute(replace(program, words=tuple(words)))
    assert output != program.expected
