import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

public typealias StateDelta = Components.Schemas.StateDelta

/// 작업지시서 화면이 서버에 보내는 것. 시험에서는 가짜로 바꾼다.
public protocol BriefService: Sendable {
    /// 채팅 앱에 붙여 넣을 지시서 (`GET .../episodes/{n}/brief?kind=`). API 생성과 같은 프롬프트다.
    func brief(_ project: String, ep: Int, kind: BriefKind) async throws -> String
    /// 받은 본문을 그 화 본문으로 저장한다 (`PUT .../episodes/{n}/text`). 순서 규칙은 서버가 본다.
    func saveText(_ project: String, ep: Int, text: String) async throws -> Project
    /// 받은 JSON 을 서버가 검사해 변경안으로 읽는다 (`POST .../episodes/{n}/state/parse`). 읽지 못하면 400.
    func parseState(_ project: String, ep: Int, raw: String) async throws -> StateDelta
}

/// 지시서 종류 (웹 `S.briefTab`).
public enum BriefKind: String, CaseIterable, Sendable {
    case episode, state

    public var label: String {
        switch self {
        case .episode: "1 본문 작성 지시서"
        case .state: "2 상태 승인 지시서"
        }
    }
}

/// 작업지시서 화면 상태 (웹 `viewBrief`). 지시서를 받고, 채팅 앱에서 받은 본문 · JSON 을 서버로 보낸다.
@MainActor
@Observable
public final class BriefModel {
    public let document: ProjectDocument
    /// 보는 화.
    public private(set) var ep: Int
    public private(set) var kind: BriefKind = .episode
    /// 받은 지시서. nil 이면 받는 중이거나 받지 못했다.
    public private(set) var text: String?
    public private(set) var loadError: String?
    /// 받은 JSON 을 서버가 거절한 이유. 사라지지 않게 칸 아래에 남긴다 (웹 `briefImportError`).
    public private(set) var importError: String?
    /// 확인한 변경안. 상태 승인 화면으로 넘길 곳이 없을 때 여기에 남는다.
    public private(set) var parsed: StateDelta?
    public private(set) var busy = false
    public private(set) var notice: (text: String, isError: Bool)?
    private let service: any BriefService

    /// 화마다 고른 지시서 종류 ('작품:화'). 앱이 도는 동안 남는다 (웹 `BRIEF_TABS`).
    private static var tabs: [String: BriefKind] = [:]
    /// 붙여 넣은 글 ('작품:화:종류'). 화면을 옮겨도 남는다 (웹 `S.briefDraft`).
    private static var kept: [String: String] = [:]
    private var drafts: [String: String] = [:]

    public init(document: ProjectDocument, service: any BriefService, ep: Int? = nil) {
        self.document = document
        self.service = service
        self.ep = ep ?? document.project.map(Self.defaultEpisode) ?? 1
        drafts = Self.kept
    }

    /// 처음 볼 화: 반영이 끝나지 않은 첫 화, 모두 끝났으면 마지막 화.
    public nonisolated static func defaultEpisode(_ p: Project) -> Int {
        let eps = p.episodes ?? []
        return (eps.first { BriefText.status($0) != .finalized } ?? eps.last)?.plot.number ?? 1
    }

    public var project: Project? { document.project }
    public var episodes: [Episode] { project?.episodes ?? [] }
    public var episode: Episode? { episodes.first { $0.plot.number == ep } }
    public var status: EpisodeStatus { episode.map(BriefText.status) ?? .draft }
    private var key: String { "\(document.name):\(ep)" }

    /// 받은 글 칸 (지금 화 · 종류).
    public var draft: String {
        get { drafts["\(key):\(kind.rawValue)"] ?? "" }
        set { keep("\(key):\(kind.rawValue)", newValue) }
    }

    /// 본문이 없어 상태 승인 지시서를 만들 수 없다.
    public var stateBlocked: Bool { kind == .state && (episode?.text ?? "").isEmpty }
    /// 앞 화 반영이 끝나지 않아 서버가 막는 화 (받은 본문 저장은 처음 쓰는 화만, 변경안은 본문이 있는 화만).
    public var order: [Int] {
        let check = kind == .episode ? status == .confirmed : status == .written
        return check ? BriefText.blockedBefore(ep, in: episodes) : []
    }

    public var canImport: Bool {
        guard order.isEmpty else { return false }
        return kind == .episode ? BriefText.canImportText(status) : status == .written
    }

    public func start() async {
        await document.load()
        if episode == nil, let p = project { ep = Self.defaultEpisode(p) }
        kind = Self.tabs[key] ?? BriefText.defaultKind(status)
        await load()
    }

    public func select(_ n: Int) async {
        guard n != ep else { return }
        ep = n
        kind = Self.tabs[key] ?? BriefText.defaultKind(status)
        importError = nil
        parsed = nil
        await load()
    }

    public func setKind(_ k: BriefKind) async {
        Self.tabs[key] = k
        guard k != kind else { return }
        kind = k
        importError = nil
        parsed = nil
        await load()
    }

    /// 지시서를 받는다. 본문이 없는 화의 상태 승인 지시서는 받지 않는다.
    public func load() async {
        text = nil
        loadError = nil
        guard episode != nil, !stateBlocked else { return }
        let (n, k) = (ep, kind)
        do {
            let t = try await service.brief(document.name, ep: n, kind: k)
            if n == ep, k == kind { text = t }
        } catch {
            if n == ep, k == kind { loadError = CanonError.message(error) }
        }
    }

    public func dismissNotice() { notice = nil }
    public func copied() { notice = (BriefText.copied, false) }
    public func copyFailed() { notice = (BriefText.copyFailed, true) }

    /// 받은 본문을 저장한다 (웹 `importText`). 바꿀지는 화면이 먼저 묻는다 (`BriefText.replaceQuestion`). 저장하면 true.
    public func importText() async -> Bool {
        let body = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else {
            notice = (BriefText.pasteText, true)
            return false
        }
        let n = ep
        return await run {
            if self.document.dirty, await self.document.save() == false, self.document.dirty {
                throw CanonError.server(status: 0, message: self.document.error ?? "저장하지 못했어요", code: nil)
            }
            _ = try await self.service.saveText(self.document.name, ep: n, text: body)
            await self.document.merge { _, e in e.plot.number == n }
            self.keep("\(self.document.name):\(n):episode", nil)
            self.notice = (BriefText.savedText(n), false)
        }
    }

    /// 받은 JSON 을 서버에서 검사한다 (웹 `importJson`). 거절하면 칸 아래에 이유를 남긴다. 읽으면 변경안을 돌려준다.
    public func importJSON() async -> StateDelta? {
        let raw = draft
        guard !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            notice = (BriefText.pasteJSON, true)
            return nil
        }
        busy = true
        defer { busy = false }
        do {
            let d = try await service.parseState(document.name, ep: ep, raw: raw)
            importError = nil
            parsed = d
            keep("\(key):state", nil)
            return d
        } catch let e as CanonError where e.status == 400 {
            importError = e.errorDescription
        } catch {
            notice = (CanonError.message(error), true)
        }
        return nil
    }

    private func keep(_ k: String, _ v: String?) {
        drafts[k] = v
        Self.kept[k] = v
    }

    private func run(_ body: @escaping () async throws -> Void) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            try await body()
            return true
        } catch {
            notice = (CanonError.message(error), true)
            return false
        }
    }
}
