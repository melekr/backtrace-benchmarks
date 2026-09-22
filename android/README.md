# Android module

Gradle project that builds a plain app and an SDK app around a published `backtrace-library` version, plus a
Microbenchmark module (report path, breadcrumbs) and a Macrobenchmark module (cold start with init trace sections).

## Layout

| Path | Purpose |
|---|---|
| `app-plain/` | baseline app: one Activity, same dependencies (AppCompat, MockWebServer, profileinstaller), writes a plain `bench-result.json` |
| `app-sdk/` | same app plus the SDK init sequence in `BenchInit` (client, native, metrics, ANR, breadcrumbs) with `android.os.Trace` sections `bt.init.<stage>` and monotonic timers; writes `files/bench-result.json` and mirrors it to `Android/media/<appId>/` |
| `app-sdk/src/bt_ge_3_14`, `bt_lt_3_14`, `bt_ge_3_13`, `bt_lt_3_13` | compile-time adapters for the two public signatures that changed along the ladder (`tryEnableNativeIntegration`, `enableBreadcrumbs(Context, Level)`) |
| `microbenchmark/` | `BenchmarkRule` tests: `send()` end-to-end and caller-thread, `addBreadcrumb` with/without native; writes `benchmarkData.json` and `bench-result-micro.json` |
| `macrobenchmark/` | `MacrobenchmarkRule` cold start of any installed identity (`bt.package`), `StartupTimingMetric` + one `TraceSectionMetric` per init stage; echoes `benchmarkData.json` to logcat in 2000-char chunks for device farms |
| `scripts/bench_android.sh` | module driver (`prepare`, `build`, `install`, `run --metric-set init|micro|macro`, `size`, `clean`) |
| `scripts/benchmarkdata_to_rows.py` | `*-benchmarkData.json` (micro and macro) to result rows |
| `scripts/size_rows.py` | A3 rows: APK bytes, per-ABI `.so`, DEX references, bundletool install size per device spec |
| `scripts/logcat_chunks_to_json.py` | rebuilds `benchmarkData.json` from a device log |
| `scripts/gen_fixture.py` | 10k-entry asset fixture for the `largeapk` scenario |

## Cell selection

Everything is a Gradle property: `-PbtVersion=3.13.0` (Maven Central, or `local-…` from `mavenLocal` with
`-PbtSource=local`), `-PbtVariant=plain|sdk|sentinel`, `-PbtScenario=default|largeapk|diag`,
`-PbtFixtureAssets=<dir>`. The application id is `io.backtrace.bench.<variant>.v<version with _>` so every cell
installs side by side and keeps its own on-disk state. `./gradlew btPrintCell -PbtVersion=3.8.4` prints the resolved cell.

## Local run

```bash
export ANDROID_HOME=$HOME/Library/Android/sdk
android/scripts/bench_android.sh build   --version 3.14.0 --variant sdk --with-tests
android/scripts/bench_android.sh build   --version 3.14.0 --variant plain
android/scripts/bench_android.sh install --version 3.14.0 --variant sdk --with-tests --serial emulator-5554
android/scripts/bench_android.sh run --metric-set init  --version 3.14.0 --variant sdk --iterations 15 --serial emulator-5554 --out out/android/3.14.0/sdk/default/round-0/pos-0
android/scripts/bench_android.sh run --metric-set micro --version 3.14.0 --variant sdk --serial emulator-5554 --out out/android/3.14.0/sdk/default/micro
android/scripts/bench_android.sh run --metric-set macro --version 3.14.0 --variant sdk --iterations 15 --serial emulator-5554 --out out/android/3.14.0/sdk/default/macro
android/scripts/bench_android.sh size --version 3.14.0 --variant sdk --env env.json --out out/android/size
python3 scripts/parse_bench_result.py out/android/3.14.0/sdk/default/round-0/pos-0 --sdk android --sdk-version 3.14.0 --variant sdk --expect-mock-requests 2 --env env.json --out rows.jsonl
python3 android/scripts/benchmarkdata_to_rows.py out/android/3.14.0/sdk/default/macro --sdk-version 3.14.0 --variant sdk --env env.json --out rows-macro.jsonl
```

The interleaved multi-variant runs are driven by `scripts/run_ab_rounds.sh` and, in CI, by `scripts/ci/lane_android.sh`.

## Hermeticity

The SDK app starts an in-process `MockWebServer` on 127.0.0.1 and points the submission URL and the metrics base
URL at it (`BenchCredentials` overrides the universe/token the SDK derives from the URL). The mock counts requests and
the result file records `mock_requests` (a full init sends exactly the two metrics startup events). The
microbenchmarks use `setOnRequestHandler`, so no socket is opened at all. The SDK logger is off except in scenario
`diag`, where the SDK's own `… took X milliseconds` lines become available in logcat.

## Verified locally (2026-09-22)

- `assembleRelease` of `app-plain` and `app-sdk` against 3.14.0, 3.13.0 and 3.8.4 (adapters select correctly).
- `microbenchmark:assembleReleaseAndroidTest` and `macrobenchmark:assembleBenchmark` against 3.14.0.
- Cold-start lane on a local arm64 API 36 emulator (`Pixel_9_-_16kb`), 5 launches of the SDK app at 3.14.0: every launch
  produced `bench-result.json`, the mock received exactly the two metrics startup events, and the parser emitted 7 valid
  rows. Medians: client 19.9 ms, native 1.9 ms, metrics 5.3 ms, ANR 0.06 ms, breadcrumbs 6.1 ms, total 31.7 ms
  (single launches ranged 17–81 ms, which is why CI runs 15 launches × 3 interleaved rounds with a sentinel).
- Micro lane on the same emulator (`connectedReleaseAndroidTest`, 50 measurements): `send()` end-to-end 2.45 ms and
  caller-thread 2.47 ms with about 13.7k allocations per send; `addBreadcrumb` 1.19 ms with 46 allocations (native on or off).
  `/proc/self/io` is not readable on this emulator, so the bytes-written samples were absent.
- Macro lane on the same emulator (`connectedBenchmarkAndroidTest`, `CompilationMode.Full`, 5 cold starts): passes;
  `timeToInitialDisplay` 358 ms median, init trace sections total 40.7 ms (client 22.6, breadcrumbs 10.1, metrics 7.6,
  native 2.9, ANR 0.1 ms); the `benchmarkData.json` was also recovered from the logcat chunk echo (4 chunks). With only
  five iterations the coefficient of variation is high (0.3–0.6), which is why CI uses 15 iterations × 3 rounds.
- bundletool install sizes (`size` subcommand) are wired but were not executed in this session.
