#if canImport(SwiftUI)
import CanonAPI
import CanonUI
import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

/// 상태창 수치 화면. 왼쪽은 인물, 오른쪽은 지금 상태창 · 본문에 넣을 글 · 화별 변화 (웹 `viewStatwin`).
public struct StatWinScreen: View {
    @State private var model: StatWinModel

    public init(server: CanonServer, project: String) {
        _model = State(initialValue: StatWinModel(project: project, source: LiveStatWin(server: server)))
    }

    public init(model: StatWinModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        GeometryReader { geo in
            Group {
                if !model.loaded {
                    ProgressView("불러오는 중…").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if !model.hasCharacters {
                    ContentUnavailableView("아직 인물이 없어요", systemImage: "person.2", description: Text("설정 도우미에서 인물을 만드세요"))
                } else if geo.size.width >= 720 {
                    HStack(alignment: .top, spacing: 0) {
                        PeopleList(model: model).frame(width: 220)
                        Divider()
                        content(picker: false)
                    }
                } else {
                    content(picker: true)
                }
            }
        }
        .navigationTitle("상태창 수치")
        #if os(iOS)
        // 큰 제목은 넓은 화면에서 인물 목록 위에 붙는다
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .task { await model.load() }
    }

    private func content(picker: Bool) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("레벨, 능력치, 스킬처럼 본문에 숫자로 나오는 값을 인물마다 화별로 기록해요. 항목을 하나라도 정하면 AI가 본문을 쓸 때 이 값을 따르고, 바뀐 값만 상태 변경안에 적어요. 반영은 승인한 뒤에만 돼요.")
                    .font(.callout).foregroundStyle(.secondary)
                if picker { PeoplePicker(model: model) }
                if let error = model.error {
                    Notice(error, isError: true)
                } else if let view = model.view {
                    EditorCard(model: model, view: view)
                    PreviewCard(model: model, view: view)
                    TimelineCard(view: view)
                }
            }
            .padding()
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .refreshable { await model.load() }
        // 알림은 아래에 겹쳐 띄워, 저장 · 복사 뒤에 칸이 밀리지 않게 한다
        .overlay(alignment: .bottom) {
            if let n = model.notice {
                Notice(n.text, isError: n.isError) { model.dismissNotice() }
                    .frame(maxWidth: 520)
                    .padding()
                    .task(id: n.text) {
                        guard !n.isError else { return }
                        try? await Task.sleep(for: .seconds(3))
                        if model.notice?.text == n.text { model.dismissNotice() }
                    }
            }
        }
    }
}

/// 넓은 화면의 인물 목록.
struct PeopleList: View {
    let model: StatWinModel

    var body: some View {
        List(model.people) { person in
            Button {
                Task { await model.select(person.id) }
            } label: {
                HStack {
                    Text(person.name).fontWeight(person.id == model.selected ? .bold : .regular)
                    Spacer()
                    Text(StatWinText.count(person.count)).font(.caption).foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(person.id == model.selected ? Color.accentColor.opacity(0.15) : Color.clear)
            .accessibilityAddTraits(person.id == model.selected ? .isSelected : [])
        }
        .accessibilityLabel("인물")
    }
}

/// 좁은 화면(iPhone)의 인물 고르기.
struct PeoplePicker: View {
    let model: StatWinModel

    var body: some View {
        Picker("인물", selection: Binding(get: { model.selected }, set: { id in Task { await model.select(id) } })) {
            ForEach(model.people) { person in
                Text(person.count > 0 ? "\(person.name) · \(StatWinText.count(person.count))" : person.name).tag(person.id)
            }
        }
        .pickerStyle(.menu)
    }
}

/// 지금 상태창: 항목 고치기, 틀, 저장 (웹 `swEditor`).
struct EditorCard: View {
    @Bindable var model: StatWinModel
    let view: StatwinView

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                if model.rows.isEmpty {
                    Text("항목이 없어요. 아래에서 항목을 더하거나 틀을 고르세요.").font(.caption).foregroundStyle(.secondary)
                }
                ForEach($model.rows) { $row in
                    HStack(spacing: 8) {
                        TextField("항목 (예: 레벨)", text: $row.name)
                            .frame(width: 140)
                            .accessibilityLabel("항목 이름")
                        TextField("값 (+3 처럼 적으면 더함)", text: $row.value)
                            .accessibilityLabel("\(row.name.isEmpty ? "항목" : row.name) 값")
                        Button("지우기", role: .destructive) { model.removeRow(row.id) }
                            .buttonStyle(.borderless)
                            .accessibilityLabel("\(row.name.isEmpty ? "항목" : row.name) 지우기")
                    }
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .noAutocapitalization()
                }
                HStack(spacing: 8) {
                    Button("+ 항목") { model.addRow() }
                    if model.rows.isEmpty {
                        Text("틀:").font(.caption).foregroundStyle(.secondary)
                        ForEach(model.presetKeys, id: \.self) { key in
                            Button(StatWinText.presetLabel(key)) { model.applyPreset(key) }
                                .help((view.presets.additionalProperties[key] ?? []).joined(separator: ", "))
                        }
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                HStack(alignment: .bottom) {
                    Text("저장하면 마지막으로 반영한 화의 작가 기록으로 남아요. 값을 비운 항목은 틀만 남고, 지운 항목은 '지움'으로 기록돼요.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("저장") { Task { await model.save() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(!model.dirty || model.busy)
                }
            }
        } label: {
            HStack {
                Text("지금 상태창").font(.headline)
                Spacer()
                Text(StatWinText.recorded(view)).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// 본문에 넣을 상태창: 복사, 서식 고치기 (웹 `swPreview`).
struct PreviewCard: View {
    let model: StatWinModel
    let view: StatwinView
    @State private var editing = false
    @State private var template = ""
    @State private var row = ""

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                Text(StatWinText.preview(view))
                    .font(.system(.callout, design: .serif))
                    .lineSpacing(4)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
                if editing {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("상태창 서식").font(.subheadline.bold())
                            + Text("  {name} 인물 이름, {rows} 항목 줄").font(.caption).foregroundStyle(.secondary)
                        TextEditor(text: $template)
                            .font(.callout.monospaced())
                            .autocorrectionDisabled()
                            .noAutocapitalization()
                            .frame(minHeight: 90)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                            .accessibilityLabel("상태창 서식")
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("항목 한 줄").font(.subheadline.bold())
                            + Text("  {key} 항목, {value} 값").font(.caption).foregroundStyle(.secondary)
                        TextField(StatWinText.defaultRow, text: $row)
                            .textFieldStyle(.roundedBorder)
                            .autocorrectionDisabled()
                            .noAutocapitalization()
                            .accessibilityLabel("항목 한 줄")
                    }
                    HStack {
                        Button("서식 저장") { Task { await model.saveTemplate(template, row: row) } }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy)
                        Text("AI가 본문에 상태창을 쓸 때도 이 서식을 따라요.").font(.caption).foregroundStyle(.secondary)
                    }
                    .controlSize(.small)
                }
            }
        } label: {
            HStack {
                Text("본문에 넣을 상태창").font(.headline)
                Spacer()
                Button(editing ? "서식 닫기" : "서식 고치기") {
                    if !editing {
                        template = model.template
                        row = model.rowTemplate
                    }
                    editing.toggle()
                }
                .buttonStyle(.bordered)
                Button("복사") { model.copied(Clipboard.copy(view.text)) }
                    .buttonStyle(.borderedProminent)
            }
            .controlSize(.small)
        }
    }
}

/// 화별 변화 표 (웹 `swTimeline`). 바뀐 칸을 누르면 이전 값과 바뀐 값을 아래에 보인다.
struct TimelineCard: View {
    let view: StatwinView
    @State private var tip: String?

    var body: some View {
        GroupBox {
            if view.columns.isEmpty {
                Text("아직 기록이 없어요. 상태 승인 화면에서 AI가 적은 수치를 반영하거나, 위에서 값을 저장하면 쌓여요.")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ScrollView(.horizontal) { table }
                    Text(tip ?? "바뀐 칸을 누르면 이전 값과 바뀐 값을 봐요.")
                        .font(.caption).foregroundStyle(tip == nil ? .secondary : .primary)
                }
            }
        } label: {
            HStack {
                Text("화별 변화").font(.headline)
                Spacer()
                legend(Color.accentColor, "AI 변경안으로 바뀜")
                legend(Color.orange, "작가가 고침")
            }
        }
    }

    private var table: some View {
        Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
            GridRow {
                head("항목")
                ForEach(view.columns, id: \.episode) { head(StatWinText.columnTitle($0.episode)) }
            }
            Divider()
            ForEach(view.names, id: \.self) { name in
                GridRow {
                    head(name)
                    ForEach(view.columns, id: \.episode) { col in
                        cell(StatCell(col, name: name), title: "\(StatWinText.columnTitle(col.episode)) \(name)")
                    }
                }
                Divider()
            }
        }
        .font(.footnote)
    }

    private func head(_ text: String) -> some View {
        Text(text).bold().foregroundStyle(.secondary).lineLimit(1).padding(.horizontal, 10).padding(.vertical, 8)
    }

    @ViewBuilder
    private func cell(_ c: StatCell, title: String) -> some View {
        switch c {
        case let .plain(v):
            Text(v).lineLimit(1).padding(.horizontal, 10).padding(.vertical, 8)
        case let .changed(v, author, t):
            let color = author ? Color.orange : Color.accentColor
            Button { tip = "\(title): \(t)" } label: {
                Text(v).bold().lineLimit(1).foregroundStyle(color).padding(.horizontal, 10).padding(.vertical, 8)
                    .background(color.opacity(0.15))
            }
            .buttonStyle(.plain)
            .help(t)
            .accessibilityLabel("\(title): \(t)")
        case let .gone(before, t):
            Button { tip = "\(title): \(t)" } label: {
                Text(before).strikethrough().lineLimit(1).foregroundStyle(.secondary).padding(.horizontal, 10).padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .help(t)
            .accessibilityLabel("\(title): \(t)")
        }
    }

    private func legend(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 3).fill(color.opacity(0.15)).stroke(color).frame(width: 12, height: 12)
            Text(text).font(.caption).foregroundStyle(.secondary)
        }
    }
}

extension View {
    /// 항목 이름 · 서식은 영문 첫 글자를 대문자로 바꾸지 않는다 (iOS 만 있는 설정).
    func noAutocapitalization() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never)
        #else
        self
        #endif
    }
}

/// iOS · macOS 클립보드에 글을 넣는다.
enum Clipboard {
    @MainActor
    static func copy(_ text: String) -> Bool {
        #if canImport(UIKit)
        // 다시 읽어 확인하지 않는다. iOS 는 다른 앱이 넣은 글을 읽을 때 붙여넣기 허락을 묻는다
        UIPasteboard.general.string = text
        return true
        #elseif canImport(AppKit)
        NSPasteboard.general.clearContents()
        return NSPasteboard.general.setString(text, forType: .string)
        #else
        return false
        #endif
    }
}
#endif
