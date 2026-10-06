"""FP32 GPT-2-shaped timing frontend, independent of tensor numerical payloads.

The software contract is streamed, fenced tile dispatches and explicit LDS tree
reductions. Elementary functions use declared instruction templates; their
numerical accuracy and compiler lowering have not been validated.
"""

from dataclasses import asdict, dataclass
from math import ceil
from time import perf_counter

from .config import Hardware
from .ir import Operation, Workload
from .session import TimingSession


@dataclass(frozen=True)
class TransformerSpec:
    layers: int = 2
    width: int = 64
    heads: int = 4
    hidden: int = 256
    vocab: int = 128
    prefill: int = 16
    decode_steps: int = 2
    positions: int = 1024
    dtype: str = "FP32"

    def validate(self):
        for key, value in asdict(self).items():
            if key == "dtype":
                continue
            if type(value) is not int or value < (0 if key == "decode_steps" else 1):
                raise ValueError(f"invalid Transformer {key}")
        if self.width % self.heads or self.prefill + self.decode_steps > self.positions:
            raise ValueError("head width or position capacity is invalid")
        if self.dtype != "FP32":
            raise ValueError("only the locked FP32 Tensor path is supported")
        return self

    @classmethod
    def gpt2(cls, **changes):
        # openai-community/gpt2 config.json: 12 layers, 768 width, 12 heads,
        # 50257 tokens, 1024 positions; n_inner null means 4*width.
        return cls(
            **{"layers": 12, "width": 768, "heads": 12, "hidden": 3072, "vocab": 50257, **changes}
        ).validate()


@dataclass(frozen=True)
class Software:
    warps: int = 2
    dispatch_tiles: int = 8
    elementary: str = "range-reduced-polynomial-v1"

    def validate(self, hw):
        if type(self.warps) is not int or not 1 <= self.warps <= hw.warps_per_sm:
            raise ValueError("invalid software warp count")
        if type(self.dispatch_tiles) is not int or self.dispatch_tiles < 1:
            raise ValueError("dispatch_tiles must be positive")
        if self.elementary != "range-reduced-polynomial-v1":
            raise ValueError("unsupported elementary function implementation")
        return self


@dataclass(frozen=True)
class View:
    base: int
    rows: int
    cols: int
    row_stride: int
    col_stride: int = 1

    def address(self, row, col):
        if not 0 <= row < self.rows or not 0 <= col < self.cols:
            raise ValueError("view access outside logical shape")
        return self.base + 4 * (row * self.row_stride + col * self.col_stride)

    def slice(self, rows, cols, row=0, col=0):
        if row < 0 or col < 0 or row + rows > self.rows or col + cols > self.cols:
            raise ValueError("view slice exceeds allocation")
        return View(self.address(row, col), rows, cols, self.row_stride, self.col_stride)

    def transpose(self):
        return View(self.base, self.cols, self.rows, self.col_stride, self.row_stride)


@dataclass(frozen=True)
class Kernel:
    name: str
    kind: str
    output: View
    inputs: tuple[View, ...]
    causal_start: int | None = None


@dataclass(frozen=True)
class TransformerProgram:
    spec: TransformerSpec
    hardware: Hardware
    software: Software
    allocations: tuple[dict, ...]
    kernels: tuple[Kernel, ...]

    def describe(self):
        return {
            "spec": asdict(self.spec),
            "hardware": self.hardware.to_dict(),
            "software": asdict(self.software),
            "allocations": self.allocations,
            "kernels": [asdict(k) for k in self.kernels],
            "kv_capacity_bytes": 2
            * self.spec.layers
            * (self.spec.prefill + self.spec.decode_steps)
            * self.spec.width
            * 4,
            "numerical_payload": False,
            "rtl_unbinding_required": self.hardware.rtl_bindings(),
        }

    def batches(self, kernel):
        hw, sw = self.hardware, self.software
        out = kernel.output
        tiles = (
            [
                (r, c)
                for r in range(0, out.rows, hw.tensor_m)
                for c in range(0, out.cols, hw.tensor_k)
            ]
            if kernel.kind == "gemm"
            else [(r, 0) for r in range(out.rows)]
            if kernel.kind in {"norm", "softmax"}
            else [(r, c) for r in range(out.rows) for c in range(0, out.cols, hw.threads)]
        )
        for begin in range(0, len(tiles), sw.dispatch_tiles):
            ops = []
            for tile, (row, col) in enumerate(tiles[begin : begin + sw.dispatch_tiles]):
                block, warp = divmod(tile, sw.warps)
                # Row reductions have private LDS and run one warp per block.
                if kernel.kind in {"norm", "softmax"}:
                    block, warp = tile, 0
                emitter = Emitter(hw, kernel, block, warp, f"{kernel.name}.t{begin + tile}")
                emitter.zero_address = next(
                    a["base"] for a in self.allocations if a["name"] == "zero_panel"
                )
                if kernel.kind == "gemm":
                    emitter.gemm(row, col)
                elif kernel.kind in {"norm", "softmax"}:
                    emitter.row_reduce(row)
                else:
                    emitter.element(row, col)
                ops.extend(emitter.ops)
            scratch = (hw.threads * 2 + (out.cols if kernel.kind == "softmax" else 0)) * 4
            if kernel.kind in {"norm", "softmax"} and scratch * sw.dispatch_tiles > hw.lds_bytes:
                raise ValueError("reduction dispatch scratch exceeds LDS; reduce dispatch_tiles")
            yield Workload(
                tuple(ops),
                warps_per_block=1 if kernel.kind in {"norm", "softmax"} else sw.warps,
                vgpr_per_warp=32,
                sgpr_per_warp=16,
                lds_per_block=scratch if kernel.kind in {"norm", "softmax"} else 0,
            ).validate(hw)


def lower_transformer(spec, hardware, software=None):
    spec.validate()
    hardware.validate()
    software = (software or Software()).validate(hardware)
    allocations, kernels = [], []
    cursor = 0x90000000

    def alloc(name, rows, cols):
        nonlocal cursor
        cursor = (cursor + hardware.line_bytes - 1) // hardware.line_bytes * hardware.line_bytes
        view = View(cursor, rows, cols, cols)
        size = rows * cols * 4
        cursor += size
        if cursor >= 2**32:
            raise ValueError("Transformer allocations exceed 32-bit global address space")
        allocations.append({"name": name, "base": view.base, "bytes": size, "shape": [rows, cols]})
        return view

    def emit(name, kind, out, *inputs, causal_start=None):
        kernels.append(Kernel(name, kind, out, tuple(inputs), causal_start))
        return out

    d, h, cap = spec.width, spec.width // spec.heads, spec.prefill + spec.decode_steps
    token = alloc("token_embedding_and_lm_head", spec.vocab, d)
    position = alloc("position_embedding", spec.positions, d)
    # A real, read-only zero panel handles Tensor padding without out-of-bounds reads.
    alloc("zero_panel", 1, hardware.threads)
    weights, kv = [], []
    for layer in range(spec.layers):
        weights.append(
            {
                "qkv": alloc(f"l{layer}.wqkv", d, 3 * d),
                "proj": alloc(f"l{layer}.wproj", d, d),
                "up": alloc(f"l{layer}.wup", d, spec.hidden),
                "down": alloc(f"l{layer}.wdown", spec.hidden, d),
                "bqkv": alloc(f"l{layer}.bqkv", 1, 3 * d),
                "bproj": alloc(f"l{layer}.bproj", 1, d),
                "bup": alloc(f"l{layer}.bup", 1, spec.hidden),
                "bdown": alloc(f"l{layer}.bdown", 1, d),
                "ln1": alloc(f"l{layer}.ln1", 2, d),
                "ln2": alloc(f"l{layer}.ln2", 2, d),
            }
        )
        kv.append((alloc(f"l{layer}.K", cap, d), alloc(f"l{layer}.V", cap, d)))
    final_ln = alloc("final_ln", 2, d)
    for step in range(spec.decode_steps + 1):
        rows = spec.prefill if step == 0 else 1
        past = 0 if step == 0 else spec.prefill + step - 1
        context = past + rows
        prefix = "prefill" if step == 0 else f"decode{step}"
        x = alloc(prefix + ".embedding", rows, d)
        # Fixed, in-range symbolic input token indices, no future hidden state read.
        for row in range(rows):
            emit(
                f"{prefix}.embedding{row}",
                "add",
                x.slice(1, d, row),
                token.slice(1, d, (past + row) % spec.vocab),
                position.slice(1, d, past + row),
            )
        for layer, (w, (key, value)) in enumerate(zip(weights, kv, strict=True)):
            name = f"{prefix}.l{layer}"
            norm = emit(name + ".ln1", "norm", alloc(name + ".norm1", rows, d), x, w["ln1"])
            qkv = emit(name + ".qkv", "gemm", alloc(name + ".qkv", rows, 3 * d), norm, w["qkv"])
            emit(name + ".qkv_bias", "add", qkv, qkv, w["bqkv"])
            emit(name + ".K_append", "copy", key.slice(rows, d, past), qkv.slice(rows, d, col=d))
            emit(
                name + ".V_append",
                "copy",
                value.slice(rows, d, past),
                qkv.slice(rows, d, col=2 * d),
            )
            attn = alloc(name + ".attn", rows, d)
            for head in range(spec.heads):
                hn = name + f".h{head}"
                scores = emit(
                    hn + ".qk",
                    "gemm",
                    alloc(hn + ".scores", rows, context),
                    qkv.slice(rows, h, col=head * h),
                    key.slice(context, h, col=head * h).transpose(),
                )
                prob = emit(
                    hn + ".softmax",
                    "softmax",
                    alloc(hn + ".prob", rows, context),
                    scores,
                    causal_start=past,
                )
                emit(
                    hn + ".av",
                    "gemm",
                    attn.slice(rows, h, col=head * h),
                    prob,
                    value.slice(context, h, col=head * h),
                )
            proj = emit(name + ".proj", "gemm", alloc(name + ".proj", rows, d), attn, w["proj"])
            emit(name + ".proj_bias", "add", proj, proj, w["bproj"])
            residual = emit(
                name + ".residual1", "add", alloc(name + ".residual1", rows, d), x, proj
            )
            norm2 = emit(name + ".ln2", "norm", alloc(name + ".norm2", rows, d), residual, w["ln2"])
            up = emit(name + ".up", "gemm", alloc(name + ".up", rows, spec.hidden), norm2, w["up"])
            emit(name + ".up_bias", "add", up, up, w["bup"])
            emit(name + ".gelu", "gelu", up, up)
            down = emit(name + ".down", "gemm", alloc(name + ".down", rows, d), up, w["down"])
            emit(name + ".down_bias", "add", down, down, w["bdown"])
            x = emit(
                name + ".residual2", "add", alloc(name + ".residual2", rows, d), residual, down
            )
        norm = emit(
            prefix + ".final_ln", "norm", alloc(prefix + ".final_norm", rows, d), x, final_ln
        )
        emit(
            prefix + ".lm_head",
            "gemm",
            alloc(prefix + ".logits", rows, spec.vocab),
            norm,
            token.transpose(),
        )
    return TransformerProgram(spec, hardware, software, tuple(allocations), tuple(kernels))


class Emitter:
    def __init__(self, hw, kernel, block, warp, prefix):
        self.hw, self.k, self.block, self.warp, self.prefix = hw, kernel, block, warp, prefix
        self.ops = []

    def emit(self, kind, sources=(), dest=None, addresses=(), lanes=None, dependencies=()):
        name = self.prefix + f".i{len(self.ops)}"
        self.ops.append(
            Operation(
                name,
                kind,
                self.block,
                self.warp,
                tuple(sources),
                dest,
                tuple(addresses),
                tuple(dependencies),
                lanes,
            )
        )
        return name

    def alu(self, kind, dest, *sources, lanes=None):
        return self.emit(kind, sources, dest, lanes=lanes)

    def memory(self, kind, reg, addresses, lanes=None, dependencies=()):
        # VID, integer address arithmetic and scalar base supply; address/control
        # values are symbolic but the instruction and RF supply are charged.
        self.alu("scalar", "x5", "x0")
        self.alu("vector", "v10")
        self.alu("vector", "v10", "v10", "x5")
        return self.emit(
            kind,
            ("v10",) if kind == "load" else ("v10", reg),
            reg if kind == "load" else None,
            addresses,
            lanes,
            dependencies,
        )

    def gemm(self, row, col):
        hw, out = self.hw, self.k.output
        a, b = self.k.inputs
        self.alu("vector", "v3", "v3", "v3")
        # Padding values are explicitly supplied from a zero panel.
        zero = self.zero_address
        for red in range(0, a.cols, hw.tensor_n):
            aa = tuple(
                a.address(row + i, red + j) if row + i < a.rows and red + j < a.cols else zero
                for i in range(hw.tensor_m)
                for j in range(hw.tensor_n)
            )
            bb = tuple(
                b.address(red + j, col + i) if red + j < b.rows and col + i < b.cols else zero
                for i in range(hw.tensor_k)
                for j in range(hw.tensor_n)
            )
            self.memory("load", "v1", aa)
            self.memory("load", "v2", bb)
            self.alu("tensor", "v3", "v1", "v2", "v3")
        pairs = [
            (i * hw.tensor_k + j, out.address(row + i, col + j))
            for i in range(hw.tensor_m)
            for j in range(hw.tensor_k)
            if row + i < out.rows and col + j < out.cols
        ]
        self.memory("store", "v3", tuple(a for _, a in pairs), tuple(i for i, _ in pairs))

    def exp(self, reg, lanes):
        # Range reduction x=n*ln(2)+r, nearest integer n; degree-6 Horner
        # polynomial and exponent reconstruction. Coefficients are scalar RF
        # constants supplied by charged immediate materialization instructions.
        self.alu("fma", "v6", reg, "v20", "v21", lanes=lanes)
        self.alu("ftoi", "v7", "v6", lanes=lanes)
        self.alu("itof", "v8", "v7", lanes=lanes)
        self.alu("fma", "v8", "v8", "v22", reg, lanes=lanes)
        self.alu("vector", "v9", "v23")
        for coeff in range(6):
            self.alu("scalar", f"x{6 + coeff}", "x0")
            self.alu("fma", "v9", "v9", "v8", f"x{6 + coeff}", lanes=lanes)
        self.alu("vector", "v7", "v7", lanes=lanes)
        self.alu("fma", reg, "v9", "v7", "v24", lanes=lanes)

    def reciprocal(self, src, dest, lanes=None, sqrt=False):
        # Integer exponent/mantissa seed followed by four Newton iterations.
        self.alu("vector", "v12", src, lanes=lanes)
        src = "v12"
        self.alu("vector", dest, src, lanes=lanes)
        self.alu("vector", dest, dest, "v25", lanes=lanes)
        for _ in range(4):
            if sqrt:
                self.alu("fma", "v6", dest, dest, "v24", lanes=lanes)
                self.alu("fma", "v6", src, "v6", "v26", lanes=lanes)
            else:
                self.alu("fma", "v6", src, dest, "v26", lanes=lanes)
            self.alu("fma", dest, dest, "v6", "v24", lanes=lanes)

    def constants(self):
        for reg in range(20, 28):
            self.alu("scalar", "x5", "x0")
            self.alu("vector", f"v{reg}", "x5")

    def element(self, row, col):
        out = self.k.output
        count = min(self.hw.threads, out.cols - col)
        lanes = tuple(range(count))
        for index, view in enumerate(self.k.inputs):
            self.memory(
                "load",
                f"v{index + 1}",
                tuple(view.address(row if view.rows > 1 else 0, col + i) for i in lanes),
                lanes,
            )
        if self.k.kind == "add":
            self.alu("fadd", "v1", "v1", "v2", lanes=lanes)
        elif self.k.kind == "gelu":
            self.constants()
            # GPT-2 tanh GELU: x^3, c*(x+0.044715*x^3), tanh via exp
            # and reciprocal; approximate elementary templates are declared.
            self.alu("fma", "v4", "v1", "v1", "v24", lanes=lanes)
            self.alu("fma", "v4", "v4", "v1", "v24", lanes=lanes)
            self.alu("fma", "v4", "v4", "v20", "v1", lanes=lanes)
            self.alu("fma", "v4", "v4", "v21", "v24", lanes=lanes)
            self.exp("v4", lanes)
            self.alu("fadd", "v5", "v4", "v26", lanes=lanes)
            self.reciprocal("v5", "v5", lanes)
            self.alu("fma", "v4", "v5", "v22", "v26", lanes=lanes)
            self.alu("fma", "v1", "v1", "v4", "v24", lanes=lanes)
        elif self.k.kind != "copy":
            raise ValueError(f"unsupported element {self.k.kind}")
        self.memory("store", "v1", tuple(out.address(row, col + i) for i in lanes), lanes)

    def tree(self, reg, kind, slot):
        width = self.hw.threads
        base = self.scratch_base + slot * width * 4
        stored = self.memory("store", reg, tuple(base + i * 4 for i in range(width)))
        distance = width // 2
        while distance:
            lanes = tuple(range(distance))
            self.memory(
                "load", "v4", tuple(base + (i + distance) * 4 for i in lanes), lanes, (stored,)
            )
            self.alu(kind, reg, reg, "v4", lanes=lanes)
            stored = self.memory("store", reg, tuple(base + i * 4 for i in lanes), lanes)
            distance //= 2
        self.memory("load", reg, (base,) * width, tuple(range(width)), (stored,))

    def row_reduce(self, row):
        width = self.hw.threads
        scratch_bytes = (2 * width + (self.k.output.cols if self.k.kind == "softmax" else 0)) * 4
        self.scratch_base = 0x70000000 + self.block * scratch_bytes
        temporary = self.scratch_base + 2 * width * 4
        out, source = self.k.output, self.k.inputs[0]
        valid = (
            min(out.cols, self.k.causal_start + row + 1) if self.k.kind == "softmax" else out.cols
        )
        self.constants()
        self.alu("vector", "v1", "v1", "v1")
        self.alu("vector", "v2", "v2", "v2")
        # Softmax identity is -infinity (immediate materialization), not zero.
        if self.k.kind == "softmax":
            self.alu("vector", "v1", "v27")
        for col in range(0, valid, width):
            lanes = tuple(range(min(width, valid - col)))
            self.memory("load", "v3", tuple(source.address(row, col + i) for i in lanes), lanes)
            self.alu("fmax" if self.k.kind == "softmax" else "fadd", "v1", "v1", "v3", lanes=lanes)
            if self.k.kind == "norm":
                self.alu("fma", "v2", "v3", "v3", "v2", lanes=lanes)
        self.tree("v1", "fmax" if self.k.kind == "softmax" else "fadd", 0)
        if self.k.kind == "norm":
            self.tree("v2", "fadd", 1)
            self.alu("fma", "v1", "v1", "v20", "v24")
            self.alu("fma", "v2", "v2", "v20", "v24")
            self.alu("fma", "v2", "v1", "v1", "v2")
            self.alu("fadd", "v2", "v2", "v21")
            self.reciprocal("v2", "v2", sqrt=True)
        else:
            self.alu("vector", "v2", "v2", "v2")
            for col in range(0, valid, width):
                lanes = tuple(range(min(width, valid - col)))
                self.memory("load", "v3", tuple(source.address(row, col + i) for i in lanes), lanes)
                self.alu("fma", "v3", "v3", "v20", "v1", lanes=lanes)
                self.exp("v3", lanes)
                stored = self.memory(
                    "store", "v3", tuple(temporary + (col + i) * 4 for i in lanes), lanes
                )
                self.alu("fadd", "v2", "v2", "v3", lanes=lanes)
            self.tree("v2", "fadd", 1)
            self.reciprocal("v2", "v2")
        for col in range(0, out.cols, width):
            lanes = tuple(range(min(width, out.cols - col)))
            addresses = tuple(out.address(row, col + i) for i in lanes)
            if self.k.kind == "norm":
                self.memory("load", "v3", tuple(source.address(row, col + i) for i in lanes), lanes)
                self.alu("fma", "v3", "v3", "v26", "v1", lanes=lanes)
                self.alu("fma", "v3", "v3", "v2", "v24", lanes=lanes)
                param = self.k.inputs[1]
                self.memory("load", "v4", tuple(param.address(0, col + i) for i in lanes), lanes)
                self.memory("load", "v5", tuple(param.address(1, col + i) for i in lanes), lanes)
                self.alu("fma", "v3", "v3", "v4", "v5", lanes=lanes)
                self.memory("store", "v3", addresses, lanes)
            else:
                active = tuple(i for i in lanes if col + i < valid)
                if active:
                    self.memory(
                        "load",
                        "v3",
                        tuple(temporary + (col + i) * 4 for i in active),
                        active,
                        (stored,),
                    )
                    self.alu("fma", "v3", "v3", "v2", "v24", lanes=active)
                    self.memory(
                        "store", "v3", tuple(out.address(row, col + i) for i in active), active
                    )
                masked = tuple(i for i in lanes if col + i >= valid)
                if masked:
                    self.alu("vector", "v3", "v3", "v3", lanes=masked)
                    self.memory(
                        "store", "v3", tuple(out.address(row, col + i) for i in masked), masked
                    )

    # Set by the program frontend from its actual allocation map, not a global
    # hardcoded scratch address. This property is overridden on each emitter.
    zero_address: int = 0


def census(program):
    rows = []
    hw = program.hardware
    for kernel in program.kernels:
        out = kernel.output
        if kernel.kind == "gemm":
            red = kernel.inputs[0].cols
            instructions = (
                ceil(out.rows / hw.tensor_m)
                * ceil(out.cols / hw.tensor_k)
                * ceil(red / hw.tensor_n)
            )
            effective = 2 * out.rows * out.cols * red
            issued = instructions * hw.tensor_flops_per_instruction
        else:
            instructions = effective = issued = 0
        rows.append(
            {
                "name": kernel.name,
                "kind": kernel.kind,
                "output_elements": out.rows * out.cols,
                "tensor_instructions": instructions,
                "effective_tensor_flops": effective,
                "issued_tensor_flops": issued,
            }
        )
    return {
        "kernels": rows,
        "tensor_instructions": sum(r["tensor_instructions"] for r in rows),
        "effective_tensor_flops": sum(r["effective_tensor_flops"] for r in rows),
        "issued_tensor_flops": sum(r["issued_tensor_flops"] for r in rows),
    }


def execute_transformer(program, *, mode="summary", time_budget=60):
    if not isinstance(time_budget, (int, float)) or not 0 < time_budget < float("inf"):
        raise ValueError("time_budget must be finite and positive")
    session = TimingSession(program.hardware, mode=mode)
    begin = perf_counter()
    stages, instructions, request_bytes = [], 0, 0
    completed = True
    for kernel in program.kernels:
        start = session.cycles
        batches = 0
        for workload in program.batches(kernel):
            if perf_counter() - begin > time_budget:
                completed = False
                break
            session.dispatch(workload)
            batches += 1
            instructions += len(workload.operations)
            request_bytes += sum(
                4 * len(op.addresses) for op in workload.operations if op.kind in {"load", "store"}
            )
        stages.append(
            {
                "name": kernel.name,
                "kind": kernel.kind,
                "start": start,
                "end": session.cycles,
                "dispatches": batches,
                "completed": completed,
            }
        )
        if not completed:
            break
    return {
        "completed": completed,
        "cycles": session.cycles if completed else None,
        "partial_cycles": session.cycles,
        "host_seconds": perf_counter() - begin,
        "instructions": instructions,
        "events": session.events,
        "peak_batch_events": session.peak_batch_events,
        "requested_bytes": request_bytes,
        "counters": session.counters,
        "stages": stages,
        "mode": mode,
        "census": census(program),
        "state_policy": "fenced tile dispatches; drain writes; invalidate written L1/L2 lines; retain read-only tags and L2 replacement state",
        "limitations": [
            "Decoded timing excludes CTA/I-cache/host launch and invalidation scan cycles; 8-warp absolute timing remains unvalidated.",
            "Polynomial exp, Newton reciprocal/rsqrt and tanh GELU are explicit software templates, not official compiled kernels; numerical accuracy is unverified.",
            "Cache/MSHR and LDS response timing retain v5 abstraction limits; coherence fences are a declared software policy, not a translated RTL flush FSM.",
            "Dispatch boundaries serialize batches by software contract; changing dispatch_tiles changes the program, not merely debug memory usage.",
            "Full GPT-2 shape uses FP32 templates; no equivalence to a low-precision PyTorch backend or full-network RTL accuracy is claimed.",
        ],
        "units": {
            "cycles": "decoded model cycles",
            "requested_bytes": "active-lane read+write bytes, including LDS",
            "memory_read_bytes": "external line transactions",
            "tensor_flops": "multiply and add each count one",
        },
    }
