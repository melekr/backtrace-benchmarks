import XCTest

/// Launch benchmark: XCTApplicationLaunchMetric (C2.launch_ms) plus the in-app `bt.init`
/// signpost interval (C1.init.total). The iteration count comes from BT_ITERATIONS
/// (forward it with TEST_RUNNER_BT_ITERATIONS=<n> on the xcodebuild command line).
final class LaunchTests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testLaunch() throws {
        let environment = ProcessInfo.processInfo.environment
        let iterations = Int(environment["BT_ITERATIONS"] ?? "") ?? 10
        let options = XCTMeasureOptions()
        options.iterationCount = iterations

        let app = XCUIApplication()
        for (key, value) in environment where key.hasPrefix("BT_") {
            app.launchEnvironment[key] = value
        }

        let metrics: [XCTMetric] = [
            XCTApplicationLaunchMetric(waitUntilResponsive: true),
            XCTOSSignpostMetric(subsystem: "io.backtrace.bench", category: "init", name: "bt.init")
        ]
        measure(metrics: metrics, options: options) {
            app.launch()
        }
        app.terminate()
    }
}
