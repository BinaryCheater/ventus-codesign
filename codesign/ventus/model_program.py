"""Lightweight kernel launches; timing sees ELF programs, never model/operator names."""

import hashlib
import json
import math
import shutil
import struct
from pathlib import Path

from .compiler import compile_kernel
from .elf import ELFProgram

ROOT = Path(__file__).resolve().parents[2]
TARGET = dict(
    packed_latency=3,
    conversion_latency=2,
    sfu_latency=4,
    mma_pipeline_latency=14,
    multiply_packing=2,
    fmul_latency=3,
    compare_latency=2,
    shuffle_latency=1,
)


def fbits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def build_bundle(official_kernels, compiler_root, llvm_source, out):
    """Compile once. Hardware searches subsequently reuse both linked programs."""
    out.mkdir()
    compile_kernel(
        ROOT / "examples/kernels/transformer_bf16.cl",
        "embedding_bf16",
        compiler_root,
        llvm_source,
        out / "generic",
    )
    compile_kernel(
        ROOT / "examples/kernels/mma_reuse_bf16.cl",
        "mma_reuse_bf16",
        compiler_root,
        llvm_source,
        out / "reuse",
    )
    compile_kernel(
        ROOT / "examples/kernels/mma_packed_bf16.cl",
        "mma_packed_bf16",
        compiler_root,
        llvm_source,
        out / "packed",
    )
    compile_kernel(
        official_kernels / "addmm_mma_bf16.cl",
        "addmm_mma_bf16",
        compiler_root,
        llvm_source,
        out / "mma",
    )
    bundle = {
        "schema": "ventus-kernel-bundle-v1",
        "generic": "generic/program.elf",
        "mma": "mma/program.elf",
        "packed": "packed/program.elf",
        "reuse": "reuse/program.elf",
        "precision": "BF16",
        "software": "branchless-finite-softmax; warp-shuffle-RMS; compact-GQA-KV; packed-SwiGLU",
        "sources": {
            "pytorch": "2b0e0cffbd4a46add6ec5f89bea665ce233c6b17",
            "llvm": "97df137e687669f9acf4bfd734779f52f2878614",
        },
        "instruction_target": TARGET,
        "target_status": "declared uncalibrated extended-ISA target; no low-precision measured cost",
    }
    for name in ("generic", "mma", "packed", "reuse"):
        bundle[name + "_sha256"] = ELFProgram.read(out / bundle[name]).sha256
    (out / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")


class Allocator:
    def __init__(self, base, limit):
        self.next, self.limit, self.buffers = base, limit, []

    def alloc(self, name, shape, dtype_bytes=2):
        size = math.prod(shape) * dtype_bytes
        address = (self.next + 127) // 128 * 128
        if address + size > self.limit:
            raise ValueError("RV32 allocation overflow")
        self.next = address + size
        self.buffers.append(
            dict(
                name=name,
                shape=list(shape),
                bytes=size,
                address=address,
                end=address + size,
                dtype_bytes=dtype_bytes,
            )
        )
        return address


def qwen_manifest(bundle_path, out, *, phase, context, steps=16, small=False, mapping="packed"):
    if phase not in ("prefill", "decode") or type(context) is not int or context < 1:
        raise ValueError("invalid scenario")
    if type(steps) is not int or steps < 1:
        raise ValueError("invalid decode steps")
    if mapping not in ("packed", "packed64", "scalar"):
        raise ValueError("unknown software mapping")
    source = ROOT / "examples/models/qwen2.5-0.5b-instruct.config.json"
    frozen = json.loads(source.read_text())
    cfg = dict(frozen)
    if small:
        cfg.update(
            hidden_size=64,
            intermediate_size=128,
            num_attention_heads=2,
            num_key_value_heads=1,
            num_hidden_layers=2,
            vocab_size=256,
        )
    width, ff, heads, kvheads, layers, vocab = (
        cfg[k]
        for k in (
            "hidden_size",
            "intermediate_size",
            "num_attention_heads",
            "num_key_value_heads",
            "num_hidden_layers",
            "vocab_size",
        )
    )
    dim = width // heads
    if (
        width % heads
        or heads % kvheads
        or dim % 2
        or context + steps > cfg["max_position_embeddings"]
    ):
        raise ValueError("invalid model shape")
    bundle = json.loads(bundle_path.read_text())
    if bundle["schema"] != "ventus-kernel-bundle-v1" or bundle["precision"] != "BF16":
        raise ValueError("incompatible compiled bundle")
    out.mkdir()
    for kind in ("generic", "mma", "packed", *(["reuse"] if "reuse" in bundle else [])):
        elf = ELFProgram.read(bundle_path.parent / bundle[kind])
        if elf.sha256 != bundle[kind + "_sha256"]:
            raise ValueError("compiled bundle hash differs")
        shutil.copyfile(bundle_path.parent / bundle[kind], out / (kind + ".elf"))
    weights, temps = Allocator(0x90000000, 0xF0000000), Allocator(0x10000000, 0x50000000)
    embedding = weights.alloc("embedding=lm_head", [vocab, width])
    freq = weights.alloc("rope_inverse_frequency", [dim // 2], 4)
    per_layer = []
    for layer in range(layers):
        shapes = {
            "norm1": [width],
            "norm2": [width],
            "q": [width, width],
            "k": [kvheads * dim, width],
            "v": [kvheads * dim, width],
            "qb": [width],
            "kb": [kvheads * dim],
            "vb": [kvheads * dim],
            "o": [width, width],
            "gate": [ff, width],
            "up": [ff, width],
            "down": [width, ff],
        }
        per_layer.append(
            {k: weights.alloc(f"layer{layer}.{k}", shape) for k, shape in shapes.items()}
        )
    weight_addresses = {
        embedding,
        *[w[k] for w in per_layer for k in ("q", "k", "v", "o", "gate", "up", "down")],
    }
    for buffer in weights.buffers:
        if mapping in ("packed", "packed64") and buffer["address"] in weight_addresses:
            buffer["layout"] = "MMA B tiles: [ceil(N/16),ceil(K/16),K16,N16]; logical shape [N,K]"
    finalnorm = weights.alloc("final_norm", [width])
    rows = context if phase == "prefill" else 1
    cap = context if phase == "prefill" else context + steps
    packed_a = temps.alloc(
        "packed_activation_scratch", [(rows + 15) // 16, (ff + 15) // 16, 16, 16]
    )
    tokens = temps.alloc("tokens", [rows], 4)
    x = temps.alloc("hidden", [rows, width])
    y = temps.alloc("normalized", [rows, width])
    q = temps.alloc("q_projection", [rows, width])
    k = temps.alloc("k_projection", [rows, kvheads * dim])
    v = temps.alloc("v_projection", [rows, kvheads * dim])
    qr = temps.alloc("rotated_q", [heads, rows, dim])
    att = temps.alloc("head_attention", [heads, rows, dim])
    joined = temps.alloc("joined_attention", [rows, width])
    proj = temps.alloc("output_projection", [rows, width])
    gate = temps.alloc("gate", [rows, ff])
    up = temps.alloc("up", [rows, ff])
    glu = temps.alloc("swiglu", [rows, ff])
    scores = temps.alloc("scores", [rows, cap])
    prob = temps.alloc("probabilities", [rows, cap])
    logits = temps.alloc("logits_bf16", [vocab])
    logits32 = temps.alloc("logits_fp32", [vocab], 4)
    softscratch = temps.alloc("softmax_fp32_exponentials", [rows, cap], 4)
    caches = [
        (
            temps.alloc(f"layer{layer}.K", [kvheads, cap, dim]),
            temps.alloc(f"layer{layer}.V", [kvheads, cap, dim]),
        )
        for layer in range(layers)
    ]
    dispatches = []

    def emit(name, kernel, args, items, kind="generic", known=None, check=None):
        elf_hash = bundle[kind + "_sha256"]
        dispatches.append(
            dict(
                name=name,
                kernel=kernel,
                elf=kind + ".elf",
                elf_sha256=elf_hash,
                arguments=args,
                global_size=[(items + 31) // 32 * 32, 1, 1],
                local_size=[32, 1, 1],
                functional_words=known or {},
                previous_dispatch=dispatches[-1]["name"] if dispatches else None,
                work=check or {},
            )
        )

    def mm(name, a, b, bias, o, m, n, kdim, astride, bstride, ostride, offset=0):
        if mapping in ("packed", "packed64") and b in weight_addresses:
            if astride != (kdim, 1) or ostride != (n, 1) or offset:
                raise ValueError("packed software mapping requires row-major activation/output")
            emit(
                name + ".pack_activation",
                "pack_a_bf16",
                [a, packed_a, m, kdim],
                ((m + 15) // 16) * ((kdim + 15) // 16) * 32,
                "packed",
            )
            if mapping == "packed64" and n % 64 == 0:
                two_m = int(m >= 32)
                mt = 32 if two_m else 16
                emit(
                    name,
                    "mma_reuse_bf16",
                    [packed_a, b, bias, o, m, n, kdim, int(bool(bias)), two_m],
                    ((m + mt - 1) // mt) * (n // 64) * 32,
                    "reuse",
                    check=dict(
                        effective_multiplies=m * n * kdim,
                        mma_instructions=((m + mt - 1) // mt)
                        * (n // 64)
                        * (8 if two_m else 4)
                        * ((kdim + 15) // 16),
                    ),
                )
                return
            emit(
                name,
                "mma_packed_bf16",
                [packed_a, b, bias, o, m, n, kdim, int(bool(bias))],
                ((m + 15) // 16) * ((n + 15) // 16) * 32,
                "packed",
                check=dict(
                    effective_multiplies=m * n * kdim,
                    mma_instructions=((m + 15) // 16) * ((n + 15) // 16) * ((kdim + 15) // 16),
                ),
            )
            return
        args = [
            a,
            b,
            bias,
            o,
            m,
            n,
            kdim,
            *astride,
            0,
            *bstride,
            0,
            *ostride,
            offset,
            1,
            0,
            int(bool(bias)),
        ]
        emit(
            name,
            "addmm_mma_bf16",
            args,
            ((m + 15) // 16) * ((n + 15) // 16) * 32,
            "mma",
            check=dict(
                effective_multiplies=m * n * kdim,
                mma_instructions=((m + 15) // 16) * ((n + 15) // 16) * ((kdim + 15) // 16),
            ),
        )

    for step in range(1 if phase == "prefill" else steps):
        pos = 0 if phase == "prefill" else context + step
        length = rows if phase == "prefill" else pos + 1
        prefix = "prefill" if phase == "prefill" else f"decode{step:02}"
        known = {tokens + 4 * t: (pos + t + 17) % vocab for t in range(rows)}
        emit(
            prefix + ".embedding",
            "embedding_packed_bf16" if mapping in ("packed", "packed64") else "embedding_bf16",
            [embedding, tokens, x, width, rows],
            rows * width,
            known=known,
        )
        for layer, w in enumerate(per_layer):
            stem = f"{prefix}.layer{layer:02}"
            kc, vc = caches[layer]
            for norm, inp, output in [("norm1", x, y)]:
                emit(
                    stem + "." + norm,
                    "rms_bf16",
                    [
                        inp,
                        w[norm],
                        output,
                        width,
                        rows,
                        fbits(cfg["rms_norm_eps"]),
                        fbits(1 / width),
                    ],
                    rows * 32,
                )
            for name, outbuf, n in [
                ("q", q, width),
                ("k", k, kvheads * dim),
                ("v", v, kvheads * dim),
            ]:
                mm(
                    stem + "." + name,
                    y,
                    w[name],
                    w[name + "b"],
                    outbuf,
                    rows,
                    n,
                    width,
                    (width, 1),
                    (1, width),
                    (n, 1),
                )
            emit(
                stem + ".rope_q",
                "rope_bf16",
                [q, freq, qr, heads, dim, rows, rows, pos, 0],
                rows * heads * dim // 2,
            )
            emit(
                stem + ".rope_k_append",
                "rope_bf16",
                [k, freq, kc, kvheads, dim, rows, cap, pos, pos],
                rows * kvheads * dim // 2,
            )
            emit(
                stem + ".v_append",
                "transpose_append_bf16",
                [v, vc, kvheads, dim, rows, cap, pos],
                rows * kvheads * dim,
            )
            for h in range(heads):
                kh = h // (heads // kvheads)
                mm(
                    stem + f".head{h:02}.qk",
                    qr + h * rows * dim * 2,
                    kc + kh * cap * dim * 2,
                    0,
                    scores,
                    rows,
                    length,
                    dim,
                    (dim, 1),
                    (1, dim),
                    (length, 1),
                )
                emit(
                    stem + f".head{h:02}.softmax",
                    "causal_softmax_bf16",
                    [scores, prob, softscratch, rows, length, pos, fbits(dim**-0.5)],
                    rows * 32,
                )
                mm(
                    stem + f".head{h:02}.pv",
                    prob,
                    vc + kh * cap * dim * 2,
                    0,
                    att + h * rows * dim * 2,
                    rows,
                    dim,
                    length,
                    (length, 1),
                    (dim, 1),
                    (dim, 1),
                )
            emit(
                stem + ".join_heads",
                "heads_to_rows_bf16",
                [att, joined, heads, dim, rows],
                rows * width,
            )
            mm(
                stem + ".o",
                joined,
                w["o"],
                0,
                proj,
                rows,
                width,
                width,
                (width, 1),
                (1, width),
                (width, 1),
            )
            emit(
                stem + ".attention_residual",
                "packed_add_bf16",
                [x, proj, x, rows * width // 2],
                rows * width // 2,
            )
            emit(
                stem + ".norm2",
                "rms_bf16",
                [x, w["norm2"], y, width, rows, fbits(cfg["rms_norm_eps"]), fbits(1 / width)],
                rows * 32,
            )
            for name, outbuf in [("gate", gate), ("up", up)]:
                mm(
                    stem + "." + name,
                    y,
                    w[name],
                    0,
                    outbuf,
                    rows,
                    ff,
                    width,
                    (width, 1),
                    (1, width),
                    (ff, 1),
                )
            emit(
                stem + ".swiglu",
                "packed_swiglu_bf16",
                [gate, up, glu, rows * ff // 2],
                rows * ff // 2,
            )
            mm(
                stem + ".down",
                glu,
                w["down"],
                0,
                proj,
                rows,
                width,
                ff,
                (ff, 1),
                (1, ff),
                (width, 1),
            )
            emit(
                stem + ".ffn_residual",
                "packed_add_bf16",
                [x, proj, x, rows * width // 2],
                rows * width // 2,
            )
        emit(
            prefix + ".final_norm",
            "rms_bf16",
            [x, finalnorm, y, width, rows, fbits(cfg["rms_norm_eps"]), fbits(1 / width)],
            rows * 32,
        )
        mm(
            prefix + ".lm_head",
            y + (rows - 1) * width * 2,
            embedding,
            0,
            logits,
            1,
            vocab,
            width,
            (width, 1),
            (1, width),
            (vocab, 1),
        )
        emit(prefix + ".logits_cast", "cast_bf16_f32", [logits, logits32, vocab], vocab)
    raw = dict(
        schema="ventus-dispatches-v1",
        hardware=dict(memory_channels=1, memory_latency=100, memory_bytes_per_cycle=64),
        instruction_target=bundle["instruction_target"],
        dispatches=dispatches,
        scenario=dict(
            model="Qwen2.5-0.5B-Instruct",
            configuration=cfg,
            configuration_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            small_debug=small,
            phase=phase,
            context=context,
            decode_steps=steps if phase == "decode" else 0,
            precision="BF16 operands and storage; FP32 reductions/MMA accumulator",
            software=bundle["software"],
            mapping=mapping,
            initial_cache="cold",
            initial_kv="empty"
            if phase == "prefill"
            else f"{context} tokens per layer in external memory",
            kv_capacity=cap,
            kv_initial_bytes=0 if phase == "prefill" else layers * 2 * kvheads * context * dim * 2,
            kv_appended_bytes=layers
            * 2
            * kvheads
            * (rows if phase == "prefill" else steps)
            * dim
            * 2,
            weights=weights.buffers,
            buffers=temps.buffers,
            launch_order="fenced sequential dispatches; caches carried throughout",
            excluded=[
                "sampling",
                "tokenizer",
                "initial host-device transfer",
                "compilation",
                "weight loading",
            ],
            official_fallback_policy="explicit device software variants replace unsupported BF16 embedding/advanced indexing and row reductions; no claim to replay unmodified PyTorch CPU fallback",
        ),
    )
    (out / "program.json").write_text(json.dumps(raw, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                dispatches=len(dispatches),
                weights_bytes=sum(b["bytes"] for b in weights.buffers),
                buffers_bytes=sum(b["bytes"] for b in temps.buffers),
                manifest=str(out / "program.json"),
            )
        )
    )
