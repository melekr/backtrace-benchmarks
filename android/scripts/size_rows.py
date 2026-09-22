#!/usr/bin/env python3
"""Integrated-size rows (A3) for one built variant: APK bytes, per-ABI native bytes, DEX method references and
bundletool install-size estimates per device spec.

  size_rows.py --apk app.apk [--aab app.aab --bundletool bundletool.jar] [--apkanalyzer PATH]
               --sdk-version V --variant plain|sdk|sentinel [--source maven] --env env.json [--run-id ID] --out rows.jsonl
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

SPECS = {
    "arm64-v8a": {"supportedAbis": ["arm64-v8a"], "supportedLocales": ["en"], "screenDensity": 420, "sdkVersion": 34},
    "armeabi-v7a": {"supportedAbis": ["armeabi-v7a"], "supportedLocales": ["en"], "screenDensity": 420, "sdkVersion": 34},
    "x86_64": {"supportedAbis": ["x86_64"], "supportedLocales": ["en"], "screenDensity": 420, "sdkVersion": 34},
}


def so_bytes(apk):
    per = {}
    with zipfile.ZipFile(apk) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if len(parts) == 3 and parts[0] == "lib" and parts[2].endswith(".so"):
                per[parts[1]] = per.get(parts[1], 0) + info.file_size
    return per


def dex_refs(apkanalyzer, apk):
    if not apkanalyzer:
        return None
    try:
        out = subprocess.run([apkanalyzer, "dex", "references", apk], capture_output=True, text=True, timeout=300)
        return int(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def install_sizes(bundletool, aab):
    if not (bundletool and aab and os.path.exists(aab)):
        return {}
    keystore = os.path.expanduser("~/.android/debug.keystore")
    if not os.path.exists(keystore):
        os.makedirs(os.path.dirname(keystore), exist_ok=True)
        subprocess.run(["keytool", "-genkeypair", "-keystore", keystore, "-storepass", "android", "-alias", "androiddebugkey",
                        "-keypass", "android", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
                        "-dname", "CN=Android Debug,O=Android,C=US"], check=False, capture_output=True)
    sizes = {}
    work = tempfile.mkdtemp(prefix="bt-size-")
    try:
        for abi, spec in SPECS.items():
            spec_path = os.path.join(work, abi + ".json")
            json.dump(spec, open(spec_path, "w"))
            apks = os.path.join(work, abi + ".apks")
            cmd = ["java", "-jar", bundletool, "build-apks", "--bundle=" + aab, "--output=" + apks, "--device-spec=" + spec_path,
                   "--ks=" + keystore, "--ks-pass=pass:android", "--ks-key-alias=androiddebugkey", "--key-pass=pass:android"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                print("size_rows: build-apks failed for %s: %s" % (abi, r.stderr.strip()[-400:]), file=sys.stderr)
                continue
            g = subprocess.run(["java", "-jar", bundletool, "get-size", "total", "--apks=" + apks, "--device-spec=" + spec_path],
                               capture_output=True, text=True, timeout=300)
            if g.returncode != 0:
                print("size_rows: get-size failed for %s: %s" % (abi, g.stderr.strip()[-400:]), file=sys.stderr)
                continue
            # Output: "MIN,MAX" (header line "MIN,MAX" then values in older versions)
            lines = [l for l in g.stdout.strip().splitlines() if l and not l.startswith("MIN")]
            if lines:
                mn, mx = lines[-1].split(",")[:2]
                sizes[abi] = int(mx)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return sizes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apk", required=True)
    ap.add_argument("--aab")
    ap.add_argument("--bundletool")
    ap.add_argument("--apkanalyzer")
    ap.add_argument("--sdk-version", required=True)
    ap.add_argument("--variant", required=True, choices=["plain", "sdk", "sentinel"])
    ap.add_argument("--source", default="maven", choices=["maven", "local"])
    ap.add_argument("--scenario", default="default")
    ap.add_argument("--env")
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--workflow", default="bench-android")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    env = json.load(open(a.env)) if a.env and os.path.exists(a.env) else {"fingerprint": "unknown", "tier": "tier1"}
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def row(metric, unit, value):
        return {"schemaVersion": 1, "sdk": "android", "platform": "android", "sdkVersion": a.sdk_version, "source": a.source,
                "variant": a.variant, "scenario": a.scenario, "metric": metric, "unit": unit, "value": value, "samples": [value],
                "stats": {"n": 1, "sampleKind": "exact"}, "env": env, "run": {"id": a.run_id, "ts": ts, "workflow": a.workflow}, "valid": True}

    rows = [row("A3.apk_universal_bytes", "bytes", os.path.getsize(a.apk))]
    for abi, size in sorted(so_bytes(a.apk).items()):
        rows.append(row("A3.so_bytes." + abi, "bytes", size))
    refs = dex_refs(a.apkanalyzer, a.apk)
    if refs is not None:
        rows.append(row("A3.dex_method_refs", "count", refs))
    for abi, size in sorted(install_sizes(a.bundletool, a.aab).items()):
        rows.append(row("A3.install_bytes." + abi, "bytes", size))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("size_rows: wrote %d rows to %s" % (len(rows), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
