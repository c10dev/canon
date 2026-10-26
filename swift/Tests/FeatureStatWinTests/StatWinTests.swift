import CanonCore
import FeatureStatWin
import Foundation
import Testing

func decode<T: Decodable>(_ json: String, as: T.Type = T.self) throws -> T {
    try JSONDecoder().decode(T.self, from: Data(json.utf8))
}

/// 서버 `GET .../statwin/hero` 응답 모양 (statwin.timeline + render + PRESETS).
let heroView = #"""
{"names":["레벨","HP","스킬"],
 "columns":[
  {"episode":0,"values":{"레벨":"1","HP":"100"},"changed":{"레벨":{"before":"","source":"author"},"HP":{"before":"","source":"author"}}},
  {"episode":1,"values":{"레벨":"3","HP":"100","스킬":"베기"},"changed":{"레벨":{"before":"1","source":"ai"},"스킬":{"before":"","source":"ai"}}},
  {"episode":2,"values":{"레벨":"3","HP":"","스킬":"베기"},"changed":{"HP":{"before":"100","source":"both"}}}],
 "current":[{"name":"레벨","value":"3"},{"name":"스킬","value":"베기"}],
 "text":"【 상태창 】\n이름: 한결\n레벨: 3\n스킬: 베기",
 "presets":{"simple":["레벨","스킬"],"game":["레벨","HP","MP","힘","민첩","체력","지능","스킬"],"hunter":["등급","레벨","마력","스킬","칭호"]}}
"""#

let emptyView = #"{"names":[],"columns":[],"current":[],"text":"","presets":{"game":["레벨","HP"],"simple":["레벨","스킬"]}}"#

func project(states: String = #"[{"character_id":"hero","stats":[{"name":"레벨","value":"3"},{"name":"스킬","value":"베기"}]}]"#,
             template: String = "【 상태창 】\\n이름: {name}\\n{rows}") -> String {
    #"""
    {"characters":[{"id":"rival","name":"서진","role":"적대자","tier":"support"},{"id":"hero","name":"한결","role":"주인공","tier":"main"},{"id":"kid","name":"아이","role":"단역","tier":"minor"}],
     "states":\#(states),
     "stat_window":{"template":"\#(template)","row":"{key}: {value}"}}
    """#
}

/// 받은 요청을 적어 두고 정해 둔 답을 돌려준다.
actor FakeSource: StatWinSource {
    var projectJSON: String
    var views: [String: String]
    var failure: CanonError?
    var saved: [(String, [StatValue])] = []
    var templates: [(String, String)] = []

    init(project: String, views: [String: String], failure: CanonError? = nil) {
        self.projectJSON = project
        self.views = views
        self.failure = failure
    }

    func project(_ name: String) async throws -> Project { try decode(projectJSON) }

    func view(_ name: String, character: String) async throws -> StatwinView {
        try decode(views[character] ?? emptyView)
    }

    func save(_ name: String, character: String, stats: [StatValue]) async throws -> Project {
        if let failure { throw failure }
        saved.append((character, stats))
        return try decode(projectJSON)
    }

    func saveTemplate(_ name: String, template: String, row: String) async throws -> Project {
        if let failure { throw failure }
        templates.append((template, row))
        return try decode(projectJSON)
    }
}

@Suite struct OutgoingTests {
    /// '+2' · '+독 내성' 은 서버가 계산하니 적은 그대로 보낸다.
    @Test func skipsBlankNamesAndKeepsValues() {
        let rows = [StatRow(name: " 레벨 ", value: "+2"), StatRow(name: "", value: "9"), StatRow(name: "힘", value: ""),
                    StatRow(name: "스킬", value: " +독 내성 ")]
        let out = StatWinText.outgoing(rows, current: [StatValue(name: "레벨", value: "3")])
        #expect(out.map(\.name) == ["레벨", "힘", "스킬"])
        #expect(out.map(\.value) == ["+2", "", "+독 내성"])
    }
}

@Suite struct TextTests {
    @Test func cells() throws {
        let v: StatwinView = try decode(heroView)
        #expect(StatCell(v.columns[0], name: "레벨") == .changed("1", author: true, tip: "없음 → 1 (작가)"))
        #expect(StatCell(v.columns[1], name: "레벨") == .changed("3", author: false, tip: "1 → 3"))
        #expect(StatCell(v.columns[1], name: "HP") == .plain("100"))
        #expect(StatCell(v.columns[0], name: "스킬") == .plain(""))
        #expect(StatCell(v.columns[2], name: "HP") == .gone("100", tip: "100 → 지움 (승인 뒤 작가가 고침)"))
    }

    @Test func labels() throws {
        let v: StatwinView = try decode(heroView)
        #expect(StatWinText.recorded(v) == "2화까지 기록")
        #expect(StatWinText.recorded(try decode(emptyView)) == "기록 없음")
        #expect(StatWinText.columnTitle(0) == "시작")
        #expect(StatWinText.columnTitle(4) == "4화")
        #expect(StatWinText.count(0) == "")
        #expect(StatWinText.count(2) == "2항목")
        #expect(StatWinText.preview(try decode(emptyView)) == "(값이 있는 항목이 없어요)")
        #expect(StatWinText.presetOrder(["simple", "zeta", "growth", "game", "hunter"]) == ["game", "hunter", "simple", "growth", "zeta"])
        #expect(StatWinText.presetLabel("growth") == "스킬 · 특성 · 돈")
        #expect(StatWinText.presetLabel("hunter") == "헌터물")
    }

    @Test func pick() {
        let people = [StatPerson(id: "a", name: "가", count: 0, isMain: false),
                      StatPerson(id: "b", name: "나", count: 0, isMain: true),
                      StatPerson(id: "c", name: "다", count: 2, isMain: false)]
        #expect(StatWinText.pick("a", people: people) == "a")
        #expect(StatWinText.pick("", people: people) == "c")  // 상태창이 있는 인물 먼저
        #expect(StatWinText.pick("x", people: Array(people.prefix(2))) == "b")  // 다음은 주역
        #expect(StatWinText.pick("", people: [people[0]]) == "a")
        #expect(StatWinText.pick("", people: []) == "")
    }
}

@MainActor
@Suite struct ModelTests {
    @Test func loadsCharacterWithStats() async {
        let model = StatWinModel(project: "등대", source: FakeSource(project: project(), views: ["hero": heroView]))
        await model.load()
        #expect(model.selected == "hero")
        #expect(model.people.map(\.count) == [0, 2, 0])
        #expect(model.rows.map(\.name) == ["레벨", "스킬"])
        #expect(!model.dirty)
        #expect(model.template.hasPrefix("【 상태창 】"))
        #expect(model.loaded)
    }

    @Test func editsAndSaves() async {
        let source = FakeSource(project: project(), views: ["hero": heroView])
        let model = StatWinModel(project: "등대", source: source)
        await model.load()
        model.rows[0].value = "+2"
        #expect(model.dirty)
        model.addRow()
        model.rows[2].name = "칭호"
        model.rows[2].value = "검성"
        model.removeRow(model.rows[1].id)
        await model.save()
        let saved = await source.saved
        #expect(saved.count == 1)
        #expect(saved.first?.0 == "hero")
        #expect(saved.first?.1.map(\.name) == ["레벨", "칭호"])
        #expect(saved.first?.1.map(\.value) == ["5", "검성"])
        #expect(model.notice?.text == "상태창을 저장했어요")
        #expect(!model.dirty)  // 저장 뒤 서버 값으로 다시 채운다
    }

    @Test func presetAddsMissingNames() async {
        let model = StatWinModel(project: "등대", source: FakeSource(project: project(states: "[]"), views: [:]))
        await model.load()
        #expect(model.selected == "hero")  // 상태창이 없으면 주역
        #expect(model.rows.isEmpty)
        #expect(model.presetKeys == ["game", "simple"])
        model.rows = [StatRow(name: "레벨", value: "1")]
        model.applyPreset("simple")
        #expect(model.rows.map(\.name) == ["레벨", "스킬"])
        #expect(model.dirty)
    }

    @Test func templateUsesDefaultRowWhenBlank() async {
        let source = FakeSource(project: project(), views: ["hero": heroView])
        let model = StatWinModel(project: "등대", source: source)
        await model.load()
        await model.saveTemplate("[{name}]\n{rows}", row: "")
        let t = await source.templates
        #expect(t.first?.1 == "{key}: {value}")
        #expect(model.notice?.text == "서식을 저장했어요")
    }

    @Test func showsServerError() async {
        let err = CanonError.server(status: 400, message: "서식에 {rows} 가 있어야 항목이 들어갑니다", code: nil)
        let model = StatWinModel(project: "등대", source: FakeSource(project: project(), views: ["hero": heroView], failure: err))
        await model.load()
        await model.saveTemplate("없음", row: "")
        #expect(model.notice?.isError == true)
        #expect(model.notice?.text == err.errorDescription)
    }

    @Test func noCharacters() async {
        let model = StatWinModel(project: "등대", source: FakeSource(project: #"{"characters":[],"states":[]}"#, views: [:]))
        await model.load()
        #expect(!model.hasCharacters)
        #expect(model.view == nil)
        #expect(model.loaded)
    }

    @Test func copiedNotice() {
        let model = StatWinModel(project: "등대", source: FakeSource(project: project(), views: [:]))
        model.copied(true)
        #expect(model.notice?.text == "상태창을 복사했어요")
        model.copied(false)
        #expect(model.notice?.isError == true)
    }
}
