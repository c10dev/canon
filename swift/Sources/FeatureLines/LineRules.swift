import CanonAPI
import CanonCore
import CanonStore

public typealias Storyline = Components.Schemas.Storyline
public typealias StorylineKind = Components.Schemas.Storyline.KindPayload
public typealias StorylineProposal = Components.Schemas.StorylineProposal

/// 이야기 줄기 규칙. 웹 `lines.js` 와 서버 `canon/storylines.py` 와 같은 규칙이라 함께 고친다 (README '웹과 같은 규칙').
/// 플롯 편집기의 줄기 칸(`LineField`)과 화 카드 표시(`LineBadges`)도 이 규칙을 쓴다.
public enum LineRules {
    /// 줄기 종류 (웹 `LINE_KINDS`, 서버 `storylines.KINDS`).
    public static let kinds: [StorylineKind] = [.서브플롯, .과거회상, .외전, .인물이야기]

    /// 종류 칸의 도움말 (웹 `LINE_KIND_HINT`).
    public static func hint(_ kind: StorylineKind) -> String {
        switch kind {
        case .서브플롯: "메인과 같은 시간에 다른 인물이나 다른 곳에서 진행되는 이야기"
        case .과거회상: "인물의 과거를 보여 주는 화나 장면"
        case .외전: "본편 밖의 시간이나 인물을 다루는 이야기"
        case .인물이야기: "조연 한 명을 깊게 다루는 이야기"
        }
    }

    /// 줄기 색: 흰 배경에서 대비 4.5 이상인 색만 (웹 `LINE_COLORS`).
    public static let colors = ["#B4570A", "#7A3FB0", "#1C6E45", "#B42318", "#0E6F7C", "#6E5A00", "#A3367A", "#3E5C14"]

    public static func lines(_ p: Project) -> [Storyline] { p.storylines ?? [] }

    public static func line(_ p: Project, _ id: String) -> Storyline? { lines(p).first { $0.id == id } }

    /// 줄기 색. 줄기 순서로 정한다 (웹 `lineColor`). 없는 줄기는 첫 색.
    public static func color(_ p: Project, _ id: String) -> String {
        let i = lines(p).firstIndex { $0.id == id } ?? 0
        return colors[i % colors.count]
    }

    public static func kind(_ s: Storyline) -> StorylineKind { s.kind ?? .서브플롯 }

    /// 이름이 비면 대신 보일 말.
    public static func title(_ s: Storyline, empty: String = "이름 없음") -> String {
        let t = s.title ?? ""
        return t.isEmpty ? empty : t
    }

    /// 새 줄기 id: sl-01, sl-02 … 비어 있는 다음 번호 (웹 `newLineId`, 서버 `storylines.new_id`).
    public static func newID(_ p: Project) -> String {
        let have = Set(lines(p).map(\.id))
        var n = lines(p).count + 1
        while have.contains(id(n)) { n += 1 }
        return id(n)
    }

    private static func id(_ n: Int) -> String { n < 10 ? "sl-0\(n)" : "sl-\(n)" }

    /// 빈 줄기 (웹 `lineNew`).
    public static func blank(_ p: Project) -> Storyline {
        Storyline(id: newID(p), kind: .서브플롯, title: "", focus: [], when: "", goal: "", branchEp: 0, joinEp: 0, rejoin: "", summary: "")
    }

    public enum Role: String, Sendable {
        /// 그 화가 이 줄기를 주로 따라간다
        case main
        /// 메인 화 안에 이 줄기 장면이 끼어든다
        case thread
    }

    /// 이 줄기에 붙은 화, 화 번호 순 (웹 `lineEpisodes`, 서버 `storylines.episodes_of`).
    public static func episodes(_ p: Project, _ id: String) -> [(n: Int, role: Role)] {
        (p.episodes ?? []).sorted { $0.plot.number < $1.plot.number }.compactMap { e in
            if e.plot.storyline == id { return (e.plot.number, .main) }
            if (e.plot.threads ?? []).contains(id) { return (e.plot.number, .thread) }
            return nil
        }
    }

    /// 줄기가 걸친 화 범위. 갈라지는 화 · 합류하는 화가 비면 붙은 화로 정한다. 아무것도 없으면 (0, 0) (웹 `lineSpan`, 서버 `storylines.span`).
    public static func span(_ p: Project, _ s: Storyline) -> (lo: Int, hi: Int) {
        let eps = episodes(p, s.id).map(\.n)
        let lo = ([s.branchEp ?? 0] + eps).filter { $0 != 0 }
        let hi = ([s.joinEp ?? 0] + eps).filter { $0 != 0 }
        guard let a = lo.min(), let b = hi.max() else { return (0, 0) }
        return (a, b)
    }

    /// 메인과 다른 시점(과거 회상, 앞뒤 시간의 외전)을 따라가는 줄기 (웹 `linePast`, 서버 `storylines.past`).
    public static func isPast(_ s: Storyline) -> Bool {
        !(s.when ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || s.kind == .과거회상
    }

    /// 작품 총 화수: 목표 화수와 플롯이 있는 마지막 화 중 큰 쪽, 적어도 1 (웹 `lineMap` 의 `total`).
    public static func total(_ p: Project) -> Int {
        max(p.meta?.targetEpisodes ?? 0, (p.episodes ?? []).map(\.plot.number).max() ?? 0, 1)
    }

    // MARK: 화 붙이기

    /// 화를 줄기에 붙인다. main 은 그 화가 줄기를 따라가고, thread 는 장면만 끼어든다. id 가 비면 메인으로 되돌린다
    /// (웹 `tagEp`, 서버 `storylines.tag`).
    public static func tag(_ plot: inout Components.Schemas.EpisodePlot, _ id: String, _ role: Role) {
        var threads = plot.threads ?? []
        if role == .main {
            threads.removeAll { $0 == id }
            plot.storyline = id
        } else if !id.isEmpty && !threads.contains(id) && plot.storyline != id {
            threads.append(id)
        }
        plot.threads = threads
    }

    /// 그 화를 이 줄기에서 뺀다 (웹 `lineUntag`).
    public static func untag(_ plot: inout Components.Schemas.EpisodePlot, _ id: String) {
        if plot.storyline == id { plot.storyline = "" }
        plot.threads = (plot.threads ?? []).filter { $0 != id }
    }

    /// 플롯 편집기: 이 화가 따라가는 줄기를 바꾼다. 같은 줄기의 장면 표시는 지운다 (웹 `lineField` 의 바꾸기).
    public static func setMain(_ plot: inout Components.Schemas.EpisodePlot, _ id: String) {
        plot.storyline = id
        plot.threads = (plot.threads ?? []).filter { $0 != id }
    }

    /// 플롯 편집기: 장면으로 끼어드는 줄기를 켜고 끈다 (웹 `data-line-thread`).
    public static func setThread(_ plot: inout Components.Schemas.EpisodePlot, _ id: String, _ on: Bool) {
        var threads = plot.threads ?? []
        if on {
            if !threads.contains(id) { threads.append(id) }
        } else {
            threads.removeAll { $0 == id }
        }
        plot.threads = threads
    }

    /// '7, 8' 같은 글에서 화 번호를 읽는다. 겹침과 0 이하를 빼고 오름차순 (웹 `parseEps`).
    public static func parseEpisodes(_ text: String) -> [Int] {
        let parts = text.split { $0 == "," || $0.isWhitespace }
        return Array(Set(parts.compactMap { leadingInt(String($0)) }.filter { $0 > 0 })).sorted()
    }

    /// JS `parseInt` 처럼 앞쪽 숫자만 읽는다 ('7화' → 7).
    private static func leadingInt(_ s: String) -> Int? {
        var t = Substring(s)
        var sign = 1
        if t.first == "-" || t.first == "+" { sign = t.first == "-" ? -1 : 1; t = t.dropFirst() }
        let digits = t.prefix { $0.isASCII && $0.isNumber }
        return Int(digits).map { $0 * sign }
    }

    // MARK: 문구

    /// 줄기 목록 칸의 범위: 정해 둔 갈라짐 · 합류 화가 있으면 그것, 없으면 붙은 화의 범위 (웹 `lineList`).
    public static func rangeLabel(_ p: Project, _ s: Storyline) -> String {
        let marks = [(s.branchEp ?? 0) > 0 ? "갈라짐 \(s.branchEp!)화" : "", (s.joinEp ?? 0) > 0 ? "합류 \(s.joinEp!)화" : ""]
            .filter { !$0.isEmpty }.joined(separator: " · ")
        if !marks.isEmpty { return marks }
        let (lo, hi) = span(p, s)
        return episodes(p, s.id).isEmpty ? "" : "\(lo)~\(hi)화"
    }

    /// 줄기 목록 칸의 아랫줄: 중심 인물, 시점, 붙은 화 수 (웹 `lineList`).
    public static func listDetail(_ p: Project, _ s: Storyline) -> String {
        let names = (s.focus ?? []).map { name(p, $0) }.joined(separator: ", ")
        let n = episodes(p, s.id).count
        let when = s.when ?? ""
        return "\(names.isEmpty ? "중심 인물 없음" : names)\(when.isEmpty ? "" : " · " + when) · \(n > 0 ? "붙은 화 \(n)개" : "붙은 화 없음")"
    }

    /// 인물 이름. 이름이 비거나 없는 인물이면 id (웹 `charName`).
    public static func name(_ p: Project, _ id: String) -> String {
        guard let c = (p.characters ?? []).first(where: { $0.id == id }), !c.name.isEmpty else { return id }
        return c.name
    }

    /// 갈라지는 화 · 합류하는 화가 맞지 않거나 범위 밖에 붙은 화. 저장은 막지 않고 고칠 곳을 알린다 (웹 `lineRangeNote`).
    public static func rangeNotes(_ p: Project, _ s: Storyline) -> [String] {
        let total = p.meta?.targetEpisodes ?? 0
        let branch = s.branchEp ?? 0
        let join = s.joinEp ?? 0
        var out: [String] = []
        if branch != 0 && join != 0 && branch > join { out.append("갈라지는 화(\(branch)화)가 합류하는 화(\(join)화)보다 뒤예요") }
        let late = [("갈라지는 화", branch), ("합류하는 화", join)].filter { $0.1 > total }.map(\.0)
        if !late.isEmpty { out.append("\(late.joined(separator: " · "))가 총 화수(\(total)화)보다 뒤예요") }
        let outside = episodes(p, s.id).map(\.n).filter { (branch != 0 && $0 < branch) || (join != 0 && $0 > join) }
        if !outside.isEmpty { out.append("갈라지는 화 앞이나 합류하는 화 뒤에 붙은 화가 있어요: \(rangeText(outside))화") }
        return out
    }

    /// [1,2,3,5] → '1~3, 5' (웹 `rangeText`).
    public static func rangeText(_ nums: [Int]) -> String {
        var out: [String] = []
        var i = 0
        while i < nums.count {
            var j = i
            while j + 1 < nums.count && nums[j + 1] == nums[j] + 1 { j += 1 }
            out.append(i == j ? "\(nums[i])" : "\(nums[i])~\(nums[j])")
            i = j + 1
        }
        return out.joined(separator: ", ")
    }

    /// 줄기 편집 칸 아래 안내 (웹 `lineEditor` 의 마지막 줄).
    public static func timeNote(_ s: Storyline) -> String {
        isPast(s)
            ? "다른 시점의 줄기예요. 이 줄기 화를 쓸 때 AI에게 그 시점에 몰랐던 것을 알지 않도록 지시하고, 상태 반영 때 인물의 지금 감정과 위치는 바꾸지 않아요."
            : "메인과 같은 시간의 줄기예요. 이 줄기 화를 쓸 때 줄기 정보와 앞 화 요약이 함께 들어가요."
    }

    /// 지우기 전에 묻는 말 (웹 `lineDelete`).
    public static func deleteQuestion(_ s: Storyline) -> String {
        "'\(title(s))' 줄기를 지울까요? 붙은 화는 메인으로 돌아가고, 플롯과 본문은 그대로예요."
    }

    /// 플롯 편집기 줄기 칸의 도움말. 본문이 있는 화도 줄기 표시는 바꿀 수 있다 (웹 `lineField`).
    public static func fieldHint(written: Bool) -> String {
        written ? "본문이 있는 화도 줄기 표시는 바꿀 수 있어요. 본문은 그대로예요" : "이 화가 주로 따라가는 줄기"
    }

    /// 플롯 편집기 줄기 고르기의 항목: ('' 메인 줄기) 와 줄기마다 '종류 · 이름' (웹 `lineField` 의 `opts`).
    public static func fieldOptions(_ p: Project) -> [(id: String, label: String)] {
        [("", "메인 줄기")] + lines(p).map { ($0.id, "\(kind($0).rawValue) · \(title($0, empty: $0.id))") }
    }

    /// 장면으로 끼어들 수 있는 줄기: 이 화가 따라가는 줄기를 뺀 전부 (웹 `lineField` 의 `scenes`).
    public static func sceneOptions(_ p: Project, _ plot: Components.Schemas.EpisodePlot) -> [Storyline] {
        lines(p).filter { $0.id != (plot.storyline ?? "") }
    }

    /// 화 카드의 줄기 표시 하나 (웹 `lineBadge`).
    public struct Badge: Equatable, Sendable {
        public let id: String
        public let text: String
        public let color: String
        /// 메인 화 안에 끼어드는 장면
        public let scene: Bool
    }

    /// 화 카드의 줄기 표시: 따라가는 줄기, 그다음 끼어드는 장면. 없는 줄기는 뺀다 (웹 `lineBadge`).
    public static func badges(_ p: Project, _ plot: Components.Schemas.EpisodePlot) -> [Badge] {
        let main = plot.storyline ?? ""
        let ids = ([main] + (plot.threads ?? [])).filter { !$0.isEmpty }
        return ids.compactMap { id in
            guard let s = line(p, id) else { return nil }
            let scene = id != main
            let name = (s.title ?? "").isEmpty ? kind(s).rawValue : s.title!
            return Badge(id: id, text: (scene ? "장면 · " : "") + name, color: color(p, id), scene: scene)
        }
    }
}
