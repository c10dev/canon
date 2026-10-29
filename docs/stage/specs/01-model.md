# 01. 스키마 · 방 틀 · 어휘 · 위치 계산 · 규칙 판정

상태: 설계 · 계획: [plan.md](../plan.md) 의 1번

## 목표

작가에게 보이는 변화는 아직 없다. 장면 연출의 데이터와 LLM 없는 계산(위치, 규칙 판정, 막기, 사건 찾기)을 넣어 2~5번 일감이 그 위에서 일하게 한다.

## 정할 것

1. shadowcast 와의 관계 — 추천: 1차 판정기는 `canon/stage.py` 에 둔다. 규칙 이름(`handoff` 등)과 `?` 손 규칙은 DESIGN.md 의 shadowcast 계획과 맞춘다. 2026-10-29 현재 `~/Projects/shadowcast` 에는 실험 도구(`hand-check`)만 있고 엔진 패키지가 없다. 엔진이 나오면 손 · 물건 규칙을 엔진 판정기로 바꿀지 그때 견준다(2차 후보). 다른 안: 엔진 패키지를 먼저 만들고 Canon 은 그것을 가져온다.
2. 거리 문턱 — 추천: 손 접촉 1.2m, 그 밖 부위 0.6m 로 시작하고 일감 3 의 시험 장면으로 고친다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | `Room` · `Anchor` · `StageScene` · `StageBeat` · `StageBody` · `Spot` · `Hand` · `Contact`, `Project.rooms`, `Episode.stage`, `Settings.stage_extract`. 형식은 [model.md](../model.md) |
| `canon/stage.py` (새) | 방 틀 `ROOMS`, 어휘 `PARTS` · `POSTURES` · `ACTS`, `place`(위치 계산), `state_at`(박자 겹치기), `judge`(규칙 판정), `blocked`(막기), `find_event`(사건 글 → 번호 → 없음), `clean`(이름 → id, 목록 밖 → memo, 막는 접촉 빼기), `stale`(본문에 없는 인용 박자), `vocab()`(화면용 목록). LLM 호출 없음 |
| `canon/renumber.py` | 장면은 `Episode` 에 있어 화와 함께 옮겨진다. 화 번호를 품은 칸이 없음을 확인만 한다 |

## 규칙

[model.md](../model.md) 의 위치 계산 · 검수 규칙 · 막기. 사건 찾기: 같은 사건 글이 있으면 그 번호, 없으면 저장한 번호의 사건, 그 번호가 없거나 글이 다르면 '사건이 바뀌었어요' 표시. 장면은 지우지 않는다.

## 화면 · 명령줄 · 프롬프트

없음(2 · 3 · 5번).

## 시험

- `tests/test_stage.py`: 틀마다 기준점이 방 안에 있다, `place` 의 겹침 펴기와 인물 기준 고리, 규칙 다섯 개의 걸림 · 통과 사례, `?` 손은 짚지 않음, `blocked`(미성년 + sexual 만 참, 성인은 거짓), `clean` 이 막는 접촉을 뺀다, 옛 `project.json` 읽기.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q tests`.

## 문서

AGENTS.md 표에 `canon/stage.py` 줄. 스키마 목록에 `StageDraft` 는 3번에서 더한다.

## 확인하지 못할 것

없음.
