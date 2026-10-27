import CanonAPI
import CanonCore
import Foundation

public typealias AutoState = Components.Schemas.AutoView
public typealias AutoRun = Components.Schemas.AutoRun
public typealias AutoLog = Components.Schemas.AutoLog
public typealias AutoEstimate = Components.Schemas.AutoEstimate
public typealias Policy = Components.Schemas.Policy
public typealias Project = Components.Schemas.Project
public typealias Episode = Components.Schemas.Episode

/// 새로 시작할 때 고르는 것 (웹 `S.autoForm`).
public struct AutoForm: Equatable, Sendable {
    public var target: Int
    public var batch: Bool
    public var policy: Policy

    public init(target: Int, batch: Bool, policy: Policy) {
        self.target = target
        self.batch = batch
        self.policy = policy
    }
}

/// 자동 집필 화면의 문구와 표시 규칙. 웹 `auto.js` 와 같은 말이라 함께 고친다.
public enum AutoText {
    /// 실행 상태 이름과 칩 색 (웹 `AUTO_STATUS`). 칩 색은 화 상태 이름으로 적는다.
    public static func status(_ s: AutoRun.StatusPayload) -> (label: String, tone: EpisodeStatus) {
        switch s {
        case .running: ("진행 중", .confirmed)
        case .paused: ("일시정지", .written)
        case .review: ("검토 대기", .written)
        case .stopped: ("중지됨", .draft)
        case .done: ("끝남", .finalized)
        case .error: ("오류로 멈춤", .written)
        }
    }

    public static let offlineLabel = "연결 끊김"

    /// 단계 이름 (웹 `AUTO_STEP`). 모르는 단계는 받은 그대로.
    public static func step(_ s: String) -> String {
        ["write": "본문 쓰는 중", "review": "검수와 상태 변경안 만드는 중", "confirm": "플롯 확정", "applied": "반영함"][s] ?? s
    }

    /// 돌고 있을 때 보일 지금 단계. 돌지 않으면 빈 글 (웹 `autoRunCard` 의 `step`).
    public static func stepLine(_ r: AutoRun, active: Bool) -> String {
        guard active else { return "" }
        guard let n = r.ep else { return "첫 화를 준비하는 중" }
        return "\(n)화 \(step(r.step))\(r.batches.additionalProperties.isEmpty ? "" : " · 배치 결과 기다리는 중")"
    }

    /// 관계 변화 민감도 (웹 `AUTO_SHIFT`).
    public static let shiftOptions: [(value: Double, label: String)] = [
        (0.2, "민감하게 (작은 변화에도 멈춤)"), (0.3, "보통"), (0.45, "둔하게 (큰 변화에만 멈춤)"), (0, "보지 않음"),
    ]
    public static let issueOptions: [(value: Int, label: String)] = [
        (0, "하나라도 있으면 멈춤"), (1, "1개까지 넘어감"), (2, "2개까지 넘어감"), (5, "5개까지 넘어감"),
    ]
    public static let everyOptions: [(value: Int, label: String)] = [
        (0, "멈추지 않음"), (1, "매 화"), (2, "2화마다"), (3, "3화마다"), (5, "5화마다"),
    ]

    /// 시간 (웹 `autoDuration`).
    public static func duration(_ s: Double?) -> String {
        guard let s else { return "" }
        if s >= 86400 * 2 { return "\(Int((s / 86400).rounded()))일" }
        if s >= 3600 { return String(format: "%.1f시간", s / 3600) }
        if s < 60 { return s > 0 ? "\(max(1, Int(s.rounded())))초" : "0초" }
        return "\(Int((s / 60).rounded()))분"
    }

    /// 비용 (웹 `autoCost`).
    public static func cost(_ c: Double?) -> String {
        guard let c else { return "가격 모름" }
        if c == 0 { return "$0" }
        return c < 0.01 ? "$0.01 미만" : String(format: "$%.2f", c)
    }

    /// '12,345' (웹 `toLocaleString()`).
    public static func number(_ n: Int) -> String {
        let digits = String(abs(n))
        var out = ""
        for (i, ch) in digits.enumerated() {
            if i > 0, (digits.count - i) % 3 == 0 { out.append(",") }
            out.append(ch)
        }
        return n < 0 ? "-" + out : out
    }

    /// '1~3, 5' (웹 `rangeText`).
    public static func rangeText(_ nums: [Int]) -> String {
        var out: [String] = []
        var i = 0
        while i < nums.count {
            var j = i
            while j + 1 < nums.count, nums[j + 1] == nums[j] + 1 { j += 1 }
            out.append(i == j ? "\(nums[i])" : "\(nums[i])~\(nums[j])")
            i = j + 1
        }
        return out.joined(separator: ", ")
    }

    // MARK: 새로 시작

    /// 새로 시작 칸의 처음 값 (웹 `autoDefaults`). 정책은 지난 실행 것, 없으면 서버 기본값.
    public static func defaults(_ p: Project, _ state: AutoState?) -> AutoForm {
        let eps = p.episodes ?? []
        let target = eps.map(\.plot.number).max() ?? p.meta?.targetEpisodes ?? 1
        if let last = state?.run { return AutoForm(target: target, batch: last.batch, policy: last.policy) }
        return AutoForm(target: target, batch: false, policy: state?.policyDefaults ?? Policy())
    }

    /// 배치 설명 (웹 `viewAuto` 의 `batchNote`).
    public static func batchNote(_ stages: [String]) -> String {
        stages.isEmpty
            ? "지금 단계들이 Gemini 가 아니라서 배치를 켜도 일반 호출로 돌아요."
            : "배치를 켜면 Gemini Batch API 로 보내 비용이 절반이에요. 대신 단계마다 몇 분에서 길게는 24시간까지 기다려요. 화는 앞 화가 반영돼야 쓸 수 있어 한 화씩 차례로 가고, 한 화의 검수와 상태 변경안은 함께 보내요."
    }

    public static let restartWarning = "새로 시작하면 지금 실행의 검토 대기와 기다리던 배치는 버려요"

    /// 남은 화가 없다. 시작 단추를 끈다.
    public static func nothingLeft(_ e: AutoEstimate?) -> Bool {
        guard let e else { return false }
        return e.episodes == 0 && e.missing.isEmpty
    }

    public static func nothingLeftNote(_ e: AutoEstimate) -> String {
        "\(e.to)화까지 남은 화가 없어요. 더 쓰려면 위에서 목표 화를 늘리세요."
    }

    /// 추정 위 한 줄 (웹 `autoEstCard`).
    public static func estimateLine(_ e: AutoEstimate) -> String {
        guard e.episodes > 0 else { return "\(e.to)화까지 남은 화가 없어요" }
        let c = e.calls.additionalProperties
        return "\(e.from.map(String.init) ?? "")~\(e.to)화 \(e.episodes)화 남음 · 호출 본문 \(c["write"] ?? 0) · 검수 \(c["check"] ?? 0) · 상태 \(c["state"] ?? 0) · 토큰 입력 약 \(number(e.tokensIn)) / 출력 약 \(number(e.tokensOut))"
    }

    /// 배치 끔 · 켬 칸의 시간과 그 아래 설명.
    public static func estimateTime(_ e: AutoEstimate) -> (time: String, note: String) {
        guard e.batchRounds > 0 else { return ("약 \(duration(Double(e.secondsMin)))", "") }
        let avg = e.batchAvgSeconds.map { " (지난 평균 \(duration(Double($0))))" } ?? ""
        return ("\(duration(Double(e.secondsMin)))~\(duration(Double(e.secondsMax)))",
                "배치 \(e.batchRounds)번 기다림. 길면 한 번에 24시간까지 걸릴 수 있어요\(avg)")
    }

    /// 추정 아래 경고 (멈출 화).
    public static func estimateWarnings(_ e: AutoEstimate) -> [String] {
        var out: [String] = []
        if !e.missing.isEmpty { out.append("플롯이 없는 화(\(rangeText(e.missing))화)에서 멈춰요. 먼저 플롯을 만드세요.") }
        if !e.drafts.isEmpty { out.append("플롯이 초안인 \(rangeText(e.drafts))화에서 멈춰요. 추정은 끝까지 쓴다고 보고 셌어요. 확정하거나 '초안 플롯도 자동으로 확정하고 쓰기'를 켜세요.") }
        return out
    }

    /// 추정 아래 안내 (로컬 단계, 추정 근거와 가격).
    public static func estimateNotes(_ e: AutoEstimate) -> [String] {
        var out: [String] = []
        let stages = e.stages.additionalProperties
        let local = [("write", "본문"), ("check", "검수"), ("state", "상태")].filter { stages[$0.0] == "local" }.map(\.1)
        if !local.isEmpty { out.append("\(local.joined(separator: ", ")) 단계는 로컬 모델이라 비용이 없고 배치도 쓰지 않아요.") }
        var s = (e.measured ? "지난 실행에서 잰 출력량과 시간을 썼어요." : "처음이라 화당 목표 분량으로 추정했어요.")
            + " 가격은 사용량 · 비용 화면의 가격표(\(e.model) 기준)로 계산한 추정치이고, 생각(thinking) 토큰이 많으면 더 나올 수 있어요."
        if !e.unpriced.isEmpty { s += " 가격표에 없는 모델(\(e.unpriced.joined(separator: ", ")))이 있어 비용을 몰라요." }
        out.append(s)
        return out
    }

    /// 시작 전에 묻는 말 (웹 `autoStart`).
    public static func startQuestion(_ target: Int, _ e: AutoEstimate?) -> String {
        var lines = ["\(target)화까지 자동으로 써요."]
        if let e {
            lines.append("남은 화 \(e.episodes)화 (\(e.from.map(String.init) ?? "")~\(e.to)화)")
            lines.append("예상 시간 \(e.batchRounds > 0 ? "\(duration(Double(e.secondsMin)))~\(duration(Double(e.secondsMax))) (배치는 한 번에 최대 24시간까지 걸릴 수 있어요)" : "약 \(duration(Double(e.secondsMin)))")")
            lines.append("예상 비용 \(e.cost == nil ? "알 수 없어요 (가격표에 없는 모델)" : cost(e.cost))")
        }
        lines += ["정해 둔 멈춤 조건에 걸리지 않은 화는 검토 없이 상태를 반영해요.", "시작할까요?"]
        return lines.joined(separator: "\n")
    }

    public static let started = "자동 집필을 시작했어요. 다른 화면으로 옮겨 가도 계속 돌아요."

    // MARK: 실행

    /// 목표 화까지 반영이 끝난 화 수.
    public static func doneCount(_ p: Project, target: Int) -> Int {
        (p.episodes ?? []).filter { $0.plot.number <= target && $0.status == .finalized }.count
    }

    /// 진행 줄 (웹 `autoRunCard` 의 `.small`). 서버 재시작 횟수는 따로 붙인다.
    public static func progressLine(_ r: AutoRun, done: Int) -> String {
        var s = "\(done) / \(r.target)화 반영 완료 · 이번 실행에서 자동 반영 \(r.applied.count)화 · 토큰 입력 \(number(r.tokensIn)) / 출력 \(number(r.tokensOut)) · 비용 약 \(cost(r.cost))"
        if r.restarts > 0 { s += " · 서버 재시작 \(r.restarts)번" }
        return s
    }

    public static let restartsHelp = "서버가 다시 시작돼 하던 단계를 처음부터 다시 했어요. 끊긴 호출 비용은 여기에 없어요"
    public static let offlineNote = "서버와 연결이 끊겼어요. 다시 연결되면 이어서 보여 드려요. 서버가 다시 시작되면 자동 집필은 서버에서 이어 가요."
    public static let reconnected = "서버에 다시 연결됐어요. 자동 집필을 이어서 보여 드려요"
    public static let restarted = "서버가 다시 시작돼 자동 집필을 이어 가요. 끊긴 단계는 처음부터 다시 해요. 진행 로그에서 확인하세요"
    public static let batchWait = "배치 결과는 몇 분에서 길게는 몇 시간 뒤에 와요. 창을 닫아도 서버가 계속 기다려요."
    public static let settingsHint = "모델 · API 키 설정에서 키와 모델을 확인한 뒤 이어 가세요."
    public static let reviewHint = "검토하기: 변경안을 상태 승인 화면에 열어요. 고른 항목만 반영한 뒤 여기로 돌아와 이어 가면 돼요."

    /// 오류 이유가 키 · 연결 문제라 설정을 보라고 할까 (웹 `/API 키|연결|quota|429|403|401/i`).
    public static func needsSettings(_ r: AutoRun) -> Bool {
        r.status == .error && r.reasons.contains { x in
            x.range(of: "API 키|연결|quota|429|403|401", options: [.regularExpression, .caseInsensitive]) != nil
        }
    }

    /// 사용자가 검토 화면에서 이미 반영했다 (서버가 `pending` 을 비운다).
    public static func reviewDone(_ r: AutoRun) -> Bool { r.status == .review && r.pending == nil }

    public static func reviewDoneNote(_ n: Int) -> String { "\(n)화를 검토 화면에서 반영했어요. 이어 가기를 누르세요." }

    /// 검토 대기 변경안을 만든 뒤 그 화 본문이 바뀌었다 (웹 `pendingStale`, 서버 `autorun.resume` 도 막는다).
    public static func pendingStale(_ r: AutoRun, _ p: Project) -> Bool {
        guard r.pending != nil, !r.pendingText.isEmpty, let n = r.ep,
              let e = (p.episodes ?? []).first(where: { $0.plot.number == n }) else { return false }
        return (e.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines) != r.pendingText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public static func staleNote(_ n: Int) -> String {
        "변경안을 만든 뒤 \(n)화 본문을 고쳤어요. 그대로 반영하면 옛 본문 기준의 요약 · 인물 상태 · 사건이 들어가서 막아 두었어요. 검토하기에서 변경안을 다시 만들거나 다시 쓰기를 고르세요."
    }

    /// 멈춘 이유를 고칠 화면으로 가는 단추 (웹 `autoHaltLinks`, `Run.halt` 는 서버 `autorun._Halt` 의 kind).
    public static func haltLink(_ r: AutoRun, _ p: Project) -> (label: String, screen: Screen)? {
        guard let n = r.ep else { return nil }
        switch r.halt {
        case "plot_draft": return ("\(n)화 플롯 확정하러 가기", .arc)
        case "plot_missing": return ("\(n)화 플롯 만들러 가기", .arc)
        case "review":
            let issues = (p.episodes ?? []).first { $0.plot.number == n }?.issues ?? []
            return (issues.isEmpty ? "\(n)화 본문 읽기" : "\(n)화 검수 결과 보기", .write)
        case "every": return ("\(n)화 읽으러 가기", .write)
        case "changed": return ("\(n)화 집필 화면 보기", .write)
        default: return nil
        }
    }

    /// 멈춘 실행의 정책 칸 설명 (웹 `autoRunPolicy`).
    public static func runPolicyNote(_ r: AutoRun) -> String {
        "바꾼 정책은 다음 판정부터 적용돼요. " + (r.status == .review ? "지금 검토를 기다리는 \(r.ep.map(String.init) ?? "")화 변경안은 그대로 남아요." : "검토 대기와 기다리던 배치는 그대로예요.")
    }

    public static func paused(batch: Bool) -> String {
        batch ? "멈추는 중이에요. 기다리던 배치는 취소하지 않아, 이어 가면 결과를 받아 와요." : "지금 단계가 끝나면 멈춰요."
    }

    public static let stopQuestion = "자동 집필을 중지할까요? 기다리던 배치 작업이 있으면 취소해요. 이미 반영한 화는 그대로예요."
    public static func approveQuestion(_ n: Int) -> String { "\(n)화 변경안을 보지 않고 그대로 반영할까요?" }
    public static func rewriteQuestion(_ n: Int) -> String { "\(n)화를 다시 쓸까요? 지금 본문은 이전 판으로 남아 집필 화면에서 되돌릴 수 있어요." }
    public static func batchChanged(_ on: Bool) -> String {
        on ? "배치를 켰어요. 다음 단계부터 배치로 보내요." : "배치를 껐어요. 다음 단계부터 일반 호출이에요."
    }
    public static let policyChanged = "승인 정책을 바꿨어요. 다음 판정부터 적용돼요."

    // MARK: 자동 반영한 화

    /// 검토 없이 반영한 화의 문체 · 초반 경고 수 (진행 로그에만 남는다, 웹 `autoAppliedCard`).
    public static func styleWarnings(_ log: [AutoLog]) -> [Int: Int] {
        var out: [Int: Int] = [:]
        for x in log where x.level == .warn {
            guard let n = x.ep, x.message.hasPrefix("문체:") || x.message.hasPrefix("초반:") else { continue }
            out[n, default: 0] += 1
        }
        return out
    }

    public static let appliedHelp = "읽어 보고 문제가 있으면 그 화부터 반영을 취소하세요. 그 화 직전 상태로 돌아가고, 본문은 남아 상태 승인부터 다시 할 수 있어요."

    /// 반영 취소 전에 묻는 말 (웹 `revertFrom`, 상태 승인 화면 `ReviewText.revertQuestion` 과 같은 말).
    public static func revertQuestion(_ n: Int, _ p: Project) -> String {
        let fin = finalized(from: n, p)
        let added = (p.history ?? []).filter { $0.episode >= n }.flatMap { $0.newCharacters ?? [] }.map { $0.name.isEmpty ? $0.id : $0.name }
        let places = (p.elements ?? []).filter { $0.foundIn == .본문 && ($0.foundEp ?? 0) >= n }.map { $0.name ?? $0.id }
        var s = "\(rangeText(fin))화의 상태 반영을 취소할까요? \(n - 1 > 0 ? "\(n - 1)화 반영 직후" : "1화 시작 전") 상태로 돌아가고, 본문은 남아 상태 승인을 다시 하게 돼요."
        if !added.isEmpty { s += " 그 반영이 더한 인물(\(added.joined(separator: ", ")))도 빠져요." }
        if !places.isEmpty { s += " 본문에서 등록한 장소(\(places.joined(separator: ", ")))도 빠져요. 아직 안 쓴 화 플롯에 나오거나 직접 고친 장소는 남아요." }
        return s
    }

    public static func finalized(from n: Int, _ p: Project) -> [Int] {
        (p.episodes ?? []).filter { $0.status == .finalized && $0.plot.number >= n }.map(\.plot.number)
    }

    /// 반영 취소 뒤 알림 (웹 `revertFrom`). `fin` 은 취소하기 전 `finalized(from:)`.
    public static func revertDone(_ n: Int, fin: [Int]) -> String {
        "\(rangeText(fin))화의 반영을 취소했어요. \(n)화 변경안을 다시 골라 적용하세요"
    }

    // MARK: 진행 로그

    /// 로그 시각: 오늘이면 '14:05:09', 아니면 '2026.10.25 14:05:09' (웹 `autoLogCard`).
    public static func logTime(_ iso: String, now: Date = Date(), timeZone: TimeZone = .current) -> String {
        guard let d = parseISO(iso) else { return iso }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = timeZone
        let c = cal.dateComponents([.hour, .minute, .second], from: d)
        let clock = String(format: "%02d:%02d:%02d", c.hour!, c.minute!, c.second!)
        return cal.isDate(d, inSameDayAs: now) ? clock : "\(KoreanText.date(iso, timeZone: timeZone)) \(clock)"
    }

    /// 토큰 칸: 둘 다 0 이면 빈 글.
    public static func logTokens(_ e: AutoLog) -> String {
        e.tokensIn == 0 && e.tokensOut == 0 ? "" : "\(number(e.tokensIn)) / \(number(e.tokensOut))"
    }

    public static let logShown = 30

    public static func moreLog(_ hidden: Int) -> String { "이전 로그 \(hidden)줄 더 보기" }

    /// 서버 `_now()` 글 ('2026-10-26T05:03:09+00:00').
    static func parseISO(_ s: String) -> Date? {
        ISO8601DateFormatter().date(from: s)
    }

    /// 상태가 바뀌었는지 볼 값 (웹 `autoPoll` 의 `sig`). `updated` 는 초 단위라 같은 초의 변화를 놓쳐 보이는 값을 함께 본다.
    public static func signature(_ r: AutoRun?) -> String {
        guard let r else { return "" }
        return [r.updated, r.status.rawValue, r.ep.map(String.init) ?? "", r.step, String(r.log.count)].joined(separator: "|")
    }
}
