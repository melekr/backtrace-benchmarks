#!/usr/bin/env bash
# Tier-0 lane: size ladders from published artifacts. Env: SDK (all|android|apple|unity), ANDROID_VERSIONS,
# APPLE_VERSIONS, UNITY_VERSIONS, OUT (default out/tier0). Prints the Markdown tables (for the step summary).
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SDK="${SDK:-all}"; OUT="${OUT:-out/tier0}"; RUN_ID="${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
"$repo/scripts/env_fingerprint.sh" --tier tier0 > "$OUT/env.json"
run_one() {  # run_one <sdk> <versions>
  local sdk="$1"; local versions="$2"
  local args=(--sdk "$sdk" --out "$repo/artifacts" --results "$OUT" --run-id "$RUN_ID" --env "$OUT/env.json" --markdown "$OUT/TIER0-$sdk.md")
  [ -n "$versions" ] && args+=(--versions "$versions")
  [ -n "${GITHUB_WORKFLOW:-}" ] && args+=(--workflow "$GITHUB_WORKFLOW") && args+=(--sha "${GITHUB_SHA:-}")
  python3 "$repo/scripts/fetch_artifacts.py" "${args[@]}" >/dev/null
  cat "$OUT/TIER0-$sdk.md"; echo
}
case "$SDK" in
  all) run_one android "${ANDROID_VERSIONS:-}"; run_one apple "${APPLE_VERSIONS:-}"; run_one unity "${UNITY_VERSIONS:-}";;
  android) run_one android "${ANDROID_VERSIONS:-}";;
  apple) run_one apple "${APPLE_VERSIONS:-}";;
  unity) run_one unity "${UNITY_VERSIONS:-}";;
  *) echo "unknown SDK=$SDK" >&2; exit 1;;
esac
