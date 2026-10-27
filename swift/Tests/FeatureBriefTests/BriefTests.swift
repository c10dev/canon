import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureBrief
import Foundation
import Testing

func project(_ json: String) -> Project {
    try! JSONDecoder().decode(Project.self, from: Data(json.utf8))
}

func plot(_ n: Int) -> String {
    #"{"number":\#(n),"act":"기","title":"\#(n)화 제목","summary":"","events":[],"characters":[],"emotional_shift":"","ending_hook":""}"#
}

/// 1화 반영 끝 · 2화 본문 있음 · 3화 확정 · 4화 초안. 한 화 목표 1000자.
let sample = project(#"""
{"meta":{"words_per_episode":1000},
 "episodes":[{"plot":\#(plot(1)),"status":"finalized","text":"1화 본문"},
             {"plot":\#(plot(2)),"status":"written","text":"2화 본문"},
             {"plot":\#(plot(3)),"status":"confirmed"},
             {"plot":\#(plot(4)),"status":"draft"}]}
"""#)

@Suite struct BriefTextTests {
    /// 웹 `briefTabFor`: 본문이 있고 반영하지 않은 화는 상태 승인 지시서, 나머지는 본문 작성 지시서.
    @Test func defaultKind() {
        #expect(BriefText.defaultKind(.written) == .state)
        #expect(BriefText.defaultKind(.confirmed) == .episode)
        #expect(BriefText.defaultKind(.finalized) == .episode)
        #expect(BriefModel.defaultEpisode(sample) == 2)
    }

    /// 웹 `importCount`: UTF-16 길이, 천 단위 쉼표, 목표의 70%보다 짧으면 경고.
    @Test func count() {
        #expect(BriefText.count("", goal: 1000) == ("0 / 1,000자", false))
        #expect(BriefText.count("  " + String(repeating: "가", count: 699) + "\n", goal: 1000) == ("699 / 1,000자", true))
        #expect(BriefText.count(String(repeating: "가", count: 700), goal: 1000) == ("700 / 1,000자", false))
        #expect(BriefText.count("😀", goal: 0) == ("2 / 0자", false))
        #expect(BriefText.length(String(repeating: "a", count: 12345)) == "12,345자")
    }

    @Test func orderAndFiles() {
        let eps = sample.episodes!
        #expect(BriefText.blockedBefore(3, in: eps) == [2])
        let note = BriefText.orderNote([2], in: eps)
        #expect(note?.text == "이전 화(2화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요.")
        #expect(note?.button == "2화 상태 승인으로")
        #expect(note?.screen == .review)
        #expect(BriefText.orderNote([3], in: eps)?.button == "3화 집필로")
        #expect(BriefText.filename("책", ep: 3, kind: .state) == "책-03-state.md")
        #expect(BriefText.textNote(.draft) == "플롯을 확정해야 본문을 저장할 수 있어요.")
        #expect(BriefText.canImportText(.written) && !BriefText.canImportText(.finalized))
    }

    @Test func parsedSummary() {
        let d = try! JSONDecoder().decode(StateDelta.self, from: Data(#"{"episode":2,"summary":"","events":[{"episode":2,"actor":"a","target":"b","kind":"도움"}],"new_facts":["x","y"]}"#.utf8))
        #expect(BriefText.parsedSummary(d) == "JSON을 확인했어요: 사건 1 · 새 사실 2")
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

final class FakeBrief: BriefService, @unchecked Sendable {
    let store: FakeStore
    var asked: [(Int, BriefKind)] = []
    var saved: [(Int, String)] = []
    var parseError: CanonError?
    init(_ store: FakeStore) { self.store = store }
    func brief(_ project: String, ep: Int, kind: BriefKind) async throws -> String {
        asked.append((ep, kind))
        return "\(ep)화 \(kind.rawValue) 지시서"
    }
    func saveText(_ project: String, ep: Int, text: String) async throws -> Project {
        saved.append((ep, text))
        store.project.episodes![ep - 1].text = text
        store.project.episodes![ep - 1].status = .written
        return store.project
    }
    func parseState(_ project: String, ep: Int, raw: String) async throws -> StateDelta {
        if let parseError { throw parseError }
        return try JSONDecoder().decode(StateDelta.self, from: Data(#"{"episode":\#(ep),"summary":"요약"}"#.utf8))
    }
}

@MainActor
func makeModel(name: String) async -> (BriefModel, FakeStore, FakeBrief) {
    let store = FakeStore(sample)
    let doc = ProjectDocument(name: name, store: store)
    await doc.load()
    let fb = FakeBrief(store)
    let m = BriefModel(document: doc, service: fb)
    await m.start()
    return (m, store, fb)
}

@MainActor
@Suite struct BriefModelTests {
    /// 본문이 있는 2화는 상태 승인 지시서로 연다. 고른 종류는 그 화에 남는다.
    @Test func tabs() async {
        let (m, _, fb) = await makeModel(name: "탭")
        #expect(m.ep == 2 && m.kind == .state)
        #expect(m.text == "2화 state 지시서")
        await m.select(3)
        #expect(m.kind == .episode)
        await m.setKind(.state)
        #expect(m.stateBlocked)
        #expect(m.text == nil)
        #expect(fb.asked.count == 2)
        await m.select(2)
        await m.select(3)
        #expect(m.kind == .state)
    }

    /// 받은 본문 저장: 앞 화 반영이 끝나지 않으면 막고, 저장하면 붙여 넣은 글을 지운다.
    @Test func importText() async {
        let (m, _, fb) = await makeModel(name: "본문")
        await m.select(3)
        #expect(m.order == [2])
        #expect(!m.canImport)
        await m.select(1)
        #expect(!m.canImport)
        // 막히지 않은 화를 만들려고 2화를 끝낸 작품으로 다시 연다
        let store = FakeStore(sample)
        store.project.episodes![1].status = .finalized
        let doc = ProjectDocument(name: "본문2", store: store)
        await doc.load()
        let fb2 = FakeBrief(store)
        let m2 = BriefModel(document: doc, service: fb2, ep: 3)
        await m2.start()
        #expect(m2.canImport)
        #expect(await m2.importText() == false)
        #expect(m2.notice?.text == "본문을 붙여 넣으세요")
        m2.draft = "  받은 본문  "
        #expect(await m2.importText())
        #expect(fb2.saved.first?.1 == "받은 본문")
        #expect(m2.draft.isEmpty)
        #expect(m2.episode?.text == "받은 본문")
        #expect(m2.notice?.text == "3화 본문으로 저장했어요")
        #expect(fb.saved.isEmpty)
    }

    /// 받은 JSON: 서버가 400 으로 거절하면 이유를 칸 아래에 남기고, 읽으면 변경안을 돌려주고 칸을 비운다.
    @Test func importJSON() async {
        let (m, _, fb) = await makeModel(name: "JSON")
        #expect(m.canImport)
        fb.parseError = .server(status: 400, message: "JSON을 찾지 못했어요", code: nil)
        m.draft = "아무 말"
        #expect(await m.importJSON() == nil)
        #expect(m.importError == "JSON을 찾지 못했어요")
        #expect(m.draft == "아무 말")
        fb.parseError = nil
        let d = await m.importJSON()
        #expect(d?.episode == 2)
        #expect(m.importError == nil)
        #expect(m.parsed?.summary == "요약")
        #expect(m.draft.isEmpty)
    }

    /// 붙여 넣은 글은 화면을 다시 만들어도 남는다 (웹 `S.briefDraft`).
    @Test func draftsSurvive() async {
        let (m, store, fb) = await makeModel(name: "남김")
        m.draft = "남는 글"
        let again = BriefModel(document: m.document, service: fb)
        await again.start()
        #expect(again.draft == "남는 글")
        #expect(store.saved == 0)
    }
}
