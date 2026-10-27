import CanonAPI
import CanonCore
import CanonStore

/// 노선도의 자리 계산 (웹 `lineMap`). 가로가 화, 맨 위는 아크 · 기승전결 띠, 그 아래 메인 줄기, 줄기마다 한 줄.
/// 화면은 이 값으로 그리기만 하고 누른 자리도 여기서 찾는다 (`hit`). 단위는 점(pt), 웹의 px 과 같은 수.
public struct LineMapLayout: Sendable {
    /// 한 화의 가로 폭 (웹 `S.lineZoom`). fit 은 칸 폭에 맞춘다.
    public enum Zoom: Int, CaseIterable, Sendable {
        case fit = 0, narrow = 9, normal = 16, wide = 30

        public var label: String {
            switch self {
            case .fit: "맞춤"
            case .narrow: "좁게"
            case .normal: "보통"
            case .wide: "넓게"
            }
        }
    }

    public struct Point: Equatable, Sendable {
        public let x: Double
        public let y: Double
    }

    /// 줄 모양 (SVG path 의 M · L · C).
    public enum Segment: Equatable, Sendable {
        case move(Point)
        case line(Point)
        case curve(Point, Point, Point)
    }

    /// 위쪽 띠 하나. index 는 색 고르기 (0~3).
    public struct Band: Equatable, Sendable {
        public let x: Double
        public let width: Double
        public let label: String
        public let index: Int
    }

    public struct Dot: Equatable, Sendable {
        public let n: Int
        public let x: Double
        public let y: Double
        public let role: LineRules.Role
        public let status: EpisodeStatus
        public let label: String
    }

    /// 메인 줄의 화 점. gap 은 다른 줄기를 따라가 메인에서 비운 자리.
    public struct MainDot: Equatable, Sendable {
        public let n: Int
        public let x: Double
        public let status: EpisodeStatus
        public let gap: Bool
        public let label: String
    }

    public struct Lane: Equatable, Sendable {
        public let id: String
        public let title: String
        /// 이름 아래 줄: 종류 · 시점
        public let sub: String
        public let color: String
        public let y: Double
        /// 다른 시점 줄기는 점선
        public let past: Bool
        /// 붙은 화도 갈라짐 · 합류 화도 없으면 nil
        public let path: [Segment]?
        /// 합류 화가 없으면 줄 끝의 '열림' 글자 자리
        public let openX: Double?
        /// 메인 줄 위 갈라짐 · 합류 테두리 원의 x
        public let nodes: [Double]
        public let dots: [Dot]
    }

    public enum Hit: Equatable, Sendable {
        case episode(Int)
        case line(String)
    }

    public static let bandY = 8.0
    public static let mainY = 64.0
    public static let gap = 58.0

    public let total: Int
    public let left: Double
    public let step: Double
    public let width: Double
    public let height: Double
    /// 화 점 반지름
    public let radius: Double
    public let bands: [Band]
    public let ticks: [Int]
    /// 플롯이 있는 데까지 실선
    public let mainSolid: (Double, Double)?
    /// 그 뒤 총 화수까지 흐린 선
    public let mainFuture: (Double, Double)?
    public let lanes: [Lane]
    public let mainDots: [MainDot]

    /// wrapWidth 는 노선도 칸의 폭. 좁은 화면(600 미만)은 이름 칸도 줄인다.
    public init(_ p: Project, wrapWidth: Double, zoom: Zoom = .fit, serial: Bool = false) {
        let lines = LineRules.lines(p)
        let total = LineRules.total(p)
        let left = wrapWidth < 600 ? 96.0 : 168.0
        let step = zoom == .fit ? max(4, min(30, (wrapWidth - left - 24) / Double(total))) : Double(zoom.rawValue)
        let x = { (n: Int) in left + (Double(n) - 0.5) * step }
        let mainY = Self.mainY
        let laneY = { (i: Int) in mainY + Self.gap * Double(i + 1) }
        let r = max(3.5, min(7, step / 3.2))
        let eps = p.episodes ?? []
        let byNo = Dictionary(eps.map { ($0.plot.number, $0) }, uniquingKeysWith: { a, _ in a })
        let lastPlot = eps.map(\.plot.number).max() ?? 0
        self.total = total
        self.left = left
        self.step = step
        self.width = left + Double(total) * step + 24
        self.height = laneY(lines.count) - Self.gap + 46
        self.radius = r

        // 위쪽 띠: 장편은 아크, 단편은 기승전결
        let order: [Components.Schemas.Act.NamePayload] = [.기, .승, .전, .결]
        let raw: [(Int, Int, String, Int)] = serial
            ? (p.storyArcs ?? []).map { ($0.startEp, $0.endEp, "아크 \($0.number) \($0.title)", ($0.number - 1) % 4) }
            : (p.arc ?? []).map { ($0.startEp, $0.endEp, $0.name.rawValue, order.firstIndex(of: $0.name) ?? 0) }
        bands = raw.map { a, b, label, i in
            Band(x: left + Double(a - 1) * step, width: max(2, Double(b - a + 1) * step - 2), label: label, index: i)
        }

        let every = step >= 24 ? 1 : step >= 14 ? 5 : 10
        ticks = (1...total).filter { $0 == 1 || $0 % every == 0 }

        mainSolid = lastPlot > 0 ? (x(1), x(min(lastPlot, total))) : nil
        mainFuture = lastPlot < total ? (x(max(1, lastPlot)), x(total)) : nil

        let status = { (n: Int) in EpisodeStatus(rawValue: byNo[n]?.status?.rawValue ?? "draft") ?? .draft }
        lanes = lines.enumerated().map { i, s in
            let y = laneY(i)
            let (lo, hi) = LineRules.span(p, s)
            let title = LineRules.title(s)
            let when = s.when ?? ""
            let sub = LineRules.kind(s).rawValue + (when.isEmpty ? "" : " · " + when)
            let color = LineRules.color(p, s.id)
            guard lo != 0 else {
                return Lane(id: s.id, title: title, sub: sub, color: color, y: y, past: LineRules.isPast(s), path: nil, openX: nil, nodes: [], dots: [])
            }
            let xs = x(lo)
            let xe = x(hi)
            let k = min(step * 0.9, 22)
            let branch = s.branchEp ?? 0
            let join = s.joinEp ?? 0
            var d: [Segment] = []
            if branch != 0 {
                let xb = x(branch)
                d = [.move(Point(x: xb, y: mainY)), .curve(Point(x: xb, y: y), Point(x: xb, y: y), Point(x: xb + k, y: y))]
            } else {
                d = [.move(Point(x: xs, y: y))]
            }
            if join != 0 {
                let xj = x(join)
                d += [.line(Point(x: max(xj - k, xs), y: y)), .curve(Point(x: xj, y: y), Point(x: xj, y: y), Point(x: xj, y: mainY))]
            } else {
                d.append(.line(Point(x: xe + step * 0.6, y: y)))
            }
            let dots = LineRules.episodes(p, s.id).map { n, role in
                let e = byNo[n]
                let st = status(n)
                return Dot(n: n, x: x(n), y: y, role: role, status: st,
                           label: "\(n)화 \(e?.plot.title ?? "") · \(s.title ?? "")\(role == .thread ? " (장면)" : "") · \(st.label)")
            }
            return Lane(id: s.id, title: title, sub: sub, color: color, y: y, past: LineRules.isPast(s), path: d,
                        openX: join == 0 ? xe + step * 0.6 + 6 : nil,
                        nodes: [branch, join].filter { $0 != 0 }.map(x), dots: dots)
        }

        // 메인 화 점 (줄기를 따라가는 화는 메인에서 비운다)
        mainDots = lastPlot < 1 ? [] : (1...min(lastPlot, total)).compactMap { n in
            guard let e = byNo[n] else { return nil }
            let side = LineRules.line(p, e.plot.storyline ?? "")
            let st = status(n)
            let label = "\(n)화 \(e.plot.title) · \(side.map { "\($0.title ?? "") 줄기를 따라감" } ?? "메인") · \(st.label)"
            return MainDot(n: n, x: x(n), status: st, gap: side != nil, label: label)
        }
    }

    public func x(_ n: Int) -> Double { left + (Double(n) - 0.5) * step }

    /// 누른 자리: 화 점(세로 24, 가로는 옆 화와 겹치지 않는 폭까지)이나 왼쪽 줄기 이름 칸 (웹 `hit` · `lm-lane`).
    /// 줄기 줄의 점이 메인 점보다 먼저다.
    public func hit(_ px: Double, _ py: Double) -> Hit? {
        let w = min(24, step) / 2
        for lane in lanes {
            if px >= 4 && px <= left - 8 && abs(py - lane.y) <= 17 { return .line(lane.id) }
            if let d = lane.dots.first(where: { abs(px - $0.x) <= w && abs(py - $0.y) <= 12 }) { return .episode(d.n) }
        }
        if abs(py - Self.mainY) <= 12, let d = mainDots.first(where: { !$0.gap && abs(px - $0.x) <= w }) { return .episode(d.n) }
        return nil
    }

    /// 화면 읽기 프로그램에 읽어 줄 노선도 요약: 줄마다 이름 · 범위 · 붙은 화.
    public static func summary(_ p: Project) -> [String] {
        let main = (p.episodes ?? []).filter { ($0.plot.storyline ?? "").isEmpty }.map(\.plot.number).sorted()
        var out = ["메인 줄기: " + (main.isEmpty ? "화 없음" : "\(LineRules.rangeText(main))화")]
        for s in LineRules.lines(p) {
            let eps = LineRules.episodes(p, s.id)
            let range = LineRules.rangeLabel(p, s)
            let list = eps.map { "\($0.n)화\($0.role == .thread ? " 장면" : "")" }.joined(separator: ", ")
            out.append("\(LineRules.kind(s).rawValue) \(LineRules.title(s))\(range.isEmpty ? "" : " (\(range))"): \(list.isEmpty ? "붙은 화 없음" : list)")
        }
        return out
    }
}
