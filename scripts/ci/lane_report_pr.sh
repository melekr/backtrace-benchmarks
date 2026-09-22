#!/usr/bin/env bash
# Shared per-job report: split rows by variant/version, run compare.py pr (older vs newer, plain, sentinel) and
# overhead (plain vs newest), write markdown for the step summary and the PR comment, exit with the gate code when GATE=1.
#   lane_report_pr.sh <sdk> <older> <newer> <OUT> [<source>]
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sdk="$1"; older="$2"; newer="$3"; OUT="$4"; source="${5:-}"
mkdir -p "$OUT/report"
all="$OUT/rows/all.jsonl"; cat "$OUT"/rows/*.jsonl 2>/dev/null | grep -v '^$' > "$all" || true
[ -s "$all" ] || { echo "no rows under $OUT/rows"; exit 1; }
python3 - "$all" "$OUT/report" "$older" "$newer" <<'PY'
import json, sys
rows_path, out, older, newer = sys.argv[1:5]
buckets = {"base": [], "head": [], "plain": [], "sentinel": []}
for line in open(rows_path):
    r = json.loads(line)
    v, var = r.get("sdkVersion"), r.get("variant")
    if var == "plain": buckets["plain"].append(r)
    elif var == "sentinel": buckets["sentinel"].append(r)
    elif var == "sdk" and v == newer: buckets["head"].append(r)
    elif var == "sdk" and v == older: buckets["base"].append(r)
for k, rs in buckets.items():
    with open(f"{out}/rows-{k}.jsonl", "w") as f:
        for r in rs: f.write(json.dumps(r) + "\n")
    print(f"{k}: {len(rs)} rows")
PY
args=(pr --base "$OUT/report/rows-base.jsonl" --head "$OUT/report/rows-head.jsonl" --format md --out "$OUT/report/pr-comment.md")
[ -s "$OUT/report/rows-plain.jsonl" ] && args+=(--plain "$OUT/report/rows-plain.jsonl")
[ -s "$OUT/report/rows-sentinel.jsonl" ] && args+=(--sentinel "$OUT/report/rows-sentinel.jsonl")
[ "${GATE:-0}" = "1" ] && args+=(--gate)
[ "$older" = "$newer" ] && args=(overhead --plain "$OUT/report/rows-plain.jsonl" --head "$OUT/report/rows-head.jsonl" --format md --out "$OUT/report/pr-comment.md")
set +e
python3 "$repo/scripts/compare.py" "${args[@]}" >/dev/null; rc=$?   # the markdown is read back from --out below
set -e
{ echo "## $sdk: $older → $newer"; echo; cat "$OUT/report/pr-comment.md"; } 
python3 "$repo/scripts/compare.py" "${args[@]}" --format json --out "$OUT/report/pr-comparison.json" >/dev/null 2>&1 || true
exit $rc
