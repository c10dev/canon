import CanonAPI
import CanonCore
import Foundation
import Observation

public typealias CastSummary = Components.Schemas.CastView
public typealias CastFrame = Components.Schemas.CastFrame
public typealias CastTie = Components.Schemas.CastTie
public typealias CastPair = Components.Schemas.CastPair
public typealias CastTimelineRow = Components.Schemas.CastTimelineRow
public typealias CastAppearance = Components.Schemas.CastAppearance
public typealias CastCharacter = Components.Schemas.Character
public typealias CastProject = Components.Schemas.Project
public typealias CastEvent = Components.Schemas.StoryEvent

/// 인물 화면이 받는 것: 작품 전체(인물 설정 · 플롯 · 사건 원본)와 서버 계산값(`/cast`). 시험에서는 가짜로 바꾼다.
public protocol CastSource: Sendable {
    func project(_ name: String) async throws -> CastProject
    func cast(_ name: String) async throws -> CastSummary
}

/// 끌어 옮긴 관계도 배치를 기기에 남기는 곳. 웹은 브라우저 localStorage(`canon-cast-pos:<작품>`)에 둔다.
public protocol CastLayoutStore {
    func load(_ project: String) -> [String: CastPoint]
    func save(_ project: String, _ positions: [String: CastPoint])
}

/// 고른 인물이나 두 사람. 쌍은 id 를 정렬해 둔다 (웹 `p:<a>|<b>`).
public enum CastSelection: Hashable, Sendable {
    case character(String)
    case pair(String, String)

    public static func pairOf(_ a: String, _ b: String) -> CastSelection {
        a <= b ? .pair(a, b) : .pair(b, a)
    }

    public func includes(_ id: String) -> Bool {
        switch self {
        case let .character(c): c == id
        case let .pair(a, b): a == id || b == id
        }
    }
}

/// 인물 · 관계도 화면 상태. 관계 수치는 서버(`canon/cast.py`)가 계산한 프레임을 그대로 쓴다.
@MainActor
@Observable
public final class CastModel {
    public enum Tab: String, Sendable { case graph, table }

    public let name: String
    public private(set) var project: CastProject?
    public private(set) var cast: CastSummary?
    public private(set) var loading = false
    public private(set) var error: String?
    /// frames 의 몇 번째 시점을 보는지
    public private(set) var frameIndex = 0
    public var selection: CastSelection?
    public var tab: Tab = .graph
    /// 단역도 관계도에 그린다
    public var showMinor = true
    /// 타임라인 전체 보기
    public var showAllTimeline = false
    /// 추이 그래프 전체 보기 (시점이 40개를 넘을 때)
    public var chartAll = false
    /// 말로 · 숫자로. 처음 값은 작품 설정(`settings.show_numbers`)이고, 바꿔도 이 기기 화면에서만 바뀐다
    public var showNumbers = false
    /// 끌어 옮긴 자리
    public private(set) var positions: [String: CastPoint] = [:]
    public private(set) var playing = false
    /// 재생 간격 (웹 900ms). 시험에서 줄인다
    public var playInterval: Duration = .milliseconds(900)

    private let source: any CastSource
    private let store: any CastLayoutStore
    private var playTask: Task<Void, Never>?
    private var layoutCache: (key: String, pos: [String: CastPoint])?

    public init(name: String, source: any CastSource, store: any CastLayoutStore) {
        self.name = name
        self.source = source
        self.store = store
    }

    // MARK: 불러오기

    public func load() async {
        stop()
        loading = true
        defer { loading = false }
        let same = cast != nil
        let wasLast = same && frameIndex == frames.count - 1  // 마지막 시점을 보고 있었으면 새로 반영한 화로 따라간다
        do {
            async let p = source.project(name)
            async let c = source.cast(name)
            let (project, cast) = try await (p, c)
            self.project = project
            self.cast = cast
            error = nil
        } catch {
            self.error = CanonError.message(error)
            return
        }
        if !same || wasLast || frameIndex >= frames.count { frameIndex = max(0, frames.count - 1) }
        if !same {
            showAllTimeline = false
            positions = store.load(name)
            showNumbers = project?.settings?.showNumbers ?? false
        }
        if let s = selection, valid(s) { return }
        let first = characters.first { $0.tier ?? .main == .main } ?? characters.first
        selection = first.map { .character($0.id) }
    }

    private func valid(_ s: CastSelection) -> Bool {
        switch s {
        case let .character(id): character(id) != nil
        case let .pair(a, b): character(a) != nil && character(b) != nil
        }
    }

    // MARK: 읽기

    public var characters: [CastCharacter] { project?.characters ?? [] }
    public var frames: [CastFrame] { cast?.frames ?? [] }
    public var frame: CastFrame? { frames.isEmpty ? nil : frames[min(frameIndex, frames.count - 1)] }

    public func character(_ id: String) -> CastCharacter? { characters.first { $0.id == id } }

    /// 인물 이름. 후보 인물도 찾고, 없으면 id (웹 `charName`).
    public func name(_ id: String) -> String {
        let c = character(id) ?? project?.castCandidates?.first { $0.id == id }
        guard let c else { return id }
        return c.name.isEmpty ? id : c.name
    }

    public func episode(_ n: Int) -> Components.Schemas.Episode? {
        project?.episodes?.first { $0.plot.number == n }
    }

    public func label(_ f: CastFrame?) -> String {
        guard let f else { return "" }
        return CastText.frameLabel(f.episode, title: episode(f.episode)?.plot.title)
    }

    public func appearances(_ id: String) -> [CastAppearance] {
        cast?.appearances.additionalProperties[id] ?? []
    }

    public func timeline(_ id: String) -> [CastTimelineRow] {
        cast?.timelines.additionalProperties[id] ?? []
    }

    /// 두 사람 사이 관계 사건 (작품 원본), 화 순서.
    public func events(_ a: String, _ b: String) -> [CastEvent] {
        (project?.events ?? [])
            .filter { ($0.actor == a && $0.target == b) || ($0.actor == b && $0.target == a) }
            .enumerated().sorted { ($0.element.episode, $0.offset) < ($1.element.episode, $1.offset) }.map(\.element)
    }

    public var hasMinor: Bool { characters.contains { $0.tier == .minor } }

    /// 관계도에 그릴 인물. 단역을 숨겨도 고른 인물은 그린다.
    public var shownCharacters: [CastCharacter] {
        characters.filter { showMinor || $0.tier != .minor || selection == .character($0.id) }
    }

    /// 플롯 총 화수 (등장 줄 · 등장표 너비).
    public var totalEpisodes: Int {
        max(project?.meta?.targetEpisodes ?? 0, project?.episodes?.map(\.plot.number).max() ?? 0, 1)
    }

    public var isSerial: Bool { project?.meta?.form == .serial }

    // MARK: 시점

    public func step(_ d: Int) {
        stop()
        go(frameIndex + d)
    }

    public func go(_ i: Int) {
        stop()
        frameIndex = min(max(0, frames.count - 1), max(0, i))
    }

    public var playLabel: String {
        if playing { return "멈춤" }
        return frameIndex >= frames.count - 1 ? "처음부터 재생" : "여기서 재생"
    }

    /// 재생 · 멈춤. 끝에 있을 때만 처음으로 돌아가고, 아니면 지금 시점부터 이어 간다.
    public func togglePlay() {
        if playing {
            stop()
            return
        }
        guard frames.count > 1 else { return }
        if frameIndex >= frames.count - 1 { frameIndex = 0 }
        playing = true
        let interval = playInterval
        playTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: interval)
                guard let self, !Task.isCancelled, self.playing else { return }
                if self.frameIndex >= self.frames.count - 1 {
                    self.playing = false
                    return
                }
                self.frameIndex += 1
            }
        }
    }

    public func stop() {
        playTask?.cancel()
        playTask = nil
        playing = false
    }

    // MARK: 고르기

    public func pick(_ s: CastSelection) {
        selection = s
        showAllTimeline = false
    }

    /// 등장표에서 인물 이름을 누르면 관계도에서 그 인물을 연다.
    public func open(_ id: String) {
        tab = .graph
        selection = .character(id)
    }

    // MARK: 배치

    /// 인물 자리. 모든 시점의 간선을 합쳐 한 번만 계산해서 재생해도 자리가 흔들리지 않는다. 끌어 옮긴 자리가 앞선다.
    public func layout() -> [String: CastPoint] {
        let key = characters.map { "\($0.id):\(($0.tier ?? .main).rawValue)" }.joined(separator: ",") + "#\(frames.count)"
        if layoutCache?.key != key {
            layoutCache = (key, CastLayout.force(characters.map { ($0.id, CastTier($0.tier)) }, frames: frames))
        }
        var pos = layoutCache!.pos
        for (id, p) in positions where pos[id] != nil { pos[id] = p }
        return pos
    }

    /// 끄는 동안 자리를 옮긴다. 저장은 `endMove` 에서.
    public func move(_ id: String, to p: CastPoint) {
        positions[id] = CastPoint(x: min(CastLayout.width - 30, max(30, p.x)), y: min(CastLayout.height - 30, max(30, p.y)))
    }

    public func endMove() {
        store.save(name, positions)
    }

    public func resetPositions() {
        positions = [:]
        store.save(name, [:])
    }
}

/// 서버에서 작품 전체(ETag)와 인물 화면 계산값을 받는다.
public struct LiveCastSource: CastSource {
    let server: CanonServer
    let loader: ProjectLoader

    public init(server: CanonServer) {
        self.server = server
        self.loader = ProjectLoader(server: server)
    }

    public func project(_ name: String) async throws -> CastProject {
        try await loader.load(name)
    }

    public func cast(_ name: String) async throws -> CastSummary {
        switch try await server.call({ try await $0.castView(path: .init(name: name)) }) {
        case let .ok(ok):
            return try ok.body.json
        case let .unprocessableContent(bad):
            throw CanonError.badResponse(String(describing: bad))
        case let .undocumented(status, payload):
            throw await CanonServer.failure(status, payload)
        }
    }
}

/// 배치를 `UserDefaults` 에 둔다. 키는 웹 localStorage 와 같은 `canon-cast-pos:<작품>`.
public struct DefaultsLayoutStore: CastLayoutStore {
    public init() {}

    static func key(_ project: String) -> String { "canon-cast-pos:\(project)" }

    public func load(_ project: String) -> [String: CastPoint] {
        guard let data = UserDefaults.standard.data(forKey: Self.key(project)),
              let raw = try? JSONDecoder().decode([String: [Double]].self, from: data) else { return [:] }
        return raw.compactMapValues { $0.count == 2 ? CastPoint(x: $0[0], y: $0[1]) : nil }
    }

    public func save(_ project: String, _ positions: [String: CastPoint]) {
        if positions.isEmpty {
            UserDefaults.standard.removeObject(forKey: Self.key(project))
            return
        }
        let raw = positions.mapValues { [$0.x, $0.y] }
        if let data = try? JSONEncoder().encode(raw) { UserDefaults.standard.set(data, forKey: Self.key(project)) }
    }
}
