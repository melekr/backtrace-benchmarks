import XCTest

#if BT_SDK
import Backtrace

/// C7 deterministic counters sampled in the test process (threads after the shared init).
final class CounterTests: XCTestCase {
    func testThreadCountAfterInit() throws {
        let host = BenchTestHost.shared
        try XCTSkipIf(host.client == nil, "BacktraceClient failed to initialize: \(host.harness.errors)")
        XCTAssertGreaterThanOrEqual(host.harness.threadsAfterInit, 1)
        host.counter("threads_after_init", Double(host.harness.threadsAfterInit))
        host.counter("threads_before_init", Double(host.harness.threadsBeforeInit))
        host.counter("threads_now", Double(BenchProcess.threadCount()))
        host.counter("mock_requests", Double(host.stub.requestCount))
        if let size = BenchProcess.fileSize(at: BenchTestHost.breadcrumbFileURL) {
            host.counter("breadcrumb_file_bytes", Double(size))
        }
    }
}
#endif
