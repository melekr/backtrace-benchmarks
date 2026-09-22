#!/usr/bin/env bash
# Android lane wrapper used by bench-android.yml. Env: VERSIONS (older,newer), SOURCE (maven|local), LOCAL_VERSION,
# ROUNDS, ITERATIONS, METRIC_SETS (size,init,micro,macro), SCENARIO, OUT (out/android), GATE (1 => compare --gate).
#   lane_android.sh build   : build plain + every version + sentinel (with test APKs), measure sizes
#   lane_android.sh run     : interleaved rounds on the attached emulator (init), then micro and macro per version
#   lane_android.sh report  : rows -> pr comparison (older vs newer, plain, sentinel) + step summary markdown
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cmd="${1:-}"; shift || true
VERSIONS="${VERSIONS:?}"; SOURCE="${SOURCE:-maven}"; ROUNDS="${ROUNDS:-3}"; ITERATIONS="${ITERATIONS:-15}"
METRIC_SETS="${METRIC_SETS:-size,init,micro,macro}"; SCENARIO="${SCENARIO:-default}"; OUT="${OUT:-out/android}"
RUN_ID="${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"; ENV_JSON="${ENV_JSON:-env.json}"
driver="$repo/android/scripts/bench_android.sh"; parser="$repo/android/scripts/benchmarkdata_to_rows.py"
[ "$SOURCE" = "local" ] && [ -n "${LOCAL_VERSION:-}" ] && VERSIONS="$LOCAL_VERSION"
IFS=',' read -r -a vlist <<< "$VERSIONS"; newest="${vlist[$((${#vlist[@]} - 1))]}"; oldest="${vlist[0]}"
has() { case ",$METRIC_SETS," in *",$1,"*) return 0;; *) return 1;; esac; }
mkdir -p "$OUT/rows" "$OUT/raw" "$OUT/report"
[ -f "$ENV_JSON" ] || "$repo/scripts/env_fingerprint.sh" --tier tier1 > "$ENV_JSON"
export BT_GRADLE_ARGS="${BT_GRADLE_ARGS:---no-daemon -q}"

case "$cmd" in
  build)
    [ "$SCENARIO" = "largeapk" ] && "$driver" prepare --version "$newest" --scenario largeapk
    "$driver" build --version "$newest" --variant plain --scenario "$SCENARIO" --source "$SOURCE"
    for v in "${vlist[@]}"; do "$driver" build --version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --with-tests; done
    "$driver" build --version "$newest" --variant sentinel --scenario "$SCENARIO" --source "$SOURCE"
    if has size; then
      "$driver" size --version "$newest" --variant plain --scenario "$SCENARIO" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/raw/size-plain"
      for v in "${vlist[@]}"; do "$driver" size --version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/raw/size-$v"; done
      cat "$OUT"/raw/size-*/rows-size-*.jsonl > "$OUT/rows/size.jsonl"
    fi
    ;;
  run)
    serial="${ANDROID_SERIAL:-$("$HOME/Library/Android/sdk/platform-tools/adb" devices 2>/dev/null | grep -E 'device$' | head -1 | cut -f1 || true)}"
    [ -n "$serial" ] || serial="$(adb devices | grep -E 'device$' | head -1 | cut -f1)"
    if has init; then
      "$repo/scripts/run_ab_rounds.sh" --sdk android --driver "$driver" --parser "$parser" --versions "$VERSIONS" --plain --sentinel \
        --rounds "$ROUNDS" --iterations "$ITERATIONS" --metric-set init --scenario "$SCENARIO" --source "$SOURCE" \
        --expect-mock-requests 2 --device "$serial" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$OUT/raw/init"
      cp "$OUT/raw/init/rows.jsonl" "$OUT/rows/init.jsonl"
    fi
    for v in "${vlist[@]}"; do
      if has micro; then
        d="$OUT/raw/micro/$v"; mkdir -p "$d"
        "$driver" run --metric-set micro --version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --serial "$serial" --out "$d"
        python3 "$parser" "$d" --sdk-version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-platform.jsonl" || true
        ls "$d"/bench-result*.json >/dev/null 2>&1 && python3 "$repo/scripts/parse_bench_result.py" "$d" --sdk android --sdk-version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-bench.jsonl" || true
        cat "$d"/rows-*.jsonl >> "$OUT/rows/micro.jsonl" 2>/dev/null || true
      fi
      if has macro; then
        d="$OUT/raw/macro/$v"; mkdir -p "$d"
        "$driver" run --metric-set macro --version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --serial "$serial" --iterations "$ITERATIONS" --out "$d"
        python3 "$parser" "$d" --sdk-version "$v" --variant sdk --scenario "$SCENARIO" --source "$SOURCE" --env "$ENV_JSON" --run-id "$RUN_ID" --out "$d/rows-platform.jsonl" || true
        cat "$d"/rows-*.jsonl >> "$OUT/rows/macro.jsonl" 2>/dev/null || true
      fi
    done
    ;;
  report)
    "$repo/scripts/ci/lane_report_pr.sh" android "$oldest" "$newest" "$OUT" "$SOURCE"
    ;;
  *) echo "usage: lane_android.sh build|run|report" >&2; exit 1;;
esac
