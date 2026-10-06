"""Generate source-defined ISA probes; no latency is inferred or fitted."""

import json
import struct
import sys
from pathlib import Path


def i_type(imm, rs1, funct3, rd, opcode=0x13):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def v_type(funct6, vs2, src1, funct3, vd):
    return (
        (funct6 << 26) | (1 << 25) | (vs2 << 20) | (src1 << 15) | (funct3 << 12) | (vd << 7) | 0x57
    )


def store(rs2, rs1, funct3=2, opcode=0x23):
    return (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | opcode


def generate(upstream, destination):
    source = upstream / "sim-verilator/testcase/vecadd"
    lines = (source / "vecadd_32b8w8t.metadata").read_text().splitlines()
    base = [int(lines[i], 16) | (int(lines[i + 1], 16) << 32) for i in range(0, len(lines), 2)]
    original = [int(x, 16) for x in (source / "vecadd_32b8w8t.data").read_text().splitlines()]
    sizes = base[14 + base[13] : 14 + 2 * base[13]]
    bases = base[14 : 14 + base[13]]
    code_offset = sum(sizes[: bases.index(0x80000000)]) // 4
    code_words = sizes[bases.index(0x80000000)] // 4
    output_offset = sum(sizes[: bases.index(0x90002000)]) // 4
    destination.mkdir()
    cases = []

    def emit(name, metadata, data, expected, family, n):
        path = destination / name
        path.mkdir()
        (path / "input.metadata").write_text(
            "".join(f"{x & 0xFFFFFFFF:08x}\n{x >> 32:08x}\n" for x in metadata)
        )
        (path / "input.data").write_text("".join(f"{x:08x}\n" for x in data))
        case = {"name": name, "family": family, "n": n, "expected_words": expected}
        (path / "expected.json").write_text(json.dumps(case, indent=2) + "\n")
        cases.append(case)

    for family in ["scalar_add", "vector_add", "vector_fadd", "vector_div", "repeat_load"]:
        for n in [16, 64, 192]:
            metadata, data = base.copy(), original.copy()
            metadata[2], metadata[5], metadata[6] = 1, 32, 1
            data[output_offset : output_offset + 1024] = [0xDEADBEEF] * 1024
            if family == "scalar_add":
                program = [i_type(0, 0, 0, 1)] + [i_type(1, 1, 0, 1)] * n
                expected = [n]
            elif family == "repeat_load":
                program = [0x900002B7] + [i_type(0, 5, 2, 1, 0x03)] * n
                expected = [original[0]]
            else:
                program = []
                if family == "vector_add":
                    program += [v_type(0x0B, 1, 1, 0, 1)]  # vxor.vv v1, v1, v1
                    program += [v_type(0, 1, 1, 3, 1)] * n  # vadd.vi v1, v1, 1
                    expected = [n] * 32
                else:
                    program += [v_type(0x0B, 1, 1, 0, 1)]
                    if family == "vector_div":
                        program += [i_type(1, 0, 0, 5), v_type(0, 1, 5, 4, 1)]
                        program += [v_type(0x21, 1, 5, 6, 1)] * n
                        value = 1
                    else:
                        program += [0x3F8002B7, v_type(0, 1, 5, 4, 2)]
                        program += [v_type(0, 1, 2, 1, 1)] * n
                        value = struct.unpack("<I", struct.pack("<f", float(n)))[0]
                    expected = [value] * 32
            program += [0x90002137]  # lui x2, 0x90002
            if family.startswith("vector"):
                program += [
                    v_type(0x14, 0, 17, 2, 10),
                    v_type(0x25, 10, 2, 3, 10),
                    v_type(0, 10, 2, 4, 10),
                ]
                program += [store(1, 10, 6, 0x7B)]  # vsw12.v v1, 0(v10)
            else:
                program += [store(1, 2)]
            program += [0x0000400B]  # endprg, from official Instructions.scala
            assert len(program) <= code_words
            data[code_offset : code_offset + code_words] = program + [0x13] * (
                code_words - len(program)
            )
            emit(f"{family}-{n}", metadata, data, expected, family, n)

    for wg in [1, 4, 8]:
        metadata = base.copy()
        metadata[2] = wg
        # The compiled kernel's hardware metadata remains unchanged; only grid size changes.
        emit(f"vecadd-wg{wg}", metadata, original, [0x44800000] * (wg * 32), "vecadd", wg)
    (destination / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")


if __name__ == "__main__":
    generate(Path(sys.argv[1]), Path(sys.argv[2]))
