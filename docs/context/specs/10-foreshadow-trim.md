# 10. 열린 복선 블록 줄이기

상태: PR (2026-11-09, 확인 (가) 뒤 꼴을 바꿈) · 계획: [plan.md](../plan.md) 의 10번 · 먼저: 1(끝)

## 목표

장편 본문 쓰기 프롬프트의 '# 열린 복선' 블록이 짧아진다.
고른 복선을 JSON 대신 복선 하나에 한 줄(id · 심은 화 · 회수 예정 화 · 회수 범위 · 갈래 · 설명 전부)로 넣는다.
복선을 빼지도, 설명을 자르지도 않는다.
처음 계획(상위 K개 전문 + 나머지 설명을 자른 한 줄)은 확인 (가)를 넘지 못해 2026-11-09 에 바꿨다(아래 '바뀐 결정').
모델이 열린 줄기를 알고 모순을 피하게 하는 몫은 남긴다.
작가가 할 일은 늘지 않는다.
고르기는 저장된 데이터를 바꾸지 않는다.
따르는 정한 규칙: [README.md](../README.md) 의 2026-11-08 결정 Q34(섞은 꼴, 1순위) · Q35(두 가지 확인) · Q36(활성화 조건은 지금 만들지 않음).

### 왜 하나

- 2026-11-08 측정(일감 1)에서 열린 복선 블록이 쓰기 프롬프트의 가장 큰 낭비였다.
- 고른 열린 복선 가운데 본문이 잇지 않은 것이 75.0%(847/1,129)였다([README.md](../README.md) 의 측정 결과 줄).
- 그 낭비는 화마다 약 3,200자였다(결과 글의 표: 3,217자).
- 결과 글: `reports/컨텍스트 놓침 실측 2026-11-08.md`(커밋하지 않음).
- 같은 결과 글의 사람 표본에서 낭비로 센 복선 가운데 본문이 분명히 이은 것은 14%(26/192)였다.
- 그래서 대리값이 복선 낭비를 크게 세는 것은 맞지만, 사람 표본으로도 낭비가 대부분이다.
- 블록을 통째로 빼면 모델이 열린 줄기를 모르게 된다.
- 그래서 빼지 않고 줄인다(Q34).

### 지금 코드

- 고르기는 `canon/prompts.py` 의 `relevant_foreshadows(p, n)` 이다.
- 돌려주는 값은 (복선 목록, 뺀 수)다.
- 먼저 열린 복선(`status == "open"`)만 남긴다.
- 단편(`not p.serial`)은 열린 복선을 모두 돌려주고 뺀 수는 0 이다.
- 단편에는 거르기 · 상한 · 차례가 없다.
- 장편은 넷 가운데 하나에 맞으면 남긴다: 아크 `payoffs` 에 있음, `due_ep <= 아크 끝`, `scope == "series"`, `planted_ep >= min(아크 시작, n - FORESHADOW_RECENT)`.
- `FORESHADOW_RECENT` 는 30 이다.
- 남은 것을 `context.rank_foreshadows` 가 `foreshadow_rank` 차례로 `FORESHADOW_CAP`(25)개 고르고, 심은 화 차례로 다시 늘어놓는다.
- `foreshadow_rank`: 0 회수 예정이 이번 화이거나 지남(`due_ep <= n`) > 1 이번 아크 `payoffs` > 2 아크 안 회수 예정 > 3 작품 단위 > 4 부 단위 > 5 이번 아크에 심음 > 6 그 밖.
- 같은 순위면 3 · 4 는 오래된 것, 나머지는 최근 것이 먼저다.
- 뺀 수는 '열린 복선 전체 − 고른 수'라 거르기와 상한을 함께 센다.
- `payoff_ep`, `ForeshadowClue`, 플롯 글의 언급은 고르기에 쓰지 않는다.
- 이번 화 플롯의 `EpisodePlot.foreshadow_payoff`(이번 화에 회수하는 복선 id)도 고르기에 쓰지 않는다.
- 쓰기 프롬프트 블록은 `dump(fs)` 다.
- `Foreshadow` 에는 프롬프트용 직렬화기가 없어 모든 칸이 들여쓴 JSON 으로 찍힌다.
- 찍히는 칸: `id` · `description` · `planted_ep` · `payoff_ep` · `status` · `scope` · `due_ep` · `kind` · `public`.
- 이 블록에는 글자 예산(`context.BUDGET` 키)이 없다.
- 이 블록에는 개수 상한 25 만 있다.
- 복선 `BUDGET` 키는 플레이 장면의 `play_foreshadows`(900자) 하나뿐이다.

### 블록 자리와 캐시

- 장편 `serial_episode_context` 의 앞부분(`head`)은 `static_context` → 부 · 아크 → 접은 줄거리 → 이번 화 위치 → 사실 · 요소 · 인물 · 상태 · 관계 → '# 열린 복선' → 이번 아크 줄거리 → 이번 화 줄기 → 직전 화 원문 차례다.
- `write_head` 는 이 `head` 다.
- 파이프라인은 그 길이를 스토리보드 · 큐 시트 · 본문 쓰기가 함께 쓰는 캐시 경계(`llm.PREFIX_HINT`)로 넘긴다.
- 그래서 복선 블록을 바꾸면 그 블록부터 뒤의 앞부분이 바뀐다.
- `static_context` 는 바뀌지 않는다.
- 같은 화의 스토리보드 · 큐 시트 · 본문 쓰기 요청 셋의 복선 블록은 글자까지 같아야 캐시가 맞는다.
- 단편 `build_episode_context` 도 블록을 두지만 `write_head` 는 빈 글이라 캐시 경계가 없다.

## 정할 것

시작 전에 사용자와 정할 것이다.
추천안을 먼저 쓴다.
정하면 결과를 여기 적고 [README.md](../README.md) 의 정한 규칙에도 더한다.
2026-11-09: 사용자가 1~11 모두 추천안을 골랐다.
시작 값: K(`FORESHADOW_FULL`) 10, 한 줄 길이 N(`FORESHADOW_LINE`) 60자, 최근 칸(`FORESHADOW_RECENT_EPS`) 3화, 설명 겹침 문턱(`FORESHADOW_OVERLAP`) 2조각.
네 값은 확인 (가)에서 다시 정한다.

### 바뀐 결정 (2026-11-09, 확인 (가) 뒤)

- 확인 (가)에서 K 나누기는 어느 K(5~15) · 최근 칸(0 · 1 · 3 · 5) · 겹침 문턱(1 · 2 · 3)으로도 문턱을 넘지 못했다.
- 정확히 되돌린 81화 합계에서 K10 은 덮는 몫 78% · 줄어듦 31%, K15 는 83% · 25% 였다.
- 칸 차례를 세 가지로 바꿔도 K10 합계 덮는 몫은 77~79% 였다.
- subway-1-수정본은 화마다 고른 복선이 25개(상한)이고 본문이 화마다 약 7개를 이어서 상위 몇 개로는 덮지 못했다.
- 낭비의 큰 몫은 JSON 꼴이었다: 복선 하나에 붙는 키 · 따옴표 · 늘 같은 칸이 약 211자로 설명(평균 101자)보다 길었다.
- 그래서 사용자가 '모든 복선을 설명 전부와 함께 한 줄로' 를 골랐다.
- 이 결정은 정할 것 11(전문 꼴을 바꾸지 않는다)을 뒤집는다.
- 정할 것 1(K) · 3(신호와 차례) · 4(설명 자르기) · 10(K 를 바꾸는 ContextVar)은 버린다.
- 정할 것 7(프롬프트 보기)은 나눔이 없으니 뺀 복선 이름만 남는다.
- 정할 것 8 의 덮는 몫 문턱은 빼는 복선이 없어 늘 100% 다. 글자 문턱 40% 만 남는다.
- 정할 것 9 의 두 조건은 `fs_json`(예전 JSON 꼴)과 `fs_line`(한 줄 꼴)이다. 시험할 화는 열린 복선이 있는 장편 화다.
- 정할 것 2 · 5 · 6 은 그대로다: 고른 목록 안에서만 바꾸고, 단편과 다른 요청은 그대로다.
- 한 줄 꼴: `- {id} ({planted_ep}화에 심음, 회수 예정 {due_ep}화, 회수 범위 {이번 아크|이번 부|작품 전체}, {갈래}[ · 드러남]): {설명 전부}`.
- 회수 예정이 없으면 그 칸을 뺀다.
- 갈래는 `foreshadows.KINDS`(단서 · 판돈 · 제약 · 관객 · 금지선), 회수 범위는 `foreshadows.SCOPES` 의 한국어 이름이다.
- 늘 같은 칸(`status` open, `payoff_ep` 없음)은 뺀다.
- 설명의 줄바꿈은 띄어쓰기로 바꾼다.
- 시험 조건만 `prompts.FORESHADOW_JSON`(ContextVar)을 참으로 두어 예전 JSON 꼴을 쓴다.

1. K 값과 정하는 방식 (2026-11-09 버림)
   - 추천: `context.py` 의 고정 상수 `FORESHADOW_FULL` 하나로 둔다.
   - 작품 설정과 `BUDGET` 키는 두지 않는다.
   - 값은 확인 (가)(정할 것 8)의 흉내에서 문턱을 넘는 가장 작은 K 다.
   - 후보는 5 · 8 · 10 · 12 · 15 다.
   - 후보는 작품마다 고른 수의 분포를 먼저 본 뒤 다시 정한다(정할 것 8).
   - 까닭: 블록 예산을 작품마다 바꾸는 일은 일감 3 의 블록 설정이 맡는다.
   - 두 일감이 같은 값을 따로 두지 않는다.
   - 다른 안: `BUDGET["foreshadow_full"]` 글자 예산.
   - 이 안이면 일감 3 과 고칠 줄을 먼저 견준다([plan.md](../plan.md)).
   - 다른 안: 작품 설정.
   - 이 안은 스키마 필드가 더 생긴다.
2. 한 줄로 넣는 복선의 범위
   - 추천: 지금 고른 목록(장편 거르기 + 상한 25) 안에서만 나눈다.
   - 꼴은 전문 K개 + 나머지 한 줄이다.
   - 추천안에서는 지금 빠지는 복선이 새로 들어오지 않는다.
   - 블록은 지금보다 짧아지기만 한다.
   - 다른 안: 열린 복선 전체를 한 줄로 넣는다.
   - 이 안은 화수에 따라 블록이 끝없이 커져 장편 예산 원칙에 어긋난다.
   - 뺀 수(`fs_cut`)의 뜻은 지금 그대로다(거르기 + 상한으로 빠진 수).
3. 관련 신호와 차례(상위 K개를 고르는 차례) (2026-11-09 버림)
   - 추천 차례:
   - ① 이번 화 플롯의 `foreshadow_payoff` 에 있는 복선.
   - ① 은 K 와 상관없이 늘 전문이다.
   - ② 지금 `foreshadow_rank` 0~2(회수 예정이 이번 화이거나 지남, 이번 아크 `payoffs`, 아크 안 회수 예정).
   - ② 는 아크 기획이 정한 것이다.
   - ③ 이번 화 플롯 글에 id 가 나오거나 `description` 과 플롯 글이 겹치는 복선.
   - ④ 최근 3화 안에 근거 문장(`ForeshadowClue`)이 있는 복선.
   - ⑤ 최근 3화 안에 심은 복선.
   - ⑥ 나머지는 지금 `foreshadow_rank` 차례.
   - 같은 칸 안에서는 지금 `rank_foreshadows` 의 차례를 쓴다.
   - Q17 과 맞춤: ① ② 는 '늘 넣기'(기획이 정함), ③ 은 '키워드 직접 발견', ④ ⑤ 는 '유지'(최근)에 가깝고, ⑥ 은 지금 순위다.
   - 이 차례는 전문과 한 줄을 나눌 뿐 아무것도 빼지 않는다.
   - 그래서 이 차례는 Q17 의 뺄 차례와 부딪히지 않는다.
   - ④ ⑤ 는 이미 고른 목록 안의 차례만 정한다.
   - ④ ⑤ 는 목록에 넣을지를 정하지 않는다.
   - ④ ⑤ 때문에 `Activation` 모델이나 조건 칸을 더하지 않는다(Q36).
   - 확인 (가)는 ④ ⑤ 의 N = 1 · 3 · 5 를 '④ ⑤ 없음'과 견준다.
   - 2026-11-08 측정에서 'N화 유지(1화)'는 낭비를 47% 늘렸다([README.md](../README.md)).
   - 그래서 '④ ⑤ 없음'이 덮는 몫에서 지지 않으면 ④ ⑤ 를 뺀다.
   - ③ 의 id 는 플롯 글에서 낱말 경계로 찾는다(`context.grams` 는 한글만 본다. `fs-3-a1` 은 `fs-3-a12` 안에서 맞지 않는다).
   - ③ 의 `description` 겹침은 `context.grams`(한글 3글자 조각)로 센다.
   - ③ 의 겹침 문턱 값은 확인 (가)에서 고른다.
   - `elements.plot_text` 는 `foreshadow_plant` 를 넣지만 `foreshadow_payoff` 는 넣지 않는다.
   - 그래서 플롯 글에 나오는 id 는 대부분 이번 화에 새로 심는 복선의 id 이고, 그 복선은 열린 목록에 없다.
   - 그래서 ③ 의 id 맞춤은 드물게 맞는다.
   - ③ 의 몫은 대부분 `description` 겹침이 맡는다.
   - ③ 은 스토리보드와 큐 시트를 보지 않는다.
   - ③ 은 플롯 글(`elements.plot_text`)만 본다.
   - 까닭: 스토리보드는 스토리보드 요청 뒤에 생긴다.
   - 스토리보드를 보면 스토리보드 요청과 본문 쓰기 요청의 복선 블록이 달라져 캐시 경계가 깨진다.
   - ④ 의 '3화'와 ⑤ 의 '3화'는 확인 (가)에서 1 · 3 · 5 를 견줘 고른다.
   - 다른 안: 플롯 언급(③)을 빼고 지금 `foreshadow_rank` 만 쓴다.
   - 이 안은 가장 단순하지만 이번 화와의 관련을 보지 않는다.
4. 한 줄 요약을 어디서 얻나 (2026-11-09 버림: 설명을 자르지 않는다)
   - 추천: 새 LLM 호출 없이 `description` 을 결정적으로 자른다.
   - 꼴: `- {id} ({planted_ep}화에 심음, 회수 예정 {due_ep}화): {description 앞 N자}…` 다.
   - 회수 예정이 없으면 그 칸을 뺀다.
   - 자르는 길이 N 의 추천은 60자다.
   - 확인 (가)에서 `description` 길이 분포를 보고 N 을 다시 정한다.
   - N자보다 짧은 `description` 은 자르지 않고 '…'도 붙이지 않는다.
   - 같은 꼴의 앞선 예: `convert_prompt` 의 한 줄 꼴 `- id (N화에 심음, scope): description`.
   - 다른 안: `Foreshadow` 에 짧은 칸(`short`)을 두고 상태 변경안이 채운다.
   - 이 안은 LLM 응답 형식과 `canon/mock.py` 가 바뀐다.
   - 이 안에서 옛 복선의 짧은 칸은 비어 있다.
5. 단편에도 쓰나
   - 추천: 장편에만 쓴다.
   - 단편 경로는 바꾸지 않는다(AGENTS.md 의 단편 원칙).
   - 단편은 지금 열린 복선을 모두 넣는다.
   - 단편은 10~20화라 블록이 크지 않다고 보고 그대로 둔다.
   - 단편에도 쓰려면 사용자와 따로 정한다.
6. 같은 목록을 쓰는 다른 요청
   - 추천: 플롯 · 상태 변경안 · 검수 요청은 바꾸지 않는다.
   - 추천안에서 `relevant_foreshadows` 의 출력은 바뀌지 않는다.
   - 나누기는 쓰기 프롬프트 조립에서만 한다.
   - 그래서 `serial_plot_prompt`, `_serial_plot_parts`(플롯 대화), 장편 `state_prompt`, `play_view` 의 뺀 수는 지금 그대로다.
   - 상태 변경안은 복선 근거 문장을 뽑는다.
   - 상태 변경안의 전문 목록을 그대로 둬야 근거 문장 뽑기가 줄지 않는다.
   - 검수 요청에는 지금 복선 블록이 없다.
   - 상태 변경안이 검수 재료를 앞에 둘 때도 자기 '[열린 복선]' 블록을 둔다.
   - `context.FORESHADOW_CAP` 값은 바꾸지 않는다.
   - `storyline_prompt` 도 `FORESHADOW_CAP` 을 쓴다.
7. 프롬프트 보기(일감 3)에 무엇을 보이나 (2026-11-09: 전문 · 한 줄 나눔과 까닭은 없어짐)
   - 추천: 전문으로 넣은 복선과 한 줄로 넣은 복선을 나눠 보이고, 전문인 복선마다 까닭을 보인다.
   - 까닭 이름: '이번 화 회수', '아크 계획', '플롯에 나옴', '최근 근거', '최근 심음', '순위'.
   - 뺀 복선(거르기 · 상한)의 이름도 보인다(Q17).
   - 일감 3 이 먼저 머지되지 않으면 이 일감은 까닭을 돌려주는 함수만 두고, 화면은 일감 3 이 붙인다.
   - 일감 3 전에도 지금 프롬프트 길목(`GET /api/projects/{name}/episodes/{n}/prompt`)의 글에 나뉜 블록이 그대로 보인다.
8. 확인 (가)의 문턱: LLM 없이 줄어든 글자와 덮는 몫 (2026-11-09: 글자 문턱만 남음)
   - 추천 문턱: 블록 글자가 40% 이상 줄고, 본문이 이은 복선의 90% 이상이 전문 K개 안에 든다.
   - 40% 의 기준은 확인 (가)가 먼저 잰 지금 블록 글자 수다.
   - 줄어든 글자와 덮는 몫은 고른 수가 K 를 넘는 화만으로 센다.
   - 고른 수가 K 이하인 화는 블록이 지금과 같아(경계 사례) 줄일 몫이 없기 때문이다.
   - 작품마다 고른 수가 K 를 넘는 화의 몫을 함께 적는다.
   - 결과 글의 고른 열린 복선은 81화에 1,129개로 화당 평균 약 14개다.
   - 그래서 후보 K 는 작품마다 고른 수의 분포를 먼저 본 뒤 정한다.
   - 고른 수가 K 이하인 화가 대부분인 작품은 글자 문턱에서 빼고 덮는 몫만 본다.
   - '본문이 이은 복선'은 일감 1 의 대리값이다: 그 화의 `ForeshadowClue` 가 있거나 `payoff_ep` 가 그 화.
   - 덮는 몫의 분모는 `relevant_foreshadows(p, n)` 목록 안에 있는 '본문이 이은 복선'이다.
   - 그 목록 밖에 있는 '본문이 이은 복선'의 수는 따로 적는다.
   - 그 목록 밖의 복선은 K 와 상관없이 전문에 들 수 없다.
   - 흉내는 일감 1 의 되돌린 사본(`stattrial.before`)으로 n-1 화 끝 상태에서 한다.
   - 신호 ④ 는 `episode < n` 인 `ForeshadowClue` 만 읽는다.
   - 엄격한 정답(반영한 근거)과 느슨한 정답(작가가 체크를 푼 근거까지) 둘 다 센다(일감 1 의 정할 것 4).
   - 작품 기준: 넷을 합친 값과 독립 작품 셋(nsfw_saintess, subway-1-수정본, 불타는-세상에서-내-캠핑카만-진화한다) 각각이 문턱을 넘는다.
   - 까닭: nsfw_saintess-claude 는 nsfw_saintess 의 사본이다([README.md](../README.md)).
   - 넘지 못하면 K 를 키우거나 신호를 바꿔 다시 잰다.
   - 그래도 넘지 못하면 사용자와 다시 정한다.
9. 확인 (나)의 방법과 문턱: 줄이기 전 · 뒤 복선 모순 수 (2026-11-09: 조건 이름은 `fs_json` · `fs_line`)
   - 지금 코드: 연구 화면 검수 시험(`research.check_trial`)은 이미 쓴 본문에 모순을 심고 검수가 찾는지 센다.
   - 지금 코드: 검수 시험은 쓰기 프롬프트를 바꾸지 않고 새 본문을 쓰지 않는다.
   - 그래서 검수 시험은 그대로는 줄인 쓰기 프롬프트의 복선 모순을 재지 못한다.
   - 지금 코드: 심는 모순(`plant_prompt`)에 복선 갈래가 없다.
   - 추천: 쓰기 블록 시험(`blocktrial`)에 조건 둘을 둔다: `fs_json`(바꾸기 전 JSON 꼴)과 `fs_line`(이 일감의 한 줄 꼴).
   - 추천: 두 조건이 쓴 본문마다 복선 판정 요청을 한 번 부른다.
   - 판정 요청은 `relevant_foreshadows(p, n)` 목록(최대 25개)만 전문으로 받는다.
   - 이 목록은 두 조건이 넣는 목록과 같다.
   - 그래서 판정 요청의 크기는 화수에 따라 커지지 않는다.
   - 두 조건이 함께 뺀 복선(`fs_cut`)은 판정에 넣지 않는다.
   - 까닭: 그 복선은 두 조건의 차이를 보이지 못하고 잡음과 비용만 더한다.
   - 판정 요청은 본문이 어긴 복선을 id · 인용 · 까닭으로 적는다.
   - 판정 요청은 `blocktrial.run` 이 받은 `llm`(본문 단계)을 그대로 쓴다.
   - `settings.STAGES` 에 새 단계를 더하지 않는다.
   - 판정 결과는 연구 기록(`research/log.jsonl`)과 `blocktrial` 명령줄 출력(`describe`)으로 본다.
   - 지금 연구 화면의 기록 줄(`research.js` 의 `rsLogLine`)에는 kind `blocks` 갈래가 없다.
   - 이 일감은 연구 화면을 고치지 않는다.
   - 블라인드 비교본은 `blocktrial` 처럼 kind `blocks` 로 남긴다.
   - 비교본은 연구 화면의 블라인드 비교에서 읽는다.
   - 이 방법은 Q35 의 '연구 화면 검수 시험'을 지금 코드에 맞게 푼 것이다.
   - 사용자가 이 풀이를 받아들이는지 정한다.
   - 다른 안: `check_trial` 에 '쓰고 나서 검수' 모드를 더한다.
   - 이 안은 검수 시험의 뜻(심은 모순 찾기)과 섞인다.
   - 추천 문턱: `fs_line` 의 화당 복선 모순 수가 `fs_json` 보다 잡음 너머로 많지 않다.
   - 문턱에 세는 것은 kind '모순'과 '미리 회수'뿐이다.
   - 잡음은 같은 조건을 두 번 써서 본다.
   - 두 조건의 차이가 같은 조건 두 번의 차이보다 크지 않으면 '나빠지지 않음'이다.
   - 시험할 화는 열린 복선이 있는 장편 화에서 고른다.
   - 첫 표본은 독립 작품 셋에서 화 2개씩이다.
   - 형식과 비용을 본 뒤 늘린 표본은 세 작품을 합쳐 화 10개다(예: 4 · 3 · 3).
   - `blocktrial.run` 은 작품 하나만 받으므로 작품마다 따로 돌린다.
   - 한 번에 쓰는 수는 `MAX_WRITES`(60) 안이다.
   - 모델은 flash 급으로 둔다.
   - 설정 파일은 바꾸지 않고 환경 변수로만 고른다.
   - 돌리는 명령: `CANON_LLM=gemini CANON_MODEL_WRITE=gemini-3.8-flash python -m canon blocktrial <작품> --conditions fs_json,fs_line --episodes <화> --repeats 2 --estimate`.
   - 추정을 본 뒤 같은 명령을 `--estimate` 없이 돌린다.
10. `fs_full` 조건을 어떻게 만드나 (2026-11-09 버림: `prompts.FORESHADOW_JSON` 고리로 바꿈)
    - 추천: K 를 `context.py` 의 `ContextVar` 로도 읽게 해 시험 조건만 K 를 `FORESHADOW_CAP` 으로 둔다.
    - K 가 고른 수 이상이면 블록이 지금과 글자까지 같다(규칙의 '경계 사례').
    - 까닭: `blocktrial` 조건은 작품 사본과 `write_episode` 인자만 바꾼다.
    - 이 안은 스키마나 `write_episode` 인자를 늘리지 않는다.
    - `blocktrial.run` 은 스레드를 띄우지 않고 한 스레드에서 조건마다 차례로 쓴다.
    - 지금 `CONDITIONS` 의 꼴은 (이름, 설명, 사본 바꾸기, `write_episode` 인자)뿐이라 ContextVar 를 둘 자리가 없다.
    - 그래서 조건 꼴에 다섯째 칸으로 문맥 고리(예: `with_k: Callable[[], ContextManager] | None`)를 더한다.
    - `run` · `estimate` · `prompt_size` 는 그 조건의 `write_episode` · `episode_prompt` 호출을 이 고리로 감싼다.
    - 고리는 `token = FORESHADOW_FULL_VAR.set(k)` … `FORESHADOW_FULL_VAR.reset(token)` 을 한다.
    - 감싸지 않으면 `--estimate` 가 두 조건의 요청 글자를 똑같이 센다.
    - `blocktrial` 은 두 조건의 쓰기 프롬프트가 같은 화를 건너뛰고 그렇다고 적는다.
    - 다른 안: `write_episode` 에 인자 `fs_full` 을 더해 `build_episode_context` 까지 넘긴다.
11. 전문 꼴을 바꾸나 (2026-11-09 뒤집음: 한 줄 꼴로 바꾼다)
    - 추천: 바꾸지 않는다.
    - 전문 K개는 지금처럼 `dump` 한다.
    - 까닭: 이 일감은 나누기만 한다.
    - 칸을 줄이는(예: 늘 `open` 인 `status` 빼기) 일은 다른 요청의 `dump` 와 함께 따로 본다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/prompts.py` | `serial_episode_context` 의 '# 열린 복선' 블록을 `serial_foreshadow_block(fs, fs_cut)` 로 찍는다 |
| `canon/prompts.py` | 한 줄 꼴 함수 `foreshadow_line` 과 시험 조건용 ContextVar `FORESHADOW_JSON` |
| `canon/prompts.py` | 복선 판정 요청 `foreshadow_judge_prompt`(확인 (나)용, 정할 것 9) |
| `canon/schema.py` | 판정 응답 형식 `ForeshadowBreaks`(확인 (나)용). dict 칸 없음 |
| `canon/blocktrial.py` | 조건 `fs_json` · `fs_line` 과 조건마다 판정 요청 한 번, 결과의 모순 수 |
| `canon/blocktrial.py` | 조건 꼴의 다섯째 칸(ContextVar 문맥 고리). `run` · `estimate` · `prompt_size` 가 그 조건의 호출을 고리로 감싼다 |
| `canon/blocktrial.py` | `estimate` 가 판정 요청의 입력 · 출력 토큰도 센다 |
| `canon/blocktrial.py` | `summary` · `_KEYS` · `describe` 에 조건별 모순 수('모순' · '미리 회수')를 더한다 |
| `canon/blocktrial.py` | 두 조건의 쓰기 프롬프트가 같은 화(단편 화)는 건너뛰고 그렇다고 적는다 |
| `canon/mock_foreshadow_judge.py` | 판정 요청의 가짜 응답(`@responds(ForeshadowBreaks)`, `mock.py` 맨 끝에서 불러옴) |
| `scripts/context_measure.py` | 블록 흉내: 화마다 한 줄 꼴과 JSON 꼴의 글자(확인 (가)) |

- `canon/context.py` 는 바꾸지 않는다.
- `relevant_foreshadows` 는 바꾸지 않는다(정할 것 6).
- 단편 `build_episode_context` 의 블록은 바꾸지 않는다(정할 것 5).
- 일감 3 도 `prompts.py` 의 쓰기 프롬프트 조립을 고친다.
- 시작 전에 고칠 함수를 서로 견주고, 나중에 머지하는 쪽이 rebase 한다([plan.md](../plan.md)).
- 판정 요청은 `LLM` 인터페이스 뒤에서 부른다.
- 판정 요청은 `blocktrial.run` 이 받은 `llm`(`cmd_blocktrial` 의 `get_llm("write")`)을 그대로 쓴다.
- 새 `settings.STAGES` 이름은 없다.
- flash 급은 `CANON_MODEL_WRITE` 환경 변수로 고른다(정할 것 9).
- 판정 요청도 `usage.record` 로 사용량 화면에 잡힌다(`LLM` 구현을 거치므로).

## 데이터 · 스키마

- 작품 스키마(`Project` · `Foreshadow`)는 바꾸지 않는다.
- 옛 `project.json` 은 그대로 읽힌다.
- 정할 것 4 의 다른 안(`Foreshadow.short`)을 고르면 그때 기본값 `""` 을 두고 이 절을 고친다.
- 새 응답 형식 `ForeshadowBreaks`(확인 (나)용, 작품에 저장하지 않음):
  - `items: list[ForeshadowBreak]`, 기본값 빈 목록.
  - `ForeshadowBreak.foreshadow: str`(복선 id).
  - `ForeshadowBreak.quote: str`(본문 인용).
  - `ForeshadowBreak.reason: str`(어긴 까닭).
  - `ForeshadowBreak.kind: Literal["모순", "미리 회수"]`.
  - '잊음'은 두지 않는다.
  - 까닭: '잊음'은 모순이 아니고, 대부분의 화가 열린 복선 대부분을 잇지 않아 판정이 믿을 만하지 않다.
  - 값 이름은 시작할 때 다시 본다.
- `ForeshadowBreaks` 에는 dict 칸을 두지 않는다(`tests/test_schema_nodict.py`).
- [compat.md](../compat.md) 에 더할 줄은 없다.
- 까닭: RisuAI · CCv3 와 맞추는 필드가 아니다.

## 규칙

### 한 줄 꼴

1. 장편에서 `relevant_foreshadows(p, n)` 이 고른 목록을 받는다(지금 그대로, 최대 25개).
2. 목록의 차례 그대로 복선마다 `foreshadow_line` 한 줄을 찍는다(지금 JSON 의 차례와 같다).
3. 머리 문구는 지금 그대로다: `# 열린 복선` 과 뺀 수가 있으면 `(이번 아크와 관련된 것만, N개 생략)`.
4. 목록이 비면 `없음` 을 찍는다.

### 경계 사례

- `FORESHADOW_JSON` 이 참이면 블록은 바꾸기 전과 글자까지 같다(빈 목록도 바꾸기 전처럼 `[]`).
- 같은 데이터와 같은 화에는 같은 블록이 나온다.
- 같은 화의 스토리보드 · 큐 시트 · 본문 쓰기 · 다시 쓰기(`rework_prompt`) 요청은 같은 블록을 받는다.
- 이 블록부터 뒤의 앞부분 글이 바뀌므로, 바꾼 첫 화에는 화 사이 캐시가 한 번 맞지 않는다.

### 숫자의 근거

- `FORESHADOW_CAP` 25, `FORESHADOW_RECENT` 30: 지금 상수다.
- 이 두 상수는 바꾸지 않는다.
- 문턱 40%: 정할 것 8 의 추천이다.

### 승인 · 자동 집필 · 되돌리기

- 한 줄 꼴은 프롬프트에 찍는 꼴만 바꾼다.
- 한 줄 꼴은 저장된 데이터를 바꾸지 않는다.
- AI 가 만든 것을 저장하지 않으므로 승인 흐름이 없다.
- 자동 집필과 `-y` 는 같은 꼴을 쓴다.
- 자동 집필에 따로 정책이 없다.
- 되돌릴 데이터가 없다.
- 대화 에이전트(`canon/agent.py`)는 이 기능을 고치지 않는다.
- 대화 에이전트가 고칠 값(작품 설정)이 없다.

### 단편과 장편

- 장편: 위 규칙을 쓴다.
- 단편: 지금 그대로 열린 복선을 모두 JSON 으로 넣는다(정할 것 5).

## 화면 · 명령줄 · 프롬프트

- 프롬프트는 `canon/prompts.py` 한 곳만 고친다.
- API 경로와 작업지시서(`brief`) 경로가 같은 블록을 쓴다.
- 고친 뒤 `brief` 출력(`episode_brief`)에서도 같은 블록이 나오는지 본다.
- 블록 자리는 그대로다: 장편 `serial_episode_context` 의 '# 열린 복선' 자리.
- 블록 차례를 바꾸지 않는다.
- 머리 문구는 지금 그대로다.
- 예산: 새 `BUDGET` 키는 없다.
- 블록 크기는 개수 상한 25 로 묶여 화수에 따라 끝없이 커지지 않는다.
- 뺀 수는 지금처럼 머리에 적는다.
- 뺀 이름은 일감 3 의 프롬프트 보기에 넘긴다(정할 것 7, Q17).
- 단편(`form = "short"`) 경로의 프롬프트는 바뀌지 않는다.
- 화면 모양은 바꾸지 않는다.
- `docs/design/` 은 고칠 것이 없다(프롬프트 보기 화면은 일감 3 이 고친다).
- 연구 화면(`canon/static/research.js`)도 고치지 않는다.
- 판정 결과는 명령줄 `describe` 와 `research/log.jsonl` 로 본다(정할 것 9).
- 명령줄: `blocktrial --conditions fs_json,fs_line` 으로 확인 (나)를 돌린다.
- 새 명령은 없다.
- 명령줄: `scripts/context_measure.py` 에 블록 흉내 옵션(`--fs-works` · `--fs-mode` · `--fs-only` · `--fs-table`)을 더한다.
- 웹 엔드포인트는 더하지 않는다.
- Swift 앱 개발은 멈췄다(AGENTS.md).
- `swift/` 를 고치지 않고 `scripts/make_openapi.py` 를 돌리지 않는다.
- RisuAI 코드와 기본 프롬프트 글은 옮기지 않는다(Q4).

## 시험

- 새 시험 `tests/test_foreshadow_trim.py`:
  - 단편 작품의 쓰기 프롬프트 복선 블록이 지금과 글자까지 같다.
  - 장편 블록은 고른 복선마다 `foreshadow_line` 한 줄이고 JSON 이 없다.
  - 고른 수가 상한을 넘으면 머리에 뺀 수를 적고, 고른 복선은 모두 든다.
  - 한 줄 꼴: id, 심은 화, 회수 예정 화(있을 때만), 회수 범위, 갈래 · 드러남, 자르지 않은 설명.
  - `as_json` 또는 `FORESHADOW_JSON` 이 참이면 블록이 바꾸기 전과 같다.
  - 같은 복선에서 한 줄 꼴이 JSON 꼴보다 짧다.
  - 같은 입력을 두 번 부르면 같은 글이 나온다.
  - 스토리보드 요청과 본문 쓰기 요청이 `write_head` 로 시작한다(스토리보드가 생긴 뒤에도).
  - `relevant_foreshadows` 의 출력과 장편 `state_prompt` · `serial_plot_prompt` 의 복선 블록이 꼴 스위치와 상관없다.
  - 판정 응답 형식 `ForeshadowBreaks` 가 dict 칸 없이 `tests/test_schema_nodict.py` 를 통과한다.
- 지금 행동을 묶는 시험은 그대로 통과해야 한다:
  - `tests/test_context.py` 의 `test_foreshadow_rank_keeps_old_series_hooks`.
  - `tests/test_context.py` 의 `test_serial_prompts_note_cut_secrets_and_foreshadows`.
  - `tests/test_context.py` 의 `test_impact_caps_open_foreshadows_in_serial`.
  - `tests/test_serial.py` 의 `test_cast_filter_and_foreshadow_filter`.
- `tests/test_blocktrial.py`: `fs_json` · `fs_line` 조건이 mock 으로 돌고 결과에 모순 수가 든다.
- `tests/test_blocktrial.py`: 장편 fixture 에서 `blocktrial.estimate` 의 `input_tokens` 가 `fs_json` 이 `fs_line` 보다 크다.
- `tests/test_blocktrial.py`: 두 조건의 쓰기 프롬프트가 같은 화(단편 화)는 건너뛴다.
- `tests/test_context_measure.py`: 블록 흉내가 작은 fixture 에서 두 꼴의 글자와 줄어든 몫을 맞게 센다.
- 가짜 응답: 판정 요청의 mock 응답을 `canon/mock_foreshadow_judge.py` 에 더한다(`tests/test_mock_registry.py`).
- 작품 쪽 LLM 응답 형식은 바뀌지 않으므로 다른 mock 은 고칠 것이 없다.
- 머리 문구 '# 열린 복선' 을 보는 시험(2026-11-08 grep): `tests/test_context.py` 의 블록 차례 시험은 `ctx.index("# 열린 복선")` 이라 새 머리에도 맞는다.
- `tests/test_context.py` 의 '이번 아크와 관련된 것만' 확인은 `state_prompt` 의 '[열린 복선]' 이라 바뀌지 않는다.
- `test_cache_family.py` · `test_play_prompts.py` 의 '[열린 복선]' 은 다른 요청의 블록이라 바뀌지 않는다.
- 시작할 때 같은 grep(`이번 아크와 관련된 것만`, `# 열린 복선`)을 다시 돌려 기대값이 바뀌는 시험을 PR 에 적는다.
- 스냅샷: 열린 복선이 있는 장편 fixture 의 스냅샷이 바뀔 수 있다(`tests/snapshots/`).
- 바뀐 까닭을 PR 에 적는다.
- 고친 기능만: `CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_foreshadow_trim.py tests/test_context.py tests/test_serial.py tests/test_context_measure.py`.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- 정적 검사: `ruff check canon tests scripts`.

## 문서

- DESIGN.md 7장 '컨텍스트 (장편)'의 떡밥 줄(`relevant_foreshadows` → `context.rank_foreshadows`) 바로 뒤에 한 줄 꼴 한 줄을 더한다.
- DESIGN.md 7장: 확인 (가)의 실측값(줄어든 글자)과 확인 (나)의 모순 수를 날짜와 함께 적는다.
- DESIGN.md 4장 '컨텍스트 조립'의 장편 블록 차례 글은 바뀌지 않는다.
- 까닭: 블록 자리를 옮기지 않는다.
- README.md 의 장편 프롬프트 예산 문단에 열린 복선 한 줄 꼴 한 문장을 더한다.
- `docs/modules/core.md` 의 `canon/prompts.py` 절: 장편 쓰기 블록 줄 가까이에 한 줄 꼴(`foreshadow_line`)과 판정 요청(`foreshadow_judge_prompt`) 줄을 한 줄씩 더한다.
- `docs/modules/labs.md` 의 `canon/blocktrial.py` 절: 조건 목록 줄에 `fs_json` · `fs_line` 을 넣는다.
- 같은 절에 판정 요청 한 줄, 조건 문맥 고리 한 줄, 결과의 모순 수 한 줄을 더한다.
- `docs/modules/labs.md` 의 `context_measure` 줄 바로 뒤에 블록 흉내 한 줄을 더한다.
- `docs/modules/ai.md` 의 `### canon/mock.py` 절 가짜 응답 파일 목록에 `mock_foreshadow_judge.py` 를 알파벳 차례로 한 줄 더한다.
- 가짜 응답 파일은 따로 절을 두지 않는다.
- 이 목록 줄이 `tests/test_agents_docs.py` 를 맞춘다.
- `docs/modules/` 는 AGENTS.md 의 '문서 줄 규칙'을 지킨다.
- 이 폴더의 [plan.md](../plan.md) 10번 상태 칸을 고친다.
- 정할 것을 정하면 이 폴더 [README.md](../README.md) 의 정한 규칙에 날짜와 함께 더한다.
- 확인 결과 글은 `reports/` 에 둔다(커밋하지 않음).

## 확인하지 못할 것

- 확인 (가)의 블록 글자와 설명 길이는 2026-11-09 에 쟀다(복선 하나의 JSON 덧붙는 글자 약 211자, 설명 평균 101자).
- 확인 (가)는 LLM 없이 글자만 잰다. 한 줄 꼴이 본문의 복선 모순을 늘리는지는 확인 (나)가 잰다.
- 확인 (가) 결과(2026-11-09, 정확히 되돌린 81화): 블록 글자가 합계 49.5% 줄었다(nsfw_saintess 51.8%, subway-1-수정본 46.8%, 캠핑카 56.2%). 문턱 40% 를 넘었다.
- 확인 (나) 결과(2026-11-09, flash, 작품 셋 × 2화 × 2번): 모순 · 미리 회수가 `fs_json` 7번, `fs_line` 6번으로 같은 꼴 두 번의 차이 안이다. 문턱 '나빠지지 않음'을 넘었다.
- 확인 (나)는 첫 표본(화 6개)만 돌렸다. 늘린 표본(화 10개)은 사용자가 돌리지 않기로 했다.
- 판정 요청(`foreshadow_judge_prompt`)도 LLM 이라, 판정이 놓치거나 잘못 센 모순은 두 조건에 함께 섞인다.
