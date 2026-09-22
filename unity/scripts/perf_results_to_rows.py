#!/usr/bin/env python3
"""Convert a Unity Performance Testing results file (PerformanceTestResults.json) to result rows.

  perf_results_to_rows.py RESULTS.json --sdk-version 3.17.0 --variant sdk [--scenario default] [--source openupm]
                          [--round R --position P] --env env.json [--run-id ID] [--out rows.jsonl] [--keep-unknown]

Sample-group names are metric ids (schema/metrics.yml). Units are converted from the package's SampleUnit to the
metric's unit (Millisecond->ms, Microsecond->us, Byte->bytes). sampleKind perIteration. Stdlib only.
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
UNIT_NAMES = {0: "Nanosecond", 1: "Microsecond", 2: "Millisecond", 3: "Second", 4: "Byte", 5: "Kilobyte", 6: "Megabyte", 7: "Gigabyte", 8: "Undefined"}
TO_BASE = {"Nanosecond": ("ms", 1e-6), "Microsecond": ("us", 1.0), "Millisecond": ("ms", 1.0), "Second": ("ms", 1000.0),
           "Byte": ("bytes", 1.0), "Kilobyte": ("bytes", 1024.0), "Megabyte": ("bytes", 1024.0 ** 2), "Gigabyte": ("bytes", 1024.0 ** 3), "Undefined": ("count", 1.0)}


def load_metric_units():
    """metric id -> unit from schema/metrics.yml (tiny line parser; the file is flat)."""
    units = {}
    path = os.path.join(REPO, "schema", "metrics.yml")
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^\s{4}([A-Za-z0-9_.<>-]+):\s*\{\s*unit:\s*([a-z_]+)", line)
            if m:
                units[m.group(1)] = m.group(2)
    except OSError:
        pass
    return units


def metric_known(metric, units):
    if metric in units:
        return units[metric]
    for pattern, unit in units.items():
        if "<" not in pattern:
            continue
        rx = "^" + "".join(
            {"<abi>": r"[^.]+", "<slice>": r"[^.]+", "<stage>": r"[^.]+", "<N>": r"\d+", "<platform>": r"[^.]+", "<variant>": r"[^.]+"}.get(tok, re.escape(tok))
            for tok in re.split(r"(<[a-zA-Z]+>)", pattern) if tok) + "$"
        if re.match(rx, metric):
            return unit
    return None


def convert(value, from_unit, to_unit):
    base_unit, factor = TO_BASE.get(from_unit, ("count", 1.0))
    v = value * factor
    if base_unit == to_unit:
        return v
    if base_unit == "ms" and to_unit == "us":
        return v * 1000.0
    if base_unit == "us" and to_unit == "ms":
        return v / 1000.0
    return v


def summary(samples):
    xs = sorted(samples)
    n = len(xs)
    med = statistics.median(xs)
    mad = statistics.median([abs(x - med) for x in xs]) if n else 0.0
    mean = statistics.fmean(xs) if n else 0.0
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    p95 = xs[min(n - 1, int(math.ceil(0.95 * n)) - 1)] if n else 0.0
    return {"n": n, "median": med, "mean": mean, "mad": mad, "p95": p95, "min": xs[0], "max": xs[-1],
            "cov": (sd / mean) if mean else 0.0, "sampleKind": "perIteration"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("--sdk-version", required=True)
    ap.add_argument("--variant", default="sdk", choices=["plain", "sdk", "sentinel"])
    ap.add_argument("--scenario", default="default")
    ap.add_argument("--source", default="openupm", choices=["openupm", "local"])
    ap.add_argument("--platform", default="unity-editor")
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--position", type=int, default=0)
    ap.add_argument("--env", default=None)
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--workflow", default="bench-unity")
    ap.add_argument("--sha", default="")
    ap.add_argument("--out", default="-")
    ap.add_argument("--keep-unknown", action="store_true")
    a = ap.parse_args()

    data = json.load(open(a.results, encoding="utf-8"))
    env = json.load(open(a.env, encoding="utf-8")) if a.env and os.path.exists(a.env) else {"fingerprint": "unknown", "tier": "tier1"}
    units = load_metric_units()
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows, skipped = [], []
    for result in data.get("Results", []):
        for group in result.get("SampleGroups", []):
            name = group.get("Name", "")
            unit_raw = group.get("Unit", 8)
            from_unit = UNIT_NAMES.get(unit_raw, unit_raw) if isinstance(unit_raw, int) else str(unit_raw)
            to_unit = metric_known(name, units)
            if to_unit is None:
                if not a.keep_unknown:
                    skipped.append(name)
                    continue
                to_unit = TO_BASE.get(from_unit, ("count", 1.0))[0]
            samples = [convert(float(s), from_unit, to_unit) for s in group.get("Samples", [])]
            if not samples:
                skipped.append(name + " (no samples)")
                continue
            st = summary(samples)
            rows.append({
                "schemaVersion": 1, "sdk": "unity", "platform": a.platform, "sdkVersion": a.sdk_version, "source": a.source,
                "variant": a.variant, "scenario": a.scenario, "metric": name, "unit": to_unit, "value": st["median"],
                "samples": samples, "round": a.round, "position": a.position, "stats": st, "env": env,
                "run": {"id": a.run_id, "ts": ts, "workflow": a.workflow, "sha": a.sha}, "valid": True,
                "notes": "unity test " + result.get("Name", ""),
            })
    out = sys.stdout if a.out == "-" else open(a.out, "w", encoding="utf-8")
    for r in rows:
        out.write(json.dumps(r) + "\n")
    if out is not sys.stdout:
        out.close()
    print("perf_results_to_rows: %d rows%s" % (len(rows), (", skipped unknown groups: " + ", ".join(sorted(set(skipped)))) if skipped else ""), file=sys.stderr)
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
