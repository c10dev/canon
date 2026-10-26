import CanonAPI
import CanonCore
import Observation

public typealias ProjectCard = Components.Schemas.ProjectCard

/// 작품 목록을 가져오는 곳. 시험에서는 가짜로 바꾼다.
public protocol ProjectListing: Sendable {
    func listProjects() async throws -> [ProjectCard]
}

/// 작품 목록 화면 상태.
@MainActor
@Observable
public final class ProjectsModel {
    public private(set) var cards: [ProjectCard] = []
    public private(set) var loading = false
    public private(set) var error: String?
    private let source: any ProjectListing

    public init(source: any ProjectListing) {
        self.source = source
    }

    public func load() async {
        loading = true
        defer { loading = false }
        do {
            cards = try await source.listProjects()
            error = nil
        } catch {
            self.error = CanonError.message(error)
        }
    }
}

/// 작품 카드 문구. 웹 화면(`app.js` 의 `viewProjects`, `projectNext`)과 같다.
public enum ProjectCardText {
    public static func title(_ c: ProjectCard) -> String { c.title.isEmpty ? c.name : c.title }

    /// '3 / 20화'
    public static func progress(_ c: ProjectCard) -> String { "\(c.finalized) / \(c.episodes)화" }

    /// 다음 할 일: '3화 상태 승인 대기', '완결', '플롯 없음'
    public static func next(_ c: ProjectCard) -> String {
        if c.openEp == 0 {
            if c.planned > 0 && c.finalized >= c.episodes { return "완결" }
            return c.planned > 0 ? "\(c.planned + 1)화부터 플롯 만들기" : "플롯 없음"
        }
        return "\(c.openEp)화 \(EpisodeStatus(rawValue: c.openStatus)?.waiting ?? "")"
    }

    /// '장편 · 3화 쓰기 대기'
    public static func summary(_ c: ProjectCard) -> String {
        "\(c.form == "serial" ? "장편" : "단편") · \(next(c))"
    }

    /// '로맨스 · 폴더 등대 · 고친 때 2026.10.26 14:05'
    public static func detail(_ c: ProjectCard) -> String {
        let genre = c.genre.isEmpty ? "장르 미정" : c.genre
        let when = c.updatedAt.isEmpty ? "" : " · 고친 때 \(KoreanText.dateTime(c.updatedAt))"
        return "\(genre) · 폴더 \(c.name)\(when)"
    }
}

/// 서버에서 작품 목록을 받는다.
public struct LiveProjectListing: ProjectListing {
    let server: CanonServer

    public init(server: CanonServer) {
        self.server = server
    }

    public func listProjects() async throws -> [ProjectCard] {
        switch try await server.call({ try await $0.listProjects() }) {
        case let .ok(ok):
            return try ok.body.json
        case let .undocumented(status, payload):
            throw await CanonServer.failure(status, payload)
        }
    }
}
