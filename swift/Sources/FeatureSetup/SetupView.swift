#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 설정 도우미 (웹 `viewSetup`): 기본 정보, 세계관, 인물, 관계, AI 설정 제안.
public struct SetupView: View {
    @State private var model: SetupModel
    let go: (Screen) -> Void

    public init(document: ProjectDocument, jobs: JobCenter, server: CanonServer, go: @escaping (Screen) -> Void) {
        _model = State(initialValue: SetupModel(document: document, jobs: jobs, service: LiveSetupService(server: server)))
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
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
                if let f = model.suggestFailure {
                    Notice("\(f.label) 실패: \(f.error)", isError: true) { Task { await model.jobs.dismissFailure(SetupModel.suggestKey) } }
                }
                if let s = model.suggestion { SuggestionCard(model: model, suggestion: s) }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 380), alignment: .topLeading)], alignment: .leading, spacing: 20) {
                    BasicSection(model: model)
                    WorldSection(model: model)
                }
                CharactersSection(model: model)
                RelationsSection(model: model)
            }
            .padding()
            .frame(maxWidth: 1200, alignment: .leading)
        }
        .disabled(model.busy != nil)
        .overlay(alignment: .top) {
            if let busy = model.busy { ProgressView(busy).padding(10).background(.thinMaterial, in: Capsule()).padding(.top, 8) }
        }
    }

    private var header: some View {
        let first = (model.project?.characters ?? []).isEmpty
        return VStack(alignment: .leading, spacing: 8) {
            Text("1단계").font(.caption).foregroundStyle(.secondary)
            Text("설정 도우미").font(.largeTitle.bold())
            Text("채운 칸은 그대로 두고, 빈칸만 AI가 제안해요. 제안에서 원하는 인물과 관계만 골라 적용하세요.").foregroundStyle(.secondary)
            HStack {
                // 인물이 없으면 첫 할 일은 AI 제안이다. 인물이 생기면 다음 단계(문체)를 앞세운다
                if first {
                    Button(model.suggestLabel) { Task { await model.suggest() } }.buttonStyle(.borderedProminent).disabled(model.suggesting)
                    Button("문체로") { go(.style) }.buttonStyle(.bordered)
                } else {
                    Button(model.suggestLabel) { Task { await model.suggest() } }.buttonStyle(.bordered).disabled(model.suggesting)
                    Button("문체로") { go(.style) }.buttonStyle(.borderedProminent)
                }
            }
        }
    }
}

/// 칸 하나를 작품에 잇는다. 값이 같으면 고친 표시를 하지 않는다.
@MainActor
func binding<V: Equatable>(_ get: @escaping () -> V, _ set: @escaping (V) -> Void) -> Binding<V> {
    Binding(get: get, set: { v in if v != get() { set(v) } })
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

// MARK: 기본 정보

struct BasicSection: View {
    let model: SetupModel
    @State private var customGenre = ""

    private var meta: Meta? { model.project?.meta }

    private func text(_ kp: WritableKeyPath<Meta, String?>) -> Binding<String> {
        binding({ model.project?.meta?[keyPath: kp] ?? "" }, { v in model.editMeta { $0[keyPath: kp] = v } })
    }

    private func number(_ kp: WritableKeyPath<Meta, Int?>, _ fallback: Int) -> Binding<Int> {
        binding({ model.project?.meta?[keyPath: kp] ?? fallback }, { v in model.editMeta { $0[keyPath: kp] = v } })
    }

    var body: some View {
        Card("기본 정보") {
            LabeledText("제목", text: text(\.title))
            genrePicker
            Toggle(isOn: binding({ meta?.adult ?? false }, { v in model.editMeta { $0.adult = v } })) {
                VStack(alignment: .leading) {
                    Text("성인물").bold()
                    Text("성인 독자 대상. 끄면 노골적인 성적 묘사와 과도한 잔혹 묘사를 피하도록 지시해요").font(.caption).foregroundStyle(.secondary)
                }
            }
            numberField("총 화수", number(\.targetEpisodes, 16),
                        hint: model.document.serial ? "늘리거나 줄이면 마지막 부 끝 화가 따라가요" : "단편은 10~20화를 권해요 · 4~40화")
            LoglineBox(model: model)
            LabeledText("주제", text: text(\.theme), hint: "이 이야기가 끝까지 묻는 질문 하나", placeholder: "예: 떠난 사람을 이해하면 용서할 수 있나?")
            ToneBox(model: model)
            numberField("화당 분량", number(\.wordsPerEpisode, 5000), hint: "공백 포함 글자 수")
            LabeledText("메모", text: text(\.notes), lines: 2)
        }
    }

    private func numberField(_ label: String, _ value: Binding<Int>, hint: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            FieldLabel(label, hint: hint)
            TextField(label, value: value, format: .number)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 160)
            #if os(iOS)
                .keyboardType(.numberPad)
            #endif
        }
    }

    private var genrePicker: some View {
        let picked = meta?.genres ?? []
        let catalog = model.genres
        let custom = picked.filter { id in !catalog.contains { $0.id == id } }
        let isOn = { (name: String) in picked.contains(catalog.first { $0.name == name }?.id ?? name) }
        let toggle = { (name: String) in model.toggleGenre(catalog.first { $0.name == name }?.id ?? name) }
        return VStack(alignment: .leading, spacing: 6) {
            FieldLabel("장르", hint: "여러 개 고를 수 있어요. 고른 장르의 안내가 AI 프롬프트에 들어가요")
            ChipRow("장르", options: catalog.filter { $0.kind != .요소 }.map(\.name), isOn: isOn, toggle: toggle)
            Text("요소").font(.caption).foregroundStyle(.secondary)
            ChipRow("요소", options: catalog.filter { $0.kind == .요소 }.map(\.name) + custom, isOn: isOn, toggle: toggle)
            HStack {
                TextField("목록에 없으면 직접 적기 (예: 오컬트)", text: $customGenre)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(addCustom)
                Button("추가", action: addCustom)
            }
            ForEach(catalog.filter { picked.contains($0.id) }, id: \.id) { g in
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 4) {
                        guideRow("독자가 기대하는 것", g.readerExpects ?? [])
                        guideRow("관습", g.conventions ?? [])
                        guideRow("자주 쓰는 소재", g.tropes ?? [])
                        guideRow("전개 속도", [g.pacing ?? ""].filter { !$0.isEmpty })
                        guideRow("피할 것", g.avoid ?? [])
                    }
                } label: {
                    VStack(alignment: .leading) {
                        Text(g.name).bold()
                        Text(g.summary).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func guideRow(_ k: String, _ v: [String]) -> some View {
        if !v.isEmpty {
            (Text(k + "  ").font(.caption.bold()) + Text(v.joined(separator: ", ")).font(.caption))
        }
    }

    private func addCustom() {
        model.addGenre(customGenre)
        customGenre = ""
    }
}

/// 로그라인 다섯 칸, 합친 문장, 점검, 예시 (웹 `loglineBuilder`).
struct LoglineBox: View {
    let model: SetupModel
    @State private var manualOpen = false

    var body: some View {
        let m = model.project?.meta
        let examples = SetupRules.loglineExamples(m, catalog: model.genres)
        VStack(alignment: .leading, spacing: 8) {
            FieldLabel("로그라인", hint: "다섯 칸을 채우면 한 문장으로 합쳐요. 예시를 누르면 칸에 들어가요")
            if Logline.isLegacy(m) {
                Text("지금 로그라인은 한 문장으로만 저장되어 있어요. 칸을 채우면 칸 내용으로 바뀌어요.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(LoglineField.allCases) { f in
                VStack(alignment: .leading, spacing: 4) {
                    LabeledText(f.label, text: binding({ f.get(model.project?.meta?.loglineParts) }, { v in model.editMeta { Logline.set(f, v, in: &$0) } }), hint: f.hint)
                    let chips = SetupRules.slotExamples(f, examples)
                    if !chips.isEmpty {
                        ChipRow("\(f.label) 예시", options: chips, isOn: { _ in false }) { v in model.editMeta { Logline.set(f, v, in: &$0) } }
                    }
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(m?.logline.flatMap { $0.isEmpty ? nil : $0 } ?? Logline.empty)
                    .font(.body.italic())
                    .accessibilityAddTraits(.updatesFrequently)
                if !Logline.isEmpty(m?.loglineParts) {
                    ForEach(Logline.checks(m?.loglineParts), id: \.text) { c in
                        Label(c.text, systemImage: c.ok ? "checkmark.circle.fill" : "circle")
                            .font(.caption)
                            .foregroundStyle(c.ok ? Color.green : Color.secondary)
                    }
                    Text(Logline.lengthNote(m)).font(.caption2).foregroundStyle(.secondary)
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
            if !examples.isEmpty {
                DisclosureGroup("예시 로그라인 \(examples.count)개 보기") {
                    ForEach(Array(examples.enumerated()), id: \.offset) { _, e in
                        HStack(alignment: .top) {
                            Text(Logline.compose(e)).font(.caption).frame(maxWidth: .infinity, alignment: .leading)
                            Button("이 예시로 채우기") { model.editMeta { Logline.fill(e, in: &$0) } }.font(.caption)
                        }
                    }
                }
            }
            if Logline.isManual(m) {
                HStack {
                    Text("직접 고친 문장을 쓰고 있어요. 칸을 고쳐도 이 문장은 바뀌지 않아요.").font(.caption)
                    Button("칸 내용으로 다시 만들기") { model.editMeta { Logline.rebuild(&$0) } }.font(.caption)
                }
            }
            DisclosureGroup("한 문장으로 직접 고쳐 쓰기", isExpanded: $manualOpen) {
                LabeledText("로그라인 문장", text: binding({ model.project?.meta?.logline ?? "" }, { v in model.editMeta { $0.logline = v } }),
                            hint: "직접 고친 문장은 칸을 고쳐도 그대로 둬요", lines: 3)
            }
            .onAppear { manualOpen = Logline.isLegacy(m) || Logline.isManual(m) }
        }
    }
}

/// 톤 다이얼과 톤 문장 (웹 `toneBox`).
struct ToneBox: View {
    let model: SetupModel

    var body: some View {
        let m = model.project?.meta
        VStack(alignment: .leading, spacing: 6) {
            FieldLabel("톤", hint: "양 끝 중 어디에 가까운가. 왼쪽부터 1~4단계이고, 고른 단계를 다시 누르면 꺼져요. 직접 쓴 문장은 다이얼이 덮지 않아요")
            ForEach(ToneDial.allCases) { k in
                HStack(spacing: 6) {
                    Text(k.ends.left).font(.caption).frame(width: 52, alignment: .trailing)
                    ForEach(1...4, id: \.self) { v in
                        let on = k.get(m?.toneDials) == v
                        Button { model.editMeta { Tone.set(k, v, in: &$0) } } label: {
                            Circle().fill(on ? Color.accentColor : Color.secondary.opacity(0.2)).frame(width: 22, height: 22)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(k.ends.left)에서 \(k.ends.right) 사이 \(v)단계: \(k.words[v - 1].1)")
                        .accessibilityAddTraits(on ? .isSelected : [])
                    }
                    Text(k.ends.right).font(.caption).frame(width: 52, alignment: .leading)
                    Text(k.now(m?.toneDials)).font(.caption).foregroundStyle(.secondary)
                }
            }
            LabeledText("톤 문장", text: binding({ model.project?.meta?.tone ?? "" }, { v in model.editMeta { $0.tone = v } }),
                        placeholder: "예: 조금 어둡고 진지하고 호흡이 느리다")
            if let offer = Tone.offer(m) {
                HStack {
                    Text("다이얼 문장: \(offer)").font(.caption)
                    Button("다이얼 문장으로 바꾸기") { model.editMeta { $0.tone = offer } }.font(.caption)
                }
            }
        }
    }
}

// MARK: 세계관

struct WorldSection: View {
    let model: SetupModel

    private func text(_ kp: WritableKeyPath<World, String?>) -> Binding<String> {
        binding({ model.project?.world?[keyPath: kp] ?? "" }, { v in model.editWorld { $0[keyPath: kp] = v } })
    }

    private func list(_ kp: WritableKeyPath<World, [String]?>) -> Binding<[String]> {
        binding({ model.project?.world?[keyPath: kp] ?? [] }, { v in model.editWorld { $0[keyPath: kp] = v } })
    }

    var body: some View {
        Card("세계관") {
            LabeledText("배경", text: text(\.setting), lines: 2)
            LabeledText("시대", text: text(\.era))
            ListField("깨면 안 되는 규칙", items: list(\.rules))
            ListField("장소", items: list(\.locations))
            HStack {
                Picker("지명 종류", selection: Binding(get: { model.placeKind }, set: { model.placeKind = $0 })) {
                    Text("종류 무관").tag("")
                    ForEach(model.currentStyle?.placeKinds ?? [], id: \.self) { Text($0).tag($0) }
                }
                .fixedSize()
                Button("지명 후보 뽑기") { Task { await model.placeNames(ai: false) } }
                Button("AI 지명 추천") { Task { await model.placeNames(ai: true) } }
            }
            .font(.callout)
            if let picks = model.names["place"] {
                NamePicksBox(picks: picks, place: true, close: { model.closeNames("place") }) { model.addPlace($0) }
            }
            VStack(alignment: .leading, spacing: 4) {
                FieldLabel("이름 스타일", hint: "이름과 지명 후보를 뽑는 기준")
                Picker("이름 스타일", selection: text(\.nameStyle)) {
                    Text(model.autoStyleLabel).tag("")
                    ForEach(model.namingStyles, id: \.id) { Text($0.label).tag($0.id) }
                }
                .labelsHidden()
                .fixedSize()
                if let cur = model.currentStyle { Text(cur.summary).font(.caption).foregroundStyle(.secondary) }
            }
            ListField("이름 규칙", items: list(\.nameRules), placeholder: "예: 북부 귀족은 성 앞에 '폰'을 붙인다", lines: 2)
        }
    }
}

/// 이름 · 지명 후보 칩 (웹 `namePicks`).
struct NamePicksBox: View {
    let picks: NamePicks
    let place: Bool
    let close: () -> Void
    let use: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(picks.title(place: place)).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("닫기", action: close).font(.caption)
            }
            if picks.items.isEmpty {
                Text("후보가 없어요").font(.caption).foregroundStyle(.secondary)
            } else {
                Flow(spacing: 6) {
                    ForEach(picks.items, id: \.name) { item in
                        Button { use(item.name) } label: {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(item.name).font(.callout.bold())
                                if !item.note.isEmpty { Text(item.note).font(.caption2).foregroundStyle(.secondary) }
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 6))
                        }
                        .buttonStyle(.plain)
                        .help(item.note)
                    }
                }
            }
        }
        .padding(8)
        .background(.background.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: 인물

struct CharactersSection: View {
    let model: SetupModel
    @State private var removing: Person?

    private var removalQuestion: String {
        guard let c = removing, let p = model.project else { return "" }
        return SetupRules.removalQuestion(c, in: p)
    }

    var body: some View {
        let people = model.project?.characters ?? []
        Card("인물", trailing: "\(people.count)명") {
            Text("이름, 말투, 성격은 고정 설정이에요. 회차가 지나며 바뀌는 감정과 목표는 상태 승인 화면에서 관리해요.").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("+ 인물 추가") { model.addCharacter() }
                Button("이름 점검") { Task { await model.checkNames(show: true) } }
                Text("글자가 겹치는 이름, 나이와 안 맞는 이름, AI가 자주 짓는 이름을 찾아요").font(.caption).foregroundStyle(.secondary)
            }
            NameCheckBox(model: model)
            if people.isEmpty {
                Text("인물이 없어요. 직접 추가하거나 AI 제안을 받으세요.").foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), alignment: .topLeading)], alignment: .leading, spacing: 12) {
                    ForEach(people, id: \.id) { c in
                        CharacterCard(model: model, id: c.id) { removing = c }
                    }
                }
            }
        }
        .confirmationDialog(removalQuestion,
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("삭제", role: .destructive) {
                if let c = removing { model.removeCharacter(c.id) }
                removing = nil
            }
        }
    }
}

/// 이름 점검 묶음 (웹 `nameCheckBox`).
struct NameCheckBox: View {
    let model: SetupModel

    var body: some View {
        switch model.nameCheck {
        case .none:
            EmptyView()
        case .failed:
            HStack {
                Text("이름 점검을 못 했어요.")
                Button("다시 시도") { Task { await model.checkNames(show: true) } }
            }
            .font(.caption)
        case let .done(check):
            if let g = NameCheckGroups(check) {
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(g.groups, id: \.title) { group in
                            Text(group.title).font(.caption.bold())
                            ForEach(group.issues, id: \.text) { Text("• \($0.text)").font(.caption) }
                        }
                    }
                } label: {
                    Text(g.head).font(.callout.bold())
                }
                .padding(10)
                .background((g.warn ? Color.orange : Color.blue).opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
            } else {
                Text("이름 점검: 문제 없음").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// 인물 카드: 불변 설정 칸 (웹 `viewSetup` 의 `char-card`). 서술 말투와 삽화 외형 태그는 아직 웹에서.
struct CharacterCard: View {
    let model: SetupModel
    let id: String
    let remove: () -> Void

    private var person: Person? { model.project?.characters?.first { $0.id == id } }

    private func text(_ kp: WritableKeyPath<Person, String>) -> Binding<String> {
        binding({ person?[keyPath: kp] ?? "" }, { v in model.editCharacter(id) { $0[keyPath: kp] = v } })
    }

    private func optional(_ kp: WritableKeyPath<Person, String?>) -> Binding<String> {
        binding({ person?[keyPath: kp] ?? "" }, { v in model.editCharacter(id) { $0[keyPath: kp] = v } })
    }

    var body: some View {
        if let c = person {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(c.name.isEmpty ? "이름 없음" : c.name).font(.headline)
                    Spacer()
                    Button("삭제", role: .destructive, action: remove).font(.caption)
                        .accessibilityLabel("\(c.name.isEmpty ? c.id : c.name) 삭제")
                }
                HStack(alignment: .top) {
                    LabeledText("이름", text: text(\.name))
                    LabeledText("역할", text: text(\.role), placeholder: "주인공, 상대역, 조력자…")
                }
                ForEach(NameCheckGroups.issues(for: id, in: model.nameCheck.result), id: \.text) { i in
                    Text(i.text).font(.caption).foregroundStyle(i.level == "warn" ? Color.orange : Color.secondary)
                }
                HStack(alignment: .top) {
                    LabeledText("나이", text: optional(\.age), placeholder: "예: 17세, 40대 초반")
                    LabeledText("성별", text: optional(\.gender), placeholder: "남 / 여")
                }
                VStack(alignment: .leading, spacing: 4) {
                    FieldLabel("비중", hint: "주역은 매 화 설정 전체가 들어가고, 조연 · 단역은 나오는 화에만 들어가요"
                               + ((c.firstEp ?? 0) > 0 ? " · \(c.firstEp!)화에 처음 나옴" : ""))
                    Picker("비중", selection: binding({ person?.tier ?? .main }, { v in model.editCharacter(id) { $0.tier = v } })) {
                        ForEach(SetupRules.tiers, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
                HStack {
                    Button("이름 후보 뽑기") { Task { await model.characterNames(id, ai: false) } }
                    Button("AI 이름 추천") { Task { await model.characterNames(id, ai: true) } }
                }
                .font(.callout)
                if let picks = model.names["c:" + id] {
                    NamePicksBox(picks: picks, place: false, close: { model.closeNames("c:" + id) }) { model.useName($0, for: id) }
                }
                LabeledText("원하는 것", text: optional(\.goal), hint: "작품 전체에서")
                LabeledText("두려운 것 · 약점", text: optional(\.wound))
                ListField("숨기는 것", items: binding({ person?.secrets ?? [] }, { v in model.editCharacter(id) { $0.secrets = v } }), lines: 2)
                LabeledText("말투 (대사)", text: optional(\.speechStyle), hint: "어미, 호칭, 대사 한 줄", lines: 2)
                DisclosureGroup("더 자세히: 성격, 배경, 외모, 아크") {
                    VStack(alignment: .leading, spacing: 10) {
                        LabeledText("성격", text: optional(\.personality), lines: 2)
                        LabeledText("배경", text: optional(\.background), lines: 2)
                        LabeledText("외모", text: optional(\.appearance))
                        LabeledText("아크", text: optional(\.arc), hint: "시작 → 결말")
                        Text("id: \(c.id) · 관계와 플롯이 인물을 찾는 값이에요").font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(.top, 8)
                }
            }
            .padding(12)
            .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 10))
        }
    }
}

// MARK: 관계

struct RelationsSection: View {
    let model: SetupModel

    var body: some View {
        let rels = model.project?.relationships ?? []
        let started = SetupRules.started(model.project)
        Card("관계") {
            HStack {
                Text(started ? "첫 반영 뒤에는 관계 사건으로 계산돼요" : "서로 어떻게 보는지 고르면 시작 관계를 계산해요. 긴장은 자동 계산")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("+ 관계 추가") { model.addRelationship() }.disabled(model.relationsLocked)
            }
            if model.relationsLocked {
                Notice("자동 집필이 도는 동안은 관계를 고칠 수 없어요. 반영하는 관계와 겹치지 않게 서버가 받지 않아요. 고치려면 자동 집필을 일시정지하세요.", isError: true)
            }
            if rels.isEmpty {
                Text("관계가 없어요.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(rels.indices, id: \.self) { i in
                RelationRow(model: model, index: i, started: started).disabled(model.relationsLocked)
            }
        }
    }
}

/// 관계 한 줄 (웹 `relRow`): 두 인물, 어떤 사이, 서로 보는 방식(첫 반영 전), 목표 충돌, 숫자로 정하기.
struct RelationRow: View {
    let model: SetupModel
    let index: Int
    let started: Bool

    private var rel: Relationship? {
        guard let rs = model.project?.relationships, rs.indices.contains(index) else { return nil }
        return rs[index]
    }

    var body: some View {
        if let r = rel {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .bottom) {
                    personPicker("인물 A", r.a) { v in model.editRelationship(index) { $0.a = v } }
                    personPicker("인물 B", r.b) { v in model.editRelationship(index) { $0.b = v } }
                    Spacer()
                    Button(role: .destructive) { model.removeRelationship(index) } label: { Image(systemName: "xmark") }
                        .accessibilityLabel("관계 삭제")
                }
                LabeledText("어떤 사이", text: binding({ rel?._type ?? "" }, { v in model.editRelationship(index) { $0._type = v } }), placeholder: "오빠의 친구, 남매…")
                if let problem = SetupRules.relationshipProblem(index, in: model.project?.relationships ?? []) {
                    Text(problem).font(.caption).foregroundStyle(.orange)
                }
                ChipRow("어떤 사이 예시", options: SetupRules.relationTypes, isOn: { $0 == r._type }) { t in model.editRelationship(index) { $0._type = t } }
                if started {
                    Text("지금 호감 \(r.affinity ?? 0) · 긴장 \(r.tension ?? 0). 첫 반영 뒤에는 본문의 관계 사건으로 바뀌어요.").font(.caption).foregroundStyle(.secondary)
                } else {
                    view(r.a, r.b, r.aView) { w in model.editRelationship(index) { $0.aView = SetupRules.toggle(w, in: $0.aView) } }
                    view(r.b, r.a, r.bView) { w in model.editRelationship(index) { $0.bView = SetupRules.toggle(w, in: $0.bView) } }
                }
                VStack(alignment: .leading, spacing: 4) {
                    FieldLabel("원하는 게 부딪치나")
                    ChipRow("목표 충돌", options: SetupRules.conflicts.map(\.0), isOn: { $0 == SetupRules.conflictWord(r.goalConflict ?? 0) }) { w in
                        let v = SetupRules.conflicts.first { $0.0 == w }?.1 ?? 0
                        model.editRelationship(index) { $0.goalConflict = v }
                    }
                }
                if !started {
                    DisclosureGroup("숫자로 직접 정하기") {
                        VStack(alignment: .leading) {
                            Text("시작 호감 \(r.affinity ?? 0)  ").font(.caption) + Text("보는 방식을 고른 방향은 고른 말이 우선").font(.caption2).foregroundStyle(.secondary)
                            Slider(value: binding({ Double(rel?.affinity ?? 0) }, { v in model.editRelationship(index) { $0.affinity = Int(v.rounded()) } }), in: -5...5, step: 1)
                            Text("목표 충돌 \((r.goalConflict ?? 0).formatted(.number.precision(.fractionLength(0...1))))").font(.caption)
                            Slider(value: binding({ rel?.goalConflict ?? 0 }, { v in model.editRelationship(index) { $0.goalConflict = (v * 10).rounded() / 10 } }), in: 0...1, step: 0.1)
                        }
                    }
                }
            }
            .padding(12)
            .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func personPicker(_ label: String, _ selected: String, _ set: @escaping (String) -> Void) -> some View {
        let people = model.project?.characters ?? []
        return VStack(alignment: .leading, spacing: 4) {
            FieldLabel(label)
            Picker(label, selection: binding({ selected }, set)) {
                // 없는 인물을 가리키면 첫 인물이 고른 것처럼 보이지 않게 그 id 를 따로 보인다
                if !people.contains(where: { $0.id == selected }) { Text("(없는 인물: \(selected))").tag(selected) }
                ForEach(people, id: \.id) { Text($0.name.isEmpty ? $0.id : $0.name).tag($0.id) }
            }
            .labelsHidden()
            .fixedSize()
        }
    }

    private func view(_ from: String, _ to: String, _ words: [String]?, toggle: @escaping (String) -> Void) -> some View {
        let a = SetupRules.name(from, in: model.project)
        let b = SetupRules.name(to, in: model.project)
        return VStack(alignment: .leading, spacing: 4) {
            FieldLabel("\(a) → \(b)")
            ChipRow("\(a)\(KoreanText.josa(a, "이", "가")) \(b)\(KoreanText.josa(b, "을", "를")) 보는 방식", options: model.views,
                    isOn: { (words ?? []).contains($0) }, toggle: toggle)
        }
    }
}

// MARK: AI 제안

/// AI 설정 제안: 칸 · 인물 · 관계를 골라 빈 칸에만 적용 (웹 `viewSuggestion`).
struct SuggestionCard: View {
    let model: SetupModel
    let suggestion: SetupSuggestion
    @State private var confirmDrop = false

    var body: some View {
        let p = model.project
        let s = suggestion
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("AI 제안").font(.title3.bold())
                Text("적용 전").font(.caption).padding(.horizontal, 6).padding(.vertical, 2).background(.purple.opacity(0.15), in: Capsule())
                Spacer()
                Button("버리기", role: .destructive) { confirmDrop = true }
                Button("고른 것 적용") { Task { await model.applySuggestion() } }.buttonStyle(.borderedProminent)
            }
            Text("주제, 톤, 세계관은 비어 있는 칸에만 들어가요. 이미 있는 인물 id 는 건너뛰어요.").font(.caption).foregroundStyle(.secondary)
            ForEach(SuggestionPicks.fields, id: \.key) { f in
                let v = SuggestionPicks.value(s, f.key)
                if !v.isEmpty {
                    let have = SuggestionPicks.has(f.key, in: p)
                    pickRow("sf:" + f.key, disabled: have) {
                        Text(f.label).bold() + Text("  \(v)") + Text(have ? "  이미 있음 · 건너뜀" : "").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), alignment: .topLeading)], alignment: .leading, spacing: 10) {
                ForEach(Array(s.characters.enumerated()), id: \.offset) { i, c in
                    let exists = SuggestionPicks.same(c, in: p)
                    let note = exists ? " · 이미 있음" : SuggestionPicks.clash(c, in: p) ? " · 같은 id 의 다른 인물이 있어 새 id 로 넣어요" : ""
                    pickRow("sc\(i)", disabled: exists) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.name).bold() + Text("  \(c.role) · \(c.id)\(note)").font(.caption).foregroundStyle(.secondary)
                            Text("목표: \(c.goal ?? "")").font(.caption)
                            Text("말투: \(c.speechStyle ?? "")").font(.caption)
                        }
                    }
                    .padding(8)
                    .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 8))
                }
            }
            ForEach(Array(s.relationships.enumerated()), id: \.offset) { i, r in
                let off = SuggestionPicks.end(r.a, s, p, model.picks) == nil || SuggestionPicks.end(r.b, s, p, model.picks) == nil
                pickRow("sr\(i)", disabled: off) {
                    Text(SuggestionPicks.relationLine(r, s, p, model.picks)).font(.callout)
                        + Text(off ? "  (고르지 않은 인물이라 넣지 않아요)" : "").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .padding(14)
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.accentColor, lineWidth: 2))
        .confirmationDialog("AI 설정 제안을 버릴까요? 되살릴 수 없어서, 다시 보려면 AI에게 다시 받아야 해요.", isPresented: $confirmDrop, titleVisibility: .visible) {
            Button("버리기", role: .destructive) { Task { await model.dropSuggestion() } }
        }
    }

    private func pickRow<Label: View>(_ key: String, disabled: Bool, @ViewBuilder label: () -> Label) -> some View {
        Toggle(isOn: Binding(get: { model.picked(key) }, set: { model.setPick(key, $0) })) { label() }
            .disabled(disabled)
            #if os(macOS)
            .toggleStyle(.checkbox)
            #endif
    }
}
#endif
