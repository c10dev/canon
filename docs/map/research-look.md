# 지도 모양 리서치: 작가가 쓰고 싶은 지도

지도 화면의 그림과 기능을 작가에게 매력 있게 만들 방법을 조사한 제안 문서다. 다음 일감을 고르는 근거로 쓴다. 코드는 고치지 않았다.
조사는 2026-10-29 에 브랜치 `claude/map-stack`(초안 PR [#148](https://github.com/c10dev/canon/pull/148)) 위에서 했다. 줄 번호는 이 브랜치의 `canon/static/atlas.js` 기준이다.

## 1. 결론

지금 지도는 생성기 그림은 탄탄하지만 '지도다운 장식'과 '이야기 겹'이 약하다. 축척 · 나침반 · 범례가 없고, 이름표 · 인물 · 동선이 화풍과 따로 논다.
빨리 효과가 큰 다섯 가지는 아래다. 모두 화면 파일만 고치고 지도 데이터 형식은 바꾸지 않는다.

1. 지도 장식 한 벌: 축척 막대 · 나침반 · 제목 틀 · 출처를 지도 그림 안에 그린다 (작음).
2. 이름표 충돌 보강: 인물 표가 장소 이름을 덮지 않게 하고, 같은 구역 이름이 되풀이되지 않게 한다 (작음).
3. 화풍을 따라가는 동선 · 핀: 흑백 인쇄는 점선 무늬, 양피지는 잉크 색, 동선에는 방향 화살표와 화 번호를 단다 (작음~보통).
4. 장소 종류 아이콘과 범례: 모든 장소가 같은 검은 점인 것을 바꾼다 (보통).
5. 현대 지도 화풍: OpenStreetMap · 현대 동네에 판타지 지붕 색 대신 네이버 · 카카오식 무채색 건물과 길 위계를 쓴다 (보통).

## 2. 지금 상태

### 2.1 그림 구조 (코드에서 읽은 것)

- 화풍 4종 `ATLAS_STYLES`(`atlas.js:20`): 기본 · 양피지 · 밤(불 켜진 창 `lamps`) · 흑백 인쇄(선 굵기 `lw` 1.8). 색은 CSS 변수 묶음 `.at-map.st-*`(`atlas.js:1760` 부근)로 바꾼다. 단축키 1~4, 브라우저에만 기억한다.
- 화풍은 마을 데이터 그림에만 걸린다. 핀 · 이름표 · 동선 · 인물 표는 화풍과 상관없는 색을 쓴다(`ATLAS_COLORS`, `atlas.js:61`, `atlasColor` `atlas.js:495`).
- 겹(`ATLAS_LAYERS`): 나무 · 밭 · 그림자 · 집 번호 · 이름 · 구역 · 쓰임 · 길 이름.
- 그리는 차례(`atlasVillageSvg`, `atlas.js:300`): 땅 → 밭(이랑 무늬 `pattern`) · 녹지 · 광장 → 구역 → 물(모래톱 + 물결 두 줄) → 섬(`land`) → 강 → 길(테두리 + 길 색) · 다리 → 성벽 · 탑 → 건물(그림자 · 4색 지붕 · 박공 어두운 반쪽 · 마루선, 평지붕은 `flat`) → 쓰임 색 → 밤 불빛 → 나무(그림자 · 수관 · 밝은 점) → 집 번호 → 출처 글.
- 지붕 색은 건물 번호 해시로 4색 중 하나다(`atlas.js:400`). OSM · 현대 동네도 같다(박공만 뺀다, `atlas.js:394`).
- 밤 불빛은 건물 열에 일곱쯤 무게중심에 하나씩 그린다(`atlas.js:436`). 건물 크기 · 쓰임과 상관없다.
- 이름표: 장소 이름표는 점 둘레 여덟 자리 → 먼 고리 + 지시선(`atlasLabels`, `atlas.js:784`). 구역 이름(`atlasWardLabels`, `atlas.js:282`)과 길 이름(`atlasStreetLabels`)은 장소 이름표가 차지한 상자를 비켜 간다. 같은 길 이름은 화면 폭 1/4 안에 하나(README 2026-10-29 규칙). 길 이름 각도는 서버가 -90°~90° 로 맞춘다(`bldgs.py:450`).
- 인물 표는 이름표를 놓은 뒤에 그리고 차지한 상자에 넣지 않는다(`atlas.js:617`).
- 글꼴은 앱 산세리프 하나다. 앱에는 `--serif: 'Noto Serif KR'`(`app.css:29`)과 토스페이스 이모지(`.tf`)가 이미 있다.
- 지도 안에는 축척 · 나침반 · 범례 · 테두리가 없다. 축척은 이동 시간 칸의 글('지도 크기를 약 …로 셈해요')로만 보인다(`atlas-travel.js:14`). 제목은 HTML 상자(`atlasTitleBox`)이고 내보내기 때만 SVG 글로 넣는다(`atlas-export.js`).
- SVG 필터(`filter`, `feTurbulence`)와 애니메이션은 쓰지 않는다.
- 내보내기(`atlasExportSvg`)는 계산된 CSS 를 정해진 속성 목록(`fill` · `stroke` · 글꼴 등)만 옮겨 적는다. `filter` · `mask` 는 목록에 없다.

### 2.2 스크린샷

mock 서버(`CANON_LLM=mock`)에 작품 하나를 만들고 장소 9곳과 인물 셋의 화별 위치를 손으로 넣었다. 생성기 지도는 시드를 고정했다(마을 7, 바다 · 도시 11 · 현대 동네 5). OSM 세 곳은 웹 화면에서 파일을 올렸고, 장소 자리는 길 꼭짓점에서 골라 넣었다(실제 그 자리의 장소가 아니다). 화면 폭 1440px, 지도 칸만 찍었다.

스크린샷은 저장소 밖 `/tmp/playwright-mcp/look/` 에 있다.

| 파일 | 내용 |
|---|---|
| `sheet-village.png` | 마을 생성기, 화풍 4종 (기본 · 양피지 / 밤 · 흑백) |
| `sheet-city.png` | 도시 생성기, 화풍 4종 |
| `sheet-modern.png` | 현대 동네 생성기, 화풍 4종 |
| `sheet-mangwon.png` · `sheet-gangnam.png` · `sheet-haeundae.png` | OSM 망원 · 강남 · 해운대, 화풍 4종 |
| `sheet-zoom.png` | 확대: 마을 ×(+3번) · 도시 ×(+3번) · 강남 ×(+2번) |
| `<지도>-<화풍>.png` | 위 묶음의 낱장 24장 (예: `city-night.png`) |
| `page-haeundae.png` | 지도 화면 전체 (옆 칸 포함) |

### 2.3 약한 점

| # | 약한 점 | 근거 스크린샷 | 코드 |
|---|---|---|---|
| W1 | 축척 · 나침반 · 범례가 없다. 지도 이름은 늘 '이름 없는 마을 · 도시 · 동네'로 보인다. | 모든 장 | `atlasSvg`, `atlasTitleBox` |
| W2 | 인물 표가 장소 이름을 덮는다. 현대 동네 기본에서 '수산시장'이 '수신 (도) 장'으로 읽힌다. | `modern-base.png` 가운데 아래 | `atlas.js:617` (표를 `taken` 에 넣지 않음) |
| W3 | 도시 구역 이름 '상인'이 한 화면에 열 번 넘게, '빈민'이 다섯 번쯤 되풀이된다. 이야기 장소 이름이 묻힌다. | `city-base.png` | `atlasWardLabels` (같은 이름 거르기 없음) |
| W4 | 동선 · 인물 색이 화풍을 따르지 않는다. 흑백 인쇄에 파랑 · 주황 선이 남고, 양피지에도 같은 색이다. | `*-print.png`, `*-parchment.png` | `ATLAS_COLORS`, `.at-trail` |
| W5 | 동선이 가늘고 반투명(`opacity .6`)이라 길 색과 섞인다. 방향 · 화 순서가 보이지 않는다. 두 인물이 같은 길을 가면 선이 겹친다. | `zoom-gangnam.png`, `gangnam-base.png` | `atlas.js:556` 동선, `.at-trail` (`atlas.js:1923`) |
| W6 | 모든 장소가 같은 검은 점이다. 등대 · 시장 · 성당이 구분되지 않는다. | 모든 장 | `atlas.js:596` |
| W7 | OSM · 현대 동네 건물도 판타지 지붕 4색(주황 · 갈색 · 청회 · 황토)을 해시로 받는다. 해운대 엘시티 부지(건물 597번, 넓이 약 23,725㎡, 쓰임 hotel)는 진회색 덩어리 하나로 보인다. 층수가 그림에 없다. | `haeundae-base.png` 오른쪽, `gangnam-base.png` | `atlas.js:400` |
| W8 | 밤 화풍 불빛이 건물마다 가운데 점 하나라, 강남 업무 건물에 점이 격자처럼 박힌다. 도시는 노란 점이 모래처럼 뿌려진다. | `gangnam-night.png`, `city-night.png` | `atlas.js:436` |
| W9 | 양피지가 '색만 바꾼 기본'이다. 종이 결 · 테두리 · 해칭이 없고 바다는 평평한 회녹색이다. 밭 둘레 나무가 같은 크기 원을 줄지어 놓아 구슬 목걸이처럼 보인다. | `village-parchment.png`, `village-base.png` | `.st-parchment` (`atlas.js:1803`), 나무 `atlas.js:449` |
| W10 | 도시 확대 화면에 '57번 거리', '53번 골목', '60번 거리'처럼 번호 이름이 많다. | `zoom-city.png` | `bldgs._name_streets` |
| W11 | 모든 글자가 앱 산세리프다. 지도 제목 · 구역 · 장소 · 길 이름의 위계가 굵기와 크기로만 나뉜다. | 모든 장 | `.at-name`, `.at-v-ward-label`, `.at-v-street-label` |
| W12 | 양피지 · 밤을 OSM 과 현대 동네에도 그대로 씌운다. 현대 지도는 양피지에서 '세피아 사진'처럼 보이고, 현대 지도다운 화풍은 없다. | `mangwon-parchment.png`, `modern-parchment.png` | `ATLAS_STYLES` |

잘된 점도 적어 둔다. 마을 · 도시는 지붕 박공 · 그림자 · 이랑 무늬 · 성벽 탑으로 첫눈에 '지도답다'(`zoom-village.png`, `zoom-city.png`). 밤 화풍은 분위기가 확실하다. 흑백 인쇄는 선이 또렷해 출력용으로 쓸 만하다. OSM 출처 글은 네 화풍 모두 오른쪽 아래에 보인다.

## 3. 참고 조사

웹 조사는 하위 에이전트가 WebSearch · WebFetch 로 했다. '(검색 요약)'은 페이지를 열지 못하고 검색 결과 요약만 본 것이다. '(미확인)'은 근거를 찾지 못한 것이다.

### 3.1 판타지 지도 도구

| 도구 | 무엇이 지도를 예쁘게 만드나 | 작가에게 쓸모 있는 것 | 라이선스 |
|---|---|---|---|
| Watabou 도시 · 마을 생성기 ([도시](https://watabou.itch.io/medieval-fantasy-city-generator), [마을](https://watabou.itch.io/village-generator)) | 지붕 디테일, 구역 보기, 숲, 색 스타일 프리셋 · 색약 · 고대비 모드. 마을은 땅 색 · 길 폭 · 외곽선 · 나무 밀도를 고친다. | PNG · SVG · JSON 내보내기, 퍼머링크. 도시는 3D City Viewer. | 만든 지도는 마음대로 써도 되고 출처 표기는 권장. 옛 도시 생성기 코드 [TownGeneratorOS](https://github.com/watabou/TownGeneratorOS) 는 GPL-3.0. 마을 생성기 코드는 공개하지 않음. |
| [Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) | 요소마다 색 · 선 · 필터, 지도 전체 색 필터. 옛 판의 산 · 숲 기호(검색 요약). | 레이어 프리셋(정치 · 문화 · 종교 등)과 사용자 프리셋 저장(검색 요약), 마커 · 메모 · 문장(emblem). | [MIT](https://raw.githubusercontent.com/Azgaar/Fantasy-Map-Generator/master/LICENSE) |
| Inkarnate | 낡은 손그림 parchment 스타일, Sepia · Night 필터(검색 요약). | — | 마켓 에셋은 기본 비상업, 에셋 따로 뽑기 · 재배포 금지([약관](https://inkarnate.com/marketplaceTerms)). 본체 상업 조건(미확인). |
| [Wonderdraft](http://wonderdraft.net/) | 자동으로 다듬은 해안선, 프리셋 이름표, 기호 묶어 칠하기, 큐레이션한 기본 테마. 이름표 glow(검색 요약). | 클릭 몇 번으로 강 · 길. | 한 번 결제, 상업 추가 비용 없음. |
| [Dungeondraft](https://dungeondraft.net/) | 조명 시스템, 물체 흩뿌리기. | VTT 내보내기. | 직접 만든 지도는 상업 이용 가능. 제3자 에셋 팩은 팩마다 다름. |

### 3.2 작가용 세계관 도구

| 도구 | 기능 |
|---|---|
| [World Anvil 지도](https://www.worldanvil.com/learn/map-making/maps) | 글 · 선 · 다각형 핀, 핀이 문서나 다른 지도로 이어짐, 레이어별 핀, 스포일러를 막는 비밀 핀 · 레이어 (검색 요약, 페이지는 403 으로 열지 못함). |
| [World Anvil Chronicles](https://www.worldanvil.com/learn/chronicles/chronicles) | 지도 아래 가로 타임라인. 사건을 누르면 연결한 지도 마커로 화면이 옮겨 간다. 중요도는 핀 모양, 종류는 아이콘 (검색 요약). |
| [Campfire 지도](https://campfirewriting.com/interactive-maps) | 이야기 요소 · 다른 지도로 잇는 핀, 아이콘 수백 종, 넓은 영역 핀(Zones), 단위를 고르는 자로 인물이 지나간 길 길이 재기, 핀 종류 범례, 나침반, 레이어. [Reedsy 리뷰](https://blog.reedsy.com/campfire-write-review/)는 축척을 정해 이동 시간을 맞춰 보는 데 쓸모 있다고 평한다. |

Canon 은 이미 이야기 장소 · 화별 인물 동선 · 이동 시간 검사 · 독자 시점 가리기가 있다. 세 도구에 없는 강점이다. 빠진 것은 핀 아이콘 · 범례 · 영역 핀 · 지도 아래 타임라인 · 나침반이다.

### 3.3 현대 지도 스타일

| 대상 | 배울 것 | 라이선스 |
|---|---|---|
| [Stamen Watercolor 만드는 법](https://stamen.com/watercolor-process-3dd5135861fe/) | 겹마다 마스크 → 가우시안 블러 → Perlin 노이즈 → threshold 로 가장자리를 울퉁불퉁하게, 스캔한 수채 질감을 씌우고 반전 마스크로 가장자리를 어둡게. | 원본 타일 CC BY 4.0, 생성 코드 ISC, Toner · Terrain 스타일시트 CC BY-NC-SA 4.0 ([Stadia 출처 페이지](https://stadiamaps.com/attribution/)). |
| [Stamen Toner](https://stamen.com/work/maps-stamen-com/) | 흑백만 쓰고 핵심만 남긴 바탕 지도. 다른 데이터 겹의 바탕. | 위와 같음 |
| [Felt](https://felt.com/blog/map-backgrounds-and-styling-controls) | 경로 끝 모양(endcap), 점선 · 파선, 겹친 투명도. 핀 · 선 · 경로 · 영역 주석([도움말](https://help.felt.com/annotations/annotations), 검색 요약). | 상용 SaaS (미확인) |
| [MapLibre 스타일 명세](https://maplibre.org/maplibre-style-spec/layers/) | 이름표 우선순위 `symbol-sort-key`, 여러 자리 시도 `text-variable-anchor`, 선 따라 글 `symbol-placement: line` · 꺾임 한도 `text-max-angle` 45°, 자간 `text-letter-spacing`, 겹침 기본 금지(`*-allow-overlap` false, [Mapbox 도움말](https://docs.mapbox.com/help/dive-deeper/optimize-map-label-placement.md) 검색 요약). | 명세는 참고만 |
| 네이버 · 카카오 지도 | 공항 · 역 · 터미널 따로 아이콘, 색약용 노선도([네이버](https://navercorp.com/media/pressReleasesDetail?seq=29035), 검색 요약). 큰길 옅은 노랑, 버스 · 지하철 아이콘 나눔([사용자 글](https://ditoday.com/?p=80937), 비공식 검색 요약). 공식 팔레트 · 아이콘 체계(미확인). | 참고만 |

### 3.4 손그림 기법과 지도 관례

- [rough.js](https://awesome.ecosyste.ms/projects/github.com%2Frough-stuff%2Frough): MIT, SVG · Canvas 손그림 선(검색 요약). Canon 화면 파일은 외부 JS 의존이 없다. 쓰려면 의존을 하나 더하는 결정이 필요하다.
- SVG `feTurbulence` + `feDisplacementMap`: 선을 흔드는 필터. 예시 값 fractalNoise baseFrequency≈0.02, 2 octaves, scale≈1.5. 글자는 필터 밖에 둬야 선명하다(검색 요약, [예시](https://instagit.com/cathrynlavery/diagram-design/how-do-i-create-a-sketchy-hand-drawn-variant-of-a-diagram.md)).
- 이름표 관례([Making Maps](https://colorado.pressbooks.pub/makingmaps/?p=97)): 영역 이름은 자간을 벌려 영역 안에 펼친다. 긴 선(강) 이름은 자간을 벌리지 않고 되풀이한다. 곡선은 완만하게.
- 곡선 글자([Red Blob Games](https://www.redblobgames.com/blog/2024-10-09-sdf-curved-text/)): Imhof 는 이름을 영역 가로축을 따라 휘어 펼치라고 권한다. 휘는 방향에 따라 기준선을 바꾼다.
- 나침반 · 축척 막대 · 제목 틀(cartouche)은 한 모서리에 모아 범례 자리를 만든다([ProFantasy 포럼](https://forum.profantasy.com/discussion/comment/13649)).

## 4. 제안

빨리 효과가 큰 순서다. 크기는 작음(하루 안, 화면 파일 한두 곳), 보통(며칠, 화면 여러 곳이나 서버 조금), 큼(스키마 · 생성기 · 새 의존)이다.
'규칙'은 [README.md](README.md) 의 정한 규칙과의 관계다. '충돌'은 사용자와 다시 정해야 하는 것이고, '맞춤'은 그 규칙을 지키려고 따로 챙길 것이다.

| # | 무엇을 | 왜 (배운 곳) | 고칠 모듈 | 크기 | 위험 | 규칙 |
|---|---|---|---|---|---|---|
| P1 | **지도 장식 한 벌.** 오른쪽 아래(또는 고른 모서리)에 축척 막대(50 · 100 · 200 m 처럼 둥근 값)와 북쪽 화살표, 왼쪽 위에 제목 틀(지도 이름 · 인구), 출처 글을 같은 틀 안에 그린다. 겹 '장식'으로 끄고 켠다. 확대하면 축척 막대 값이 바뀐다. | W1. Campfire 나침반 · 범례, Wonderdraft 나침반, ProFantasy 제목 틀 관례. 축척 막대는 Campfire 자와 Reedsy 리뷰가 말한 '거리로 이동 시간 맞춰 보기'를 지도 위에서 바로 보게 한다. | `atlasSvg` 끝(확대에 따라 `sc` 크기), `atlas-export.js` 의 제목 글을 이 틀로 바꿈, `ATLAS_LAYERS`. m 단위는 `W / v.w` 와 `Atlas.meters`(Watabou 파일) | 작음 | 축척을 모르는 지도(배경 그림, 모눈)는 축척 막대를 빼야 한다. 북쪽은 지도 데이터의 위쪽으로 가정한다(OSM 은 북이 위, 생성기는 정해진 북이 없음). | 맞춤: OSM 출처 글을 틀 안으로 옮겨도 지우지 않는다(2026-10-28). 빈 블록을 채운 지도는 긴 출처 글(`FILLED_SOURCE`)이 들어갈 폭이 필요하다. |
| P2 | **이름표 충돌 보강.** (a) 인물 표 상자를 이름표보다 먼저 `taken` 에 넣거나, 이름표가 표를 비켜 간다. (b) 같은 구역 이름은 화면 폭 1/4 안에 하나만(`atlasLabelPick` 재사용). (c) 우선순위를 '이야기 장소 > 구역 > 길'로 고정하고 적어 둔다. | W2 · W3. MapLibre `symbol-sort-key` · 겹침 기본 금지. | `atlasLabels`(`atlas.js:784`), `atlasWardLabels`(`atlas.js:282`), 인물 표(`atlas.js:617`), `atlasLabelPick` | 작음 | 화면 시험(`tests/test_atlas_js.py`)이 섹션 주석으로 자르는 구간을 건드릴 수 있다(modules.md 6절). | 맞춤: 2026-10-29 길 이름 1/4 규칙을 구역 이름에도 넓히는 것이라 사용자에게 알린다. |
| P3 | **화풍을 따라가는 동선 · 핀 · 인물 표.** 흑백 인쇄는 검정 + 인물마다 다른 점선 무늬, 양피지는 잉크 색 열 개(적갈 · 남색 · 먹색 …), 밤은 밝은 색 + 은은한 빛. 동선 굵기를 키우고 불투명하게, 바깥 테두리(halo)로 길 색과 떼어 놓는다. 방향 화살표(`marker-mid`)와 갈아탄 장소마다 작은 화 번호 점. | W4 · W5. Felt 의 끝 모양 · 점선 · 겹친 투명도, 인쇄 지도 관례(흑백은 색 대신 선 무늬). | `ATLAS_COLORS` · `atlasColor` → 화풍별 색 변수(`--v-ink0…9`), `.at-trail` CSS, `<marker>` 를 `defs` 에, `atlas.js:556` 동선 | 작음~보통 | 색만으로 인물을 나누던 것을 무늬로도 나누므로 옆 칸 인물 목록 색 견본도 함께 바꾼다. 화살표가 많은 도시 동선에서 지저분할 수 있어 확대 배율로 줄인다. | — |
| P4 | **장소 종류 아이콘과 범례.** 장소 종류(`placekinds.CATEGORIES`: 여관 · 신전 · 시장 · 부두 · 우물 …)마다 작은 기호를 핀 안에 그린다. 지도 한 모서리에 '이 지도의 장소' 범례. 지금 화에 나온 장소(`hot`)는 기호를 키운다. | W6. Campfire 아이콘 · 범례, World Anvil 핀 종류, 네이버 역 · 터미널 아이콘. | 새 기호 표(화면 파일 하나, SVG path), `atlas.js:596` 장소 그리기, 서버 `atlas.places` 에 종류(`placekinds.classify`)를 실어 보냄 | 보통 | 토스페이스 이모지를 쓰면 빠르지만, 내보낸 SVG · PNG 에 이모지 그림이 들어간다. 토스페이스 [저작권 안내](https://toss.im/tossface/copyright)의 '원본 그대로' 조건을 내보내기에도 지키는지 확인해야 한다. 직접 그린 단순 기호가 안전하다. | — |
| P5 | **현대 지도 화풍.** OSM · 현대 동네 전용 화풍 '현대'를 더한다. 건물은 무채색 두세 톤, 쓰임이 있는 건물만 옅은 쓰임 색, 큰 건물은 층수만큼 그림자를 길게. 길은 폭에 따라 큰길(옅은 노랑) · 보통 · 골목 색을 나눈다. 판타지 4색 지붕 해시는 `flat` 지도에서 쓰지 않는다. 양피지 · 밤은 그대로 두되 기본값을 '현대'로. | W7 · W12. 네이버 · 카카오(큰길 노랑, POI 아이콘, 검색 요약), Stamen Toner(바탕은 조용하게, 이야기 겹이 앞으로). | `ATLAS_STYLES`, 새 `.st-modern` 변수, `atlas.js:391~416` 지붕(`flat` 갈래), 길 `stroke` 를 폭으로 나눔, `blds[i].floors` 읽기 | 보통 | 화풍 단축키가 1~4 에서 1~5 로 는다. 지금 '기본'에 익숙한 작가는 OSM 지도 색이 바뀐다. | 맞춤: 빈 블록에 지은 건물은 흐린 색 · 점선(2026-10-28)을 새 화풍에서도 지킨다. 층수를 그릴 때 OSM 에 없는 층수(`levels` 0)를 지어 넣지 않고 기본 그림자로 둔다. |
| P6 | **밤 불빛을 건물 크기에 맞추기.** 작은 집은 창 하나, 큰 건물은 넓이에 비례해 여러 창을 건물 안에 흩고, 창고 · 헛간 쓰임은 끈다. 도시 성 밖 · 빈민 구역은 덜 켠다. | W8. Dungeondraft 조명 시스템. | `atlas.js:436` 밤 불빛, 쓰임은 `layers.useOf` | 작음 | 건물 수가 많은 도시에서 점 수가 늘어 그리기가 느려질 수 있다. 상한을 둔다. | — |
| P7 | **화 타임라인 띠.** 화 슬라이더 아래에 화마다 '누가 어디로 옮겼나 · 이 화에 나온 장소'를 칸으로 보인다. 칸을 누르면 그 화로 가고 그 장소로 화면을 옮긴다(기존 따라가기 `atlasFollowView`). 이동 시간 경고가 있는 화는 표시한다. | World Anvil Chronicles (지도 아래 타임라인, 사건 → 마커로 이동). Canon 은 화별 프레임(`frames`)과 이동 경고(`travel.view`)를 이미 받는다. | `atlasSlider`, 새 함수(띠 그리기), `atlas-travel.js` 의 경고 목록 읽기. 서버는 고치지 않음 | 보통 | 화가 200화 넘는 장편은 띠를 아크 단위로 접어야 한다. | — |
| P8 | **양피지 다듬기.** (a) 바탕 사각형 하나에만 `feTurbulence` 종이 결과 가장자리 어둡게(vignette), (b) 바다 · 호수에 해안선과 나란한 해칭 선, (c) 지도 둘레 이중 테두리, (d) 제목 · 구역 이름을 `Noto Serif KR` + 자간으로, (e) 밭 둘레 나무를 크기 · 간격을 흔들어 구슬 줄 느낌을 줄인다. | W9 · W11. Inkarnate parchment, Wonderdraft 테마 · 해안선, Making Maps 영역 이름 자간 관례, SVG 필터 기법. | `.st-parchment` 변수, `atlasVillageSvg` 의 `defs`(필터 · 해칭 무늬), 이름표 CSS, 나무 `atlas.js:449` | 보통 | 필터를 건물마다 걸면 1,131채 도시에서 느리다. 바탕 하나에만 건다. 내보내기는 `filter` 를 옮겨 적지 않으므로(`atlas-export.js` 속성 목록) PNG · SVG 에서 종이 결이 빠진다. 내보내기 시험이 필요하다. 나무 배치를 바꾸면 생성기 결과가 아니라 그림만 바뀌게 화면에서 흔든다(스냅샷 시험 영향 없음). | — |
| P9 | **독자 시점을 그림으로.** 지금은 아직 모르는 장소를 숨긴다. 대신 그 둘레를 안개(흐림 + 종이색)로 덮고, 슬라이더가 드러나는 화를 지나면 안개가 걷히는 짧은 움직임을 준다. | World Anvil 비밀 레이어(검색 요약), Dungeondraft 조명 · VTT 안개 관례. | `atlas.js` 의 `hidden` · `atlasKnown`, 새 `mask` | 보통 | 마스크는 내보내기에서 빠진다(P8 과 같은 문제). 움직임은 `prefers-reduced-motion` 이면 끈다. | — |
| P10 | **재생할 때 인물이 길을 따라 움직이기.** '처음부터 재생'에서 인물 표가 `row.route` 길을 따라 옮겨 간다. 지금은 화를 넘기면 순간 이동한다. | 지도 앱의 경로 미리보기 관례(출처 없음, 일반 기법). | `atlasFollow`(재생), 인물 표 그리기 `atlas.js:617`, `requestAnimationFrame` | 보통 | 다시 그리기(`atlasRedraw`)가 SVG 문자열 전체를 만든다. 움직임은 표 겹만 따로 고쳐야 느려지지 않는다. `prefers-reduced-motion` 을 지킨다. | — |
| P11 | **겹 묶음(프리셋).** '독자에게 보이는 지도'(독자 시점 · 이름 · 장식), '작가 작업용'(쓰임 · 집 번호 · 길 이름), '인물 동선만'(나무 · 밭 끔, 동선 굵게)을 한 번에 고른다. | Azgaar 레이어 프리셋. | `atlasLayersLoad` · `atlasLayerToggles` | 작음 | 겹 체크칸이 이미 많아 화면이 더 복잡해질 수 있다. 펼침 메뉴(`menuBtn`)로 넣는다. | — |
| P12 | **도시 번호 길 이름 줄이기.** '57번 거리'처럼 번호로 끝나는 이름을 줄이고 구역 · 지형 · 장소 이름에서 따온 이름을 늘린다. | W10. 참고 도구에서 배운 것이 아니라 스크린샷에서 찾은 문제다. | `bldgs._name_streets`, `bldgs.VERSION` 올림 | 작음~보통 | `bldgs.VERSION` 을 올리면 옛 지도 파일을 열 때 이름이 다시 지어진다(layout.md 판 규칙). 작가가 본문에 쓴 길 이름이 바뀔 수 있다. | 맞춤: 가상 지도만 해당. OSM 은 이름을 짓지 않는다(2026-10-28). |
| P13 | **영역 장소.** 장소를 점 대신 다각형(구역 · 숲 · 시장 광장)으로도 걸어, 그 안에 있으면 그 장소로 본다. | Campfire Zones, World Anvil 다각형 핀. | `MapPin` 스키마(새 칸, 기본값), `atlas.match` · `frames`, 이동 시간 거리 계산, 화면 그리기 · 끌기 | 큼 | 스키마를 바꾸면 옛 `project.json` 기본값이 필요하다(AGENTS.md). 이동 시간 검사의 거리 기준(점)이 바뀐다. | — |
| P14 | **수채화 · 손그림 화풍.** Stamen 과정(마스크 → 블러 → 노이즈 → threshold → 가장자리 어둡게)을 SVG 필터로 겹마다 흉내 내거나, rough.js 로 선을 흔든다. 질감은 직접 만든다(스캔 에셋 쓰지 않음). | Stamen Watercolor, rough.js, SVG 필터 기법. | 새 화풍, `atlasVillageSvg` 의 겹마다 필터 그룹, 내보내기 | 큼 | 느림(겹마다 블러 필터), 내보내기에서 빠짐, rough.js 는 첫 외부 JS 의존. 먼저 P8 의 바탕 필터 하나로 효과와 속도를 재 본다. | — |
| P15 | **지도에서 지도로.** 왕국 지도의 도시 핀을 누르면 그 도시 지도로 들어간다. | World Anvil · Campfire 지도 잇기. | `Project.atlas` 를 목록으로(스키마), 화면 전체 | 큼 | [plan.md](plan.md) 장기 후보 '지도 여러 장'이 먼저다. 충돌이 아니라 선행 조건이다. | — |

### 4.1 따로 사용자와 정할 것

- **OSM 지도 이름을 파일의 지명에서 읽기.** OSM 의 `place=*` · `name` 태그(예: 망원동)를 지도 이름 칸에 미리 채우면 '이름 없는 동네'(W1)가 줄어든다. 지어 넣는 것이 아니라 읽는 것이지만, 2026-10-28 규칙('실제 지도에는 이름 · 번지를 지어 넣지 않는다')과 같은 자리라 사용자가 정한다. 고칠 곳은 `osm.parse` · `atlas.village_title` 이고 크기는 작음이다.
- **현대 화풍을 OSM 기본값으로 바꾸기(P5).** 작가가 고르는 기본값이 바뀌는 것이라 사용자와 정한다.

## 5. 지킬 것

- 참고 도구의 에셋 · 코드는 쓰지 않고 아이디어 · 알고리즘만 참고한다. Watabou 옛 도시 생성기 코드는 GPL-3.0 이라 읽고 옮기지 않는다. Inkarnate · Dungeondraft 에셋 팩은 재배포가 금지되거나 팩마다 조건이 다르다. Stamen 수채 질감 타일(CC BY 4.0)도 가져오지 않고 같은 효과를 필터로 만든다.
- rough.js(MIT)는 가져다 쓸 수 있지만 첫 외부 JS 의존이다. 먼저 SVG 필터로 해 보고, 모자라면 의존을 더할지 정한다.
- OSM 지도의 화면 그림과 내보낸 그림에는 출처 글을 늘 그린다(README 2026-10-28). P1 · P8 · P14 처럼 테두리나 장식을 더할 때 출처 글이 가려지지 않게 한다.
- 실제 지도에는 이름 · 번지를 짓지 않는다(README 2026-10-28). P4 의 범례 · P12 의 이름 짓기는 가상 지도와 작가의 이야기 장소에만 쓴다.
- 지도 화면 문구는 해요체로 쓴다. 예: 겹 이름 '장식', 안내 '축척을 모르는 지도라 축척 막대를 그리지 않아요'.
- 화풍 색은 지금처럼 CSS 변수 묶음으로 바꾸고, 내보내기(`atlasExportSvg`)가 새 속성(`filter`, `mask`, `marker-*`)을 옮겨 적는지 함께 고친다.

## 6. 확인한 것과 확인하지 않은 것

확인한 것:

- 그림 코드: `canon/static/atlas.js`(화풍 · 겹 · 이름표 · 건물 · 물 · 섬 · 밤 불빛 · 동선 · 인물 표)와 `atlas-export.js` · `atlas-travel.js` 를 읽었다. 길 이름 각도 정리는 `bldgs.py:450` 에서 읽었다.
- 화면: mock 서버(포트 8600)에서 마을 · 도시 · 현대 동네 생성기 지도와 OSM 망원 · 강남 · 해운대를 화풍 4종으로 찍었다(24장 + 확대 3장 + 화면 전체 1장). W1~W12 는 그 스크린샷과 코드로 확인했다. W7 의 큰 건물은 해운대 지도 데이터에서 넓이를 계산해 찾았다.
- 웹: 3절의 출처는 하위 에이전트가 열거나 검색 결과로 본 페이지다. 표시한 '(검색 요약)' · '(미확인)'은 그대로 두었다.

확인하지 않은 것:

- 독자 시점 · 쓰임 겹 · 집 번호 겹 · 지도 만들기 미리보기 · 빈 블록 채우기 화면은 찍지 않았다. 이 문서의 제안과 직접 닿지 않아서다.
- 좁은 화면(휴대폰 폭)은 찍지 않았다. P1 장식과 P7 띠는 좁은 화면 배치를 따로 봐야 한다.
- SVG 필터 · 마스크의 실제 속도와 내보내기 결과는 재지 않았다. P8 · P9 · P14 를 시작할 때 1,131채 도시 지도로 먼저 잰다.
- World Anvil 페이지(403), Inkarnate 본체 상업 조건, Felt 라이선스, 네이버 · 카카오 공식 팔레트는 원문을 보지 못했다.
- 토스페이스를 지도 기호와 내보낸 그림에 써도 되는지는 저작권 안내 원문을 읽지 않았다(P4).
- 실제 작가가 어느 제안을 더 원하는지는 사용자만 판단할 수 있다.
