import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 자동 집필 화면이 서버에 보내는 것 (`web.py` 의 `auto_*` · `revert`). 실행을 바꾸는 호출은 바뀐 상태를 돌려준다. 시험에서는 가짜로 바꾼다.
public protocol AutoService: Sendable {
    func status(_ project: String) async throws -> AutoState
    func estimate(_ project: String, target: Int, batch: Bool, policy: Policy) async throws -> AutoEstimate
    func start(_ project: String, target: Int, batch: Bool, policy: Policy) async throws -> AutoState
    /// `what`: pause | stop
    func request(_ project: String, _ what: String) async throws -> AutoState
    func resume(_ project: String, approve: Bool, rewrite: Bool) async throws -> AutoState
    func setBatch(_ project: String, _ on: Bool) async throws -> AutoState
    func setPolicy(_ project: String, _ policy: Policy) async throws -> AutoState
    /// 검토 대기 변경안을 검토를 기다리는 결과(`state:<화>`)로 둔다. 상태 승인 화면이 읽는다.
    func sendToReview(_ project: String) async throws -> AutoState
    /// `after` 화 반영 직후로 되돌린다 (`POST .../revert/{after}`).
    func revert(_ project: String, after: Int) async throws
}

/// 자동 집필 화면 상태 (웹 `auto.js` 의 `S.auto` · `S.autoForm` · `S.autoEst` · `autoPoll`).
/// 실행은 서버가 돌리고, 화면은 3초마다 상태를 묻는다. 작품에 쓴 화는 `JobCenter` 가 받아 오고, 여기서는 상태가 바뀔 때도 받는다.
@MainActor
@Observable
public final class AutoModel {
    public let document: ProjectDocument
    public let jobs: JobCenter
    public private(set) var state: AutoState?
    /// 서버와 연결이 끊겼다. 마지막 상태를 '진행 중'으로 두지 않는다.
    public private(set) var offline = false
    /// 새로 시작할 때의 값. 바꾸면 화면이 `estimate` 를 부른다.
    public var form: AutoForm?
    public private(set) var estimates: (off: AutoEstimate, on: AutoEstimate)?
    public private(set) var estimateError: String?
    /// 멈춘 실행이 있어도 새로 시작 칸을 펼쳤다.
    public var formOpen = false
    /// 멈춘 실행의 정책을 고치는 중인 값. `started` 가 다른 실행이면 새로 둔다.
    public var runPolicy: Policy?
    private var runPolicyOf: String?
    public var logAll = false
    public private(set) var busy = false
    public private(set) var notice: (text: String, isError: Bool)?
    /// 다음 상태 묻기까지 기다릴 시간. 시작 · 이어 가기 직후에는 첫 단계가 바로 보이게 1초.
    private var nextDelay: Duration = .seconds(3)
    private let service: any AutoService

    public init(document: ProjectDocument, jobs: JobCenter, service: any AutoService) {
        self.document = document
        self.jobs = jobs
        self.service = service
    }

    public var name: String { document.name }
    public var project: Project? { document.project }
    public var run: AutoRun? { state?.run }
    /// 서버에서 실행 스레드가 돈다. 연결이 끊기면 모른다고 본다.
    public var active: Bool { !offline && (state?.active ?? false) }

    /// 처음 열 때: 작품과 상태를 받고, 새로 시작 칸을 채우고, 추정한다.
    public func start() async {
        await document.load()
        do {
            state = try await service.status(name)
        } catch {
            notice = (CanonError.message(error), true)
        }
        if form == nil, let p = project { form = AutoText.defaults(p, state) }
        syncRunPolicy()
        await estimate()
    }

    /// 화면이 보이는 동안 상태를 묻는다 (웹 `autoPoll`).
    public func watch() async {
        while !Task.isCancelled {
            let delay = nextDelay
            nextDelay = .seconds(3)
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await refresh()
        }
    }

    public func refresh() async {
        let before = AutoText.signature(run)
        let wasActive = state?.active ?? false
        let restarts = run?.restarts
        let fresh: AutoState
        do {
            fresh = try await service.status(name)
        } catch {
            offline = true
            return
        }
        if offline {
            offline = false
            if fresh.active { notice = (AutoText.reconnected, false) }
        }
        // 서버가 다시 시작돼 하던 단계를 처음부터 다시 하면 한 번 알린다
        if let restarts, let r = fresh.run, r.restarts > restarts { notice = (AutoText.restarted, false) }
        state = fresh
        syncRunPolicy()
        guard fresh.run != nil, AutoText.signature(fresh.run) != before || fresh.active != wasActive else { return }
        // 자동 집필이 바꾼 화(상태, 본문, 자동 표시)만 받는다. 저장하지 않은 변경이 없으면 작품을 통째로 받는다
        await document.merge { cur, e in cur.status != e.status || cur.text != e.text || (cur.auto ?? false) != (e.auto ?? false) }
        if !fresh.active { await estimate() }  // 멈추거나 끝나면 남은 화 추정을 새로
    }

    private func syncRunPolicy() {
        guard let r = run else { runPolicy = nil; runPolicyOf = nil; return }
        if runPolicyOf != r.started { runPolicy = r.policy; runPolicyOf = r.started }
    }

    /// 배치 끔 · 켬 두 경우를 함께 추정한다 (웹 `autoEstimate`).
    public func estimate() async {
        guard let f = form else { return }
        do {
            async let off = service.estimate(name, target: f.target, batch: false, policy: f.policy)
            async let on = service.estimate(name, target: f.target, batch: true, policy: f.policy)
            estimates = try await (off, on)
            estimateError = nil
        } catch {
            estimates = nil
            estimateError = CanonError.message(error)
        }
    }

    // MARK: 보이는 것

    /// 새로 시작 칸을 보인다: 돌지 않고, 실행이 없거나 끝났거나, 사용자가 펼쳤다.
    public var canStart: Bool {
        guard !active else { return false }
        return ended || formOpen
    }

    /// 지난 실행이 없거나 끝났다 (이어 갈 것이 없다).
    public var ended: Bool {
        guard let r = run else { return true }
        return r.status == .done || r.status == .stopped
    }

    /// 지금 고른 배치 쪽 추정.
    public var pickedEstimate: AutoEstimate? {
        guard let f = form, let e = estimates else { return nil }
        return f.batch ? e.on : e.off
    }

    public var nothingLeft: Bool { AutoText.nothingLeft(estimates?.off) }

    /// 멈춘 실행의 정책을 바꿀 수 있다 (웹: 일시정지 · 검토 대기 · 오류).
    public var canEditRunPolicy: Bool {
        guard let r = run, !active, !offline else { return false }
        return [.paused, .review, .error].contains(r.status)
    }

    public var runPolicyChanged: Bool {
        guard let r = run, let p = runPolicy else { return false }
        return p != r.policy
    }

    /// 실행 중인 배치 켜고 끄기를 서버에 보낸다 (끝났거나 중지한 실행은 새로 시작 칸만 바꾼다).
    public var batchLocked: Bool {
        guard let r = run else { return false }
        return r.status == .done || r.status == .stopped
    }

    /// 검토 없이 반영한 화.
    public var autoApplied: [Episode] {
        (project?.episodes ?? []).filter { $0.auto ?? false }
    }

    /// 보일 로그 (최신이 위).
    public var shownLog: [AutoLog] {
        let log = run?.log ?? []
        return Array((logAll ? log : Array(log.suffix(AutoText.logShown))).reversed())
    }

    public var hiddenLog: Int {
        logAll ? 0 : max(0, (run?.log.count ?? 0) - AutoText.logShown)
    }

    public func dismissNotice() { notice = nil }

    // MARK: 서버

    /// 시작한다. 묻는 일(`AutoText.startQuestion`)은 화면이 한다 (웹 `autoStart`).
    public func begin() async {
        guard let f = form else { return }
        await call {
            self.state = try await self.service.start(self.name, target: f.target, batch: f.batch, policy: f.policy)
            self.formOpen = false
            self.notice = (AutoText.started, false)
        }
        await jobs.refresh()
        nextDelay = .seconds(1)
    }

    public func pause() async {
        await call {
            self.state = try await self.service.request(self.name, "pause")
            self.notice = (AutoText.paused(batch: self.run?.batch ?? false), false)
        }
    }

    public func stop() async {
        await call { self.state = try await self.service.request(self.name, "stop") }
        await estimate()
    }

    /// 이어 간다. `approve` 는 검토 대기 변경안을 그대로 반영, `rewrite` 는 그 화를 다시 쓴다 (웹 `autoResume`).
    public func resume(approve: Bool = false, rewrite: Bool = false) async {
        let ok = await call {
            self.state = try await self.service.resume(self.name, approve: approve, rewrite: rewrite)
            await self.document.load()
        }
        guard ok else { return }
        await jobs.refresh()
        nextDelay = .seconds(1)
    }

    /// 배치를 켜고 끈다. 돌거나 멈춘 실행이면 서버에도 보낸다 (다음 단계부터 적용).
    public func setBatch(_ on: Bool) async {
        if let r = run, [.running, .paused, .review, .error].contains(r.status) {
            await call {
                self.state = try await self.service.setBatch(self.name, on)
                self.notice = (AutoText.batchChanged(on), false)
            }
        }
        form?.batch = on
    }

    /// 멈춘 실행의 승인 정책을 바꾼다. 검토 대기와 기다리던 배치는 그대로다.
    public func applyRunPolicy() async {
        guard let p = runPolicy else { return }
        await call {
            self.state = try await self.service.setPolicy(self.name, p)
            self.runPolicy = self.run?.policy
            self.notice = (AutoText.policyChanged, false)
        }
    }

    /// 검토 대기 변경안을 상태 승인 화면이 읽을 결과로 두고 작업 결과를 다시 받는다. 성공하면 화면이 상태 승인으로 간다.
    @discardableResult
    public func sendToReview() async -> Bool {
        let ok = await call { self.state = try await self.service.sendToReview(self.name) }
        if ok { await jobs.open(document) }
        return ok
    }

    /// n화부터 반영을 취소한다 (웹 `autoRevert` → `revertFrom`). 서버가 실행 기록도 맞춘다.
    public func revert(from n: Int) async {
        let fin = project.map { AutoText.finalized(from: n, $0) } ?? []
        let ok = await call {
            try await self.service.revert(self.name, after: n - 1)
            await self.document.reload()
            self.notice = (AutoText.revertDone(n, fin: fin), false)
        }
        guard ok else { return }
        if let fresh = try? await service.status(name) { state = fresh }
        await estimate()
    }

    /// 저장하지 않은 변경을 먼저 저장하고 서버를 부른다 (웹 `run` · `saveIfDirty`).
    @discardableResult
    private func call(_ body: @escaping () async throws -> Void) async -> Bool {
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
