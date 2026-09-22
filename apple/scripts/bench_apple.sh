#!/usr/bin/env bash
# Apple module driver (docs/CONVENTIONS.md section 7). iOS Simulator lanes.
#
#   bench_apple.sh prepare --version 2.2.0 --source xcframework|spm|local [--local-path DIR] [--variants plain,sdk,sentinel]
#   bench_apple.sh build   --variant sdk [--udid UDID] [--out DIR]          # build-for-testing, Release, unsigned
#   bench_apple.sh install --version 2.2.0 --variant sdk --udid UDID
#   bench_apple.sh run     --metric-set init|micro --version 2.2.0 --variant sdk --udid UDID --iterations N --out DIR
#   bench_apple.sh size    --version 2.2.0 --variant plain|sdk [--env env.json] [--run-id ID] --out DIR
#   bench_apple.sh clean
# init  = N launches of the app through the UI test bundle (XCTApplicationLaunchMetric + signpost) with the app's
#         Documents/bt-bench-stages.json copied after every launch; micro = BenchUnitTests (send/breadcrumbs/counters).
# Exit 4 = the requested SDK version does not build on this toolchain (unsupported cell).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
apple_dir="$(cd "$here/.." && pwd)"
repo="$(cd "$apple_dir/.." && pwd)"
cmd="${1:-}"; shift || true
version="2.2.0" source="xcframework" local_path="" variants="plain,sdk,sentinel" variant="sdk" udid="${SIM_UDID:-}" out=""
metric_set="init" iterations=10 env_json="" run_id="local" round=0 position=0 scenario="default" crash=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="$2"; shift 2;; --source) source="$2"; shift 2;; --local-path) local_path="$2"; shift 2;;
    --variants) variants="$2"; shift 2;; --variant) variant="$2"; shift 2;; --udid|--device|--serial) udid="$2"; shift 2;;
    --out) out="$2"; shift 2;; --metric-set) metric_set="$2"; shift 2;; --iterations) iterations="$2"; shift 2;;
    --env) env_json="$2"; shift 2;; --run-id) run_id="$2"; shift 2;; --round) round="$2"; shift 2;; --position) position="$2"; shift 2;;
    --scenario) scenario="$2"; shift 2;; --crash) crash="$2"; shift 2;;
    *) echo "bench_apple.sh: unknown argument $1" >&2; exit 1;;
  esac
done
version_id="v$(echo "$version" | tr '.-' '__')"
bundle_id="io.backtrace.bench.$variant.$version_id"
project="$apple_dir/BenchApp.xcodeproj"
dd="$apple_dir/build/dd"
log() { echo "bench_apple.sh[$variant $version]: $*"; }
pick_udid() {
  if [ -n "$udid" ]; then echo "$udid"; return; fi
  local booted; booted=$(xcrun simctl list devices booted 2>/dev/null | grep -E -o '\(([0-9A-F-]{36})\)' | head -1 | tr -d '()')
  if [ -n "$booted" ]; then echo "$booted"; return; fi
  local any; any=$(xcrun simctl list devices available 2>/dev/null | grep -E 'iPhone 1[5-9]( Pro)?( Max)? \(' | head -1 | grep -E -o '[0-9A-F-]{36}' | head -1)
  [ -n "$any" ] || { echo "bench_apple.sh: no iPhone simulator available" >&2; exit 1; }
  xcrun simctl boot "$any" >/dev/null 2>&1 || true
  xcrun simctl bootstatus "$any" -b >/dev/null 2>&1 || true
  echo "$any"
}
app_path() { echo "$dd/Build/Products/Release-iphonesimulator/BenchApp-$variant.app"; }

case "$cmd" in
  prepare)
    args=(--source "$source" --version "$version" --variants "$variants")
    [ -n "$local_path" ] && args+=(--local-path "$local_path")
    python3 "$here/render_project.py" "${args[@]}"
    (cd "$apple_dir" && xcodegen generate --quiet)
    log "project rendered ($source) for variants $variants"
    ;;
  build)
    u=$(pick_udid); mkdir -p "${out:-$apple_dir/build}/logs"
    logf="${out:-$apple_dir/build}/logs/build-$variant-$version_id.log"
    set +e
    xcodebuild -project "$project" -scheme "BenchApp-$variant" -configuration Release -destination "platform=iOS Simulator,id=$u" \
      -derivedDataPath "$dd" build-for-testing CODE_SIGNING_ALLOWED=NO -quiet >"$logf" 2>&1
    rc=$?; set -e
    if [ $rc -ne 0 ]; then
      if grep -q -E "error: .*(no such module|cannot find|is unavailable|Swift Compiler Error|failed to resolve|Dependencies could not be resolved)" "$logf"; then
        log "SDK $version does not build with $(xcodebuild -version | head -1) ($source)"; grep -E "error:" "$logf" | head -5 >&2; exit 4
      fi
      grep -E "error:" "$logf" | head -20 >&2; exit 1
    fi
    log "built $(app_path)"
    ;;
  install)
    u=$(pick_udid); xcrun simctl install "$u" "$(app_path)"; log "installed $bundle_id on $u"
    ;;
  run)
    [ -n "$out" ] || { echo "run needs --out" >&2; exit 1; }
    u=$(pick_udid); mkdir -p "$out"
    case "$metric_set" in
      init)
        # One UI-test invocation launches the app `iterations` times inside measure(); the app rewrites its stage
        # file on every launch, so the file is copied after the run and the per-launch values come from the
        # signpost metric in the xcresult plus the app's own JSON (last launch) for stage names.
        # xcodebuild forwards environment to the test runner only with the TEST_RUNNER_ prefix.
        export BT_ITERATIONS="$iterations" TEST_RUNNER_BT_ITERATIONS="$iterations"
        [ -n "$crash" ] && export BT_BENCH_CRASH=1 TEST_RUNNER_BT_BENCH_CRASH=1
        set +e
        xcodebuild test-without-building -project "$project" -scheme "BenchApp-$variant" -configuration Release \
          -destination "platform=iOS Simulator,id=$u" -derivedDataPath "$dd" -only-testing:"BenchAppUITests-$variant" \
          -resultBundlePath "$out/launch.xcresult" >"$out/xcodebuild-launch.log" 2>&1
        rc=$?; set -e
        container=$(xcrun simctl get_app_container "$u" "$bundle_id" data 2>/dev/null || true)
        if [ -n "$container" ]; then
          for f in "$container"/Documents/bt-bench-stages*.json "$container"/Documents/bench-result*.json; do
            [ -f "$f" ] && cp "$f" "$out/"
          done
        fi
        [ $rc -eq 0 ] || { grep -E "error:|failed" "$out/xcodebuild-launch.log" | head -10 >&2; log "launch lane failed (rc=$rc)"; exit 1; }
        log "init lane: xcresult at $out/launch.xcresult; $(ls "$out"/*.json 2>/dev/null | wc -l | tr -d ' ') app JSON file(s)"
        ;;
      micro)
        [ "$variant" != "plain" ] || { log "micro lane needs the sdk variant"; exit 1; }
        set +e
        xcodebuild test-without-building -project "$project" -scheme "BenchApp-$variant" -configuration Release \
          -destination "platform=iOS Simulator,id=$u" -derivedDataPath "$dd" -only-testing:BenchUnitTests \
          -resultBundlePath "$out/micro.xcresult" >"$out/xcodebuild-micro.log" 2>&1
        rc=$?; set -e
        container=$(xcrun simctl get_app_container "$u" "$bundle_id" data 2>/dev/null || true)
        [ -n "$container" ] && [ -f "$container/Documents/bench-result.json" ] && cp "$container/Documents/bench-result.json" "$out/bench-result-micro.json"
        [ $rc -eq 0 ] || { grep -E "error:|failed" "$out/xcodebuild-micro.log" | head -10 >&2; log "micro lane failed (rc=$rc)"; exit 1; }
        log "micro lane: xcresult at $out/micro.xcresult"
        ;;
      *) echo "unknown --metric-set $metric_set" >&2; exit 1;;
    esac
    ;;
  size)
    [ -n "$out" ] || { echo "size needs --out" >&2; exit 1; }
    mkdir -p "$out"
    archive="$apple_dir/build/archives/BenchApp-$variant-$version_id.xcarchive"; rm -rf "$archive"
    xcodebuild -project "$project" -scheme "BenchApp-$variant" -configuration Release -destination 'generic/platform=iOS' \
      -archivePath "$archive" archive CODE_SIGNING_ALLOWED=NO -quiet >"$out/xcodebuild-archive-$variant.log" 2>&1 || { grep -E "error:" "$out/xcodebuild-archive-$variant.log" | head -10 >&2; exit 1; }
    app="$archive/Products/Applications/BenchApp-$variant.app"
    python3 - "$app" "$variant" "$version" "$source" "${env_json:-}" "$run_id" "$out/rows-size-$variant.jsonl" <<'PY'
import datetime, json, os, shutil, subprocess, sys, tempfile
app, variant, ver, source, env_path, run_id, out = sys.argv[1:8]
env = json.load(open(env_path)) if env_path and os.path.exists(env_path) else {"fingerprint": "unknown", "tier": "tier1"}
ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
def du(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total
binary = os.path.join(app, os.path.basename(app)[:-4])
tmp = tempfile.mkdtemp(); zipf = os.path.join(tmp, "app.zip")
subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, zipf], check=True)
def row(metric, value):
    return {"schemaVersion": 1, "sdk": "apple", "platform": "ios", "sdkVersion": ver, "source": source, "variant": variant,
            "scenario": "default", "metric": metric, "unit": "bytes", "value": value, "samples": [value],
            "stats": {"n": 1, "sampleKind": "exact"}, "env": env, "run": {"id": run_id, "ts": ts, "workflow": "bench-apple"}, "valid": True}
rows = [row("C3.app_binary_bytes", os.path.getsize(binary)), row("C3.app_bundle_bytes", du(app)), row("C3.app_zip_bytes", os.path.getsize(zipf))]
shutil.rmtree(tmp, ignore_errors=True)
with open(out, "w") as f:
    for r in rows: f.write(json.dumps(r) + "\n")
print("bench_apple.sh: wrote %d size rows to %s" % (len(rows), out))
PY
    ;;
  clean)
    rm -rf "$apple_dir/build" "$apple_dir/Generated" "$apple_dir/project.yml" "$apple_dir/BenchApp.xcodeproj"; log "cleaned"
    ;;
  *) echo "usage: bench_apple.sh prepare|build|install|run|size|clean [options]" >&2; exit 1;;
esac
