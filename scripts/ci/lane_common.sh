#!/usr/bin/env bash
# Shared by scripts/ci/lane_*.sh (sourced after OUT is set). A failed per-version pass (micro, macro) is retried once,
# then recorded in $OUT/report/lane-failures.md; the lane continues with the remaining cells and finish_lane exits 1
# only after every other pass has run, so the report and artifact steps still see all completed rows.
# Bash 3.2 compatible (macOS runners).
lane_failed=0

lane_failures_file() { echo "${LANE_FAILURES:-$OUT/report/lane-failures.md}"; }

# run_with_retry <label> <command...>: returns 0 on the first success, otherwise records the failure and returns 1.
run_with_retry() {
  local label="$1"; shift
  local attempt rc=1
  for attempt in 1 2; do
    set +e; "$@"; rc=$?; set -e
    [ "$rc" -eq 0 ] && return 0
    echo "lane: $label failed (rc=$rc, attempt $attempt/2)" >&2
  done
  local f; f="$(lane_failures_file)"
  mkdir -p "$(dirname "$f")"
  echo "- \`$label\`: exit code $rc after 2 attempts (no rows from this pass; raw output kept under \`$OUT/raw\`)" >> "$f"
  lane_failed=1
  return 1
}

# finish_lane: call last; fails the step when any pass was recorded as failed.
finish_lane() {
  if [ "$lane_failed" -ne 0 ]; then
    echo "lane: one or more passes failed, see $(lane_failures_file)" >&2
    exit 1
  fi
}
