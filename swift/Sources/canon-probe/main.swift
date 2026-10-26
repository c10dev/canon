// 실제 서버에 붙어 응답이 앱의 타입대로 읽히는지 본다. 서버를 고친 뒤 openapi.json 을 다시 만들었으면 돌려 본다.
//   swift run canon-probe http://127.0.0.1:8000
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
    let jobs = try await server.listJobs()
    print("작업 \(jobs.count)개")
} catch {
    print("실패: \(CanonError.message(error))")
    exit(1)
}
