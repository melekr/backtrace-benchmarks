#!/usr/bin/env python3
"""Tier-0 size ladders from published SDK artifacts (docs/CONVENTIONS.md sections 1, 3).

  fetch_artifacts.py --sdk android|apple|unity|all [--versions v1,v2] [--out artifacts]
                     [--results DIR] [--markdown FILE] [--run-id ID] [--env env.json] [--offline]

Sources (downloaded once, cached under --out/<sdk>/):
  android  Maven Central  backtrace-library-<v>.aar
  apple    GitHub Release Archive_XCFrameworks_<v>.tar.gz
  unity    OpenUPM        io.backtrace.unity-<v>.tgz
Rows follow schema/result.schema.json (variant sdk, scenario default, stats n=1 exact,
env tier0) and are written to <results>/<sdk>/tier0/<version>/tier0-<run-id>.jsonl.
Nothing here contacts a Backtrace endpoint; only the public artifact hosts above.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402

URLS = {
    "android": "https://repo1.maven.org/maven2/com/github/backtrace-labs/backtrace-android/backtrace-library/{v}/backtrace-library-{v}.aar",
    "apple": "https://github.com/backtrace-labs/backtrace-cocoa/releases/download/{v}/Archive_XCFrameworks_{v}.tar.gz",
    "unity": "https://package.openupm.com/io.backtrace.unity/-/io.backtrace.unity-{v}.tgz",
}
SOURCE = {"android": "maven", "apple": "xcframework", "unity": "openupm"}
FILENAME = {"android": "backtrace-library-{v}.aar", "apple": "Archive_XCFrameworks_{v}.tar.gz", "unity": "io.backtrace.unity-{v}.tgz"}
USER_AGENT = "backtrace-benchmarks-fetch/1.0 (+python-urllib)"


class FetchError(RuntimeError):
    pass


# ------------------------------------------------------------------ download

def download(url: str, dest: str, retries: int = 3, offline: bool = False) -> str:
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return "cached"
    if offline:
        raise FetchError(f"offline and not cached: {dest}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    last: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp, dest)
            return "downloaded"
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (401, 403, 404, 410):
                break
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
        time.sleep(min(2 ** attempt, 8))
    if os.path.exists(tmp):
        os.remove(tmp)
    raise FetchError(f"download failed for {url}: {last}")


# ------------------------------------------------------------- archive views

def tar_members(path: str) -> List[Tuple[str, int, bool]]:
    """(name, size, is_regular_file) for every member."""
    out = []
    with tarfile.open(path, "r:*") as tf:
        for m in tf.getmembers():
            out.append((m.name, m.size, m.isreg()))
    return out


def zip_members(path: str) -> List[Tuple[str, int, bool]]:
    out = []
    with zipfile.ZipFile(path) as zf:
        for zi in zf.infolist():
            out.append((zi.filename, zi.file_size, not zi.is_dir()))
    return out


def _norm(name: str) -> str:
    return name[2:] if name.startswith("./") else name


# ------------------------------------------------------------------ android

def android_metrics(members: Iterable[Tuple[str, int, bool]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    so_by_abi: Dict[str, int] = {}
    for name, size, is_file in members:
        if not is_file:
            continue
        name = _norm(name)
        if name == "classes.jar":
            out["A0.classes_jar_bytes"] = size
        m = re.match(r"^jni/([^/]+)/[^/]+\.so$", name)
        if m:
            so_by_abi[m.group(1)] = so_by_abi.get(m.group(1), 0) + size
    for abi, size in sorted(so_by_abi.items()):
        out[f"A0.so_bytes.{abi}"] = size
    out["A0.so_total_bytes"] = sum(so_by_abi.values())
    return out


# -------------------------------------------------------------------- apple

def framework_binaries(members: Iterable[Tuple[str, int, bool]], xcframework: str, fw_name: str) -> Dict[str, int]:
    """slice -> bytes of the framework binary. Prefers Framework/<Name>, then Versions/A/<Name>."""
    rx = re.compile(
        r"(?:^|/)" + re.escape(xcframework) + r"\.xcframework/([^/]+)/" + re.escape(fw_name)
        + r"\.framework/(?:Versions/([^/]+)/)?" + re.escape(fw_name) + r"$"
    )
    cands: Dict[str, List[Tuple[int, int]]] = {}
    for name, size, is_file in members:
        if not is_file:
            continue
        name = _norm(name)
        if "/dSYMs/" in name or ".dSYM/" in name:
            continue
        m = rx.search(name)
        if not m:
            continue
        slice_, ver = m.group(1), m.group(2)
        rank = 0 if ver is None else (1 if ver != "Current" else 2)
        cands.setdefault(slice_, []).append((rank, size))
    return {s: sorted(v)[0][1] for s, v in cands.items()}


def apple_metrics(members: Iterable[Tuple[str, int, bool]]) -> Dict[str, int]:
    members = list(members)
    out: Dict[str, int] = {}
    for slice_, size in sorted(framework_binaries(members, "Backtrace", "Backtrace").items()):
        out[f"C0.xcframework_slice_bytes.{slice_}"] = size
    for slice_, size in sorted(framework_binaries(members, "CrashReporter", "CrashReporter").items()):
        out[f"C0.crashreporter_slice_bytes.{slice_}"] = size
    return out


# -------------------------------------------------------------------- unity

def unity_metrics(members: Iterable[Tuple[str, int, bool]]) -> Dict[str, int]:
    members = [(_norm(n), s, f) for n, s, f in members]
    out: Dict[str, int] = {}
    natives: Dict[str, Dict[str, int]] = {"android": {}, "ios": {}, "macos": {}, "windows": {}}

    def bump(platform: str, abi: str, size: int) -> None:
        natives[platform][abi] = natives[platform].get(abi, 0) + size

    managed = 0
    for name, size, is_file in members:
        if not is_file or name.endswith(".meta"):
            continue
        rel = name.split("/", 1)[1] if name.startswith("package/") else name
        if rel.startswith("Runtime/") and rel.endswith(".cs"):
            managed += size
            continue
        m = re.match(r"^Android/.*?(?:^|/)(arm64-v8a|armeabi-v7a|x86_64|x86)/[^/]+\.so$", rel)
        if m:
            bump("android", m.group(1), size)
            continue
        if rel.startswith("iOS/"):
            if ".dSYM/" in rel or "/dSYMs/" in rel:
                continue
            m = re.match(r"^iOS/(?:.*/)?[^/]+\.xcframework/([^/]+)/([^/]+)\.framework/(?:Versions/A/)?\2$", rel)
            if m:
                bump("ios", m.group(1), size)
                continue
            m = re.match(r"^iOS/(?:.*/)?lib[^/]*?-([A-Za-z0-9_]+(?:-sim)?)\.a$", rel)
            if m:
                bump("ios", m.group(1), size)
                continue
            if rel.endswith(".a"):
                bump("ios", "static", size)
                continue
        if rel.startswith("Mac/") or rel.startswith("macOS/"):
            if re.search(r"\.bundle/Contents/MacOS/[^/]+$", rel) or re.search(r"\.framework/Versions/[^/]+/[^/.]+$", rel) and "Current" not in rel:
                bump("macos", "bundle", size)
                continue
            if rel.endswith((".dylib", ".bundle")):
                bump("macos", "bundle", size)
                continue
        m = re.match(r"^Windows/(?:.*/)?(x86_64|x86|arm64|ARM64)/[^/]+\.dll$", rel)
        if m:
            bump("windows", m.group(1).lower(), size)
            continue
    for platform, abis in natives.items():
        if not abis:
            continue
        for abi, size in sorted(abis.items()):
            out[f"U0.native_bytes.{platform}.{abi}"] = size
        if len(abis) > 1:
            out[f"U0.native_bytes.{platform}.total"] = sum(abis.values())
    out["U0.managed_source_bytes"] = managed
    return out


# --------------------------------------------------------------------- rows

def measure(sdk: str, version: str, path: str) -> Dict[str, int]:
    if sdk == "android":
        metrics = {"A0.aar_bytes": os.path.getsize(path)}
        metrics.update(android_metrics(zip_members(path)))
    elif sdk == "apple":
        metrics = {"C0.archive_bytes": os.path.getsize(path)}
        metrics.update(apple_metrics(tar_members(path)))
    elif sdk == "unity":
        metrics = {"U0.tgz_bytes": os.path.getsize(path)}
        metrics.update(unity_metrics(tar_members(path)))
    else:
        raise ValueError(sdk)
    return metrics


def make_rows(sdk: str, version: str, metrics: Dict[str, int], env: Dict[str, Any], run: Dict[str, Any],
              catalog: hc.MetricCatalog, note: str) -> List[Dict[str, Any]]:
    rows = []
    for mid, value in metrics.items():
        entry = catalog.resolve(mid)
        if entry is None:
            print(f"fetch_artifacts: {mid} not in metrics.yml, skipping", file=sys.stderr)
            continue
        rows.append({
            "schemaVersion": 1, "sdk": sdk, "sdkVersion": version, "source": SOURCE[sdk], "variant": "sdk",
            "scenario": "default", "metric": mid, "unit": entry["unit"], "value": value, "samples": [value],
            "stats": {"n": 1, "median": value, "mean": value, "mad": 0, "p95": value, "min": value, "max": value, "cov": 0, "sampleKind": "exact"},
            "env": env, "run": run, "valid": True, "notes": note,
        })
    return rows


def ladder_table(sdk: str, per_version: Dict[str, Dict[str, int]], versions: List[str]) -> str:
    """Markdown: metrics as rows, versions as columns, delta vs the previous column."""
    present = [v for v in versions if v in per_version]
    metrics: List[str] = []
    for v in present:
        for m in per_version[v]:
            if m not in metrics:
                metrics.append(m)
    metrics.sort(key=lambda m: (m.split(".")[0], m))
    rows = []
    for m in metrics:
        cells: List[str] = [f"`{m}`"]
        prev: Optional[int] = None
        for v in present:
            val = per_version[v].get(m)
            if val is None:
                cells.append("n/a")
            elif prev in (None, 0):
                cells.append(hc.fmt_int(val))
            else:
                cells.append(f"{hc.fmt_int(val)} ({hc.fmt_pct(val / prev - 1)})")
            prev = val if val is not None else prev
        rows.append(cells)
    return hc.md_table(["metric (bytes)"] + present, rows)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdk", required=True, choices=list(hc.SDKS) + ["all"])
    ap.add_argument("--versions", help="comma-separated override of the ladder in docs/CONVENTIONS.md section 3")
    ap.add_argument("--out", default="artifacts", help="download cache directory")
    ap.add_argument("--results", help="write rows to <results>/<sdk>/tier0/<version>/tier0-<run-id>.jsonl")
    ap.add_argument("--markdown", help="also write the ladder tables to this file")
    ap.add_argument("--json", help="write {sdk: {version: {metric: bytes}}} to this file")
    ap.add_argument("--run-id")
    ap.add_argument("--workflow")
    ap.add_argument("--sha")
    ap.add_argument("--env", help="env.json (default: env_fingerprint.sh --tier tier0)")
    ap.add_argument("--offline", action="store_true", help="fail instead of downloading missing artifacts")
    ap.add_argument("--metrics", default=hc.METRICS_PATH)
    args = ap.parse_args(argv)

    sdks = list(hc.SDKS) if args.sdk == "all" else [args.sdk]
    if args.versions and args.sdk == "all":
        ap.error("--versions needs a single --sdk")
    catalog = hc.load_metrics(args.metrics)
    env = hc.load_env(args.env, tier="tier0")
    run = hc.make_run(args.run_id, args.workflow, args.sha)
    run_id = run["id"]

    all_tables: List[str] = []
    all_json: Dict[str, Dict[str, Dict[str, int]]] = {}
    failures: List[str] = []
    written: List[str] = []
    for sdk in sdks:
        versions = [v.strip() for v in args.versions.split(",")] if args.versions else list(hc.LADDERS[sdk])
        per_version: Dict[str, Dict[str, int]] = {}
        for v in versions:
            url = URLS[sdk].format(v=v)
            dest = os.path.join(args.out, sdk, FILENAME[sdk].format(v=v))
            try:
                how = download(url, dest, offline=args.offline)
                metrics = measure(sdk, v, dest)
            except (FetchError, tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
                failures.append(f"{sdk} {v}: {exc}")
                print(f"fetch_artifacts: FAILED {sdk} {v}: {exc}", file=sys.stderr)
                continue
            sha = hc.sha256_file(dest)
            print(f"fetch_artifacts: {sdk} {v} {how} {hc.fmt_int(os.path.getsize(dest))} bytes sha256={sha[:16]}...", file=sys.stderr)
            per_version[v] = metrics
            note = f"source={url} sha256={sha}"
            rows = make_rows(sdk, v, metrics, env, run, catalog, note)
            if args.results:
                out_dir = os.path.join(args.results, sdk, "tier0", v)
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, f"tier0-{run_id}.jsonl")
                hc.write_rows(rows, out_path)
                written.append(out_path)
        all_json[sdk] = per_version
        if per_version:
            table = f"### {sdk} (source: {SOURCE[sdk]})\n\n" + ladder_table(sdk, per_version, versions)
            all_tables.append(table)
    md = "\n\n".join(all_tables) + "\n"
    print(md)
    if args.markdown:
        os.makedirs(os.path.dirname(os.path.abspath(args.markdown)), exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(md)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(all_json, fh, indent=2, sort_keys=True)
    if written:
        print(f"fetch_artifacts: wrote {len(written)} row file(s) under {args.results}", file=sys.stderr)
    if failures:
        print("fetch_artifacts: failures:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
