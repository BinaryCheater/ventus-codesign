# Build a reproducible optimization case

Read the English project docs, existing finite-menu event MILP and cost wrapper.
Use local.toml for the default execution machine and let AI prepare its environment.

Fix a small Transformer semantic workload (start from examples/tiny-transformer.json).
Construct a cost-supported hardware menu and meaningful software warp/dispatch
choices. Regenerate each concrete instruction graph/address map; preserve the
mathematical work. Implement the missing complete-Transformer experiment wrapper.

Optimize latency under logic-area and separate memory-bit budgets. Distinguish
the candidate-selection formulation from a structural MILP; record status, bound,
gap and exactly which finite space supports an optimality claim. Compare with
exhaustive enumeration, a strong fixed-hardware software baseline and a fixed-
software hardware baseline. Verify selected candidates independently in the fast
executor, then use targeted RTL to test ranking on changed mechanisms.

Report a compact tradeoff table/Pareto plot, runtime, feasible/unsupported points,
model uncertainty and realized versus hypothetical hardware changes. Preserve
versions and original hashes; never overwrite saved results. Do not label modeled
cycles as hardware measurements or local kernel accuracy as full-network accuracy.
