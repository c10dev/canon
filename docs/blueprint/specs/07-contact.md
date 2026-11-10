# 07. 본문에서 실제로 닿은 칸 기록 (6b)

상태: 진행 (claude/blueprint-contact) · 계획: [plan.md](../plan.md) 의 6b · 먼저: 6a

## 목표

본문을 쓴 뒤 상태 변경안이 '이번 화에 두 인물이 처음 닿은 사다리 칸'을 칸 id 목록에서 골라 제안한다.
작가가 상태 승인 화면에서 고르면 기록되고, 설계도 화면이 계획 칸과 실제 칸을 함께 보인다.
README 2026-11-10 규칙 '실제로 닿은 칸은 상태 변경안이 칸 id 목록에서 골라 제안하고 작가가 승인한다'를 따른다.

## 정할 것

1. 자동 집필 · `-y` — 정함(2026-11-10 사용자): 반영하지 않고 남겨 둔다(`Project.contact_held`). 작가가 설계도 화면에서 기록하거나 버린다.
2. 승인 화면의 기본 체크 — 추천대로: 고르지 않은 채로 놓는다(설정 바꾸기 · 호칭과 같다). '직접 정할 것' 칸에 보인다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | `ContactReach`(a · b · rung · quote, episode 는 프로그램이 채움), `StateDelta.contacts`, `DismissedItems.contacts`, `Project.contact_log` · `contact_held` |
| `canon/blueprint.py` | `reached` · `actual_rung` · `open_rungs`, 요청 줄 `state_rule`, 훅 `clean_delta` · `apply_delta` · `hold` · `revert`, `take_held` · `drop_held` |
| `canon/features.py` | `CLEAN` · `APPLY_LAST` · `REVERT_LAST` · `HOLD` 에 위 훅 |
| `canon/prompts.py` | 상태 변경안 요청 규칙에 `blueprint.state_rule`, 조각 `contact_state`, 변경안 줄(`delta_lines`)의 닿은 칸 |
| `canon/web.py` | `POST /api/projects/{name}/blueprint/held/{i}/{take\|drop}` |
| `canon/mock.py` | 상태 변경안 가짜 응답: 요청에 칸 목록이 있으면 첫 칸에 닿음 |
| `canon/static/review.js` | 목록 `contacts`(체크 키 'u'): 고르기 · 빼 둔 항목 · 기본 체크 해제 · 요지 · 직접 정할 것 수 · 빼 둔 항목 보기 |
| `canon/static/blueprint.js` | 승인 화면 줄 `contactDeltaRows`, 사다리 카드의 'n화에 닿음', 계획 띠의 '본문에서 닿음' 줄, 남겨 둔 제안 카드 |

## 데이터 · 스키마

- `Project.contact_log` · `contact_held` 의 기본값은 빈 목록이라 옛 작품이 읽힌다.
- `ContactReach.episode` 는 응답 형식에서 뺀다(`SkipJsonSchema`). dict 가 없다.
- 지금 칸은 저장하지 않고 기록에서 계산한다(`reached` · `actual_rung`). 지워진 칸의 기록은 셈에서 뺀다.

## 규칙

- 요청 줄: 그 화 플롯 인물끼리 사다리에서 아직 닿지 않은 칸만 'id: 이름(id) ↔ 이름(id) 칸 한 줄'로 준다. 칸이 없으면 빈 글이라 지금 요청 그대로다.
- 정리: 목록에 있는 칸만, 쌍이 그 사다리와 같을 때만, 이미 닿은 칸과 한 변경안 안의 겹친 칸은 뺀다. 쌍 차례는 사다리에 맞추고 화 번호를 채운다.
- 반영: 작가가 고른 줄만 `contact_log` 에 더한다(같은 칸 · 같은 쌍은 한 번).
- 사람 검토 없는 반영(자동 집필 · `run -y` · 플레이): `hold` 가 `contact_held` 로 옮기고 변경안에서 뺀다. 같은 화의 옛 남김은 바꾼다.
- 반영 취소: n 화 뒤의 기록과 남김을 지운다.
- 대화 에이전트는 이 기록을 쓰지 않는다.
- 단편과 장편이 같다.

## 화면 · 명령줄 · 프롬프트

- 상태 승인 화면 '직접 정할 것': '아영 ↔ 지훈 · 설계도 칸 · 기본으로 고르지 않았어요', 칸 이름, 본문 문장.
- 설계도 화면: 사다리 카드의 칸 옆 'n화에 닿음', 계획 띠의 '본문에서 닿음' 줄(초록), 개요와 쌍 쪽의 '남겨 둔 닿은 칸' 카드('기록하기' · '버리기').
- 명령줄은 바꾸지 않는다.

## 시험

- `tests/test_blueprint.py`: 요청 줄, mock 변경안 → 반영 → 기록, 다시 묻지 않음, 정리, 남겨 두기 → 기록하기, 되돌리기, 남겨 둔 제안 API.
- `tests/test_blueprint_js.py`: 승인 화면 줄 · 기본 체크 해제, 'n화에 닿음' · '본문에서 닿음', 남겨 둔 제안 카드.
- `tests/test_delta_count.py`: `DELTA_LISTS` 가 `contacts` 를 센다.
- `tests/test_prompt_registry.py` 의 요청 스냅샷: 작업지시서 상태 변경안 두 개가 바뀐다(응답 형식 글에 `contacts` 칸).

## 문서

- `docs/modules/story.md` 의 `canon/blueprint.py` · `canon/static/blueprint.js` 절, `docs/modules/core.md` 의 상태 변경안 · 웹 줄, `docs/modules/web.md` 의 `review.js` 절.
- README.md · DESIGN.md 의 설계도 줄.
- [plan.md](../plan.md) 의 6a · 6b 상태.

## 확인하지 못할 것

- 실제 모델이 칸 목록에서 맞게 고르는지는 재지 않았다(LLM 비용 없음으로 끝냄). 재려면 flash 로 상태 변경안 2~3화부터 잰다.

## 비용

- LLM 비용 없음.
