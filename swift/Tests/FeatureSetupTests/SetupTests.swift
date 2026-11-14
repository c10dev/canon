import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureSetup
import Foundation
import Testing

func person(_ id: String, _ name: String, role: String = "조연") -> Person {
    Person(id: id, name: name, role: role)
}

func rel(_ a: String, _ b: String, type: String = "친구", aView: [String] = [], bView: [String] = []) -> Relationship {
    Relationship(a: a, b: b, _type: type, affinity: 1, tension: 2, aView: aView, bView: bView)
}

@Suite struct SetupRulesTests {
    @Test func newCharacterIDs() {
        #expect(SetupRules.newCharacter(after: []).id == "hero")
        #expect(SetupRules.newCharacter(after: []).role == "주인공")
        let two = [person("hero", "서진"), person("char2", "도현")]
        let c = SetupRules.newCharacter(after: two)
        #expect(c.id == "char3")
        #expect(c.role == "조연")
        #expect(SetupRules.newCharacter(after: [person("char2", "")]).id == "hero")
    }

    @Test func newRelationshipFindsFreePair() {
        var p = Project(characters: [person("a", "가"), person("b", "나"), person("c", "다")], relationships: [rel("b", "a")])
        guard case let .success(r) = SetupRules.newRelationship(in: p) else { Issue.record("관계를 만들지 못했어요"); return }
        #expect((r.a, r.b) == ("a", "c"))
        p.relationships = [rel("a", "b"), rel("a", "c"), rel("c", "b")]
        #expect(SetupRules.newRelationship(in: p) == .failure(SetupProblem("모든 인물 쌍에 관계가 이미 있어요")))
        #expect(SetupRules.newRelationship(in: Project(characters: [person("a", "가")])) == .failure(SetupProblem("인물이 두 명 이상 있어야 해요")))
    }

    @Test func relationshipProblems() {
        let rels = [rel("a", "b"), rel("b", "a"), rel("c", "c")]
        #expect(SetupRules.relationshipProblem(0, in: rels) == "이 두 인물의 관계가 2번째에도 있어요. 하나만 남기세요.")
        #expect(SetupRules.relationshipProblem(1, in: rels) == "이 두 인물의 관계가 1번째에도 있어요. 하나만 남기세요.")
        #expect(SetupRules.relationshipProblem(2, in: rels) == "같은 인물끼리는 관계를 만들 수 없어요. 인물 B를 바꾸세요.")
        #expect(SetupRules.relationshipProblem(0, in: [rel("a", "b")]) == nil)
    }

    @Test func conflictWords() {
        #expect(SetupRules.conflictWord(0) == "아니다")
        #expect(SetupRules.conflictWord(0.4) == "조금")
        #expect(SetupRules.conflictWord(0.6) == "정면으로")
        #expect(SetupRules.toggle("믿는다", in: ["믿는다", "빚졌다"]) == ["빚졌다"])
        #expect(SetupRules.toggle("얕본다", in: nil) == ["얕본다"])
    }

    @Test func removalAsksAboutPlotsAndHistory() {
        let plot = { (n: Int, cast: [String]) in
            Components.Schemas.Episode(plot: .init(number: n, act: .기, title: "", summary: "", events: [], characters: cast, emotionalShift: "", endingHook: ""))
        }
        var p = Project(characters: [person("hero", "서진"), person("ally", "")], relationships: [rel("hero", "ally")],
                        episodes: [plot(1, ["hero"]), plot(2, ["hero"]), plot(4, ["hero"]), plot(5, ["ally"])],
                        states: [.init(characterId: "hero"), .init(characterId: "ally")],
                        history: [.init(episode: 1, summary: "", characterUpdates: [.init(characterId: "hero")])])
        #expect(SetupRules.removalQuestion(p.characters![0], in: p)
            == "서진 인물을 삭제할까요? 관계와 지금 상태도 함께 삭제돼요. 저장하기 전에는 저장 띠의 '되돌리기'로 되살릴 수 있어요.\n이 인물은 1~2, 4화 플롯의 등장 인물과 1화 반영 기록에 남아 있어요. 그곳에는 이름 대신 id(hero)로 보여요. 이미 반영한 화에 나온 인물이면 지우기보다 비중을 단역으로 낮추는 편이 안전해요.")
        #expect(SetupRules.removalQuestion(p.characters![1], in: p).hasPrefix("ally 인물을 삭제할까요?"))
        SetupRules.remove("hero", from: &p)
        #expect(p.characters?.map(\.id) == ["ally"])
        #expect(p.relationships == [])
        #expect(p.states?.map(\.characterId) == ["ally"])
        #expect(p.episodes?[0].plot.characters == ["hero"])  // 플롯의 id 는 그대로 둔다
    }

    @Test func rangeText() {
        #expect(SetupRules.rangeText([1, 2, 3, 5, 7, 8]) == "1~3, 5, 7~8")
        #expect(SetupRules.rangeText([]) == "")
    }

    @Test func genres() {
        let catalog = [Genre(id: "mystery", name: "미스터리", kind: .장르, summary: "", logline: [LoglineParts(who: "사진관을 하는 서윤", goal: "되짚는다")]),
                       Genre(id: "drama", name: "현대 드라마", summary: "", logline: [LoglineParts(who: "은퇴한 기자", goal: "되짚는다")]),
                       Genre(id: "regression", name: "회귀", kind: .요소, summary: "")]
        var m = Meta()
        SetupRules.toggleGenre("mystery", in: &m, catalog: catalog)
        SetupRules.addGenre("회귀", in: &m, catalog: catalog)
        SetupRules.addGenre(" 오컬트 ", in: &m, catalog: catalog)
        #expect(m.genres == ["mystery", "regression", "오컬트"])
        #expect(m.genre == "미스터리 · 회귀 · 오컬트")
        SetupRules.toggleGenre("mystery", in: &m, catalog: catalog)
        #expect(m.genre == "회귀 · 오컬트")
        // 고른 장르에 예시가 없으면 미스터리와 현대 드라마 예시
        #expect(SetupRules.loglineExamples(Meta(genres: ["오컬트"]), catalog: catalog).map(\.who) == ["사진관을 하는 서윤", "은퇴한 기자"])
        #expect(SetupRules.loglineExamples(Meta(genres: ["drama"]), catalog: catalog).map(\.who) == ["은퇴한 기자"])
        #expect(SetupRules.slotExamples(.goal, SetupRules.loglineExamples(nil, catalog: catalog)) == ["되짚는다"])
        #expect(SetupRules.genreLabel(Meta(genre: "옛 장르", genres: []), catalog: catalog) == "옛 장르")
    }

    @Test func nameCheckGroups() {
        let check = NameCheck(warnings: ["a", "b", "c"], issues: [
            .init(kind: "overused", level: "info", text: "흔해요", ids: ["c1"]),
            .init(kind: "same", level: "warn", text: "같아요", ids: ["c1", "c2"]),
            .init(kind: "mystery", level: "info", text: "기타", ids: []),
        ], kinds: .init(additionalProperties: ["same": "같은 이름", "overused": "흔한 이름"]), style: "korea_modern", detected: "korea_modern")
        let g = NameCheckGroups(check)
        #expect(g?.head == "이름 점검 3건 · 같은 이름 1건")
        #expect(g?.warn == true)
        #expect(g?.groups.map(\.title) == ["같은 이름", "흔한 이름", "기타"])
        #expect(NameCheckGroups.issues(for: "c2", in: check).map(\.text) == ["같아요"])
        #expect(NameCheckGroups(NameCheck(warnings: [], issues: [], kinds: .init(), style: "", detected: "")) == nil)
    }
}

@Suite struct SuggestionPicksTests {
    let project = Project(meta: .init(theme: "이미 있는 주제"), world: .init(era: ""),
                          characters: [person("hero", "서진", role: "주인공"), person("ally", "도현")])
    let suggestion = SetupSuggestion(
        theme: "새 주제", tone: "서늘하다", world: .init(setting: "바닷가 마을", era: "현대", rules: ["규칙"], locations: []),
        characters: [person("hero", "서진"), person("ally", "민재"), person("rival", "한결")],
        relationships: [rel("hero", "rival", aView: ["경계한다"]), rel("ally", "hero"), rel("rival", "ghost")])

    @Test func defaults() {
        let s = suggestion, p = project
        #expect(SuggestionPicks.same(s.characters[0], in: p))
        #expect(!SuggestionPicks.same(s.characters[1], in: p))
        #expect(SuggestionPicks.clash(s.characters[1], in: p))
        #expect(!SuggestionPicks.picked("sf:theme", s, p, [:]))  // 이미 있는 칸은 건너뛴다
        #expect(SuggestionPicks.picked("sf:tone", s, p, [:]))
        #expect(SuggestionPicks.picked("sf:world.era", s, p, [:]))
        #expect(!SuggestionPicks.picked("sc0", s, p, [:]))  // 이미 있는 인물
        #expect(SuggestionPicks.picked("sc1", s, p, [:]))
        #expect(SuggestionPicks.picked("sr0", s, p, [:]))
        #expect(!SuggestionPicks.picked("sr2", s, p, [:]))  // ghost 는 어디에도 없다
    }

    @Test func relationNeedsPickedEnds() {
        let s = suggestion, p = project
        #expect(!SuggestionPicks.picked("sr0", s, p, ["sc2": false]))
        // ally 는 이름이 달라 제안 인물로 본다. 고르지 않으면 관계도 넣지 않는다
        #expect(!SuggestionPicks.picked("sr1", s, p, ["sc1": false]))
        #expect(SuggestionPicks.relationLine(s.relationships[0], s, p, [:]) == "서진 ↔ 한결 · 친구 · 서진→한결 경계한다 · 한결→서진 -")
        #expect(SuggestionPicks.relationLine(s.relationships[1], s, p, [:]) == "민재 ↔ 서진 · 친구 · 호감 1 · 긴장 2")
    }

    @Test func chosenBlanksUnpickedFields() {
        let out = SuggestionPicks.chosen(suggestion, project, ["sf:tone": false, "sf:world.rules": false, "sc1": false])
        #expect(out.tone == "")
        #expect(out.theme == "새 주제")  // 서버가 이미 있는 칸을 건너뛴다
        #expect(out.world.rules == [])
        #expect(out.world.setting == "바닷가 마을")
        #expect(out.characters.map(\.id) == ["rival"])
        #expect(out.relationships.map(\.a) == ["hero"])
    }
}

// MARK: 모델

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project
    var loads = 0
    init(_ project: Project) { self.project = project }
    func load(_ name: String) async throws -> Project { loads += 1; return project }
    func save(_ name: String, _ p: Project, merged: [String], force: Bool) async throws -> SaveResult {
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var pendingList = PendingList()
    var started: [JobRequest] = []
    var dropped: [String] = []
    func listJobs() async throws -> [Job] { [] }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        return (Job(id: "j1", project: project, kind: request.kind, label: "설정 제안"), false)
    }
    func stopJob(_ id: String) async throws -> Job { Job(id: id, project: "", kind: "", label: "") }
    func pending(_ project: String) async throws -> PendingList { pendingList }
    func dropPending(_ project: String, key: String, failure: Bool) async throws { dropped.append(key) }
}

final class FakeSetup: SetupService, @unchecked Sendable {
    let store: FakeStore
    var applied: [SetupSuggestion] = []
    var checks: [Components.Schemas.NameCheckIn] = []
    var failCheck = false
    var namesOut = NamesOut(style: "korea_modern", detected: "korea_modern", styleLabel: "현대 한국",
                            candidates: [.init(name: "윤서진", note: "1990년대생에 흔한 이름"), .init(name: "솔내", note: "", kind: "마을")],
                            options: [.init(name: "한결", reason: "단단한 느낌")])
    init(_ store: FakeStore) { self.store = store }

    func genres() async throws -> [Genre] { [Genre(id: "mystery", name: "미스터리", summary: "")] }
    func relationViews() async throws -> [String] { ["믿는다", "좋아한다"] }
    func namingStyles() async throws -> [NamingStyle] { [.init(id: "korea_modern", label: "현대 한국", summary: "", placeKinds: ["마을"])] }
    func names(_ project: String, _ body: Components.Schemas.NamesIn) async throws -> NamesOut { namesOut }
    func checkNames(_ project: String, _ body: Components.Schemas.NameCheckIn) async throws -> NameCheck {
        checks.append(body)
        if failCheck { throw CanonError.offline }
        return NameCheck(warnings: [], issues: [], kinds: .init(), style: "korea_modern", detected: "joseon")
    }
    func applySuggestion(_ project: String, _ s: SetupSuggestion) async throws {
        applied.append(s)
        store.project.characters = (store.project.characters ?? []) + s.characters
    }
}

@MainActor
func makeModel(_ p: Project, pending: PendingList = PendingList(), name: String = "등대") async -> (SetupModel, FakeStore, FakeJobs, FakeSetup) {
    let store = FakeStore(p)
    let doc = ProjectDocument(name: name, store: store)
    let jobs = FakeJobs()
    jobs.pendingList = pending
    let center = JobCenter(service: jobs)
    await center.open(doc)
    let service = FakeSetup(store)
    let model = SetupModel(document: doc, jobs: center, service: service)
    await model.load()
    return (model, store, jobs, service)
}

@MainActor
@Suite struct SetupModelTests {
    @Test func loadsListsAndChecksNames() async {
        let (m, _, _, service) = await makeModel(Project(characters: [person("hero", "서진")]))
        #expect(m.views == ["믿는다", "좋아한다"])
        #expect(m.genres.map(\.id) == ["mystery"])
        #expect(m.autoStyleLabel == "자동 (지금: joseon)")
        #expect(m.currentStyle?.id == "korea_modern")
        #expect(service.checks.first?.characters?.map(\.name) == ["서진"])
    }

    @Test func editsMarkDirty() async {
        let (m, _, _, _) = await makeModel(Project(characters: [person("hero", "서진")]))
        m.editMeta { Logline.set(.who, "등대지기 서진", in: &$0) }
        #expect(m.document.dirty)
        #expect(m.project?.meta?.logline == "등대지기 서진이")
        let id = m.addCharacter()
        #expect(id == "char2")
        m.addRelationship()
        #expect(m.project?.relationships?.count == 1)
        m.addRelationship()
        #expect(m.notice?.text == "모든 인물 쌍에 관계가 이미 있어요")
        m.removeCharacter("char2")
        #expect(m.project?.relationships == [])
    }

    @Test func namePicks() async {
        let (m, _, _, _) = await makeModel(Project(world: .init(locations: ["등대"]), characters: [person("hero", "")]))
        await m.characterNames("hero", ai: false)
        #expect(m.names["c:hero"]?.items.map(\.note) == ["1990년대생에 흔한 이름", "마을"])
        #expect(m.names["c:hero"]?.title(place: false) == "무작위 후보 · 현대 한국 · 눌러서 이름으로 쓰기")
        m.useName("윤서진", for: "hero")
        #expect(m.project?.characters?.first?.name == "윤서진")
        #expect(m.names["c:hero"] == nil)
        await m.placeNames(ai: true)
        #expect(m.names["place"]?.items.map(\.name) == ["한결"])
        m.addPlace("한결")
        #expect(m.project?.world?.locations == ["등대", "한결"])
        #expect(m.names["place"]?.items.isEmpty == true)
    }

    @Test func failedCheckIsShown() async {
        let (m, _, _, service) = await makeModel(Project(characters: []))
        service.failCheck = true
        await m.checkNames(show: true)
        #expect(m.nameCheck == .failed)
        #expect(m.notice?.isError == true)
    }

    @Test func applySuggestionSendsPicksAndDrops() async throws {
        let s = SetupSuggestion(theme: "새 주제", tone: "", world: .init(), characters: [person("hero", "서진"), person("rival", "한결")],
                                relationships: [rel("hero", "rival")])
        let pending = PendingList(results: ["suggest:": PendingResult(key: "suggest:", id: "j1", kind: "suggest", ep: nil, label: "설정 제안",
                                                                     result: try JSONValue.encoded(s), base: nil)])
        let (m, store, jobs, service) = await makeModel(Project(characters: [person("hero", "서진")]), pending: pending)
        #expect(m.suggestion?.characters.count == 2)
        #expect(!m.picked("sc0"))
        #expect(m.picked("sc1"))
        m.editMeta { $0.title = "고친 제목" }  // 저장하지 않은 변경은 먼저 저장한다
        await m.applySuggestion()
        #expect(store.project.meta?.title == "고친 제목")
        #expect(service.applied.first?.characters.map(\.id) == ["rival"])
        #expect(service.applied.first?.relationships.count == 1)
        #expect(m.project?.characters?.map(\.id) == ["hero", "rival"])
        #expect(!m.document.dirty)
        #expect(jobs.dropped == ["suggest:"])
        #expect(m.suggestion == nil)
        #expect(m.notice?.text == "빈칸을 채웠어요. 기존 입력은 그대로예요.")
    }

    @Test func suggestStartsJob() async {
        let (m, _, jobs, _) = await makeModel(Project(characters: []))
        await m.suggest()
        #expect(jobs.started.map(\.kind) == ["suggest"])
        #expect(m.suggestLabel == "빈칸 AI 제안받기")
    }
}

extension JSONValue {
    static func encoded<T: Encodable>(_ v: T) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(v))
    }
}

/// 새 작품 마법사 (웹 `setupMode` · `wizState` · `wizGo`). 보기는 작품 이름마다 기억하므로 시험마다 이름을 따로 쓴다.
@MainActor
@Suite struct SetupWizardModelTests {
    static func full() -> Project {
        Project(meta: Meta(title: "소금 정원의 계약", genres: ["romance_fantasy"], logline: "서윤이 염전을 되찾으려 한다."),
                world: World(setting: "북방 왕국"),
                characters: [person("hero", "서윤"), person("char2", "이헌")], relationships: [rel("hero", "char2")])
    }

    @Test func newProjectOpensWizardAtFirstGap() async {
        var p = Self.full()
        p.world?.setting = ""
        let (m, _, _, _) = await makeModel(p, name: "마법사-빈 세계")
        #expect(m.mode == .wizard)
        #expect(m.wizard?.step == 2)
        #expect(m.stepState(2) == .miss)
        #expect(m.stepState(5) == .none)
        m.pickWorldKind("서양풍 제국")
        #expect(m.project?.world?.setting == "귀족과 황실이 다스리는 서양풍 제국.")
        // 다 채워도 마법사는 닫히지 않는다
        #expect(m.mode == .wizard)
        #expect(m.stepState(2) == .done)
        m.pickEra("중세풍")
        m.pickEra("중세풍")
        #expect(m.project?.world?.era == "")
    }

    @Test func fullOrStartedProjectOpensDoc() async {
        let (full, _, _, _) = await makeModel(Self.full(), name: "마법사-다 채움")
        #expect(full.mode == .doc)
        var started = Project(meta: Meta(title: "등대", genres: ["mystery"]))
        started.snapshots = [.init(episode: 1)]
        let (m, _, _, _) = await makeModel(started, name: "마법사-반영 시작")
        #expect(m.mode == .doc)
        m.setMode(.wizard)
        #expect(m.mode == .wizard)
        #expect(m.wizard?.step == 1)
        #expect(m.wizard?.seen == [1])
    }

    @Test func forwardSavesAndBackDoesNot() async {
        let (m, store, _, _) = await makeModel(Project(), name: "마법사-걸음")
        #expect(m.wizard?.step == 0)
        m.editMeta { $0.title = "등대" }
        await m.go(step: 1)
        #expect(store.project.meta?.title == "등대")
        #expect(m.document.dirty == false)
        m.editMeta { $0.title = "등대지기" }
        await m.go(step: 0)
        #expect(m.document.dirty)
        #expect(m.wizard?.seen == [0, 1])
        await m.go(step: 9)
        #expect(m.wizard?.step == 0)
    }

    @Test func modeSurvivesReopening() async {
        let (m, store, _, _) = await makeModel(Project(), name: "마법사-다시 열기")
        m.setMode(.doc)
        let again = SetupModel(document: ProjectDocument(name: "마법사-다시 열기", store: store), jobs: m.jobs, service: FakeSetup(store))
        await again.load()
        #expect(again.mode == .doc)
    }
}
