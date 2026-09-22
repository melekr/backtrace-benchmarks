#!/usr/bin/env python3
"""Load and validate thresholds.yml against schema/metrics.yml; resolve gate rules.

CLI:
  thresholds.py validate [--thresholds F] [--metrics F]      exit 1 when invalid
  thresholds.py resolve METRIC [METRIC ...]                   print the rule per metric id
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402

CLASSES = ("det", "pair", "warn", "trend")
GATE_KEYS = {"name", "match", "class", "rel", "abs", "same_job_only"}
NOISE_KEYS = {"sentinel_max_rel", "cov_max", "rerun_failing_variant_once", "min_samples"}
COV_GROUPS = {"ttid": ("A2.*", "C2.*", "U7.player.ttid"), "trace": ("A1.*", "A1b.*", "C1.*", "U1.*")}


class ThresholdsError(ValueError):
    pass


def _is_pos_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def validate(th: Dict[str, Any], catalog: hc.MetricCatalog) -> List[str]:
    """Return a list of human-readable problems (empty when valid)."""
    errs: List[str] = []
    if not isinstance(th, dict):
        return ["thresholds: top level must be a mapping"]
    if th.get("version") != 1:
        errs.append(f"thresholds: version must be 1, got {th.get('version')!r}")

    noise = th.get("noise")
    if not isinstance(noise, dict):
        errs.append("thresholds: 'noise' mapping is required")
    else:
        for k in noise:
            if k not in NOISE_KEYS:
                errs.append(f"noise: unknown key {k!r}")
        smr = noise.get("sentinel_max_rel")
        if not (_is_pos_number(smr) and smr < 1):
            errs.append("noise.sentinel_max_rel must be a number in (0, 1)")
        cov = noise.get("cov_max")
        if not isinstance(cov, dict) or not cov:
            errs.append("noise.cov_max must be a non-empty mapping")
        else:
            for k, v in cov.items():
                if not _is_pos_number(v):
                    errs.append(f"noise.cov_max.{k} must be > 0")
            if "micro" not in cov:
                errs.append("noise.cov_max must define the 'micro' default")
        ms = noise.get("min_samples")
        if not isinstance(ms, dict):
            errs.append("noise.min_samples must be a mapping")
        else:
            for kind in hc.SAMPLE_KINDS:
                v = ms.get(kind)
                if not (isinstance(v, int) and not isinstance(v, bool) and v >= 1):
                    errs.append(f"noise.min_samples.{kind} must be an integer >= 1")

    comp = th.get("comparison")
    if not isinstance(comp, dict):
        errs.append("thresholds: 'comparison' mapping is required")
    else:
        br = comp.get("bootstrap_resamples")
        if not (isinstance(br, int) and br >= 100):
            errs.append("comparison.bootstrap_resamples must be an integer >= 100")
        ci = comp.get("ci")
        if not (_is_pos_number(ci) and ci < 1):
            errs.append("comparison.ci must be in (0, 1)")

    gates = th.get("gates")
    if not isinstance(gates, list) or not gates:
        errs.append("thresholds: 'gates' must be a non-empty list")
        gates = []
    names = set()
    for i, g in enumerate(gates):
        where = f"gates[{i}]"
        if not isinstance(g, dict):
            errs.append(f"{where}: must be a mapping")
            continue
        name = g.get("name")
        where = f"gates[{i}] ({name})" if name else where
        if not isinstance(name, str) or not name:
            errs.append(f"{where}: 'name' is required")
        elif name in names:
            errs.append(f"{where}: duplicate gate name")
        names.add(name)
        for k in g:
            if k not in GATE_KEYS:
                errs.append(f"{where}: unknown key {k!r} (rules are only class/rel/abs; no free-form assertions)")
        cls = g.get("class")
        if cls not in CLASSES:
            errs.append(f"{where}: class must be one of {CLASSES}, got {cls!r}")
        if cls in ("det", "pair"):
            if not _is_pos_number(g.get("rel")):
                errs.append(f"{where}: {cls} rule needs rel > 0 (got {g.get('rel')!r})")
            if not _is_pos_number(g.get("abs")):
                errs.append(f"{where}: {cls} rule needs abs > 0 (got {g.get('abs')!r})")
            if isinstance(g.get("rel"), (int, float)) and g.get("rel", 0) >= 1:
                errs.append(f"{where}: rel is a fraction and must be < 1")
        if "same_job_only" in g and not isinstance(g["same_job_only"], bool):
            errs.append(f"{where}: same_job_only must be a boolean")
        match = g.get("match")
        if not isinstance(match, list) or not match or not all(isinstance(m, str) and m for m in match):
            errs.append(f"{where}: match must be a non-empty list of metric globs")
            continue
        for glob in match:
            if not catalog.glob_matches(glob):
                errs.append(f"{where}: glob {glob!r} matches no metric id in metrics.yml")

    budgets = th.get("budgets", [])
    if budgets is None:
        budgets = []
    if not isinstance(budgets, list):
        errs.append("thresholds: 'budgets' must be a list")
        budgets = []
    for i, b in enumerate(budgets):
        where = f"budgets[{i}]"
        if not isinstance(b, dict) or not isinstance(b.get("metric"), str):
            errs.append(f"{where}: needs a 'metric'")
            continue
        if not catalog.resolve(b["metric"]):
            errs.append(f"{where}: unknown metric {b['metric']!r}")
        lo, hi = b.get("diff_min_ms"), b.get("diff_max_ms")
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)) or lo > hi:
            errs.append(f"{where}: diff_min_ms <= diff_max_ms required")
    return errs


def load_thresholds(path: str = hc.THRESHOLDS_PATH, metrics_path: str = hc.METRICS_PATH, strict: bool = True) -> Dict[str, Any]:
    th = hc.load_yaml(path)
    catalog = hc.load_metrics(metrics_path)
    errs = validate(th, catalog)
    if errs and strict:
        raise ThresholdsError("invalid thresholds:\n  " + "\n  ".join(errs))
    th["_catalog"] = catalog
    return th


def resolve_gate(metric_id: str, th: Dict[str, Any], catalog: Optional[hc.MetricCatalog] = None) -> Dict[str, Any]:
    """First gate whose glob matches; unmatched metrics are reported as ``warn``."""
    catalog = catalog or th.get("_catalog")
    for g in th.get("gates", []):
        for glob in g.get("match", []):
            if hc.glob_match_metric(glob, metric_id, catalog):
                return {
                    "name": g["name"], "class": g["class"],
                    "rel": g.get("rel"), "abs": g.get("abs"),
                    "same_job_only": bool(g.get("same_job_only", False)),
                }
    return {"name": None, "class": "warn", "rel": None, "abs": None, "same_job_only": False}


def cov_limit(metric_id: str, th: Dict[str, Any]) -> float:
    cov = th["noise"]["cov_max"]
    for group, globs in COV_GROUPS.items():
        if group in cov and any(hc.glob_match_metric(g, metric_id) for g in globs):
            return float(cov[group])
    return float(cov["micro"])


def min_samples(sample_kind: Optional[str], th: Dict[str, Any]) -> int:
    ms = th["noise"]["min_samples"]
    return int(ms.get(sample_kind or "exact", 1))


def budget_for(metric_id: str, th: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for b in th.get("budgets") or []:
        if b.get("metric") == metric_id:
            return b
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thresholds", default=hc.THRESHOLDS_PATH)
    ap.add_argument("--metrics", default=hc.METRICS_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    rp = sub.add_parser("resolve")
    rp.add_argument("metric", nargs="+")
    rp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    th = hc.load_yaml(args.thresholds)
    catalog = hc.load_metrics(args.metrics)
    errs = validate(th, catalog)
    if args.cmd == "validate":
        if errs:
            print("thresholds.yml: INVALID")
            for e in errs:
                print(f"  - {e}")
            return 1
        print(f"thresholds.yml: OK ({len(th['gates'])} gates, {len(catalog.ids())} catalogue metrics)")
        return 0
    if errs:
        print("thresholds.yml is invalid; fix it before resolving rules:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    for m in args.metric:
        rule = resolve_gate(m, th, catalog)
        rule["cov_max"] = cov_limit(m, th)
        rule["known"] = catalog.resolve(m) is not None
        if args.json:
            print(json.dumps({"metric": m, **rule}, sort_keys=True))
        else:
            print(f"{m}: class={rule['class']} rule={rule['name']} rel={rule['rel']} abs={rule['abs']} cov_max={rule['cov_max']} known={rule['known']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
