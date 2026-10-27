#if canImport(SwiftUI)
import CanonCore
import SwiftUI

/// 이름 붙은 글 칸. 여러 줄이면 늘어난다.
struct TextRow: View {
    let label: String
    let text: Binding<String>
    var lines = 1
    var hint: String?
    var placeholder = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption.bold()).foregroundStyle(.secondary)
            if lines > 1 {
                TextField(placeholder, text: text, axis: .vertical).lineLimit(lines...)
            } else {
                TextField(placeholder, text: text)
            }
            if let hint { Text(hint).font(.caption2).foregroundStyle(.secondary) }
        }
        .textFieldStyle(.roundedBorder)
    }
}

/// 한 줄에 하나씩 적는 목록 칸 (웹 `kind: 'list'`). 빈 줄은 빼고 넘긴다. 적는 동안 빈 줄이 사라지지 않게 글은 이 칸이 들고 있고,
/// 바깥 값이 바뀌면(작업이 그 화를 채움, 다시 받음) 글을 다시 맞춘다.
struct ListRow: View {
    let label: String
    let value: [String]
    let set: ([String]) -> Void
    var lines = 3
    var hint: String?
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption.bold()).foregroundStyle(.secondary)
            TextField("한 줄에 하나씩", text: $text, axis: .vertical)
                .lineLimit(lines...)
                .textFieldStyle(.roundedBorder)
                .onChange(of: text) { _, v in
                    let list = Self.parse(v)
                    if list != value { set(list) }
                }
            if let hint { Text(hint).font(.caption2).foregroundStyle(.secondary) }
        }
        .onAppear { text = value.joined(separator: "\n") }
        .onChange(of: value) { _, v in
            if Self.parse(text) != v { text = v.joined(separator: "\n") }
        }
    }

    static func parse(_ text: String) -> [String] {
        text.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
}

/// 화 번호 칸. 다 적고 나서(엔터, 칸 나가기) 값을 넘긴다.
struct NumberRow: View {
    let label: String
    let value: Binding<Int>
    var hint: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption.bold()).foregroundStyle(.secondary)
            TextField(label, value: value, format: .number)
                .textFieldStyle(.roundedBorder)
                #if os(iOS)
                .keyboardType(.numberPad)
                #endif
            if let hint { Text(hint).font(.caption2).foregroundStyle(.secondary) }
        }
    }
}

/// 안내 칸 (웹 `.note`).
struct NoteBox: View {
    enum Tone { case info, warn, plain }
    let text: String
    var tone: Tone = .info

    var body: some View {
        Text(text)
            .font(.callout)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }

    private var color: Color {
        switch tone {
        case .info: .blue
        case .warn: .orange
        case .plain: .gray
        }
    }
}

/// 칩 (상태, 구간 이름).
struct Chip: View {
    let text: String
    var color: Color = .secondary

    var body: some View {
        Text(text).font(.caption2).padding(.horizontal, 6).padding(.vertical, 2)
            .background(color.opacity(0.18), in: Capsule())
    }
}

extension EpisodeStatus {
    /// 화 상태 색 (작품 홈과 같다).
    var color: Color {
        switch self {
        case .draft: .gray
        case .confirmed: .accentColor
        case .written: .orange
        case .finalized: .green
        }
    }
}

/// 구간 색 (웹 `actClass`).
func actColor(_ name: Act.NamePayload) -> Color {
    switch name {
    case .기: .blue
    case .승: .green
    case .전: .orange
    case .결: .purple
    }
}

/// 카드 바탕.
struct CardBox<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10, content: content)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }
}
#endif
