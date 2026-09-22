#!/usr/bin/env bash
# Publish a backtrace-android checkout to mavenLocal with the SDK's own toolchain and record the version it produced.
# Usage: scripts/ci/publish_android_local.sh <sdk-src-dir> [git-ref] [label]
#   With a git-ref, the ref is built from a detached worktree under out/sdk-worktree-<label> (the checkout is not modified).
#   Writes out/local-version[-<label>].txt with the published version (from the SDK's own tag-derived versioning).
set -euo pipefail
SRC="${1:?sdk source dir}"; REF="${2:-}"; LABEL="${3:-}"
OUT_DIR="${OUT_DIR:-out}"; mkdir -p "$OUT_DIR"
M2="$HOME/.m2/repository/com/github/backtrace-labs/backtrace-android/backtrace-library"
BUILD_DIR="$SRC"
if [ -n "$REF" ]; then
  BUILD_DIR="$OUT_DIR/sdk-worktree-${LABEL:-ref}"
  rm -rf "$BUILD_DIR"
  git -C "$SRC" worktree prune
  git -C "$SRC" worktree add --detach "$(cd "$OUT_DIR" && pwd)/sdk-worktree-${LABEL:-ref}" "$REF"
  git -C "$BUILD_DIR" submodule update --init --recursive --depth 1
fi
# Known build-time nuisance in the SDK repo: a symlinked .clang-format inside a native submodule.
rm -f "$BUILD_DIR/backtrace-library/src/main/cpp/libbun/external/libunwindstack-ndk/.clang-format" || true
mkdir -p "$M2"
before=$(ls -1 "$M2" 2>/dev/null | sort || true)
( cd "$BUILD_DIR" && ./gradlew --no-daemon -q :backtrace-library:publishToMavenLocal -PRELEASE_SIGNING_ENABLED=false -x lint -x test )
after=$(ls -1 "$M2" | sort)
new=$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | head -1 || true)
if [ -z "$new" ]; then new=$(ls -1t "$M2" | head -1); fi
[ -n "$new" ] || { echo "no published version found under $M2" >&2; exit 1; }
suffix=""; [ -n "$LABEL" ] && suffix="-$LABEL"
echo "$new" > "$OUT_DIR/local-version${suffix}.txt"
echo "published backtrace-library $new to mavenLocal (label: ${LABEL:-none}, ref: ${REF:-working tree})"
