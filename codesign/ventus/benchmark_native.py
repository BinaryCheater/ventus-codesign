"""Measure one real, cold-cache dispatch through the stable native ABI.

An older locally preserved library can be compared without rebuilding or changing
its receipt. This utility never resumes a model using an incompatible runtime.
"""

import argparse
import ctypes
import hashlib
import json
import resource
import sys
from dataclasses import fields
from pathlib import Path
from time import perf_counter

from .coalescer import shared_service_intervals
from .config import Hardware
from .instruction_cli import prepare
from .rust import COUNTERS, library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dispatch", required=True)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text())
    chosen = next(d for d in raw["dispatches"] if d["name"] == args.dispatch)
    single = {**raw, "dispatches": [chosen]}
    hw = Hardware(**raw["hardware"]).validate()
    _, program = next(prepare(single, args.input.parent, hw, None))
    lib = ctypes.CDLL(str(args.library.resolve())) if args.library else library()
    pointer = ctypes.POINTER(ctypes.c_uint64)
    lib.vt_create.argtypes = [pointer, pointer, ctypes.c_size_t]
    lib.vt_create.restype = ctypes.c_void_p
    lib.vt_target.argtypes = [ctypes.c_void_p, pointer]
    lib.vt_run_program.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_size_t,
        pointer,
        ctypes.c_size_t,
        pointer,
    ]
    lib.vt_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    lib.vt_state.restype = pointer
    lib.vt_destroy.argtypes = [ctypes.c_void_p]
    packed_hw = (ctypes.c_uint64 * 32)(*[getattr(hw, f.name) for f in fields(Hardware)])
    intervals = shared_service_intervals(hw.lsu_entries)
    packed_intervals = (ctypes.c_uint64 * len(intervals))(*intervals)
    handle = lib.vt_create(packed_hw, packed_intervals, len(intervals))
    if not handle:
        raise ValueError("native session creation failed")
    target = raw["instruction_target"]
    packed_target = (ctypes.c_uint64 * 10)(
        1,
        target["packed_latency"],
        target["conversion_latency"],
        target["sfu_latency"],
        target["mma_pipeline_latency"],
        1,
        target["multiply_packing"],
        target["fmul_latency"],
        target["compare_latency"],
        target["shuffle_latency"],
    )
    result = (ctypes.c_uint64 * (5 + len(COUNTERS)))()
    args.out.mkdir()
    try:
        if lib.vt_target(handle, packed_target):
            raise ValueError("native instruction target rejected")
        begin = perf_counter()
        status = lib.vt_run_program(
            handle, program.words, len(program.words), program.launch, len(program.launch), result
        )
        seconds = perf_counter() - begin
        if status:
            raise ValueError("native dispatch failed")
        n = ctypes.c_size_t()
        state = lib.vt_state(handle, ctypes.byref(n))
        # Hash canonical u64 bytes, not a Python list's representation.
        state_bytes = ctypes.string_at(state, n.value * ctypes.sizeof(ctypes.c_uint64))
        cache_hash = hashlib.sha256(state_bytes).hexdigest()
        receipt = dict(
            dispatch=args.dispatch,
            program_sha256=program.sha256,
            library_sha256=hashlib.sha256(Path(lib._name).read_bytes()).hexdigest(),
            hardware=hw.to_dict(),
            instruction_target=target,
            initial_state="cold cache; one complete fenced dispatch",
            cycles=result[0],
            instructions=result[1],
            requested_bytes=result[2],
            counters=dict(zip(COUNTERS, result[5:], strict=True)),
            cache_sha256=cache_hash,
            host_seconds=seconds,
            process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1024**2 if sys.platform == "darwin" else 1024),
        )
        (args.out / "benchmark.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: receipt[k]
                    for k in ("cycles", "instructions", "host_seconds", "process_peak_rss_mib")
                }
            )
        )
    finally:
        lib.vt_destroy(handle)


if __name__ == "__main__":
    main()
