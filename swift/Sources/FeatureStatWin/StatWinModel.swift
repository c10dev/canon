import CanonAPI
import CanonCore
import Foundation
import Observation

public typealias StatwinView = Components.Schemas.StatwinView
public typealias StatValue = Components.Schemas.StatValue
public typealias Project = Components.Schemas.Project

/// 상태창 화면이 서버에서 받고 보내는 것. 시험에서는 가짜로 바꾼다.
public protocol StatWinSource: Sendable {
    /// 작품 전체 (인물 목록, 인물별 항목 수, 상태창 서식).
    func project(_ name: String) async throws -> Project
    /// 인물 하나의 지금 상태창, 화별 비교표, 본문에 넣을 글 (`GET .../statwin/{cid}`).
    func view(_ name: String, character: String) async throws -> StatwinView
    /// 작가가 상태창 전체를 고친다 (`PUT .../statwin/{cid}`). 저장한 작품을 돌려준다.
    func save(_ name: String, character: String, stats: [StatValue]) async throws -> Project
    /// 본문 상태창 서식을 고친다 (`PUT .../statwin-template`). 저장한 작품을 돌려준다.
    func saveTemplate(_ name: String, template: String, row: String) async throws -> Project
}

/// 왼쪽 인물 목록 한 줄.
public struct StatPerson: Equatable, Sendable, Identifiable {
    public let id: String
    public let name: String
    /// 지금 상태창 항목 수. 0 이면 표시하지 않는다.
    public let count: Int
    public let isMain: Bool

    public init(id: String, name: String, count: Int, isMain: Bool) {
        self.id = id
        self.name = name
        self.count = count
        self.isMain = isMain
    }
}

/// 고치는 중인 항목 한 줄.
public struct StatRow: Equatable, Sendable, Identifiable {
    public let id = UUID()
    public var name: String
    public var value: String

    public init(name: String, value: String) {
        self.name = name
        self.value = value
    }

    public static func == (a: StatRow, b: StatRow) -> Bool { a.name == b.name && a.value == b.value }
}

/// 상태창 수치 화면 상태. 웹 화면(`statwin.js` 의 `viewStatwin`)과 같은 흐름이다.
@MainActor
@Observable
public final class StatWinModel {
    public let project: String
    public private(set) var people: [StatPerson] = []
    public private(set) var selected = ""
    /// 서버 값. nil 이면 불러오는 중이거나 인물이 없다.
    public private(set) var view: StatwinView?
    public private(set) var hasCharacters = true
    public var rows: [StatRow] = [] { didSet { if rows != oldValue { dirty = true } } }
    public private(set) var dirty = false
    public private(set) var busy = false
    public private(set) var loaded = false
    /// 불러오기 실패. 화면 가운데에 보인다.
    public private(set) var error: String?
    /// 저장 · 복사 알림 (웹 toast).
    public private(set) var notice: (text: String, isError: Bool)?
    /// 본문 상태창 서식. 서식 고치기 칸이 이 값으로 열린다.
    public private(set) var template = ""
    public private(set) var rowTemplate = ""
    private let source: any StatWinSource

    public init(project: String, source: any StatWinSource) {
        self.project = project
        self.source = source
    }

    /// 작품을 받고, 보던 인물(없으면 고를 인물)의 상태창을 받는다.
    public func load(_ character: String? = nil) async {
        do {
            take(try await source.project(project))
            error = nil
        } catch {
            self.error = CanonError.message(error)
            loaded = true
            return
        }
        await select(character ?? selected)
    }

    /// 인물을 고른다. 없는 인물이면 웹 `swLoad` 처럼 상태창이 있는 인물 → 주역 → 첫 인물 순으로 고른다.
    public func select(_ character: String) async {
        selected = StatWinText.pick(character, people: people)
        guard !selected.isEmpty else {
            view = nil
            loaded = true
            return
        }
        do {
            let v = try await source.view(project, character: selected)
            view = v
            rows = v.current.map { StatRow(name: $0.name, value: $0.value ?? "") }
            dirty = false
            error = nil
        } catch {
            view = nil
            self.error = CanonError.message(error)
        }
        loaded = true
    }

    public func addRow() { rows.append(StatRow(name: "", value: "")) }

    public func removeRow(_ id: StatRow.ID) { rows.removeAll { $0.id == id } }

    /// 틀(게임 판타지 등)의 항목 중 아직 없는 것을 값 없이 더한다.
    public func applyPreset(_ key: String) {
        let have = Set(rows.map(\.name))
        let names = view?.presets.additionalProperties[key] ?? []
        rows += names.filter { !have.contains($0) }.map { StatRow(name: $0, value: "") }
    }

    public var presetKeys: [String] { StatWinText.presetOrder(view?.presets.additionalProperties.keys.map { $0 } ?? []) }

    /// 지금 항목을 저장한다. '+3' · '+독 내성' 은 서버가 저장한 값 기준으로 계산한다.
    public func save() async {
        guard let view else { return }
        let stats = StatWinText.outgoing(rows, current: view.current)
        await run("상태창을 저장했어요") {
            try await self.source.save(self.project, character: self.selected, stats: stats)
        }
    }

    /// 본문 상태창 서식을 저장한다. 항목 한 줄이 비면 '{key}: {value}' 로 보낸다.
    public func saveTemplate(_ template: String, row: String) async {
        let row = row.isEmpty ? StatWinText.defaultRow : row
        await run("서식을 저장했어요") {
            try await self.source.saveTemplate(self.project, template: template, row: row)
        }
    }

    /// 복사한 뒤 알린다. 복사는 화면이 클립보드에 한다.
    public func copied(_ ok: Bool) {
        notice = ok ? ("상태창을 복사했어요", false) : ("복사하지 못했어요. 글을 직접 골라 복사하세요", true)
    }

    public func dismissNotice() { notice = nil }

    private func run(_ done: String, _ work: @escaping () async throws -> Project) async {
        busy = true
        defer { busy = false }
        do {
            take(try await work())
            await select(selected)
            notice = (done, false)
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    private func take(_ p: Project) {
        let chars = p.characters ?? []
        hasCharacters = !chars.isEmpty
        let counts = Dictionary((p.states ?? []).map { ($0.characterId, $0.stats?.count ?? 0) }, uniquingKeysWith: { a, _ in a })
        people = chars.map { StatPerson(id: $0.id, name: $0.name, count: counts[$0.id] ?? 0, isMain: ($0.tier ?? .main) == .main) }
        template = p.statWindow?.template ?? StatWinText.defaultTemplate
        rowTemplate = p.statWindow?.row ?? StatWinText.defaultRow
    }
}

/// 상태창 화면 문구와 규칙. 웹 `statwin.js` 와 같다 (README '웹과 같은 규칙').
public enum StatWinText {
    public static let defaultTemplate = "【 상태창 】\n이름: {name}\n{rows}"
    public static let defaultRow = "{key}: {value}"

    /// 고를 인물: 있는 인물이면 그대로, 아니면 상태창이 있는 인물 → 주역 → 첫 인물 (웹 `swLoad`).
    public static func pick(_ id: String, people: [StatPerson]) -> String {
        if people.contains(where: { $0.id == id }) { return id }
        return (people.first { $0.count > 0 } ?? people.first { $0.isMain } ?? people.first)?.id ?? ""
    }

    /// 서버로 보낼 항목: 이름이 빈 줄은 빼고, 값은 적은 그대로 보낸다.
    /// '+3', '+300', '+독 내성', '-은신' 은 서버가 저장한 값에 맞춰 계산한다 (`statwin.resolve`, `set_stats`).
    public static func outgoing(_ rows: [StatRow], current: [StatValue]) -> [StatValue] {
        rows.compactMap { r in
            let name = r.name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty else { return nil }
            return StatValue(name: name, value: r.value.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    /// 틀 이름 (웹 `swEditor` 의 틀 버튼).
    public static func presetLabel(_ key: String) -> String {
        ["game": "게임 판타지", "hunter": "헌터물", "simple": "레벨 · 스킬", "growth": "스킬 · 특성 · 돈"][key] ?? key
    }

    /// 서버는 틀을 dict 로 보내 순서가 사라진다. 서버 `PRESETS` 순서(게임 판타지, 헌터물, 레벨 · 스킬, 스킬 · 특성 · 돈)로, 모르는 틀은 뒤에 이름 순으로.
    public static func presetOrder(_ keys: [String]) -> [String] {
        let known = ["game", "hunter", "simple", "growth"]
        return known.filter(keys.contains) + keys.filter { !known.contains($0) }.sorted()
    }

    /// '3화까지 기록', '기록 없음'
    public static func recorded(_ v: StatwinView) -> String {
        v.columns.last.map { "\($0.episode)화까지 기록" } ?? "기록 없음"
    }

    /// 비교표 머리 칸: 0 은 '시작'.
    public static func columnTitle(_ episode: Int) -> String { episode == 0 ? "시작" : "\(episode)화" }

    /// 인물 목록 오른쪽: '3항목'
    public static func count(_ n: Int) -> String { n > 0 ? "\(n)항목" : "" }

    /// 본문에 넣을 글. 값이 있는 항목이 없으면 안내.
    public static func preview(_ v: StatwinView) -> String { v.text.isEmpty ? "(값이 있는 항목이 없어요)" : v.text }
}

/// 화별 비교표의 칸 하나 (웹 `swTimeline`).
public enum StatCell: Equatable, Sendable {
    /// 그 화에 바뀌지 않았다.
    case plain(String)
    /// 그 화에 바뀌었다. author 는 작가가 고쳤거나 승인 뒤 작가가 또 고쳤다.
    case changed(String, author: Bool, tip: String)
    /// 그 화에 지웠다. 이전 값을 지운 줄로 보인다.
    case gone(String, tip: String)

    public init(_ column: Components.Schemas.StatColumn, name: String) {
        let v = column.values.additionalProperties[name] ?? ""
        guard let ch = column.changed.additionalProperties[name] else {
            self = .plain(v)
            return
        }
        let suffix = ["ai": "", "author": " (작가)", "both": " (승인 뒤 작가가 고침)"][ch.source.rawValue] ?? ""
        let tip = "\(ch.before.isEmpty ? "없음" : ch.before) → \(v.isEmpty ? "지움" : v)\(suffix)"
        self = v.isEmpty ? .gone(ch.before, tip: tip) : .changed(v, author: ch.source != .ai, tip: tip)
    }
}

/// 서버에 붙는 상태창 화면. 작품 전체는 `ProjectLoader` 로 판(ETag)과 함께 받는다.
public struct LiveStatWin: StatWinSource {
    let server: CanonServer
    let loader: ProjectLoader

    public init(server: CanonServer) {
        self.server = server
        self.loader = ProjectLoader(server: server)
    }

    public func project(_ name: String) async throws -> Project {
        try await loader.load(name)
    }

    public func view(_ name: String, character: String) async throws -> StatwinView {
        switch try await server.call({ try await $0.statwinView(path: .init(name: name, cid: character)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func save(_ name: String, character: String, stats: [StatValue]) async throws -> Project {
        let out = try await server.call({
            try await $0.statwinSet(path: .init(name: name, cid: character), body: .json(.init(stats: stats)))
        })
        switch out {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func saveTemplate(_ name: String, template: String, row: String) async throws -> Project {
        let out = try await server.call({
            try await $0.statwinTemplate(path: .init(name: name), body: .json(.init(template: template, row: row)))
        })
        switch out {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
