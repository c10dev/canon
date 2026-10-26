import CanonAPI
import CanonCore
import Foundation

public typealias UsageSummary = Components.Schemas.UsageSummary
public typealias UsageTotal = Components.Schemas.UsageTotal
public typealias UsageGroup = Components.Schemas.UsageGroup
public typealias UsageCall = Components.Schemas.UsageCall
public typealias PriceTable = Components.Schemas.PriceTable
public typealias PriceRow = Components.Schemas.PriceRow
public typealias PriceIn = Components.Schemas.Price

/// 사용량 화면 문구. 웹 화면(`canon/static/usage.js`)과 같은 규칙이라 함께 고친다.
/// 비용은 서버(`usage.py`)가 계산한 값을 그대로 쓴다. 여기서는 보여 주는 글만 만든다.
public enum UsageText {
    /// 기간 고르기 (`USAGE_DAYS`). 0 이면 전체 기간.
    public static let days: [(days: Int, label: String)] = [(1, "오늘"), (7, "7일"), (30, "30일"), (90, "90일"), (0, "전체")]

    /// 단계 이름 (`USAGE_STAGE`).
    public static let stages: [String: String] = [
        "plan": "계획", "write": "본문", "check": "검수", "state": "상태 변경안", "name": "이름 추천", "revise": "부분 수정",
        "illustration": "삽화 프롬프트", "research": "연구 · 모델 실험",
    ]

    /// 부른 곳 (`USAGE_SOURCE`).
    public static let sources: [String: String] = ["web": "화면에서 직접", "autorun": "자동 집필", "research": "연구 화면", "cli": "명령줄"]

    /// 작업 이름 (`USAGE_TASK`).
    public static let tasks: [String: String] = [
        "suggest": "설정 제안", "arc": "기승전결 구조", "series": "부 구성", "nextarc": "다음 아크", "convert": "장편 전환",
        "rebuild": "장편 재구성 계획", "rework": "재구성 다듬기", "storyline": "이야기 줄기",
        "recap_arc": "아크 요약", "recap_part": "부 요약", "plots": "화별 플롯", "write": "본문", "state": "상태 변경안",
        "impact": "인과율 영향 분석", "hook": "흡입력 판정", "openings": "여는 방식 안", "opening_drafts": "여러 안으로 쓰기",
        "names": "이름 추천", "style": "문체 분석", "chat": "AI 대화", "edits": "부분 수정", "auto": "자동 집필", "sample": "샘플 비교",
        "stage": "단계 시험", "compare": "가려 비교", "budget": "컨텍스트 크기", "probe": "서버 점검", "check": "검수",
        "update": "상태 변경안", "run": "연속 실행", "fix": "부분 수정",
    ]

    public static let title = "사용량 · 비용"
    public static let intro = "AI를 부를 때마다 토큰 수를 기록하고 가격표로 비용을 계산해요. 추정치라 Google 청구 금액과 다를 수 있어요."
    public static let billingLink = "AI Studio 실제 사용량 ↗"
    public static let defaultBillingURL = "https://aistudio.google.com/usage"

    // MARK: 숫자

    /// 금액 (`usd`): 1달러 미만은 소수 넷째 자리까지 (한 번 호출은 대개 몇 센트도 안 된다).
    public static func usd(_ c: Double?) -> String {
        guard let c else { return "가격 모름" }
        if c == 0 { return "$0" }
        if abs(c) < 0.0001 { return "$0.0001 미만" }
        if abs(c) < 1 { return "$" + fixed(c, 4) }
        return "$" + grouped(fixed(c, 2))
    }

    /// 토큰 수 (`tok`): '1.2M', '35K', '9,800'.
    public static func tok(_ n: Int) -> String {
        if n >= 1_000_000 { return fixed(Double(n) / 1e6, n >= 10_000_000 ? 0 : 1) + "M" }
        if n >= 10_000 { return "\(Int((Double(n) / 1e3).rounded()))K" }
        return number(n)
    }

    /// 소수 `digits` 자리 글 (JS `toFixed`): 가운데 값은 0 에서 먼 쪽으로 (1.25 → '1.3'). printf 는 짝수 쪽이라 쓰지 않는다.
    public static func fixed(_ x: Double, _ digits: Int) -> String {
        let scale = pow(10, Double(digits))
        let n = (x * scale).rounded(.toNearestOrAwayFromZero) / scale
        return String(format: "%.\(digits)f", n)
    }

    /// 세 자리마다 쉼표 (`toLocaleString`).
    public static func number(_ n: Int) -> String {
        n < 0 ? "-" + grouped(String(-n)) : grouped(String(n))
    }

    private static func grouped(_ text: String) -> String {
        let parts = text.split(separator: ".", maxSplits: 1)
        var head = String(parts[0])
        var out = ""
        while head.count > 3 {
            out = "," + head.suffix(3) + out
            head = String(head.dropLast(3))
        }
        return head + out + (parts.count > 1 ? "." + parts[1] : "")
    }

    /// 가격표 칸에 보일 수: 2 → '2', 0.375 → '0.375' (웹 입력칸이 보이는 모양).
    public static func plain(_ d: Double) -> String {
        if d == d.rounded(), abs(d) < 1e15 { return String(Int(d)) }
        return "\(d)"
    }

    // MARK: 이름

    /// 작품 이름 (`usageName`): 제목이 있고 폴더 이름과 다르면 '제목 (폴더)'.
    public static func projectName(_ p: String, titles: [String: String]) -> String {
        if let t = titles[p], !t.isEmpty, t != p { return "\(t) (\(p))" }
        return p
    }

    /// 작품 고르기 목록: 작품 목록, 기록에 있는 작품, 지금 고른 작품을 합쳐 이름순.
    public static func projectChoices(titles: [String: String], recorded: [String], current: String) -> [String] {
        var all = Set(titles.keys).union(recorded)
        if !current.isEmpty { all.insert(current) }
        return all.sorted()
    }

    public static func stage(_ s: String) -> String { stages[s] ?? (s.isEmpty ? "기타" : s) }
    public static func source(_ s: String) -> String { sources[s] ?? (s.isEmpty ? "기타" : s) }

    /// 기록이 없을 때.
    public static func empty(project: String, titles: [String: String]) -> String {
        let whose = project.isEmpty ? "" : "에 \(projectName(project, titles: titles))"
        return "이 기간\(whose)의 AI 호출 기록이 없어요. 이 화면이 생긴 뒤의 호출부터 기록해요 (mock 은 기록하지 않음)."
    }

    /// 가격표 설명에서 링크 뒤 글 (`viewPrices`). 앞은 '기본값은 <확인한 날>에 Google Gemini API 가격표'.
    public static let priceIntroTail = "(유료 등급 표준 요금)에서 옮긴 값이에요. 가격이 바뀌면 여기서 고치세요. 적용 시작일을 적은 줄은 그날부터의 호출에 쓰고(예고된 인상), 고치면 지난 기록과 자동 집필 예상 비용도 이 표로 다시 계산해요. 생각 토큰은 출력 요금, 배치 칸을 비우면 절반으로 쳐요. 로컬 모델은 0원이고, 표에 없는 Gemini 모델은 '가격 모름'으로 빠져요."
    public static let priceFooter = "모델 이름은 정확히 같거나 그 이름으로 시작하는 모델에 써요 (예: gemini-4-argon 은 gemini-4-argon-001 에도). 기본 모델을 고치면 그 모델의 예고 줄까지 내 줄로 대신해요. 기본 줄은 지울 수 없고, 값을 고치면 내 값으로 대신해요."

    public static let unpricedWarning = "가격표에 없는 모델이 있어요. 이 호출은 비용에서 빠졌어요. 가격을 넣으면 다시 계산해요."

    // MARK: 합계 칸

    public struct Tile: Equatable, Sendable {
        public let title: String
        public let value: String
        public let note: String
    }

    /// 위쪽 합계 칸 여섯 개.
    public static func tiles(_ t: UsageTotal) -> [Tile] {
        [
            Tile(title: "추정 비용", value: usd(t.cost), note: t.unpriced > 0 ? "가격 모르는 호출 \(t.unpriced)번 제외" : "가격표 기준"),
            Tile(title: "호출", value: "\(number(t.calls))번",
                 note: (t.failed > 0 ? "실패 \(t.failed)" : "실패 없음") + (t.retries > 0 ? " · 다시 요청 \(t.retries)" : "")),
            Tile(title: "입력 토큰", value: tok(t._in), note: t.cached > 0 ? "캐시 \(tok(t.cached)) (싸게 매겨짐)" : "캐시 없음"),
            Tile(title: "출력 토큰", value: tok(t.out), note: "생각(thinking) 토큰 포함"),
            Tile(title: "배치로 아낀 비용", value: usd(t.saved), note: t.batch > 0 ? "배치 \(t.batch)번" : "배치 안 씀"),
            Tile(title: "실패 · 재시도 비용", value: usd(t.wasted), note: "형식 오류로 다시 받은 것 포함"),
        ]
    }
}

// MARK: - 묶음 표

/// 단계별 · 모델별 · 화별 · 작품별 · 어디서 불렀나 표 (`usageTable`).
public enum UsageTableKind: String, CaseIterable, Sendable {
    case stage, model, episode, project, source

    public var title: String {
        switch self {
        case .stage: "단계별"
        case .model: "모델별"
        case .episode: "화별"
        case .project: "작품별"
        case .source: "어디서 불렀나"
        }
    }

    /// 첫 칸 머리 (제목에서 '별'을 뗀다).
    public var column: String { title.hasSuffix("별") ? String(title.dropLast()) : title }

    /// 표 아래 설명. 비면 빈 표에 '기록 없음'.
    public var note: String { self == .episode ? "화가 정해지지 않은 호출(설정, 기획 등)은 빠져요" : "" }

    public func rows(_ u: UsageSummary) -> [UsageGroup] {
        switch self {
        case .stage: u.byStage
        case .model: u.byModel
        case .episode: u.byEpisode
        case .project: u.byProject
        case .source: u.bySource
        }
    }
}

public struct UsageTableRow: Equatable, Sendable {
    public let label: String
    /// 이름 옆 작은 글 (모델의 '로컬 · 0원').
    public let sub: String
    /// 작품별 표에서 누르면 그 작품으로 거른다.
    public let project: String?
    public let failed: Int
    public let batch: Int
    public let calls: String
    public let input: String
    public let output: String
    public let cost: String
    /// 비중 막대 0~100.
    public let share: Int
}

extension UsageText {
    public static func tableRows(_ kind: UsageTableKind, _ rows: [UsageGroup], titles: [String: String]) -> [UsageTableRow] {
        let sum = rows.reduce(0) { $0 + $1.cost }
        let total = sum == 0 ? 1 : sum
        return rows.map { r in
            var label = ""
            var sub = ""
            var project: String?
            switch kind {
            case .stage:
                label = stage(r.stage ?? "")
            case .model:
                label = (r.model ?? "").isEmpty ? "(이름 없음)" : r.model!
                sub = r.backend == "local" ? "로컬 · 0원" : "Gemini"
            case .episode:
                label = "\(r.episode ?? 0)화"
            case .project:
                let p = r.project ?? ""
                if p.isEmpty {
                    sub = "작품 밖 (연구 서버 점검 등)"
                } else {
                    label = projectName(p, titles: titles)
                    project = p
                }
            case .source:
                label = source(r.source ?? "")
            }
            return UsageTableRow(
                label: label, sub: sub, project: project, failed: r.failed, batch: r.batch,
                calls: number(r.calls), input: tok(r._in), output: tok(r.out),
                cost: r.unpriced > 0 && r.cost == 0 ? "가격 모름" : usd(r.cost),
                share: Int((r.cost / total * 100).rounded())
            )
        }
    }
}

// MARK: - 호출 목록

public enum UsageList: String, CaseIterable, Sendable {
    case recent, trouble
}

public struct UsageCallRow: Equatable, Sendable {
    public enum State: String, Sendable { case failed, retried, ok }

    public let when: String
    public let place: String
    public let task: String
    /// 작업 아래 작은 글: '본문 · 화면에서 직접'.
    public let detail: String
    public let model: String
    public let batch: Bool
    public let input: String
    public let cached: String
    public let output: String
    public let thought: String
    public let seconds: String
    public let cost: String
    public let saved: String
    public let state: State
    public let error: String
    /// 입력 구성: 가장 큰 두 블록 (`usageBlocks`). 기록에 블록 크기가 없으면 빈 글.
    public let blocksTop: String
    public let blocks: [String]
    public let promptChars: String

    public var stateLabel: String {
        switch state {
        case .failed: "실패"
        case .retried: "다시 요청"
        case .ok: "성공"
        }
    }

    /// 긴 오류는 앞부분만 보이고 눌러서 펼친다.
    public var errorShort: String { error.count > 60 ? String(error.prefix(60)) + "…" : error }
}

extension UsageText {
    public static func tabs(_ u: UsageSummary) -> [(list: UsageList, label: String)] {
        [(.recent, "최근 호출"), (.trouble, "실패 · 재시도" + (u.trouble.isEmpty ? "" : " \(u.trouble.count)"))]
    }

    public static let noTrouble = "실패하거나 다시 요청한 호출이 없어요."
    public static let tokenNote = "형식이 어긋난 응답도 토큰은 쓴 것이라 비용에 들어가요."

    public static func callRow(_ r: UsageCall, timeZone: TimeZone = .current) -> UsageCallRow {
        let place = [r.project, r.episode.map { "\($0)화" } ?? ""].filter { !$0.isEmpty }.joined(separator: " ")
        let state: UsageCallRow.State = !r.ok ? .failed : (r.attempt > 1 ? .retried : .ok)
        var top = ""
        var all: [String] = []
        var chars = ""
        if let blocks = r.blocks, !blocks.isEmpty, let total = r.chars, total > 0 {
            let pairs = blocks.map { b in (b.first?.value1 ?? "", b.last?.value2 ?? 0) }
            let pct = { (v: Int) in "\(Int((Double(v) / Double(total) * 100).rounded()))%" }
            top = pairs.prefix(2).map { "\($0.0) \(pct($0.1))" }.joined(separator: " · ")
            all = pairs.map { "\($0.0) \(number($0.1))자 · \(pct($0.1))" }
            chars = "프롬프트 \(number(total))자"
        }
        return UsageCallRow(
            when: KoreanText.dateTime(r.at, timeZone: timeZone),
            place: place.isEmpty ? "-" : place,
            task: tasks[r.task] ?? stages[r.stage] ?? (r.task.isEmpty ? "-" : r.task),
            detail: "\(stages[r.stage] ?? r.stage) · \(sources[r.source] ?? r.source)",
            model: r.model, batch: r.batch,
            input: tok(r._in), cached: r.cached > 0 ? "캐시 \(tok(r.cached))" : "",
            output: tok(r.out + r.thought), thought: r.thought > 0 ? "생각 \(tok(r.thought))" : "",
            seconds: r.seconds.map { fixed($0, 1) + "초" } ?? "-",
            cost: usd(r.cost), saved: r.saved != 0 ? "아낌 \(usd(r.saved))" : "",
            state: state, error: r.error,
            blocksTop: top, blocks: all, promptChars: chars
        )
    }

    /// 목록 아래 줄 (`usageMoreLine`): 몇 건을 보여 주는지와 펼치기 · 더 불러오기. 서버는 최근 `limit` 건만 준다.
    public struct MoreLine: Equatable, Sendable {
        public enum Action: Sendable { case none, showAll, loadMore }
        /// 펼치기는 버튼 글이 곧 이 줄이다.
        public let text: String
        public let button: String?
        public let action: Action
    }

    public static func moreLine(_ u: UsageSummary, list: UsageList, all: Int, shown: Int, limit: Int) -> MoreLine {
        let total = list == .trouble ? u.troubleTotal : u.total.calls
        let of = total > shown ? " (기간 전체 \(number(total))건 중)" : ""
        if all > shown { return MoreLine(text: "", button: "최근 \(all)건 보기\(of)", action: .showAll) }
        if total > all && limit < 1000 { return MoreLine(text: "최근 \(shown)건을 보여요\(of).", button: "더 불러오기", action: .loadMore) }
        return MoreLine(text: "최근 \(shown)건을 보여요\(of).", button: nil, action: .none)
    }
}

// MARK: - 날짜별 막대

/// 날짜별 비용 막대 (`usageChart`). 비용이 모두 0(로컬만 씀)이면 호출 수로 그린다.
/// 기간 안의 날을 빈 날까지 모두 채운다 ('전체'는 첫 기록 날부터 오늘까지). 120일이 넘으면 주 단위로 묶는다.
/// 좁은 화면에서는 60일이 넘으면 묶는다 (90개 막대는 폭을 넘고 너무 가늘어 누를 수 없다).
public struct UsageChart: Equatable, Sendable {
    public struct Bar: Equatable, Sendable, Identifiable {
        /// 날짜 'YYYY-MM-DD' (주별이면 그 주 첫날).
        public let key: String
        /// 0~100. 기록이 있으면 2 이상.
        public let height: Int
        public let tip: String
        public var id: String { key }
    }

    public let bars: [Bar]
    public let weekly: Bool
    public let byCost: Bool
    public let title: String
    public let scale: String
    public let first: String
    public let last: String

    public static let hint = "막대를 누르거나, 차트에 초점을 두고 ←/→ 키로 날짜별 값을 봐요."

    public var label: String { "\(weekly ? "주별" : "날짜별") \(byCost ? "비용" : "호출 수") 막대. ←/→ 키로 옮겨 값을 봐요" }

    public func tip(_ key: String?) -> String? { bars.first { $0.key == key }?.tip }

    struct Sum {
        var cost = 0.0, calls = 0, input = 0, output = 0, failed = 0
    }

    public static func make(_ byDay: [UsageGroup], days: Int, today: Date = Date(), narrow: Bool = false,
                            calendar: Calendar = .current) -> UsageChart {
        var cal = calendar
        cal.locale = Locale(identifier: "en_US_POSIX")
        let fmt = DateFormatter()
        fmt.calendar = cal
        fmt.timeZone = cal.timeZone
        fmt.locale = cal.locale
        fmt.dateFormat = "yyyy-MM-dd"
        let start = cal.startOfDay(for: today)
        let from: Date
        if days > 0 {
            from = cal.date(byAdding: .day, value: -days + 1, to: start)!
        } else if let firstDay = byDay.compactMap(\.day).sorted().first, let d = fmt.date(from: firstDay) {
            from = d
        } else {
            from = start
        }
        var keys: [String] = []
        var x = from
        while x <= start {
            keys.append(fmt.string(from: x))
            x = cal.date(byAdding: .day, value: 1, to: x)!
        }
        var sums: [String: Sum] = [:]
        for r in byDay {
            guard let d = r.day else { continue }
            sums[d] = Sum(cost: r.cost, calls: r.calls, input: r._in, output: r.out, failed: r.failed)
        }
        let weekly = keys.count > 120 || (narrow && keys.count > 60)
        if weekly {
            var weeks: [String: Sum] = [:]
            var order: [String] = []
            for (i, d) in keys.enumerated() {
                let w = keys[i - i % 7]
                if weeks[w] == nil {
                    weeks[w] = Sum()
                    order.append(w)
                }
                if let r = sums[d] {
                    weeks[w]!.cost += r.cost
                    weeks[w]!.calls += r.calls
                    weeks[w]!.input += r.input
                    weeks[w]!.output += r.output
                    weeks[w]!.failed += r.failed
                }
            }
            keys = order
            sums = weeks.filter { $0.value.calls > 0 }
        }
        let byCost = byDay.contains { $0.cost > 0 }
        let value = { (r: Sum?) -> Double in r.map { byCost ? $0.cost : Double($0.calls) } ?? 0 }
        let top = keys.map { value(sums[$0]) }.max() ?? 0
        let max = top > 0 ? top : 1
        let bars = keys.map { d -> Bar in
            let r = sums[d]
            let h = r == nil ? 0 : Swift.max(2, Int((value(r) / max * 100).rounded()))
            let when = weekly ? "\(d) 주" : d
            let tip = r.map { r in
                "\(when): \(UsageText.usd(r.cost)) · 호출 \(r.calls)번 · 입력 \(UsageText.tok(r.input)) / 출력 \(UsageText.tok(r.output))"
                    + (r.failed > 0 ? " · 실패 \(r.failed)" : "")
            } ?? "\(when): 호출 없음"
            return Bar(key: d, height: h, tip: tip)
        }
        let most = byCost ? UsageText.usd(max) : "\(Int(max))번"
        return UsageChart(
            bars: bars, weekly: weekly, byCost: byCost,
            title: "\(weekly ? "주별" : "날짜별") \(byCost ? "추정 비용" : "호출 수")",
            scale: "가장 많은 \(weekly ? "주" : "날") \(most) · 막대를 누르면 자세히",
            first: String((keys.first ?? "").dropFirst(5)), last: String((keys.last ?? "").dropFirst(5))
        )
    }

    /// 키보드로 옮기기: ←/→ 는 한 칸, Home/End 는 처음과 끝. 고른 막대가 없으면 ← 는 끝, → 는 처음.
    public enum Move: Sendable { case left, right, home, end }

    public func move(_ m: Move, from key: String?) -> String? {
        guard !bars.isEmpty else { return nil }
        let i = bars.firstIndex { $0.key == key }
        let at: Int
        switch m {
        case .left: at = i.map { $0 - 1 } ?? bars.count - 1
        case .right: at = i.map { $0 + 1 } ?? 0
        case .home: at = 0
        case .end: at = bars.count - 1
        }
        return bars[Swift.max(0, Swift.min(bars.count - 1, at))].key
    }
}
