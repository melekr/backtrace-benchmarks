#!/usr/bin/env bash
# Probe which SDK versions build on the current toolchain.
#
#   probe_buildability.sh --sdk apple --versions 2.0.6,2.0.9,2.1.0,2.2.0 --toolchain xcode-26.0
#                         [--driver PATH] [--source xcframework|spm|maven|openupm] [--out DIR]
#                         [--scenario default] [--variant sdk] [--dry-run]
#
# Calls `<driver> build` per version (after `prepare`); exit 4 => unsupported, 0 => supported,
# anything else => failure recorded as unsupported with the exit code as reason.
# Writes <out>/supported-cells.json: {sdk, toolchain, cells: [{version, supported, reason}]}.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
sdk="" versions="" toolchain="" driver="" source="" out="out/probe" scenario="default" variant="sdk" dry_run=0

while [ $# -gt 0 ]; do
  case "$1" in
    --sdk) sdk="$2"; shift 2 ;;
    --versions) versions="$2"; shift 2 ;;
    --toolchain) toolchain="$2"; shift 2 ;;
    --driver) driver="$2"; shift 2 ;;
    --source) source="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --scenario) scenario="$2"; shift 2 ;;
    --variant) variant="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "probe_buildability.sh: unknown argument: $1" >&2; exit 1 ;;
  esac
done
[ -n "$sdk" ] && [ -n "$versions" ] && [ -n "$toolchain" ] || { echo "probe_buildability.sh: --sdk, --versions and --toolchain are required" >&2; exit 1; }
case "$sdk" in android|apple|unity) ;; *) echo "probe_buildability.sh: --sdk must be android|apple|unity" >&2; exit 1 ;; esac
[ -n "$driver" ] || driver="$repo/$sdk/scripts/bench_$sdk.sh"
if [ -z "$source" ]; then
  case "$sdk" in android) source="maven" ;; apple) source="xcframework" ;; unity) source="openupm" ;; esac
fi
[ -x "$driver" ] || [ "$dry_run" = 1 ] || { echo "probe_buildability.sh: driver not executable: $driver" >&2; exit 1; }

mkdir -p "$out"
IFS=',' read -r -a version_list <<< "$versions"
cells=""
json_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'; }

for v in "${version_list[@]}"; do
  vout="$out/$sdk/$v/$variant/$scenario"
  args=(--version "$v" --source "$source" --variant "$variant" --scenario "$scenario" --out "$vout")
  if [ "$dry_run" = 1 ]; then
    printf 'DRY: %q prepare' "$driver"; printf ' %q' "${args[@]}"; printf '\n'
    printf 'DRY: %q build' "$driver"; printf ' %q' "${args[@]}"; printf '\n'
    supported=true; reason="dry-run"
  else
    log="$out/probe-$sdk-$v.log"
    set +e
    "$driver" prepare "${args[@]}" >"$log" 2>&1 && "$driver" build "${args[@]}" >>"$log" 2>&1
    rc=$?
    set -e
    case "$rc" in
      0) supported=true; reason="built" ;;
      4) supported=false; reason="unsupported on $toolchain (driver exit 4)" ;;
      *) supported=false; reason="build failed (exit $rc), see $(basename "$log")" ;;
    esac
    printf '[probe] %s %s -> %s (%s)\n' "$sdk" "$v" "$supported" "$reason" >&2
  fi
  [ -n "$cells" ] && cells="$cells,"
  cells="$cells{\"version\":\"$(json_str "$v")\",\"supported\":$supported,\"reason\":\"$(json_str "$reason")\"}"
done

result="{\"sdk\":\"$sdk\",\"toolchain\":\"$(json_str "$toolchain")\",\"source\":\"$source\",\"cells\":[$cells]}"
printf '%s\n' "$result" > "$out/supported-cells.json"
printf '%s\n' "$result"
