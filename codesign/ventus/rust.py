"""Compact Rust execution of the existing v7 decoded instruction contract."""

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, fields
from pathlib import Path

from .coalescer import shared_service_intervals
from .config import Hardware

RUST_VERSION = "ventus-instruction-rust-v9-1"
KINDS = (
    "scalar",
    "vector",
    "fadd",
    "fmax",
    "fma",
    "ftoi",
    "itof",
    "tensor",
    "load",
    "store",
    "barrier",
    "fp_add_internal",
    "packed",
    "convert",
    "sfu",
    "mma_bf16",
    "mma_f16",
    "mma_tf32",
    "fmul",
    "fcmp",
    "shuffle",
)
COUNTERS = (
    *KINDS,
    "memory_read_bytes",
    "memory_write_bytes",
    "l2_hit",
    "l2_miss",
    "l1_merge",
    "l1_hit",
    "l1_write_miss",
    "l1_read_miss",
    "lds_rounds",
    "writeback_stall_cycles",
    "execution_input_stall_cycles",
    "fpu_add_backpressure_cycles",
    "fpu_add_arbitration_stalls",
)
NONE = 2**64 - 1
ABI = 0x56545337


def source_hash():
    root = Path(__file__).with_name("rust_core")
    digest = hashlib.sha256()
    for p in sorted([root / "Cargo.toml", root / "Cargo.lock", *root.joinpath("src").glob("*.rs")]):
        digest.update(p.name.encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def runtime_hash():
    digest = hashlib.sha256(source_hash().encode())
    for name in (
        "rust.py",
        "elf.py",
        "coalescer.py",
        "config.py",
        "ir.py",
        "instruction_cli.py",
        "__main__.py",
    ):
        path = Path(__file__).with_name(name)
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def library():
    root = Path(__file__).with_name("rust_core")
    key = source_hash()[:20]
    cache = Path("results/.rust") / key
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    output = cache / "release" / ("libventus_timing" + suffix)
    if not output.is_file():
        cargo = shutil.which("cargo")
        if not cargo:
            candidate = Path.home() / ".cargo/bin/cargo"
            cargo = str(candidate) if candidate.is_file() else None
        build_env = os.environ.copy()
        if not cargo:
            candidates = sorted((Path.home() / ".rustup/toolchains").glob("*/bin/cargo"))
            if candidates:
                cargo = str(candidates[-1])
                build_env["PATH"] = (
                    str(candidates[-1].parent) + os.pathsep + build_env.get("PATH", "")
                )
        if not cargo:
            raise RuntimeError(
                "Rust toolchain missing on execution machine; install rustup (see docs/workflows.md)"
            )
        subprocess.run(
            [
                cargo,
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(root / "Cargo.toml"),
                "--target-dir",
                str(cache.resolve()),
            ],
            check=True,
            capture_output=True,
            env=build_env,
        )
    lib = ctypes.CDLL(str(output.resolve()))
    u64ptr = ctypes.POINTER(ctypes.c_uint64)
    lib.vt_create.argtypes = [u64ptr, u64ptr, ctypes.c_size_t]
    lib.vt_create.restype = ctypes.c_void_p
    lib.vt_fast.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.vt_target.argtypes = [ctypes.c_void_p, u64ptr]
    lib.vt_destroy.argtypes = [ctypes.c_void_p]
    lib.vt_run.argtypes = [ctypes.c_void_p, u64ptr, ctypes.c_size_t, u64ptr]
    lib.vt_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    lib.vt_state.restype = u64ptr
    lib.vt_restore.argtypes = [ctypes.c_void_p, u64ptr, ctypes.c_size_t]
    lib.vt_generate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_size_t,
        u64ptr,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.vt_generate.restype = u64ptr
    lib.vt_run_program.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_size_t,
        u64ptr,
        ctypes.c_size_t,
        u64ptr,
    ]
    lib.vt_error.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    lib.vt_error.restype = ctypes.POINTER(ctypes.c_uint8)
    return lib


def encode(workload, hardware):
    workload.validate(hardware)
    names = {o.name: i for i, o in enumerate(workload.operations)}

    def reg(r):
        return int(r[1:]) + (256 if r[0] == "x" else 0)

    data = [
        ABI,
        len(workload.operations),
        workload.warps_per_block,
        workload.vgpr_per_warp,
        workload.sgpr_per_warp,
        workload.lds_per_block,
    ]
    for o in workload.operations:
        data.extend(
            [
                KINDS.index(o.kind),
                o.block,
                o.warp,
                reg(o.destination) if o.destination else NONE,
                len(o.sources),
                len(o.addresses),
                len(o.dependencies),
            ]
        )
        data.extend(reg(r) for r in o.sources)
        data.extend(o.addresses)
        data.extend(names[d] for d in o.dependencies)
    return (ctypes.c_uint64 * len(data))(*data)


@dataclass(frozen=True)
class PreparedInstructions:
    """Hardware-independent compact input, encoded once for a hardware sweep."""

    data: object
    sha256: str

    @classmethod
    def from_workload(cls, workload, hardware):
        data = encode(workload, hardware)
        return cls(data, hashlib.sha256(bytes(data)).hexdigest())

    @classmethod
    def from_bytes(cls, payload):
        if len(payload) < 48 or len(payload) % 8 or sys.byteorder != "little":
            raise ValueError("compact instructions require little-endian aligned u64 input")
        data = (ctypes.c_uint64 * (len(payload) // 8)).from_buffer_copy(payload)
        if data[0] not in {ABI, 0x56545338, 0x56545339}:
            raise ValueError("compact instruction ABI differs")
        return cls(data, hashlib.sha256(payload).hexdigest())

    def to_bytes(self):
        return bytes(self.data)


@dataclass(frozen=True)
class PreparedProgram:
    words: object
    launch: object
    sha256: str
    metadata: dict

    @classmethod
    def from_elf(cls, elf, launch):
        code = (ctypes.c_uint32 * len(elf.words))(*elf.words)
        args = (ctypes.c_uint64 * len(launch))(*launch)
        key = hashlib.sha256(bytes(code) + bytes(args) + elf.sha256.encode()).hexdigest()
        return cls(
            code,
            args,
            key,
            {
                "elf_sha256": elf.sha256,
                "compiler_resources": elf.resources,
                "launch_resources": {"vgpr": launch[6], "sgpr": launch[7], "lds": launch[8]},
                "blocks": launch[3],
                "warps_per_block": launch[4],
                "threads": launch[5],
            },
        )


class RustSession:
    def __init__(self, hardware, *, instruction_target=None, event_jumps=True):
        self.hw = hardware.validate()
        if any(getattr(hardware, f.name) >= 2**64 for f in fields(Hardware)):
            raise ValueError("hardware exceeds native u64 ABI")
        self.source_sha256, self.runtime_sha256 = source_hash(), runtime_hash()
        self.lib = library()
        hw = (ctypes.c_uint64 * 32)(*[getattr(hardware, f.name) for f in fields(Hardware)])
        raw = shared_service_intervals(hardware.lsu_entries)
        intervals = (ctypes.c_uint64 * len(raw))(*raw)
        self.handle = self.lib.vt_create(hw, intervals, len(raw))
        if not self.handle:
            raise RuntimeError("Rust initialization failed")
        self.event_jumps = bool(event_jumps)
        self.lib.vt_fast(self.handle, int(self.event_jumps))
        self.instruction_target = dict(instruction_target or {})
        if instruction_target:
            defaults = {
                "packed_latency": 3,
                "conversion_latency": 2,
                "sfu_latency": 4,
                "mma_pipeline_latency": 14,
                "multiply_packing": 2,
                "fmul_latency": 3,
                "compare_latency": 2,
                "shuffle_latency": 1,
            }
            if set(instruction_target) != set(defaults):
                self.close()
                raise ValueError(
                    "explicit extended instruction target must declare every timing field"
                )
            if any(type(v) is not int or not 1 <= v <= 256 for v in instruction_target.values()):
                self.close()
                raise ValueError("invalid extended instruction timing")
            target = (ctypes.c_uint64 * 10)(
                1,
                instruction_target["packed_latency"],
                instruction_target["conversion_latency"],
                instruction_target["sfu_latency"],
                instruction_target["mma_pipeline_latency"],
                int(self.event_jumps),
                instruction_target["multiply_packing"],
                instruction_target["fmul_latency"],
                instruction_target["compare_latency"],
                instruction_target["shuffle_latency"],
            )
            if self.lib.vt_target(self.handle, target):
                self.close()
                raise ValueError("native target rejected")
        self.cycles = 0
        self.counters = {}
        self.instructions = self.requested_bytes = self.host_ticks = self.idle_skipped = 0

    def close(self):
        if self.handle:
            self.lib.vt_destroy(self.handle)
            self.handle = None

    def __del__(self):
        if getattr(self, "handle", None):
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def dispatch(self, workload):
        if not self.handle:
            raise ValueError("Rust session is closed")
        result = (
            ctypes.c_uint64
            * len(COUNTERS + ("cycles", "instructions", "bytes", "ticks", "skipped"))
        )()
        if isinstance(workload, PreparedProgram):
            status = self.lib.vt_run_program(
                self.handle,
                workload.words,
                len(workload.words),
                workload.launch,
                len(workload.launch),
                result,
            )
        else:
            data = (
                workload.data
                if isinstance(workload, PreparedInstructions)
                else encode(workload, self.hw)
            )
            status = self.lib.vt_run(self.handle, data, len(data), result)
        if status:
            n = ctypes.c_size_t()
            error = self.lib.vt_error(self.handle, ctypes.byref(n))
            detail = ctypes.string_at(error, n.value).decode(errors="replace")
            self.close()
            raise ValueError("Rust execution rejected program; session discarded: " + detail)
        start = self.cycles
        self.cycles += result[0]
        self.instructions += result[1]
        self.requested_bytes += result[2]
        self.host_ticks += result[3]
        self.idle_skipped += result[4]
        counters = {k: v for k, v in zip(COUNTERS, result[5:], strict=True) if v}
        for k, v in counters.items():
            self.counters[k] = self.counters.get(k, 0) + v
        return {
            "start": start,
            "end": self.cycles,
            "cycles": result[0],
            "instructions": result[1],
            "requested_bytes": result[2],
            "host_ticks": result[3],
            "idle_skipped": result[4],
            "counters": counters,
        }

    def generate(self, words, launch):
        if not self.handle:
            raise ValueError("Rust session is closed")
        code = (ctypes.c_uint32 * len(words))(*words)
        args = (ctypes.c_uint64 * len(launch))(*launch)
        n = ctypes.c_size_t()
        ptr = self.lib.vt_generate(self.handle, code, len(code), args, len(args), ctypes.byref(n))
        if not ptr:
            error = self.lib.vt_error(self.handle, ctypes.byref(n))
            raise ValueError(ctypes.string_at(error, n.value).decode())
        return PreparedInstructions.from_bytes(ctypes.string_at(ptr, n.value * 8))

    def cache_state(self):
        if not self.handle:
            raise ValueError("Rust session is closed")
        n = ctypes.c_size_t()
        p = self.lib.vt_state(self.handle, ctypes.byref(n))
        return list(p[: n.value])

    def restore_cache(self, state):
        if not self.handle:
            raise ValueError("Rust session is closed")
        data = (ctypes.c_uint64 * len(state))(*state)
        if self.lib.vt_restore(self.handle, data, len(data)):
            raise ValueError("invalid Rust cache checkpoint")

    def checkpoint(self):
        return {
            "version": RUST_VERSION,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "hardware": self.hw.to_dict(),
            "instruction_target": self.instruction_target,
            "event_jumps": self.event_jumps,
            "cache": self.cache_state(),
            "cycles": self.cycles,
            "counters": self.counters,
            "instructions": self.instructions,
            "requested_bytes": self.requested_bytes,
            "host_ticks": self.host_ticks,
            "idle_skipped": self.idle_skipped,
        }

    def restore(self, checkpoint):
        if (
            checkpoint["version"] != RUST_VERSION
            or checkpoint["source_sha256"] != self.source_sha256
            or checkpoint["runtime_sha256"] != self.runtime_sha256
            or checkpoint["hardware"] != self.hw.to_dict()
            or checkpoint["instruction_target"] != self.instruction_target
            or checkpoint["event_jumps"] != self.event_jumps
        ):
            raise ValueError("checkpoint code/hardware identity differs")
        for field in ("cycles", "instructions", "requested_bytes", "host_ticks", "idle_skipped"):
            if type(checkpoint[field]) is not int or checkpoint[field] < 0:
                raise ValueError("invalid checkpoint counters")
        if not isinstance(checkpoint["counters"], dict) or any(
            k not in COUNTERS or type(v) is not int or v < 0
            for k, v in checkpoint["counters"].items()
        ):
            raise ValueError("invalid checkpoint counters")
        self.restore_cache(checkpoint["cache"])
        for field in (
            "cycles",
            "counters",
            "instructions",
            "requested_bytes",
            "host_ticks",
            "idle_skipped",
        ):
            setattr(self, field, checkpoint[field])


def python_cache_state(session):
    """Canonical fenced state, with replacement order and L2 ways preserved."""
    data = [ABI, session.lfsr]
    l1 = sorted((k, v) for k, v in session.l1.items() if v)
    data.append(len(l1))
    for (sm, bank), tags in l1:
        data.extend([sm, bank, len(tags)])
        for line, record in tags.items():
            data.extend([line, record.way])
    l2 = sorted((k, v) for k, v in session.l2.items() if v)
    data.append(len(l2))
    for bank, tags in l2:
        data.extend([bank, len(tags)])
        for line, record in tags.items():
            data.extend([line, record.way])
    return data
