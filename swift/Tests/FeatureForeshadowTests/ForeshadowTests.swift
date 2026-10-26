import CanonAPI
import CanonCore
@testable import FeatureForeshadow
import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing

func clue(_ episode: Int, _ quote: String = "등대 불이 꺼졌다", by: String = "ai", broken: Bool = false) -> ForeshadowClue {
    ForeshadowClue(episode: episode, quote: quote, by: by, broken: broken)
}

func item(_ id: String = "fs-03-a1", planted: Int = 3, payoff: Int? = nil, status: ForeshadowItem.StatusPayload = .open,
          scope: ForeshadowScope = .arc, due: Int? = nil, plants: [ForeshadowClue] = [], payoffs: [ForeshadowClue] = [],
          lastSeen: Int = 3, planned: [Int] = [], overdue: Bool = false, stale: Bool = false, broken: Int = 0) -> ForeshadowItem {
    ForeshadowItem(id: id, description: "목걸이 문양", plantedEp: planted, payoffEp: payoff, status: status, scope: scope,
                   dueEp: due, plants: plants, payoffs: payoffs, lastSeen: lastSeen, planned: planned,
                   overdue: overdue, stale: stale, broken: broken)
}

func center(_ items: [ForeshadowItem], rate: Double? = nil, done: Int = 5, last: Int = 11) -> ForeshadowCenter {
    let resolved = items.filter { $0.status == .resolved }.count
    return ForeshadowCenter(total: items.count, open: items.count - resolved, resolved: resolved, rate: rate,
                            broken: items.reduce(0) { $0 + $1.broken }, overdue: items.filter(\.overdue).count,
                            stale: items.filter(\.stale).count, done: done, lastEp: last, items: items)
}

@Suite struct ForeshadowTextTests {
    @Test func rate() {
        #expect(ForeshadowText.rate(center([])) == "-")
        #expect(ForeshadowText.rate(center([item()], rate: 0.667)) == "67%")
        #expect(ForeshadowText.rate(center([item()], rate: 1)) == "100%")
    }

    @Test func meta() {
        #expect(ForeshadowText.meta(item(payoff: 9, status: .resolved, plants: [clue(3)], payoffs: [clue(9)]))
                == "3화 → 9화 회수 · 문장 2개")
        #expect(ForeshadowText.meta(item(due: 9, lastSeen: 5, planned: [7, 8]))
                == "3화에 심음 · 마지막 등장 5화 · 예정 9화 · 7, 8화 플롯에서 회수 예정 · 문장 0개")
        // 회수한 복선에는 플롯 회수 예정을 붙이지 않는다
        #expect(ForeshadowText.meta(item(payoff: 9, status: .resolved, planned: [10])) == "3화 → 9화 회수 · 문장 0개")
    }

    @Test func flagsAndAttention() {
        let x = item(due: 4, overdue: true, stale: true, broken: 2)
        #expect(ForeshadowText.flags(x) == ["예정 4화 지남", "50화 넘게 안 나옴", "끊어진 연결 2"])
        #expect(ForeshadowText.flags(item()).isEmpty)
        #expect(ForeshadowText.needsAttention(item(broken: 1)))
        #expect(!ForeshadowText.needsAttention(item()))
    }

    @Test func labels() {
        #expect(ForeshadowText.scope(.series) == "작품 끝까지")
        #expect(ForeshadowText.status(item(status: .resolved)) == "회수")
        let c = center([item(), item("b", status: .resolved), item("c", overdue: true)])
        #expect(ForeshadowTab.allCases.map { ForeshadowText.tab($0, c) } == ["열린 2", "회수한 1", "전체 3", "손볼 것 1"])
        #expect(ForeshadowText.now(c) == "세로선은 5화(마지막 반영)")
        #expect(ForeshadowText.brokenNote(center([item(broken: 2)])) == "본문을 고쳐 걸어 둔 문장이 사라진 연결이 2개 있어요. 다시 걸거나 정리하세요.")
    }

    @Test func shown() {
        let open = item(), done = item("b", status: .resolved, scope: .series), late = item("c", stale: true)
        #expect(ForeshadowText.shown(open, tab: .open, scope: nil))
        #expect(!ForeshadowText.shown(done, tab: .open, scope: nil))
        #expect(ForeshadowText.shown(done, tab: .resolved, scope: .series))
        #expect(!ForeshadowText.shown(done, tab: .all, scope: .arc))
        #expect(ForeshadowText.shown(late, tab: .attention, scope: nil))
        #expect(!ForeshadowText.shown(open, tab: .attention, scope: nil))
    }

    @Test func cluesInEpisodeOrderKeepingPlantsFirst() {
        let x = item(plants: [clue(5, "b"), clue(3, "a")], payoffs: [clue(5, "c", by: "author")])
        let rows = ForeshadowText.clues(x)
        #expect(rows.map(\.label) == ["3화 심음", "5화 심음", "5화 회수"])
        #expect(rows.last?.byAuthor == true)
    }

    @Test func fieldDefaults() {
        #expect(ForeshadowText.resolveEpisode(item(planted: 3), done: 5) == 5)
        #expect(ForeshadowText.resolveEpisode(item(planted: 7), done: 5) == 7)
        #expect(ForeshadowText.addEpisode(center([], done: 0)) == 1)
        #expect(ForeshadowText.number(" 9 ") == 9)
        #expect(ForeshadowText.number("") == nil)
        #expect(ForeshadowText.number("0") == nil)
    }
}

@Suite struct ForeshadowTrackTests {
    @Test func positions() {
        // 1~11화 줄에서 3화는 0.2, 5화(마지막 반영)는 0.4
        let t = ForeshadowTrack(item(due: 9, lastSeen: 4, planned: [8]), last: 11, done: 5)
        #expect(t.spanFrom == 0.2)
        #expect(t.spanTo == 0.4)
        #expect(t.now == 0.4)
        #expect(t.ticks.map(\.kind) == [.due, .planned])
        #expect(t.ticks.map(\.episode) == [9, 8])
        // 걸린 문장이 없으면 심은 화에 점 하나
        #expect(t.dots.map(\.kind) == [.plant])
    }

    @Test func resolvedWithoutPayoffClue() {
        let t = ForeshadowTrack(item(payoff: 7, status: .resolved, plants: [clue(3, broken: true)], planned: [8]), last: 11, done: 0)
        #expect(t.spanTo == 0.6)
        #expect(t.now == nil)
        #expect(t.ticks.isEmpty)
        #expect(t.dots.map(\.kind) == [.broken, .payoff])
    }

    @Test func singleEpisodeLine() {
        let t = ForeshadowTrack(item(planted: 1, lastSeen: 1), last: 1, done: 1)
        #expect(t.spanFrom == 0)
        #expect(t.now == 0)
    }
}

/// 받은 고치기를 적어 두는 가짜 서버.
final class FakeService: ForeshadowService, @unchecked Sendable {
    var result: ForeshadowCenter
    var error: CanonError?
    var changes: [ForeshadowChange] = []

    init(_ result: ForeshadowCenter) {
        self.result = result
    }

    func center() async throws -> ForeshadowCenter {
        result
    }

    func perform(_ change: ForeshadowChange) async throws {
        if let error { throw error }
        changes.append(change)
    }
}

@MainActor
@Suite struct ForeshadowModelTests {
    @Test func loadsAndFilters() async {
        let model = ForeshadowModel(service: FakeService(center([item(), item("b", status: .resolved)])))
        await model.load()
        #expect(model.shown.map(\.id) == ["fs-03-a1"])
        model.tab = .all
        #expect(model.shown.count == 2)
        model.scope = .part
        #expect(model.shown.isEmpty)
    }

    @Test func addClosesFormAndShowsOpenTab() async {
        let fake = FakeService(center([]))
        let model = ForeshadowModel(service: fake)
        model.adding = true
        model.tab = .resolved
        let ok = await model.apply(.add(description: "목걸이", episode: 3, scope: .arc, due: nil))
        #expect(ok)
        #expect(!model.adding)
        #expect(model.tab == .open)
        #expect(fake.changes == [.add(description: "목걸이", episode: 3, scope: .arc, due: nil)])
        #expect(model.busy == nil)
    }

    @Test func emptyDescriptionIsNotSent() async {
        let fake = FakeService(center([]))
        let model = ForeshadowModel(service: fake)
        let ok = await model.apply(.add(description: "  ", episode: 3, scope: .arc, due: nil))
        #expect(!ok)
        #expect(model.error == "복선 내용을 적어 주세요")
        #expect(fake.changes.isEmpty)
    }

    @Test func removeCollapsesItem() async {
        let fake = FakeService(center([item()]))
        let model = ForeshadowModel(service: fake)
        model.toggle("fs-03-a1")
        #expect(model.expanded == ["fs-03-a1"])
        await model.apply(.remove(id: "fs-03-a1"))
        #expect(model.expanded.isEmpty)
    }

    @Test func showsServerError() async {
        let fake = FakeService(center([item()]))
        fake.error = .server(status: 400, message: "회수 예정 화가 심은 화보다 앞입니다", code: nil)
        let model = ForeshadowModel(service: fake)
        let ok = await model.apply(.edit(id: "fs-03-a1", description: "x", scope: .arc, due: 1))
        #expect(!ok)
        #expect(model.error == "회수 예정 화가 심은 화보다 앞입니다")
    }

    @Test func progressText() {
        #expect(ForeshadowChange.prune.progress == "끊어진 연결 정리하는 중")
        #expect(ForeshadowChange.resolve(id: "a", episode: 3).progress == "회수로 표시하는 중")
    }
}

/// 요청을 본문까지 적어 두고 정해 둔 답을 돌려준다.
final class BodyTransport: ClientTransport, @unchecked Sendable {
    var sent: [(request: HTTPRequest, body: String)] = []
    let status: HTTPResponse.Status
    let body: String

    init(status: HTTPResponse.Status = .ok, body: String) {
        self.status = status
        self.body = body
    }

    func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        var text = ""
        if let body { text = try await String(collecting: body, upTo: 1 << 20) }
        sent.append((request, text))
        var response = HTTPResponse(status: status)
        response.headerFields[.contentType] = "application/json"
        return (response, HTTPBody(self.body))
    }
}

@Suite struct LiveForeshadowServiceTests {
    /// 서버 `foreshadows.center` 모양 그대로. 복선이 없을 때 rate 와 payoff_ep · due_ep 는 null 이다.
    @Test func readsNullsAsNil() async throws {
        let json = #"""
        {"total":1,"open":1,"resolved":0,"rate":null,"broken":0,"overdue":0,"stale":0,"done":2,"last_ep":12,
         "items":[{"id":"fs-01-a1","description":"목걸이","planted_ep":1,"payoff_ep":null,"status":"open","scope":"series",
                   "due_ep":null,"plants":[{"episode":1,"quote":"문양","by":"author","broken":false}],"payoffs":[],
                   "last_seen":1,"planned":[5],"overdue":false,"stale":false,"broken":0}]}
        """#
        let transport = BodyTransport(body: json)
        let service = LiveForeshadowService(server: CanonServer(config: .local, transport: transport), project: "등대")
        let c = try await service.center()
        #expect(c.rate == nil)
        #expect(c.items.first?.payoffEp == nil)
        #expect(c.items.first?.scope == .series)
        #expect(c.items.first?.planned == [5])
        #expect(transport.sent.first?.request.path == APIPath.project("등대", "foreshadows"))
    }

    @Test func editWithoutDueClearsIt() async throws {
        let transport = BodyTransport(status: .badRequest, body: #"{"detail":"복선이 없습니다: x"}"#)
        let service = LiveForeshadowService(server: CanonServer(config: .local, transport: transport), project: "등대")
        await #expect(throws: CanonError.server(status: 400, message: "복선이 없습니다: x", code: nil)) {
            try await service.perform(.edit(id: "x", description: " 새 내용 ", scope: .part, due: nil))
        }
        let sent = try #require(transport.sent.first)
        #expect(sent.request.method == .put)
        #expect(sent.request.path == APIPath.project("등대", "foreshadows/x"))
        let body = try JSONSerialization.jsonObject(with: Data(sent.body.utf8)) as? [String: Any]
        #expect(body?["description"] as? String == "새 내용")
        #expect(body?["scope"] as? String == "part")
        #expect(body?["clear_due"] as? Bool == true)
        #expect(body?["due_ep"] == nil)
    }

    @Test func dropClueSendsKey() async throws {
        let transport = BodyTransport(status: .badRequest, body: #"{"detail":"그 문장이 걸려 있지 않습니다"}"#)
        let service = LiveForeshadowService(server: CanonServer(config: .local, transport: transport), project: "등대")
        _ = try? await service.perform(.dropClue(id: "fs-01-a1", episode: 3, quote: "문양"))
        let sent = try #require(transport.sent.first)
        #expect(sent.request.method == .post)
        #expect(sent.request.path == APIPath.project("등대", "foreshadows/clues/remove"))
        let body = try JSONSerialization.jsonObject(with: Data(sent.body.utf8)) as? [String: Any]
        #expect(body?["foreshadow"] as? String == "fs-01-a1")
        #expect(body?["episode"] as? Int == 3)
    }
}
