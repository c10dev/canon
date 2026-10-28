import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 검수 화면이 서버에 보내는 것. 시험에서는 가짜로 바꾼다.
public protocol CheckService: Sendable {
    /// 지적의 처리 상태와 메모를 정한다 (`PUT .../episodes/{n}/findings/{id}`). note 를 비우면(nil) 메모는 그대로.
    func setFinding(_ project: String, ep: Int, id: String, status: CheckText.Status, note: String?) async throws
    /// 이번 화 문체 지표와 경고 (`GET .../episodes/{n}/style`). LLM 없이 잰다.
    func style(_ project: String, ep: Int) async throws -> StyleDrift
}

/// 검수 화면 상태 (웹 `check.js` 의 `viewCheck`). 지적과 회차는 작품(`Episode.findings` · `rounds`)에 있고,
/// 고른 지적 · 거르기 · 탭 · 메모 칸만 여기에 둔다. 상태를 바꾸면 그 화만 다시 받는다.
@MainActor
@Observable
public final class CheckModel {
    public enum Tab: String, CaseIterable, Sendable { case issues, style }

    public let document: ProjectDocument
    public let jobs: JobCenter
    /// 보는 화.
    public private(set) var ep: Int
    public var filter: CheckText.Filter = .open
    public var tab: Tab = .issues
    /// 화마다 고른 지적 id.
    public private(set) var chosen: [Int: String] = [:]
    /// 고른 지적의 메모 칸 (저장 전).
    public var note = ""
    private var noteFor: String?
    /// 화마다 받은 문체 지표, 또는 받지 못한 까닭.
    public private(set) var style: [Int: Result<StyleDrift, CanonError>] = [:]
    public private(set) var busy = false
    public private(set) var notice: (text: String, isError: Bool)?
    private let service: any CheckService
    private var picked: Bool

    public init(document: ProjectDocument, jobs: JobCenter, service: any CheckService, ep: Int? = nil) {
        self.document = document
        self.jobs = jobs
        self.service = service
        self.ep = ep ?? 1
        picked = ep != nil
        if ep == nil, let p = document.project { self.ep = Self.defaultEpisode(p); picked = true }
    }

    /// 처음 볼 화: 본문이 있고 반영하지 않았는데 검수가 끝나지 않은 첫 화, 없으면 반영하지 않은 첫 본문 화, 그것도 없으면 본문이 있는 마지막 화.
    public static func defaultEpisode(_ p: Project) -> Int {
        let eps = (p.episodes ?? []).filter { !($0.text ?? "").isEmpty }
        if let e = eps.first(where: { $0.status == .written && !$0.checkState.done }) { return e.plot.number }
        if let e = eps.first(where: { $0.status == .written }) { return e.plot.number }
        return eps.last?.plot.number ?? p.episodes?.first?.plot.number ?? 1
    }

    public var project: Project? { document.project }
    public var episodes: [Episode] { project?.episodes ?? [] }
    public var episode: Episode? { episodes.first { $0.plot.number == ep } }
    public var text: String { episode?.text ?? "" }
    public var selectedID: String? { episode.flatMap { CheckText.selected($0, chosen: chosen[ep]) } }
    public var selected: Finding? { episode?.findings?.first { $0.id == selectedID } }
    public var shown: [Finding] { episode.map { CheckText.list($0, filter) } ?? [] }
    public var marks: [CheckText.Mark] { episode.map { CheckText.marks($0, text: text, selected: selectedID) } ?? [] }
    /// 자동 집필이 도는 동안은 검수 · 상태 바꾸기를 하지 않는다 (웹 `autoOn`).
    public var autoRunning: Bool { jobs.running("auto") != nil }
    public var checkBusy: String? { jobs.busyLabel("check", ep: ep) }
    public var failure: PendingFailure? { jobs.failures[Job.key("check", ep)] }

    public func start() async {
        await document.load()
        if !picked, let p = project { ep = Self.defaultEpisode(p); picked = true }
        await loadStyle()
    }

    public func select(_ n: Int) async {
        picked = true
        guard n != ep else { return }
        ep = n
        notice = nil
        await loadStyle()
    }

    public func choose(_ id: String) {
        chosen[ep] = id
        syncNote()
    }

    /// 고른 지적이 바뀌면 메모 칸을 그 지적의 메모로 채운다.
    public func syncNote() {
        let key = selected.map { "\(ep):\($0.id ?? "")" }
        guard key != noteFor else { return }
        noteFor = key
        note = selected?.note ?? ""
    }

    public func dismissNotice() { notice = nil }

    /// 검수한다 (다시 검수하면 회차가 하나 는다). 저장하지 않은 변경은 `JobCenter.start` 가 먼저 저장한다.
    @discardableResult
    public func check() async -> Bool {
        await jobs.start(JobRequest(kind: "check", ep: ep))
    }

    /// 처리 상태를 바꾼다. 고침으로 닫으면 다음 열린 지적으로 넘어간다. 그대로 둠 · 잘못 짚음은 메모를 적을 수 있게 남는다.
    @discardableResult
    public func set(_ status: CheckText.Status) async -> Bool {
        guard let f = selected, let id = f.id, CheckText.status(f) != status else { return false }
        chosen[ep] = id  // 열린 지적이 사라져도 고른 지적을 그대로 본다
        let next = status == .fixed ? episode?.findings?.first { CheckText.status($0) == .open && $0.id != id }?.id : nil
        let ok = await send(id, status: status, note: nil)
        if ok, let next { chosen[ep] = next }
        syncNote()
        return ok
    }

    /// 메모를 저장한다.
    @discardableResult
    public func saveNote() async -> Bool {
        guard let f = selected, let id = f.id else { return false }
        let ok = await send(id, status: CheckText.status(f), note: note)
        if ok {
            noteFor = nil
            syncNote()
            notice = ("메모를 저장했어요", false)
        }
        return ok
    }

    private func send(_ id: String, status: CheckText.Status, note: String?) async -> Bool {
        let n = ep
        busy = true
        defer { busy = false }
        do {
            try await service.setFinding(document.name, ep: n, id: id, status: status, note: note)
            await document.merge { _, e in e.plot.number == n }
            return true
        } catch {
            notice = (CanonError.message(error), true)
            return false
        }
    }

    /// 문체 지표를 (다시) 잰다. 본문이 없으면 받지 않는다.
    public func loadStyle() async {
        let n = ep
        guard !text.isEmpty else { style[n] = nil; return }
        do {
            style[n] = .success(try await service.style(document.name, ep: n))
        } catch let e as CanonError {
            style[n] = .failure(e)
        } catch {
            style[n] = .failure(.badResponse(CanonError.message(error)))
        }
    }
}
