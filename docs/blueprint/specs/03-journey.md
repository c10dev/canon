# 03. 설계도 화면: 여정 편집과 계획 띠

상태: 끝 ([#478](https://github.com/c10dev/canon/pull/478)) · 계획: [plan.md](../plan.md) 의 3번 · 먼저: 1번

## 목표

작가가 관계 이정표와 접촉 사다리를 화면에서 적고 고친다.
쌍마다 계획 띠로 몇 화쯤 무엇이 오는지 한눈에 본다.
이정표 경고(`blueprint.warnings`, 일감 2)를 화면에서 본다.

## 정할 것

1. 편집 화면의 자리 — 정함(2026-11-10 사용자): 사이드바 도구 '설계도' 쪽을 둔다. 틀은 스킬 도감과 같다(왼쪽 목차 + 오른쪽 카드 한 열). 기획서의 관계 카드에는 '여정' 줄(이정표 수 · 사다리 칸 수)과 '여정 고치기' 링크만 둔다. [README.md](../README.md) 의 화면 규칙을 이렇게 고쳤다.
2. 계획 띠의 기본 범위 — 추천대로: 기획한 화(아크 · 구간 · 플롯 끝)와 이 쌍 설계도의 끝 화 가운데 큰 것. '작품 전체'로 바꿀 수 있다. 615화 작품에서 1~79화 이정표가 보이지 않을 만큼 얇아져서다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/blueprint.py` | 경고에 방향을 붙인 `warning_rows` (`warnings` 는 그 글만) |
| `canon/web.py` | `GET /api/projects/{name}/blueprint`(`BlueprintView`), `PUT /api/projects/{name}/blueprint`(설계도 통째, `blueprint.check`) |
| `canon/static/blueprint.js` (새 파일) | 설계도 쪽: 목차, 개요, 쌍 쪽(계획 띠 · 경고 · 관계 이정표 · 접촉 사다리) |
| `canon/static/app.js` | 주소 `blueprint`, 사이드바 도구(데이터가 없으면 '더 보기'에 접힘) |
| `canon/static/setup.js` | 관계 카드의 '여정' 줄 `relJourney` |
| `canon/static/index.html` | `blueprint.js` |
| `canon/static/app.css` | `.bp-*` 규칙 |

- LLM 호출이 없다.

## 데이터 · 스키마

- 바꾸지 않는다.
- `BlueprintView`: `blueprint`, `warnings`(`source` · `target` · `text`), `parts` · `acts`(`id` · `label`, `stage.PARTS` · `stage.ACTS`), `last`(마지막 반영 화).

## 규칙

- 쌍 목록은 관계 설정의 쌍(그 차례와 a · b 차례)에 설계도에만 있는 쌍을 더한다.
- 쌍 주소 키는 두 인물 id 를 정렬해 `~` 로 잇는다.
- 카드는 읽는 모양이 기본이고 '고치기'로 그 카드 하나만 편다(스킬 도감과 같다).
- 저장은 서버의 설계도에 고친 카드의 몫만 바꿔 넣은 설계도 전체를 보낸다(`bpMerged`). 칸을 다 지운 사다리는 뺀다.
- 서버 검사에 걸리면 고치던 칸을 그대로 두고 서버 문구를 알린다.
- 저장하지 않은 글이 있으면 다른 쪽으로 갈 때 묻는다(`S.editDrafts.bp`).
- 대화 에이전트는 아직 설계도를 쓰지 않는다.

## 화면 · 명령줄 · 프롬프트

- 도구 이름은 '설계도', 기호는 🧭 이다.
- 늘 보이는 안내 문장은 머리 설명 한 문장이다. 주 버튼은 고치는 중인 카드의 '저장' 하나다.
- 계획 띠: 줄은 두 방향 이정표와 접촉 사다리 셋이다. 아크(장편) · 구간(단편) 경계는 점선, 마지막 반영 화는 녹색 선이다.
- 프롬프트 · 명령줄은 바꾸지 않는다.
- 고친 디자인 문서: `docs/design/components/Outline/README.md` 의 쓰는 화면, `docs/design/README.md` 의 도구 기호, `docs/design/layout.md`.

## 시험

- `tests/test_blueprint.py::test_blueprint_api`: 보기 · 저장 · 경고 방향 · 400.
- `tests/test_blueprint_js.py`: 단계 말이 스키마와 같음, 쌍 목록, 개요 · 쌍 쪽 · 고치는 칸 그리기, 저장할 몫 합치기, 관계 카드 링크.

## 문서

- `docs/modules/story.md` 의 `canon/blueprint.py` 절과 새 `canon/static/blueprint.js` 절.
- `docs/modules/web.md` 의 `canon/static/setup.js` 절.
- README.md 의 도구 목록, DESIGN.md 의 설계도 줄.
- [plan.md](../plan.md) 의 2 · 3 상태.

## 확인하지 못할 것

- 없음. LLM 을 부르지 않는다. 화면은 지하철 작품 사본(임시 폴더)으로 브라우저에서 확인했다.

## 비용

- LLM 비용 없음.
