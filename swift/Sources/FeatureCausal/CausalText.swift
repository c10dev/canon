import CanonAPI
import CanonCore
import CanonStore
import Foundation

public typealias StoryElement = Components.Schemas.StoryElement
public typealias ElementImpact = Components.Schemas.ElementImpact
public typealias ImpactReport = Components.Schemas.ImpactReport
public typealias ElementLink = Components.Schemas.ElementLink
public typealias EpisodePlot = Components.Schemas.EpisodePlot

/// 인과율 화면의 표시 규칙. 웹 `causal.js` 와 같은 문구 · 규칙이라 함께 고친다.
public enum CausalText {
    /// 요소 종류 (웹 `EL_KINDS`, 서버 `elements.KINDS`).
    public static let kinds: [StoryElement.KindPayload] = [.세계규칙, .장소, .물건, .세력, .인물특징, .과거사건, .예정사건, .기타]

    /// 종류별 설명 칸 예시 (웹 `EL_KIND_HINT`).
    public static func hint(_ kind: StoryElement.KindPayload) -> String {
        switch kind {
        case .세계규칙: "마법은 해가 진 뒤에만 쓸 수 있다"
        case .장소: "폐쇄된 등대의 지하 창고"
        case .물건: "녹슨 등대 열쇠"
        case .세력: "항구를 쥔 선주 조합"
        case .인물특징: "주인공은 왼손잡이고 피를 보면 손이 떨린다"
        case .과거사건: "10년 전 겨울, 등대지기가 실종됐다"
        case .예정사건: "12화에 마을에 태풍이 온다"
        case .기타: ""
        }
    }

    /// 본문을 쓸 때 AI에 넣기 (웹 `causalEditor` 의 `ctx`).
    public static let contexts: [(StoryElement.ContextPayload, String)] = [(.auto, "관련 있을 때"), (.always, "항상"), (.off, "넣지 않음")]

    static func status(_ e: Episode) -> EpisodeStatus {
        EpisodeStatus(rawValue: e.status?.rawValue ?? "draft") ?? .draft
    }

    // MARK: 요소

    /// 새 요소 id 'el-NN' (웹 `newElementId`, 서버 `elements.new_id`).
    public static func newID(_ els: [StoryElement]) -> String {
        let have = Set(els.map(\.id))
        var n = els.count + 1
        while have.contains(String(format: "el-%02d", n)) { n += 1 }
        return String(format: "el-%02d", n)
    }

    /// 빈 새 요소 (웹 `causalNew`).
    public static func blank(id: String, kind: StoryElement.KindPayload) -> StoryElement {
        StoryElement(id: id, kind: kind, name: "", aliases: [], description: "", characters: [], sinceEp: 0, episodes: [], revealEp: 0,
                     context: .auto, createdAt: "", addedAfter: 0, impact: nil)
    }

    /// 본문이 있는 마지막 화 (웹 `lastWritten`, 서버 `elements.last_written`).
    public static func lastWritten(_ p: Project) -> Int {
        (p.episodes ?? []).filter { !($0.text ?? "").isEmpty }.map(\.plot.number).max() ?? 0
    }

    /// '7, 12' 같은 글을 화 번호로 (웹 `data-el-eps` 의 change). 0 이하와 겹친 번호는 뺀다.
    public static func parseEpisodes(_ text: String) -> [Int] {
        let nums = text.split(whereSeparator: { $0 == "," || $0.isWhitespace }).compactMap { Int(leadingDigits($0)) }.filter { $0 > 0 }
        return Array(Set(nums)).sorted()
    }

    /// JS `parseInt` 처럼 앞쪽 숫자만 읽는다 ('7화' → 7).
    private static func leadingDigits(_ s: Substring) -> String {
        var out = s.first == "-" || s.first == "+" ? String(s.first!) : ""
        for c in s.dropFirst(out.count) {
            guard c.isASCII, c.isNumber else { break }
            out.append(c)
        }
        return out
    }

    // MARK: 분석이 지났나

    /// 영향 분석에 쓰인 요소 내용 (웹 `elBasis`, 서버 `elements.basis`). Python `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 과 같은 글.
    public static func basis(_ el: StoryElement) -> String {
        let parts = [
            str(el.kind?.rawValue ?? "기타"), str(el.name ?? ""), list((el.aliases ?? []).map(str)), str(el.description ?? ""),
            list((el.characters ?? []).map(str)), String(el.sinceEp ?? 0), list((el.episodes ?? []).map(String.init)), String(el.revealEp ?? 0),
        ]
        return list(parts)
    }

    private static func list(_ items: [String]) -> String { "[" + items.joined(separator: ",") + "]" }

    private static func str(_ s: String) -> String {
        var out = "\""
        for u in s.unicodeScalars {
            switch u {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            case let c where c.value < 0x20: out += String(format: "\\u%04x", c.value)
            default: out.unicodeScalars.append(u)
            }
        }
        return out + "\""
    }

    /// 분석한 뒤 요소를 고쳤다 (웹 `causalStale`). 기록된 basis 가 없으면 지난 것으로 보지 않는다.
    public static func stale(_ el: StoryElement) -> Bool {
        guard let b = el.impact?.basis, !b.isEmpty else { return false }
        return b != basis(el)
    }

    public static let staleNote = "분석한 뒤 요소를 고쳤어요. 다시 분석하면 지금 내용으로 봐요."

    // MARK: 시점

    /// 목록의 시점 줄 (웹 `timingText`).
    public static func timing(_ el: StoryElement) -> String {
        let since = el.sinceEp ?? 0
        var parts = [since > 0 ? "\(since)화부터" : "처음부터"]
        if let eps = el.episodes, !eps.isEmpty { parts.append("나올 화 \(eps.map(String.init).joined(separator: ", "))") }
        if let r = el.revealEp, r > 0 { parts.append("\(r)화 공개") }
        if let found = el.foundIn, found != ._empty_ { parts.append("\(el.foundEp ?? 0)화 \(found.rawValue)에 처음 나옴") }
        return parts.joined(separator: " · ")
    }

    /// '언제부터' 칸 아래 설명 (웹 `causalEditor`).
    public static func sinceNote(_ el: StoryElement) -> String {
        let since = el.sinceEp ?? 0
        return since <= 0 ? "이미 쓴 화도 이 설정과 맞아야 해서, 영향 분석이 본문까지 검사해요."
            : "\(since)화 전 본문은 이 요소가 없던 때라 모순으로 보지 않아요."
    }

    /// '어느 화부터 생긴다'를 고를 때의 화 (웹 `causalSince`).
    public static func since(start: Bool, _ el: StoryElement, lastWritten: Int) -> Int {
        start ? 0 : max(1, (el.sinceEp ?? 0) > 0 ? el.sinceEp! : lastWritten + 1)
    }

    /// 본문 · 플롯에서 처음 나와 등록된 장소의 안내 (웹 `causalEditor` 의 `found_in`).
    public static func foundNote(_ el: StoryElement) -> String? {
        guard let found = el.foundIn, found != ._empty_ else { return nil }
        let ep = el.foundEp ?? 0
        let body = found == .본문
        return "\(ep)화 \(found.rawValue)에 처음 나와 \(body ? "상태 승인 때" : "화를 확정할 때") 등록한 장소예요. 이름이나 설명을 고쳐도 돼요."
            + (body ? " \(ep)화부터 반영을 취소하면 빠져요 (시점이나 관련 인물을 더했으면 남아요)." : "")
    }

    // MARK: 목록 배지

    public enum Tone: Sendable, Equatable { case plain, warn, done }

    public struct Badge: Equatable, Sendable {
        public let text: String
        public let tone: Tone
    }

    /// 분석이 건드리는 화. 모순 · 플롯 고치기 · 본문 고치기가 같은 화면 한 번만 센다 (웹 `impactEpisodes`).
    public static func impactEpisodes(_ r: ImpactReport) -> Set<Int> {
        var out = Set<Int>()
        for c in r.conflicts ?? [] { if let e = c.episode, e != 0 { out.insert(e) } }
        for e in r.episodes ?? [] where e.number != 0 { out.insert(e.number) }
        for t in r.patches ?? [] where t.episode != 0 { out.insert(t.episode) }
        return out
    }

    /// 목록 줄의 배지 (웹 `impactBadge`). 없으면 nil.
    public static func badge(_ el: StoryElement) -> Badge? {
        guard let imp = el.impact else {
            if let found = el.foundIn, found != ._empty_ { return Badge(text: "\(el.foundEp ?? 0)화 \(found.rawValue)에서", tone: .plain) }
            return (el.addedAfter ?? 0) > 0 ? Badge(text: "분석 전", tone: .warn) : nil
        }
        if stale(el) { return Badge(text: "다시 분석 필요", tone: .warn) }
        if imp.outcome == .applied { return Badge(text: "적용함", tone: .done) }
        if imp.outcome == .dismissed { return Badge(text: "분석 봄", tone: .plain) }
        let r = imp.report
        let n = impactEpisodes(r).count
        if n > 0 { return Badge(text: "영향 \(n)개 화", tone: .warn) }
        return !(r.conflicts ?? []).isEmpty || !(r.newFacts ?? []).isEmpty ? Badge(text: "검토할 것 있음", tone: .warn) : Badge(text: "영향 없음", tone: .done)
    }

    // MARK: 관련 화 지도

    public enum CellKind: String, Sendable, Equatable { case none, bad, plot, done, rel, weak }

    /// 지도 칸 하나 (웹 `causalStrip` 의 `cells`).
    public struct Cell: Equatable, Sendable, Identifiable {
        public let ep: Int
        public let kind: CellKind
        /// 칸 아래 작은 글: 모순 · 고침 · 반영함 · 언급 · 예정 · 인물.
        public let tag: String
        public let since: Bool
        public let reveal: Bool
        public let hasText: Bool
        /// 생기기 전 화 (흐리게).
        public let before: Bool
        /// 플롯이 있는 화.
        public let hasPlot: Bool
        /// 길게 누르거나 고를 때 보이는 설명.
        public let title: String
        public var id: Int { ep }
    }

    /// 지도 칸 수: 목표 화수와 가장 큰 화 번호 중 큰 쪽.
    public static func total(_ p: Project) -> Int {
        max(p.meta?.targetEpisodes ?? 0, (p.episodes ?? []).map(\.plot.number).max() ?? 0)
    }

    /// 반영한 뒤에는 분석 때의 '모순 · 고침'이 지금 일이 아니다. 반영한 화는 따로 표시하고 남은 것만 모순 · 고칠 화로 둔다.
    public static func strip(_ el: StoryElement, links: [ElementLink], project p: Project, names: [String: String]) -> [Cell] {
        let byEp = Dictionary(links.map { ($0.episode, $0) }, uniquingKeysWith: { a, _ in a })
        let imp = el.impact.flatMap { $0.outcome == .dismissed ? nil : $0 }
        let r = imp?.report
        var bad = Set((r?.conflicts ?? []).compactMap { $0.episode }.filter { $0 != 0 })
        var plot = Set((r?.episodes ?? []).map(\.number) + (r?.patches ?? []).map(\.episode))
        var done = Set<Int>()
        if let imp, let r, imp.outcome == .applied {
            for x in imp.applied ?? [] {
                let parts = x.split(separator: ":", maxSplits: 1).map(String.init)
                guard parts.count == 2, let v = Int(parts[1]) else { continue }
                if parts[0] == "ep" { done.insert(v) }
                if parts[0] == "patch", let patches = r.patches, patches.indices.contains(v) { done.insert(patches[v].episode) }
            }
            bad.subtract(done)
            plot.subtract(done)
        }
        let eps = Dictionary((p.episodes ?? []).map { ($0.plot.number, $0) }, uniquingKeysWith: { a, _ in a })
        let since = el.sinceEp ?? 0, reveal = el.revealEp ?? 0
        return (0..<total(p)).map { k in
            let n = k + 1
            let e = eps[n]
            let l = byEp[n]
            let kind: CellKind = bad.contains(n) ? .bad : plot.contains(n) ? .plot : done.contains(n) ? .done
                : l.map { !$0._where.isEmpty || $0.planned ? .rel : .weak } ?? CellKind.none
            let tag = bad.contains(n) ? "모순" : plot.contains(n) ? "고침" : done.contains(n) ? "반영함"
                : l.map { !$0._where.isEmpty ? "언급" : $0.planned ? "예정" : "인물" } ?? ""
            var title = ["\(n)화", e.map { status($0).label } ?? "플롯 없음"]
            if let l, !l.terms.isEmpty { title.append("언급: \(l.terms.joined(separator: ", "))") }
            if let l, !l.characters.isEmpty { title.append("인물: \(l.characters.map { names[$0] ?? $0 }.joined(separator: ", "))") }
            if since == n { title.append("이 화부터 생김") }
            if reveal == n { title.append("독자에게 드러남") }
            return Cell(ep: n, kind: kind, tag: tag, since: since > 0 && n == since, reveal: reveal == n,
                        hasText: !(e?.text ?? "").isEmpty, before: since > n, hasPlot: e != nil, title: title.joined(separator: " · "))
        }
    }

    /// 지도 아래 언급 줄 (웹 `snippets`, 여섯 개까지).
    public static func snippets(_ links: [ElementLink]) -> [(head: String, text: String)] {
        links.filter { !$0.snippet.isEmpty }.prefix(6).map { ("\($0.episode)화 \($0._where.joined(separator: "·"))", $0.snippet) }
    }

    // MARK: 영향 분석

    public static let introSummary = "요소, 특징, 설정, 사건을 언제든 더하세요. 더할 때마다 이미 쓴 화와 정해 둔 플롯 중 어디가 흔들리는지 보여 주고, 고칠 방법을 변경안으로 내요. 적용은 고른 것만 해요."

    /// 분석 전 안내 (웹 `causalImpact` 의 `why`).
    public static func why(lastWritten lw: Int) -> String {
        (lw > 0 ? "\(lw)화까지 쓴 작품이에요. 이 요소가 이미 쓴 화, 확정한 플롯과 부딪치는지 AI가 근거를 인용해 찾고 고칠 방법을 제안해요."
            : "정해 둔 플롯이 이 요소와 맞는지, 어느 화에 심고 드러내면 좋을지 AI가 제안해요.") + " 적용은 고른 것만 해요."
    }

    /// 체크 열쇠 '요소:분석시각:ep:3' (웹 `pickId`). 분석을 다시 하면 열쇠가 바뀌어 처음 체크로 돌아간다.
    public static func pickID(_ el: StoryElement, _ part: String) -> String {
        "\(el.id):\(el.impact?.at ?? ""):\(part)"
    }

    /// 처음 보는 분석의 체크 (웹 `initCausalPicks`): 플롯은 초안 · 없는 화만, 본문 고침은 반영이 끝나지 않은 화만, 사실은 모두.
    public static func defaultPicks(_ el: StoryElement, project p: Project) -> [String: Bool] {
        guard let r = el.impact?.report else { return [:] }
        let eps = Dictionary((p.episodes ?? []).map { ($0.plot.number, $0) }, uniquingKeysWith: { a, _ in a })
        var out: [String: Bool] = [:]
        for e in r.episodes ?? [] { out[pickID(el, "ep:\(e.number)")] = eps[e.number].map { status($0) == .draft } ?? true }
        for (i, t) in (r.patches ?? []).enumerated() { out[pickID(el, "patch:\(i)")] = eps[t.episode].map { status($0) != .finalized } ?? false }
        for i in (r.newFacts ?? []).indices { out[pickID(el, "fact:\(i)")] = true }
        return out
    }

    /// 플롯을 바꿀 수 없는 화: 본문이 생겼다 (웹 `LOCKED_STATUS`).
    public static func locked(_ e: Episode?) -> Bool {
        guard let e else { return false }
        return [.written, .finalized].contains(status(e))
    }

    /// 플롯 고치기 칸의 안내 (웹 `causalImpact` 의 `plots` 의 `note`).
    public static func plotNote(_ e: Episode?, open: Bool) -> (text: String, warn: Bool)? {
        guard let e else { return nil }
        if locked(e) { return ("본문이 생겨서 이제는 바꿀 수 없어요.", false) }
        if status(e) == .confirmed, open { return ("확정한 화예요. 적용하면 초안으로 돌아가 다시 확정해야 해요.", true) }
        return nil
    }

    public static let finalizedPatchNote = "상태 반영까지 끝난 화예요. 본문만 고치고 요약과 인물 상태는 그대로 둬요."
    public static let timingTip = "시점 변경을 권한 곳이 있어요. 위의 '언제부터'를 늦추고 저장한 뒤 다시 분석하면 앞 본문은 모순이 아니게 돼요."

    /// '시점 변경'을 권한 모순이 있다 (웹 `timingTip`).
    public static func suggestsTiming(_ r: ImpactReport) -> Bool {
        (r.conflicts ?? []).contains { $0.fix == .시점변경 }
    }

    /// 고친 화에 남길 처리 칩 색 (웹 `FIX_CLASS`).
    public static func fixTone(_ fix: Components.Schemas.ImpactConflict.FixPayload) -> Tone {
        switch fix {
        case .본문수정, .플롯수정: .warn
        case .설명추가: .done
        case .시점변경, .그대로둠: .plain
        }
    }

    /// 적용한 부분 이름 'ep:3' → '3화 플롯' (웹 `appliedLabel`).
    public static func appliedLabel(_ x: String, _ r: ImpactReport?) -> String {
        let parts = x.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return x }
        let v = parts[1]
        switch parts[0] {
        case "ep": return "\(v)화 플롯"
        case "patch":
            if let i = Int(v), let t = r?.patches, t.indices.contains(i) { return "\(t[i].episode)화 본문 수정" }
            return "본문 수정 \((Int(v) ?? 0) + 1)"
        case "fact": return "사실 \((Int(v) ?? 0) + 1)"
        default: return x
        }
    }

    public static func appliedText(_ imp: ElementImpact) -> String {
        (imp.applied ?? []).map { appliedLabel($0, imp.report) }.joined(separator: ", ")
    }

    /// 고른 부분 (웹 `causalApply` 의 `body`). 막힌 플롯 칸은 빼고 보낸다.
    public static func picked(_ el: StoryElement, picks: [String: Bool], project p: Project) -> Components.Schemas.ImpactApply {
        guard let r = el.impact?.report else { return .init(episodes: [], patches: [], facts: []) }
        let eps = Dictionary((p.episodes ?? []).map { ($0.plot.number, $0) }, uniquingKeysWith: { a, _ in a })
        let on = { (part: String) in picks[pickID(el, part)] == true }
        return .init(episodes: (r.episodes ?? []).map(\.number).filter { on("ep:\($0)") && !locked(eps[$0]) },
                     patches: (r.patches ?? []).indices.filter { on("patch:\($0)") },
                     facts: (r.newFacts ?? []).indices.filter { on("fact:\($0)") })
    }

    public static func isEmpty(_ a: Components.Schemas.ImpactApply) -> Bool {
        (a.episodes ?? []).isEmpty && (a.patches ?? []).isEmpty && (a.facts ?? []).isEmpty
    }

    // MARK: 묻는 말 · 알림

    public static let needNameAndDescription = "이름과 설명을 먼저 적으세요"
    public static let pickSomething = "적용할 부분을 고르세요"

    public static func label(_ el: StoryElement) -> String {
        let n = el.name ?? ""
        return n.isEmpty ? "이름 없음" : n
    }

    /// 지우기 전에 묻는 말 (웹 `causalDelete`).
    public static func deleteQuestion(_ el: StoryElement, dirty: Bool) -> String {
        "'\(label(el))' 요소를 지울까요? 이미 반영한 플롯과 본문은 그대로예요.\(dirty ? " 저장하지 않은 다른 변경도 함께 저장해요." : "") 지운 뒤 이 화면에서 바로 되살릴 수 있어요."
    }

    public static func goneNote(_ el: StoryElement) -> String { "'\(label(el))' 요소를 지웠어요." }
    public static func restored(_ el: StoryElement) -> String { "'\(label(el))' 요소를 되살렸어요" }
    public static func applied(_ imp: ElementImpact) -> String { "적용했어요: \(appliedText(imp))" }

    /// 요소가 없을 때 예시 (웹 `viewCausal` 의 `exName`).
    public static func emptyExample(_ p: Project) -> String {
        let chars = p.characters ?? []
        let name = { (i: Int) in chars.indices.contains(i) && !chars[i].name.isEmpty ? chars[i].name : (["주인공", "조연", "악역"].indices.contains(i) ? ["주인공", "조연", "악역"][i] : "인물") }
        return "예: \"\(name(2))은(는) \(name(0))의 친아버지다\"(과거 사건, 처음부터 사실), \"7화부터 마을에 통금이 생긴다\"(세계 규칙, 7화부터)"
    }

    // MARK: 플롯 비교 (웹 `chat.js` 의 `plotDiff` · `diffField`)

    public struct DiffRow: Equatable, Sendable {
        public let label: String
        /// 글 칸이면 [이전], [새 값]. 목록 칸이면 빠진 것, 더한 것. 사건 순서는 이전 목록 전체와 새 목록 전체.
        public let removed: [String]
        public let added: [String]
        /// 사건 순서처럼 번호 목록으로 보인다.
        public let ordered: Bool
    }

    /// 지금 플롯과 다른 칸. 지금 화가 없으면 빈 플롯과 비교한다. 같으면 빈 목록 (화면은 '지금 플롯과 같아요').
    public static func plotDiff(_ new: EpisodePlot, current: EpisodePlot?, names: [String: String] = [:], lines: [String: String] = [:]) -> [DiffRow] {
        typealias Field = (String, String, (EpisodePlot?) -> PlotValue)
        let fields: [Field] = [
            ("title", "제목", { .text($0?.title ?? "") }), ("opening", "여는 장면", { .text($0?.opening ?? "") }),
            ("summary", "요약", { .text($0?.summary ?? "") }), ("events", "사건 순서", { .list($0?.events ?? []) }),
            ("characters", "등장 인물", { .list($0?.characters ?? []) }), ("emotional_shift", "감정 변화", { .text($0?.emotionalShift ?? "") }),
            ("ending_hook", "엔딩 훅", { .text($0?.endingHook ?? "") }), ("foreshadow_plant", "심을 복선", { .list($0?.foreshadowPlant ?? []) }),
            ("foreshadow_payoff", "회수할 복선", { .list($0?.foreshadowPayoff ?? []) }), ("storyline", "이야기 줄기", { .text($0?.storyline ?? "") }),
            ("threads", "끼어드는 줄기", { .list($0?.threads ?? []) }), ("pov", "시점 인물", { .text($0?.pov ?? "") }),
            ("pov_mode", "서술 방식", { .text($0?.povMode ?? "") }),
        ]
        var out: [DiffRow] = []
        for (key, label, get) in fields {
            let before = get(current), after = get(new)
            guard before != after else { continue }
            switch (before, after) {
            case let (.list(b), .list(a)) where key == "events":
                out.append(DiffRow(label: label, removed: b, added: a, ordered: true))
            case let (.list(b), .list(a)):
                let name = { (x: String) in key == "characters" ? names[x] ?? x : key == "threads" ? lines[x] ?? x : x }
                let gone = b.filter { !a.contains($0) }.map(name), added = a.filter { !b.contains($0) }.map(name)
                if !gone.isEmpty || !added.isEmpty { out.append(DiffRow(label: label, removed: gone, added: added, ordered: false)) }
            case let (.text(b), .text(a)):
                out.append(DiffRow(label: label, removed: b.isEmpty ? [] : [b], added: a.isEmpty ? [] : [a], ordered: false))
            default: break
            }
        }
        return out
    }

    enum PlotValue: Equatable { case text(String), list([String]) }
}
