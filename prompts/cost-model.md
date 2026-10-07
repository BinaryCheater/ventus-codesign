# Extend synthesis costs

Read README.md and docs/cost-model.md and workflows.md. Configure tools and private
machine paths through local.toml; avoid adding owner/server values to source.

Follow docs/area-budget.md and examples/project-baseline-v4.json for the current unified area policy. Multi-precision assumptions are fixed; do not block experiments on new precision RTL or calibration. Preserve v1/v2 and the independent-memory-budget historical results.

Extend only dimensions needed by an explicit hardware search menu. Inspect RTL
couplings and sampled synthesis points before adding coefficients. Collect fresh
component/full-SM points for missing RF capacities/ports, cache dimensions or
module interactions as needed. Keep logic area, memory bits, macro area, timing
closure and energy as distinct quantities. Never substitute zero for missing cost.

Pin source, tools, libraries, scripts and inputs; use new result directories.
Version coefficient changes and replay measurements. Verify supported menu costs
and rejection of unsupported points. Deliver a portable table/API, tests and a
short English report that separates measured coefficients from replication estimates.
