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


def robust_cov(xs: Sequence[float]) -> float:
    """Outlier-resistant dispersion: 1.4826 * MAD / |median| (equals the CoV for normal data); 0 when the median is 0."""
    m = median(xs)
    return 0.0 if m == 0 else 1.4826 * mad(xs) / abs(m)


def geomean(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("geomean of empty sequence")
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def summarize(xs: Sequence[float], sample_kind: Optional[str] = None) -> Dict[str, float]:
    xs = [float(x) for x in xs]
    out: Dict[str, float] = {
        "n": len(xs), "median": median(xs), "mean": mean(xs), "mad": mad(xs),
        "p95": p95(xs), "min": float(min(xs)), "max": float(max(xs)), "cov": cov(xs), "rcov": robust_cov(xs),
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


def common_rounds(base_rounds: Dict[int, Sequence[float]], head_rounds: Dict[int, Sequence[float]]) -> List[int]:
    return [r for r in sorted(set(base_rounds) & set(head_rounds)) if base_rounds[r] and head_rounds[r]]


def point_ratio(base_rounds: Dict[int, Sequence[float]], head_rounds: Dict[int, Sequence[float]]) -> Optional[float]:
    """Geometric mean over common rounds of ``median(head_r)/median(base_r)``; None without a usable round."""
    ratios = []
    for r in common_rounds(base_rounds, head_rounds):
        b, h = median(base_rounds[r]), median(head_rounds[r])
        if b > 0 and h > 0:
            ratios.append(h / b)
    return geomean(ratios) if ratios else None


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


def stratified_ratio_ci(base_rounds: Dict[int, Sequence[float]], head_rounds: Dict[int, Sequence[float]],
                        resamples: int = DEFAULT_RESAMPLES, ci: float = DEFAULT_CI, seed: int = 0) -> Optional[Tuple[float, float]]:
    """Percentile bootstrap CI of the geometric mean of per-round median ratios.

    Rounds are fixed strata: both variants ran inside every round, so round-level drift cancels in the ratio and
    is not resampled. Samples are resampled with replacement within each round on both sides. One round is a
    plain two-sample bootstrap of the median ratio. The interval only collapses to a point when every sample is
    identical; it never degenerates the way a bootstrap over three per-round ratios does."""
    rounds = common_rounds(base_rounds, head_rounds)
    if not rounds:
        return None
    b = {r: [float(x) for x in base_rounds[r]] for r in rounds}
    h = {r: [float(x) for x in head_rounds[r]] for r in rounds}
    if any(len(b[r]) < 2 or len(h[r]) < 2 for r in rounds):
        # A stratum with a single value cannot be resampled: fall back to one unpaired stratum.
        b = {0: [x for r in rounds for x in b[r]]}
        h = {0: [x for r in rounds for x in h[r]]}
        rounds = [0]
    if sum(len(v) for v in b.values()) < 2 or sum(len(v) for v in h.values()) < 2:
        return None
    rng = random.Random(seed)
    stats: List[float] = []
    dropped = 0
    for _ in range(resamples):
        logs = []
        for r in rounds:
            mb = median(rng.choices(b[r], k=len(b[r])))
            mh = median(rng.choices(h[r], k=len(h[r])))
            if mb > 0 and mh > 0:
                logs.append(math.log(mh / mb))
        if len(logs) == len(rounds):
            stats.append(math.exp(sum(logs) / len(logs)))
        else:
            dropped += 1
    if not stats or dropped > 0.05 * resamples:
        return None   # zero medians (counts, byte deltas) make the ratio undefined too often for a usable interval
    alpha = (1.0 - ci) / 2.0
    return percentile(stats, alpha * 100.0), percentile(stats, (1.0 - alpha) * 100.0)


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

TIERS = ("improved", "improved (small)", "no change", "within threshold", "no significant change", "inconclusive",
         "regressed (small)", "regressed", "n/a")
VERDICTS = TIERS
DEFAULT_REPORT_REL = 0.10


def ci_contains_one(ci: Optional[Tuple[float, float]]) -> bool:
    return ci is not None and ci[0] <= 1.0 <= ci[1]


def verdict(base: Optional[float], head: Optional[float], gate: Dict[str, object],
            ci: Optional[Tuple[float, float]] = None, inconclusive: bool = False, point: Optional[float] = None,
            report_rel: float = DEFAULT_REPORT_REL) -> Dict[str, object]:
    """Tiered verdict per docs/CONVENTIONS.md section 10.

    All metrics are lower-is-better. ``limit = max(rel*|base|, abs)`` is the gate threshold (``rel`` falls back to
    ``report_rel`` and ``abs`` to 0 for warn/trend rules), ``t = limit/|base|`` the same threshold as a ratio.
      det   : delta == 0 -> no change; |delta| < limit -> within threshold; else improved / regressed (gate fails).
      timing: the CI decides. CI entirely below 1 -> improved (large: ratio <= 1-t) or improved (small);
              CI entirely above 1 -> regressed / regressed (small), the pair gate fails only for the large one;
              CI containing 1 inside [1-t, 1+t] -> no change; a wider CI with the point estimate inside the band ->
              no significant change; a wider CI with the point estimate beyond the band -> inconclusive (leaning ...).
              A missing or zero-width CI (identical samples, single values) -> inconclusive (no CI), never a
              "(small)" tier.
    ``inconclusive=True`` (too few samples) forces that tier for every class. ``point`` is the paired ratio estimate
    (defaults to head/base); for timing classes ``delta`` is derived from it (``base * (point - 1)``) so the delta and
    delta_rel columns agree, while det rows report the exact ``head - base``.
    Returns {verdict, tier, fails_gate, delta, delta_rel, ratio, limit, significant, lean, no_ci}.
    """
    out: Dict[str, object] = {"verdict": "n/a", "tier": "n/a", "fails_gate": False, "delta": None, "delta_rel": None,
                              "ratio": None, "limit": None, "significant": False, "lean": None, "no_ci": False}
    if base is None or head is None:
        return out
    delta = head - base
    ratio = point if point is not None else ((head / base) if base else None)
    delta_rel = (ratio - 1.0) if ratio is not None else None
    cls = str(gate.get("class", "warn"))
    rel = float(gate["rel"]) if gate.get("rel") is not None else float(report_rel)
    absv = float(gate["abs"]) if gate.get("abs") is not None else 0.0
    limit = max(rel * abs(base), absv)
    t = (limit / abs(base)) if base else rel
    out.update({"delta": delta, "delta_rel": delta_rel, "ratio": ratio, "limit": limit})

    def finish(tier: str, suffix: str = "", fails: bool = False, significant: bool = False, lean: Optional[str] = None) -> Dict[str, object]:
        out.update({"tier": tier, "verdict": tier + suffix, "fails_gate": fails, "significant": significant, "lean": lean})
        return out

    if cls == "det":
        # Deterministic metrics are compared on their exact values, not on the per-round ratio estimate.
        out.update({"ratio": (head / base) if base else None, "delta_rel": ((head / base) - 1.0) if base else None})
        if inconclusive:
            return finish("inconclusive")
        if delta == 0:
            return finish("no change")
        if abs(delta) < limit:
            return finish("within threshold", significant=True)
        return finish("regressed", fails=True, significant=True) if delta > 0 else finish("improved", significant=True)

    if point is not None and base:
        # Timing classes: the displayed delta follows the paired ratio estimate so delta and delta_rel never disagree in sign.
        delta = base * (point - 1.0)
        out["delta"] = delta
    large_improve = ratio is not None and ratio <= 1.0 - t
    large_regress = ratio is not None and ratio >= 1.0 + t
    lean = "improved" if large_improve else ("regressed" if large_regress else None)
    if inconclusive:
        return finish("inconclusive", f" (leaning {lean})" if lean else "", lean=lean)
    if ci is None or ci[0] == ci[1]:
        out["no_ci"] = True
        return finish("inconclusive", " (no CI" + (f", leaning {lean})" if lean else ")"), lean=lean)
    lo, hi = ci
    if hi < 1.0:
        return finish("improved" if large_improve else "improved (small)", significant=True)
    if lo > 1.0:
        if large_regress:
            return finish("regressed", fails=(cls == "pair"), significant=True)
        return finish("regressed (small)", significant=True)
    if 1.0 - t <= lo and hi <= 1.0 + t:
        return finish("no change")
    if lean:
        return finish("inconclusive", f" (leaning {lean})", lean=lean)
    return finish("no significant change", f" (CI wider than ±{t * 100:.0f}%)")


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
            hc.fmt_num(s["p95"], r.get("unit", "")), f"{s['cov']:.3f}", f"{s['rcov']:.3f}", "yes" if hc.row_is_valid(r) else "NO",
        ])
    return hc.md_table(["sdk", "version", "variant", "scenario", "metric", "unit", "n", "median", "MAD", "p95", "CoV", "rCoV", "valid"], table)


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
