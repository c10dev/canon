import CanonAPI
import CanonCore
import Observation

/// 작업을 시작 · 멈추고, 작업 목록과 검토를 기다리는 결과를 받는 곳. 시험에서는 가짜로 바꾼다.
public protocol JobServing: Sendable {
    func listJobs() async throws -> [Job]
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool)
    func stopJob(_ id: String) async throws -> Job
    func pending(_ project: String) async throws -> PendingList
    func dropPending(_ project: String, key: String, failure: Bool) async throws
}

extension CanonServer: JobServing {}

/// 오래 걸리는 AI 작업 (웹 `startJob` · `pollJobs` · `finishJob` · `loadPending`).
/// 작업이 작품에 쓴 화는 연 작품(`ProjectDocument`)에 받아 오고, 검토할 결과는 `results` 에 둔다.
/// 화면은 `results[Job.key(kind, ep)]` 의 `result` 를 자기 타입으로 읽고, 반영하거나 버리면 `drop` 한다.
@MainActor
@Observable
public final class JobCenter {
    public private(set) var tracker = JobTracker()
    /// 화면 위쪽 알림 (시작, 끝남, 실패).
    public private(set) var notice: (text: String, isError: Bool)?
    /// 연 작품의 검토를 기다리는 결과. 열쇠는 `Job.key`.
    public private(set) var results: [String: PendingResult] = [:]
    /// 연 작품의 실패한 작업. 같은 작업이 성공하면 사라진다.
    public private(set) var failures: [String: PendingFailure] = [:]
    /// 시작 요청을 보내고 답을 기다리는 작업 열쇠. 그동안 버튼을 막는다.
    public private(set) var starting: Set<String> = []
    public private(set) var document: ProjectDocument?
    private let service: any JobServing

    public init(service: any JobServing) {
        self.service = service
    }

    public var jobs: [Job] { tracker.jobs }
    private var project: String? { document?.name }

    /// 작품을 연다 (nil 이면 닫는다). 다른 화면 · 지난 실행에서 받은 결과와 실패를 받아 온다.
    public func open(_ document: ProjectDocument?) async {
        self.document = document
        results = [:]
        failures = [:]
        guard let name = document?.name, let list = try? await service.pending(name), self.document?.name == name else { return }
        results = list.results
        failures = list.failures
    }

    /// 이 작품에서 도는 그 작업 (`ep` 가 nil 이면 화를 가리지 않는다, 웹 `jobFor`).
    public func running(_ kind: String, ep: Int? = nil) -> Job? {
        jobs.first { $0.isRunning && $0.project == project && $0.kind == kind && (ep == nil || $0.ep == ep) }
    }

    /// 플롯 작업이 아직 만들지 않은 화. 그 화는 고치지 못하게 막는다 (웹 `jobOwns`).
    public func owns(_ ep: Int) -> Bool {
        if running("plot_one", ep: ep) != nil { return true }
        return running("plots")?.pending.contains(ep) ?? false
    }

    /// 버튼에 보일 진행 글자. 돌지 않으면 nil (웹 `jobBtn`).
    public func busyLabel(_ kind: String, ep: Int? = nil) -> String? {
        if let j = running(kind, ep: ep) { return "\(j.label) 만드는 중…\(j.total > 1 ? " \(j.done)/\(j.total)" : "")" }
        return starting.contains(Job.key(kind, ep)) ? "시작하는 중…" : nil
    }

    /// 작업을 시작한다. 저장하지 않은 변경이 있으면 먼저 저장한다 (묻는 일은 화면이 한다, 웹 `startJob`).
    @discardableResult
    public func start(_ request: JobRequest) async -> Bool {
        guard let doc = document else { return false }
        let key = Job.key(request.kind, request.ep)
        guard !starting.contains(key) else { return false }
        starting.insert(key)
        defer { starting.remove(key) }
        if doc.dirty, await doc.save() == false, doc.dirty { return false }
        do {
            let (job, already) = try await service.startJob(doc.name, request)
            if !already { notice = (JobText.started(job.label), false) }
            await refresh()
            return true
        } catch {
            notice = (CanonError.message(error), true)
            return false
        }
    }

    public func stop(_ job: Job) async {
        do {
            _ = try await service.stopJob(job.id)
            notice = ("\(job.label)\(KoreanText.josa(job.label, "을", "를")) 멈췄어요", false)
        } catch {
            notice = (CanonError.message(error), true)
        }
        await refresh()
    }

    /// 반영하거나 버린 결과를 지운다.
    public func drop(_ kind: String, ep: Int? = nil) async {
        let key = Job.key(kind, ep)
        results[key] = nil
        if let name = project { try? await service.dropPending(name, key: key, failure: false) }
    }

    /// 실패 알림을 닫는다.
    public func dismissFailure(_ key: String) async {
        failures[key] = nil
        if let name = project { try? await service.dropPending(name, key: key, failure: true) }
    }

    public func dismissNotice() { notice = nil }

    /// 작업 목록을 계속 지켜본다. 진행 중인 작업이 없으면 15초마다 묻는다 (다른 기기에서 시작한 작업도 알아채게).
    public func watch() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: tracker.pollInterval ?? .seconds(15))
        }
    }

    public func refresh() async {
        let list: [Job]
        do {
            list = try await service.listJobs()
        } catch {
            tracker.failed()
            return
        }
        let before = Dictionary(uniqueKeysWithValues: tracker.jobs.map { ($0.id, $0) })
        let events = tracker.received(list)
        document?.runningJobs = Set(tracker.jobs.filter { $0.isRunning && $0.project == project }.map(\.id))
        for event in events {
            if let n = JobText.notice(event, currentProject: project) { notice = n }
            switch event {
            case let .progressed(job): await apply(job, was: before[job.id])
            case let .finished(job): await apply(job, was: before[job.id])
            case .lost: break
            }
        }
    }

    /// 이 작품의 작업이 나아가거나 끝났다: 작업이 작품에 쓴 화를 받아 오고, 결과 · 실패를 둔다 (웹 `pollJobs` · `finishJob`).
    private func apply(_ job: Job, was old: Job?) async {
        guard let doc = document, job.project == doc.name else { return }
        let ep = job.ep
        switch job.kind {
        case "plots":
            // 이번에 끝난 구간(지난번에 아직 만들던 화)과 새로 생긴 화만 받는다. 먼저 끝난 구간에서 고치던 초안은 그대로 둔다
            let was = old.map { Set($0.pending) }
            await doc.merge { cur, e in cur.status == .draft && (was?.contains(e.plot.number) ?? true) }
            doc.noteMerged(job.id, done: job.done)
        case "write" where !job.isRunning, "plot_one" where !job.isRunning:
            await doc.merge { _, e in e.plot.number == ep }
        case "check" where job.status == .done:
            await doc.merge { _, e in e.plot.number == ep }
        case "auto":
            // 자동 집필이 실제로 바꾼 화(상태, 본문, 자동 표시)만 받는다
            await doc.merge { cur, e in cur.status != e.status || cur.text != e.text || (cur.auto ?? false) != (e.auto ?? false) }
        default:
            break
        }
        guard !job.isRunning else { return }
        let key = job.key
        if job.status == .error {
            failures[key] = PendingFailure(key: key, kind: job.kind, ep: job.ep, label: job.label, error: job.error)
        } else if job.status == .done {
            failures[key] = nil
            if JobText.pendingKinds.contains(job.kind), let result = job.result, result != .null {
                results[key] = PendingResult(key: key, id: job.id, kind: job.kind, ep: job.ep, label: job.label, result: result, base: nil)
            }
        }
    }
}
