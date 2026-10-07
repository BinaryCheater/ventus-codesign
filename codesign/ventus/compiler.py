"""Compile real OpenCL kernels with a configured official Ventus LLVM checkout."""

import hashlib
import json
import subprocess
from time import perf_counter

from .elf import ELFProgram


def compile_kernel(source, kernel, compiler_root, llvm_source, out, *, optimization="O1"):
    if optimization not in {"O1", "O2", "O3"}:
        raise ValueError("unsupported optimization level")
    compiler_root, llvm_source = compiler_root.resolve(), llvm_source.resolve()
    clang, objdump = compiler_root / "bin/clang", compiler_root / "bin/llvm-objdump"
    workitem = llvm_source / "libclc/riscv32/lib/workitem"
    helpers = sorted(workitem.glob("*.cl"))
    if not clang.is_file() or not objdump.is_file() or not helpers:
        raise ValueError("official Ventus compiler or workitem sources absent")
    out.mkdir()
    source = source.resolve()
    begin = perf_counter()
    target = [str(clang), "-target", "riscv32", "-mcpu=ventus-gpgpu"]
    assembly = out / "workitem.o"
    commands = [
        [
            *target,
            "-I" + str(workitem.parent),
            "-c",
            str(workitem / "workitem.S"),
            "-o",
            str(assembly),
        ],
        [
            *target,
            "-cl-std=CL2.0",
            "-" + optimization,
            "-I" + str(llvm_source / "libclc/generic/include"),
            "-nodefaultlibs",
            "-fuse-ld=lld",
            "--ld-path=" + str(compiler_root / "bin/ld.lld"),
            "-Wl,-T," + str(llvm_source / "utils/ldscripts/ventus/elf32lriscv.ld"),
            "-Wl,-e," + kernel,
            str(source),
            *map(str, helpers),
            str(assembly),
            "-o",
            str(out / "program.elf"),
        ],
        [str(objdump), "-d", "--mattr=+v,+zfinx", str(out / "program.elf")],
    ]
    logs = []
    status = 0
    for command in commands:
        result = subprocess.run(command, capture_output=True)
        logs.append(result.stderr.decode(errors="replace"))
        status = result.returncode
        if status:
            break
        if command[0] == str(objdump):
            (out / "program.dump").write_bytes(result.stdout)
    # This output is an ignored build directory. Portable receipts bind bytes
    # and use symbolic paths; diagnostics remain local to the build machine.
    (out / "build.log").write_text("\n".join(logs))
    sources = [source, *helpers, workitem / "workitem.S", workitem.parent / "ventus.h"]
    receipt = {
        "completed": status == 0,
        "exit_code": status,
        "kernel": kernel,
        "target": "riscv32/ventus-gpgpu",
        "optimization": optimization,
        "host_seconds": perf_counter() - begin,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "compiler_sha256": hashlib.sha256(clang.read_bytes()).hexdigest(),
    }
    if status == 0:
        program = ELFProgram.read(out / "program.elf")
        receipt.update({"elf_sha256": program.sha256, "resources": program.resources})
        if kernel not in program.resources or kernel not in program.symbols:
            status = 1
            receipt.update(
                {"completed": False, "exit_code": 1, "error": "requested kernel entry absent"}
            )
    (out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if status:
        raise ValueError("official kernel compilation failed; see the new result's build.log")
    print(json.dumps({"out": str(out), "completed": True, "elf_sha256": receipt["elf_sha256"]}))
