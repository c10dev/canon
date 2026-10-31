#if canImport(SwiftUI)
import CanonAPI
import CanonCore
import CanonStore
import CanonUI
import SwiftUI

/// 새 작품 마법사 (웹 `viewSetupWizard`): 필수 칸 여섯 개를 여섯 걸음으로 묻는다.
/// '다음'은 막지 않고, '문체 레퍼런스로'는 필수를 다 채웠을 때만 켠다. 규칙은 `SetupWizard`.
struct WizardContent: View {
    let model: SetupModel
    let go: (Screen) -> Void
    @AccessibilityFocusState private var questionFocused: Bool

    private var step: Int { model.wizard?.step ?? 0 }

    var body: some View {
        ScrollViewReader { scroll in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header.id("top")
                    if let n = model.notice { Notice(n.text, isError: n.isError) { model.dismissNotice() } }
                    if let f = model.suggestFailure {
                        Notice("\(f.label) 실패: \(f.error)", isError: true) { Task { await model.jobs.dismissFailure(SetupModel.suggestKey) } }
                    }
                    if let s = model.suggestion { SuggestionCard(model: model, suggestion: s) }
                    WizardSteps(model: model)
                    VStack(alignment: .leading, spacing: 16) {
                        question
                        stepBody
                        Divider()
                        WizardFoot(model: model, go: go)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 12))
                }
                .padding()
                .frame(maxWidth: 860, alignment: .leading)
            }
            .onChange(of: step) {
                scroll.scrollTo("top", anchor: .top)
                questionFocused = true
            }
        }
        .disabled(model.busy != nil)
        .overlay(alignment: .top) {
            if let busy = model.busy { ProgressView(busy).padding(10).background(.thinMaterial, in: Capsule()).padding(.top, 8) }
        }
    }

    private var header: some View {
        let reqs = SetupWizard.reqs(model.wizardInput)
        let n = reqs.filter { $0 }.count
        return VStack(alignment: .leading, spacing: 8) {
            Text("1단계 · 새 작품").font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline) {
                Text("설정 도우미").font(.largeTitle.bold())
                Spacer()
                Button("기획서로 보기") { model.setMode(.doc) }.buttonStyle(.bordered)
            }
            HStack(spacing: 8) {
                ProgressView(value: Double(n), total: Double(reqs.count)).frame(maxWidth: 120).accessibilityHidden(true)
                Text(SetupWizard.meter(model.wizardInput)).font(.caption.bold())
            }
        }
    }

    private static let questions: [(String, String)] = [
        ("어떤 이야기인가요?", "제목과 장르를 정해요. 둘 다 나중에 바꿀 수 있어요."),
        ("한 문장으로 줄이면요?", "다섯 칸을 채우면 로그라인 한 문장이 돼요. AI가 플롯을 짤 때 가장 먼저 읽는 문장이에요."),
        ("어디서 벌어지나요?", "세계 종류를 고르면 시작할 수 있어요. 고른 뒤 한두 문장을 더 적으면 AI가 더 잘 맞춰요."),
        ("누가 나오나요?", "주요 인물 두세 명만 적어요. 두려운 것 · 숨기는 것 · 말투 같은 상세는 마친 뒤 기획서에서 채워요."),
        ("두 사람은 어떤 사이인가요?", "관계 하나면 시작할 수 있어요. 여기서 고른 시작 관계는 1화를 반영하면 잠겨요."),
    ]

    private var question: some View {
        let (title, desc): (String, String)
        if step < SetupWizard.finish {
            (title, desc) = Self.questions[step]
        } else if SetupWizard.complete(model.wizardInput) {
            (title, desc) = ("뼈대가 섰어요", "나머지 칸은 지금 더하거나, 마친 뒤 기획서에서 언제든 채워요.")
        } else {
            (title, desc) = ("필수 칸이 남았어요", "남은 칸을 채우면 문체 단계로 넘어갈 수 있어요.")
        }
        return VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.title2.bold()).accessibilityAddTraits(.isHeader).accessibilityFocused($questionFocused)
            Text(desc).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var stepBody: some View {
        switch step {
        case 0: WizardBasics(model: model)
        case 1: WizardLogline(model: model)
        case 2: WizardWorld(model: model)
        case 3: WizardCast(model: model)
        case 4: WizardRelations(model: model)
        default: WizardFinish(model: model)
        }
    }
}

/// 필수 칸 표시: '필수' 또는 '채움' (웹 `wizTag`).
struct ReqTag: View {
    let ok: Bool

    init(_ model: SetupModel, _ k: Int) {
        ok = SetupWizard.reqs(model.wizardInput)[k]
    }

    var body: some View {
        Text(ok ? "채움" : "필수")
            .font(.caption2.bold())
            .padding(.horizontal, 6).padding(.vertical, 2)
            .foregroundStyle(ok ? Color.green : Color.orange)
            .background((ok ? Color.green : Color.orange).opacity(0.12), in: Capsule())
    }
}

/// 걸음 막대 (웹 `wizStepper`): 걸음마다 채움 · 빈 필수 있음 · 아직.
struct WizardSteps: View {
    let model: SetupModel

    var body: some View {
        let now = model.wizard?.step ?? 0
        VStack(alignment: .leading, spacing: 6) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(SetupWizard.steps.indices, id: \.self) { i in
                        let st = model.stepState(i)
                        Button { Task { await model.go(step: i) } } label: {
                            HStack(spacing: 4) {
                                Image(systemName: st == .done ? "checkmark.circle.fill" : st == .miss ? "exclamationmark.circle.fill" : "circle")
                                    .foregroundStyle(st == .done ? Color.green : st == .miss ? Color.orange : Color.secondary)
                                Text("\(i + 1). \(SetupWizard.steps[i])").fontWeight(i == now ? .bold : .regular)
                            }
                            .font(.callout)
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background(i == now ? Color.accentColor.opacity(0.15) : Color.clear, in: Capsule())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(SetupWizard.stepLabel(i, st))
                        .accessibilityAddTraits(i == now ? .isSelected : [])
                    }
                }
            }
            Text("\(now + 1)/\(SetupWizard.steps.count) · \(SetupWizard.steps[now])").font(.caption).foregroundStyle(.secondary).accessibilityHidden(true)
        }
    }
}

/// 이전 · 다음, 마무리 걸음은 기획서로 보기 · 문체 레퍼런스로 (웹 `wizFoot`).
struct WizardFoot: View {
    let model: SetupModel
    let go: (Screen) -> Void

    var body: some View {
        let step = model.wizard?.step ?? 0
        let gaps = SetupWizard.gaps(model.wizardInput)
        VStack(alignment: .trailing, spacing: 6) {
            HStack {
                Button("이전") { Task { await model.go(step: step - 1) } }.disabled(step == 0)
                Spacer()
                if step < SetupWizard.finish {
                    Button("다음") { Task { await model.go(step: step + 1) } }.buttonStyle(.borderedProminent)
                } else {
                    Button("기획서로 보기") { model.setMode(.doc) }
                    Button("문체 레퍼런스로") { go(.style) }.buttonStyle(.borderedProminent).disabled(!gaps.isEmpty)
                }
            }
            if step == SetupWizard.finish, !gaps.isEmpty {
                Text("남은 필수 칸: \(gaps.joined(separator: ", "))").font(.caption).foregroundStyle(.orange)
            }
        }
    }
}

// MARK: 걸음

/// 1. 제목 · 장르 (웹 `wizBasics`).
struct WizardBasics: View {
    let model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) { Text("제목").font(.callout.bold()); ReqTag(model, 0) }
            TextField("예: 소금 정원의 계약", text: binding({ model.project?.meta?.title ?? "" }, { v in model.editMeta { $0.title = v } }))
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("제목")
            HStack(alignment: .firstTextBaseline) { ReqTag(model, 1); Text("장르를 하나 이상 골라요").font(.caption).foregroundStyle(.secondary) }
            GenrePicker(model: model)
            EpisodeCountField(model: model)
            AdultToggle(model: model)
        }
    }
}

/// 2. 로그라인 (웹 `wizLogline`).
struct WizardLogline: View {
    let model: SetupModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) { ReqTag(model, 2); Text("합친 문장이 생기면 채워져요").font(.caption).foregroundStyle(.secondary) }
            LoglineBox(model: model)
        }
    }
}

/// 3. 세계: 세계 종류 · 시대 칩, 배경 (웹 `wizWorld`).
struct WizardWorld: View {
    let model: SetupModel

    var body: some View {
        let w = model.project?.world
        let genres = model.project?.meta?.genres ?? []
        let kind = SetupWizard.worldKind(of: w?.setting ?? "")
        let era = w?.era ?? ""
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text("세계 종류").font(.callout.bold())
                    ReqTag(model, 3)
                    Text("고르면 배경 칸 첫 문장이 돼요").font(.caption).foregroundStyle(.secondary)
                }
                RecChips("세계 종류", all: SetupWizard.worldKinds.map(\.label), rec: SetupWizard.worldRecs(genres, eras: false),
                         isOn: { $0 == kind }) { model.pickWorldKind($0) }
            }
            LabeledText("배경", text: binding({ model.project?.world?.setting ?? "" }, { v in model.editWorld { $0.setting = v } }),
                        hint: "고르지 않고 직접 써도 돼요", placeholder: "예: 소금이 돈을 대신하는 북방 왕국 헤른", lines: 3)
            VStack(alignment: .leading, spacing: 6) {
                FieldLabel("시대", hint: "선택")
                RecChips("시대", all: SetupWizard.eras, rec: SetupWizard.worldRecs(genres, eras: true), isOn: { $0 == era }) { model.pickEra($0) }
                // 칩에 없는 시대만 이 칸에 보인다 (웹 `wiz-era-custom`)
                TextField("직접 쓰기: 예) 중세풍, 증기 기관이 막 들어오는 때",
                          text: binding({ SetupWizard.eras.contains(era) ? "" : era }, { v in model.editWorld { $0.era = v } }))
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("시대 직접 쓰기")
            }
        }
    }
}

/// 추천 줄과 나머지 줄로 나눈 고르기 칩 (웹 `wizChips`).
struct RecChips: View {
    let label: String
    let all: [String]
    let rec: [String]
    let isOn: (String) -> Bool
    let toggle: (String) -> Void

    init(_ label: String, all: [String], rec: [String], isOn: @escaping (String) -> Bool, toggle: @escaping (String) -> Void) {
        self.label = label
        self.all = all
        self.rec = rec
        self.isOn = isOn
        self.toggle = toggle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !rec.isEmpty {
                HStack(alignment: .top, spacing: 6) {
                    Text("장르에 맞춰 추천").font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 3)
                        .background(.purple.opacity(0.15), in: Capsule())
                    ChipRow("\(label) 추천", options: rec, isOn: isOn, toggle: toggle)
                }
            }
            ChipRow(label, options: all.filter { !rec.contains($0) }, isOn: isOn, toggle: toggle)
        }
    }
}

/// 4. 인물: 이름 · 나이 · 성별 · 역할 · 원하는 것 (웹 `wizCast`).
struct WizardCast: View {
    let model: SetupModel
    @State private var removing: Person?

    var body: some View {
        let people = model.project?.characters ?? []
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                ReqTag(model, 4)
                Text("이름 있는 인물 \(SetupWizard.named(model.wizardInput))명").font(.caption).foregroundStyle(.secondary)
                Button("이름 점검") { Task { await model.checkNames(show: true) } }.font(.caption)
            }
            NameCheckBox(model: model)
            if people.isEmpty {
                Text("아직 인물이 없어요. 로그라인에 나온 사람부터 적어 보세요.").foregroundStyle(.secondary)
            }
            ForEach(Array(people.enumerated()), id: \.element.id) { i, c in
                WizardPerson(model: model, id: c.id, index: i) { removing = c }
            }
            Button("+ 인물 더하기") { model.addCharacter() }
        }
        .confirmationDialog(removing.flatMap { c in model.project.map { SetupRules.removalQuestion(c, in: $0) } } ?? "",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("빼기", role: .destructive) {
                if let c = removing { model.removeCharacter(c.id) }
                removing = nil
            }
        }
    }
}

/// 마법사의 인물 한 명 (웹 `wizPerson`). 상세 칸은 기획서의 `CharacterCard`.
struct WizardPerson: View {
    let model: SetupModel
    let id: String
    let index: Int
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
            let who = c.name.isEmpty ? "\(index + 1)번 인물" : c.name
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(c.name.isEmpty ? "이름 없음" : c.name).font(.headline)
                    Spacer()
                    Button("이름 후보") { Task { await model.characterNames(id, ai: false) } }.font(.caption)
                    Button("✦ AI 이름 추천") { Task { await model.characterNames(id, ai: true) } }.font(.caption)
                    Button("빼기", role: .destructive, action: remove).font(.caption).accessibilityLabel("\(who) 빼기")
                }
                if let picks = model.names["c:" + id] {
                    NamePicksBox(picks: picks, place: false, close: { model.closeNames("c:" + id) }) { model.useName($0, for: id) }
                }
                HStack(alignment: .top) {
                    LabeledText("이름", text: text(\.name))
                    LabeledText("나이", text: optional(\.age), placeholder: "예: 22")
                    LabeledText("성별", text: optional(\.gender), placeholder: "여")
                }
                ForEach(NameCheckGroups.issues(for: id, in: model.nameCheck.result), id: \.text) { i in
                    Text(i.text).font(.caption).foregroundStyle(i.level == "warn" ? Color.orange : Color.secondary)
                }
                LabeledText("역할", text: text(\.role), placeholder: "주인공, 상대역, 조력자…")
                ChipRow("\(who) 역할 예시", options: SetupWizard.roles, isOn: { $0 == c.role }) { r in model.editCharacter(id) { $0.role = r } }
                LabeledText("원하는 것", text: optional(\.goal), hint: "한 줄", placeholder: "예: 염전을 되찾아 동생을 지키고 싶다")
            }
            .padding(12)
            .background(.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 10))
        }
    }
}

/// 5. 관계 (웹 `wizRels`). 이름 있는 인물이 둘 미만이면 인물 걸음으로 보낸다.
struct WizardRelations: View {
    let model: SetupModel

    var body: some View {
        let n = SetupWizard.named(model.wizardInput)
        let rels = model.project?.relationships ?? []
        let started = SetupRules.started(model.project)
        VStack(alignment: .leading, spacing: 12) {
            if n < 2 {
                HStack {
                    Text("관계를 만들려면 이름이 있는 인물이 둘 있어야 해요. 지금은 \(n)명이에요.")
                    Button("인물 걸음으로") { Task { await model.go(step: 3) } }
                }
                .font(.callout)
            } else {
                ReqTag(model, 5)
                if model.relationsLocked {
                    Notice("자동 집필이 도는 동안은 관계를 고칠 수 없어요. 고치려면 자동 집필을 일시정지하세요.", isError: true)
                }
                if rels.isEmpty { Text("관계가 없어요. 아래에서 더해요.").foregroundStyle(.secondary) }
                ForEach(rels.indices, id: \.self) { i in
                    RelationRow(model: model, index: i, started: started, compact: true).disabled(model.relationsLocked)
                }
                Button("+ 관계 더하기") { model.addRelationship() }.disabled(model.relationsLocked)
            }
        }
    }
}

/// 6. 마무리: 필수 칸 요약, 더 채우면 좋은 칸 (웹 `wizFinish`).
struct WizardFinish: View {
    let model: SetupModel

    private func text(_ kp: WritableKeyPath<Meta, String?>) -> Binding<String> {
        binding({ model.project?.meta?[keyPath: kp] ?? "" }, { v in model.editMeta { $0[keyPath: kp] = v } })
    }

    private func list(_ kp: WritableKeyPath<World, [String]?>) -> Binding<[String]> {
        binding({ model.project?.world?[keyPath: kp] ?? [] }, { v in model.editWorld { $0[keyPath: kp] = v } })
    }

    var body: some View {
        let input = model.wizardInput
        let reqs = SetupWizard.reqs(input)
        let vals = SetupWizard.summary(input) { id in model.genres.first { $0.id == id }?.name ?? id }
        VStack(alignment: .leading, spacing: 12) {
            ForEach(SetupWizard.required.indices, id: \.self) { i in
                let r = SetupWizard.required[i]
                HStack(alignment: .firstTextBaseline) {
                    Image(systemName: reqs[i] ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                        .foregroundStyle(reqs[i] ? Color.green : Color.orange).accessibilityHidden(true)
                    Text(r.label).font(.caption.bold()).frame(width: 96, alignment: .leading)
                    Text(vals[i].isEmpty ? "비어 있어요" : vals[i]).font(.caption)
                        .foregroundStyle(reqs[i] ? Color.primary : Color.secondary)
                        .lineLimit(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if reqs[i] {
                        Button("고치기") { Task { await model.go(step: r.step) } }.font(.caption).accessibilityLabel("\(r.label) 고치기")
                    } else {
                        Button("채우기") { Task { await model.go(step: r.step) } }.font(.caption).buttonStyle(.borderedProminent)
                            .accessibilityLabel("\(r.label) 채우기")
                    }
                }
            }
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 12) {
                    LabeledText("주제", text: text(\.theme), hint: "이 이야기가 끝까지 묻는 질문 하나", placeholder: "예: 떠난 사람을 이해하면 용서할 수 있나?")
                    ToneBox(model: model)
                    ListField("깨면 안 되는 규칙", items: list(\.rules))
                    ListField("장소", items: list(\.locations))
                    VStack(alignment: .leading, spacing: 4) {
                        FieldLabel("이름 스타일", hint: "이름과 지명 후보를 뽑는 기준")
                        Picker("이름 스타일", selection: binding({ model.project?.world?.nameStyle ?? "" }, { v in model.editWorld { $0.nameStyle = v } })) {
                            Text(model.autoStyleLabel).tag("")
                            ForEach(model.namingStyles, id: \.id) { Text($0.label).tag($0.id) }
                        }
                        .labelsHidden()
                        .fixedSize()
                    }
                    ListField("이름 규칙", items: list(\.nameRules), placeholder: "예: 북부 귀족은 성 앞에 '폰'을 붙인다", lines: 2)
                    NumberField("화당 분량", binding({ model.project?.meta?.wordsPerEpisode ?? 5000 }, { v in model.editMeta { $0.wordsPerEpisode = v } }),
                                hint: "공백 포함 글자 수")
                    LabeledText("메모", text: text(\.notes), lines: 2)
                }
                .padding(.top, 8)
            } label: {
                VStack(alignment: .leading) {
                    Text("더 채우면 좋아요").bold()
                    Text("주제 · 톤 · 세계 규칙 · 장소 · 이름 스타일 · 분량 · 메모").font(.caption).foregroundStyle(.secondary)
                }
            }
            Text("인물 상세(두려운 것 · 숨기는 것 · 말투 · 성격 · 외모), 관계 수치는 기획서에서 고쳐요.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}
#endif
