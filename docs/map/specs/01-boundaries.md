# 01. 경계 정리 (파일은 그대로)

상태: 설계 · 계획: [plan.md](../plan.md) 의 1번 · 설계: [modules.md](../modules.md) 3절의 문제 1 · 2 · 3 · 5 · 6

## 목표

동작은 바뀌지 않는다. 지도 모듈 사이의 잘못된 의존을 끊어, 빈 블록 채우기(04)와 현대 장소 종류(08)가 기댈 자리를 만든다. 파일은 옮기지 않는다(옮기기는 02).

## 정할 것

1. 새 모듈 이름 — 추천: `canon/blocks.py`(블록 · 필지 쪼개기), `canon/placekinds.py`(장소 종류), `canon/mapprompt.py`(프롬프트 블록). 02 에서 `canon/maps/blocks.py` · `kinds.py` · `prompt.py` 로 옮긴다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/citygen.py` | `_cut` · `_inset` · `_parts` · `_scatter` · `_fit_rect` · `_crossings` · `_line_hit` · `_unit` 를 `blocks.py` 로 옮기고 밑줄을 뗀다. `citygen` 은 `blocks` 를 가져온다 |
| `canon/moderngen.py` | `from .citygen import _…` 대신 `from . import blocks` (`moderngen.py:24`) |
| `canon/towngen.py` | `CATEGORIES` · `CATEGORY_IDS` · `classify` · `water_for` 를 `placekinds.py` 로. `towngen` 은 가져와서 쓴다 |
| `canon/citygen.py`, `moderngen.py`, `pipeline.py`, `cli.py`, `mock.py` | `towngen.CATEGORIES` 등을 `placekinds` 로 |
| `canon/travel.py`, `canon/atlas.py` | `episode_block` · `check_rule` 의 문구 조립을 `mapprompt.py` 로. `travel` 은 줄 데이터(거리 · 시간)만 낸다. `prompts.py` 는 `mapprompt` 를 부른다 |
| `canon/atlas.py`, `canon/web.py` | `atlas.summary` 가 `travel.view` 를 부르지 않는다(`atlas.py:141`). `web.atlas_view` 가 둘을 합친다. 응답 모양은 같다. `atlas.py` 맨 위의 `travel` 가져오기를 지운다 |
| `canon/cli.py`, `canon/mock.py`, `canon/atlas.py` | `towngen.OPTIONS` · `citygen.WARD_KINDS` · `moderngen.ZONES` 를 바로 읽지 않고 `atlas.MAKERS` 로. 생성기 모듈이 `ZONES`(구역 이름)를 같은 이름으로 내게 맞춘다 |

## 지도 데이터

바뀌지 않는다. `VERSION` 을 올리지 않는다.

## 규칙

- 함수 몸은 옮기기만 한다. 고치고 싶은 곳이 보이면 다음 일감으로 적는다.
- 순환 가져오기를 만들지 않는다. `python -c "import canon.web"` 이 돈다.

## 시험

- 스냅샷 시험이 그대로 통과한다: `tests/test_mapgen.py`, `tests/test_citygen.py`, `tests/test_moderngen.py`.
- `tests/test_travel.py` 의 프롬프트 블록 시험이 문구 그대로 통과한다.
- 새 시험 하나: 지도 모듈의 가져오기 그래프에 순환이 없고, 생성기끼리 가져오지 않는다(`ast` 로 `from . import` 를 읽는다).
- `python scripts/make_openapi.py` 뒤 `openapi.json` 에 바뀐 곳이 없다.

## 문서

AGENTS.md 의 `towngen` · `citygen` · `moderngen` · `travel` · `atlas` 줄과 새 모듈 줄. DESIGN.md 지도 절의 `towngen.CATEGORIES` 언급. [modules.md](../modules.md) 의 1 · 2절 표와 그림.

## 확인하지 못할 것

Swift 빌드(맥). API 가 같으면 영향이 없다.
