# 04. 검수 연결

상태: 설계 · 계획: [plan.md](../plan.md) 의 4번 · 먼저: 1번, 3번

## 목표

장면 연출의 규칙 판정이 검수 화면의 '동선' 지적으로 나와, 작가가 다른 지적과 같은 곳에서 고침 · 그대로 둠 · 잘못 짚음을 정한다. 설정을 켜면 검수할 때 본문에서 연출을 함께 뽑는다.

## 두 역할 결정 (2026-10-29)

- 검수 때 본문 장면 추출이 자동으로 돈다(`Settings.stage_extract` 기본 켬). 추출 결과는 본문 장면(`role = text`, 일감 07)으로 두고 계획 장면을 덮지 않는다.
- 판별은 둘이다: 본문 장면의 규칙 판정(`judge`), 계획 장면이 있으면 계획 대비 차이(`stage.diff`, 일감 07).
- 동선 지적의 심각도는 low 다. 고침안(`propose_fixes`)은 어긋난 낱말만 바꾸고, 새 동작 문장을 더하는 고침안은 `clean_fixes` 가 거른다.

## 정할 것

1. `Finding` 출처 칸 — 추천: `ConsistencyIssue` 에 `origin: Literal["ai", "rule"] = "ai"` 를 더한다. 화면은 '규칙' 표시를 달고, 이 지적만 다시 검수는 규칙 지적이면 LLM 을 부르지 않고 판정을 다시 돌린다. DESIGN.md shadowcast 계획이 '출처 칸이 필요해 뒤로 미룬다'고 적은 칸이다.
2. 심각도 — 정함(두 역할 결정): 규칙 지적과 계획 대비 차이는 low 다. 자동 집필은 `ignore_minor` 를 켜면 세지 않는다.
3. 쓰기 전 연출(인용 없는 박자)의 지적 — 추천: 검수 세션에 넣지 않고 장면 연출 화면에만 보인다. 검수 세션은 본문 문장을 짚는 곳이다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | `ConsistencyIssue.origin`, `CheckRound.stage: bool = False` |
| `canon/stage.py` | `to_issues(violations, scene)`: 인용 있는 박자만, `current_quote` 는 어긋난 박자 인용, `source_quote` 는 `cause` 박자 인용(시작 상태면 빈칸), 한 문장의 여러 위반은 하나로 |
| `canon/pipeline.py` | `check_episode` 끝에서 `Settings.stage_extract` 가 켜져 있으면 사건마다 `extract_stage` → 장면이 비었으면 바로 적용(작가 장면은 덮지 않음) → `judge` → `to_issues` 를 같은 `apply_check` 에 넣음. 첫 검수 지적과 `same_quote` 이면 뺌. 꺼져 있어도 이미 있는 장면의 판정은 넣는다 |
| `canon/findings.py` | 규칙 지적의 다시 검수(`recheck_finding` 에서 `origin == "rule"` 이면 판정만) |
| `canon/web.py` | `PUT …/stage-extract`(`check-widen` 과 같은 모양) |
| `canon/autorun.py` | 비용 추정에 사건 수만큼 추출 호출 더하기(설정이 켜졌을 때) |
| `canon/static/check.js` | 지적에 '규칙' 표시, '장면 연출에서 보기' 링크(그 박자로) |
| `canon/static/settings.js` 또는 검수 화면 | '검수 때 함께 뽑기' 스위치 |

## 시험

- 규칙 지적이 `findings.merge` 로 합쳐지고 다시 검수해도 kept · wrong 이 지켜진다.
- 설정을 끄면 추출 호출이 없다(mock 호출 수).
- 작가가 만든 장면은 검수 추출이 덮지 않는다.

## 문서

DESIGN.md 검수 절: shadowcast 계획 문단을 장면 연출로 이어 고치고, '화마다 좌표나 배치도를 만들지 않는다' 문장 옆에 기준점 + 관계 방식을 적는다.

## 확인하지 못할 것

실제 모델로 헛짚은 비율(심지 않은 지적 중 틀린 것). 연구 화면 검수 시험으로 잰다.
