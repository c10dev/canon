#if canImport(SwiftUI)
import SwiftUI

/// 관계도 카드: 시점 슬라이더, 보기 설정, 관계도, 범례, 관계 목록, 삼각 구도 알림.
struct CastGraphCard: View {
    @Bindable var model: CastModel

    var body: some View {
        CastCard {
            HStack {
                Text("관계도").font(.title3.bold())
                Spacer()
                NumbersToggle(model: model)
            }
            slider
            HStack(spacing: 12) {
                if model.hasMinor { Toggle("단역도 보기", isOn: $model.showMinor).fixedSize() }
                Button("배치 처음대로") { model.resetPositions() }
                    .disabled(model.positions.isEmpty)
                Text("인물을 끌어 자리를 옮길 수 있어요. 누르면 자세히, 선을 누르면 두 사람 관계를 봐요.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .font(.callout)
            CastGraph(model: model)
                .aspectRatio(CastLayout.width / CastLayout.height, contentMode: .fit)
                .frame(maxWidth: .infinity)
            legend
            tieList
            if let note = CastText.triads(model.frame?.triads ?? [], name: model.name) {
                Text(note).font(.callout).padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    @ViewBuilder
    private var slider: some View {
        let count = model.frames.count
        if count < 2 {
            Text("1화를 반영하면 화별로 관계가 어떻게 바뀌었는지 재생할 수 있어요.").font(.caption).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Button { model.step(-1) } label: { Image(systemName: "chevron.left") }
                        .accessibilityLabel("이전 시점")
                    Slider(value: Binding(get: { Double(model.frameIndex) }, set: { model.go(Int($0.rounded())) }),
                           in: 0...Double(count - 1), step: 1)
                        .accessibilityLabel("관계도 시점")
                        .accessibilityValue(model.label(model.frame))
                    Button { model.step(1) } label: { Image(systemName: "chevron.right") }
                        .accessibilityLabel("다음 시점")
                    Button(model.playLabel) { model.togglePlay() }
                }
                .buttonStyle(.bordered)
                Text(model.label(model.frame)).font(.headline)
            }
        }
    }

    private var legend: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text("온기").bold()
                ForEach(WarmthBand.all, id: \.word) { b in
                    HStack(spacing: 4) { RoundedRectangle(cornerRadius: 2).fill(Color(hex: b.hex)).frame(width: 14, height: 4); Text(b.word) }
                }
            }
            HStack(spacing: 10) {
                Text("두 사람 긴장").bold()
                ForEach(CastText.tensionFill, id: \.word) { t in
                    HStack(spacing: 4) { Circle().fill(Color(hex: t.hex)).frame(width: 9, height: 9); Text("긴장 \(t.word)") }
                }
                HStack(spacing: 4) {
                    Circle().strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [3, 2])).frame(width: 10, height: 10)
                    Text("이 시점엔 아직 안 나온 인물")
                }
            }
            Text("화살표는 보는 쪽 → 보이는 쪽이에요. 색은 온기, 굵기는 함께 겪은 정도(친숙도)예요.").foregroundStyle(.secondary)
        }
        .font(.caption)
    }

    @ViewBuilder
    private var tieList: some View {
        let ties = model.frame?.ties ?? []
        if !ties.isEmpty {
            DisclosureGroup("관계 목록 보기 (\(ties.count)줄)") {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(ties.enumerated()), id: \.offset) { _, t in
                        Text("\(model.name(t.source)) → \(model.name(t.target)): \(CastText.tie(t, numbers: model.showNumbers))")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 4)
            }
            .font(.callout)
        }
    }
}

/// 관계도 그림. 760 × 540 판에 그린 뒤 화면 크기에 맞게 늘인다. 인물을 끌면 자리를 옮기고, 누르면 자세히 본다.
struct CastGraph: View {
    let model: CastModel
    @State private var dragging: String?
    @State private var checked = false
    @State private var moved = false

    var body: some View {
        GeometryReader { geo in
            let scale = min(geo.size.width / CastLayout.width, geo.size.height / CastLayout.height)
            let scene = model.scene()
            let board = { (p: CGPoint) in CastPoint(x: p.x / scale, y: p.y / scale) }
            Canvas { ctx, _ in
                ctx.scaleBy(x: scale, y: scale)
                draw(scene, in: &ctx)
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        if !checked {
                            dragging = CastHit.node(board(v.startLocation), model: scene)
                            checked = true
                        }
                        if let id = dragging, moved || hypot(v.translation.width, v.translation.height) >= 4 {
                            moved = true
                            model.move(id, to: board(v.location))
                        }
                    }
                    .onEnded { v in
                        if moved {
                            model.endMove()
                        } else if let s = CastHit.find(board(v.location), model: scene) {
                            model.pick(s)
                        }
                        dragging = nil
                        checked = false
                        moved = false
                    }
            )
            .accessibilityElement(children: .contain)
            .accessibilityLabel("\(model.label(model.frame)) 관계도")
            .accessibilityChildren {
                ForEach(model.shownCharacters, id: \.id) { c in
                    Button("\(c.name.isEmpty ? c.id : c.name) 자세히 보기") { model.pick(.character(c.id)) }
                }
            }
        }
    }

    private func hot(_ a: String, _ b: String) -> Bool {
        switch model.selection {
        case let .character(c): a == c || b == c
        case let .pair(x, y): Set([a, b]) == Set([x, y])
        case nil: true
        }
    }

    private func draw(_ scene: CastHitInput, in ctx: inout GraphicsContext) {
        for e in scene.edges {
            var layer = ctx
            layer.opacity = hot(e.source, e.target) ? 1 : 0.16
            let color = Color(hex: WarmthBand.all[e.band].hex)
            var path = Path()
            path.move(to: cg(e.curve.start))
            path.addQuadCurve(to: cg(e.curve.end), control: cg(e.curve.control))
            layer.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: e.width, lineCap: .round))
            // 화살촉: 끝에서 곡선 방향으로
            let dx = e.curve.end.x - e.curve.control.x
            let dy = e.curve.end.y - e.curve.control.y
            let d = max(0.01, hypot(dx, dy))
            let (ux, uy) = (dx / d, dy / d)
            let tip = CGPoint(x: e.curve.end.x + ux, y: e.curve.end.y + uy)
            let base = CGPoint(x: e.curve.end.x - ux * 8, y: e.curve.end.y - uy * 8)
            var head = Path()
            head.move(to: tip)
            head.addLine(to: CGPoint(x: base.x - uy * 4.5, y: base.y + ux * 4.5))
            head.addLine(to: CGPoint(x: base.x + uy * 4.5, y: base.y - ux * 4.5))
            head.closeSubpath()
            layer.fill(head, with: .color(color))
        }
        for t in scene.tensions {
            var layer = ctx
            layer.opacity = hot(t.a, t.b) ? 1 : 0.16
            let circle = Path(ellipseIn: CGRect(x: t.at.x - t.radius, y: t.at.y - t.radius, width: t.radius * 2, height: t.radius * 2))
            layer.fill(circle, with: .color(Color(hex: t.hex)))
            layer.stroke(circle, with: .style(.background), lineWidth: 2)
        }
        for n in scene.nodes {
            guard let c = model.character(n.id) else { continue }
            let tier = CastTier(c.tier)
            let here = model.present(c)
            let selected = model.selection?.includes(c.id) ?? false
            var layer = ctx
            layer.opacity = here ? 1 : 0.45
            let r = n.radius
            if selected {
                let halo = Path(ellipseIn: CGRect(x: n.at.x - r - 6, y: n.at.y - r - 6, width: (r + 6) * 2, height: (r + 6) * 2))
                layer.fill(halo, with: .color(Color.accentColor.opacity(0.18)))
            }
            let dot = Path(ellipseIn: CGRect(x: n.at.x - r, y: n.at.y - r, width: r * 2, height: r * 2))
            layer.fill(dot, with: .style(.background))
            let stroke: GraphicsContext.Shading = selected ? .color(.accentColor) : tier == .main ? .style(.primary) : tier == .minor ? .style(.tertiary) : .style(.secondary)
            let width = selected ? 3.5 : tier == .main ? 3 : 2
            layer.stroke(dot, with: stroke, style: StrokeStyle(lineWidth: width, dash: here ? [] : [4, 3]))
            let label = c.name.isEmpty ? c.id : c.name
            let inside = tier != .minor && label.count <= 3  // 짧은 이름은 원 안에, 긴 이름과 단역은 원 아래에
            let font: Font = tier == .support && inside ? .system(size: 12, weight: .bold) : .system(size: 13, weight: .bold)
            if inside {
                layer.draw(Text(label).font(font), at: cg(n.at))
            } else {
                let at = CGPoint(x: n.at.x, y: n.at.y + r + 11)
                let text = layer.resolve(Text(label).font(font))
                let size = text.measure(in: CGSize(width: 300, height: 40))
                let box = Path(roundedRect: CGRect(x: at.x - size.width / 2 - 3, y: at.y - size.height / 2, width: size.width + 6, height: size.height), cornerRadius: 4)
                layer.fill(box, with: .style(.background.opacity(0.85)))
                layer.draw(text, at: at)
            }
        }
    }

    private func cg(_ p: CastPoint) -> CGPoint { CGPoint(x: p.x, y: p.y) }
}
#endif
