import XCTest

#if BT_SDK
import Backtrace

/// C5: addBreadcrumb latency at a retained-count level, plus the breadcrumb file size.
///
/// Each test clears the trail, pre-fills N crumbs, then measures one addBreadcrumb per iteration.
/// The retained count therefore drifts from N to N + iterations during the measurement; with the
/// default 64 KiB file cap the trail saturates around a few hundred crumbs, so `retained_1000`
/// measures the steady state at the cap (documented in apple/README.md).
final class BreadcrumbTests: XCTestCase {
    private var host: BenchTestHost!

    override func setUpWithError() throws {
        continueAfterFailure = true
        host = BenchTestHost.shared
        try XCTSkipIf(host.client == nil, "BacktraceClient failed to initialize: \(host.harness.errors)")
    }

    private func measureRetained(_ retained: Int) {
        let client = host.client!
        _ = client.clearBreadcrumbs()
        for index in 0..<retained {
            _ = client.addBreadcrumb("prefill \(index) lorem ipsum dolor sit amet", attributes: ["i": "\(index)"])
        }
        let options = XCTMeasureOptions()
        options.iterationCount = BenchConfig.iterations(default: 30)
        var samples: [Double] = []
        var rejected = 0
        measure(metrics: [XCTClockMetric()], options: options) {
            let start = BenchClock.now()
            let accepted = client.addBreadcrumb("bench crumb lorem ipsum dolor sit amet", attributes: ["k": "v"])
            samples.append(BenchClock.microseconds(from: start, to: BenchClock.now()))
            if !accepted { rejected += 1 }
        }
        XCTAssertEqual(rejected, 0, "addBreadcrumb returned false \(rejected) times")
        host.record(metric: "C5.breadcrumb.add_us.retained_\(retained)", samples: Array(samples.dropFirst()))
        if let size = BenchProcess.fileSize(at: BenchTestHost.breadcrumbFileURL) {
            host.counter("C5.breadcrumb.file_bytes.retained_\(retained)", Double(size))
            host.counter("breadcrumb_file_bytes", Double(size))
        }
    }

    func testAddBreadcrumbRetained10() { measureRetained(10) }
    func testAddBreadcrumbRetained100() { measureRetained(100) }
    func testAddBreadcrumbRetained1000() { measureRetained(1000) }
}
#endif
