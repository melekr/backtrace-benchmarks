import Foundation
import os.signpost

#if BT_SDK
import Backtrace
#endif

/// Signpost log shared by the app and the XCTOSSignpostMetric in BenchAppUITests
/// (subsystem "io.backtrace.bench", category "init", interval name "bt.init").
enum BenchSignpost {
    static let log = OSLog(subsystem: "io.backtrace.bench", category: "init")
}

enum BenchError: Error {
    case sample
}

#if BT_SDK
/// Drives the SDK through its init sequence on the calling thread and records per-stage timings.
///
/// Stage names follow docs/CONVENTIONS.md section 6 for Apple: `client` (BacktraceClient(configuration:)),
/// `attributes` (attributes setter) and `breadcrumbs` (enableBreadcrumbs()).
final class BenchSDKHarness {
    let stub: BenchStub
    private(set) var client: BacktraceClient?
    private(set) var stages: [BenchResultFile.Stage] = []
    private(set) var totalMs: Double = 0
    private(set) var errors: [String] = []
    private(set) var threadsBeforeInit = -1
    private(set) var threadsAfterInit = -1

    init(stub: BenchStub) {
        self.stub = stub
    }

    static func makeConfiguration(endpoint: URL) -> BacktraceClientConfiguration {
        let credentials = BacktraceCredentials(endpoint: endpoint, token: BenchConfig.token)
        let configuration = BacktraceClientConfiguration(credentials: credentials)
        configuration.allowsAttachingDebugger = true
        configuration.reportsPerMin = 100000
        // Default database settings (retryBehaviour .interval, retryInterval 5 s).
        configuration.dbSettings = BacktraceDatabaseSettings()
        #if BT_GE_2_1
        configuration.oomMode = .none
        #endif
        #if BT_GE_2_2
        if BenchConfig.scenario == "diag" {
            configuration.loggingDestinations = [BacktraceConsoleDestination(level: .debug)]
        } else {
            configuration.loggingDestinations = []
        }
        #endif
        return configuration
    }

    /// Runs client init, attribute set and breadcrumb enable, wrapped in `bt.init` signposts.
    func initialize() {
        threadsBeforeInit = BenchProcess.threadCount()
        let log = BenchSignpost.log
        let spid = OSSignpostID(log: log)
        let threadName = Thread.isMainThread ? "main" : "background"
        let start = BenchClock.now()
        os_signpost(.begin, log: log, name: "bt.init", signpostID: spid)

        // Stage 1: client
        os_signpost(.begin, log: log, name: "bt.init.client", signpostID: spid)
        let clientStart = BenchClock.now()
        var clientOk = true
        do {
            client = try BacktraceClient(configuration: BenchSDKHarness.makeConfiguration(endpoint: stub.baseURL))
        } catch {
            clientOk = false
            errors.append("BacktraceClient init failed: \(error)")
        }
        let clientEnd = BenchClock.now()
        os_signpost(.end, log: log, name: "bt.init.client", signpostID: spid)
        stages.append(BenchResultFile.Stage(name: "client",
                                            ms: BenchClock.milliseconds(from: clientStart, to: clientEnd),
                                            thread: threadName, ok: clientOk))

        // Stage 2: attributes
        os_signpost(.begin, log: log, name: "bt.init.attributes", signpostID: spid)
        let attributesStart = BenchClock.now()
        client?.attributes = [
            "bench.variant": BenchConfig.variant,
            "bench.sdkVersion": BenchConfig.sdkVersion,
            "bench.scenario": BenchConfig.scenario,
            "bench.flag": true,
            "bench.number": 42
        ]
        let attributesEnd = BenchClock.now()
        os_signpost(.end, log: log, name: "bt.init.attributes", signpostID: spid)
        stages.append(BenchResultFile.Stage(name: "attributes",
                                            ms: BenchClock.milliseconds(from: attributesStart, to: attributesEnd),
                                            thread: threadName, ok: client != nil))

        // Stage 3: breadcrumbs
        os_signpost(.begin, log: log, name: "bt.init.breadcrumbs", signpostID: spid)
        let breadcrumbsStart = BenchClock.now()
        client?.enableBreadcrumbs()
        let breadcrumbsEnd = BenchClock.now()
        os_signpost(.end, log: log, name: "bt.init.breadcrumbs", signpostID: spid)
        stages.append(BenchResultFile.Stage(name: "breadcrumbs",
                                            ms: BenchClock.milliseconds(from: breadcrumbsStart, to: breadcrumbsEnd),
                                            thread: threadName, ok: client != nil))

        os_signpost(.end, log: log, name: "bt.init", signpostID: spid)
        totalMs = BenchClock.milliseconds(from: start, to: BenchClock.now())
        threadsAfterInit = BenchProcess.threadCount()
        BacktraceClient.shared = client
    }

    /// Fills the deterministic counters of a result file from this harness and the stub.
    func fill(_ result: BenchResultFile) {
        result.stages = stages
        result.totalMs = totalMs
        result.errors.append(contentsOf: errors)
        result.counters["mock_requests"] = Double(stub.requestCount)
        result.counters["mock_incomplete_requests"] = Double(stub.incompleteCount)
        result.counters["threads_before_init"] = Double(threadsBeforeInit)
        result.counters["threads_after_init"] = Double(threadsAfterInit)
        if threadsBeforeInit >= 0 && threadsAfterInit >= 0 {
            result.counters["threads_delta"] = Double(threadsAfterInit - threadsBeforeInit)
        }
        if let size = BenchProcess.fileSize(at: BenchResultFile.documentsDirectory().appendingPathComponent("bt-breadcrumbs-0")) {
            result.counters["breadcrumb_file_bytes"] = Double(size)
        }
    }

    static func statusName(_ status: BacktraceReportStatus) -> String {
        switch status {
        case .ok: return "ok"
        case .serverError: return "serverError"
        case .debuggerAttached: return "debuggerAttached"
        case .unknownError: return "unknownError"
        case .limitReached: return "limitReached"
        @unknown default: return "unknown(\(status.rawValue))"
        }
    }
}
#endif
