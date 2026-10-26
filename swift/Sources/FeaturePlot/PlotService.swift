import CanonAPI
import CanonCore
import CanonStore

/// 플롯 화면이 서버에 시키는 일. 모두 작품을 바꾸고, 화면은 끝나면 작품을 다시 받는다. 시험에서는 가짜로 바꾼다.
public protocol PlotService: Sendable {
    func confirm(_ n: Int) async throws
    func unconfirm(_ n: Int) async throws
    func applySeries(_ plan: SeriesPlan) async throws
    func applyArc(_ proposal: ArcProposal) async throws
    func removeLastArc() async throws
    /// kind 는 "arc" 나 "part"
    func applyRecap(kind: String, number: Int, summary: String) async throws
    /// 새 화를 넣고 무엇을 옮겼는지 돌려준다
    func insert(at: Int, title: String, summary: String, storyline: String) async throws -> [String]
    func remove(_ n: Int) async throws -> [String]
}

/// 서버의 플롯 엔드포인트 (`web.py` 의 confirm_plot · apply_series · apply_arc · apply_recap · insert_episode 등).
public struct LivePlotService: PlotService {
    let server: CanonServer
    let project: String

    public init(server: CanonServer, project: String) {
        self.server = server
        self.project = project
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func confirm(_ n: Int) async throws {
        let name = project
        switch try await server.call({ try await $0.confirmPlot(path: .init(name: name, n: n)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func unconfirm(_ n: Int) async throws {
        let name = project
        switch try await server.call({ try await $0.unconfirmPlot(path: .init(name: name, n: n)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func applySeries(_ plan: SeriesPlan) async throws {
        let name = project
        switch try await server.call({ try await $0.applySeries(path: .init(name: name), body: .json(plan)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func applyArc(_ proposal: ArcProposal) async throws {
        let name = project
        switch try await server.call({ try await $0.applyArc(path: .init(name: name), body: .json(proposal)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func removeLastArc() async throws {
        let name = project
        switch try await server.call({ try await $0.removeLastArc(path: .init(name: name)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func applyRecap(kind: String, number: Int, summary: String) async throws {
        let name = project
        switch try await server.call({
            try await $0.applyRecap(path: .init(name: name, kind: kind, number: number), body: .json(.init(summary: summary)))
        }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func insert(at: Int, title: String, summary: String, storyline: String) async throws -> [String] {
        let name = project
        let body = Components.Schemas.InsertIn(at: at, title: title, summary: summary, storyline: storyline)
        switch try await server.call({ try await $0.insertEpisode(path: .init(name: name), body: .json(body)) }) {
        case let .ok(ok): return try ok.body.json.notes
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func remove(_ n: Int) async throws -> [String] {
        let name = project
        switch try await server.call({ try await $0.removeEpisode(path: .init(name: name, n: n)) }) {
        case let .ok(ok): return try ok.body.json.notes
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
