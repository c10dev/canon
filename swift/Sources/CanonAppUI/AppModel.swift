import CanonAPI
import CanonCore
import CanonStore
import FeatureBranches
import FeatureProjects
import Foundation
import Observation

/// 앱 전체 상태: 어느 서버에 붙었나, 어느 작품 · 화면을 보나, 작업 목록.
@MainActor
@Observable
public final class AppModel {
    public private(set) var server: CanonServer
    public private(set) var projects: ProjectsModel
    /// 연 작품의 이름. 바꿀 때는 `open` 을 쓴다.
    public private(set) var project: String?
    /// 연 작품. 화면들이 함께 쓴다.
    public private(set) var document: ProjectDocument?
    /// 연 작품의 갈래 집안. 작품 머리 띠 · 사이드바 · 작품 홈 · 갈래 비교가 함께 쓴다.
    public private(set) var branches: BranchModel?
    /// 열린 갈래 만들기 칸.
    public var branchForm: BranchDraft?
    private var loader: ProjectLoader
    public var screen: Screen = .home
    /// 작업 목록, 검토를 기다리는 결과. 연 작품과 함께 바뀐다.
    public private(set) var jobs: JobCenter
    private let defaults: UserDefaults
    static let serverKey = "canon.server"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let saved = defaults.string(forKey: Self.serverKey).flatMap(ServerConfig.parse) ?? .local
        let server = CanonServer(config: saved)
        self.server = server
        self.loader = ProjectLoader(server: server)
        self.projects = ProjectsModel(source: LiveProjectListing(server: server))
        self.jobs = JobCenter(service: server)
    }

    /// 작품을 연다 (nil 이면 작품 목록으로). 저장하지 않은 변경이 있어도 닫는다. 묻는 일은 화면이 한다.
    public func open(_ name: String?) {
        project = name
        document = name.map { ProjectDocument(name: $0, store: loader) }
        branches = name.map { BranchModel(project: $0, service: LiveBranchService(server: server)) }
        branchForm = nil
        screen = .home
        let doc = document
        let fam = branches
        Task { await jobs.open(doc) }
        Task { await fam?.load() }
    }

    /// 갈래 만들기 칸을 연다. n 을 주지 않으면 마지막으로 반영한 화부터 (웹 `branchOpen`).
    public func openBranchForm(_ n: Int?) {
        guard let project, let p = document?.project else { return }
        branchForm = BranchDraft(project: project, from: n, last: BranchText.lastFinal(p))
    }

    /// 만든 갈래를 연다. 본문을 비웠으면 집필, 남겼으면 상태 승인으로 간다 (웹 `branchCreate`).
    public func openBranch(_ made: BranchModel.Created) {
        open(made.name)
        screen = made.keep ? .review : .write
        branches?.notice = made.notice
    }

    /// 서버 주소를 바꾼다. 읽을 수 없는 주소면 false.
    @discardableResult
    public func connect(_ text: String) -> Bool {
        guard let config = ServerConfig.parse(text) else { return false }
        defaults.set(config.baseURL.absoluteString, forKey: Self.serverKey)
        server = CanonServer(config: config)
        loader = ProjectLoader(server: server)
        projects = ProjectsModel(source: LiveProjectListing(server: server))
        jobs = JobCenter(service: server)
        open(nil)
        return true
    }
}
