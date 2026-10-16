import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import synth  # noqa: E402


def run(args, **kw):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=REPO, **kw)


class ThresholdsTests(unittest.TestCase):
    def test_repo_thresholds_are_valid(self):
        r = run([os.path.join(SCRIPTS, "thresholds.py"), "validate"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_zero_gate_is_rejected(self):
        bad = """version: 1
noise: {sentinel_max_rel: 0.05, cov_max: {ttid: 0.2, trace: 0.12, micro: 0.1}, rerun_failing_variant_once: true}
comparison: {bootstrap_resamples: 100, ci: 0.95, pairing: per_round_ratio_to_anchor}
gates:
  - {name: bad, match: ["A0.*"], class: det, rel: 0, abs: 0}
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(bad)
        r = run([os.path.join(SCRIPTS, "thresholds.py"), "--thresholds", f.name, "validate"])
        self.assertNotEqual(r.returncode, 0, "a det gate with rel=0 and abs=0 must be rejected")


class ValidateRowsTests(unittest.TestCase):
    def test_wildcard_metric_ids_validate(self):
        rows = [synth.size_row("A0.so_bytes.arm64-v8a", 5397056, "3.14.0"),
                synth.row("U5.db_reload.seeded_8", "ms", [0.02, 0.03], "3.17.0", kind="perIteration")]
        rows[1]["sdk"] = "unity"; rows[1]["platform"] = "unity-editor"; rows[1]["source"] = "openupm"
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            synth.write(f.name, rows)
        r = run([os.path.join(SCRIPTS, "validate_rows.py"), f.name])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_unknown_metric_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            synth.write(f.name, [synth.size_row("Z9.nonsense", 1, "3.14.0")])
        r = run([os.path.join(SCRIPTS, "validate_rows.py"), f.name])
        self.assertNotEqual(r.returncode, 0)


class CompareTests(unittest.TestCase):
    def _pr(self, base_center, head_center, gate=True, sentinel=None, extra_args=()):
        d = tempfile.mkdtemp()
        base = synth.timing_rows("A4.send.e2e_ms", "ms", base_center, "3.13.0", "sdk", seed=1) + [synth.size_row("A0.aar_bytes", 7019760, "3.13.0")]
        head = synth.timing_rows("A4.send.e2e_ms", "ms", head_center, "3.14.0", "sdk", seed=2) + [synth.size_row("A0.aar_bytes", 7031209, "3.14.0")]
        synth.write(os.path.join(d, "base.jsonl"), base)
        synth.write(os.path.join(d, "head.jsonl"), head)
        args = [os.path.join(SCRIPTS, "compare.py"), "pr", "--base", os.path.join(d, "base.jsonl"), "--head", os.path.join(d, "head.jsonl"),
                "--format", "md", "--out", os.path.join(d, "out.md")]
        if sentinel is not None:
            synth.write(os.path.join(d, "sentinel.jsonl"), synth.timing_rows("A4.send.e2e_ms", "ms", sentinel, "3.14.0", "sentinel", seed=3))
            args += ["--sentinel", os.path.join(d, "sentinel.jsonl")]
        if gate:
            args.append("--gate")
        args += list(extra_args)
        r = run(args)
        return r, open(os.path.join(d, "out.md")).read() if os.path.exists(os.path.join(d, "out.md")) else ""

    def test_no_change_passes(self):
        r, md = self._pr(10.0, 10.0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("A4.send.e2e_ms", md)

    def test_regression_fails_gate(self):
        r, md = self._pr(10.0, 13.0)
        self.assertEqual(r.returncode, 2, "30% slower send must fail the pair gate\n" + r.stdout + r.stderr + md)

    def test_improvement_passes(self):
        r, md = self._pr(10.0, 8.0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("### Improvements", md)
        self.assertRegex(md, r"### Improvements\n\n- 🟢 `A4.send.e2e_ms`", "a 20% faster send must be listed as an improvement")
        self.assertIn("1 improved", md)

    def test_no_change_is_not_called_an_improvement(self):
        r, md = self._pr(10.0, 10.0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("### Improvements\n\nNone.", md)
        self.assertIn("0 improved", md)

    def test_noisy_sentinel_disables_gates(self):
        # sentinel is the same version as head but measured 20% off: the job is noisy, no gate may fail
        r, md = self._pr(10.0, 13.0, sentinel=12.0)
        self.assertIn(r.returncode, (0, 3), r.stdout + r.stderr)
        r2, _ = self._pr(10.0, 13.0, sentinel=12.0, extra_args=("--strict",))
        self.assertEqual(r2.returncode, 3, r2.stdout + r2.stderr)

    def test_mixed_env_refused(self):
        d = tempfile.mkdtemp()
        other = dict(synth.ENV, fingerprint="e" * 64)
        synth.write(os.path.join(d, "base.jsonl"), synth.timing_rows("A4.send.e2e_ms", "ms", 10, "3.13.0", "sdk"))
        synth.write(os.path.join(d, "head.jsonl"), synth.timing_rows("A4.send.e2e_ms", "ms", 10, "3.14.0", "sdk", env=other))
        r = run([os.path.join(SCRIPTS, "compare.py"), "pr", "--base", os.path.join(d, "base.jsonl"), "--head", os.path.join(d, "head.jsonl"), "--gate"])
        self.assertNotEqual(r.returncode, 0, "different fingerprints must be refused without --allow-mixed-env")
        r2 = run([os.path.join(SCRIPTS, "compare.py"), "pr", "--base", os.path.join(d, "base.jsonl"), "--head", os.path.join(d, "head.jsonl"), "--allow-mixed-env"])
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

    def test_ladder_renders_all_versions(self):
        d = tempfile.mkdtemp()
        rows = []
        for i, v in enumerate(["3.8.4", "3.9.0", "3.10.6"]):
            rows.append(synth.size_row("A0.aar_bytes", 6500000 + i * 100000, v))
        synth.write(os.path.join(d, "rows.jsonl"), rows)
        r = run([os.path.join(SCRIPTS, "compare.py"), "ladder", "--results", d, "--sdk", "android", "--ladder", "3.8.4,3.9.0,3.10.6", "--format", "md"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for v in ["3.8.4", "3.9.0", "3.10.6"]:
            self.assertIn(v, r.stdout)
        self.assertIn("### Improvements since 3.8.4", r.stdout)
        self.assertRegex(r.stdout, r"\*\*3\.8\.4 → 3\.10\.6: 🟢 \d+ improved", "the ladder opens with the tally")


class StatsTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, SCRIPTS)
        import random
        import stats as st
        self.st = st
        rng = random.Random(3)
        self.base = {r: [100 * (1 + rng.uniform(-0.15, 0.15)) for _ in range(15)] for r in (1, 2, 3)}
        self.same = {r: [100 * (1 + rng.uniform(-0.15, 0.15)) for _ in range(15)] for r in (1, 2, 3)}
        self.faster = {r: [70 * (1 + rng.uniform(-0.15, 0.15)) for _ in range(15)] for r in (1, 2, 3)}

    def test_stratified_ci_contains_one_for_identical_distributions(self):
        lo, hi = self.st.stratified_ratio_ci(self.base, self.same, resamples=2000)
        self.assertLessEqual(lo, 1.0)
        self.assertGreaterEqual(hi, 1.0)
        self.assertLess(lo, hi, "the interval must not collapse to a point")

    def test_stratified_ci_excludes_one_for_a_real_change(self):
        lo, hi = self.st.stratified_ratio_ci(self.base, self.faster, resamples=2000)
        self.assertLess(hi, 1.0, (lo, hi))
        self.assertAlmostEqual(self.st.point_ratio(self.base, self.faster), 0.7, delta=0.05)

    def test_single_round_is_not_a_point_interval(self):
        lo, hi = self.st.stratified_ratio_ci({1: self.base[1]}, {1: self.same[1]}, resamples=2000)
        self.assertLess(lo, hi)
        self.assertLessEqual(lo, 1.0)
        self.assertGreaterEqual(hi, 1.0)

    def test_verdict_tiers(self):
        v = self.st.verdict
        pair = {"class": "pair", "rel": 0.10, "abs": 0.5}
        self.assertEqual(v(100, 80, pair, (0.70, 0.90), point=0.80)["tier"], "improved")
        self.assertEqual(v(100, 97, pair, (0.95, 0.99), point=0.97)["tier"], "improved (small)")
        self.assertEqual(v(100, 100.5, pair, (0.97, 1.04), point=1.005)["tier"], "no change")
        wide = v(100, 80, pair, (0.78, 1.01), point=0.80)
        self.assertEqual(wide["tier"], "inconclusive")
        self.assertEqual(wide["lean"], "improved")
        self.assertIn("leaning improved", wide["verdict"])
        reg = v(100, 130, pair, (1.25, 1.35), point=1.30)
        self.assertEqual((reg["tier"], reg["fails_gate"]), ("regressed", True))
        small = v(100, 103, pair, (1.01, 1.05), point=1.03)
        self.assertEqual((small["tier"], small["fails_gate"]), ("regressed (small)", False))
        warn = v(100, 130, {"class": "warn"}, (1.25, 1.35), point=1.30)
        self.assertEqual((warn["tier"], warn["fails_gate"]), ("regressed", False), "warn rules never fail")
        det = {"class": "det", "rel": 0.02, "abs": 102400}
        self.assertEqual(v(16977815, 16977817, det)["tier"], "within threshold")
        self.assertEqual(v(1000000, 1200000, det)["fails_gate"], True)
        self.assertEqual(v(1200000, 1000000, det)["tier"], "improved")
        self.assertEqual(v(5, 5, det)["tier"], "no change")

    def test_degenerate_ci_never_yields_a_small_tier(self):
        v = self.st.verdict
        pair = {"class": "pair", "rel": 0.10, "abs": 0.5}
        zero_width = v(100, 99, pair, (0.99, 0.99), point=0.99)
        self.assertEqual(zero_width["tier"], "inconclusive")
        self.assertIn("no CI", zero_width["verdict"])
        self.assertTrue(zero_width["no_ci"])
        self.assertEqual(v(100, 99, pair, None, point=0.99)["tier"], "inconclusive")
        ci = self.st.stratified_ratio_ci({1: [5.0] * 10}, {1: [5.0] * 10}, resamples=200)
        self.assertEqual(ci, (1.0, 1.0), "identical samples give a zero-width interval, handled by verdict()")

    def test_wide_ci_inside_band_is_not_inconclusive(self):
        v = self.st.verdict
        pair = {"class": "pair", "rel": 0.10, "abs": 0.5}
        r = v(100, 101, pair, (0.88, 1.15), point=1.01)
        self.assertEqual(r["tier"], "no significant change")
        self.assertIsNone(r["lean"])
        self.assertFalse(r["no_ci"])

    def test_single_value_strata_fall_back_to_unpaired(self):
        lo, hi = self.st.stratified_ratio_ci({1: [10.0], 2: [11.0], 3: [9.0]}, {1: [8.0], 2: [8.5], 3: [7.5]}, resamples=500)
        self.assertLess(lo, hi)
        self.assertLess(hi, 1.0)

    def test_too_few_samples_is_inconclusive_for_every_class(self):
        v = self.st.verdict
        det = v(1000000, 1500000, {"class": "det", "rel": 0.02, "abs": 102400}, inconclusive=True)
        self.assertEqual((det["tier"], det["fails_gate"]), ("inconclusive", False))
        pair = v(100, 150, {"class": "pair", "rel": 0.10, "abs": 0.5}, (1.4, 1.6), inconclusive=True, point=1.5)
        self.assertEqual((pair["tier"], pair["fails_gate"]), ("inconclusive", False))
        self.assertIn("leaning regressed", pair["verdict"])

    def test_delta_follows_the_paired_ratio_for_timing_metrics(self):
        v = self.st.verdict
        r = v(10.71, 11.11, {"class": "warn"}, (0.8, 1.05), point=0.90)
        self.assertLess(r["delta"], 0, "pooled medians rose but the paired ratio fell: the shown delta follows the ratio")
        self.assertAlmostEqual(r["delta"], 10.71 * -0.10, places=6)
        d = v(100, 104, {"class": "det", "rel": 0.02, "abs": 1}, point=0.90)
        self.assertEqual(d["delta"], 4, "deterministic rows keep the exact difference")

    def test_robust_cov_ignores_outliers(self):
        xs = [100.0] * 20 + [1800.0]
        self.assertGreater(self.st.cov(xs), 0.5)
        self.assertLess(self.st.robust_cov(xs), 0.01)


class ParseBenchResultTests(unittest.TestCase):
    def _parse(self, expect_mock):
        d = tempfile.mkdtemp()
        env = os.path.join(d, "env.json")
        json.dump(synth.ENV, open(env, "w"))
        out = os.path.join(d, "rows.jsonl")
        r = run([os.path.join(SCRIPTS, "parse_bench_result.py"), os.path.join(HERE, "fixtures", "bench-result-android.json"), "--sdk", "android",
                 "--sdk-version", "3.14.0", "--variant", "sdk", "--env", env, "--expect-mock-requests", str(expect_mock), "--out", out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return [json.loads(l) for l in open(out)]

    def test_stages_become_rows(self):
        rows = self._parse(2)
        metrics = {r["metric"]: r for r in rows}
        self.assertIn("A1.init.total", metrics)
        self.assertIn("A1.init.native", metrics)
        self.assertAlmostEqual(metrics["A1.init.total"]["value"], 57.0)
        self.assertTrue(all(r.get("valid", True) for r in rows))
        v = run([os.path.join(SCRIPTS, "validate_rows.py"), "-"], input="\n".join(json.dumps(r) for r in rows)) if False else None

    def test_mock_mismatch_marks_invalid(self):
        rows = self._parse(5)
        self.assertTrue(rows, "rows expected")
        self.assertTrue(all(r.get("valid") is False for r in rows), "mock request mismatch must invalidate the launch")


class FingerprintTests(unittest.TestCase):
    def test_env_fingerprint_is_deterministic(self):
        a = subprocess.run(["bash", os.path.join(SCRIPTS, "env_fingerprint.sh"), "--tier", "tier0"], capture_output=True, text=True, cwd=REPO).stdout
        b = subprocess.run(["bash", os.path.join(SCRIPTS, "env_fingerprint.sh"), "--tier", "tier0"], capture_output=True, text=True, cwd=REPO).stdout
        self.assertEqual(json.loads(a)["fingerprint"], json.loads(b)["fingerprint"])
        c = subprocess.run(["bash", os.path.join(SCRIPTS, "env_fingerprint.sh"), "--tier", "tier1"], capture_output=True, text=True, cwd=REPO).stdout
        self.assertNotEqual(json.loads(a)["fingerprint"], json.loads(c)["fingerprint"])



class ParseBenchResultExclusionTests(unittest.TestCase):
    def _rows(self, extra):
        d = tempfile.mkdtemp()
        env = os.path.join(d, "env.json")
        json.dump(synth.ENV, open(env, "w"))
        out = os.path.join(d, "rows.jsonl")
        r = run([os.path.join(SCRIPTS, "parse_bench_result.py"), os.path.join(HERE, "fixtures", "bench-result-android.json"), "--sdk", "android",
                 "--sdk-version", "3.14.0", "--variant", "sdk", "--env", env, "--expect-mock-requests", "2", "--out", out] + list(extra))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return [json.loads(l) for l in open(out)], r.stderr

    def test_exclude_metrics_glob(self):
        rows, _ = self._rows([])
        self.assertTrue(any(r["metric"].startswith("A1.") for r in rows))
        rows, err = self._rows(["--exclude-metrics", "A1.*"])
        self.assertFalse(any(r["metric"].startswith("A1.") for r in rows), [r["metric"] for r in rows])
        self.assertIn("dropped", err)

    def test_exclude_metrics_present_in_platform_rows(self):
        rows, _ = self._rows([])
        covered = os.path.join(tempfile.mkdtemp(), "rows-platform.jsonl")
        first = rows[0]["metric"]
        synth.write(covered, [rows[0]])
        rows2, _ = self._rows(["--exclude-metrics-in", covered])
        self.assertNotIn(first, [r["metric"] for r in rows2])
        self.assertEqual(len(rows2), len(rows) - 1)


class LaunchFileSelectionTests(unittest.TestCase):
    def _dir(self, n_indexed, with_latest=True):
        d = tempfile.mkdtemp()
        for i in range(1, n_indexed + 1):
            open(os.path.join(d, "bt-bench-stages-%d.json" % i), "w").write(json.dumps({"i": i}))
        if with_latest:
            open(os.path.join(d, "bt-bench-stages.json"), "w").write(json.dumps({"i": n_indexed}))
        open(os.path.join(d, "bench-result-micro.json"), "w").write("{}")
        return d

    def test_latest_copy_is_not_counted_twice(self):
        sys.path.insert(0, SCRIPTS)
        import parse_bench_result as pbr
        names = sorted(os.path.basename(f) for f in pbr.find_files([self._dir(11)]))
        self.assertNotIn("bt-bench-stages.json", names)
        self.assertIn("bench-result-micro.json", names, "non-indexed files of another stem are untouched")
        self.assertEqual(len([n for n in names if n.startswith("bt-bench-stages-")]), 11)

    def test_drop_first_removes_exactly_the_warmups(self):
        sys.path.insert(0, SCRIPTS)
        import parse_bench_result as pbr
        d = self._dir(11)
        os.remove(os.path.join(d, "bt-bench-stages-7.json"))   # one measured launch wrote no file
        names = sorted(os.path.basename(f) for f in pbr.find_files([d], drop_first=1))
        self.assertNotIn("bt-bench-stages-1.json", names)
        self.assertEqual(len([n for n in names if n.startswith("bt-bench-stages-")]), 9, "only the warm-up is dropped")

    def test_keep_last_drops_warmup_launches(self):
        sys.path.insert(0, SCRIPTS)
        import parse_bench_result as pbr
        names = sorted(os.path.basename(f) for f in pbr.find_files([self._dir(11)], keep_last=10))
        self.assertNotIn("bt-bench-stages-1.json", names)
        self.assertEqual(len([n for n in names if n.startswith("bt-bench-stages-")]), 10)
        all_names = sorted(os.path.basename(f) for f in pbr.find_files([self._dir(3, with_latest=False)], keep_last=10))
        self.assertEqual(len(all_names), 4, "keep_last larger than the file count keeps everything")


class FetchRetryTests(unittest.TestCase):
    def test_truncated_body_is_retried(self):
        import http.client
        sys.path.insert(0, os.path.join(REPO, "apple", "scripts"))
        import fetch_xcframework as fx
        d = tempfile.mkdtemp()
        calls = {"n": 0}
        real = fx.urllib.request.urlopen

        class Resp:
            def __init__(self, body, declared):
                self.body, self.headers = body, {"Content-Length": str(declared)}
                self.pos = 0
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1):
                chunk = self.body[self.pos:] if n < 0 else self.body[self.pos:self.pos + n]
                self.pos += len(chunk)
                return chunk

        def flaky(request, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                return Resp(b"abc", 10)            # short body for the announced length
            if calls["n"] == 2:
                raise http.client.IncompleteRead(b"ab")
            return Resp(b"0123456789", 10)
        fx.urllib.request.urlopen = flaky
        try:
            fx.download("https://example.invalid/c.tar.gz", os.path.join(d, "c.tar.gz"), sleep=lambda s: None)
        finally:
            fx.urllib.request.urlopen = real
        self.assertEqual(calls["n"], 3)
        self.assertEqual(open(os.path.join(d, "c.tar.gz"), "rb").read(), b"0123456789")

    def test_transient_errors_retry_and_404_is_final(self):
        import urllib.error
        sys.path.insert(0, os.path.join(REPO, "apple", "scripts"))
        import fetch_xcframework as fx
        d = tempfile.mkdtemp()
        calls = {"n": 0}
        real = fx.urllib.request.urlopen

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return b""

        def flaky(request, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("nodename nor servname provided")
            return Resp()
        fx.urllib.request.urlopen = flaky
        try:
            fx.download("https://example.invalid/a.tar.gz", os.path.join(d, "a.tar.gz"), sleep=lambda s: None)
            self.assertEqual(calls["n"], 3, "two transient failures then success")
            self.assertTrue(os.path.exists(os.path.join(d, "a.tar.gz")))
            calls["n"] = 0

            def missing(request, timeout=0):
                calls["n"] += 1
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            fx.urllib.request.urlopen = missing
            with self.assertRaises(urllib.error.HTTPError):
                fx.download("https://example.invalid/b.tar.gz", os.path.join(d, "b.tar.gz"), sleep=lambda s: None)
            self.assertEqual(calls["n"], 1, "a 404 must not be retried")
        finally:
            fx.urllib.request.urlopen = real


class RowHygieneTests(unittest.TestCase):
    def test_dedupe_prefers_platform_parser_rows(self):
        sys.path.insert(0, SCRIPTS)
        import compare
        a = dict(synth.row("C1.init.total", "ms", [1.0, 2.0, 3.0], "2.2.0", rnd=1, pos=0), origin="bench-result")
        b = dict(synth.row("C1.init.total", "ms", [1.5, 2.5, 3.5], "2.2.0", rnd=1, pos=0), origin="platform")
        c = dict(synth.row("C1.init.total", "ms", [1.0, 2.0, 3.0], "2.2.0", rnd=2, pos=1), origin="bench-result")
        out = compare.dedupe_cells([a, b, c])
        self.assertEqual(len(out), 2)
        self.assertIs(out[0], b, "the platform parser's row wins even when it comes second")
        self.assertIs(out[1], c)
        # rows written before `origin` existed: the platform note still identifies them
        legacy_bench = synth.row("C1.init.total", "ms", [1.0] * 12, "2.1.0", rnd=1, pos=0)
        legacy_xc = dict(synth.row("C1.init.total", "ms", [1.0] * 10, "2.1.0", rnd=1, pos=0), notes="xcresult LaunchTests/testLaunch bt.init")
        self.assertIs(compare.dedupe_cells([legacy_bench, legacy_xc])[0], legacy_xc)

    def test_dedupe_never_merges_different_runs(self):
        sys.path.insert(0, SCRIPTS)
        import compare
        a = synth.row("A4.send.e2e_ms", "ms", [5.0, 5.1, 4.9], "3.14.0", rnd=1, pos=0)
        b = dict(synth.row("A4.send.e2e_ms", "ms", [5.2, 5.3, 5.1], "3.14.0", rnd=1, pos=0), run={"id": "other-run", "ts": "2026-10-01T00:00:00Z"})
        self.assertEqual(len(compare.clean_rows([a, b])), 2, "a results directory with two runs of one version keeps both")

    def test_round_zero_rows_are_dropped_next_to_real_rounds(self):
        sys.path.insert(0, SCRIPTS)
        import compare
        rounds = synth.timing_rows("A1.init.total", "ms", 20.0, "3.14.0", "sdk", rounds=3)
        macro = synth.row("A1.init.total", "ms", [40.0] * 10, "3.14.0", rnd=0, pos=0)
        other = synth.row("A2.ttid", "ms", [300.0] * 10, "3.14.0", rnd=0, pos=0)
        out = compare.drop_unrounded(rounds + [macro, other])
        self.assertEqual(len(out), 4)
        self.assertNotIn(macro, out)
        self.assertIn(other, out, "a metric that only has round-0 rows keeps them")

    def test_filter_rows_keeps_only_matching_metrics(self):
        d = tempfile.mkdtemp()
        rows = [synth.row("A1.init.total", "ms", [1.0], "3.14.0"), synth.row("A2.ttid", "ms", [300.0], "3.14.0"), synth.row("A2.ttfd", "ms", [310.0], "3.14.0")]
        synth.write(os.path.join(d, "rows.jsonl"), rows)
        r = run([os.path.join(SCRIPTS, "filter_rows.py"), "--keep", "A2.*", os.path.join(d, "rows.jsonl")])
        self.assertEqual(r.returncode, 0, r.stderr)
        kept = [json.loads(l)["metric"] for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(kept, ["A2.ttid", "A2.ttfd"])


class LaneReportTests(unittest.TestCase):
    def test_lane_failures_lead_the_comment(self):
        out = tempfile.mkdtemp()
        os.makedirs(os.path.join(out, "rows"))
        os.makedirs(os.path.join(out, "report"))
        rows = synth.timing_rows("A4.send.e2e_ms", "ms", 5.0, "3.13.0", "sdk", seed=1) + synth.timing_rows("A4.send.e2e_ms", "ms", 5.0, "3.14.0", "sdk", seed=2)
        synth.write(os.path.join(out, "rows", "micro.jsonl"), rows)
        open(os.path.join(out, "report", "lane-failures.md"), "w").write("- `android macro 3.14.0 (sdk, default)`: exit code 1 after 2 attempts\n")
        r = subprocess.run(["bash", os.path.join(SCRIPTS, "ci", "lane_report_pr.sh"), "android", "3.13.0", "3.14.0", out],
                           capture_output=True, text=True, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        md = open(os.path.join(out, "report", "pr-comment.md")).read()
        self.assertTrue(md.startswith("### Lane failures"), md[:200])
        self.assertIn("android macro 3.14.0", md)
        self.assertIn("A4.send.e2e_ms", md)
        self.assertIn("### Lane failures", r.stdout)

if __name__ == "__main__":
    unittest.main()
