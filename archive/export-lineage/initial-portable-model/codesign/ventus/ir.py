"""Timing instructions carry addresses/dependencies, never matrix numerical payloads."""

from dataclasses import dataclass

from .config import Hardware


@dataclass(frozen=True)
class Operation:
    name: str
    kind: str
    block: int = 0
    warp: int = 0
    sources: tuple[str, ...] = ()
    destination: str | None = None
    addresses: tuple[int, ...] = ()
    dependencies: tuple[str, ...] = ()
    active_lanes: tuple[int, ...] | None = None
    variant: str | None = None


@dataclass(frozen=True)
class Workload:
    operations: tuple[Operation, ...]
    warps_per_block: int = 1
    vgpr_per_warp: int = 64
    sgpr_per_warp: int = 64
    lds_per_block: int = 4096

    def validate(self, hw: Hardware):
        hw.validate()
        for name in ["warps_per_block", "vgpr_per_warp", "sgpr_per_warp", "lds_per_block"]:
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name == "warps_per_block" else 0):
                raise ValueError(f"invalid {name}")
        if not self.operations:
            raise ValueError("empty workload")
        seen = set()
        for op in self.operations:
            if not op.name or op.name in seen:
                raise ValueError("operation names must be unique and nonempty")
            if op.kind not in {
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
            }:
                raise ValueError(f"unsupported operation {op.kind}")
            if (
                type(op.block) is not int
                or op.block < 0
                or type(op.warp) is not int
                or not 0 <= op.warp < self.warps_per_block
            ):
                raise ValueError("invalid block/warp")
            if set(op.dependencies) - seen:
                raise ValueError("dependencies must precede their consumer")
            for reg in (*op.sources, *([op.destination] if op.destination else [])):
                if (
                    not isinstance(reg, str)
                    or len(reg) < 2
                    or reg[0] not in "xv"
                    or not reg[1:].isdigit()
                    or not 0 <= int(reg[1:]) < 256
                ):
                    raise ValueError(f"invalid register {reg!r}")
            if op.variant is not None and op.variant not in {
                "fadd": {"add", "sub"},
                "fma": {"fmadd", "fnmadd"},
            }.get(op.kind, set()):
                raise ValueError("unsupported instruction variant")
            if op.active_lanes is not None:
                if not op.active_lanes or tuple(sorted(set(op.active_lanes))) != op.active_lanes:
                    raise ValueError("active lanes must be nonempty, unique and ordered")
                if any(type(i) is not int or not 0 <= i < hw.threads for i in op.active_lanes):
                    raise ValueError("active lane exceeds warp width")
                if op.kind == "tensor":
                    raise ValueError("Tensor masking is unsupported; emit padded full tiles")
                if op.kind in {"load", "store"} and len(op.addresses) != len(op.active_lanes):
                    raise ValueError("one address is required per active lane")
            if op.kind in {"load", "store"}:
                if (op.kind == "load" and not op.destination) or (
                    op.kind == "store" and op.destination
                ):
                    raise ValueError("load needs a destination; store cannot write a register")
                if not op.addresses or len(op.addresses) > hw.threads:
                    raise ValueError("memory operation needs one address per active lane")
                if any(type(a) is not int or a < 0 or a >= 2**32 or a % 4 for a in op.addresses):
                    raise ValueError("addresses must be aligned 32-bit word addresses")
                shared = [0x70000000 <= a < 0x70000000 + hw.lds_bytes for a in op.addresses]
                if any(shared) and not all(shared):
                    raise ValueError("mixed shared/global instruction is outside this model")
            elif op.addresses:
                raise ValueError("non-memory operation carries addresses")
            if op.kind == "barrier" and (op.sources or op.destination):
                raise ValueError("collective barrier has no register operands")
            seen.add(op.name)
        if self.resident_blocks(hw) < 1:
            raise ValueError("one block does not fit hardware")
        return self

    def resident_blocks(self, hw):
        bounds = [hw.blocks_per_sm, hw.warps_per_sm // self.warps_per_block]
        for capacity, use in [
            (hw.vgpr_slots, self.vgpr_per_warp * self.warps_per_block),
            (hw.sgpr_slots, self.sgpr_per_warp * self.warps_per_block),
            (hw.lds_bytes, self.lds_per_block),
        ]:
            if use:
                bounds.append(capacity // use)
        return min(bounds)
