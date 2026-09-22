#!/usr/bin/env python3
"""Convert XCTest performance metrics from an .xcresult bundle to result rows (Xcode 16+ xcresulttool).

  xcresult_to_rows.py BUNDLE.xcresult --sdk-version 2.2.0 --variant sdk [--scenario default] [--source xcframework]
                      [--round R --position P] --env env.json [--run-id ID] [--out rows.jsonl]

Uses `xcrun xcresulttool get test-results metrics --path BUNDLE --compact`, which returns per test the list of
metrics with per-iteration `measurements` and `unitOfMeasurement`. Mapping (test identifier, metric identifier):
  SendTests/testSendEndToEnd        Clock -> C4.send.e2e_ms   CPU time -> C4.send.cpu_ms   Memory peak -> C4.send.memory_peak_kb (bytes)
  SendTests/testSendCallerThreadOnly Clock -> C4.send.caller_ms
  BreadcrumbTests/testAddBreadcrumbRetained<N> Clock -> C5.breadcrumb.add_us.retained_<N>
  LaunchTests/*                      ApplicationLaunch -> C2.launch_ms   OSSignpost (duration) -> C1.init.total
Stdlib only.
"""
import argparse
import datetime
import json
import math
import re
import statistics
import subprocess
import sys

UNIT_TO_MS = {"s": 1000.0, "ms": 1.0, "us": 0.001, "µs": 0.001}


def summary(samples, kind="perIteration"):
    xs = sorted(samples)
    n = len(xs)
    med = statistics.median(xs)
    mean = statistics.fmean(xs)
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    return {"n": n, "median": med, "mean": mean, "mad": statistics.median([abs(x - med) for x in xs]),
            "p95": xs[min(n - 1, int(math.ceil(0.95 * n)) - 1)], "min": xs[0], "max": xs[-1],
            "cov": (sd / mean) if mean else 0.0, "sampleKind": kind}


def map_metric(test_id, metric):
    ident = metric.get("identifier", "")
    unit = metric.get("unitOfMeasurement", "")
    vals = [float(v) for v in metric.get("measurements", [])]
    if not vals:
        return None
    is_clock = "Clock" in ident
    if test_id.startswith("SendTests/testSendEndToEnd"):
        if is_clock:
            return "C4.send.e2e_ms", "ms", [v * UNIT_TO_MS.get(unit, 1.0) for v in vals], "perIteration"
        if "CPU.time" in ident:
            return "C4.send.cpu_ms", "ms", [v * UNIT_TO_MS.get(unit, 1.0) for v in vals], "perIteration"
        if "physical_peak" in ident:
            factor = 1024.0 if unit.lower().startswith("kb") else 1.0
            return "C4.send.memory_peak_kb", "bytes", [v * factor for v in vals], "perIteration"
        return None
    if test_id.startswith("SendTests/testSendCallerThreadOnly") and is_clock:
        return "C4.send.caller_ms", "ms", [v * UNIT_TO_MS.get(unit, 1.0) for v in vals], "perIteration"
    m = re.match(r"BreadcrumbTests/testAddBreadcrumbRetained(\d+)", test_id)
    if m and is_clock:
        return "C5.breadcrumb.add_us.retained_%s" % m.group(1), "us", [v * UNIT_TO_MS.get(unit, 1.0) * 1000.0 for v in vals], "perIteration"
    if test_id.startswith("LaunchTests/"):
        if "ApplicationLaunch" in ident and unit in UNIT_TO_MS:
            return "C2.launch_ms", "ms", [v * UNIT_TO_MS[unit] for v in vals], "perLaunch"
        if "OSSignpost" in ident and unit in UNIT_TO_MS:
            return "C1.init.total", "ms", [v * UNIT_TO_MS[unit] for v in vals], "perLaunch"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle")
    ap.add_argument("--sdk-version", required=True)
    ap.add_argument("--variant", default="sdk", choices=["plain", "sdk", "sentinel"])
    ap.add_argument("--scenario", default="default")
    ap.add_argument("--source", default="xcframework", choices=["spm", "xcframework", "cocoapods", "local"])
    ap.add_argument("--platform", default="ios")
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--position", type=int, default=0)
    ap.add_argument("--env")
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--workflow", default="bench-apple")
    ap.add_argument("--sha", default="")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    import glob, os
    bundles = [a.bundle] if a.bundle.endswith(".xcresult") else sorted(glob.glob(os.path.join(a.bundle, "**", "*.xcresult"), recursive=True))
    if not bundles:
        print("xcresult_to_rows: no .xcresult under %s" % a.bundle, file=sys.stderr)
        return 0  # nothing to convert is not an error for a round
    data = []
    for b in bundles:
        raw = subprocess.run(["xcrun", "xcresulttool", "get", "test-results", "metrics", "--path", b, "--compact"],
                             capture_output=True, text=True, check=True).stdout
        data.extend(json.loads(raw))
    env = json.load(open(a.env)) if a.env else {"fingerprint": "unknown", "tier": "tier1"}
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows = []
    for test in data:
        test_id = test.get("testIdentifier", "")
        for run in test.get("testRuns", []):
            for metric in run.get("metrics", []):
                mapped = map_metric(test_id, metric)
                if not mapped:
                    continue
                metric_id, unit, samples, kind = mapped
                if metric_id.startswith("C1.") and (a.variant == "plain" or not any(samples)):
                    continue  # the plain app emits no init signpost; an all-zero interval is XCTest's placeholder, not a measurement
                st = summary(samples, kind)
                rows.append({"schemaVersion": 1, "sdk": "apple", "platform": a.platform, "sdkVersion": a.sdk_version, "source": a.source,
                             "variant": a.variant, "scenario": a.scenario, "metric": metric_id, "unit": unit, "value": st["median"],
                             "samples": samples, "round": a.round, "position": a.position, "stats": st, "env": env,
                             "run": {"id": a.run_id, "ts": ts, "workflow": a.workflow, "sha": a.sha}, "valid": True,
                             "notes": "xcresult " + test_id + " " + metric.get("displayName", "")})
    out = sys.stdout if a.out == "-" else open(a.out, "w")
    for r in rows:
        out.write(json.dumps(r) + "\n")
    if out is not sys.stdout:
        out.close()
    print("xcresult_to_rows: %d rows from %s" % (len(rows), a.bundle), file=sys.stderr)
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
