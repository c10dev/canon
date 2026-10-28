import Foundation

/// 서버의 오래 걸리는 AI 작업 하나 (`jobs.Job.public()`). 결과(`result`)는 작업마다 모양이 달라
/// `JSONValue` 로 받고, 그 결과를 쓰는 화면이 자기 타입으로 읽는다.
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
    public var result: JSONValue?

    public init(id: String, project: String, kind: String, ep: Int? = nil, label: String, total: Int = 1, done: Int = 0,
                note: String = "", status: Status = .running, error: String = "", started: Double = 0,
                finished: Double? = nil, pending: [Int] = [], result: JSONValue? = nil) {
        self.id = id; self.project = project; self.kind = kind; self.ep = ep; self.label = label
        self.total = total; self.done = done; self.note = note; self.status = status; self.error = error
        self.started = started; self.finished = finished; self.pending = pending; self.result = result
    }

    /// 화면이 작업을 찾는 열쇠 '<kind>:<ep>' (웹 `${kind}:${ep ?? ''}`, 서버 pending.json 의 열쇠).
    public var key: String { Job.key(kind, ep) }

    public static func key(_ kind: String, _ ep: Int?) -> String { "\(kind):\(ep.map(String.init) ?? "")" }

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

/// 작업 시작 요청 (`POST /api/projects/{name}/jobs`, 서버 `JobIn`). 쓰지 않는 칸은 기본값으로 둔다.
public struct JobRequest: Encodable, Sendable, Equatable {
    public var kind: String
    public var ep: Int?
    public var element = ""
    public var note = ""
    public var lineKind = ""
    public var length = 0
    public var ending = ""
    public var span = 0
    public var approaches: [String] = []
    public var draft = 0
    /// write: 다시 생성 요청 (`RewriteRequest`). 화면이 자기 타입을 `JSONValue` 로 바꿔 넣는다
    public var rewrite: JSONValue?

    public init(kind: String, ep: Int? = nil) {
        self.kind = kind
        self.ep = ep
    }

    enum CodingKeys: String, CodingKey {
        case kind, ep, element, note, length, ending, span, approaches, draft, rewrite
        case lineKind = "line_kind"
    }
}

/// 작업 알림 문구. 웹 화면(`pollJobs`, `finishJob`, `JOB_DONE_MSG`)과 같다.
public enum JobText {
    /// 결과를 검토하고 반영하기를 기다리는 작업 (서버 `pending.json` 에 남는다, 웹 `PENDING_KINDS`).
    public static let pendingKinds: Set<String> = ["arc", "suggest", "series", "nextarc", "convert", "rebuild", "rework", "storyline",
                                                   "recap_arc", "recap_part", "state", "openings"]

    /// 시작 알림. 이미 도는 작업이면 버튼이 진행을 보여 주므로 nil.
    public static func started(_ label: String) -> String {
        "\(label)\(KoreanText.josa(label, "을", "를")) 시작했어요. 끝나면 알려 드릴게요. 그동안 다른 작업을 해도 돼요."
    }

    /// 이 작품의 작업이 끝났을 때 (웹 `JOB_DONE_MSG`, `app.js` · `rewrite.js` · `convert.js` · `opening.js`). 목록에 없는 작업은 '<label>이 끝났어요'.
    public static func done(_ job: Job) -> String {
        let ep = job.ep.map(String.init) ?? ""
        switch job.kind {
        case "suggest": return "설정 제안이 도착했어요. 설정 도우미에서 확인하세요."
        case "arc": return "기승전결 구조 제안이 도착했어요. 확인하고 저장하세요."
        case "plots": return "화별 플롯 초안을 만들었어요. 확정된 화는 그대로예요."
        case "plot_one": return "\(ep)화 플롯을 앞뒤 화에 맞춰 채웠어요. 다듬은 뒤 확정하세요."
        case "write":
            // 본문이 있는 화를 다시 생성하면 새 판은 본문을 덮지 않고 고르기를 기다린다 (웹 rewrite.js 의 JOB_DONE_MSG.write)
            return job.result?["candidate"]?.truthy == true ? "\(ep)화 새 판이 나왔어요. 지금 판과 비교해 고르세요." : "\(ep)화 본문을 저장했어요."
        case "state": return "\(ep)화 상태 변경안이 도착했어요."
        case "series": return "부 구성 제안이 도착했어요. 확인하고 반영하세요."
        case "nextarc": return "다음 아크 제안이 도착했어요. 고친 뒤 반영하세요."
        case "recap_arc": return "아크 \(ep) 요약 제안이 도착했어요."
        case "recap_part": return "\(ep)부 요약 제안이 도착했어요."
        case "impact":
            let name = job.label.hasPrefix("인과율: ") ? String(job.label.dropFirst("인과율: ".count)) : job.label
            return "\(name)이 끝났어요. 인과율에서 확인하세요."
        case "storyline": return "이야기 줄기 제안이 도착했어요. 고른 화와 함께 반영하세요."
        case "convert": return "장편 전환 계획이 도착했어요. 확인하고 고른 것만 적용하세요."
        case "rebuild": return "재구성 계획이 도착했어요. 화 지도를 확인하고 적용하세요."
        case "rework": return "\(ep)화 다듬기 제안이 도착했어요. 집필 화면에서 비교하세요."
        case "openings": return "\(ep)화 여는 방식 플롯 안이 도착했어요. 플롯 화면의 \(ep)화 서랍 '초반 화 · 여는 방식 고르기'에서 고르세요."
        case "opening_drafts": return "\(ep)화를 여는 방식마다 썼어요. 읽고 고르세요."
        case "check":
            let round = job.result?["round"]?.int ?? 0
            return "\(ep)화 검수가 끝났어요\(round > 0 ? " (\(round)회차)" : ""): 짚은 곳 \(job.result?["issues"]?.int ?? 0)개"
                + (round > 1 ? ", 새 지적 \(job.result?["added"]?.int ?? 0)개" : "")
        case "auto":
            let status = job.result?["status"].flatMap { if case let .string(s) = $0 { s } else { nil } }
            let tail = ["review": " · 검토가 필요해요", "paused": " · 일시정지했어요", "error": " · 오류로 멈췄어요"][status ?? ""] ?? ""
            return "자동 집필\(tail): \(job.note.isEmpty ? "멈췄어요" : job.note)"
        default: return "\(job.label)\(KoreanText.josa(job.label, "이", "가")) 끝났어요"
        }
    }

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
            return (here ? Self.done(job) : "\(job.project) · \(done). 그 작품을 열면 결과가 보여요", false)
        }
    }
}

/// 검토를 기다리는 AI 결과 하나 (서버 `pending.json` 의 `results`). 반영하거나 버리면 화면이 지운다.
public struct PendingResult: Decodable, Equatable, Sendable {
    public var key: String
    public var id: String
    public var kind: String
    public var ep: Int?
    public var label: String
    public var result: JSONValue
    /// state: 변경안을 만든 본문. 그 뒤 본문을 고쳤으면 상태 승인 화면이 알린다
    public var base: String?

    public init(key: String, id: String, kind: String, ep: Int?, label: String, result: JSONValue, base: String?) {
        self.key = key; self.id = id; self.kind = kind; self.ep = ep; self.label = label; self.result = result; self.base = base
    }
}

/// 실패한 작업 하나 (`pending.json` 의 `failures`). 같은 작업이 성공하면 서버가 지운다.
public struct PendingFailure: Decodable, Equatable, Sendable {
    public var key: String
    public var kind: String
    public var ep: Int?
    public var label: String
    public var error: String

    public init(key: String, kind: String, ep: Int?, label: String, error: String) {
        self.key = key; self.kind = kind; self.ep = ep; self.label = label; self.error = error
    }
}

/// `GET /api/projects/{name}/pending`
public struct PendingList: Decodable, Equatable, Sendable {
    public var results: [String: PendingResult]
    public var failures: [String: PendingFailure]

    public init(results: [String: PendingResult] = [:], failures: [String: PendingFailure] = [:]) {
        self.results = results
        self.failures = failures
    }
}
