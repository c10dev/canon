# 01. 스키마 · 저장 검사 · 화 번호 옮기기

상태: 진행 (claude/blueprint) · 계획: [plan.md](../plan.md) 의 1번 · 먼저: —

## 목표

설계도 데이터를 작품에 저장할 수 있게 한다.
작가에게 보이는 동작은 아직 바뀌지 않는다. 프롬프트 · 화면 · 명령줄은 고치지 않는다(일감 3 · 4 · 6).
이 일감은 [README.md](../README.md) 의 2026-11-10 규칙을 따른다.

## 정할 것

1. 사다리 칸의 차례와 처음 닿는 화가 어긋나면? — 정함: 저장을 거절한다. 화 범위를 적은 칸끼리는 칸 차례대로 `from_ep` 가 줄지 않아야 한다. 범위를 비운 칸은 '정하지 않음'이라 견주지 않는다.
2. 빼는 화가 범위의 끝 화이면? — 정함: 범위가 한 칸 줄어든다. 범위가 그 한 화뿐이면 그 자리에 온 다음 화를 가리킨다(다른 화 번호와 같음).

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | `Milestone` · `ContactRung` · `ContactLadder` · `Blueprint`, `Project.blueprint` |
| `canon/blueprint.py` (새 파일) | id 채우기, 저장 검사 `check`, 계획 칸 `planned_rung`, 화 번호 옮기기 `move` · `remap` |
| `canon/renumber.py` 의 `move_points` | `blueprint.move` 를 부르고 고친 수를 `count["blueprint"]` 에 센다 |
| `canon/pipeline.py` 의 `_renumber_notes` | '설계도 n개' 라벨 |
| `canon/reshape.py` | 재구성의 화 지도로 설계도 화 번호를 옮기고, 옮기지 못한 줄을 알림에 적는다 |
| `canon/web.py` 의 `_put_locked` | 저장 때 `blueprint.check(p, disk)` |

- LLM 호출이 없다.

## 데이터 · 스키마

- `Milestone`: `id` (str, 빈 글이면 저장 때 `ms-<k>`), `source` · `target` (인물 id), `from_ep` · `to_ep` (int, 0 은 정하지 않음), `stage` (`""` 또는 `RelStage`), `label` (str), `trigger` (str).
- `ContactRung`: `id` (빈 글이면 `cr-<k>`), `label`, `parts` (`stage.PARTS` id 목록), `acts` (`stage.ACTS` id 목록), `layer` (`""` · `옷 위` · `옷 안` · `맨살`), `places` (인과율 '장소' 요소 id 목록), `lead` (인물 id 또는 빈 글), `note`, `from_ep` · `to_ep`.
- `ContactLadder`: `a` · `b` (인물 id), `rungs` (`ContactRung` 목록, 차례가 단계).
- `Blueprint`: `milestones` · `ladders` · `note` (설계 원칙 한 줄).
- `Project.blueprint` 의 기본값은 빈 `Blueprint` 다. 옛 `project.json` 이 고치지 않고 읽힌다.
- dict 필드가 없다. 아직 LLM 응답 형식에 들어가지 않는다(일감 5 에서 제안 형식을 따로 둔다).

## 규칙

- 저장 검사 `check(p, before)` 는 `ValueError` 로 거절한다(웹은 400). 말없이 지우지 않는다.
- 거절하는 것: 같은 인물끼리의 이정표 · 사다리, 없는 인물, 같은 쌍의 사다리 두 개, 모르는 부위 · 동작 id, '장소'가 아닌 요소 id, 쌍 밖의 주도 인물, `to_ep < from_ep`, 한쪽만 적은 범위, 겹치는 id, 정할 것 1 의 차례 어긋남.
- `before`(디스크 것)에서 이미 끊겨 있던 인물 · 장소 참조는 막지 않는다. 다른 라우트가 인물 · 요소를 지워 생긴 옛 데이터다(`validate_characters` 와 같은 방식).
- 빈 id 는 저장 때 채운다. 이미 있는 id 는 바꾸지 않는다.
- 계획 칸 `planned_rung(ladder, n)`: `from_ep` 가 있고 `from_ep <= n` 인 칸 가운데 차례가 가장 뒤인 칸. 없으면 None.
- 화 끼워 넣기(at): `from_ep >= at` 이면 한 칸, `to_ep >= at` 이면 한 칸 민다. 범위 안에 넣으면 범위가 는다.
- 화 빼기(n): 뒤 화는 한 칸 당긴다. 정할 것 2.
- 재구성: 화 지도로 옮긴다. 옮기지 못한 범위는 0(정하지 않음)으로 두고 알림에 적는다.
- 갈래 복사는 작품 전체를 복사하므로 고칠 것이 없다.
- 대화 에이전트(`canon/agent.py`)는 아직 설계도를 읽거나 쓰지 않는다.
- 단편과 장편이 같다.

## 화면 · 명령줄 · 프롬프트

- 바꾸지 않는다. 프롬프트는 일감 4 · 6, 화면은 일감 3 이다.
- 작품 저장(PUT · PATCH)이 설계도 칸을 받고 검사한다.

## 시험

- `tests/test_blueprint.py`: 옛 작품 읽기, id 채우기, 거절 사례, 옛 끊긴 참조 허용, 계획 칸, 끼워 넣기 · 빼기의 범위 네 경계, 재구성 알림, 웹 저장 400.
- `tests/test_agents_docs.py`: `docs/modules/story.md` 의 `canon/blueprint.py` 절.

## 문서

- `docs/modules/story.md` 에 `### canon/blueprint.py` 절.
- `docs/modules/core.md` 의 스키마 기본값 줄, `renumber.py` 절.
- AGENTS.md 의 '언제 무엇을 읽나' 표에 `docs/blueprint/` 줄.
- DESIGN.md · README.md 는 작가에게 보이는 기능이 생기는 일감(3)에서 고친다.

## 확인하지 못할 것

- 없음. LLM 을 부르지 않는다.

## 비용

- LLM 비용 없음.
