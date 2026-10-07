# Compiled programs and native instruction execution

The simulator accepts programs, launch resources and dynamic instructions. No
timing-core dispatch depends on a model or kernel name. The Qwen runner organizes
kernel calls and buffer aliases; the official compiler produces their instructions,
and the native provider executes only control/address calculations. Tensor values
are unknown unless needed and explicitly supplied for control or addresses.

## Reproduce a complete task

Install Rust on the execution machine in addition to the Python environment.
The first evaluation builds a release library; subsequent evaluations reuse the
source-addressed build cache. No GPU, RTL build or SystemC installation is needed.
The checked-in ELF bundle supports reproduction without rebuilding LLVM:

```bash
./run --local model prepare-qwen --bundle tests/fixtures/compiled-transformer/bundle.json --phase prefill --context 128 --mapping packed64 --out results/qwen-p128-program-001
./run --local model instructions --input results/qwen-p128-program-001/program.json --hardware examples/baseline-hardware-v1.json --out results/qwen-p128-001 --budget 3600

./run --local model prepare-qwen --bundle tests/fixtures/compiled-transformer/bundle.json --phase prefill --context 512 --mapping packed64 --out results/qwen-p512-program-001
./run --local model instructions --input results/qwen-p512-program-001/program.json --hardware examples/baseline-hardware-v1.json --out results/qwen-p512-001 --budget 7200

./run --local model prepare-qwen --bundle tests/fixtures/compiled-transformer/bundle.json --phase decode --context 128 --steps 16 --mapping packed64 --out results/qwen-d128-program-001
./run --local model instructions --input results/qwen-d128-program-001/program.json --hardware examples/baseline-hardware-v1.json --out results/qwen-d128-001 --budget 7200

./run --local model prepare-qwen --bundle tests/fixtures/compiled-transformer/bundle.json --phase decode --context 512 --steps 16 --mapping packed64 --out results/qwen-d512-program-001
./run --local model instructions --input results/qwen-d512-program-001/program.json --hardware examples/baseline-hardware-v1.json --out results/qwen-d512-001 --budget 7200
```

These commands use [current baseline](baseline_cn.md), including the experiment memory target. Historical measurements are reference only, not a fresh baseline result. Precision timing constants remain fixed throughout search.

Every output directory must be new. Omit `--local` to honor the private profile's
daily execution default. These measurements explicitly override that default;
no private configuration or parent project has been changed.

Hardware JSON overrides use the same compiled manifest:

```bash
./run --local model instructions --input results/qwen-p128-program-001/program.json --hardware candidate-hardware.json --out results/qwen-p128-hardware-001 --budget 3600
```

Changing `--mapping scalar|packed|packed64` generates different programs,
addresses, packing dispatches and resource requirements. `packed` uses 16×16
MMA tiles. `packed64` shares operands across four output-column tiles and, where
appropriate, two row tiles; all distinct accumulator groups and compiler spills
remain timed. Lower instruction count need not imply lower GPU latency.

## Rebuild real software variants

Use official Ventus LLVM `dev-thu-sfu-mma` commit
`97df137e687669f9acf4bfd734779f52f2878614` and PyTorch `ventus` commit
`2b0e0cffbd4a46add6ec5f89bea665ce233c6b17`. Apply
`patches/llvm-initialize-divergence.patch` before building LLVM; it fixes a missing
analysis initialization and does not alter instruction selection. Paths below
are placeholders for the local checkout and build, not private machine settings.

```bash
./run --local model compile-model-kernels --official-kernels <pytorch>/aten/src/ATen/ventus/kernels --compiler-root <llvm-build> --llvm-source <llvm> --out results/kernel-bundle-001
./run --local model compile-kernel --source examples/kernels/vecadd_f32_pairs.cl --kernel vecadd_f32_pairs --compiler-root <llvm-build> --llvm-source <llvm> --out results/vecadd-pairs-001
```

Receipts retain source/compiler/ELF hashes, instructions and actual resource
metadata. The runtime reads RV32 ELF text, constants, symbols and Ventus resource
records. Dynamic register extensions, SIMT reconvergence, active masks, halfword
traffic and interleaved private spills use the official encodings. Unknown
numerical values used for branch/mask/address decisions fail explicitly.

## Frozen Qwen scenario

The official model configuration is frozen at Hugging Face revision
`7ae557604adf67be50417f59c2c2f167def9a775`: 24 layers, width 896, intermediate
width 4864, 14 query heads, 2 KV heads, head width 64 and vocabulary 151936.
Q/K/V have bias; output and feed-forward projections have no bias. Embedding
and the final projection share weights. The graph includes split-half RoPE,
RMSNorm, causal attention, softmax, both residuals, SwiGLU and final normalization.
Its configuration and reference-source receipt are in `examples/models/`.

BF16 operand and storage traffic is two bytes, packed fragments use 32-bit registers,
and MMA/reductions accumulate in FP32. Prefill computes hidden states for every
input position and logits for the last position. Each decode step appends one
token's K/V per layer and computes logits. No sampling or numerical tensor
evaluation is performed. Initial weights and input are already in external
memory; initial host transfer, weight loading and tokenization are excluded.

Prefill starts with cold caches and empty KV. Decode starts with cold caches and
the stated context's KV already in external memory, then preserves caches and
KV across all 16 steps. Seven query heads share each KV head. Buffers, dimensions,
layouts, ranges, KV bytes, aliases and ordered dependencies are in the manifest.

Official PyTorch BF16 embedding/advanced indexing and reductions require unsupported
fallbacks in the inspected backend. This runner selects explicit compiled device
variants for those operations. It includes their traffic and temporaries; it does
not claim to replay an unmodified PyTorch CPU-fallback execution.

## Timing and execution boundaries

`ventus-instruction-rust-v9-1` preserves the v7 operand collectors, scoreboard,
RF banks/ports, shared FADD/FMA path, elastic pipelines, LSU occupancy, LDS conflicts,
cache/MSHR and external-memory service. BF16/FP16/TF32 grouped MMA, packed arithmetic,
conversions, multiply/compare, shuffle and approximate SFU have an explicit timing
target. The eight timing values are centralized in each manifest, separately from
hardware parameters. Grouped MMA reads A/B/C register windows and writes all eight
accumulator registers through RF/writeback credits. Precision variants share the
configured Tensor resources; latency and initiation interval reflect the declared
array shape and packing capacity.

This is an uncalibrated extended-ISA target, not measured BF16 RTL timing.
Integer/address instructions currently use the scalar/vector timing classes;
dedicated integer multiply/divide-unit timing remains a specific accuracy gap.
The low-precision measured-cost query remains unsupported. Structural-v2 costs
are a separate, explicit approximation and cannot be presented as measurements.
Instruction fetch, host launch and complete flush/visibility protocols remain
outside the source-validated core interval. There is no full-network RTL error bound.

Streaming ELF execution currently supports one 32-lane warp per block. Generic
compact instructions retain the existing multi-warp barrier path. A compiled
multi-warp barrier frontend and general numerical/data-dependent functional
execution remain incomplete. Official FP16 and TF32 kernels have executable
fixtures, but full Pythia's LayerNorm/partial-RoPE/parallel-residual program launcher
and a full compiled GPT-2 launcher remain separate unfinished frontends.

## Speed, state and audit

The executor retains resident block instructions, not a network-sized event DAG.
It recycles live instruction slots, per-block index/scoreboard buffers and cycle
scratch space, uses numeric resource keys and direct unit indices, skips expired
reservation prefixes, and advances free pipelines with a ring buffer. Per-line
subscriber history is released after L1 eviction has waited for the prior fill;
an evicted line can no longer merge another request. Idle jumps stop at the first
event/output and preserve elastic backpressure. No layer's cycles are multiplied
to approximate another layer or decode step.

`experiment.json` contains completion, cycles, host time, build/load time, process
peak RSS, dynamic instruction/traffic/resource counters, per-dispatch resources,
and per-phase/per-decode-step totals. Process RSS includes the Python coordinator.
It is a per-process high-water measurement, not live device-memory allocation.
The progress stream and append-only `stages.jsonl` expose the current bottleneck.

Recovery is supported at complete fenced dispatches only. A checkpoint includes
cache tags and replacement state, counters and cycle offset, bound to the native
source/runtime, hardware, target, input and hashed journal prefix. It contains no
unfinished kernel. Periodic checkpoints are about 30 host seconds apart; a failed
run may have extra completed journal entries after its latest recovery point.
Those entries are re-executed on resume. Keep the entire previous result directory:

```bash
./run --local model instructions --input results/qwen-p128-program-001/program.json --resume results/qwen-p128-001/checkpoint.json --out results/qwen-p128-resumed-001 --budget 3600
```

Do not edit the runtime between checkpoint and resume. A different runtime is
rejected rather than continuing with an empty or incompatible cache state.

For an executor-only comparison, the stable native ABI utility measures one cold,
complete dispatch using an optional preserved library:

```bash
uv run python -m codesign.ventus.benchmark_native --input results/qwen-p128-program-001/program.json --dispatch prefill.lm_head --out results/native-lm-001
```

The evidence directory linked from status records actual whole-task timings,
unchanged-program comparisons and hardware sensitivity. Its numbers are model
predictions and host measurements. Existing SystemC failures remain in the archived
accuracy study; no whole-Qwen SystemC host-time measurement or accuracy bound exists,
and no new SystemC/RTL benchmark is required for this instruction path.

## Software compatibility during hardware search

The compiler wrapper targets a fixed Ventus ISA and takes no hardware JSON.
Resource-only changes reuse an ELF if its launch fits; smaller register/LDS pools
change residency, and a block that cannot fit must be rejected or replaced by a
lower-resource software variant. There is no automatic per-hardware tiling,
register-budget recompilation or general kernel replacement pass. The project does
not require building one: agents may write and integrate software variants for
selected hardware, then compile and check their actual resource requirements.

Edit OpenCL in `examples/kernels/` and the calls/buffers in `model_program.py` to
add software variants. Compile them and use their recorded resource requirements.
Within the modeled Tensor menu, grouped MMA keeps its instruction semantics and
uses array dimensions for service time; this does not establish compatibility
with an unmodified upstream RTL. Threads, ISA and ABI remain fixed in this task.
The performance-only executor does not prove numerical correctness of new kernels.

GPT-2 retains the older `transformer --preset gpt2` template frontend. The complete
compiled-ELF network launcher exists for Qwen only; GPT-2 and Pythia launchers are
still absent in this checkout. FP16/TF32 kernel fixtures do not fill that gap.

Agents also derive the optimization abstraction from source and compiled programs:
software choices, instruction work, memory traffic, dependencies and resource
constraints. Bind those abstractions to source/artifact versions, distinguishing
compiler-reported facts from estimates. MIP selects a design; implement that
design and evaluate its actual program with the instruction simulator, using
discrepancies to refine the abstraction.
