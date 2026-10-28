# 08. 현대 장소 종류

상태: 설계 · 계획: [plan.md](../plan.md) 의 8번 (차례 미정)

## 목표

현대 동네 지도 만들기에서 장소 종류를 현대 이름(편의점, 역, 학교, 아파트 …)으로 고른다. 지금 종류 목록은 중세 마을 것(`towngen.CATEGORIES`: 신전, 주막, 대장간 …)이고, 현대 동네 생성기는 그 id 를 현대 자리로 바꿔 읽는다(지도 만들기 칸 안내: '주막은 호텔, 신전은 교회, 장터는 마트 자리'). PR #139 는 id 를 그대로 두고 프롬프트에 현대 자리를 적었다.

## 정할 것

1. id 를 새로 둘지 — 추천: 현대 종류는 새 id 를 둔다(`convenience`, `station`, `school` …). 장소 종류 표(`placekinds`, 01)에 시대(`era`)를 붙이고, 지도 종류가 고른 시대의 종류만 보인다. 옛 id 로 저장된 `MapSpec.places` 는 대응표로 읽는다.
2. 현대 종류 목록 — 추천: `bldgs.MODERN` 의 쓰임에서 장소로 자주 쓰는 것(편의점, 카페, 식당, 학교, 학원, 병원, 경찰서, 역, 아파트, 빌라, 회사, 공원, 교회, 시장).

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/placekinds.py` (01) | 현대 종류와 이름에서 찾는 낱말(`classify`) |
| `canon/moderngen.py` | 종류마다 자리 규칙을 새 id 로 |
| `canon/pipeline.py` · `prompts.py` | AI 설정 제안이 지도 종류에 맞는 id 만 받는다 (#139 의 `moderngen.PLACE_KINDS` 를 대신한다) |
| `canon/static/atlas.js` | 지도 종류를 바꾸면 종류 드롭다운도 바뀐다 |

## 지도 데이터

`spots[].kind` 에 새 id 가 온다. 현대 동네 생성기 `VERSION` 을 올리고 스냅샷을 고친다.

## 시험

- 이름에서 종류 찾기: '편의점' → `convenience`, '강남역' → `station`.
- 옛 id 로 저장된 입력이 같은 자리를 낸다.

## 문서

DESIGN.md '현대 동네 생성기' 절, AGENTS.md 의 moderngen · towngen 줄.

## 확인하지 못할 것

실제 Gemini 가 새 id 를 고르는지(키 없음).
