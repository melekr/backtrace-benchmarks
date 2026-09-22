#!/usr/bin/env bash
# Unity module driver (docs/CONVENTIONS.md section 7).
#
#   bench_unity.sh prepare --version 3.17.0 --editor 6000.3.7f1 [--source openupm|local --local-path DIR] [--variant sdk|plain|sentinel] [--perf-version 3.5.0]
#   bench_unity.sh run     --metric-set micro --out DIR [--editor V | --editor-path BIN] [--variant sdk] [--test-filter REGEX]
#   bench_unity.sh size    --out DIR [--editor V | --editor-path BIN] --variant plain|sdk [--sdk-version V] [--env env.json] [--run-id ID]
#   bench_unity.sh clean
#
# Editor binary: --editor-path, $UNITY_BIN, /Applications/Unity/Hub/Editor/<editor>/Unity.app/Contents/MacOS/Unity,
# or unity-editor on PATH (container images). In CI the test action runs the tests itself; the driver is used for
# prepare/size there. Exit 4 = unsupported cell (package did not resolve).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unity_dir="$(cd "$here/.." && pwd)"
project="$unity_dir/project"
cmd="${1:-}"; shift || true
version="" editor="" editor_path="${UNITY_BIN:-}" source="openupm" local_path="" variant="sdk" perf_version="3.5.0"
out="" metric_set="micro" test_filter="" env_json="" run_id="local" sdk_version="" timeout_s=1800
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="$2"; shift 2;; --editor) editor="$2"; shift 2;; --editor-path) editor_path="$2"; shift 2;;
    --source) source="$2"; shift 2;; --local-path) local_path="$2"; shift 2;; --variant) variant="$2"; shift 2;;
    --perf-version) perf_version="$2"; shift 2;; --out) out="$2"; shift 2;; --metric-set) metric_set="$2"; shift 2;;
    --test-filter) test_filter="$2"; shift 2;; --env) env_json="$2"; shift 2;; --run-id) run_id="$2"; shift 2;;
    --sdk-version) sdk_version="$2"; shift 2;; --timeout) timeout_s="$2"; shift 2;;
    --scenario|--iterations|--round|--position|--serial|--udid) shift 2;;  # accepted for interface symmetry
    *) echo "bench_unity.sh: unknown argument $1" >&2; exit 1;;
  esac
done

find_editor() {
  if [ -n "$editor_path" ]; then echo "$editor_path"; return; fi
  if [ -n "$editor" ]; then
    local mac="/Applications/Unity/Hub/Editor/$editor/Unity.app/Contents/MacOS/Unity"
    [ -x "$mac" ] && { echo "$mac"; return; }
    local linux="$HOME/Unity/Hub/Editor/$editor/Editor/Unity"
    [ -x "$linux" ] && { echo "$linux"; return; }
  fi
  if command -v unity-editor >/dev/null 2>&1; then command -v unity-editor; return; fi
  echo "bench_unity.sh: no Unity editor found (use --editor-path or UNITY_BIN)" >&2; exit 1
}

current_editor_version() { sed -n 's/^m_EditorVersion: //p' "$project/ProjectSettings/ProjectVersion.txt" | head -1; }

run_unity() {  # run_unity <logfile> <args...>
  local log="$1"; shift
  local bin; bin="$(find_editor)"
  set +e
  "$bin" -batchmode -nographics -projectPath "$project" -logFile "$log" "$@"
  local rc=$?
  set -e
  if grep -q -E "Cannot resolve package|An error occurred while resolving packages|Package .* cannot be found" "$log" 2>/dev/null; then
    echo "bench_unity.sh: package resolution failed (see $log)" >&2; return 4
  fi
  if grep -q -E "No valid Unity Editor license|Unable to activate|License is not active|Licensing::Client.*(Failed|Error)" "$log" 2>/dev/null; then
    echo "bench_unity.sh: editor licence problem (see $log)" >&2; return 1
  fi
  if grep -q "Scripts have compiler errors" "$log" 2>/dev/null; then
    echo "bench_unity.sh: C# compile errors:" >&2; grep -E "error CS|Assembly with name" "$log" | sort -u | head -20 >&2; return 1
  fi
  return $rc
}

case "$cmd" in
  prepare)
    [ -n "$version" ] && [ -n "$editor" ] || { echo "prepare needs --version and --editor" >&2; exit 1; }
    args=(--version "$version" --editor "$editor" --source "$source" --variant "$variant" --perf-version "$perf_version")
    [ -n "$local_path" ] && args+=(--local-path "$local_path")
    python3 "$here/render_manifest.py" "${args[@]}"
    ;;
  build|install)
    echo "bench_unity.sh: $cmd is a no-op for editor lanes (player builds happen in 'size')"
    ;;
  run)
    [ -n "$out" ] || { echo "run needs --out" >&2; exit 1; }
    mkdir -p "$out"; out="$(cd "$out" && pwd)"   # the editor resolves relative paths against the project directory
    [ -z "$editor" ] && editor="$(current_editor_version)"
    args=(-runTests -testPlatform PlayMode -testResults "$out/TestResults.xml" -perfTestResults "$out/PerformanceTestResults.json" -btBenchOut "$out" -btVariant "$variant")
    [ -n "$test_filter" ] && args+=(-testFilter "$test_filter")
    echo "bench_unity.sh: running PlayMode benchmarks with editor $editor -> $out"
    rc=0; run_unity "$out/unity.log" "${args[@]}" || rc=$?
    if [ ! -f "$out/PerformanceTestResults.json" ]; then
      # Package versions before 3.1.0 ignore -perfTestResults and write next to the player data.
      for cand in "$HOME/Library/Application Support/io.backtrace/BacktraceBench/PerformanceTestResults.json" \
                  "$HOME/.config/unity3d/io.backtrace/BacktraceBench/PerformanceTestResults.json"; do
        [ -f "$cand" ] && cp "$cand" "$out/PerformanceTestResults.json" && break
      done
    fi
    ls "$out"/bench-result-*.json >/dev/null 2>&1 && echo "bench_unity.sh: $(ls "$out"/bench-result-*.json | wc -l | tr -d ' ') bench-result files"
    [ -f "$out/PerformanceTestResults.json" ] && echo "bench_unity.sh: PerformanceTestResults.json present" || echo "bench_unity.sh: WARNING no PerformanceTestResults.json"
    exit $rc
    ;;
  size)
    [ -n "$out" ] || { echo "size needs --out" >&2; exit 1; }
    mkdir -p "$out"; out="$(cd "$out" && pwd)"
    [ -z "$editor" ] && editor="$(current_editor_version)"
    apk="$out/bench-$variant.apk"
    rc=0; run_unity "$out/build-$variant.log" -quit -executeMethod BacktraceBench.Editor.BenchBuild.BuildAndroid -btOut "$apk" -btVariant "$variant" || rc=$?
    [ $rc -eq 0 ] && [ -f "$apk" ] || { echo "bench_unity.sh: player build failed (see $out/build-$variant.log)" >&2; exit ${rc:-1}; }
    python3 - "$apk" "$variant" "${sdk_version:-$version}" "$source" "${env_json:-}" "$run_id" "$out/rows-size-$variant.jsonl" <<'PY'
import datetime, json, os, sys, zipfile
apk, variant, ver, source, env_path, run_id, out = sys.argv[1:8]
env = json.load(open(env_path)) if env_path and os.path.exists(env_path) else {"fingerprint": "unknown", "tier": "tier1"}
ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
def row(metric, value):
    return {"schemaVersion": 1, "sdk": "unity", "platform": "unity-android", "sdkVersion": ver, "source": source, "variant": variant,
            "scenario": "default", "metric": metric, "unit": "bytes", "value": value, "samples": [value],
            "stats": {"n": 1, "sampleKind": "exact"}, "env": env, "run": {"id": run_id, "ts": ts, "workflow": "bench-unity"}, "valid": True}
rows = [row("U4.player_bytes.android", os.path.getsize(apk))]
per_abi = {}
with zipfile.ZipFile(apk) as z:
    for info in z.infolist():
        parts = info.filename.split("/")
        if len(parts) >= 3 and parts[0] == "lib":
            per_abi[parts[1]] = per_abi.get(parts[1], 0) + info.file_size
for abi, size in sorted(per_abi.items()):
    rows.append(row("U4.native_bytes.android." + abi, size))
with open(out, "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
print("bench_unity.sh: wrote %d size rows to %s" % (len(rows), out))
PY
    ;;
  clean)
    rm -rf "$project/Library" "$project/Temp" "$project/Logs" "$project/obj" "$project/Build" "$project/Packages/packages-lock.json"
    echo "bench_unity.sh: cleaned editor caches"
    ;;
  *) echo "usage: bench_unity.sh prepare|run|size|clean [options]" >&2; exit 1;;
esac
