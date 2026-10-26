#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 다시 생성 패널: 빠른 요청, 피드백, 함께 넣을 것, 방식, 살릴 부분, 보낼 프롬프트 (웹 `rewritePanel`).
struct RewritePanel: View {
    let model: WriteModel
    let n: Int
    let startJob: (@escaping () async -> Void) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("\(n)화 다시 생성").font(.headline)
                Spacer()
                Button("닫기") { model.closeRewrite() }.buttonStyle(.bordered).controlSize(.small)
            }
            Text(RewriteText.panelHelp).font(.caption).foregroundStyle(.secondary)
            if let info = model.rewriteInfo[n] {
                form(info, model.rewrite[n] ?? RewriteDraft())
            } else {
                ProgressView("불러오는 중")
            }
        }
        .padding(12)
        .background(.blue.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func form(_ info: RewriteInfo, _ r: RewriteDraft) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("빠른 요청 (여러 개 고를 수 있어요)").font(.caption).foregroundStyle(.secondary)
            FlowRow(info.presets.map(\.id)) { id in
                let on = r.presets.contains(id)
                Button(info.presets.first { $0.id == id }?.label ?? id) { model.editRewrite(n) { $0.toggle(preset: id) } }
                    .buttonStyle(.bordered).controlSize(.small)
                    .tint(on ? .accentColor : .secondary)
                    .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        VStack(alignment: .leading, spacing: 4) {
            Text("피드백").font(.caption).foregroundStyle(.secondary)
            TextField("예: 주인공이 너무 빨리 마음을 연다. 중간에 한 번 더 밀어내게 해 줘",
                      text: Binding(get: { model.rewrite[n]?.feedback ?? "" }, set: { v in model.editRewrite(n) { $0.feedback = v } }),
                      axis: .vertical)
                .lineLimit(3...6)
                .textFieldStyle(.roundedBorder)
        }
        VStack(alignment: .leading, spacing: 6) {
            Text("함께 넣을 것").font(.caption).foregroundStyle(.secondary)
            ForEach(info.materials, id: \.id) { m in
                let none = m.lines.isEmpty
                VStack(alignment: .leading, spacing: 2) {
                    Toggle(isOn: Binding(get: { r.materials.contains(m.id) && !none }, set: { _ in model.editRewrite(n) { $0.toggle(material: m.id) } })) {
                        Text(m.label).bold() + Text("  \(RewriteText.materialCount(m.lines))").font(.caption).foregroundStyle(.secondary)
                    }
                    .disabled(none)
                    if !m.note.isEmpty { Text(m.note).font(.caption).foregroundStyle(.orange) }
                    if !none {
                        DisclosureGroup("넣을 내용 보기") {
                            Text(m.lines.joined(separator: "\n")).font(.caption).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .font(.caption)
                    }
                }
            }
        }
        VStack(alignment: .leading, spacing: 4) {
            Text("방식").font(.caption).foregroundStyle(.secondary)
            Picker("다시 쓰는 방식", selection: Binding(get: { r.mode }, set: { v in model.editRewrite(n) { $0.mode = v } })) {
                ForEach(RewriteDraft.Mode.allCases, id: \.self) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            Text(r.mode.help).font(.caption).foregroundStyle(.secondary)
        }
        VStack(alignment: .leading, spacing: 4) {
            Text("살릴 부분 \(r.keep.count)/\(info.keepMax)").font(.caption).foregroundStyle(.secondary)
            ForEach(Array(r.keep.enumerated()), id: \.offset) { i, k in
                HStack(alignment: .top) {
                    Text(WriteText.clip(k, 200)).font(.caption).padding(6).frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                    Button("빼기") { model.editRewrite(n) { $0.keep.remove(at: i) } }
                        .buttonStyle(.bordered).controlSize(.small).accessibilityLabel("살릴 부분 빼기")
                }
            }
            Button("살릴 부분 담기") { model.addKeep(n, Clipboard.read() ?? "") }
                .buttonStyle(.bordered).controlSize(.small)
            Text(RewriteText.keepHelp).font(.caption).foregroundStyle(.secondary)
        }
        HStack {
            Button(model.rewritePrompt == nil ? "보낼 프롬프트 보기" : "프롬프트 닫기") { Task { await model.toggleRewritePrompt(n) } }
                .buttonStyle(.bordered).controlSize(.small)
                .disabled(model.busy != nil)
            Spacer()
            let busy = model.jobs.busyLabel("write", ep: n)
            Button(busy ?? "새 판 만들기") { startJob { await model.submitRewrite(n) } }
                .buttonStyle(.borderedProminent)
                .disabled(busy != nil)
        }
        if model.writing(n) {
            Text("다른 화면으로 옮겨 가도 계속 써요. 끝나면 알려 드려요.").font(.caption).foregroundStyle(.secondary)
        }
        if let prompt = model.rewritePrompt {
            ScrollView {
                Text(prompt).font(.caption.monospaced()).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 420)
            .padding(8)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 6))
        }
    }
}

/// 새 판 비교: 나란히 · 바뀐 곳, 고르기 (웹 `candidateCard`).
struct CandidateCard: View {
    let model: WriteModel
    let n: Int
    let candidate: TextVersion

    var body: some View {
        let cur = model.text(n)
        let new = candidate.text ?? ""
        let labels = model.presetLabels
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("새 판이 나왔어요").font(.headline)
                    FlowRow(RewriteText.requestBits(candidate.request, labels: labels) + [WriteText.when(candidate.at)].filter { !$0.isEmpty }) { bit in
                        Text(bit).font(.caption).padding(.horizontal, 6).padding(.vertical, 2).background(.purple.opacity(0.12), in: Capsule())
                    }
                }
                Spacer()
                Picker("비교 방식", selection: Binding(get: { model.compare }, set: { model.compare = $0 })) {
                    Text("나란히").tag(WriteModel.CompareMode.side)
                    Text("바뀐 곳").tag(WriteModel.CompareMode.diff)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 180)
            }
            if model.compare == .side {
                HStack(alignment: .top, spacing: 12) {
                    column(RewriteText.side("지금 판", cur), cur)
                    column(RewriteText.side("새 판", new), new)
                }
            } else {
                DiffBox(a: cur, b: new, note: "지금 판에서 지운 글은 빨강, 새 판에 더한 글은 초록이에요.")
            }
            Text(RewriteText.compareHelp).font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("지금 판 두기") { Task { await model.dropCandidate(n) } }
                Button("요청 고쳐 다시") { Task { await model.rewriteAgain(n) } }
                Button("새 판으로 바꾸기") { Task { await model.adopt(n) } }.buttonStyle(.borderedProminent)
            }
            .buttonStyle(.bordered)
            .disabled(model.busy != nil)
        }
        .padding(12)
        .background(.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
        .task { await model.loadRewriteInfo(n) }
    }

    private func column(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            ScrollView {
                Text(text).font(.system(.callout, design: .serif)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 420)
        }
        .frame(maxWidth: .infinity)
    }
}

/// 바뀐 곳 비교와 바뀐 곳 개수 (웹 `diffBox`).
struct DiffBox: View {
    let a: String
    let b: String
    let note: String

    var body: some View {
        let d = TextDiff.lines(a, b)
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(note).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text(RewriteText.changes(d.changes)).font(.caption)
            }
            ScrollView {
                Text(Self.attributed(d.pieces)).font(.system(.callout, design: .serif)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 420)
        }
    }

    static func attributed(_ pieces: [DiffPiece]) -> AttributedString {
        var out = AttributedString()
        for p in pieces {
            var s = AttributedString(p.text)
            switch p.kind {
            case .same: break
            case .removed:
                s.backgroundColor = .red.opacity(0.18)
                s.strikethroughStyle = .single
            case .added:
                s.backgroundColor = .green.opacity(0.22)
            }
            out += s
        }
        return out
    }
}

/// 이전 판 목록: 지금 판과 비교, 이 판으로 복원 (웹 `versionsPanel`).
struct VersionsPanel: View {
    let model: WriteModel
    let episode: Episode
    let askRestore: (String) -> Void

    var body: some View {
        let n = episode.plot.number
        let list = Array((episode.versions ?? []).reversed())
        let can = model.canRestore(n)
        let labels = model.presetLabels
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(list, id: \.id) { v in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            FlowRow([RewriteText.kind(v), "\(WriteText.number((v.text ?? "").utf16.count))자"]
                                    + RewriteText.requestBits(v.request, labels: labels) + [WriteText.when(v.at)].filter { !$0.isEmpty }) { bit in
                                Text(bit).font(.caption)
                            }
                            Spacer()
                            Button(model.peek == v.id ? "접기" : "지금 판과 비교") { model.peek = model.peek == v.id ? nil : v.id }
                            if can { Button("이 판으로 복원") { askRestore(v.id) } }
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                        if model.peek == v.id {
                            DiffBox(a: model.text(n), b: v.text ?? "", note: "빨강은 지금 판에만, 초록은 이 판에만 있는 글이에요.")
                        }
                    }
                    Divider()
                }
            }
            .padding(.top, 6)
        } label: {
            Text("이전 판").bold() + Text("  " + RewriteText.versionsHelp(list.count, blocked: WriteText.editable(episode) && !can)).font(.caption).foregroundStyle(.secondary)
        }
        .padding(12)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
        .disabled(model.busy != nil)
        .task { await model.loadRewriteInfo(n) }
    }
}

/// 짧은 조각을 줄 바꿈하며 늘어놓는다.
struct FlowRow<Item: Hashable, Content: View>: View {
    let items: [Item]
    let content: (Item) -> Content

    init(_ items: [Item], @ViewBuilder content: @escaping (Item) -> Content) {
        self.items = items
        self.content = content
    }

    var body: some View {
        FlowLayout(spacing: 6) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in content(item) }
        }
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        rows(proposal.width ?? .infinity, subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for (i, p) in rows(bounds.width, subviews).points.enumerated() {
            subviews[i].place(at: CGPoint(x: bounds.minX + p.x, y: bounds.minY + p.y), proposal: .unspecified)
        }
    }

    private func rows(_ width: CGFloat, _ subviews: Subviews) -> (points: [CGPoint], size: CGSize) {
        var points: [CGPoint] = []
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0, widest: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x > 0 && x + s.width > width {
                x = 0
                y += line + spacing
                line = 0
            }
            points.append(CGPoint(x: x, y: y))
            x += s.width + spacing
            line = max(line, s.height)
            widest = max(widest, x - spacing)
        }
        return (points, CGSize(width: widest, height: y + line))
    }
}
#endif
