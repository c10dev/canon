import CanonAPI
import CanonCore
import CanonStore
import Foundation

public typealias Person = Components.Schemas.Character
public typealias Relationship = Components.Schemas.Relationship
public typealias World = Components.Schemas.WorldSetting
public typealias Genre = Components.Schemas.Genre
public typealias SetupSuggestion = Components.Schemas.SetupSuggestion
public typealias NamingStyle = Components.Schemas.NamingStyleOut
public typealias NamesOut = Components.Schemas.NamesOut
public typealias NameCheck = Components.Schemas.NameCheckOut
public typealias NameIssue = Components.Schemas.NameIssue

/// 설정 도우미의 편집 규칙. 웹 `app.js` 의 설정 도우미(`viewSetup`, `actions` 의 인물 · 관계 · 장르)와 같아 함께 고친다.
public enum SetupRules {
    /// 인물 비중 (웹 `TIERS`).
    public static let tiers: [(Person.TierPayload, String)] = [(.main, "주역"), (.support, "조연"), (.minor, "단역")]
    /// '어떤 사이' 예시 칩 (웹 `REL_TYPES`).
    public static let relationTypes = ["가족", "친구", "동료", "연인", "옛 연인", "라이벌", "사제", "상사와 부하"]
    /// '원하는 게 부딪치나' (웹 `CONFLICTS`).
    public static let conflicts: [(String, Double)] = [("아니다", 0), ("조금", 0.4), ("정면으로", 0.8)]

    public static func conflictWord(_ v: Double) -> String {
        v >= 0.6 ? "정면으로" : v > 0 ? "조금" : "아니다"
    }

    /// 새 인물. id 는 관계와 플롯이 인물을 찾는 열쇠라 자동으로 짓는다: 처음은 hero, 다음은 char<n> (웹 `addCharacter`).
    public static func newCharacter(after people: [Person]) -> Person {
        let ids = Set(people.map(\.id))
        var id = ids.contains("hero") ? "" : "hero"
        var n = people.count + 1
        while id.isEmpty {
            if !ids.contains("char\(n)") { id = "char\(n)" }
            n += 1
        }
        return Person(id: id, name: "", role: id == "hero" ? "주인공" : "조연", age: "", gender: "", appearance: "",
                      personality: "", background: "", goal: "", wound: "", speechStyle: "", secrets: [], arc: "")
    }

    /// 인물 이름. 없으면 id (웹 `charName`, 인물 후보도 본다).
    public static func name(_ id: String, in p: Project?) -> String {
        let c = p?.characters?.first { $0.id == id } ?? p?.castCandidates?.first { $0.id == id }
        guard let c else { return id }
        return c.name.isEmpty ? id : c.name
    }

    /// 인물을 지우기 전에 묻는 말. 플롯 · 반영 기록에 남은 id 를 알린다 (웹 `removeCharacter`).
    public static func removalQuestion(_ c: Person, in p: Project) -> String {
        let shown = c.name.isEmpty ? c.id : c.name
        let inPlots = (p.episodes ?? []).filter { $0.plot.characters.contains(c.id) }.map(\.plot.number)
        var inHistory: [Int] = []
        for h in p.history ?? [] {
            let used = (h.events ?? []).contains { $0.actor == c.id || $0.target == c.id }
                || (h.characterUpdates ?? []).contains { $0.characterId == c.id }
            if used, !inHistory.contains(h.episode) { inHistory.append(h.episode) }
        }
        let used = [inPlots.isEmpty ? "" : "\(rangeText(inPlots))화 플롯의 등장 인물",
                    inHistory.isEmpty ? "" : "\(rangeText(inHistory))화 반영 기록"].filter { !$0.isEmpty }
        var warn = ""
        if !used.isEmpty {
            warn = "\n이 인물은 \(used.joined(separator: "과 "))에 남아 있어요. 그곳에는 이름 대신 id(\(c.id))로 보여요."
            if !inHistory.isEmpty { warn += " 이미 반영한 화에 나온 인물이면 지우기보다 비중을 단역으로 낮추는 편이 안전해요." }
        }
        return "\(shown) 인물을 삭제할까요? 관계와 지금 상태도 함께 삭제돼요. 저장하기 전에는 저장 띠의 '되돌리기'로 되살릴 수 있어요.\(warn)"
    }

    /// 인물과 그 인물의 관계 · 지금 상태를 지운다. 플롯 · 반영 기록의 id 는 그대로 둔다.
    public static func remove(_ id: String, from p: inout Project) {
        p.characters?.removeAll { $0.id == id }
        p.relationships?.removeAll { $0.a == id || $0.b == id }
        p.states?.removeAll { $0.characterId == id }
    }

    /// 아직 관계가 없는 첫 인물 쌍으로 새 관계. 인물이 둘 미만이거나 모든 쌍에 관계가 있으면 그 까닭 (웹 `addRelationship`).
    public static func newRelationship(in p: Project) -> Result<Relationship, SetupProblem> {
        let cs = p.characters ?? []
        guard cs.count >= 2 else { return .failure(.init("인물이 두 명 이상 있어야 해요")) }
        let has = Set((p.relationships ?? []).map { pairKey($0.a, $0.b) })
        for (i, x) in cs.enumerated() {
            for y in cs[(i + 1)...] where !has.contains(pairKey(x.id, y.id)) {
                return .success(Relationship(a: x.id, b: y.id, _type: "", description: "", affinity: 0, tension: 0, goalConflict: 0, aView: [], bView: []))
            }
        }
        return .failure(.init("모든 인물 쌍에 관계가 이미 있어요"))
    }

    /// 같은 인물끼리이거나 앞선 관계와 같은 쌍이면 알린다. 서버는 이런 관계를 저장하지 않는다 (웹 `relProblem`).
    public static func relationshipProblem(_ i: Int, in rels: [Relationship]) -> String? {
        let r = rels[i]
        if r.a == r.b { return "같은 인물끼리는 관계를 만들 수 없어요. 인물 B를 바꾸세요." }
        guard let j = rels.indices.first(where: { $0 != i && pairKey(rels[$0].a, rels[$0].b) == pairKey(r.a, r.b) }) else { return nil }
        return "이 두 인물의 관계가 \(j + 1)번째에도 있어요. 하나만 남기세요."
    }

    /// 첫 상태 반영 뒤에는 관계를 사건으로 계산한다. 그 전에만 말로 시작 관계를 고른다.
    public static func started(_ p: Project?) -> Bool { !(p?.snapshots ?? []).isEmpty }

    /// 보는 방식 말을 켜고 끈다.
    public static func toggle(_ word: String, in list: [String]?) -> [String] {
        let l = list ?? []
        return l.contains(word) ? l.filter { $0 != word } : l + [word]
    }

    /// 화면과 프롬프트에 쓸 한 줄 장르 (서버 `genres.label`, 웹 `genreLabel`).
    public static func genreLabel(_ m: Meta?, catalog: [Genre]) -> String {
        let names = (m?.genres ?? []).map { id in catalog.first { $0.id == id }?.name ?? id }
        let joined = names.joined(separator: " · ")
        return joined.isEmpty ? m?.genre ?? "" : joined
    }

    /// 장르를 켜고 끄고 한 줄 장르를 맞춘다 (웹 `toggleGenre` · `syncGenre`).
    public static func toggleGenre(_ id: String, in m: inout Meta, catalog: [Genre]) {
        let g = m.genres ?? []
        m.genres = g.contains(id) ? g.filter { $0 != id } : g + [id]
        m.genre = genreLabel(m, catalog: catalog)
    }

    /// 직접 적은 장르를 더한다. 목록의 이름이나 id 와 같으면 그 장르로 (웹 `addCustomGenre`).
    public static func addGenre(_ text: String, in m: inout Meta, catalog: [Genre]) {
        let v = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !v.isEmpty else { return }
        let id = catalog.first { $0.name == v || $0.id == v }?.id ?? v
        if !(m.genres ?? []).contains(id) { m.genres = (m.genres ?? []) + [id] }
        m.genre = genreLabel(m, catalog: catalog)
    }

    /// 고른 장르의 로그라인 예시. 고른 장르가 목록에 없으면 미스터리와 현대 드라마 예시 (웹 `loglineExamples`).
    public static func loglineExamples(_ m: Meta?, catalog: [Genre]) -> [LoglineParts] {
        let ids = (m?.genres ?? []).filter { id in catalog.contains { $0.id == id } }
        return (ids.isEmpty ? ["mystery", "drama"] : ids).flatMap { id in catalog.first { $0.id == id }?.logline ?? [] }
    }

    /// 칸마다 예시 칩: 예시에서 그 칸 글 중 서로 다른 앞 셋.
    public static func slotExamples(_ field: LoglineField, _ examples: [LoglineParts]) -> [String] {
        var out: [String] = []
        for e in examples {
            let v = field.get(e)
            if !v.isEmpty, !out.contains(v) { out.append(v) }
        }
        return Array(out.prefix(3))
    }

    /// 화 번호 묶음 '1~3, 5' (웹 `rangeText`).
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

    static func pairKey(_ a: String, _ b: String) -> String { [a, b].sorted().joined(separator: "|") }
}

public struct SetupProblem: Error, Equatable, Sendable {
    public let message: String
    public init(_ message: String) { self.message = message }
}

/// 이름 점검 묶음 (웹 `nameCheckBox`): 종류별 소제목, 같은 이름 · 성을 뺀 이름은 경고, 나머지는 안내.
public struct NameCheckGroups: Equatable, Sendable {
    public struct Group: Equatable, Sendable {
        public let title: String
        public let issues: [NameIssue]
    }

    public let head: String
    public let warn: Bool
    public let groups: [Group]

    static let order = ["same", "given", "confusable", "era", "style", "overused", "other"]

    public init?(_ check: NameCheck) {
        let issues = check.issues
        guard !issues.isEmpty else { return nil }
        let kinds = check.kinds.additionalProperties
        let warns = issues.filter { $0.level == "warn" }.count
        warn = warns > 0
        head = "이름 점검 \(issues.count)건" + (warn ? " · 같은 이름 \(warns)건" : "")
        groups = Self.order.compactMap { k in
            let list = issues.filter { (Self.order.contains($0.kind) ? $0.kind : "other") == k }
            return list.isEmpty ? nil : Group(title: kinds[k] ?? "기타", issues: list)
        }
    }

    /// 그 인물에 해당하는 점검만 (인물 카드 아래, 웹 `nameIssuesFor`).
    public static func issues(for id: String, in check: NameCheck?) -> [NameIssue] {
        (check?.issues ?? []).filter { $0.ids.contains(id) }
    }
}

/// AI 설정 제안에서 고르기 (웹 `viewSuggestion` · `applySuggestion` · `sameChar` · `sugEnd` · `SUG_FIELDS`).
/// 고른 표시는 `[열쇠: Bool]` 이고, 열쇠가 없으면 기본값을 쓴다. 열쇠: 칸 'sf:<칸>', 인물 'sc<번호>', 관계 'sr<번호>'.
public enum SuggestionPicks {
    /// 칸마다 고르는 기본 정보 · 세계관. 서버(`pipeline.apply_setup`)는 빈 칸만 채운다.
    public static let fields: [(key: String, label: String)] = [
        ("theme", "주제"), ("tone", "톤"), ("world.setting", "배경"), ("world.era", "시대"), ("world.rules", "규칙"),
        ("world.locations", "장소"), ("world.name_style", "이름 스타일"), ("world.name_rules", "이름 규칙"),
    ]

    /// 제안의 그 칸 글.
    public static func value(_ s: SetupSuggestion, _ key: String) -> String {
        if key == "theme" { return s.theme }
        if key == "tone" { return s.tone }
        return worldValue(s.world, key)
    }

    /// 작품의 그 칸 글. 주제 · 톤은 meta 에 있다.
    public static func value(_ p: Project?, _ key: String) -> String {
        if key == "theme" { return p?.meta?.theme ?? "" }
        if key == "tone" { return p?.meta?.tone ?? "" }
        return worldValue(p?.world, key)
    }

    static func worldValue(_ w: World?, _ key: String) -> String {
        switch key {
        case "world.setting": w?.setting ?? ""
        case "world.era": w?.era ?? ""
        case "world.rules": (w?.rules ?? []).joined(separator: ", ")
        case "world.locations": (w?.locations ?? []).joined(separator: ", ")
        case "world.name_style": w?.nameStyle ?? ""
        case "world.name_rules": (w?.nameRules ?? []).joined(separator: ", ")
        default: ""
        }
    }

    /// 제안 인물이 이미 있는 인물과 같은 사람이다: id 가 같고 이름도 같다 (이름이 다르면 서버가 새 id 로 넣는다).
    public static func same(_ c: Person, in p: Project?) -> Bool {
        guard let old = p?.characters?.first(where: { $0.id == c.id }) else { return false }
        let name = c.name.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty || old.name.trimmingCharacters(in: .whitespacesAndNewlines) == name
    }

    /// 같은 id 의 다른 인물이 있어 서버가 새 id 로 넣는다.
    public static func clash(_ c: Person, in p: Project?) -> Bool {
        !same(c, in: p) && (p?.characters ?? []).contains { $0.id == c.id }
    }

    /// 칸이 이미 채워져 있어 건너뛴다.
    public static func has(_ key: String, in p: Project?) -> Bool { !value(p, key).isEmpty }

    /// 고른 상태. 칸은 작품에 이미 있으면 늘 꺼짐, 인물은 이미 있는 사람이면 꺼짐, 관계는 양쪽 인물이 있어야 켜짐.
    public static func picked(_ key: String, _ s: SetupSuggestion, _ p: Project?, _ picks: [String: Bool]) -> Bool {
        if key.hasPrefix("sf:") {
            let k = String(key.dropFirst(3))
            return !has(k, in: p) && picks[key] != false
        }
        if key.hasPrefix("sc"), let i = Int(key.dropFirst(2)), s.characters.indices.contains(i) {
            return !same(s.characters[i], in: p) && (picks[key] ?? true)
        }
        if key.hasPrefix("sr"), let i = Int(key.dropFirst(2)), s.relationships.indices.contains(i) {
            let r = s.relationships[i]
            return (picks[key] ?? true) && end(r.a, s, p, picks) != nil && end(r.b, s, p, picks) != nil
        }
        return false
    }

    /// 제안 관계의 한쪽 인물: 고른 제안 인물이면 그 인물, 아니면 이미 있는 인물. 고르지 않은 제안 인물이면 nil.
    public static func end(_ id: String, _ s: SetupSuggestion, _ p: Project?, _ picks: [String: Bool]) -> Person? {
        if let i = s.characters.firstIndex(where: { $0.id == id }), !same(s.characters[i], in: p) {
            return picked("sc\(i)", s, p, picks) ? s.characters[i] : nil
        }
        return p?.characters?.first { $0.id == id }
    }

    /// 서버에 보낼 제안: 고르지 않은 칸은 비우고(서버가 건너뛴다), 고른 인물 · 관계만 남긴다.
    public static func chosen(_ s: SetupSuggestion, _ p: Project?, _ picks: [String: Bool]) -> SetupSuggestion {
        var out = s
        for (k, _) in fields where picks["sf:" + k] == false {
            switch k {
            case "theme": out.theme = ""
            case "tone": out.tone = ""
            case "world.setting": out.world.setting = ""
            case "world.era": out.world.era = ""
            case "world.rules": out.world.rules = []
            case "world.locations": out.world.locations = []
            case "world.name_style": out.world.nameStyle = ""
            case "world.name_rules": out.world.nameRules = []
            default: break
            }
        }
        out.characters = s.characters.indices.filter { picked("sc\($0)", s, p, picks) }.map { s.characters[$0] }
        out.relationships = s.relationships.indices.filter { picked("sr\($0)", s, p, picks) }.map { s.relationships[$0] }
        return out
    }

    /// 제안 관계 한 줄: 'A ↔ B · 사이 · A→B 믿는다 · B→A -' 또는 '호감 2 · 긴장 3'.
    public static func relationLine(_ r: Relationship, _ s: SetupSuggestion, _ p: Project?, _ picks: [String: Bool]) -> String {
        let nm = { (id: String) -> String in
            guard let c = end(id, s, p, picks) else { return id }
            return c.name.isEmpty ? c.id : c.name
        }
        let a = nm(r.a), b = nm(r.b)
        let av = r.aView ?? [], bv = r.bView ?? []
        let detail = av.isEmpty && bv.isEmpty
            ? "호감 \(r.affinity ?? 0) · 긴장 \(r.tension ?? 0)"
            : "\(a)→\(b) \(av.isEmpty ? "-" : av.joined(separator: ", ")) · \(b)→\(a) \(bv.isEmpty ? "-" : bv.joined(separator: ", "))"
        return "\(a) ↔ \(b) · \(r._type) · \(detail)"
    }
}
