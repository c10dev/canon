import CanonAPI
import CanonCore
import Foundation

public typealias StyleProfile = Components.Schemas.StyleProfile
public typealias StyleMarker = Components.Schemas.StyleMarker
public typealias StyleDevice = Components.Schemas.StyleDevice
public typealias StyleMetrics = Components.Schemas.StyleMetrics
public typealias StyleLink = Components.Schemas.StyleLink
public typealias StyleSummary = Components.Schemas.StyleSummary

/// 문체 화면 문구 · 규칙. 웹 `app.js` 의 `styleBlank` · `styleChangeWho` · `styleLibraryCard` · `baselineRows` 와 같아 함께 고친다.
public enum StyleText {
    /// 예시 원문 최소 글자 수 (서버 `web.analyze_style` 과 같은 기준).
    public static let minSample = 200

    /// 스타일 프로필 칸이 모두 비었다 (서버 `library.blank`, 웹 `styleBlank`).
    public static func blank(_ s: StyleProfile?) -> Bool {
        guard let s else { return true }
        let texts = [s.narrationPov, s.tense, s.sentenceRhythm, s.descriptionDensity, s.dialogueRatio, s.dialogueStyle,
                     s.innerMonologue, s.pacing, s.sceneTransition, s.vocabulary]
        if texts.contains(where: { !($0 ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) { return false }
        let lists = [s.dos?.count, s.donts?.count, s.bannedPhrases?.count, s.markers?.count, s.devices?.count, s.samplePassages?.count]
        return !lists.contains { ($0 ?? 0) > 0 }
    }

    /// 라이브러리 항목과 연결돼 있다 (같음 · 다름).
    public static func linked(_ l: StyleLink?) -> Bool { l?.state == "same" || l?.state == "changed" }

    /// 라이브러리와 다를 때 어느 쪽이 바뀌었는지 (서버 `library.link_state` 의 mine · theirs, 웹 `styleChangeWho`).
    public static func changeWho(_ l: StyleLink) -> String {
        let mine = !(l.mine ?? []).isEmpty
        let theirs = !(l.theirs ?? []).isEmpty
        let applied = l.applied ?? 0, version = l.version ?? 0
        if !(l.baseKnown ?? false) {
            return applied > 0 && version > applied ? "이 작품은 \(applied)번 버전, 라이브러리는 \(version)번 버전이에요" : "이 작품에서 고쳤거나 라이브러리가 바뀌었어요"
        }
        if mine && theirs { return "이 작품도 고쳤고, 라이브러리도 \(applied)번 → \(version)번 버전으로 바뀌었어요" }
        if theirs { return "라이브러리가 \(applied)번 → \(version)번 버전으로 바뀌었어요. 이 작품은 그대로예요" }
        return "이 작품에서 고쳤어요. 라이브러리는 가져온 버전 그대로예요"
    }

    /// 라이브러리가 더 새 버전이면 '가져오기', 작품만 고쳤으면 '되돌리기'.
    public static func newer(_ l: StyleLink) -> Bool {
        !(l.theirs ?? []).isEmpty || (!(l.baseKnown ?? false) && (l.applied ?? 0) > 0 && (l.version ?? 0) > (l.applied ?? 0))
    }

    public static func pullLabel(_ l: StyleLink) -> String {
        newer(l) ? "라이브러리 최신 버전 가져오기" : "라이브러리 버전으로 되돌리기"
    }

    /// 연결 상태 한 줄 (웹 `styleLibraryCard` 의 status).
    public enum Status: Equatable, Sendable {
        case none(blank: Bool)
        case missing
        case same(name: String, version: Int)
        case changed(name: String, who: String)

        public var text: String {
            switch self {
            case .none(true): "아직 문체가 없어요. 아래에 원문을 붙여 넣어 분석하거나 라이브러리에서 고르세요."
            case .none(false): "이 작품에서 직접 만든 문체예요."
            case .missing: "가져온 라이브러리 항목이 지워졌어요. 작품에 복사된 문체는 그대로 써요."
            case let .same(name, version): "라이브러리와 같음 · \(name) · \(version)번 버전"
            case let .changed(name, who): "라이브러리와 다름 · \(name) · \(who)"
            }
        }
    }

    public static func status(_ l: StyleLink?, blank: Bool) -> Status {
        switch l?.state {
        case "missing": .missing
        case "same": .same(name: l?.name ?? "", version: l?.version ?? 0)
        case "changed": .changed(name: l?.name ?? "", who: changeWho(l!))
        default: .none(blank: blank)
        }
    }

    /// '어느 칸이 다른지' 줄. 다른 칸이 없으면 빈 목록.
    public static func diffLines(_ l: StyleLink) -> [String] {
        guard l.state == "changed" else { return [] }
        let fields = { (list: [Components.Schemas.StyleFieldDiff]) in list.map(\.label).joined(separator: ", ") }
        let mine = l.mine ?? [], theirs = l.theirs ?? []
        guard !mine.isEmpty || !theirs.isEmpty else { return [] }
        var out: [String] = []
        if !mine.isEmpty { out.append("이 작품에서 고친 칸: \(fields(mine))") }
        if !theirs.isEmpty { out.append("라이브러리 \(l.version ?? 0)번 버전에서 바뀐 칸: \(fields(theirs))") }
        out.append("올리기는 작품 쪽을 라이브러리 새 버전으로, 가져오기 · 되돌리기는 라이브러리 쪽을 작품에 가져와요.")
        return out
    }

    /// 분석 결과로 프로필을 바꾸기 전에 묻는 말. 묻지 않아도 되면 nil (웹 `analyzeStyle`).
    public static func analyzeQuestion(_ s: StyleProfile?, link: StyleLink?) -> String? {
        let has = !(s?.narrationPov ?? "").isEmpty || !(s?.samplePassages ?? []).isEmpty
        let unlink = linked(link) ? "\n라이브러리 '\(link?.name ?? "")' 연결도 끊겨요. 라이브러리 항목은 그대로예요." : ""
        guard has || !unlink.isEmpty else { return nil }
        return "분석 결과로 지금 스타일 프로필을 바꿀까요? 저장하기 전에는 저장 띠의 '되돌리기'로 되돌릴 수 있어요.\(unlink)"
    }

    /// 라이브러리 문체를 적용하기 전에 묻는 말 (웹 `useLibStyle`).
    public static func useQuestion(_ name: String, link: StyleLink?) -> String {
        let lost = link?.state == "same" ? "" : "\n지금 문체는 라이브러리에 없어서 되돌릴 수 없어요. 남겨 두려면 취소하고 '이 문체를 라이브러리에 새로 저장'을 먼저 누르세요."
        return "'\(name)' 문체를 이 작품에 적용할까요? 지금 작품의 스타일 프로필은 바뀌어요.\(lost)"
    }

    /// 라이브러리에 새로 저장할 때의 안내 (웹 `keepStyle`).
    public static func keepNote(sample: String, link: StyleLink?) -> String {
        let bare = sample.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "이 화면에 붙여 넣은 원문이 없어 원문 없이 저장돼요." : ""
        let name = link?.name ?? ""
        let moved = linked(link) ? "이 작품은 새 항목에 연결되고, 지금 연결된 '\(name)' 연결은 끊겨요. '\(name)' 항목은 그대로 남아요." : ""
        return [bare, moved].filter { !$0.isEmpty }.joined(separator: "\n")
    }

    /// 라이브러리 새 버전으로 올릴 때의 안내 (웹 `pushStyle`).
    public static func pushNote(_ l: StyleLink, usedBy: [String], project: String) -> String {
        let others = usedBy.filter { $0 != project }
        var out = "이 작품의 문체를 라이브러리 '\(l.name ?? "")' 의 새 버전으로 올려요. 예전 버전은 남아 있어 되돌릴 수 있어요."
        if !others.isEmpty { out += "\n다른 작품(\(others.joined(separator: ", ")))은 다시 적용하기 전까지 바뀌지 않아요." }
        let theirs = l.theirs ?? []
        if !theirs.isEmpty { out += "\n라이브러리 \(l.version ?? 0)번 버전에서 바뀐 칸(\(theirs.map(\.label).joined(separator: ", ")))은 이 작품 값으로 덮여요." }
        return out
    }

    /// 라이브러리 버전을 가져오기 전에 묻는 말 (웹 `pullStyle`).
    public static func pullQuestion(_ l: StyleLink) -> String {
        let lost = !(l.mine ?? []).isEmpty || !(l.baseKnown ?? false) ? " 작품에서 고친 내용은 사라져요." : ""
        return "이 작품의 문체를 라이브러리 '\(l.name ?? "")' \(l.version ?? 0)번 버전으로 바꿀까요?\(lost)"
    }

    /// 라이브러리 고르기 줄 '이름 · 출처'.
    public static func optionLabel(_ s: StyleSummary) -> String {
        s.source.isEmpty ? s.name : "\(s.name) · \(s.source)"
    }

    /// 기준 지표 줄 (웹 `baselineRows`). JS `toFixed` · `Math.round` 처럼 반올림한다.
    public static func baselineRows(_ b: StyleMetrics) -> [(String, String)] {
        let pct = { (v: Double?) in v.map { "\(Int(($0 * 100).rounded()))%" } ?? "–" }
        return [
            ("문장 평균 길이", "\(fixed(b.sentenceLenMean ?? 0, 1))자"),
            ("문장 길이 변화폭", fixed(b.sentenceLenCv ?? 0, 2)),
            ("문단 평균 길이", "\(Int((b.paragraphLenMean ?? 0).rounded()))자"),
            ("대사 비율", pct(b.dialogueRatio)),
            ("과거형 비율", pct(b.pastTenseRatio)),
            ("어휘 다양도", b.mattr.map { fixed($0, 2) } ?? "–"),
            ("쉼표 문장 비율", pct(b.commaSentenceRatio)),
        ]
    }

    public static let noBaseline = "원문을 넣고 저장하면 문장 길이, 대사 비율 같은 기준 지표를 재요. 본문을 쓴 뒤 문체가 얼마나 벗어났는지 비교하는 기준이 돼요."

    /// JS `toFixed` 와 같은 소수 자리: double 의 정확한 값으로 반올림하고, 딱 절반이면 올린다 (FeatureCast `CastText.fixed` 와 같다).
    /// 23.45 는 실제로 23.4499… 라 '23.4'. 지표는 0 이상이라 부호는 다루지 않는다.
    static func fixed(_ v: Double, _ digits: Int) -> String {
        var exact = Decimal(string: String(format: "%.30f", v)) ?? Decimal(v)
        var rounded = Decimal()
        NSDecimalRound(&rounded, &exact, digits, .plain)
        return String(format: "%.\(digits)f", NSDecimalNumber(decimal: rounded).doubleValue)
    }

    /// 프로필의 글 칸 (웹 `profileFields` 의 두 칸씩 줄, 순서 그대로).
    public static var textFields: [(label: String, path: WritableKeyPath<StyleProfile, String?>, lines: Int)] {
        [("시점", \.narrationPov, 1), ("시제", \.tense, 1),
         ("문장 리듬", \.sentenceRhythm, 2), ("묘사 밀도", \.descriptionDensity, 2),
         ("대사 비율", \.dialogueRatio, 1), ("대사 방식", \.dialogueStyle, 1),
         ("내면 독백", \.innerMonologue, 1), ("전개 속도", \.pacing, 1),
         ("장면 전환", \.sceneTransition, 1), ("어휘", \.vocabulary, 1)]
    }
}
