#!/usr/bin/env python3
"""Convert result rows to the generic "smaller is better" JSON consumed by the benchmark
charting action: [{"name", "unit", "value", "range", "extra"}].

  to_gha_benchmark.py ROWS [ROWS ...] --series latest-release|nightly-HEAD [--sdk X] [--sdk-version V]
                      [--variant sdk] [--out FILE]

name  = <sdk>/<metric>/<scenario>; value = pooled median across rounds (all metrics are
lower-is-better); range = "± <MAD>"; extra = sdkVersion/source/variant/n/fingerprint.
latest-release keeps published-source rows of the highest sdkVersion present (or --sdk-version);
nightly-HEAD keeps source=local rows. Invalid rows are dropped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402
import stats as st  # noqa: E402


def select(rows: List[Dict[str, Any]], series: str, sdk: Optional[str], sdk_version: Optional[str], variant: str) -> List[Dict[str, Any]]:
    rows = [r for r in rows if hc.row_is_valid(r) and r.get("variant", "sdk") == variant]
    if sdk:
        rows = [r for r in rows if r.get("sdk") == sdk]
    if series == "nightly-HEAD":
        return [r for r in rows if r.get("source") == "local"]
    rows = [r for r in rows if r.get("source") != "local"]
    if not rows:
        return []
    out = []
    for s in sorted({r["sdk"] for r in rows}):
        rs = [r for r in rows if r["sdk"] == s]
        want = sdk_version or max({str(r["sdkVersion"]) for r in rs}, key=hc.version_key)
        out += [r for r in rs if str(r["sdkVersion"]) == want]
    return out


def convert(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pooled: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        name = f"{r['sdk']}/{r['metric']}/{r.get('scenario', 'default')}"
        slot = pooled.setdefault(name, {"unit": r["unit"], "samples": [], "rows": []})
        slot["samples"].extend(float(x) for x in (r.get("samples") or [r["value"]]))
        slot["rows"].append(r)
    out = []
    for name in sorted(pooled):
        slot = pooled[name]
        s = st.summarize(slot["samples"])
        first = slot["rows"][0]
        env = first.get("env") or {}
        extra = (f"sdkVersion={first.get('sdkVersion')} source={first.get('source')} variant={first.get('variant', 'sdk')} "
                 f"n={s['n']} rounds={len({r.get('round') for r in slot['rows'] if r.get('round') is not None})} "
                 f"fingerprint={str(env.get('fingerprint', ''))[:12]}")
        for k in ("runner", "device", "emulator", "simulator"):
            if env.get(k):
                extra += f" {k}={env[k]}"
        out.append({"name": name, "unit": slot["unit"], "value": s["median"], "range": f"± {hc.fmt_num(s['mad'], slot['unit'])}", "extra": extra})
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--series", required=True, choices=("latest-release", "nightly-HEAD"))
    ap.add_argument("--sdk", choices=hc.SDKS)
    ap.add_argument("--sdk-version")
    ap.add_argument("--variant", default="sdk", choices=hc.VARIANTS)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    rows = hc.read_rows(args.paths)
    picked = select(rows, args.series, args.sdk, args.sdk_version, args.variant)
    data = convert(picked)
    text = json.dumps(data, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"to_gha_benchmark: {len(data)} entries from {len(picked)} rows -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0 if data else 1


if __name__ == "__main__":
    sys.exit(main())
