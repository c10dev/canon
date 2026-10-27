#if canImport(SwiftUI)
import SwiftUI

/// 이름표와 도움말이 붙은 글 칸 (웹 `input`). `lines` 가 1보다 크면 여러 줄로 늘어난다.
public struct LabeledText: View {
    let label: String
    let hint: String
    let placeholder: String
    let lines: Int
    @Binding var text: String

    public init(_ label: String, text: Binding<String>, hint: String = "", placeholder: String = "", lines: Int = 1) {
        self.label = label
        self.hint = hint
        self.placeholder = placeholder
        self.lines = lines
        _text = text
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel(label, hint: hint)
            if lines > 1 {
                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(lines...)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel(label)
            } else {
                TextField(placeholder, text: $text)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel(label)
            }
        }
    }
}

/// 한 줄에 하나씩 적는 목록 칸 (웹 `input` 의 `kind: 'list'`). 빈 줄은 빼고 앞뒤 공백은 지운다.
/// 적는 동안의 빈 줄 · 끝 줄바꿈은 칸에 남기고, 바깥에서 목록이 바뀌면 칸을 다시 채운다.
public struct ListField: View {
    let label: String
    let hint: String
    let placeholder: String
    let lines: Int
    @Binding var items: [String]
    @State private var text = ""

    public init(_ label: String, items: Binding<[String]>, hint: String = "", placeholder: String = "한 줄에 하나씩", lines: Int = 3) {
        self.label = label
        self.hint = hint
        self.placeholder = placeholder
        self.lines = lines
        _items = items
    }

    public static func parse(_ text: String) -> [String] {
        text.split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel(label, hint: hint)
            TextField(placeholder, text: $text, axis: .vertical)
                .lineLimit(lines...)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel(label)
        }
        .onAppear { text = items.joined(separator: "\n") }
        .onChange(of: text) { _, new in
            let parsed = Self.parse(new)
            if parsed != items { items = parsed }
        }
        .onChange(of: items) { _, new in
            if Self.parse(text) != new { text = new.joined(separator: "\n") }
        }
    }
}

/// 칸 이름과 회색 도움말.
public struct FieldLabel: View {
    let label: String
    let hint: String

    public init(_ label: String, hint: String = "") {
        self.label = label
        self.hint = hint
    }

    public var body: some View {
        (Text(label).font(.subheadline.weight(.semibold)) + Text(hint.isEmpty ? "" : "  \(hint)").font(.caption).foregroundStyle(.secondary))
    }
}

/// 눌러서 켜고 끄는 칩 줄 (웹 `genre-opts` 의 `aria-pressed` 버튼).
public struct ChipRow: View {
    let label: String
    let options: [String]
    let isOn: (String) -> Bool
    let toggle: (String) -> Void

    public init(_ label: String, options: [String], isOn: @escaping (String) -> Bool, toggle: @escaping (String) -> Void) {
        self.label = label
        self.options = options
        self.isOn = isOn
        self.toggle = toggle
    }

    public var body: some View {
        Flow(spacing: 6) {
                ForEach(options, id: \.self) { o in
                    Button { toggle(o) } label: {
                        Text(o).font(.callout)
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(isOn(o) ? Color.accentColor.opacity(0.2) : Color.secondary.opacity(0.08), in: Capsule())
                            .overlay(Capsule().stroke(isOn(o) ? Color.accentColor : .secondary.opacity(0.3)))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(isOn(o) ? .isSelected : [])
                }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(label)
    }
}

/// 줄이 차면 다음 줄로 넘기는 배치 (칩, 이름 후보).
public struct Flow: Layout {
    let spacing: CGFloat

    public init(spacing: CGFloat = 6) {
        self.spacing = spacing
    }

    public func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(proposal.width ?? .infinity, subviews)
        let width = rows.map { $0.width }.max() ?? 0
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width ?? width, height: height)
    }

    public func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(bounds.width, subviews) {
            var x = bounds.minX
            for i in row.items {
                let size = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var items: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(_ maxWidth: CGFloat, _ subviews: Subviews) -> [Row] {
        var rows: [Row] = [Row()]
        for i in subviews.indices {
            let size = subviews[i].sizeThatFits(.unspecified)
            let extra = rows[rows.count - 1].items.isEmpty ? size.width : rows[rows.count - 1].width + spacing + size.width
            if extra > maxWidth, !rows[rows.count - 1].items.isEmpty {
                rows.append(Row())
            }
            var r = rows[rows.count - 1]
            r.width = r.items.isEmpty ? size.width : r.width + spacing + size.width
            r.height = max(r.height, size.height)
            r.items.append(i)
            rows[rows.count - 1] = r
        }
        return rows.filter { !$0.items.isEmpty }
    }
}
#endif
