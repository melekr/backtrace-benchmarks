# Unity module

A committed minimal Unity project whose `Packages/manifest.json` is rendered per cell (SDK version from the OpenUPM
scoped registry or `file:` for a local checkout, Test Framework and Performance Testing package pinned per editor).
Benchmarks are PlayMode tests in `Assets/Benchmarks` (assembly `BacktraceBench.Runtime`, referencing `Backtrace.Unity`
and `Unity.PerformanceTesting`).

## Layout

| Path | Purpose |
|---|---|
| `manifest.json.tmpl`, `scripts/render_manifest.py` | render `Packages/manifest.json` and `ProjectSettings/ProjectVersion.txt`; the `plain` variant omits the SDK and hides `Assets/Benchmarks` (renamed to `Benchmarks~`) |
| `project/Assets/Benchmarks/BenchHarness.cs` | configuration factory (loopback URL so metrics self-disable, `ReportPerMin` 100000, fresh database dir), request-handler stub with a request counter, `DestroyImmediate` helper |
| `U1InitBenchmarks.cs` | `Initialize()` wall time and allocated bytes, one live client per measurement |
| `U2SendBenchmarks.cs` | `Send()` wall-to-stub over frames, allocated bytes, `BacktraceData.ToJson()` |
| `U3LogBenchmarks.cs` | per-`Debug.Log` cost with capture, with and without breadcrumbs |
| `U5DatabaseBenchmarks.cs` | breadcrumb append, `Database.Reload()` with 0/8/100 records |
| `BenchResultWriter.cs` | writes `bench-result-<test>.json` (per-iteration samples keyed by metric id) to `-btBenchOut` |
| `project/Assets/Editor/BenchBuild.cs` | `-executeMethod` player builds for the size lane (Android IL2CPP arm64+x86_64, iOS export) |
| `scripts/bench_unity.sh` | driver (`prepare`, `run --metric-set micro`, `size`, `clean`); finds the editor via `--editor-path`, `$UNITY_BIN`, the Hub path or `unity-editor` |
| `scripts/perf_results_to_rows.py` | `PerformanceTestResults.json` sample groups (named by metric id) to result rows |

## Local run

```bash
unity/scripts/bench_unity.sh prepare --version 3.17.0 --editor 6000.3.14f1 --variant sdk
unity/scripts/bench_unity.sh run --metric-set micro --editor 6000.3.14f1 --variant sdk --out out/unity/3.17.0
python3 unity/scripts/perf_results_to_rows.py out/unity/3.17.0/PerformanceTestResults.json --sdk-version 3.17.0 --variant sdk --env env.json --out rows.jsonl
python3 scripts/parse_bench_result.py out/unity/3.17.0 --sdk unity --sdk-version 3.17.0 --source openupm --variant sdk --env env.json --out rows-app.jsonl
```

Editor PlayMode timings are informational (headless editor, Mono JIT, no native client); allocated-bytes metrics are
deterministic and gate. In CI the test action runs the tests; the driver renders the project and builds players.

## Verified locally (2026-09-22)

- Package resolution on Unity 6000.5.10f1: `io.backtrace.unity` 3.17.0, `com.unity.test-framework.performance` 3.5.0,
  `com.unity.test-framework` 1.7.0 (the 1.6.0 request was upgraded by the editor).
- All 9 PlayMode benchmarks pass on 6000.5.10f1 against io.backtrace.unity 3.17.0 (editor, `-nographics`): `Initialize`
  0.20 ms and about 1.6 MB allocated; `Send()` to the stub 0.97 ms and about 68 KB; `ToJson` 0.02 ms; a captured
  `Debug.Log` 0.45 ms (4.2 ms with breadcrumbs enabled, i.e. one file append per log); breadcrumb `Info()` 3.8 ms;
  `Database.Reload()` 0.02 ms regardless of 0/8/100 records. Both parsers produce valid rows from the run.
- `GC.GetAllocatedBytesForCurrentThread()` returns 0 under Unity's Mono; the harness falls back to the Mono heap
  "used" size after a forced collection, so allocation numbers are approximate.
