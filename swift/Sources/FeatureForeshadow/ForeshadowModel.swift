import CanonAPI
import CanonCore
import Foundation
import Observation

public typealias ForeshadowCenter = Components.Schemas.ForeshadowCenter
public typealias ForeshadowItem = Components.Schemas.ForeshadowCenterItem
public typealias ForeshadowClue = Components.Schemas.ForeshadowCenterClue
public typealias ForeshadowScope = Components.Schemas.ForeshadowCenterItem.ScopePayload

/// 복선 센터에서 작가가 하는 일. 모두 작가 입력이라 승인 단계 없이 서버가 바로 저장한다.
public enum ForeshadowChange: Sendable, Equatable {
    /// 복선 직접 더하기. `episode` 화에 심은 것으로 본다.
    case add(description: String, episode: Int, scope: ForeshadowScope, due: Int?)
    /// 내용, 회수 범위, 회수 예정 화 고치기. `due` 가 nil 이면 예정 화를 지운다.
    case edit(id: String, description: String, scope: ForeshadowScope, due: Int?)
    /// 근거 문장 없이 회수로 표시.
    case resolve(id: String, episode: Int)
    /// 회수 취소. 회수 문장도 지운다.
    case reopen(id: String)
    /// 복선과 걸린 문장을 모두 지운다.
    case remove(id: String)
    /// 걸린 문장 하나의 연결을 지운다.
    case dropClue(id: String, episode: Int, quote: String)
    /// 본문에서 사라진 문장에 걸린 연결을 모두 지운다.
    case prune

    /// 하는 동안 보일 문구 (웹 `fsCall` 의 label).
    public var progress: String {
        switch self {
        case .add: "복선 더하는 중"
        case .edit: "저장 중"
        case .resolve: "회수로 표시하는 중"
        case .reopen: "다시 여는 중"
        case .remove: "지우는 중"
        case .dropClue: "연결 지우는 중"
        case .prune: "끊어진 연결 정리하는 중"
        }
    }
}

/// 복선 센터 서버. 시험에서는 가짜로 바꾼다.
public protocol ForeshadowService: Sendable {
    /// 서버 `foreshadows.center` 계산값.
    func center() async throws -> ForeshadowCenter
    func perform(_ change: ForeshadowChange) async throws
}

/// 목록 거르기 (웹 `S.fsTab`).
public enum ForeshadowTab: String, CaseIterable, Sendable, Identifiable {
    case open, resolved, all, attention
    public var id: String { rawValue }
}

/// 복선 센터 화면 상태.
@MainActor
@Observable
public final class ForeshadowModel {
    public private(set) var center: ForeshadowCenter?
    public private(set) var loading = false
    public private(set) var error: String?
    /// 진행 중인 고치기 문구. 그동안 다른 고치기는 받지 않는다.
    public private(set) var busy: String?
    public var tab: ForeshadowTab = .open
    /// nil 이면 범위 전체.
    public var scope: ForeshadowScope?
    /// 펼친 복선 id.
    public var expanded: Set<String> = []
    /// '복선 직접 더하기' 칸 열림.
    public var adding = false
    private let service: any ForeshadowService

    public init(service: any ForeshadowService) {
        self.service = service
    }

    /// 지금 탭과 범위에 맞는 복선.
    public var shown: [ForeshadowItem] {
        center?.items.filter { ForeshadowText.shown($0, tab: tab, scope: scope) } ?? []
    }

    public func load() async {
        loading = true
        defer { loading = false }
        do {
            center = try await service.center()
            error = nil
        } catch {
            self.error = CanonError.message(error)
        }
    }

    public func toggle(_ id: String) {
        if expanded.contains(id) { expanded.remove(id) } else { expanded.insert(id) }
    }

    public func dismissError() { error = nil }

    /// 고치고 계산값을 다시 받는다. 성공하면 true.
    @discardableResult
    public func apply(_ change: ForeshadowChange) async -> Bool {
        guard busy == nil else { return false }
        if case let .add(description, _, _, _) = change,
           description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            error = "복선 내용을 적어 주세요"
            return false
        }
        busy = change.progress
        defer { busy = nil }
        do {
            try await service.perform(change)
        } catch {
            self.error = CanonError.message(error)
            return false
        }
        switch change {
        case .add:
            adding = false
            tab = .open
        case let .remove(id):
            expanded.remove(id)
        default:
            break
        }
        await load()
        return true
    }
}

/// 화면 문구와 거르기. 웹 화면(`foreshadow.js` 의 `viewForeshadow`, `fsItem`, `fsShown`, `fsClueList`)과 같다.
public enum ForeshadowText {
    /// 웹 `FS_SCOPE` (서버 명령줄 문구와 달리 series 는 '작품 끝까지').
    public static func scope(_ s: ForeshadowScope) -> String {
        switch s {
        case .arc: "이번 아크"
        case .part: "이번 부"
        case .series: "작품 끝까지"
        }
    }

    public static func status(_ x: ForeshadowItem) -> String { x.status == .resolved ? "회수" : "열림" }

    /// 예정 지남, 오래 묵음, 끊어진 연결 가운데 하나라도 있다.
    public static func needsAttention(_ x: ForeshadowItem) -> Bool { x.overdue || x.stale || x.broken > 0 }

    public static func shown(_ x: ForeshadowItem, tab: ForeshadowTab, scope: ForeshadowScope?) -> Bool {
        if let scope, x.scope != scope { return false }
        switch tab {
        case .open: return x.status == .open
        case .resolved: return x.status == .resolved
        case .attention: return needsAttention(x)
        case .all: return true
        }
    }

    /// '열린 3', '회수한 2', '전체 5', '손볼 것 1'
    public static func tab(_ t: ForeshadowTab, _ c: ForeshadowCenter) -> String {
        switch t {
        case .open: "열린 \(c.open)"
        case .resolved: "회수한 \(c.resolved)"
        case .all: "전체 \(c.total)"
        case .attention: "손볼 것 \(c.items.filter(needsAttention).count)"
        }
    }

    /// '67%', 복선이 없으면 '-'
    public static func rate(_ c: ForeshadowCenter) -> String {
        guard let r = c.rate else { return "-" }
        return "\(Int((r * 100).rounded()))%"
    }

    /// ['예정 9화 지남', '50화 넘게 안 나옴', '끊어진 연결 2']
    public static func flags(_ x: ForeshadowItem) -> [String] {
        var out: [String] = []
        if x.overdue { out.append("예정 \(x.dueEp.map(String.init) ?? "")화 지남") }
        if x.stale { out.append("50화 넘게 안 나옴") }
        if x.broken > 0 { out.append("끊어진 연결 \(x.broken)") }
        return out
    }

    /// '3화 → 9화 회수' 또는 '3화에 심음 · 마지막 등장 5화 · 예정 9화 · 7, 8화 플롯에서 회수 예정 · 문장 2개'
    public static func meta(_ x: ForeshadowItem) -> String {
        let when: String
        if let payoff = x.payoffEp {
            when = "\(x.plantedEp)화 → \(payoff)화 회수"
        } else {
            let due = x.dueEp.map { " · 예정 \($0)화" } ?? ""
            when = "\(x.plantedEp)화에 심음 · 마지막 등장 \(x.lastSeen)화\(due)"
        }
        let plan = x.status == .open && !x.planned.isEmpty
            ? " · \(x.planned.map(String.init).joined(separator: ", "))화 플롯에서 회수 예정" : ""
        return "\(when)\(plan) · 문장 \(x.plants.count + x.payoffs.count)개"
    }

    /// 걸린 문장 한 줄.
    public struct ClueRow: Sendable, Hashable, Identifiable {
        public let clue: ForeshadowClue
        public let payoff: Bool
        public var id: String { "\(payoff ? "payoff" : "plant")-\(clue.episode)-\(clue.quote)" }
        /// '3화 심음', '9화 회수'
        public var label: String { "\(clue.episode)화 \(payoff ? "회수" : "심음")" }
        public var byAuthor: Bool { clue.by == "author" }
    }

    /// 심은 문장 뒤에 회수한 문장을 두고 화 순서로 (웹처럼 같은 화에서는 원래 순서를 지킨다).
    public static func clues(_ x: ForeshadowItem) -> [ClueRow] {
        let rows = x.plants.map { ClueRow(clue: $0, payoff: false) } + x.payoffs.map { ClueRow(clue: $0, payoff: true) }
        return rows.enumerated()
            .sorted { ($0.element.clue.episode, $0.offset) < ($1.element.clue.episode, $1.offset) }
            .map(\.element)
    }

    public static let noClues = "본문에 걸린 문장이 없어요. 집필 화면에서 문장을 드래그해 '복선으로'를 누르면 걸 수 있어요."
    public static let empty = "해당하는 복선이 없어요."
    public static let removeConfirm = "이 복선과 걸어 둔 문장을 모두 지울까요? 플롯의 회수 계획에서도 빠집니다."
    public static let addHint = "본문 문장 없이 계획만 적어 둘 수도 있어요. 문장을 함께 걸려면 집필 화면에서 문장을 골라 '복선으로'를 누르세요."
    public static let intro = "복선마다 본문 어느 문장에 심고 회수했는지, 회수율과 오래 묵은 복선을 봐요. AI 가 찾은 문장은 상태 승인 화면에서 골라 반영돼요."

    public static func brokenNote(_ c: ForeshadowCenter) -> String {
        "본문을 고쳐 걸어 둔 문장이 사라진 연결이 \(c.broken)개 있어요. 다시 걸거나 정리하세요."
    }

    /// '세로선은 5화(마지막 반영)'
    public static func now(_ c: ForeshadowCenter) -> String { "세로선은 \(c.done)화(마지막 반영)" }

    /// 회수한 화 칸의 처음 값.
    public static func resolveEpisode(_ x: ForeshadowItem, done: Int) -> Int { max(done, x.plantedEp) }

    /// 새 복선의 심은 화 칸의 처음 값.
    public static func addEpisode(_ c: ForeshadowCenter) -> Int { max(c.done, 1) }

    /// 화 번호 칸. 비었거나 0 이하이면 nil (웹 `Number(v) || null`).
    public static func number(_ text: String) -> Int? {
        guard let n = Int(text.trimmingCharacters(in: .whitespaces)), n > 0 else { return nil }
        return n
    }
}

/// 복선 한 줄의 화 막대 (웹 `fsTrack`). 위치는 0~1 비율이다.
public struct ForeshadowTrack: Sendable, Equatable {
    public enum Dot: Sendable, Equatable { case plant, payoff, broken }
    public enum Tick: Sendable, Equatable { case due, planned }

    public struct Mark<Kind: Sendable & Equatable>: Sendable, Equatable {
        public let at: Double
        public let kind: Kind
        public let episode: Int
    }

    public let spanFrom: Double
    public let spanTo: Double
    /// 마지막 반영한 화의 세로선. 반영한 화가 없으면 nil.
    public let now: Double?
    public let ticks: [Mark<Tick>]
    public let dots: [Mark<Dot>]

    public init(_ x: ForeshadowItem, last: Int, done: Int) {
        let at = { (n: Int) in Double(max(0, n - 1)) / Double(max(1, last - 1)) }
        let end = x.payoffEp ?? max(done, x.lastSeen)
        spanFrom = at(x.plantedEp)
        spanTo = at(end)
        now = done > 0 ? at(done) : nil
        var ticks: [Mark<Tick>] = []
        if let due = x.dueEp { ticks.append(Mark(at: at(due), kind: .due, episode: due)) }
        if x.status == .open { ticks += x.planned.map { Mark(at: at($0), kind: .planned, episode: $0) } }
        self.ticks = ticks
        var dots = x.plants.map { Mark(at: at($0.episode), kind: $0.broken ? Dot.broken : .plant, episode: $0.episode) }
            + x.payoffs.map { Mark(at: at($0.episode), kind: $0.broken ? Dot.broken : .payoff, episode: $0.episode) }
        if x.plants.isEmpty { dots.insert(Mark(at: at(x.plantedEp), kind: .plant, episode: x.plantedEp), at: 0) }
        if let payoff = x.payoffEp, x.payoffs.isEmpty {
            dots.append(Mark(at: at(payoff), kind: .payoff, episode: payoff))
        }
        self.dots = dots
    }
}
