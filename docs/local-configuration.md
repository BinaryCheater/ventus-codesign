# Private machine configuration

`local.toml` is the single project-level profile for owner-specific settings.
Git ignores it, and the share command excludes it by an allowlist. Do not force-add
it. `local.example.toml` contains blank/portable defaults and is safe to share.
SSH credentials stay in the operating system's SSH setup, outside this project.

| Field | Purpose |
|---|---|
| `execution.mode` | Default `local` or `remote`; preserves each person's preferred machine |
| `remote.enabled`, `remote.host` | Explicit SSH enablement and the person's own SSH destination |
| `remote.run_root`, `remote.python`, `remote.uv` | Standalone server project and interpreter used during deployment |
| `remote.environment_script` | Optional toolchain setup before running on the server |
| `remote.project_root`, `remote.flow_root`, `remote.liberty_root` | Optional paths for new RTL/synthesis work |
| `owner.*` | Private owner paths/identifiers retained during extraction |
| `privacy.redactions` | Private literals that make a future share scan fail |

No profile means local execution. Requesting remote execution without an enabled,
complete profile fails before invoking SSH. The supplied owner's private profile
keeps server execution as the default. Collaborators receive no profile and choose
their own machine. Running direct Python model modules always uses the current
machine; use `ventus-project run` to select the configured default.

Historical paths use labels such as `${REMOTE_PROJECT_ROOT}`, `${REMOTE_FLOW_ROOT}`,
`${REMOTE_LIBERTY_ROOT}`, `${REMOTE_HOME}` and `${LOCAL_HOME}`. They identify origins
in evidence, without revealing locations. They are not automatically expanded
when a historical script is invoked. Supported execution reads TOML fields and
quotes command arguments; an AI adapting hardware scripts should do the same.

Share through `ventus-project share`, which scans the allowlisted files before
packaging. It normalizes archive owner metadata and excludes the profile, all Git
metadata, virtual environments, caches and new results. It also recreates the
relative `analysis` link. Re-run audit before distributing a changed project.
