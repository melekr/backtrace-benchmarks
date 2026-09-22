#!/usr/bin/env python3
"""Statistics for the harness: robust summaries, paired ratios, bootstrap CIs, verdicts.

All functions are pure Python (stdlib) and deterministic given a seed.

CLI:
  stats.py summarize rows.jsonl [more.jsonl|DIR ...]      per-row summary table
  stats.py summarize --samples 1,2,3,...                   summary of a literal list
  stats.py ci --values r1,r2,...  [--seed 0] [--resamples 10000]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402

DEFAULT_RESAMPLES = 10000
DEFAULT_CI = 0.95


# ------------------------------------------------------------------- descriptive

def median(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("median of empty sequence")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def mean(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("mean of empty sequence")
    return float(sum(xs)) / len(xs)


def mad(xs: Sequence[float]) -> float:
    """Median absolute deviation (raw, unscaled)."""
    m = median(xs)
    return median([abs(x - m) for x in xs])


def percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not xs:
        raise ValueError("percentile of empty sequence")
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(s[lo])
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def p95(xs: Sequence[float]) -> float:
    return percentile(xs, 95)


def stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def cov(xs: Sequence[float]) -> float:
    """Coefficient of variation (sample stdev / mean); 0 when mean is 0."""
    m = mean(xs)
    return 0.0 if m == 0 else stdev(xs) / abs(m)


def summarize(xs: Sequence[float], sample_kind: Optional[str] = None) -> Dict[str, float]:
    xs = [float(x) for x in xs]
    out: Dict[str, float] = {
        "n": len(xs), "median": median(xs), "mean": mean(xs), "mad": mad(xs),
        "p95": p95(xs), "min": float(min(xs)), "max": float(max(xs)), "cov": cov(xs),
    }
    if sample_kind:
        out["sampleKind"] = sample_kind  # type: ignore[assignment]
    return out


# -------------------------------------------------------------------- pairing

def paired_ratios(variant_rounds: Dict[int, Sequence[float]], anchor_rounds: Dict[int, Sequence[float]]) -> List[float]:
    """Per-round ``median(variant)/median(anchor)`` for rounds present in both."""
    out: List[float] = []
    for r in sorted(set(variant_rounds) & set(anchor_rounds)):
        a = median(anchor_rounds[r])
        v = median(variant_rounds[r])
        if a == 0:
            continue
        out.append(v / a)
    return out


# ------------------------------------------------------------------- bootstrap

def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = median,
                 resamples: int = DEFAULT_RESAMPLES, ci: float = DEFAULT_CI, seed: int = 0) -> Tuple[float, float]:
    """Percentile bootstrap CI of ``stat`` over ``values`` with a seeded RNG."""
    vals = [float(v) for v in values]
    if not vals:
        raise ValueError("bootstrap of empty sequence")
    if len(vals) == 1:
        return vals[0], vals[0]
    rng = random.Random(seed)
    n = len(vals)
    stats = []
    for _ in range(resamples):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        stats.append(stat(sample))
    alpha = (1.0 - ci) / 2.0
    return percentile(stats, alpha * 100.0), percentile(stats, (1.0 - alpha) * 100.0)


def ratio_ci_from_samples(base: Sequence[float], head: Sequence[float], resamples: int = DEFAULT_RESAMPLES,
                          ci: float = DEFAULT_CI, seed: int = 0) -> Optional[Tuple[float, float]]:
    """Unpaired fallback: bootstrap of median(head*)/median(base*) resampling each side."""
    b = [float(x) for x in base]
    h = [float(x) for x in head]
    if not b or not h or median(b) == 0:
        return None
    if len(b) == 1 and len(h) == 1:
        r = h[0] / b[0]
        return r, r
    rng = random.Random(seed)
    ratios = []
    for _ in range(resamples):
        mb = median([b[rng.randrange(len(b))] for _ in range(len(b))])
        mh = median([h[rng.randrange(len(h))] for _ in range(len(h))])
        if mb == 0:
            continue
        ratios.append(mh / mb)
    if not ratios:
        return None
    alpha = (1.0 - ci) / 2.0
    return percentile(ratios, alpha * 100.0), percentile(ratios, (1.0 - alpha) * 100.0)


# ---------------------------------------------------------------- noise floor

def sentinel_delta(sentinel_value: float, reference_value: float) -> Optional[float]:
    """|ratio - 1| of sentinel vs the reference (same version installed twice)."""
    if reference_value == 0:
        return None
    return abs(sentinel_value / reference_value - 1.0)


def noise_floor(deltas: Iterable[Optional[float]], sentinel_max_rel: float) -> Dict[str, object]:
    ds = [d for d in deltas if d is not None]
    worst = max(ds) if ds else None
    return {"max_rel": worst, "noisy": bool(worst is not None and worst > sentinel_max_rel), "n": len(ds), "limit": sentinel_max_rel}


# --------------------------------------------------------------------- verdict

VERDICTS = ("no change", "improved", "regressed", "regressed (within threshold)", "inconclusive", "n/a")


def ci_contains_one(ci: Optional[Tuple[float, float]]) -> bool:
    return ci is not None and ci[0] <= 1.0 <= ci[1]


def verdict(base: Optional[float], head: Optional[float], gate: Dict[str, object],
            ci: Optional[Tuple[float, float]] = None, inconclusive: bool = False) -> Dict[str, object]:
    """Apply the gate class rules from docs/CONVENTIONS.md section 10.

    det:  fail iff delta >= max(rel*base, abs)
    pair: fail iff delta_median >= max(rel*base, abs) and the CI excludes 1
    warn/trend never fail. Returns {verdict, fails_gate, delta, delta_rel, ratio}.
    """
    out: Dict[str, object] = {"verdict": "n/a", "fails_gate": False, "delta": None, "delta_rel": None, "ratio": None}
    if base is None or head is None:
        return out
    delta = head - base
    ratio = (head / base) if base else None
    delta_rel = (ratio - 1.0) if ratio is not None else None
    out.update({"delta": delta, "delta_rel": delta_rel, "ratio": ratio})
    cls = str(gate.get("class", "warn"))
    if inconclusive:
        out["verdict"] = "inconclusive"
        return out
    rel = gate.get("rel")
    absv = gate.get("abs")
    if cls in ("det", "pair") and rel is not None and absv is not None:
        limit = max(float(rel) * abs(base), float(absv))
    else:
        limit = None

    if cls == "pair":
        if ci is not None and ci_contains_one(ci):
            out["verdict"] = "no change"
            return out
        if ci is None:
            # No CI available (no paired rounds and no samples): report direction, never fail.
            if limit is not None and abs(delta) < limit:
                out["verdict"] = "no change"
            else:
                out["verdict"] = "regressed (within threshold)" if delta > 0 else "improved"
            out["verdict"] = out["verdict"] if delta != 0 else "no change"
            return out
        if limit is not None and delta >= limit:
            out["verdict"] = "regressed"
            out["fails_gate"] = True
        elif delta > 0:
            out["verdict"] = "regressed (within threshold)"
        elif delta < 0:
            out["verdict"] = "improved"
        else:
            out["verdict"] = "no change"
        return out

    if cls == "det":
        if limit is not None and delta >= limit:
            out["verdict"] = "regressed"
            out["fails_gate"] = True
        elif limit is not None and delta <= -limit:
            out["verdict"] = "improved"
        elif delta == 0:
            out["verdict"] = "no change"
        else:
            out["verdict"] = "regressed (within threshold)" if delta > 0 else "improved"
        return out

    # warn / trend: informational only
    if ci is not None and ci_contains_one(ci):
        out["verdict"] = "no change"
    elif delta > 0:
        out["verdict"] = "regressed (within threshold)"
    elif delta < 0:
        out["verdict"] = "improved"
    else:
        out["verdict"] = "no change"
    return out


# ------------------------------------------------------------------------- CLI

def _summarize_rows(paths: List[str]) -> str:
    rows = hc.read_rows(paths)
    table = []
    for r in rows:
        samples = r.get("samples") or [r.get("value")]
        s = summarize(samples)
        table.append([
            r.get("sdk"), r.get("sdkVersion"), r.get("variant"), r.get("scenario"), r.get("metric"), r.get("unit"),
            s["n"], hc.fmt_num(s["median"], r.get("unit", "")), hc.fmt_num(s["mad"], r.get("unit", "")),
            hc.fmt_num(s["p95"], r.get("unit", "")), f"{s['cov']:.3f}", "yes" if hc.row_is_valid(r) else "NO",
        ])
    return hc.md_table(["sdk", "version", "variant", "scenario", "metric", "unit", "n", "median", "MAD", "p95", "CoV", "valid"], table)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("summarize")
    sp.add_argument("paths", nargs="*")
    sp.add_argument("--samples", help="comma-separated literal samples instead of rows")
    sp.add_argument("--json", action="store_true")
    cp = sub.add_parser("ci")
    cp.add_argument("--values", required=True, help="comma-separated ratios")
    cp.add_argument("--seed", type=int, default=0)
    cp.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    cp.add_argument("--ci", type=float, default=DEFAULT_CI)
    args = ap.parse_args(argv)

    if args.cmd == "summarize":
        if args.samples:
            xs = [float(x) for x in args.samples.split(",") if x.strip()]
            s = summarize(xs)
            print(json.dumps(s, sort_keys=True) if args.json else "\n".join(f"{k}: {v}" for k, v in s.items()))
            return 0
        if not args.paths:
            ap.error("summarize needs rows.jsonl paths or --samples")
        print(_summarize_rows(args.paths))
        return 0
    if args.cmd == "ci":
        vals = [float(x) for x in args.values.split(",") if x.strip()]
        lo, hi = bootstrap_ci(vals, resamples=args.resamples, ci=args.ci, seed=args.seed)
        print(json.dumps({"n": len(vals), "median": median(vals), "ci_low": lo, "ci_high": hi, "contains_one": lo <= 1 <= hi}))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
