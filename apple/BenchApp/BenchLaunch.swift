import Foundation
import os.signpost

/// Launch-time benchmark flow shared by the plain, sdk and sentinel app targets.
///
/// - Starts the loopback HTTP stub in every variant (constant harness cost, keeps plain and sdk symmetric).
/// - For BT_SDK builds, runs the SDK init sequence inside the `bt.init` signpost interval.
/// - For plain builds, emits an empty `bt.init` interval so XCTOSSignpostMetric always has data.
/// - Writes Documents/bt-bench-stages.json and bt-bench-stages-<n>.json after the first frame.
/// - Honors BT_BENCH_SEND=1 (one send(error:) after init) and BT_BENCH_CRASH=1 (SIGSEGV 1 s after init).
final class BenchLaunch {
    private let result = BenchResultFile(coldStart: true)
    private let stub = BenchStub.shared
    private(set) var summary = ""
    private var launchIndex: Int?
    #if BT_SDK
    private var harness: BenchSDKHarness?
    #endif

    func run() {
        if BenchConfig.isTestHost && !BenchConfig.flag("BT_BENCH_FORCE_INIT") {
            // A unit-test bundle is about to drive the SDK itself; stay out of its way.
            summary = "variant=\(BenchConfig.variant) host-mode (unit tests own the SDK)"
            return
        }
        let stubStarted = stub.start()
        if !stubStarted {
            result.errors.append(stub.startError ?? "stub failed to start")
        }
        #if BT_SDK
        let harness = BenchSDKHarness(stub: stub)
        harness.initialize()
        harness.fill(result)
        self.harness = harness
        #else
        let log = BenchSignpost.log
        let spid = OSSignpostID(log: log)
        os_signpost(.begin, log: log, name: "bt.init", signpostID: spid)
        os_signpost(.end, log: log, name: "bt.init", signpostID: spid)
        result.totalMs = 0
        result.counters["mock_requests"] = Double(stub.requestCount)
        result.counters["threads_after_init"] = Double(BenchProcess.threadCount())
        #endif
        result.counters["stub_port"] = Double(stub.port)
        summary = buildSummary()
    }

    /// Called once the window is visible: defers file IO out of the launch critical path and
    /// schedules the optional environment-driven actions.
    func afterFirstFrame() {
        if BenchConfig.isTestHost && !BenchConfig.flag("BT_BENCH_FORCE_INIT") { return }
        DispatchQueue.main.async { [self] in
            self.launchIndex = self.result.writeLaunchFiles()
            self.runEnvironmentActions()
        }
    }

    private func runEnvironmentActions() {
        #if BT_SDK
        if BenchConfig.flag("BT_BENCH_SEND"), let client = harness?.client {
            let start = BenchClock.now()
            client.send(error: BenchError.sample, attachmentPaths: []) { [self] sendResult in
                let elapsed = BenchClock.milliseconds(from: start, to: BenchClock.now())
                DispatchQueue.main.async {
                    self.result.counters["send_status_ok"] = sendResult.backtraceStatus == .ok ? 1 : 0
                    self.result.samples["C4.send.e2e_ms"] = [elapsed]
                    self.harness?.fill(self.result)
                    if sendResult.backtraceStatus != .ok {
                        self.result.errors.append("send status: \(BenchSDKHarness.statusName(sendResult.backtraceStatus))")
                    }
                    self.result.writeLaunchFiles(index: self.launchIndex)
                }
            }
        }
        #endif
        if BenchConfig.flag("BT_BENCH_CRASH") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                raise(SIGSEGV)
            }
        }
    }

    private func buildSummary() -> String {
        var lines = [
            "variant=\(BenchConfig.variant) sdk=\(BenchConfig.sdkVersion) source=\(BenchConfig.source ?? "-")",
            "appId=\(BenchConfig.appId)",
            "stub=127.0.0.1:\(stub.port)",
            String(format: "totalMs=%.3f", result.totalMs)
        ]
        for stage in result.stages {
            lines.append(String(format: "  %-12@ %9.3f ms ok=%@", stage.name as NSString, stage.ms, stage.ok ? "1" : "0"))
        }
        for key in result.counters.keys.sorted() {
            lines.append("  \(key)=\(Int(result.counters[key] ?? 0))")
        }
        return lines.joined(separator: "\n")
    }
}
