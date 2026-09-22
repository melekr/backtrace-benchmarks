#!/usr/bin/env bash
# CI-only: append rows and REPORT.md to the `results` branch. Runs in bench-release-report.yml when publish=true.
# Expects: out/report/rows/**.jsonl, out/report/REPORT.md, env SDK, GITHUB_ACTOR, a checkout with push credentials.
set -euo pipefail
SDK="${SDK:?}"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; RUN="${GITHUB_RUN_ID:-local}"
WT="out/results-branch"
git fetch origin results:refs/remotes/origin/results 2>/dev/null || true
rm -rf "$WT"; git worktree prune
if git show-ref --verify --quiet refs/remotes/origin/results; then
  git worktree add "$WT" -B results origin/results
else
  git worktree add --detach "$WT"
  git -C "$WT" checkout --orphan results
  git -C "$WT" rm -rf --quiet . || true
  printf '# Benchmark results\n\nRows and reports written by bench-release-report.yml.\n' > "$WT/README.md"
fi
DEST="$WT/results/$SDK"; mkdir -p "$DEST/runs/$STAMP-$RUN"
cp -R out/report/rows/. "$DEST/runs/$STAMP-$RUN/" 2>/dev/null || true
cp out/report/REPORT.md "$DEST/REPORT.md"
cp out/report/REPORT.md "$DEST/runs/$STAMP-$RUN/REPORT.md"
git -C "$WT" add -A
git -C "$WT" -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -q -m "results($SDK): ladder report from run $RUN" || { echo "nothing to commit"; exit 0; }
git -C "$WT" push origin HEAD:results
echo "published results/$SDK from run $RUN"
