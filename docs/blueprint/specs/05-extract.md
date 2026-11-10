# 05. 지금 플롯에서 설계도 거꾸로 뽑기

상태: 진행 (claude/blueprint-extract) · 계획: [plan.md](../plan.md) 의 5번 · 먼저: 1번, 3번

## 목표

이미 플롯이 있는 작품(지하철 작품 1~119화)에서 두 인물의 설계도를 AI 가 아크 단위로 뽑아 제안한다.
작가가 고른 줄만 설계도에 들어간다([README.md](../README.md) 2026-11-10 '거꾸로 뽑고 작가가 고쳐 확정한다').
플롯은 바꾸지 않는다. 맞지 않는 확정 플롯은 일감 2 의 경고로만 보인다.

## 정할 것

1. 한 번에 뽑는 범위 — 정함: 장편은 아크 하나, 단편은 작품 전체. 설계 세션 평가의 '아크 단위로 나눠 뽑기'를 따른다.
2. 근거 — 정함: 줄마다 근거 화와 그 화 플롯에서 옮긴 구절을 1~3개 받는다. 범위 밖 화의 근거는 정리 때 뺀다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | 응답 형식 `BlueprintProposal`(`MilestoneDraft` · `RungDraft` · `BlueprintEvidence`) |
| `canon/blueprint.py` | 범위 `extract_range`, 정리 `clean_proposal`, 고른 줄 더하기 `apply_picks` |
| `canon/prompts.py` | `blueprint_extract_prompt`, 갈래 `KINDS["blueprint"]`, 조각 `blueprint_req` |
| `canon/pipeline.py` | `propose_blueprint` (단계 plan, `SYSTEM_PLANNER`) |
| `canon/mock_blueprint.py` (새 파일) | 가짜 응답. 정리가 거르는 줄을 섞는다 |
| `canon/web.py` | 작업 `blueprint`(대상 'a~b', 결과는 `PENDING_KINDS`), `POST /api/projects/{name}/blueprint/apply` |
| `canon/static/blueprint.js` | 쌍 쪽의 '지금 플롯에서 뽑기' 카드와 제안 카드 |
| `canon/static/app.js` | `PENDING_KINDS` · `pendingShown` · `applyJobResult` · 작품마다 두는 상태 `bpDraft` |

## 데이터 · 스키마

- 응답 형식에 dict 가 없다(`tests/test_schema_nodict.py`).
- 작품 데이터는 바꾸지 않는다. 고른 줄은 기존 `Milestone` · `ContactRung` 으로 들어간다.

## 규칙

- 정리(`clean_proposal`): 두 인물 사이 줄만 남긴다. 화 범위를 뽑은 범위로 자르고, 범위 밖 줄은 뺀다.
- 정리는 모르는 부위 · 동작 id, '장소'가 아닌 요소 id, 쌍 밖 주도 인물을 뺀다. AI 제안이라 지운다(작가 데이터는 지우지 않고 거절하는 `check` 와 다르다).
- 이정표는 화 차례, 사다리 칸은 처음 닿는 화 차례로 놓는다.
- 더하기(`apply_picks`): 이정표는 뒤에 붙인다. 사다리 칸은 처음 닿는 화 차례로 끼우고, 범위를 비운 칸은 자리를 지킨다.
- 더한 뒤 `check` 가 어긋나면 400 이고 아무것도 바꾸지 않는다.
- 제안 카드의 줄은 기본으로 고른 채로 보인다. 자동 집필은 이 작업을 부르지 않는다.
- 결과는 고르기를 기다리는 결과로 남아 새로고침해도 다시 놓인다. 더하거나 버리면 지운다.
- 대화 에이전트는 이 작업을 부르지 않는다.

## 화면 · 명령줄 · 프롬프트

- 쌍 쪽 맨 아래 '지금 플롯에서 뽑기' 카드: 장편은 플롯이 있는 아크를 고르고 'AI로 뽑기'.
- 제안 카드는 계획 띠 · 경고 다음에 놓인다. 줄마다 고르기 칸, 근거 '12화 「…」', '버리기' · '고른 줄 더하기'.
- 프롬프트: 작품 한 줄, 두 인물 설정, 그 범위 화별 플롯(제목 · 요약 · 사건 · 감정 변화), 이미 적은 설계도 줄, 부위 · 동작 · 장소 id 목록. 수위 지시는 넣지 않는다.
- 명령줄은 바꾸지 않는다.

## 시험

- `tests/test_blueprint.py`: mock 제안의 정리, 더하기의 차례 · 거절, 프롬프트의 id 목록 · 이미 적은 줄, 웹 작업 → 고르기를 기다리는 결과 → 더하기 API · 400.
- `tests/test_blueprint_js.py`: 제안 카드 그리기, 다른 쌍 쪽에서 숨김, `pendingShown`.

## 문서

- `docs/modules/story.md` 의 `canon/blueprint.py` · `canon/static/blueprint.js` 절, `docs/modules/core.md` 의 파이프라인 · 웹 작업 줄, `docs/modules/ai.md` 의 가짜 응답 목록.
- README.md 의 설계도 줄, DESIGN.md 의 설계도 줄.
- [plan.md](../plan.md) 의 4 · 5 상태.

## 실호출 확인 (2026-11-10)

- 지하철 작품 사본(임시 `CANON_HOME`)의 아크 1(1~15화), 조아영 ↔ 김지훈, gemini-3.8-flash.
- 추론 강도 high(기획 단계 설정)로 보낸 첫 호출은 300초 안에 응답이 없어 끊었다(기록 없음).
- 추론 강도 low 로 다시 보냈다. 첫 시도는 출력이 65,522토큰까지 늘어나 실패했고(399초), Canon 의 다시 보내기가 13초 만에 받았다.
- 받은 것: 이정표 3줄(근거 0개), 사다리 5칸(1 · 2 · 3 · 8 · 11화, 칸마다 근거 1~2개). 부위 · 동작은 모두 목록 안 id 였다.
- 비용: 가격표 어림 약 $0.28 (늘어난 실패 $0.26 + 성공 $0.02).
- 남은 위험: 출력이 끝없이 늘어나는 실패가 한 번 있었다. 이정표에는 근거가 붙지 않았다.

## 확인하지 못할 것

- 뽑은 줄이 맞는지는 작가가 판단한다. 제안 카드의 근거 구절로 확인한다.

## 비용

- 실호출 확인 위 절. 나머지 시험은 mock 이라 LLM 비용 없음.
