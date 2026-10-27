import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureLines
import Foundation
import Testing

typealias Ep = Components.Schemas.Episode

func ep(_ n: Int, _ line: String = "", _ threads: [String] = [], _ status: Ep.StatusPayload = .draft, text: String? = nil) -> Ep {
    Ep(plot: .init(number: n, act: .기, title: "\(n)화", summary: "", events: [], characters: [], emotionalShift: "", endingHook: "",
                   storyline: line, threads: threads),
       status: status, text: text)
}

/// 웹 시험(node 로 `lines.js` 를 돌린 값)과 같은 작품.
func sample() -> Project {
    Project(meta: .init(targetEpisodes: 12),
            characters: [.init(id: "c1", name: "서연", role: "주인공"), .init(id: "c2", name: "", role: "조연")],
            episodes: [ep(1), ep(2, "", ["sl-02"], .finalized), ep(4, "sl-01", [], .written), ep(5, "", ["sl-01", "sl-02"], .confirmed),
                       ep(7, "sl-01"), ep(8, "sl-02", ["sl-01"])],
            storylines: [
                Storyline(id: "sl-01", kind: .과거회상, title: "떠난 밤", focus: ["c1", "zz"], when: "10년 전", branchEp: 3, joinEp: 6),
                Storyline(id: "sl-02", kind: .서브플롯, title: "", focus: [], when: "", branchEp: 0, joinEp: 0),
                Storyline(id: "sl-03", kind: .외전, title: "등대", focus: [], when: "", branchEp: 9, joinEp: 4),
            ])
}

// MARK: 웹 · 서버와 같은 규칙

@Suite struct RuleTests {
    @Test func episodesAndSpanMatchWeb() {
        let p = sample()
        let lines = LineRules.lines(p)
        #expect(lines.map { LineRules.span(p, $0).lo } == [3, 2, 9])
        #expect(lines.map { LineRules.span(p, $0).hi } == [8, 8, 4])
        let eps = LineRules.episodes(p, "sl-01")
        #expect(eps.map(\.n) == [4, 5, 7, 8])
        #expect(eps.map(\.role) == [.main, .thread, .main, .thread])
        #expect(LineRules.episodes(p, "sl-02").map(\.n) == [2, 5, 8])
        #expect(LineRules.episodes(p, "sl-03").isEmpty)
        #expect(lines.map(LineRules.isPast) == [true, false, false])
        #expect(LineRules.newID(p) == "sl-04")
    }

    /// 서버 `tests/test_storylines.py` 의 `test_suggest_cleans_and_apply_tags`: 4화 따라감, 5화 장면, 합류 6화 → (4, 6).
    @Test func spanMatchesServer() {
        let p = Project(meta: .init(targetEpisodes: 12), episodes: [ep(4, "sl-01"), ep(5, "", ["sl-01"])],
                        storylines: [Storyline(id: "sl-01", kind: .과거회상, title: "회상", joinEp: 6)])
        let s = LineRules.lines(p)[0]
        #expect(LineRules.span(p, s) == (4, 6))
        #expect(LineRules.span(p, Storyline(id: "none")) == (0, 0))
    }

    @Test func newIDSkipsTaken() {
        let p = Project(storylines: [Storyline(id: "sl-02"), Storyline(id: "sl-03")])
        #expect(LineRules.newID(p) == "sl-04")
        #expect(LineRules.newID(Project()) == "sl-01")
    }

    @Test func tagMatchesWeb() {
        var plot = ep(1, "", ["sl-01"]).plot
        LineRules.tag(&plot, "sl-01", .main)
        #expect(plot.storyline == "sl-01" && plot.threads == [])
        LineRules.tag(&plot, "sl-02", .thread)
        LineRules.tag(&plot, "sl-02", .thread)
        LineRules.tag(&plot, "sl-01", .thread)  // 따라가는 줄기는 장면으로 겹치지 않는다
        #expect(plot.storyline == "sl-01" && plot.threads == ["sl-02"])
        LineRules.tag(&plot, "", .main)  // 메인으로 되돌린다
        #expect(plot.storyline == "" && plot.threads == ["sl-02"])
        LineRules.untag(&plot, "sl-02")
        #expect(plot.threads == [])
    }

    @Test func plotEditorField() {
        var plot = ep(1, "", ["sl-01", "sl-02"]).plot
        LineRules.setMain(&plot, "sl-01")
        #expect(plot.storyline == "sl-01" && plot.threads == ["sl-02"])
        LineRules.setThread(&plot, "sl-03", true)
        LineRules.setThread(&plot, "sl-03", true)
        #expect(plot.threads == ["sl-02", "sl-03"])
        LineRules.setThread(&plot, "sl-02", false)
        #expect(plot.threads == ["sl-03"])
        let p = sample()
        #expect(LineRules.fieldOptions(p).map(\.label) == ["메인 줄기", "과거 회상 · 떠난 밤", "서브플롯 · sl-02", "외전 · 등대"])
        #expect(LineRules.sceneOptions(p, plot).map(\.id) == ["sl-02", "sl-03"])
        #expect(LineRules.fieldHint(written: true) == "본문이 있는 화도 줄기 표시는 바꿀 수 있어요. 본문은 그대로예요")
    }

    @Test func parseEpisodesLikeParseInt() {
        #expect(LineRules.parseEpisodes("7, 8 7 0 -3 9화,,12") == [7, 8, 9, 12])
        #expect(LineRules.parseEpisodes("") == [])
    }

    /// 웹 `lineBadge`: 5화는 두 줄기 장면, 8화는 서브플롯을 따라가고 떠난 밤 장면.
    @Test func badgesMatchWeb() {
        let p = sample()
        let b5 = LineRules.badges(p, p.episodes![3].plot)
        #expect(b5 == [.init(id: "sl-01", text: "장면 · 떠난 밤", color: "#B4570A", scene: true),
                       .init(id: "sl-02", text: "장면 · 서브플롯", color: "#7A3FB0", scene: true)])
        let b8 = LineRules.badges(p, p.episodes![5].plot)
        #expect(b8.map(\.text) == ["서브플롯", "장면 · 떠난 밤"])
        #expect(b8.map(\.scene) == [false, true])
        #expect(LineRules.badges(p, ep(3, "sl-99").plot).isEmpty)  // 없는 줄기는 뺀다
    }

    @Test func rangeNotesMatchWeb() {
        let p = sample()
        let lines = LineRules.lines(p)
        #expect(LineRules.rangeNotes(p, lines[0]) == ["갈라지는 화 앞이나 합류하는 화 뒤에 붙은 화가 있어요: 7~8화"])
        #expect(LineRules.rangeNotes(p, lines[1]).isEmpty)
        #expect(LineRules.rangeNotes(p, lines[2]) == ["갈라지는 화(9화)가 합류하는 화(4화)보다 뒤예요"])
        let late = Storyline(id: "x", branchEp: 13, joinEp: 14)
        #expect(LineRules.rangeNotes(p, late) == ["갈라지는 화 · 합류하는 화가 총 화수(12화)보다 뒤예요"])
    }

    @Test func listText() {
        let p = sample()
        let lines = LineRules.lines(p)
        #expect(LineRules.rangeLabel(p, lines[0]) == "갈라짐 3화 · 합류 6화")
        #expect(LineRules.rangeLabel(p, lines[1]) == "2~8화")
        #expect(LineRules.rangeLabel(p, Storyline(id: "none")) == "")
        #expect(LineRules.listDetail(p, lines[0]) == "서연, zz · 10년 전 · 붙은 화 4개")
        #expect(LineRules.listDetail(p, lines[2]) == "중심 인물 없음 · 붙은 화 없음")
        #expect(LineRules.deleteQuestion(lines[1]) == "'이름 없음' 줄기를 지울까요? 붙은 화는 메인으로 돌아가고, 플롯과 본문은 그대로예요.")
    }

    /// 웹 `lineMap` 의 자리 (칸 폭 1000): 단계 폭, 크기, 줄 모양.
    @Test func layoutMatchesWeb() {
        let p = sample()
        let m = LineMapLayout(p, wrapWidth: 1000)
        #expect(m.total == 12 && m.left == 168 && m.step == 30)
        #expect(m.width == 552 && m.height == 284 && m.radius == 7)
        #expect(m.ticks == Array(1...12))
        // "M 243 64 C 243 122 243 122 265 122 L 311 122 C 333 122 333 122 333 64"
        #expect(m.lanes[0].path == [.move(.init(x: 243, y: 64)), .curve(.init(x: 243, y: 122), .init(x: 243, y: 122), .init(x: 265, y: 122)),
                                    .line(.init(x: 311, y: 122)), .curve(.init(x: 333, y: 122), .init(x: 333, y: 122), .init(x: 333, y: 64))])
        // "M 213 180 L 411 180"
        #expect(m.lanes[1].path == [.move(.init(x: 213, y: 180)), .line(.init(x: 411, y: 180))])
        #expect(m.lanes[1].openX == 417)
        // 붙은 화가 없어도 갈라짐 · 합류 화가 있으면 줄을 그린다: "M 423 64 C 423 238 423 238 445 238 L 423 238 C 273 238 273 238 273 64"
        #expect(m.lanes[2].path == [.move(.init(x: 423, y: 64)), .curve(.init(x: 423, y: 238), .init(x: 423, y: 238), .init(x: 445, y: 238)),
                                    .line(.init(x: 423, y: 238)), .curve(.init(x: 273, y: 238), .init(x: 273, y: 238), .init(x: 273, y: 64))])
        #expect(m.lanes[0].nodes == [243, 333])
        #expect(m.mainDots.map(\.n) == [1, 2, 4, 5, 7, 8])
        #expect(m.mainDots.map(\.gap) == [false, false, true, false, true, true])
        #expect(m.mainDots[2].label == "4화 4화 · 떠난 밤 줄기를 따라감 · 본문 작성됨")
        #expect(m.lanes[0].dots[1].label == "5화 5화 · 떠난 밤 (장면) · 플롯 확정")
        #expect(m.mainSolid! == (183, 393) && m.mainFuture! == (393, 513))
    }

    @Test func layoutNarrowAndZoom() {
        let p = sample()
        let narrow = LineMapLayout(p, wrapWidth: 400)
        #expect(narrow.left == 96 && narrow.step == (400 - 96 - 24) / 12.0)
        #expect(LineMapLayout(p, wrapWidth: 400, zoom: .narrow).ticks == [1, 10])
        #expect(LineMapLayout(p, wrapWidth: 400, zoom: .normal).ticks == [1, 5, 10])
        // 너무 좁으면 한 화 4pt 아래로 줄이지 않는다
        #expect(LineMapLayout(Project(meta: .init(targetEpisodes: 300)), wrapWidth: 400).step == 4)
    }

    @Test func hitFindsDotsAndLanes() {
        let m = LineMapLayout(sample(), wrapWidth: 1000)
        #expect(m.hit(50, 122) == .line("sl-01"))
        #expect(m.hit(280, 125) == .episode(4))   // 4화: x 273, 줄기 줄 y 122
        #expect(m.hit(210, 60) == .episode(2))    // 메인 2화: x 213
        #expect(m.hit(273, 64) == nil)            // 줄기를 따라가 메인에서 비운 자리
        #expect(m.hit(600, 300) == nil)
    }

    @Test func bands() {
        var p = sample()
        p.arc = [.init(name: .기, startEp: 1, endEp: 3, goal: ""), .init(name: .승, startEp: 4, endEp: 12, goal: "")]
        let m = LineMapLayout(p, wrapWidth: 1000)
        #expect(m.bands.map(\.label) == ["기", "승"])
        #expect(m.bands.map(\.index) == [0, 1])
        #expect(m.bands[1].x == 258 && m.bands[1].width == 268)
        p.storyArcs = [.init(number: 2, title: "둘", startEp: 1, endEp: 12, goal: "")]
        #expect(LineMapLayout(p, wrapWidth: 1000, serial: true).bands.map(\.label) == ["아크 2 둘"])
    }
}

// MARK: 화면 동작

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project
    var saved = 0
    init(_ p: Project) { project = p }
    func load(_ name: String) async throws -> Project { project }
    func save(_ name: String, _ project: Project, merged: [String], force: Bool) async throws -> SaveResult {
        saved += 1
        self.project = project
        return SaveResult(project: project, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var list: [Job] = []
    var pendingList = PendingList()
    var started: [JobRequest] = []
    var dropped: [String] = []
    func listJobs() async throws -> [Job] { list }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        let j = Job(id: "j\(started.count)", project: project, kind: request.kind, ep: request.ep, label: "이야기 줄기 제안")
        list.append(j)
        return (j, false)
    }
    func stopJob(_ id: String) async throws -> Job { list.first { $0.id == id }! }
    func pending(_ project: String) async throws -> PendingList { pendingList }
    func dropPending(_ project: String, key: String, failure: Bool) async throws { dropped.append(key) }
}

/// 서버 대신: 더하면 줄기를 넣고 고른 화에 붙이고, 지우면 붙은 화를 메인으로 돌린다 (`pipeline.apply_storyline` · `remove_storyline`).
final class FakeLines: LinesService, @unchecked Sendable {
    let store: FakeStore
    var calls: [String] = []
    init(_ store: FakeStore) { self.store = store }
    func apply(_ proposal: StorylineProposal, episodes: [Int], threads: [Int]) async throws {
        calls.append("apply \(proposal.storyline.title ?? "") \(episodes) \(threads)")
        store.project.storylines = (store.project.storylines ?? []) + [proposal.storyline]
        for i in store.project.episodes!.indices {
            let n = store.project.episodes![i].plot.number
            if episodes.contains(n) { LineRules.tag(&store.project.episodes![i].plot, proposal.storyline.id, .main) }
            if threads.contains(n) { LineRules.tag(&store.project.episodes![i].plot, proposal.storyline.id, .thread) }
        }
    }
    func remove(_ id: String) async throws {
        calls.append("remove \(id)")
        store.project.storylines = store.project.storylines?.filter { $0.id != id }
        for i in store.project.episodes!.indices { LineRules.untag(&store.project.episodes![i].plot, id) }
    }
}

@MainActor
func makeModel(_ p: Project, pending: PendingList = PendingList()) async -> (LinesModel, FakeStore, FakeJobs, FakeLines) {
    let store = FakeStore(p)
    let doc = ProjectDocument(name: "등대", store: store)
    await doc.load()
    let jobs = FakeJobs()
    jobs.pendingList = pending
    let center = JobCenter(service: jobs)
    await center.open(doc)
    let lines = FakeLines(store)
    return (LinesModel(document: doc, jobs: center, service: lines), store, jobs, lines)
}

func result(_ value: some Encodable, id: String = "r1") throws -> PendingResult {
    let json = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
    return PendingResult(key: "storyline:", id: id, kind: "storyline", ep: nil, label: "이야기 줄기 제안", result: json, base: nil)
}

@MainActor
@Suite struct ModelTests {
    @Test func selectsFirstAndAddsLine() async {
        let (m, store, _, _) = await makeModel(sample())
        #expect(m.selected?.id == "sl-01")
        m.newLine()
        #expect(m.selected?.id == "sl-04" && m.selected?.kind == .서브플롯)
        m.edit { $0.title = "빚" }
        m.toggleFocus("c1")
        #expect(m.selected?.title == "빚" && m.selected?.focus == ["c1"])
        #expect(m.document.dirty)
        await m.document.save()
        #expect(store.project.storylines?.last?.title == "빚")
    }

    @Test func tagChecksEpisodes() async {
        let (m, _, _, _) = await makeModel(sample())
        m.select("sl-03")
        m.tag(.main)
        #expect(m.notice?.text == "붙일 화 번호를 적으세요")
        m.tagText = "1, 3"
        m.tag(.main)
        #expect(m.notice?.text == "플롯이 없는 화예요: 3화")
        #expect(!m.document.dirty)
        m.tagText = "1 2"
        m.tag(.thread)
        #expect(LineRules.episodes(m.project!, "sl-03").map(\.n) == [1, 2])
        #expect(m.tagText.isEmpty && m.document.dirty)
        m.untag(2)
        #expect(LineRules.episodes(m.project!, "sl-03").map(\.n) == [1])
    }

    @Test func deleteAsksSavesThenRemoves() async {
        let (m, store, _, lines) = await makeModel(sample())
        m.edit { $0.goal = "고침" }
        m.delete()
        #expect(m.ask?.message == "'떠난 밤' 줄기를 지울까요? 붙은 화는 메인으로 돌아가고, 플롯과 본문은 그대로예요.")
        await m.ask?.run()
        #expect(store.saved == 1)  // 저장하지 않은 변경을 먼저 저장한다
        #expect(lines.calls == ["remove sl-01"])
        #expect(m.project?.storylines?.map(\.id) == ["sl-02", "sl-03"])
        #expect(m.project?.episodes?[2].plot.storyline == "")
        #expect(m.selected?.id == "sl-02")
    }

    @Test func suggestionIsAppliedWithPickedEpisodes() async throws {
        let prop = StorylineProposal(storyline: Storyline(id: "sl-04", kind: .외전, title: "등대지기"), episodes: [1, 7], threads: [2], reply: "이유")
        let (m, _, jobs, lines) = await makeModel(sample(), pending: PendingList(results: ["storyline:": try result(prop)]))
        m.syncResults()
        #expect(m.draft?.proposal.reply == "이유")
        #expect(m.draft?.episodes == [1, 7] && m.draft?.threads == [2])
        m.draft?.pick(.main, 7, false)
        m.editDraft { $0.title = "" }
        await m.applyDraft()
        #expect(m.notice?.text == "줄기 이름을 적으세요")
        #expect(lines.calls.isEmpty)
        m.editDraft { $0.title = "등대지기의 겨울" }
        await m.applyDraft()
        #expect(lines.calls == ["apply 등대지기의 겨울 [1] [2]"])
        #expect(jobs.dropped == ["storyline:"])
        #expect(m.draft == nil && m.selected?.id == "sl-04")
        #expect(m.notice?.text == "줄기를 더했어요. 기승전결 · 플롯 화면에서 그 화들을 다듬으세요.")
        m.syncResults()
        #expect(m.draft == nil)  // 받은 결과를 다시 받지 않는다
    }

    @Test func dropAsksFirst() async throws {
        let prop = StorylineProposal(storyline: Storyline(id: "sl-04", title: "x"))
        let (m, _, jobs, _) = await makeModel(sample(), pending: PendingList(results: ["storyline:": try result(prop)]))
        m.syncResults()
        m.dropDraft()
        #expect(m.ask?.message == "AI 이야기 줄기 제안을 버릴까요? 되살릴 수 없어서, 다시 보려면 AI에게 다시 받아야 해요.")
        await m.ask?.run()
        #expect(m.draft == nil && jobs.dropped == ["storyline:"])
    }

    @Test func suggestSendsNoteAndKind() async {
        let (m, _, jobs, _) = await makeModel(sample())
        m.note = " 7화쯤 과거 "
        m.aiKind = .과거회상
        await m.suggest()
        #expect(jobs.started.count == 1)
        #expect(jobs.started[0].kind == "storyline" && jobs.started[0].note == "7화쯤 과거" && jobs.started[0].lineKind == "과거 회상")
        m.edit { $0.goal = "고침" }
        await m.suggest()
        #expect(m.ask?.message == "저장하지 않은 변경이 있어요. 저장하고 작업을 시작할까요?")
    }
}
