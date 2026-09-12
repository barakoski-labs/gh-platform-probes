# gh-platform-probes

Small, standalone scripts for probing observable GitHub platform behavior —
pull request file listings, merge strategies, branch protection, required
status checks, deployments — for feasibility research.

This repository contains **probe scripts and fixtures only**: no product code,
no design documents, no specification text. Each script is self-contained,
reads its target repository/PR/run from arguments or environment variables,
and writes its raw observation to `fixtures/` as JSON so a result can be
inspected or diffed later without re-running the probe.

## Layout

- `probes/` — one script per platform question being probed. Each script's
  header comment states exactly what it observes and why.
- `fixtures/` — captured output from probe runs. Not curated or asserted
  against anything; a record of what the platform actually returned.

## Running a probe

Each script is invoked directly and requires the GitHub CLI (`gh`) to be
authenticated:

```
./probes/<script-name>.sh <args>
```

Output is printed and also written to `fixtures/<script-name>_<timestamp>.json`.

## Scope

Nothing in this repository asserts what the *correct* platform behavior should
be — these scripts only observe and record what the platform actually does.
