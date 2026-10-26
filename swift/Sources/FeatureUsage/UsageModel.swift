import CanonAPI
import CanonCore
import Foundation
import Observation

/// 사용량과 가격표를 주고받는 곳. 시험에서는 가짜로 바꾼다.
public protocol UsageSource: Sendable {
    /// `GET /api/usage`. days 가 0 이면 전체, project 가 비면 모든 작품.
    func summary(days: Int, project: String, limit: Int) async throws -> UsageSummary
    func prices() async throws -> PriceTable
    func savePrices(_ rows: [PriceIn]) async throws -> PriceTable
    func resetPrices() async throws -> PriceTable
    /// 작품 고르기에 쓸 폴더 이름 → 제목. 실패해도 화면은 열린다.
    func projectTitles() async -> [String: String]
}

/// 고치는 중인 가격표 한 줄. 숫자 칸은 적는 중인 글 그대로 둔다 ('0.' 을 적는 중에도 지워지지 않게).
public struct PriceDraft: Equatable, Sendable, Identifiable {
    public enum Field: String, CaseIterable, Sendable {
        case input, output, cached, batchInput, batchOutput

        /// 칸 이름 (`PRICE_COLS`).
        public var label: String {
            switch self {
            case .input: "입력"
            case .output: "출력"
            case .cached: "캐시 입력"
            case .batchInput: "배치 입력"
            case .batchOutput: "배치 출력"
            }
        }
    }

    public let id: UUID
    public var model: String
    public var since: String
    public var input: String
    public var output: String
    public var cached: String
    public var batchInput: String
    public var batchOutput: String
    public var note: String
    /// 서버에서 받은 줄만 값이 있다. 새로 더한 줄은 nil.
    public var custom: Bool?
    public var current = false
    public var upcoming = false

    public init(model: String = "", since: String = "", input: String = "0", output: String = "0", cached: String = "",
                batchInput: String = "", batchOutput: String = "", note: String = "") {
        id = UUID()
        self.model = model
        self.since = since
        self.input = input
        self.output = output
        self.cached = cached
        self.batchInput = batchInput
        self.batchOutput = batchOutput
        self.note = note
    }

    public init(_ r: PriceRow) {
        self.init(model: r.model, since: r.since, input: UsageText.plain(r.input), output: UsageText.plain(r.output),
                  cached: r.cached.map(UsageText.plain) ?? "", batchInput: r.batchInput.map(UsageText.plain) ?? "",
                  batchOutput: r.batchOutput.map(UsageText.plain) ?? "", note: r.note)
        custom = r.custom
        current = r.current
        upcoming = r.upcoming
    }

    public subscript(field: Field) -> String {
        get {
            switch field {
            case .input: input
            case .output: output
            case .cached: cached
            case .batchInput: batchInput
            case .batchOutput: batchOutput
            }
        }
        set {
            switch field {
            case .input: input = newValue
            case .output: output = newValue
            case .cached: cached = newValue
            case .batchInput: batchInput = newValue
            case .batchOutput: batchOutput = newValue
            }
        }
    }

    /// 칸 값. 빈 칸은 입력 · 출력이면 0, 나머지는 nil (서버가 입력 가격이나 절반으로 친다). 숫자가 아니면 nan.
    public func value(_ field: Field) -> Double? {
        let t = self[field].trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return field == .input || field == .output ? 0 : nil }
        return Double(t) ?? .nan
    }

    /// 빈 칸에 흐리게 보일 값: 캐시는 입력 가격, 배치는 절반.
    public func placeholder(_ field: Field) -> String {
        let i = value(.input).flatMap { $0.isNaN ? nil : $0 } ?? 0
        let o = value(.output).flatMap { $0.isNaN ? nil : $0 } ?? 0
        switch field {
        case .cached: return UsageText.plain(i)
        case .batchInput: return UsageText.plain(i / 2)
        case .batchOutput: return UsageText.plain(o / 2)
        default: return ""
        }
    }

    /// 줄 표시: 고침 · 예고 · 지금.
    public var status: String {
        if custom == true { return "고침" }
        if upcoming { return "예고" }
        return current ? "지금" : ""
    }

    /// 기본 줄은 지울 수 없다 (지워도 저장하면 되살아난다). 값을 고쳐 덮어쓴다.
    public var fixed: Bool { custom == false }

    var named: Bool { !model.trimmingCharacters(in: .whitespaces).isEmpty }

    var sent: PriceIn {
        PriceIn(model: model.trimmingCharacters(in: .whitespaces), since: since, input: value(.input), output: value(.output),
                cached: value(.cached), batchInput: value(.batchInput), batchOutput: value(.batchOutput), note: note)
    }
}

/// 사용량 · 비용 화면 상태. 웹 `usage.js` 의 `S.usage*` · `S.price*` 와 같다.
@MainActor
@Observable
public final class UsageModel {
    public private(set) var summary: UsageSummary?
    public private(set) var days = 30
    /// '' 이면 모든 작품.
    public private(set) var project: String
    public var list: UsageList = .recent
    /// 호출 목록을 20건 넘게 펼침.
    public private(set) var showAll = false
    /// 서버에서 받는 최근 호출 수 ('더 불러오기'로 늘린다).
    public private(set) var limit = 60
    /// 차트에서 고른 막대 (날짜 키).
    public var bar: String?
    public private(set) var titles: [String: String] = [:]
    public private(set) var prices: PriceTable?
    public private(set) var rows: [PriceDraft] = []
    public private(set) var dirty = false
    public private(set) var busy: String?
    public private(set) var notice: (text: String, isError: Bool)?
    private let source: any UsageSource

    /// 작품 안에서 열면 그 작품만 본다 (웹 `#/p/<이름>/usage`).
    public init(source: any UsageSource, project: String = "") {
        self.source = source
        self.project = project
    }

    // MARK: 사용량

    public func load() async {
        await run("불러오는 중") {
            async let u = source.summary(days: days, project: project, limit: limit)
            async let t = source.projectTitles()
            let table = prices == nil ? try await source.prices() : nil
            summary = try await u
            titles = await t
            bar = nil
            if let table { setPrices(table) }
        }
    }

    public func setDays(_ d: Int) async {
        days = d
        await load()
    }

    public func setProject(_ p: String) async {
        project = p
        await load()
    }

    public func expand() { showAll = true }

    public func loadMore() async {
        limit = min(1000, limit + 200)
        showAll = true
        await load()
    }

    public var projectChoices: [String] {
        UsageText.projectChoices(titles: titles, recorded: summary?.projects ?? [], current: project)
    }

    /// 지금 탭의 호출 전부와 보일 것.
    public var calls: (all: [UsageCall], shown: [UsageCall]) {
        guard let u = summary else { return ([], []) }
        let all = list == .trouble ? u.trouble : u.recent
        return (all, showAll ? all : Array(all.prefix(20)))
    }

    public var moreLine: UsageText.MoreLine? {
        guard let u = summary else { return nil }
        let c = calls
        return UsageText.moreLine(u, list: list, all: c.all.count, shown: c.shown.count, limit: limit)
    }

    public func dismissNotice() { notice = nil }

    /// 화면이 막은 동작의 이유 (저장 전 확인에서 막힌 줄).
    public func showError(_ text: String) { notice = (text, true) }

    // MARK: 가격표

    private func setPrices(_ table: PriceTable) {
        prices = table
        rows = table.rows.map(PriceDraft.init)
        dirty = false
    }

    /// 칸 하나 고치기.
    public func edit(_ id: PriceDraft.ID, _ change: (inout PriceDraft) -> Void) {
        guard let i = rows.firstIndex(where: { $0.id == id }) else { return }
        change(&rows[i])
        dirty = true
    }

    public func addRow() {
        rows.append(PriceDraft())
        dirty = true
    }

    /// '가격 없는 모델' 경고에서: 그 이름으로 줄을 더한다. 이미 있으면 그 줄. 옮겨 갈 줄 id 를 돌려준다.
    @discardableResult
    public func addModel(_ model: String) -> PriceDraft.ID {
        if let r = rows.first(where: { $0.model.trimmingCharacters(in: .whitespaces) == model }) { return r.id }
        rows.append(PriceDraft(model: model))
        dirty = true
        return rows[rows.count - 1].id
    }

    public func removeRow(_ id: PriceDraft.ID) {
        rows.removeAll { $0.id == id }
        dirty = true
    }

    public func cancelEdits() {
        if let prices { setPrices(prices) }
    }

    public var canReset: Bool { prices?.rows.contains { $0.custom } ?? false }

    /// 저장 전 확인.
    public enum SaveCheck: Equatable, Sendable {
        case ready
        /// 고칠 줄이 있다. 저장하지 않는다.
        case blocked(String, PriceDraft.ID)
        /// 저장할지 물어본다.
        case confirm(String)
    }

    public func checkSave() -> SaveCheck {
        // 웹처럼 0 이나 빈 칸만 있는 줄은 값이 없는 줄로 본다
        let hasValue = { (r: PriceDraft) in
            PriceDraft.Field.allCases.contains { f in r.value(f).map { $0 != 0 && !$0.isNaN } ?? false }
                || !r.since.trimmingCharacters(in: .whitespaces).isEmpty
        }
        if let i = rows.firstIndex(where: { !$0.named && hasValue($0) }) {
            return .blocked("\(i + 1)번째 줄에 모델 이름을 적으세요. 이름이 없으면 그 줄은 저장되지 않아요", rows[i].id)
        }
        if let i = rows.firstIndex(where: { r in r.named && PriceDraft.Field.allCases.contains { r.value($0)?.isNaN == true } }) {
            return .blocked("\(i + 1)번째 줄의 가격을 숫자로 적으세요", rows[i].id)
        }
        let free = rows.filter { $0.named && !(($0.value(.input) ?? 0) > 0 && ($0.value(.output) ?? 0) > 0) }
            .map { $0.model.trimmingCharacters(in: .whitespaces) }
        if !free.isEmpty {
            return .confirm("\(free.joined(separator: ", "))의 입력이나 출력 가격이 0원이에요. 비용이 0원으로 계산돼요. 이대로 저장할까요?")
        }
        return .ready
    }

    public nonisolated static let resetQuestion = "고친 가격을 모두 지우고 기본 가격표로 되돌릴까요?"

    /// 확인을 마친 뒤 저장한다. 이름 없는 줄은 보내지 않는다.
    public func save() async {
        let sent = rows.filter(\.named).map(\.sent)
        await changePrices("가격표 저장 중", done: "가격표를 저장했어요. 비용을 다시 계산했어요") {
            try await self.source.savePrices(sent)
        }
    }

    public func reset() async {
        await changePrices("되돌리는 중", done: "기본 가격표로 되돌렸어요") { try await self.source.resetPrices() }
    }

    private func changePrices(_ label: String, done: String, _ send: @escaping () async throws -> PriceTable) async {
        await run(label) {
            setPrices(try await send())
            if summary != nil {
                summary = try await source.summary(days: days, project: project, limit: limit)
            }
            notice = (done, false)
        }
    }

    private func run(_ label: String, _ body: () async throws -> Void) async {
        busy = label
        defer { busy = nil }
        do {
            try await body()
        } catch {
            notice = (CanonError.message(error), true)
        }
    }
}

/// 서버에서 사용량과 가격표를 받는다.
public struct LiveUsageSource: UsageSource {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    public func summary(days: Int, project: String, limit: Int) async throws -> UsageSummary {
        switch try await server.call({ try await $0.usageSummary(query: .init(days: days, project: project, limit: limit)) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw Self.invalid(try bad.body.json)
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func prices() async throws -> PriceTable {
        switch try await server.call({ try await $0.usagePrices() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func savePrices(_ rows: [PriceIn]) async throws -> PriceTable {
        switch try await server.call({ try await $0.putUsagePrices(body: .json(.init(rows: rows))) }) {
        case let .ok(ok): return try ok.body.json
        case let .unprocessableContent(bad): throw Self.invalid(try bad.body.json)
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func resetPrices() async throws -> PriceTable {
        switch try await server.call({ try await $0.resetUsagePrices() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func projectTitles() async -> [String: String] {
        guard case let .ok(ok)? = try? await server.call({ try await $0.listProjects() }),
              let cards = try? ok.body.json else { return [:] }
        return Dictionary(cards.map { ($0.name, $0.title.trimmingCharacters(in: .whitespacesAndNewlines)) }) { a, _ in a }
    }

    /// 422 본문을 다른 실패와 같은 문구로 (`CanonError.from`).
    static func invalid(_ body: Components.Schemas.HTTPValidationError) -> CanonError {
        CanonError.from(status: 422, body: (try? JSONEncoder().encode(body)) ?? Data())
    }
}
