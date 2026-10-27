#if canImport(SwiftUI)
import CanonCore
import SwiftUI
import UniformTypeIdentifiers
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

/// 복사 · 내보내기 카드: 줄바꿈 형식, 제목 줄, 이 화 복사, 여러 화 복사, .txt 내려받기 (웹 `exportCard`).
struct PublishCard: View {
    let model: WriteModel
    let n: Int
    @State private var file: TextFile?

    var body: some View {
        let nums = model.writtenNumbers
        if !nums.isEmpty {
            let r = model.range
            let last = nums.last ?? 1
            let bad = PublishText.rangeError(from: r.from, to: r.to)
            VStack(alignment: .leading, spacing: 8) {
                Text("복사 · 내보내기").font(.headline)
                Picker("줄바꿈 형식", selection: Binding(get: { model.format }, set: { model.format = $0 })) {
                    ForEach(model.formats, id: \.id) { Text($0.label).tag($0.id) }
                    if model.formats.isEmpty { Text("문단 사이 빈 줄").tag(PublishText.defaultFormat) }
                }
                if let hint = model.formats.first(where: { $0.id == model.format })?.hint {
                    Text(hint).font(.caption).foregroundStyle(.secondary)
                }
                Toggle(PublishText.titleToggle(n), isOn: Binding(get: { model.withTitle }, set: { model.withTitle = $0 })).font(.caption)
                if nums.contains(n) {
                    HStack {
                        Button("이 화 복사") { copy([n]) }
                        Button(".txt") { download(n, n) }
                    }
                }
                HStack(spacing: 4) {
                    Text("여러 화").font(.caption)
                    Stepper(value: Binding(get: { r.from }, set: { model.setRange(from: $0) }), in: 1...last) { Text("\(r.from)").monospacedDigit() }
                        .accessibilityLabel("시작 화")
                    Text("~")
                    Stepper(value: Binding(get: { r.to }, set: { model.setRange(to: $0) }), in: 1...last) { Text("\(r.to)화").monospacedDigit() }
                        .accessibilityLabel("끝 화")
                }
                .font(.caption)
                if let bad { Text(bad).font(.caption).foregroundStyle(.red) }
                HStack {
                    Button("한꺼번에 복사") { copy(PublishText.pick(nums, from: r.from, to: r.to)) }
                    Button(".txt 내려받기") { download(r.from, r.to) }
                }
                .disabled(bad != nil)
                Text(PublishText.rangeHelp).font(.caption).foregroundStyle(.secondary)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10))
            .fileExporter(isPresented: Binding(get: { file != nil }, set: { if !$0 { file = nil } }), document: file,
                          contentType: .plainText, defaultFilename: file?.name) { result in
                if case let .failure(error) = result { model.copyFailed(error.localizedDescription) }
            }
        }
    }

    private func copy(_ numbers: [Int]) {
        Task {
            guard let out = await model.export(numbers) else { return }
            Clipboard.copy(text: out.text, html: out.html)
            model.copied(out)
        }
    }

    private func download(_ a: Int, _ b: Int) {
        Task {
            guard let out = await model.export(PublishText.pick(model.writtenNumbers, from: a, to: b)) else { return }
            file = TextFile(text: out.text, name: PublishText.filename(model.document.name, from: a, to: b))
        }
    }
}

/// .txt 내려받기 (웹 `downloadTxt`).
struct TextFile: FileDocument {
    static let readableContentTypes: [UTType] = [.plainText]
    var text: String
    var name: String

    init(text: String, name: String) {
        self.text = text
        self.name = name
    }

    init(configuration: ReadConfiguration) throws {
        text = String(decoding: configuration.file.regularFileContents ?? Data(), as: UTF8.self)
        name = ""
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
    }
}

/// 클립보드. 텍스트와 HTML 을 함께 넣어 서식 있는 편집기는 HTML 을, 메모장은 텍스트를 받는다 (웹 `copyBoth`).
enum Clipboard {
    static func copy(text: String, html: String?) {
        #if canImport(UIKit)
        var item: [String: Any] = [UTType.plainText.identifier: text]
        if let html { item[UTType.html.identifier] = html }
        UIPasteboard.general.setItems([item])
        #elseif canImport(AppKit)
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(text, forType: .string)
        if let html { pb.setString(html, forType: .html) }
        #endif
    }

    static func read() -> String? {
        #if canImport(UIKit)
        UIPasteboard.general.string
        #elseif canImport(AppKit)
        NSPasteboard.general.string(forType: .string)
        #else
        nil
        #endif
    }
}
#endif
