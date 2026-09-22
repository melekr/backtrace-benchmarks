#!/usr/bin/env bash
# Unity lane wrapper used by bench-unity.yml after the test action ran versions A, B and the sentinel.
# Env: VERSION_A, VERSION_B, EDITOR, SOURCE, OUT (out/unity), GATE. Raw dirs: $OUT/raw/{a,b,sentinel}.
#   lane_unity.sh report
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cmd="${1:-report}"
VERSION_A="${VERSION_A:?}"; VERSION_B="${VERSION_B:?}"; SOURCE="${SOURCE:-openupm}"; OUT="${OUT:-out/unity}"
RUN_ID="${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"; ENV_JSON="${ENV_JSON:-env.json}"
mkdir -p "$OUT/rows" "$OUT/report"
[ -f "$ENV_JSON" ] || "$repo/scripts/env_fingerprint.sh" --tier tier1 --unity "${EDITOR:-}" > "$ENV_JSON"
convert() {  # convert <rawdir> <version> <variant>
  local d="$1" v="$2" variant="$3"
  local perf; perf=$(find "$d" -name 'PerformanceTestResults.json' | head -1 || true)
  [ -n "$perf" ] && python3 "$repo/unity/scripts/perf_results_to_rows.py" "$perf" --sdk-version "$v" --variant "$variant" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-platform.jsonl" || echo "no PerformanceTestResults.json under $d"
  find "$d" -name 'bench-result-*.json' | grep -q . && python3 "$repo/scripts/parse_bench_result.py" "$d" --sdk unity --sdk-version "$v" --variant "$variant" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-bench.jsonl" || true
  cat "$d"/rows-*.jsonl >> "$OUT/rows/micro.jsonl" 2>/dev/null || true
}
case "$cmd" in
  report)
    : > "$OUT/rows/micro.jsonl"
    convert "$OUT/raw/a" "$VERSION_A" sdk
    convert "$OUT/raw/b" "$VERSION_B" sdk
    [ -d "$OUT/raw/sentinel" ] && convert "$OUT/raw/sentinel" "$VERSION_B" sentinel
    "$repo/scripts/ci/lane_report_pr.sh" unity "$VERSION_A" "$VERSION_B" "$OUT" "$SOURCE"
    ;;
  *) echo "usage: lane_unity.sh report" >&2; exit 1;;
esac
