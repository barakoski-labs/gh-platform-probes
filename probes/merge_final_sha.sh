#!/usr/bin/env bash
# Probes: after a pull request merges, what SHA does the platform report as
# the "landed" commit under each merge strategy (merge commit, squash,
# rebase), and what does that commit's first-parent chain look like?
#
# This matters for anything that needs to evaluate "the exact commit that
# landed" after the fact — squash and rebase both rewrite history, so the
# head SHA a reviewer approved is not the SHA that ends up on the base
# branch. This script records the merge_commit_sha GitHub reports and the
# immediate parent SHAs of that commit, so the two can be compared for a
# merged PR of known strategy.
#
# Usage: ./merge_final_sha.sh <owner/repo> <pr-number>

set -euo pipefail
REPO="${1:?usage: merge_final_sha.sh <owner/repo> <pr-number>}"
PR="${2:?usage: merge_final_sha.sh <owner/repo> <pr-number>}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/fixtures"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/merge_final_sha_${STAMP}.json"

PR_JSON="$(gh api "repos/${REPO}/pulls/${PR}" --jq '{merged, merge_commit_sha, head_sha: .head.sha, base_sha: .base.sha}')"
MERGE_SHA="$(echo "$PR_JSON" | jq -r '.merge_commit_sha')"

if [ "$MERGE_SHA" = "null" ]; then
  echo "PR ${PR} has no merge_commit_sha (not merged, or merge_commit_sha unset)." >&2
  echo "$PR_JSON" | tee "$OUT_FILE"
  exit 0
fi

PARENTS_JSON="$(gh api "repos/${REPO}/commits/${MERGE_SHA}" --jq '[.parents[].sha]')"

jq -n \
  --arg repo "$REPO" \
  --arg pr "$PR" \
  --arg stamp "$STAMP" \
  --argjson pr_info "$PR_JSON" \
  --argjson parents "$PARENTS_JSON" \
  '{repo: $repo, pr: $pr, observed_at: $stamp} + $pr_info + {landed_commit_parents: $parents}' \
  | tee "$OUT_FILE"

echo "Wrote $OUT_FILE" >&2
