"""Shell scripts must run under macOS /bin/bash 3.2 (GitHub macOS runners execute them with it)."""
import glob
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = sorted(glob.glob(os.path.join(REPO, p)) for p in ("scripts/*.sh", "scripts/ci/*.sh", "android/scripts/*.sh", "apple/scripts/*.sh", "unity/scripts/*.sh"))
SCRIPTS = [s for group in SCRIPTS for s in group]
BASH32 = "/bin/bash" if sys.platform == "darwin" and os.path.exists("/bin/bash") else None


class ShellCompatTests(unittest.TestCase):
    def test_no_bash4_only_constructs(self):
        offenders = []
        for path in SCRIPTS:
            text = open(path, encoding="utf-8").read()
            for token in ("declare -A", "mapfile", "readarray", "local -n"):
                if token in text:
                    offenders.append("%s uses %s" % (os.path.relpath(path, REPO), token))
        self.assertEqual(offenders, [], "Bash 4-only constructs break macOS runners")

    @unittest.skipUnless(BASH32, "macOS /bin/bash (3.2) not available")
    def test_syntax_under_bash32(self):
        for path in SCRIPTS:
            r = subprocess.run([BASH32, "-n", path], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "%s: %s" % (path, r.stderr))

    @unittest.skipUnless(BASH32, "macOS /bin/bash (3.2) not available")
    def test_round_orchestrator_dry_run_under_bash32(self):
        out = tempfile.mkdtemp()
        for sdk, driver in (("apple", "apple/scripts/bench_apple.sh"), ("android", "android/scripts/bench_android.sh")):
            r = subprocess.run([BASH32, os.path.join(REPO, "scripts/run_ab_rounds.sh"), "--sdk", sdk, "--driver", os.path.join(REPO, driver),
                                "--versions", "1.0.0,1.0.1", "--plain", "--sentinel", "--rounds", "2", "--iterations", "3",
                                "--metric-set", "init", "--expect-mock-requests", "2", "--out", os.path.join(out, sdk), "--dry-run"],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("dry run complete: 4 variants x 2 rounds", r.stderr + r.stdout)
            self.assertIn("--expect-mock-requests DRY: 0", r.stdout, "plain variant must expect zero mock requests")
        env = os.path.join(out, "env.json")
        open(env, "w").write("{}")
        r = subprocess.run([BASH32, os.path.join(REPO, "scripts/run_ab_rounds.sh"), "--sdk", "apple", "--driver", os.path.join(REPO, "apple/scripts/bench_apple.sh"),
                            "--versions", "1.0.0", "--rounds", "1", "--metric-set", "init", "--env", env, "--out", os.path.join(out, "envtest"), "--dry-run"],
                           capture_output=True, text=True, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DRY: cp " + env, r.stdout, "--env must be reused instead of generating a new fingerprint")


    @unittest.skipUnless(BASH32, "macOS /bin/bash (3.2) not available")
    def test_lane_common_retries_and_records_under_bash32(self):
        out = tempfile.mkdtemp()
        script = (
            'set -euo pipefail; OUT="$1"; . "$2"; n=0; flaky() { n=$((n+1)); [ "$n" -ge 2 ]; }; '
            'run_with_retry "flaky pass" flaky && echo "flaky ok after $n"; '
            'if run_with_retry "broken pass" false; then echo "unexpected"; fi; '
            'echo "continued"; finish_lane'
        )
        r = subprocess.run([BASH32, "-c", script, "bash", out, os.path.join(REPO, "scripts/ci/lane_common.sh")], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("flaky ok after 2", r.stdout)
        self.assertIn("continued", r.stdout, "a failed pass must not abort the remaining passes")
        failures = open(os.path.join(out, "report", "lane-failures.md")).read()
        self.assertIn("broken pass", failures)
        self.assertNotIn("flaky pass", failures)


if __name__ == "__main__":
    unittest.main()
