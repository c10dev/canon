# 웹소설식 작품 구축 계획

단기는 차례를 제안한 일감이다. 차례도 사용자와 정하기 전에는 제안이다.
미룬 것과 장기 후보는 아래 표에 둔다.
일감을 시작할 때 `specs/NN-이름.md` 를 쓴다. 끝내면 그 명세서의 상태 칸과 이 표의 상태를 고친다.
새로 정한 것은 [README.md](README.md) 에 '정한 규칙' 절을 만들어 더한다.

## 일감마다 지킬 것

- 기본값(드라마식 틀, 하렘 요소 없음, 성장 일정 없음)이면 그 일감이 고친 프롬프트 글이 지금과 글자까지 같다는 시험을 둔다.
- 스키마를 바꾸면 기본값을 두고 `canon/mock.py`(새 기능은 `mock_<기능>.py`)를 맞춘다.
- 고친 모듈의 `docs/modules/` 절과 README.md · DESIGN.md 의 해당 부분을 같은 변경 안에서 고친다.
- 화면에 늘 보이는 칸 · 버튼을 더하면 `docs/design/README.md` 의 '덜기' 절을 따른다.
- 프롬프트 글을 고치면 `brief` 출력도 함께 본다(API 경로와 작업지시서 경로가 같은 프롬프트를 쓴다).
- Swift 앱(`swift/`)은 고치지 않는다.

## 단기

| 차례 | # | 일감 | 상태 | 명세서 | 먼저 끝날 것 |
|---|---|---|---|---|---|
| 1 | 1 | 이야기 틀 칸(`Meta.frame`, 기본 drama)과 설정 화면의 고르기, 장르를 고를 때 틀 추천. 프롬프트는 바꾸지 않음 (LLM 비용 없음) | 끝 ([#527](https://github.com/c10dev/canon/pull/527)) | [01-frame.md](specs/01-frame.md) | — |
| 2 | 2 | 장르 정의: `light_novel` 의 관습 · 속도 · 예시 로그라인, 요소 장르 `harem` · `system` 더하기, `modern_fantasy.avoid` 고치기, `light_novel` 의 '캐릭터마다 말버릇' · '화마다 웃음 포인트' 같은 매 화 지시 빼기 | 끝 ([#531](https://github.com/c10dev/canon/pull/531)) | [02-genre-defs.md](specs/02-genre-defs.md) | — |
| 3 | 3 | 로그라인 웹소설 칸: 새 칸 둘(주인공만 가진 것, 독자가 받는 재미)과 틀별 합치기 · 점검(`logline.py` 와 `setup.js` 함께), 막는 것 · 걸린 것은 접어 선택으로 | 설계 | — | 1 |
| 4 | 4 | 부 · 아크 기획 프롬프트를 틀별로: 보상 루프 아크, 짧은 고구마(`conflict` 의 뜻), 새 칸 `StoryArc.gain`(이 아크에서 얻는 성장), 하렘이면 `StoryArc.focus`(공략 대상) | 설계 | — | 1, 2 |
| 5 | 5 | 성장 일정(능력 일정 앞당김): 설계도 능력 일정(`Blueprint.ability_plans`)의 스키마 · 저장 검사 · 화 번호 옮기기 · 상태창 기록과 견주는 경고 · 설계도 화면 | 일부 끝 (설계도 일감 10 · 11b · 12 · 13): 상태창 수치 항목은 명세서 정할 것 1 을 기다림 | [05-growth.md](specs/05-growth.md) | 1 |
| 6 | 6 | 화별 플롯 규칙을 틀별로: 사이다를 깔끔하게, 2~3화마다 작은 보상, 하렘이면 관계는 위로 · 균열은 1~3화 오해, 새 칸 `EpisodePlot.reward`(이 화의 사이다 한 줄) | 설계 | — | 4 |
| 7 | 7 | 고구마 · 사이다 경고 (LLM 비용 없음): 사이다 없는 화가 이어짐, 고구마 구간이 김, 하렘 쌍의 균열 · 적대가 오래 이어짐, 아크에 성장이 없음 | 설계 | — | 6 |
| 8 | 8 | 성장 일정을 기획 프롬프트(다음 아크 · 장편 화별 플롯)에 넣기, 플롯에서 거꾸로 뽑기 · AI 로 짜기 | 끝 (설계도 일감 10 · 11b · 12 가 맡음, [#490](https://github.com/c10dev/canon/pull/490) · [#501](https://github.com/c10dev/canon/pull/501)) | [05-growth.md](specs/05-growth.md) | — |
| 9 | 9 | 완급 계획 웹소설 판: 틀별 `heat_rules`(쌓기 비율을 낮추고 작은 터뜨리기를 자주, 뒤집힘은 고르기), 긴 고구마 경고 | 설계 | — | 6 |
| 10 | 10 | 인물 표지: 승인한 본문에서 작가가 거둔 말버릇 · 버릇 · 외모 특징을 인물 카드에 기록. 쓰기 요청에 넣을지는 정할 것 15 를 따른다 | 진행 (claude/cast-marks-22fd2d) | [10-marks.md](specs/10-marks.md) | 11 |
| 1과 나란히 | 11 | 인물 카드를 '표현'에서 '압력'으로: 설정 프롬프트가 버릇 하나 · 대사 예시 한 줄을 요구하지 않고, 지키려는 것과 흔들리면 어디로 가는지를 적게 함 | 진행 (claude/cast-pressure-3db64b, [#535](https://github.com/c10dev/canon/pull/535)): 11a 새 칸 · 설정 프롬프트 · 실측 묶음, 11b · 11c 남음 | [11-pressure.md](specs/11-pressure.md) | — |
| 1과 나란히 | 12 | 문체 규칙의 빈도 하한 막기: 분석 · 다듬기 프롬프트가 dos · pacing 에 '마다' · '한 번 이상' 같은 규칙과 화마다 같은 구성을 적지 않게 하고, 저장 때 그런 줄을 경고 (LLM 비용 없는 검사) | 끝 ([#526](https://github.com/c10dev/canon/pull/526) · [#533](https://github.com/c10dev/canon/pull/533)) | [12-rate-floor.md](specs/12-rate-floor.md) | — |
| 1과 나란히 | 13 | 문체 다듬기 결과의 LLM 찌꺼기 거르기: '[Wait: …]' 같은 메타 글이 칸에 저장되지 않게 `clean_style_revision` 에서 검사 (LLM 비용 없음) | 끝 ([#525](https://github.com/c10dev/canon/pull/525)) | [13-style-junk.md](specs/13-style-junk.md) | — |

- 2 · 11 · 12 · 13 은 틀과 상관없이 할 수 있어 다른 일감과 나란히 해도 된다.
- 11 · 12 · 13 은 사용자가 실제로 써 보고 느낀 'AI 느낌'의 Canon 쪽 원인이다(2026-11-10). 먼저 하기를 추천한다.
- 'AI 느낌' 묶음은 빈도 상한 · 하한을 새로 더하지 않는다(사용자 의견, 2026-11-10). 전환 속도는 6 · 8 에서 설계도 이정표 · 사다리처럼 이야기 사실로 잡는다.
- 5 · 8 의 대부분은 설계도 일감 10~13([docs/blueprint/plan.md](../blueprint/plan.md))이 '능력 일정'으로 만들었다. 남은 차이(상태창 수치 항목)와 `StoryArc.gain` 과의 경계는 [specs/05-growth.md](specs/05-growth.md) 에 있다.
- 4 · 6 · 8 · 9 는 `prompts.py` 의 같은 함수들(`series_prompt` · `next_arc_prompt` · `plot_rules` · `heat_rules`)을 고친다. 한 번에 한 세션만 고친다.
- 9 가 걸려 있던 화 끼워 넣기 · 빼기의 `heat` 화 번호 문제는 2026-11-14 에 고쳤다(설계도 plan.md 의 장기 후보 줄).

### 일감별 바꿀 곳

줄 번호는 커밋 2a1bbbf8 기준이다. 자세한 목록은 [README.md](README.md) 의 '조사 결과'.

| # | 바꿀 곳 |
|---|---|
| 1 | `canon/schema.py:43` `Meta` |
| 1 | `canon/static/setup.js` 설정 화면 (장르 칩 옆) |
| 1 | `canon/cli.py` `new` (`--frame` 같은 선택지) |
| 2 | `canon/genres.py:153` `light_novel` · `:285` `_LOGLINES` · `_OPENINGS` |
| 2 | `canon/genres.py:60` `modern_fantasy.avoid` |
| 3 | `canon/schema.py:27` `LoglineParts` |
| 3 | `canon/logline.py:46` `compose` · `:71` `checks` |
| 3 | `canon/static/setup.js:12` · `:18` · `:29` |
| 3 | `canon/prompts.py:461` 설정 대화 키 · `:6282` 아이디어 칸 |
| 3 | `canon/schema.py:1152` `SetupKey` · `canon/setupchat.py:34` · `canon/static/setupchat.js:10` · `canon/static/palette.js:17` · `canon/static/ideas.js:15` |
| 3 | `canon/mock.py:592` · `:616` |
| 4 | `canon/schema.py:822` `StoryArc` · `:1109` `ArcEdit` |
| 4 | `canon/prompts.py:1966` `series_prompt` · `:2092` · `:2094` `next_arc_prompt` · `:2580` 플롯 대화 아크 규칙 · `:2327` 전환 |
| 4 | `canon/static/plot.js:934` · `:988` · `:1004` · `canon/static/chat.js:58` · `canon/static/convert.js:189` · `:318` |
| 4 | `canon/static/agent.js:73` · `:79` 제안 칩 · `canon/cli.py:583` · `:615` |
| 4 | `canon/mock.py:305` · `:317` |
| 5 | 남은 차이(상태창 수치 항목)만: `canon/schema.py` `AbilityPlan` · `canon/blueprint.py` `got_ep` · 경고 · `canon/static/blueprint.js` 편집 카드. 목록은 [specs/05-growth.md](specs/05-growth.md) |
| 5 | `canon/statwin.py` `_amount` · `after_delta` (수치 값 읽기만) |
| 6 | `canon/prompts.py:1120` · `:1131` `plot_rules` · `:1430` 초반 규칙 |
| 6 | `canon/prompts.py:5584` `HOOK_GUIDE` (항목 이름은 두고 설명만) |
| 6 | `canon/schema.py:678` `EpisodePlot` · `canon/static/plot.js` 화 플롯 칸 |
| 7 | 새 파일(예: `canon/reward.py`) · `canon/pace.py:210` 옆 · `canon/board.py` `checks` · `canon/static/plot.js` 경고 |
| 8 | 없음: `prompts.blueprint_ability_block` · `pipeline.propose_abilities` · `draft_abilities` 가 이미 있다(설계도 일감 10 · 12) |
| 9 | `canon/prompts.py:1198` `heat_rules` · `canon/heatplan.py:108` `WARN_CODES` · `warnings` |
| 10 | `canon/schema.py:119` `Character` · `canon/prompts.py` 인물 블록 · `canon/static/cast.js` |
| 11 | `canon/prompts.py:229` · `:230` 설정 요구사항 · `:319` 원형 굴리기 · `:6293` 말투 칸 설명 |
| 11 | `canon/schema.py:126` `Character.personality` · `:130` `speech_style` 설명 |
| 11 | `canon/prompts.py:6463` `cast_view` · `:3141` `static_parts` 인물 블록 · `:3609` `WRITE_SPEECH_LINE` |
| 12 | `canon/prompts.py:477` `style_prompt` · `:680` · `:684` 문체 다듬기 요구사항 |
| 12 | `canon/schema.py:417` `StyleProfile.pacing` · `:421` `dos` · `:405` `StyleDevice.every` |
| 13 | `canon/pipeline.py:520` `clean_style_revision` · `:620` `apply_style_edits` |

## 정할 것

사용자가 정할 질문이다. 추천안을 먼저 쓴다.

1. (정함 2026-11-14: 추천안대로) 웹소설식을 장르와 따로 작품 설정 '이야기 틀'(`Meta.frame`)로 둘까요? — 추천: 따로 둔다. 장르는 고를 때 틀을 추천만 한다.
2. (정함 2026-11-14: 추천안대로) 틀 이름은 '드라마식 · 웹소설식'이 좋을까요? — 추천: 그렇다. 화면 문구는 '이야기 틀'.
3. (정함 2026-11-14: 추천안대로) 단편에도 웹소설 틀을 열까요? — 추천: 연다. 단편 기승전결 프롬프트(`arc_prompt`)의 틀별 줄은 4 다음에 따로 본다.
4. 웹소설 로그라인 다섯 칸을 '누가 · 무엇 때문에 · 무엇을 하려 하나 · 주인공만 가진 것 · 독자가 받는 재미'로 할까요? 막는 것 · 걸린 것은 접어서 선택으로. — 추천: 그렇다.
5. 하렘을 틀이 아니라 요소 장르 `harem` 으로 가를까요? — 추천: 그렇다. 사이다 헌터물처럼 하렘이 아닌 웹소설이 있다.
6. 아크마다 공략 대상 칸(`StoryArc.focus`)을 둘까요, 주요 인물(`cast`)로 충분할까요? — 추천: 칸을 둔다. 설계도 이정표를 그 인물 것만 골라 넣을 수 있다.
7. 관계 단계 위쪽 끝이 '신뢰'라 하렘 히로인이 일찍 끝에 닿아요. 그 뒤 진도는 이정표 라벨과 접촉 사다리로 충분할까요? — 추천: 충분하다고 보고, 모자라면 '공략 사다리'(접촉 사다리처럼 작가가 칸을 적는 목록)를 장기 후보로 둔다.
8. 하렘 쌍의 균열 · 적대가 몇 화 넘게 이어지면 경고할까요? — 추천: 3화.
9. 사이다 없는 화가 몇 화 이어지면 경고할까요? — 추천: 3화.
10. (정함 2026-11-14: 추천안대로) 능력 일정을 '성장 일정'으로 앞당겨 웹소설 일감 5 로 할까요? 설계도 정한 규칙(2026-11-10, 두 번째 묶음으로 미룸)을 바꾸는 일이에요. — 추천: 앞당긴다. 먼저 필요한 설계도 일감 1~6 이 모두 머지됐다.
11. (정함 2026-11-14: 추천안대로) 성장 일정 한 줄을 [화 범위, 인물, 상태창 항목이나 스킬 도감 항목, 등급, 얻는 계기]로 할까요? — 추천: 그렇다. 실제 기록(`abilities.acquired` · `stat_log`)과 견줄 수 있다.
12. 웹소설 틀이면 완급 계획(`Settings.heat_plan`)을 기본으로 켤까요? — 추천: 켜지 않는다. 웹소설 판 규칙만 준비하고 켜기는 작가가 한다.
13. 장르 계수(`Genre.dynamics`)로 하렘의 원망(grievance)이 빨리 식게 할까요? — 추천: 지금은 하지 않는다. 프롬프트 규칙과 경고(7)로 먼저 보고, 모자라면 다시 정한다.
14. (정함 2026-11-14: 추천안대로) 인물 표지 칸을 모든 작품에 둘까요, 웹소설 틀에만 둘까요? — 추천: 모든 작품에 둔다. 비면 프롬프트에 넣지 않는다.
15. (정함 2026-11-14: 추천안대로) 거둔 표지(말버릇 · 버릇)를 쓰기 요청에 넣을까요? — 추천: 넣지 않는다. 검수 · 인물 화면의 기록으로만 쓴다. 넣으면 모델이 장면마다 그 표지를 쓴다.
16. '압력'을 새 칸(예: `Character.pressure`)으로 둘까요, `personality` 설명만 바꿀까요? — 추천: 새 칸을 두고 `personality` 설명에서 '버릇 하나'를 뺀다.
17. 기존 작품의 버릇 문장 · 대사 예시는 어떻게 옮길까요? — 추천: 자동으로 옮기지 않는다. 인물 화면에 '압력으로 다시 쓰기' 제안 카드를 두고 작가가 고른다. 사용자 작품 '비밀-계정이-나한테만-보인다'는 이미 손봤으니 건드리지 않는다.
18. 대사 예시 한 줄을 `speech_style` 에 계속 둘까요? — 추천: 새로 만드는 인물에는 요구하지 않는다. 이미 있는 예시는 남기되 쓰기 요청의 인물 블록(`cast_view`)에서 뺄지 실측으로 정한다.
19. (정함 2026-11-14: 추천안대로) 문체 장치의 최소 간격(`StyleDevice.every`)도 빈도 규칙이에요. 그대로 둘까요? — 추천: 칸은 두되 분석이 원문 빈도로 짐작해 채우지 않게 하고(기본 0, 상황이 올 때만), 작가가 적은 값만 쓴다.
20. 문체 규칙의 빈도 하한 줄을 저장 때 경고만 할까요, 막을까요? — 추천: 경고만 한다. 이미 저장된 줄은 그대로 두고 문체 화면에서 표시한다.

## 실측 계획

비용 드는 실험은 AGENTS.md 의 '비용 드는 모델 실험' 규칙을 따른다.

- 1 · 2 · 3 · 5 · 7 · 10 은 프롬프트 형식이나 화면만 바꾸거나 LLM 을 부르지 않는다. mock 시험으로 확인한다.
- 4 · 6 · 9 는 틀별 프롬프트를 바꾼다. 일감마다 flash 급 모델로 드라마식 · 웹소설식 두 판을 같은 작품 사본(임시 `CANON_HOME`)에 2~3회씩 돌려 본다.
- 판 비교는 한 판 안에서 같은 글을 두 번 넣어 점수 흔들림을 함께 잰다(블라인드 점수가 하루 안에도 흔들린 기록이 있다).
- 보는 것: 아크 제안의 고구마 화수, 사이다 화 간격, `gain` 이 비었는지, 관계 단계가 내려가는 화 수.
- 11 · 12 는 지하철 79화 조율판 실측(DESIGN.md '조율' 절, 2026-11-09: 동작 지시를 뺀 판이 블라인드에서 높았음)과 같은 방식으로 견준다: 버릇 · 대사 예시를 뺀 인물 블록 판과 지금 판을 같은 화로 2~3편씩.
- 11 · 12 에서 보는 것: 같은 버릇 · 대사 예시 문장이 본문에 나온 횟수, 장면 수, 한 순간에 머문 구간 비율, 작가 블라인드 점수.
- 추정 비용: 아크 제안 한 번 약 2만 토큰 입력 기준으로 일감마다 $1 안팎(실행 전 `python -m canon usage --prices` 로 다시 어림).

## 미룬 것 · 장기 후보

| 후보 | 상태 | 먼저 필요한 것 |
|---|---|---|
| 공략 사다리 (히로인마다 작가가 적는 공략 단계 목록) | 장기 후보 (정할 것 7) | 4, 7 |
| 스토리보드 · 큐 시트의 긴장 기호(T · S · D)와 정점 규칙을 틀별로 | 장기 후보 | 6 |
| 검수 프롬프트가 웹소설 틀에서 '갈등 부족'을 흠으로 보지 않게 | 장기 후보 (검수 프롬프트는 아직 조사하지 않음) | 6 |
| 장르 계수(`Genre.dynamics`) 하렘 프리셋 | 장기 후보 (정할 것 13) | 7 |
