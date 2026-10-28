import CanonAPI

/// 한 화의 검수 세션 (웹 `home.js` 의 `checkState` 와 같은 규칙이라 함께 고친다).
/// 지적과 회차는 서버 `findings.merge` 가 만든다 (`Episode.findings` · `rounds`).
public struct CheckState: Equatable, Sendable {
    /// 한 번이라도 검수했다.
    public let checked: Bool
    /// 마지막 회차 뒤에 본문을 고쳤다 (되돌린 수정과 이 지적만 다시 검수가 본 고침안 묶음은 빼고 마지막 수정 시각과 견준다).
    public let stale: Bool
    /// 열린 지적 수.
    public let open: Int
    /// 검수했고 그 뒤 고치지 않았고 열린 지적이 없다. 진행 막대의 검수 칸이 찬다.
    public var done: Bool { checked && !stale && open == 0 }

    public init(checked: Bool, stale: Bool, open: Int) {
        self.checked = checked
        self.stale = stale
        self.open = open
    }
}

extension Episode {
    public var checkState: CheckState {
        let at = checkedAt ?? ""
        // 이 지적만 다시 검수로 풀린 고침안 묶음은 그 검수가 이미 본 수정이라 '검수 뒤 고침'으로 세지 않는다
        let seen = Set((findings ?? []).filter { $0.closedBy == .one }.compactMap { $0.fixGroup }.filter { !$0.isEmpty })
        let last = (edits ?? []).last { $0.undone != true && !seen.contains($0.group ?? "") }
        let checked = !at.isEmpty
        return CheckState(checked: checked, stale: checked && (last?.at ?? "") > at,
                          open: (findings ?? []).filter { ($0.status ?? .open) == .open }.count)
    }
}
