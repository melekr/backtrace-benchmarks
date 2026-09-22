#!/usr/bin/env bash
# Apple lane wrapper used by bench-apple.yml. Env: VERSIONS (older,newer), SOURCE (xcframework|spm|local), ROUNDS,
# ITERATIONS, METRIC_SETS (size,init,micro), OUT (out/apple), SIM_UDID, GATE.
#   lane_apple.sh all | build | run | thinning | report
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cmd="${1:-all}"; shift || true
VERSIONS="${VERSIONS:?}"; SOURCE="${SOURCE:-xcframework}"; ROUNDS="${ROUNDS:-3}"; ITERATIONS="${ITERATIONS:-10}"
METRIC_SETS="${METRIC_SETS:-size,init,micro}"; OUT="${OUT:-out/apple}"; RUN_ID="${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"
ENV_JSON="${ENV_JSON:-env.json}"; LOCAL_PATH="${LOCAL_PATH:-sdk-src}"
driver="$repo/apple/scripts/bench_apple.sh"; parser="$repo/apple/scripts/xcresult_to_rows.py"
IFS=',' read -r -a vlist <<< "$VERSIONS"; newest="${vlist[$((${#vlist[@]} - 1))]}"; oldest="${vlist[0]}"
has() { case ",$METRIC_SETS," in *",$1,"*) return 0;; *) return 1;; esac; }
mkdir -p "$OUT/rows" "$OUT/raw" "$OUT/report"
[ -f "$ENV_JSON" ] || "$repo/scripts/env_fingerprint.sh" --tier tier1 > "$ENV_JSON"
udid="${SIM_UDID:-}"; dev=(); [ -n "$udid" ] && dev=(--udid "$udid")
local_flag=(); [ "$SOURCE" = "local" ] && local_flag=(--local-path "$LOCAL_PATH")

# One rendered project per SDK version: build all variants, then run per-version lanes. Versions are interleaved
# per round by run_ab_rounds.sh, which re-renders through the driver's prepare step.
build_all() {
  for v in "${vlist[@]}"; do
    "$driver" prepare --version "$v" --source "$SOURCE" ${local_flag[@]+"${local_flag[@]}"}
    for variant in plain sdk sentinel; do
      set +e; "$driver" build --version "$v" --variant "$variant" ${dev[@]+"${dev[@]}"} --out "$OUT/raw/build-$v"; rc=$?; set -e
      [ $rc -eq 4 ] && { echo "unsupported: $v"; break; }
      [ $rc -eq 0 ] || exit $rc
      if has size && { [ "$variant" != "plain" ] || [ "$v" = "$newest" ]; }; then
        "$driver" size --version "$v" --variant "$variant" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/raw/size-$v"
      fi
    done
  done
  cat "$OUT"/raw/size-*/rows-size-*.jsonl > "$OUT/rows/size.jsonl" 2>/dev/null || true
}
run_all() {
  if has init; then
    "$repo/scripts/run_ab_rounds.sh" --sdk apple --driver "$driver" --parser "$parser" --versions "$VERSIONS" --plain --sentinel \
      --rounds "$ROUNDS" --iterations "$ITERATIONS" --metric-set init --source "$SOURCE" ${udid:+--device "$udid"} --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/raw/init"
    cp "$OUT/raw/init/rows.jsonl" "$OUT/rows/init.jsonl"
  fi
  if has micro; then
    for v in "${vlist[@]}"; do
      d="$OUT/raw/micro/$v"; mkdir -p "$d"
      "$driver" prepare --version "$v" --source "$SOURCE" ${local_flag[@]+"${local_flag[@]}"} >/dev/null
      "$driver" run --metric-set micro --version "$v" --variant sdk ${dev[@]+"${dev[@]}"} --out "$d"
      python3 "$parser" "$d/micro.xcresult" --sdk-version "$v" --variant sdk --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-platform.jsonl" || true
      ls "$d"/bench-result*.json >/dev/null 2>&1 && python3 "$repo/scripts/parse_bench_result.py" "$d" --sdk apple --sdk-version "$v" --variant sdk --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-bench.jsonl" || true
      cat "$d"/rows-*.jsonl >> "$OUT/rows/micro.jsonl" 2>/dev/null || true
    done
  fi
}
case "$cmd" in
  build) build_all;;
  run) run_all;;
  all) build_all; run_all;;
  thinning)
    "$driver" prepare --version "$newest" --source "$SOURCE" ${local_flag[@]+"${local_flag[@]}"} >/dev/null
    vid="v$(echo "$newest" | tr '.-' '__')"
    "$repo/scripts/ci/apple_thinning.sh" --project "$repo/apple/BenchApp.xcodeproj" --scheme BenchApp-sdk --bundle-id "io.backtrace.bench.sdk.$vid" \
      --sdk-version "$newest" --variant sdk --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/rows/thinning-sdk.jsonl"
    "$repo/scripts/ci/apple_thinning.sh" --project "$repo/apple/BenchApp.xcodeproj" --scheme BenchApp-plain --bundle-id "io.backtrace.bench.plain.$vid" \
      --sdk-version "$newest" --variant plain --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/rows/thinning-plain.jsonl"
    ;;
  report) "$repo/scripts/ci/lane_report_pr.sh" apple "$oldest" "$newest" "$OUT" "$SOURCE";;
  *) echo "usage: lane_apple.sh all|build|run|thinning|report" >&2; exit 1;;
esac
