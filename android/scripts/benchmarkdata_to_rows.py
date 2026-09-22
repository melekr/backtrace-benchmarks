#!/usr/bin/env python3
"""Convert Jetpack Microbenchmark/Macrobenchmark *-benchmarkData.json files to result rows.

  benchmarkdata_to_rows.py FILE_OR_DIR [...] --sdk-version 3.14.0 --variant sdk [--scenario default] [--source maven]
                           [--round R --position P] --env env.json [--run-id ID] [--out rows.jsonl]

Metric mapping:
  macro  timeToInitialDisplayMs -> A2.ttid   timeToFullDisplayMs -> A2.ttfd   (perLaunch)
         bt.init.<stage>SumMs   -> A1.init.<stage>   bt.init.%SumMs -> A1.init.total
         scenario largeapk additionally emits A1b.init.native.largeapk from the native stage
  micro  sendE2E/timeNs -> A4.send.e2e_ms   sendE2E/allocationCount -> A4.send.alloc_count
         sendCallerThread/timeNs -> A4.send.caller_ms   addBreadcrumb/timeNs -> A5.breadcrumb.add_us
         addBreadcrumbNative/timeNs -> A5.breadcrumb.add_native_us          (measurementAverage)
context.cpuLocked is copied into env. Stdlib only.
"""
import argparse
import datetime
import glob
import json
import math
import os
import re
import statistics
import sys

MACRO = {"timeToInitialDisplayMs": ("A2.ttid", "ms", 1.0), "timeToFullDisplayMs": ("A2.ttfd", "ms", 1.0)}
STAGE_RE = re.compile(r"^bt\.init\.([a-z]+)SumMs$")
MICRO = {
    ("sendE2E", "timeNs"): ("A4.send.e2e_ms", "ms", 1e-6),
    ("sendE2E", "allocationCount"): ("A4.send.alloc_count", "count", 1.0),
    ("sendCallerThread", "timeNs"): ("A4.send.caller_ms", "ms", 1e-6),
    ("addBreadcrumb", "timeNs"): ("A5.breadcrumb.add_us", "us", 1e-3),
    ("addBreadcrumbNative", "timeNs"): ("A5.breadcrumb.add_native_us", "us", 1e-3),
}


def summary(samples, kind):
    xs = sorted(samples)
    n = len(xs)
    med = statistics.median(xs)
    mean = statistics.fmean(xs)
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    return {"n": n, "median": med, "mean": mean, "mad": statistics.median([abs(x - med) for x in xs]),
            "p95": xs[min(n - 1, int(math.ceil(0.95 * n)) - 1)], "min": xs[0], "max": xs[-1],
            "cov": (sd / mean) if mean else 0.0, "sampleKind": kind}


def files(paths):
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(glob.glob(os.path.join(p, "**", "*benchmarkData*.json"), recursive=True)):
                yield f
        elif os.path.exists(p):
            yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--sdk-version", required=True)
    ap.add_argument("--variant", default="sdk", choices=["plain", "sdk", "sentinel"])
    ap.add_argument("--scenario", default="default")
    ap.add_argument("--source", default="maven", choices=["maven", "local"])
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--position", type=int, default=0)
    ap.add_argument("--env", default=None)
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--workflow", default="bench-android")
    ap.add_argument("--sha", default="")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    env = json.load(open(a.env, encoding="utf-8")) if a.env and os.path.exists(a.env) else {"fingerprint": "unknown", "tier": "tier1"}
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows, seen = [], 0

    def emit(metric, unit, samples, kind, note):
        st = summary(samples, kind)
        rows.append({"schemaVersion": 1, "sdk": "android", "platform": "android", "sdkVersion": a.sdk_version, "source": a.source,
                     "variant": a.variant, "scenario": a.scenario, "metric": metric, "unit": unit, "value": st["median"],
                     "samples": samples, "round": a.round, "position": a.position, "stats": st, "env": env,
                     "run": {"id": a.run_id, "ts": ts, "workflow": a.workflow, "sha": a.sha}, "valid": True, "notes": note})

    for path in files(a.paths):
        seen += 1
        data = json.load(open(path, encoding="utf-8"))
        ctx = data.get("context", {})
        if "cpuLocked" in ctx and "cpuLocked" not in env:
            env["cpuLocked"] = bool(ctx.get("cpuLocked"))
        for bench in data.get("benchmarks", []):
            # Microbenchmark prefixes names with the suppressed error codes (EMULATOR_, DEBUGGABLE_, UNLOCKED_, ...).
            name = re.sub(r"^(?:[A-Z][A-Z-]*_)+", "", bench.get("name", ""))
            is_macro = "timeToInitialDisplayMs" in bench.get("metrics", {})
            for mname, m in bench.get("metrics", {}).items():
                runs = [float(x) for x in m.get("runs", [])]
                if not runs:
                    continue
                if is_macro:
                    if mname in MACRO:
                        metric, unit, f = MACRO[mname]
                        emit(metric, unit, [r * f for r in runs], "perLaunch", name)
                        continue
                    sm = STAGE_RE.match(mname)
                    if sm:
                        emit("A1.init." + sm.group(1), "ms", runs, "perLaunch", name)
                        if sm.group(1) == "native" and a.scenario == "largeapk":
                            emit("A1b.init.native.largeapk", "ms", runs, "perLaunch", name)
                    elif mname == "bt.init.%SumMs":
                        emit("A1.init.total", "ms", runs, "perLaunch", name)
                else:
                    key = (name, mname)
                    if key in MICRO:
                        metric, unit, f = MICRO[key]
                        emit(metric, unit, [r * f for r in runs], "measurementAverage", name)
    out = sys.stdout if a.out == "-" else open(a.out, "w", encoding="utf-8")
    for r in rows:
        out.write(json.dumps(r) + "\n")
    if out is not sys.stdout:
        out.close()
    print("benchmarkdata_to_rows: %d file(s), %d rows" % (seen, len(rows)), file=sys.stderr)
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
