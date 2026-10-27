import CanonAPI
import CanonCore
import CanonStore
@testable import FeaturePlot
import Foundation
import Testing

typealias Ep = Components.Schemas.Episode

func ep(_ n: Int, _ status: Ep.StatusPayload = .draft, title: String? = nil, chars: [String] = [], payoff: [String] = [], text: String? = nil) -> Ep {
    Ep(plot: .init(number: n, act: .기, title: title ?? "\(n)화", summary: "", events: [], characters: chars, emotionalShift: "", endingHook: "",
                   foreshadowPayoff: payoff),
       status: status, text: text)
}

func act(_ name: Act.NamePayload, _ a: Int, _ b: Int) -> Act { Act(name: name, startEp: a, endEp: b, goal: "\(name.rawValue) 목표") }

func short(_ eps: [Ep], target: Int = 4) -> Project {
    Project(meta: .init(targetEpisodes: target), characters: [.init(id: "c1", name: "서연", role: "주인공")],
            arc: [act(.기, 1, 1), act(.승, 2, 2), act(.전, 3, 3), act(.결, 4, 4)], episodes: eps)
}

func serialProject() -> Project {
    let eps = (1...12).map { ep($0, $0 <= 10 ? .finalized : .draft) }
    return Project(meta: .init(targetEpisodes: 100, form: .serial),
                   parts: [.init(number: 1, title: "시작", startEp: 1, endEp: 10, goal: "", summary: "1부 요약"),
                           .init(number: 2, title: "전환", startEp: 11, endEp: 100, goal: "")],
                   storyArcs: [.init(number: 1, title: "첫", startEp: 1, endEp: 5, goal: "", acts: [act(.기, 1, 5)]),
                               .init(number: 2, title: "둘", startEp: 6, endEp: 10, goal: "", acts: [act(.기, 6, 10)], summary: "요약"),
                               .init(number: 3, title: "셋", startEp: 11, endEp: 14, goal: "", acts: [act(.기, 11, 11), act(.승, 12, 12), act(.전, 13, 13), act(.결, 14, 14)])],
                   episodes: eps)
}

// MARK: 웹과 같은 규칙

@Suite struct RuleTests {
    /// 서버 pipeline.act_ranges 결과와 같은 사례 (scripts 없이 python 으로 뽑은 값)
    @Test func actRangesMatchServer() {
        let r = { (t: Int, s: Int, w: [Double]?) in PlotRules.actRanges(total: t, start: s, weights: w)!.map { [$0.0, $0.1] } }
        #expect(r(12, 1, nil) == [[1, 2], [3, 7], [8, 10], [11, 12]])
        #expect(r(16, 1, nil) == [[1, 3], [4, 9], [10, 13], [14, 16]])
        #expect(r(4, 1, nil) == [[1, 1], [2, 2], [3, 3], [4, 4]])
        #expect(r(5, 1, nil) == [[1, 1], [2, 3], [4, 4], [5, 5]])
        #expect(r(2, 1, nil) == [[1, 1], [1, 1], [2, 2], [2, 2]])
        #expect(r(3, 1, nil) == [[1, 1], [2, 2], [3, 3], [3, 3]])
        #expect(r(30, 11, nil) == [[11, 14], [15, 22], [23, 27], [28, 30]])
        #expect(r(20, 11, [1, 1, 1, 1]) == [[11, 13], [14, 16], [17, 18], [19, 20]])
        #expect(r(14, 5, [2, 4, 3, 2]) == [[5, 6], [7, 9], [10, 12], [13, 14]])
        #expect(PlotRules.actRanges(total: 3, start: 5) == nil)
    }

    @Test func setArcEndMovesLastActOrRedistributes() {
        var a = StoryArc(number: 1, title: "", startEp: 11, endEp: 30, goal: "",
                         acts: [act(.기, 11, 14), act(.승, 15, 22), act(.전, 23, 27), act(.결, 28, 30)])
        PlotRules.setArcEnd(&a, 33)
        #expect(a.endEp == 33)
        #expect(a.acts?.map(\.endEp) == [14, 22, 27, 33])
        // 결이 시작 화보다 앞으로 오면 구간 길이(4, 8, 5, 6) 비율로 다시 나눈다
        PlotRules.setArcEnd(&a, 20)
        #expect(a.acts?.map { [$0.startEp, $0.endEp] } == PlotRules.actRanges(total: 20, start: 11, weights: [4, 8, 5, 6])!.map { [$0.0, $0.1] })
        // 시작 화보다 앞이면 구간은 그대로
        let before = a.acts
        PlotRules.setArcEnd(&a, 5)
        #expect(a.acts == before)
    }

    @Test func rangeText() {
        #expect(PlotRules.rangeText([1, 2, 3, 5, 7, 8]) == "1~3, 5, 7~8")
        #expect(PlotRules.rangeText([]) == "")
    }

    @Test func coverage() {
        #expect(PlotRules.coverage([act(.기, 1, 1), act(.승, 2, 2), act(.전, 3, 3), act(.결, 4, 4)], start: 1, end: 4).isEmpty)
        #expect(PlotRules.coverage([act(.기, 1, 2), act(.승, 2, 3), act(.전, 6, 6), act(.결, 7, 9)], start: 1, end: 8)
            == ["어느 구간에도 들지 않는 화: 4~5화", "두 구간에 겹친 화: 2화", "범위(1~8화) 밖: 9화"])
        // 4화보다 짧으면 겹쳐도 된다
        #expect(PlotRules.coverage([act(.기, 1, 1), act(.승, 1, 1), act(.전, 2, 2), act(.결, 2, 2)], start: 1, end: 2).isEmpty)
    }

    @Test func draftsAndWriteNext() {
        let eps = [ep(1, .confirmed), ep(2, .draft), ep(4, .draft)]
        #expect(PlotRules.needsDraft(eps, 1, 1) == false)
        #expect(PlotRules.needsDraft(eps, 3, 3))  // 없는 화
        #expect(PlotRules.redraftQuestion(eps) == "초안 2화(2, 4화)를 AI 새 초안으로 바꿔요. 손본 내용도 사라져요. 지키려면 먼저 그 화를 확정하세요. 계속할까요?")
        #expect(PlotRules.redraftQuestion([ep(1, .confirmed)]) == nil)
        #expect(PlotRules.writeNext(short(eps)) == 1)
        #expect(PlotRules.writeNext(short([ep(1, .finalized), ep(2, .draft)])) == nil)
    }

    @Test func board() {
        let b = PlotBoard(acts: [act(.기, 1, 1), act(.승, 1, 2), act(.전, 3, 3), act(.결, 3, 3)], episodes: [ep(1), ep(2), ep(3), ep(7)])
        #expect(b.columns.map(\.numbers) == [[1], [2], [3], []])
        #expect(b.columns[1].shared == "1화는 기 구간과 한 화에 함께 들어가요")
        #expect(b.columns[3].shared == "3화는 전 구간과 한 화에 함께 들어가요")
        #expect(b.columns.map { $0.episodes.map(\.plot.number) } == [[1], [2], [3], []])
        #expect(b.loose.map(\.plot.number) == [7])
    }

    @Test func serialRecapsAndChips() {
        var p = serialProject()
        // 아크 1 은 끝났지만 요약이 있는 1부에 들어 따로 요약할 필요가 없다
        #expect(PlotRules.pendingRecaps(p).arcs.isEmpty)
        #expect(PlotRules.arcChip(p, p.storyArcs![0]).label == "부 요약에 포함")
        #expect(PlotRules.arcChip(p, p.storyArcs![1]).label == "완료")
        #expect(PlotRules.arcChip(p, p.storyArcs![2]).label == "반영 0/4")
        #expect(PlotRules.arcChip(p, p.storyArcs![2]).status == .draft)
        p.parts![0].summary = ""
        #expect(PlotRules.pendingRecaps(p).arcs.map(\.number) == [1])
        #expect(PlotRules.pendingRecaps(p).parts.map(\.number) == [1])
        #expect(PlotRules.arcChip(p, p.storyArcs![0]).label == "요약 필요")
        let plan = SeriesPlan(parts: [.init(number: 1, title: "", startEp: 1, endEp: 12, goal: "")])
        p.parts![0].summary = "1부 요약"
        #expect(PlotRules.lostPartSummaries(p, plan).map(\.number) == [1])
    }

    @Test func railFoldsFinishedArcs() {
        var p = serialProject()
        p.storyArcs = (1...6).map { StoryArc(number: $0, title: "", startEp: $0 * 2 - 1, endEp: $0 * 2, goal: "", summary: $0 <= 5 ? "요약" : nil) }
        let r = PlotRules.rail(p, selected: 2, all: false)
        #expect(r.folded?.first == 1 && r.folded?.last == 5 && r.folded?.count == 4)
        #expect(r.shown.map(\.number) == [2, 6])
        #expect(PlotRules.rail(p, selected: 2, all: true).folded == nil)
    }

    @Test func insertSlots() {
        var p = short([ep(1, .finalized, text: "본문"), ep(2, .confirmed), ep(3, .draft)])
        #expect(PlotRules.lastFixed(p) == 1)
        #expect(PlotRules.insertSlots(p, 1) == (false, false))
        #expect(PlotRules.insertSlots(p, 2) == (true, false))
        #expect(PlotRules.insertSlots(p, 3) == (true, true))
        #expect(PlotRules.insertNote(p, at: 2) == "지금 2~3화가 3~4화로 밀려요. 플롯과 확정 상태는 그대로이고, 구간 · 아크 범위와 복선 · 인과율 요소 · 이야기 줄기의 화 번호도 함께 옮겨요. 총 화수가 1 늘어요.")
        #expect(PlotRules.insertNote(p, at: 4) == "마지막 화 뒤에 붙여요. 마지막 구간이 한 화 늘어나요. 총 화수가 1 늘어요.")
        p.history = [.init(episode: 3, summary: "")]
        #expect(PlotRules.lastFixed(p) == 3)
    }

    @Test func editorInfo() {
        var p = short([ep(1, .finalized), ep(2, .draft, chars: ["c1", "new", "ghost"], payoff: ["fs-2", "fs-x"]), ep(3)])
        p.foreshadows = [.init(id: "fs-1", description: "열쇠", plantedEp: 1, dueEp: 3), .init(id: "fs-2", description: "편지", plantedEp: 1, status: .resolved)]
        p.castCandidates = [.init(id: "new", name: "새 인물", role: "조연", tier: .support)]
        let e = PlotEditorInfo(p, episode: p.episodes![1], busy: false)
        #expect(e.prev == 1 && e.next == 3)
        #expect(!e.locked && e.lockNote == nil)
        #expect(e.actNote == "승 구간 목표 · 승 목표")
        #expect(e.payoffs.map(\.id) == ["fs-1", "fs-2", "fs-x"])
        #expect(e.payoffs.map(\.detail) == ["1화에 심음 · 3화 회수 예정", "이미 회수함", "없는 복선 id"])
        #expect(e.payoffs.map(\.fixed) == [false, true, true])
        #expect(e.candidates.map(\.id) == ["new"])
        #expect(e.unknown == ["ghost"])
        #expect(e.showOpening)
        let done = PlotEditorInfo(p, episode: p.episodes![0], busy: false)
        #expect(done.locked && done.lockNote == "본문이 있는 화라 플롯을 고칠 수 없어요.")
        let busy = PlotEditorInfo(p, episode: p.episodes![2], busy: true, busyNote: "승 구간")
        #expect(busy.lockNote == "AI가 이 화의 초안을 새로 만드는 중이라 끝날 때까지 고칠 수 없어요 (승 구간). 먼저 끝난 구간의 화는 지금 고칠 수 있어요.")
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
        let j = Job(id: "j\(started.count)", project: project, kind: request.kind, ep: request.ep, label: request.kind)
        list.append(j)
        return (j, false)
    }
    func stopJob(_ id: String) async throws -> Job { list.first { $0.id == id }! }
    func pending(_ project: String) async throws -> PendingList { pendingList }
    func dropPending(_ project: String, key: String, failure: Bool) async throws { dropped.append(key) }
}

/// 서버 대신: 확정하면 그 화를 확정하고, 새 인물 후보를 등록한다.
final class FakePlot: PlotService, @unchecked Sendable {
    let store: FakeStore
    var calls: [String] = []
    init(_ store: FakeStore) { self.store = store }
    func confirm(_ n: Int) async throws {
        calls.append("confirm \(n)")
        let i = store.project.episodes!.firstIndex { $0.plot.number == n }!
        store.project.episodes![i].status = .confirmed
        for c in store.project.castCandidates ?? [] where store.project.episodes![i].plot.characters.contains(c.id) {
            store.project.characters!.append(c)
        }
    }
    func unconfirm(_ n: Int) async throws { calls.append("unconfirm \(n)") }
    func applySeries(_ plan: SeriesPlan) async throws { calls.append("series \(plan.parts.count)") }
    func applyArc(_ proposal: ArcProposal) async throws { calls.append("arc \(proposal.arc.number) \(proposal.arc.endEp)") }
    func removeLastArc() async throws { calls.append("remove arc") }
    func applyRecap(kind: String, number: Int, summary: String) async throws { calls.append("recap \(kind) \(number) \(summary)") }
    func insert(at: Int, title: String, summary: String, storyline: String) async throws -> [String] {
        calls.append("insert \(at) \(title)")
        return ["\(at)화를 넣었어요."]
    }
    func remove(_ n: Int) async throws -> [String] { calls.append("remove \(n)"); return ["뺐어요."] }
}

@MainActor
func makeModel(_ p: Project, pending: PendingList = PendingList()) async -> (PlotModel, FakeStore, FakeJobs, FakePlot) {
    let store = FakeStore(p)
    let doc = ProjectDocument(name: "등대", store: store)
    await doc.load()
    let jobs = FakeJobs()
    jobs.pendingList = pending
    let center = JobCenter(service: jobs)
    await center.open(doc)
    let plot = FakePlot(store)
    return (PlotModel(document: doc, jobs: center, service: plot), store, jobs, plot)
}

func result(_ kind: String, ep: Int? = nil, _ value: some Encodable) throws -> PendingResult {
    let json = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
    return PendingResult(key: Job.key(kind, ep), id: "r-\(kind)", kind: kind, ep: ep, label: kind, result: json, base: nil)
}

@MainActor
@Suite struct ModelTests {
    @Test func arcProposalIsAppliedOnlyWhenChosen() async throws {
        let plan = ArcPlan(acts: [act(.기, 1, 2), act(.승, 3, 3), act(.전, 4, 4), act(.결, 4, 4)])
        let (m, _, jobs, _) = await makeModel(short([]), pending: PendingList(results: ["arc:": try result("arc", plan)]))
        m.syncResults()
        #expect(m.arcProposal?.count == 4)
        #expect(m.project?.arc?.first?.endEp == 1)  // 아직 그대로
        await m.useArcProposal()
        #expect(m.project?.arc?.first?.endEp == 2)
        #expect(m.document.dirty)
        #expect(jobs.dropped == ["arc:"])
        m.syncResults()
        #expect(m.arcProposal == nil)  // 받은 결과를 다시 받지 않는다
    }

    @Test func dropAsksFirst() async throws {
        let plan = ArcPlan(acts: [act(.기, 1, 4)])
        let (m, _, jobs, _) = await makeModel(short([]), pending: PendingList(results: ["arc:": try result("arc", plan)]))
        m.syncResults()
        m.dropArcProposal()
        #expect(m.ask?.message == "AI 구조 제안을 버릴까요? 되살릴 수 없어서, 다시 보려면 AI에게 다시 받아야 해요.")
        await m.ask?.run()
        #expect(m.arcProposal == nil)
        #expect(jobs.dropped == ["arc:"])
    }

    @Test func splitArc() async {
        var p = short([], target: 12)
        p.arc = []
        let (m, _, _, _) = await makeModel(p)
        m.splitArc()
        #expect(m.project?.arc?.map { [$0.startEp, $0.endEp] } == [[1, 2], [3, 7], [8, 10], [11, 12]])
        #expect(m.panel == .act(0))
    }

    @Test func startAsksWhenUnsaved() async {
        let (m, store, jobs, _) = await makeModel(short([ep(1)]))
        m.planNote = " 첫 반전은 3화 "
        m.editPlot(1) { $0.title = "고친 제목" }
        await m.planArc()
        #expect(jobs.started.isEmpty)
        #expect(m.ask?.message == "저장하지 않은 변경이 있어요. 저장하고 작업을 시작할까요?")
        await m.ask?.run()
        #expect(store.saved == 1)
        #expect(jobs.started.map(\.kind) == ["arc"])
        #expect(jobs.started.first?.note == "첫 반전은 3화")
    }

    @Test func redraftAsksAboutDrafts() async {
        let (m, _, jobs, _) = await makeModel(short([ep(1, .confirmed), ep(2)]))
        await m.draftPlots()
        #expect(m.ask?.message.hasPrefix("초안 1화(2화)를 AI 새 초안으로 바꿔요.") == true)
        await m.ask?.run()
        #expect(jobs.started.map(\.kind) == ["plots"])
        #expect(jobs.started.first?.ep == nil)
    }

    @Test func confirmSavesThenReloadsAndAnnouncesNewCast() async {
        var p = short([ep(1, chars: ["c1", "new"])])
        p.castCandidates = [.init(id: "new", name: "등대지기", role: "조연")]
        let (m, store, _, plot) = await makeModel(p)
        m.editPlot(1) { $0.summary = "요약" }
        await m.confirm(1)
        #expect(store.saved == 1)
        #expect(plot.calls == ["confirm 1"])
        #expect(m.project?.episodes?.first?.status == .confirmed)
        #expect(!m.document.dirty)
        #expect(m.notice?.text == "새 인물도 등록했어요: 등대지기")
    }

    @Test func confirmAllInArc() async {
        let (m, _, _, plot) = await makeModel(serialProject())
        m.confirmAll(arc: 3)
        #expect(m.ask?.message == "초안 2화를 모두 확정할까요?")
        await m.ask?.run()
        #expect(plot.calls == ["confirm 11", "confirm 12"])
        m.confirmAll(arc: 2)
        #expect(m.notice?.text == "확정할 초안이 없어요")
    }

    @Test func nextArcDraftEditsThenApplies() async throws {
        let prop = ArcProposal(arc: .init(number: 4, title: "넷", startEp: 15, endEp: 20, goal: "",
                                          acts: [act(.기, 15, 16), act(.승, 17, 18), act(.전, 19, 19), act(.결, 20, 20)]), reply: "왜")
        let (m, _, jobs, plot) = await makeModel(serialProject(), pending: PendingList(results: ["nextarc:": try result("nextarc", prop)]))
        m.syncResults()
        #expect(m.arcDraft?.arc.number == 4)
        #expect(m.selectedArc == .arc(3))  // 열 때 되살린 결과는 고른 아크를 옮기지 않는다 (지금 화 11화의 아크)
        m.setDraftEnd(22)
        #expect(m.arcDraft?.arc.acts?.last?.endEp == 22)
        m.arcLength = 7
        await m.applyArc()
        #expect(plot.calls == ["arc 4 22"])
        #expect(m.arcDraft == nil && m.arcLength == 0)
        #expect(m.arcPick == .arc(4))
        #expect(jobs.dropped == ["nextarc:"])
    }

    @Test func liveResultMovesSelection() async throws {
        let (m, _, jobs, _) = await makeModel(serialProject())
        m.syncResults()
        jobs.list = [Job(id: "r1", project: "등대", kind: "recap_arc", ep: 1, label: "아크 1 요약", status: .running)]
        await m.jobs.refresh()
        jobs.list = [Job(id: "r1", project: "등대", kind: "recap_arc", ep: 1, label: "아크 1 요약", status: .done, result: .object(["summary": .string("요약 제안")]))]
        await m.jobs.refresh()
        m.syncResults()
        #expect(m.recapDrafts["arc1"]?.summary == "요약 제안")
        #expect(m.selectedArc == .arc(1))
        m.recapDrafts["arc1"]?.summary = "고친 요약"
        await m.applyRecap("arc1")
        #expect(m.recapDrafts.isEmpty)
        #expect(jobs.dropped == ["recap_arc:1"])
    }

    @Test func seriesAsksWhenSummaryLost() async throws {
        let plan = SeriesPlan(parts: [.init(number: 1, title: "", startEp: 1, endEp: 50, goal: ""), .init(number: 2, title: "", startEp: 51, endEp: 100, goal: "")])
        let (m, _, _, plot) = await makeModel(serialProject(), pending: PendingList(results: ["series:": try result("series", plan)]))
        m.syncResults()
        await m.applySeries()
        #expect(m.ask?.message == "범위가 바뀌어 저장된 1부 요약이 사라져요. 반영할까요?")
        #expect(plot.calls.isEmpty)
        await m.ask?.run()
        #expect(plot.calls == ["series 2"])
        #expect(m.notice?.text == "부 구성을 바꿨어요. 아크와 반영한 화는 그대로예요.")
    }

    @Test func insertThenFillWithAI() async {
        let (m, _, jobs, plot) = await makeModel(short([ep(1), ep(2)]))
        m.openInsert(at: 2)
        m.insForm?.title = "외전"
        await m.submitInsert()
        #expect(plot.calls == ["insert 2 외전"])
        #expect(m.insForm == nil && m.panel == .episode(2))
        #expect(m.notice?.text == "2화를 넣었어요.")
        #expect(jobs.started.map(\.kind) == ["plot_one"])
        #expect(m.owns(2))
        m.removeEpisode(2)
        await m.ask?.run()
        #expect(plot.calls.last == "remove 2")
    }

    @Test func togglesKeepOrder() async {
        let (m, _, _, _) = await makeModel(short([ep(1, chars: ["c1"], payoff: ["a"])]))
        m.togglePayoff(1, "b", true)
        m.togglePayoff(1, "a", false)
        m.toggleCast(1, "c1", false)
        m.toggleCast(1, "c2", true)
        #expect(m.project?.episodes?.first?.plot.foreshadowPayoff == ["b"])
        #expect(m.project?.episodes?.first?.plot.characters == ["c2"])
    }
}
