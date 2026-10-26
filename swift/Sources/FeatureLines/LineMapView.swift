#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 노선도 카드: 폭 고르기, 노선도, 범례 (웹 `lineMap`). 점을 누르면 그 화 플롯으로, 줄기 이름을 누르면 그 줄기를 고친다.
struct LineMapCard: View {
    @Bindable var model: LinesModel
    let project: Project
    let openPlot: (Int) -> Void

    var body: some View {
        LinesCard {
            HStack {
                Text("노선도").font(.title3.bold())
                Spacer()
                Picker("노선도 폭", selection: $model.zoom) {
                    ForEach(LineMapLayout.Zoom.allCases, id: \.self) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .fixedSize()
            }
            GeometryReader { geo in
                let layout = LineMapLayout(project, wrapWidth: geo.size.width, zoom: model.zoom, serial: model.document.serial)
                ScrollView(.horizontal) {
                    LineMapCanvas(layout: layout, selected: model.selected?.id) { hit in
                        switch hit {
                        case let .episode(n): openPlot(n)
                        case let .line(id): model.select(id)
                        }
                    }
                    .frame(width: layout.width, height: layout.height)
                }
            }
            .frame(height: Self.height(LineRules.lines(project).count))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("이야기 줄기 노선도")
            .accessibilityValue(LineMapLayout.summary(project).joined(separator: ". "))
            legend
            Text("점을 누르면 그 화 플롯을 열고, 왼쪽 줄기 이름을 누르면 줄기를 고쳐요. 메인에서 갈라지는 화와 합류하는 화는 메인 줄 위의 테두리 원이에요.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    /// 노선도 높이는 줄기 수로만 정해진다 (`LineMapLayout.height`).
    static func height(_ lines: Int) -> CGFloat {
        LineMapLayout.mainY + LineMapLayout.gap * Double(lines) + 46
    }

    private var legend: some View {
        Flow(spacing: 12) {
            ForEach(EpisodeStatus.allCases, id: \.self) { s in
                HStack(spacing: 4) {
                    StatusDot(status: s).frame(width: 14, height: 14)
                    Text(s == .written ? "본문 있음" : s.label)
                }
            }
            HStack(spacing: 4) {
                Circle().stroke(Color.secondary, lineWidth: 2).frame(width: 9, height: 9)
                Text("작은 점: 메인 화에 끼어드는 장면")
            }
            HStack(spacing: 4) {
                Path { $0.move(to: .init(x: 0, y: 1)); $0.addLine(to: .init(x: 16, y: 1)) }
                    .stroke(Color.secondary, style: StrokeStyle(lineWidth: 2, dash: [4, 3])).frame(width: 16, height: 2)
                Text("다른 시점(과거 · 외전)")
            }
        }
        .font(.caption)
    }
}

/// 범례의 상태 점: 상태를 색만이 아니라 모양으로도 보인다 (웹 `statusKey`).
struct StatusDot: View {
    let status: EpisodeStatus

    var body: some View {
        Canvas { ctx, size in
            let r = min(size.width, size.height) / 2 - 1
            LineMapCanvas.drawDot(&ctx, center: CGPoint(x: size.width / 2, y: size.height / 2), r: r, status: status,
                                  stroke: .secondary, width: 1.2, dashed: status == .draft)
        }
        .accessibilityHidden(true)
    }
}

/// 노선도 그림 (웹 `lineMap` 의 SVG). 자리는 모두 `LineMapLayout` 이 정한다.
struct LineMapCanvas: View {
    let layout: LineMapLayout
    let selected: String?
    let tap: (LineMapLayout.Hit) -> Void

    var body: some View {
        Canvas { ctx, _ in draw(&ctx) }
            .contentShape(Rectangle())
            .gesture(SpatialTapGesture().onEnded { v in
                if let hit = layout.hit(v.location.x, v.location.y) { tap(hit) }
            })
    }

    private func draw(_ ctx: inout GraphicsContext) {
        let mainY = LineMapLayout.mainY
        let r = layout.radius
        // 위쪽 띠
        for b in layout.bands {
            let rect = CGRect(x: b.x + 1, y: LineMapLayout.bandY, width: b.width, height: 22)
            let color = Color.lineBand(b.index)
            ctx.fill(Path(roundedRect: rect, cornerRadius: 5), with: .color(color.opacity(0.16)))
            var inner = ctx
            inner.clip(to: Path(rect.insetBy(dx: 3, dy: 0)))
            inner.draw(Text(b.label).font(.caption2.weight(.semibold)).foregroundStyle(color),
                       at: CGPoint(x: b.x + 7, y: LineMapLayout.bandY + 11), anchor: .leading)
        }
        // 화 번호 눈금
        for n in layout.ticks {
            ctx.draw(Text("\(n)").font(.caption2).foregroundStyle(.secondary), at: CGPoint(x: layout.x(n), y: layout.height - 14))
        }
        // 메인 줄기
        ctx.draw(Text("메인 줄기").font(.callout.bold()), at: CGPoint(x: 12, y: mainY), anchor: .leading)
        if let (a, b) = layout.mainFuture {
            ctx.stroke(line(a, b, mainY), with: .color(.secondary.opacity(0.35)), style: StrokeStyle(lineWidth: 3, lineCap: .round, dash: [2, 5]))
        }
        if let (a, b) = layout.mainSolid {
            ctx.stroke(line(a, b, mainY), with: .color(.secondary), style: StrokeStyle(lineWidth: 4, lineCap: .round))
        }

        // 갈라지는 줄기
        for lane in layout.lanes {
            let color = Color(lineHex: lane.color)
            let sel = lane.id == selected
            let y = lane.y
            if sel {
                ctx.fill(Path(roundedRect: CGRect(x: 4, y: y - 17, width: layout.left - 12, height: 34), cornerRadius: 6),
                         with: .color(color.opacity(0.14)))
            }
            ctx.fill(Path(roundedRect: CGRect(x: 12, y: y - 6, width: 12, height: 12), cornerRadius: 3), with: .color(color))
            var label = ctx
            label.clip(to: Path(CGRect(x: 0, y: y - 20, width: layout.left - 14, height: 40)))
            label.draw(Text(lane.title).font(.callout.weight(sel ? .bold : .regular)), at: CGPoint(x: 30, y: y - 7), anchor: .leading)
            label.draw(Text(lane.sub).font(.caption2).foregroundStyle(.secondary), at: CGPoint(x: 30, y: y + 9), anchor: .leading)
            guard let segs = lane.path else {
                ctx.draw(Text("아직 붙은 화가 없어요. 아래에서 화를 붙이세요.").font(.caption).foregroundStyle(.secondary),
                         at: CGPoint(x: layout.left + 6, y: y), anchor: .leading)
                continue
            }
            // 고른 줄은 굵고 끝이 둥글어 틈을 넓혀야 점선으로 보인다
            let dash: [CGFloat] = lane.past ? (sel ? [10, 9] : [7, 5]) : []
            ctx.stroke(path(segs), with: .color(color), style: StrokeStyle(lineWidth: sel ? 5 : 3, lineCap: .round, lineJoin: .round, dash: dash))
            if let ox = lane.openX {
                ctx.draw(Text("열림").font(.caption2).foregroundStyle(.secondary), at: CGPoint(x: ox, y: y), anchor: .leading)
            }
            for nx in lane.nodes {
                let c = circle(nx, mainY, r + 1.5)
                ctx.fill(c, with: .style(.background))
                ctx.stroke(c, with: .color(color), lineWidth: 2.5)
            }
            for d in lane.dots {
                if d.role == .thread {
                    let c = circle(d.x, y, r - 1)
                    ctx.fill(c, with: .style(.background))
                    ctx.stroke(c, with: .color(color), lineWidth: 2)
                } else {
                    Self.drawDot(&ctx, center: CGPoint(x: d.x, y: y), r: r + 1, status: d.status, stroke: color, width: 3, dashed: d.status == .draft)
                }
            }
        }

        // 메인 화 점 (줄기를 따라가는 화는 메인에서 비운다)
        for d in layout.mainDots {
            if d.gap {
                ctx.fill(circle(d.x, mainY, max(1.5, r - 1.5)), with: .style(.background))
                ctx.stroke(circle(d.x, mainY, max(1.5, r - 1.5)), with: .color(.secondary.opacity(0.5)), lineWidth: 1)
            } else {
                Self.drawDot(&ctx, center: CGPoint(x: d.x, y: mainY), r: r, status: d.status, stroke: .secondary, width: 2, dashed: d.status == .draft)
            }
        }
    }

    /// 화 점: 바탕 + 상태 모양 (반영 완료는 가운데를 채운 점, 본문 있음은 아래 반을 채운 점, 초안은 점선 테두리, 웹 `statusMark`).
    static func drawDot(_ ctx: inout GraphicsContext, center: CGPoint, r: Double, status: EpisodeStatus, stroke: Color, width: Double, dashed: Bool) {
        let c = Path(ellipseIn: CGRect(x: center.x - r, y: center.y - r, width: 2 * r, height: 2 * r))
        ctx.fill(c, with: .style(.background))
        if let fill = Color.lineDotFill(status) { ctx.fill(c, with: .color(fill)) }
        ctx.stroke(c, with: .color(stroke), style: StrokeStyle(lineWidth: width, dash: dashed ? [3, 2] : []))
        let k = r * 0.5
        switch status {
        case .finalized:
            ctx.fill(Path(ellipseIn: CGRect(x: center.x - k, y: center.y - k, width: 2 * k, height: 2 * k)), with: .color(.lineFinalized))
        case .written:
            var half = Path()
            half.move(to: CGPoint(x: center.x - k, y: center.y))
            half.addArc(center: center, radius: k, startAngle: .degrees(180), endAngle: .degrees(0), clockwise: true)
            half.closeSubpath()
            ctx.fill(half, with: .color(.lineWritten))
        default:
            break
        }
    }

    private func line(_ a: Double, _ b: Double, _ y: Double) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: a, y: y))
        p.addLine(to: CGPoint(x: b, y: y))
        return p
    }

    private func circle(_ x: Double, _ y: Double, _ r: Double) -> Path {
        Path(ellipseIn: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r))
    }

    private func path(_ segs: [LineMapLayout.Segment]) -> Path {
        var p = Path()
        let pt = { (q: LineMapLayout.Point) in CGPoint(x: q.x, y: q.y) }
        for s in segs {
            switch s {
            case let .move(q): p.move(to: pt(q))
            case let .line(q): p.addLine(to: pt(q))
            case let .curve(c1, c2, q): p.addCurve(to: pt(q), control1: pt(c1), control2: pt(c2))
            }
        }
        return p
    }
}
#endif
