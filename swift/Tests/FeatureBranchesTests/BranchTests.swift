import CanonAPI
import CanonCore
import CanonStore
@testable import FeatureBranches
import Foundation
import Testing

func decode<T: Decodable>(_ type: T.Type, _ json: String) -> T {
    try! JSONDecoder().decode(T.self, from: Data(json.utf8))
}

/// 본편 '등대'(제목 '등대 이야기'), 5화부터 갈라진 이름 없는 갈래 '등대-b', 그 갈래에서 6화부터 갈라진 'C안'.
let household = decode(BranchFamily.self, #"""
{"main":"등대","members":[
 {"name":"등대","title":"등대 이야기","info":{"id":"i1","family":"F"},"depth":0,"finalized":6,"planned":10,"episodes":20},
 {"name":"등대-b","title":"등대 이야기","info":{"id":"i2","family":"F","parent":"i1","from_ep":5},"parent_name":"등대","depth":1,
  "finalized":4,"planned":6,"episodes":20,"shared_edited":true,"parent_edited":true},
 {"name":"등대-c","title":"등대 이야기","info":{"id":"i3","family":"F","parent":"i2","from_ep":6,"label":"C안"},"parent_name":"등대-b","depth":2,
  "finalized":3,"planned":8,"episodes":20}]}
"""#)

func member(_ name: String) -> BranchMember { household.members!.first { $0.name == name }! }

func plot(_ n: Int) -> String {
    #"{"number":\#(n),"act":"기","title":"","summary":"","events":[],"characters":[],"emotional_shift":"","ending_hook":""}"#
}

/// 1~4화 반영, 5화 본문 있음, 6화 플롯 확정.
let sample = decode(Project.self, #"""
{"episodes":[{"plot":\#(plot(1)),"status":"finalized","text":"1"},{"plot":\#(plot(2)),"status":"finalized","text":"2"},
 {"plot":\#(plot(4)),"status":"finalized","text":"4"},{"plot":\#(plot(3)),"status":"finalized","text":"3"},
 {"plot":\#(plot(5)),"status":"written","text":"5"},{"plot":\#(plot(6)),"status":"confirmed"}]}
"""#)

let diff = decode(BranchDiff.self, #"""
{"from_ep":5,"episode":6,"ready_a":true,"ready_b":false,
 "episodes":[{"number":5,"a":{"title":"갈림길","status":"finalized","summary":"요약"},"b":{"title":"","status":"written"}},
  {"number":6,"a":{"status":"draft"},"b":{"status":"draft"}},{"number":7,"a":{"status":"draft"}},
  {"number":8,"a":{"status":"draft"},"b":{"status":"draft"}},{"number":9,"b":{"status":"confirmed"}}],
 "text_a":"본문","rows":[{"kind":"character","who":"도현","field":"감정","a":"불안","b":""},{"kind":"fact","a":"x"}]}
"""#)

@Suite struct BranchTextTests {
    /// 웹 `branchName` (node 로 돌린 값): 이름 없는 본편은 제목, 이름 없는 갈래는 폴더 이름.
    @Test func names() {
        #expect(household.members!.map(BranchText.name) == ["등대 이야기", "등대-b", "C안"])
        let bare = decode(BranchMember.self, #"{"name":"x","title":"","info":{"id":"a","family":"F"}}"#)
        #expect(BranchText.name(bare) == "x")
        #expect(BranchText.shared(1) == "")
        #expect(BranchText.shared(2) == "1화")
        #expect(BranchText.shared(5) == "1~4화")
    }

    @Test func sideTag() {
        #expect(BranchText.sideTag(household, "등대") == nil)
        #expect(BranchText.sideTag(household, "등대-b") == "갈래 · 등대-b (5화부터)")
        #expect(BranchText.sideTag(household, "등대-c") == "갈래 · C안 (6화부터)")
        #expect(BranchText.sideTag(nil, "등대") == nil)
    }

    @Test func mainStripOnlyAtHome() {
        #expect(BranchText.strip(household, "등대", home: false) == nil)
        let s = BranchText.strip(household, "등대", home: true)!
        #expect(s.main && s.title == "본편" && s.line == "갈래 2개")
        #expect(s.others == [.init(name: "등대-b", label: "등대-b", detail: "5화부터"), .init(name: "등대-c", label: "C안", detail: "6화부터")])
        // 혼자인 작품은 띠가 없다
        let alone = decode(BranchFamily.self, #"{"main":"","members":[]}"#)
        #expect(BranchText.strip(alone, "등대", home: true) == nil)
    }

    @Test func branchStrip() {
        let b = BranchText.strip(household, "등대-b", home: false)!
        #expect(b.title == "갈래 · 등대-b")
        #expect(b.line == "5화부터 '등대 이야기'와 달라요 (1~4화는 함께 써요)")
        #expect(b.parent == "등대" && b.mainName == nil)
        #expect(b.warnings == ["갈라진 뒤 이 갈래에서 1~4화를 고쳤어요. 다른 갈래에는 들어가지 않아요.",
                               "갈라진 뒤 '등대 이야기'에서 1~4화를 고쳤어요. 이 갈래에는 들어가지 않아요."])
        #expect(b.others.map(\.name) == ["등대", "등대-c"])
        let c = BranchText.strip(household, "등대-c", home: true)!
        #expect(c.title == "갈래 · C안")
        #expect(c.line == "6화부터 '등대-b'과(와) 달라요 (1~5화는 함께 써요)")
        #expect(c.parent == "등대-b" && c.mainName == "등대")
        #expect(c.warnings.isEmpty)
    }

    @Test func homeRows() {
        let rows = BranchText.homeRows(household, "등대-b")
        #expect(rows.map(\.label) == ["등대 이야기", "등대-b", "C안"])
        #expect(rows.map(\.me) == [false, true, false])
        #expect(rows.map(\.detail) == ["본편 · 6 / 20화 반영", "5화부터 · 4 / 20화 반영", "6화부터 · 3 / 20화 반영"])
        #expect(rows[0].shared == 0 && rows[0].start == 0 && rows[0].done == 0.3)
        #expect(rows[1].shared == 0.2 && rows[1].start == 0.2 && rows[1].done == nil)
        #expect(rows.map(\.depth) == [0, 1, 2])
        #expect(rows[0].accessibility == "등대 이야기: 1화부터 따로, 6화까지 반영")
        #expect(rows[1].accessibility == "등대-b: 1~4화는 함께 쓰고 5화부터 따로, 4화까지 반영")
    }

    @Test func promoteAndDetach() {
        #expect(BranchText.promoteQuestion(member("등대-c")) == "'C안'을 본편으로 올릴까요? 갈래 정보만 바뀌고 작품 내용과 폴더 이름은 그대로예요.")
        #expect(BranchText.promoted(member("등대-c")) == "'C안'이 본편이 됐어요")
        #expect(BranchText.detachQuestion(household, member("등대-b"))
            == "'등대-b' 갈래를 끊을까요? 따로 선 작품이 되고 작품 내용은 그대로예요. 이 갈래에서 갈라진 'C안'은 '등대 이야기'에 다시 이어요.")
        #expect(BranchText.detachQuestion(household, member("등대-c")) == "'C안' 갈래를 끊을까요? 따로 선 작품이 되고 작품 내용은 그대로예요.")
        #expect(BranchText.detached(member("등대-c")) == "'C안' 갈래를 끊었어요")
    }

    /// 웹 `folderOf` · `branchFolder` · `FOLDER_BAD` (node 로 돌린 값).
    @Test func folders() {
        #expect(BranchText.folderOf("  B안 - 세린이 떠난다 ") == "B안---세린이-떠난다")
        #expect(BranchText.folderOf("..숨김") == "숨김")
        #expect(BranchText.folderOf(#"a/b:c*d?"e<f>g|h"#) == "abcdefgh")
        #expect(BranchText.folderOf(String(repeating: "x", count: 70)) == String(repeating: "x", count: 64))
        #expect(BranchText.folderOf(String(repeating: "😀", count: 40)) == String(repeating: "😀", count: 32))
        #expect(BranchText.folder(label: "", project: "등대") == "등대-갈래")
        #expect(BranchText.folder(label: "B안 - 세린", project: "등대") == "등대-B안---세린")
        #expect(BranchText.folder(label: "/", project: "등대") == "등대-갈래")
        #expect(BranchText.folderBad(".a") && BranchText.folderBad("a/b") && !BranchText.folderBad("ok-이름"))
    }

    @Test func form() {
        #expect(BranchText.lastFinal(sample) == 4)
        #expect(BranchText.formDesc(1) == "이 작품을 복사해 다른 전개를 써 봐요. 1화부터는 갈래에서만 바뀌어요. 지금 작품은 그대로예요.")
        #expect(BranchText.formDesc(2) == "이 작품을 복사해 다른 전개를 써 봐요. 1화는 그대로 복사하고, 2화부터는 갈래에서만 바뀌어요. 지금 작품은 그대로예요.")
        #expect(BranchText.formNote(sample, from: 3, keep: false) == "갈래에서는 3~4화의 상태 반영을 취소해 2화 반영 직후 상태로 돌아가요. 3~5화 본문은 비워요.")
        #expect(BranchText.formNote(sample, from: 3, keep: true) == "갈래에서는 3~4화의 상태 반영을 취소해 2화 반영 직후 상태로 돌아가요.")
        #expect(BranchText.formNote(sample, from: 1, keep: true) == "갈래에서는 1~4화의 상태 반영을 취소해 1화 시작 전 상태로 돌아가요.")
        #expect(BranchText.formNote(sample, from: 5, keep: false) == "갈래에서는 5화 본문은 비워요.")
        #expect(BranchText.formNote(sample, from: 6, keep: false) == nil)
        #expect(BranchText.created(label: " ", to: "등대-갈래") == "'등대-갈래' 갈래를 만들었어요. 지금은 갈래 작품을 보고 있어요")
    }

    @Test func pickToCompare() {
        #expect(BranchText.pick(household, "등대-c", other: nil) == "등대-b")
        #expect(BranchText.pick(household, "등대-c", other: "등대") == "등대")
        #expect(BranchText.pick(household, "등대-c", other: "없는-작품") == "등대-b")
        #expect(BranchText.pick(household, "등대-c", other: "등대-c") == "등대-b")
        #expect(BranchText.pick(household, "등대", other: nil) == "등대-b")
        #expect(BranchText.pick(nil, "등대", other: nil) == nil)
        #expect(BranchText.option(member("등대")) == "등대 이야기 (본편)")
        #expect(BranchText.option(member("등대-c")) == "C안 (6화부터)")
    }

    @Test func compareRows() {
        #expect(BranchText.headline(diff, a: "등대-b", b: "C안") == "'등대-b'과(와) 'C안'은 5화부터 달라요. 1~4화는 함께 써요.")
        let (rows, idle) = BranchText.episodeRows(diff)
        #expect(rows.map(\.number) == [5, 6, 9])
        #expect(rows.map(\.current) == [false, true, false])
        #expect(rows[0].a == .init(title: "갈림길", status: .finalized, summary: "요약"))
        #expect(rows[0].b == .init(title: "제목 없음", status: .written, summary: ""))
        #expect(rows[2].a == nil)
        #expect(idle == [7, 8])
        #expect(BranchText.episodeNote(idle: idle) == "7~8화는 양쪽 모두 플롯 초안이라 빼고 보여요. 화를 누르면 아래에 그 화 본문과 상태가 나와요.")
        #expect(BranchText.episodeNote(idle: []) == "화를 누르면 아래에 그 화 본문과 상태가 나와요.")
        #expect(BranchText.notReady(diff, a: "A", b: "B") == "'B'에서 6화를 아직 반영하지 않아 상태는 견줄 수 없어요.")
        #expect(BranchText.diffRows(diff) == [.init(kind: "인물", item: "도현 · 감정", a: "불안", b: nil), .init(kind: "사실", item: "", a: "x", b: nil)])
        #expect(BranchText.empty(last: 0) == "아직 갈래가 없어요. 1화를 반영한 뒤에 만들 수 있어요.")
    }
}

@Suite struct BranchDraftTests {
    @Test func folderFollowsLabelUntilTyped() {
        var d = BranchDraft(project: "등대", from: nil, last: 4)
        #expect(d.from == "4" && d.to == "등대-갈래" && !d.keep)
        #expect(BranchDraft(project: "등대", from: nil, last: 0).from == "1")
        #expect(BranchDraft(project: "등대", from: 2, last: 4).from == "2")
        d.label = "B안 - 세린"
        #expect(d.to == "등대-B안---세린")
        d.typeFolder("내-폴더")
        d.label = "C안"
        #expect(d.to == "내-폴더")
        d.typeFolder("  ")
        d.label = "D안"
        #expect(d.to == "등대-D안")
    }

    @Test func checks() {
        var d = BranchDraft(project: "등대", from: 6, last: 4)
        #expect(d.check(last: 4) == .init(field: .from, message: "시작 화는 1~5화 중에 골라 주세요. 4화까지 반영했어요."))
        #expect(BranchDraft(project: "등대", from: 2, last: 0).check(last: 0)?.message == "시작 화는 1~1화 중에 골라 주세요. 아직 반영한 화가 없어요.")
        d.from = "abc"
        #expect(d.check(last: 4)?.field == .from)
        d.from = " 5 "
        d.typeFolder("")
        #expect(d.check(last: 4) == .init(field: .to, message: "폴더 이름을 적어 주세요."))
        d.typeFolder(".숨김")
        #expect(d.check(last: 4)?.message == "폴더 이름에 / \\ : * ? \" < > | 는 쓸 수 없고, . 으로 시작할 수 없어요.")
        d.typeFolder(" 등대-새 ")
        d.label = " 새 안 "
        d.keep = true
        #expect(d.check(last: 4) == nil)
        #expect(d.body == BranchIn(to: "등대-새", fromEp: 5, mode: .keep, label: "새 안"))
        // 고치기 시작하면 그 칸의 오류를 걷는다
        d.problem = BranchDraft.taken
        d.from = "4"
        #expect(d.problem == BranchDraft.taken)
        d.typeFolder("등대-또")
        #expect(d.problem == nil)
    }
}

final class FakeBranches: BranchService, @unchecked Sendable {
    var fam = household
    var made: [BranchIn] = []
    var compared: [(String, String, Int?)] = []
    var promoted: [String] = []
    var makeError: CanonError?

    func family(_ project: String) async throws -> BranchFamily { fam }

    func make(_ project: String, _ body: BranchIn) async throws -> BranchMember {
        if let makeError { throw makeError }
        made.append(body)
        return member("등대-b")
    }

    func compare(_ project: String, with other: String, ep: Int?) async throws -> BranchDiff {
        compared.append((project, other, ep))
        return diff
    }

    func promote(_ project: String) async throws -> BranchFamily {
        promoted.append(project)
        return fam
    }

    func detach(_ project: String) async throws -> BranchFamily { fam }
}

@MainActor
@Suite struct BranchModelTests {
    @Test func createSendsDraft() async {
        let fake = FakeBranches()
        let model = BranchModel(project: "등대", service: fake)
        var d = BranchDraft(project: "등대", from: 9, last: 4)
        #expect(await model.create(&d, last: 4) == nil)
        #expect(d.problem?.field == .from && fake.made.isEmpty)
        d.from = "3"
        d.label = "B안"
        let made = await model.create(&d, last: 4)
        #expect(made == .init(name: "등대-B안", from: 3, keep: false, notice: "'B안' 갈래를 만들었어요. 지금은 갈래 작품을 보고 있어요"))
        #expect(fake.made == [BranchIn(to: "등대-B안", fromEp: 3, mode: .clear, label: "B안")])
    }

    @Test func takenFolderIsFieldError() async {
        let fake = FakeBranches()
        fake.makeError = .server(status: 409, message: "이미 있는 이름이에요: 등대-갈래", code: nil)
        let model = BranchModel(project: "등대", service: fake)
        var d = BranchDraft(project: "등대", from: 2, last: 4)
        #expect(await model.create(&d, last: 4) == nil)
        #expect(d.problem == BranchDraft.taken)
        #expect(model.error == nil)
        fake.makeError = .server(status: 400, message: "작업이 도는 중이에요", code: nil)
        #expect(await model.create(&d, last: 4) == nil)
        #expect(model.error == "작업이 도는 중이에요")
    }

    @Test func compareAndPromote() async {
        let fake = FakeBranches()
        let model = BranchModel(project: "등대-c", service: fake)
        await model.load()
        #expect(model.members.count == 3)
        await model.compare(other: nil, ep: nil)
        #expect(model.diffWith == "등대-b" && model.diff?.episode == 6)
        await model.promote(member("등대-c"))
        #expect(fake.promoted == ["등대-c"])
        #expect(model.notice == "'C안'이 본편이 됐어요")
        // 비교를 보던 중이면 같은 작품 · 화로 다시 불러온다
        #expect(fake.compared.map(\.1) == ["등대-b", "등대-b"])
        #expect(fake.compared.last?.2 == 6)
    }
}
