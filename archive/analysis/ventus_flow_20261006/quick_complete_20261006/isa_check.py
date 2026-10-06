"""Independent sequential decoding for numeric/address checks, not timing."""

import ctypes
import struct

_fma = ctypes.CDLL(None).fmaf
_fma.argtypes = (ctypes.c_float, ctypes.c_float, ctypes.c_float)
_fma.restype = ctypes.c_float


def number(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


def word(number):
    return struct.unpack("<I", struct.pack("<f", number))[0]


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def initial_memory(path):
    lines = (path / "input.metadata").read_text().splitlines()
    meta = [int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)]
    payload = [int(x, 16) for x in (path / "input.data").read_text().splitlines()]
    n = meta[13]
    offset = 0
    memory = {}
    ranges = []
    for base, size in zip(meta[14 : 14 + n], meta[14 + n : 14 + 2 * n]):
        ranges.append((base, base + size))
        memory.update({base + 4 * i: w for i, w in enumerate(payload[offset : offset + size // 4])})
        offset += size // 4
    return memory, ranges


def execute(case, path, *, snapshots=None):
    memory, ranges = initial_memory(path)
    by_warp = {
        w: [op for op in case["workload"]["operations"] if op["warp"] == w]
        for w in range(case["warps"])
    }
    accesses = 0
    for warp in range(case["warps"]):
        v = [[0] * 32 for _ in range(32)]
        x = [0] * 32
        for index, instruction in enumerate(case["words"]):
            if instruction == 0x400B:
                if index != len(by_warp[warp]):
                    raise ValueError("IR/word length differs")
                break
            op = instruction & 127
            rd = (instruction >> 7) & 31
            rs1 = (instruction >> 15) & 31
            rs2 = (instruction >> 20) & 31
            mode = (instruction >> 12) & 7
            if op == 0x37:
                x[rd] = instruction & 0xFFFFF000
            elif op == 0x13 and mode == 0:
                x[rd] = (x[rs1] + signed(instruction >> 20, 12)) & 0xFFFFFFFF
            elif op == 0x13 and mode == 1:
                x[rd] = (x[rs1] << ((instruction >> 20) & 31)) & 0xFFFFFFFF
            elif op == 0x73 and instruction >> 20 == 0x800 and mode == 2:
                x[rd] = warp * 32
            elif op == 0x7B:
                addresses = tuple(v[rs1])
                if list(addresses) != by_warp[warp][index]["addresses"]:
                    raise ValueError("actual ISA address differs from timing input")
                if any(
                    a % 4
                    or not (0x70000000 <= a < 0x70000200 or any(lo <= a < hi for lo, hi in ranges))
                    for a in addresses
                ):
                    raise ValueError("address outside allocated buffers")
                accesses += len(addresses)
                if mode == 2:
                    v[rd] = [memory[a] for a in addresses]
                elif mode == 6:
                    for a, w in zip(addresses, v[rs2]):
                        memory[a] = w
                    if snapshots is not None and addresses[0] == 0x90002000:
                        snapshots.append((0x80000000 + 4 * index, v[rs2][:]))
                else:
                    raise ValueError("unsupported memory")
            elif op == 0x0B and instruction >> 26 == 3:
                if mode != 4:
                    raise ValueError("unsupported Tensor mode")
                a = v[rs1][:]
                b = v[rs2][:]
                old = v[rd][:]
                for row in range(4):
                    for col in range(4):
                        # These Tensor inputs are small integer-valued FP32;
                        # dot tree and sequential sum agree exactly in this domain.
                        dot = sum(number(a[row * 8 + k]) * number(b[col * 8 + k]) for k in range(8))
                        v[rd][row * 4 + col] = word(number(old[row * 4 + col]) + dot)
            elif op == 0x57:
                fn = instruction >> 26
                a = v[rs2][:]
                b = (
                    v[rs1][:]
                    if mode in (0, 1)
                    else [x[rs1]] * 32
                    if mode == 4
                    else [signed(rs1, 5) & 0xFFFFFFFF] * 32
                )
                if fn == 0x14 and mode == 2 and rs1 == 17:
                    result = list(range(32))
                elif fn == 0x17 and mode == 4 and rs2 == 0:
                    result = [x[rs1]] * 32
                elif mode == 1 and fn in (0, 2, 6):
                    result = [
                        word(
                            number(aa) + number(bb)
                            if fn == 0
                            else number(aa) - number(bb)
                            if fn == 2
                            else max(number(aa), number(bb))
                        )
                        for aa, bb in zip(a, b)
                    ]
                elif mode == 1 and fn in (0x2C, 0x2F):
                    result = [
                        word(
                            _fma(-number(aa) if fn == 0x2F else number(aa), number(bb), number(cc))
                        )
                        for aa, bb, cc in zip(a, b, v[rd][:])
                    ]
                elif fn == 0 and mode in (0, 3, 4):
                    result = [(aa + bb) & 0xFFFFFFFF for aa, bb in zip(a, b)]
                elif fn == 2 and mode == 0:
                    result = [(aa - bb) & 0xFFFFFFFF for aa, bb in zip(a, b)]
                elif fn == 0x09:
                    result = [aa & bb for aa, bb in zip(a, b)]
                elif fn == 0x0A:
                    result = [aa | bb for aa, bb in zip(a, b)]
                elif fn == 0x0B:
                    result = [aa ^ bb for aa, bb in zip(a, b)]
                elif fn == 0x25:
                    result = [(aa << (bb & 31)) & 0xFFFFFFFF for aa, bb in zip(a, b)]
                elif fn == 0x28:
                    result = [aa >> (bb & 31) for aa, bb in zip(a, b)]
                else:
                    raise ValueError(f"unsupported vector {instruction:08x}")
                v[rd] = result
            else:
                raise ValueError(f"unsupported instruction {instruction:08x}")
            x[0] = 0
    output = [memory[0x90002000 + 4 * i] for i in range(len(case["expected_words"]))]
    if output != case["expected_words"]:
        raise ValueError("independent ISA result differs")
    return accesses
