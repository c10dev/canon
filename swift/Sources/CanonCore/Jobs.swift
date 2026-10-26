import Foundation

/// 서버의 오래 걸리는 AI 작업 하나 (`jobs.Job.public()`). 결과(`result`)는 작업마다 모양이 달라 읽지 않는다.
/// 화면은 작업이 끝나면 작품이나 `GET /api/projects/{name}/pending` 을 다시 받아 결과를 본다.
public struct Job: Codable, Sendable, Equatable, Identifiable {
    public enum Status: String, Codable, Sendable {
        case running, done, error, cancelled
    }

    public var id: String
    public var project: String
    public var kind: String
    public var ep: Int?
    public var label: String
    public var total: Int
    public var done: Int
    public var note: String
    public var status: Status
    public var error: String
    public var started: Double
    public var finished: Double?
    /// 맡은 화 중 아직 결과를 쓰지 않은 화. 화면은 이 화만 잠근다.
    public var pending: [Int]

    public init(id: String, project: String, kind: String, ep: Int? = nil, label: String, total: Int = 1, done: Int = 0,
                note: String = "", status: Status = .running, error: String = "", started: Double = 0,
                finished: Double? = nil, pending: [Int] = []) {
        self.id = id; self.project = project; self.kind = kind; self.ep = ep; self.label = label
        self.total = total; self.done = done; self.note = note; self.status = status; self.error = error
        self.started = started; self.finished = finished; self.pending = pending
    }

    public var isRunning: Bool { status == .running }
}

/// 작업 목록을 다시 받을 때마다 무엇이 바뀌었는지 알린다.
public enum JobEvent: Equatable, Sendable {
    /// 진행 중인 작업이 한 단계 나아갔다. 장편 플롯처럼 구간마다 결과를 쓰는 작업은 이때 그 화를 받아 온다.
    case progressed(Job)
    /// 작업이 끝났다 (성공, 실패, 멈춤).
    case finished(Job)
    /// 연결이 끊긴 사이 서버가 다시 시작돼 사라진 작업. 끝나지 못했다.
    case lost([Job])
}

/// 웹 화면 `pollJobs` 의 작업 목록 정리를 옮긴 것. 네트워크 없이 시험할 수 있게 받은 목록만 다룬다.
public struct JobTracker: Sendable {
    public private(set) var jobs: [Job] = []
    /// 마지막 요청이 실패했다. 다시 연결되면 사라진 작업을 `lost` 로 알린다.
    public private(set) var offline = false
    /// 화면이 닫은 작업과, 처음 받을 때 이미 끝나 있던 작업. 다시 보이지 않는다.
    private var seen: Set<String>?

    public init() {}

    public mutating func received(_ list: [Job]) -> [JobEvent] {
        var events: [JobEvent] = []
        if offline {
            offline = false
            let ids = Set(list.map(\.id))
            let lost = jobs.filter { $0.isRunning && !ids.contains($0.id) }
            if !lost.isEmpty { events.append(.lost(lost)) }
        }
        if seen == nil { seen = Set(list.filter { !$0.isRunning }.map(\.id)) }
        let before = Dictionary(uniqueKeysWithValues: jobs.map { ($0.id, $0) })
        jobs = list.filter { !seen!.contains($0.id) || $0.isRunning }
        for job in jobs {
            let old = before[job.id]
            let progressed = old == nil || old!.done != job.done || old!.status != job.status
            guard progressed else { continue }
            if job.isRunning {
                events.append(.progressed(job))
            } else if old == nil || old!.isRunning {
                events.append(.finished(job))
            }
        }
        return events
    }

    /// 목록을 받지 못했다. 가진 목록은 그대로 두고 더 천천히 다시 묻는다.
    public mutating func failed() {
        offline = true
    }

    /// 화면이 작업을 목록에서 닫았다.
    public mutating func dismiss(_ id: String) {
        seen = (seen ?? []).union([id])
        jobs.removeAll { $0.id == id && !$0.isRunning }
    }

    /// 다음에 다시 물을 때까지 기다릴 시간. 진행 중인 작업이 없으면 nil (화면이 새 작업을 시작할 때 다시 묻는다).
    public var pollInterval: Duration? {
        guard jobs.contains(where: \.isRunning) else { return nil }
        return offline ? .seconds(4) : .milliseconds(1500)
    }
}

/// 작업 알림 문구. 웹 화면(`pollJobs`, `finishJob`)과 같다. 작업별 완료 문구(`JOB_DONE_MSG`)는 화면 모듈이 옮겨 올 때 더한다.
public enum JobText {
    /// 알릴 것이 없으면 nil (멈춘 작업, 진행 중 단계).
    public static func notice(_ event: JobEvent, currentProject: String?) -> (text: String, isError: Bool)? {
        switch event {
        case .progressed:
            return nil
        case let .lost(jobs):
            let labels = jobs.map(\.label).joined(separator: ", ")
            return ("서버가 다시 시작돼 작업이 끝나지 못했어요: \(labels). 다시 시작하세요", true)
        case let .finished(job):
            if job.status == .cancelled { return nil }
            let here = job.project == currentProject
            if job.status == .error {
                return (here ? "\(job.label) 실패: \(job.error)" : "\(job.project) · \(job.label) 실패: \(job.error)", true)
            }
            let done = "\(job.label)\(KoreanText.josa(job.label, "이", "가")) 끝났어요"
            return (here ? done : "\(job.project) · \(done). 그 작품을 열면 결과가 보여요", false)
        }
    }
}
