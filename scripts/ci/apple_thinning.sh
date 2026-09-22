#!/usr/bin/env bash
# Optional signed lane: build a signed iOS archive of a bench app target and export it with app thinning to obtain the
# App Thinning Size Report (compressed = download size, uncompressed = install size per device variant).
# Emits rows C3.thinning_download_bytes.<variant> and C3.thinning_install_bytes.<variant>. Reports `unsupported` (exit 4)
# when the provisioning profile cannot be used for an ad-hoc/development export.
#
# Env (from GitHub secrets): BUILD_CERTIFICATE_BASE64_2026, P12_PASSWORD_2026, BUILD_PROVISION_PROFILE_BASE64_2026,
#                             KEYCHAIN_PASSWORD, DISTRIBUTION_IDENTITY
# Usage: apple_thinning.sh --project apple/BenchApp.xcodeproj --scheme BenchApp-sdk --bundle-id io.backtrace.bench.sdk.v2_2_0 \
#            --sdk-version 2.2.0 --variant sdk --env env.json --run-id <id> --out out/apple/rows/thinning-sdk.jsonl
set -euo pipefail
PROJECT=""; SCHEME=""; BUNDLE_ID=""; SDK_VERSION=""; VARIANT="sdk"; SOURCE="xcframework"; ENV_JSON="env.json"; RUN_ID="local"; OUT=""
while [ $# -gt 0 ]; do case "$1" in
  --project) PROJECT="$2"; shift 2;; --scheme) SCHEME="$2"; shift 2;; --bundle-id) BUNDLE_ID="$2"; shift 2;;
  --sdk-version) SDK_VERSION="$2"; shift 2;; --variant) VARIANT="$2"; shift 2;; --env) ENV_JSON="$2"; shift 2;;
  --run-id) RUN_ID="$2"; shift 2;; --out) OUT="$2"; shift 2;; --source) SOURCE="$2"; shift 2;; *) echo "unknown arg $1" >&2; exit 1;; esac; done
: "${PROJECT:?}" "${SCHEME:?}" "${BUNDLE_ID:?}" "${SDK_VERSION:?}" "${OUT:?}"
for v in BUILD_CERTIFICATE_BASE64_2026 P12_PASSWORD_2026 BUILD_PROVISION_PROFILE_BASE64_2026 KEYCHAIN_PASSWORD DISTRIBUTION_IDENTITY; do
  [ -n "${!v:-}" ] || { echo "missing $v; signed lane skipped"; exit 4; }
done
WORK="$(mktemp -d)"; KEYCHAIN="$WORK/bench.keychain-db"
cleanup() { security delete-keychain "$KEYCHAIN" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
echo "$BUILD_CERTIFICATE_BASE64_2026" | base64 --decode > "$WORK/cert.p12"
echo "$BUILD_PROVISION_PROFILE_BASE64_2026" | base64 --decode > "$WORK/profile.mobileprovision"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security import "$WORK/cert.p12" -P "$P12_PASSWORD_2026" -A -t cert -f pkcs12 -k "$KEYCHAIN" >/dev/null
security set-key-partition-list -S apple-tool:,apple: -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
security list-keychain -d user -s "$KEYCHAIN" login.keychain-db
# Profile facts: UUID, name, team, app id, and whether it is usable for ad-hoc/development export.
PLIST="$WORK/profile.plist"; security cms -D -i "$WORK/profile.mobileprovision" > "$PLIST"
UUID=$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$PLIST"); PNAME=$(/usr/libexec/PlistBuddy -c 'Print :Name' "$PLIST")
TEAM=$(/usr/libexec/PlistBuddy -c 'Print :TeamIdentifier:0' "$PLIST"); APPID=$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' "$PLIST")
HAS_DEVICES=$(/usr/libexec/PlistBuddy -c 'Print :ProvisionedDevices' "$PLIST" >/dev/null 2>&1 && echo yes || echo no)
GET_TASK_ALLOW=$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:get-task-allow' "$PLIST" 2>/dev/null || echo false)
mkdir -p "$HOME/Library/MobileDevice/Provisioning Profiles"; cp "$WORK/profile.mobileprovision" "$HOME/Library/MobileDevice/Provisioning Profiles/$UUID.mobileprovision"
APPID_SUFFIX="${APPID#*.}"
case "$APPID_SUFFIX" in
  "*"|"${BUNDLE_ID}") ;;
  *".*") prefix="${APPID_SUFFIX%\*}"; [[ "$BUNDLE_ID" == "$prefix"* ]] || { echo "profile app id $APPID does not cover $BUNDLE_ID"; exit 4; };;
  *) echo "profile app id $APPID does not cover $BUNDLE_ID"; exit 4;;
esac
if [ "$HAS_DEVICES" != "yes" ]; then echo "profile has no provisioned devices: App Store profiles cannot produce a thinning report"; exit 4; fi
METHOD="ad-hoc"; [ "$GET_TASK_ALLOW" = "true" ] && METHOD="development"
ARCHIVE="$WORK/$SCHEME.xcarchive"; EXPORT="$WORK/export"
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -configuration Release -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" archive CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM="$TEAM" \
  CODE_SIGN_IDENTITY="$DISTRIBUTION_IDENTITY" PROVISIONING_PROFILE_SPECIFIER="$UUID" PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" -quiet
cat > "$WORK/export.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>$METHOD</string>
  <key>signingStyle</key><string>manual</string>
  <key>teamID</key><string>$TEAM</string>
  <key>signingCertificate</key><string>$DISTRIBUTION_IDENTITY</string>
  <key>provisioningProfiles</key><dict><key>$BUNDLE_ID</key><string>$PNAME</string></dict>
  <key>thinning</key><string>&lt;thin-for-all-variants&gt;</string>
  <key>compileBitcode</key><false/>
  <key>stripSwiftSymbols</key><true/>
</dict></plist>
PL
xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportPath "$EXPORT" -exportOptionsPlist "$WORK/export.plist" -quiet
REPORT="$EXPORT/App Thinning Size Report.txt"; [ -f "$REPORT" ] || { echo "no thinning report produced"; exit 1; }
python3 - "$REPORT" "$OUT" "$SDK_VERSION" "$VARIANT" "$ENV_JSON" "$RUN_ID" "$SOURCE" <<'PY'
import json, re, sys, datetime
report, out, ver, variant, env_path, run_id, source = sys.argv[1:8]
env = json.load(open(env_path)) if env_path and __import__("os").path.exists(env_path) else {"fingerprint": "unknown"}
text = open(report, encoding="utf-8", errors="replace").read()
rows = []
def to_bytes(s):
    n, unit = re.match(r"([\d.,]+)\s*(KB|MB|GB|bytes)", s).groups(); n = float(n.replace(",", ""))
    return int(n * {"bytes": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3}[unit])
for block in re.split(r"\n(?=Variant: )", text):
    m = re.search(r"Variant: (.+)", block)
    if not m: continue
    variant_name = m.group(1).strip().replace(".ipa", "")
    dl = re.search(r"App size: ([\d.,]+ \w+) compressed, ([\d.,]+ \w+) uncompressed", block)
    if not dl: continue
    for metric, val in (("C3.thinning_download_bytes." + variant_name, to_bytes(dl.group(1))), ("C3.thinning_install_bytes." + variant_name, to_bytes(dl.group(2)))):
        rows.append({"schemaVersion": 1, "sdk": "apple", "platform": "ios", "sdkVersion": ver, "source": source, "variant": variant,
                     "scenario": "default", "metric": metric, "unit": "bytes", "value": val, "samples": [val],
                     "stats": {"n": 1, "sampleKind": "exact"}, "env": env,
                     "run": {"id": run_id, "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "workflow": "bench-apple"}, "valid": True})
import os; os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
with open(out, "w") as f:
    for r in rows: f.write(json.dumps(r) + "\n")
print(f"wrote {len(rows)} thinning rows to {out}")
PY
