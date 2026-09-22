# Harness conventions (the contract between modules, scripts and workflows)

This document is normative. Module drivers, parsers, `compare.py` and the GitHub workflows are written against it.

## 1. Ground rules

- **Published artifacts for retro rows.** A benchmark row for a released SDK version is built from the published artifact (Maven Central AAR, GitHub Release XCFramework archive or SwiftPM tag, OpenUPM tarball), never from a rebuilt checkout. `source=local` exists only for HEAD/PR builds and publishes the SDK checkout to a local repository with the SDK's own toolchain.
- **In-job comparisons only.** Every timing comparison is between variants built, installed and run in the same job, interleaved. Stored results feed reports and trend charts, never gates.
- **Hermetic.** No benchmark process may reach a production endpoint. Every lane runs against an in-process or on-runner mock server, or a request-handler stub, and asserts the number of requests the mock received.
- **Deterministic before statistical.** Prefer byte counts, allocation counts, thread and timer counts. Time is compared with paired medians and bootstrap confidence intervals.
- **Automation never commits or pushes.** Scripts and agents write files; humans commit. Workflows write to the `results` and `gh-pages` branches only from `bench-release-report.yml`.
- **Pinned everything.** Runner images by version (`ubuntu-24.04`, `macos-26`), actions by SHA, tools by version; never `latest`.

## 2. Layout

```
schema/            result.schema.json, bench-result.schema.json, metrics.yml
thresholds.yml     gate policy
scripts/           shared Python/shell: fetch_artifacts.py, stats.py, compare.py, parsers, run_ab_rounds.sh, env_fingerprint.sh, probe_buildability.sh, thresholds.py, tests/
android/           Gradle project: app-plain, app-sdk, microbenchmark, macrobenchmark; scripts/bench_android.sh
apple/             XcodeGen project.yml, BenchApp, BenchAppUITests, BenchUnitTests, Package.swift.tmpl; scripts/bench_apple.sh
unity/             project/ (committed minimal Unity project; benchmarks in assembly BacktraceBench.Runtime), manifest.json.tmpl; scripts/bench_unity.sh
.github/workflows/ probe.yml, bench-tier0-size.yml, bench-android.yml, bench-apple.yml, bench-unity.yml, bench-release-report.yml, bench-sauce.yml
results/           (on the `results` branch) results/<sdk>/<platform>/<version>/<run-id>.jsonl and REPORT.md
docs/              this file, per-metric notes
```

## 3. Versions under test

| SDK | Retro ladder (oldest → newest) | Consumption | HEAD/PR |
|---|---|---|---|
| android | 3.8.4, 3.9.0, 3.10.6, 3.11.0, 3.13.0, 3.14.0 | Maven Central `com.github.backtrace-labs.backtrace-android:backtrace-library:<ver>` | `source=local`: `./gradlew :backtrace-library:publishToMavenLocal -PVERSION_NAME=local-SNAPSHOT` in the SDK checkout (needs `fetch-depth: 0` and submodules), then `-PbtVersion=local-SNAPSHOT` |
| apple | 2.0.6, 2.0.9, 2.1.0, 2.2.0 | `source=xcframework`: `Archive_XCFrameworks_<ver>.tar.gz` from the GitHub Release (default for retro rows); `source=spm`: `.package(url:…, exact:)` | `source=spm` with `.package(path:)` |
| unity | 3.13.0, 3.14.1, 3.15.1, 3.16.2, 3.17.0 | OpenUPM scoped registry `"io.backtrace.unity": "<ver>"` (tarball `https://package.openupm.com/io.backtrace.unity/-/io.backtrace.unity-<ver>.tgz`) | `"io.backtrace.unity": "file:<path>"` |

Pre-release tags are excluded from ladders.

## 4. Toolchain pins

- Android harness: AGP `8.13.2`, Gradle `8.14.5` (wrapper committed), JDK 17, `compileSdk 36`, `minSdk 21`, `targetSdk 36`, `androidx.benchmark` `1.4.1` (`benchmark-junit4`, `benchmark-macro-junit4`), `androidx.profileinstaller` `1.4.1`, `com.squareup.okhttp3:mockwebserver` `4.12.0`, bundletool `1.18.3` (downloaded, sha256-verified), emulator image `system-images;android-34;google_apis;x86_64`. The harness never composite-builds the SDK repo.
- Apple harness: XcodeGen project, iOS deployment target 15.0, Release configuration, iOS Simulator destination; CI default runner `macos-26` (Xcode 26.x); `macos-15` (Xcode 16.x) only for retro cells the probe marks unsupported on 26.x. Per-version bundle ids.
- Unity harness: committed minimal project, `com.unity.test-framework` per editor (`1.4.6` on 2021.3/2022.3, `1.6.0` on 6000.x), `com.unity.test-framework.performance` `3.5.0` (fallback `3.0.3` where 3.5.0 does not resolve). CI editors `2021.3.56f2`, `2022.3.56f1`, `6000.3.7f1`; PlayMode `-batchmode -nographics`.

## 5. Variants, scenarios, identities

- `variant`: `plain` (no SDK), `sdk` (SDK at the requested version), `sentinel` (the newest version of the ladder installed a second time under its own identity; its self-vs-self delta is the job noise floor).
- `scenario`: `default`, `largeapk` (10k-entry asset fixture, Android), `diag` (SDK debug logging on, Android), `seeded-<N>` (N pending records in the offline store), `idle`, `busy`.
- Identities: Android `applicationId = io.backtrace.bench.<variant>.v<version with . and - replaced by _>`; Apple `PRODUCT_BUNDLE_IDENTIFIER = io.backtrace.bench.<variant>.v<…>`; Unity `productName = BacktraceBench-<variant>-<version>` and every run uses a fresh database directory. Never erase a device between rounds; identities keep on-disk state separate.

## 6. bench-result.json (written by the apps)

Schema: `schema/bench-result.schema.json`. One file per launch/run. Location: Android `files/bench-result.json` (pulled with `adb exec-out run-as <appId> cat files/bench-result.json`), Apple `Documents/bt-bench-stages.json` (pulled from `xcrun simctl get_app_container booted <bundleId> data`), Unity `<persistentDataPath>/bench-result-<test>.json` or the directory passed with `-btBenchOut` (drivers pass absolute paths: the editor resolves relative paths against the project directory). Stage names: Android `client, native, metrics, anr, breadcrumbs`; Apple `client, breadcrumbs` (plus `repository, pendingCrash, crashReporter, watcher` when the app can observe them); Unity `initialize, refresh, database, breadcrumbs, metrics`. `counters` must include `mock_requests` and `threads_after_init` where the platform can provide them.

## 7. Module driver interface

Each platform ships `<platform>/scripts/bench_<platform>.sh`. Common flags: `--version`, `--source`, `--variant`, `--scenario`, `--out DIR`, `--serial|--udid` (device), `--iterations N`, `--round R`, `--position P`, `--local-path DIR` (with `--source local`).

| Subcommand | Effect | Output |
|---|---|---|
| `prepare` | render templates, download artifacts (idempotent, cached under `artifacts/`) | |
| `build` | build the variant/scenario at the version | build products copied to a per-cell directory (Android: `android/build/cells/<appId>-<scenario>/`) so a later build for another version cannot replace them; also under `--out` when given |
| `install` | install on the attached emulator/simulator (no-op for Unity editor lanes) | |
| `run --metric-set init|micro|macro|steady|crash` | execute one measurement pass | raw files under `--out` (see §8) |
| `size` | measure integrated size of already-built products | `rows.jsonl` under `--out` |
| `clean` | remove build products, keep `artifacts/` cache | |

Exit codes: `0` ok, `1` failure, `4` unsupported cell (e.g. tag does not compile on this toolchain). Drivers never print secrets and never contact production hosts.

Sub-lane failures: `scripts/ci/lane_*.sh` (via `lane_common.sh`) retry a failed per-version `micro`/`macro` pass once, record it in `out/<sdk>/report/lane-failures.md`, continue with the remaining cells and exit `1` only after every other pass has run. The report and artifact steps still execute, and the PR comment then starts with a **Lane failures** section explaining which metrics are missing.

## 8. Raw output layout

`out/<sdk>/<version>/<variant>/<scenario>/round-<R>/pos-<P>/` containing platform raw files: `bench-result-<i>.json`, `*-benchmarkData.json`, `*.xcresult/`, `PerformanceTestResults.json`, `logcat.txt`, `stdout.txt`, `env.json`. Platform-specific raw parsers live with their platform and emit `rows.jsonl`: `android/scripts/benchmarkdata_to_rows.py` (micro and macro `*-benchmarkData.json`), `apple/scripts/xcresult_to_rows.py` (`.xcresult`), `unity/scripts/perf_results_to_rows.py` (`PerformanceTestResults.json`). The shared `scripts/parse_bench_result.py` converts `bench-result.json` files from every platform. `size` subcommands and `scripts/fetch_artifacts.py` emit rows directly. For Apple `micro` passes the XCTest metrics from the `.xcresult` are authoritative; `parse_bench_result.py --exclude-metrics 'C1.*' --exclude-metrics-in rows-platform.jsonl` then adds only counters and metrics the xcresult lacks (test-host init stages are not app cold starts and are dropped).

## 9. Result rows

Schema: `schema/result.schema.json`; metric ids and units: `schema/metrics.yml`. Rows are newline-delimited JSON (`rows.jsonl`). `stats.sampleKind` declares what `samples` are (`perLaunch`, `perIteration`, `measurementAverage`, `exact`). A row is `valid: false` when any stage reported `ok: false`, the mock request count did not match, or a rate-limit / debugger-attached status was observed; invalid rows are excluded from statistics and listed in the report.

`env` is produced by `scripts/env_fingerprint.sh` and includes `fingerprint = sha256(sorted(runner, os, nproc, xcode, agp, gradle, jdk, unity, emulator, simulator, device, cpuLocked, tier))`. `compare.py` refuses to compare rows with different fingerprints unless `--allow-mixed-env` is given (report only, never gates).

## 10. Statistics and gates (`thresholds.yml`)

- Per round: `ratio = median_variant(round) / median_anchor(round)`; pooled paired ratios → percentile bootstrap CI (10 000 resamples, 95 %). Verdict `no change` when the CI contains 1.
- Order rotation: variants are launched in a different order every round; `position` is recorded.
- Noise: CoV above the class limit reruns that variant's round once, then the row is `inconclusive`. Sentinel |Δ| above `sentinel_max_rel` marks the job `noisy` and disables gates.
- Gate classes: `det` fail iff Δ ≥ max(rel, abs); `pair` fail iff Δmedian ≥ max(rel, abs) and CI excludes 1; `warn` and `trend` never fail. Exit codes from `compare.py --gate`: `0` pass, `2` gate failed, `3` noisy/inconclusive (only fails with `--strict`).
- Validity asserts are fail-closed: plain-vs-sdk size diff > 0, exact sample counts, exact mock request counts.

## 11. Hermeticity per platform

- Android: `okhttp3.mockwebserver.MockWebServer` bound to `127.0.0.1` inside the app process (the bench apps declare `android:usesCleartextTraffic="true"`, otherwise Android rejects plain HTTP even on loopback); submission URL `http://127.0.0.1:<port>/post?format=json&token=<64 hex>`; metrics via a `BacktraceCredentials` subclass overriding `getUniverseName()`/`getSubmissionToken()` and `BacktraceMetricsSettings(creds, "http://127.0.0.1:<port>/api", 0)`; micro paths use `setOnRequestHandler`; SDK logger `OFF` except scenario `diag`; crash-path lanes use a fixed 50 ms mock latency and subtract it.
- Apple: `NWListener` HTTP stub on `127.0.0.1` in the app/test process: `Content-Length` and chunked bodies, `Expect: 100-continue`, a 30 s idle timeout per connection (counted as incomplete), graceful close after every response (FIN, never a reset); `NSAppTransportSecurity/NSAllowsLocalNetworking = YES`; `allowsAttachingDebugger = true`; `reportsPerMin = 100000`; metrics disabled in default lanes. In-process tests wait through `XCTWaiter` (run loop), never on a semaphore held by the main thread, and record a metric only when every send completed `ok` with exactly one stub request; otherwise the failure lands in `errors` and the pass is reported as failed.
- Unity: `BacktraceClient.RequestHandler` stub for editor lanes; server URL on a non-`backtrace.io` host so metrics self-disable, keeping `format=json` and a 64-character `token=`; `ReportPerMin` set to 100000; player lanes reach the runner mock through `adb reverse tcp:<port> tcp:<port>`.

## 12. Testing the harness itself

`python3 -m unittest discover -s scripts/tests` must pass; drivers have `--dry-run` where a device is needed. Fixtures for parsers live under `scripts/tests/fixtures/`.
