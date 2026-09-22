import Foundation

/// In-memory model of schema/bench-result.schema.json plus a JSON writer.
final class BenchResultFile {
    struct Stage {
        let name: String
        let ms: Double
        let thread: String
        let ok: Bool
    }

    var stages: [Stage] = []
    var totalMs: Double = 0
    var counters: [String: Double] = [:]
    var samples: [String: [Double]] = [:]
    var errors: [String] = []
    var coldStart: Bool
    let startedAt = ISO8601DateFormatter().string(from: Date())

    init(coldStart: Bool) {
        self.coldStart = coldStart
    }

    func dictionary() -> [String: Any] {
        var dict: [String: Any] = [
            "schemaVersion": 1,
            "sdk": "apple",
            "sdkVersion": BenchConfig.sdkVersion,
            "variant": BenchConfig.variant,
            "scenario": BenchConfig.scenario,
            "appId": BenchConfig.appId,
            "platform": BenchConfig.platform,
            "process": [
                "pid": Int(ProcessInfo.processInfo.processIdentifier),
                "startedAt": startedAt,
                "coldStart": coldStart
            ] as [String: Any],
            "stages": stages.map { stage -> [String: Any] in
                return ["name": stage.name, "ms": stage.ms, "thread": stage.thread, "ok": stage.ok]
            },
            "totalMs": totalMs,
            "counters": counters,
            "device": BenchConfig.deviceInfo()
        ]
        if let source = BenchConfig.source, ["spm", "xcframework", "local", "cocoapods"].contains(source) {
            dict["source"] = source
        }
        if !samples.isEmpty { dict["samples"] = samples }
        if !errors.isEmpty { dict["errors"] = errors }
        return dict
    }

    func data() throws -> Data {
        return try JSONSerialization.data(withJSONObject: dictionary(), options: [.prettyPrinted, .sortedKeys])
    }

    static func documentsDirectory() -> URL {
        let urls = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)
        let url = urls.first ?? URL(fileURLWithPath: NSTemporaryDirectory())
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    /// Writes `bt-bench-stages.json` (latest launch) and `bt-bench-stages-<index>.json`
    /// so that repeated launches never overwrite each other; returns the index used.
    @discardableResult
    func writeLaunchFiles(index: Int? = nil) -> Int {
        let dir = BenchResultFile.documentsDirectory()
        let launchIndex = index ?? BenchResultFile.nextLaunchIndex(in: dir)
        do {
            let payload = try data()
            try payload.write(to: dir.appendingPathComponent("bt-bench-stages.json"), options: .atomic)
            try payload.write(to: dir.appendingPathComponent("bt-bench-stages-\(launchIndex).json"), options: .atomic)
        } catch {
            NSLog("bench: failed to write stages file: \(error)")
        }
        return launchIndex
    }

    /// Writes `bench-result.json` (micro/unit-test lane).
    func writeMicroFile() {
        let url = BenchResultFile.documentsDirectory().appendingPathComponent("bench-result.json")
        do {
            try data().write(to: url, options: .atomic)
        } catch {
            NSLog("bench: failed to write bench-result.json: \(error)")
        }
    }

    static func nextLaunchIndex(in dir: URL) -> Int {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        var maxIndex = -1
        for name in names where name.hasPrefix("bt-bench-stages-") && name.hasSuffix(".json") {
            let middle = name.dropFirst("bt-bench-stages-".count).dropLast(".json".count)
            if let value = Int(middle) { maxIndex = max(maxIndex, value) }
        }
        return maxIndex + 1
    }
}
