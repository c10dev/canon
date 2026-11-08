# 03. 프롬프트 보기와 블록 설정

상태: 설계 · 계획: [plan.md](../plan.md) 의 3번 · 먼저: —

## 목표

작가가 쓰기 화면에서 AI에게 실제로 보내는 요청 원문을 본다.
요청을 블록으로 나눠 블록마다 글자 수, 토큰 수, 예산을 본다.
예산을 넘겨 뺀 항목의 이름과, 들어간 항목마다 들어간 이유를 본다.
작품마다 블록을 끄고 켜고, 블록 예산(`context.BUDGET` 의 값)을 바꾼다.
블록 차례와 블록 문구는 `prompts.py` 에 그대로 둔다(2026-11-08 사용자 결정 Q10).
설정을 건드리지 않은 작품은 요청이 한 글자도 바뀌지 않는다.

## 정할 것

1. 블록을 나누는 단위 — 추천: `prompts.py` 에 블록 id 목록(`BLOCKS`: id, 화면 이름, 끌 수 있는지, 쓰는 `BUDGET` 키)을 두고, 조립 함수가 블록 조각 목록을 만든 뒤 이어 붙여 요청 문자열을 만든다.
   - 지금 `web.context` 는 요청을 `^# ` 으로 자른다. 그래서 `style_block` 안의 '# 문체 예시' 와 '# 스타일 프로필' 이 따로 잡히고 `static_context` 의 묶음이 보이지 않는다.
   - 조각 목록에서 보기와 실제 요청을 함께 만들면 둘이 어긋나지 않는다.
   - `BLOCKS` 표에는 예산 종류(글자 · 개수 · 없음)도 적는다.
   - `static_context` 는 쓰기 요청 밖에서도 쓴다: `check_material`(검수 · 상태 변경안), `fix_recheck_prompt`, `polish_prompt`, `style_example_prompt`, `passage_head`.
   - 그래서 `static_context` 에 설정을 따를지 정하는 인자를 두고 기본은 따르지 않는다. 쓰기 경로(정할 것 4)만 이 인자를 켠다.
2. 토큰 수 — 추천: 기본은 `context.est_tokens`(글자 수 ÷ `CHARS_PER_TOKEN` 1.7) 추정값이고, 화면에 '추정'이라고 쓴다.
   - '실제 토큰 세기' 버튼을 두면 쓰기 단계 백엔드의 `count_tokens` 로 요청 전체를 한 번 센다.
   - `count_tokens` 는 `LLM` Protocol 에 없다. Gemini · Claude API · 로컬 백엔드에만 있다.
   - `ClaudeCodeLLM.count_tokens` 는 늘 `None` 을 돌려준다. mock 과 `BatchLLM` 에는 이 메서드가 없다.
   - `research.py` 의 `getattr(llm, "count_tokens", None)` 패턴을 다시 쓴다.
   - 메서드가 없거나 `None` 을 돌려주면 버튼 자리에 '이 백엔드는 토큰을 셀 수 없어요'를 보인다.
   - 블록마다 실제 토큰을 세면 호출이 블록 수만큼 늘어 하지 않는다.
   - `count_tokens` 호출에 비용이 드는지, `usage.record` 에 잡아야 하는지는 시작 전에 확인할 것.
3. 단편의 블록 설정 — 정함(2026-11-08, Q32): 단편(`form = "short"`)은 블록 끄고 켜기도 예산 칸도 보여 주지 않는다. 보기 강화만 받는다.
   - 단편 쓰기 요청도 쓰는 `BUDGET` 키가 있다: `deadlines`(`timeline.deadline_lines`), `stage`(`stage_block`), `travel` · `spots`(`maps/prompt.py`), `stat_lines`(`statwin.lines_block`).
   - 그래서 `context.budget(p, key)` 는 단편 작품에서는 저장한 값과 상관없이 늘 `BUDGET` 기본값을 돌려준다.
   - 단편은 저장한 블록 설정이 있어도 무시하고 지금 요청을 그대로 만든다.
4. 설정이 미치는 요청 — 추천: 본문 쓰기 가족만 따른다.
   - `build_episode_context` 를 바로 부르는 곳: 본문 쓰기(`episode_prompt`), 고쳐 쓰기(`rework_prompt`), 스토리보드(`storyboard_prompt`), 큐 시트(`cue_sheet_prompt`).
   - 다시 생성(`rewrite_prompt`)은 `episode_prompt` 를 거쳐 따른다.
   - `write_head` 는 장편 캐시 경계 힌트로 `build_episode_context(head_only=True)` 를 부르므로 같은 설정을 따라야 경계가 맞는다.
   - 부분 고치기 머리(`passage_head`)는 `build_episode_context` 를 거치지 않고 `static_context` 와 `relevant_facts` 를 바로 부른다. 이번 일감에서는 따르지 않는다.
   - 검수 · 상태 변경안 · 기획 · 플레이 요청은 이번 일감에서 따르지 않는다. 검수는 앞선 본문 전체를 보는 예외라 블록 끄기와 뜻이 다르다.
   - 화면 예산 칸도 위 요청이 쓰는 `BUDGET` 키만 보인다(`check_*` · `plan_*` · `play_*` · `rev_*` 는 보이지 않음).
   - 여러 요청이 함께 쓰는 키(아래 '함께 쓰는 예산 키' 표)는 받는 함수 안의 기본 읽기를 그대로 둔다. 쓰기 경로에서만 `context.budget(p, key)` 값을 인자로 넘긴다.
5. 지시문 꼬리 — 추천: `episode_prompt` 가 `build_episode_context` 뒤에 붙이는 모든 글은 보기에는 '지시문' 블록으로 보이되 끌 수 없다.
   - 지금 그 글: `opening_rules`, 쓰기 지시(`shift_label` 조건 줄 포함), `FOCUS_LINE`, `priority_line`, `statwin.write_rule`, `attire_write_rule`, `ending_line`.
   - 지시문은 블록 문구와 같이 `prompts.py` 가 정하는 몫이다(Q10).
   - 큐 시트 블록(`cue_write_block`)은 이미 `Settings.cue_sheet` 로 켜고 끄므로 이 설정에 넣지 않고, 보기에서 그 설정을 가리킨다.
6. 예산 값의 범위 — 추천: 기본값의 1/4 ~ 4배, 100자 단위.
   - 0 은 받지 않는다. 아예 빼려면 블록을 끈다(뜻이 둘로 갈리지 않게).
   - 범위 밖 값은 서버가 거절하고 해요체 오류 문구를 돌려준다.
   - 개수 상한으로 줄이는 블록(열린 복선 `FORESHADOW_CAP`, 아는 정보 `KNOWS_KEEP` · `KNOWS_RECENT`, 최근 사실 `FACTS_RECENT`)은 `BUDGET` 키가 없다. 이번 일감에서는 예산 칸을 두지 않는다.
7. 뺀 항목과 이유를 모으는 방법 — 추천: 조립 함수들이 선택 인자 `trace`(기본 `None`)를 받아, 고른 항목과 뺀 항목을 이름 · 이유와 함께 적는다.
   - `trace` 가 `None` 이면 지금과 같은 일을 하고 같은 문자열을 돌려준다.
   - `contextvars` 로 숨겨 넘기는 방법보다 시험에서 보이고 스레드 문제가 없다.
   - 지금 `fit_named` · `fit_cast` · `pick_facts` · `pick_secrets` · `story_parts` 는 뺀 수만 돌려주므로 이름을 돌려주게 손본다.
   - `fit_named` · `fit_cast` · `pick_facts` · `pick_secrets` 는 `context.py` 에 있고, `fit_states` · `story_parts` 는 `prompts.py` 에 있다.
8. 활성 이유의 이름 — 추천: 이 일감에서는 지금 있는 이유만 보인다: 늘 넣기(`context = "always"` 또는 주역), 이번 화 플롯 등장, 이름 발견(플롯 · 직전 화 끝), 관련 점수, 최근 N개, 아크 회수 · 기한.
   - 02(Activation)가 들어오면 Q17 의 이유(늘 넣기 > 키워드 직접 발견 > 재귀 > 유지)로 바꾼다.
   - 이유 이름은 `context.py` 한 곳의 상수로 두어 02 와 이 일감이 같은 말을 쓴다(Q7 '판정은 `context.py` 만').
9. 정적 블록을 바꿀 때 알림 — 추천: 앞쪽 블록(`static_context` 안의 블록과 장편의 부 · 아크 구조, 접은 줄거리)을 끄거나 그 예산을 바꾸면 '다음 요청부터 캐시가 처음부터 다시 쌓여요' 를 한 번 보인다.
10. 자동 집필 중에 바꿀 때 — 추천: 설정은 요청을 조립할 때 읽으므로 다음 화부터 따른다. 따로 멈추지 않는다.
11. 조연 · 단역 설정 — 정함(2026-11-08, Q31): 이번 화 플롯에 나오는 인물은 주연 · 조연 · 단역 모두 불변 설정을 끌 수 없다. 이번 화에 나오지 않는 조연 목록은 끌 수 있다.
    - 시작 전에 확인할 것: `extra_block` · `named_block` 가운데 이번 화에 나오지 않는 인물을 담는 부분이 따로 나뉘는지.
    - `cast` 예산은 이번 화에 나오는 인물의 설정을 빼지 않는 범위에서만 줄일 수 있다.

### 함께 쓰는 예산 키

| 키 | 쓰는 요청 | 받는 함수 |
|---|---|---|
| `address` | 쓰기 · 검수 · 상태 변경안 | `address.block` (예산 인자가 없어 더한다) |
| `deadlines` | 쓰기 · 검수 · 기획 · 상태 변경안 | `timeline.deadline_lines` (`episode_block` 이 예산을 넘겨받게 더한다) |
| `facts` | 쓰기 · 부분 고치기 | `prompts.relevant_facts` |
| `spots` | 쓰기 · 검수 | `mapprompt.spot_block` |
| `travel` | 쓰기 · 검수 | `mapprompt.travel_block` |

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/prompts.py` | `BLOCKS` 목록, 블록 조각을 모으는 조립(`build_episode_context` · `serial_episode_context` · `static_context`), 꺼진 블록 건너뛰기, 지시문 꼬리를 조각으로 보이게 하기 |
| `canon/prompts.py` | `static_context` 에 설정을 따를지 정하는 인자(기본은 따르지 않음) |
| `canon/prompts.py` | `fit_states` · `story_parts` 가 `trace` 에 뺀 항목 이름을 적기 |
| `canon/prompts.py` | 쓰기 경로의 `context.BUDGET[key]` 직접 읽기(54곳 가운데 쓰기 요청에 드는 곳)를 `context.budget(p, key)` 로 바꾸기 |
| `canon/context.py` | 작품 예산을 읽는 `budget(p, key)`, 이유 이름 상수, `fit_named` · `fit_cast` · `pick_facts` · `pick_knows` · `pick_secrets` 가 `trace` 에 뺀 항목 이름을 적기 |
| `canon/schema.py` | `Settings.blocks` 와 `BlockSetting` 모델 |
| `canon/web.py` | `/episodes/{n}/context` 응답 넓히기, 블록 설정 저장 엔드포인트 |
| `canon/static/write.js` | 컨텍스트 대화상자(`ctxDialogHtml`)와 쓰기 화면의 펼치는 곳 두 곳(`details[data-ctx-toggle]`)이 함께 쓰는 `ctxList` 를 블록 표로 바꾸기 |
| `canon/static/settings.js` 또는 작품 설정 화면 | 블록 켜기 · 끄기, 예산 칸 (자리는 시작 전에 `docs/modules/web.md` 를 읽고 고른다) |
| `canon/address.py` | `block` 에 예산 인자를 더한다. 기본 읽기(`BUDGET["address"]`)는 그대로 둔다 |
| `canon/timeline.py` | `episode_block` 이 예산을 받아 `deadline_lines` 에 넘기게 한다. 기본 읽기는 그대로 둔다 |
| `canon/maps/prompt.py` | 바꾸지 않는다. `travel_block` · `spot_block` 은 이미 예산 인자를 받는다 |
| `canon/statwin.py` | `lines_block` 에 예산 인자를 더한다(`stat_lines`). 기본 읽기는 그대로 둔다 |
| `canon/pairlog.py` · `canon/elements.py` · `canon/storylines.py` | 바꾸지 않는다. `pairlog` 는 예산을 인자로 받고, `places` · `storylines` 는 쓰기 요청 밖의 블록이다 |

`agent.py` 는 바꾸지 않는다(Q29).
`canon/mock.py` 는 바꾸지 않는다. LLM 응답 형식이 바뀌지 않는다.

## 데이터 · 스키마

```python
class BlockSetting(BaseModel):
    id: str                      # prompts.BLOCKS 의 블록 id
    on: bool = True              # False 면 요청에서 뺀다
    budget: Optional[int] = None # None 이면 context.BUDGET 기본값
```

- `Settings.blocks: list[BlockSetting] = []` 를 더한다. 비어 있으면 지금과 같다.
- 기본값을 두므로 기존 `project.json` 이 그대로 읽힌다.
- 블록 하나가 `BUDGET` 키를 여럿 쓰면(예: 관계 블록의 `relations` · `secrets` · `address` · `pairs`) 예산은 키마다 따로 둔다. 이때 `BlockSetting` 대신 키 단위 목록이 필요한지는 정할 것 1 의 `BLOCKS` 표를 만들며 정한다.
- `Settings` 는 LLM 이 채우는 스키마가 아니지만, 다른 설정과 같게 dict 대신 모델 목록을 쓴다.
- 모르는 블록 id(뒤에 블록 이름이 바뀜)는 읽을 때 무시하고 지우지 않는다.
- 끌 수 없는 블록에 `on = False` 가 들어와도 조립은 넣는다. 저장 엔드포인트는 거절한다.

## 규칙

- 끌 수 없는 블록: 이번 화 플롯, 문체(`style_block`: 문체 예시와 스타일 프로필), 인물 설정(`static_characters` 의 불변 설정) (Q19).
- 이번 화 조연 · 단역 설정(`extra_block` · `named_block`)도 끌 수 없다. `cast` 예산만 바꾼다(정할 것 11).
- 블록 차례와 블록 문구는 바꿀 수 없다. 설정은 넣고 빼기와 예산만 정한다(Q10).
- 꺼진 블록은 머리글째 뺀다. 빈 머리글('없음')을 남기지 않는다.
- 꺼진 블록이 있으면 보기에 '작가가 끔' 으로 보이고, 요청 안에는 끈 사실을 적지 않는다.
- 예산을 넘겨 뺀 항목은 이름을 남긴다(Q17). 지금처럼 요청 안의 '(N개 생략)' 같은 줄은 그대로 둔다.
- 접은 줄거리에서 뺀 묶음(`PAST_DROPPED`)은 부 · 아크 이름으로 보인다.
- API 경로와 작업지시서 경로는 같은 설정을 따른다. 본문 쓰기는 둘 다 `episode_prompt` → `build_episode_context` 를 거치므로 설정을 조립 안에서 읽으면 맞는다(`brief_parts` · `brief_request`).
- 부분 고치기(`passage_head`)는 따로 조립하므로 이 설정을 따르지 않는다(정할 것 4).
- 보기는 실제 쓰기 요청과 같은 인자로 만든다. 지금 `web.context` 는 `write=False` 로 만들어 플롯 블록과 장편의 `echo_block` 이 실제 요청과 다를 수 있다. 보기는 `episode_prompt` 와 같은 조각에서 만든다.
- 보기의 `episode_prompt` 인자: 그 화에 스토리보드가 있으면 `use_board` 를 켠다.
- 보기의 `episode_prompt` 인자: 그 화의 큐 시트가 `skipped` 가 아니면 `use_cues` 를 켠다. 다시 생성(`rewrite_prompt`)과 같은 규칙이다.
- 보기의 `episode_prompt` 인자: 1~3화 여는 방식(`approach`)은 비운다. 보기에 '여는 방식은 고른 뒤 정해져요'라고 적는다.
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
  - 합계 줄: 'N개 블록 · 합계 X자 · 약 Y토큰(추정)'.
  - 블록 설정으로 가는 링크: '블록 설정 바꾸기'.
- 쓰기 화면의 펼치는 곳 두 곳(쓰기 버튼 아래, 본문이 없는 화)도 `ctxList` 를 쓰므로 같은 블록 표를 보인다.
  - 펼치는 곳은 블록 표의 요약 줄(이름 · 글자 수 · 추정 토큰 · 상태)만 보인다.
  - 블록 원문, 항목과 이유, 뺀 항목은 대화상자에서만 보인다.
- 작품 설정 화면에 '프롬프트 블록' 칸을 더한다.
  - 블록마다 켜기 · 끄기 스위치. 끌 수 없는 블록은 잠금 표시와 '이 블록은 끌 수 없어요'.
  - 장편이면 예산 칸과 기본값, '기본값으로' 버튼.
  - 앞쪽 블록을 바꾸면 '다음 요청부터 캐시가 처음부터 다시 쌓여요' 안내(정할 것 9).
- 엔드포인트:
  - `GET /api/projects/{name}/episodes/{n}/context` 는 블록마다 `id` · `title` · `chars` · `tokens` · `budget` · `default_budget` · `on` · `locked` · `items`(이름 · 이유) · `dropped`(이름 · 이유) · `text` 를 돌려준다.
  - 지금 응답의 `title` · `chars` 는 그대로 남겨 지금 화면이 깨지지 않게 한다.
  - 이 엔드포인트는 `use_board` · `use_cues` · `approach` 를 쿼리 인자로 받지 않는다. 규칙의 '보기의 `episode_prompt` 인자' 줄대로 서버가 정한다.
  - `PUT /api/projects/{name}/blocks` 는 `list[BlockSetting]` 을 받아 저장한다. 다른 설정 엔드포인트(`set_check_widen` 등)와 같은 꼴이다.
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
