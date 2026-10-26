import CanonAPI
import CanonCore
import Foundation

public typealias LoglineParts = Components.Schemas.LoglineParts
public typealias ToneDials = Components.Schemas.ToneDials
public typealias Meta = Components.Schemas.Meta

/// 로그라인 다섯 칸. 서버 `canon/logline.py` · 웹 `app.js` 의 `LOGLINE_SLOTS` 와 같은 순서 · 문구라 함께 고친다.
public enum LoglineField: String, CaseIterable, Sendable, Identifiable {
    case who, why, goal, block, stake

    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .who: "누가"
        case .why: "무엇 때문에"
        case .goal: "무엇을 하려 하나"
        case .block: "무엇이 막나"
        case .stake: "무엇이 걸렸나"
        }
    }

    public var hint: String {
        switch self {
        case .who: "이름보다 특징이 먼저 보이게"
        case .why: "이야기를 시작하게 만드는 일"
        case .goal: "눈에 보이는 행동, '~한다'로 끝내기"
        case .block: "사람이나 힘"
        case .stake: "선택, 비워도 돼요"
        }
    }

    public func get(_ p: LoglineParts?) -> String {
        switch self {
        case .who: p?.who ?? ""
        case .why: p?.why ?? ""
        case .goal: p?.goal ?? ""
        case .block: p?.block ?? ""
        case .stake: p?.stake ?? ""
        }
    }

    public func set(_ p: inout LoglineParts, _ value: String) {
        switch self {
        case .who: p.who = value
        case .why: p.why = value
        case .goal: p.goal = value
        case .block: p.block = value
        case .stake: p.stake = value
        }
    }
}

/// 로그라인 합치기 · 점검 (서버 `logline.compose` · `checks`, 웹 `composeLogline` · `loglineChecks` · `updateLogline`).
/// 셋이 같은 규칙이라 함께 고친다.
public enum Logline {
    public struct Check: Equatable, Sendable {
        public let ok: Bool
        public let text: String
    }

    /// 칸이 모두 비었을 때 미리보기 자리 글.
    public static let empty = "칸을 채우면 여기에 로그라인이 만들어져요."

    /// '{누가}이/가 {무엇 때문에} {목표}. 하지만 {막는 것}. {걸린 것}.' 빈 칸은 건너뛴다.
    public static func compose(_ p: LoglineParts?) -> String {
        let v = LoglineField.allCases.map { trimDots($0.get(p).trimmingCharacters(in: .whitespacesAndNewlines)) }
        let (who, why, goal, block, stake) = (v[0], v[1], v[2], v[3], v[4])
        var out = ""
        if !who.isEmpty { out += who + KoreanText.josa(who, "이", "가") + " " }
        if !why.isEmpty { out += why + " " }
        if !goal.isEmpty { out += goal + "." }
        if !block.isEmpty { out += (out.isEmpty ? "" : " 하지만 ") + block + "." }
        if !stake.isEmpty { out += " " + stake + "." }
        return out.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public static func isEmpty(_ p: LoglineParts?) -> Bool {
        LoglineField.allCases.allSatisfy { $0.get(p).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    /// 형식 점검. 참고용이며 다음 단계를 막지 않는다. 길이는 Python `len` 처럼 코드 포인트로 센다.
    public static func checks(_ p: LoglineParts?) -> [Check] {
        let n = length(compose(p))
        let who = LoglineField.who.get(p).split(whereSeparator: \.isWhitespace)
        return [
            Check(ok: who.count > 1, text: "주인공에게 이름 말고 특징이 있다"),
            Check(ok: !blank(LoglineField.why.get(p)), text: "이야기를 시작하게 만드는 일이 있다"),
            Check(ok: LoglineField.goal.get(p).trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix("다"),
                  text: "목표가 눈에 보이는 행동이다 ('~한다'로 끝남)"),
            Check(ok: !blank(LoglineField.block.get(p)), text: "목표를 막는 사람이나 힘이 있다"),
            Check(ok: (40...150).contains(n), text: "길이가 40~150자 사이다"),
        ]
    }

    /// 직접 고친 문장을 쓰는 중: 칸 내용과 다르다 (웹 `loglineManual`).
    public static func isManual(_ m: Meta?) -> Bool {
        let line = m?.logline ?? ""
        return !isEmpty(m?.loglineParts) && !blank(line) && line != compose(m?.loglineParts)
    }

    /// 칸은 비었고 한 문장으로만 저장된 옛 로그라인.
    public static func isLegacy(_ m: Meta?) -> Bool {
        isEmpty(m?.loglineParts) && !blank(m?.logline ?? "")
    }

    /// 칸 하나를 고친다. 지금 문장이 고치기 전 칸으로 합친 문장이거나 비었으면 새 칸 내용으로 바꾼다.
    /// 직접 고친 문장은 그대로 둔다 (웹 `updateLogline(prev)`).
    public static func set(_ field: LoglineField, _ value: String, in m: inout Meta) {
        var parts = m.loglineParts ?? LoglineParts()
        let prev = compose(parts)
        field.set(&parts, value)
        m.loglineParts = parts
        let line = m.logline ?? ""
        if !isEmpty(parts), blank(line) || line == prev { m.logline = compose(parts) }
    }

    /// 칸을 예시로 모두 바꾼다 (웹 `useExample`). 직접 고친 문장도 칸 내용으로 다시 만든다.
    public static func fill(_ example: LoglineParts, in m: inout Meta) {
        var parts = m.loglineParts ?? LoglineParts()
        for f in LoglineField.allCases { f.set(&parts, f.get(example)) }
        m.loglineParts = parts
        if !isEmpty(parts) { m.logline = compose(parts) }
    }

    /// '칸 내용으로 다시 만들기'
    public static func rebuild(_ m: inout Meta) {
        m.logline = compose(m.loglineParts)
    }

    /// 칸 아래 '○자 · 점검은 참고용이에요'
    public static func lengthNote(_ m: Meta?) -> String {
        "\(length(m?.logline ?? ""))자 · 점검은 참고용이에요"
    }

    static func length(_ s: String) -> Int { s.unicodeScalars.count }

    static func blank(_ s: String) -> Bool { s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    static func trimDots(_ s: String) -> String {
        var s = Substring(s)
        while s.hasSuffix(".") { s = s.dropLast() }
        return String(s)
    }
}

/// 톤 다이얼 (서버 `logline.TONE_WORDS` · `tone_text`, 웹 `TONE_DIALS` · `TONE_WORDS` · `toneText` · `setDial`).
public enum ToneDial: String, CaseIterable, Sendable, Identifiable {
    case dark, serious, slow

    public var id: String { rawValue }

    /// 양 끝 이름 (왼쪽, 오른쪽).
    public var ends: (left: String, right: String) {
        switch self {
        case .dark: ("밝다", "어둡다")
        case .serious: ("가볍다", "진지하다")
        case .slow: ("빠르다", "느리다")
        }
    }

    /// 1~4단계마다 (이어지는 말, 끝맺는 말).
    public var words: [(String, String)] {
        switch self {
        case .dark: [("밝고", "밝다"), ("조금 밝고", "조금 밝다"), ("조금 어둡고", "조금 어둡다"), ("어둡고", "어둡다")]
        case .serious: [("가볍고", "가볍다"), ("조금 가볍고", "조금 가볍다"), ("조금 진지하고", "조금 진지하다"), ("진지하고", "진지하다")]
        case .slow: [("호흡이 빠르다", "호흡이 빠르다"), ("호흡이 조금 빠르다", "호흡이 조금 빠르다"),
                     ("호흡이 조금 느리다", "호흡이 조금 느리다"), ("호흡이 느리다", "호흡이 느리다")]
        }
    }

    public func get(_ d: ToneDials?) -> Int {
        switch self {
        case .dark: d?.dark ?? 0
        case .serious: d?.serious ?? 0
        case .slow: d?.slow ?? 0
        }
    }

    func set(_ d: inout ToneDials, _ v: Int) {
        switch self {
        case .dark: d.dark = v
        case .serious: d.serious = v
        case .slow: d.slow = v
        }
    }

    /// 지금 단계의 끝맺는 말. 고르지 않았으면 빈 글.
    public func now(_ d: ToneDials?) -> String {
        let v = get(d)
        return (1...4).contains(v) ? words[v - 1].1 : ""
    }
}

public enum Tone {
    /// 다이얼을 문장으로. 고르지 않은 다이얼은 뺀다. 예: '조금 어둡고 진지하고 호흡이 느리다'.
    public static func text(_ d: ToneDials?) -> String {
        let words = ToneDial.allCases.compactMap { k -> (String, String)? in
            let v = k.get(d)
            return (1...4).contains(v) ? k.words[v - 1] : nil
        }
        return words.enumerated().map { i, w in i == words.count - 1 ? w.1 : w.0 }.joined(separator: " ")
    }

    /// 다이얼을 고른다. 고른 단계를 다시 누르면 끈다. 직접 쓴 톤 문장은 덮지 않는다 (웹 `setDial`).
    public static func set(_ dial: ToneDial, _ value: Int, in m: inout Meta) {
        var d = m.toneDials ?? ToneDials()
        let prev = text(d)
        dial.set(&d, dial.get(d) == value ? 0 : value)
        m.toneDials = d
        let tone = m.tone ?? ""
        if Logline.blank(tone) || tone == prev { m.tone = text(d) }
    }

    /// 다이얼 문장이 톤 문장과 달라 바꾸기를 권할 문장. 권할 것이 없으면 nil (웹 `toneBox` 의 offer).
    public static func offer(_ m: Meta?) -> String? {
        let dial = text(m?.toneDials)
        let tone = m?.tone ?? ""
        return !dial.isEmpty && !Logline.blank(tone) && tone != dial ? dial : nil
    }
}
