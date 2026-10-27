#if canImport(SwiftUI)
import SwiftUI

/// 갈래 만들기 칸 열기 (웹 `actions.branchOpen`). 작품 홈 · 상태 승인 · 갈래 비교 화면의 단추가 부르고,
/// 칸은 `CanonAppUI` 가 띄운다. 화면 모듈끼리는 서로 기대지 않아 환경 값으로 넘긴다.
public struct BranchOpener: Sendable {
    let action: @MainActor @Sendable (Int?) -> Void

    public init(_ action: @escaping @MainActor @Sendable (Int?) -> Void) {
        self.action = action
    }

    /// n 화부터 갈래를 만드는 칸을 연다. nil 이면 마지막으로 반영한 화부터.
    @MainActor public func callAsFunction(_ n: Int? = nil) { action(n) }
}

extension EnvironmentValues {
    @Entry public var openBranchForm: BranchOpener?
}
#endif
