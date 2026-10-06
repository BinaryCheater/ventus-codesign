"""Freeze multi-warp numerical GEMM and both RF configurations before RTL.

The modeled window ends at the final Tensor writeback. The output epilogue
reads the upstream thread-id CSR and writes a separate 128-byte slice per warp.
Host launch, instruction fetch and the output epilogue are outside this window.
"""

import argparse
import hashlib
import json
from dataclasses import asdict, replace

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Workload
from codesign.ventus.program import packed_gemm, vector
from codesign.ventus.timing import build_graph


def generate(root, batch):
    dest = root / batch
    dest.mkdir()
    cases = []
    for warps in [2, 4, 8]:
        for steps in [8, 32]:
            program = packed_gemm(steps, strategy="resident")
            prefix = (program.final_tensor_pc - 0x80000000) // 4 + 1
            # x17 <- CSR.threadid (warp*32), then bytes = threadid*4.
            tail = (
                0x90002137,
                vector(0x14, 0, 17, 2, 14),
                vector(0x25, 14, 2, 3, 14),
                vector(0, 14, 2, 4, 14),
                (0x800 << 20) | (2 << 12) | (17 << 7) | 0x73,
                (2 << 20) | (17 << 15) | (1 << 12) | (17 << 7) | 0x13,
                vector(0, 14, 17, 4, 14),
                (1 << 20) | (14 << 15) | (6 << 12) | 0x7B,
                0x400B,
            )
            words = program.words[:prefix] + tail
            streams = program.workload.operations[:prefix]
            workload = Workload(
                tuple(
                    replace(op, name=f"w{warp}.{op.name}", warp=warp)
                    for op in streams
                    for warp in range(warps)
                ),
                warps_per_block=warps,
                lds_per_block=0,
            )
            name = f"resident-w{warps}-k{steps * 8}"
            path = dest / name
            replaced = replace(program, words=words)
            replaced.write(path, root / "kernel-probes-v3/stream-4-rf0-lds1/input")
            lines = (path / "input.metadata").read_text().splitlines()
            meta = [
                int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)
            ]
            data = [int(x, 16) for x in (path / "input.data").read_text().splitlines()]
            count = meta[13]
            sizes = meta[14 + count : 14 + 2 * count]
            pos = meta[14 : 14 + count].index(0x90002000)
            offset = sum(sizes[:pos]) // 4
            data[offset : offset + sizes[pos] // 4] = [0] * (32 * warps)
            meta[6] = warps
            meta[14 + count + pos] = meta[14 + 2 * count + pos] = 128 * warps
            (path / "input.metadata").write_text(
                "".join(f"{x & 0xFFFFFFFF:08x}\n{x >> 32:08x}\n" for x in meta)
            )
            (path / "input.data").write_text("".join(f"{x:08x}\n" for x in data))
            predictions = []
            for banks in [4, 8]:
                hardware = Hardware().with_changes(rf_banks=banks)
                graph = build_graph(workload, hardware)
                result = execute(graph)
                predictions.append(
                    dict(
                        hardware=hardware.to_dict(),
                        cycles=result["cycles"],
                        per_warp=[
                            result["times"][
                                graph.names.index(
                                    f"w{warp}.pc{program.final_tensor_pc:08x}.writeback"
                                )
                            ]
                            for warp in range(warps)
                        ],
                    )
                )
            cases.append(
                dict(
                    name=name,
                    warps=warps,
                    steps=steps,
                    words=list(words),
                    expected_words=list(program.expected) * warps,
                    final_tensor_pc=program.final_tensor_pc,
                    modeled_prefix_instructions=prefix,
                    workload=asdict(workload),
                    predictions=predictions,
                    input_sha256={
                        name: hashlib.sha256((path / name).read_bytes()).hexdigest()
                        for name in ["input.metadata", "input.data"]
                    },
                )
            )
    (dest / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    frozen = dict(
        version=MODEL_VERSION,
        code_sha256=model_hashes(),
        timing_window="first collector admission -> last Tensor writeback across all warps",
        initial_state="SRAM reset finished; cold caches; launch gated to cycle 512",
        output_layout="private 128-byte output slice per warp, CSR.threadid-derived",
        cases=cases,
    )
    (dest / "pre_run_predictions.json").write_text(json.dumps(frozen, indent=2) + "\n")
    print(json.dumps([{k: case[k] for k in ["name", "predictions"]} for case in cases]))


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--batch", required=True)
    args = parser.parse_args()
    generate(args.root, args.batch)
