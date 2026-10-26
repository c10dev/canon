#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 플롯 편집기에 붙는 줄기 칸: 이 화가 따라가는 줄기와 장면으로 끼어드는 줄기 (웹 `lineField`).
/// 줄기가 없으면 아무것도 그리지 않는다. 고치기는 `change` 로 넘긴다 (예: `LineField(...) { model.editPlot(n, $0) }`).
public struct LineField: View {
    let project: Project
    let plot: Components.Schemas.EpisodePlot
    let locked: Bool
    let written: Bool
    let change: ((inout Components.Schemas.EpisodePlot) -> Void) -> Void

    /// locked: 작업이 이 화를 쓰는 중이라 고치지 못한다. written: 본문이 있는 화 (도움말만 바뀐다).
    public init(project: Project, plot: Components.Schemas.EpisodePlot, locked: Bool, written: Bool, change: @escaping ((inout Components.Schemas.EpisodePlot) -> Void) -> Void) {
        self.project = project
        self.plot = plot
        self.locked = locked
        self.written = written
        self.change = change
    }

    public var body: some View {
        if !LineRules.lines(project).isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                VStack(alignment: .leading, spacing: 4) {
                    FieldLabel("이야기 줄기", hint: LineRules.fieldHint(written: written && !locked))
                    Picker("이야기 줄기", selection: Binding(get: { plot.storyline ?? "" }, set: { id in change { LineRules.setMain(&$0, id) } })) {
                        ForEach(LineRules.fieldOptions(project), id: \.id) { o in Text(o.label).tag(o.id) }
                    }
                    .labelsHidden()
                    .disabled(locked)
                }
                let scenes = LineRules.sceneOptions(project, plot)
                if !scenes.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        FieldLabel("장면으로 끼어드는 줄기")
                        Flow(spacing: 10) {
                            ForEach(scenes, id: \.id) { s in
                                Toggle(LineRules.title(s, empty: s.id), isOn: Binding(
                                    get: { (plot.threads ?? []).contains(s.id) },
                                    set: { on in change { LineRules.setThread(&$0, s.id, on) } }))
                                .toggleStyle(.checkboxLike)
                                .disabled(locked)
                            }
                        }
                    }
                }
            }
        }
    }
}

/// 화 카드에 붙는 줄기 표시 (웹 `lineBadge`). 붙은 줄기가 없으면 빈칸.
public struct LineBadges: View {
    let badges: [LineRules.Badge]

    public init(project: Project, plot: Components.Schemas.EpisodePlot) {
        badges = LineRules.badges(project, plot)
    }

    public var body: some View {
        if !badges.isEmpty {
            Flow(spacing: 4) {
                ForEach(badges, id: \.id) { LineBadgeView(text: $0.text, color: Color(lineHex: $0.color), scene: $0.scene) }
            }
        }
    }
}

/// 줄기 색 점이 붙은 작은 표시. 장면은 테두리만.
struct LineBadgeView: View {
    let text: String
    let color: Color
    var scene = false

    var body: some View {
        HStack(spacing: 4) {
            Circle().fill(scene ? Color.clear : color).overlay(Circle().stroke(color, lineWidth: 1.5)).frame(width: 8, height: 8)
            Text(text).lineLimit(1)
        }
        .font(.caption2)
        .padding(.horizontal, 6).padding(.vertical, 2)
        .background(color.opacity(0.12), in: Capsule())
    }
}

/// 체크 상자처럼 보이는 켜고 끄기. macOS 는 체크 상자, iOS 는 누르는 칩.
struct CheckboxLike: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button { configuration.isOn.toggle() } label: {
            HStack(spacing: 6) {
                Image(systemName: configuration.isOn ? "checkmark.square.fill" : "square")
                    .foregroundStyle(configuration.isOn ? Color.accentColor : .secondary)
                configuration.label
            }
            .font(.callout)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(configuration.isOn ? .isSelected : [])
    }
}

extension ToggleStyle where Self == CheckboxLike {
    static var checkboxLike: CheckboxLike { CheckboxLike() }
}

extension Color {
    /// '#B4570A' 같은 글로 색을 만든다.
    init(lineHex text: String) {
        let v = UInt32(text.dropFirst(), radix: 16) ?? 0
        self.init(red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255, blue: Double(v & 0xFF) / 255)
    }

    /// 화 점 안쪽 색 (웹 `DOT_FILL`). 초안은 바탕색이라 nil.
    static func lineDotFill(_ s: EpisodeStatus) -> Color? {
        switch s {
        case .draft: nil
        case .confirmed: Color.accentColor.opacity(0.22)
        case .written: Color(lineHex: "#A85300").opacity(0.22)
        case .finalized: Color(lineHex: "#1C6E45").opacity(0.22)
        }
    }

    static let lineWritten = Color(lineHex: "#A85300")
    static let lineFinalized = Color(lineHex: "#1C6E45")

    /// 기 · 승 · 전 · 결 띠 색 (웹 `act-1` ~ `act-4`).
    static func lineBand(_ i: Int) -> Color {
        switch i % 4 {
        case 0: .blue
        case 1: .green
        case 2: .orange
        default: .purple
        }
    }
}

/// 카드 바탕.
struct LinesCard<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12, content: content)
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// 안내 칸 (웹 `.note`).
struct LinesNote: View {
    let text: String
    var warn = false

    var body: some View {
        Text(text)
            .font(.callout)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background((warn ? Color.orange : Color.blue).opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }
}

/// 숫자 칸. 0 은 비워 보인다 (웹 `input` 의 `zeroBlank`).
struct EpisodeNumberField: View {
    let label: String
    let hint: String
    let placeholder: String
    @Binding var value: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel(label, hint: hint)
            TextField(placeholder, value: Binding(get: { value == 0 ? nil : value }, set: { value = max(0, $0 ?? 0) }), format: .number)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel(label)
#if os(iOS)
                .keyboardType(.numberPad)
#endif
        }
    }
}

/// 중심 인물 고르기.
struct FocusPicker: View {
    let project: Project
    let focus: [String]
    let toggle: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel("중심 인물")
            let chars = project.characters ?? []
            if chars.isEmpty {
                Text("인물이 아직 없어요.").font(.caption).foregroundStyle(.secondary)
            } else {
                Flow(spacing: 10) {
                    ForEach(chars, id: \.id) { c in
                        Toggle(c.name.isEmpty ? c.id : c.name, isOn: Binding(get: { focus.contains(c.id) }, set: { _ in toggle(c.id) }))
                            .toggleStyle(.checkboxLike)
                    }
                }
            }
        }
    }
}

/// 종류 고르기와 도움말.
struct KindPicker: View {
    @Binding var kind: StorylineKind

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel("종류", hint: LineRules.hint(kind))
            Picker("종류", selection: $kind) {
                ForEach(LineRules.kinds, id: \.self) { Text($0.rawValue).tag($0) }
            }
            .labelsHidden()
            .fixedSize()
        }
    }
}
#endif
