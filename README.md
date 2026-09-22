# Backtrace SDK Benchmarks

Continuous, release-over-release performance benchmarks for the Backtrace client SDKs:

- [backtrace-android](https://github.com/backtrace-labs/backtrace-android) (Maven Central `backtrace-library`)
- [backtrace-cocoa](https://github.com/backtrace-labs/backtrace-cocoa) (SwiftPM, CocoaPods, XCFramework archives)
- [backtrace-unity](https://github.com/backtrace-labs/backtrace-unity) (OpenUPM `io.backtrace.unity`)

The harness runs in GitHub Actions, consumes **published** SDK versions so any past release can be measured, and reports
plain-vs-SDK overhead and version-vs-version deltas with confidence intervals and an in-job noise floor.

## What is measured

| Area | Android | iOS / macOS | Unity |
|---|---|---|---|
| Size added by the SDK | AAR, per-ABI `.so`, install size per device spec, DEX method refs | XCFramework slices, `.app` binary/bundle/zip | UPM natives per platform, player size |
| Main-thread init cost | per stage (client, native, metrics, ANR, breadcrumbs) | per stage (client, breadcrumbs, …) | `Initialize`/`Refresh` (editor) |
| Report path | `send()` end-to-end and caller-thread, allocations, bytes written | `send()` clock/CPU/memory | `Send()` to completion, GC bytes, JSON |
| Breadcrumbs / logging | add latency, bytes per 1k | add latency vs retained count | per-`Debug.Log` cost |
| Cold start (informational) | TTID/TTFD plain vs SDK | launch time plain vs SDK | player cold start |
| Steady state, crash path | SDK-thread CPU, timers, dump/upload latency | timer wakeups, ingestion latency | dump/upload latency |

Full catalogue: [`schema/metrics.yml`](schema/metrics.yml). Gate policy: [`thresholds.yml`](thresholds.yml). Contract: [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

## Quick start (no device, no licence)

```bash
python3 scripts/fetch_artifacts.py --sdk all --out artifacts --results out/tier0 --markdown out/tier0/TIER0.md
python3 scripts/compare.py ladder --results out/tier0 --sdk android --ladder 3.8.4,3.9.0,3.10.6,3.11.0,3.13.0,3.14.0 --format md
python3 -m unittest discover -s scripts/tests            # harness self-tests (13 tests)
```

This downloads the published artifacts (about 290 MB, cached under `artifacts/`) and prints the multi-version size
tables; the first report produced this way is in [`docs/reports/tier0-2026-09-22.md`](docs/reports/tier0-2026-09-22.md).
`scripts/requirements.txt` lists optional packages (`pyyaml`, `jsonschema`); every script falls back to the standard library.

## Running a timing lane locally

| Lane | Command | Needs |
|---|---|---|
| Android cold start | `android/scripts/bench_android.sh build --version 3.14.0 --variant sdk --with-tests && … install … && … run --metric-set init --iterations 15 --out out/a` | Android SDK, a booted emulator (`ANDROID_HOME`) |
| Android micro / macro | `… run --metric-set micro` / `… run --metric-set macro` | same |
| Apple in-process | `apple/scripts/bench_apple.sh prepare --source spm --version 2.2.0 && … build --variant sdk && … run --metric-set micro --version 2.2.0 --variant sdk --out out/c` | Xcode, XcodeGen (`brew install xcodegen`), an iOS simulator |
| Unity editor | `unity/scripts/bench_unity.sh prepare --version 3.17.0 --editor 6000.3.14f1 && … run --metric-set micro --editor 6000.3.14f1 --out out/u` | a licensed Unity editor |
| Interleaved multi-version rounds | `scripts/run_ab_rounds.sh --sdk android --driver android/scripts/bench_android.sh --parser android/scripts/benchmarkdata_to_rows.py --versions 3.13.0,3.14.0 --plain --sentinel --rounds 3 --iterations 15 --metric-set init --out out/rounds` | as above |

Every lane writes raw files under `out/…`, the parsers turn them into rows (`schema/result.schema.json`), and
`scripts/compare.py pr|ladder|overhead` renders the comparison. Module details: [`android/README.md`](android/README.md),
[`apple/README.md`](apple/README.md), [`unity/README.md`](unity/README.md). Secrets for the optional lanes: [`docs/SECRETS.md`](docs/SECRETS.md).

## State of verification (2026-09-22, local machine)

| Piece | Verified |
|---|---|
| Tier-0 size ladders, all three SDKs, full backfill windows | yes, 338 rows validate; AAR bytes match Maven Central |
| Android: plain + SDK apps build against 3.14.0, 3.13.0, 3.8.4; micro/macro test APKs build | yes |
| Android: cold-start, micro and Macrobenchmark lanes on a local arm64 API 36 emulator; the full `lane_android.sh` (plain + 3.13.0 + 3.14.0 + sentinel interleaved round, report with noise floor) verified under Bash 3.2 | yes, rows validate |
| Apple: SwiftPM and XCFramework consumption both build; in-process benchmarks (6 tests) and the launch lane run; the full `lane_apple.sh` (plain + versions + sentinel, size/init/micro, report) verified under Bash 3.2 | yes |
| Unity: packages resolve on Unity 6 (performance package 3.5.0); all 9 PlayMode benchmarks pass and convert to rows | yes |
| Harness self-tests (thresholds, rows, gates, parser, fingerprint) | 13 pass |
| GitHub Actions, first runs (2026-09-22) | `bench-tier0-size` and `probe` passed; `bench-android` and `bench-apple` failed on harness bugs fixed the same day (Bash 3.2 empty-array expansions on macOS runners, a fatal parser call on cold-start directories, and `xcframework` mode not vendoring the release archive). Probe result: Cocoa 2.1.0 and 2.2.0 build from SwiftPM on both Xcode 16 (`macos-15`) and Xcode 26 (`macos-26`); Android 3.13.0 and 3.14.0 resolve on AGP 8.13 |

## Layout

See [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) §2. Each of `android/`, `apple/`, `unity/` has its own README with build and run instructions.

## Workflows

| Workflow | Purpose |
|---|---|
| `bench-tier0-size.yml` | size ladders from published artifacts |
| `probe.yml` | which SDK version × toolchain cells build |
| `bench-android.yml`, `bench-apple.yml`, `bench-unity.yml` | timing and integrated-size lanes on GitHub-hosted runners |
| `bench-release-report.yml` | chains ladder jobs, renders `REPORT.md`, updates `results` and `gh-pages` |
| `bench-sauce.yml` | optional real-device lane (Sauce Labs), numbers only |

## Results

Rows are JSON (`schema/result.schema.json`) on the `results` branch; reports are Markdown with ratios normalized to the oldest
version of each ladder. Every table states the environment fingerprint and the sentinel noise floor of the job that produced it.
