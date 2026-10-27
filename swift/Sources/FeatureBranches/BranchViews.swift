#if canImport(SwiftUI)
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 작품 머리 띠: 갈래 작품이면 어느 화면에서든 갈래 이름과 갈라진 곳을 보인다 (다른 갈래를 고치는 줄 헷갈리지 않게).
/// 본편은 작품 홈에서만 갈래 목록을 보인다 (웹 `branchStrip`).
public struct BranchStrip: View {
    let model: BranchModel
    let home: Bool
    let open: (String) -> Void

    public init(model: BranchModel, home: Bool, open: @escaping (String) -> Void) {
        self.model = model
        self.home = home
        self.open = open
    }

    public var body: some View {
        if let s = BranchText.strip(model.family, model.project, home: home) {
            VStack(alignment: .leading, spacing: 6) {
                (Text(s.title).bold() + Text(" · \(s.line)"))
                Flow(spacing: 10) {
                    if let p = s.parent { Button("갈라져 나온 작품 열기") { open(p) } }
                    if let m = s.mainName { Button("본편 열기") { open(m) } }
                    if !s.others.isEmpty {
                        Text(s.main ? "갈래:" : "집안:").foregroundStyle(.secondary)
                        ForEach(s.others, id: \.name) { l in
                            Button { open(l.name) } label: { Text(l.label) + Text(" \(l.detail)").foregroundStyle(.secondary) }
                        }
                    }
                }
                .buttonStyle(.borderless)
                .font(.caption)
                ForEach(s.warnings, id: \.self) { Text($0).font(.callout) }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background((s.main ? Color.secondary : Color.blue).opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            .accessibilityElement(children: .contain)
        }
    }
}

/// 사이드바 작품 이름 아래 갈래 줄 (웹 `branchSideTag`). 갈래는 본편과 제목이 같아 이 줄로 가른다.
public struct BranchSideTag: View {
    let model: BranchModel

    public init(model: BranchModel) {
        self.model = model
    }

    public var body: some View {
        if let tag = BranchText.sideTag(model.family, model.project) {
            Text(tag).font(.caption).foregroundStyle(.secondary)
        }
    }
}

/// 작품 홈의 갈래 카드: 화 축 위에 집안의 작품마다 한 줄, 열기 · 비교 · 본편으로 · 끊기 (웹 `branchHomeCard`).
public struct BranchHomeCard: View {
    let model: BranchModel
    let open: (String) -> Void
    let compare: (String?) -> Void
    @State private var ask: Ask?

    struct Ask: Identifiable {
        let id = UUID()
        let text: String
        let button: String
        let destructive: Bool
        let action: () async -> Void
    }

    /// compare: 갈래 비교 화면으로 (nil 이면 견줄 작품을 화면이 고른다).
    public init(model: BranchModel, open: @escaping (String) -> Void, compare: @escaping (String?) -> Void) {
        self.model = model
        self.open = open
        self.compare = compare
    }

    public var body: some View {
        let rows = BranchText.homeRows(model.family, model.project)
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("갈래").font(.title3.bold())
                    Spacer()
                    Button("갈래 비교") { compare(nil) }.buttonStyle(.borderless).font(.caption)
                }
                if let e = model.error { Notice(e, isError: true) { model.dismissError() } }
                ForEach(rows, id: \.name) { row($0) }
                Text(BranchText.homeNote).font(.caption).foregroundStyle(.secondary)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
            .alert(ask?.text ?? "", isPresented: Binding(get: { ask != nil }, set: { if !$0 { ask = nil } }), presenting: ask) { q in
                Button(q.button, role: q.destructive ? .destructive : nil) { Task { await q.action() } }
                Button("그만두기", role: .cancel) {}
            }
        }
    }

    private func row(_ r: BranchText.HomeRow) -> some View {
        let m = model.members.first { $0.name == r.name }
        return ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                name(r).frame(width: 200, alignment: .leading)
                track(r).frame(minWidth: 120)
                actions(r, m)
            }
            VStack(alignment: .leading, spacing: 6) {
                name(r)
                track(r)
                HStack { actions(r, m) }
            }
        }
        .padding(.leading, CGFloat(r.depth) * 16)
        .padding(8)
        .background(r.me ? Color.accentColor.opacity(0.08) : .clear, in: RoundedRectangle(cornerRadius: 6))
    }

    private func name(_ r: BranchText.HomeRow) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(r.label).font(.subheadline.bold()).lineLimit(1)
            Text(r.detail).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func track(_ r: BranchText.HomeRow) -> some View {
        GeometryReader { g in
            let w = g.size.width
            ZStack(alignment: .leading) {
                if r.shared > 0 {
                    RoundedRectangle(cornerRadius: 3).stroke(style: StrokeStyle(lineWidth: 1, dash: [3, 3])).foregroundStyle(.secondary)
                        .frame(width: w * r.shared)
                }
                RoundedRectangle(cornerRadius: 3).fill(.quaternary)
                    .frame(width: max(0, w * (1 - r.start))).offset(x: w * r.start)
                if let done = r.done {
                    RoundedRectangle(cornerRadius: 3).fill(.green)
                        .frame(width: max(0, w * (done - r.start))).offset(x: w * r.start)
                }
            }
        }
        .frame(height: 10)
        .accessibilityElement()
        .accessibilityLabel(r.accessibility)
    }

    @ViewBuilder
    private func actions(_ r: BranchText.HomeRow, _ m: BranchMember?) -> some View {
        if r.me {
            Text("지금 작품").font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2).background(.quaternary, in: Capsule())
        } else {
            Button("열기") { open(r.name) }
            Button("비교") { compare(r.name) }
        }
        if r.branch, let m {
            Button("본편으로") {
                ask = Ask(text: BranchText.promoteQuestion(m), button: "본편으로", destructive: false) { await model.promote(m) }
            }
            Button("끊기", role: .destructive) {
                ask = Ask(text: BranchText.detachQuestion(model.family, m), button: "끊기", destructive: true) { await model.detach(m) }
            }
        }
    }
}

/// 갈래 만들기 칸 (웹 `branchFormCard`). 저장하지 않은 변경이 있으면 먼저 저장해 갈래로 옮긴다.
public struct BranchFormView: View {
    let model: BranchModel
    let document: ProjectDocument
    let done: (BranchModel.Created) -> Void
    @State private var draft: BranchDraft
    @State private var saveError: String?
    @Environment(\.dismiss) private var dismiss

    public init(model: BranchModel, document: ProjectDocument, draft: BranchDraft, done: @escaping (BranchModel.Created) -> Void) {
        self.model = model
        self.document = document
        self.done = done
        _draft = State(initialValue: draft)
    }

    private var last: Int { document.project.map(BranchText.lastFinal) ?? 0 }

    public var body: some View {
        let n = draft.fromEp ?? 1
        NavigationStack {
            Form {
                Section { Text(BranchText.formDesc(n)).foregroundStyle(.secondary) }
                Section {
                    TextField("갈래 이름", text: $draft.label, prompt: Text("예: B안 - 세린이 떠난다"))
                    VStack(alignment: .leading, spacing: 4) {
                        TextField("시작 화 (1~\(last + 1)화)", text: $draft.from)
                        problem(.from)
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        TextField("폴더 이름 (주소)", text: Binding(get: { draft.to }, set: { draft.typeFolder($0) }))
                            .autocorrectionDisabled()
                        problem(.to)
                    }
                }
                Section("\(n)화부터의 본문") {
                    Picker("\(n)화부터의 본문", selection: $draft.keep) {
                        mode("비우고 다시 쓰기", "지금 본문은 그 화의 이전 판으로 남아요").tag(false)
                        mode("남겨 두고 상태 승인부터 다시", "본문을 고쳐 쓰면서 이어 가요").tag(true)
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                }
                if let p = document.project, let note = BranchText.formNote(p, from: n, keep: draft.keep) {
                    Section { Text(note) }
                }
                if let e = saveError ?? model.error {
                    Section { Text(e).foregroundStyle(.red) }
                }
            }
            .formStyle(.grouped)
            .navigationTitle("갈래 만들기")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("갈래 만들기") { Task { await create() } }.disabled(model.busy || document.busy)
                }
            }
        }
        #if os(macOS)
        .frame(minWidth: 480, minHeight: 520)
        #endif
    }

    private func mode(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
            Text(detail).font(.caption).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func problem(_ field: BranchDraft.Field) -> some View {
        if let p = draft.problem, p.field == field {
            Text(p.message).font(.caption).foregroundStyle(.red)
        }
    }

    private func create() async {
        saveError = nil
        if document.dirty {  // 지금 고친 것까지 갈래로 옮긴다
            guard await document.save() else {
                saveError = document.error ?? "저장하지 못해 갈래를 만들지 않았어요"
                return
            }
        }
        var d = draft
        let made = await model.create(&d, last: last)
        draft = d
        if let made {
            dismiss()
            done(made)
        }
    }
}

/// 갈래 비교 화면: 견줄 작품 고르기, 화별 줄거리, 고른 화 두 본문, 그 화 반영 직후 상태 차이 (웹 `viewBranches`).
public struct BranchCompareScreen: View {
    let model: BranchModel
    let document: ProjectDocument
    let open: (String) -> Void
    let go: (Screen) -> Void
    @Environment(\.openBranchForm) private var openForm

    public init(model: BranchModel, document: ProjectDocument, open: @escaping (String) -> Void, go: @escaping (Screen) -> Void) {
        self.model = model
        self.document = document
        self.open = open
        self.go = go
    }

    private var last: Int { document.project.map(BranchText.lastFinal) ?? 0 }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                content
            }
            .padding()
            .frame(maxWidth: 1100, alignment: .leading)
        }
        .navigationTitle("갈래 비교")
        .toolbar {
            Button("작품 홈") { go(.home) }
            if last > 0, let openForm { Button("갈래 만들기") { openForm() } }
        }
        .task {
            await document.load()
            await model.load()
            await model.compare(other: model.wanted, ep: nil)
            model.wanted = nil
        }
        .refreshable {
            await model.load()
            await model.compare(other: model.diffWith, ep: model.diff?.episode)
        }
    }

    @ViewBuilder
    private var content: some View {
        if model.members.isEmpty {
            Text(BranchText.emptyDesc).foregroundStyle(.secondary)
            if let e = model.error {
                Notice(e, isError: true)
            } else if model.family != nil {
                Text(BranchText.empty(last: last)).note()
            } else {
                ProgressView("불러오는 중이에요")
            }
        } else if let e = model.diffError {
            Notice(e, isError: true)
        } else if let d = model.diff, let with = model.diffWith {
            compared(d, with: with)
        } else {
            ProgressView("불러오는 중이에요")
        }
    }

    @ViewBuilder
    private func compared(_ d: BranchDiff, with: String) -> some View {
        let a = BranchText.me(model.family, model.project).map(BranchText.name) ?? model.project
        let b = model.members.first { $0.name == with }.map(BranchText.name) ?? with
        let n = d.episode
        Text(BranchText.headline(d, a: a, b: b)).foregroundStyle(.secondary)
        Picker("견줄 작품", selection: Binding(get: { with }, set: { v in Task { await model.compare(other: v, ep: d.episode) } })) {
            ForEach(model.members.filter { $0.name != model.project }, id: \.name) { Text(BranchText.option($0)).tag($0.name) }
        }
        .frame(maxWidth: 360)
        if let e = model.error { Notice(e, isError: true) { model.dismissError() } }
        episodes(d, a: a, b: b, with: with)
        texts(d, a: a, b: b, with: with)
        box("\(n)화 반영 직후 상태") { state(d, a: a, b: b) }
    }

    private func episodes(_ d: BranchDiff, a: String, b: String, with: String) -> some View {
        let (rows, idle) = BranchText.episodeRows(d)
        return box("화별 줄거리") {
            Grid(alignment: .topLeading, horizontalSpacing: 12, verticalSpacing: 8) {
                GridRow {
                    Text("화").bold()
                    Text(a).bold()
                    Text(b).bold()
                }
                .font(.caption)
                Divider()
                ForEach(rows, id: \.number) { r in
                    GridRow {
                        Button("\(r.number)화") { Task { await model.compare(other: with, ep: r.number) } }
                            .buttonStyle(.borderless)
                            .fontWeight(r.current ? .bold : .regular)
                            .accessibilityAddTraits(r.current ? .isSelected : [])
                        side(r.a)
                        side(r.b)
                    }
                    .padding(.vertical, 2)
                    .background(r.current ? Color.accentColor.opacity(0.08) : .clear)
                }
            }
            Text(BranchText.episodeNote(idle: idle)).font(.caption).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func side(_ s: BranchText.Side?) -> some View {
        if let s {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(s.title).font(.subheadline.bold())
                    if let st = s.status {
                        Text(st.label).font(.caption2).padding(.horizontal, 6).padding(.vertical, 1).background(.quaternary, in: Capsule())
                    }
                }
                if !s.summary.isEmpty { Text(s.summary).font(.caption).foregroundStyle(.secondary) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Text("없음").font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func texts(_ d: BranchDiff, a: String, b: String, with: String) -> some View {
        let n = d.episode
        return box("\(n)화 본문") {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), alignment: .top)], alignment: .leading, spacing: 16) {
                column(a, text: d.textA ?? "", n: n, mine: true)
                column(b, text: d.textB ?? "", n: n, mine: false)
            }
        }
    }

    private func column(_ who: String, text: String, n: Int, mine: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(who) · \(n)화").font(.headline)
            if text.isEmpty {
                HStack {
                    Text("본문이 없어요.").font(.caption).foregroundStyle(.secondary)
                    if mine { Button("\(n)화 집필로") { go(.write) }.buttonStyle(.borderless).font(.caption) }
                }
            } else {
                ForEach(Array(paragraphs(text).enumerated()), id: \.offset) { _, p in
                    Text(p).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(who) \(n)화 본문")
    }

    /// 빈 줄로 나눈 문단 (웹 `bcParas`).
    private func paragraphs(_ text: String) -> [String] {
        text.split(separator: /\n{2,}/).map(String.init)
    }

    @ViewBuilder
    private func state(_ d: BranchDiff, a: String, b: String) -> some View {
        if let note = BranchText.notReady(d, a: a, b: b) {
            Text(note).note()
        } else {
            let rows = BranchText.diffRows(d)
            if rows.isEmpty {
                Text(BranchText.sameState(d.episode)).note()
            } else {
                Grid(alignment: .topLeading, horizontalSpacing: 12, verticalSpacing: 6) {
                    GridRow {
                        Text("구분").bold()
                        Text("항목").bold()
                        Text(a).bold()
                        Text(b).bold()
                    }
                    .font(.caption)
                    Divider()
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                        GridRow {
                            Text(r.kind).font(.caption)
                            Text(r.item).font(.caption)
                            value(r.a)
                            value(r.b)
                        }
                    }
                }
            }
        }
    }

    private func value(_ v: String?) -> some View {
        Text(v ?? "없음").font(.caption).foregroundStyle(v == nil ? .secondary : .primary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func box<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.title3.bold())
            content()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }
}

extension View {
    /// 안내 띠 (웹 `.note.plain`).
    func note() -> some View {
        self.font(.callout).padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }
}
#endif
