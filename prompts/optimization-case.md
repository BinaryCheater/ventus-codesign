# Implement the standalone Ventus optimization case

Read docs/baseline_cn.md, docs/project_tasks_cn.md and docs/area-budget.md. They
fully define the experiment; no other conversation is required. Honor local.toml.
Use Qwen prefill 128/512 and decode-context128/512 for 16 steps, packed64 reference
software, the frozen baseline hardware, and the unified total-area constraint.
All participants complete the three objectives and five optimization controls.
GPT-2/Pythia are optional transfer extensions until their launchers are complete.

Keep multi-precision modes and timing assumptions fixed. Use the 27 hardware
fields within supported ranges and actual compiled-program capabilities; do not
introduce multi-warp/block software mappings into the currently single-warp/block
ELF frontend. Construct MIP resource/software couplings and use representative
kernels/subgraphs to screen candidates before full-network final evaluations.
Use add_unified_area_constraints and decode_unified_solution, not the historical
dual-budget adapter defaults. Record solver status, gap, actual evaluation costs
and the finite/model scope of optimality. Preserve failures and source/config hashes.
No per-candidate RTL or new multi-precision circuitry is required. Do not claim
physical chip area, timing closure or measured full-network accuracy.
