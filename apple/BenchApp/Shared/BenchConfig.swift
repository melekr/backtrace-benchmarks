import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// Static benchmark configuration: compile-time identity from Info.plist (written by the renderer)
/// plus runtime switches from the process environment (forwarded by the drivers as BT_* variables).
enum BenchConfig {
    /// 64 hex characters; the SDK only forwards it as a query parameter to the loopback stub.
    static let token = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    static var environment: [String: String] { return ProcessInfo.processInfo.environment }

    private static func info(_ key: String) -> String? {
        return Bundle.main.object(forInfoDictionaryKey: key) as? String
    }

    /// plain | sdk | sentinel (renderer writes BTBenchVariant into the app Info.plist)
    static var variant: String { return info("BTBenchVariant") ?? "plain" }
    /// Published SDK version, "local-SNAPSHOT" or a git sha.
    static var sdkVersion: String { return info("BTBenchSDKVersion") ?? "none" }
    /// spm | xcframework | local
    static var source: String? { return info("BTBenchSource") }
    static var appId: String { return Bundle.main.bundleIdentifier ?? "unknown" }
    static var scenario: String { return environment["BT_SCENARIO"] ?? "default" }

    static func iterations(default defaultValue: Int) -> Int {
        if let raw = environment["BT_ITERATIONS"], let value = Int(raw), value > 0 { return value }
        return defaultValue
    }

    static func flag(_ name: String) -> Bool {
        guard let raw = environment[name] else { return false }
        return raw == "1" || raw.lowercased() == "true" || raw.lowercased() == "yes"
    }

    /// True when this process hosts an XCTest bundle (unit tests drive the SDK themselves).
    static var isTestHost: Bool {
        let env = environment
        return env["XCTestConfigurationFilePath"] != nil
            || env["XCTestBundlePath"] != nil
            || env["XCTestSessionIdentifier"] != nil
            || env["XCInjectBundleInto"] != nil
    }

    static var platform: String {
        #if os(iOS)
        return "ios"
        #elseif os(macOS)
        return "macos"
        #elseif os(tvOS)
        return "tvos"
        #else
        return "unknown"
        #endif
    }

    static var isSimulator: Bool {
        #if targetEnvironment(simulator)
        return true
        #else
        return false
        #endif
    }

    static func deviceInfo() -> [String: Any] {
        var device: [String: Any] = [
            "os": platform,
            "osVersion": ProcessInfo.processInfo.operatingSystemVersionString,
            "model": BenchProcess.sysctlString("hw.machine"),
            "cpuCores": ProcessInfo.processInfo.activeProcessorCount,
            "isEmulator": isSimulator
        ]
        #if arch(arm64)
        device["abi"] = "arm64"
        #elseif arch(x86_64)
        device["abi"] = "x86_64"
        #endif
        #if canImport(UIKit) && !os(watchOS)
        device["osVersion"] = UIDevice.current.systemVersion
        device["uiModel"] = UIDevice.current.model
        #endif
        if isSimulator, let simModel = environment["SIMULATOR_MODEL_IDENTIFIER"] {
            device["model"] = simModel
        }
        return device
    }
}
