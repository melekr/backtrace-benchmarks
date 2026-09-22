#!/usr/bin/env bash
# Real-device lane (Sauce Labs). Env: VERSIONS, DEVICE, ITERATIONS, OUT (out/sauce), GITHUB_RUN_ID.
#   lane_sauce.sh build  : app + macrobenchmark APKs for the newest version (one suite per version is a follow-up)
#   lane_sauce.sh config : render .sauce/rendered.yml from the template
#   lane_sauce.sh report : recover benchmarkData.json from device logs and convert to rows
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cmd="${1:-}"; VERSIONS="${VERSIONS:?}"; DEVICE="${DEVICE:-Google_Pixel_9_Pro_XL_15_real_sjc1}"; ITERATIONS="${ITERATIONS:-12}"; OUT="${OUT:-out/sauce}"
newest="${VERSIONS##*,}"; vid="v$(echo "$newest" | tr '.-' '__')"; app_id="io.backtrace.bench.sdk.$vid"
driver="$repo/android/scripts/bench_android.sh"; export BT_GRADLE_ARGS="${BT_GRADLE_ARGS:---no-daemon -q}"
case "$cmd" in
  build) mkdir -p "$OUT"; "$driver" build --version "$newest" --variant sdk --with-tests --out "$OUT";;
  config)
    sed -e "s#{{APP_APK}}#$repo/android/build/cells/$app_id-default/app.apk#" -e "s#{{TEST_APK}}#$repo/android/build/cells/$app_id-default/macrobenchmark.apk#" \
        -e "s#{{VERSION}}#$newest#g" -e "s#{{DEVICE}}#$DEVICE#g" -e "s#{{ANNOTATION}}#androidx.test.filters.LargeTest#" "$repo/.sauce/android-macrobenchmark.tmpl.yml"
    ;;
  report)
    mkdir -p "$OUT/rows"
    python3 "$repo/android/scripts/logcat_chunks_to_json.py" $(find "$OUT/artifacts" -name '*.log') --out "$OUT/recovered" || { echo "no benchmark data recovered from device logs"; exit 1; }
    python3 "$repo/android/scripts/benchmarkdata_to_rows.py" "$OUT/recovered" --sdk-version "$newest" --variant sdk --env env.json --run-id "${GITHUB_RUN_ID:-local}" --workflow bench-sauce --out "$OUT/rows/macro.jsonl"
    python3 "$repo/scripts/compare.py" overhead --plain "$OUT/rows/macro.jsonl" --head "$OUT/rows/macro.jsonl" --format md --allow-mixed-env 2>/dev/null || true
    echo "### real-device rows (trend only, unlocked clocks)"; python3 -c "
import json,sys
for l in open('$OUT/rows/macro.jsonl'):
    r=json.loads(l); print('- %s: median %.1f %s (n=%d, cov %.1f%%)' % (r['metric'], r['value'], r['unit'], r['stats']['n'], 100*r['stats'].get('cov',0)))"
    ;;
  *) echo "usage: lane_sauce.sh build|config|report" >&2; exit 1;;
esac
