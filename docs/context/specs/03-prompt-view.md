# 03. 프롬프트 보기와 블록 설정

상태: PR (2026-11-09) · 계획: [plan.md](../plan.md) 의 3번 · 먼저: —

## 목표

작가가 쓰기 화면에서 AI에게 실제로 보내는 요청 원문을 본다.
요청을 블록으로 나눠 블록마다 글자 수, 토큰 수, 예산을 본다.
예산을 넘겨 뺀 항목의 이름과, 들어간 항목마다 들어간 이유를 본다.
작품마다 블록을 끄고 켜고, 블록 예산(`context.BUDGET` 의 값)을 바꾼다.
블록 차례와 블록 문구는 `prompts.py` 에 그대로 둔다(2026-11-08 사용자 결정 Q10).
설정을 건드리지 않은 작품은 요청이 한 글자도 바뀌지 않는다.

## 정할 것

2026-11-09: 명세서의 코드 주장을 지금 main(#420 뒤)과 대조해 고쳤다(주장 94개 가운데 맞음 40, 고침 45). 대조 중에 새로 생긴 정할 것 12~15 를 더했다.
2026-11-09: 사용자가 남은 정할 것(1 · 2 · 4~10 · 12~15)을 모두 추천안으로 골랐다.

1. 블록을 나누는 단위 — 추천: `prompts.py` 에 블록 id 목록(`BLOCKS`: id, 화면 이름, 끌 수 있는지, 쓰는 `BUDGET` 키)을 두고, 조립 함수가 블록 조각 목록을 만든 뒤 이어 붙여 요청 문자열을 만든다.
   - 지금 `web.context` 는 요청을 `^# ` 으로 자른다. 그래서 `style_block` 안의 '# 문체 예시' 와 '# 스타일 프로필' 이 따로 잡히고 `static_context` 의 묶음이 보이지 않는다.
   - 조각 목록에서 보기와 실제 요청을 함께 만들면 둘이 어긋나지 않는다.
   - `BLOCKS` 표에는 예산 종류(글자 · 개수 · 없음)도 적는다.
   - `static_context` 는 쓰기 요청 밖에서도 쓴다: `check_material`(검수 · 상태 변경안), `fix_recheck_prompt`, `polish_prompt`, `style_example_prompt`, `passage_head`.
   - `pipeline.recheck_fixed` 도 `fix_recheck_prompt` 의 캐시 경계 힌트(`PREFIX_HINT`)로 `len(static_context(p))` 를 센다. 이 호출도 기본(따르지 않음)으로 둬야 경계가 맞는다.
   - `style_block` 도 `static_context` 밖에서 쓴다: 문단 연습장(`paragraph_prompt`)이 `markers` 인자를 넘겨 바로 부른다. 블록 조각으로 나눠도 `style_block(p, markers)` 의 반환 글은 그대로 둔다.
   - 그래서 `static_context` 에 설정을 따를지 정하는 인자를 두고 기본은 따르지 않는다. 쓰기 경로(정할 것 4)만 이 인자를 켠다.
2. 토큰 수 — 추천: 기본은 `context.est_tokens`(글자 수 ÷ `CHARS_PER_TOKEN` 1.7) 추정값이고, 화면에 '추정'이라고 쓴다.
   - '실제 토큰 세기' 버튼을 두면 쓰기 단계 백엔드의 `count_tokens` 로 요청 전체를 한 번 센다.
   - `count_tokens` 는 `LLM` Protocol 에 없다. 실제로 세는 구현은 Gemini · Claude API · 로컬 백엔드에만 있다.
   - 로컬 백엔드는 서버의 `/tokenize` 로 센다(vLLM 꼴, llama.cpp 꼴 차례). 그 엔드포인트가 없거나(예: Ollama) 연결할 수 없으면 `None` 을 돌려준다.
   - `count_tokens(text)` 는 글 하나만 받는다. 요청 전체를 세려면 `research.py` 처럼 시스템 프롬프트와 요청을 이어 붙인다. 백엔드가 보내기 직전에 붙이는 `with_note`(`POLICY_NOTE` · `ADULT_NOTE`)도 붙여야 실제 요청과 맞는다.
   - 백엔드는 `llm.get_llm("write")` 로 얻는다. `get_llm` 은 백엔드를 감싸지 않으므로 `getattr` 이 실제 클래스에 닿는다. `BatchLLM` 으로 감싸는 곳은 자동 집필 배치 경로 하나뿐이다.
   - `ClaudeCodeLLM.count_tokens` 는 늘 `None` 을 돌려준다. mock 과 `BatchLLM` 에는 이 메서드가 없다.
   - `research.py` 의 `getattr(llm, "count_tokens", None)` 패턴을 다시 쓴다.
   - 메서드가 없거나, `None` 을 돌려주거나, 예외를 던지면(키 · 네트워크 오류) 버튼 자리에 '이 백엔드는 토큰을 셀 수 없어요'를 보인다. `research.py` 처럼 예외도 `None` 과 같게 다룬다.
   - 블록마다 실제 토큰을 세면 호출이 블록 수만큼 늘어 하지 않는다.
   - 지금 `count_tokens` 구현 셋과 유일한 호출부(`research.py`)는 `usage.record` 를 부르지 않는다. 그래서 이 호출은 사용량 화면에 잡히지 않는다.
   - 비용이 드는지는 저장소 코드와 문서에 적혀 있지 않다. 제공자 문서로 본 것은 정할 것 13 에 적는다.
3. 단편의 블록 설정 — 정함(2026-11-08, Q32): 단편(`form = "short"`)은 블록 끄고 켜기도 예산 칸도 보여 주지 않는다. 보기 강화만 받는다.
   - 단편 쓰기 요청도 쓰는 `BUDGET` 키가 있다: `deadlines`(`timeline.deadline_lines`), `stage`(`stage_block`), `travel` · `spots`(`maps/prompt.py`), `stat_lines`(`statwin.lines_block`).
   - `stat_lines` 는 `build_episode_context` 가 아니라 지시문 꼬리의 `statwin.write_rule` → `lines_block` 이 읽는다(`stat_window.prompt = "lines"` 일 때만, 단편 · 장편 같음).
   - 그래서 `context.budget(p, key)` 는 단편 작품에서는 저장한 값과 상관없이 늘 `BUDGET` 기본값을 돌려준다.
   - 단편은 저장한 블록 설정이 있어도 무시하고 지금 요청을 그대로 만든다.
4. 설정이 미치는 요청 — 추천: 본문 쓰기 가족만 따른다.
   - `build_episode_context` 를 바로 부르는 곳: 본문 쓰기(`episode_prompt`), 고쳐 쓰기(`rework_prompt`), 스토리보드(`storyboard_prompt`), 큐 시트(`cue_sheet_prompt`, lead 가 없을 때만), `write_head`, 지금의 컨텍스트 보기(`web.context`).
   - 장편 조각 조립 `serial_parts` 는 `context_parts`(`build_episode_context` 의 조각 함수) 안에서만 불린다. 예전 글 함수 `serial_episode_context` 는 부르는 곳이 없어 지웠다.
   - `cue_sheet_prompt` 는 lead 가 있으면(`pipeline.cue_lead` 가 방금 AI 가 만든 낡지 않은 스토리보드일 때 고름) 그 `storyboard_prompt` 글을 앞에 두고 `board_block` 과 큐 요청만 붙인다. 이 경로는 스토리보드 요청을 만들 때의 설정을 그대로 따른다.
   - `episode_prompt` 를 거쳐 따르는 요청: 다시 생성(`rewrite_prompt`), 큐 시트 한 번에 쓰기(`cue_score_prompt`), 큐마다 쓰기(`cue_head` → `cue_play_prompt`).
   - 스토리보드 고치기(`storyboard_revise_prompt`)는 `storyboard_prompt` 를 거친다. 작업지시서(`brief_request`)도 세 함수를 그대로 부른다.
   - 쓰기 재료가 '꼭 쓸 것만'(`Settings.write_material = "lean"`)이면 본문 쓰기 · 고쳐 쓰기의 스토리보드 블록이 `lean_board_block` 이 된다. 이 블록은 '# 이번 화에서 어기면 안 되는 것' · '# 이번 화에 쓸 것' 두 머리글로 나뉜다(정할 것 12).
   - `write_head` 는 장편 캐시 경계 힌트로 `build_episode_context(head_only=True)` 를 부르므로 같은 설정을 따라야 경계가 맞는다.
   - 부분 고치기 머리(`passage_head`)는 `build_episode_context` 를 거치지 않고 `static_context` 와 `relevant_facts` 를 바로 부른다. 이번 일감에서는 따르지 않는다.
   - 검수 · 상태 변경안 · 기획 · 플레이 요청은 이번 일감에서 따르지 않는다. 검수는 앞선 본문 전체를 보는 예외라 블록 끄기와 뜻이 다르다.
   - 화면 예산 칸도 위 요청이 쓰는 `BUDGET` 키만 보인다: `facts` · `story_past` · `story_arc` · `secrets` · `deadlines` · `cast` · `travel` · `spots` · `stage` · `address` · `stat_lines` · `relations` · `pairs` · `states`.
   - 보이지 않는 키: `check_*` · `plan_*` · `plot_*` · `play_*` · `rev_*` · `impact_*`, `places` · `storylines`, 상태 변경안 키(`state_secrets`, #414 에서 생긴 `state_facts`).
   - 여러 요청이 함께 쓰는 키(아래 '함께 쓰는 예산 키' 표)는 받는 함수 안의 기본 읽기를 그대로 둔다. 쓰기 경로에서만 `context.budget(p, key)` 값을 인자로 넘긴다.
5. 지시문 꼬리 — 추천: `episode_prompt` 가 `build_episode_context` 뒤에 붙이는 모든 글은 보기에는 '지시문' 블록으로 보이되 끌 수 없다.
   - 지금 그 글(차례대로): `opening_rules`(1~3화만), 쓰기 지시(4화부터 `RETOLD_LINE` 구절, `shift_label` 조건 줄, speech_style 대사 예시 줄 포함), `focus_line(p, sb)`(기본은 `FOCUS_LINE`, lean 이고 스토리보드가 중심 장면을 골랐으면 그 장면 문장), `priority_line`, `statwin.write_rule`, `attire_write_rule`, `ending_line`.
   - 그 뒤에 큐 시트 블록(`cue_write_block`)과 작가 연출 지시(`direction_block`, 맨 끝)가 붙는다. 연출 지시는 정할 것 14 에서 정한다.
   - 지시문은 블록 문구와 같이 `prompts.py` 가 정하는 몫이다(Q10).
   - 큐 시트 블록(`cue_write_block`)은 그 화에 저장된 큐 시트에 큐가 있고, `use_cues` 가 켜져 있고, 쓰기 재료가 고정점만(`board.fixed_only`)이 아닐 때 들어간다.
   - `use_cues` 는 쓰기 요청의 큐 시트 선택(`body.cues`), 자동 집필의 `no_cues`, 다시 생성의 `skipped` 가 정한다. `Settings.cue_sheet` 는 큐 시트를 만들지만 정하고, 꺼도 저장된 시트는 들어간다.
   - 그래서 큐 시트 블록은 블록 설정에 넣지 않고, 보기에서 이 규칙을 가리킨다.
6. 예산 값의 범위 — 추천: 기본값의 1/4 ~ 4배, 100자 단위.
   - 0 은 받지 않는다. 아예 빼려면 블록을 끈다(뜻이 둘로 갈리지 않게).
   - 지금 예산 인자를 받는 `stage_block` · `travel_block` · `spot_block` · `deadline_lines` 는 `budget or context.BUDGET[...]` 로 0 을 '기본값'으로 읽는다. 그래서 서버가 0 을 거절해야 한다.
   - 범위 밖 값은 서버가 거절하고 해요체 오류 문구를 돌려준다.
   - 개수 상한으로 줄이는 블록(열린 복선 `FORESHADOW_CAP`, 아는 정보 `KNOWS_KEEP` · `KNOWS_RECENT`, 최근 사실 `FACTS_RECENT`)은 `BUDGET` 키가 없다. 이번 일감에서는 예산 칸을 두지 않는다.
   - 같은 꼴의 고정값이 더 있다: `STATES_KNOWS_SHORT`(플롯 밖 인물의 아는 정보 3개), 직전 화 끝 1,500자(`prev_block`), 원고 재료 `MATERIAL_LIMIT`(6,000자) · `MATERIAL_SOURCES`(3화), `FORESHADOW_RECENT`(30화), `FACTS_FILTER_FROM`(60개). 이 값들도 예산 칸을 두지 않는다.
7. 뺀 항목과 이유를 모으는 방법 — 추천: 조립 함수들이 선택 인자 `trace`(기본 `None`)를 받아, 고른 항목과 뺀 항목을 이름 · 이유와 함께 적는다.
   - `trace` 가 `None` 이면 지금과 같은 일을 하고 같은 문자열을 돌려준다.
   - `contextvars` 로 숨겨 넘기는 방법보다 시험에서 보이고 스레드 문제가 없다.
   - 지금 `fit_named` · `fit_cast` · `pick_facts` · `pick_secrets` · `pick_knows` 는 (들어간 항목, 뺀 수)를 돌려주고 뺀 항목의 이름은 돌려주지 않는다.
   - `story_parts` 는 글 둘만 돌려주어 뺀 묶음 수가 `PAST_DROPPED` 줄 안에만 있다. `fit_states` 는 뺀 수를 머리글 글로만 준다.
   - `relevant_foreshadows` · `serial_relations`(`context.fit_lines`) · `relevant_facts` 의 단편 경로도 뺀 수만 돌려준다.
   - 그래서 이 함수들이 `trace` 에 뺀 항목 이름과 이유를 적게 손본다.
   - `state_view` 는 인물마다 `pick_knows` 의 뺀 수를 더해 `knows_note` 머리글에 적는다. 그래서 `state_view` 도 `trace` 를 받아 인물 이름과 함께 넘긴다.
   - 열린 복선의 뺀 수는 `keep` 으로 거른 것과 `rank_foreshadows`(`FORESHADOW_CAP`)로 자른 것의 합이다. 이유를 나누려면 두 단계를 따로 적는다('아크와 무관' · '개수 상한').
   - 장편 '# 열린 복선' 블록은 `serial_foreshadow_block` 이 복선마다 `foreshadow_line` 한 줄로 만든다(#420). 블록 안에서는 더 빼지 않는다. 단편은 늘 `dump(fs)` 다.
   - 조립 결과를 바꾸는 ContextVar 가 이미 하나 있다: `prompts.FORESHADOW_JSON`(기본 거짓, 블록 시험만 켬). 보기와 '설정 없는 작품은 같은 요청' 시험은 이 값이 기본일 때를 본다.
   - `fit_named` · `fit_cast` · `pick_facts` · `pick_knows` · `pick_secrets` 는 `context.py` 에 있고, `fit_states` · `story_parts` · `state_view` · `relevant_foreshadows` 는 `prompts.py` 에 있다.
8. 활성 이유의 이름 — 추천: 이 일감에서는 지금 있는 이유만 보인다: 늘 넣기(`context = "always"` 또는 주역), 이번 화 플롯 등장, 이름 발견(플롯 · 직전 화 끝), 관련 점수, 최근 N개, 아크 회수 · 기한.
   - 지금 넣는 이유는 더 있다: 복선의 작품 · 부 단위(`foreshadow_rank` 3 · 4위), 사실이 `FACTS_FILTER_FROM`(60)개 이하라 전부, 단편 사실에 이번 화 인물 이름이 있음, 관계 블록에서 늘 넣는 고른 비밀 줄, '항상' 조연 · 단역이 없을 때 이번 화 조연 · 단역 전부(`fit_cast`), 오랜만의 재등장(`return_block`, `context.RETURN_GAP` 10화).
   - 장편 확정 사실 줄은 `prompts.fact_rows` 가 들어온 화를 '(n화)'로 앞에 붙인다. `trace` 의 항목 이름은 이 표시를 뗀 사실 글이고, 들어온 화는 이유 쪽에 보일 수 있다.
   - 02(Activation)가 들어오면 Q17 의 이유(늘 넣기 > 키워드 직접 발견 > 재귀 > 유지)로 바꾼다.
   - 이유 이름은 `context.py` 한 곳의 상수로 두어 02 와 이 일감이 같은 말을 쓴다(Q7 '판정은 `context.py` 만').
9. 정적 블록을 바꿀 때 알림 — 추천: 앞쪽 블록(`static_context` 안의 블록과 장편의 부 · 아크 구조, 접은 줄거리)을 끄거나 그 예산을 바꾸면 '다음 요청부터 캐시가 처음부터 다시 쌓여요' 를 한 번 보인다.
10. 자동 집필 중에 바꿀 때 — 추천: 설정은 요청을 조립할 때 읽으므로 다음 화부터 따른다. 따로 멈추지 않는다.
11. 조연 · 단역 설정 — 정함(2026-11-08, Q31): 이번 화 플롯에 나오는 인물은 주연 · 조연 · 단역 모두 불변 설정을 끌 수 없다. 이번 화에 나오지 않는 조연 목록은 끌 수 있다.
    - 2026-11-09 확인: `extra_block`(이번 화 플롯의 조연 · 단역)과 `named_block`(장편만, 플롯 목록 밖이지만 플롯 글이나 직전 화 끝에 이름이 나온 조연 · 단역)은 함수로는 나뉘지만 장편 조립에서 한 문자열로 이어 넘긴다.
    - 이번 화에 나오지 않는 '항상' 조연 · 단역은 `static_context` 의 '# 인물 설정'(`static_characters`) 안에 주역과 함께 들어간다. 따로 끌 수 없다(정할 것 15).
    - `cast` 예산은 이번 화에 나오는 인물의 설정을 빼지 않는 범위에서만 줄일 수 있다.
12. lean 스토리보드의 두 머리글 — 추천: `lean_board_block` 의 두 머리글('# 이번 화에서 어기면 안 되는 것' · '# 이번 화에 쓸 것')을 한 스토리보드 블록으로 본다.
    - 스토리보드 블록의 넣고 빼기는 지금처럼 `Settings.write_material` 과 `use_board` 가 정한다. 블록 설정은 다시 다루지 않는다.
    - 다른 안: 두 조각을 따로 보이고 따로 끈다. 이 안은 '어기면 안 되는 것'을 끌 수 있어 고정점이 깨질 수 있다.
13. '실제 토큰 세기'의 사용량 기록 — 추천: `usage.record` 로 남긴다. 작업 이름은 '토큰 세기'로 따로 붙이고, 입력 · 출력 토큰은 0 으로 적어 비용 0 으로 남긴다.
    - 2026-11-09 확인: Anthropic 문서는 토큰 세기가 무료이고 요청 수 한도만 따로 있다고 적는다(docs.claude.com 의 token counting).
    - 2026-11-09 확인: Firebase AI Logic 문서는 Gemini countTokens 호출에 요금이 없다고 적는다. Gemini API 를 바로 부르는 경로의 요금은 공식 문서에서 확인하지 못했다.
    - 로컬 백엔드의 `/tokenize` 는 요금이 없다.
    - 까닭: AGENTS.md 는 새 API 호출 경로가 `usage.record` 를 부르게 한다.
    - 앞선 예: Gemini 캐시 만들기 기록은 작업 이름을 따로 붙여 남긴다.
    - 다른 안: 기록하지 않는다(지금 `research.py` 와 같음).
14. 작가 연출 지시(`direction_block`) — 추천: 보기에 '작가 연출 지시' 블록으로 따로 보이고, 블록 설정으로 끌 수 없게 둔다. 빼려면 작가가 아크 · 화의 연출 지시 칸을 비운다.
    - 지금 코드: `episode_prompt` 는 큐 시트 블록 뒤 맨 끝에 '# 작가 연출 지시'(아크 `Arc.direction` → 화 `Episode.direction`)를 붙인다. 둘 다 비면 붙지 않는다.
    - 지금 코드: `priority_line` 은 지시가 있으면 우선 차례에 '작가 연출 지시'를 넣는다.
    - 지금 코드: `cue_score_prompt` · `cue_head` 는 `episode_prompt(direction=False)` 를 쓰고 자기 글 맨 끝에 이 블록을 다시 붙인다. 보기도 그 자리를 따른다.
    - 지금 코드: `storyboard_prompt` 는 `direction_texts` 로 읽은 지시를 요구사항의 `focus` 줄 괄호 안에 넣는다. 블록이 아니므로 보기에서는 요구사항 안에 보인다.
    - 다른 안: 끌 수 있는 블록으로 둔다. 이 안은 스토리보드의 `focus` 줄도 따를지 함께 정해야 한다.
15. 이번 화에 나오지 않는 조연 · 단역 — 추천: 장편 `named_block`(이름이 나온 조연 · 단역)을 끌 수 있는 블록으로 나눈다. '항상' 조연 · 단역은 '# 인물 설정' 안에 두고 끌 수 없다.
    - Q31 의 '이번 화에 나오지 않는 조연 목록은 끌 수 있다'를 지금 코드에 맞게 푼 것이다.
    - `named_block` 은 플롯 목록 밖의 인물이라 이번 화에 나오지 않을 수 있다. 그래서 Q31 의 '끌 수 있는 목록'에 가장 가깝다.
    - '항상' 조연 · 단역은 작가가 인물마다 `context = "always"` 로 고른 것이다. 빼려면 그 인물의 넣기 설정을 바꾼다.
    - 다른 안: `static_characters` 에서 '항상' 조연 · 단역을 따로 떼어 끌 수 있는 블록으로 만든다. 이 안은 `static_context`(캐시 앞부분)가 갈라진다.

### 함께 쓰는 예산 키

| 키 | 쓰는 요청 | 받는 함수 |
|---|---|---|
| `address` | 쓰기 · 검수 · 상태 변경안 | `address.block` (예산 인자가 없어 더한다) |
| `deadlines` | 쓰기 · 검수 · 기획 · 상태 변경안 · 플레이 | `timeline.deadline_lines` 는 이미 `budget` 인자를 받는다. 부르는 함수 넷(`timeline.episode_block`, 스토리보드가 있을 때 `board.deadline_rows`, `timeline.plan_block`, `timeline.state_block`)이 예산을 넘겨받게 더한다 |
| `facts` | 쓰기 · 부분 고치기 | `prompts.relevant_facts`. 지금 `budget` 인자는 예산 값이 아니라 `BUDGET` 키 이름이다. 예산 값 인자(예: `limit`)를 더해 `build_episode_context` 에서만 넘긴다 |
| `spots` | 쓰기 · 검수 | `mapprompt.spot_block` |
| `travel` | 쓰기 · 검수 | `mapprompt.travel_block` |
| `story_past` · `story_arc` | 쓰기 · 기획 · 검수 | `prompts.story_parts` (예산 인자가 없어 더한다. 기획 · 검수의 `story_so_far` 경로는 기본 읽기 그대로) |

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/prompts.py` | `BLOCKS` 목록, 블록 조각을 모으는 조립(`context_parts` · `serial_parts` · `static_parts` · `episode_parts`), 꺼진 블록 건너뛰기, 지시문 꼬리를 조각으로 보이게 하기 |
| `canon/prompts.py` | `static_context` 에 설정을 따를지 정하는 인자(기본은 따르지 않음) |
| `canon/prompts.py` | `fit_states` · `story_parts` 가 `trace` 에 뺀 항목 이름을 적기 |
| `canon/prompts.py` | 쓰기 경로의 `context.BUDGET[key]` 직접 읽기를 `context.budget(p, key)` 로 바꾸기. 화면 예산 키는 `context.WRITE_KEYS` 14개다(정할 것 4 의 목록). `places`(스토리보드 요청의 `places_line`)는 화면 키가 아니라 기본 읽기 그대로다 |
| `canon/prompts.py` | `story_parts` · `relevant_facts` · `stage_block` 은 다른 요청도 부르므로 기본 읽기를 두고, 쓰기 경로에서만 예산 값을 인자로 넘긴다 |
| `canon/context.py` | 작품 예산을 읽는 `budget(p, key)`, 이유 이름 상수, `fit_named` · `fit_cast` · `pick_facts` · `pick_knows` · `pick_secrets` 가 `trace` 에 뺀 항목 이름을 적기 |
| `canon/address.py` · `canon/timeline.py` · `canon/board.py` · `canon/statwin.py` · `canon/pairlog.py` · `canon/maps/prompt.py` · `prompts.stage_block` | 예산으로 뺀 줄을 짧은 이름(`context.trace_label`, 약 40자)과 '예산 넘음'으로 적는 `trace` 인자. `None` 이면 글이 그대로다 |
| `canon/schema.py` | `Settings.blocks` · `Settings.budgets` 와 `BlockSetting` · `BudgetSetting` 모델 |
| `canon/web.py` | `/episodes/{n}/context` 응답 넓히기, 블록 설정 저장 엔드포인트 |
| `canon/static/write.js` | 컨텍스트 대화상자(`ctxDialogHtml`)와 쓰기 화면의 펼치는 곳 두 곳(`details[data-ctx-toggle]`)이 함께 쓰는 `ctxList` 를 블록 표로 바꾸기 |
| `canon/static/settings.js` | 블록 켜기 · 끄기, 예산 칸. '이 작품' 갈래(`SET_CATS` 의 `preset` · `writing` · `backup`)에 갈래를 더하거나 `writing` 에 묶음을 더하고 `SET_ROWS` · `setRowHtml` · `setChange` 를 함께 고친다. 쓰기 화면 링크는 `openSettings(갈래)` 로 연다 |
| `canon/address.py` | `block` 에 예산 인자를 더한다. 기본 읽기(`BUDGET["address"]`)는 그대로 둔다 |
| `canon/timeline.py` | `episode_block` 이 예산을 받아 `deadline_lines` 에 넘기게 한다. 기본 읽기는 그대로 둔다 |
| `canon/board.py` | `deadline_rows` 가 예산을 받아 `deadline_lines` 에 넘기게 한다(스토리보드가 있는 화의 기한 줄) |
| `canon/maps/prompt.py` | `travel_block` · `spot_block` 은 이미 예산 인자를 받는다. 예산으로 뺀 줄을 적는 `trace` 인자만 더한다 |
| `canon/statwin.py` | `lines_block` 에 예산 인자를 더한다(`stat_lines`). 기본 읽기는 그대로 둔다 |
| `canon/pairlog.py` | `write_block` · `write_lines` 는 이미 예산을 인자로 받는다. 예산으로 뺀 줄을 적는 `trace` 인자만 더한다 |
| `canon/elements.py` · `canon/storylines.py` | 바꾸지 않는다. `places` · `storylines` 는 화면 예산 키가 아니다 |

`agent.py` 는 바꾸지 않는다(Q29).
`canon/mock.py` 는 바꾸지 않는다. LLM 응답 형식이 바뀌지 않는다.

## 데이터 · 스키마

2026-11-09 정함: 끄고 켜기는 블록마다, 예산은 `BUDGET` 키마다 둔다. 블록 하나가 키를 여럿 쓰기 때문이다(관계 블록의 `relations` · `secrets`).

```python
class BlockSetting(BaseModel):
    id: str           # prompts.BLOCKS 의 블록 id
    on: bool = True   # False 면 장편 쓰기 가족 요청에서 뺀다

class BudgetSetting(BaseModel):
    key: str          # context.WRITE_KEYS 의 예산 키
    value: int        # 글자 예산, context.budget_range 안의 100 단위
```

- `Settings.blocks: list[BlockSetting] = []` 와 `Settings.budgets: list[BudgetSetting] = []` 를 더한다. 비어 있으면 지금과 같다.
- 기본값을 두므로 기존 `project.json` 이 그대로 읽힌다.
- 예산은 `context.budget(p, key)` 가 읽는다. 장편이고 `WRITE_KEYS` 의 키에 값이 있으면 그 값, 아니면 `BUDGET[key]` 다.
- 두 목록에는 기본값과 다른 것만 저장한다.
- `Settings` 는 LLM 이 채우는 스키마가 아니지만, 다른 설정과 같게 dict 대신 모델 목록을 쓴다.
- 블록을 넣고 빼는 설정이 이미 있다: 장편 `echo_block` 은 `Settings.recent_echoes`, 스토리보드 · 큐 시트 꼴은 `Settings.write_material` · `cue_sheet`, 인물 · 요소는 `context = "off"`, 시간 · 이동은 `timeline.enabled` · `atlas.travel.enabled`(상태 변경안 · 검수까지 함께 끄는 기능 스위치)다.
- `BLOCKS` 표는 이런 블록을 새 `on` 칸으로 다시 켜고 끄지 않고, 보기에서 그 설정을 가리킨다.
- 모르는 블록 id(뒤에 블록 이름이 바뀜)와 모르는 예산 키는 읽을 때 무시하고 지우지 않는다.
- 끌 수 없는 블록에 `on = False` 가 들어와도 조립은 넣는다. 저장 엔드포인트는 거절한다.

## 규칙

- 끌 수 없는 블록: 이번 화 플롯, 문체(`style_block`: 문체 예시와 스타일 프로필), 인물 설정(`static_characters` 의 불변 설정) (Q19).
- `static_characters` 에는 주역과 함께 '항상'(`context = "always"`)으로 둔 조연 · 단역도 들어가고, '넣지 않음' 주역은 빠진다(`context.core_ids`).
- 이번 화 플롯 인물 목록에 든 조연 · 단역 설정(`extra_block`)도 끌 수 없다. `cast` 예산만 바꾼다(정할 것 11).
- 인물 현재 상태(`states`)도 끌 수 없다(2026-11-09 정함). 상태창 줄(`statwin.write_rule`) · 스토리보드 · 옷차림 규칙(`attire_write_rule`)이 '[인물 현재 상태]'를 가리켜, 끄면 가리킬 곳이 없는 지시가 남는다. `states` 예산만 바꾼다.
- 장편 `named_block` 을 끌 수 있는지는 정할 것 15 에서 정한다.
- 블록 차례와 블록 문구는 바꿀 수 없다. 설정은 넣고 빼기와 예산만 정한다(Q10).
- 꺼진 블록은 머리글째 뺀다. 빈 머리글('없음')을 남기지 않는다.
- 꺼진 블록이 있으면 보기에 '작가가 끔' 으로 보이고, 요청 안에는 끈 사실을 적지 않는다.
- 예산을 넘겨 뺀 항목은 이름을 남긴다(Q17). 지금처럼 요청 안의 '(N개 생략)' 같은 줄은 그대로 둔다.
- 접은 줄거리에서 뺀 묶음(`PAST_DROPPED`)은 부 · 아크 이름으로 보인다.
- API 경로와 작업지시서 경로는 같은 설정을 따른다. 본문 쓰기는 둘 다 `episode_prompt` → `build_episode_context` 를 거치므로 설정을 조립 안에서 읽으면 맞는다(`brief_parts` · `brief_request`).
- 부분 고치기(`passage_head`)는 따로 조립하므로 이 설정을 따르지 않는다(정할 것 4).
- 보기는 실제 쓰기 요청과 같은 인자로 만든다. 지금 `web.context` 는 `write=False` 로 만들어 실제 요청과 세 곳이 다르다: 플롯(`write_plot` 대신 원래 플롯), 장편 `echo_block`(빠짐), lean 일 때 스토리보드(실제는 `lean_board_block`, 보기는 전체). 보기는 `episode_prompt` 와 같은 조각에서 만든다.
- 보기의 `episode_prompt` 인자: 그 화에 스토리보드가 있으면 `use_board` 를 켠다.
- 보기의 `episode_prompt` 인자: 그 화의 큐 시트가 `skipped` 가 아니면 `use_cues` 를 켠다. 다시 생성(`rewrite_prompt`)과 같은 규칙이다.
- 보기의 `episode_prompt` 인자: 1~3화 여는 방식(`approach`)은 비운다. 보기에 '여는 방식은 고른 뒤 정해져요'라고 적는다.
- 보기의 `episode_prompt` 인자: `direction` 은 켠다. 본문 쓰기와 다시 생성도 기본값으로 켠다. 연출 지시가 없으면 그 블록은 보이지 않는다.
- 대화 에이전트(`agent.py`)는 블록 설정과 예산을 읽지도 고치지도 않는다(Q29). 에이전트 도구 목록에 넣지 않는다.
- 캐시: 앞쪽 블록을 끄거나 예산을 바꾸면 `static_context` 가 바뀌어 `claude.cache_blocks` 가 앞 요청과 겹치는 부분이 줄어든다. 그 뒤 첫 요청은 캐시를 새로 쓴다.
- 캐시: Gemini 암묵적 캐시도 앞 요청을 통째로 품은 요청에만 맞으므로 같은 영향을 받는다.
- 캐시: 뒤쪽 블록(화마다 바뀌는 블록)은 끄거나 예산을 바꿔도 앞부분 캐시를 깨지 않는다.
- 캐시: 설정을 바꾼 작품은 쓰기 가족과 검수 가족의 `static_context` 가 달라져 두 가족이 앞부분 캐시를 함께 쓰지 못한다.
- 캐시: `pipeline` 은 `len(prompts.static_context(p))` 를 `PREFIX_HINT` 로 넘긴다. 쓰기 호출은 설정을 따르는 `static_context` 로 이 길이를 센다.
- 장편 예산은 화수에 따라 끝없이 커지지 않는다는 원칙을 지킨다. 예산 상한(정할 것 6)이 그 몫이다.
- 03 과 08(접은 줄거리 고르기)은 둘 다 `story_past` 예산을 읽는다. 둘 다 `context.budget(p, key)` 로 읽으면 겹치지 않는다. 먼저 머지한 쪽 위에 다른 쪽을 다시 맞춘다(Q30).

## 화면 · 명령줄 · 프롬프트

화면 문구는 해요체다.

- 쓰기 화면의 컨텍스트 대화상자(`#w-ctx`, 제목 'AI에게 보내는 컨텍스트')를 넓힌다.
  - 블록 표: 블록 이름, 글자 수, 추정 토큰, 예산(장편), 상태(넣음 · 작가가 끔 · 비어 있음).
  - 블록을 펼치면 그 블록 원문, 들어간 항목과 이유, 예산 때문에 뺀 항목 이름이 보인다.
  - '프롬프트 원문 보기'(`togglePrompt`)는 그대로 두고, 시스템 프롬프트와 요청 원문을 함께 보인다.
  - 합계 줄: 'N개 블록 · 합계 X자 · 약 Y토큰(추정)'. 지금 `ctxTotal()`(write.js)이 그리는 'N개 블록 · 합계 X자' 뒤에 붙이고, 값은 블록별 `tokens` 의 합이다. `ctxTotal` 을 세 곳이 함께 쓰므로 세 곳 모두에 나온다.
  - 블록 설정으로 가는 링크: '블록 설정 바꾸기'.
- 쓰기 화면의 펼치는 곳 두 곳도 `ctxList` 를 쓰므로 같은 블록 표를 보인다. 둘 다 본문이 없는 화에 보인다: 쓰기 시작 칸(`.w-go`)과 만든 스토리보드 시작 칸(`.w-board`)의 '직접 쓰기' 옆.
  - 펼치는 곳은 블록 표의 요약 줄(이름 · 글자 수 · 추정 토큰 · 상태)만 보인다.
  - 블록 원문, 항목과 이유, 뺀 항목은 대화상자에서만 보인다.
- 작품 설정 화면에 '프롬프트 블록' 칸을 더한다.
  - 블록마다 켜기 · 끄기 스위치. 끌 수 없는 블록은 잠금 표시와 '이 블록은 끌 수 없어요'.
  - 장편이면 예산 칸과 기본값, '기본값으로' 버튼.
  - 앞쪽 블록을 바꾸면 '다음 요청부터 캐시가 처음부터 다시 쌓여요' 안내(정할 것 9).
- 엔드포인트:
  - `GET /api/projects/{name}/episodes/{n}/context` 는 블록 목록을 돌려준다. 블록마다 `id` · `title` · `chars` · `tokens` · `on` · `locked` · `toggle` · `front` · `note` · `budgets` · `items` · `dropped` · `text` 다.
  - `budgets` 는 그 블록이 쓰는 예산 키마다 `{key, value, default, min, max}` 다. 단편은 빈 목록이다.
  - `items` · `dropped` 는 `{name, reason}` 목록이다. 꺼진 블록은 `on = false`, `chars` 0, `text` 빈 글이고 항목이 없다.
  - 지금 응답의 `title` · `chars` 는 그대로 남겨 지금 화면이 깨지지 않게 한다.
  - 이 엔드포인트는 `use_board` · `use_cues` · `approach` 를 쿼리 인자로 받지 않는다. 규칙의 '보기의 `episode_prompt` 인자' 줄대로 서버가 정한다.
  - `GET /api/projects/{name}/blocks` 는 `{serial, blocks, budgets}` 를 돌려준다. `blocks` 는 블록마다 `{id, title, locked, toggle, front, note, on, keys}`, `budgets` 는 장편만 `{key, value, default, min, max}` 다.
  - `PUT /api/projects/{name}/blocks` 는 본문 `{blocks: list[BlockSetting], budgets: list[BudgetSetting]}` 를 받아 두 목록을 바꿔 저장하고 작품을 돌려준다.
  - 이 저장은 단편 · 모르는 id 나 키 · 끌 수 없는 블록의 off · 범위 밖이거나 100 단위가 아니거나 0 인 예산을 400 으로 거절한다.
  - `POST /api/projects/{name}/episodes/{n}/count-tokens` 는 `{tokens, estimate, note}` 를 돌려준다. 셀 수 없는 백엔드면 `tokens` 가 `null` 이다.
  - Swift 개발이 멈춰 있어 `scripts/make_openapi.py` 는 돌리지 않는다(AGENTS.md).
- 명령줄: 이번 일감에서는 더하지 않는다. 필요하면 `brief` 출력으로 원문을 본다.
- 프롬프트: 블록 문구와 차례는 바뀌지 않는다. 꺼진 블록이 빠지고 예산이 바뀐 블록의 항목 수만 달라진다.

## 시험

- 새 시험 `tests/test_block_settings.py`:
  - `Settings.blocks` 가 빈 작품에서 `episode_prompt` 결과가 고치기 전과 같다(단편 · 장편 mock 작품 둘 다).
  - 블록을 끄면 그 머리글이 요청에서 빠지고 다른 블록 차례는 그대로다.
  - 끌 수 없는 블록(플롯 · 문체 · 인물 설정 · 조연 · 단역 설정)은 `on = False` 여도 들어가고, 저장 엔드포인트는 거절한다.
  - 예산을 줄이면 `dropped` 에 뺀 항목 이름이 생기고, 요청 길이가 줄어든다.
  - 단편 작품에는 예산 칸이 없고 예산 값을 넣어도 요청이 같다.
  - `brief_parts(p, n, "episode")` 의 본문과 `episode_prompt` 가 같은 설정을 따른다.
  - 범위 밖 예산과 0 은 거절한다.
  - 모르는 블록 id 가 든 `project.json` 이 읽힌다.
- `tests/test_agents_docs.py`: 새 파일이 없으면 고칠 것이 없다.
- 에이전트 도구 목록에 블록 설정 도구가 없는지 보는 줄을 에이전트 시험에 더한다.
- `context.BUDGET` 을 바꾸던 시험(`monkeypatch.setitem(context.BUDGET, …)`)은 기본값 경로로 그대로 돈다.
- 화면: `write.js` 의 대화상자를 브라우저에서 열어 블록 표 · 펼치기 · 원문을 본다.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- `ruff check canon tests scripts`.

## 문서

- `docs/modules/core.md` 의 `canon/context.py` 절: `budget(p, key)`, 이유 상수, `trace` 인자.
- `docs/modules/core.md` 의 `canon/prompts.py` 절: `BLOCKS`, 블록 조각 조립, 꺼진 블록 건너뛰기.
- `docs/modules/core.md` 의 `canon/schema.py` 절: `Settings.blocks`.
- `docs/modules/core.md` 의 `canon/web.py` 절: 넓힌 `context` 응답, `PUT /blocks`.
- `docs/modules/web.md` 의 `canon/static/write.js` 절: 컨텍스트 대화상자.
- 화면 모양이 바뀌므로 `docs/design/` 의 해당 컴포넌트 문서.
- README.md 의 쓰기 화면 설명, DESIGN.md 4장 '컨텍스트 조립' 에 블록 설정과 캐시 영향.
- 이 폴더의 [plan.md](../plan.md) 상태와 [README.md](../README.md) 정한 규칙.

## 확인하지 못할 것

- 블록을 끄거나 예산을 바꾼 뒤 실제 Claude · Gemini 캐시 적중이 얼마나 떨어지는지. 키가 있는 세션에서 `usage` 의 캐시 토큰을 앞뒤로 견줘야 한다.
- 블록을 끈 요청이 본문 품질에 어떤 영향을 주는지. 작가가 직접 써 보고 판단한다.
- 추정 토큰(`CHARS_PER_TOKEN` 1.7)과 실제 토큰의 차이. 쓰기 백엔드의 `count_tokens` 로 몇 화를 재 봐야 한다.

## 비용

- 이 일감은 LLM 을 부르는 새 경로를 더하지 않는다. 시험은 가짜 응답(mock)만 쓴다.
- `count_tokens` 호출에 비용이 드는지는 정할 것의 '시작 전에 확인할 것'으로 본다. 비용이 들면 호출 수를 어림해 PR 에 적는다.
