import CanonAPI
import CanonCore
import Foundation
import Observation

/// 갈래 엔드포인트 (`web.py` 의 `branch_family` · `make_branch` · `compare_branches` · `promote_branch` · `detach_branch`).
/// 시험에서는 가짜로 바꾼다.
public protocol BranchService: Sendable {
    func family(_ project: String) async throws -> BranchFamily
    func make(_ project: String, _ body: BranchIn) async throws -> BranchMember
    func compare(_ project: String, with other: String, ep: Int?) async throws -> BranchDiff
    func promote(_ project: String) async throws -> BranchFamily
    func detach(_ project: String) async throws -> BranchFamily
}

/// 갈래 만들기 칸 (웹 `S.branchForm`, `branchFormCard` · `syncBranchForm`).
public struct BranchDraft: Equatable, Sendable, Identifiable {
    public enum Field: String, Sendable { case from, to }

    /// 칸 하나의 오류.
    public struct Problem: Equatable, Sendable {
        public let field: Field
        public let message: String
    }

    public let id = UUID()
    public let project: String
    /// 갈래 이름. 폴더 이름을 고치지 않았으면 폴더 이름이 따라 바뀐다.
    public var label: String {
        didSet {
            if !edited { to = BranchText.folder(label: label, project: project) }
        }
    }
    /// 시작 화 (칸 글 그대로).
    public var from: String { didSet { clear(.from) } }
    /// 폴더 이름. 작가가 적으면 갈래 이름을 따라가지 않는다.
    public var to: String {
        didSet {
            if writing { edited = !to.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            clear(.to)
        }
    }
    /// 본문을 남겨 두고 상태 승인부터 다시 (`keep`). 아니면 비우고 다시 쓰기 (`clear`).
    public var keep = false
    public private(set) var edited = false
    public var problem: Problem?
    private var writing = false

    /// n 을 주지 않으면 마지막으로 반영한 화부터 (그 화를 다르게 다시 쓰는 흐름, 웹 `branchOpen`).
    public init(project: String, from n: Int?, last: Int) {
        self.project = project
        self.label = ""
        self.from = String(n.flatMap { $0 > 0 ? $0 : nil } ?? max(1, last))
        self.to = BranchText.folder(label: "", project: project)
    }

    /// 화면의 폴더 이름 칸이 쓴다. 고친 뒤로는 갈래 이름을 따라가지 않는다.
    public mutating func typeFolder(_ text: String) {
        writing = true
        to = text
        writing = false
    }

    private mutating func clear(_ field: Field) {
        if problem?.field == field { problem = nil }
    }

    /// 시작 화. 정수가 아니면 nil.
    public var fromEp: Int? { Int(from.trimmingCharacters(in: .whitespaces)) }

    /// 보내기 전 칸 검사 (웹 `branchCreate`).
    public func check(last: Int) -> Problem? {
        guard let n = fromEp, n >= 1, n <= last + 1 else {
            return Problem(field: .from, message: "시작 화는 1~\(last + 1)화 중에 골라 주세요. \(last > 0 ? "\(last)화까지 반영했어요." : "아직 반영한 화가 없어요.")")
        }
        let to = to.trimmingCharacters(in: .whitespacesAndNewlines)
        if to.isEmpty { return Problem(field: .to, message: "폴더 이름을 적어 주세요.") }
        if BranchText.folderBad(to) { return Problem(field: .to, message: "폴더 이름에 / \\ : * ? \" < > | 는 쓸 수 없고, . 으로 시작할 수 없어요.") }
        return nil
    }

    public static let taken = Problem(field: .to, message: "이미 있는 폴더 이름이에요. 다른 이름을 적어 주세요.")

    public var body: BranchIn {
        BranchIn(to: to.trimmingCharacters(in: .whitespacesAndNewlines), fromEp: fromEp ?? 1, mode: keep ? .keep : .clear,
                 label: label.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

/// 연 작품의 갈래 집안. 작품 머리 띠 · 사이드바 · 작품 홈 카드 · 갈래 비교 화면이 함께 쓴다.
@MainActor
@Observable
public final class BranchModel {
    public let project: String
    /// 갈래가 없는 작품이면 members 가 비거나 하나다.
    public private(set) var family: BranchFamily?
    public private(set) var busy = false
    public private(set) var error: String?
    /// 화면 위 알림 (만들었어요, 본편이 됐어요).
    public var notice: String?
    /// 갈래 비교 (웹 `S.branchDiff`).
    public private(set) var diff: BranchDiff?
    public private(set) var diffWith: String?
    public private(set) var diffError: String?
    /// 갈래 비교 화면을 열 때 견줄 작품 (작품 홈 카드의 '비교').
    public var wanted: String?
    private let service: any BranchService

    public init(project: String, service: any BranchService) {
        self.project = project
        self.service = service
    }

    /// 집안의 작품 (갈래가 없으면 빈 목록).
    public var members: [BranchMember] { BranchText.members(family) }

    public func load() async {
        do {
            family = try await service.family(project)
            error = nil
        } catch {
            self.error = CanonError.message(error)
        }
    }

    /// 만든 갈래.
    public struct Created: Equatable, Sendable {
        public let name: String
        public let from: Int
        public let keep: Bool
        public let notice: String
    }

    /// 갈래를 만든다. 칸 오류는 draft.problem 에 남기고 nil (409 는 폴더 이름 칸 오류).
    public func create(_ draft: inout BranchDraft, last: Int) async -> Created? {
        if let p = draft.check(last: last) {
            draft.problem = p
            return nil
        }
        draft.problem = nil
        busy = true
        defer { busy = false }
        let body = draft.body
        do {
            _ = try await service.make(project, body)
            error = nil
            return Created(name: body.to, from: body.fromEp, keep: draft.keep, notice: BranchText.created(label: draft.label, to: body.to))
        } catch let e as CanonError where e.isConflict {
            draft.problem = BranchDraft.taken
        } catch {
            self.error = CanonError.message(error)
        }
        return nil
    }

    /// 이 갈래를 본편으로 올린다.
    public func promote(_ m: BranchMember) async {
        await change(m, BranchText.promoted(m)) { try await self.service.promote(m.name) }
    }

    /// 갈래를 끊어 따로 선 작품으로 만든다.
    public func detach(_ m: BranchMember) async {
        await change(m, BranchText.detached(m)) { try await self.service.detach(m.name) }
    }

    private func change(_ m: BranchMember, _ done: String, _ call: () async throws -> BranchFamily) async {
        busy = true
        defer { busy = false }
        do {
            _ = try await call()
            notice = done
            error = nil
            await load()  // 끊은 작품이 지금 작품이 아닐 수도 있어 지금 작품의 집안을 다시 읽는다
            if diffWith != nil { await compare(other: diffWith, ep: diff?.episode) }
        } catch {
            self.error = CanonError.message(error)
        }
    }

    /// 견줄 작품을 고르고 비교를 불러온다 (웹 `branchCompareLoad`). ep 가 nil 이면 서버가 고른다.
    public func compare(other: String?, ep: Int?) async {
        guard let pick = BranchText.pick(family, project, other: other) else {
            diff = nil
            diffWith = nil
            return
        }
        do {
            let d = try await service.compare(project, with: pick, ep: ep)
            diff = d
            diffWith = pick
            diffError = nil
        } catch {
            diffError = CanonError.message(error)
        }
    }

    public func dismissNotice() { notice = nil }
    public func dismissError() { error = nil }
}
