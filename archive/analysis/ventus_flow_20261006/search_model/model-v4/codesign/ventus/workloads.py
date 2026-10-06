"""Bounded tensor workloads with explicit layouts and resource footprints."""

from .config import Hardware
from .ir import Operation, Workload


def chain(kind, count, *, conflicts=False, lds_conflict=1, threads=32):
    if type(count) is not int or count < 1:
        raise ValueError("count must be positive")
    if lds_conflict not in {1, 2, 4, 8, 16, 32} or threads % lds_conflict:
        raise ValueError("invalid LDS conflict multiplicity")
    sources = ("v1", "v1", "v1") if conflicts else ("v2", "v3", "v1")
    if kind == "vector":
        sources = ("v1",)
    elif kind == "scalar":
        sources = ("x1",)
    elif kind == "fadd":
        sources = ("v1", "v2")
    addresses = ()
    if kind == "load":
        sources = ("v10",)
        addresses = tuple(0x70000000 + (lane // lds_conflict) * 4 for lane in range(threads))
    return Workload(
        tuple(
            Operation(
                f"i{i}",
                kind,
                sources=sources,
                destination="x1" if kind == "scalar" else "v1",
                addresses=addresses,
            )
            for i in range(count)
        )
    )


def gemm(hw: Hardware, *, m=16, n=16, k=32, warps=1, transpose_b=False, lds_padding=0, shared=True):
    """One warp computes an output tile; source/address generation is explicit.

    This is a timing lowering, not yet a compiler-emitted Ventus binary.
    Tensor input packing follows Tensor.scala's m*n / k*n indexing.
    """
    hw.validate()
    if any(type(x) is not int or x <= 0 for x in [m, n, k, warps]):
        raise ValueError("GEMM dimensions and warps must be positive integers")
    if m % hw.tensor_m or n % hw.tensor_k or k % hw.tensor_n:
        raise ValueError("GEMM must tile exactly in this bounded lowering")
    if type(lds_padding) is not int or lds_padding < 0:
        raise ValueError("LDS padding must be a nonnegative integer")
    ops = []
    tile_id = 0
    for row in range(0, m, hw.tensor_m):
        for col in range(0, n, hw.tensor_k):
            block, warp = divmod(tile_id, warps)
            prefix = f"b{block}.w{warp}.t{tile_id}"
            ops.append(Operation(prefix + ".zero", "vector", block, warp, ("v3", "v3"), "v3"))
            for red in range(0, k, hw.tensor_n):
                stage = prefix + f".r{red}"
                a = tuple(
                    0x90000000 + ((row + i) * k + red + j) * 4
                    for i in range(hw.tensor_m)
                    for j in range(hw.tensor_n)
                )
                bb = tuple(
                    0x91000000
                    + (((col + i) * k + red + j) if transpose_b else ((red + j) * n + col + i)) * 4
                    for i in range(hw.tensor_k)
                    for j in range(hw.tensor_n)
                )
                for operand, addresses, register in [("a", a, "v1"), ("b", bb, "v2")]:
                    addr = stage + f".{operand}.address"
                    ops.append(Operation(addr, "vector", block, warp, ("v10",), "v10"))
                    load = stage + f".{operand}.global"
                    ops.append(Operation(load, "load", block, warp, ("v10",), register, addresses))
                    if shared:
                        width = hw.tensor_m if operand == "a" else hw.tensor_k
                        stride = hw.tensor_n + lds_padding
                        base = 0x70000000 + warp * (hw.tensor_m + hw.tensor_k) * stride * 4
                        if operand == "b":
                            base += hw.tensor_m * stride * 4
                        local = tuple(
                            base + (i * stride + j) * 4
                            for i in range(width)
                            for j in range(hw.tensor_n)
                        )
                        store = stage + f".{operand}.shared_write"
                        ops.append(
                            Operation(
                                store,
                                "store",
                                block,
                                warp,
                                ("v11", register),
                                addresses=local,
                                dependencies=(load,),
                            )
                        )
                        ops.append(
                            Operation(
                                stage + f".{operand}.shared_read",
                                "load",
                                block,
                                warp,
                                ("v11",),
                                register,
                                local,
                                (store,),
                            )
                        )
                ops.append(
                    Operation(stage + ".tensor", "tensor", block, warp, ("v1", "v2", "v3"), "v3")
                )
            output = tuple(
                0x92000000 + ((row + i) * n + col + j) * 4
                for i in range(hw.tensor_m)
                for j in range(hw.tensor_k)
            )
            ops.append(
                Operation(
                    prefix + ".output",
                    "store",
                    block,
                    warp,
                    ("v12", "v3"),
                    addresses=output,
                    dependencies=(stage + ".tensor",),
                )
            )
            tile_id += 1
    # Interleave per-warp instruction streams within each block, preserving each program.
    streams = {}
    for op in ops:
        streams.setdefault(op.block, {}).setdefault(op.warp, []).append(op)
    interleaved = []
    for warps_map in streams.values():
        for i in range(max(len(stream) for stream in warps_map.values())):
            interleaved.extend(stream[i] for stream in warps_map.values() if i < len(stream))
    return Workload(
        tuple(interleaved),
        warps_per_block=warps,
        lds_per_block=warps * (hw.tensor_m + hw.tensor_k) * (hw.tensor_n + lds_padding) * 4
        if shared
        else 0,
    ).validate(hw)
