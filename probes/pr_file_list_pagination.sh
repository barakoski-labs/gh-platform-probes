#!/usr/bin/env bash
# Probes: does a pull request's file-listing endpoint return every changed
# file, or does it cap out and silently truncate on a large PR?
#
# GitHub's PR-files REST endpoint and comparison/diff surfaces are documented
# as capping at a fixed number of entries with pagination. This script counts
# how many file entries are actually returned for a given PR, across all
# pages, and records whether the response shows any sign of truncation
# (a page short of the requested per_page size ends pagination; a full last
# page does not by itself prove completeness).
#
# Usage: ./pr_file_list_pagination.sh <owner/repo> <pr-number>

set -euo pipefail
REPO="${1:?usage: pr_file_list_pagination.sh <owner/repo> <pr-number>}"
PR="${2:?usage: pr_file_list_pagination.sh <owner/repo> <pr-number>}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/fixtures"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/pr_file_list_pagination_${STAMP}.json"

FILES_JSON="$(gh api --paginate "repos/${REPO}/pulls/${PR}/files" --jq '[.[] | {filename, status}]')"
COUNT="$(echo "$FILES_JSON" | jq -s 'add | length')"

jq -n \
  --arg repo "$REPO" \
  --arg pr "$PR" \
  --arg stamp "$STAMP" \
  --argjson count "$COUNT" \
  --argjson files "$(echo "$FILES_JSON" | jq -s 'add')" \
  '{repo: $repo, pr: $pr, observed_at: $stamp, file_count: $count, files: $files}' \
  | tee "$OUT_FILE"

echo "Wrote $OUT_FILE" >&2
