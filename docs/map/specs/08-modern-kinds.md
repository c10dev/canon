# 08. 현대 장소 종류

상태: 구현 (08a~08d, PR [#187](https://github.com/c10dev/canon/pull/187)) · 계획: [plan.md](../plan.md) 의 8번

## 목표

현대 동네 지도 만들기에서 장소 종류를 현대 이름(편의점, 역, 학교, 아파트 …)으로 고른다. 지금 종류 목록은 중세 마을 것(`towngen.CATEGORIES`: 신전, 주막, 대장간 …)이고, 현대 동네 생성기는 그 id 를 현대 자리로 바꿔 읽는다(지도 만들기 칸 안내: '주막은 호텔, 신전은 교회, 장터는 마트 자리'). PR #139 는 id 를 그대로 두고 프롬프트에 현대 자리를 적었다.

## 정할 것

1. id 를 새로 둘지 — 정함(2026-10-29, 추천안): 현대 종류는 새 id 를 둔다(`convenience`, `station`, `school` …). 장소 종류 표(`placekinds`, 01)에 시대(`era`)를 붙이고, 지도 종류가 고른 시대의 종류만 보인다. 옛 id 로 저장된 `MapSpec.places` 는 대응표로 읽는다.
2. 현대 종류 목록 — 정함(2026-10-29, 추천안): `bldgs.MODERN` 의 쓰임에서 장소로 자주 쓰는 것(편의점, 카페, 식당, 학교, 학원, 병원, 경찰서, 역, 아파트, 빌라, 회사, 공원, 교회, 시장). 옛 종류를 옮겨 받을 곳으로 호텔 · 공장 · 집을 더했다(아래 '종류 표').

## 종류 표 (08a 계약)

08b · 08c · 08d 는 이 절만 보고 일한다. 코드는 `canon/placekinds.py` 이고, 이 절과 다르면 이 절을 먼저 고친다.

### 바뀌지 않는 것

- `CATEGORIES` 는 지금과 같은 옛 종류 16개의 `(id, 화면 이름, 낱말)` 3칸 목록이다. 차례도 같다.
- `CATEGORY_IDS` 는 그 16개 id 다. 현대 id 는 들지 않는다.
- `classify(name, description)` 를 `era` 없이 부르면 지금과 똑같은 값을 낸다.
- `default_put` · `water_for` 는 그대로다.
- 그래서 08b~08d 가 하나도 고치지 않아도 마을 · 도시 · 현대 동네 지도는 지금과 똑같이 나온다.

### 시대와 지도 종류

| 지도 종류 `MapSpec.kind` | 시대 `era` |
|---|---|
| `village` 마을 · `city` 도시 · `realm` 왕국(아직 없음) | `old` |
| `modern` 현대 동네 | `modern` |

종류 하나는 시대 `old` · `modern` · `both`(두 시대 모두) 가운데 하나다. 실제 지도(OpenStreetMap)는 생성기가 아니라서 종류를 쓰지 않는다.

### 옛 종류 (`era` 는 `old`, 표 `CATEGORIES` 와 같다)

| id | 화면 이름 | 현대 동네에서 (대응표) |
|---|---|---|
| `center` | 마을 가운데 | `station` |
| `market` | 장터 · 광장 | `mart` |
| `well` | 우물 | `station` |
| `temple` | 신전 · 사당 | `church` |
| `inn` | 여관 · 주막 | `hotel` |
| `smith` | 대장간 · 공방 | `factory` |
| `mill` | 방앗간 | `factory` |
| `manor` | 저택 · 관아 | `house` |
| `home` | 집 · 가게 | `house` |
| `field` | 밭 · 농장 | 없음 (빈 글자) |

낱말은 지금 `CATEGORIES` 그대로다.

### 두 시대 모두 (`era` 는 `both`)

`shore` 나루 · 부두, `bridge` 다리, `river` 강가, `pond` 호수 · 연못, `forest` 숲, `far` 마을 밖. 화면 이름과 낱말은 지금 그대로이고, 대응표 없이 두 시대에서 같은 id 를 쓴다. 지금 현대 동네 생성기가 이 여섯을 이미 놓는다(하천 둔치 · 다리 · 공원 연못 · 공원 · 대로 끝).

### 현대 종류 (`era` 는 `modern`)

차례는 현대 동네의 드롭다운 · 프롬프트 차례이고, 낱말 길이가 같을 때 앞이 이긴다. 그 뒤에 `both` 여섯이 위 차례로 온다. id 가 `bldgs.MODERN` 에 있으면 같은 id 다(08b 가 건물 쓰임 `lt["use"]` 와 바로 견준다).

| id | 화면 이름 | 이름 · 설명에서 찾는 낱말 | 옛 지도에서 (대응표) | `bldgs.MODERN` |
|---|---|---|---|---|
| `station` | 역 | 역, 지하철역, 기차역, 전철역, 정류장, 버스정류장, 터미널, 버스터미널, 광장, 역전 | `center` | 있음 |
| `convenience` | 편의점 | 편의점, 슈퍼, 슈퍼마켓, 구멍가게 | `home` | 있음 |
| `cafe` | 카페 | 카페, 커피, 다방, 찻집, 빵집, 베이커리 | `home` | 있음 |
| `restaurant` | 식당 | 식당, 음식점, 레스토랑, 밥집, 맛집, 분식, 분식집, 국밥집, 고깃집, 횟집, 중국집, 술집, 주점, 포차, 호프 | `inn` | 있음 |
| `mart` | 시장 · 마트 | 시장, 전통시장, 재래시장, 마트, 대형마트, 백화점, 상가, 쇼핑몰, 아울렛 | `market` | 있음 (`mart`) |
| `school` | 학교 | 학교, 초등학교, 중학교, 고등학교, 대학, 대학교, 캠퍼스, 유치원, 교실 | `home` | 있음 |
| `academy` | 학원 | 학원, 교습소, 독서실, 스터디카페 | `home` | 있음 |
| `hospital` | 병원 | 병원, 의원, 한의원, 치과, 약국, 응급실, 보건소, 의료원 | `home` | 있음 |
| `police` | 경찰서 | 경찰서, 파출소, 지구대, 경찰 | `manor` | 있음 |
| `church` | 교회 · 성당 · 절 | 교회, 성당, 예배당, 성전, 절, 사찰, 법당 | `temple` | 있음 |
| `company` | 회사 | 회사, 사무실, 오피스, 본사, 지사, 사옥, 빌딩, 은행 | `home` | 있음 |
| `factory` | 공장 · 정비소 | 공장, 공업사, 정비소, 카센터, 창고, 물류센터, 작업장, 공방 | `smith` | 있음 |
| `hotel` | 호텔 · 모텔 | 호텔, 모텔, 여관, 여인숙, 게스트하우스, 펜션, 숙소 | `inn` | 있음 |
| `apartment` | 아파트 | 아파트, 단지, 오피스텔, 맨션, 주상복합 | `home` | 있음 |
| `villa` | 빌라 · 원룸 | 빌라, 연립, 다세대, 원룸, 고시원, 하숙, 자취방, 옥탑방, 반지하 | `home` | 있음 |
| `house` | 집 · 단독주택 | 집, 주택, 단독주택, 댁, 가게, 상점 | `home` | 없음 (`home` 단독주택 쓰임에 놓는다) |
| `park` | 공원 | 공원, 놀이터, 운동장, 산책로 | `forest` | 없음 (공원 블록) |

- 현대에서 찾지 못하면 `house` 다(옛 시대는 지금처럼 `home`).
- 호텔 · 공장 · 집은 사용자가 고른 14개 밖이다. 옛 `inn` · `smith` · `mill` · `manor` · `home` 을 옮겨 받을 자리가 있어야 해서 더했다.
- 한 글자 낱말 `역` · `절` · `집` 은 다른 낱말 안에도 있다(구역, 지역, 절벽, 중국집). 이름을 먼저 보고 설명은 이름에서 못 찾을 때만 보므로, '강남역' 은 `station` 이다(`역` 과 강가의 `강` 이 같은 길이라 앞 차례인 `station` 이 이긴다). 설명만 '…구역…' 이면 `station` 이 된다. 지금 옛 표의 `강` · `산` · `성` 과 같은 규칙이고, 고치지 않는다.

### 공개 함수와 값

```python
Kind = NamedTuple("Kind", [("id", str), ("label", str), ("era", str), ("words", tuple[str, ...])])
KINDS: list[Kind]              # 모든 종류 (옛 16 + 현대 17), id 는 겹치지 않는다
ERAS = ("old", "modern")
MAP_ERA = {"village": "old", "city": "old", "realm": "old", "modern": "modern"}
FALLBACK = {"old": "home", "modern": "house"}
OLD_TO_MODERN: dict[str, str]  # 옛 id → 현대 id (위 옛 종류 표). field 는 ""
MODERN_TO_OLD: dict[str, str]  # 현대 id → 옛 id (위 현대 종류 표)

def era_of(map_kind: str) -> str: ...                 # 모르는 지도 종류는 "old"
def kinds_for(map_kind: str) -> list[Kind]: ...       # 그 지도에서 보이는 종류, 위 표의 차례
def kind_ids(map_kind: str) -> list[str]: ...         # kinds_for 의 id
def label(kind: str) -> str: ...                      # 화면 이름. 모르는 id 는 그대로
def classify(name: str, description: str = "", era: str = "old") -> tuple[str, str]: ...
    # (종류 id, 찾은 낱말). 그 시대 종류(both 포함)에서만 찾는다. 못 찾으면 (FALLBACK[era], "").
    # 모르는 era 는 ValueError
def to_era(kind: str, era: str) -> str: ...
    # 저장된 종류를 그 시대 id 로. 이미 그 시대(both 포함)면 그대로, 아니면 대응표, 대응이 없거나 모르는 id 면 ""
CATEGORIES: list[tuple[str, str, tuple[str, ...]]]  # 옛 시대 3칸 목록 (바뀌지 않음)
CATEGORY_IDS: list[str]
def default_put(kind: str) -> bool: ...   # far 만 False (현대도 같다)
def water_for(rows: list[dict]) -> str: ... # 물 종류는 모두 both 라서 현대 행도 그대로 넣는다
```

`placekinds` 는 지금처럼 아무 모듈도 가져오지 않는다. 현대 화면 이름은 `bldgs.MODERN` 을 가져오지 않고 이 표에 따로 적는다.

### 뒤 조각이 쓰는 법

- 08b `moderngen`: 받은 `kind` 가 현대 id 가 아니면 `to_era(kind, "modern")` 로 바꾸고, 빈 글자면 `house` 로 본다. 현대 id 마다 자리 규칙을 둔다. 대응이 하나인 옛 id(`center` → `station`, `market` → `mart`, `temple` → `church`, `inn` → `hotel`)는 새 id 의 규칙을 옛 규칙과 같게 두면 옛 입력이 같은 자리를 낸다. 여럿이 하나로 모이는 `well` · `mill` · `manor` · `home` · `field` 는 자리가 바뀔 수 있으니 시험에 적는다. `PLACE_KINDS` 는 현대 id(`kind_ids("modern")`)마다 자리 글로 바꾸고, `tests/test_mapgen.py` 의 `set(moderngen.PLACE_KINDS) == set(towngen.CATEGORY_IDS)` 도 `kind_ids("modern")` 과 견주게 고친다. `VERSION` 을 올린다.
- 08c `pipeline.suggest_map` · `prompts.map_suggest_prompt` · `mock`: 종류 목록은 `kinds_for(지도 종류)` 의 `(id, label)` 이고, 받은 id 가 `kind_ids(지도 종류)` 에 없으면 뺀다. AI 가 지도 종류를 바꿔 제안하면 그 종류의 목록으로 거른다. mock 은 `classify(n, era=era_of(kind))`.
- 08d `atlas.gen_places` · `gen_info` · `atlas-gen.js` · `cli.py`: 장소 표는 `classify(이름, 설명, era_of(spec.kind))`, 저장된 `MapPlace.kind` 는 `to_era(m.kind, era)` 로 읽고 빈 글자면 찾은 값을 쓴다. 지도 화면의 종류 드롭다운은 `kinds_for` 로 지도 종류마다 내려보내고(예: `gen_info` 의 `kinds` 를 `{village: […], city: […], modern: […]}` 로), 지도 종류를 바꾸면 고른 값도 `to_era` 와 같은 대응표로 옮긴다. 명령줄의 종류 이름은 `label`.
- 물 기본값(`default_spec` 의 `water_for`)은 시대와 상관없이 그대로 쓴다. 현대 동네가 호수 · 바다를 하천으로 바꾸는 일은 지금처럼 `pipeline` · `cli` 가 한다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/placekinds.py` (01) | 현대 종류와 이름에서 찾는 낱말(`classify`) — 08a 에서 끝 |
| `canon/moderngen.py` | 종류마다 자리 규칙을 새 id 로 |
| `canon/pipeline.py` · `prompts.py` | AI 설정 제안이 지도 종류에 맞는 id 만 받는다 (#139 의 `moderngen.PLACE_KINDS` 를 대신한다) |
| `canon/atlas.py` · `static/atlas-gen.js` · `cli.py` (08d) | 지도 종류를 바꾸면 종류 드롭다운도 바뀐다. 장소 표 · 명령줄 종류 이름도 시대를 따른다. `schema.MapPlace.kind` 설명 글(`towngen.CATEGORIES`)도 고친다 |

## 지도 데이터

`spots[].kind` 에 새 id 가 온다. 현대 동네 생성기 `VERSION` 을 올리고 스냅샷을 고친다.

## 시험

- 이름에서 종류 찾기: '편의점' → `convenience`, '강남역' → `station`.
- 옛 id 로 저장된 입력이 같은 자리를 낸다.

## 문서

DESIGN.md '현대 동네 생성기' 절, AGENTS.md 의 moderngen · towngen 줄.

## 확인하지 못할 것

실제 Gemini 가 새 id 를 고르는지(키 없음).

## 08b 구현 메모 (2026-10-29, 브랜치 `claude/map-kinds-gen-715a7d`)

- `moderngen._place_spots` 가 종류를 `to_era(kind, "modern") or "house"` 로 읽는다. `spots[].kind` 는 현대 id 다.
- 자리 규칙은 현대 id 마다 하나다. 자리 글은 `moderngen.KIND_SPOTS`(현대 id 23개 = `kind_ids("modern")`).
  - 옛 규칙을 그대로 옮긴 것: `station`(옛 `center`, 역 광장), `mart`(옛 `market`), `church`(옛 `temple`), `hotel`(옛 `inn`), `factory`(옛 `smith` · `mill`), 두 시대 종류 여섯.
  - 새 규칙: `convenience` 는 편의점 건물, 없으면 대로변 상가나 빌라촌 모퉁이 가게. `cafe` · `restaurant` · `academy` · `hospital` · `company` 는 같은 쓰임 건물, 없으면 역에 가까운 상가. `police` 는 경찰서, 없으면 대로변 상가. `school` 은 학교 교사이고, 학교 터가 없으면 `missing`(까닭 `NEED["school"]`). `apartment` · `villa` 는 그 쓰임 건물 아무것. `house` 는 단독주택(`home`) 아무것, 없으면 빌라. `park` 는 옛 `forest` 와 같은 규칙(역에 가장 가까운 근린공원, 없으면 `NEED["park"]`).
- 가게 · 공공 종류(`moderngen.USE_OF`: 편의점 · 카페 · 식당 · 마트 · 학원 · 병원 · 경찰서 · 교회 · 회사 · 공장 · 호텔)는 놓인 건물의 쓰임(`parts[].use`)을 그 종류로 바꾼다. `bldgs.MODERN_PLACE_USE` 가 옛 id 로만 쓰임을 덮어서다. 그래서 건물 정보의 쓰임은 08b 전과 같다.
- `VERSION` 을 2 로 올렸다. 옛 입력 가운데 대응이 하나인 종류와 두 시대 종류는 같은 자리 · 같은 건물 쓰임에 놓인다(시험 `test_old_kinds_keep_their_spots`, seed 11 보통 하천에서 좌표를 견준다). 바뀌는 것:
  - `spots[].kind` 가 현대 id 다(`inn` → `hotel` 등).
  - `well` 은 광장과 역 사이(0.4)에서 광장 가운데(겹치면 옆)로.
  - `manor` 는 가장 큰 단독주택에서 아무 단독주택으로, `home` 은 빌라 · 아파트 · 단독주택에서 단독주택으로.
  - `field` 는 `missing`(밭이 없어요)에서 단독주택으로 놓인다. 계약(대응이 없으면 `house`)대로이고, `NEED["field"]` 는 지웠다.
  - 모르는 id 는 옛 `home` 에서 `house` 로.
  - `mart` 가 백화점에 놓이면 그 건물 쓰임이 `mart` 가 된다(건물 정보는 전에도 `mart` 로 보였다).
  - 요약 스냅샷(건물 · 길 · 블록 · 나무 수)은 바뀌지 않았다.
- 계약과 다르게 둔 것:
  - `PLACE_KINDS`(옛 id → 자리 글)를 현대 id 로 바꾸지 않고 그대로 두었다. 08c 가 `pipeline` 에서 읽기를 그만둔 뒤 지우고, 현대 자리 글은 `KIND_SPOTS` 를 쓴다. `tests/test_mapgen.py` 의 `set(moderngen.PLACE_KINDS) == set(towngen.CATEGORY_IDS)` 도 그때 고친다.
- 계약에 없던 것: `bldgs.MODERN_PLACE_USE` 는 옛 id 키만 있다. 새 id 지도는 위 `USE_OF` 로 맞췄고, 옛 id 키는 VERSION 1 지도를 읽을 때만 쓰인다.

## 08c 구현 메모

- `pipeline.suggest_map` 은 지도 종류(`atlas.MAKERS` 의 village · city · modern)마다 `placekinds.kinds_for` 의 `(id, label)` 목록을 프롬프트에 넘긴다. AI 가 지도 종류와 장소 종류를 한 번의 응답으로 고르기 때문에, 응답을 받기 전에는 어느 시대 목록을 보일지 정할 수 없다. 그래서 두 시대 목록을 다 보이고(목록이 같은 마을 · 도시는 한 절로 묶는다), 고른 지도 종류의 절에서만 id 를 고르게 한다. 계약의 '종류 목록은 `kinds_for(지도 종류)`'를 이렇게 읽었다.
- 받은 id 는 AI 가 고른 지도 종류(`MapSuggestion.kind`)의 `kind_ids` 로 거른다. 화면에서 고른 종류(`spec.kind`)가 아니다. 시대 밖 id 는 `to_era` 로 옮기지 않고 뺀다(계약대로). 빠진 장소는 지도 화면 · 명령줄에서 지금 값을 그대로 둔다.
- `prompts.map_suggest_prompt(p, rows, places, kinds, options, chosen)`: `kinds` 는 `{지도 종류: [(id, 이름)]}` 이고, 옛 인자 `modern_kinds`(`moderngen.PLACE_KINDS`)는 뺐다. 요구사항 줄의 예시 · 기본값도 시대마다 적는다: 근거가 없으면 마을 · 도시는 `home`, 현대 동네는 `house`(`FALLBACK`). 지도 자체를 가리키는 이름은 마을 · 도시 `center`, 현대 동네 `station`(`OLD_TO_MODERN["center"]`).
- `mock` 의 지도 제안은 화면에서 현대 동네를 골랐으면 `classify(이름, era="modern")`, 아니면 옛 시대로 고른다.
- 시험: `tests/test_map_suggest.py`(mock 의 시대별 id, 시대 밖 id 빼기, AI 가 지도 종류를 바꾼 경우, 명령줄 `map <작품> gen modern --ai`). `tests/test_mapgen.py` 는 옛 단언(`/ 현대 동네:` 글, `inn` 을 받는 현대 제안, 목록 인자)만 고쳤다.
- 08d 와 합치기 전에는 명령줄 `gen modern --ai` 가 저장하는 `MapPlace.kind` 는 현대 id 이지만, 미리보기의 종류 이름과 자리는 옛 `atlas.gen_places` 가 모르는 id 로 보고 다시 찾은 옛 종류를 쓴다. 08d 의 `to_era` 읽기가 이것을 고친다.
- 명령줄은 `a.kind or sug["kind"]` 라서 `gen modern --ai` 에 AI 가 village 를 답하면 옛 id 가 현대 지도 입력에 들어간다. 08d 의 `to_era` 읽기가 대응표로 옮긴다.

## 08d 구현 메모

브랜치 `claude/map-kinds-ui-46d9f2`. 고친 곳은 `atlas.py` · `static/atlas-gen.js` · `cli.py` 한 곳 · `schema.MapPlace.kind` 설명 글이다.

- 장소 표(`atlas.gen_places`): 시대는 `era_of(spec.kind)`, spec 이 없으면 마을(old). 종류는 `to_era(m.kind, era) or classify(이름, 설명, era)`. 빈 값 · 모르는 id · 대응 없는 id(`field` → 현대) 모두 찾은 값이다. 줄마다 시대별로 찾은 값 `found_in: {old, modern}` 을 더했다.
- `gen_info`: `kinds` 를 지도 종류별 `{village: [{id, label}], city: …, modern: …}` 로 바꿨다(옛 목록 모양은 없어졌다). `eras`(지도 종류 → 시대), `kind_to`(시대마다 모든 id → `to_era` 값, 대응 없으면 '')를 더했다. 화면이 대응표를 따로 적지 않게 서버에서 보낸다.
- 화면(`atlas-gen.js`): 드롭다운은 `atlasGenKinds(spec.kind)`. 지도 종류를 바꾸면(직접 고르기, AI 설정 제안이 종류를 바꿀 때) `atlasKindShift` 가 줄마다 옮긴다.
  - 계약과 다른 곳: 이름에서 찾은 값 그대로인 줄(`kind === found_in[옛 시대]`)은 대응표 대신 새 시대에서 찾은 값을 쓴다. 대응표로 옮기면 '골목 편의점'(옛 시대에서 집 · 가게)이 '집 · 단독주택'이 되고, 찾은 값을 쓰면 '편의점'이 된다. 작가가 고른 값(찾은 값과 다른 값)만 계약대로 `kind_to` 로 옮기고, 대응이 없으면 새 시대에서 찾은 값이다.
  - AI 설정 제안이 준 종류는 지금 고른 지도 종류의 시대로 옮겨 넣는다(`atlasGenToEra`: `kind_to`, 대응이 없으면 그 시대에서 찾은 값). 작가가 지도 종류를 직접 골랐고 AI 가 다른 시대를 고르면 AI 의 id 가 드롭다운에 없을 수 있어서다.
  - 놓기(`put`)가 옛 종류의 기본값(마을 밖만 끔)이면 새 종류의 기본값으로 바꾼다. 작가가 바꾼 놓기는 그대로다.
  - 서버는 계약대로 저장된 값을 늘 `to_era` 로 읽는다. 그래서 마을로 적용한 작품을 명령줄 `map gen modern` 으로 만들면 '골목 편의점'은 '집 · 단독주택'이고, 화면에서 지도 종류를 바꾸면 '편의점'이다.
- 지도 제목 기본값(`village_title`): 현대 동네는 '마을 가운데'가 없어서 `to_era("center", era)`(역) 종류 장소 이름을 쓴다.
- 명령줄: 장소 종류 이름은 `placekinds.label`(모든 시대).
- 시험: `tests/test_atlas_kinds.py`(장소 표 · 옛 id 대응 · `gen_info` 모양 · 제목 · 명령줄 · node 로 `atlasKindShift`), `tests/test_mapgen.py` 의 `kinds` 모양 한 줄.
- 08b 와 함께 합쳐야 한다: 이 브랜치만으로는 현대 동네 장소 표가 현대 id 를 보내는데 `moderngen` 이 옛 id 만 알아 모두 집 · 가게 자리에 놓는다(mock 서버 미리보기로 봤다).

## 합친 뒤 정리 (2026-10-29)

- 08b · 08c · 08d 를 `claude/map-stack` 에 합친 뒤 옛 자리 글 `moderngen.PLACE_KINDS` 와 그것을 보던 시험 줄(`tests/test_mapgen.py`)을 지웠다. 현대 자리 글은 `moderngen.KIND_SPOTS` 하나다.
