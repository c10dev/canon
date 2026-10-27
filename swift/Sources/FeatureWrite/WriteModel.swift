import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 집필 화면이 부르는 서버. 시험에서는 가짜로 바꾼다.
/// 본문을 바꾸는 호출은 저장된 작품을 돌려주고, 화면은 그 화를 연 작품(`ProjectDocument.merge`)에 받아 온다.
public protocol WriteServing: Sendable {
    /// 직접 고친 본문 저장 (`PUT .../episodes/{n}/text`, 서버가 순서 규칙과 수정 기록을 맡는다)
    func saveText(_ project: String, ep: Int, text: String) async throws -> Project
    func rewriteInfo(_ project: String, ep: Int) async throws -> RewriteInfo
    func rewritePrompt(_ project: String, ep: Int, request: RewriteRequest) async throws -> String
    func adopt(_ project: String, ep: Int) async throws -> Project
    func dropCandidate(_ project: String, ep: Int) async throws -> Project
    func restore(_ project: String, ep: Int, version: String) async throws -> Project
    func formats() async throws -> [PublishFormat]
    func export(_ project: String, episodes: [Int], format: String, title: Bool, drafts: [Int: String]) async throws -> ExportOut
}

/// 집필 화면 (웹 `viewWrite`, `rewrite.js`, `publish.js`). 본문 초안은 작품 저장과 따로 '본문 저장'으로 저장한다 (웹 `S.textDraft`).
/// 쓰기 · 검수 · 다시 생성은 `JobCenter` 작업이고, 작업이 쓴 화는 `JobCenter` 가 받아 온다.
@MainActor
@Observable
public final class WriteModel {
    public let document: ProjectDocument
    public let jobs: JobCenter
    private let service: any WriteServing
    private let defaults: UserDefaults?

    /// 보는 화. nil 이면 지금 작업해야 할 화 (웹 `currentEp`).
    public var picked: Int?
    /// 화 → 저장하지 않은 본문 초안. '직접 쓰기'는 빈 초안을 연다.
    public private(set) var drafts: [Int: String] = [:] {
        didSet { Self.kept[document.name] = drafts }
    }
    /// 작품 → 본문 초안. 다른 화면에 다녀와도 초안이 남는다 (웹 `S.textDraft` 처럼 앱이 도는 동안만).
    static var kept: [String: [Int: String]] = [:]
    /// 진행 중인 저장 · 불러오기 (단추를 막는다).
    public private(set) var busy: String?
    public private(set) var notice: (text: String, isError: Bool)?

    // 다시 생성
    public var rewriteOpen = false
    public private(set) var rewriteInfo: [Int: RewriteInfo] = [:]
    public var rewrite: [Int: RewriteDraft] = [:]
    public private(set) var rewritePrompt: String?
    public enum CompareMode: String, Sendable { case side, diff }
    public var compare: CompareMode = .side
    /// 이전 판 목록에서 펼친 판 id.
    public var peek: String?

    // 복사 · 내보내기
    public private(set) var formats: [PublishFormat] = []
    public var format: String {
        didSet { defaults?.set(format, forKey: Self.formatKey) }
    }
    public var withTitle: Bool {
        didSet { defaults?.set(withTitle ? "1" : "0", forKey: Self.titleKey) }
    }
    /// 여러 화 범위. nil 이면 쓴 첫 화 · 마지막 화.
    public var copyFrom: Int?
    public var copyTo: Int?

    static let formatKey = "canon.copyFmt"
    static let titleKey = "canon.copyTitle"

    public init(document: ProjectDocument, jobs: JobCenter, service: any WriteServing, defaults: UserDefaults? = .standard) {
        self.document = document
        self.jobs = jobs
        self.service = service
        self.defaults = defaults
        format = defaults?.string(forKey: Self.formatKey) ?? PublishText.defaultFormat
        withTitle = (defaults?.string(forKey: Self.titleKey) ?? "1") == "1"
        drafts = Self.kept[document.name] ?? [:]
    }

    // MARK: 화

    public var episodes: [Episode] { document.project?.episodes ?? [] }

    /// 보는 화 번호.
    public var number: Int {
        if let picked, episodes.contains(where: { $0.plot.number == picked }) { return picked }
        guard let last = episodes.last else { return 1 }
        return episodes.first { WriteText.status($0) != .finalized }?.plot.number ?? last.plot.number
    }

    public var episode: Episode? { episodes.first { $0.plot.number == number } }

    public func episode(_ n: Int) -> Episode? { episodes.first { $0.plot.number == n } }

    public var previous: Int? { episodes.map(\.plot.number).filter { $0 < number }.last }
    public var next: Int? { episodes.map(\.plot.number).first { $0 > number } }

    /// 화면에 보일 본문: 고칠 수 있는 화는 초안이 있으면 초안 (웹 `textNow`).
    public func text(_ n: Int) -> String {
        guard let e = episode(n) else { return "" }
        if WriteText.editable(e), let d = drafts[n] { return d }
        return e.text ?? ""
    }

    public func setDraft(_ n: Int, _ text: String) {
        guard let e = episode(n), WriteText.editable(e) else { return }
        drafts[n] = text
    }

    /// 빈 칸을 열어 직접 쓴다 (웹 `startManual`).
    public func startManual(_ n: Int) {
        drafts[n] = ""
    }

    public func discardDraft(_ n: Int) {
        drafts[n] = nil
    }

    /// 고칠 수 있는 화의 저장하지 않은 본문.
    public func unsaved(_ n: Int) -> Bool {
        guard let e = episode(n), WriteText.editable(e) else { return false }
        return WriteText.unsaved(draft: drafts[n], saved: e.text ?? "")
    }

    /// 반영이 끝나 고칠 수 없는 화에 남은 초안 (웹 `orphan`). 플롯 초안으로 돌아간 화에 생긴다.
    public func orphan(_ n: Int) -> String? {
        guard let e = episode(n), !WriteText.editable(e), let d = drafts[n], !d.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return d
    }

    public func blocked(_ n: Int) -> [Int] { WriteText.blockedBefore(n, in: episodes) }

    /// 이 화를 쓰는 작업이 돈다 (처음 쓰기와 다시 생성).
    public func writing(_ n: Int) -> Bool { jobs.running("write", ep: n) != nil }

    public func dismissNotice() { notice = nil }

    // MARK: 본문 저장

    /// 본문 초안을 저장한다. 저장하지 않은 작품 변경이 있으면 먼저 저장한다 (웹 `saveText` 의 `saveIfDirty`).
    @discardableResult
    public func saveText(_ n: Int) async -> Bool {
        guard busy == nil, drafts[n] != nil else { return false }
        busy = "본문 저장 중"
        defer { busy = nil }
        do {
            try await flush(n, always: true)
            notice = ("본문을 저장했어요", false)
            return true
        } catch {
            notice = (CanonError.message(error), true)
            return false
        }
    }

    /// 초안이 있으면 저장하고 그 화를 받아 온다 (웹 `flushText`). `always` 는 초안이 저장본과 같아도 보낸다.
    private func flush(_ n: Int, always: Bool = false) async throws {
        guard let draft = drafts[n] else { return }
        if !always && !WriteText.unsaved(draft: draft, saved: episode(n)?.text ?? "") {
            drafts[n] = nil
            return
        }
        if document.dirty, await document.save() == false, document.dirty {
            throw CanonError.badResponse(document.error ?? "작품을 저장하지 못했어요")
        }
        _ = try await service.saveText(document.name, ep: n, text: draft)
        drafts[n] = nil
        await document.merge { _, e in e.plot.number == n }
    }

    // MARK: 작업

    /// 본문 생성 (웹 `writeEp`). 앞 화가 반영되지 않았으면 시작하지 않는다 (설계 원칙 '순서를 지킨다').
    @discardableResult
    public func write(_ n: Int) async -> Bool {
        guard blocked(n).isEmpty else { return false }
        return await jobs.start(JobRequest(kind: "write", ep: n))
    }

    /// 검수 (웹 `checkEp`). 저장한 본문을 검수한다.
    @discardableResult
    public func check(_ n: Int) async -> Bool {
        await jobs.start(JobRequest(kind: "check", ep: n))
    }

    // MARK: 다시 생성

    /// 다시 생성 패널을 연다. 재료는 본문과 수정 기록에 따라 바뀌니 열 때마다 새로 받는다 (웹 `rwOpen`).
    public func openRewrite(_ n: Int) async {
        rewriteOpen = true
        rewritePrompt = nil
        do {
            let info = try await service.rewriteInfo(document.name, ep: n)
            rewriteInfo[n] = info
            if rewrite[n] == nil { rewrite[n] = RewriteDraft(info: info) }
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    /// 새 판 · 이전 판의 요청에 빠른 요청 이름을 붙이려고 받는다 (패널을 열지 않았을 때).
    public func loadRewriteInfo(_ n: Int) async {
        guard rewriteInfo.isEmpty, let info = try? await service.rewriteInfo(document.name, ep: n) else { return }
        rewriteInfo[n] = info
    }

    /// 빠른 요청 id → 이름.
    public var presetLabels: [String: String] {
        Dictionary(rewriteInfo.values.flatMap(\.presets).map { ($0.id, $0.label) }, uniquingKeysWith: { a, _ in a })
    }

    public func closeRewrite() {
        rewriteOpen = false
        rewritePrompt = nil
    }

    /// 고르는 중인 요청을 바꾼다. 펼친 프롬프트는 닫는다.
    public func editRewrite(_ n: Int, _ change: (inout RewriteDraft) -> Void) {
        var r = rewrite[n] ?? RewriteDraft()
        change(&r)
        rewrite[n] = r
        rewritePrompt = nil
    }

    /// 살릴 부분을 담는다. 못 담으면 알린다.
    public func addKeep(_ n: Int, _ text: String) {
        var r = rewrite[n] ?? RewriteDraft()
        if let why = r.add(keep: text, max: rewriteInfo[n]?.keepMax ?? 5) {
            notice = (why, why != "이미 담은 부분이에요")
            return
        }
        rewrite[n] = r
        rewritePrompt = nil
    }

    /// 보낼 프롬프트 보기 · 닫기 (웹 `rwShowPrompt`).
    public func toggleRewritePrompt(_ n: Int) async {
        if rewritePrompt != nil {
            rewritePrompt = nil
            return
        }
        busy = "불러오는 중"
        defer { busy = nil }
        do {
            try await flush(n)
            let x = try await service.rewritePrompt(document.name, ep: n, request: (rewrite[n] ?? RewriteDraft()).request)
            rewritePrompt = x
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    /// 새 판 만들기 (웹 `rwSubmit`). 고쳐 쓰기는 저장한 본문을 보내므로 초안을 먼저 저장한다.
    @discardableResult
    public func submitRewrite(_ n: Int) async -> Bool {
        let r = rewrite[n] ?? RewriteDraft()
        do {
            try await flush(n)
        } catch {
            notice = (CanonError.message(error), true)
            return false
        }
        rewriteOpen = false
        rewritePrompt = nil
        var request = JobRequest(kind: "write", ep: n)
        request.rewrite = Self.json(r.request)
        return await jobs.start(request)
    }

    nonisolated static func json(_ r: RewriteRequest) -> JSONValue? {
        guard let data = try? JSONEncoder().encode(r) else { return nil }
        return try? JSONDecoder().decode(JSONValue.self, from: data)
    }

    /// 새 판으로 바꾸기 (웹 `rwAdopt`). 지금 본문은 이전 판에 남는다.
    public func adopt(_ n: Int) async {
        await change("바꾸는 중", RewriteText.adopted, n) { [service] name in
            _ = try await service.adopt(name, ep: n)
        }
        if notice?.isError == false { rewrite[n] = nil }
    }

    /// 지금 판 두기 (웹 `rwDrop`).
    public func dropCandidate(_ n: Int) async {
        await change("정리 중", RewriteText.dropped, n, flushFirst: false) { [service] name in
            _ = try await service.dropCandidate(name, ep: n)
        }
    }

    /// 요청 고쳐 다시: 새 판을 만든 요청으로 패널을 연다 (웹 `rwAgain`).
    public func rewriteAgain(_ n: Int) async {
        if let req = episode(n)?.candidate?.request { rewrite[n] = RewriteDraft(req) }
        await openRewrite(n)
    }

    /// 이전 판으로 되돌리기 (웹 `rwRestore`). 묻는 일은 화면이 한다.
    public func restore(_ n: Int, version: String) async {
        await change("되돌리는 중", RewriteText.restored, n, flushFirst: false) { [service] name in
            _ = try await service.restore(name, ep: n, version: version)
        }
        if notice?.isError == false { peek = nil }
    }

    /// 이전 판 복원은 저장하지 않은 본문이 있으면 막는다 (웹 `versionsPanel` 의 `can`).
    public func canRestore(_ n: Int) -> Bool {
        guard let e = episode(n) else { return false }
        return WriteText.editable(e) && drafts[n] == nil
    }

    private func change(_ label: String, _ done: String, _ n: Int, flushFirst: Bool = true, _ call: (String) async throws -> Void) async {
        guard busy == nil else { return }
        busy = label
        defer { busy = nil }
        do {
            if flushFirst { try await flush(n) }
            try await call(document.name)
            await document.merge { _, e in e.plot.number == n }
            notice = (done, false)
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    // MARK: 복사 · 내보내기

    public func loadFormats() async {
        guard formats.isEmpty else { return }
        formats = (try? await service.formats()) ?? []
    }

    /// 본문이 있는 화 (저장하지 않은 초안 포함, 웹 `writtenNums`).
    public var writtenNumbers: [Int] {
        episodes.filter { !($0.text ?? "").isEmpty || (WriteText.editable($0) && drafts[$0.plot.number] != nil) }.map(\.plot.number)
    }

    public var range: (from: Int, to: Int) {
        PublishText.range(writtenNumbers, picked: (copyFrom, copyTo))
    }

    public func setRange(from: Int? = nil, to: Int? = nil) {
        let last = writtenNumbers.last ?? 1
        if let from { copyFrom = PublishText.clamp(from, last: last) }
        if let to { copyTo = PublishText.clamp(to, last: last) }
    }

    /// 붙여 넣을 글을 받는다. 저장하지 않은 초안이 있으면 그 초안으로 (웹 `exportBody`). 범위에 본문이 없으면 알리고 nil.
    public func export(_ numbers: [Int]) async -> ExportOut? {
        let eps = numbers.filter { writtenNumbers.contains($0) }
        guard !eps.isEmpty else {
            notice = (PublishText.emptyRange, true)
            return nil
        }
        var live: [Int: String] = [:]
        for n in eps {
            if let e = episode(n), WriteText.editable(e), let d = drafts[n] { live[n] = d }
        }
        do {
            return try await service.export(document.name, episodes: eps, format: format, title: withTitle, drafts: live)
        } catch {
            notice = (CanonError.message(error), true)
            return nil
        }
    }

    /// 복사한 뒤 화면이 부른다.
    public func copied(_ out: ExportOut) {
        notice = (PublishText.copied(out), false)
    }

    public func copyFailed(_ message: String) {
        notice = (message, true)
    }
}
