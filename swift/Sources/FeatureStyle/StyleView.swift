#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 문체 레퍼런스 (웹 `viewStyle`): 문체 라이브러리, 예시 원문과 분석, 기준 지표, 스타일 프로필.
public struct StyleView: View {
    @State private var model: StyleModel
    @State private var pick = ""
    @State private var asking: Ask?
    @State private var entryName = ""
    @State private var pushNote = ""
    let go: (Screen) -> Void

    enum Ask: Identifiable {
        case analyze(String), use(String, String), keep, push, pull(String)
        var id: String {
            switch self {
            case .analyze: "analyze"
            case .use: "use"
            case .keep: "keep"
            case .push: "push"
            case .pull: "pull"
            }
        }
    }

    public init(document: ProjectDocument, server: CanonServer, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: StyleModel(document: document, service: LiveStyleService(server: server)))
        self.go = go
    }

    public var body: some View {
        Group {
            if model.project != nil {
                content
            } else if let error = model.document.error {
                ContentUnavailableView("작품을 불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("불러오는 중")
            }
        }
        .task { await model.load() }
        .alert(alertTitle, isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }), presenting: asking) { ask in
            alertActions(ask)
        } message: { ask in
            Text(alertMessage(ask))
        }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("2단계").font(.caption).foregroundStyle(.secondary)
                    Text("문체 레퍼런스").font(.largeTitle.bold())
                    Text("닮고 싶은 소설 문단을 붙여 넣으면 문체 규칙을 뽑아요. 규칙과 원문 예시가 매 화 본문 생성에 함께 들어가요. 라이브러리에 저장한 문체를 그대로 가져올 수도 있어요.")
                        .foregroundStyle(.secondary)
                    Button(model.document.serial ? "부 · 아크로" : "기승전결로") { go(.arc) }.buttonStyle(.borderedProminent)
                }
                if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 20) {
                        left.frame(width: 380)
                        ProfileCard(model: model)
                    }
                    VStack(alignment: .leading, spacing: 20) {
                        left
                        ProfileCard(model: model)
                    }
                }
            }
            .padding()
            .frame(maxWidth: 1200, alignment: .leading)
        }
        .disabled(model.busy != nil)
        .overlay(alignment: .top) {
            if let busy = model.busy { ProgressView(busy).padding(10).background(.thinMaterial, in: Capsule()).padding(.top, 8) }
        }
    }

    private var left: some View {
        VStack(alignment: .leading, spacing: 20) {
            libraryCard
            sampleCard
            baselineCard
        }
    }

    // MARK: 라이브러리

    private var libraryCard: some View {
        let l = model.link
        let status = StyleText.status(l, blank: StyleText.blank(model.profile))
        return Card("문체 라이브러리") {
            Text(status.text).font(.callout)
            if let l, !StyleText.diffLines(l).isEmpty {
                DisclosureGroup("어느 칸이 다른지") {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(StyleText.diffLines(l), id: \.self) { Text($0).font(.caption) }
                    }
                }
                .font(.caption)
            }
            if model.library.isEmpty {
                Text("라이브러리가 비어 있어요. \(model.canKeep ? "이 작품의 문체를 저장해 두면" : "문체를 만든 뒤 저장해 두면") 다른 작품에서 다시 쓸 수 있어요.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                HStack {
                    Picker("라이브러리 문체", selection: $pick) {
                        Text("라이브러리에서 고르기").tag("")
                        ForEach(model.library, id: \.id) { Text(StyleText.optionLabel($0)).tag($0.id) }
                    }
                    .labelsHidden()
                    Button("적용") {
                        if pick.isEmpty { Task { await model.use("") } } else { asking = .use(pick, model.useQuestion(pick)) }
                    }
                }
            }
            if let l, l.state == "changed" {
                Button("라이브러리 새 버전으로 올리기") { pushNote = ""; asking = .push }
                Button(StyleText.pullLabel(l)) { asking = .pull(StyleText.pullQuestion(l)) }
            }
            Button("이 문체를 라이브러리에 새로 저장") { entryName = model.defaultKeepName; asking = .keep }
                .disabled(!model.canKeep)
            if !model.canKeep { Text("문체 분석이나 프로필을 채운 뒤 저장할 수 있어요").font(.caption).foregroundStyle(.secondary) }
        }
        .onAppear { if pick.isEmpty, let id = l?.id { pick = id } }
    }

    // MARK: 원문

    private var sampleCard: some View {
        Card("예시 원문", trailing: "\(model.sample.count.formatted())자 · 2,000자 이상 권장") {
            Text("소설 본문을 붙여 넣으세요. 원문은 작품에 저장되지 않고 고른 대표 문단만 남아요. 이 칸에 원문이 남아 있을 때 라이브러리에 저장하면 원문도 함께 보관해요. 화면을 닫으면 이 칸은 비어요.")
                .font(.caption).foregroundStyle(.secondary)
            TextEditor(text: Binding(get: { model.sample }, set: { model.sample = $0 }))
                .font(.system(.body, design: .serif))
                .frame(minHeight: 260)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.secondary.opacity(0.3)))
                .accessibilityLabel("예시 원문")
            Button("문체 분석") {
                guard model.sampleReady() else { return }
                if let q = model.analyzeQuestion { asking = .analyze(q) } else { Task { await model.analyze() } }
            }
            .buttonStyle(.borderedProminent)
            Text("원문은 문체 분석과 예시 문단으로만 쓰여요. 내용이나 인물은 작품에 가져오지 않아요.").font(.caption).foregroundStyle(.secondary)
        }
    }

    private var baselineCard: some View {
        Card("기준 지표") {
            Text("본문 문체 경고는 이 값과 비교해요.").font(.caption).foregroundStyle(.secondary)
            if let b = model.project?.styleBaseline {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 4) {
                    ForEach(StyleText.baselineRows(b), id: \.0) { row in
                        GridRow {
                            Text(row.0).foregroundStyle(.secondary)
                            Text(row.1).monospacedDigit()
                        }
                        .font(.callout)
                    }
                }
            } else {
                Text(StyleText.noBaseline).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: 묻기

    private var alertTitle: String {
        switch asking {
        case .keep: "라이브러리에 저장할 문체 이름"
        case .push: "라이브러리 새 버전으로 올리기"
        default: "확인"
        }
    }

    private func alertMessage(_ ask: Ask) -> String {
        switch ask {
        case let .analyze(q), let .use(_, q), let .pull(q): q
        case .keep: StyleText.keepNote(sample: model.sample, link: model.link)
        case .push: model.pushNote + "\n\n버전 메모 (비워도 돼요)"
        }
    }

    @ViewBuilder
    private func alertActions(_ ask: Ask) -> some View {
        switch ask {
        case .analyze:
            Button("바꾸기") { Task { await model.analyze() } }
        case let .use(id, _):
            Button("적용") { Task { await model.use(id) } }
        case .pull:
            Button("가져오기") { Task { await model.pull() } }
        case .keep:
            TextField("이름", text: $entryName)
            Button("저장") { Task { await model.keep(as: entryName) } }
        case .push:
            TextField("버전 메모", text: $pushNote)
            Button("올리기") { Task { await model.push(note: pushNote) } }
        }
        Button("취소", role: .cancel) {}
    }
}

/// 카드 모양 묶음.
struct Card<Content: View>: View {
    let title: String
    let trailing: String
    @ViewBuilder let content: Content

    init(_ title: String, trailing: String = "", @ViewBuilder content: () -> Content) {
        self.title = title
        self.trailing = trailing
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(title).font(.title3.bold())
                Spacer()
                if !trailing.isEmpty { Text(trailing).font(.caption).foregroundStyle(.secondary) }
            }
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 12))
    }
}

/// 칸 하나를 작품에 잇는다. 값이 같으면 고친 표시를 하지 않는다.
@MainActor
func binding<V: Equatable>(_ get: @escaping () -> V, _ set: @escaping (V) -> Void) -> Binding<V> {
    Binding(get: get, set: { v in if v != get() { set(v) } })
}

/// 스타일 프로필 칸 (웹 `profileFields` + `mystyle.js` 의 `deviceFields`).
struct ProfileCard: View {
    let model: StyleModel

    private var s: StyleProfile? { model.profile }

    private func list(_ kp: WritableKeyPath<StyleProfile, [String]?>) -> Binding<[String]> {
        binding({ model.profile?[keyPath: kp] ?? [] }, { v in model.editStyle { $0[keyPath: kp] = v } })
    }

    var body: some View {
        Card("스타일 프로필", trailing: "모든 칸은 직접 고칠 수 있어요") {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), alignment: .topLeading)], alignment: .leading, spacing: 10) {
                ForEach(StyleText.textFields, id: \.label) { f in
                    LabeledText(f.label, text: binding({ model.profile?[keyPath: f.path] ?? "" }, { v in model.editStyle { $0[keyPath: f.path] = v } }), lines: f.lines)
                }
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), alignment: .topLeading)], alignment: .leading, spacing: 10) {
                ListField("지킬 것", items: list(\.dos), lines: 4)
                    .padding(8).background(Color.green.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                ListField("피할 것", items: list(\.donts), lines: 4)
                    .padding(8).background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
            }
            ListField("금지 표현", items: list(\.bannedPhrases), placeholder: "본문에 나오면 경고할 표현, 한 줄에 하나씩", lines: 2)
            markers
            devices
            passages
        }
    }

    private func sectionHead(_ title: String, _ hint: String, add: String, _ action: @escaping () -> Void) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(hint).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button(add, action: action)
        }
        .padding(.top, 6)
    }

    private func marker<V: Equatable>(_ i: Int, _ kp: WritableKeyPath<StyleMarker, V>, _ fallback: V) -> Binding<V> {
        binding({ (model.profile?.markers ?? []).indices.contains(i) ? model.profile!.markers![i][keyPath: kp] : fallback },
                { v in model.editStyle { s in if s.markers?.indices.contains(i) == true { s.markers![i][keyPath: kp] = v } } })
    }

    private var markers: some View {
        let list = s?.markers ?? []
        return VStack(alignment: .leading, spacing: 8) {
            sectionHead("문체 표지", "어미, 조사, 말버릇과 원문 빈도. 넘치거나 빠지면 경고", add: "+ 표지") { model.addMarker() }
            if list.isEmpty { Text("아직 없어요. 문체 분석을 하면 원문에서 골라 빈도를 세어요.").font(.caption).foregroundStyle(.secondary) }
            ForEach(list.indices, id: \.self) { i in
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .bottom) { markerFields(i) }
                    VStack(alignment: .leading) { markerFields(i) }
                }
            }
        }
    }

    @ViewBuilder
    private func markerFields(_ i: Int) -> some View {
        LabeledText("표지 \(i + 1)", text: marker(i, \.text, ""), placeholder: "원문에 적힌 그대로, 예: 것이었다").frame(minWidth: 180)
        LabeledText("쓰임", text: binding({ marker(i, \.note, nil).wrappedValue ?? "" }, { marker(i, \.note, nil).wrappedValue = $0 })).frame(minWidth: 160)
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel("1,000자당")
            TextField("1,000자당", value: binding({ marker(i, \.per1k, nil).wrappedValue ?? 0 }, { marker(i, \.per1k, nil).wrappedValue = $0 }), format: .number)
                .textFieldStyle(.roundedBorder).frame(width: 90)
        }
        Button(role: .destructive) { model.removeMarker(i) } label: { Image(systemName: "xmark") }
            .accessibilityLabel("표지 \(i + 1) 삭제")
    }

    private func device<V: Equatable>(_ i: Int, _ kp: WritableKeyPath<StyleDevice, V>, _ fallback: V) -> Binding<V> {
        binding({ (model.profile?.devices ?? []).indices.contains(i) ? model.profile!.devices![i][keyPath: kp] : fallback },
                { v in model.editStyle { s in if s.devices?.indices.contains(i) == true { s.devices![i][keyPath: kp] = v } } })
    }

    private func deviceText(_ i: Int, _ kp: WritableKeyPath<StyleDevice, String?>) -> Binding<String> {
        binding({ device(i, kp, nil).wrappedValue ?? "" }, { device(i, kp, nil).wrappedValue = $0 })
    }

    private var devices: some View {
        let list = s?.devices ?? []
        return VStack(alignment: .leading, spacing: 8) {
            sectionHead("가끔 쓰는 장치", "특정 상황에만, 몇 화에 한 번 쓰는 장면 장치. 최근 화에서 쓴 화를 세어 이번 화에 쓸지 정해 줘요", add: "+ 장치") { model.addDevice() }
            if list.isEmpty { Text("아직 없어요. 레퍼런스의 버릇이 매 화 반복되면 규칙이나 대표 문단에서 빼고 여기에 적으세요.").font(.caption).foregroundStyle(.secondary) }
            ForEach(list.indices, id: \.self) { i in
                VStack(alignment: .leading, spacing: 8) {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), alignment: .topLeading)], alignment: .leading, spacing: 8) {
                        LabeledText("장치 이름", text: device(i, \.name, ""), placeholder: "예: 자문자답 망상")
                        LabeledText("쓰는 상황", text: deviceText(i, \.when), placeholder: "예: 상대의 작은 반응에 혼자 설렐 때")
                        ListField("알아보는 글자", items: binding({ device(i, \.cues, nil).wrappedValue ?? [] }, { device(i, \.cues, nil).wrappedValue = $0 }),
                                  hint: "한 화에 합쳐 두 번 이상 나오면 쓴 화로 쳐요", placeholder: "예: 다는 건\n거지?", lines: 2)
                        VStack(alignment: .leading, spacing: 4) {
                            FieldLabel("몇 화에 한 번까지", hint: "0 이면 간격 없이 상황이 올 때만")
                            TextField("몇 화에 한 번까지", value: binding({ device(i, \.every, nil).wrappedValue ?? 0 }, { device(i, \.every, nil).wrappedValue = max(0, $0) }), format: .number)
                                .textFieldStyle(.roundedBorder).frame(width: 90)
                        }
                    }
                    HStack(alignment: .bottom) {
                        LabeledText("예시 (써도 되는 화에만 보여 줘요)", text: deviceText(i, \.example), lines: 2)
                        Button(role: .destructive) { model.removeDevice(i) } label: { Image(systemName: "xmark") }
                            .accessibilityLabel("장치 \(i + 1) 삭제")
                    }
                }
                .padding(10)
                .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private var passages: some View {
        let list = s?.samplePassages ?? []
        return VStack(alignment: .leading, spacing: 8) {
            sectionHead("대표 문단", "본문 생성 때 그대로 보여줄 원문 예시, 2~4개", add: "+ 문단") { model.addPassage() }
            if list.isEmpty { Text("아직 없어요. 문체 분석을 하면 원문에서 골라 넣어요.").font(.caption).foregroundStyle(.secondary) }
            ForEach(list.indices, id: \.self) { i in
                HStack(alignment: .bottom) {
                    LabeledText("대표 문단 \(i + 1)", text: binding({ (model.profile?.samplePassages ?? []).indices.contains(i) ? model.profile!.samplePassages![i] : "" },
                                                                  { v in model.editStyle { s in if s.samplePassages?.indices.contains(i) == true { s.samplePassages![i] = v } } }),
                                lines: 3)
                    Button(role: .destructive) { model.removePassage(i) } label: { Image(systemName: "xmark") }
                        .accessibilityLabel("대표 문단 \(i + 1) 삭제")
                }
            }
        }
    }
}
#endif
