"""Decode the tested ISA subset independently of the emitter's shadow values."""

import ctypes
import struct

_fmaf = ctypes.CDLL(None).fmaf
_fmaf.argtypes = (ctypes.c_float, ctypes.c_float, ctypes.c_float)
_fmaf.restype = ctypes.c_float


def word(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def number(value):
    return struct.unpack("<f", struct.pack("<I", value))[0]


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def execute(program):
    memory = {0x90000000 + 4 * i: v for i, v in enumerate(program.panels_a)}
    memory.update({0x90001000 + 4 * i: v for i, v in enumerate(program.panels_b)})
    vector_regs = [[0] * 32 for _ in range(32)]
    scalar_regs = [0] * 32
    actual_addresses = []
    for index, instruction in enumerate(program.words):
        if instruction == 0x400B:
            break
        opcode = instruction & 0x7F
        rd = (instruction >> 7) & 31
        rs1 = (instruction >> 15) & 31
        rs2 = (instruction >> 20) & 31
        mode = (instruction >> 12) & 7
        if opcode == 0x37:
            scalar_regs[rd] = instruction & 0xFFFFF000
        elif opcode == 0x13 and mode == 0:
            scalar_regs[rd] = (scalar_regs[rs1] + signed(instruction >> 20, 12)) & 0xFFFFFFFF
        elif opcode == 0x7B:
            addresses = tuple(vector_regs[rs1])
            if addresses != program.workload.operations[index].addresses:
                raise ValueError("decoded addresses differ from timing IR")
            actual_addresses.append(addresses)
            if mode == 2:
                vector_regs[rd] = [memory[a] for a in addresses]
            elif mode == 6:
                for address, value in zip(addresses, vector_regs[rs2]):
                    memory[address] = value
            else:
                raise ValueError("unsupported memory encoding")
        elif opcode == 0x57:
            fn = instruction >> 26
            left = vector_regs[rs2][:]
            right = (
                vector_regs[rs1][:]
                if mode in (0, 1)
                else [scalar_regs[rs1]] * 32
                if mode == 4
                else [signed(rs1, 5) & 0xFFFFFFFF] * 32
            )
            if fn == 0x14 and mode == 2 and rs1 == 17:
                result = list(range(32))
            elif fn == 0x17 and mode == 4 and rs2 == 0:
                result = [scalar_regs[rs1]] * 32
            elif mode == 1 and fn in (0, 2):
                result = [
                    word(number(a) + number(b) if fn == 0 else number(a) - number(b))
                    for a, b in zip(left, right)
                ]
            elif mode == 1 and fn in (0x2C, 0x2F):
                old = vector_regs[rd][:]
                result = [
                    word(_fmaf(-number(a) if fn == 0x2F else number(a), number(b), number(c)))
                    for a, b, c in zip(left, right, old)
                ]
            elif fn == 0 and mode in (0, 3, 4):
                result = [(a + b) & 0xFFFFFFFF for a, b in zip(left, right)]
            elif fn == 2 and mode == 0:
                result = [(a - b) & 0xFFFFFFFF for a, b in zip(left, right)]
            elif fn == 0x09 and mode in (0, 3, 4):
                result = [a & b for a, b in zip(left, right)]
            elif fn == 0x0A and mode == 0:
                result = [a | b for a, b in zip(left, right)]
            elif fn == 0x25 and mode == 3:
                result = [(a << (b & 31)) & 0xFFFFFFFF for a, b in zip(left, right)]
            elif fn == 0x28 and mode == 3:
                result = [a >> (b & 31) for a, b in zip(left, right)]
            else:
                raise ValueError(f"unsupported instruction: {instruction:08x}")
            vector_regs[rd] = result
        else:
            raise ValueError(f"unsupported opcode: {instruction:08x}")
        scalar_regs[0] = 0
    return tuple(memory[0x90002000 + 4 * i] for i in range(len(program.expected))), actual_addresses
