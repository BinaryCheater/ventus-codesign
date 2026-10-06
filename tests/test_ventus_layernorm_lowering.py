"""The production timing frontend must preserve the independently tested ISA."""

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.layernorm import LayerNormEmitter
from codesign.ventus.transformer import TransformerSpec, lower_transformer


@pytest.mark.parametrize("width", [32, 64])
def test_same_words_and_timing_as_independent_rtl_fixture(width):
    path = Path("analysis/ventus_flow_20261006/layernorm_rtl_20261006/generate.py")
    spec = importlib.util.spec_from_file_location("rtl_layernorm_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reference, _ = module.Emitter(width, 1).build()
    words, ops = LayerNormEmitter(
        width, 0x90000000, 0x90001000, 0x90001000 + 4 * width, 0x90002000, 0x70000000
    ).build()
    assert words == reference.words
    assert (
        tuple(replace(op, name=f"pc{0x80000000 + i * 4:08x}") for i, op in enumerate(ops))
        == reference.workload.operations
    )


def test_transformer_uses_relocated_paired_layernorm_with_private_scratch():
    program = lower_transformer(TransformerSpec(prefill=3, decode_steps=0), Hardware())
    kernel = next(k for k in program.kernels if k.kind == "norm")
    batch = next(program.batches(kernel))
    assert program.describe()["layernorm_lowering"] == "paired-isa-butterfly32-newton4-v1"
    assert batch.lds_per_block == 512
    for block in range(3):
        operations = [op for op in batch.operations if op.block == block]
        global_reads = {
            a for op in operations if op.kind == "load" for a in op.addresses if a >= 0x80000000
        }
        assert {kernel.inputs[0].address(block, col) for col in range(64)} <= global_reads
        scratch = {a for op in operations for a in op.addresses if a < 0x80000000}
        assert all(0x70000000 + block * 512 <= a < 0x70000000 + (block + 1) * 512 for a in scratch)


@pytest.mark.parametrize("width", [0, 31, 33, True])
def test_unrepresentable_full_lane_shape_rejected(width):
    with pytest.raises(ValueError):
        LayerNormEmitter(width, 0, 0, 0, 0, 0)
