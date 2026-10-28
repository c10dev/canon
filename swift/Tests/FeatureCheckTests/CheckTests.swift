import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureCheck
import Foundation
import Testing

func project(_ json: String) -> Project {
    try! JSONDecoder().decode(Project.self, from: Data(json.utf8))
}

func plot(_ n: Int) -> String {
    #"{"number":\#(n),"act":"기","title":"\#(n)화 제목","summary":"","events":[],"characters":[],"emotional_shift":"","ending_hook":""}"#
}

func finding(_ id: String, _ status: String, quote: String, first: Int = 1, last: Int = 1, closedBy: String = "", type: String = "사실", src: Int = 0) -> String {
    #"{"id":"\#(id)","type":"\#(type)","description":"\#(id) 설명","source_episode":\#(src),"source_quote":"근거","current_quote":"\#(quote)","status":"\#(status)","first":\#(first),"last":\#(last),"closed_by":"\#(closedBy)"}"#
}

let Q2 = "서윤은 눈앞의 문손잡이를 두 손으로 붙잡았다."
let Q3 = "“그만해. 네가 뭘 안다고.”"
let Q4 = "도현은 그녀가 눈치채지 못하기를 속으로 빌었다."
let text2 = "도현은 왼손에 남은 흉터를 엄지로 문질렀다. \(Q2) \(Q3) \(Q4)"

/// 웹 `tests/test_check_js.py` 의 세션과 같다: 1회차 4곳 → f1 은 문장을 고쳐 다시 검수에서 사라짐, f2 그대로 둠(2회차에 다시 나옴),
/// f3 잘못 짚음, f4 는 2회차가 짚지 않았지만 문장이 그대로라 열림. 1화는 반영 끝 · 검수 없음, 3화는 확정.
let sample = project(#"""
{"meta":{"title":"등대","target_episodes":3},
 "episodes":[{"plot":\#(plot(1)),"status":"finalized","text":"1화 본문"},
             {"plot":\#(plot(2)),"status":"written","text":"\#(text2)","checked_at":"2026-10-28T11:00:00",
              "findings":[\#(finding("f1", "fixed", quote: "도현은 오른손에 남은 흉터를 엄지로 문질렀다.", closedBy: "recheck")),
                          \#(finding("f2", "kept", quote: Q2, last: 2, type: "동선", src: 2)),
                          \#(finding("f3", "wrong", quote: Q3, type: "말투")),
                          \#(finding("f4", "open", quote: Q4, type: "시점", src: 1))],
              "rounds":[{"no":1,"at":"2026-10-28T10:00:00","found":4,"added":4},
                        {"no":2,"at":"2026-10-28T11:00:00","source":"chat","found":1,"added":0,"kept_again":1}]},
             {"plot":\#(plot(3)),"status":"confirmed"}]}
"""#)

var ep2: Episode { sample.episodes![1] }

@Suite struct CheckTextTests {
    @Test func flagsMatchWeb() {
        let flags = ep2.findings!.map { CheckText.flag(ep2, $0, text: text2)?.rawValue ?? "" }
        #expect(flags == ["gone", "again", "", "miss"])
        let draft = text2.replacingOccurrences(of: Q4, with: "도현이 시선을 피했다.")
        #expect(CheckText.flag(ep2, ep2.findings![3], text: draft) == .changed)
    }

    @Test func marksOpenAndSelected() {
        let marks = CheckText.marks(ep2, text: text2, selected: "f2")
        #expect(marks.map { [$0.id, String(text2[$0.range]), $0.selected ? "sel" : ""] } == [["f2", Q2, "sel"], ["f4", Q4, ""]])
    }

    @Test func selectionFallsBackToFirstOpen() {
        #expect(CheckText.selected(ep2, chosen: nil) == "f4")
        #expect(CheckText.selected(ep2, chosen: "f3") == "f3")
        #expect(CheckText.selected(ep2, chosen: "f9") == "f4")
    }

    @Test func listsAndLabels() {
        #expect(CheckText.Filter.allCases.map { CheckText.count(ep2, $0) } == [1, 1, 1, 1, 4])
        #expect(CheckText.source(2, ep2.findings![0]) == "설정 · 확정 사실")
        #expect(CheckText.source(2, ep2.findings![1]) == "이번 화 앞 문장")
        #expect(CheckText.source(2, ep2.findings![3]) == "1화")
        #expect(CheckText.checkLabel(ep2) == "다시 검수 · 3회차")
        #expect(CheckText.reviewLabel(ep2) == "상태 승인으로 · 열린 지적 1")
        let utc = TimeZone(identifier: "UTC")!
        let now = ISO8601DateFormatter().date(from: "2026-10-28T12:00:00Z")!
        #expect(CheckText.round(ep2.rounds![1], now: now, timeZone: utc) == "2회차 · 11:00 · 짚은 1 · 새로 0 · 결정 그대로 1 · 채팅 앱")
        #expect(CheckText.round(ep2.rounds![0], now: now, timeZone: utc) == "1회차 · 10:00 · 짚은 4")
    }

    /// 진행 막대의 검수 칸 (웹 `home.js` `checkState`).
    @Test func checkState() {
        #expect(ep2.checkState == CheckState(checked: true, stale: false, open: 1))
        #expect(!ep2.checkState.done)
        #expect(sample.episodes![0].checkState == CheckState(checked: false, stale: false, open: 0))
        var edited = ep2
        edited.edits = [try! JSONDecoder().decode(Components.Schemas.TextEdit.self, from: Data(#"{"id":"e1","at":"2026-10-28T12:00:00"}"#.utf8))]
        #expect(edited.checkState.stale)
        #expect(CheckText.staleNote(edited)?.hasPrefix("2회차 뒤에 본문을 고쳤어요") == true)
    }
}

// MARK: 모델

final class FakeStore: ProjectStoring, @unchecked Sendable {
    var project: Project

    init(_ project: Project) { self.project = project }

    func load(_ name: String) async throws -> Project { project }

    func save(_ name: String, _ p: Project, merged: [String], force: Bool) async throws -> SaveResult {
        project = p
        return SaveResult(project: p, kept: [])
    }
}

final class FakeJobs: JobServing, @unchecked Sendable {
    var list: [Job] = []
    var started: [JobRequest] = []

    func listJobs() async throws -> [Job] { list }
    func startJob(_ project: String, _ request: JobRequest) async throws -> (job: Job, already: Bool) {
        started.append(request)
        let j = Job(id: "j\(started.count)", project: project, kind: request.kind, ep: request.ep, label: "\(request.ep ?? 0)화 검수")
        list.append(j)
        return (j, false)
    }
    func stopJob(_ id: String) async throws -> Job { list.first { $0.id == id }! }
    func pending(_ project: String) async throws -> PendingList { PendingList() }
    func dropPending(_ project: String, key: String, failure: Bool) async throws {}
}

/// 서버 대신: 지적 상태를 가짜 저장소의 작품에 적는다 (서버 findings.set_status 처럼).
final class FakeCheck: CheckService, @unchecked Sendable {
    let store: FakeStore
    var sent: [(String, String, String?)] = []

    init(_ store: FakeStore) { self.store = store }

    func setFinding(_ project: String, ep: Int, id: String, status: CheckText.Status, note: String?) async throws {
        sent.append((id, status.rawValue, note))
        var p = store.project
        let i = p.episodes!.firstIndex { $0.plot.number == ep }!
        let j = p.episodes![i].findings!.firstIndex { $0.id == id }!
        p.episodes![i].findings![j].status = .init(rawValue: status.rawValue)
        if let note { p.episodes![i].findings![j].note = note }
        store.project = p
    }

    func style(_ project: String, ep: Int) async throws -> StyleDrift {
        try JSONDecoder().decode(StyleDrift.self, from: Data(#"{"metrics":{},"warnings":["문체 거리: 1.6"]}"#.utf8))
    }
}

@MainActor
@Suite struct CheckModelTests {
    func make() async -> (CheckModel, FakeStore, FakeJobs, FakeCheck) {
        let store = FakeStore(sample)
        let doc = ProjectDocument(name: "등대", store: store)
        let jobs = FakeJobs()
        let center = JobCenter(service: jobs)
        await center.open(doc)
        let check = FakeCheck(store)
        let model = CheckModel(document: doc, jobs: center, service: check)
        await model.start()
        return (model, store, jobs, check)
    }

    @Test func opensWrittenEpisodeNotDone() async {
        let (model, _, _, _) = await make()
        #expect(model.ep == 2)
        #expect(model.selectedID == "f4")
        #expect(model.shown.map(\.id) == ["f4"])
        if case let .success(d)? = model.style[2] { #expect(d.warnings == ["문체 거리: 1.6"]) } else { Issue.record("문체 지표를 받지 못했어요") }
    }

    @Test func keepWithNoteAndFixMovesOn() async {
        let (model, store, _, check) = await make()
        #expect(await model.set(.kept))
        #expect(store.project.episodes![1].findings![3].status == .kept)
        #expect(model.selectedID == "f4")  // 그대로 둠은 메모를 적을 수 있게 남는다
        model.note = "일부러"
        #expect(await model.saveNote())
        #expect(check.sent.last! == ("f4", "kept", "일부러"))
        #expect(model.episode!.checkState.done)

        model.filter = .all
        model.choose("f3")
        #expect(model.note == "")
        #expect(await model.set(.open))
        model.choose("f3")
        #expect(await model.set(.fixed))
        #expect(model.selectedID == "f3")  // 다른 열린 지적이 없으면 그대로
    }

    @Test func checkStartsJob() async {
        let (model, _, jobs, _) = await make()
        #expect(await model.check())
        #expect(jobs.started.map(\.kind) == ["check"] && jobs.started.first?.ep == 2)
    }
}
