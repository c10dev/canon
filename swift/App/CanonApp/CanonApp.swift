import CanonAppUI
import SwiftUI

/// Xcode 앱 껍데기. 화면과 상태는 모두 CanonKit 패키지(CanonAppUI)에 있다.
@main
struct CanonApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
