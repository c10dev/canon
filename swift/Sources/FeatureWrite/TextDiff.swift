/// 비교 결과 한 조각: 그대로 둔 글, 지운 글, 더한 글.
public struct DiffPiece: Equatable, Sendable {
    public enum Kind: Equatable, Sendable { case same, removed, added }
    public var kind: Kind
    public var text: String

    public init(_ kind: Kind, _ text: String) {
        self.kind = kind
        self.text = text
    }
}

/// 본문 두 판 비교. 웹 `rewrite.js` 의 `textDiff` · `rwSimilar` 와 `passage.js` 의 `tokens` · `wordDiff` 와 같은 규칙이라 함께 고친다.
public enum TextDiff {
    static let marks: Set<Character> = [".", ",", "!", "?", "…", "\"", "'", "“", "”", "‘", "’"]

    /// 띄어쓰기 덩어리, 문장 부호 하나, 그 밖의 글 덩어리로 나눈다 (웹 `tokens`).
    static func tokens(_ t: String) -> [String] {
        var out: [String] = []
        var cur = ""
        var curSpace = false
        for ch in t {
            if marks.contains(ch) {
                if !cur.isEmpty { out.append(cur); cur = "" }
                out.append(String(ch))
            } else if ch.isWhitespace != curSpace, !cur.isEmpty {
                out.append(cur)
                cur = String(ch)
                curSpace = ch.isWhitespace
            } else {
                if cur.isEmpty { curSpace = ch.isWhitespace }
                cur.append(ch)
            }
        }
        if !cur.isEmpty { out.append(cur) }
        return out
    }

    /// 두 문단이 닮았나: 낱말이 40% 이상 겹친다 (웹 `rwSimilar`).
    static func similar(_ a: String, _ b: String) -> Bool {
        let blank = { (t: String) in t.allSatisfy(\.isWhitespace) }
        let A = Set(tokens(a).filter { !blank($0) })
        let B = tokens(b).filter { !blank($0) }
        guard !A.isEmpty, !B.isEmpty else { return false }
        return Double(B.filter { A.contains($0) }.count) / Double(max(A.count, B.count)) >= 0.4
    }

    /// 가장 긴 공통 부분열 표 (끝에서부터). `L[i][j]` 는 `a[i...]` 와 `b[j...]` 의 공통 길이.
    private static func lcs(_ a: [String], _ b: [String]) -> [[Int32]] {
        var L = Array(repeating: Array(repeating: Int32(0), count: b.count + 1), count: a.count + 1)
        for i in stride(from: a.count - 1, through: 0, by: -1) {
            for j in stride(from: b.count - 1, through: 0, by: -1) {
                L[i][j] = a[i] == b[j] ? L[i + 1][j + 1] + 1 : max(L[i + 1][j], L[i][j + 1])
            }
        }
        return L
    }

    /// 단어 단위 비교 (웹 `wordDiff`). 바뀐 곳 사이의 띄어쓰기는 바뀐 곳에 붙여 덩어리로 읽게 한다.
    public static func words(_ a: String, _ b: String) -> [DiffPiece] {
        let A = tokens(a)
        let B = tokens(b)
        if A.count * B.count > 400_000 { return [DiffPiece(.removed, a), DiffPiece(.added, b)].filter { !$0.text.isEmpty } }
        let L = lcs(A, B)
        var ops: [(DiffPiece.Kind, String)] = []
        func push(_ k: DiffPiece.Kind, _ t: String) {
            if let last = ops.last, last.0 == k { ops[ops.count - 1].1 += t } else { ops.append((k, t)) }
        }
        var i = 0, j = 0
        while i < A.count && j < B.count {
            if A[i] == B[j] {
                push(.same, A[i]); i += 1; j += 1
            } else if L[i + 1][j] >= L[i][j + 1] {
                push(.removed, A[i]); i += 1
            } else {
                push(.added, B[j]); j += 1
            }
        }
        while i < A.count { push(.removed, A[i]); i += 1 }
        while j < B.count { push(.added, B[j]); j += 1 }
        var out: [DiffPiece] = []
        var del = "", ins = ""
        func flush() {
            if !del.isEmpty { out.append(DiffPiece(.removed, del)) }
            if !ins.isEmpty { out.append(DiffPiece(.added, ins)) }
            del = ""; ins = ""
        }
        for (x, (k, t)) in ops.enumerated() {
            let gap = k == .same && t.allSatisfy(\.isWhitespace) && (!del.isEmpty || !ins.isEmpty) && x + 1 < ops.count && ops[x + 1].0 != .same
            if k == .removed || gap { del += t }
            if k == .added || gap { ins += t }
            if k == .same && !gap {
                flush()
                out.append(DiffPiece(.same, t))
            }
        }
        flush()
        return merged(out)
    }

    /// 본문 두 판을 문단(줄)으로 맞춰 보고, 바뀐 문단끼리 닮았으면 단어 단위로, 아니면 통째로 지운 글 · 더한 글로 (웹 `textDiff`).
    /// `changes` 는 바뀐 곳(연달아 바뀐 문단 묶음) 개수.
    public static func lines(_ a: String, _ b: String) -> (pieces: [DiffPiece], changes: Int) {
        let A = a.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        let B = b.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        if A.count * B.count > 250_000 { return ([DiffPiece(.removed, a), DiffPiece(.added, b)].filter { !$0.text.isEmpty }, 1) }
        let L = lcs(A, B)
        var rows: [[DiffPiece]] = []
        var changes = 0
        var dels: [String] = [], adds: [String] = []
        func one(_ k: DiffPiece.Kind, _ t: String) -> [DiffPiece] { t.isEmpty ? [] : [DiffPiece(k, t)] }
        func flush() {
            if !dels.isEmpty || !adds.isEmpty { changes += 1 }
            let k = min(dels.count, adds.count)
            for x in 0..<k {
                if similar(dels[x], adds[x]) {
                    rows.append(words(dels[x], adds[x]))
                } else {
                    let gap = !dels[x].isEmpty && !adds[x].isEmpty ? [DiffPiece(.same, "\n")] : []
                    rows.append(one(.removed, dels[x]) + gap + one(.added, adds[x]))
                }
            }
            for t in dels.dropFirst(k) { rows.append(one(.removed, t)) }
            for t in adds.dropFirst(k) { rows.append(one(.added, t)) }
            dels = []; adds = []
        }
        var i = 0, j = 0
        while i < A.count || j < B.count {
            if i < A.count && j < B.count && A[i] == B[j] {
                flush()
                rows.append(one(.same, A[i]))
                i += 1; j += 1
            } else if j >= B.count || (i < A.count && L[i + 1][j] >= L[i][j + 1]) {
                dels.append(A[i]); i += 1
            } else {
                adds.append(B[j]); j += 1
            }
        }
        flush()
        var out: [DiffPiece] = []
        for (x, row) in rows.enumerated() {
            if x > 0 { out.append(DiffPiece(.same, "\n")) }
            out += row
        }
        return (merged(out), changes)
    }

    /// 이웃한 같은 종류 조각을 잇는다.
    static func merged(_ pieces: [DiffPiece]) -> [DiffPiece] {
        var out: [DiffPiece] = []
        for p in pieces where !p.text.isEmpty {
            if let last = out.last, last.kind == p.kind { out[out.count - 1].text += p.text } else { out.append(p) }
        }
        return out
    }
}
