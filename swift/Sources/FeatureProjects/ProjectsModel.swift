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

    /// 갈래 집안끼리 묶은 목록.
    public var groups: [ProjectGroup] { ProjectGroup.make(cards) }
}

/// 작품 목록의 카드 한 장과 그 아래 갈래 (웹 `branches.js` `branchGroups`).
public struct ProjectGroup: Equatable, Sendable {
    public struct Branch: Equatable, Sendable {
        public let card: ProjectCard
        /// 본편에서 갈라진 갈래는 0, 그 갈래에서 갈라진 갈래는 1
        public let depth: Int
    }

    public let card: ProjectCard
    public let branches: [Branch]

    /// 같은 집안(family)을 본편 카드 하나로 묶고, 갈래는 부모 바로 뒤에 갈라진 화 순서로 늘어놓는다.
    /// 목록 순서(최근에 고친 작품부터)는 집안에서 가장 최근에 고친 작품 자리를 따른다.
    /// 본편을 찾지 못한 갈래나 혼자 남은 작품은 따로 선 카드로 보인다.
    public static func make(_ list: [ProjectCard]) -> [ProjectGroup] {
        var families: [String: [ProjectCard]] = [:]
        for x in list { if let b = x.branch { families[b.family, default: []].append(x) } }
        var out: [ProjectGroup] = []
        var used: Set<String> = []
        for x in list where !used.contains(x.name) {
            let fam = x.branch.flatMap { families[$0.family] } ?? []
            guard fam.count >= 2, let main = fam.first(where: { ($0.branch?.parent ?? "").isEmpty }) else {
                used.insert(x.name)
                out.append(ProjectGroup(card: x, branches: []))
                continue
            }
            func kids(_ id: String) -> [ProjectCard] {
                fam.filter { $0.branch?.parent == id }.sorted {
                    let (a, b) = ($0.branch?.fromEp ?? 0, $1.branch?.fromEp ?? 0)
                    return a != b ? a < b : $0.name.localizedCompare($1.name) == .orderedAscending
                }
            }
            var branches: [Branch] = []
            func walk(_ y: ProjectCard, _ depth: Int) {
                for k in kids(y.branch?.id ?? "") where !used.contains(k.name) {
                    used.insert(k.name)
                    branches.append(Branch(card: k, depth: depth))
                    walk(k, depth + 1)
                }
            }
            used.insert(main.name)
            walk(main, 0)
            out.append(ProjectGroup(card: main, branches: branches))
        }
        return out
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

    /// 갈래가 있는 본편 카드: '장편 · 3화 쓰기 대기 · 갈래 2개'
    public static func summary(_ c: ProjectCard, branches: Int) -> String {
        summary(c) + (branches > 0 ? " · 갈래 \(branches)개" : "")
    }

    /// 갈래 줄의 이름: 갈래 이름, 없으면 폴더 이름.
    public static func branchTitle(_ c: ProjectCard) -> String {
        let label = c.branch?.label ?? ""
        return label.isEmpty ? c.name : label
    }

    /// 갈래 줄: '5화부터 · 4 / 20화 · 5화 쓰기 대기'
    public static func branchDetail(_ c: ProjectCard) -> String {
        "\(c.branch?.fromEp ?? 0)화부터 · \(c.finalized) / \(c.episodes)화 · \(next(c))"
    }

    /// 갈래 줄의 폴더: '폴더 등대-B안 · 고친 때 2026.10.26 14:05'
    public static func folder(_ c: ProjectCard) -> String {
        "폴더 \(c.name)" + (c.updatedAt.isEmpty ? "" : " · 고친 때 \(KoreanText.dateTime(c.updatedAt))")
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
