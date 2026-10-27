# AGENTS.md

Canon 저장소에서 작업하는 AI 에이전트(Claude Code, Codex, Gemini CLI 등)를 위한 안내서.

## 프로젝트 목표

AI 로 소설을 길게 쓸수록 인물 관계, 심리, 말투, 복선, 문체가 무너진다. Canon 은 이것들을 **구조화된 데이터**로 관리하고, 매 화마다 그 데이터로 프롬프트를 조립해 일관성을 유지한다. 본문을 쓴 뒤 AI 가 상태 변경안을 만들고, **사용자가 승인해야** 데이터에 반영된다.

현재 범위(MVP): 단편 1권 10~20화, 그리고 부 → 아크 → 화로 나눠 쓰는 200~300화 장편 연재(`Meta.form = "serial"`). 자세한 설계는 [DESIGN.md](DESIGN.md).

## 구조

| 파일 | 역할 |
|---|---|
| `canon/schema.py` | pydantic 데이터 스키마. 모든 상태는 `Project` 하나(`project.json`)에 저장. 인물 신체 프로필(`Character.body`)은 작가 메모라 AI 응답 형식(`SkipJsonSchema`)과 프롬프트(`llm.dump` 의 context `prompt`)에서 빠진다. 이 칸을 다루는 AI 호출은 신체 프로필 제안(`pipeline.suggest_body`)뿐이고, 미성년(`cast.is_minor_age`)이면 쓰리사이즈를 제안하지 않는다. 인물 지금 차림(`CharacterState.attire`, 옷 · 상처 · 지닌 물건)은 지금 값만 덮어쓰고 지난 값은 스냅샷, 규칙은 `prompts.ATTIRE_STATE_RULE` · `attire_write_rule` · `attire_check_rule` |
| `canon/prompts.py` | 프롬프트 템플릿, 화별 컨텍스트 조립(`build_episode_context`), 작업지시서(`episode_brief`, `state_brief`) |
| `canon/pipeline.py` | 단계별 로직: 설정 제안 → 스타일 분석 → 기승전결 → 화별 플롯(대화로 다듬기 `revise_plot`/`apply_revision` 포함, 대상 `chat_target`: 고른 아크 · 다음 아크, 아크 칸 · 부 구성 변경안, 방향 여러 안, 플롯이 데려온 새 인물은 후보 `Project.cast_candidates`, 새 장소는 `Project.place_candidates` 로 두고 화 확정 `confirm_plot` 때 등록. 상태 변경안 정리 `clean_delta`) → 본문 → 검수 → 상태 추출/반영. 장편은 부 계획(`plan_series`) → 다음 아크(`plan_next_arc`/`apply_arc`) → 아크 · 부 요약(`recap`/`apply_recap`). 단편 → 장편 전환은 이어 쓰기 `propose_conversion`/`apply_conversion`, 재구성 `propose_rebuild`/`apply_rebuild`(옛 상태 변경안 재사용 `carried_delta`, 다듬기 `propose_rework`/`accept_rework`), 되돌리기 `undo_conversion` |
| `canon/context.py` | 장편 프롬프트 크기 관리: 블록 재기(`blocks`, 사용량 기록 · 연구 화면), 블록 글자 예산(`BUDGET`), 관련 사실(`pick_facts`) · 비밀(`pick_secrets`) · 떡밥(`rank_foreshadows`) 고르기, 기획 프롬프트 인물(`planning_cast`), 검수용 옛 본문 단락 찾기(`recall`, 질문 여러 개는 색인 `PassageIndex` 하나로), 진술과 겹치는 줄 · 사실(`related_lines` · `related_facts`, 셈이 있는 진술은 셈이 있는 줄을 앞세움 `has_count`). LLM 호출 없음. 단편 경로는 쓰지 않는다 |
| `canon/metrics.py` | 문체 지표(문장 길이, 대사 비율, 과거형 비율, 어휘 다양도, 반복 구, 상투 표현, 쇠맛 패턴과 쉼표·대명사 지표, 문체 거리, 문체 표지 빈도, 예시 문단 베끼기)와 기준 대비 경고, 1~3화 초반 지표(`measure_opening`). LLM 호출 없음. 문체 거리 기준표는 `style_background.py`(`scripts/make_style_background.py` 로 생성) |
| `canon/genres.py` | 장르 목록(`CATALOG`)과 장르별 안내. 프롬프트의 장르 안내와 수위 블록(`guide`), 설정 화면의 장르별 로그라인 예시(`Genre.logline`) |
| `canon/logline.py` | 로그라인 다섯 칸 합치기(`compose`, 조사 자동), 형식 점검(`checks`), 톤 다이얼 문장(`tone_text`). LLM 호출 없음. `static/setup.js` 에 같은 규칙이 있어 함께 고친다 |
| `canon/archetypes.py` | 원형 도감: 인물 유형 카드(`CATALOG`, `Archetype`), 상처(`WOUNDS`), 말투 틀(`SPEECH`), 장르로 거르기(`match`), 빈 칸만 채우기(`fill`, 비틀기는 아크 끝 한 줄), 고른 원형 기록(`Project.cast_archetypes`, `remember` · `prune`, 프롬프트에 넣지 않음), 주사위(`roll`, 이름은 `naming`), 명령줄 `dex`. LLM 호출 없음. 화면은 `static/archetypes.js` (`dexMatch` · `dexRemember` 는 `match` · `remember` 와 같은 규칙). 글은 새로 쓴다(TV Tropes · 나무위키 옮기지 않음) |
| `canon/naming.py` | 이름·지명 무작위 생성(세계관별 스타일, 나이에 맞는 한국 이름)과 출연진 이름 점검. LLM 을 부르지 않는다. 자료와 출처는 `canon/naming_data.py` |
| `canon/dynamics.py` | 관계 역학: 사건(`StoryEvent`)으로 방향 관계(`Tie`)를 계산, 긴장도, 스냅샷 재생, 숫자를 말로 바꾸기, 말로 고른 보는 방식(`VIEWS`)으로 시작 관계 만들기. LLM 을 부르지 않는 순수 계산 |
| `canon/charlog.py` | 인물 설정 변경: 상태 변경안의 설정 바꾸기 제안(`StateDelta.setting_changes`, 외모 · 성격 · 말투 등 뒤 화까지 이어지는 변화) 정리(`clean_delta`)와 반영(`apply`, 작가가 고른 것만), 변경 기록(`Project.setting_log`: 화, 칸, 전후 값, AI · 작가), 1화 반영 뒤 설정 화면 수정 기록(`record_author`, `web.put_project`), 되돌리기(`revert`, 스냅샷에 인물 설정이 없어 기록으로 되돌림), 자동 집필 · `run -y` 가 남겨 둔 제안(`hold`, `Project.setting_held`, `take_held` · `drop_held`). 기록은 프롬프트에 넣지 않는다. LLM 호출 없음. 화면은 `static/charlog.js` |
| `canon/static/app.js` | 웹 화면의 뼈대: 상태 `S`, 서버 호출 `api`, 백그라운드 작업 · 검토 대기 결과, 입력 바인딩(`data-bind`), 공통 동작(`actions` 의 저장 · 되돌리기 · 작품 관리), 라우팅, 사이드바, 다시 그리기와 포커스. 화면 코드는 아래 화면 파일에 있고, 화면 파일이 모두 실행된 뒤(`DOMContentLoaded`) 첫 화면을 그린다 |
| `canon/static/settings.js` · `home.js` · `setup.js` · `style.js` · `plot.js` · `write.js` · `review.js` · `research.js` | 화면별 파일: 모델 · API 키 설정, 작품 목록 · 작품 홈 · 장르, 1단계 설정 도우미(로그라인 · 관계 · 이름 후보 · 조사 `josa`), 2단계 문체 · 문체 라이브러리, 3단계 기승전결 · 장편 · 서술 시점 · 플롯 편집기 등장 인물, 4단계 집필 · 작업지시서, 5단계 상태 승인 · 관계 표시(`DELTA_LISTS`, `setDelta`), 연구 화면. 각 파일은 `viewX` 와 `Object.assign(actions, {...})` 로 붙는다. `index.html` 에서 `app.js` 바로 뒤에 읽는다 |
| `canon/static/charlog.js` | 상태 승인 화면의 인물 설정 바꾸기 카드(`scDeltaCard`, 키 `t`, 기본으로 체크하지 않음, 값 고치기), 반영 기록(`scHistory`), 인물 화면의 남겨 둔 제안(`scHeldCard`) · 설정 변경 기록(`scLogCard`) · 보는 시점의 설정(`scAt`). 칸 이름 `SC_LABELS` 는 `charlog.LOG_FIELDS` 와 같다 |
| `canon/cast.py` | 인물 화면 계산: 화별 관계 프레임(스냅샷, 지워진 화는 사건 로그로 다시 계산), 인물별 등장 화, 화별 타임라인, 명령줄 `cast` 출력. LLM 호출 없음 |
| `canon/foreshadows.py` | 복선 센터: 복선을 본문 문장에 건다(`ForeshadowClue`, `Project.foreshadow_clues`, 본문은 바꾸지 않음). AI 문장 정리(`clean_delta`)와 반영 · 되돌리기, 작가가 걸기 · 복선 고치기(그 화 이후 스냅샷도), 센터 계산(`center`: 회수율, 끊어진 연결, 예정 지남, 오래 묵음, 플롯 회수 계획). 명령줄 `foreshadows`. LLM 호출 없음 |
| `canon/static/foreshadow.js` | 복선 센터 화면, 본문에서 고른 문장을 '복선으로' 거는 칸(`passage.js` 도구와 `illust.js` 읽기 전용 도구에 버튼을 붙인다), 상태 승인 화면의 복선 문장 고르기(`fsClueRows`, `q` 항목) |
| `canon/statwin.py` | 상태창 수치: 인물의 수치(`CharacterState.stats`)가 하나라도 있으면 켜짐. 바뀐 항목만 합치기(`merge`, `+3` · 단위 붙은 돈 `+300` · 목록 `+독 내성` / `-은신` 계산은 `resolve`), 기록(`Project.stat_log`, 목록은 더한 것 · 뺀 것 `diff`), 작가 수정(`set_stats`), 화별 비교표, 본문 상태창 글(`render`, 서식 `Project.stat_window`), 프롬프트 규칙(`write_rule`, `state_rule`, 인벤토리 항목이 있으면 `check_rule` 과 지금 차림 나누기 `inventory`). 명령줄 `statwin`. LLM 호출 없음 |
| `canon/static/statwin.js` | 상태창 수치 화면(항목 고치기, 틀, 복사, 서식, 화별 변화 표)과 상태 승인 화면의 상태창 줄(`swDeltaRows`). `swResolve` 는 `statwin.resolve` 와 같은 규칙(`tests/test_statwin_js.py` 가 node 로 맞춰 본다) |
| `canon/timeline.py` | 작품 속 시간: 화가 끝난 시점(`Episode.time`, `StoryTime`: 날수 · 시간대 · 날짜), 플롯의 시점(`EpisodePlot.time`), 기한(`Timeline.deadlines`, `Deadline`)과 남은 날(`left`). 상태 변경안 정리 · 반영 · 되돌리기(`clean_delta`, `apply_delta`, `revert`, 기한은 `Snapshot.deadlines`), 작가가 기한 고치기(`upsert`, `remove`), 프롬프트 블록(쓰기 · 검수 `episode_block`, 요약 줄 `tag`, 기획 `plan_block`, 상태 `state_block` · `state_rule`, 검수 `check_rule`, 기한은 `context.BUDGET["deadlines"]`), 날짜 · 요일 계산(`calendar`, `day_label`, `when`, 쓰기 블록의 요일 셈 `weekday_hint`). 기록이 없거나 꺼지면 블록이 빈다. 명령줄 `time`. LLM 호출 없음. 화면은 `static/timeline.js` (`tlLeft` · `tlDay` · `tlCalendar` · `tlDayLabel` · `tlWhen` 은 `left` · `current_day` · `calendar` · `day_label` · `when` 과 같은 규칙) |
| `canon/atlas.py` | 지도: 장소(설정 장소 칸 + 인과율 '장소' 요소, `places`) 위에 자리 · 배경 그림 · 위치 글 잇기(`Project.atlas`)를 얹는다. 지도 만들기(마을 생성기 `towngen`)의 장소 표(`gen_places`), 미리보기(`generate`, 저장 안 함), 적용(`apply_generated`, `Atlas.spec`). 인물 위치 글을 장소와 맞추기(`match`), 화별 인물 자리(`frames`, `cast.walk` 재사용), 장소와 맞지 않은 위치 글(`unmatched`)과 한 번에 정리(`clean_sort`, `apply_sort`, AI 제안은 `pipeline.sort_places`), 마을 데이터(Watabou 생성기 JSON, `read_layout`)와 길 따라 동선 · 거리(`road_graph`, `route`, `add_routes`), 명령줄 `map`. LLM 호출 없음. 화면은 `static/atlas.js` (배경 그림 · 마을 데이터는 작품 폴더 `map/`) |
| `canon/towngen.py` | 마을 생성기: `MapSpec`(시드, 크기 · 길 모양 · 물 · 밭 · 숲)으로 길 · 다리 · 필지 · 집 · 밭 · 나무를 만들어 `atlas.read_layout` 과 같은 모양으로 낸다(`village`). 단계마다 난수원을 따로 둬 같은 입력이면 같은 마을. 장소 종류 찾기(`classify`, `CATEGORIES`)와 종류별 자리 고르기. 알고리즘을 바꾸면 `VERSION` 과 `tests/test_mapgen.py` 스냅샷을 함께 고친다. LLM 호출 없음. 도시 · 왕국은 다음 단계 |
| `canon/geom.py` | 지도 생성기의 기하 도구: 다각형(넓이 · 무게중심 · 겹침 · 자르기), Delaunay · Voronoi · Lloyd, 노이즈, Poisson disk, 격자 찾기. 순수 파이썬, 지도를 모른다 |
| `canon/static/cast.js` | 인물 · 관계도 화면: 화 슬라이더로 재생하는 SVG 관계도(끌어 옮긴 배치는 localStorage), 인물 요약, 인물 카드(`castSheet`: 보는 시점의 상태 · 상태창 수치(바뀐 양 `castStatDelta`, 시스템 창 테마는 localStorage) · 관계 막대 · 비밀 · 설정과 남겨 둔 제안 · 타임라인), 두 사람 추이 그래프, 등장표. 온기 색 구간은 `dynamics.warmth_word` 경계와 같다 |
| `canon/elements.py` | 인과율: 작가가 언제든 더하는 이야기 요소(`StoryElement`)의 관련 화 지도(`links`), 화별로 넣을 요소(`episode_block`), 시점 설명. 본문 · 플롯에서 처음 나온 장소(`NewPlace`)를 '장소' 요소로 등록(`clean_places`, `add_places`, 반영 취소 `unregister_places`, 플롯 후보 `place_candidates`), 장편은 그런 장소를 예산(`context.BUDGET["places"]`)까지만. 비슷한 지명은 `naming.similar_place`. LLM 호출 없음. 영향 분석과 반영은 `pipeline.analyze_impact` / `apply_impact` |
| `canon/storylines.py` | 이야기 줄기: 메인에서 갈라졌다 합류하는 서브플롯 · 과거 회상 · 외전 · 인물 이야기(`Storyline`). 화의 줄기는 `EpisodePlot.storyline`(주로 따라가는 줄기, 비면 메인)과 `threads`(끼어드는 장면). 범위(`span`), 프롬프트 블록(`plan_block`, `episode_block`, `state_rule`), 명령줄 노선도(`ascii_map`). LLM 호출 없음. 제안과 반영은 `pipeline.suggest_storyline` / `apply_storyline` |
| `canon/renumber.py` | 화 끼워 넣기 · 빼기: 안 쓴 화의 번호를 옮길 때 함께 옮길 곳(플롯, 구간 · 아크 · 부 범위, 복선, 인과율 요소, 줄기, 인물 첫 등장 화, 대화 주제). LLM 호출 없음. 검사와 새 화는 `pipeline.insert_episode` / `remove_episode`, 새 화 AI 초안은 `draft_episode`(`prompts.episode_plot_prompt`). 화 번호를 품은 칸을 새로 만들면 `move_points` 에도 넣는다. 화면은 `static/insert.js` (넣을 수 있는 자리 `lastFixed` 는 `last_fixed` 와 같은 규칙) |
| `canon/static/lines.js` | 이야기 줄기 화면: SVG 노선도, 줄기 편집, 화 붙이기, AI 제안. 플롯 편집기의 줄기 칸(`lineField`)과 화 카드 표시(`lineBadge`)도 여기 있다. `storylines.span` · `tag` 와 같은 규칙이라 함께 고친다 |
| `canon/static/causal.js` | 인과율 화면: 요소 추가·편집, 관련 화 지도, 영향 분석 변경안 고르기. `elements.basis` 와 같은 모양(`elBasis`)으로 분석이 지났는지 본다 |
| `canon/static/convert.js` | 단편 → 장편 전환 화면: 이어 쓰기(총 화수 · 결말 처리, AI 전환 계획에서 항목 골라 반영)와 재구성(화 지도 고치기, 반영), 되돌리기. 집필 화면의 재구성 안내 · 다듬기 비교(`rebuildNote`)도 여기 있다 |
| `canon/static/chat.js` | 화면에 붙는 AI 대화 패널(기승전결 · 플롯 화면 `plot`, 집필 화면 `text:<화>`). 변경안을 칸별로 지금 값과 비교해 보여 주고 고른 것만 반영 요청. 주제마다 요청 내용과 변경안 그리기를 `CHAT_TOPICS` 에서 바꿔 끼운다. 플롯 대화는 대상(`plotScope`: 고른 아크 · 다음 아크 초안, 연 구간 · 화)을 함께 보내고, 아크 칸 · 부 구성 변경안, 방향 여러 안(`optionsCard`), 다음 아크 안을 초안으로 놓기(`draftFromRev`)를 그린다. 적용한 플롯 변경안의 적용 취소(`chatUndo`, 서버 `pipeline.undo_plot_chat`). 서버 `pipeline.chat_target` · `chat_where` 와 같은 규칙. 화면 본체는 `plot.js` · `write.js` |
| `canon/static/rewrite.js` | 다시 생성: 집필 화면의 다시 생성 패널(빠른 요청, 피드백, 함께 넣을 재료, 처음부터 / 고쳐 쓰기, 살릴 부분), 새 판 비교(나란히 · 바뀐 곳 `textDiff`)와 고르기, 이전 판 목록과 되돌리기. 서버는 `pipeline.rewrite_episode` · `set_candidate` · `adopt_candidate` · `drop_candidate` · `restore_version`, 프롬프트는 `prompts.rewrite_prompt` |
| `canon/static/restate.js` | 반영 뒤 고친 화: 반영이 끝난 화를 고쳤을 때 집필 화면 알림(`restateNote`, 뒤 화 검수 권유), 상태 승인 화면의 다시 맞추기 카드(`restateCard`: 요약 · 새 사실 · 새 복선만 고르기, 그대로 두기). 서버는 `pipeline.apply_restate` · `keep_state`, 표시는 `Episode.final_text` (`edited_after_final` 과 같은 규칙) |
| `canon/static/passage.js` | 본문 부분 수정: 본문에서 고르면 뜨는 도구(직접 수정, AI에게 고치기), 후보를 원문과 단어 단위로 비교, 수정 기록과 되돌리기, 고친 뒤 다시 할 단계 알림. 상태 정리 경고에서 «» 문장을 찾아 고르기(`warnQuote`, `warnItems`, `warnPick`). 서버는 `pipeline.edit_text` · `revise_passage` · `apply_passage` · `undo_edit` |
| `canon/static/opening.js` | 초반 1~3화: 집필 화면의 초반 점검 카드(지표 경고, 흡입력 판정, 여는 방식 비교본, 반영 끝난 화는 비교를 감춤), 플롯 편집기의 여는 방식별 플롯 안(고르기 전 플롯은 `Episode.opening_prev`, 되돌리기 `pipeline.undo_opening`). 서버는 `pipeline.opening_metrics` · `check_hook` · `suggest_openings` · `apply_opening` · `research.run_opening_compare`. 규칙은 `prompts.opening_rules` / `OPENING_APPROACHES`, 지표는 `metrics.measure_opening` |
| `canon/publish.py` | 복사 · 내보내기: 본문을 다른 사이트에 붙여 넣기 좋게 다듬기(줄바꿈 형식 `FORMATS`, 마크다운 흔적 지우기, HTML), 여러 화 잇기(`export`). LLM 호출 없음. 화면은 `static/publish.js` |
| `canon/illust.py` | NovelAI 삽화 프롬프트 조립: AI 원안(`IllustDraft`)에 저장된 인물 외형 태그(`Project.visuals`), 인물 수, 등급, 모델별 품질 태그(`MODELS`)를 붙여 기본 · 인물 · 부정 프롬프트로(`assemble`), 태그 정리(`clean`). LLM 호출 없음. AI 호출은 `pipeline.illustrate` / `suggest_look` (`illustration` 단계) |
| `canon/static/illust.js` | 집필 화면 삽화 프롬프트 카드(칸별 복사, 다시 조립, 외형 고정), 읽기 전용 본문에서 고르는 도구, 설정 화면 인물 카드의 삽화 외형 태그(`visualFields`). 고치는 본문의 도구 버튼은 `passage.js` |
| `canon/static/publish.js` | 집필 화면의 복사 · 내보내기 카드와 복사 버튼. 텍스트와 HTML 을 함께 클립보드에 넣고(보안 연결이 아니면 복사 이벤트로), 막히면 .txt 내려받기 |
| `canon/llm.py` | LLM 프로바이더 인터페이스(`json`, `text`)와 Gemini(API 키 또는 Vertex AI 서비스 계정 `_vertex_client`), 로컬(OpenAI 호환) 구현, 단계별 선택(`get_llm(stage)`). 설정 화면의 Gemini 연결 방식은 `static/vertex.js` |
| `canon/claude.py` | Claude 백엔드: 구독 로그인(`claude`, 설치된 Claude Code 를 `claude -p` 로 부름, 로그인 상태 `status`)과 API 키(`claude-api`, Anthropic SDK). Canon 은 Claude 계정 로그인을 직접 받거나 토큰을 저장하지 않는다(Anthropic 정책). 화면은 `static/claude.js` |
| `canon/usage.py` | AI 사용량과 비용: LLM 구현이 실제 호출마다 `record` 로 `projects/.usage/usage.jsonl` 에 남기고, 작품 · 화 · 작업은 `scope(...)` 로 붙인다(웹 미들웨어, `jobs.start`, 자동 집필, CLI). 가격표(`DEFAULT_PRICES` + 설정의 `prices`, 날짜별 `since`)로 볼 때 비용을 계산하고 자동 집필 추정도 같은 표를 쓴다. 화면은 `static/usage.js` |
| `canon/research.py` | 연구 화면(모델 실험) 로직. 서버 점검, 샘플 비교, 단계 시험, 컨텍스트 크기, 검수 시험(모순을 심고 `TRIAL_MODES` 마다 찾는지, `check_trial`, 판단기를 주면 두 걸음 검수 `twostep`도), 블라인드 비교. 작품 데이터와 분리해 `research/log.jsonl` 에 기록 |
| `canon/judge.py` | 판단기: 글을 쓰지 않고 선택지 확률만 낸다(Jev 의 System One 방식). `LocalJudge`(OpenAI 호환 서버 logprobs, 출력 1토큰), `MockJudge`, `make_judge` / `get_judge`(`CANON_JUDGE`). 호출마다 `usage.record`(단계 `judge`). 두 걸음 검수 `pipeline.check_two_step`(진술 `prompts.claims_prompt` → 근거 `claim_evidence` → 의심 `verdict_prompt`)가 쓰고, 아직 연구 화면에서만 |
| `canon/mock.py` | 테스트용 가짜 LLM |
| `canon/library.py` | 문체 라이브러리: 작품과 따로 `projects/.styles/<id>.json` 에 문체(원문, 프로필, 기준 지표)를 저장. 작품에 적용하면 복사하고 `Project.style_id` · `style_version` 으로 출처만 기억. 저장마다 버전(`StyleVersion`), 칸별 비교(`diff`), 되돌리기(`restore`) |
| `canon/static/marks.js` | 집필 화면 문체 표시: 장치마다 이번 화 배지(`deviceBadges`), 본문에서 장치 글자 · 금지 표현 밑줄(고치는 본문은 textarea 뒤에 깐 칸 `hl-layer`, 읽기 전용은 `<mark>`), 밑줄에서 부분 수정 도구 띄우기. 쓴 화 세기와 쉬는 화 판정은 `metrics.device_hits` · `device_last` · `prompts.device_block` 과 같은 규칙이라 함께 고친다(`tests/test_marks_js.py` 가 node 로 맞춰 본다) |
| `canon/setupchat.py` | 설정 도우미 대화(대화 주제 `setup`): AI 변경안(`SetupRevision`: 기본 정보 · 세계관 칸 `SetupEdit`, 인물 칸 `CharacterEdit`, 새 인물, 관계, 방향 여러 안) 정리(`clean`), 고른 부분만 적용(`apply`, 부분 id `part_ids`), 변경안 단위 적용 취소(`undo`, `ChatMessage.setup_before`), 기록(`record`). AI 는 칸 · 인물 · 관계를 지우지 않고, 첫 반영 뒤에는 관계의 시작 방식과 수치를 바꾸지 않으며, 1화 반영 뒤 바꾼 인물 칸은 `charlog.record_author` 로 남긴다. LLM 호출은 `pipeline.revise_setup`, 프롬프트는 `prompts.setup_chat_prompt`. 명령줄 `setupchat` |
| `canon/static/setupchat.js` | 설정 도우미의 대화로 다듬기 패널(`CHAT_TOPICS.setup`): 칸별 변경안과 지금 값 비교(이미 채운 칸을 바꾸는 부분은 기본으로 체크하지 않음), 새 인물을 고르지 않으면 그 인물과의 관계는 끔, 방향 여러 안(`chat.js` 의 `optionsCard`), 적용 · 적용 취소. 칸 이름(`SETUP_KEYS`, `SETUP_CHAR_LABEL`)과 부분 id 는 `setupchat.KEY_LABELS` · `CHAR_LABELS` · `part_ids` 와 같다 |
| `canon/static/stylechat.js` | 문체 화면의 대화로 다듬기(대화 주제 `style`: 칸별 변경안과 지금 값 비교, 시험 문단, 고른 칸 적용 · 적용 취소, 라이브러리 새 버전)와 '이 문체로 쓴 예시' 카드. 서버는 `pipeline.revise_style` · `apply_style_chat` · `undo_style_chat` · `style_example`. 칸 이름은 `prompts.STYLE_KEY_LABELS` 와 같다 |
| `canon/static/mystyle.js` | 나만의 문체: 스타일 프로필의 가끔 쓰는 장치 칸(`deviceFields`), 문체 화면의 '내 수정에서 배우기' 카드(서버 `pipeline.learn_style` / `apply_learning`), 라이브러리 항목의 버전 목록. 장치의 쓴 화 세기는 `metrics.device_last` 와 같은 규칙 |
| `canon/store.py` | `projects/<이름>/project.json` 저장, 본문을 `episodes/NN.md` 로 내보내기. 화면 저장 기록(`writer`, `edit_rev` · `saved_by`, 파일 끝만 읽음), 검토를 기다리는 AI 결과와 실패한 작업(`pending.json`, `load_pending` / `edit_pending`) |
| `canon/cancel.py` | 웹 작업 멈추기 신호. `jobs.start` 가 스레드마다 두고, LLM 호출 전과 저장 전에 `check()` 로 확인해 멈춘 작업이 결과를 저장하지 못하게 한다 |
| `canon/cli.py` | 명령줄 (`python -m canon ...`) |
| `canon/jobs.py` | 웹의 오래 걸리는 AI 작업을 스레드로 돌리는 메모리 작업 목록. 중복 실행 막기, 진행률, 작업이 맡은 화를 저장 덮어쓰기에서 지키기(`owned_episodes`), 멈추기(`stop`) |
| `canon/autorun.py` | 자동 집필: 목표 화까지 write → check + state → 정책(`Policy`) 통과 시 반영을 반복. 배치(`llm.BatchLLM`) 켜고 끄기, 비용·시간 추정, `autorun.json` 에 진행 기록, 서버 재시작 후 이어 가기. 화면은 `static/auto.js` |
| `canon/updater.py` | 코드 자동 업데이트: `origin/main` fast-forward, 의존성 설치, 프로세스 재시작. `serve` 가 시작 때와 주기적으로 부른다 |
| `swift/` | SwiftUI 앱(macOS · iOS · iPadOS): 서버에 붙는 클라이언트, 패키지 `CanonKit`. 순수 Swift `CanonCore`(오류 문구 · 작업 추적 · 조사 · 날짜 · 사이드바 `Screen`), 생성 클라이언트 `CanonAPI`(`Sources/CanonAPI/openapi.json`), 화면마다 `Feature*` 모듈, 앱 뼈대 `CanonAppUI`, Xcode 껍데기 `App/project.yml`. 계산 · 프롬프트는 옮기지 않는다. `CanonCore` 의 표시 규칙은 웹 화면 파일(`app.js` 와 화면별 파일)과 같아 함께 고친다(표는 `swift/README.md`). 설계는 `swift/README.md` |

흐름: `new`(설정은 `setupchat` 으로 말로 다듬기) → `style` → `arc` → `plot` → (사용자 수정) → `confirm` → `write` → `check` → `update` 반복 (`run` 이 자동 반복). 장편(`new --serial`)은 `arc` 대신 `series` 한 번, 그리고 아크마다 `nextarc` → `plot` → `confirm` → `run` → `recap` 을 반복한다 (`arcs` 로 진행 보기). 단편은 `convert` 로 장편으로 바꿀 수 있다(단편 전체가 아크 1, `--rebuild` 는 단편을 씨앗으로 앞부분을 다시 짜고 다듬기 화는 `rework`, `--undo` 로 되돌리기). 서브플롯 · 과거 회상 · 외전은 `lines` 로 이야기 줄기를 만들고 화에 붙인다. 이미 짜 둔 플롯 사이에 외전이나 새 화를 넣거나 안 쓴 화를 빼려면 `insert`(뒤 화 번호와 범위 · 복선 · 요소 · 줄기를 함께 옮김). `rewrite` 로 피드백 · 검수 결과 등을 반영해 그 화를 다시 생성하고(새 판과 바꿀지 고르기, 이전 판 되돌리기), `fix` 로 본문 일부를 AI 후보로 고치고 `edits` 로 수정 기록 보기 · 되돌리기 · 내보내기. `learn` 으로 수정 기록에서 문체 규칙 후보 찾기, `styles versions` · `restore` 로 문체 버전. `export` 로 다른 사이트에 붙여 넣을 본문 내보내기. `illust` 로 NovelAI 삽화 프롬프트, `look` 으로 인물 외형 태그. `pov` 로 화별 서술 시점(남주 → 여주 등) 보기 · 정하기, `voice` 로 시점 인물별 서술 말투. `cast` 로 인물별 등장 · 지금 관계 · 화별 타임라인(바뀐 설정 포함) 보기, `map` 으로 장소와 인물별로 옮겨 다닌 길 보기, `map gen` 으로 마을 만들기. `stats` 로 화별 문체 지표 확인. `dex` 로 원형 도감 보기 · 인물 빈 칸 채우기 · 주사위. `time` 으로 작품 속 시간(화별로 끝난 시점, 기한) 보기 · 고치기. 1~3화는 `openings` 로 여는 방식 여러 안(플롯 `--plot` · 본문 블라인드 비교), `hook` 으로 흡입력 판정. `usage` 로 AI 사용량과 추정 비용 보기. `compare` 로 같은 화를 두 백엔드로 써서 가려 비교.

## 설계 원칙 (깨지 않기)

- **인물은 불변 설정(`Character`)과 가변 상태(`CharacterState`)로 나눈다.** 말투와 성격은 고정, 감정·목표·아는 정보만 화마다 바뀐다. 본문에서 뒤 화까지 이어지게 바뀐 설정(머리를 자름, 영구 흉터, 말투를 바꾸기로 함)은 상태 변경안의 설정 바꾸기 제안으로만 오고, 작가가 상태 승인 화면에서 골라야 바뀐다(기본으로 체크하지 않음). 자동 집필과 `-y` 는 반영하지 않고 남겨 둔다(`charlog.hold`). 바뀐 것은 `Project.setting_log` 에 전후 값으로 남긴다.
- **AI 출력은 제안일 뿐이다.** 설정, 플롯, 상태 변경은 사용자 확인(`confirm` 또는 `-y`) 후에만 저장한다. 자동 집필은 사용자가 정한 승인 정책을 통과한 화만 반영하고 `Episode.auto` 로 표시한다. 정책을 느슨하게 만드는 기본값 변경은 사용자와 정한다.
- **확정된 것은 덮어쓰지 않는다.** confirmed 이상인 화의 플롯은 재생성해도 유지한다. 사용자가 입력한 설정은 AI 제안이 덮지 않는다.
- **순서를 지킨다.** 이전 화가 `finalized` 가 아니면 다음 화를 쓰지 않는다.
- **관계 수치는 AI 가 적지 않는다.** AI 는 사건만 뽑고 `dynamics.py` 가 계산한다. 사용자가 고칠 때는 `수동보정` 사건으로 기록해 재생할 수 있게 한다.
- **컨텍스트는 일정한 크기로.** 이전 본문 전체가 아니라 화별 요약 + 직전 화 끝부분 + 현재 데이터만 넣는다. (검수는 예외로 앞선 본문 전체를 본다.)
- **장편은 줄거리를 접는다.** 화별 요약을 다 넣지 않고 `story_so_far`(끝난 부 · 아크 요약 + 지금 아크 화별 요약)를 쓴다. 인물 · 떡밥 · 사실 · 비밀 · 알게 된 정보도 `prompts.py` 의 필터와 `context.BUDGET` 예산을 거친다. 장편 검수는 `budget` 방식(직전 3화 원문 + 옛 화 관련 단락)이 기본이다. 새 블록도 화수에 따라 끝없이 커지지 않게 하고, 예산을 넘겨 뺐으면 몇 개 뺐는지 적는다. 단편(`form = "short"`) 경로는 바꾸지 않는다.
- **바뀌지 않는 블록이 앞, 화마다 바뀌는 블록이 뒤.** `static_context()` 를 앞에 둬야 Gemini 암묵적 캐시가 맞는다. 컨텍스트에 블록을 추가할 때 이 순서를 지킨다.
- **API 경로와 작업지시서 경로는 같은 프롬프트를 공유한다.** 프롬프트를 고칠 때는 `prompts.py` 한 곳만 고치고, `brief` 출력도 함께 확인한다. 나중에 MCP 서버도 이 함수들을 재사용한다.
- **LLM 호출은 `LLM` 인터페이스 뒤에만 둔다.** pipeline 이나 cli 에서 SDK 를 직접 부르지 않는다. 새 LLM 구현이나 새 API 호출 경로는 `usage.record` 를 불러 사용량 화면에 잡히게 한다. 스레드를 새로 띄우면 `contextvars.copy_context()` 로 작품 · 화 정보를 넘긴다.
- LLM 이 채우는 스키마(`SetupSuggestion`, `StyleProfile`, `ArcPlan`, `PlotBatch`, `EpisodeDraft`, `PlotRevision`, `NameOptions`, `PassageRevision`, `StateDelta`, `NewPlace`, `StoryEvent`, `ConsistencyReport`, `SeriesPlan`, `ArcProposal`, `Recap`, `ImpactReport`, `StorylineProposal`, `SerialConversion`, `SerialRebuild`, `Rework`, `HookReport`, `OpeningPlots`, `IllustDraft`, `LookSuggestion`, `StyleLearning`, `StyleRevision`, `StyleEdit`, `StyleSample`, `SetupRevision`, `SetupEdit`, `CharacterEdit`, `VoiceSuggestion`, `PlantSet`, `PlaceSort`, `ClaimSet`, `StoryTime`, `Deadline`, `BodySuggestion`)에는 dict 타입 필드를 쓰지 않는다 (Gemini 구조화 출력 호환).

## 개발 명령

```bash
pip install -r requirements.txt
python -m unittest                  # mock LLM 으로 전체 흐름 스모크 테스트 (API 키 불필요)
CANON_LLM=mock python -m canon ...  # 수동 확인
```

환경 변수: `GEMINI_API_KEY`, `CANON_GEMINI_AUTH`(key | vertex) / `CANON_VERTEX_CREDENTIALS` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`(Vertex AI 서비스 계정), `CANON_LLM`(gemini | local | claude | claude-api | mock), `CANON_CLAUDE_MODEL` / `CANON_CLAUDE_BIN` / `CANON_CLAUDE_TIMEOUT` / `ANTHROPIC_API_KEY`(Claude, `claude-api` 만 키를 씀), `CANON_MODEL`(기본 `gemini-4-argon`), `CANON_LOCAL_URL` / `CANON_LOCAL_MODEL` / `CANON_LOCAL_KEY`(로컬 서버), `CANON_LLM_PLAN` / `_WRITE` / `_CHECK` / `_STATE` / `_NAME` / `_REVISE` / `_ILLUSTRATION`(단계별 백엔드), `CANON_MODEL_PLAN` / `_WRITE` / `_CHECK` / `_STATE` / `_NAME` / `_REVISE` / `_ILLUSTRATION`(단계별 모델), `CANON_HOME`(프로젝트 저장 위치, 기본 `projects/`), `CANON_USAGE`(사용량 기록 파일, 기본 `projects/.usage/usage.jsonl`).

스키마나 파이프라인을 바꾸면 `canon/mock.py` 도 맞춰 고치고 `python -m unittest` 가 통과하는지 확인한다. `web.py` 의 엔드포인트나 응답 모델을 바꾸면 `python scripts/make_openapi.py` 로 Swift 앱의 명세를 다시 만든다(`tests/test_openapi.py` 가 본다). 연산 이름은 함수 이름이라 웹 함수 이름을 바꾸면 Swift 호출부도 바뀐다. 실제 Gemini 호출은 키가 있을 때만 확인할 수 있으니, 확인하지 못했다면 그렇다고 밝힌다.

## 규칙

- 사용자에게 보이는 문구, 프롬프트, 문서는 **한국어**로 쓴다. 코드 식별자는 영어.
- 화면 문구는 해요체로 쓴다("저장했어요"). 화면에 보이는 서버 문구(오류, 작업 기록, 자동 집필 멈춤 이유, 명령줄 안내)도 같다. LLM 에게 주는 프롬프트는 이 규칙 밖이다. 영문 뒤 조사는 붙인다("AI가", "JSON을"). 단계 이름은 사이드바와 같게, '반영'은 상태 승인으로 데이터에 들어가는 뜻에만, AI 제안을 받아들이는 동작은 '적용'으로 쓴다. 날짜는 `fmtDate` · `fmtDateTime`, 화 범위는 'a~b화'.
- 기본 LLM 은 **Gemini** 다 (사용자 결정). 다른 프로바이더는 `LLM` 구현을 추가하는 방식으로만 넣는다. Claude 구독 로그인은 설치된 Claude Code 를 부르는 방식만 쓴다. Claude 계정 로그인 화면을 Canon 에 만들거나 OAuth 토큰을 읽고 저장하는 코드는 넣지 않는다 (Anthropic 약관). 로컬 모델은 `LocalLLM`(OpenAI 호환) 하나로 Ollama, llama.cpp, vLLM, LM Studio 를 모두 다룬다. 파이프라인 호출부는 `get_llm("plan" | "write" | "check" | "state" | "name" | "revise" | "illustration")` 로 단계를 밝힌다.
- **API 키, `.env`, `projects/`(사용자 소설 데이터)는 커밋하지 않는다.** `.gitignore` 에 있다.
- 스키마 필드를 바꾸면 기존 `project.json` 이 읽히도록 기본값을 둔다.
- 기능을 바꾸면 README.md 와 DESIGN.md 의 해당 부분도 고친다.

## 로드맵

1. Gemini 실호출 검증과 프롬프트 튜닝, 화별 상태 스냅샷과 되돌리기
2. 구독형 채팅 앱(Claude, Gemini, ChatGPT)용 작업지시서 고도화 (`brief`, `import`, `update --from-json` 은 이미 있음)
3. MCP 서버: 작업지시서 조회, 본문 제출, 상태 변경 제안/반영을 tool 로 노출
4. 웹 UI: 설정 폼, 관계도, 기승전결 플롯 보드, 상태 변경 승인 화면
5. 장편 확장 (부 · 아크 · 롤링 기획 · 접은 줄거리는 완료. 관계 시간 감쇠, 장르 프리셋 남음)
