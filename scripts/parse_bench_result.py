#!/usr/bin/env python3
"""Convert bench-result.json files (schema/bench-result.schema.json, all platforms) to result rows.

  parse_bench_result.py FILE_OR_DIR [...] --variant sdk --round 1 --position 0 --env env.json \
      [--sdk android] [--sdk-version 3.14.0] [--source maven] [--scenario default] \
      [--expect-mock-requests N] [--run-id ID] [--workflow W] [--sha SHA] [--out rows.jsonl]

Mapping (prefix A=android, C=apple, U=unity):
  stages[].ms            -> <prefix>1.init.<stage>   (sampleKind perLaunch, one sample per file)
  totalMs                -> <prefix>1.init.total
  counters.threads_after_init -> A7/C7.threads_after_init (perLaunch)
  samples{metric: [..]}  -> that metric id, sampleKind perIteration, pooled across files
Validity (fail-closed): any stage ok:false, counters.mock_requests != --expect-mock-requests,
or a rate-limit / debugger-attached indication in errors/counters marks every row of that
launch, and hence the pooled row, as valid:false with a note.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402
import stats as st  # noqa: E402

THREADS_METRIC = {"android": "A7.threads_after_init", "apple": "C7.threads_after_init"}
DEFAULT_SOURCE = {"android": "maven", "apple": "xcframework", "unity": "openupm"}


def find_files(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "**", "bench-result*.json"), recursive=True)))
            out.extend(sorted(glob.glob(os.path.join(p, "**", "bt-bench-stages*.json"), recursive=True)))
        else:
            out.append(p)
    seen = set()
    uniq = []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def launch_problems(doc: Dict[str, Any], expect_mock: Optional[int]) -> List[str]:
    """Reasons that make one launch invalid (docs/CONVENTIONS.md section 9)."""
    problems: List[str] = []
    for s in doc.get("stages", []):
        if s.get("ok") is False:
            problems.append(f"stage {s.get('name')} reported ok=false")
    counters = doc.get("counters") or {}
    if expect_mock is not None:
        got = counters.get("mock_requests")
        if got is None:
            problems.append("counters.mock_requests missing while --expect-mock-requests given")
        elif int(got) != expect_mock:
            problems.append(f"mock_requests={int(got)} expected {expect_mock}")
    for key in ("rate_limited", "rate_limit_hits", "debugger_attached"):
        if counters.get(key, 0):
            problems.append(f"counters.{key}={counters[key]}")
    for e in doc.get("errors") or []:
        low = str(e).lower()
        if "rate" in low and "limit" in low:
            problems.append(f"error: {e}")
        elif "debugger" in low:
            problems.append(f"error: {e}")
    return problems


def _required(doc: Dict[str, Any], path: str) -> None:
    for k in ("schemaVersion", "sdk", "sdkVersion", "variant", "scenario", "appId", "stages", "totalMs"):
        if k not in doc:
            raise ValueError(f"{path}: bench-result.json missing required key {k!r}")
    if doc["schemaVersion"] != 1:
        raise ValueError(f"{path}: unsupported bench-result schemaVersion {doc['schemaVersion']!r}")
    if doc["sdk"] not in hc.SDKS:
        raise ValueError(f"{path}: unknown sdk {doc['sdk']!r}")


def collect(files: List[str], expect_mock: Optional[int], catalog: hc.MetricCatalog,
            sdk_override: Optional[str] = None, keep_unknown: bool = False) -> Tuple[Dict[str, Dict[str, Any]], List[str], Dict[str, Any]]:
    """Pool per-metric samples across files. Returns (metrics, problems, meta)."""
    pooled: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    meta: Dict[str, Any] = {}
    unknown: List[str] = []

    def add(mid: str, unit: str, kind: str, value: float) -> None:
        slot = pooled.setdefault(mid, {"unit": unit, "sampleKind": kind, "samples": []})
        if slot["sampleKind"] != kind:
            problems.append(f"{mid}: mixed sampleKind {slot['sampleKind']} vs {kind}")
        slot["samples"].append(float(value))

    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        _required(doc, path)
        sdk = sdk_override or doc["sdk"]
        prefix = hc.SDK_PREFIX[sdk]
        for key in ("sdk", "sdkVersion", "variant", "scenario", "source", "platform", "appId"):
            if doc.get(key) is not None:
                prev = meta.setdefault(key, doc[key])
                if prev != doc[key]:
                    problems.append(f"{os.path.basename(path)}: {key}={doc[key]!r} differs from {prev!r} in another file")
        for s in doc.get("stages", []):
            add(f"{prefix}1.init.{s['name']}", "ms", "perLaunch", s["ms"])
        if doc.get("stages"):
            # A launch without stages (plain apps, in-process micro files) has no init total to report.
            add(f"{prefix}1.init.total", "ms", "perLaunch", doc["totalMs"])
        counters = doc.get("counters") or {}
        if "threads_after_init" in counters and sdk in THREADS_METRIC:
            add(THREADS_METRIC[sdk], "count", "perLaunch", counters["threads_after_init"])
        for mid, samples in (doc.get("samples") or {}).items():
            entry = catalog.resolve(mid)
            if entry is None and not keep_unknown:
                unknown.append(mid)
                continue
            unit = entry["unit"] if entry else "ms"
            for v in samples:
                add(mid, unit, "perIteration", v)
        for p in launch_problems(doc, expect_mock):
            problems.append(f"{os.path.basename(path)}: {p}")
    if unknown:
        print(f"parse_bench_result: skipped unknown sample metrics: {sorted(set(unknown))}", file=sys.stderr)
    return pooled, problems, meta


def build_rows(pooled: Dict[str, Dict[str, Any]], problems: List[str], meta: Dict[str, Any], args: argparse.Namespace,
               env: Dict[str, Any], catalog: hc.MetricCatalog) -> List[Dict[str, Any]]:
    sdk = args.sdk or meta.get("sdk")
    if sdk not in hc.SDKS:
        raise ValueError("sdk unknown: pass --sdk")
    version = args.sdk_version or meta.get("sdkVersion")
    if not version:
        raise ValueError("sdkVersion unknown: pass --sdk-version")
    source = args.source or meta.get("source") or DEFAULT_SOURCE[sdk]
    variant = args.variant or meta.get("variant")
    if variant not in hc.VARIANTS:
        raise ValueError("variant unknown: pass --variant plain|sdk|sentinel")
    scenario = args.scenario or meta.get("scenario") or "default"
    run = hc.make_run(args.run_id, args.workflow, args.sha)
    rows: List[Dict[str, Any]] = []
    for mid in sorted(pooled):
        slot = pooled[mid]
        entry = catalog.resolve(mid)
        unit = entry["unit"] if entry else slot["unit"]
        s = st.summarize(slot["samples"], slot["sampleKind"])
        row: Dict[str, Any] = {
            "schemaVersion": 1, "sdk": sdk, "sdkVersion": str(version), "source": source, "variant": variant,
            "scenario": scenario, "metric": mid, "unit": unit, "value": s["median"], "samples": slot["samples"],
            "stats": s, "env": env, "run": run, "valid": not problems,
        }
        if meta.get("platform") or args.platform:
            row["platform"] = args.platform or meta["platform"]
        if args.round is not None:
            row["round"] = args.round
        if args.position is not None:
            row["position"] = args.position
        if problems:
            row["notes"] = "; ".join(problems)
        rows.append(row)
    return rows


def drop_metrics(pooled: Dict[str, Dict[str, Any]], patterns: List[str], rows_path: Optional[str]) -> List[str]:
    """Remove pooled metric ids matching any glob in `patterns` (comma-separated, repeatable) or already present
    in `rows_path` (a rows.jsonl written by a platform parser, which then takes precedence). Returns the ids dropped."""
    globs = [g for arg in patterns for g in arg.split(",") if g]
    covered = set()
    if rows_path and os.path.exists(rows_path):
        with open(rows_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    covered.add(json.loads(line).get("metric"))
    dropped = [mid for mid in pooled if mid in covered or any(fnmatch.fnmatchcase(mid, g) for g in globs)]
    for mid in dropped:
        del pooled[mid]
    return dropped


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="bench-result*.json files or directories containing them")
    ap.add_argument("--sdk", choices=hc.SDKS)
    ap.add_argument("--sdk-version")
    ap.add_argument("--source", choices=hc.SOURCES)
    ap.add_argument("--variant", choices=hc.VARIANTS)
    ap.add_argument("--scenario")
    ap.add_argument("--platform")
    ap.add_argument("--round", type=int)
    ap.add_argument("--position", type=int)
    ap.add_argument("--env", help="env.json from env_fingerprint.sh (default: run it)")
    ap.add_argument("--tier", default="tier1")
    ap.add_argument("--run-id")
    ap.add_argument("--workflow")
    ap.add_argument("--sha")
    ap.add_argument("--expect-mock-requests", type=int)
    ap.add_argument("--keep-unknown-metrics", action="store_true")
    ap.add_argument("--exclude-metrics", action="append", default=[],
                    help="glob(s) of metric ids to drop, e.g. 'C1.*' (repeatable or comma-separated)")
    ap.add_argument("--exclude-metrics-in", metavar="ROWS_JSONL",
                    help="drop metric ids already present in this rows file (the platform parser's output wins)")
    ap.add_argument("--metrics", default=hc.METRICS_PATH)
    ap.add_argument("--out", help="rows.jsonl (default stdout)")
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args(argv)

    files = find_files(args.paths)
    if not files:
        print("parse_bench_result: no bench-result*.json found", file=sys.stderr)
        return 1
    catalog = hc.load_metrics(args.metrics)
    try:
        pooled, problems, meta = collect(files, args.expect_mock_requests, catalog, args.sdk, args.keep_unknown_metrics)
        dropped = drop_metrics(pooled, args.exclude_metrics, args.exclude_metrics_in)
        if dropped:
            print(f"parse_bench_result: dropped {len(dropped)} excluded metric(s): {sorted(dropped)}", file=sys.stderr)
        env = hc.load_env(args.env, tier=args.tier)
        rows = build_rows(pooled, problems, meta, args, env, catalog)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"parse_bench_result: {exc}", file=sys.stderr)
        return 1
    hc.write_rows(rows, args.out, append=args.append)
    if problems:
        print(f"parse_bench_result: {len(rows)} rows from {len(files)} file(s) marked INVALID: {'; '.join(problems)}", file=sys.stderr)
    else:
        print(f"parse_bench_result: {len(rows)} valid rows from {len(files)} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
