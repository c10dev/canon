import Foundation

/// 관계도 좌표. 관계도는 760 × 540 판 위에 그리고 화면 크기에 맞게 늘인다 (웹 `CAST_W` · `CAST_H`).
public struct CastPoint: Hashable, Sendable {
    public var x: Double
    public var y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }

    func distance(_ o: CastPoint) -> Double { hypot(x - o.x, y - o.y) }
}

/// 관계도 배치와 선 모양. 관계 수치를 계산하지 않고, 서버가 준 친숙도로 자리만 잡는다 (웹 `castForce`).
public enum CastLayout {
    public static let width = 760.0
    public static let height = 540.0

    /// 결정적인 힘 배치. 등급별 고리에서 시작해 서로 밀고, 함께 겪은 만큼 당기고, 주역일수록 가운데로 끈다.
    public static func force(_ chars: [(id: String, tier: CastTier)], frames: [CastFrame]) -> [String: CastPoint] {
        let cx = width / 2
        let cy = height / 2
        let ring: [CastTier: Double] = [.main: 0.16, .support: 0.32, .minor: 0.43]
        var ids: [String] = []
        var pos: [String: CastPoint] = [:]
        let groups = CastTier.allCases.map { t in chars.filter { $0.tier == t } }
        for (gi, list) in groups.enumerated() {
            let tier = CastTier.allCases[gi]
            let r = (list.count == 1 && tier == .main && groups[1].isEmpty) ? 0 : ring[tier]! * min(width, height)
            for (i, c) in list.enumerated() {
                let a = Double(i) / Double(max(1, list.count)) * .pi * 2 - .pi / 2 + Double(gi) * 0.4
                pos[c.id] = CastPoint(x: cx + cos(a) * r * 1.35, y: cy + sin(a) * r)
                ids.append(c.id)
            }
        }
        // 모든 시점에서 가장 가까웠던 정도로 당긴다
        var weightKeys: [(String, String)] = []
        var weight: [String: Double] = [:]
        for f in frames {
            for t in f.ties where pos[t.source] != nil && pos[t.target] != nil {
                let (s, d) = t.source <= t.target ? (t.source, t.target) : (t.target, t.source)
                let k = "\(s)|\(d)"
                if weight[k] == nil { weightKeys.append((s, d)) }
                weight[k] = max(weight[k] ?? 0, 0.3 + t.familiarity)
            }
        }
        let n = ids.count
        guard n > 1 else { return pos }
        let pull: [CastTier: Double] = [.main: 0.04, .support: 0.015, .minor: 0.005]
        let k = (width * height / Double(n)).squareRoot() * 0.9
        var temp = 40.0
        for _ in 0..<260 {
            var disp = Dictionary(uniqueKeysWithValues: ids.map { ($0, (0.0, 0.0)) })
            for i in 0..<n {
                for j in (i + 1)..<n {
                    let a = pos[ids[i]]!
                    let b = pos[ids[j]]!
                    var dx = a.x - b.x
                    var dy = a.y - b.y
                    var d = hypot(dx, dy)
                    if d < 0.01 {
                        dx = 0.01 * Double(i + 1)
                        dy = 0.01
                        d = hypot(dx, dy)
                    }
                    let f = k * k / d
                    disp[ids[i]]!.0 += dx / d * f
                    disp[ids[i]]!.1 += dy / d * f
                    disp[ids[j]]!.0 -= dx / d * f
                    disp[ids[j]]!.1 -= dy / d * f
                }
            }
            for (s, t) in weightKeys {
                let w = weight["\(s)|\(t)"]!
                let dx = pos[s]!.x - pos[t]!.x
                let dy = pos[s]!.y - pos[t]!.y
                let d = max(0.01, hypot(dx, dy))
                let f = d * d / k * w * 0.6
                disp[s]!.0 -= dx / d * f
                disp[s]!.1 -= dy / d * f
                disp[t]!.0 += dx / d * f
                disp[t]!.1 += dy / d * f
            }
            for c in chars {
                let g = pull[c.tier]!
                disp[c.id]!.0 += (cx - pos[c.id]!.x) * g * k * 0.05
                disp[c.id]!.1 += (cy - pos[c.id]!.y) * g * k * 0.05
            }
            for id in ids {
                let (dx, dy) = disp[id]!
                let d = max(0.01, hypot(dx, dy))
                let p = pos[id]!
                pos[id] = CastPoint(
                    x: min(width - 70, max(70, p.x + dx / d * min(d, temp))),
                    y: min(height - 50, max(40, p.y + dy / d * min(d, temp)))
                )
            }
            temp = max(1.5, temp * 0.985)
        }
        return pos
    }

    /// 방향 간선 하나의 곡선 (시작, 조절점, 끝). 두 방향이 서로 반대쪽으로 휘어 겹치지 않는다.
    public struct Curve: Equatable, Sendable {
        public let start: CastPoint
        public let control: CastPoint
        public let end: CastPoint

        /// 곡선 위 점 (t = 0...1).
        public func point(_ t: Double) -> CastPoint {
            let u = 1 - t
            return CastPoint(
                x: u * u * start.x + 2 * u * t * control.x + t * t * end.x,
                y: u * u * start.y + 2 * u * t * control.y + t * t * end.y
            )
        }

        /// 점에서 곡선까지 거리 (어림).
        public func distance(_ p: CastPoint) -> Double {
            (0...16).map { point(Double($0) / 16).distance(p) }.min()!
        }
    }

    public static func curve(from a: CastPoint, to b: CastPoint, rFrom: Double, rTo: Double) -> Curve {
        let d = max(1, a.distance(b))
        let ux = (b.x - a.x) / d
        let uy = (b.y - a.y) / d
        let nx = -uy
        let ny = ux
        let bend = min(26, d * 0.12)
        return Curve(
            start: CastPoint(x: a.x + ux * (rFrom + 3) + nx * bend * 0.35, y: a.y + uy * (rFrom + 3) + ny * bend * 0.35),
            control: CastPoint(x: (a.x + b.x) / 2 + nx * bend, y: (a.y + b.y) / 2 + ny * bend),
            end: CastPoint(x: b.x - ux * (rTo + 4) + nx * bend * 0.35, y: b.y - uy * (rTo + 4) + ny * bend * 0.35)
        )
    }

    /// 쌍 긴장 점 반지름 (긴장 0~10).
    public static func tensionRadius(_ tension: Double) -> Double { 4 + tension * 0.55 }
}

/// 관계도에서 누른 곳 찾기: 인물 → 긴장 점 → 관계선 순서로 본다 (웹은 겹친 SVG 의 맨 위가 받는다).
public enum CastHit {
    public static func find(_ p: CastPoint, model: CastHitInput) -> CastSelection? {
        for c in model.nodes.reversed() where c.at.distance(p) <= max(c.radius, 22) {
            return .character(c.id)
        }
        for t in model.tensions.reversed() where t.at.distance(p) <= t.radius + 4 {
            return .pairOf(t.a, t.b)
        }
        let near = model.edges.map { ($0, $0.curve.distance(p)) }.filter { $0.1 <= 8 }.min { $0.1 < $1.1 }
        return near.map { .pairOf($0.0.source, $0.0.target) }
    }

    /// 인물 자리만 찾는다 (끌어 옮기기 시작).
    public static func node(_ p: CastPoint, model: CastHitInput) -> String? {
        model.nodes.reversed().first { $0.at.distance(p) <= max($0.radius, 22) }?.id
    }
}

/// 관계도 한 장에 그릴 것. 화면과 누르기 찾기가 같은 계산을 쓴다.
public struct CastHitInput: Sendable {
    public struct Node: Sendable {
        public let id: String
        public let at: CastPoint
        public let radius: Double
    }

    public struct Edge: Sendable {
        public let source: String
        public let target: String
        public let curve: CastLayout.Curve
        public let band: Int
        public let width: Double
    }

    public struct Tension: Sendable {
        public let a: String
        public let b: String
        public let at: CastPoint
        public let radius: Double
        public let hex: UInt32
    }

    public var nodes: [Node] = []
    public var edges: [Edge] = []
    public var tensions: [Tension] = []
}

extension CastModel {
    /// 지금 시점의 관계도: 보이는 인물, 방향 간선, 보통 이상 긴장 점.
    public func scene() -> CastHitInput {
        let pos = layout()  // 단역을 숨겨도 자리는 그대로 둔다. 숨김은 그리기에서만 거른다
        let shown = shownCharacters
        let ids = Set(shown.map(\.id))
        let radius: (String) -> Double = { CastTier(self.character($0)?.tier).radius }
        var out = CastHitInput()
        for t in frame?.ties ?? [] where ids.contains(t.source) && ids.contains(t.target) {
            guard let a = pos[t.source], let b = pos[t.target] else { continue }
            out.edges.append(.init(source: t.source, target: t.target,
                                   curve: CastLayout.curve(from: a, to: b, rFrom: radius(t.source), rTo: radius(t.target)),
                                   band: WarmthBand.index(t.warmth), width: 1.5 + 3.5 * t.familiarity))
        }
        for p in frame?.pairs ?? [] where ids.contains(p.a) && ids.contains(p.b) {
            guard let hex = CastText.tensionHex(p.tensionWord), let a = pos[p.a], let b = pos[p.b] else { continue }
            out.tensions.append(.init(a: p.a, b: p.b, at: CastPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2),
                                      radius: CastLayout.tensionRadius(p.tension), hex: hex))
        }
        for c in shown {
            guard let at = pos[c.id] else { continue }
            out.nodes.append(.init(id: c.id, at: at, radius: CastTier(c.tier).radius))
        }
        return out
    }

    /// 이 시점에 이미 나온 인물인지. 설정 단계 인물(first_ep 0)은 처음부터 있다.
    public func present(_ c: CastCharacter) -> Bool {
        guard let f = frame, let first = c.firstEp, first > 0 else { return true }
        return first <= f.episode
    }

    public func tie(_ s: String, _ t: String, in f: CastFrame? = nil) -> CastTie? {
        (f ?? frame)?.ties.first { $0.source == s && $0.target == t }
    }

    public func pair(_ a: String, _ b: String, in f: CastFrame? = nil) -> CastPair? {
        (f ?? frame)?.pairs.first { ($0.a == a && $0.b == b) || ($0.a == b && $0.b == a) }
    }

    /// 이 인물과 관계가 있는 상대 (지금 시점, 처음 나온 순서).
    public func partners(_ id: String) -> [String] {
        var seen: [String] = []
        for t in frame?.ties ?? [] where t.source == id || t.target == id {
            let o = t.source == id ? t.target : t.source
            if !seen.contains(o) { seen.append(o) }
        }
        return seen
    }
}
