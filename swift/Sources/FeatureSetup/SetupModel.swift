import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 설정 도우미가 부르는 서버. 시험에서는 가짜로 바꾼다.
public protocol SetupService: Sendable {
    func genres() async throws -> [Genre]
    /// 관계를 말로 고르는 보는 방식 (서버 `dynamics.VIEWS`).
    func relationViews() async throws -> [String]
    func namingStyles() async throws -> [NamingStyle]
    func names(_ project: String, _ body: Components.Schemas.NamesIn) async throws -> NamesOut
    func checkNames(_ project: String, _ body: Components.Schemas.NameCheckIn) async throws -> NameCheck
    /// 고른 제안을 빈 칸에만 넣고 저장한다. 서버가 작품을 저장하므로 화면은 다시 받는다.
    func applySuggestion(_ project: String, _ s: SetupSuggestion) async throws
}

/// 이름 · 지명 후보 한 묶음 (웹 `S.names[key]`). 열쇠는 인물 'c:<id>' 나 지명 'place'.
public struct NamePicks: Equatable, Sendable {
    public struct Item: Equatable, Sendable {
        public let name: String
        public let note: String
    }

    public let ai: Bool
    public let styleLabel: String
    public let items: [Item]

    /// AI 추천이면 이유를, 무작위 후보면 종류 · 메모를 함께 (웹 `namePicks`).
    public init(_ out: NamesOut, ai: Bool) {
        self.ai = ai
        styleLabel = out.styleLabel
        items = ai
            ? (out.options ?? []).map { Item(name: $0.name, note: $0.reason ?? "") }
            : out.candidates.map { Item(name: $0.name, note: [$0.kind ?? "", $0.note ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")) }
    }

    public func title(place: Bool) -> String {
        "\(ai ? "AI 추천" : "무작위 후보") · \(styleLabel) · 눌러서 \(place ? "장소에 추가" : "이름으로 쓰기")"
    }

    func removing(_ name: String) -> NamePicks {
        NamePicks(ai: ai, styleLabel: styleLabel, items: items.filter { $0.name != name })
    }

    init(ai: Bool, styleLabel: String, items: [Item]) {
        self.ai = ai
        self.styleLabel = styleLabel
        self.items = items
    }
}

/// 이름 점검 상태: 아직 안 함, 못 함, 결과.
public enum NameCheckState: Equatable, Sendable {
    case none
    case failed
    case done(NameCheck)

    public var result: NameCheck? {
        if case let .done(c) = self { return c }
        return nil
    }
}

/// 설정 도우미 화면 (웹 `viewSetup` · `viewSuggestion`). 작품은 함께 쓰는 `ProjectDocument` 로 고치고 저장 띠가 저장한다.
@MainActor
@Observable
public final class SetupModel {
    public let document: ProjectDocument
    public let jobs: JobCenter
    private let service: any SetupService

    public private(set) var genres: [Genre] = []
    /// 관계를 말로 고르는 보는 방식. 서버에서 받는다.
    public private(set) var views: [String] = []
    public private(set) var namingStyles: [NamingStyle] = []
    public private(set) var nameCheck: NameCheckState = .none
    /// 열쇠 'c:<인물 id>' · 'place' → 후보
    public private(set) var names: [String: NamePicks] = [:]
    /// 지명 후보의 종류. 비우면 종류 무관
    public var placeKind = ""
    /// 설정 제안에서 고른 것 (`SuggestionPicks` 의 열쇠)
    public var picks: [String: Bool] = [:]
    /// 진행 중인 요청 글 ('후보 뽑는 중' 등). 그동안 버튼을 막는다
    public private(set) var busy: String?
    public private(set) var notice: (text: String, isError: Bool)?
    private var checkSeq = 0

    public init(document: ProjectDocument, jobs: JobCenter, service: any SetupService) {
        self.document = document
        self.jobs = jobs
        self.service = service
    }

    public var project: Project? { document.project }
    var name: String { document.name }

    /// 화면을 열 때: 작품, 장르 목록, 보는 방식, 이름 스타일, 이름 점검.
    public func load() async {
        await document.load()
        async let g = try? service.genres()
        async let v = try? service.relationViews()
        async let s = try? service.namingStyles()
        genres = await g ?? genres
        views = await v ?? views
        namingStyles = await s ?? namingStyles
        await checkNames()
    }

    public func dismissNotice() { notice = nil }

    // MARK: 고치기

    public func editMeta(_ change: (inout Meta) -> Void) {
        document.edit { p in
            var m = p.meta ?? Meta()
            change(&m)
            p.meta = m
        }
    }

    public func editWorld(_ change: (inout World) -> Void) {
        document.edit { p in
            var w = p.world ?? World()
            change(&w)
            p.world = w
        }
    }

    public func editCharacter(_ id: String, _ change: (inout Person) -> Void) {
        document.edit { p in
            guard let i = p.characters?.firstIndex(where: { $0.id == id }) else { return }
            change(&p.characters![i])
        }
    }

    public func editRelationship(_ i: Int, _ change: (inout Relationship) -> Void) {
        document.edit { p in
            guard p.relationships?.indices.contains(i) == true else { return }
            change(&p.relationships![i])
        }
    }

    public func toggleGenre(_ id: String) {
        editMeta { SetupRules.toggleGenre(id, in: &$0, catalog: genres) }
        Task { await checkNames() }  // 장르도 자동 이름 스타일을 정한다 (naming.detect_style)
    }

    public func addGenre(_ text: String) {
        editMeta { SetupRules.addGenre(text, in: &$0, catalog: genres) }
        Task { await checkNames() }
    }

    /// 새 인물의 id 를 돌려준다.
    @discardableResult
    public func addCharacter() -> String {
        let c = SetupRules.newCharacter(after: project?.characters ?? [])
        document.edit { $0.characters = ($0.characters ?? []) + [c] }
        return c.id
    }

    public func removeCharacter(_ id: String) {
        document.edit { SetupRules.remove(id, from: &$0) }
        names["c:" + id] = nil
        Task { await checkNames() }  // 지운 인물과 겹친다던 경고를 걷어 낸다
    }

    public func addRelationship() {
        guard let p = project else { return }
        switch SetupRules.newRelationship(in: p) {
        case let .success(r): document.edit { $0.relationships = ($0.relationships ?? []) + [r] }
        case let .failure(problem): notice = (problem.message, true)
        }
    }

    public func removeRelationship(_ i: Int) {
        document.edit { p in
            guard p.relationships?.indices.contains(i) == true else { return }
            p.relationships!.remove(at: i)
        }
    }

    /// 자동 집필이 도는 동안은 관계를 고치지 못한다. 서버가 반영하는 관계와 겹치지 않게 받지 않는다.
    public var relationsLocked: Bool { jobs.running("auto") != nil }

    // MARK: 이름 · 지명

    /// 인물 이름 후보 (`ai` 면 '이름·지명' 단계 모델이 후보에서 고른다).
    public func characterNames(_ id: String, ai: Bool) async {
        await loadNames("c:" + id, Components.Schemas.NamesIn(character: id, placeKind: "", n: 8, ai: ai, project: project), ai: ai)
    }

    public func placeNames(ai: Bool) async {
        await loadNames("place", Components.Schemas.NamesIn(character: "", placeKind: placeKind, n: 8, ai: ai, project: project), ai: ai)
    }

    public func closeNames(_ key: String) { names[key] = nil }

    public func useName(_ name: String, for id: String) {
        editCharacter(id) { $0.name = name }
        names["c:" + id] = nil
        Task { await checkNames() }
    }

    public func addPlace(_ name: String) {
        editWorld { w in
            if !(w.locations ?? []).contains(name) { w.locations = (w.locations ?? []) + [name] }
        }
        names["place"] = names["place"]?.removing(name)
    }

    private func loadNames(_ key: String, _ body: Components.Schemas.NamesIn, ai: Bool) async {
        guard busy == nil else { return }
        busy = ai ? "AI가 고르는 중" : "후보 뽑는 중"
        defer { busy = nil }
        do {
            names[key] = NamePicks(try await service.names(name, body), ai: ai)
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    /// 이름 점검. 저장 전 화면 값으로 본다. 나중에 보낸 점검이 있으면 그 결과를 쓴다 (웹 `checkNames`).
    /// `show` 면 결과를 알림으로도 띄운다.
    public func checkNames(show: Bool = false) async {
        guard let p = project else { return }
        checkSeq += 1
        let my = checkSeq
        let body = Components.Schemas.NameCheckIn(meta: p.meta ?? Meta(), world: p.world ?? World(),
                                                  characters: p.characters ?? [], castCandidates: p.castCandidates ?? [])
        let result = try? await service.checkNames(name, body)
        guard my == checkSeq else { return }
        if let result {
            nameCheck = .done(result)
            if show { notice = (result.warnings.isEmpty ? "이름 점검: 문제 없음" : "이름 점검: \(result.warnings.count)건", false) }
        } else {
            nameCheck = .failed
            if show { notice = ("이름 점검을 못 했어요. 잠시 뒤 다시 해 보세요", true) }
        }
    }

    /// 이름 스타일 고르기의 '자동' 글 ('자동 (지금: 현대 한국)').
    public var autoStyleLabel: String {
        let det = nameCheck.result?.detected ?? ""
        return "자동 (지금: \(styleLabel(det)))"
    }

    public func styleLabel(_ id: String) -> String {
        namingStyles.first { $0.id == id }?.label ?? id
    }

    /// 지금 이름 스타일 (고른 것, 없으면 점검이 짐작한 것).
    public var currentStyle: NamingStyle? {
        let sid = project?.world?.nameStyle.flatMap { $0.isEmpty ? nil : $0 } ?? nameCheck.result?.style ?? ""
        return namingStyles.first { $0.id == sid }
    }

    // MARK: AI 설정 제안 (작업 'suggest')

    public static let suggestKey = Job.key("suggest", nil)

    /// 검토를 기다리는 제안. 읽지 못하면 nil.
    public var suggestion: SetupSuggestion? {
        try? jobs.results[Self.suggestKey]?.result.decode(SetupSuggestion.self)
    }

    public var suggestLabel: String { jobs.busyLabel("suggest") ?? "빈칸 AI 제안받기" }
    public var suggesting: Bool { jobs.busyLabel("suggest") != nil }
    public var suggestFailure: PendingFailure? { jobs.failures[Self.suggestKey] }

    public func suggest() async {
        picks = [:]
        await jobs.start(JobRequest(kind: "suggest"))
    }

    public func picked(_ key: String) -> Bool {
        guard let s = suggestion else { return false }
        return SuggestionPicks.picked(key, s, project, picks)
    }

    public func setPick(_ key: String, _ on: Bool) { picks[key] = on }

    public func dropSuggestion() async {
        picks = [:]
        await jobs.drop("suggest")
    }

    /// 고른 것만 빈 칸에 넣는다. 저장하지 않은 변경은 먼저 저장한다 (웹 `applySuggestion`).
    public func applySuggestion() async {
        guard let s = suggestion, busy == nil else { return }
        let chosen = SuggestionPicks.chosen(s, project, picks)
        busy = "적용하는 중"
        defer { busy = nil }
        if document.dirty, await document.save() == false, document.dirty { return }
        do {
            try await service.applySuggestion(name, chosen)
            await document.reload()
            picks = [:]
            await jobs.drop("suggest")
            notice = ("빈칸을 채웠어요. 기존 입력은 그대로예요.", false)
        } catch {
            notice = (CanonError.message(error), true)
            return
        }
        await checkNames()  // 더한 인물 이름도 점검한다
    }
}
