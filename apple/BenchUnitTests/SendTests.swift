import XCTest

#if BT_SDK
import Backtrace

/// C4: send(error:) against the loopback stub.
///
/// Waits spin the run loop through `XCTWaiter` instead of blocking the main thread on a semaphore: a blocked main
/// thread can starve SDK work that hops to the main queue and trips the priority-inversion checker. A metric is
/// recorded only when every send completed with status `ok` and the stub counted exactly one request per send;
/// otherwise the failure is written to bench-result.json `errors` and the lane reports the pass as failed instead
/// of publishing numbers that include stalled sends.
final class SendTests: XCTestCase {
    private var host: BenchTestHost!

    /// Upper bound for one completion callback (the SDK's own request timeout is 60 s).
    private static let sendTimeout: TimeInterval = 60
    /// Upper bound for draining every outstanding completion after the caller-thread measurement.
    private static let drainTimeout: TimeInterval = 120

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
            let completed = XCTestExpectation(description: "send completion")
            let lock = NSLock()
            var status: BacktraceReportStatus?
            var end: UInt64 = 0
            let start = BenchClock.now()
            client.send(error: BenchError.sample, attachmentPaths: []) { result in
                lock.lock()
                status = result.backtraceStatus
                end = BenchClock.now()
                lock.unlock()
                completed.fulfill()
            }
            let outcome = XCTWaiter().wait(for: [completed], timeout: SendTests.sendTimeout)
            lock.lock()
            if outcome == .completed, let status = status {
                samples.append(BenchClock.milliseconds(from: start, to: end))
                statuses.append(BenchSDKHarness.statusName(status))
            } else {
                samples.append(BenchClock.milliseconds(from: start, to: BenchClock.now()))
                statuses.append("timeout")
            }
            lock.unlock()
        }

        let received = waitForStub(count: samples.count, since: requestsBefore, timeout: 5)
        XCTAssertEqual(received, samples.count, "stub must receive exactly one request per send")
        XCTAssertFalse(statuses.contains("limitReached"), "rate limiter engaged: \(statuses)")
        XCTAssertFalse(statuses.contains("debuggerAttached"), "debugger policy blocked reporting: \(statuses)")
        XCTAssertFalse(statuses.contains("timeout"), "send completion timed out: \(statuses)")
        let okCount = statuses.filter { $0 == "ok" }.count
        XCTAssertEqual(okCount, statuses.count, "every send should complete with status ok: \(statuses)")

        if okCount == statuses.count && received == samples.count {
            // XCTest discards the first (warm-up) iteration; do the same for the self-timed samples.
            host.record(metric: "C4.send.e2e_ms", samples: Array(samples.dropFirst()))
        } else {
            host.error("C4.send.e2e invalid: statuses=\(statuses) stubRequests=\(received)/\(samples.count)")
        }
        host.counter("C4.send.e2e.requests", Double(received))
        host.counter("C4.send.e2e.status_ok", Double(okCount))
        host.counter("C4.send.e2e.iterations", Double(samples.count))
    }

    /// C4.send.caller_ms: caller-thread blocking time of send(error:) (report generation), not waiting
    /// for the completion. Completions are drained after the measurement so the next test starts clean.
    func testSendCallerThreadOnly() throws {
        let client = host.client!
        let options = XCTMeasureOptions()
        options.iterationCount = BenchConfig.iterations(default: 30)
        var samples: [Double] = []
        let statusLock = NSLock()
        var statuses: [String] = []
        var completions: [XCTestExpectation] = []
        let requestsBefore = host.stub.requestCount

        measure(metrics: [XCTClockMetric()], options: options) {
            let completed = XCTestExpectation(description: "send completion \(completions.count)")
            completions.append(completed)
            let start = BenchClock.now()
            client.send(error: BenchError.sample, attachmentPaths: []) { result in
                statusLock.lock()
                statuses.append(BenchSDKHarness.statusName(result.backtraceStatus))
                statusLock.unlock()
                completed.fulfill()
            }
            samples.append(BenchClock.milliseconds(from: start, to: BenchClock.now()))
        }

        let drained = XCTWaiter().wait(for: completions, timeout: SendTests.drainTimeout)
        XCTAssertEqual(drained, .completed, "not every send completed within \(Int(SendTests.drainTimeout)) s")
        let received = waitForStub(count: samples.count, since: requestsBefore, timeout: 5)
        XCTAssertEqual(received, samples.count, "stub must receive exactly one request per send")
        statusLock.lock(); let finalStatuses = statuses; statusLock.unlock()
        XCTAssertFalse(finalStatuses.contains("limitReached"), "rate limiter engaged: \(finalStatuses)")
        XCTAssertFalse(finalStatuses.contains("debuggerAttached"), "debugger policy blocked reporting")
        let okCount = finalStatuses.filter { $0 == "ok" }.count

        if drained == .completed && received == samples.count && okCount == samples.count {
            host.record(metric: "C4.send.caller_ms", samples: Array(samples.dropFirst()))
        } else {
            host.error("C4.send.caller invalid: drained=\(drained == .completed) statuses=\(finalStatuses) stubRequests=\(received)/\(samples.count)")
        }
        host.counter("C4.send.caller.requests", Double(received))
        host.counter("C4.send.caller.status_ok", Double(okCount))
    }

    /// Spins the run loop until the stub has counted `count` requests beyond `before`, or `timeout` elapses.
    private func waitForStub(count: Int, since before: Int, timeout: TimeInterval) -> Int {
        let deadline = Date().addingTimeInterval(timeout)
        while host.stub.requestCount - before < count && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
        }
        return host.stub.requestCount - before
    }
}
#endif
