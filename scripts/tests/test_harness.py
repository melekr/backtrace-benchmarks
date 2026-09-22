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
        r, _ = self._pr(10.0, 8.0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

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
