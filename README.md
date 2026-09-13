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

## Deployment identity probes

- `probes/deployment-identity-probe.py` — observe creation, identity,
  status changes, independent reads, and deletion through direct REST.

  ```sh
  python3 probes/deployment-identity-probe.py --repo OWNER/NAME --token-env GH_PROBE_TOKEN --environment probe-env-a --out-dir OUTPUT_DIR --steps 1,2,3,4a,6
  ```

- `probes/deployment-identity-compare.py` — compare one deployment through
  direct REST, `gh api`, and a selected GraphQL node, including a field diff.

  ```sh
  python3 probes/deployment-identity-compare.py --repo OWNER/NAME --deployment-id ID --out-dir OUTPUT_DIR
  ```

Both scripts use only Python standard-library modules. The comparison also
requires the `gh` executable and reads `GH_TOKEN` (preferred) or `GITHUB_TOKEN`
so every authenticated call uses the same credential. Set tokens in the
environment before invocation; never pass their values as arguments.

Use an empty output directory for each run. Each HTTP response has the same
`http_status` and `response_body` wrapper; JSON body text is embedded unchanged,
and non-JSON bodies are stored as strings. A 204 response has an empty string
body. HTTP failures are saved too; a transport failure has no HTTP response
to save and exits with an error. Credential-bearing responses are refused
instead of written. These scripts perform mutations and leave deployments
behind; only step 6 attempts deletion of its dedicated throwaway deployment.

The main probe resolves the default branch to a SHA with two recorded setup
calls. Creation disables automatic merging and required status contexts.
Steps run in numerical order. Steps 3 and 5 create A if earlier steps did not;
step 4a alone creates one deployment and checks its saved creator fields.
Use `--steps 1,2,4a` for a narrower run. Include step 5 for unauthenticated
reads and optionally add `--reader-token-env GH_PROBE_READER_TOKEN` for a
distinct reader credential. Without that option a separate not-run note is
written, which is not an HTTP response.

Step 6 first attempts deletion without an inactive status. On rejection it
records an inactive status attempt and a second deletion attempt separately;
the HTTP responses show whether the change enabled deletion. Rejection does
not fail the run. No conclusion about the cause is inferred automatically.

The comparison saves complete response bodies, including the GraphQL envelope.
`field-diff.json` compares literal nested field paths within each deployment
object; GraphQL names and its explicit selection differ from REST, so missing
fields are not proof of schema absence. HTTP metadata for CLI responses comes
from `gh api --include`; CLI diagnostic text is never substituted for a body.

`.github/workflows/deployment-identity-probe.yml` runs on manual dispatch,
creates one deployment in `probe-env-a` with the built-in workflow token,
and uploads response files with `actions/upload-artifact`.
`fixtures/deployment-identity-expected-fields.json` lists documented, untested
expectations and source URLs. Neither the scripts nor workflow have been run
against GitHub as part of this addition.
