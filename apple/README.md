# Apple module

XcodeGen-generated project with three app targets (`BenchApp-plain`, `BenchApp-sdk`, `BenchApp-sentinel`), a UI test
bundle per app (launch metric + init signpost) and one unit test bundle hosted by the SDK app (report path, breadcrumbs,
counters). The SDK is consumed from the published XCFramework archive (retro rows), from SwiftPM by exact tag, or from a
local checkout.

## Layout

| Path | Purpose |
|---|---|
| `project.yml.tmpl` | XcodeGen spec template; rendered to `project.yml` (gitignored) by `scripts/render_project.py --source xcframework|spm|local --version V` |
| `BenchApp/` | app sources; `BenchLaunch`/`BenchSDKHarness` run the staged init (`client`, `attributes`, `breadcrumbs`) inside `os_signpost` intervals and write `Documents/bt-bench-stages.json`; `BenchStub` is the 127.0.0.1 HTTP stub (`Content-Length` and chunked bodies, `Expect: 100-continue`, 30 s idle timeout, graceful close); compile conditions `BT_SDK`, `BT_GE_2_1`, `BT_GE_2_2` select code per version |
| `BenchAppUITests/` | `XCTApplicationLaunchMetric` + `XCTOSSignpostMetric` around `XCUIApplication().launch()`; iterations from `BT_ITERATIONS` |
| `BenchUnitTests/` | in-process `measure()` with clock/CPU/memory metrics: `send(error)` end-to-end and caller-thread, `addBreadcrumb` at 10/100/1000 retained crumbs, thread counters; also writes `Documents/bench-result.json` with per-iteration samples |
| `scripts/bench_apple.sh` | driver (`prepare`, `build`, `install`, `run --metric-set init|micro`, `size`, `clean`); exit 4 when a version does not build on the current Xcode |
| `scripts/xcresult_to_rows.py` | `xcrun xcresulttool get test-results metrics` (Xcode 16+) to result rows |
| `scripts/fetch_xcframework.py` | downloads and extracts `Archive_XCFrameworks_<version>.tar.gz` into `Vendor/<version>/` |

## Local run

```bash
apple/scripts/bench_apple.sh prepare --source spm --version 2.2.0          # or --source xcframework
apple/scripts/bench_apple.sh build --variant sdk                            # Release, unsigned, iOS Simulator
apple/scripts/bench_apple.sh run --metric-set micro --version 2.2.0 --variant sdk --out out/apple/2.2.0/sdk/micro
apple/scripts/bench_apple.sh run --metric-set init  --version 2.2.0 --variant sdk --iterations 10 --out out/apple/2.2.0/sdk/default/round-0/pos-0
apple/scripts/bench_apple.sh size --version 2.2.0 --variant sdk --out out/apple/size
python3 apple/scripts/xcresult_to_rows.py out/apple/2.2.0/sdk/micro/micro.xcresult --sdk-version 2.2.0 --variant sdk --source spm --env env.json --out rows.jsonl
```

`allowsAttachingDebugger` is set to true (XCTest hosts are traced, otherwise the SDK never enables its reporter),
`reportsPerMin` is 100000 (zero means unlimited only since 2.2.0), the stub is reached over plain HTTP with an ATS
local-networking exception, and metrics are never enabled in the default lanes (their endpoint is not configurable).

## Verified locally (2026-09-22, Xcode 27.0, iOS 26.5 simulator)

- Render + `xcodegen generate` for SwiftPM `exact: 2.2.0`; `build-for-testing` of `BenchApp-sdk` in Release.
- `BenchUnitTests`: 6 tests passed; `send()` caller-thread ≈ 510 ms and end-to-end ≈ 533 ms medians (simulator),
  `addBreadcrumb` ≈ 0.30 ms at 10 retained crumbs and ≈ 0.56 ms at 1000; the stub counted one request per send;
  `xcresult_to_rows.py` produced 7 valid rows.
- Launch lane (`BenchAppUITests`, 10 launches): `XCTApplicationLaunchMetric` 1252 ms median on the simulator and the
  `bt.init` signpost 56.8 ms median, consistent with the app's own per-launch stage files (client 51–60 ms, attributes
  about 0.9 ms, breadcrumbs about 2 ms).
- Full lane (`scripts/ci/lane_apple.sh all` + `report`, XCFramework mode, plain + 2.2.0 + sentinel, 3 launches): plain-vs-SDK
  overhead on the simulator: cold launch +45 ms (+3.9 %), init 58 ms, `.app` bundle +1.64 MB (+22 KB main binary, the rest is
  the embedded framework), zip +495 KB, +1 thread. XCFramework-built binaries measure slower than SwiftPM-built ones
  (breadcrumb add 0.43 ms vs 0.30 ms), so a ladder must use one consumption mode throughout. The signed thinning lane is
  wired but was not executed.
