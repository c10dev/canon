// 실제 서버에 붙어 응답이 앱의 타입대로 읽히는지 본다. 서버를 고친 뒤 openapi.json 을 다시 만들었으면 돌려 본다.
//   swift run canon-probe http://127.0.0.1:8000
//   swift run canon-probe http://127.0.0.1:8000 --save <작품>   저장과 409 충돌도 본다 (그 작품을 바꾸지 않고 두 번 저장한다. 시험 서버에서만)
import CanonAPI
import CanonCore
import Foundation

let address = CommandLine.arguments.dropFirst().first ?? "http://127.0.0.1:8000"
guard let config = ServerConfig.parse(address) else {
    print("주소를 읽지 못했어요: \(address)")
    exit(2)
}
let server = CanonServer(config: config)
do {
    guard case let .ok(ok) = try await server.call({ try await $0.listProjects() }) else {
        print("작품 목록을 받지 못했어요")
        exit(1)
    }
    let cards = try ok.body.json
    print("작품 \(cards.count)개")
    let loader = ProjectLoader(server: server)
    for card in cards {
        let p = try await loader.load(card.name)
        let again = try await loader.load(card.name)  // 같은 판이면 304 로 받는다
        print("- \(card.name): \(p.episodes?.count ?? 0)화 · 인물 \(p.characters?.count ?? 0)명 · 판 \(await loader.etag(card.name) ?? "없음") · 다시 받기 \(again.episodes?.count == p.episodes?.count ? "같음" : "다름")")
    }
    // 저장 왕복: 받은 JSON 을 생성 타입으로 읽고 다시 써서, 저장할 때 빠질 칸이 있는지 본다 (null 과 빈 값은 같다고 본다)
    for card in cards {
        let url = URL(string: APIPath.project(card.name), relativeTo: config.baseURL)!
        let (raw, _) = try await URLSession.shared.data(from: url)
        let typed = try JSONDecoder().decode(Components.Schemas.Project.self, from: raw)
        let again = try JSONEncoder().encode(typed)
        let lost = missing(try JSONSerialization.jsonObject(with: raw), in: try JSONSerialization.jsonObject(with: again), path: "")
        print("- \(card.name) 저장 왕복: \(lost.isEmpty ? "빠지는 칸 없음" : "빠지는 칸 \(lost.count)개: \(lost.prefix(5).joined(separator: ", "))")")
    }
    let jobs = try await server.listJobs()
    print("작업 \(jobs.count)개")
    if let i = CommandLine.arguments.firstIndex(of: "--save"), i + 1 < CommandLine.arguments.count {
        let name = CommandLine.arguments[i + 1]
        let a = ProjectLoader(server: CanonServer(config: config))
        let b = ProjectLoader(server: CanonServer(config: config))
        let pa = try await a.load(name)
        let pb = try await b.load(name)
        let saved = try await a.save(name, pa)
        print("저장: 판 \(pa.editRev ?? 0) → \(saved.project.editRev ?? 0), 서버가 지킨 칸 \(saved.kept.count)개")
        do {
            _ = try await b.save(name, pb)
            print("충돌: 409 가 나야 하는데 저장됐어요")
        } catch let e as CanonError where e.isConflict {
            print("충돌: 409 (\(e.errorDescription ?? ""))")
        }
        let forced = try await b.save(name, pb, force: true)
        print("덮기: 판 \(forced.project.editRev ?? 0)")
    }
} catch {
    print("실패: \(CanonError.message(error))")
    exit(1)
}

/// `a` 에 값이 있는데 `b` 에 없는 칸의 경로. 목록은 같은 자리끼리 본다.
func missing(_ a: Any, in b: Any?, path: String) -> [String] {
    func empty(_ v: Any) -> Bool { v is NSNull || (v as? [Any])?.isEmpty == true || (v as? [String: Any])?.isEmpty == true }
    if let a = a as? [String: Any] {
        let b = b as? [String: Any] ?? [:]
        return a.keys.sorted().flatMap { k -> [String] in
            guard let v = a[k], !empty(v) else { return [] }
            guard let w = b[k] else { return ["\(path)/\(k)"] }
            return missing(v, in: w, path: "\(path)/\(k)")
        }
    }
    if let a = a as? [Any] {
        let b = b as? [Any] ?? []
        return a.enumerated().flatMap { i, v in i < b.count ? missing(v, in: b[i], path: "\(path)/\(i)") : ["\(path)/\(i)"] }
    }
    return []
}
