import CanonAPI
import CanonCore
import FeatureProjects
import Foundation
import Observation

/// 앱 전체 상태: 어느 서버에 붙었나, 어느 작품 · 화면을 보나, 작업 목록.
@MainActor
@Observable
public final class AppModel {
    public private(set) var server: CanonServer
    public private(set) var projects: ProjectsModel
    public var project: String?
    public var screen: Screen = .home
    public private(set) var jobs = JobTracker()
    public private(set) var notice: (text: String, isError: Bool)?
    private let defaults: UserDefaults
    static let serverKey = "canon.server"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let saved = defaults.string(forKey: Self.serverKey).flatMap(ServerConfig.parse) ?? .local
        let server = CanonServer(config: saved)
        self.server = server
        self.projects = ProjectsModel(source: LiveProjectListing(server: server))
    }

    /// 서버 주소를 바꾼다. 읽을 수 없는 주소면 false.
    @discardableResult
    public func connect(_ text: String) -> Bool {
        guard let config = ServerConfig.parse(text) else { return false }
        defaults.set(config.baseURL.absoluteString, forKey: Self.serverKey)
        server = CanonServer(config: config)
        projects = ProjectsModel(source: LiveProjectListing(server: server))
        project = nil
        jobs = JobTracker()
        return true
    }

    public func dismissNotice() { notice = nil }

    /// 작업 목록을 계속 지켜본다. 진행 중인 작업이 없으면 천천히 묻는다
    /// (웹 화면은 창에 돌아올 때 묻지만, 앱은 다른 기기에서 시작한 작업도 알아채게 15초마다 묻는다).
    public func watchJobs() async {
        while !Task.isCancelled {
            await refreshJobs()
            try? await Task.sleep(for: jobs.pollInterval ?? .seconds(15))
        }
    }

    public func refreshJobs() async {
        do {
            let list = try await server.listJobs()
            for event in jobs.received(list) {
                if let n = JobText.notice(event, currentProject: project) { notice = n }
            }
        } catch {
            jobs.failed()
        }
    }
}
