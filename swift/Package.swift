// swift-tools-version: 6.0
// Canon 앱의 모듈. 화면이 없는 모듈(CanonCore, CanonAPI, 각 Feature 의 Model)은 Linux 에서도 빌드하고 시험한다.
// SwiftUI 화면은 `#if canImport(SwiftUI)` 안에 두어 Apple 플랫폼에서만 빌드된다.
import PackageDescription

let package = Package(
    name: "CanonKit",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        .library(name: "CanonAppUI", targets: ["CanonAppUI"]),
        .library(name: "CanonAPI", targets: ["CanonAPI"]),
        .library(name: "CanonCore", targets: ["CanonCore"]),
        .executable(name: "canon-probe", targets: ["canon-probe"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-openapi-generator", from: "1.6.0"),
        .package(url: "https://github.com/apple/swift-openapi-runtime", from: "1.7.0"),
        .package(url: "https://github.com/apple/swift-openapi-urlsession", from: "1.0.2"),
    ],
    targets: [
        // 순수 Swift: 서버 주소, 오류 문구, 작업 추적, 한국어 표시 규칙. 다른 모듈에 기대지 않는다
        .target(name: "CanonCore"),
        // openapi.json 에서 만든 클라이언트와 타입, 그리고 서버 연결(헤더, 작품 판 캐시)
        .target(
            name: "CanonAPI",
            dependencies: [
                "CanonCore",
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
            ],
            plugins: [.plugin(name: "OpenAPIGenerator", package: "swift-openapi-generator")]
        ),
        // 여러 화면이 함께 쓰는 SwiftUI 조각
        .target(name: "CanonUI", dependencies: ["CanonCore"]),
        // 열어 둔 작품: 받기 · 고친 표시 · 저장(409 충돌, 서버가 지킨 칸). 여러 화면이 함께 쓴다
        .target(name: "CanonStore", dependencies: ["CanonCore", "CanonAPI"]),
        // 화면 모듈: Model(순수 Swift) + View(SwiftUI). CanonCore · CanonAPI · CanonUI · CanonStore 에만 기댄다
        .target(name: "FeatureProjects", dependencies: ["CanonCore", "CanonAPI", "CanonUI"]),
        .target(name: "FeatureHome", dependencies: ["CanonCore", "CanonAPI", "CanonUI", "CanonStore"]),
        .target(name: "FeatureStatWin", dependencies: ["CanonCore", "CanonAPI", "CanonUI"]),
        // 앱 뼈대: 서버 설정, 사이드바, 화면 잇기. Xcode 앱(App/)은 이것 하나만 가져온다
        .target(name: "CanonAppUI", dependencies: ["CanonCore", "CanonAPI", "CanonUI", "CanonStore", "FeatureProjects", "FeatureHome", "FeatureStatWin"]),
        // 개발용: 실제 서버에 붙어 응답이 타입대로 읽히는지 본다
        .executableTarget(name: "canon-probe", dependencies: ["CanonAPI", "CanonCore"]),
        .testTarget(name: "CanonCoreTests", dependencies: ["CanonCore"]),
        .testTarget(name: "CanonAPITests", dependencies: ["CanonAPI"]),
        .testTarget(name: "CanonStoreTests", dependencies: ["CanonStore"]),
        .testTarget(name: "FeatureProjectsTests", dependencies: ["FeatureProjects"]),
        .testTarget(name: "FeatureHomeTests", dependencies: ["FeatureHome", "CanonStore"]),
        .testTarget(name: "FeatureStatWinTests", dependencies: ["FeatureStatWin"]),
    ]
)
