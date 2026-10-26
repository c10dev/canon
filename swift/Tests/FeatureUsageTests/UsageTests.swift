import CanonCore
import FeatureUsage
import Foundation
import Testing

/// 서버 응답 JSON 을 생성 타입으로 읽는다 (서버가 보내는 모양 그대로 시험한다).
func decode<T: Decodable>(_ json: String, as _: T.Type = T.self) -> T {
    try! JSONDecoder().decode(T.self, from: Data(json.utf8))
}


func group(_ extra: String, calls: Int = 1, cost: Double = 0, failed: Int = 0, input: Int = 0, out: Int = 0, unpriced: Int = 0) -> String {
    #"{"calls": \#(calls), "failed": \#(failed), "retries": 0, "in": \#(input), "out": \#(out), "cached": 0, "cost": \#(cost), "saved": 0.0, "unpriced": \#(unpriced), "seconds": 1.0, "batch": 0, \#(extra)}"#
}

func call(_ changes: [String: Any] = [:]) -> UsageCall {
    var row: [String: Any] = [
        "at": "2026-10-26T14:05:09+09:00", "project": "등대", "episode": 3, "stage": "write", "task": "write", "source": "web",
        "backend": "gemini", "model": "gemini-4-argon", "batch": false, "attempt": 1, "in": 12000, "out": 3000, "thought": 500,
        "cached": 4000, "seconds": 12.34, "ok": true, "error": "", "chars": 5000, "blocks": [["인물", 3000], ["그 밖", 2000]],
        "cost": 0.0514, "saved": 0.0,
    ]
    row.merge(changes) { _, new in new }
    return try! JSONDecoder().decode(UsageCall.self, from: JSONSerialization.data(withJSONObject: row))
}

func summary(calls: Int = 3, recent: Int = 3, trouble: Int = 0, troubleTotal: Int = 0, byDay: String = "[]",
             unpriced: String = "[]", projects: String = #"["등대"]"#) -> UsageSummary {
    let one = #"{"at": "2026-10-26T14:05:09+09:00", "project": "등대", "stage": "write", "task": "", "source": "", "backend": "gemini", "model": "m", "batch": false, "attempt": 1, "in": 1, "out": 1, "thought": 0, "cached": 0, "ok": true, "error": "", "saved": 0.0}"#
    return decode(#"""
    {"days": 30, "since": "2026-09-27", "project": null, "projects": \#(projects),
     "total": {"calls": \#(calls), "failed": 0, "retries": 0, "in": 0, "out": 0, "cached": 0, "cost": 0.0, "saved": 0.0, "unpriced": 0, "seconds": 0.0, "batch": 0, "wasted": 0.0},
     "by_day": \#(byDay), "by_project": [], "by_episode": [], "by_stage": [], "by_model": [], "by_source": [],
     "unpriced": \#(unpriced), "trouble": [\#(Array(repeating: one, count: trouble).joined(separator: ","))],
     "recent": [\#(Array(repeating: one, count: recent).joined(separator: ","))],
     "trouble_total": \#(troubleTotal), "limit": 60, "billing_url": "https://aistudio.google.com/usage", "prices_url": "u"}
    """#)
}

let priceJSON = #"""
{"rows": [
  {"model": "gemini-4-argon", "since": "", "input": 2.0, "output": 10.0, "cached": 0.1, "batch_input": 1.0, "batch_output": 5.0, "note": "", "custom": false, "current": true, "upcoming": false},
  {"model": "gemini-4-argon", "since": "2026-12-01", "input": 4.0, "output": 20.0, "cached": 0.2, "batch_input": 2.0, "batch_output": 10.0, "note": "2026-12-01 인상 예고", "custom": false, "current": false, "upcoming": true}
 ], "checked": "2026-10-22", "url": "https://ai.google.dev/gemini-api/docs/pricing", "billing_url": "https://aistudio.google.com/usage"}
"""#

@Suite struct NumberTextTests {
    @Test func usd() {
        #expect(UsageText.usd(nil) == "가격 모름")
        #expect(UsageText.usd(0) == "$0")
        #expect(UsageText.usd(0.00004) == "$0.0001 미만")
        #expect(UsageText.usd(0.0514) == "$0.0514")
        #expect(UsageText.usd(1234.5) == "$1,234.50")
    }

    @Test func tokens() {
        #expect(UsageText.tok(9800) == "9,800")
        #expect(UsageText.tok(34_600) == "35K")
        #expect(UsageText.tok(1_250_000) == "1.3M")  // JS toFixed 처럼 가운데 값은 올린다
        #expect(UsageText.fixed(0.125, 2) == "0.13")
        #expect(UsageText.tok(12_000_000) == "12M")
        #expect(UsageText.number(1_234_567) == "1,234,567")
    }

    @Test func plainNumbers() {
        #expect(UsageText.plain(2) == "2")
        #expect(UsageText.plain(0.375) == "0.375")
    }
}

@Suite struct UsageTextTests {
    @Test func projectNamesAndChoices() {
        let titles = ["lighthouse": "등대", "same": "same", "blank": ""]
        #expect(UsageText.projectName("lighthouse", titles: titles) == "등대 (lighthouse)")
        #expect(UsageText.projectName("same", titles: titles) == "same")
        #expect(UsageText.projectName("gone", titles: titles) == "gone")
        #expect(UsageText.projectChoices(titles: ["b": ""], recorded: ["a", "b"], current: "c") == ["a", "b", "c"])
    }

    @Test func emptyNotice() {
        #expect(UsageText.empty(project: "", titles: [:]) == "이 기간의 AI 호출 기록이 없어요. 이 화면이 생긴 뒤의 호출부터 기록해요 (mock 은 기록하지 않음).")
        #expect(UsageText.empty(project: "a", titles: ["a": "등대"]).hasPrefix("이 기간에 등대 (a)의 AI 호출 기록이 없어요."))
    }

    @Test func tiles() {
        let t: UsageTotal = decode(#"{"calls": 1234, "failed": 2, "retries": 1, "in": 120000, "out": 3500, "cached": 4000, "cost": 0.5, "saved": 0.0, "unpriced": 3, "seconds": 1.0, "batch": 0, "wasted": 0.01}"#)
        let tiles = UsageText.tiles(t)
        #expect(tiles.map(\.title) == ["추정 비용", "호출", "입력 토큰", "출력 토큰", "배치로 아낀 비용", "실패 · 재시도 비용"])
        #expect(tiles[0].note == "가격 모르는 호출 3번 제외")
        #expect(tiles[1].value == "1,234번")
        #expect(tiles[1].note == "실패 2 · 다시 요청 1")
        #expect(tiles[2].value == "120K")
        #expect(tiles[2].note == "캐시 4,000 (싸게 매겨짐)")
        #expect(tiles[4].note == "배치 안 씀")
        #expect(tiles[5].value == "$0.0100")
    }

    @Test func tables() {
        let rows: [UsageGroup] = decode("[\(group(#""backend": "local", "model": """#, cost: 0)), \(group(#""backend": "gemini", "model": "x""#, cost: 3, unpriced: 1))]")
        let model = UsageText.tableRows(.model, rows, titles: [:])
        #expect(model[0].label == "(이름 없음)")
        #expect(model[0].sub == "로컬 · 0원")
        #expect(model[1].sub == "Gemini")
        #expect(model[1].share == 100)
        #expect(model[1].cost == "$3.00")
        let unknown: [UsageGroup] = decode("[\(group(#""stage": "zzz""#, unpriced: 1))]")
        #expect(UsageText.tableRows(.stage, unknown, titles: [:])[0].cost == "가격 모름")
        #expect(UsageText.tableRows(.stage, unknown, titles: [:])[0].label == "zzz")
        let projects: [UsageGroup] = decode("[\(group(#""project": """#)), \(group(#""project": "a""#))]")
        let p = UsageText.tableRows(.project, projects, titles: ["a": "등대"])
        #expect(p[0].sub == "작품 밖 (연구 서버 점검 등)")
        #expect(p[0].project == nil)
        #expect(p[1].label == "등대 (a)")
        #expect(p[1].project == "a")
        let eps: [UsageGroup] = decode("[\(group(#""project": "a", "episode": 4"#))]")
        #expect(UsageText.tableRows(.episode, eps, titles: [:])[0].label == "4화")
        #expect(UsageTableKind.source.column == "어디서 불렀나")
        #expect(UsageTableKind.stage.column == "단계")
        #expect(UsageTableKind.episode.note == "화가 정해지지 않은 호출(설정, 기획 등)은 빠져요")
    }

    @Test func callRows() {
        let kst = TimeZone(identifier: "Asia/Seoul")!
        let r = UsageText.callRow(call(), timeZone: kst)
        #expect(r.when == "2026.10.26 14:05")
        #expect(r.place == "등대 3화")
        #expect(r.task == "본문")
        #expect(r.detail == "본문 · 화면에서 직접")
        #expect(r.output == "3,500")
        #expect(r.thought == "생각 500")
        #expect(r.cached == "캐시 4,000")
        #expect(r.seconds == "12.3초")
        #expect(r.stateLabel == "성공")
        #expect(r.blocksTop == "인물 60% · 그 밖 40%")
        #expect(r.blocks == ["인물 3,000자 · 60%", "그 밖 2,000자 · 40%"])
        #expect(r.promptChars == "프롬프트 5,000자")

        let bare = UsageText.callRow(call(["project": "", "episode": NSNull(), "task": "", "stage": "zzz", "seconds": NSNull(), "cost": NSNull(),
                                           "blocks": NSNull(), "ok": false, "error": String(repeating: "가", count: 70)]))
        #expect(bare.place == "-")
        #expect(bare.task == "-")
        #expect(bare.detail == "zzz · 화면에서 직접")
        #expect(bare.seconds == "-")
        #expect(bare.cost == "가격 모름")
        #expect(bare.blocksTop.isEmpty)
        #expect(bare.stateLabel == "실패")
        #expect(bare.errorShort == String(repeating: "가", count: 60) + "…")
        #expect(UsageText.callRow(call(["attempt": 2])).stateLabel == "다시 요청")
    }

    @Test func moreLines() {
        let u = summary(calls: 300, recent: 60, trouble: 2, troubleTotal: 2)
        let showAll = UsageText.moreLine(u, list: .recent, all: 60, shown: 20, limit: 60)
        #expect(showAll.action == .showAll)
        #expect(showAll.button == "최근 60건 보기 (기간 전체 300건 중)")
        let more = UsageText.moreLine(u, list: .recent, all: 60, shown: 60, limit: 60)
        #expect(more.text == "최근 60건을 보여요 (기간 전체 300건 중).")
        #expect(more.button == "더 불러오기")
        #expect(UsageText.moreLine(u, list: .recent, all: 60, shown: 60, limit: 1000).button == nil)
        #expect(UsageText.moreLine(u, list: .trouble, all: 2, shown: 2, limit: 60).text == "최근 2건을 보여요.")
        #expect(UsageText.tabs(u).map(\.label) == ["최근 호출", "실패 · 재시도 2"])
    }
}

@Suite struct UsageChartTests {
    let cal: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Asia/Seoul")!
        return c
    }()
    let today = ISO8601DateFormatter().date(from: "2026-10-26T05:00:00Z")!

    @Test func fillsEmptyDays() {
        let days: [UsageGroup] = decode("[\(group(#""day": "2026-10-24""#, calls: 2, cost: 0.5, failed: 1, input: 12000, out: 300)), \(group(#""day": "2026-10-26""#, cost: 0.25))]")
        let c = UsageChart.make(days, days: 7, today: today, calendar: cal)
        #expect(c.bars.map(\.key) == ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"])
        #expect(c.bars.map(\.height) == [0, 0, 0, 0, 100, 0, 50])
        #expect(!c.weekly)
        #expect(c.title == "날짜별 추정 비용")
        #expect(c.scale == "가장 많은 날 $0.5000 · 막대를 누르면 자세히")
        #expect(c.first == "10-20")
        #expect(c.last == "10-26")
        #expect(c.tip("2026-10-24") == "2026-10-24: $0.5000 · 호출 2번 · 입력 12K / 출력 300 · 실패 1")
        #expect(c.tip("2026-10-25") == "2026-10-25: 호출 없음")
    }

    @Test func countsCallsWhenFree() {
        let days: [UsageGroup] = decode("[\(group(#""day": "2026-10-26""#, calls: 4)), \(group(#""day": "2026-10-25""#, calls: 1))]")
        let c = UsageChart.make(days, days: 1, today: today, calendar: cal)
        #expect(c.bars.count == 1)
        #expect(c.title == "날짜별 호출 수")
        #expect(c.scale == "가장 많은 날 4번 · 막대를 누르면 자세히")
        let small = UsageChart.make(days, days: 7, today: today, calendar: cal)
        #expect(small.bars.first { $0.key == "2026-10-25" }?.height == 25)
    }

    @Test func groupsWeeks() {
        let days: [UsageGroup] = decode("[\(group(#""day": "2026-10-26""#, calls: 1)), \(group(#""day": "2026-10-25""#, calls: 2))]")
        #expect(!UsageChart.make(days, days: 90, today: today, calendar: cal).weekly)
        let narrow = UsageChart.make(days, days: 90, today: today, narrow: true, calendar: cal)
        #expect(narrow.weekly)
        #expect(narrow.bars.count == 13)
        #expect(narrow.title == "주별 호출 수")
        // 7일씩 기간 첫날부터 묶는다: 마지막 주는 10-21~10-26
        #expect(narrow.bars.last?.key == "2026-10-21")
        #expect(narrow.bars.last?.tip == "2026-10-21 주: $0 · 호출 3번 · 입력 0 / 출력 0")
        // '전체'는 첫 기록 날부터
        let old: [UsageGroup] = decode("[\(group(#""day": "2026-01-01""#))]")
        let all = UsageChart.make(old, days: 0, today: today, calendar: cal)
        #expect(all.weekly)
        #expect(all.bars.first?.key == "2026-01-01")
    }

    @Test func keyboard() {
        let c = UsageChart.make([], days: 7, today: today, calendar: cal)
        #expect(c.move(.left, from: nil) == "2026-10-26")
        #expect(c.move(.right, from: nil) == "2026-10-20")
        #expect(c.move(.right, from: "2026-10-26") == "2026-10-26")
        #expect(c.move(.home, from: "2026-10-23") == "2026-10-20")
        #expect(c.scale == "가장 많은 날 1번 · 막대를 누르면 자세히")
    }
}

/// 가짜 서버. 받은 요청을 적어 둔다.
final class FakeUsage: UsageSource, @unchecked Sendable {
    var summaryCalls: [(days: Int, project: String, limit: Int)] = []
    var priceCalls = 0
    var saved: [PriceIn]?
    var resetCount = 0
    var result = FeatureUsageTests.summary()
    var error: CanonError?

    func summary(days: Int, project: String, limit: Int) async throws -> UsageSummary {
        if let error { throw error }
        summaryCalls.append((days, project, limit))
        return result
    }

    func prices() async throws -> PriceTable {
        priceCalls += 1
        return decode(priceJSON)
    }

    func savePrices(_ rows: [PriceIn]) async throws -> PriceTable {
        saved = rows
        return decode(priceJSON)
    }

    func resetPrices() async throws -> PriceTable {
        resetCount += 1
        return decode(priceJSON)
    }

    func projectTitles() async -> [String: String] { ["등대": "밤의 등대"] }
}

@MainActor
@Suite struct UsageModelTests {
    @Test func loadsOnce() async {
        let fake = FakeUsage()
        let model = UsageModel(source: fake, project: "등대")
        await model.load()
        #expect(fake.summaryCalls.map(\.project) == ["등대"])
        #expect(fake.summaryCalls.first?.days == 30)
        #expect(model.titles["등대"] == "밤의 등대")
        #expect(model.rows.count == 2)
        await model.setDays(0)
        await model.setProject("")
        #expect(fake.summaryCalls.map(\.days) == [30, 0, 0])
        #expect(fake.summaryCalls.last?.project == "")
        #expect(fake.priceCalls == 1)  // 가격표는 처음 한 번만 받는다
    }

    @Test func listsAndLoadsMore() async {
        let fake = FakeUsage()
        fake.result = summary(calls: 300, recent: 60)
        let model = UsageModel(source: fake)
        await model.load()
        #expect(model.calls.shown.count == 20)
        #expect(model.moreLine?.action == .showAll)
        model.expand()
        #expect(model.calls.shown.count == 60)
        #expect(model.moreLine?.action == .loadMore)
        await model.loadMore()
        #expect(fake.summaryCalls.last?.limit == 260)
    }

    @Test func showsOffline() async {
        let fake = FakeUsage()
        fake.error = .offline
        let model = UsageModel(source: fake)
        await model.load()
        #expect(model.notice?.text == CanonError.offline.errorDescription)
        #expect(model.notice?.isError == true)
        #expect(model.busy == nil)
    }

    @Test func editsPrices() async {
        let fake = FakeUsage()
        let model = UsageModel(source: fake)
        await model.load()
        #expect(model.rows[0].status == "지금")
        #expect(model.rows[1].status == "예고")
        #expect(model.rows[0].fixed)
        #expect(!model.canReset)
        #expect(!model.dirty)
        // 가격 없는 모델에서 '가격 넣기': 새 줄, 같은 이름이면 그 줄
        let id = model.addModel("gemini-x")
        #expect(model.rows.count == 3)
        #expect(model.addModel("gemini-x") == id)
        #expect(model.rows.count == 3)
        #expect(model.rows[2].custom == nil)
        #expect(!model.rows[2].fixed)
        #expect(model.dirty)
        #expect(model.checkSave() == .confirm("gemini-x의 입력이나 출력 가격이 0원이에요. 비용이 0원으로 계산돼요. 이대로 저장할까요?"))
        model.edit(id) { $0.input = "1.5"; $0.output = "6" }
        #expect(model.rows[2].placeholder(.cached) == "1.5")
        #expect(model.rows[2].placeholder(.batchInput) == "0.75")
        #expect(model.rows[2].placeholder(.batchOutput) == "3")
        #expect(model.checkSave() == .ready)
        model.addRow()
        #expect(model.checkSave() == .ready)  // 이름도 값도 없는 줄은 보내지 않는다
        let blank = model.rows[3].id
        model.edit(blank) { $0.since = "2027-01-01" }
        #expect(model.checkSave() == .blocked("4번째 줄에 모델 이름을 적으세요. 이름이 없으면 그 줄은 저장되지 않아요", blank))
        model.removeRow(blank)
        model.edit(id) { $0.cached = "x" }
        #expect(model.checkSave() == .blocked("3번째 줄의 가격을 숫자로 적으세요", id))
        model.edit(id) { $0.cached = "" }
        await model.save()
        #expect(fake.saved?.count == 3)
        #expect(fake.saved?[2].model == "gemini-x")
        #expect(fake.saved?[2].input == 1.5)
        #expect(fake.saved?[2].cached == nil)
        #expect(fake.saved?[0].cached == 0.1)
        #expect(model.notice?.text == "가격표를 저장했어요. 비용을 다시 계산했어요")
        #expect(!model.dirty)
        #expect(model.rows.count == 2)
        #expect(fake.summaryCalls.count == 2)  // 저장 뒤 비용을 다시 받는다
    }

    @Test func cancelsAndResets() async {
        let fake = FakeUsage()
        let model = UsageModel(source: fake)
        await model.load()
        model.addRow()
        model.cancelEdits()
        #expect(model.rows.count == 2)
        #expect(!model.dirty)
        await model.reset()
        #expect(fake.resetCount == 1)
        #expect(model.notice?.text == "기본 가격표로 되돌렸어요")
        #expect(UsageModel.resetQuestion == "고친 가격을 모두 지우고 기본 가격표로 되돌릴까요?")
    }
}
