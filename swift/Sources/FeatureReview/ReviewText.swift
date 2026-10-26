import CanonAPI
import CanonCore
import Foundation

public typealias StateDelta = Components.Schemas.StateDelta
public typealias CharacterState = Components.Schemas.CharacterState
public typealias Project = Components.Schemas.Project
public typealias Episode = Components.Schemas.Episode
public typealias NewPlace = Components.Schemas.NewPlace
public typealias RelationPreview = Components.Schemas.RelationPreview

/// 상태 승인 화면의 표시 규칙. 웹(`app.js` 의 `viewReview` · `setDelta` · `pickedDelta` · `relationLines`,
/// `statwin.js` 의 `swDeltaRows`, `foreshadow.js` 의 `fsClueRows`, `restate.js`)과 같은 규칙이라 함께 고친다.
public enum ReviewText {
    // MARK: 항목 고르기

    /// 항목 체크 키 앞 글자 (웹 `DELTA_PICK`): 인물 상태 c, 사건 e, 비밀 s, 관계 r, 사실 f, 심은 복선 p, 회수 x, 새 인물 n, 새 장소 l, 복선 문장 q.
    public static let pickPrefixes: [Character] = ["c", "e", "s", "r", "f", "p", "x", "n", "l", "q"]

    /// 변경안을 받을 때 고를 항목 (웹 `setDelta`). 설정에도 이번 새 인물에도 없는 인물 상태와 모르는 복선의 회수는 빼 둔다.
    public static func defaultPicks(_ d: StateDelta, project p: Project) -> Set<String> {
        let known = Set((p.characters ?? []).map(\.id) + (d.newCharacters ?? []).map(\.id))
        let foreshadows = Set((p.foreshadows ?? []).map(\.id))
        var out: Set<String> = []
        for (i, u) in (d.characterUpdates ?? []).enumerated() where known.contains(u.characterId) { out.insert("c\(i)") }
        for (i, id) in (d.foreshadowResolved ?? []).enumerated() where foreshadows.contains(id) { out.insert("x\(i)") }
        let all: [(String, Int)] = [("e", d.events?.count ?? 0), ("s", d.secretsAdded?.count ?? 0), ("r", d.relationshipUpdates?.count ?? 0),
                                    ("f", d.newFacts?.count ?? 0), ("p", d.foreshadowPlanted?.count ?? 0), ("n", d.newCharacters?.count ?? 0),
                                    ("l", d.newPlaces?.count ?? 0), ("q", d.foreshadowClues?.count ?? 0)]
        for (prefix, count) in all { for i in 0..<count { out.insert("\(prefix)\(i)") } }
        return out
    }

    /// 체크한 항목만 남긴 변경안 (웹 `pickedDelta`). 반영과 관계 미리 보기에 같이 쓴다. 요약 · 경고는 그대로.
    public static func picked(_ d: StateDelta, _ picks: Set<String>) -> StateDelta {
        func keep<T>(_ prefix: String, _ list: [T]?) -> [T] {
            (list ?? []).enumerated().filter { picks.contains("\(prefix)\($0.offset)") }.map(\.element)
        }
        var out = d
        out.characterUpdates = keep("c", d.characterUpdates)
        out.events = keep("e", d.events)
        out.secretsAdded = keep("s", d.secretsAdded)
        out.relationshipUpdates = keep("r", d.relationshipUpdates)
        out.newFacts = keep("f", d.newFacts)
        out.foreshadowPlanted = keep("p", d.foreshadowPlanted)
        out.foreshadowResolved = keep("x", d.foreshadowResolved)
        out.newCharacters = keep("n", d.newCharacters)
        out.newPlaces = keep("l", d.newPlaces)
        out.foreshadowClues = keep("q", d.foreshadowClues)
        return out
    }

    /// 변경안 항목 수 (웹 `viewReview` 의 `total`).
    public static func total(_ d: StateDelta) -> Int {
        let counts: [Int?] = [d.characterUpdates?.count, d.events?.count, d.secretsAdded?.count, d.relationshipUpdates?.count, d.newFacts?.count,
                              d.foreshadowPlanted?.count, d.foreshadowResolved?.count, d.newCharacters?.count, d.newPlaces?.count, d.foreshadowClues?.count]
        return counts.reduce(0) { $0 + ($1 ?? 0) }
    }

    /// 반영 전에 한 번 물을 까닭 (웹 `applyDelta`). 비면 바로 반영한다. 복선 문장(q)은 세지 않는다.
    public static func applyReasons(_ out: StateDelta, textChanged: Bool) -> [String] {
        let counts: [Int?] = [out.characterUpdates?.count, out.events?.count, out.secretsAdded?.count, out.relationshipUpdates?.count,
                              out.newFacts?.count, out.foreshadowPlanted?.count, out.foreshadowResolved?.count, out.newCharacters?.count,
                              out.newPlaces?.count]
        let count = counts.reduce(0) { $0 + ($1 ?? 0) }
        let warnings = out.warnings?.count ?? 0
        return [count == 0 ? "고른 항목이 0건이에요. 요약만 저장하고" : "",
                warnings > 0 ? "경고 \(warnings)건이 남아 있어요." : "",
                textChanged ? "변경안을 만든 뒤 본문을 고쳤어요." : ""].filter { !$0.isEmpty }
    }

    public static func applyQuestion(_ reasons: [String], ep n: Int) -> String {
        "\(reasons.joined(separator: " ")) \(n)화를 마칠까요? 반영하면 반영 취소로만 돌아갈 수 있어요."
    }

    // MARK: 이름과 줄

    /// 인물 이름. 설정에도 후보에도 없으면 id 그대로 (웹 `charName`).
    public static func name(_ id: String, _ p: Project) -> String {
        let c = (p.characters ?? []).first { $0.id == id } ?? (p.castCandidates ?? []).first { $0.id == id }
        guard let c, !c.name.isEmpty else { return id }
        return c.name
    }

    /// 비밀 내용. 이번 변경안의 새 비밀도 찾는다 (웹 `secretLabel`).
    public static func secret(_ id: String, _ d: StateDelta?, _ p: Project) -> String {
        ((p.secrets ?? []) + (d?.secretsAdded ?? [])).first { $0.id == id }?.content ?? id
    }

    /// 좋은 사건 (웹 `GOOD_EVENTS`). 사건 칩 색을 가린다.
    public static let goodEvents: Set<String> = ["도움", "희생", "약속이행", "칭찬", "진심고백", "사과", "공동경험"]
    /// 사건 강도 (웹 `INTENSITY`).
    public static func intensity(_ n: Int?) -> String {
        let v = n ?? 2
        return [1: "가벼움", 2: "보통", 3: "결정적"][v] ?? String(v)
    }

    /// 지금 값 → 새 값 한 줄. `before` 가 비었거나 같으면 nil (웹 `diff`).
    public struct Change: Equatable, Sendable {
        public let label: String
        public let before: String?
        public let after: String
    }

    static func change(_ label: String, _ before: String?, _ after: String) -> Change {
        Change(label: label, before: before.flatMap { $0.isEmpty || $0 == after ? nil : $0 }, after: after)
    }

    /// 인물 상태 칸 (감정, 목표, 위치, 메모). 변경안에 적힌 칸만.
    public static func stateRows(_ u: CharacterState, current cur: CharacterState?) -> [Change] {
        [("감정", u.emotionalState, cur?.emotionalState), ("목표", u.currentGoal, cur?.currentGoal),
         ("위치", u.location, cur?.location), ("메모", u.notes, cur?.notes)]
            .compactMap { label, after, before in
                guard let after, !after.isEmpty else { return nil }
                return change(label, before, after)
            }
    }

    /// 새로 알게 된 정보 (지금 아는 것은 뺀다).
    public static func newKnows(_ u: CharacterState, current cur: CharacterState?) -> [String] {
        let known = Set(cur?.knows ?? [])
        return (u.knows ?? []).filter { !known.contains($0) }
    }

    /// 지금 관계 설정 (방향은 가리지 않는다).
    public static func relation(_ a: String, _ b: String, _ p: Project) -> Components.Schemas.Relationship? {
        (p.relationships ?? []).first { r in
            let same = r.a == a && r.b == b
            return same || (r.a == b && r.b == a)
        }
    }

    /// 설정에도 이번 새 인물에도 없는 인물.
    public static func unknown(_ id: String, _ d: StateDelta, _ p: Project) -> Bool {
        !(p.characters ?? []).contains { $0.id == id } && !(d.newCharacters ?? []).contains { $0.id == id }
    }

    /// 상태창 한 줄 (웹 `swDeltaRows`). `after` 가 nil 이면 항목을 지운다. `raw` 는 '+3' 처럼 계산한 값과 다를 때만.
    public struct StatRow: Equatable, Sendable {
        public let name: String
        public let before: String?
        public let after: String?
        public let raw: String?
    }

    public static func statRows(_ u: CharacterState, current cur: CharacterState?) -> [StatRow] {
        let now = Dictionary((cur?.stats ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        return (u.stats ?? []).compactMap { s in
            guard !s.name.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
            let b = now[s.name.trimmingCharacters(in: .whitespaces)] ?? ""
            let v = (s.value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let a = v.isEmpty ? "" : resolve(b, s.value ?? "")
            return StatRow(name: s.name, before: b.isEmpty ? nil : b, after: a.isEmpty ? nil : a, raw: !v.isEmpty && v != a ? v : nil)
        }
    }

    /// 서버 `statwin.resolve` 와 같은 규칙 (웹 `swResolve`, `FeatureStatWin` 의 `StatWinText.resolve`):
    /// 이전 값이 숫자일 때만 '+3', '-10' 을 더하고 뺀다. 그 밖에는 적은 값 그대로.
    public static func resolve(_ before: String, _ value: String) -> String {
        let v = value.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: ",", with: "")
        let b = before.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: ",", with: "")
        if let first = v.first, "+-".contains(first), isNumber(v), isNumber(b), let x = Double(v), let y = Double(b) {
            let sum = x + y
            if sum == sum.rounded(), abs(sum) < 1e15 { return String(Int(sum)) }
            var s = String(format: "%.2f", sum)
            while s.hasSuffix("0") { s.removeLast() }
            if s.hasSuffix(".") { s.removeLast() }
            return s
        }
        return value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func isNumber(_ s: String) -> Bool {
        s.range(of: #"^[+-]?\d+(?:\.\d+)?$"#, options: .regularExpression) != nil
    }

    /// AI 가 본문에서 찾은 복선 문장 한 줄 (웹 `fsClueRows`).
    public struct ClueRow: Equatable, Sendable {
        /// '회수한 문장', '심은 문장', '다시 떠올린 문장'
        public let note: String
        public let payoff: Bool
        public let label: String
        public let quote: String
    }

    public static func clueRows(_ d: StateDelta, _ p: Project) -> [ClueRow] {
        let planted = d.foreshadowPlanted ?? []
        return (d.foreshadowClues ?? []).map { c in
            let f = (p.foreshadows ?? []).first { $0.id == c.foreshadow }?.description ?? planted.first { $0.id == c.foreshadow }?.description
            let payoff = c.kind == .payoff
            let fresh = planted.contains { $0.id == c.foreshadow }
            return ClueRow(note: payoff ? "회수한 문장" : fresh ? "심은 문장" : "다시 떠올린 문장", payoff: payoff, label: f ?? c.foreshadow, quote: c.quote)
        }
    }

    /// 새 장소 한 줄의 덧붙임: 종류, 다른 이름 (웹 `placeLabel`).
    public static func placeDetail(_ x: NewPlace) -> String {
        var parts: [String] = []
        if let k = x.kind, !k.isEmpty { parts.append(k) }
        if let a = x.aliases, !a.isEmpty { parts.append("다른 이름: \(a.joined(separator: ", "))") }
        return parts.joined(separator: " · ")
    }

    // MARK: 관계 미리 보기

    /// 미리 보기 한 줄. `was` 는 바뀐 줄의 지금 값 (새 관계면 nil).
    public struct RelationLine: Equatable, Sendable {
        public let text: String
        public let changed: Bool
        public let was: String?
    }

    /// 줄 앞 '도현 → 서윤' 같은 쌍 (웹 `relationLines` 의 `pair`).
    static func pair(_ line: String) -> String {
        var s = String(line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).first ?? "")
        if let r = s.range(of: " (") { s = String(s[..<r.lowerBound]) }
        if let r = s.range(of: " 서로") { s = String(s[..<r.lowerBound]) }
        return s.trimmingCharacters(in: .whitespaces)
    }

    /// 반영하면 바뀌는 관계 줄 (웹 `relationLines`). 첫 값은 위에 보일 한 줄.
    public static func relationLines(_ rel: RelationPreview, numbers: Bool) -> (head: String, lines: [RelationLine]) {
        let text = numbers ? rel.numbers : rel.words
        if text.isEmpty { return ("관계가 없어요. 설정 도우미에서 관계를 추가하세요.", []) }
        let before = numbers ? rel.before.numbers : rel.before.words
        var now: [String: String] = [:]
        for l in before.split(separator: "\n").map(String.init) where !l.isEmpty { now[pair(l)] = l }
        let lines = text.split(separator: "\n").map(String.init).filter { !$0.isEmpty }.map { l in
            let was = now[pair(l)]
            return RelationLine(text: l, changed: was != l, was: was == l ? nil : was)
        }
        let changed = lines.filter(\.changed).count
        return (changed > 0 ? "반영하면 \(changed)줄이 바뀌어요. 바뀌는 줄 아래에 지금 값을 함께 보여요." : "반영해도 관계는 그대로예요.", lines)
    }

    // MARK: 반영 뒤 고친 화 (restate.js)

    /// 반영이 끝난 뒤 저장된 본문을 고쳤다 (서버 `pipeline.edited_after_final`, 웹 `editedAfterFinal`).
    public static func editedAfterFinal(_ e: Episode?) -> Bool {
        guard let e, e.status == .finalized, let f = e.finalText, !f.isEmpty else { return false }
        return f != (e.text ?? "")
    }

    /// n화 뒤에 본문이 있는 화 (웹 `laterWritten`).
    public static func laterWritten(_ n: Int, _ p: Project) -> [Int] {
        (p.episodes ?? []).filter { $0.plot.number > n && !($0.text ?? "").isEmpty }.map(\.plot.number).sorted()
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

    /// 다시 맞출 수 있는 항목: 이미 있는 것을 뺀 새 사실 · 새 복선과 새 장소의 번호 (웹 `rsItems`).
    public struct RestateItems: Equatable, Sendable {
        public let facts: [Int]
        public let plants: [Int]
        public let places: [Int]
    }

    public static func restateItems(_ d: StateDelta, _ p: Project) -> RestateItems {
        let facts = Set(p.facts ?? [])
        let fs = Set((p.foreshadows ?? []).map(\.id))
        return RestateItems(
            facts: (d.newFacts ?? []).enumerated().filter { !$0.element.trimmingCharacters(in: .whitespaces).isEmpty && !facts.contains($0.element) }.map(\.offset),
            plants: (d.foreshadowPlanted ?? []).enumerated().filter { !fs.contains($0.element.id) }.map(\.offset),
            places: Array((d.newPlaces ?? []).indices))
    }

    /// 처음 고를 항목: 요약(sum)과 다시 맞출 수 있는 항목 모두 (웹 `rsPicks`).
    public static func restatePicks(_ d: StateDelta, _ p: Project) -> Set<String> {
        let it = restateItems(d, p)
        return Set(["sum"] + it.facts.map { "f\($0)" } + it.plants.map { "p\($0)" } + it.places.map { "l\($0)" })
    }

    /// 다시 맞추기로 보낼 변경안 (웹 `applyRestate` 의 `body`). 요약을 고르지 않으면 빈 요약.
    public static func restateBody(_ d: StateDelta, _ picks: Set<String>) -> StateDelta {
        var out = d
        if !picks.contains("sum") { out.summary = "" }
        out.newFacts = (d.newFacts ?? []).enumerated().filter { picks.contains("f\($0.offset)") }.map(\.element)
        out.foreshadowPlanted = (d.foreshadowPlanted ?? []).enumerated().filter { picks.contains("p\($0.offset)") }.map(\.element)
        out.newPlaces = (d.newPlaces ?? []).enumerated().filter { picks.contains("l\($0.offset)") }.map(\.element)
        return out
    }

    /// 다시 맞추기에서 반영하지 않는 항목 ('인물 상태 2건') (웹 `restateCard` 의 `skipped`).
    public static func restateSkipped(_ d: StateDelta) -> [String] {
        let counts: [(String, Int)] = [("인물 상태", d.characterUpdates?.count ?? 0), ("관계 사건", d.events?.count ?? 0),
                                       ("관계 유형", d.relationshipUpdates?.count ?? 0), ("새 비밀", d.secretsAdded?.count ?? 0),
                                       ("복선 회수", d.foreshadowResolved?.count ?? 0), ("새 인물", d.newCharacters?.count ?? 0)]
        return counts.filter { $0.1 > 0 }.map { "\($0.0) \($0.1)건" }
    }

    /// 다시 맞춘 뒤 알림 (웹 `applyRestate` 의 toast).
    public static func restateDone(_ n: Int, body: StateDelta) -> String {
        let facts = body.newFacts?.count ?? 0
        let plants = body.foreshadowPlanted?.count ?? 0
        let places = body.newPlaces?.count ?? 0
        var what: [String] = []
        if !body.summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { what.append("요약") }
        if facts > 0 { what.append("새 사실 \(facts)건") }
        if plants > 0 { what.append("새 복선 \(plants)건") }
        if places > 0 { what.append("새 장소 \(places)곳") }
        return what.isEmpty ? "\(n)화 반영 뒤 고침 표시를 지웠어요" : "\(n)화 \(what.joined(separator: ", "))을 반영했어요"
    }

    // MARK: 반영 취소 (웹 `revertFrom`)

    /// 반영 취소 전에 묻는 말.
    /// n화부터 반영이 끝난 화. 반영을 취소하면 모두 돌아간다.
    public static func finalized(from n: Int, _ p: Project) -> [Int] {
        (p.episodes ?? []).filter { $0.status == .finalized && $0.plot.number >= n }.map(\.plot.number)
    }

    public static func revertQuestion(_ n: Int, _ p: Project) -> String {
        let fin = finalized(from: n, p)
        let added = (p.history ?? []).filter { $0.episode >= n }.flatMap { $0.newCharacters ?? [] }.map { $0.name.isEmpty ? $0.id : $0.name }
        let places = (p.elements ?? []).filter { $0.foundIn == .본문 && ($0.foundEp ?? 0) >= n }.map { $0.name ?? $0.id }
        var s = "\(rangeText(fin))화의 상태 반영을 취소할까요? \(n - 1 > 0 ? "\(n - 1)화 반영 직후" : "1화 시작 전") 상태로 돌아가고, 본문은 남아 상태 승인을 다시 하게 돼요."
        if !added.isEmpty { s += " 그 반영이 더한 인물(\(added.joined(separator: ", ")))도 빠져요." }
        if !places.isEmpty { s += " 본문에서 등록한 장소(\(places.joined(separator: ", ")))도 빠져요. 아직 안 쓴 화 플롯에 나오거나 직접 고친 장소는 남아요." }
        return s
    }

    /// `fin` 은 취소하기 전 `finalized(from:)`.
    public static func revertDone(_ n: Int, fin: [Int]) -> String {
        return "\(rangeText(fin))화의 반영을 취소했어요. \(n)화 변경안을 다시 골라 적용하세요"
    }
}
