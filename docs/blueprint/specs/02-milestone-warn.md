# 02. 관계 이정표 경고

상태: 끝 ([#477](https://github.com/c10dev/canon/pull/477)) · 계획: [plan.md](../plan.md) 의 2번 · 먼저: 1번

## 목표

작가가 관계 이정표를 적어 두면, 이정표끼리 칸이 모자라거나 플롯이 이정표를 앞지를 때 Canon 이 알린다.
막지 않는다([README.md](../README.md) 2026-11-10 '경고만').
관계 수치는 바꾸지 않는다(2026-11-10 '이정표는 계획값').

## 정할 것

1. 저장할 때 단계 길을 검사해서 막을까? — 정함: 막지 않는다. 경고 함수 `blueprint.warnings` 만 두고, 화면은 일감 3 이 보인다. 2026-11-10 '경고만' 규칙을 따른다.
2. 지난 이정표에 못 닿은 것도 알릴까? — 정함: 이번에는 넣지 않는다. 다음 이정표까지 칸이 모자라는 것만 알린다. 지난 것은 계획 띠(일감 3)에서 보인다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/dynamics.py` | 칸 수 `stage_steps(start, goals)` (STAGE_EDGES 너비 우선). `pace._steps` 가 이것을 쓴다 |
| `canon/blueprint.py` | 경고 `warnings(p)`: 이정표끼리 칸 모자람, 겹치는 범위, 지금 단계에서 다음 이정표까지 칸 모자람 |
| `canon/pace.py` 의 `plot_warnings` | 플롯이 이정표를 앞지름 경고(`milestone_warnings`)를 뒤에 더한다 |
| `canon/static/plot.js` | `pacePlot` 에 같은 규칙(`paceMilestone`), `plotTodos` 의 경고 이름 |

- LLM 호출이 없다.

## 데이터 · 스키마

- 바꾸지 않는다.

## 규칙

- 칸 수는 `dynamics.STAGE_EDGES` 로 센다(한 화에 한 칸).
- 아래 '방향'은 이정표의 `source` → `target` 이다. 단계와 화 범위를 모두 적은 이정표만 본다.
- 이정표끼리(`warnings`): 한 방향의 이정표를 `from_ep` 차례로 놓고 이웃한 두 줄을 견준다.
  - 칸 수가 '뒤 이정표의 끝 화 − 앞 이정표의 처음 화'보다 크면 알린다.
  - 두 줄의 범위가 겹치고 단계가 다르면 알린다.
- 지금에서 다음까지(`warnings`): 마지막 반영 화를 `last` 라 한다.
  - 끝 화가 `last` 보다 뒤인 첫 이정표를 고른다.
  - 지금 단계(`Tie.stage`)에서 그 단계까지 칸 수가 '끝 화 − last'보다 크면 알린다.
  - 관계 수치가 없는 방향은 넘어간다.
- 플롯이 앞지름(`pace.milestone_warnings`): n 화 플롯의 바뀜(`plot_shifts`)이 가 닿을 단계들을 본다.
  - 두 방향을 따로 본다.
  - 그 방향에 그 단계를 가진 이정표가 있어야 한다.
  - 그 이정표의 처음 화가 모두 n 보다 뒤이면 알린다.
  - 두 층 감정으로 가린 쌍(`_masked`)은 넘어간다.
- 플롯 점검(`board.checks`)과 플롯 화면의 할 일(`plotTodos`)이 이 경고를 보인다. 자동 집필은 멈추지 않는다(지금 관계 속도 경고와 같다).
- 단편과 장편이 같다.

## 화면 · 명령줄 · 프롬프트

- 플롯 화면 할 일 목록: 앞지름 경고는 '설계도보다 앞섬 · n화'로 보인다. 다른 관계 속도 경고는 지금 이름 그대로다.
- `warnings(p)` 는 설계도 화면(일감 3)이 보인다.
- 프롬프트는 바꾸지 않는다.

## 시험

- `tests/test_blueprint.py`: `warnings` 의 세 경우와 경고가 없는 경우.
- `tests/test_pace.py`: 앞지름 경고, 이정표가 있으면 조용함, 가린 쌍.
- `tests/test_plot_pace_js.py`: `pacePlot` 이 같은 글을 낸다(node).

## 문서

- `docs/modules/story.md` 의 `canon/blueprint.py` · `canon/pace.py` · `canon/dynamics.py` 절.
- `docs/modules/web.md` 의 `canon/static/plot.js` 절(있으면).
- [plan.md](../plan.md) 의 1 · 2 상태.

## 확인하지 못할 것

- 없음. LLM 을 부르지 않는다.

## 비용

- LLM 비용 없음.
