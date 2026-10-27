import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureCausal
import Foundation
import Testing

func decode<T: Decodable>(_ type: T.Type, _ json: String) -> T {
    try! JSONDecoder().decode(T.self, from: Data(json.utf8))
}

func plot(_ n: Int, _ title: String = "") -> String {
    #"{"number":\#(n),"act":"기","title":"\#(title.isEmpty ? "\(n)화 제목" : title)","summary":"","events":[],"characters":[],"emotional_shift":"","ending_hook":""}"#
}

/// 도현 · 서윤, 1화 반영 끝 · 2화 본문 있음 · 3화 확정 · 4화 초안. 요소 둘: 분석한 '등대 열쇠'와 분석 전 '통금'.
let report = #"""
{"summary":"2화 본문과 3화 플롯이 흔들려요.",
 "conflicts":[{"target":"본문","episode":2,"quote":"열쇠는 없었다","problem":"열쇠가 이미 있다","fix":"본문 수정"},
              {"target":"설정","episode":0,"quote":"등대","problem":"설정과 다르다","fix":"시점 변경"}],
 "episodes":[\#(plot(3, "새 3화")),\#(plot(4, "새 4화")),\#(plot(2, "새 2화"))],
 "patches":[{"episode":2,"quote":"열쇠는 없었다","replacement":"열쇠가 있었다"},{"episode":1,"quote":"문","replacement":"문 열쇠"}],
 "new_facts":["열쇠는 하나뿐이다"]}
"""#

let keyBasis = #"["물건","등대 열쇠",["열쇠"],"녹슨 열쇠",["dh"],0,[3],0]"#

let sampleJSON = #"""
{"meta":{"target_episodes":6},
 "characters":[{"id":"dh","name":"도현","role":"주인공"},{"id":"sy","name":"서윤","role":"조연"}],
 "elements":[{"id":"el-01","kind":"물건","name":"등대 열쇠","aliases":["열쇠"],"description":"녹슨 열쇠","characters":["dh"],"episodes":[3],
              "added_after":2,"impact":{"report":\#(report),"basis":\#(String(data: try! JSONEncoder().encode(keyBasis), encoding: .utf8)!),"at":"2026-10-26T01:00:00+00:00"}},
             {"id":"el-02","kind":"세계 규칙","name":"통금","description":"밤에는 못 나간다","since_ep":5,"added_after":2}],
 "episodes":[{"plot":\#(plot(1)),"status":"finalized","text":"1화 본문"},
             {"plot":\#(plot(2)),"status":"written","text":"2화 본문"},
             {"plot":\#(plot(3)),"status":"confirmed"},
             {"plot":\#(plot(4)),"status":"draft"}]}
"""#

let sample = decode(Project.self, sampleJSON)

func element(_ json: String) -> StoryElement { decode(StoryElement.self, json) }

@Suite struct CausalTextTests {
    /// 웹 `elBasis` · 서버 `elements.basis` 와 같은 글. 기대값은 node(JSON.stringify)와 python(json.dumps)으로 돌린 결과다.
    @Test func basisMatchesWebAndServer() {
        let a = element(#"{"id":"a","kind":"과거 사건","name":"등대지기 실종","aliases":["실종 사건"],"description":"10년 전 겨울, 등대지기가 실종됐다","characters":["dh"],"since_ep":0,"episodes":[],"reveal_ep":7}"#)
        #expect(CausalText.basis(a) == #"["과거 사건","등대지기 실종",["실종 사건"],"10년 전 겨울, 등대지기가 실종됐다",["dh"],0,[],7]"#)
        let b = element(#"{"id":"b","kind":"세계 규칙","name":"통금 \"밤\"","aliases":[],"description":"줄1\n줄2\t탭 / 슬래시 \\ 역슬래시 \u0001 조종 😀","characters":[],"since_ep":7,"episodes":[7,12],"reveal_ep":0}"#)
        #expect(CausalText.basis(b) == #"["세계 규칙","통금 \"밤\"",[],"줄1\n줄2\t탭 / 슬래시 \\ 역슬래시 \u0001 조종 😀",[],7,[7,12],0]"#)
        // 서버가 채우는 기본값과 같다
        #expect(CausalText.basis(element(#"{"id":"c"}"#)) == #"["기타","",[],"",[],0,[],0]"#)
    }

    /// 분석한 뒤 고치면 지난 분석이다. basis 가 비어 있으면 지난 것으로 보지 않는다 (웹 `causalStale`).
    @Test func stale() {
        var el = sample.elements![0]
        #expect(!CausalText.stale(el))
        el.description = "새 설명"
        #expect(CausalText.stale(el))
        el.impact?.basis = ""
        #expect(!CausalText.stale(el))
        #expect(CausalText.badge(sample.elements![0]) == .init(text: "영향 4개 화", tone: .warn))
        var edited = sample.elements![0]
        edited.name = "열쇠꾸러미"
        #expect(CausalText.badge(edited) == .init(text: "다시 분석 필요", tone: .warn))
    }

    /// 웹 `impactBadge` 의 갈래.
    @Test func badges() {
        #expect(CausalText.badge(sample.elements![1]) == .init(text: "분석 전", tone: .warn))
        #expect(CausalText.badge(element(#"{"id":"x"}"#)) == nil)
        #expect(CausalText.badge(element(#"{"id":"x","found_in":"본문","found_ep":3}"#)) == .init(text: "3화 본문에서", tone: .plain))
        let none = element(#"{"id":"x","impact":{"report":{"summary":"없음"}}}"#)
        #expect(CausalText.badge(none) == .init(text: "영향 없음", tone: .done))
        let facts = element(#"{"id":"x","impact":{"report":{"summary":"","new_facts":["a"]}}}"#)
        #expect(CausalText.badge(facts) == .init(text: "검토할 것 있음", tone: .warn))
        let applied = element(#"{"id":"x","impact":{"report":{"summary":""},"outcome":"applied"}}"#)
        #expect(CausalText.badge(applied) == .init(text: "적용함", tone: .done))
        let dismissed = element(#"{"id":"x","impact":{"report":{"summary":""},"outcome":"dismissed"}}"#)
        #expect(CausalText.badge(dismissed) == .init(text: "분석 봄", tone: .plain))
    }

    @Test func timingAndIDs() {
        #expect(CausalText.timing(sample.elements![0]) == "처음부터 · 나올 화 3")
        #expect(CausalText.timing(element(#"{"id":"x","since_ep":5,"reveal_ep":9,"found_in":"플롯","found_ep":4}"#)) == "5화부터 · 9화 공개 · 4화 플롯에 처음 나옴")
        #expect(CausalText.newID(sample.elements!) == "el-03")
        #expect(CausalText.newID([element(#"{"id":"el-02"}"#)]) == "el-03")
        #expect(CausalText.parseEpisodes("12, 7 7화 0 -3 x") == [7, 12])
        #expect(CausalText.lastWritten(sample) == 2)
        #expect(CausalText.since(start: false, sample.elements![0], lastWritten: 2) == 3)
        #expect(CausalText.since(start: false, sample.elements![1], lastWritten: 2) == 5)
        #expect(CausalText.since(start: true, sample.elements![1], lastWritten: 2) == 0)
    }

    /// 웹 `initCausalPicks`: 플롯은 초안 · 없는 화만, 본문 고침은 반영이 끝나지 않은 화만, 사실은 모두.
    @Test func picksAndApplyBody() {
        let el = sample.elements![0]
        let picks = CausalText.defaultPicks(el, project: sample)
        let id = { (part: String) in "el-01:2026-10-26T01:00:00+00:00:\(part)" }
        #expect(picks == [id("ep:3"): false, id("ep:4"): true, id("ep:2"): false, id("patch:0"): true, id("patch:1"): false, id("fact:0"): true])
        // 막힌 화(본문이 생긴 2화)는 골라도 보내지 않는다
        var all = picks
        all[id("ep:2")] = true
        all[id("ep:3")] = true
        let body = CausalText.picked(el, picks: all, project: sample)
        #expect(body.episodes == [3, 4])
        #expect(body.patches == [0])
        #expect(body.facts == [0])
        #expect(CausalText.isEmpty(CausalText.picked(el, picks: [:], project: sample)))
    }

    @Test func appliedLabels() {
        let r = sample.elements![0].impact!.report
        #expect(CausalText.appliedLabel("ep:3", r) == "3화 플롯")
        #expect(CausalText.appliedLabel("patch:1", r) == "1화 본문 수정")
        #expect(CausalText.appliedLabel("patch:9", r) == "본문 수정 10")
        #expect(CausalText.appliedLabel("fact:0", r) == "사실 1")
        #expect(CausalText.appliedLabel("weird", r) == "weird")
    }

    /// 웹 `causalStrip`: 모순 > 고침 > 반영함 > 언급 · 예정 · 인물. 반영한 화는 모순 · 고침에서 뺀다.
    @Test func strip() {
        let links = [decode(ElementLink.self, #"{"episode":1,"status":"finalized","where":["본문"],"terms":["열쇠"],"characters":[],"planned":false,"snippet":"…열쇠…"}"#),
                     decode(ElementLink.self, #"{"episode":5,"status":"draft","where":[],"terms":[],"characters":["dh"],"planned":false,"snippet":""}"#),
                     decode(ElementLink.self, #"{"episode":6,"status":"draft","where":[],"terms":[],"characters":[],"planned":true,"snippet":""}"#)]
        let cells = CausalText.strip(sample.elements![0], links: links, project: sample, names: ["dh": "도현"])
        #expect(cells.count == 6)
        #expect(cells.map(\.kind) == [.plot, .bad, .plot, .plot, .weak, .rel])
        #expect(cells.map(\.tag) == ["고침", "모순", "고침", "고침", "인물", "예정"])
        #expect(cells[0].title == "1화 · 반영 완료 · 언급: 열쇠")
        #expect(cells[4].title == "5화 · 플롯 없음 · 인물: 도현")
        #expect(cells[1].hasText && !cells[2].hasText)

        var applied = sample.elements![0]
        applied.impact?.outcome = .applied
        applied.impact?.applied = ["ep:3", "patch:0"]
        let after = CausalText.strip(applied, links: links, project: sample, names: [:])
        #expect(after.map(\.kind) == [.plot, .done, .done, .plot, .weak, .rel])
        #expect(after[1].tag == "반영함")

        var dismissed = sample.elements![0]
        dismissed.impact?.outcome = .dismissed
        #expect(CausalText.strip(dismissed, links: links, project: sample, names: [:]).map(\.kind) == [.rel, .none, .none, .none, .weak, .rel])

        let late = CausalText.strip(sample.elements![1], links: [], project: sample, names: [:])
        #expect(late[4].since && late[3].before && !late[4].before)
        #expect(CausalText.snippets(links).map(\.head) == ["1화 본문"])
    }

    /// 웹 `plotDiff` · `diffField`: 다른 칸만, 목록은 빠진 것과 더한 것, 사건 순서는 통째로.
    @Test func plotDiff() {
        let cur = decode(EpisodePlot.self, #"{"number":3,"act":"기","title":"옛","summary":"같음","events":["a"],"characters":["dh"],"emotional_shift":"","ending_hook":""}"#)
        let new = decode(EpisodePlot.self, #"{"number":3,"act":"기","title":"새","summary":"같음","events":["a","b"],"characters":["sy"],"emotional_shift":"","ending_hook":"훅","opening":""}"#)
        let rows = CausalText.plotDiff(new, current: cur, names: ["sy": "서윤", "dh": "도현"])
        #expect(rows == [
            .init(label: "제목", removed: ["옛"], added: ["새"], ordered: false),
            .init(label: "사건 순서", removed: ["a"], added: ["a", "b"], ordered: true),
            .init(label: "등장 인물", removed: ["도현"], added: ["서윤"], ordered: false),
            .init(label: "엔딩 훅", removed: [], added: ["훅"], ordered: false),
        ])
        #expect(CausalText.plotDiff(cur, current: cur).isEmpty)
        #expect(CausalText.plotDiff(new, current: nil).map(\.label) == ["제목", "요약", "사건 순서", "등장 인물", "엔딩 훅"])
    }

    @Test func questions() {
        let el = sample.elements![0]
        #expect(CausalText.deleteQuestion(el, dirty: true) == "'등대 열쇠' 요소를 지울까요? 이미 반영한 플롯과 본문은 그대로예요. 저장하지 않은 다른 변경도 함께 저장해요. 지운 뒤 이 화면에서 바로 되살릴 수 있어요.")
        #expect(CausalText.label(element(#"{"id":"x"}"#)) == "이름 없음")
        #expect(CausalText.why(lastWritten: 2).hasPrefix("2화까지 쓴 작품이에요."))
        #expect(CausalText.foundNote(element(#"{"id":"x","found_in":"본문","found_ep":3}"#)) == "3화 본문에 처음 나와 상태 승인 때 등록한 장소예요. 이름이나 설명을 고쳐도 돼요. 3화부터 반영을 취소하면 빠져요 (시점이나 관련 인물을 더했으면 남아요).")
        #expect(CausalText.plotNote(sample.episodes![2], open: true)?.warn == true)
        #expect(CausalText.plotNote(sample.episodes![1], open: true)?.text == "본문이 생겨서 이제는 바꿀 수 없어요.")
        #expect(CausalText.suggestsTiming(el.impact!.report))
        #expect(CausalText.emptyExample(sample).hasPrefix("예: \"악역은(는) 도현의 친아버지다\""))
    }
}

// MARK: - 모델

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project
    var saved = 0
    init(_ p: Project) { project = p }
    func load(_ name: String) async throws -> Project { project }
    func save(_ name: String, _ p: Project, merged: [String], force: Bool) async throws -> SaveResult {
        saved += 1
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var started: [JobRequest] = []
    var list: [Job] = []
    func listJobs() async throws -> [Job] { list }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        return (Job(id: "j", project: project, kind: request.kind, label: "인과율: 영향 분석"), false)
    }
    func stopJob(_ id: String) async throws -> Job { Job(id: id, project: "", kind: "", label: "") }
    func pending(_ project: String) async throws -> PendingList { PendingList() }
    func dropPending(_ project: String, key: String, failure: Bool) async throws {}
}

final class FakeCausal: CausalService, @unchecked Sendable {
    let store: FakeStore
    var sent: [Components.Schemas.ImpactApply] = []
    var dismissed: [String] = []
    init(_ store: FakeStore) { self.store = store }
    func links(_ project: String) async throws -> [String: [ElementLink]] { [:] }
    func apply(_ project: String, element: String, _ body: Components.Schemas.ImpactApply) async throws -> Project {
        sent.append(body)
        let i = store.project.elements!.firstIndex { $0.id == element }!
        store.project.elements![i].impact?.outcome = .applied
        store.project.elements![i].impact?.applied = (body.episodes ?? []).map { "ep:\($0)" } + (body.facts ?? []).map { "fact:\($0)" }
        return store.project
    }
    func dismiss(_ project: String, element: String) async throws -> Project {
        dismissed.append(element)
        return store.project
    }
    func reopen(_ project: String, element: String) async throws -> Project { store.project }
    func load(_ project: String) async throws -> Project { store.project }
}

@MainActor
func makeModel(_ p: Project = sample) async -> (CausalModel, FakeStore, FakeJobs, FakeCausal) {
    let store = FakeStore(p)
    let doc = ProjectDocument(name: "책", store: store)
    await doc.load()
    let fj = FakeJobs()
    let jobs = JobCenter(service: fj)
    await jobs.open(doc)
    let fc = FakeCausal(store)
    let m = CausalModel(document: doc, jobs: jobs, service: fc)
    await m.start()
    return (m, store, fj, fc)
}

@MainActor
@Suite struct CausalModelTests {
    @Test func addSelectsAndMarksDirty() async {
        let (m, _, _, _) = await makeModel()
        #expect(m.selected == "el-01")
        m.kindFilter = .세계규칙
        m.add()
        #expect(m.selected == "el-03")
        #expect(m.element?.kind == .세계규칙)
        #expect(m.document.dirty)
        #expect(m.shown.map(\.id) == ["el-02", "el-03"])
        #expect(m.filterKinds == [.세계규칙, .물건])
    }

    /// 이름 · 설명이 없으면 분석을 시작하지 않는다. 시작하면 요소 id 를 보낸다.
    @Test func analyze() async {
        let (m, _, fj, _) = await makeModel()
        m.add()
        await m.analyze()
        #expect(fj.started.isEmpty)
        #expect(m.notice?.text == "이름과 설명을 먼저 적으세요")
        m.select("el-02")
        await m.analyze()
        #expect(fj.started.map(\.element) == ["el-02"])
        #expect(fj.started.first?.kind == "impact")
    }

    /// 웹 `mergeImpacts`: 저장하지 않은 요소 편집은 두고 분석만 받아 온다.
    @Test func mergeKeepsEdits() async {
        let (m, store, _, _) = await makeModel()
        m.select("el-02")
        m.edit { $0.name = "야간 통금" }
        store.project.elements![1].impact = decode(ElementImpact.self, #"{"report":{"summary":"새 분석"},"at":"2026-10-26T02:00:00+00:00"}"#)
        await m.mergeImpacts()
        #expect(m.element?.name == "야간 통금")
        #expect(m.element?.impact?.report.summary == "새 분석")
        #expect(m.document.dirty)
    }

    /// 분석 작업이 새로 끝나면 받아 온다. 화면을 열 때 이미 끝나 있던 작업은 다시 받지 않는다.
    @Test func jobFinishMerges() async {
        let (m, store, fj, _) = await makeModel()
        fj.list = [Job(id: "a", project: "책", kind: "impact", label: "인과율: 통금 영향 분석")]
        await m.jobs.refresh()
        store.project.elements![1].impact = decode(ElementImpact.self, #"{"report":{"summary":"끝"}}"#)
        await m.jobsChanged()
        #expect(m.elements[1].impact == nil)
        fj.list[0].status = .done
        await m.jobs.refresh()
        await m.jobsChanged()
        #expect(m.elements[1].impact?.report.summary == "끝")
    }

    @Test func applyPicked() async {
        let (m, store, _, fc) = await makeModel()
        #expect(m.isPicked("ep:4") && !m.isPicked("ep:3"))
        m.setPicked("fact:0", false)
        m.setPicked("patch:0", false)
        await m.apply()
        #expect(fc.sent.first?.episodes == [4])
        #expect(fc.sent.first?.facts == [])
        #expect(m.element?.impact?.outcome == .applied)
        #expect(m.notice?.text == "적용했어요: 4화 플롯")
        // 아무것도 고르지 않으면 보내지 않는다
        store.project.elements![0].impact?.outcome = ._empty_
        await m.document.reload()
        for k in ["ep:4", "patch:0", "fact:0"] { m.setPicked(k, false) }
        await m.apply()
        #expect(fc.sent.count == 1)
        #expect(m.notice?.text == "적용할 부분을 고르세요")
    }

    /// 지우기는 바로 저장하고, 되살리면 다시 저장한다.
    @Test func deleteAndRestore() async {
        let (m, store, _, _) = await makeModel()
        await m.delete()
        #expect(store.saved == 1)
        #expect(store.project.elements?.map(\.id) == ["el-02"])
        #expect(m.gone?.id == "el-01")
        #expect(m.selected == "el-02")
        await m.restore()
        #expect(store.saved == 2)
        #expect(store.project.elements?.map(\.id) == ["el-02", "el-01"])
        #expect(m.selected == "el-01")
        #expect(m.notice?.text == "'등대 열쇠' 요소를 되살렸어요")
    }
}
