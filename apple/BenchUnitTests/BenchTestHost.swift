import XCTest
import Foundation

#if BT_SDK
import Backtrace

/// One shared BacktraceClient per test process, initialized against the loopback stub.
/// Also owns the process-wide result file (Documents/bench-result.json of the host app).
final class BenchTestHost {
    static let shared = BenchTestHost()

    let stub = BenchStub.shared
    let harness: BenchSDKHarness
    let result = BenchResultFile(coldStart: false)
    private let lock = NSLock()

    private init() {
        if !stub.start() {
            result.errors.append(stub.startError ?? "stub failed to start")
        }
        harness = BenchSDKHarness(stub: stub)
        harness.initialize()
        harness.fill(result)
        result.writeMicroFile()
    }

    var client: BacktraceClient? { return harness.client }

    /// Records per-iteration samples for a metric id and rewrites the result file.
    func record(metric: String, samples: [Double]) {
        lock.lock(); defer { lock.unlock() }
        result.samples[metric] = samples
        harness.fill(result)
        result.writeMicroFile()
    }

    func counter(_ name: String, _ value: Double) {
        lock.lock(); defer { lock.unlock() }
        result.counters[name] = value
        result.writeMicroFile()
    }

    func error(_ message: String) {
        lock.lock(); defer { lock.unlock() }
        result.errors.append(message)
        result.writeMicroFile()
    }

    static var breadcrumbFileURL: URL {
        return BenchResultFile.documentsDirectory().appendingPathComponent("bt-breadcrumbs-0")
    }
}
#endif
