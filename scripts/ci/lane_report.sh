#!/usr/bin/env bash
# Release-report lane: collect rows-* artifacts (downloaded under out/collected/<artifact>/), render the ladder,
# and prepare the gh-pages series. Env: SDK, VERSIONS (oldest first), OUT (out/report).
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SDK="${SDK:?}"; VERSIONS="${VERSIONS:?}"; OUT="${OUT:-out/report}"; COLLECTED="${COLLECTED:-out/collected}"
mkdir -p "$OUT/rows"
find "$COLLECTED" -name '*.jsonl' -path '*rows*' -exec sh -c 'cat "$1" >> "$0/rows/all.jsonl"' "$OUT" {} \; 2>/dev/null || true
[ -s "$OUT/rows/all.jsonl" ] || { echo "no rows collected under $COLLECTED"; exit 1; }
python3 "$repo/scripts/validate_rows.py" "$OUT/rows/all.jsonl" --quiet || echo "::warning::some rows failed validation"
python3 "$repo/scripts/compare.py" ladder --results "$OUT/rows" --sdk "$SDK" --ladder "$VERSIONS" --allow-mixed-env --format md --out "$OUT/REPORT.md"
python3 "$repo/scripts/compare.py" ladder --results "$OUT/rows" --sdk "$SDK" --ladder "$VERSIONS" --allow-mixed-env --format json --out "$OUT/REPORT.json" >/dev/null
newest="${VERSIONS##*,}"
python3 "$repo/scripts/to_gha_benchmark.py" "$OUT/rows/all.jsonl" --series latest-release --sdk "$SDK" --sdk-version "$newest" --variant sdk --out "$OUT/gha-latest-release.json"
cat "$OUT/REPORT.md"
