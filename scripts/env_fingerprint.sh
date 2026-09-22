#!/usr/bin/env bash
# Emit env.json for result rows (docs/CONVENTIONS.md section 9).
#
#   env_fingerprint.sh [--tier tier0|tier1|tier2] [--cpu-locked] [--set key=value ...]
#                      [--agp V] [--gradle V] [--jdk V] [--unity V] [--emulator ID]
#                      [--simulator ID] [--device ID] [--out FILE]
#
# fingerprint = sha256 over the sorted "key=value" lines (one per comparability
# field, trailing newline) of: runner os nproc xcode agp gradle jdk unity emulator
# simulator device cpuLocked tier. scripts/harness_common.py::compute_fingerprint
# implements the same function; tests assert both agree.
set -euo pipefail

tier="tier1"
cpu_locked="false"
out=""
declare -a sets=()
agp="" gradle="" jdk="" unity="" emulator="" simulator="" device="" xcode=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tier) tier="$2"; shift 2 ;;
    --cpu-locked) cpu_locked="true"; shift ;;
    --set) sets+=("$2"); shift 2 ;;
    --agp) agp="$2"; shift 2 ;;
    --gradle) gradle="$2"; shift 2 ;;
    --jdk) jdk="$2"; shift 2 ;;
    --unity) unity="$2"; shift 2 ;;
    --emulator) emulator="$2"; shift 2 ;;
    --simulator) simulator="$2"; shift 2 ;;
    --device) device="$2"; shift 2 ;;
    --xcode) xcode="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "env_fingerprint.sh: unknown argument: $1" >&2; exit 1 ;;
  esac
done

# --- runner / os / nproc ---------------------------------------------------------
runner="${RUNNER_OS:-${ImageOS:-}}"
if [ -z "$runner" ]; then runner="$(uname -s)"; fi
if [ -n "${ImageOS:-}" ] && [ -n "${RUNNER_OS:-}" ]; then runner="${RUNNER_OS}/${ImageOS}"; fi

os_name="$(uname -s)"
os_rel="$(uname -r)"
if [ "$os_name" = "Darwin" ] && command -v sw_vers >/dev/null 2>&1; then
  os_rel="$(sw_vers -productVersion 2>/dev/null || echo "$os_rel")"
  os="macOS ${os_rel}"
elif [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  os="$(. /etc/os-release; echo "${NAME:-$os_name} ${VERSION_ID:-$os_rel}")"
else
  os="${os_name} ${os_rel}"
fi

if command -v nproc >/dev/null 2>&1; then
  nproc_val="$(nproc)"
elif command -v sysctl >/dev/null 2>&1; then
  nproc_val="$(sysctl -n hw.logicalcpu 2>/dev/null || sysctl -n hw.ncpu)"
else
  nproc_val="0"
fi

# --- toolchains (only probed when not given) ----------------------------------------
if [ -z "$xcode" ] && command -v xcodebuild >/dev/null 2>&1; then
  xcode="$(xcodebuild -version 2>/dev/null | tr '\n' ' ' | sed -e 's/[[:space:]]*$//' || true)"
fi
if [ -z "$gradle" ] && command -v gradle >/dev/null 2>&1; then
  gradle="$(gradle -v 2>/dev/null | awk '/^Gradle /{print $2; exit}' || true)"
fi
if [ -z "$jdk" ] && command -v java >/dev/null 2>&1; then
  jdk="$(java -version 2>&1 | head -n1 | sed -e 's/^[^"]*"//' -e 's/".*$//' || true)"
fi

# --- overrides -------------------------------------------------------------------------
for kv in ${sets[@]+"${sets[@]}"}; do
  key="${kv%%=*}"
  val="${kv#*=}"
  case "$key" in
    runner) runner="$val" ;; os) os="$val" ;; nproc) nproc_val="$val" ;;
    xcode) xcode="$val" ;; agp) agp="$val" ;; gradle) gradle="$val" ;; jdk) jdk="$val" ;;
    unity) unity="$val" ;; emulator) emulator="$val" ;; simulator) simulator="$val" ;;
    device) device="$val" ;; cpuLocked) cpu_locked="$val" ;; tier) tier="$val" ;;
    *) echo "env_fingerprint.sh: unknown --set key: $key" >&2; exit 1 ;;
  esac
done

case "$cpu_locked" in true|false) ;; *) echo "cpuLocked must be true|false" >&2; exit 1 ;; esac
case "$tier" in tier0|tier1|tier2) ;; *) echo "tier must be tier0|tier1|tier2" >&2; exit 1 ;; esac
case "$nproc_val" in ''|*[!0-9]*) nproc_val="0" ;; esac

# --- fingerprint -------------------------------------------------------------------------
lines="$(printf '%s\n' \
  "runner=${runner}" "os=${os}" "nproc=${nproc_val}" "xcode=${xcode}" "agp=${agp}" \
  "gradle=${gradle}" "jdk=${jdk}" "unity=${unity}" "emulator=${emulator}" \
  "simulator=${simulator}" "device=${device}" "cpuLocked=${cpu_locked}" "tier=${tier}" \
  | LC_ALL=C sort)"
if command -v shasum >/dev/null 2>&1; then
  fp="$(printf '%s\n' "$lines" | shasum -a 256 | awk '{print $1}')"
else
  fp="$(printf '%s\n' "$lines" | sha256sum | awk '{print $1}')"
fi

json_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' | tr -d '\n\r'; }

json="$(printf '{"runner":"%s","os":"%s","nproc":%s,"xcode":"%s","agp":"%s","gradle":"%s","jdk":"%s","unity":"%s","emulator":"%s","simulator":"%s","device":"%s","cpuLocked":%s,"tier":"%s","fingerprint":"%s"}' \
  "$(json_str "$runner")" "$(json_str "$os")" "$nproc_val" "$(json_str "$xcode")" "$(json_str "$agp")" \
  "$(json_str "$gradle")" "$(json_str "$jdk")" "$(json_str "$unity")" "$(json_str "$emulator")" \
  "$(json_str "$simulator")" "$(json_str "$device")" "$cpu_locked" "$tier" "$fp")"

if [ -n "$out" ]; then
  mkdir -p "$(dirname "$out")"
  printf '%s\n' "$json" > "$out"
fi
printf '%s\n' "$json"
