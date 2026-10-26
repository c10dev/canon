import CanonAPI
import CanonCore
import Foundation

/// 온기 다섯 구간. 경계는 `dynamics.warmth_word` 와 같고 색은 웹 `cast.js` 의 `WARMTH_BANDS` 와 같다 (빨강 ↔ 회색 ↔ 파랑).
public struct WarmthBand: Sendable, Equatable {
    /// 이 값보다 작으면 이 구간
    public let cut: Double
    public let hex: UInt32
    public let word: String

    public static let all: [WarmthBand] = [
        WarmthBand(cut: -0.6, hex: 0xB42318, word: "적대한다"),
        WarmthBand(cut: -0.2, hex: 0xE0726A, word: "반감이 있다"),
        WarmthBand(cut: 0.2, hex: 0x9A9890, word: "무덤덤하다"),
        WarmthBand(cut: 0.6, hex: 0x5598E7, word: "호감이 있다"),
        WarmthBand(cut: .infinity, hex: 0x1C5CAB, word: "깊이 아낀다"),
    ]

    public static func index(_ warmth: Double) -> Int {
        all.firstIndex { warmth < $0.cut } ?? all.count - 1
    }

    public static func of(_ warmth: Double) -> WarmthBand { all[index(warmth)] }
}

/// 인물 등급. 관계도 원 크기와 이름 (웹 `TIER_R` · `TIER_NAME`).
public enum CastTier: String, Sendable, CaseIterable {
    case main, support, minor

    public init(_ t: CastCharacter.TierPayload?) {
        self = CastTier(rawValue: (t ?? .main).rawValue) ?? .main
    }

    public var radius: Double {
        switch self {
        case .main: 26
        case .support: 20
        case .minor: 15
        }
    }

    public var label: String {
        switch self {
        case .main: "주역"
        case .support: "조연"
        case .minor: "단역"
        }
    }
}

/// 인물 화면 문구. 웹 `cast.js` 와 같은 글을 HTML 없이 만든다.
public enum CastText {
    /// 두 사람 긴장 점 색 (웹 `TENSION_FILL`). '낮음'은 그리지 않는다.
    public static let tensionFill: [(word: String, hex: UInt32)] = [("보통", 0xF2C894), ("높음", 0xC2620A), ("매우 높음", 0xB42318)]
    /// 쌍 그래프: 앞 인물 → 뒤 인물, 뒤 → 앞 (웹 `PAIR_COLORS`)
    public static let pairColors: [UInt32] = [0x2A78D6, 0xEB6834]
    /// 좋은 사건 (웹 `app.js` 의 `GOOD_EVENTS`). 나머지는 나쁜 사건으로 칠한다.
    public static let goodEvents: Set<String> = ["도움", "희생", "약속이행", "칭찬", "진심고백", "사과", "공동경험"]

    public static func tensionHex(_ word: String) -> UInt32? { tensionFill.first { $0.word == word }?.hex }

    public static func intensity(_ n: Int?) -> String {
        switch n ?? 2 {
        case 1: "가벼움"
        case 2: "보통"
        case 3: "결정적"
        default: ""
        }
    }

    /// '1화 시작 전', '3화 반영 뒤 · 다리 위에서'
    public static func frameLabel(_ episode: Int, title: String?) -> String {
        if episode == 0 { return "1화 시작 전" }
        return "\(episode)화 반영 뒤" + (title.map { " · \($0)" } ?? "")
    }

    /// JS `toFixed` 와 같은 소수 자리. 딱 절반이면 0 에서 먼 쪽으로 올린다 (printf 는 짝수 쪽이라 5.25 → 5.2).
    /// 음수는 부호를 떼고 반올림한 뒤 붙인다 (-0.001 → '-0.00'). -0 은 '0.00'.
    public static func fixed(_ v: Double, _ digits: Int) -> String {
        var exact = Decimal(string: String(format: "%.30f", abs(v))) ?? Decimal(abs(v))
        var rounded = Decimal()
        NSDecimalRound(&rounded, &exact, digits, .plain)
        return (v < 0 ? "-" : "") + String(format: "%.\(digits)f", NSDecimalNumber(decimal: rounded).doubleValue)
    }

    static func signed(_ v: Double) -> String { (v >= 0 ? "+" : "") + fixed(v, 2) }

    /// 한 방향 관계 (웹 `tieText`).
    public static func tie(_ t: CastTie?, numbers: Bool) -> String {
        guard let t else { return "아직 관계가 없어요" }
        if numbers {
            return "온기 \(signed(t.warmth)) · 신뢰 \(fixed(t.trust, 2)) (증거 \(fixed(t.evidence, 1))) · 원한 \(fixed(t.grievance, 2)) · 서열 \(signed(t.status)) · 친숙 \(fixed(t.familiarity, 2)) · 단계 \(t.stage)"
        }
        return "\(t.warmthWord), \(t.trustWord)\(t.grievance >= 0.3 ? ", 풀리지 않은 원한" : "") · 단계 \(t.stage)"
    }

    /// 두 사람 긴장 (웹 `tensionText`).
    public static func tension(_ p: CastPair?, numbers: Bool) -> String {
        guard let p else { return "" }
        return numbers ? "긴장 \(fixed(p.tension, 1))/10" : "긴장 \(p.tensionWord)"
    }

    /// 관계선 설명 (웹 관계도 선의 title).
    public static func edge(_ t: CastTie, from: String, to: String, numbers: Bool) -> String {
        "\(from) → \(to): \(t.warmthWord), \(t.trustWord) · 단계 \(t.stage)"
            + (numbers ? " (온기 \(fixed(t.warmth, 2)), 신뢰 \(fixed(t.trust, 2)), 친숙 \(fixed(t.familiarity, 2)))" : "")
    }

    /// '플롯 등장 5화 (1~9화) · 시점 인물 2화 · 3화에 처음 등장'
    public static func appearance(_ apps: [CastAppearance], firstEp: Int?) -> String {
        var s: String
        if let a = apps.first, let b = apps.last {
            let pov = apps.filter(\.pov).count
            s = "플롯 등장 \(apps.count)화 (\(a.n)~\(b.n)화)" + (pov > 0 ? " · 시점 인물 \(pov)화" : "")
        } else {
            s = "플롯에 나오는 화가 아직 없어요"
        }
        if let f = firstEp, f > 0 { s += " · \(f)화에 처음 등장" }
        return s
    }

    /// 불안정한 삼각 구도 알림 (웹 `castTriads`).
    public static func triads(_ triads: [[String]], name: (String) -> String) -> String? {
        guard !triads.isEmpty else { return nil }
        let items = triads.map { $0.map(name).joined(separator: " · ") }.joined(separator: ", ")
        return "불안정한 삼각 구도: \(items). 두 사람은 가깝고 한 쌍은 적대라, 누군가 편을 바꾸거나 화해하거나 관계 하나가 끊어지는 쪽으로 압력이 있어요."
    }

    /// 관계 사건 한 줄: '도현 → 서윤 · 도움 결정적 (목격)'. `viewer` 가 행동하거나 받지 않았으면 목격이다.
    public static func event(_ e: CastEvent, name: (String) -> String, viewer: String? = nil) -> String {
        let witness = viewer.map { $0 != e.actor && $0 != e.target } ?? false
        return "\(name(e.actor)) → \(name(e.target)) · \(e.kind.rawValue) \(intensity(e.intensity))\(witness ? " (목격)" : "")"
    }

    public static func isGood(_ e: CastEvent) -> Bool { goodEvents.contains(e.kind.rawValue) }

    /// 타임라인 한 화에서 바뀐 것 (라벨, 글). 사건은 따로 그린다.
    public static func changes(_ r: CastTimelineRow) -> [(label: String, text: String)] {
        var out: [(String, String)] = []
        if let v = r.changes.emotionalState { out.append(("감정", v)) }
        if let v = r.changes.currentGoal { out.append(("목표", v)) }
        if let v = r.changes.location { out.append(("위치", v)) }
        if let k = r.changes.knows { out.append(("알게 됨", k.joined(separator: ", "))) }
        for s in r.secrets { out.append(("비밀 생김", s)) }
        return out
    }

    /// 타임라인에 보일 화. 고른 시점 앞뒤 10화 (1화 시작 전이면 마지막 30화). 장편에서 끝없이 길어지지 않게.
    public static func shownTimeline(_ rows: [CastTimelineRow], at episode: Int?, all: Bool) -> [CastTimelineRow] {
        if all { return rows }
        if let e = episode, e > 0 { return rows.filter { abs($0.n - e) <= 10 } }
        return Array(rows.suffix(30))
    }

    /// 추이 그래프에 그릴 시점 범위. 40개를 넘으면 고른 시점 주변 31개만 (웹 `castChart`).
    public static func chartWindow(count: Int, at i: Int, all: Bool) -> ClosedRange<Int> {
        guard count > 0 else { return 0...0 }
        guard count > 40, !all else { return 0...(count - 1) }
        let a0 = max(0, min(i - 15, count - 31))
        return a0...min(count - 1, a0 + 30)
    }

    /// 등장 줄 칸 너비 (웹 `castStrip`).
    public static func stripStep(_ total: Int) -> Double { total <= 40 ? 14 : total <= 120 ? 6 : 3 }

    /// 등장표 칸 너비. 6pt 보다 좁아지지 않게, 넘치면 가로로 스크롤한다 (웹 `castTable`).
    public static func tableStep(_ total: Int) -> Double { total <= 40 ? 18 : total <= 120 ? 8 : 6 }

    /// 등장표 아래 화 번호를 몇 화마다 쓰는지.
    public static func tickEvery(_ step: Double) -> Int { step >= 16 ? 1 : step >= 8 ? 5 : 10 }

    /// 등장표 순서: 주역 · 조연 · 단역, 같은 등급은 처음 나온 화 순서.
    public static func tableOrder(_ chars: [CastCharacter], appearances: (String) -> [CastAppearance]) -> [CastCharacter] {
        let rank: (CastCharacter) -> Int = { CastTier.allCases.firstIndex(of: CastTier($0.tier)) ?? 0 }
        return chars.enumerated().sorted { x, y in
            let a = (rank(x.element), appearances(x.element.id).first?.n ?? 9999, x.offset)
            let b = (rank(y.element), appearances(y.element.id).first?.n ?? 9999, y.offset)
            return a < b
        }.map(\.element)
    }

    /// 등장표 위 구간 띠: 장편은 아크, 단편은 기승전결. `tone` 은 1~4 (기 · 승 · 전 · 결 색), 모르면 0.
    public struct Band: Sendable, Equatable {
        public let start: Int
        public let end: Int
        public let label: String
        public let tone: Int

        public init(start: Int, end: Int, label: String, tone: Int) {
            self.start = start
            self.end = end
            self.label = label
            self.tone = tone
        }
    }

    public static func bands(_ p: CastProject?, serial: Bool) -> [Band] {
        guard let p else { return [] }
        if serial {
            return (p.storyArcs ?? []).map { Band(start: $0.startEp, end: $0.endEp, label: "아크 \($0.number)", tone: (($0.number - 1) % 4 + 4) % 4 + 1) }
        }
        let acts = ["기", "승", "전", "결"]
        return (p.arc ?? []).map { a in
            Band(start: a.startEp, end: a.endEp, label: a.name.rawValue, tone: (acts.firstIndex(of: a.name.rawValue) ?? -1) + 1)
        }
    }

    public static func status(_ raw: String) -> String { EpisodeStatus(rawValue: raw)?.label ?? raw }
}
