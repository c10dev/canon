import CanonAPI
import CanonCore
import CanonStore

/// 이야기 줄기 화면이 서버에 시키는 일. 둘 다 작품을 바꾸고, 화면은 끝나면 작품을 다시 받는다. 시험에서는 가짜로 바꾼다.
/// 줄기 고치기와 화 붙이기는 작품 저장(`ProjectDocument.save`)으로 한다 (웹과 같다).
public protocol LinesService: Sendable {
    /// AI 제안을 고른 화와 함께 더한다 (`POST .../storylines/apply`)
    func apply(_ proposal: StorylineProposal, episodes: [Int], threads: [Int]) async throws
    /// 줄기를 지우고 붙은 화를 메인으로 되돌린다 (`DELETE .../storylines/{sid}`)
    func remove(_ id: String) async throws
}

/// 서버의 줄기 엔드포인트 (`web.py` 의 apply_storyline · remove_storyline).
public struct LiveLinesService: LinesService {
    let server: CanonServer
    let project: String

    public init(server: CanonServer, project: String) {
        self.server = server
        self.project = project
    }

    /// 앱이 보낸 칸이 서버 모델과 맞지 않는다 (422). 대개 서버와 앱의 판이 다르다.
    static let invalid = CanonError.server(status: 422, message: "입력 형식이 맞지 않아요", code: nil)

    public func apply(_ proposal: StorylineProposal, episodes: [Int], threads: [Int]) async throws {
        let name = project
        let body = Components.Schemas.StorylineIn(proposal: proposal, episodes: episodes, threads: threads)
        switch try await server.call({ try await $0.applyStoryline(path: .init(name: name), body: .json(body)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }

    public func remove(_ id: String) async throws {
        let name = project
        switch try await server.call({ try await $0.removeStoryline(path: .init(name: name, sid: id)) }) {
        case .ok: return
        case .unprocessableContent: throw Self.invalid
        case let .undocumented(status, payload): throw await CanonServer.failure(status, payload)
        }
    }
}
