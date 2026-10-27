import CanonAPI
import CanonCore
import CanonStore
import Foundation

public typealias BranchFamily = Components.Schemas.BranchFamily
public typealias BranchMember = Components.Schemas.BranchMember
public typealias BranchDiff = Components.Schemas.BranchDiff
public typealias BranchIn = Components.Schemas.BranchIn

/// 갈래 화면 문구. 웹 `branches.js` 와 같은 규칙이라 함께 고친다.
public enum BranchText {
    /// 갈래 이름. 이름 없는 갈래는 제목이 본편과 같아 폴더 이름으로 부른다 (웹 `branchName`).
    public static func name(_ m: BranchMember) -> String {
        if let label = m.info.label, !label.isEmpty { return label }
        let named = (m.info.parent ?? "").isEmpty ? m.title : m.name
        return named.isEmpty ? m.name : named
    }

    static func isBranch(_ m: BranchMember) -> Bool { !(m.info.parent ?? "").isEmpty }
    static func fromEp(_ m: BranchMember) -> Int { m.info.fromEp ?? 0 }

    /// 함께 쓰는 앞 화: '1~4화' · '1화'. 1화부터 갈라졌으면 빈 값.
    public static func shared(_ fromEp: Int) -> String {
        fromEp > 1 ? (fromEp > 2 ? "1~\(fromEp - 1)화" : "1화") : ""
    }

    /// 집안에서 지금 작품.
    public static func me(_ fam: BranchFamily?, _ project: String) -> BranchMember? {
        fam?.members?.first { $0.name == project }
    }

    /// 갈래가 둘 이상인 집안 (갈래가 없는 작품은 nil).
    public static func members(_ fam: BranchFamily?) -> [BranchMember] {
        let all = fam?.members ?? []
        return all.count < 2 ? [] : all
    }

    /// 사이드바 작품 칸의 갈래 줄: '갈래 · B안 (5화부터)' (웹 `branchSideTag`). 본편이면 nil.
    public static func sideTag(_ fam: BranchFamily?, _ project: String) -> String? {
        guard let me = me(fam, project), isBranch(me) else { return nil }
        return "갈래 · \((me.info.label ?? "").ifEmpty(project)) (\(fromEp(me))화부터)"
    }

    /// 집안의 다른 작품으로 가는 고리: '본편' · '5화부터'.
    public struct Link: Equatable, Sendable {
        public let name: String
        public let label: String
        public let detail: String
    }

    static func link(_ m: BranchMember) -> Link {
        let from = fromEp(m)
        return Link(name: m.name, label: name(m), detail: from > 0 ? "\(from)화부터" : "본편")
    }

    /// 작품 머리 띠 (웹 `branchStrip`).
    public struct Strip: Equatable, Sendable {
        /// 본편이면 true. 본편 띠는 작품 홈에서만 보인다.
        public let main: Bool
        public let title: String
        public let line: String
        /// 갈라져 나온 작품 (갈래일 때만).
        public let parent: String?
        /// 본편 (갈래이고 본편이 갈라져 나온 작품과 다를 때만).
        public let mainName: String?
        /// 집안의 다른 작품. 본편 띠는 늘, 갈래 띠는 둘 이상일 때만.
        public let others: [Link]
        public let warnings: [String]
    }

    /// home: 작품 홈을 보는 중. 본편 띠는 작품 홈에서만 보인다.
    public static func strip(_ fam: BranchFamily?, _ project: String, home: Bool) -> Strip? {
        let all = members(fam)
        guard let me = all.first(where: { $0.name == project }) else { return nil }
        let others = all.filter { $0.name != project }
        if !isBranch(me) {
            guard home else { return nil }
            return Strip(main: true, title: "본편", line: "갈래 \(others.count)개", parent: nil, mainName: nil,
                         others: others.map(link), warnings: [])
        }
        let from = fromEp(me)
        let common = shared(from)
        let parent = all.first { $0.name == (me.parentName ?? "") && !(me.parentName ?? "").isEmpty }
        let main = all.first { $0.name == (fam?.main ?? "") }
        var warnings: [String] = []
        if me.sharedEdited == true, !common.isEmpty {
            warnings.append("갈라진 뒤 이 갈래에서 \(common)를 고쳤어요. 다른 갈래에는 들어가지 않아요.")
        }
        if me.parentEdited == true, !common.isEmpty, let parent {
            warnings.append("갈라진 뒤 '\(name(parent))'에서 \(common)를 고쳤어요. 이 갈래에는 들어가지 않아요.")
        }
        var line = "\(from)화부터 "
        if let parent {
            let p = name(parent)
            line += "'\(p)'\(KoreanText.josa(p, "과", "와")) 달라요"
        } else {
            line += "갈라졌어요"
        }
        if !common.isEmpty { line += " (\(common)는 함께 써요)" }
        return Strip(main: false, title: "갈래 · \((me.info.label ?? "").ifEmpty(project))", line: line,
                     parent: parent?.name, mainName: main.flatMap { $0.name == parent?.name ? nil : $0.name },
                     others: others.count > 1 ? others.map(link) : [], warnings: warnings)
    }

    /// 작품 홈 갈래 카드의 한 줄 (웹 `branchHomeCard`). 자리는 화 축 위 0~1 비율이다.
    public struct HomeRow: Equatable, Sendable {
        public let name: String
        public let label: String
        public let detail: String
        public let me: Bool
        public let branch: Bool
        public let depth: Int
        /// 갈라지기 전에 함께 쓰는 화의 폭 (0 이면 없음)
        public let shared: Double
        /// 따로 쓰는 화가 시작하는 자리
        public let start: Double
        /// 반영한 화의 끝 자리 (반영한 화가 없으면 nil)
        public let done: Double?
        public let accessibility: String
    }

    public static func homeRows(_ fam: BranchFamily?, _ project: String) -> [HomeRow] {
        let all = members(fam)
        let total = Double(max(1, all.map { max($0.episodes ?? 0, $0.planned ?? 0) }.max() ?? 1))
        let at = { (e: Int) in Double(e - 1) / total }
        return all.map { m in
            let start = isBranch(m) ? fromEp(m) : 1
            let fin = m.finalized ?? 0
            let label = name(m)
            let head = start > 1 ? "1~\(start - 1)화는 함께 쓰고 " : ""
            return HomeRow(
                name: m.name, label: label,
                detail: "\(isBranch(m) ? "\(fromEp(m))화부터" : "본편") · \(fin) / \(m.episodes ?? 0)화 반영",
                me: m.name == project, branch: isBranch(m), depth: m.depth ?? 0,
                shared: start > 1 ? at(start) : 0, start: at(start), done: fin >= start ? at(fin + 1) : nil,
                accessibility: "\(label): \(head)\(start)화부터 따로, \(fin)화까지 반영")
        }
    }

    public static let homeNote = "진한 칸은 반영한 화, 점선은 갈라지기 전에 함께 쓰는 화예요. 본편으로 올리거나 끊어도 작품 내용과 폴더 이름은 그대로예요."

    // MARK: 본편으로 · 끊기

    public static func promoteQuestion(_ m: BranchMember) -> String {
        let nm = name(m)
        return "'\(nm)'\(KoreanText.josa(nm, "을", "를")) 본편으로 올릴까요? 갈래 정보만 바뀌고 작품 내용과 폴더 이름은 그대로예요."
    }

    public static func promoted(_ m: BranchMember) -> String {
        let nm = name(m)
        return "'\(nm)'\(KoreanText.josa(nm, "이", "가")) 본편이 됐어요"
    }

    /// 끊을 때 묻는 말. 이 갈래에서 갈라진 갈래는 이 갈래의 부모에 다시 잇는다 (웹 `branchDetach`).
    public static func detachQuestion(_ fam: BranchFamily?, _ m: BranchMember) -> String {
        let all = fam?.members ?? []
        let kids = all.filter { ($0.parentName ?? "") == m.name }.map(name)
        let up = all.first { $0.name == (m.parentName ?? "") && !(m.parentName ?? "").isEmpty }
        var moved = ""
        if let last = kids.last, let up {
            moved = " 이 갈래에서 갈라진 \(kids.map { "'\($0)'" }.joined(separator: ", "))\(KoreanText.josa(last, "은", "는")) '\(name(up))'에 다시 이어요."
        }
        return "'\(name(m))' 갈래를 끊을까요? 따로 선 작품이 되고 작품 내용은 그대로예요.\(moved)"
    }

    public static func detached(_ m: BranchMember) -> String { "'\(name(m))' 갈래를 끊었어요" }

    // MARK: 갈래 만들기

    /// 마지막으로 반영한 화. 갈래는 1~(이 화+1)화부터 만들 수 있다 (웹 `lastFinal`, 서버 `branches.check_fork`).
    public static func lastFinal(_ p: Project) -> Int {
        (p.episodes ?? []).filter { $0.status == .finalized }.map(\.plot.number).max().map { max(0, $0) } ?? 0
    }

    /// 제목으로 폴더 이름 만들기: 폴더에 못 쓰는 글자를 빼고 빈칸은 - 로 (웹 `home.js` `folderOf`, 서버 `web.NAME_RE`).
    public static func folderOf(_ t: String) -> String {
        var s = t.trimmingCharacters(in: .whitespacesAndNewlines)
        s.removeAll { "/\\:*?\"<>|".contains($0) }
        while s.hasPrefix(".") { s.removeFirst() }
        s = s.replacing(/\s+/, with: "-")
        let units = Array(s.utf16.prefix(64))  // JS slice 는 UTF-16 단위로 자른다
        return String(decoding: units, as: UTF16.self)
    }

    /// 폴더 이름에 못 쓰는 글자가 있거나 . 으로 시작한다 (웹 `FOLDER_BAD`).
    public static func folderBad(_ s: String) -> Bool {
        s.hasPrefix(".") || s.contains { "/\\:*?\"<>|".contains($0) }
    }

    /// 갈래 이름에서 폴더 이름 기본값: '<지금 폴더>-<갈래 이름>' (웹 `branchFolder`).
    public static func folder(label: String, project: String) -> String {
        folderOf("\(project)-\(folderOf(label).ifEmpty("갈래"))")
    }

    /// 갈래 만들기 칸 설명.
    public static func formDesc(_ n: Int) -> String {
        "이 작품을 복사해 다른 전개를 써 봐요. \(n > 1 ? "\(shared(n))는 그대로 복사하고, " : "")\(n)화부터는 갈래에서만 바뀌어요. 지금 작품은 그대로예요."
    }

    /// 갈래에서 되돌리는 화 · 비우는 화 안내. 알릴 것이 없으면 nil.
    public static func formNote(_ p: Project, from n: Int, keep: Bool) -> String? {
        let eps = (p.episodes ?? []).sorted { $0.plot.number < $1.plot.number }
        let undo = eps.filter { $0.status == .finalized && $0.plot.number >= n }.map(\.plot.number)
        let texts = eps.filter { $0.plot.number >= n && !($0.text ?? "").isEmpty }.map(\.plot.number)
        var parts: [String] = []
        if !undo.isEmpty {
            parts.append("\(rangeText(undo))화의 상태 반영을 취소해 \(n - 1 > 0 ? "\(n - 1)화 반영 직후" : "1화 시작 전") 상태로 돌아가요.")
        }
        if !texts.isEmpty, !keep { parts.append("\(rangeText(texts))화 본문은 비워요.") }
        return parts.isEmpty ? nil : "갈래에서는 " + parts.joined(separator: " ")
    }

    public static func created(label: String, to: String) -> String {
        "'\(label.trimmingCharacters(in: .whitespacesAndNewlines).ifEmpty(to))' 갈래를 만들었어요. 지금은 갈래 작품을 보고 있어요"
    }

    // MARK: 갈래 비교

    /// 견줄 작품: 고른 작품이 집안에 있으면 그것, 아니면 갈라져 나온 작품, 본편이면 첫 갈래 (웹 `branchCompareLoad`).
    public static func pick(_ fam: BranchFamily?, _ project: String, other: String?) -> String? {
        let rest = members(fam).filter { $0.name != project }
        if let other, rest.contains(where: { $0.name == other }) { return other }
        let parent = me(fam, project)?.parentName ?? ""
        return (rest.first { $0.name == parent && !parent.isEmpty } ?? rest.first)?.name
    }

    /// 견줄 작품 고르기 칸의 이름: 'B안 (5화부터)' · '등대 (본편)'.
    public static func option(_ m: BranchMember) -> String {
        "\(name(m)) (\(isBranch(m) ? "\(fromEp(m))화부터" : "본편"))"
    }

    public static let emptyDesc = "같은 작품을 복사해 n화부터 다른 전개를 쓰는 사본을 갈래라고 해요."

    public static func empty(last: Int) -> String {
        "아직 갈래가 없어요. " + (last > 0 ? "위의 '갈래 만들기'나 상태 승인 화면에서 만들 수 있어요." : "1화를 반영한 뒤에 만들 수 있어요.")
    }

    /// 비교 화면 머리말: ''등대'와 'B안'은 5화부터 달라요. 1~4화는 함께 써요.'
    public static func headline(_ d: BranchDiff, a: String, b: String) -> String {
        let s = shared(d.fromEp)
        return "'\(a)'\(KoreanText.josa(a, "과", "와")) '\(b)'\(KoreanText.josa(b, "은", "는")) \(d.fromEp)화부터 달라요.\(s.isEmpty ? "" : " \(s)는 함께 써요.")"
    }

    /// 화별 줄거리 표의 한쪽 칸.
    public struct Side: Equatable, Sendable {
        public let title: String
        public let status: EpisodeStatus?
        public let summary: String
    }

    public struct EpisodeRow: Equatable, Sendable {
        public let number: Int
        public let a: Side?
        public let b: Side?
        /// 아래에 본문과 상태를 보이는 화
        public let current: Bool
    }

    static func side(_ s: Components.Schemas.BranchSide?) -> Side? {
        guard let s else { return nil }
        return Side(title: (s.title ?? "").ifEmpty("제목 없음"), status: EpisodeStatus(rawValue: s.status ?? ""), summary: s.summary ?? "")
    }

    /// 화별 줄거리 표. 양쪽 모두 플롯 초안인 화는 줄로 늘어놓지 않고 `idle` 로 뺀다 (장편은 수백 화).
    public static func episodeRows(_ d: BranchDiff) -> (rows: [EpisodeRow], idle: [Int]) {
        var rows: [EpisodeRow] = []
        var idle: [Int] = []
        for e in d.episodes ?? [] {
            let started = [e.a, e.b].contains { s in s.map { ($0.status ?? "") != "draft" } ?? false } || e.number == d.episode
            if started {
                rows.append(EpisodeRow(number: e.number, a: side(e.a), b: side(e.b), current: e.number == d.episode))
            } else {
                idle.append(e.number)
            }
        }
        return (rows, idle)
    }

    /// 표 아래 글.
    public static func episodeNote(idle: [Int]) -> String {
        "\(idle.isEmpty ? "" : "\(rangeText(idle))화는 양쪽 모두 플롯 초안이라 빼고 보여요. ")화를 누르면 아래에 그 화 본문과 상태가 나와요."
    }

    /// 상태를 견줄 수 없을 때 안내. 양쪽 모두 반영했으면 nil.
    public static func notReady(_ d: BranchDiff, a: String, b: String) -> String? {
        let names = [d.readyA == true ? nil : a, d.readyB == true ? nil : b].compactMap { $0 }
        guard !names.isEmpty else { return nil }
        return "\(names.map { "'\($0)'" }.joined(separator: ", "))에서 \(d.episode)화를 아직 반영하지 않아 상태는 견줄 수 없어요."
    }

    public static func sameState(_ n: Int) -> String { "\(n)화 반영 직후 상태가 같아요." }

    /// 상태 차이 한 줄: 구분 · 항목 · 양쪽 값 (빈 값은 '없음').
    public struct DiffRow: Equatable, Sendable {
        public let kind: String
        public let item: String
        public let a: String?
        public let b: String?
    }

    static let kinds: [String: String] = ["character": "인물", "tie": "관계", "fact": "사실", "foreshadow": "복선", "time": "시간", "setting": "설정"]

    public static func diffRows(_ d: BranchDiff) -> [DiffRow] {
        (d.rows ?? []).map { r in
            DiffRow(kind: kinds[r.kind.rawValue] ?? r.kind.rawValue,
                    item: [r.who ?? "", r.field ?? ""].filter { !$0.isEmpty }.joined(separator: " · "),
                    a: (r.a ?? "").isEmpty ? nil : r.a, b: (r.b ?? "").isEmpty ? nil : r.b)
        }
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
}

extension String {
    func ifEmpty(_ other: String) -> String { isEmpty ? other : self }
}
