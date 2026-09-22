import XCTest

#if BT_SDK
import Backtrace

/// C4: send(error:) against the loopback stub.
final class SendTests: XCTestCase {
    private var host: BenchTestHost!

    override func setUpWithError() throws {
        continueAfterFailure = true
        host = BenchTestHost.shared
        try XCTSkipIf(host.client == nil, "BacktraceClient failed to initialize: \(host.harness.errors)")
    }

    /// C4.send.e2e_ms (XCTClockMetric), C4.send.cpu_ms (XCTCPUMetric), C4.send.memory_peak_kb (XCTMemoryMetric):
    /// one send per iteration, the block waits for the completion callback.
    func testSendEndToEnd() throws {
        let client = host.client!
        let options = XCTMeasureOptions()
        options.iterationCount = BenchConfig.iterations(default: 30)
        var samples: [Double] = []
        var statuses: [String] = []
        let requestsBefore = host.stub.requestCount

        measure(metrics: [XCTClockMetric(), XCTCPUMetric(), XCTMemoryMetric()], options: options) {
            let done = DispatchSemaphore(value: 0)
            var status: BacktraceReportStatus?
            let start = BenchClock.now()
            client.send(error: BenchError.sample, attachmentPaths: []) { result in
                status = result.backtraceStatus
                done.signal()
            }
            let waited = done.wait(timeout: .now() + 60)
            samples.append(BenchClock.milliseconds(from: start, to: BenchClock.now()))
            if waited == .timedOut {
                statuses.append("timeout")
            } else if let status = status {
                statuses.append(BenchSDKHarness.statusName(status))
            }
        }

        let requestsAfter = host.stub.requestCount
        XCTAssertEqual(requestsAfter - requestsBefore, samples.count,
                       "stub must receive exactly one request per send")
        XCTAssertFalse(statuses.contains("limitReached"), "rate limiter engaged: \(statuses)")
        XCTAssertFalse(statuses.contains("debuggerAttached"), "debugger policy blocked reporting: \(statuses)")
        XCTAssertFalse(statuses.contains("timeout"), "send completion timed out: \(statuses)")
        let okCount = statuses.filter { $0 == "ok" }.count
        XCTAssertEqual(okCount, statuses.count, "every send should complete with status ok: \(statuses)")

        // XCTest discards the first (warm-up) iteration; do the same for the self-timed samples.
        host.record(metric: "C4.send.e2e_ms", samples: Array(samples.dropFirst()))
        host.counter("C4.send.e2e.requests", Double(requestsAfter - requestsBefore))
        host.counter("C4.send.e2e.status_ok", Double(okCount))
        host.counter("C4.send.e2e.iterations", Double(samples.count))
        if okCount != statuses.count {
            host.error("C4.send.e2e statuses: \(statuses)")
        }
    }

    /// C4.send.caller_ms: caller-thread blocking time of send(error:) (report generation), not waiting
    /// for the completion. Completions are drained after the measurement so the next test starts clean.
    func testSendCallerThreadOnly() throws {
        let client = host.client!
        let options = XCTMeasureOptions()
        options.iterationCount = BenchConfig.iterations(default: 30)
        var samples: [Double] = []
        let group = DispatchGroup()
        let statusLock = NSLock()
        var statuses: [String] = []
        let requestsBefore = host.stub.requestCount

        measure(metrics: [XCTClockMetric()], options: options) {
            group.enter()
            let start = BenchClock.now()
            client.send(error: BenchError.sample, attachmentPaths: []) { result in
                statusLock.lock()
                statuses.append(BenchSDKHarness.statusName(result.backtraceStatus))
                statusLock.unlock()
                group.leave()
            }
            samples.append(BenchClock.milliseconds(from: start, to: BenchClock.now()))
        }

        let drained = group.wait(timeout: .now() + 120)
        XCTAssertEqual(drained, .success, "not every send completed within 120 s")
        // Give the stub a moment to count the last connections.
        let deadline = Date().addingTimeInterval(5)
        while host.stub.requestCount - requestsBefore < samples.count && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        let received = host.stub.requestCount - requestsBefore
        XCTAssertEqual(received, samples.count, "stub must receive exactly one request per send")
        statusLock.lock(); let finalStatuses = statuses; statusLock.unlock()
        XCTAssertFalse(finalStatuses.contains("limitReached"), "rate limiter engaged: \(finalStatuses)")
        XCTAssertFalse(finalStatuses.contains("debuggerAttached"), "debugger policy blocked reporting")

        host.record(metric: "C4.send.caller_ms", samples: Array(samples.dropFirst()))
        host.counter("C4.send.caller.requests", Double(received))
        host.counter("C4.send.caller.status_ok", Double(finalStatuses.filter { $0 == "ok" }.count))
    }
}
#endif
