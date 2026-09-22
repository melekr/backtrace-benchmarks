import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    private var launch: BenchLaunch?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        // Everything measurable happens here, on the main thread, before the first frame.
        let launch = BenchLaunch()
        launch.run()
        self.launch = launch

        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = BenchViewController(summary: launch.summary)
        window.makeKeyAndVisible()
        self.window = window

        launch.afterFirstFrame()
        return true
    }
}
