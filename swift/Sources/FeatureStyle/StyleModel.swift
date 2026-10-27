import CanonAPI
import CanonCore
import CanonStore
import Foundation
import Observation

/// 문체 화면이 부르는 서버. 시험에서는 가짜로 바꾼다.
public protocol StyleService: Sendable {
    /// 원문으로 스타일 프로필 제안 (LLM, 서버 `analyze_style`). 저장하지 않는다.
    func analyze(_ project: String, _ text: String) async throws -> StyleProfile
    /// 원문 전체의 기준 지표 (LLM 없음, 서버 `measure`).
    func measure(_ text: String) async throws -> StyleMetrics
    func link(_ project: String) async throws -> StyleLink
    func library() async throws -> [StyleSummary]
    /// 라이브러리 문체를 작품에 복사하고 저장한다.
    func apply(_ project: String, styleID: String) async throws
    /// 작품 문체를 라이브러리에 새로 저장(`update` 면 연결된 항목의 새 버전)하고 작품을 저장한다.
    func keep(_ project: String, _ body: Components.Schemas.StyleKeep) async throws -> StyleSummary
}

/// 문체 레퍼런스 화면 (웹 `viewStyle` · `styleLibraryCard` · `profileFields` · `mystyle.js` 의 `deviceFields`).
/// 프로필은 함께 쓰는 `ProjectDocument` 로 고치고 저장 띠가 저장한다.
@MainActor
@Observable
public final class StyleModel {
    public let document: ProjectDocument
    private let service: any StyleService

    /// 예시 원문. 작품에 저장하지 않는다 (라이브러리에 저장할 때만 함께 보관).
    public var sample = ""
    public private(set) var link: StyleLink?
    public private(set) var library: [StyleSummary] = []
    public private(set) var busy: String?
    public private(set) var notice: (text: String, isError: Bool)?

    public init(document: ProjectDocument, service: any StyleService) {
        self.document = document
        self.service = service
    }

    public var project: Project? { document.project }
    public var profile: StyleProfile? { project?.style }
    var name: String { document.name }

    public func load() async {
        await document.load()
        await refreshLibrary()
    }

    public func dismissNotice() { notice = nil }

    private func refreshLibrary() async {
        async let l = try? service.link(name)
        async let libs = try? service.library()
        link = await l ?? link
        library = await libs ?? library
    }

    // MARK: 프로필 고치기

    public func editStyle(_ change: (inout StyleProfile) -> Void) {
        document.edit { p in
            var s = p.style ?? StyleProfile()
            change(&s)
            p.style = s
        }
    }

    public func addPassage() { editStyle { $0.samplePassages = ($0.samplePassages ?? []) + [""] } }
    public func removePassage(_ i: Int) { editStyle { s in if s.samplePassages?.indices.contains(i) == true { s.samplePassages!.remove(at: i) } } }
    public func addMarker() { editStyle { $0.markers = ($0.markers ?? []) + [StyleMarker(text: "", note: "", per1k: 0)] } }
    public func removeMarker(_ i: Int) { editStyle { s in if s.markers?.indices.contains(i) == true { s.markers!.remove(at: i) } } }
    public func addDevice() { editStyle { $0.devices = ($0.devices ?? []) + [StyleDevice(name: "", when: "", cues: [], every: 0, example: "")] } }
    public func removeDevice(_ i: Int) { editStyle { s in if s.devices?.indices.contains(i) == true { s.devices!.remove(at: i) } } }

    // MARK: 분석

    /// 원문이 짧으면 까닭을 알리고 false.
    public func sampleReady() -> Bool {
        guard sample.trimmingCharacters(in: .whitespacesAndNewlines).count >= StyleText.minSample else {
            notice = ("예시 원문을 200자 이상 넣어 주세요", true)
            return false
        }
        return true
    }

    /// 분석하기 전에 물을 말. 묻지 않아도 되면 nil.
    public var analyzeQuestion: String? { StyleText.analyzeQuestion(profile, link: link) }

    /// 원문을 분석해 프로필과 기준 지표를 바꾼다. 저장은 사용자가 한다 (웹 `analyzeStyle`).
    public func analyze() async {
        guard sampleReady(), busy == nil else { return }
        busy = "문체를 분석하는 중… (최대 1분)"
        defer { busy = nil }
        if document.dirty, await document.save() == false, document.dirty { return }
        do {
            let prof = try await service.analyze(name, sample)
            let base = try await service.measure(sample)  // 문체 경고가 원문 전체와 비교하도록
            document.edit { p in
                p.style = prof
                p.styleBaseline = base
                p.styleId = ""  // 새로 분석한 문체는 라이브러리 항목과 연결을 끊는다
                p.styleVersion = 0
            }
            link = StyleLink(state: "none")  // 저장하면 서버도 같은 상태가 된다
            notice = ("분석 결과를 불러왔어요. 확인하고 저장하세요.", false)
        } catch {
            notice = (CanonError.message(error), true)
        }
    }

    // MARK: 라이브러리

    public func useQuestion(_ id: String) -> String {
        StyleText.useQuestion(library.first { $0.id == id }?.name ?? id, link: link)
    }

    /// 라이브러리 문체를 적용한다 (웹 `useLibStyle`). 가져오기 · 되돌리기(`pullStyle`)도 이것으로 한다.
    public func use(_ id: String, done: String = "라이브러리 문체를 적용했어요") async {
        guard !id.isEmpty else {
            notice = ("적용할 문체를 고르세요", true)
            return
        }
        await run("적용하는 중") {
            try await self.service.apply(self.name, styleID: id)
            await self.document.reload()
            await self.refreshLibrary()
            self.notice = (done, false)
        }
    }

    public func pull() async {
        guard let l = link, let id = l.id else { return }
        await use(id, done: "라이브러리 '\(l.name ?? "")' \(l.version ?? 0)번 버전을 가져왔어요")
    }

    public var canKeep: Bool { !StyleText.blank(profile) }

    public var defaultKeepName: String {
        let title = project?.meta?.title ?? ""
        return "\(title.isEmpty ? name : title) 문체"
    }

    /// 지금 문체를 라이브러리에 새로 저장한다 (웹 `keepStyle`). 붙여 넣은 원문도 함께 보관한다.
    public func keep(as entryName: String) async {
        await run("라이브러리에 저장하는 중") {
            let body = Components.Schemas.StyleKeep(name: entryName.trimmingCharacters(in: .whitespacesAndNewlines), sample: self.sample)
            let entry = try await self.service.keep(self.name, body)
            await self.document.reload()
            await self.refreshLibrary()
            self.notice = ("라이브러리에 '\(entry.name)' 로 저장했어요", false)
        }
    }

    /// 연결된 라이브러리 항목의 새 버전으로 올린다 (웹 `pushStyle`).
    public func push(note: String) async {
        await run("라이브러리에 올리는 중") {
            let body = Components.Schemas.StyleKeep(update: true, note: note.trimmingCharacters(in: .whitespacesAndNewlines))
            let entry = try await self.service.keep(self.name, body)
            await self.document.reload()
            await self.refreshLibrary()
            self.notice = ("라이브러리 '\(entry.name)' 을 \(entry.version)번 버전으로 올렸어요", false)
        }
    }

    public var pushNote: String {
        guard let l = link else { return "" }
        return StyleText.pushNote(l, usedBy: library.first { $0.id == l.id }?.usedBy ?? [], project: name)
    }

    /// 서버가 작품을 저장하는 요청. 저장하지 않은 변경은 먼저 저장한다 (웹 `saveIfDirty`).
    private func run(_ label: String, _ work: @escaping () async throws -> Void) async {
        guard busy == nil else { return }
        busy = label
        defer { busy = nil }
        if document.dirty, await document.save() == false, document.dirty { return }
        do {
            try await work()
        } catch {
            notice = (CanonError.message(error), true)
        }
    }
}
