# Project collaboration

Read README.md, docs/status.md, docs/model.md, then docs/workflows.md.
All maintained documentation is English. Historical records live in archive/.

- Keep owner/server details only in ignored local.toml. Refer to configuration fields
  in code and docs; never add hostnames, usernames, SSH keys or owner absolute paths.
- Honor the user's local.toml execution default. No profile means local execution;
  a remote profile means SSH execution. Do not invent or contact another person's server.
- Let AI configure the environment using docs/workflows.md. Timing/cost queries do
  not require Scala, Verilator or synthesis tools.
- Never overwrite result directories. Replay frozen experiments read-only with --verify.
- Keep original versions and hashes in archive/export-manifest.json. The archive is
  a privacy-sanitized export; hashes refer to the exported bytes unless labelled original.
- When timing/cost semantics change, version the model and update status, mechanisms,
  cost evidence and validation docs. Preserve old experiment snapshots.
- Treat finite-menu optimality, model timing, RTL timing and hardware measurements
  as distinct claims. Local kernel errors are not a full-network error guarantee.
- Keep solver constraints out of independent verification code; validate after overrides.
- Use Ruff for Python. Run ruff check, ruff format --check and pytest for relevant changes.
- Historical scripts are reference material. Use the configuration-aware entry point
  for execution; migrate old hardware scripts before adding them to a supported workflow.
