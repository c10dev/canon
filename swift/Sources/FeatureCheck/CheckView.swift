#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 검수 (5단계): 한 화의 검수 세션. 회차 띠 · 처리 상태 거르기, 지적 목록 · 본문 · 지적 상세, 문체 지표 탭 (웹 `check.js` 의 `viewCheck`).
/// 본문은 읽기 전용이다. 고치기는 집필 화면에서 한다 (앱에는 아직 검수 화면의 부분 수정 도구가 없다).
/// 1~3화 초반 점검(흡입력 판정)은 앱에 아직 없어 웹에서 본다.
public struct CheckView: View {
    @State private var model: CheckModel
    let go: (Screen) -> Void
    @Environment(\.horizontalSizeClass) private var sizeClass

    public init(document: ProjectDocument, jobs: JobCenter, service: any CheckService, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: CheckModel(document: document, jobs: jobs, service: service))
        self.go = go
    }

    public var body: some View {
        Group {
            if let p = model.project {
                content(p)
            } else if let error = model.document.error {
                ContentUnavailableView("작품을 불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("불러오는 중")
            }
        }
        .task { await model.start() }
        .onChange(of: model.selectedID) { model.syncNote() }
    }

    private func content(_ p: Project) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header(p)
                if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
                if let f = model.failure {
                    HStack {
                        Text("지난 시도 실패 · \(f.label): \(f.error)").frame(maxWidth: .infinity, alignment: .leading)
                        Button("다시 시도") { Task { await model.check() } }
                        Button("닫기") { Task { await model.jobs.dismissFailure(f.key) } }
                    }
                    .note(.warn)
                }
                if model.autoRunning {
                    HStack {
                        Text("자동 집필이 쓰는 중이에요. 검수하거나 지적 상태를 바꾸려면 자동 집필을 일시정지하세요.").frame(maxWidth: .infinity, alignment: .leading)
                        Button("자동 집필") { go(.auto) }
                    }
                    .note(.warn)
                }
                if let e = model.episode {
                    if (e.text ?? "").isEmpty {
                        VStack(spacing: 10) {
                            Text("\(model.ep)화 본문이 아직 없어요. 본문을 쓴 뒤 검수해요.")
                            Button("\(model.ep)화 집필로") { go(.write) }.buttonStyle(.borderedProminent)
                        }
                        .frame(maxWidth: .infinity).padding(30)
                    } else {
                        session(e)
                    }
                } else {
                    ContentUnavailableView("화가 없어요", systemImage: "doc", description: Text("기승전결 · 플롯에서 화별 플롯을 먼저 만드세요"))
                }
            }
            .padding()
            .frame(maxWidth: 1400, alignment: .leading)
        }
    }

    // MARK: 위쪽

    private func header(_ p: Project) -> some View {
        let eps = p.episodes ?? []
        let numbers = eps.map(\.plot.number)
        let i = numbers.firstIndex(of: model.ep)
        return HStack(alignment: .center, spacing: 12) {
            Button { if let i, i > 0 { Task { await model.select(numbers[i - 1]) } } } label: { Image(systemName: "chevron.left") }
                .disabled(i == nil || i == 0)
                .accessibilityLabel("앞 화")
            Menu {
                ForEach(eps, id: \.plot.number) { e in
                    Button("\(e.plot.number)화 \(e.plot.title)\(e.checkState.open > 0 ? " · 열린 지적 \(e.checkState.open)" : "")") {
                        Task { await model.select(e.plot.number) }
                    }
                }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("5단계 검수 · \(model.ep) / \(p.meta?.targetEpisodes ?? 0)화").font(.caption).foregroundStyle(.secondary)
                    Text("\(model.ep)화 \(model.episode?.plot.title ?? "")").font(.title.bold())
                }
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            Button { if let i, i + 1 < numbers.count { Task { await model.select(numbers[i + 1]) } } } label: { Image(systemName: "chevron.right") }
                .disabled(i == nil || i! + 1 >= numbers.count)
                .accessibilityLabel("다음 화")
            Spacer()
            if let e = model.episode, !(e.text ?? "").isEmpty {
                let cs = e.checkState
                let first = e.rounds?.isEmpty ?? true
                Button(model.checkBusy ?? CheckText.checkLabel(e)) { Task { await model.check() } }
                    .prominent(first || cs.stale)
                    .disabled(model.checkBusy != nil || model.autoRunning)
                Button("집필에서 고치기") { go(.write) }.buttonStyle(.bordered)
                if e.status == .written {
                    Button(CheckText.reviewLabel(e)) { go(.review) }
                        .prominent(!first && !cs.stale)
                }
            }
        }
    }

    // MARK: 세션

    @ViewBuilder
    private func session(_ e: Episode) -> some View {
        if let rounds = e.rounds, !rounds.isEmpty {
            strip(e, rounds)
            if let s = CheckText.staleNote(e) { Text(s).note(.warn) }
        }
        if sizeClass == .compact {
            VStack(alignment: .leading, spacing: 14) {
                list(e)
                detail(e)
                bodyText(e)
            }
        } else {
            HStack(alignment: .top, spacing: 14) {
                list(e).frame(width: 280)
                bodyText(e).frame(maxWidth: .infinity)
                detail(e).frame(width: 320)
            }
        }
    }

    private func strip(_ e: Episode, _ rounds: [CheckRound]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    Text("회차").font(.caption).foregroundStyle(.secondary)
                    ForEach(rounds.suffix(4), id: \.no) { r in
                        let last = r.no == rounds.last?.no
                        Text(CheckText.round(r)).font(.caption.monospacedDigit().weight(last ? .bold : .regular))
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .overlay(Capsule().stroke(last ? Color.accentColor : Color.secondary.opacity(0.4)))
                    }
                }
            }
            Picker("처리 상태로 거르기", selection: $model.filter) {
                ForEach(CheckText.Filter.allCases, id: \.self) { f in
                    Text("\(f.label) \(CheckText.count(e, f))").tag(f)
                }
            }
            .pickerStyle(.segmented)
        }
        .padding(10)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
    }

    private func list(_ e: Episode) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("검수 종류", selection: $model.tab) {
                Text("모순 지적 \(e.findings?.count ?? 0)").tag(CheckModel.Tab.issues)
                Text("문체 지표").tag(CheckModel.Tab.style)
            }
            .pickerStyle(.segmented)
            switch model.tab {
            case .style: styleBox()
            case .issues:
                if e.rounds?.isEmpty ?? true {
                    Text(CheckText.notChecked).font(.callout).foregroundStyle(.secondary)
                } else if model.shown.isEmpty {
                    Text(CheckText.empty(model.filter)).font(.callout).foregroundStyle(.secondary)
                } else {
                    ForEach(model.shown, id: \.id) { f in item(e, f) }
                }
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
    }

    private func item(_ e: Episode, _ f: Finding) -> some View {
        let s = CheckText.status(f)
        let on = f.id == model.selectedID
        return Button { if let id = f.id { model.choose(id) } } label: {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 4) {
                    Chip(f._type.rawValue, tint: .secondary)
                    Chip(s.label, tint: tint(s))
                    if let flag = CheckText.flag(e, f, text: model.text) { Chip(flag.label, tint: .secondary) }
                }
                Text(f.description).font(.callout).foregroundStyle(s == .open ? .primary : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text("근거 · \(CheckText.source(model.ep, f))").font(.caption).foregroundStyle(.secondary)
            }
            .padding(10)
            .background(on ? Color.accentColor.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(on ? Color.accentColor : Color.secondary.opacity(0.3)))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    @ViewBuilder
    private func styleBox() -> some View {
        switch model.style[model.ep] {
        case nil: ProgressView("재는 중")
        case let .failure(err): Text(err.errorDescription ?? "").note(.error)
        case let .success(d):
            if d.warnings.isEmpty {
                Text(CheckText.noStyleWarning).note(.info)
            } else {
                ForEach(Array(d.warnings.enumerated()), id: \.offset) { _, w in Text("• \(w)").font(.callout) }
            }
            Text(CheckText.styleNote).font(.caption).foregroundStyle(.secondary)
            Button("다시 재기") { Task { await model.loadStyle() } }.controlSize(.small)
        }
    }

    /// 본문: 열린 지적 문장과 고른 지적 문장에 바탕색을 깐다.
    private func bodyText(_ e: Episode) -> some View {
        let text = model.text
        var a = AttributedString()
        var at = text.startIndex
        for m in model.marks.sorted(by: { $0.range.lowerBound < $1.range.lowerBound }) where m.range.lowerBound >= at {
            a += AttributedString(String(text[at..<m.range.lowerBound]))
            var piece = AttributedString(String(text[m.range]))
            piece.backgroundColor = m.selected ? Color.orange.opacity(0.45) : Color.orange.opacity(0.18)
            piece.underlineStyle = .single
            a += piece
            at = m.range.upperBound
        }
        a += AttributedString(String(text[at...]))
        return Text(a).font(.system(.body, design: .serif)).lineSpacing(8).textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(.background, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(.quaternary))
    }

    @ViewBuilder
    private func detail(_ e: Episode) -> some View {
        if model.tab == .issues, let f = model.selected {
            let s = CheckText.status(f)
            let q = f.currentQuote.trimmingCharacters(in: .whitespacesAndNewlines)
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 4) {
                    Chip(f._type.rawValue, tint: .secondary)
                    Chip(s.label, tint: tint(s))
                    Text("\(f.first ?? 1)회차부터\(f.last != f.first ? " · 마지막 \(f.last ?? 1)회차" : "")").font(.caption).foregroundStyle(.secondary)
                }
                Text(f.description).font(.headline)
                if !q.isEmpty {
                    field("이번 화") {
                        quote(q, now: true)
                        if !model.text.contains(q) { Text(CheckText.notFound).font(.caption).foregroundStyle(.secondary) }
                    }
                }
                if !f.sourceQuote.isEmpty {
                    field("근거 · \(CheckText.source(model.ep, f))") { quote(f.sourceQuote, now: false) }
                }
                if let sug = f.suggestion, !sug.isEmpty { field("고칠 방향") { Text("→ \(sug)").font(.callout) } }
                field("처리") {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 6) {
                        ForEach(CheckText.Status.allCases, id: \.self) { k in
                            Button(k.label) { Task { await model.set(k) } }
                                .prominent(k == s)
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .disabled(model.busy || model.autoRunning)
                }
                if s == .kept || s == .wrong {
                    field(CheckText.notePrompt(s)) {
                        TextField("메모", text: $model.note, axis: .vertical).lineLimit(2...4).textFieldStyle(.roundedBorder)
                        Button("메모 저장") { Task { await model.saveNote() } }.controlSize(.small).disabled(model.busy)
                    }
                }
                if s == .fixed, f.closedBy == .recheck { Text(CheckText.recheckClosed).font(.caption).foregroundStyle(.secondary) }
            }
            .padding(12)
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func field<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            content()
        }
    }

    private func quote(_ text: String, now: Bool) -> some View {
        Text(text).font(.system(.callout, design: .serif)).textSelection(.enabled)
            .padding(8).frame(maxWidth: .infinity, alignment: .leading)
            .overlay(alignment: .leading) { Rectangle().fill(now ? Color.orange : Color.secondary).frame(width: 3) }
            .background(.quaternary.opacity(0.4))
    }

    private func tint(_ s: CheckText.Status) -> Color {
        switch s {
        case .open: .orange
        case .fixed: .green
        case .kept: .accentColor
        case .wrong: .secondary
        }
    }
}

/// 작은 표 (웹 `.chip`).
struct Chip: View {
    let text: String
    let tint: Color

    init(_ text: String, tint: Color) {
        self.text = text
        self.tint = tint
    }

    var body: some View {
        Text(text).font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
            .foregroundStyle(tint)
            .background(tint.opacity(0.15), in: Capsule())
    }
}

enum NoteKind { case info, warn, error, plain }

/// 주 단추와 보통 단추를 조건으로 바꾼다.
private struct Prominent: ViewModifier {
    let on: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if on { content.buttonStyle(.borderedProminent) } else { content.buttonStyle(.bordered) }
    }
}

extension View {
    func prominent(_ on: Bool) -> some View { modifier(Prominent(on: on)) }

    /// 안내 띠 (웹 `.note`).
    func note(_ kind: NoteKind) -> some View {
        let color: Color = switch kind {
        case .info: .blue
        case .warn: .orange
        case .error: .red
        case .plain: .secondary
        }
        return self.font(.callout).padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }
}
#endif
