"""Explicit hardware dimensions; no measured or fitted timing coefficients."""

from dataclasses import asdict, dataclass, fields, replace


@dataclass(frozen=True)
class Hardware:
    sms: int = 2
    warps_per_sm: int = 8
    blocks_per_sm: int = 8
    threads: int = 32
    rf_banks: int = 4
    rf_read_ports: int = 1
    rf_write_ports: int = 1
    writeback_ports: int = 1
    collectors: int = 8
    vgpr_slots: int = 1024
    sgpr_slots: int = 2048
    tensor_m: int = 4
    tensor_n: int = 8  # reduction dimension in upstream's TensorCoreFP32 naming
    tensor_k: int = 4  # output columns
    tensor_units: int = 1
    lds_bytes: int = 131072
    lds_banks: int = 32
    lds_ports: int = 1
    line_bytes: int = 128
    l1_sets: int = 256
    l1_ways: int = 2
    l1_mshrs: int = 4
    l1_subentries: int = 2
    l1_write_entries: int = 4
    l2_sets: int = 64
    l2_ways: int = 16
    l2_mshrs: int = 32
    lsu_entries: int = 8
    lsu_per_warp: int = 4
    # External memory is a separately declared target, not inferred GPU behavior.
    memory_channels: int = 1
    memory_bytes_per_cycle: int = 128
    memory_latency: int = 2  # Mem_SimWrapper DELAY_DDR; response appears one edge later

    def validate(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field.name} must be a positive integer")
        for name in [
            "threads",
            "rf_banks",
            "lds_banks",
            "line_bytes",
            "l1_sets",
            "l2_sets",
            "l2_ways",
        ]:
            value = getattr(self, name)
            if value & (value - 1):
                raise ValueError(f"{name} must be a power of two")
        if self.tensor_n < 2 or self.tensor_n & (self.tensor_n - 1):
            raise ValueError("tensor_n must be a power of two greater than one")
        for a, b in [("tensor_m", "tensor_n"), ("tensor_n", "tensor_k"), ("tensor_m", "tensor_k")]:
            if getattr(self, a) * getattr(self, b) > self.threads:
                raise ValueError(f"{a} * {b} exceeds threads (upstream tensor packing)")
        if self.line_bytes < self.lds_banks * 4 or self.line_bytes % 4:
            raise ValueError("line_bytes must contain at least one word per LDS bank")
        if self.vgpr_slots % self.rf_banks or self.sgpr_slots % self.rf_banks:
            raise ValueError("register pools must divide into banks")
        if self.blocks_per_sm > self.warps_per_sm:
            raise ValueError("blocks_per_sm exceeds upstream warp-slot bound")
        return self

    def with_changes(self, **values):
        return replace(self, **values).validate()

    @property
    def tensor_latency(self):
        # TCMulPipe=2, each TCAddPipe=2, final add=2, two non-flow queues=1+1.
        return 2 + 2 * (self.tensor_n.bit_length() - 1) + 2 + 2

    @property
    def tensor_flops_per_instruction(self):
        return 2 * self.tensor_m * self.tensor_n * self.tensor_k

    def resources(self):
        """Physical storage bytes and multiplier count, without an invented area conversion."""
        return {
            "storage_bytes": self.sms
            * (
                self.vgpr_slots * self.threads * 4
                + self.sgpr_slots * 4
                + self.lds_bytes
                + self.l1_sets * self.l1_ways * self.line_bytes
            )
            + self.l2_sets * self.l2_ways * self.line_bytes,
            "tensor_multipliers": self.sms
            * self.tensor_units
            * self.tensor_m
            * self.tensor_n
            * self.tensor_k,
        }

    def rtl_bindings(self):
        """Violations require RTL unbinding or a new target; they are never silently accepted."""
        tied = {
            "collectors": self.warps_per_sm,
            "vgpr_slots": 128 * self.warps_per_sm,
            "sgpr_slots": 256 * self.warps_per_sm,
            "lds_banks": self.threads,
            "lsu_entries": self.warps_per_sm,
            "tensor_units": 1,
            "lds_ports": 1,
            "rf_read_ports": 1,
            "rf_write_ports": 1,
            "writeback_ports": 1,
        }
        shape = (4, 8, 4) if self.threads == 32 else (2, 4, 2) if self.threads == 8 else (2, 2, 2)
        tied.update(zip(["tensor_m", "tensor_n", "tensor_k"], shape))
        return {
            key: {"model": getattr(self, key), "rtl": value}
            for key, value in tied.items()
            if getattr(self, key) != value
        }

    def to_dict(self):
        return asdict(self)
