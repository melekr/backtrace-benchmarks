#!/usr/bin/env python3
"""Compare result rows: version ladders, PR base-vs-head with gates, plain-vs-SDK overhead.

  compare.py ladder   --results DIR --sdk android --ladder 3.8.4,3.9.0,... [--scenario default]
  compare.py pr       --base ROWS --head ROWS [--plain ROWS] [--sentinel ROWS] [--gate] [--strict]
  compare.py overhead --plain ROWS (--sdk-rows ROWS | --head ROWS)
Common: --format md|json --out FILE --summary-file FILE (append) --allow-mixed-env --seed N
        --thresholds F --metrics F --scenario S

ROWS is a rows.jsonl file or a directory searched recursively. Rows with valid:false are
excluded from every statistic and listed under "Excluded rows". Rows whose env.fingerprint
differ are refused unless --allow-mixed-env is given, in which case nothing is gated.

Exit codes with --gate: 0 pass, 2 det/pair gate failed, 3 noisy or inconclusive (only with
--strict; otherwise 0). Without --gate the exit code is 0 unless the input is unusable (1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402
import stats as st  # noqa: E402
import thresholds as thr  # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_GATE_FAILED, EXIT_NOISY = 0, 1, 2, 3
TIMING_UNITS = ("ms", "us")

KPI = {
    "android": {"size": ("A3.apk_universal_bytes", "A0.aar_bytes"), "init": "A1.init.total", "send": "A4.send.e2e_ms", "cold": "A2.ttid"},
    "apple": {"size": ("C3.app_binary_bytes", "C0.xcframework_slice_bytes.ios-arm64"), "init": "C1.init.total", "send": "C4.send.e2e_ms", "cold": "C2.launch_ms"},
    "unity": {"size": ("U4.player_bytes.*", "U0.tgz_bytes"), "init": "U1.init.total", "send": "U2.send.e2e_ms", "cold": "U7.player.ttid"},
}


class CompareError(Exception):
    pass


# ------------------------------------------------------------------- grouping

class Group:
    """All valid rows for one (metric, scenario, variant, sdkVersion)."""

    def __init__(self, metric: str, scenario: str, variant: str, version: str):
        self.metric, self.scenario, self.variant, self.version = metric, scenario, variant, version
        self.rows: List[Dict[str, Any]] = []

    def add(self, row: Dict[str, Any]) -> None:
        self.rows.append(row)

    @property
    def unit(self) -> str:
        return str(self.rows[0].get("unit", "")) if self.rows else ""

    @property
    def sample_kind(self) -> Optional[str]:
        kinds = {(r.get("stats") or {}).get("sampleKind") for r in self.rows}
        kinds.discard(None)
        return sorted(kinds)[0] if kinds else None

    @property
    def samples(self) -> List[float]:
        out: List[float] = []
        for r in self.rows:
            s = r.get("samples")
            out.extend(float(x) for x in s) if s else out.append(float(r["value"]))
        return out

    @property
    def rounds(self) -> Dict[int, List[float]]:
        out: Dict[int, List[float]] = {}
        for r in self.rows:
            if r.get("round") is None:
                continue
            s = r.get("samples") or [r["value"]]
            out.setdefault(int(r["round"]), []).extend(float(x) for x in s)
        return out

    @property
    def value(self) -> float:
        return st.median(self.samples)

    @property
    def run_ids(self) -> set:
        return {(r.get("run") or {}).get("id") for r in self.rows}

    def summary(self) -> Dict[str, Any]:
        return st.summarize(self.samples)


def group_rows(rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str, str, str], Group]:
    out: Dict[Tuple[str, str, str, str], Group] = {}
    for r in rows:
        key = (r["metric"], r.get("scenario", "default"), r.get("variant", "sdk"), str(r.get("sdkVersion")))
        out.setdefault(key, Group(*key)).add(r)
    return out


def split_valid(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    good = [r for r in rows if hc.row_is_valid(r)]
    bad = [r for r in rows if not hc.row_is_valid(r)]
    return good, bad


def fingerprints(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return sorted({str((r.get("env") or {}).get("fingerprint", "")) for r in rows})


def check_env(rows: Sequence[Dict[str, Any]], allow_mixed: bool) -> Tuple[List[str], bool]:
    fps = fingerprints(rows)
    if len(fps) > 1 and not allow_mixed:
        raise CompareError(
            "rows come from different environments (env.fingerprint differs): "
            + ", ".join(f[:12] + "..." for f in fps)
            + ". Re-run inside one job, or pass --allow-mixed-env for a report-only comparison."
        )
    return fps, len(fps) > 1


# ------------------------------------------------------------------ analysis

def ratio_ci(base: Optional[Group], head: Optional[Group], th: Dict[str, Any], seed: int) -> Tuple[Optional[Tuple[float, float]], str]:
    """(ci, kind): paired per-round ratios when both sides have rounds, else unpaired bootstrap."""
    if base is None or head is None:
        return None, "n/a"
    resamples = int(th["comparison"]["bootstrap_resamples"])
    ci_level = float(th["comparison"]["ci"])
    br, hr = base.rounds, head.rounds
    common = sorted(set(br) & set(hr))
    if common:
        ratios = st.paired_ratios(hr, br)
        if ratios:
            lo, hi = st.bootstrap_ci(ratios, st.median, resamples=resamples, ci=ci_level, seed=seed)
            return (lo, hi), f"paired, {len(ratios)} round(s)"
    bs, hs = base.samples, head.samples
    if len(bs) > 1 or len(hs) > 1:
        ci = st.ratio_ci_from_samples(bs, hs, resamples=resamples, ci=ci_level, seed=seed)
        if ci:
            return ci, f"unpaired, n={len(bs)}/{len(hs)}"
    return None, "n/a"


def inconclusive_reason(g: Group, th: Dict[str, Any]) -> Optional[str]:
    n = len(g.samples)
    need = thr.min_samples(g.sample_kind, th)
    if n < need:
        return f"n={n} < min_samples[{g.sample_kind or 'exact'}]={need}"
    if g.unit in TIMING_UNITS and n >= 2:
        c = st.cov(g.samples)
        limit = thr.cov_limit(g.metric, th)
        if c > limit:
            return f"CoV {c:.3f} > {limit:.2f}"
    return None


def compare_groups(base: Optional[Group], head: Optional[Group], th: Dict[str, Any], catalog: hc.MetricCatalog,
                   seed: int, gating: bool) -> Dict[str, Any]:
    metric = (head or base).metric
    gate = thr.resolve_gate(metric, th, catalog)
    ci, ci_kind = ratio_ci(base, head, th, seed)
    reasons = [r for r in (inconclusive_reason(g, th) for g in (base, head) if g is not None) if r]
    bval = base.value if base else None
    hval = head.value if head else None
    v = st.verdict(bval, hval, gate, ci, inconclusive=bool(reasons))
    same_job_ok = True
    if gate.get("same_job_only") and base is not None and head is not None and not (base.run_ids & head.run_ids):
        same_job_ok = False
    fails = bool(v["fails_gate"]) and gating and same_job_ok
    return {
        "metric": metric, "unit": (head or base).unit, "class": gate["class"], "rule": gate["name"],
        "base": bval, "head": hval, "delta": v["delta"], "delta_rel": v["delta_rel"], "ratio": v["ratio"],
        "ci": list(ci) if ci else None, "ci_kind": ci_kind,
        "verdict": v["verdict"] if same_job_ok else f"{v['verdict']} (not same job; not gated)",
        "fails_gate": fails, "inconclusive": bool(reasons), "reasons": reasons,
        "n_base": len(base.samples) if base else 0, "n_head": len(head.samples) if head else 0,
    }


def noise_from_sentinel(sentinel_groups: Dict[Tuple[str, str, str, str], Group], head_groups: Dict[Tuple[str, str, str, str], Group],
                        th: Dict[str, Any], catalog: hc.MetricCatalog) -> Dict[str, Any]:
    deltas: List[Optional[float]] = []
    per_metric: Dict[str, float] = {}
    for key, sg in sentinel_groups.items():
        metric, scenario, _variant, _version = key
        gate = thr.resolve_gate(metric, th, catalog)
        if gate["class"] != "pair":
            continue
        ref = None
        for hk, hg in head_groups.items():
            if hk[0] == metric and hk[1] == scenario and hk[2] == "sdk":
                ref = hg
                break
        if ref is None:
            continue
        rounds_s, rounds_r = sg.rounds, ref.rounds
        ratios = st.paired_ratios(rounds_s, rounds_r) if (rounds_s and rounds_r) else []
        ratio = st.median(ratios) if ratios else (sg.value / ref.value if ref.value else None)
        d = None if ratio is None else abs(ratio - 1.0)
        deltas.append(d)
        if d is not None:
            per_metric[metric] = d
    nf = st.noise_floor(deltas, float(th["noise"]["sentinel_max_rel"]))
    nf["per_metric"] = per_metric
    nf["measured"] = bool(sentinel_groups)
    return nf


# ------------------------------------------------------------------- rendering

def fmt_ci(ci: Optional[Sequence[float]]) -> str:
    if not ci:
        return "n/a"
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def fmt_val(x: Optional[float], unit: str) -> str:
    return hc.fmt_num(x, unit)


def fmt_delta(d: Optional[float], unit: str) -> str:
    if d is None:
        return "n/a"
    s = hc.fmt_num(abs(d), unit)
    return ("+" if d > 0 else "-" if d < 0 else "") + s


def env_lines(fps: List[str], mixed: bool, rows: Sequence[Dict[str, Any]]) -> List[str]:
    out = []
    if mixed:
        out.append(f"**Environment: MIXED** ({len(fps)} fingerprints; report only, no gates): " + ", ".join(f"`{f[:12]}`" for f in fps))
    elif fps:
        env = next((r.get("env") or {} for r in rows if (r.get("env") or {}).get("fingerprint") == fps[0]), {})
        desc = ", ".join(f"{k}={env[k]}" for k in ("runner", "os", "device", "emulator", "simulator", "xcode", "jdk", "unity", "tier") if env.get(k))
        out.append(f"Environment fingerprint `{fps[0][:12]}` ({desc})" if desc else f"Environment fingerprint `{fps[0][:12]}`")
    return out


def excluded_section(bad: Sequence[Dict[str, Any]]) -> str:
    if not bad:
        return "No rows were excluded."
    lines = []
    for r in bad:
        lines.append([r.get("sdk"), r.get("sdkVersion"), r.get("variant"), r.get("scenario"), r.get("metric"),
                      r.get("round", ""), os.path.basename(str(r.get("_file", ""))), (r.get("notes") or "")[:160]])
    return hc.md_table(["sdk", "version", "variant", "scenario", "metric", "round", "file", "reason"], lines)


# ----------------------------------------------------------------------- modes

def mode_ladder(args: argparse.Namespace, th: Dict[str, Any], catalog: hc.MetricCatalog) -> Tuple[str, Dict[str, Any], int]:
    rows = hc.read_rows([args.results])
    rows = [r for r in rows if r.get("sdk") == args.sdk and r.get("variant", "sdk") == args.variant]
    if args.scenario:
        rows = [r for r in rows if r.get("scenario", "default") == args.scenario]
    good, bad = split_valid(rows)
    versions = [v.strip() for v in args.ladder.split(",") if v.strip()]
    good = [r for r in good if str(r.get("sdkVersion")) in versions]
    if not good:
        raise CompareError(f"no valid rows for sdk={args.sdk} versions={versions} under {args.results}")
    fps, mixed = check_env(good, args.allow_mixed_env)
    groups = group_rows(good)
    anchor = versions[0]
    newest = versions[-1]
    present = [v for v in versions if any(k[3] == v for k in groups)]
    metrics = sorted({k[0] for k in groups}, key=lambda m: (m.split(".")[0], m))

    table_rows: List[List[str]] = []
    entries: List[Dict[str, Any]] = []
    for m in metrics:
        scen = sorted({k[1] for k in groups if k[0] == m})
        for sc in scen:
            per_v = {v: groups.get((m, sc, args.variant, v)) for v in present}
            unit = next(g.unit for g in per_v.values() if g)
            gate = thr.resolve_gate(m, th, catalog)
            cells = [f"`{m}`" + (f" ({sc})" if sc != "default" else ""), gate["class"]]
            prev_val: Optional[float] = None
            values: Dict[str, Optional[float]] = {}
            for v in present:
                g = per_v[v]
                val = g.value if g else None
                values[v] = val
                if val is None:
                    cells.append("n/a")
                elif prev_val in (None, 0):
                    cells.append(fmt_val(val, unit))
                else:
                    cells.append(f"{fmt_val(val, unit)} ({hc.fmt_pct(val / prev_val - 1)})")
                if val is not None:
                    prev_val = val
            a, n = per_v.get(anchor), per_v.get(newest)
            cmp_ = compare_groups(a, n, th, catalog, args.seed, gating=False) if (a and n) else None
            if cmp_:
                cells += [hc.fmt_pct(cmp_["delta_rel"]), fmt_ci(cmp_["ci"]), cmp_["verdict"]]
            else:
                cells += ["n/a", "n/a", "n/a"]
            table_rows.append(cells)
            entries.append({"metric": m, "scenario": sc, "unit": unit, "class": gate["class"], "values": values, "newest_vs_anchor": cmp_})

    headers = ["metric", "class"] + present + [f"Δ {anchor}→{newest}", f"{int(th['comparison']['ci'] * 100)}% CI (ratio)", "verdict"]
    md = [f"## {args.sdk} ladder: {' → '.join(present)}", ""]
    md += env_lines(fps, mixed, good)
    md += [f"Anchor (oldest) = {anchor}; each cell shows the pooled median and Δ vs the previous column; CI = bootstrap of paired per-round ratios newest/anchor where rounds exist ({th['comparison']['bootstrap_resamples']} resamples, seed {args.seed}). Ladders never gate.", ""]
    md.append(hc.md_table(headers, table_rows))
    md += ["", "### Excluded rows", "", excluded_section(bad)]
    data = {"mode": "ladder", "sdk": args.sdk, "versions": present, "anchor": anchor, "fingerprints": fps, "mixed_env": mixed,
            "metrics": entries, "excluded": [hc.strip_private(r) for r in bad], "exit_code": EXIT_OK}
    return "\n".join(md) + "\n", data, EXIT_OK


def _find_group(groups: Dict[Tuple[str, str, str, str], Group], metric_glob: str, scenario: Optional[str], variant: str) -> Optional[Group]:
    import fnmatch

    for k, g in groups.items():
        if fnmatch.fnmatchcase(k[0], metric_glob) and k[2] == variant and (scenario is None or k[1] == scenario):
            return g
    return None


def kpi_block(sdk: str, base_groups: Dict, head_groups: Dict, plain_groups: Dict, th: Dict[str, Any], catalog: hc.MetricCatalog,
              seed: int, scenario: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    spec = KPI[sdk]
    lines: List[List[str]] = []
    data: List[Dict[str, Any]] = []
    sc = scenario or "default"

    # size added by the SDK: head(sdk) - plain when plain rows exist, else the published artifact bytes
    integrated, published = spec["size"]
    hs = _find_group(head_groups, integrated, sc, "sdk")
    ps = _find_group(plain_groups, integrated, sc, "plain") or _find_group(head_groups, integrated, sc, "plain")
    bs = _find_group(base_groups, integrated, sc, "sdk")
    bp = _find_group(base_groups, integrated, sc, "plain") or ps
    if hs and ps:
        head_added = hs.value - ps.value
        base_added = (bs.value - bp.value) if (bs and bp) else None
        d = (head_added - base_added) if base_added is not None else None
        lines.append(["Size added by SDK (integrated, vs plain)", fmt_val(base_added, "bytes"), fmt_val(head_added, "bytes"), fmt_delta(d, "bytes"), "n/a",
                      "n/a" if d is None else ("no change" if d == 0 else ("regressed (within threshold)" if d > 0 else "improved"))])
        data.append({"kpi": "size_added", "base": base_added, "head": head_added, "delta": d})
        if head_added <= 0:
            lines[-1][-1] = "INVALID: plain-vs-sdk size diff must be > 0"
    else:
        hg = _find_group(head_groups, published, sc, "sdk")
        bg = _find_group(base_groups, published, sc, "sdk")
        c = compare_groups(bg, hg, th, catalog, seed, gating=False) if (hg or bg) else None
        if c:
            lines.append([f"Size added by SDK (published artifact `{published}`)", fmt_val(c["base"], "bytes"), fmt_val(c["head"], "bytes"),
                          fmt_delta(c["delta"], "bytes"), fmt_ci(c["ci"]), c["verdict"]])
            data.append({"kpi": "size_added", **c})
        else:
            lines.append(["Size added by SDK", "n/a", "n/a", "n/a", "n/a", "no size rows"])
    for label, key in (("Init total (main thread)", "init"), ("send p50 (end-to-end)", "send"), ("Cold start", "cold")):
        m = spec[key]
        hg = _find_group(head_groups, m, sc, "sdk")
        bg = _find_group(base_groups, m, sc, "sdk")
        if hg or bg:
            c = compare_groups(bg, hg, th, catalog, seed, gating=False)
            lines.append([f"{label} `{m}`", fmt_val(c["base"], c["unit"]), fmt_val(c["head"], c["unit"]), fmt_delta(c["delta"], c["unit"]), fmt_ci(c["ci"]), c["verdict"]])
            data.append({"kpi": key, **c})
        else:
            lines.append([f"{label} `{m}`", "n/a", "n/a", "n/a", "n/a", "no rows"])
    return hc.md_table(["KPI", "base", "head", "Δ", "95% CI (ratio)", "verdict"], lines), data


def mode_pr(args: argparse.Namespace, th: Dict[str, Any], catalog: hc.MetricCatalog) -> Tuple[str, Dict[str, Any], int]:
    base_rows = hc.read_rows([args.base])
    head_rows = hc.read_rows([args.head])
    plain_rows = hc.read_rows([args.plain]) if args.plain else []
    sentinel_rows = hc.read_rows([args.sentinel]) if args.sentinel else []
    sentinel_rows += [r for r in head_rows if r.get("variant") == "sentinel"]
    head_rows = [r for r in head_rows if r.get("variant") != "sentinel"]
    if args.scenario:
        flt = lambda rs: [r for r in rs if r.get("scenario", "default") == args.scenario]  # noqa: E731
        base_rows, head_rows, plain_rows, sentinel_rows = flt(base_rows), flt(head_rows), flt(plain_rows), flt(sentinel_rows)
    all_rows = base_rows + head_rows + plain_rows + sentinel_rows
    good, bad = split_valid(all_rows)
    if not good:
        raise CompareError("no valid rows to compare")
    fps, mixed = check_env(good, args.allow_mixed_env)
    gating = bool(args.gate) and not mixed

    bg = group_rows([r for r in base_rows if hc.row_is_valid(r) and r.get("variant", "sdk") != "plain"])
    hg = group_rows([r for r in head_rows if hc.row_is_valid(r) and r.get("variant", "sdk") != "plain"])
    pg = group_rows([r for r in plain_rows + base_rows + head_rows if hc.row_is_valid(r) and r.get("variant") == "plain"])
    sg = group_rows([r for r in sentinel_rows if hc.row_is_valid(r)])
    sdks = sorted({r.get("sdk") for r in good if r.get("sdk")})
    sdk = sdks[0] if len(sdks) == 1 else None

    noise = noise_from_sentinel(sg, hg, th, catalog)
    noisy = bool(noise["noisy"])
    if noisy:
        gating = False

    results: List[Dict[str, Any]] = []
    keys = sorted({(k[0], k[1]) for k in list(bg) + list(hg)}, key=lambda t: (t[0].split(".")[0], t))
    for metric, scenario in keys:
        b = next((g for k, g in bg.items() if k[0] == metric and k[1] == scenario), None)
        h = next((g for k, g in hg.items() if k[0] == metric and k[1] == scenario), None)
        c = compare_groups(b, h, th, catalog, args.seed, gating)
        c["scenario"] = scenario
        results.append(c)

    failed = [c for c in results if c["fails_gate"]]
    inconclusive = [c for c in results if c["inconclusive"]]
    if args.gate:
        if noisy or mixed:
            code = EXIT_NOISY if args.strict else EXIT_OK
        elif failed:
            code = EXIT_GATE_FAILED
        elif inconclusive:
            code = EXIT_NOISY if args.strict else EXIT_OK
        else:
            code = EXIT_OK
    else:
        code = EXIT_OK

    base_versions = sorted({str(r.get("sdkVersion")) for r in base_rows}, key=hc.version_key)
    head_versions = sorted({str(r.get("sdkVersion")) for r in head_rows}, key=hc.version_key)
    md = [f"## PR comparison{': ' + sdk if sdk else ''} — base {', '.join(base_versions) or 'n/a'} vs head {', '.join(head_versions) or 'n/a'}", ""]
    md += env_lines(fps, mixed, good)
    if noise["measured"]:
        worst = noise["max_rel"]
        md.append(f"Noise floor (sentinel self-vs-self, max |Δ| over pair metrics): **{hc.fmt_pct(worst) if worst is not None else 'n/a'}** "
                  f"(limit {hc.fmt_pct(noise['limit'])}) → {'**NOISY: gates disabled**' if noisy else 'ok'}")
    else:
        md.append("Noise floor: not measured (no sentinel rows).")
    md.append("")
    if sdk:
        md += ["### Headline", ""]
        block, kpis = kpi_block(sdk, bg, hg, pg, th, catalog, args.seed, args.scenario)
        md += [block, ""]
    else:
        kpis = []
    md += ["### All metrics", ""]
    trows = []
    for c in results:
        name = f"`{c['metric']}`" + (f" ({c['scenario']})" if c["scenario"] != "default" else "")
        verdict = c["verdict"]
        if c["reasons"]:
            verdict += " (" + "; ".join(c["reasons"]) + ")"
        if c["fails_gate"]:
            verdict = f"**GATE FAILED** {verdict}"
        trows.append([name, c["class"], fmt_val(c["base"], c["unit"]), fmt_val(c["head"], c["unit"]), fmt_delta(c["delta"], c["unit"]),
                      hc.fmt_pct(c["delta_rel"]), fmt_ci(c["ci"]) + ("" if c["ci_kind"] == "n/a" else f" {c['ci_kind']}"), verdict])
    md.append(hc.md_table(["Metric", "class", "base", "head", "Δ", "Δ%", f"{int(th['comparison']['ci'] * 100)}% CI (ratio)", "verdict"], trows))
    md += ["", f"Gate result: {'not evaluated (--gate not given)' if not args.gate else ('disabled (noisy/mixed env)' if (noisy or mixed) else ('FAILED: ' + ', '.join(c['metric'] for c in failed) if failed else 'passed'))}"
           + (f"; inconclusive: {', '.join(c['metric'] for c in inconclusive)}" if inconclusive else "") + f"; exit code {code}", ""]
    md += ["### Excluded rows", "", excluded_section(bad)]
    data = {"mode": "pr", "sdk": sdk, "fingerprints": fps, "mixed_env": mixed, "noise": noise, "gating": gating, "kpis": kpis,
            "metrics": results, "failed": [c["metric"] for c in failed], "inconclusive": [c["metric"] for c in inconclusive],
            "excluded": [hc.strip_private(r) for r in bad], "exit_code": code}
    return "\n".join(md) + "\n", data, code


def mode_overhead(args: argparse.Namespace, th: Dict[str, Any], catalog: hc.MetricCatalog) -> Tuple[str, Dict[str, Any], int]:
    plain_rows = hc.read_rows([args.plain])
    sdk_rows = hc.read_rows([args.sdk_rows or args.head])
    if args.scenario:
        plain_rows = [r for r in plain_rows if r.get("scenario", "default") == args.scenario]
        sdk_rows = [r for r in sdk_rows if r.get("scenario", "default") == args.scenario]
    good, bad = split_valid(plain_rows + sdk_rows)
    if not good:
        raise CompareError("no valid rows")
    fps, mixed = check_env(good, args.allow_mixed_env)
    pg = group_rows([r for r in plain_rows if hc.row_is_valid(r) and r.get("variant") == "plain"])
    sg = group_rows([r for r in sdk_rows if hc.row_is_valid(r) and r.get("variant", "sdk") == "sdk"])
    if not pg:
        raise CompareError("no valid variant=plain rows in --plain")
    if not sg:
        raise CompareError("no valid variant=sdk rows")
    entries = []
    trows = []
    for (metric, scenario, _v, _ver), s in sorted(sg.items(), key=lambda kv: (kv[0][0].split(".")[0], kv[0])):
        p = next((g for k, g in pg.items() if k[0] == metric and k[1] == scenario), None)
        if p is None:
            continue
        c = compare_groups(p, s, th, catalog, args.seed, gating=False)
        trows.append([f"`{metric}`" + (f" ({scenario})" if scenario != "default" else ""), fmt_val(c["base"], c["unit"]), fmt_val(c["head"], c["unit"]),
                      f"{fmt_delta(c['delta'], c['unit'])} ({hc.fmt_pct(c['delta_rel'])})", fmt_ci(c["ci"])])
        entries.append({"metric": metric, "scenario": scenario, "plain": c["base"], "sdk": c["head"], "overhead": c["delta"], "overhead_rel": c["delta_rel"], "ci": c["ci"], "unit": c["unit"]})
    versions = sorted({str(r.get("sdkVersion")) for r in sdk_rows}, key=hc.version_key)
    md = [f"## Overhead: plain vs with Backtrace ({', '.join(versions)})", ""]
    md += env_lines(fps, mixed, good)
    md += ["", hc.md_table(["Metric", "Plain", "With Backtrace", "Overhead", f"{int(th['comparison']['ci'] * 100)}% CI (ratio)"], trows) if trows else "No metric is present for both variants.", "", "### Excluded rows", "", excluded_section(bad)]
    data = {"mode": "overhead", "fingerprints": fps, "mixed_env": mixed, "metrics": entries, "excluded": [hc.strip_private(r) for r in bad], "exit_code": EXIT_OK}
    return "\n".join(md) + "\n", data, EXIT_OK


# ------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=("md", "json"), default="md")
    common.add_argument("--out")
    common.add_argument("--summary-file", help="append the Markdown to this file (e.g. $GITHUB_STEP_SUMMARY)")
    common.add_argument("--allow-mixed-env", action="store_true")
    common.add_argument("--seed", type=int, default=0)
    common.add_argument("--thresholds", default=hc.THRESHOLDS_PATH)
    common.add_argument("--metrics", default=hc.METRICS_PATH)
    common.add_argument("--scenario")
    common.add_argument("--quiet", action="store_true", help="do not print the report to stdout")
    sub = ap.add_subparsers(dest="mode", required=True)
    lp = sub.add_parser("ladder", parents=[common])
    lp.add_argument("--results", required=True)
    lp.add_argument("--sdk", required=True, choices=hc.SDKS)
    lp.add_argument("--ladder", required=True, help="comma-separated versions, oldest first (anchor)")
    lp.add_argument("--variant", default="sdk", choices=hc.VARIANTS)
    pp = sub.add_parser("pr", parents=[common])
    pp.add_argument("--base", required=True)
    pp.add_argument("--head", required=True)
    pp.add_argument("--plain")
    pp.add_argument("--sentinel")
    pp.add_argument("--gate", action="store_true")
    pp.add_argument("--strict", action="store_true")
    op = sub.add_parser("overhead", parents=[common])
    op.add_argument("--plain", required=True)
    op.add_argument("--sdk-rows", dest="sdk_rows")
    op.add_argument("--head")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.mode == "overhead" and not (args.sdk_rows or args.head):
        ap.error("overhead needs --sdk-rows or --head")
    try:
        th = thr.load_thresholds(args.thresholds, args.metrics)
    except (thr.ThresholdsError, OSError) as exc:
        print(f"compare: {exc}", file=sys.stderr)
        return EXIT_ERROR
    catalog = th["_catalog"]
    try:
        md, data, code = {"ladder": mode_ladder, "pr": mode_pr, "overhead": mode_overhead}[args.mode](args, th, catalog)
    except (CompareError, ValueError, OSError) as exc:
        print(f"compare: {exc}", file=sys.stderr)
        return EXIT_ERROR
    text = md if args.format == "md" else json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
    if not args.quiet:
        sys.stdout.write(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
