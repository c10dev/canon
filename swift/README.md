# Canon 앱 (Swift)

웹 화면(`canon/static/*.js`)을 SwiftUI 앱으로 옮긴다. macOS · iPadOS · iOS 앱 하나다.

## 범위 (2026-10-26 결정)

- **앱은 서버 클라이언트다.** Python 서버(`python -m canon serve`)를 그대로 쓰고, 앱은 그 API 를 부른다.
  프롬프트, LLM 호출, 지표, 관계 계산, 파이프라인은 Python 한 곳에만 둔다 (AGENTS.md '설계 원칙').
  앱에 같은 계산을 다시 짜지 않는다. 화면 표시 규칙(조사, 날짜, 단계 이름)만 옮긴다.
- **기기:** macOS 14+, iOS · iPadOS 17+. 다른 기기에서는 Tailscale 로 서버에 붙는다.
- **웹 화면은 그대로 둔다.** 앱으로 옮기지 않은 화면은 앱이 '옮기는 중'으로 보이고 웹에서 쓴다.

## 모듈

패키지 하나(`CanonKit`, `Package.swift`)에 모듈(target)을 나눈다. 의존은 아래 방향으로만 흐른다.

```
App/ (Xcode 앱 껍데기, @main 만)
 └─ CanonAppUI        앱 뼈대: 서버 설정, 사이드바, 화면 잇기, 작업 지켜보기
     ├─ Feature*      화면 하나: Model(순수 Swift) + View(SwiftUI)
     │   ├─ CanonUI   함께 쓰는 SwiftUI 조각 (알림, 옮기는 중)
     │   ├─ CanonAPI  openapi.json 에서 만든 Client · 타입 + 서버 연결
     │   └─ CanonCore 순수 Swift: 서버 주소, 오류 문구, 작업 추적, 한국어 표시 규칙
     └─ ...
canon-probe            개발용: 실제 서버 응답이 타입대로 읽히는지 본다
```

규칙:

1. `CanonCore` 는 다른 모듈에 기대지 않는다. Foundation 만 쓴다.
2. `Feature*` 끼리는 서로 기대지 않는다. 화면을 잇는 일은 `CanonAppUI` 가 한다. 한 화면에 다른 화면 모듈의 조각을 끼울 때는 받는 쪽이 자리(예: `FeaturePlot.PlotSlots`)를 열고 `CanonAppUI` 가 채운다. 작품 전체를 함께 쓰는 화면은 `CanonStore.ProjectDocument` 하나를 받는다 (`AppModel.document`).
3. Model 은 SwiftUI 를 가져오지 않는다. 서버는 프로토콜(예: `ProjectListing`) 뒤에 두고 시험에서 가짜로 바꾼다.
4. View 파일은 `#if canImport(SwiftUI)` 로 감싼다. 그래서 Model 과 시험은 Linux 에서도 빌드된다.
5. 서버 타입을 손으로 다시 정의하지 않는다. `Components.Schemas.*` (생성된 타입)를 쓴다.
   서버가 dict 를 돌려줘 타입이 없으면, 서버에 pydantic 응답 모델을 단다 (아래 '서버 계약' 5).

| 모듈 | 들어 있는 것 |
|---|---|
| `CanonCore` | `ServerConfig`, `ClientIdentity`, `CanonError`(웹 `fmtErr` 와 같은 문구), `APIPath`(작품 이름 인코딩), `Job` · `JobRequest` · `JobTracker` · `JobText`(웹 `pollJobs`, `JOB_DONE_MSG`), `PendingList`, `JSONValue`(모양을 모르는 작업 결과), `KoreanText`(조사, 'a~b화', 날짜), `EpisodeStatus`, `Screen`(사이드바), `SetupWizard`(새 작품 마법사의 필수 칸 · 걸음 · 세계 종류 · 시대) |
| `CanonAPI` | 생성된 `Client`(빌드 때 `openapi.json` 에서), `CanonServer`(헤더, 오류 바꾸기, 타입 없는 GET), `ProjectLoader`(작품 전체를 ETag 로) |
| `CanonUI` | `Notice`, `NotPortedYet`, 입력 칸 `LabeledText` · `ListField`(한 줄에 하나씩) · `ChipRow` · `Flow`(줄바꿈 배치), 갈래 만들기 칸 열기 `BranchOpener`(환경 값 `openBranchForm`, 작품 홈 · 상태 승인 · 갈래 비교 단추가 부르고 `CanonAppUI` 가 칸을 띄운다) |
| `CanonStore` | 검수 칸 `CheckState`(`Episode.checkState`), `ProjectDocument`(연 작품: 받기, `edit`, 고친 표시, `save` 의 409 충돌 · 덮기, 서버가 지킨 칸 알림, 작업이 쓴 화만 받기 `merge`), `JobCenter`(작업 시작 · 멈추기 · 지켜보기, 검토를 기다리는 결과 `results` 와 실패 `failures`), `ProjectStoring` · `JobServing` |
| `FeatureProjects` | 작품 목록: `ProjectsModel`, `ProjectCardText`(웹 `projectNext`), `ProjectGroup`(같은 갈래 집안을 본편 카드 하나로 묶기, 웹 `branchGroups`), `LiveProjectListing`, `ProjectsView` |
| `FeatureHome` | 작품 홈: `HomeSummary`(웹 `viewHome` · `nextStep` · `currentEp`), `HomeView`, 다른 화면 모듈이 끼우는 칸 `HomeSlots`(환경 값 `homeSlots`: 갈래 카드) |
| `FeatureStatWin` | 상태창 수치: `StatWinModel`, `StatWinText`(틀 이름 · 순서, 보낼 값. `+3` · `+독 내성` 계산은 서버 `statwin.resolve` 가 한다), `StatCell`(비교표 칸), `LiveStatWin`, `StatWinScreen` |
| `FeatureForeshadow` | 복선 센터: `ForeshadowModel`, `ForeshadowChange`(고치기 · 걸린 문장 지우기 · 정리), `ForeshadowText`(웹 `fsItem` · `fsShown`), `ForeshadowTrack`(웹 `fsTrack`), `LiveForeshadowService`, `ForeshadowView` |
| `FeatureUsage` | 사용량 · 비용: `UsageModel`(기간 · 작품 거르기, 가격표 고치기 · 되돌리기), `UsageText` · `UsageChart`(웹 `usage.js` 문구 · 막대), `LiveUsageSource`, `UsageView` |
| `FeatureCast` | 인물 · 관계도: `CastModel`(시점 재생, 고르기, 배치), `CastText`(웹 `cast.js` 문구), `WarmthBand`, `CastLayout`(힘 배치 · 선 모양), `CastHit`, `LiveCastSource`(작품 전체 + `cast_view`), `DefaultsLayoutStore`, `CastScreen` |
| `FeatureReview` | 상태 승인: `ReviewModel`(작업 결과 `state:<화>` 읽기, 고르기 · 고치기, 반영 · 다시 맞추기 · 그대로 두기 · 반영 취소, 관계 미리 보기), `ReviewText`(웹 `setDelta` · `pickedDelta` · `relationLines` · `swDeltaRows` · `fsClueRows` · `restate.js`), `LiveReviewService`, `ReviewView` |
| `FeatureCheck` | 검수 (5단계): `CheckModel`(화 고르기, 검수 작업, 지적 고르기 · 거르기, 처리 상태 · 메모 `set_finding`, 문체 지표 `episode_style`), `CheckText`(웹 `check.js` 문구와 표시 규칙), `LiveCheckService`, `CheckView`(회차 띠, 지적 목록 · 본문 밑줄 · 지적 상세, 문체 지표 탭) |
| `FeatureWrite` | 집필: `WriteModel`(화 고르기, 본문 초안과 '본문 저장', 쓰기 작업(실패한 검수 다시 시도), 다시 생성, 복사 · 내보내기), `WriteText` · `RewriteText` · `PublishText`(웹 문구), `RewriteDraft`, `TextDiff`(새 판 비교), `LiveWriteService`, `WriteView` |
| `FeaturePlot` | 기승전결 · 플롯 (장편은 부 · 아크 · 플롯): `PlotModel`(구간 · 화 · 아크 · 부 고치기, 확정, 작업 결과를 제안으로 받기 · 적용 · 버리기, 화 끼워 넣기 · 빼기), `PlotRules`(웹 `actRanges` · `fitActs` · `actCoverage` 등), `PlotBoard` · `PlotEditorInfo` · `EpisodeCard`(보드 · 편집기 · 화 카드), `LivePlotService`, `PlotScreen` |
| `FeatureSetup` | 설정 도우미: `SetupModel`(작품 정보 · 인물 · 관계 고치기, 이름 후보 · 점검, AI 설정 제안 고르기, 마법사 · 기획서 보기와 걸음 `wizard` · `go(step:)`), `Logline` · `LoglineField` · `Tone` · `ToneDial`(로그라인 합치기 · 점검, 톤 다이얼), `SetupRules`(새 인물 id, 관계 쌍 · 문제, 장르, 지우기 질문), `SuggestionPicks`, `NameCheckGroups`, `LiveSetupService`, `SetupView`(기획서), `WizardContent`(새 작품 마법사) |
| `FeatureStyle` | 문체 레퍼런스: `StyleModel`(원문 분석, 라이브러리 고르기 · 저장 · 올리기 · 가져오기, 프로필 · 표지 · 장치 · 대표 문단 고치기), `StyleText`(웹 `styleBlank` · `styleChangeWho` · `baselineRows` 문구), `LiveStyleService`, `StyleView` |
| `FeatureSettings` | 모델 · API 키 설정 (작품 목록 · 작품 사이드바 툴바의 '모델 · API 키' 시트): `SettingsModel`(불러오기, 저장 · 키 지우기, 연결 확인, 모델 목록, Claude 상태), `SettingsDraft`(고치는 칸, 보낼 값 `body`, 단계 비우기), `SettingsText`(웹 문구 · 규칙), `LiveSettingsService`, `SettingsView`. 키는 칸에만 들고 있다가 서버로 보내고 저장하면 비운다. 다시 보일 때는 서버의 끝 네 글자(`key_hint`)만 |
| `FeatureAuto` | 자동 집필: `AutoModel`(실행 상태 3초마다 묻기 · 연결 끊김, 시작 · 일시정지 · 이어 가기 · 중지, 새로 시작 칸 · 배치 끔/켬 추정, 멈춘 실행의 정책 고치기, 검토 대기 변경안을 상태 승인으로 보내기, 자동 반영한 화 반영 취소), `AutoText`(웹 `auto.js` 문구), `LiveAutoService`, `AutoScreen` · `PolicyForm` |
| `FeatureLines` | 이야기 줄기: `LinesModel`(줄기 고르기 · 고치기 · 지우기, 화 붙이기 · 빼기, AI 제안 `storyline` 받기 · 고른 화와 함께 적용 · 버리기), `LineRules`(웹 `lines.js` 규칙 · 문구), `LineMapLayout`(노선도 자리 · 누른 곳), `LiveLinesService`, `LinesScreen`. 다른 화면이 쓰는 `LineField`(플롯 편집기 줄기 칸) · `LineBadges`(화 카드 줄기 표시) |
| `FeatureCausal` | 인과율: `CausalModel`(요소 더하기 · 고치기 · 지우기 · 되살리기, 영향 분석 작업 `impact` 시작, 끝나면 분석만 받아 오기, 변경안 고르기 · 적용 · 버리기 · 다시 검토), `CausalText`(웹 `causal.js` 문구, `elBasis` · 배지 · 관련 화 지도 칸, `chat.js` `plotDiff`), `LiveCausalService`, `CausalView` |
| `FeatureBrief` | 작업지시서 (API 없이): `BriefModel`(화 · 지시서 종류 고르기, 지시서 받기, 받은 본문 저장, 받은 JSON 서버 검사), `BriefText`(웹 `viewBrief` 문구), `LiveBriefService`, `BriefView`(복사 · .md 내려받기) |
| `FeatureBranches` | 갈래: `BranchModel`(연 작품의 집안 받기, 갈래 만들기 · 409 는 폴더 이름 칸 오류, 본편으로 · 끊기, 비교 받기), `BranchDraft`(만들기 칸: 폴더 이름이 갈래 이름을 따라감, 칸 검사), `BranchText`(웹 `branches.js` 문구 · 규칙), `LiveBranchService`, 작품 머리 띠 `BranchStrip`, 사이드바 줄 `BranchSideTag`, 작품 홈 카드 `BranchHomeCard`, 만들기 칸 `BranchFormView`, `BranchCompareScreen`. 복사 · 되돌리기 · 비교 계산은 서버 `branches.py` 가 한다 |
| `CanonAppUI` | `AppModel`(서버 · 작품 · 화면 · 작업 · 연 작품 · 갈래 집안), `RootView`, 저장 띠 `SaveBar`, 서버 주소 화면 |

## 개발 명령

```bash
# 서버 API 를 바꾼 뒤 (web.py 의 엔드포인트, 응답 모델): 앱이 쓰는 명세를 다시 만든다
python scripts/make_openapi.py

# Linux: Docker 로 순수 Swift 모듈 빌드 · 시험 (SwiftUI 화면은 빠진다)
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/swift":/src -w /src swift:6.3.3-noble swift test

# 실제 서버에 붙어 보기 (서버를 먼저 띄운다)
docker run --rm --network host -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/swift":/src -w /src swift:6.3.3-noble swift run canon-probe http://127.0.0.1:8000
```

저장과 409 충돌까지 보려면 시험 서버에서 `--save <작품>` 을 붙인다 (그 작품을 바꾸지 않고 두 번 저장한다). `--job <작품> <kind> [화]` 는 작업을 시작해 끝날 때까지 보고 결과와 검토 대기를 보인다 (mock 서버에서). `canon-probe` 는 작품마다 저장 왕복(받은 JSON 을 생성 타입으로 읽고 다시 써서 빠지는 칸이 있는지)도 본다.

Mac (Xcode 16 이상):

```bash
cd swift && swift test                       # 모듈 시험 (SwiftUI 화면까지 빌드된다)
brew install xcodegen && cd swift/App && xcodegen && open Canon.xcodeproj
```

Xcode 에서 `Canon` 스킴을 고르고 대상(My Mac, iPad 시뮬레이터)을 바꿔 실행한다. 앱의 '서버' 버튼으로 서버 주소를 적는다.
번들 id(`dev.c10.canon`)와 서명 팀은 `App/project.yml` 에서 고친다. xcodegen 이 만드는 `Canon.xcodeproj`, `Info.plist`, `Canon.entitlements` 는 커밋하지 않는다 (`.gitignore`).

### TestFlight (iPhone · iPad)

1. App Store Connect 에서 번들 id `dev.c10.canon` 으로 앱을 만든다.
2. `App/project.yml` 의 `CURRENT_PROJECT_VERSION` 을 지난번 올린 수보다 크게 한다 (또는 xcodebuild 에 `CURRENT_PROJECT_VERSION=<수>` 를 붙인다).
3. Xcode 에서 실행 대상을 Any iOS Device 로 두고 Product → Archive → Distribute App → TestFlight.

준비된 것: 임시 앱 아이콘(`App/CanonApp/Assets.xcassets`, 진짜 아이콘이 생기면 `AppIcon.appiconset` 의 PNG 를 바꾼다), 수출 규정 질문을 건너뛰는 `ITSAppUsesNonExemptEncryption: false`(HTTPS 말고 다른 암호화를 쓰지 않는다), iOS 빌드에서 뺀 macOS 권한(앱 샌드박스).
테스터는 아이폰에도 Tailscale 을 켜고 서버의 `https://…ts.net:8446` 주소를 적는다. 외부 테스터는 Apple 의 베타 심사를 거치는데 심사자가 Tailscale 서버에 붙지 못하므로, 내부 테스터(App Store Connect 팀원)로 시작한다.

`python -m unittest` 의 `tests/test_openapi.py` 가 `openapi.json` 이 지금 서버와 같은지 본다. web.py 를 고치고 명세를 다시 만들지 않으면 실패한다.

## 서버 계약 (앱이 지킬 것)

웹 화면(`app.js` 와 화면별 파일)이 지키는 약속이다. 앱도 같게 한다.

1. **화면 id 헤더.** 모든 요청에 `X-Canon-Client: <실행마다 새 id>` 를 붙인다 (`CanonServer` 가 붙인다).
   서버는 작품을 마지막으로 저장한 화면을 기억한다.
2. **작품 저장 충돌.** `PUT /api/projects/{name}` 은 다른 화면이 먼저 저장했으면(`edit_rev` 가 더 크고 `saved_by` 가 다르면) 409 를 돌려준다.
   앱은 '다시 불러오기'와 '내 변경으로 덮기(`?force=true`)'를 고르게 한다. 덮기는 사용자가 고를 때만 한다.
3. **작품 전체는 판(ETag)으로.** `GET /api/projects/{name}` 은 `If-None-Match` 가 같으면 304 를 돌려준다 (`ProjectLoader`). 장편은 수 MB 라 꼭 쓴다.
4. **오래 걸리는 AI 작업은 작업 목록으로.** `POST /api/projects/{name}/jobs` 로 시작하고 `GET /api/jobs` 를 진행 중엔 1.5초, 연결이 끊기면 4초마다 다시 묻는다 (`JobTracker.pollInterval`).
   작업이 맡은 화(`pending`)는 그 화를 잠근다. 작품 전체를 저장할 때 받아 간 단계를 `?merged=<작업 id>:<done>,...` 로 알린다 (웹 `S.jobsMerged`). 멈추기는 `POST /api/jobs/{id}/stop`.
5. **AI 결과는 제안이다.** 끝난 작업의 결과는 서버 `pending.json` 에 남는다 (`GET /api/projects/{name}/pending`).
   앱은 결과를 보여 주고, 사용자가 고른 것만 `.../apply` 로 보낸다. 상태 변경안의 '반영'은 상태 승인 화면에서만 한다.
6. **연산 이름은 Python 함수 이름이다** (`web.py` 의 `generate_unique_id_function`). Swift 에서는 낙타 표기로 바뀐다 (`list_projects` → `listProjects`).
7. **타입이 없는 응답.** 2026-10-26 기준 연산 151개 중 73개가 dict(또는 dict 목록)를 돌려줘 타입이 없다 (생성 타입이 `OpenAPIObjectContainer`).
   3개는 응답 모양이 아예 없다: 작품 전체 GET, `export.txt`, 지도 그림. 화면을 옮길 때 그 화면이 쓰는 응답에 pydantic 모델을 단다.
   예: `list_projects` 의 `ProjectCard`. 작품 전체 GET 처럼 본문이 큰 응답은 `ProjectLoader` 처럼 직접 받아 생성 타입으로 읽는다.
8. **인증이 없다.** 서버는 127.0.0.1 에 열고 Tailscale 이 막는다. Tailscale 밖의 기기는 붙지 못한다. 앱에 로그인을 만들지 않는다.

## 화면 옮기는 순서

화면 하나가 모듈 하나다. 웹 파일과 서버 쪽을 함께 본다. 위에서부터 옮긴다 (쓰는 흐름 순).

| 순서 | 모듈 | 화면 (사이드바 이름) | 웹 파일 | 서버 |
|---|---|---|---|---|
| 1 | `FeatureProjects` | 작품 목록 | `home.js` `viewProjects` | `list_projects` — **됨** |
| 2 | `FeatureHome`, `CanonStore` | 작품 홈, 작품 저장(409 · merged) | `home.js` `viewHome`, `app.js` `save` | `get_project`, `put_project` — **됨** (남음: 홈의 자동 집필 줄 · 관계 카드 · 장편 전환 단추 · 화 진행 막대 · 연재 일정) |
| 3 | `FeatureCheck` | 검수 (회차 띠, 지적 목록 · 상세, 처리 상태 · 메모, 문체 지표) | `check.js` | `set_finding`, `episode_style`, 작업 `check` — **일부 됨**. 남음: 검수 화면 본문의 부분 수정 도구(지금은 '집필에서 고치기'), 초반 점검 탭(흡입력 판정, `opening.js` `openingChecks`), 넓혀 찾기 켜기 · 끄기 |
| 3 | `FeatureWrite` | 집필 (부분 수정, 다시 생성, 문체 표시, 복사, 삽화) | `passage.js` `rewrite.js` `marks.js` `publish.js` `illust.js` `opening.js` `restate.js` | `put_text`, `rewrite_info`, `export_text` 등 — **일부 됨**: 본문 보기 · 고치기, 쓰기, 다시 생성, 복사 · 내보내기. 남음: 부분 수정 `passage.js`, 문체 표시 `marks.js`, 삽화 `illust.js`, 초반 1~3화 `opening.js`, 반영 뒤 고친 화 `restate.js`, AI 대화 패널, 작업지시서 방식, 컨텍스트 블록 보기 |
| 4 | `FeatureReview` | 상태 승인 (변경안 만들기 · 고르기 · 고치기 · 반영, 관계 미리 보기, 상태창 줄, 복선 문장, 반영 뒤 고친 화 다시 맞추기, 반영 취소) | `review.js` `restate.js` `statwin.js`(`swDeltaRows`) `foreshadow.js`(`fsClueRows`) | 작업 `state`, `apply_state`, `apply_restate`, `keep_state`, `revert`, `preview`(`RelationPreview`) — **됨**. 채팅 앱 JSON 은 작업지시서 화면이, 자동 집필 변경안은 자동 집필 화면(`auto/review`)이 검토 대기로 넘긴다 |
| 5 | `FeaturePlot` | 기승전결 · 플롯 / 부 · 아크 · 플롯, AI 대화 | `plot.js` `chat.js` `insert.js` `convert.js` | `plots`, `chat`, `series`, `arcs` — **됨** (`viewArc` · `viewSerial` · `insert.js`, 응답 `Renumbered` · 본문 `Recap`). 남음: AI 대화 `chat.js`, 단편 → 장편 전환 `convert.js`, 여는 방식 `opening.js`, 화별 시점 칸 `povField`, 새 인물 만들기 · 등록(`castQuickEdit`), 새 장소 후보 안내(`placeCandNotes`), 자동 집필 중인 화 잠금(`autoEp`) |
| 6 | `FeatureSetup`, `FeatureStyle` | 설정 도우미, 문체 레퍼런스 | `setup.js` `style.js` `mystyle.js` | `suggest`, `names`, `relation_views`, `style`, `styles` — **됨** (남음: 인물 서술 말투 `voiceField`, 삽화 외형 태그 `visualFields`, 이름 칸으로 가기 단추, '내 수정에서 배우기' 카드, 문체 라이브러리 화면 · 버전 목록) |
| 7 | `FeatureCast` | 인물 · 관계도 (관계도 재생, 인물 · 두 사람 상세, 추이 그래프, 등장표) | `cast.js` | `cast_view`(`CastView`) — **됨**. 수치 직접 보정(`adjust_tie`)과 말로 · 숫자로 저장(`PUT .../view`), 인물 카드 탭(`castSheet`)은 아직 웹에서 |
| 7 | `FeatureForeshadow` | 복선 센터 | `foreshadow.js` | `foreshadow_*` — **됨** (본문에서 문장 골라 걸기는 3, `fsClueRows` 는 4에서) |
| 7 | `FeatureStatWin` | 상태창 수치 (항목 고치기, 틀, 복사, 서식, 화별 변화 표) | `statwin.js` (`swDeltaRows` 는 4 상태 승인) | `statwin_view`(`StatwinView`), `statwin_set`, `statwin_template` — **됨** |
| 7 | `FeatureAuto` | 자동 집필 (실행 상태 · 진행 로그, 시작 · 일시정지 · 이어 가기 · 중지, 승인 정책, 비용 · 시간 추정, 배치, 검토 대기 화, 검토 없이 반영한 화) | `auto.js` | `auto_*`(`AutoView` · `AutoEstimate`), 검토 대기 변경안을 상태 승인 결과로 두기 `auto_review` — **됨**. 남음: 시작 전 집필 화면의 저장하지 않은 본문 초안 저장(`autoFlushDrafts`), 집필 · 플롯 · 홈 화면의 잠금 안내(`autoLockNote` · `autoEp`, 상태 승인은 됨), 홈의 자동 집필 줄, 오류 안내의 '모델 · API 키 설정' 단추 |
| 7 | `FeatureLines` | 이야기 줄기 (노선도, 줄기 목록 · 편집, 화 붙이기, AI 제안) | `lines.js` | 작업 `storyline`, `apply_storyline`, `remove_storyline` — **됨**. 플롯 편집기의 줄기 칸 `lineField` · 화 카드 `lineBadge` 는 `LineField` · `LineBadges` 이고, `CanonAppUI` 가 `PlotSlots`(환경 값 `plotSlots`)로 `FeaturePlot` 에 끼운다. 화 점을 누르면 플롯 화면으로만 옮기고 그 화를 열지는 않음 |
| 7 | `FeatureCausal` | 인과율 (요소, 관련 화 지도, 영향 분석) | `causal.js` | `element_links`(`ElementLink`), 작업 `impact`, `impact_apply` · `impact_dismiss` · `impact_reopen` — **됨**. 지도 칸에서 그 화로 바로 가기는 화면만 옮긴다 (화를 고르지 않음) |
| 7 | `FeatureBrief` | 작업지시서 (API 없이) | `write.js` `viewBrief` | `brief`(`BriefText`), `put_text`, `parse_state`, `import_check`(검수 지시서 탭, 받은 JSON 을 회차 하나로) — **됨**. 받은 JSON 은 서버가 검사하고, `CanonAppUI` 가 `BriefView` 의 `handOff` 로 `JobCenter.offer` 에 놓아 상태 승인 화면의 검토 대기(`state:<화>`)가 된다 (웹 `setDelta(n, d, 'chat')`, 화면 메모리에만) |
| 7 | `FeatureBranches` | 갈래 비교 (작품 머리 띠, 사이드바 갈래 줄, 작품 목록 묶기, 작품 홈 갈래 카드, 갈래 만들기, 비교) | `branches.js`, `home.js` `viewProjects`, `app.js` `sidebar` | `branch_family` · `make_branch` · `compare_branches` · `promote_branch` · `detach_branch`(`BranchFamily` · `BranchMember` · `BranchDiff`) — **됨**. 웹은 갈래가 없으면 사이드바의 '갈래 비교'를 '더 보기'로 접지만 앱은 다른 도구처럼 늘 보인다. 비교 화면의 '집필로'는 그 화를 고르지 않고 화면만 옮긴다 |
| 7 | 작품 도구 (남은 것) | 스킬 도감 | `abilities.js` | `abilities_view`(`AbilitiesView`), `abilities_lookup`, `abilities_save`, `abilities_delete` |
| 7 | 작품 도구 (남은 것) | 지도 | `atlas.js` | `atlas` 엔드포인트 (지도 생성기는 다른 세션이 고치는 중) |
| 8 | `FeatureUsage` | 사용량 · 비용 | `usage.js` | `usage_summary` · `usage_prices` — **됨** |
| 8 | `FeatureSettings` | 모델 · API 키 설정 (사이드바 칸이 아니라 툴바 시트) | `settings.js` `viewSettings` `claude.js` `vertex.js` | `config` · `put_config`(`ConfigView`, 본문 `SettingsIn`), `test_config`(`ConfigTest`), `config_models`(`ModelList`), `config_health`(`ConfigHealth`), `claude_status`(`ClaudeStatus`) — **됨** (가격표 칸은 사용량 화면에서) |
| 8 | 본편과 분리 (남은 것) | 연구 | | `research` |

새 화면 모듈을 만들 때:

1. `Package.swift` 에 `.target(name: "FeatureX", dependencies: ["CanonCore", "CanonAPI", "CanonUI"])` 와 시험 모듈을 더한다.
2. 그 화면이 쓰는 dict 응답에 pydantic 응답 모델을 달고 `python scripts/make_openapi.py` 를 돌린다.
3. Model 을 쓴다. 서버 호출은 프로토콜 뒤에 두고, 웹 화면의 문구 규칙은 웹과 같은 문구로 시험한다.
4. View 를 `#if canImport(SwiftUI)` 안에 쓴다. 화면 문구는 웹과 같은 해요체다.
5. `CanonAppUI` 의 `RootView.screen(_:project:)` 에 `case` 한 줄을 더해 그 화면을 잇는다. 모듈은 `CanonAppUI` 의존에 더한다.
6. Linux Docker 시험과 `canon-probe` 를 돌리고, Mac 에서 화면을 본다.

## AI 작업을 쓰는 화면

`AppModel.jobs`(`JobCenter`) 하나를 함께 쓴다. 웹 `startJob` · `pollJobs` · `finishJob` 와 같다.

1. 시작: `await jobs.start(JobRequest(kind: "write", ep: 3))`. 저장하지 않은 변경이 있으면 먼저 묻고(화면), `start` 가 저장한다. 버튼 글자는 `jobs.busyLabel(kind, ep:)`, 막을지는 그 값이 있는지로 본다.
2. 작업이 작품에 쓰는 것(본문, 플롯, 검수, 자동 집필)은 `JobCenter` 가 `ProjectDocument.merge` 로 그 화만 받아 온다. 화면이 따로 받지 않는다.
3. 검토할 제안(`JobText.pendingKinds`)은 `jobs.results[Job.key(kind, ep)]` 에 남는다. `result.result.decode(Components.Schemas.StateDelta.self)` 처럼 생성 타입으로 읽는다. 생성 타입이 없으면 그 작업 결과 모델을 서버 응답 모델로 명세에 드러낸다.
4. 사용자가 고른 것만 적용하고(설계 원칙: AI 출력은 제안), 적용하거나 버리면 `await jobs.drop(kind, ep:)` 로 서버의 `pending.json` 에서도 지운다.
5. 실패는 `jobs.failures[key]` 에 남는다. 화면은 '다시 시도'와 '닫기'(`dismissFailure`)를 보인다.

## 웹과 같은 규칙 (함께 고친다)

앱에 옮긴 표시 규칙은 웹 화면과 같아야 한다. 웹을 고치면 여기도 고친다.

| Swift | 웹 (`canon/static/*.js`) |
|---|---|
| `CanonError.from` | `fmtErr` |
| `KoreanText.josa` · `episodeRange` · `date` · `dateTime` | `josa` · `epRange` · `fmtDate` · `fmtDateTime` |
| `EpisodeStatus` | `STATUS`, `projectNext` 의 대기 문구 |
| `Screen` | `sidebar` 의 `items` · `tools` |
| `JobTracker` · `JobText` | `pollJobs` · `finishJob` · `JOB_DONE_MSG` · `PENDING_KINDS`(서버 `web.PENDING_KINDS`) |
| `JobCenter` · `ProjectDocument.merge` | `startJob` · `pollJobs` 의 화 받아 오기 · `mergeEpisodes` · `loadPending` · `jobFor` · `jobOwns` · `jobBtn`, `offer` 는 `setDelta(n, d, 'chat')` |
| `ProjectCardText` | `viewProjects` · `projectNext` |
| `ProjectGroup.make`, `ProjectCardText.summary(_:branches:)` · `branchTitle` · `branchDetail` · `folder` | `branches.js` `branchGroups`, `home.js` `viewProjects` 의 `branchRow` (시험 기대값은 node 로 돌린 웹 결과) |
| `BranchText.name` · `sideTag` · `strip` · `homeRows` · `promoteQuestion` · `detachQuestion` | `branches.js` `branchName` · `branchSideTag` · `branchStrip` · `branchHomeCard` · `branchPromote` · `branchDetach` |
| `BranchText.folderOf` · `folderBad` · `folder` · `lastFinal` · `formDesc` · `formNote`, `BranchDraft` | `home.js` `folderOf` · `FOLDER_BAD`, `branches.js` `branchFolder` · `lastFinal` · `branchFormCard` · `syncBranchForm` · `branchCreate` (시험 기대값은 node 로 돌린 웹 결과) |
| `BranchText.pick` · `headline` · `episodeRows` · `episodeNote` · `notReady` · `diffRows` | `branches.js` `branchCompareLoad` · `viewBranches` · `BC_KIND` |
| `HomeSummary` | `viewHome` · `nextStep` · `currentEp` · `actGroups` |
| `SaveText` · `ProjectDocument.edited` | `save()` 의 토스트와 `edited` |
| `StatWinText.pick` · `outgoing` · `presetLabel`, `StatCell` | `statwin.js` `swLoad` · `swSave` · `swEditor` · `swTimeline` |
| `WarmthBand` (경계 -0.6 · -0.2 · 0.2 · 0.6, 값이 경계보다 작으면 그 구간) | `cast.js` `WARMTH_BANDS`, 서버 `dynamics.warmth_word` |
| `CastText`, `CastText.fixed`(JS `toFixed` 반올림) | `cast.js` `tieText` · `tensionText` · `frameLabel` · `castTimeline` · `castChart` 범위, `review.js` `GOOD_EVENTS` · `INTENSITY` |
| `CastLayout.force` · `curve` | `cast.js` `castForce` · 간선 곡선 |
| `ReviewText.defaultPicks` · `picked` · `total` · `applyReasons` | `review.js` `setDelta` · `pickedDelta` · `viewReview` 의 `total` · `applyDelta` 의 묻는 말 |
| `ReviewText.stateRows` · `newKnows` · `unknown` · `relation` · `name` · `secret` · `goodEvents` · `intensity` | `viewReview` 의 인물 · 관계 줄, `charName` · `secretLabel` · `GOOD_EVENTS` · `INTENSITY` |
| `ReviewText.relationLines` (`pair`) | `relationLines` |
| `ReviewText.statRows` · `resolve` | `statwin.js` `swDeltaRows` · `swResolve` (서버 `statwin.resolve`, 시험은 `tests/test_statwin.py` 의 `RESOLVE_CASES` 와 같은 사례. 반영은 서버가 다시 계산한다) |
| `ReviewText.clueRows` | `foreshadow.js` `fsClueRows` |
| `ReviewText` 의 k · o · t 고르기, `settingLabel` · `settingValue` · `timeText` · `deadlineDay` | `timeline.js` `tlDeltaCard`, `charlog.js` `scDeltaCard` · `SC_LABELS`(서버 `charlog.LOG_FIELDS`). 인물 설정 바꾸기(t)는 기본으로 고르지 않는다 |
| `ReviewText.editedAfterFinal` · `laterWritten` · `restateItems` · `restatePicks` · `restateBody` · `restateSkipped` · `restateDone` | `restate.js` `editedAfterFinal`(서버 `pipeline.edited_after_final`) · `laterWritten` · `rsItems` · `rsPicks` · `applyRestate` · `restateCard` |
| `ReviewText.rangeText` · `revertQuestion` · `revertDone` | `rangeText` · `revertFrom` |
| `WriteText` (`blockedBefore` · `orderNote` · `unsaved` · `when`), `WriteModel` 의 본문 초안 | `write.js` `blockedBefore` · `orderNote` · `viewWrite`, `app.js` `textUnsaved`, `passage.js` `editableEp` · `clip` · `editTime` · `flushText` |
| `CheckState` (`CanonStore`, `Episode.checkState`) | `home.js` `checkState` (진행 막대 검수 칸, 다음 할 일, 집필 · 상태 승인 · 자동 집필 · 작업지시서의 열린 지적) |
| `CheckText` (`Status` · `Filter` · `Flag` · `flag` · `marks` · `selected` · `source` · `round` · `checkLabel` · `reviewLabel` · `when`) | `check.js` `FINDING_STATUS` · `FINDING_FLAG` · `findingFlag` · `findingMarks` · `chkSelected` · `srcLabel` · `chkStrip` · `viewCheck` (시험 기대값은 `tests/test_check_js.py` 와 같은 세션) |
| `TextDiff.lines` · `words` · `tokens`, `RewriteDraft` · `RewriteText` | `rewrite.js` `textDiff` · `rwSimilar` · `rwReq` · `rwReqLabel` · `RW_MODES` · `RW_KIND`, `passage.js` `wordDiff` · `tokens` (시험 기대값은 node 로 돌린 웹 결과) |
| `PublishText` | `publish.js` `copyRangeOf` · `copyEpisodes` · `downloadTxt` 문구 (다듬기 규칙은 서버 `publish.py`) |
| `PlotRules.actRanges` · `setArcEnd` | `actRanges` · `fitActs` (서버 `pipeline.act_ranges` · `fit_arc`, 시험은 서버 값과 같은 사례) |
| `PlotRules.coverage` · `rangeText` · `needsDraft` · `redraftQuestion` · `writeNext` | `actCoverage` · `rangeText` · `needsDraft` · `confirmRedraft` · `writeNextBtn` |
| `PlotRules.pendingRecaps` · `arcChip` · `rail` · `lostPartSummaries` · `progress` | `viewSerial` 의 요약 안내 · `arcChip` · `railChips` · `lostPartSummaries` · `arcProgress` (서버 `pipeline.pending_recaps`) |
| `PlotRules.lastFixed` · `insertSlots` · `insertNote` | `insert.js` `lastFixed` · `insertBlock` · `insertForm` (서버 `renumber.last_fixed`) |
| `PlotBoard`, `PlotEditorInfo`, `EpisodeCard` | `actBoard`, `plotEditor` · `payoffPicker` · `castField`, `epCard` |
| `PlotModel.syncResults` · `start` | `applyJobResult` · `loadPending`(되살린 결과는 고른 아크를 옮기지 않음) · `startJob`(저장하지 않은 변경을 먼저 묻기) |
| `Logline` · `LoglineField` · `Tone` · `ToneDial` | `composeLogline` · `loglineChecks` · `updateLogline` · `toneText` · `setDial` · `LOGLINE_SLOTS` · `TONE_WORDS`, 서버 `canon/logline.py` (셋을 함께 고친다. 시험은 `tests/test_logline.py` 와 같은 사례, `test_logline.py` 가 Swift 톤 말도 본다) |
| `SetupWizard` (`steps` · `required` · `reqs` · `firstGap` · `stepState` · `worldKinds` · `eras` · `worldRec` · `worldKind(of:)` · `withWorldKind` · `worldRecs` · `summary` · `roles`), `SetupModel.openMode` · `setMode` · `go(step:)` | `setup.js` `WIZ_STEPS` · `WIZ_REQ` · `setupReqs` · `wizFirstGap` · `wizStepState` · `WORLD_KINDS` · `ERAS` · `WORLD_REC` · `worldKindOf` · `withWorldKind` · `worldRecs` · `wizFinish` · `WIZ_ROLES`, `setupMode` · `wizState` · `wizGo` (시험 기대값은 `tests/test_setup_wizard_js.py` 와 같은 사례) |
| `SetupRules`, `SuggestionPicks`, `NameCheckGroups` | `addCharacter` · `removeCharacter` · `addRelationship` · `relProblem` · `conflictWord` · `REL_TYPES` · `CONFLICTS` · `TIERS` · `genreLabel` · `loglineExamples` · `rangeText`, `viewSuggestion` · `sameChar` · `sugEnd` · `SUG_FIELDS` · `applySuggestion`, `nameCheckBox` |
| `AutoText.status` · `step` · `stepLine` · `shiftOptions` · `issueOptions` · `everyOptions` | `auto.js` `AUTO_STATUS` · `AUTO_STEP` · `AUTO_SHIFT` · `autoRunCard` 의 `step` · `autoPolicyForm` |
| `AutoText.duration` · `cost` · `number` · `rangeText` | `auto.js` `autoDuration` · `autoCost`, `toLocaleString`, `app.js` `rangeText` (시험 기대값은 node 로 돌린 웹 결과) |
| `AutoText.defaults` · `estimateLine` · `estimateTime` · `estimateWarnings` · `estimateNotes` · `startQuestion` · `nothingLeft` | `autoDefaults`(기본 정책은 웹은 화면에, 앱은 서버 `policy_defaults`) · `autoEstCard` · `autoStart` · `viewAuto` 의 `nothingLeft` |
| `AutoText.progressLine` · `needsSettings` · `reviewDone` · `pendingStale` · `haltLink` · `runPolicyNote` · `paused` · `signature` · 알림 문구, `AutoModel.refresh` | `autoRunCard` · `pendingStale` · `autoHaltLinks` · `autoRunPolicy` · `actions.auto*` · `autoPoll` |
| `AutoText.styleWarnings` · `revertQuestion` · `revertDone` · `logTime` · `logTokens` | `autoAppliedCard` · `revertFrom`(`ReviewText.revertQuestion` 과 같은 말) · `autoLogCard` |
| `LineRules` (`episodes` · `span` · `isPast` · `newID` · `tag` · `untag` · `parseEpisodes` · `rangeNotes` · `badges` · `fieldOptions`), `LineMapLayout` | `lines.js` `lineEpisodes` · `lineSpan` · `linePast` · `newLineId` · `tagEp` · `lineUntag` · `parseEps` · `lineRangeNote` · `lineBadge` · `lineField` · `lineMap` (서버 `storylines.episodes_of` · `span` · `past` · `new_id` · `tag`. 시험 기대값은 node 로 돌린 웹 결과와 `tests/test_storylines.py` 사례) |
| `CausalText.basis` · `stale` | `causal.js` `elBasis` · `causalStale` (서버 `elements.basis`. 시험 기대값은 node `JSON.stringify` 와 python `json.dumps` 로 돌린 결과, 따옴표 · 줄바꿈 · 조종 문자 · 이모지 사례) |
| `CausalText.badge` · `timing` · `strip` · `snippets` · `defaultPicks` · `picked` · `appliedLabel` · `since` · `newID` | `causal.js` `impactBadge` · `timingText` · `causalStrip` · `initCausalPicks` · `causalApply` · `appliedLabel` · `causalSince` · `newElementId` (서버 `elements.new_id`) |
| `CausalText.plotDiff` | `chat.js` `plotDiff` · `diffField` · `PLOT_FIELDS` |
| `CausalModel.mergeImpacts` | `causal.js` `mergeImpacts` (저장하지 않은 요소 편집은 두고 분석만 받기) |
| `BriefText` (`defaultKind`(검수가 끝나기 전에는 검수 지시서) · `mergedCheck` · `count` · `orderNote` · `filename`) | `write.js` `briefTabFor` · `importCount` · `blockedBefore` · `orderNote` · `downloadBrief` · `copyBrief` · `importText` · `importJson` 문구 |
| `StyleText` | `styleBlank`(서버 `library.blank`) · `styleChangeWho` · `styleLibraryCard` · `baselineRows`, `analyzeStyle` · `useLibStyle` · `keepStyle` · `pushStyle` · `pullStyle` 의 묻는 말 |
| `SettingsText` (`providers` · `stages` · `stageParent` · `followLabel` · `stageModelHint` · `stageEnvLines` · `localOpen` · `stageOpen` · `claudeOpen` · `modelOptions` · `modelStatus` · `aiWarning` · `claudeCard` · 키 칩), `SettingsDraft.body` | `settings.js` `providerOptions` · `STAGES` · `STAGE_PARENT`(서버 `settings.STAGE_PARENT`) · `STAGE_PARENT_LABEL` · `stageModelHint` · `viewSettings` · `modelDatalist` · `KNOWN_MODELS` · `modelStatus` · `saveSettings`(환경 변수 · 기본값을 보이기만 한 칸은 보내지 않음), `home.js` `aiWarning`, `vertex.js` `geminiAuthSettings` · `geminiAuthBody` · `VERTEX_SRC`, `claude.js` `claudeStatusView` · `claudeSettings` · `claudeSettingsBody` |

## 알려진 한계

- SwiftUI 화면은 Mac 에서만 빌드된다. Linux 에서는 Model 과 시험만 확인한다.
- `swift test` 는 macOS 로만 빌드한다. iOS 에만 없는 API 는 iOS 대상 빌드에서만 드러난다. 예: iOS 의 `List(selection:)` 은 옵셔널 선택만 받는다. 화면을 고치면 iPad 시뮬레이터로도 빌드한다.
- 서버 주소에 하위 경로(`https://host/canon`)를 쓰면 `ProjectLoader` · `CanonServer.get` 이 경로를 잃는다. 지금 서버는 루트에 연다.
- `openapi.json` 은 설치된 FastAPI · pydantic 판에 따라 글이 조금 달라질 수 있다 (`requirements.txt` 는 가장 낮은 판만 정한다). 다른 기기에서 `tests/test_openapi.py` 가 코드 변경 없이 실패하면 그 기기에서 명세를 다시 만들고 차이를 본다. 2026-10-26 명세는 FastAPI 0.159.1, pydantic 2.14.1 로 만들었다.
- 서버의 `str | None` 같은 칸은 명세에서 `anyOf` 의 `null` 을 빼고 옵셔널로 둔다 (`scripts/make_openapi.py` 의 `drop_null`, 68곳). 생성기는 `null` 을 읽지 못해 그대로 두면 그 칸을 생성 타입에서 빼고, 앱이 작품을 저장할 때 그 칸이 지워진다. 서버의 `null` 은 `nil` 로 읽히고, `nil` 은 칸을 빼고 보내 서버 기본값이 된다.
