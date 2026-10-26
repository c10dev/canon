#if canImport(SwiftUI)
import SwiftUI

/// 등장표: 인물마다 플롯에 나오는 화 (웹 `castTable`). 이름을 누르면 관계도에서 그 인물을 연다.
struct CastTableCard: View {
    let model: CastModel

    private let left = 150.0
    private let top = 34.0
    private let rowH = 28.0

    var body: some View {
        let total = model.totalEpisodes
        let step = CastText.tableStep(total)
        let chars = CastText.tableOrder(model.characters, appearances: model.appearances)
        let width = left + Double(total) * step + 70
        let height = top + Double(chars.count) * rowH + 22
        CastCard {
            HStack {
                Text("등장표").font(.title3.bold())
                Spacer()
                Text("플롯의 등장 인물 기준. 이름을 누르면 관계도에서 그 인물을 열어요").font(.caption).foregroundStyle(.secondary)
            }
            ScrollView(.horizontal) {
                ZStack(alignment: .topLeading) {
                    Canvas { ctx, _ in draw(&ctx, chars: chars, total: total, step: step, height: height) }
                        .frame(width: width, height: height)
                    VStack(spacing: 0) {
                        ForEach(chars, id: \.id) { c in
                            Button { model.open(c.id) } label: {
                                Color.clear.frame(width: width, height: rowH).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("\(c.name.isEmpty ? c.id : c.name) 관계도에서 보기")
                            .accessibilityValue("\(model.appearances(c.id).count)화")
                        }
                    }
                    .padding(.top, top)
                }
            }
            legend
        }
    }

    private func draw(_ ctx: inout GraphicsContext, chars: [CastCharacter], total: Int, step: Double, height: Double) {
        for band in CastText.bands(model.project, serial: model.isSerial) {
            let x = left + Double(band.start - 1) * step
            let w = max(2, Double(band.end - band.start + 1) * step - 2)
            ctx.fill(Path(roundedRect: CGRect(x: x + 1, y: 4, width: w, height: 20), cornerRadius: 5), with: .color(Color.act(band.tone).opacity(0.2)))
            if w > 30 {
                ctx.draw(Text(band.label).font(.caption2.bold()).foregroundColor(Color.act(band.tone)), at: CGPoint(x: x + 6, y: 14), anchor: .leading)
            }
        }
        for (i, c) in chars.enumerated() {
            let y = top + Double(i) * rowH
            let rows = model.appearances(c.id)
            ctx.draw(Text(c.name.isEmpty ? c.id : c.name).font(.callout.bold()), at: CGPoint(x: 10, y: y + rowH / 2), anchor: .leading)
            ctx.draw(Text(CastTier(c.tier).label).font(.caption).foregroundColor(.secondary), at: CGPoint(x: left - 10, y: y + rowH / 2), anchor: .trailing)
            for a in rows where a.n >= 1 && a.n <= total {
                let x = left + Double(a.n - 1) * step
                let color = Color.episodeStatus(a.status)
                let cell = Path(roundedRect: CGRect(x: x + 0.5, y: y + 5, width: max(1.5, step - 1.5), height: rowH - 10), cornerRadius: step > 8 ? 3 : 1)
                ctx.fill(cell, with: .color(color.opacity(a.status == "draft" ? 0.08 : 0.3)))
                ctx.stroke(cell, with: .color(color), lineWidth: 1)
                if a.pov {
                    let r = max(1.5, min(4, step / 4))
                    ctx.fill(Path(ellipseIn: CGRect(x: x + step / 2 - r, y: y + rowH / 2 - r, width: r * 2, height: r * 2)), with: .style(.primary))
                }
            }
            ctx.draw(Text("\(rows.count)화").font(.caption).foregroundColor(.secondary), at: CGPoint(x: left + Double(total) * step + 8, y: y + rowH / 2), anchor: .leading)
        }
        let every = CastText.tickEvery(step)
        for n in 1...total where n == 1 || n % every == 0 {
            ctx.draw(Text("\(n)").font(.caption2).foregroundColor(.secondary), at: CGPoint(x: left + (Double(n) - 0.5) * step, y: height - 10))
        }
    }

    private var legend: some View {
        HStack(spacing: 12) {
            ForEach(["draft", "confirmed", "written", "finalized"], id: \.self) { s in
                HStack(spacing: 4) {
                    RoundedRectangle(cornerRadius: 2).fill(Color.episodeStatus(s).opacity(s == "draft" ? 0.08 : 0.3))
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.episodeStatus(s)))
                        .frame(width: 12, height: 12)
                    Text(s == "written" ? "본문 있음" : CastText.status(s))
                }
            }
            HStack(spacing: 4) { Circle().fill(.primary).frame(width: 8, height: 8); Text("시점 인물") }
        }
        .font(.caption)
    }
}
#endif
