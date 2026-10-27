import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 상태 승인 화면이 서버에 보내는 것. 반영 · 다시 맞추기 · 그대로 두기 · 반영 취소는 저장한 작품을 돌려준다. 시험에서는 가짜로 바꾼다.
public protocol ReviewService: Sendable {
    /// 고른 항목만 담긴 변경안을 반영하고 그 화를 끝낸다 (`POST .../episodes/{n}/apply`).
    func apply(_ project: String, ep: Int, delta: StateDelta) async throws
    /// 반영 뒤 고친 화: 고른 요약 · 새 사실 · 새 복선 · 새 장소만 반영한다 (`POST .../episodes/{n}/restate`).
    func restate(_ project: String, ep: Int, delta: StateDelta) async throws
    /// 반영 뒤 고쳤지만 상태는 그대로 둔다 (`POST .../episodes/{n}/keep-state`).
    func keepState(_ project: String, ep: Int) async throws
    /// `after` 화 반영 직후로 되돌린다 (`POST .../revert/{after}`).
    func revert(_ project: String, after: Int) async throws
    /// 고른 변경안으로 계산할 관계 (`POST .../episodes/{n}/preview`). 저장하지 않는다.
    func preview(_ project: String, ep: Int, delta: StateDelta) async throws -> RelationPreview
    /// 관계를 말로 · 숫자로 볼지 (`PUT .../view`).
    func setShowNumbers(_ project: String, _ show: Bool) async throws
}

/// 상태 승인 화면 상태 (웹 `viewReview` · `restateCard`). 변경안은 작업 결과(`JobCenter.results["state:<화>"]`)에서 읽고,
/// 화면에서 고친 요약 · 항목과 체크는 여기에 둔다. 반영하면 결과를 지우고 작품을 다시 받는다.
@MainActor
@Observable
public final class ReviewModel {
    public let document: ProjectDocument
    public let jobs: JobCenter
    /// 보는 화.
    public private(set) var ep: Int
    /// 고치는 중인 변경안. nil 이면 아직 없다.
    public private(set) var draft: StateDelta?
    /// 체크한 항목 키 ('c0', 'e1' …, `ReviewText.pickPrefixes`).
    public var picks: Set<String> = []
    /// 다시 맞추기 카드의 체크 ('sum', 'f0', 'p0', 'l0').
    public var restatePicks: Set<String> = []
    /// 변경안을 만든 본문. 그 뒤 본문을 고쳤으면 알린다 (웹 `S.deltaBase`).
    public private(set) var base: String?
    /// 반영 취소로 되살린 변경안이다 (작업 결과가 아니다).
    public private(set) var fromHistory = false
    public private(set) var preview: RelationPreview?
    public private(set) var previewError: String?
    public private(set) var showNumbers = false
    public private(set) var busy = false
    public private(set) var notice: (text: String, isError: Bool)?
    /// 반영한 뒤 다음 화 집필로 갈 수 있다 (알림 옆 단추).
    public private(set) var nextWrite: Int?
    private let service: any ReviewService
    /// 지금 변경안을 만든 결과 id 와 받은 그대로의 변경안 · 체크. 다시 만들 때 고친 것을 버리는지 묻는다.
    private var source: String?
    private var original: (delta: StateDelta, picks: Set<String>)?
    /// 볼 화를 정했다 (만들 때 받았거나 작품을 받아 골랐다).
    private var chosen: Bool

    public init(document: ProjectDocument, jobs: JobCenter, service: any ReviewService, ep: Int? = nil) {
        self.document = document
        self.jobs = jobs
        self.service = service
        self.ep = ep ?? 1
        chosen = ep != nil
        if ep == nil, let p = document.project { self.ep = Self.defaultEpisode(p); chosen = true }
    }

    /// 처음 볼 화: 본문만 있고 반영하지 않은 첫 화, 없으면 반영이 끝나지 않은 첫 화, 그것도 없으면 마지막 화.
    public static func defaultEpisode(_ p: Project) -> Int {
        let eps = p.episodes ?? []
        if let w = eps.first(where: { $0.status == .written }) { return w.plot.number }
        if let open = eps.first(where: { $0.status != .finalized }) { return open.plot.number }
        return eps.last?.plot.number ?? 1
    }

    public var project: Project? { document.project }
    public var episode: Episode? { project?.episodes?.first { $0.plot.number == ep } }
    public var key: String { Job.key("state", ep) }
    /// 화면이 지켜볼 결과 id. 바뀌면 `sync` 한다.
    public var resultID: String? { jobs.results[key]?.id }
    /// 자동 집필이 도는 동안은 반영하지 않는다 (웹 `autoOn`).
    public var autoRunning: Bool { jobs.running("auto") != nil }
    public var extractLabel: String? { jobs.busyLabel("state", ep: ep) }
    public var failure: PendingFailure? { jobs.failures[key] }

    /// 작품을 받은 뒤 처음 볼 화를 정한다 (작품을 아직 받지 못한 채 만들었으면).
    public func start() async {
        await document.load()
        if !chosen, let p = document.project { ep = Self.defaultEpisode(p); chosen = true }
        showNumbers = document.project?.settings?.showNumbers ?? false
        sync()
    }

    public func select(_ n: Int) {
        chosen = true
        guard n != ep else { return }
        ep = n
        draft = nil
        source = nil
        fromHistory = false
        nextWrite = nil
        preview = nil
        sync()
    }

    /// 작업 결과를 변경안으로 놓는다. 같은 결과면 고친 것을 그대로 둔다 (웹 `loadPending` · `applyJobResult` · `setDelta`).
    public func sync() {
        guard let result = jobs.results[key] else {
            if !fromHistory { draft = nil; source = nil }
            return
        }
        guard result.id != source, let d = try? result.result.decode(StateDelta.self), let p = project else { return }
        source = result.id
        fromHistory = false
        // 서버가 기억한 '만든 본문'이 없으면(이 실행에서 끝난 작업) 지금 본문으로 둔다
        base = result.base ?? episode?.text ?? ""
        set(d, project: p)
    }

    private func set(_ d: StateDelta, project p: Project) {
        draft = d
        picks = ReviewText.defaultPicks(d, project: p)
        restatePicks = ReviewText.restatePicks(d, p)
        original = (d, picks)
        preview = nil
        previewError = nil
    }

    // MARK: 고치기

    /// 변경안을 고친다 (요약, 사실, 인물 상태 칸 등). 체크는 그대로.
    public func edit(_ change: (inout StateDelta) -> Void) {
        guard var d = draft else { return }
        change(&d)
        draft = d
    }

    public func toggle(_ key: String) {
        if picks.contains(key) { picks.remove(key) } else { picks.insert(key) }
    }

    public func toggleRestate(_ key: String) {
        if restatePicks.contains(key) { restatePicks.remove(key) } else { restatePicks.insert(key) }
    }

    /// 받은 뒤 요약 · 항목 · 체크를 고쳤다. 다시 만들면 버려진다 (웹 `extractState` 의 `edited`).
    public var edited: Bool {
        guard let d = draft, let o = original else { return false }
        return d != o.delta || picks != o.picks
    }

    /// 변경안을 만든 뒤 본문을 고쳤다.
    public var textChanged: Bool {
        guard draft != nil, let base, let e = episode else { return false }
        return base != (e.text ?? "")
    }

    public var total: Int { draft.map(ReviewText.total) ?? 0 }
    public var pickedCount: Int { picks.count }
    public var picked: StateDelta? { draft.map { ReviewText.picked($0, picks) } }

    /// 반영 전에 물을 까닭. 비면 바로 반영한다.
    public var applyReasons: [String] {
        guard let out = picked else { return [] }
        return ReviewText.applyReasons(out, textChanged: textChanged)
    }

    // MARK: 서버

    /// 변경안을 만든다 (다시 만든다). 저장하지 않은 변경은 `JobCenter.start` 가 먼저 저장한다.
    public func extract() async {
        await jobs.start(JobRequest(kind: "state", ep: ep))
    }

    /// 변경안을 버린다.
    public func discard() async {
        await jobs.drop("state", ep: ep)
        draft = nil
        source = nil
        fromHistory = false
    }

    /// 고른 항목을 반영하고 이 화를 마친다 (웹 `applyDelta`).
    @discardableResult
    public func apply() async -> Bool {
        guard let out = picked else { return false }
        let n = ep
        return await run {
            try await self.service.apply(self.document.name, ep: n, delta: out)
            await self.finish()
            let next = self.project?.episodes?.first { $0.plot.number == n + 1 }
            self.nextWrite = next?.status == .confirmed ? n + 1 : nil
            self.notice = ("\(n)화를 마쳤어요", false)
        }
    }

    /// 반영 뒤 고친 화: 고른 요약 · 새 사실 · 새 복선 · 새 장소만 반영한다 (웹 `applyRestate`).
    @discardableResult
    public func applyRestate() async -> Bool {
        guard let d = draft else { return false }
        let n = ep
        let body = ReviewText.restateBody(d, restatePicks)
        return await run {
            try await self.service.restate(self.document.name, ep: n, delta: body)
            await self.finish()
            self.notice = (ReviewText.restateDone(n, body: body), false)
        }
    }

    /// 반영 뒤 고쳤지만 상태는 그대로 둔다 (웹 `keepState`).
    @discardableResult
    public func keepState() async -> Bool {
        let n = ep
        return await run {
            try await self.service.keepState(self.document.name, ep: n)
            await self.finish()
            self.notice = ("\(n)화 상태는 그대로 둘게요", false)
        }
    }

    /// 이 화 반영을 취소할 수 있다 (앞 화 반영 직후 스냅샷이 있다).
    public var canRevert: Bool {
        episode?.status == .finalized && (project?.snapshots ?? []).contains { $0.episode == ep - 1 }
    }

    /// 이 화부터 반영을 취소하고, 반영했던 변경안을 다시 고를 수 있게 둔다 (웹 `revertFrom`).
    @discardableResult
    public func revert() async -> Bool {
        let n = ep
        let h = history
        let fin = project.map { ReviewText.finalized(from: n, $0) } ?? []
        return await run {
            try await self.service.revert(self.document.name, after: n - 1)
            await self.document.reload()
            if let h, let p = self.project {
                self.set(h, project: p)
                self.source = nil
                self.fromHistory = true
                self.base = self.episode?.text ?? ""
            }
            self.notice = (ReviewText.revertDone(n, fin: fin), false)
        }
    }

    /// 이 화에 반영한 변경안 (마지막 것, 웹 `historyView`).
    public var history: StateDelta? {
        project?.history?.last { $0.episode == ep }
    }

    /// 체크를 바꿀 때마다 관계를 다시 계산한다. 화면이 잠깐 기다린 뒤 부른다 (웹 `refreshPreview`).
    public func refreshPreview() async {
        guard let out = picked else { return }
        do {
            preview = try await service.preview(document.name, ep: ep, delta: out)
            previewError = nil
        } catch {
            previewError = CanonError.message(error)
        }
    }

    /// 미리 보기를 다시 계산할 때를 가리는 값.
    public var previewKey: String { "\(ep)|\(source ?? "")|\(picks.sorted().joined(separator: ","))" }

    public func setShowNumbers(_ show: Bool) async {
        showNumbers = show
        do {
            try await service.setShowNumbers(document.name, show)
            await document.load()
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    public func dismissNotice() { notice = nil }

    /// 반영 · 다시 맞추기 · 그대로 두기 뒤: 결과를 지우고 작품을 다시 받는다.
    private func finish() async {
        await jobs.drop("state", ep: ep)
        draft = nil
        source = nil
        fromHistory = false
        base = nil
        await document.reload()
    }

    /// 저장하지 않은 변경을 먼저 저장하고 서버를 부른다 (웹 `run` · `saveIfDirty`).
    private func run(_ body: @escaping () async throws -> Void) async -> Bool {
        guard !busy else { return false }
        busy = true
        defer { busy = false }
        if document.dirty {
            await document.save()
            if document.dirty {
                notice = (document.error ?? "저장하지 못했어요", true)
                return false
            }
        }
        do {
            try await body()
            return true
        } catch {
            notice = (CanonError.message(error), true)
            return false
        }
    }
}
