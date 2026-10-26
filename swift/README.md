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
2. `Feature*` 끼리는 서로 기대지 않는다. 화면을 잇는 일은 `CanonAppUI` 가 한다. 작품 전체를 함께 쓰는 화면은 `CanonStore.ProjectDocument` 하나를 받는다 (`AppModel.document`).
3. Model 은 SwiftUI 를 가져오지 않는다. 서버는 프로토콜(예: `ProjectListing`) 뒤에 두고 시험에서 가짜로 바꾼다.
4. View 파일은 `#if canImport(SwiftUI)` 로 감싼다. 그래서 Model 과 시험은 Linux 에서도 빌드된다.
5. 서버 타입을 손으로 다시 정의하지 않는다. `Components.Schemas.*` (생성된 타입)를 쓴다.
   서버가 dict 를 돌려줘 타입이 없으면, 서버에 pydantic 응답 모델을 단다 (아래 '서버 계약' 5).

| 모듈 | 들어 있는 것 |
|---|---|
| `CanonCore` | `ServerConfig`, `ClientIdentity`, `CanonError`(웹 `fmtErr` 와 같은 문구), `APIPath`(작품 이름 인코딩), `Job` · `JobRequest` · `JobTracker` · `JobText`(웹 `pollJobs`, `JOB_DONE_MSG`), `PendingList`, `JSONValue`(모양을 모르는 작업 결과), `KoreanText`(조사, 'a~b화', 날짜), `EpisodeStatus`, `Screen`(사이드바) |
| `CanonAPI` | 생성된 `Client`(빌드 때 `openapi.json` 에서), `CanonServer`(헤더, 오류 바꾸기, 타입 없는 GET), `ProjectLoader`(작품 전체를 ETag 로) |
| `CanonUI` | `Notice`, `NotPortedYet`, 입력 칸 `LabeledText` · `ListField`(한 줄에 하나씩) · `ChipRow` · `Flow`(줄바꿈 배치) |
| `CanonStore` | `ProjectDocument`(연 작품: 받기, `edit`, 고친 표시, `save` 의 409 충돌 · 덮기, 서버가 지킨 칸 알림, 작업이 쓴 화만 받기 `merge`), `JobCenter`(작업 시작 · 멈추기 · 지켜보기, 검토를 기다리는 결과 `results` 와 실패 `failures`), `ProjectStoring` · `JobServing` |
| `FeatureProjects` | 작품 목록: `ProjectsModel`, `ProjectCardText`(웹 `projectNext`), `LiveProjectListing`, `ProjectsView` |
| `FeatureHome` | 작품 홈: `HomeSummary`(웹 `viewHome` · `nextStep` · `currentEp`), `HomeView` |
| `FeatureStatWin` | 상태창 수치: `StatWinModel`, `StatWinText`(웹 `swResolve` 등), `StatCell`(비교표 칸), `LiveStatWin`, `StatWinScreen` |
| `FeatureForeshadow` | 복선 센터: `ForeshadowModel`, `ForeshadowChange`(고치기 · 걸린 문장 지우기 · 정리), `ForeshadowText`(웹 `fsItem` · `fsShown`), `ForeshadowTrack`(웹 `fsTrack`), `LiveForeshadowService`, `ForeshadowView` |
| `FeatureUsage` | 사용량 · 비용: `UsageModel`(기간 · 작품 거르기, 가격표 고치기 · 되돌리기), `UsageText` · `UsageChart`(웹 `usage.js` 문구 · 막대), `LiveUsageSource`, `UsageView` |
| `FeatureCast` | 인물 · 관계도: `CastModel`(시점 재생, 고르기, 배치), `CastText`(웹 `cast.js` 문구), `WarmthBand`, `CastLayout`(힘 배치 · 선 모양), `CastHit`, `LiveCastSource`(작품 전체 + `cast_view`), `DefaultsLayoutStore`, `CastScreen` |
| `FeatureReview` | 상태 승인: `ReviewModel`(작업 결과 `state:<화>` 읽기, 고르기 · 고치기, 반영 · 다시 맞추기 · 그대로 두기 · 반영 취소, 관계 미리 보기), `ReviewText`(웹 `setDelta` · `pickedDelta` · `relationLines` · `swDeltaRows` · `fsClueRows` · `restate.js`), `LiveReviewService`, `ReviewView` |
| `FeatureWrite` | 집필: `WriteModel`(화 고르기, 본문 초안과 '본문 저장', 쓰기 · 검수 작업, 다시 생성, 복사 · 내보내기), `WriteText` · `RewriteText` · `PublishText`(웹 문구), `RewriteDraft`, `TextDiff`(새 판 비교), `LiveWriteService`, `WriteView` |
| `FeaturePlot` | 기승전결 · 플롯 (장편은 부 · 아크 · 플롯): `PlotModel`(구간 · 화 · 아크 · 부 고치기, 확정, 작업 결과를 제안으로 받기 · 적용 · 버리기, 화 끼워 넣기 · 빼기), `PlotRules`(웹 `actRanges` · `fitActs` · `actCoverage` 등), `PlotBoard` · `PlotEditorInfo` · `EpisodeCard`(보드 · 편집기 · 화 카드), `LivePlotService`, `PlotScreen` |
| `FeatureSetup` | 설정 도우미: `SetupModel`(작품 정보 · 인물 · 관계 고치기, 이름 후보 · 점검, AI 설정 제안 고르기), `Logline` · `LoglineField` · `Tone` · `ToneDial`(로그라인 합치기 · 점검, 톤 다이얼), `SetupRules`(새 인물 id, 관계 쌍 · 문제, 장르, 지우기 질문), `SuggestionPicks`, `NameCheckGroups`, `LiveSetupService`, `SetupView` |
| `FeatureStyle` | 문체 레퍼런스: `StyleModel`(원문 분석, 라이브러리 고르기 · 저장 · 올리기 · 가져오기, 프로필 · 표지 · 장치 · 대표 문단 고치기), `StyleText`(웹 `styleBlank` · `styleChangeWho` · `baselineRows` 문구), `LiveStyleService`, `StyleView` |
| `FeatureAuto` | 자동 집필: `AutoModel`(실행 상태 3초마다 묻기 · 연결 끊김, 시작 · 일시정지 · 이어 가기 · 중지, 새로 시작 칸 · 배치 끔/켬 추정, 멈춘 실행의 정책 고치기, 검토 대기 변경안을 상태 승인으로 보내기, 자동 반영한 화 반영 취소), `AutoText`(웹 `auto.js` 문구), `LiveAutoService`, `AutoScreen` · `PolicyForm` |
| `CanonAppUI` | `AppModel`(서버 · 작품 · 화면 · 작업 · 연 작품), `RootView`, 저장 띠 `SaveBar`, 서버 주소 화면 |

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

`python -m unittest` 의 `tests/test_openapi.py` 가 `openapi.json` 이 지금 서버와 같은지 본다. web.py 를 고치고 명세를 다시 만들지 않으면 실패한다.

## 서버 계약 (앱이 지킬 것)

웹 화면(`app.js`)이 지키는 약속이다. 앱도 같게 한다.

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
| 1 | `FeatureProjects` | 작품 목록 | `app.js` `viewProjects` | `list_projects` — **됨** |
| 2 | `FeatureHome`, `CanonStore` | 작품 홈, 작품 저장(409 · merged) | `app.js` `viewHome` `save` | `get_project`, `put_project` — **됨** (남음: 홈의 자동 집필 줄 · 관계 카드 · 장편 전환 단추) |
| 3 | `FeatureWrite` | 집필 (부분 수정, 다시 생성, 문체 표시, 복사, 삽화) | `passage.js` `rewrite.js` `marks.js` `publish.js` `illust.js` `opening.js` `restate.js` | `put_text`, `rewrite_info`, `export_text` 등 — **일부 됨**: 본문 보기 · 고치기, 쓰기 · 검수, 다시 생성, 복사 · 내보내기. 남음: 부분 수정 `passage.js`, 문체 표시 `marks.js`, 삽화 `illust.js`, 초반 1~3화 `opening.js`, 반영 뒤 고친 화 `restate.js`, AI 대화 패널, 작업지시서 방식, 컨텍스트 블록 보기 |
| 4 | `FeatureReview` | 상태 승인 (변경안 만들기 · 고르기 · 고치기 · 반영, 관계 미리 보기, 상태창 줄, 복선 문장, 반영 뒤 고친 화 다시 맞추기, 반영 취소) | `app.js` `restate.js` `statwin.js`(`swDeltaRows`) `foreshadow.js`(`fsClueRows`) | 작업 `state`, `apply_state`, `apply_restate`, `keep_state`, `revert`, `preview`(`RelationPreview`) — **됨**. 채팅 앱 JSON 가져오기(`state/parse`)와 자동 집필 변경안 불러오기는 아직 웹에서 |
| 5 | `FeaturePlot` | 기승전결 · 플롯 / 부 · 아크 · 플롯, AI 대화 | `app.js` `chat.js` `insert.js` `convert.js` | `plots`, `chat`, `series`, `arcs` — **됨** (`viewArc` · `viewSerial` · `insert.js`, 응답 `Renumbered` · 본문 `Recap`). 남음: AI 대화 `chat.js`, 줄기 칸 `lines.js` `lineField`, 단편 → 장편 전환 `convert.js`, 여는 방식 `opening.js`, 화별 시점 칸 `povField`, 새 인물 만들기 · 등록(`castQuickEdit`), 새 장소 후보 안내(`placeCandNotes`), 자동 집필 중인 화 잠금(`autoEp`) |
| 6 | `FeatureSetup`, `FeatureStyle` | 설정 도우미, 문체 레퍼런스 | `app.js` `mystyle.js` | `suggest`, `names`, `relation_views`, `style`, `styles` — **됨** (남음: 인물 서술 말투 `voiceField`, 삽화 외형 태그 `visualFields`, 이름 칸으로 가기 단추, '내 수정에서 배우기' 카드, 문체 라이브러리 화면 · 버전 목록) |
| 7 | `FeatureCast` | 인물 · 관계도 (관계도 재생, 인물 · 두 사람 상세, 추이 그래프, 등장표) | `cast.js` | `cast_view`(`CastView`) — **됨**. 수치 직접 보정(`adjust_tie`)과 말로 · 숫자로 저장(`PUT .../view`)은 아직 웹에서 |
| 7 | `FeatureForeshadow` | 복선 센터 | `foreshadow.js` | `foreshadow_*` — **됨** (본문에서 문장 골라 걸기는 3, `fsClueRows` 는 4에서) |
| 7 | `FeatureStatWin` | 상태창 수치 (항목 고치기, 틀, 복사, 서식, 화별 변화 표) | `statwin.js` (`swDeltaRows` 는 4 상태 승인) | `statwin_view`(`StatwinView`), `statwin_set`, `statwin_template` — **됨** |
| 7 | `FeatureAuto` | 자동 집필 (실행 상태 · 진행 로그, 시작 · 일시정지 · 이어 가기 · 중지, 승인 정책, 비용 · 시간 추정, 배치, 검토 대기 화, 검토 없이 반영한 화) | `auto.js` | `auto_*`(`AutoView` · `AutoEstimate`), 검토 대기 변경안을 상태 승인 결과로 두기 `auto_review` — **됨**. 남음: 시작 전 집필 화면의 저장하지 않은 본문 초안 저장(`autoFlushDrafts`), 집필 · 플롯 · 홈 화면의 잠금 안내(`autoLockNote` · `autoEp`, 상태 승인은 됨), 홈의 자동 집필 줄, 오류 안내의 '모델 · API 키 설정' 단추 |
| 7 | 작품 도구 (남은 것) | 지도, 이야기 줄기, 인과율, 작업지시서 | `atlas.js` `lines.js` `causal.js` | 각 화면 |
| 8 | `FeatureUsage` | 사용량 · 비용 | `usage.js` | `usage_summary` · `usage_prices` — **됨** |
| 8 | 본편과 분리 · 설정 (남은 것) | 연구, 모델 · API 키 설정 | `claude.js` `vertex.js` | `research`, `config` |

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

| Swift | 웹 (`canon/static/app.js`) |
|---|---|
| `CanonError.from` | `fmtErr` |
| `KoreanText.josa` · `episodeRange` · `date` · `dateTime` | `josa` · `epRange` · `fmtDate` · `fmtDateTime` |
| `EpisodeStatus` | `STATUS`, `projectNext` 의 대기 문구 |
| `Screen` | `sidebar` 의 `items` · `tools` |
| `JobTracker` · `JobText` | `pollJobs` · `finishJob` · `JOB_DONE_MSG` · `PENDING_KINDS`(서버 `web.PENDING_KINDS`) |
| `JobCenter` · `ProjectDocument.merge` | `startJob` · `pollJobs` 의 화 받아 오기 · `mergeEpisodes` · `loadPending` · `jobFor` · `jobOwns` · `jobBtn` |
| `ProjectCardText` | `viewProjects` · `projectNext` |
| `HomeSummary` | `viewHome` · `nextStep` · `currentEp` · `actGroups` |
| `SaveText` · `ProjectDocument.edited` | `save()` 의 토스트와 `edited` |
| `StatWinText.resolve` | `statwin.js` `swResolve` (서버 `statwin.resolve`, 시험은 `tests/test_statwin.py` 의 `test_resolve` 와 같은 사례) |
| `StatWinText.pick` · `outgoing` · `presetLabel`, `StatCell` | `statwin.js` `swLoad` · `swSave` · `swEditor` · `swTimeline` |
| `WarmthBand` (경계 -0.6 · -0.2 · 0.2 · 0.6, 값이 경계보다 작으면 그 구간) | `cast.js` `WARMTH_BANDS`, 서버 `dynamics.warmth_word` |
| `CastText`, `CastText.fixed`(JS `toFixed` 반올림) | `cast.js` `tieText` · `tensionText` · `frameLabel` · `castTimeline` · `castChart` 범위, `app.js` `GOOD_EVENTS` · `INTENSITY` |
| `CastLayout.force` · `curve` | `cast.js` `castForce` · 간선 곡선 |
| `ReviewText.defaultPicks` · `picked` · `total` · `applyReasons` | `app.js` `setDelta` · `pickedDelta` · `viewReview` 의 `total` · `applyDelta` 의 묻는 말 |
| `ReviewText.stateRows` · `newKnows` · `unknown` · `relation` · `name` · `secret` · `goodEvents` · `intensity` | `viewReview` 의 인물 · 관계 줄, `charName` · `secretLabel` · `GOOD_EVENTS` · `INTENSITY` |
| `ReviewText.relationLines` (`pair`) | `relationLines` |
| `ReviewText.statRows` · `resolve` | `statwin.js` `swDeltaRows` · `swResolve` (서버 `statwin.resolve`, 시험은 `tests/test_statwin.py` 의 `test_resolve` 와 같은 사례. `StatWinText.resolve` 와 같은 규칙) |
| `ReviewText.clueRows` | `foreshadow.js` `fsClueRows` |
| `ReviewText.editedAfterFinal` · `laterWritten` · `restateItems` · `restatePicks` · `restateBody` · `restateSkipped` · `restateDone` | `restate.js` `editedAfterFinal`(서버 `pipeline.edited_after_final`) · `laterWritten` · `rsItems` · `rsPicks` · `applyRestate` · `restateCard` |
| `ReviewText.rangeText` · `revertQuestion` · `revertDone` | `rangeText` · `revertFrom` |
| `WriteText` (`blockedBefore` · `orderNote` · `unsaved` · `issue` · `when`), `WriteModel` 의 본문 초안 | `app.js` `blockedBefore` · `orderNote` · `textUnsaved` · `viewWrite`, `passage.js` `editableEp` · `issuesBlock` · `clip` · `editTime` · `flushText` |
| `TextDiff.lines` · `words` · `tokens`, `RewriteDraft` · `RewriteText` | `rewrite.js` `textDiff` · `rwSimilar` · `rwReq` · `rwReqLabel` · `RW_MODES` · `RW_KIND`, `passage.js` `wordDiff` · `tokens` (시험 기대값은 node 로 돌린 웹 결과) |
| `PublishText` | `publish.js` `copyRangeOf` · `copyEpisodes` · `downloadTxt` 문구 (다듬기 규칙은 서버 `publish.py`) |
| `PlotRules.actRanges` · `setArcEnd` | `actRanges` · `fitActs` (서버 `pipeline.act_ranges` · `fit_arc`, 시험은 서버 값과 같은 사례) |
| `PlotRules.coverage` · `rangeText` · `needsDraft` · `redraftQuestion` · `writeNext` | `actCoverage` · `rangeText` · `needsDraft` · `confirmRedraft` · `writeNextBtn` |
| `PlotRules.pendingRecaps` · `arcChip` · `rail` · `lostPartSummaries` · `progress` | `viewSerial` 의 요약 안내 · `arcChip` · `railChips` · `lostPartSummaries` · `arcProgress` (서버 `pipeline.pending_recaps`) |
| `PlotRules.lastFixed` · `insertSlots` · `insertNote` | `insert.js` `lastFixed` · `insertBlock` · `insertForm` (서버 `renumber.last_fixed`) |
| `PlotBoard`, `PlotEditorInfo`, `EpisodeCard` | `actBoard`, `plotEditor` · `payoffPicker` · `castField`, `epCard` |
| `PlotModel.syncResults` · `start` | `applyJobResult` · `loadPending`(되살린 결과는 고른 아크를 옮기지 않음) · `startJob`(저장하지 않은 변경을 먼저 묻기) |
| `Logline` · `LoglineField` · `Tone` · `ToneDial` | `composeLogline` · `loglineChecks` · `updateLogline` · `toneText` · `setDial` · `LOGLINE_SLOTS` · `TONE_WORDS`, 서버 `canon/logline.py` (셋을 함께 고친다. 시험은 `tests/test_logline.py` 와 같은 사례, `test_logline.py` 가 Swift 톤 말도 본다) |
| `SetupRules`, `SuggestionPicks`, `NameCheckGroups` | `addCharacter` · `removeCharacter` · `addRelationship` · `relProblem` · `conflictWord` · `REL_TYPES` · `CONFLICTS` · `TIERS` · `genreLabel` · `loglineExamples` · `rangeText`, `viewSuggestion` · `sameChar` · `sugEnd` · `SUG_FIELDS` · `applySuggestion`, `nameCheckBox` |
| `AutoText.status` · `step` · `stepLine` · `shiftOptions` · `issueOptions` · `everyOptions` | `auto.js` `AUTO_STATUS` · `AUTO_STEP` · `AUTO_SHIFT` · `autoRunCard` 의 `step` · `autoPolicyForm` |
| `AutoText.duration` · `cost` · `number` · `rangeText` | `auto.js` `autoDuration` · `autoCost`, `toLocaleString`, `app.js` `rangeText` (시험 기대값은 node 로 돌린 웹 결과) |
| `AutoText.defaults` · `estimateLine` · `estimateTime` · `estimateWarnings` · `estimateNotes` · `startQuestion` · `nothingLeft` | `autoDefaults`(기본 정책은 웹은 화면에, 앱은 서버 `policy_defaults`) · `autoEstCard` · `autoStart` · `viewAuto` 의 `nothingLeft` |
| `AutoText.progressLine` · `needsSettings` · `reviewDone` · `pendingStale` · `haltLink` · `runPolicyNote` · `paused` · `signature` · 알림 문구, `AutoModel.refresh` | `autoRunCard` · `pendingStale` · `autoHaltLinks` · `autoRunPolicy` · `actions.auto*` · `autoPoll` |
| `AutoText.styleWarnings` · `revertQuestion` · `revertDone` · `logTime` · `logTokens` | `autoAppliedCard` · `revertFrom`(`ReviewText.revertQuestion` 과 같은 말) · `autoLogCard` |
| `StyleText` | `styleBlank`(서버 `library.blank`) · `styleChangeWho` · `styleLibraryCard` · `baselineRows`, `analyzeStyle` · `useLibStyle` · `keepStyle` · `pushStyle` · `pullStyle` 의 묻는 말 |

## 알려진 한계

- SwiftUI 화면은 Mac 에서만 빌드된다. Linux 에서는 Model 과 시험만 확인한다.
- `swift test` 는 macOS 로만 빌드한다. iOS 에만 없는 API 는 iOS 대상 빌드에서만 드러난다. 예: iOS 의 `List(selection:)` 은 옵셔널 선택만 받는다. 화면을 고치면 iPad 시뮬레이터로도 빌드한다.
- 서버 주소에 하위 경로(`https://host/canon`)를 쓰면 `ProjectLoader` · `CanonServer.get` 이 경로를 잃는다. 지금 서버는 루트에 연다.
- `openapi.json` 은 설치된 FastAPI · pydantic 판에 따라 글이 조금 달라질 수 있다 (`requirements.txt` 는 가장 낮은 판만 정한다). 다른 기기에서 `tests/test_openapi.py` 가 코드 변경 없이 실패하면 그 기기에서 명세를 다시 만들고 차이를 본다. 2026-10-26 명세는 FastAPI 0.159.1, pydantic 2.14.1 로 만들었다.
- 서버의 `str | None` 같은 칸은 명세에서 `anyOf` 의 `null` 을 빼고 옵셔널로 둔다 (`scripts/make_openapi.py` 의 `drop_null`, 68곳). 생성기는 `null` 을 읽지 못해 그대로 두면 그 칸을 생성 타입에서 빼고, 앱이 작품을 저장할 때 그 칸이 지워진다. 서버의 `null` 은 `nil` 로 읽히고, `nil` 은 칸을 빼고 보내 서버 기본값이 된다.
