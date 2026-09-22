#!/usr/bin/env bash
# A/B round orchestrator: builds every variant once, then runs them interleaved in a
# rotated order per round and converts the raw output to result rows.
#
#   run_ab_rounds.sh --sdk android|apple|unity --driver PATH/bench_<sdk>.sh --versions v1,v2
#                    [--plain] [--sentinel] [--rounds 3] [--iterations N] [--metric-set init]
#                    [--scenario default] [--source maven|xcframework|spm|openupm|local]
#                    [--local-path DIR] [--parser PATH] [--expect-mock-requests N]
#                    [--device ID] [--env FILE | --env-args "--agp 8.13.2 --jdk 17"] [--run-id ID]
#                    --out DIR [--dry-run]
#
# Layout (docs/CONVENTIONS.md section 8): <out>/<sdk>/<version>/<variant>/<scenario>/round-<R>/pos-<P>/
# Rows: <out>/rows.jsonl. Driver exit 4 marks a variant unsupported and skips it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sdk="" driver="" versions="" plain=0 sentinel=0 rounds=3 iterations="" metric_set="init"
scenario="default" source="" local_path="" parser="" expect_mock="" device="" env_args="" env_file=""
run_id="" out="" dry_run=0

while [ $# -gt 0 ]; do
  case "$1" in
    --sdk) sdk="$2"; shift 2 ;;
    --driver) driver="$2"; shift 2 ;;
    --versions) versions="$2"; shift 2 ;;
    --plain) plain=1; shift ;;
    --sentinel) sentinel=1; shift ;;
    --rounds) rounds="$2"; shift 2 ;;
    --iterations) iterations="$2"; shift 2 ;;
    --metric-set) metric_set="$2"; shift 2 ;;
    --scenario) scenario="$2"; shift 2 ;;
    --source) source="$2"; shift 2 ;;
    --local-path) local_path="$2"; shift 2 ;;
    --parser) parser="$2"; shift 2 ;;
    --expect-mock-requests) expect_mock="$2"; shift 2 ;;
    --device) device="$2"; shift 2 ;;
    --env-args) env_args="$2"; shift 2 ;;
    --env) env_file="$2"; shift 2 ;;
    --run-id) run_id="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "run_ab_rounds.sh: unknown argument: $1" >&2; exit 1 ;;
  esac
done

[ -n "$sdk" ] && [ -n "$driver" ] && [ -n "$versions" ] && [ -n "$out" ] || { echo "run_ab_rounds.sh: --sdk, --driver, --versions and --out are required" >&2; exit 1; }
case "$sdk" in android|apple|unity) ;; *) echo "run_ab_rounds.sh: --sdk must be android|apple|unity" >&2; exit 1 ;; esac
[ -x "$driver" ] || [ "$dry_run" = 1 ] || { echo "run_ab_rounds.sh: driver not executable: $driver" >&2; exit 1; }
if [ -z "$source" ]; then
  case "$sdk" in android) source="maven" ;; apple) source="xcframework" ;; unity) source="openupm" ;; esac
fi
[ -n "$run_id" ] || run_id="$(date -u +%Y%m%dT%H%M%SZ)"

IFS=',' read -r -a version_list <<< "$versions"
newest="${version_list[$((${#version_list[@]} - 1))]}"

# variant spec: "<variant>@<version>"
declare -a variants=()
[ "$plain" = 1 ] && variants+=("plain@${newest}")
for v in "${version_list[@]}"; do variants+=("sdk@${v}"); done
[ "$sentinel" = 1 ] && variants+=("sentinel@${newest}")
n="${#variants[@]}"

device_flag=()
if [ -n "$device" ]; then
  case "$sdk" in apple) device_flag=(--udid "$device") ;; *) device_flag=(--serial "$device") ;; esac
fi
iter_flag=()
[ -n "$iterations" ] && iter_flag=(--iterations "$iterations")
local_flag=()
[ -n "$local_path" ] && local_flag=(--local-path "$local_path")

log() { printf '[run_ab_rounds] %s\n' "$*" >&2; }
run_cmd() {
  if [ "$dry_run" = 1 ]; then printf 'DRY: %q ' "$@"; printf '\n'; return 0; fi
  "$@"
}

mkdir -p "$out"
env_json="$out/env.json"
if [ -n "$env_file" ]; then
  # Reuse the job's env.json so every row of the job shares one fingerprint (size rows, init rows, micro rows).
  if [ "$dry_run" = 1 ]; then printf 'DRY: cp %q %q\n' "$env_file" "$env_json"; else cp "$env_file" "$env_json"; fi
elif [ "$dry_run" = 1 ]; then
  printf 'DRY: bash %q --tier tier1 %s --out %q\n' "$here/env_fingerprint.sh" "$env_args" "$env_json"
else
  # shellcheck disable=SC2086
  bash "$here/env_fingerprint.sh" --tier tier1 $env_args --out "$env_json" >/dev/null
fi

rows="$out/rows.jsonl"
: > "$rows" 2>/dev/null || true
unsupported=" "   # space-separated "<variant>@<version>" specs (Bash 3.2 has no associative arrays)

# ---- phase 1: prepare/build/install every variant once ------------------------------------
log "plan: sdk=$sdk variants=${variants[*]} rounds=$rounds metric-set=$metric_set scenario=$scenario out=$out"
for spec in "${variants[@]}"; do
  variant="${spec%@*}"; version="${spec#*@}"
  vout="$out/$sdk/$version/$variant/$scenario"
  common=(--version "$version" --source "$source" --variant "$variant" --scenario "$scenario" --out "$vout" ${device_flag[@]+"${device_flag[@]}"} ${local_flag[@]+"${local_flag[@]}"})
  for step in prepare build install; do
    set +e
    run_cmd "$driver" "$step" "${common[@]}"
    rc=$?
    set -e
    if [ "$rc" = 4 ]; then log "unsupported cell: $spec ($step exit 4); skipping"; unsupported="$unsupported$spec "; break; fi
    if [ "$rc" != 0 ]; then log "driver $step failed for $spec (exit $rc)"; exit 1; fi
  done
done

# ---- phase 2: rounds with rotated launch order --------------------------------------------
for ((r = 1; r <= rounds; r++)); do
  shift_by=$(( (r - 1) % n ))
  log "round $r: order rotated by $shift_by"
  for ((p = 0; p < n; p++)); do
    idx=$(( (p + shift_by) % n ))
    spec="${variants[$idx]}"
    case "$unsupported" in *" $spec "*) continue ;; esac
    variant="${spec%@*}"; version="${spec#*@}"
    rdir="$out/$sdk/$version/$variant/$scenario/round-$r/pos-$p"
    [ "$dry_run" = 1 ] || mkdir -p "$rdir"
    run_cmd "$driver" run --metric-set "$metric_set" --version "$version" --source "$source" --variant "$variant" \
      --scenario "$scenario" --out "$rdir" --round "$r" --position "$p" ${device_flag[@]+"${device_flag[@]}"} ${iter_flag[@]+"${iter_flag[@]}"} ${local_flag[@]+"${local_flag[@]}"}
    [ "$dry_run" = 1 ] || cp "$env_json" "$rdir/env.json"
    common_parse=(--sdk "$sdk" --sdk-version "$version" --source "$source" --variant "$variant" --scenario "$scenario"
                  --round "$r" --position "$p" --env "$env_json" --run-id "$run_id")
    if [ -n "$parser" ]; then
      # The platform parser only applies to metric sets that produce its raw files (e.g. benchmarkData.json);
      # "no rows" is not an error for the round.
      run_cmd python3 "$parser" "$rdir" "${common_parse[@]}" --out "$rdir/rows-platform.jsonl" || log "platform parser: no rows for $rdir"
    fi
    mock_flag=()
    if [ -n "$expect_mock" ]; then
      # The plain app has no SDK and must see zero mock requests; sdk/sentinel expect the configured count.
      if [ "$variant" = "plain" ]; then mock_flag=(--expect-mock-requests 0); else mock_flag=(--expect-mock-requests "$expect_mock"); fi
    fi
    if [ "$dry_run" = 1 ] || ls "$rdir"/bench-result*.json >/dev/null 2>&1 || ls "$rdir"/bt-bench-stages*.json >/dev/null 2>&1; then
      run_cmd python3 "$here/parse_bench_result.py" "$rdir" "${common_parse[@]}" ${mock_flag[@]+"${mock_flag[@]}"} --out "$rdir/rows-bench.jsonl" || log "bench-result parser failed for $rdir"
    else
      log "no bench-result*.json in $rdir"
    fi
    if [ "$dry_run" = 0 ]; then
      for f in "$rdir"/rows-*.jsonl; do [ -f "$f" ] && cat "$f" >> "$rows"; done
    fi
  done
done

if [ "$dry_run" = 1 ]; then
  log "dry run complete: $n variants x $rounds rounds"
else
  log "rows: $rows ($(wc -l < "$rows" | tr -d ' ') lines)"
  python3 "$here/validate_rows.py" "$rows" --quiet || log "WARNING: some rows failed validation"
fi
