#if canImport(SwiftUI)
import CanonCore
import Charts
import SwiftUI

/// 고른 인물이나 두 사람 상세 (웹 `castDetail`).
struct CastDetail: View {
    let model: CastModel
    let go: (Screen) -> Void

    var body: some View {
        switch model.selection {
        case let .character(id):
            if let c = model.character(id) {
                CharacterDetail(model: model, c: c, go: go)
            } else {
                hint
            }
        case let .pair(a, b):
            PairDetail(model: model, a: a, b: b, go: go)
        case nil:
            hint
        }
    }

    private var hint: some View {
        CastCard { Text("관계도에서 인물이나 관계선을 누르세요.").font(.callout).foregroundStyle(.secondary) }
    }
}

/// 칸 이름과 값 한 줄 (웹 `.cast-kv`).
/// 칸 이름이 길면(`stacked`) 이름을 위에 둔다.
struct KeyValue: View {
    let label: String
    let value: String
    var stacked = false

    var body: some View {
        if stacked {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.caption).foregroundStyle(.secondary)
                Text(value).textSelection(.enabled)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(label).font(.caption).foregroundStyle(.secondary).frame(width: 64, alignment: .leading)
                Text(value).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
            }
        }
    }
}

/// 관계 사건 한 줄. 좋은 사건은 파랑, 나쁜 사건은 빨강 띠 (웹 `.cast-ev`).
struct EventLine: View {
    let text: String
    let quote: String?
    let good: Bool

    var body: some View {
        HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 1.5).fill(Color(hex: good ? 0x5598E7 : 0xE0726A)).frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                Text(text)
                if let quote, !quote.isEmpty { Text("“\(quote)”").font(.caption).foregroundStyle(.secondary) }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - 인물

struct CharacterDetail: View {
    @Bindable var model: CastModel
    let c: CastCharacter
    let go: (Screen) -> Void

    var body: some View {
        VStack(spacing: 16) {
            CastCard { card }
            timeline
        }
    }

    @ViewBuilder
    private var card: some View {
        let f = model.frame
        let st = f?.states.first { $0.characterId == c.id }
        let apps = model.appearances(c.id)
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Text(c.name.isEmpty ? c.id : c.name).font(.title2.bold())
                HStack(spacing: 6) {
                    Chip(CastTier(c.tier).label)
                    if !c.role.isEmpty { Chip(c.role) }
                    ForEach([c.age, c.gender].compactMap { $0 }.filter { !$0.isEmpty }, id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                }
            }
            Spacer()
            Button("설정에서 고치기") { go(.setup) }.buttonStyle(.bordered).controlSize(.small)
        }
        Text(CastText.appearance(apps, firstEp: c.firstEp)).font(.caption).foregroundStyle(.secondary)
        if !apps.isEmpty { AppearanceStrip(model: model, id: c.id) }

        Text(model.label(f)).font(.headline).padding(.top, 4)
        let fields = [("감정", st?.emotionalState), ("목표", st?.currentGoal), ("위치", st?.location)].compactMap { l, v in v.flatMap { $0.isEmpty ? nil : (l, $0) } }
        if fields.isEmpty {
            Text("기록된 상태가 없어요").font(.caption).foregroundStyle(.secondary)
        } else {
            ForEach(fields, id: \.0) { KeyValue(label: $0.0, value: $0.1) }
        }
        if let knows = st?.knows, !knows.isEmpty {
            DisclosureGroup("아는 것 \(knows.count)개") {
                VStack(alignment: .leading, spacing: 4) { ForEach(knows, id: \.self) { Text("· \($0)") } }
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }

        Text("관계").font(.headline).padding(.top, 4)
        let partners = model.partners(c.id)
        if partners.isEmpty {
            Text("이 시점에 관계가 없어요").font(.caption).foregroundStyle(.secondary)
        } else {
            ForEach(partners, id: \.self) { o in relation(o) }
        }

        secrets

        DisclosureGroup("바뀌지 않는 설정") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(settingFields, id: \.0) { KeyValue(label: $0.0, value: $0.1) }
                if let s = c.secrets, !s.isEmpty { KeyValue(label: "설정 비밀", value: s.joined(separator: "\n")) }
            }
            .padding(.top, 6)
        }
        links
    }

    private var settingFields: [(String, String)] {
        [("성격", c.personality), ("말투", c.speechStyle), ("목표", c.goal), ("결핍", c.wound), ("아크", c.arc), ("배경", c.background), ("외모", c.appearance)]
            .compactMap { l, v in v.flatMap { $0.isEmpty ? nil : (l, $0) } }
    }

    private func relation(_ o: String) -> some View {
        let pr = model.pair(c.id, o)
        return VStack(alignment: .leading, spacing: 2) {
            HStack {
                Button { model.pick(.pairOf(c.id, o)) } label: {
                    HStack(spacing: 4) {
                        Text(model.name(o))
                        if let t = pr?._type, !t.isEmpty { Text(t).font(.caption).foregroundStyle(.secondary) }
                    }
                }
                .buttonStyle(.borderless)
                Spacer()
                Text(CastText.tension(pr, numbers: model.showNumbers)).font(.caption).foregroundStyle(.secondary)
            }
            Text("→ \(CastText.tie(model.tie(c.id, o), numbers: model.showNumbers))").font(.caption)
            Text("← \(CastText.tie(model.tie(o, c.id), numbers: model.showNumbers))").font(.caption)
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var secrets: some View {
        let all = model.frame?.secrets ?? []
        let own = all.filter { $0.owner == c.id }
        let hidden = all.filter { $0.hiddenFrom.contains(c.id) }
        if !own.isEmpty || !hidden.isEmpty {
            Text("비밀").font(.headline).padding(.top, 4)
            ForEach(own, id: \.id) { s in
                VStack(alignment: .leading, spacing: 2) {
                    Text("숨김: \(s.content)")
                    Text(s.hiddenFrom.isEmpty ? "모두 앎" : "아직 모름: \(s.hiddenFrom.map(model.name).joined(separator: ", "))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            ForEach(hidden, id: \.id) { s in
                VStack(alignment: .leading, spacing: 2) {
                    Text("모름: \(s.content)")
                    Text("\(model.name(s.owner))의 비밀").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder
    private var links: some View {
        let lines = (model.project?.storylines ?? []).filter { ($0.focus ?? []).contains(c.id) }
        let els = (model.project?.elements ?? []).filter { ($0.characters ?? []).contains(c.id) }
        if !lines.isEmpty || !els.isEmpty {
            FlowRow {
                ForEach(lines, id: \.id) { s in
                    Button("\(s.kind?.rawValue ?? "") \(s.title.flatMap { $0.isEmpty ? nil : $0 } ?? s.id)") { go(.lines) }
                }
                ForEach(els, id: \.id) { x in
                    Button("\(x.kind?.rawValue ?? "") \(x.name.flatMap { $0.isEmpty ? nil : $0 } ?? x.id)") { go(.causal) }
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
    }

    @ViewBuilder
    private var timeline: some View {
        let rows = model.timeline(c.id)
        if !rows.isEmpty {
            let now = model.frame?.episode
            let shown = CastText.shownTimeline(rows, at: now, all: model.showAllTimeline)
            CastCard {
                HStack {
                    Text("화별 타임라인").font(.title3.bold())
                    Spacer()
                    Text("반영한 화에서 바뀐 것만").font(.caption).foregroundStyle(.secondary)
                }
                if rows.count > shown.count {
                    Button("나머지 \(rows.count - shown.count)화도 보기") { model.showAllTimeline = true }.controlSize(.small)
                }
                ForEach(shown, id: \.n) { r in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 6) {
                            Text("\(r.n)화").bold()
                            Text(r.title).font(.caption).foregroundStyle(.secondary)
                            if r.new { Chip("첫 등장", tint: .accentColor) }
                            if r.pov { Chip("시점") }
                        }
                        let bits = CastText.changes(r)
                        ForEach(Array(bits.enumerated()), id: \.offset) { _, b in
                            (Text(b.label).font(.caption).foregroundColor(.secondary) + Text(" \(b.text)"))
                        }
                        ForEach(Array(r.events.enumerated()), id: \.offset) { _, e in
                            EventLine(text: CastText.event(e, name: model.name, viewer: c.id), quote: e.quote, good: CastText.isGood(e))
                        }
                        if bits.isEmpty && r.events.isEmpty { Text("등장").font(.caption).foregroundStyle(.secondary) }
                    }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(now == r.n ? Color.accentColor.opacity(0.1) : .clear, in: RoundedRectangle(cornerRadius: 8))
                }
            }
        }
    }
}

/// 인물 등장 화 줄 (웹 `castStrip`). 화 상태별 색, 시점 인물인 화는 아래 막대.
struct AppearanceStrip: View {
    let model: CastModel
    let id: String

    var body: some View {
        let total = model.totalEpisodes
        let step = CastText.stripStep(total)
        let apps = Dictionary(model.appearances(id).map { ($0.n, $0) }, uniquingKeysWith: { a, _ in a })
        ScrollView(.horizontal, showsIndicators: false) {
            Canvas { ctx, _ in
                for n in 1...total {
                    let x = Double(n - 1) * step
                    let w = max(1, step - 1)
                    guard let a = apps[n] else {
                        ctx.fill(Path(CGRect(x: x, y: 6, width: w, height: 6)), with: .color(.secondary.opacity(0.2)))
                        continue
                    }
                    let color = Color.episodeStatus(a.status)
                    let cell = Path(CGRect(x: x, y: 1, width: w, height: 16))
                    ctx.fill(cell, with: .color(color.opacity(a.status == "draft" ? 0.08 : 0.3)))
                    ctx.stroke(cell, with: .color(color), lineWidth: 1)
                    if a.pov { ctx.fill(Path(CGRect(x: x, y: 19, width: w, height: 3)), with: .style(.primary)) }
                }
            }
            .frame(width: Double(total) * step, height: 23)
        }
        .accessibilityElement()
        .accessibilityLabel("\(model.name(id)) 등장 화")
        .accessibilityValue(model.appearances(id).map { "\($0.n)화" }.joined(separator: ", "))
    }
}

// MARK: - 두 사람

struct PairDetail: View {
    @Bindable var model: CastModel
    let a: String
    let b: String
    let go: (Screen) -> Void

    var body: some View {
        let f = model.frame
        let pr = model.pair(a, b)
        let names = ["\(model.name(a)) → \(model.name(b))", "\(model.name(b)) → \(model.name(a))"]
        let events = model.events(a, b)
        CastCard {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Button(model.name(a)) { model.pick(.character(a)) }.buttonStyle(.borderless)
                        Text("↔")
                        Button(model.name(b)) { model.pick(.character(b)) }.buttonStyle(.borderless)
                    }
                    .font(.title2.bold())
                    HStack(spacing: 6) {
                        if let t = pr?._type, !t.isEmpty { Chip(t) } else { Text("관계 설정 없이 사건으로 생긴 관계").font(.caption).foregroundStyle(.secondary) }
                        Text(CastText.tension(pr, numbers: model.showNumbers)).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Button("관계 설정 고치기") { go(.setup) }.buttonStyle(.bordered).controlSize(.small)
            }
            if let d = pr?.description, !d.isEmpty { Text(d).font(.caption).foregroundStyle(.secondary) }
            Text(model.label(f)).font(.headline).padding(.top, 4)
            KeyValue(label: names[0], value: CastText.tie(model.tie(a, b), numbers: model.showNumbers), stacked: true)
            KeyValue(label: names[1], value: CastText.tie(model.tie(b, a), numbers: model.showNumbers), stacked: true)
            if model.frames.count > 1 {
                charts(names: names)
            } else {
                Text("1화를 반영하면 화별 추이 그래프가 나와요.").font(.caption).foregroundStyle(.secondary)
            }
            HStack(alignment: .firstTextBaseline) {
                Text("두 사람 사이 관계 사건").font(.headline)
                Text("\(events.count)개").font(.caption).foregroundStyle(.secondary)
            }
            .padding(.top, 4)
            if events.isEmpty {
                Text("아직 없어요").font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(Array(events.enumerated()), id: \.offset) { _, e in
                    EventLine(text: "\(e.episode)화 \(CastText.event(e, name: model.name))", quote: e.quote, good: CastText.isGood(e))
                }
            }
        }
    }

    @ViewBuilder
    private func charts(names: [String]) -> some View {
        let window = CastText.chartWindow(count: model.frames.count, at: model.frameIndex, all: model.chartAll)
        let pick = { (f: CastFrame, s: String, t: String, v: (CastTie) -> Double) in model.tie(s, t, in: f).map(v) }
        let warmth = series(window, names) { f, i in pick(f, i == 0 ? a : b, i == 0 ? b : a) { $0.warmth } }
        let trust = series(window, names) { f, i in pick(f, i == 0 ? a : b, i == 0 ? b : a) { $0.trust } }
        let tension = series(window, ["긴장"]) { f, _ in model.pair(a, b, in: f)?.tension }
        HStack(spacing: 12) {
            ForEach(0..<2, id: \.self) { i in
                HStack(spacing: 4) { RoundedRectangle(cornerRadius: 2).fill(Color(hex: CastText.pairColors[i])).frame(width: 16, height: 3); Text(names[i]) }
            }
        }
        .font(.caption)
        Text("온기").font(.subheadline.bold())
        TrendChart(model: model, points: warmth, window: window, domain: -1...1, grid: [-1, 0, 1], label: "온기 추이")
        Text("신뢰").font(.subheadline.bold())
        TrendChart(model: model, points: trust, window: window, domain: 0...1, grid: [0, 0.5, 1], label: "신뢰 추이")
        HStack(alignment: .firstTextBaseline) {
            Text("긴장").font(.subheadline.bold())
            Text("0~10, 3 · 5 · 7 에서 보통 · 높음 · 매우 높음").font(.caption).foregroundStyle(.secondary)
        }
        TrendChart(model: model, points: tension, window: window, domain: 0...10, grid: [0, 3, 5, 7, 10], label: "긴장 추이", gray: true)
        if model.frames.count > 40 {
            HStack {
                Text(model.chartAll ? "전체 \(model.frames.count)개 시점"
                     : "\(model.label(model.frames[window.lowerBound])) ~ \(model.label(model.frames[window.upperBound]))")
                Button(model.chartAll ? "고른 시점 주변만" : "전체 보기") { model.chartAll.toggle() }.buttonStyle(.borderless)
            }
            .font(.caption)
        }
        Text("그래프를 누르면 관계도가 그 시점으로 가요.").font(.caption).foregroundStyle(.secondary)
    }

    private func series(_ window: ClosedRange<Int>, _ names: [String], _ value: (CastFrame, Int) -> Double?) -> [TrendPoint] {
        names.indices.flatMap { i in
            window.compactMap { fi in value(model.frames[fi], i).map { TrendPoint(frame: fi, series: names[i], color: i, value: $0) } }
        }
    }
}

struct TrendPoint: Identifiable {
    let frame: Int
    let series: String
    let color: Int
    let value: Double
    var id: String { "\(series)#\(frame)" }
}

/// 두 사람 추이 그래프 하나 (웹 `castChart`). 세로 점선은 지금 보는 시점, 누르면 그 시점으로 간다.
struct TrendChart: View {
    let model: CastModel
    let points: [TrendPoint]
    let window: ClosedRange<Int>
    let domain: ClosedRange<Double>
    let grid: [Double]
    let label: String
    var gray = false

    var body: some View {
        Chart {
            ForEach(points) { p in
                LineMark(x: .value("시점", p.frame), y: .value("값", p.value), series: .value("방향", p.series))
                    .foregroundStyle(gray ? Color.secondary : Color(hex: CastText.pairColors[p.color]))
                    .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
            }
            ForEach(points.filter { $0.frame == model.frameIndex }) { p in
                PointMark(x: .value("시점", p.frame), y: .value("값", p.value))
                    .foregroundStyle(gray ? Color.secondary : Color(hex: CastText.pairColors[p.color]))
            }
            RuleMark(x: .value("지금", model.frameIndex))
                .foregroundStyle(Color.accentColor)
                .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
        }
        .chartXScale(domain: window.lowerBound...max(window.upperBound, window.lowerBound + 1))
        .chartYScale(domain: domain)
        .chartYAxis {
            AxisMarks(position: .leading, values: grid) { v in
                AxisGridLine()
                AxisValueLabel { if let d = v.as(Double.self) { Text(d == d.rounded() ? String(Int(d)) : CastText.fixed(d, 1)) } }
            }
        }
        .chartXAxis {
            AxisMarks(values: ticks) { v in
                AxisValueLabel { if let i = v.as(Int.self), i < model.frames.count { Text(model.frames[i].episode == 0 ? "시작" : "\(model.frames[i].episode)화") } }
            }
        }
        .chartLegend(.hidden)
        .chartOverlay { proxy in
            GeometryReader { geo in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onTapGesture { loc in
                        guard let plot = proxy.plotFrame else { return }
                        let x = loc.x - geo[plot].origin.x
                        if let v: Double = proxy.value(atX: x) { model.go(Int(v.rounded())) }
                    }
            }
        }
        .frame(height: gray ? 110 : 120)
        .accessibilityLabel(label)
    }

    /// 아래 화 번호: 10개쯤만 (웹 `every`).
    private var ticks: [Int] {
        let n = window.count
        let every = max(1, Int((Double(n) / 10).rounded(.up)))
        return window.enumerated().filter { $0.offset % every == 0 || $0.offset == n - 1 }.map(\.element)
    }
}

/// 버튼을 줄 바꿈하며 늘어놓는다.
struct FlowRow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(proposal.width ?? .infinity, subviews)
        return CGSize(width: proposal.width ?? rows.map(\.width).max() ?? 0, height: rows.last.map { $0.y + $0.height } ?? 0)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for row in arrange(bounds.width, subviews) {
            var x = bounds.minX
            for i in row.items {
                let s = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: bounds.minY + row.y), proposal: .unspecified)
                x += s.width + spacing
            }
        }
    }

    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> [(items: [Int], y: CGFloat, width: CGFloat, height: CGFloat)] {
        var rows: [(items: [Int], y: CGFloat, width: CGFloat, height: CGFloat)] = []
        var cur: [Int] = []
        var x: CGFloat = 0
        var h: CGFloat = 0
        var y: CGFloat = 0
        for (i, v) in subviews.enumerated() {
            let s = v.sizeThatFits(.unspecified)
            if !cur.isEmpty && x + s.width > width {
                rows.append((cur, y, x - spacing, h))
                y += h + spacing
                cur = []
                x = 0
                h = 0
            }
            cur.append(i)
            x += s.width + spacing
            h = max(h, s.height)
        }
        if !cur.isEmpty { rows.append((cur, y, x - spacing, h)) }
        return rows
    }
}
#endif
