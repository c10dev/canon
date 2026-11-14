# 01. 이야기 틀 칸

상태: 진행 (claude/story-frame) · 계획: [plan.md](../plan.md) 의 1번 · 먼저: —

## 목표

작가가 작품마다 이야기 틀(드라마식 · 웹소설식)을 고를 수 있다.
이 일감은 값을 저장하는 데까지다. 프롬프트는 글자까지 그대로이고, 아크 · 플롯 기획은 아직 이 값을 따르지 않는다(일감 3 · 4 · 6 · 9).
[README.md](../README.md) 의 2026-11-14 규칙 셋을 따른다.

## 정할 것

1. 틀을 장르와 따로 둘까요? — 정함(2026-11-14): 따로 둔다.
2. 틀 이름 — 정함(2026-11-14): 드라마식 · 웹소설식, 화면 문구 '이야기 틀'.
3. 단편에도 열까요? — 정함(2026-11-14): 연다.
4. 어느 장르가 웹소설식을 권할까요? — 추천: 현대 판타지 · 판타지 · 무협 · 라이트노벨 · 회귀 · 빙의. **사용자가 정하지 않았다. 추천안으로 구현했다.** 로맨스 판타지 · 대체역사는 넣지 않았다.
5. 설정 마법사에도 고르기를 둘까요? — 정함(2026-11-14): 둔다. 새 작품은 마법사로 열리므로 '제목 · 장르' 단계에서 추천 칩이 보여야 한다. 홈의 새 작품 칸에는 두지 않는다(묻지 않음).

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | `Frame` · `FRAMES`, `Meta.frame`(기본 `drama`) |
| `canon/genres.py` | `Genre.frame`(권하는 틀), `frame_hint` |
| `canon/prompts.py` | `meta_text` 가 `frame` 을 빼고 덤프한다 |
| `canon/cli.py` | `new --frame`, 장르가 권할 때 한 줄 안내 |
| `canon/static/home.js` | `FRAMES` · `frameHint` · `frameField` · `setFrame`, `syncGenre` 가 틀 칸도 다시 그림 |
| `canon/static/setup.js` | 기본 정보 절과 마법사 `wizBasics` 에 `frameField()` |
| `tests/test_frame.py` | 기본값, 옛 작품 읽기, 프롬프트 그대로, 추천, 명령줄, 화면 |

## 데이터 · 스키마

- `Meta.frame: Literal["drama", "webnovel"] = "drama"`. 옛 `project.json` 은 고치지 않고 읽힌다.
- `Meta` 는 LLM 이 채우는 응답 형식에 들어가지 않는다(설정 제안은 `SetupSuggestion`, 설정 대화는 `SetupRevision`).
- `Genre.frame: Literal["", "webnovel"] = ""`. 프롬프트의 장르 안내(`guide`)에는 넣지 않는다.

## 규칙

- 틀은 작가만 바꾼다. 장르를 골라도 값은 바뀌지 않고 추천 칩만 달린다.
- 추천 칩은 권하는 틀이 지금 값과 다를 때만 보인다.
- `prompts.meta_text` 가 `frame` 을 빼므로 모든 요청 글이 지금과 같다(`tests/test_prompt_registry.py` 스냅샷이 그대로 통과).
- 틀을 바꿔도 로그라인 · 아크 · 플롯 칸은 그대로다.
- 설정 대화 변경안의 적용 취소(`SetupBefore.meta`)는 `Meta` 를 통째로 되돌린다. 적용과 취소 사이에 바꾼 틀도 함께 돌아간다. 다른 `Meta` 칸과 같은 동작이다.

## 화면

- 설정 화면 기본 정보와 설정 마법사 '제목 · 장르' 단계의 장르 칸 아래에 나눔 버튼(`.seg`) 둘과 설명 풍선(`help`)을 둔다.
- 늘 보이는 안내 문장은 늘지 않는다(`tests/test_copy_count_js.py` 통과). 이름표 하나와 버튼 둘이 늘었다.
- 설명 풍선은 '지금은 고른 값만 저장해요'라고 밝힌다. 일감 4 가 끝나면 이 문장을 뺀다.

## 확인

- `CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_frame.py tests/test_prompt_registry.py tests/test_copy_count_js.py`
