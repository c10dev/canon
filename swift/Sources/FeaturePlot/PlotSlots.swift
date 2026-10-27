#if canImport(SwiftUI)
import CanonAPI
import CanonStore
import SwiftUI

/// 다른 화면 모듈이 플롯 화면에 끼우는 조각. 화면 모듈끼리는 서로 기대지 않으므로(README 모듈 규칙 2)
/// `CanonAppUI` 가 `.environment(\.plotSlots, ...)` 로 넣어 준다. 넣지 않으면 아무것도 그리지 않는다.
public struct PlotSlots: Sendable {
    /// 화 플롯 편집기의 등장 인물 칸 아래 (웹 `plotEditor` 의 `lineField`).
    /// locked: 작업이 이 화를 쓰는 중이라 고치지 못한다. written: 본문이 있는 화. change: 이 화 플롯 고치기.
    public var episodeField: @MainActor @Sendable (_ project: Project, _ plot: EpisodePlot, _ locked: Bool, _ written: Bool,
                                                   _ change: @escaping ((inout EpisodePlot) -> Void) -> Void) -> AnyView
    /// 화 카드의 제목 옆 (웹 `lineBadge`).
    public var cardBadges: @MainActor @Sendable (_ project: Project, _ plot: EpisodePlot) -> AnyView

    public init(episodeField: @escaping @MainActor @Sendable (Project, EpisodePlot, Bool, Bool, @escaping ((inout EpisodePlot) -> Void) -> Void) -> AnyView,
                cardBadges: @escaping @MainActor @Sendable (Project, EpisodePlot) -> AnyView) {
        self.episodeField = episodeField
        self.cardBadges = cardBadges
    }

    public static let none = PlotSlots(episodeField: { _, _, _, _, _ in AnyView(EmptyView()) }, cardBadges: { _, _ in AnyView(EmptyView()) })
}

extension EnvironmentValues {
    @Entry public var plotSlots: PlotSlots = .none
}
#endif
