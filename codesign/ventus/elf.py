"""Read actual Ventus ELF32 sections, symbols and compiler resource metadata."""

import hashlib
import struct
from dataclasses import dataclass
from math import prod


@dataclass(frozen=True)
class ELFProgram:
    sha256: str
    base: int
    words: tuple[int, ...]
    symbols: dict
    memory: dict
    resources: dict

    @classmethod
    def read(cls, path):
        data = path.read_bytes()
        if data[:7] != b"\x7fELF\x01\x01\x01" or len(data) < 52:
            raise ValueError("expected little-endian ELF32")
        header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
        if header[1] != 2 or header[2] != 243:
            raise ValueError("expected linked RISC-V executable")
        offset, stride, count, names = header[6], header[11], header[12], header[13]
        if stride != 40 or offset + stride * count > len(data) or names >= count:
            raise ValueError("invalid ELF section table")
        rows = [struct.unpack_from("<10I", data, offset + i * stride) for i in range(count)]

        def payload(row):
            if row[4] + row[5] > len(data):
                raise ValueError("truncated ELF section")
            return data[row[4] : row[4] + row[5]]

        strings = payload(rows[names])

        def string(table, start):
            if start >= len(table):
                raise ValueError("invalid ELF string offset")
            end = table.find(b"\0", start)
            if end < 0:
                raise ValueError("unterminated ELF string")
            return table[start:end].decode()

        sections = {string(strings, row[0]): row for row in rows}
        text = sections.get(".text")
        if not text or text[5] % 4:
            raise ValueError("expected aligned .text section")
        words = struct.unpack(f"<{text[5] // 4}I", payload(text))
        symbols, resources, memory = {}, {}, {}
        for name, row in sections.items():
            if row[1] == 2:
                table = payload(rows[row[6]])
                if row[9] != 16 or row[5] % 16:
                    raise ValueError("unsupported ELF symbol table")
                for entry in struct.iter_unpack("<IIIBBH", payload(row)):
                    if entry[0] and entry[5]:
                        symbols[string(table, entry[0])] = {"address": entry[1], "bytes": entry[2]}
            elif name.startswith(".ventus.resource."):
                raw = payload(row)
                if len(raw) != 56 or struct.unpack_from("<I", raw)[0] != 3:
                    raise ValueError("unsupported Ventus resource metadata version")
                values = struct.unpack("<II6Q", raw)
                resources[name.removeprefix(".ventus.resource.")] = dict(
                    zip(
                        (
                            "version",
                            "flags",
                            "vgpr",
                            "sgpr",
                            "lds_static",
                            "pds_static",
                            "lds_stack",
                            "pds_stack",
                        ),
                        values,
                        strict=True,
                    )
                )
            # Only initialized, allocated non-code bytes are functional inputs.
            # Large tensor allocations are intentionally absent/unknown.
            if row[2] & 2 and not row[2] & 4 and row[1] == 1:
                raw = payload(row)
                for i in range(0, len(raw) - 3, 4):
                    memory[row[3] + i] = struct.unpack_from("<I", raw, i)[0]
        return cls(hashlib.sha256(data).hexdigest(), text[3], words, symbols, memory, resources)

    def launch(
        self,
        kernel,
        arguments,
        *,
        global_size,
        local_size=(32, 1, 1),
        resource_override=None,
        functional_words=None,
    ):
        if kernel not in self.symbols or kernel not in self.resources:
            raise ValueError("kernel symbol or official resource metadata absent")
        if len(global_size) != 3 or len(local_size) != 3:
            raise ValueError("launch dimensions must have three axes")
        if any(type(n) is not int or n <= 0 for n in (*global_size, *local_size)):
            raise ValueError("launch dimensions must be positive integers")
        if prod(local_size) % 32:
            raise ValueError("current program provider requires complete 32-lane warps")
        resource = self.resources[kernel]
        if resource["flags"]:
            if resource_override is None:
                raise ValueError(
                    "compiler resource summary incomplete or private stack unsupported; explicit audited launch resources required"
                )
            vgpr, sgpr, lds = (resource_override[k] for k in ("vgpr", "sgpr", "lds"))
        else:
            vgpr, sgpr = resource["vgpr"], resource["sgpr"]
            lds = resource["lds_static"] + resource["lds_stack"]
        lds = (lds + 127) // 128 * 128
        args, metadata = 0x50000000, 0x50000100
        initial = dict(self.memory)
        for address, value in (functional_words or {}).items():
            address = int(address)
            if (
                address % 4
                or not 0 <= address < 2**32
                or type(value) is not int
                or not 0 <= value < 2**32
            ):
                raise ValueError("invalid functional input word")
            if address in initial or args <= address < metadata + 128:
                raise ValueError("functional input overlaps program/launch memory")
            initial[address] = value
        for i, value in enumerate(arguments):
            if type(value) is not int or not 0 <= value < 2**32:
                raise ValueError("kernel arguments must be RV32 words")
            initial[args + 4 * i] = value
        entry = self.symbols[kernel]["address"]
        meta_words = [
            entry,
            args,
            3,
            *global_size,
            *local_size,
            0,
            0,
            0,
            0,
            0,
            resource["lds_stack"],
            resource["lds_static"],
        ]
        initial.update({metadata + 4 * i: v for i, v in enumerate(meta_words)})
        blocks = prod(
            (g + local_extent - 1) // local_extent
            for g, local_extent in zip(global_size, local_size, strict=True)
        )
        gp = self.symbols.get("__global_pointer$", {}).get("address", 0)
        return [
            self.base,
            entry,
            0xFFFFFFF0,
            blocks,
            prod(local_size) // 32,
            32,
            vgpr,
            sgpr,
            lds,
            args,
            *global_size,
            *local_size,
            0,
            gp,
            metadata,
            len(initial),
            *[v for address, value in sorted(initial.items()) for v in (address, value)],
            resource["pds_static"] + resource["pds_stack"],
        ]
