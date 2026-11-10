# 모듈 지도: 이야기 데이터 기능과 그 화면

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/abilities.py`

- 스킬 · 특성 도감
- 상태창 목록 조각(스킬 · 특성 · 칭호, 이름 `LIST_NAMES` 이거나 조각이 둘 이상, 인벤토리는 도감 항목이 가리킬 때만 `list_stats`)마다 설명 · 효과 · 대가 · 등급별 효과(`Project.abilities`, `Ability`)
- 정의는 인물 사이에 하나
- 등급 꼬리를 뗀 이름으로 잇는다(`split`, `key`, `find`, `statwin._GRADE` 재사용)
- 가진 인물(`owners`)
- 얻은 화 · 바뀐 기록은 `stat_log` 에서 계산(`history`, `acquired`, 저장 안 함)
- 도감에 없는 조각(`unlinked`)
- AI 에게 보이는 한 줄(`line`: 이름(=다른 이름) [상태창 항목 · 가진 인물 등급]: 효과 / 가진 등급 효과 / 대가, 다음 단계 프롬프트가 같은 함수를 쓴다)
- 화면 값(`catalog`, `lookup`)
- 작가 편집(`upsert`, `remove`)
- 명령줄 `abilities`
- LLM 호출 없음
- 화면은 `static/abilities.js`

### `canon/address.py`

- 호칭 · 말씨
- 인물 A 가 B 를 부르는 말 · 말씨(`AddressForm`, 방향마다 하나, `Project.address_forms`)
- 작가가 정하기(`set_form`, 1화 반영 뒤 작가 기록)
- 상태 변경안의 바뀜(`StateDelta.address_changes`, `AddressChange`) 정리 · 반영 · 되돌리기(features 훅 `clean_delta` · `apply_delta` · `revert`, 기록 `Project.address_log`)
- 자동 집필 · `run -y` · 플레이의 남겨 두기(`hold`, `Project.address_held`, `take_held` · `drop_held`)
- 프롬프트 블록(`block`, 장편 예산 `context.BUDGET["address"]`) · 검수 규칙(`check_rule`) · 상태 규칙(`state_rule`)
- `block(budget=, trace=)`: 쓰기 가족만 작품 예산(`context.budget`)을 넘기고, trace 에 예산으로 뺀 줄을 적는다
- 자주 쓰는 말씨 `SPEECH_LEVELS`
- LLM 호출 없음
- 화면은 `static/address.js` (두 사람 상세 `addressCard` · 인물 카드 `addressHeldCard` · 상태 승인 '직접 정할 것' 줄 `addressDeltaRows`, 말씨 목록 `ADDRESS_LEVELS` 는 `SPEECH_LEVELS` 와 같음 `tests/test_address.py`)

### `canon/agent.py`

- 대화 에이전트. 작품 안 모든 화면의 대화 패널 하나가 쓴다
- 세션 목록은 작품 하나에 하나다(`sessions`, `TOPICS`). 새 세션 topic 은 `agent` 이고, 옛 `plot` 세션도 같은 목록에 보인다
- 세션(`AgentSession`, 다듬을 곳 · 권한 모드 `ask|draft|all`). 다듬을 곳은 `arc:N` · `next` · 부 `part:N` · 한 화 `ep:N`(`pipeline.chat_focus`, 그 곳이 든 아크는 `chat_target`), 밖을 고치면 종류 `outside` 로 늘 묻는다(`outside`, `permit`)
- 화면이 주는 대상 `text:N`(집필 · 검수 · 상태 승인) · `setup`(설정 도우미) · `style`(문체)도 `chat_focus` 가 읽는다. `chat_target` 은 `text:N` 을 `ep:N` 처럼, `setup` · `style` 을 '' 처럼 읽는다
- 이 세 대상에서 플롯 쓰기는 모두 `outside` 로 묻는다(`OTHER_FOCUS`)
- 본문 대상 `text:N` 의 쓰기 도구는 본문 고치기 `revise_text`(`agent_text.py`)다
- 설정 쓰기 도구는 `edit_setup`(`agent_setup.py`)이다. 대상과 상관없이 쓸 수 있다
- 문체 쓰기 도구는 `edit_style`(`agent_style.py`)이다. 대상과 상관없이 쓸 수 있다
- 규칙 제안 도구는 `propose_regex`(`agent_regex.py`)다. 대상과 상관없이 쓸 수 있다
- 플롯 화면 밖에서 작품 전체('')를 대상으로 보낸 턴도 플롯 쓰기를 모두 `outside` 로 묻는다(`off_plot`, 2026-11-09 사용자 결정). 플롯 화면(`PLOT_SCREENS`)은 지금 규칙 그대로다
- 턴은 작가가 보던 화면을 `AgentTurn.screen` 에 남긴다. `SCREENS`(웹 drawApp 의 views 표와 'home')에 없거나 비면 '' 이고 플롯 화면과 같게 다룬다
- 턴을 열 때 화면 대상이 오면(`add_turn` 의 `target`) 고정하지 않은 세션의 대상을 그 값으로 바꾼다. 고정은 `AgentSession.pinned`(옛 세션은 False)
- 턴에 재료(`add_turn` 의 `selection`, `schema.TextMaterial`: 고른 본문과 그 화)와 빠른 요청(`preset`, `prompts.PASSAGE_PRESETS`)을 붙일 수 있다. 빠른 요청만 있고 재료가 없거나 모르는 빠른 요청이면 막는다
- 재료와 빠른 요청으로 연 새 세션의 이름은 'N화 본문 · 빠른 요청 이름'이다
- 설정 · 문체 · 본문 고치기의 옛 대화는 `legacy_chats` 가 (주제, 메시지 수)로 준다. 웹 세션 목록의 `older` 이고 화면은 읽기만 한다
- 그 옛 대화 셋의 보내기(`web.py` `chat_send` 의 `setup` · `style` · `text:N`)는 04e 에서 지웠다. 새 말은 이 에이전트의 도구가 받는다
- 옛 기록의 적용 취소(`chat/setup/{i}/undo` · `chat/style/{i}/undo`)와 본문 되돌리기(수정 기록)는 그대로 쓴다
- 턴(`AgentTurn`)을 백그라운드 작업 `agent` 로 돌린다(`run_turn`, 단계마다 `llm.json(PlotAgentStep)`, 최대 `MAX_STEPS`=8, 단계마다 저장)
- `first_step_prompt` 는 새 세션 첫 턴에서 `run_turn` 이 처음 보내는 요청이다. 세션(id `LAB_SID`)을 작품에 붙이지 않는다. 프롬프트 놀이터 불러오기가 쓴다
- 단계 호출은 `step_wait` 초까지 기다린다: Claude Code(구독)는 `STEP_WAIT_CLAUDE`(480), 나머지는 `STEP_WAIT`(300)
- 단계를 시작할 때 그 한도를 `Job.step_wait` 에 적는다. 화면의 늦음 안내가 이 값을 보인다(`agentStepLimit`)
- 턴이 끝나면 끝난 시각 `AgentTurn.ended` 를 남긴다(`_step` · 단계 상한 · 작업 상태 맞추기). 옛 턴은 빈 값이다
- `PlotAgentStep.tool` 은 빈 글과 도구 이름만 받는 Literal 이다. 빈 글이면 reply 로 턴을 끝낸다
- 도구 이름 목록은 `schema.AGENT_TOOL_NAMES` 이고 한 줄에 하나다. 새 도구는 줄을 더한다
- 도구 이름만 오고 칸이 빈 단계는 같은 단계에서 그 칸만 담은 형식으로 한 번 더 부른다(`fill`: ask 는 `AgentAsk`, edit_plot 은 `PlotRevision`, 방향 안만 오면 되묻기로). 그래도 비면 되돌림 단계(`ask_empty` · `edit_empty`)
- `fill` 이 다시 부르는 동안 작업 진행 줄(`cancel.say` → `Job.retry`)에 까닭을 띄우고 끝나면 지운다
- 모델이 'reply' · 'done' 같은 끝 이름(`schema.AGENT_END_TOOLS`)을 tool 에 적으면 빈 글로 받는다
- 도구는 읽기(`read_plots` · `read_summaries` · `find_text`(`context.recall`) · `read_cast` · `read_rules`, 결과 `RESULT_LIMIT` 자)와 쓰기 `edit_plot`
- 읽기 도구 `read_rules`(함수 `read_rules`)는 이 작품이 켠 정규식 규칙 묶음마다 id · 이름 · 켠 작품 수와 규칙 칸을 돌려준다. 켜지 않은 묶음은 보이지 않는다
- 되묻기 `ask`
- 화 넣기 · 빼기 `insert_episodes` · `remove_episode`(`RENUMBER_TOOLS`, `RenumberOp`): 복사본에 해 보고(`preview`) 늘 승인 카드로 묻는다(`permit` 의 `renumber`). 쓰기 `apply_op`, 되돌리기 반대 동작 `inverse`, 자동 집필 번호 `shift`. 번호를 옮긴 뒤에는 턴을 다시 찾는다(작품 칸이 통째로 바뀜)
- 화 넣기 · 빼기가 빼는 옛 화 번호 `dropped`(되돌리기면 넣었던 화들): 웹이 `store.renumber_side_files` 의 `gone` 으로 넘긴다
- 늘 카드로 묻는 도구는 `CARD_TOOLS`(도구 이름 → 모듈)에 한 줄씩 등록한다. 몸통은 제 파일에 두고 모듈은 `agent_text.py` 머리에 적은 이름들을 둔다. 04c · 04d · 06b(`agent_regex`)도 같은 방식으로 더한다
- 권한 모드('모두 자동' 포함)와 '이 세션에서 묻지 않기'를 따르지 않고 늘 묻는 종류는 `ALWAYS_ASK`(`renumber` 와 `CARD_TOOLS` 의 종류, 규칙 제안의 `rule` 포함)다
- `permit` 은 `ALWAYS_ASK` 종류에 늘 'ask' 를 낸다. `decide` 의 `remember` 는 이 종류를 `auto_kinds` 에 넣지 않는다
- `run_turn` 은 카드 도구의 AI 호출(`prepare`)을 잠금 밖에서 부르고, 그 결과를 `_step` 에 넘겨 잠금 안에서 기록한다(`record`)
- 지름길: 턴의 첫 단계에서 `card_shortcut` 이 단계를 정하면 에이전트 단계(`PlotAgentStep`)를 부르지 않는다. 재료나 빠른 요청이 붙은 턴이다(`agent_text.shortcut`)
- 카드 도구의 카드에 답하면 `decide` 가 그 모듈의 `decide` 를 부르고 턴을 끝낸다(`resume` 하지 않는다)
- `undo` 는 카드 도구가 쓴 기록(`WriteRecord.tool`)이면 그 모듈의 `undo` 를 부른다. `_compact` 는 그 모듈에 `compact` 훅이 있을 때만 부른다(설정 도구)
- `RenumberOp.aside`: 화 빼기 승인 때 웹이 removed/ 에 남긴 큐 시트 실험 · 비교본 경로를 적는다. 빼기를 되돌리면 웹이 그 파일을 되돌린다
- 쓰기는 `clean_revision` 으로 거른다(본문이 있는 화는 막힘)
- 쓰기 부분마다 종류(`KIND_LABELS`)를 매긴다
- 권한(`permit`) 안이면 `pipeline.plot_apply` 로 바로 쓴다(`WriteRecord`)
- 권한 밖이면 승인 카드(`Approval`, `decide`)로 남기고 턴을 끝낸다
- 다음 아크 칸 · 구조는 화면 초안('draft')으로만 간다
- 되돌리기(`undo`)는 `pipeline.plot_undo`
- 화 빼기는 뺀 화 전체를 `RenumberOp.removed_ep` 에 남겨, 되돌리면 스토리보드 · 큐 시트 · 장면 연출 · 고칠 곳까지 살린다(`inverse`)
- 화 넣기를 되돌릴 때 넣은 화가 넣은 직후(`RenumberOp.inserted`)와 다르면 고친 것으로 보고 되돌리지 않는다
- 새 턴을 열 때 최근 `UNDO_TURNS`(20) 턴보다 오래된 턴의 쓰기 전 · 뒤 값과 초안을 지운다(`_compact`). 그 턴의 쓰기는 kept(`OLD_UNDO`)로 남는다
- 멈추거나 실패한 턴은 `reconcile`
- 프롬프트 `prompts.agent_plot_prompt`
- 대상 블록 `prompts.agent_focus_block` 은 문체 대상에 '문체를 바꾸자는 말이면 edit_style 을 부른다(늘 칸마다 물어진다)'를 알린다
- 본문 대상에는 '본문을 고쳐 달라고 하면 revise_text 를 그 화로 부른다'를 알린다
- 설정 대상에는 같은 블록이 '설정을 바꾸라는 말이면 edit_setup 을 부른다(늘 칸마다 물어진다)'를 알린다
- 플롯 화면 밖의 작품 전체 턴이면 같은 블록이 '플롯 쓰기는 모두 물어진다' 한 줄을 넣는다
- mock 단계(`mock._agent_step`)는 힌트 `aim` 이 본문 · 설정이면 '플롯'이 든 말만 고치고 나머지는 읽은 뒤 답만 한다
- mock 단계는 본문 대상에서 «원문» 이 든 말이면 `revise_text` 를 그 원문으로 부르고, 막혔으면 답만 한다
- mock 단계는 대상이 설정이거나 '설정을' 이 든 말이 `mock.MOCK_SETUP_WORDS`('날카롭', '다듬' 등)를 담으면 `edit_setup` 을 부른다
- mock 단계는 `aim` 이 문체이거나 말에 '문체'가 들면 `edit_style` 을 부른다. 'N화 참고' 는 episode 인자, 문체 대상의 '?' 물음은 답만 한다
- 단계 프롬프트는 바뀌지 않는 블록(도구 · 규칙 · 요구사항)이 앞, 턴 블록과 이번 턴 단계가 뒤, 남은 단계 수가 맨 끝 한 줄이다(단계 k+1 요청이 단계 k 요청을 품음)
- 이름 후보는 `random.Random(session.id)` 로 뽑아 단계마다 같다(`plot_chat_parts` 의 rng)

### `canon/agent_regex.py`

- 대화 에이전트의 정규식 규칙 제안 도구 `propose_regex`(종류 `rule`, 이름표 '규칙'). `agent.CARD_TOOLS` 가 등록한다
- 명세서는 [docs/context/specs/06b-rule-propose.md](../context/specs/06b-rule-propose.md)
- 에이전트 단계(`PlotAgentStep.args`)가 규칙 칸을 채운다. `prepare` 는 AI 를 부르지 않는다(LLM 호출은 에이전트의 `chat` 단계 하나)
- 인자: `bundle` · `rule`(고칠 규칙 id, 비우면 새 규칙) · `comment` · `in` · `out` · `action` · `type` · `flag` · `enabled`
- 고치기에서 비운 인자는 지금 값을 두고, 새 규칙에서 비운 인자는 `RegexRule` 기본값(warn · output · g)을 쓴다
- 도구 한 번에 규칙 하나를 더하거나 고친다. 지우기는 하지 않는다. 끄기는 `enabled=false` 고치기다
- 넣을 묶음은 이 작품이 켠 묶음(`regexrules.bundles_of`)에서만 고른다. `bundle` 이 비고 켠 묶음이 둘 이상이면 묶음 이름을 돌려주며 막는다
- 켠 묶음이 없으면 새 묶음('<작품 제목> 규칙') 카드다. 적용할 때 묶음을 만들고 `Settings.rule_bundles` 끝에 켠다. 이미 있는 묶음은 켜거나 끄지 않는다
- 고치기는 그 규칙이 든 켠 묶음이다. 켜지 않은 묶음 id 나 없는 규칙 id 는 막는다
- `prepare` 는 규칙 하나를 `regexrules.validate` 로, 넣은 뒤 묶음 전체를 `check` 로 검사한다. 빈 `in`, 같은 규칙(같은 in · out · action · type · flag)도 막는다
- 끄기만 하는 카드(`regexrules.switched_off`)는 그 규칙을 검사하지 않는다. 지금 검사에 걸리는 옛 규칙도 끌 수 있다
- 막히면 `record` 가 카드 없이 `block` 단계를 남기고 까닭을 `why` 와 결과로 AI 에게 돌려준다. AI 는 같은 턴에서 고쳐 다시 부를 수 있다
- 시험: 규칙 하나만 `regexrules.trial(strict=True)` 로 건다. 화는 본문 대상(`text:N`) · 턴의 화 · 본문이 있는 가장 뒤 화 차례다
- 시험이 시간 한도를 넘으면 막는다. 본문이 있는 화가 없으면 시험 없이 카드를 띄운다
- 끄기 카드(`turned_off`)는 적용 전 규칙을 걸어 '더 걸리지 않을 곳'을 보인다
- 끄기 카드는 그 시험이 시간 한도를 넘어도 막지 않고 카드에 `timed_out` 을 남긴다
- 카드(`Approval.regex`, `schema.RegexCard`)는 바뀐 곳 · 걸린 곳을 각 `CARD_LIMIT`(10)개와 전체 수로 남긴다. 내보내기 규칙은 `export_changed`
- 카드의 `used_by` 는 그 묶음을 켠 다른 작품이다(`regexrules.used_by` 에서 이 작품 `project` 를 뺀다)
- `decide` 는 묶음을 다시 읽어 규칙 하나만 넣는다(`regexrules.set_rule`, 버전 메모 '대화 에이전트 제안: <규칙 이름>'). 답하면 턴을 끝낸다
- `decide` 는 묶음을 지웠거나, 이 작품에서 껐거나, 고칠 규칙이 카드를 만든 뒤 바뀌었으면 ValueError 로 막고 카드를 둔다(웹 400)
- 적용해도 이미 쓴 화의 본문에는 다시 걸지 않는다. 경고 규칙은 다음 검수부터 걸린다(`effect`)
- `undo` 는 지금 규칙이 적용 뒤 값과 같을 때만 그 규칙 하나를 돌린다. 새 규칙은 빼고 고치기는 적용 전 규칙으로 바꾼다(메모 '대화 에이전트 제안 되돌림')
- 그 뒤 규칙을 고쳤으면 `KEPT`, 묶음이나 규칙이 없으면 `GONE` 으로 남긴다
- 새 묶음 되돌리기는 이 작품에서 끈다. 묶음에 그 규칙만 남았고 다른 작품이 켜지 않았으면 묶음 파일도 지운다
- 다른 작품 수는 `used_by` 의 수에서 지금 작품이 켰으면 1을 뺀다. 복제 · 이름 바꾸기로 폴더 이름이 카드의 `project` 와 달라도 맞다
- `compact`: 오래된 턴의 `WriteRecord.regex` 를 지운다
- 규칙 묶음 파일은 작품 잠금 밖이다. 규칙 화면과 함께 고치면 나중 저장이 이긴다
- 화면 카드는 `static/agent.js` 의 `agentRegexApproval`
- 시험 `tests/test_agent_regex.py`

### `canon/agent_setup.py`

- 대화 에이전트의 설정 도구 `edit_setup`(종류 `setup`, 04c). `agent.CARD_TOOLS` 가 등록한다
- `prepare`: 잠금 밖에서 `pipeline.revise_setup`(LLM 단계 `plan`)을 부른다. 옛 설정 대화와 같은 프롬프트 · 정리다
- `prepare` 의 요청은 `request` 인자이고, 비면 작가의 이번 말이다(`request`). 편집자는 세션 대화를 보지 않는다
- 방향 여러 안은 에이전트의 `ask` 가 묻는다. 그래서 `revise_setup` 의 mode 는 늘 비운다
- 지름길(`shortcut`)은 없다. 늘 에이전트 단계가 고른다
- `record`: 잠근 작품에서 `setupchat.clean` 으로 다시 거르고 승인 카드(`Approval.setup` · `keys` · `kinds` ['setup'] · `defaults`)를 남긴 뒤 턴을 끝낸다
- 바뀌는 칸이 없거나 요청이 비면 카드 없이 단계 줄(note · block)만 남기고 같은 턴을 잇는다
- 권한 모드와 상관없이 늘 묻는다. '이 세션에서 묻지 않기'(`auto_kinds`)도 받지 않는다(`agent.ALWAYS_ASK`, 2026-11-09 사용자 결정)
- 처음 체크(`defaults`): 빈 칸 · 새 인물 · 새 관계만 켠다. 이미 채운 칸과 인물 칸(인물 설정 바꾸기)은 꺼 둔다
- 새 관계의 호감 · 긴장 수치는 0 으로 둔다(`_no_numbers`). 관계 수치는 AI 가 적지 않는다
- `decide`: 작가가 고른 부분만 `setupchat.apply_revision` 으로 넣고 쓰기 전 설정을 `WriteRecord.setup_before` 에 남긴다. 고른 것이 없으면 카드를 그대로 둔다
- `decide` 는 승인이든 거절이든 턴을 끝낸다. 에이전트를 다시 부르지 않는다
- `undo`: `setupchat.undo_revision` 으로 그 뒤에 다시 고치지 않은 부분만 돌린다. 남긴 부분은 까닭 `KEPT`
- `compact`: 오래된 턴의 `WriteRecord.setup` · `setup_before` 를 지운다(`agent._compact` 가 이 훅이 있는 도구에만 부른다)
- 화면 카드는 `static/agentsetup.js`
- 웹 승인(`web.agent_approval`)은 관계를 고르면 자동 집필이 도는지 본다(`chat_apply` 와 같다)

### `canon/agent_style.py`

- 대화 에이전트의 문체 도구 `edit_style`(종류 `style`, 04d). `agent.CARD_TOOLS` 가 등록한다
- 화면 칸 이름표 `STYLE_LABELS`: `prompts.STYLE_KEY_LABELS` 에서 화면 이름만 바꾼 표(`markers` 는 '문체 버릇'). 카드 · 명령줄 · `stylechat.js` `STYLE_KEYS` 가 같은 이름을 쓴다(`tests/test_labels_js.py`)
- `prepare`: 잠금 밖에서 `pipeline.revise_style`(LLM 단계 `plan`)을 부른다. 옛 문체 대화와 같은 프롬프트 · 정리다
- 인자는 `request`(비우면 작가의 이번 말)와 `episode`(참고할 화)다
- 참고할 화 `ref_episode`: 인자가 먼저이고, 비었으면 문체 대상 턴의 `AgentTurn.episode`(화면의 '참고할 화' 칩)를 쓴다
- 본문이 없는 화를 참고로 고르면 막힘 단계로 AI 에게 돌려준다
- 지름길(`shortcut`)은 없다. 참고할 화 칩은 지울 때까지 남아 말 하나의 뜻을 정하지 않는다
- `record`: 잠근 작품에서 `clean_style_revision` 으로 다시 거르고 문체 변경안 카드(`Approval.style`, `schema.StyleCard`)를 남긴 뒤 턴을 끝낸다
- 바꿀 칸이 없으면 편집자 답으로 턴을 끝낸다
- 권한 모드와 상관없이 늘 묻는다. '이 세션에서 묻지 않기'(`auto_kinds`)도 받지 않는다(`agent.ALWAYS_ASK`, 2026-11-09 사용자 결정)
- `decide`: 작가가 고른 칸만 `pipeline.apply_style_edits` 로 넣고, 넣기 전 문체를 `WriteRecord.style.before` 에 남긴다
- `decide` 는 승인이든 거절이든 턴을 끝낸다. 에이전트를 다시 부르지 않는다
- `undo`: `pipeline.undo_style_edits` 로 그 뒤에 다시 고치지 않은 칸만 돌린다. 남긴 칸은 까닭 `KEPT`
- `compact`: 오래된 턴의 `WriteRecord.style` 을 지운다
- 옛 문체 대화(`Project.chats` 의 `style`)에는 남기지 않는다. 옛 기록은 '이전 대화'에서 읽기만 한다
- 화면 카드는 `static/agent.js` 의 `agentStyleApproval`
- 시험 `tests/test_agent_style.py`

### `canon/agent_text.py`

- 대화 에이전트의 본문 고치기 도구 `revise_text`(종류 `text`, 04b). `agent.CARD_TOOLS` 가 등록한다
- 후보는 `pipeline.revise_passage`(LLM 단계 `revise`), 기록은 `record_passage`, 넣기는 `apply_passage` 를 그대로 쓴다. 지금 'AI에게 고치기'와 같은 부분 수정 대화(`text:N`)와 수정 기록에 남는다
- 후보에는 'AI에게 고치기'처럼 작품이 켠 고침 규칙을 건다(`revise_passage(rules=True)`). 넣은 후보에 남은 규칙 고침은 대화가 잘려 `edit_text` 로 넣어도 규칙 기록(kind passage)에 남는다
- 결과는 후보 2~3개가 든 승인 카드(`Approval.passage` · `selection` · `episode` · `preset` · `at`)다. 권한 모드와 상관없이 늘 묻는다(`agent.ALWAYS_ASK`)
- 카드에 답하면(`decide`) 고른 후보 하나만 넣는다. 작가가 손본 글(`text`)도 받는다. 거절하면 대화의 그 답을 버린 것(`dismissed`)으로 둔다. 어느 쪽이든 턴을 끝낸다
- 넣기는 카드가 남긴 대화 답을 시각 · 고른 부분으로 찾는다(`_chat_index`). 대화가 잘려 없으면 `pipeline.edit_text` 로 같은 기록을 남긴다
- 넣은 것은 `WriteRecord`(`tool` · `episode` · `edit`)로 남는다. 되돌리기(`undo`)는 `pipeline.undo_edit` 이라 수정 기록의 되돌리기와 같다
- 지름길(`shortcut`): 턴에 재료(`AgentTurn.selection`)나 빠른 요청(`AgentTurn.preset`)이 붙으면 에이전트 단계 없이 이 도구를 부른다. AI 호출은 한 번이다
- 에이전트가 부를 때는 인자 `quote`(본문 원문) · `request` · `n`(비우면 다듬을 곳의 화) · `preset` 을 받는다. 원문을 본문에서 못 찾으면 막힘 단계로 돌려준다
- 빠른 요청 이름만 보낸 말은 작가의 말로 넘기지 않는다(`_message`, 빠른 요청 지시가 이미 들어간다)
- 자동 집필이 돌거나 그 화를 쓰는 작업이 돌면 AI를 부르지 않고 막는다(`_guard`, `web._text_guard` 와 같은 검사)
- 지름길 턴이 막히면 까닭을 답으로 남기고 턴을 끝낸다. 에이전트가 부른 턴이면 막힘 결과를 받고 이어 간다
- 모듈 머리 글에 늘 카드로 묻는 도구 모듈이 둘 이름(`TOOL` · `KIND` · `LABEL` · `shortcut` · `prepare` · `record` · `decide` · `undo`)을 적는다

### `canon/aliases.py`

- 다른 이름 채우기(`docs/context/specs/04-key-suggest.md`): 인물 · 이야기 요소의 다른 이름을 AI 가 제안하고 작가가 고른다
- 항목 열쇠는 `c:<인물 id>` · `e:<요소 id>` 다(`Item`, `item`, `find`)
- `targets` 는 열쇠 하나면 그 항목, `c:` · `e:` · 빈 글이면 다른 이름이 빈 항목을 `ALIAS_BATCH`(10)개까지 고른다. 이름이 빈 항목은 받지 않는다
- `material` 은 쓴 화(`written` · `finalized`) 본문에서 이름 · 다른 이름이 맞은 단락과 그 앞뒤를 최근 화부터 `ALIAS_SAMPLE`(3,000)자까지 고른다
- 예산을 넘어 뺀 맞은 단락 수(`Item.cut`)는 프롬프트에 적는다
- 이름이 본문에 없는 요소는 `context.recall` 로 이름 · 설명과 겹치는 단락을 찾는다(임베딩 없음)
- 인물 항목은 `Project.address_forms` 에서 그 인물을 부르는 호칭을 씨앗으로 넣는다(`_calls`)
- `clean` 은 앞뒤 빈칸 · 따옴표만 지우고 조사는 떼지 않는다
- `clean` 이 빼는 말: 두 글자 미만, `ALIAS_MAX_LEN`(12)자 초과, 이름(인물은 `metrics.name_forms`) · 있는 다른 이름과 같은 말, 항목 안 겹침, 재료 단락에 글자로 없는 말
- `clean` 은 요청하지 않았거나 없는 항목을 가리키는 제안을 빼고, 뺀 수를 `AliasSuggestion.notices` 에 적는다
- `hits` 는 최근 `ALIAS_HIT_EPS`(30)개 쓴 화에서 다른 이름마다 찾히는 화(`AliasHit.episodes`)와 이름 · 지금 다른 이름으로는 안 찾히는 화(`only`)를 센다
- 인물 다른 이름은 그 말만 넣은 인물 사본의 `context.name_pattern` 으로, 요소는 `elements.terms` 의 부분 문자열로 찾는다. 판정을 따로 만들지 않는다
- `clash` 는 다른 항목의 이름 · 다른 이름과 같거나 서로 품는 말이면 그 항목 이름이다. 빼지 않고 작가가 판단한다
- LLM 을 부르지 않는다(호출은 `pipeline.suggest_aliases`). 저장하지 않는다

### `canon/anchor.py`

- 이 작품의 문체: 작가가 고른 반영한 화를 이 작품의 문체 기준으로 고정한다(`Project.anchor`, `StyleAnchor`)
- 고를 수 있는 화 `usable`(반영 끝, 본문 있음, 서술 말투 화 아님) · 처음 추천 `suggest`(앞 5화, 저장하지 않음)
- 재기 `measure` · `set_anchor`(합쳐 6,000자 이상, 대표 문단은 고른 화 본문에 글자 그대로 있어야 함, 표지 빈도는 고른 화에서 다시 셈)
- 잴 때 고른 화 뒤 10화가 떨어진 평균 거리 `later`(크면 고른 화가 작품을 대표하지 못함)
- 대표 문단 후보 `candidates`(문단 묶음 중 문장 길이 · 대사 비율이 기준에 가까운 것, 대사 위주 · 서술 위주 하나씩 먼저)
- 본문 지문 `basis` · 낡음 `stale`(고른 화 본문을 고치거나 지우면 다시 재라고 알림, 번호만 옮기면 그대로)
- 기준이 있으면 `pipeline.style_baseline` 이 이것을 쓰고 표지 빈도는 `markers`, 쓰기 예시는 `prompts.style_passages`
- 흐름 `distance` · `rolling`(최근 5화, 서술 말투 화 · 고른 화 빼고) · 경고 `warning`(`DRIFT_WARN` 1.15, `pipeline.style_drift` 가 붙임)
- 문턱은 사람 웹소설 4편 실측: 같은 작품은 80화 뒤 0.85~1.05(`HUMAN_BAND`), 다른 작품끼리 평균 1.33(`OTHER_AUTHOR`)
- AI 가 쓴 본문의 문체 지문 `stamp` · `style_basis`(`Episode.style_basis`, `pipeline.replace_text` 가 비움)
- 화면 값 `view` · 추이 `trend`(문체를 바꾼 화 `changed`)
- 화 번호 옮기기 `move`(`renumber.move_points` 가 부름)
- 라이브러리에는 올리지 않는다(`library.push_project` 는 `p.style` 만)
- LLM 호출 없음
- 화면은 `static/anchor.js`

### `canon/archetypes.py`

- 원형 도감
- 인물 유형 카드(`CATALOG`, `Archetype`)
- 상처(`WOUNDS`)
- 말투 틀(`SPEECH`)
- 장르로 거르기(`match`)
- 빈 칸만 채우기(`fill`, 비틀기는 아크 끝 한 줄)
- 고른 원형 기록(`Project.cast_archetypes`, `remember` · `prune`, 프롬프트에 넣지 않음)
- 주사위(`roll`, 이름은 `naming`)
- 명령줄 `dex`
- LLM 호출 없음
- 화면은 `static/archetypes.js` (설정 도우미의 도감 주사위만, `dexRemember` 는 `remember` 와 같은 규칙, `tests/test_archetypes_js.py`)
- 글은 새로 쓴다(TV Tropes · 나무위키 옮기지 않음)

### `canon/attire.py`

- 지금 차림(`CharacterState.attire`) 점검. 규칙 글은 `prompts.ATTIRE_STATE_RULE` · `attire_write_rule` · `attire_check_rule`
- 끝 낱말이 '가방' · '옷' · '겉옷' · '신발'인 조각 찾기(`vague`, 이름 `VAGUE`). 앞 낱말이 쓰임(`KIND_WORDS`)이거나 가방의 메는 자리(`CARRY`, 괄호 안 포함)를 말하면 넘어간다. 색 · 재질은 종류로 보지 않는다
- 상태 변경안 정리 훅(`clean_delta`, `features.CLEAN`): 인물 이름으로 시작하는 경고
- 그 경고는 (글, 인물 id) 로 돌려줘 상태 승인 화면이 그 인물 줄에 붙인다(`StateDelta.warn_to`)
- LLM 호출 없음

### `canon/birth.py`

- 무작위 출생과 새 세계
- 코드가 시드로 굴린 출생
  - `roll`
  - `Birth`: 원형 · 상처 · 말투 · 비틀기는 `archetypes.match` · `roll`
  - 이름은 `naming.character_candidates`(세계 인물 · 인물 후보와 겹치지 않게)
  - 태어난 곳은 `birth_places`(`atlas.places` 에서 반영한 마지막 화 `last_finalized` 까지 생기고 드러난 곳)
  - 나이는 장르 범위 `AGE_RANGES`
  - 성인 작품은 19세부터
  - 갈래마다 시드에서 난수원을 따로 둔다
- AI 배경 채우기(`sketch`, `BirthSketch`, `prompts.birth_prompt`: 세계 · 장소 · 세력 · 인물 한 줄이 앞, 굴린 값이 뒤)
- 플레이어 인물 만들기(`to_character`: id `player_id`, 빈 칸은 `archetypes.fill`, 세계 작품은 바꾸지 않음)
- 장르 · 한 줄로 새 세계 작품(`new_world`: 웹 새 작품 만들기와 `pipeline.suggest_setup` · `apply_setup`, 장소가 없으면 `naming.location_candidates` 로 채움, AI 제안 뒤에만 저장)
- LLM 호출은 `sketch` · `new_world` 뿐

### `canon/blueprint.py`

- 설계도: 작가가 먼저 정하는 계획 층(`Project.blueprint`, `Blueprint`). 설계 문서는 `docs/blueprint/`
- 관계 이정표(`Milestone`)는 방향마다 [화 범위, 관계 단계(dynamics 말, 비워도 됨), 라벨, 계기]
- 접촉 사다리(`ContactLadder`)는 쌍마다 하나, 칸(`ContactRung`)의 차례가 단계의 차례
- 사다리 칸의 부위 · 동작은 `stage.PARTS` · `stage.ACTS` id, 장소는 인과율 '장소' 요소 id, 겹(`layer`)은 옷 위 · 옷 안 · 맨살
- 화 번호는 범위(`from_ep` ~ `to_ep`, 둘 다 0 이면 정하지 않음)
- 빈 id 채우기 `fill_ids`(`ms-<k>` · `cr-<k>`, 있는 id 는 그대로)
- 저장 검사 `check(p, before)`: 모르는 값을 지우지 않고 `ValueError` 로 거절. 작품 저장(`web._put_locked`)이 부른다
- `check` 는 디스크 작품에서 이미 끊겨 있던 인물 · 장소 참조는 막지 않는다(`validate_characters` 와 같은 방식)
- 범위를 적은 사다리 칸끼리는 칸 차례대로 처음 닿는 화가 줄지 않아야 한다
- 계획 칸 `planned_rung(ladder, n)`: 처음 닿는 화가 n 화 이하인 칸 가운데 차례가 가장 뒤. 쌍 찾기 `ladder`
- 화 끼워 넣기 · 빼기 `move`(`renumber.move_points` 가 부름): 범위 안에 넣으면 범위가 늘고, 끝 화를 빼면 범위가 준다
- 재구성 `remap`(`reshape` 가 부름): 옮기지 못한 범위는 비우고 알림에 적는다
- 이정표 경고 `warnings`(막지 않음): 이웃한 두 이정표 사이 칸 모자람, 범위가 겹치는데 단계가 다름, 지금 단계에서 다음 이정표까지 칸 모자람
- 플롯이 이정표를 앞지르는 경고는 `pace.milestone_warnings`
- 계획값이라 관계 수치(`Tie`) · 플롯을 바꾸지 않는다
- 경고에 방향을 붙인 `warning_rows`(보는 인물, 보이는 인물, 글). `warnings` 는 그 글만
- 웹은 `GET` · `PUT /api/projects/{name}/blueprint`(보기 `BlueprintView`: 설계도 · 방향 붙은 경고 · 부위 · 동작 이름 · 마지막 반영 화, 저장은 설계도 통째와 `check`)
- 화면은 `static/blueprint.js`
- 기획 프롬프트 줄 `plan_lines(p, ids, start, end)`: 화 범위를 적은 줄만, 범위에 걸린 이정표 · 사다리 칸과 그 뒤 첫 것. 두 인물이 모두 ids 에 들 때만
- 사다리 칸 한 줄 `rung_text`: '차례. 이름 (겹 · 부위 · 동작 · 장소 · 주도 · 메모)', 부위 · 동작은 장면 연출의 이름
- 스토리보드 · 쓰기 · 검수 요청의 설계도 줄은 `prompts.blueprint_board_rule` · `blueprint_write_line` · `blueprint_check_rule`(그 화 플롯 인물끼리만)
- 거꾸로 뽑기 범위 `extract_range`: 장편은 아크 하나, 단편은 플롯이 있는 첫 화부터 마지막 화까지
- AI 로 짜기 범위 `draft_range`: 장편은 부 하나(0 이면 작품 전체), 단편은 1화부터 작품 화수까지
- AI 제안 정리 `clean_proposal`(`BlueprintProposal`): 두 인물 사이 줄만, 화 범위를 자르고 모르는 id · 쌍 밖 주도 인물 · 범위 밖 근거를 뺀다
- 고른 제안 줄 더하기 `apply_picks`: 이정표는 뒤에, 사다리 칸은 처음 닿는 화 차례로 끼운다. 사본에서 `check` 한 뒤에만 바꾼다
- 본문에서 닿은 칸은 기록 `Project.contact_log`(`ContactReach`)에서 계산한다: `reached`(칸 id → 처음 닿은 화) · `actual_rung`. 지워진 칸의 기록은 뺀다
- 상태 변경안 요청 줄 `state_rule`: 그 화 플롯 인물끼리 아직 닿지 않은 칸(`open_rungs`) 목록. 칸이 없으면 빈 글
- 상태 변경안 훅: 정리 `clean_delta`(목록 안 · 아직 닿지 않은 칸만), 반영 `apply_delta`, 남겨 두기 `hold`(`contact_held`), 반영 취소 `revert`(그 화 뒤 기록 · 남김 지움)
- 남겨 둔 제안 기록하기 · 버리기 `take_held` · `drop_held`
- LLM 호출 없음

### `canon/branches.py`

- 갈래
- 같은 작품을 복사해 n화부터 다른 전개를 쓰는 사본
- 갈래 하나는 작품 폴더 하나
- 갈래 정보(`BranchInfo`)는 `project.json` 밖의 `branch.json`(`store.load_branch` · `save_branch` · `drop_branch`, 화면 저장이 덮지 않게)
- 만들기(`make` → `fork`: 복사본을 `pipeline.revert(n-1)`, 뒤 아크 · 부 요약 비움, `clear` 는 n화부터 본문을 이전 판으로)
- `clear` 갈래는 비운 화의 고칠 곳 · 다 쓴 사건 체크 · 복선 문장(작가 것도)을 함께 뺀다
- `clear` 갈래는 이전 판으로 남기는 본문의 `meta_cut` · `rule_runs` 도 그 판(`TextVersion`)으로 옮기고 화에서 비운다
- 함께 쓰는 앞 화 고침(`shared_edited`, `base` 해시)
- 집안 계산(`family`, `order`, `diverge`, `promote` · `promote_saved`, `remove`, `{폴더: BranchInfo}` 만 받는 순수 함수)
- 비교(`compare` · `compare_saved`)
- 합치기는 없다
- 원본 `project.json` 은 바꾸지 않는다
- 작품 복제는 `branch.json` 을 옮기지 않는다
- 갈래 · 복제 · 플레이 사본은 자동 집필 기록과 실행 주인 파일(`autorun.json` · `.autorun.lock` · `autorun.want`)을 옮기지 않는다(`COPY_SKIP`)
- 보낸 프롬프트 기록 `sent/` 는 `COPY_SKIP` 에 넣지 않아 함께 옮긴다. 함께 쓰는 앞 화 본문이 받은 요청이다(`canon/sent.py`)
- 명령줄 `branch` · `branches` · `branch-compare` · `promote`
- LLM 호출 없음

### `canon/cast.py`

- 인물 화면 계산
- 화별 관계 프레임(스냅샷, 지워진 화는 사건 로그로 다시 계산)
- 지워진 화의 상태 재계산 `_apply_gap` 은 `pipeline.apply_delta` 처럼 `cleared` 칸을 비운다
- 인물별 등장 화
- 화별 타임라인
- 명령줄 `cast` 출력
- 반영 때 본문에 이름이 나오고 상태 변경안이 다룬 인물을 그 화 등장 인물에 붙이기(`cast_to_add`, features 훅 `clean_delta` · `apply_delta` · `revert`, 기록 `StateDelta.cast_added`, 상태 승인 화면은 `review.js` `castAdd`)
- LLM 호출 없음

### `canon/charlog.py`

- 인물 설정 변경
- 상태 변경안의 설정 바꾸기 제안(`StateDelta.setting_changes`, 외모 · 성격 · 말투 등 뒤 화까지 이어지는 변화) 정리(`clean_delta`)와 반영(`apply`, 작가가 고른 것만)
- 변경 기록(`Project.setting_log`: 화, 칸, 전후 값, AI · 작가)
- 1화 반영 뒤 설정 화면 수정 기록(`record_author`, `web.put_project`)
- 되돌리기(`revert`, 스냅샷에 인물 설정이 없어 기록으로 되돌림)
- 자동 집필 · `run -y` 가 남겨 둔 제안(`hold`, `Project.setting_held`, `take_held` · `drop_held`)
- 기록은 프롬프트에 넣지 않는다
- LLM 호출 없음
- 화면은 `static/charlog.js`

### `canon/comfy.py`

- 저장한 삽화 프롬프트(`Illustration`)를 ComfyUI로 그려 작품 폴더 `illust/` 에 PNG로 둔다
- LLM 호출 없음. 사용량 기록(`usage.record`)은 LLM 토큰만 세므로 부르지 않는다
- ComfyUI 주소는 `CANON_COMFY_URL` 이다. GPU 서버의 ComfyUI를 SSH 터널로 이어 쓴다
- `CANON_COMFY_URL=mock` 이면 가짜 ComfyUI(`_fake`)가 시드로 색을 정한 작은 PNG를 준다. 시험과 수동 확인이 쓴다
- 워크플로 틀은 ComfyUI의 'Export (API)' JSON이다(`CANON_COMFY_WORKFLOW`). 화면용 JSON(`nodes` · `links`)은 받지 않는다
- 틀을 정하지 않으면 SDXL 체크포인트 하나로 그리는 기본 틀(`DEFAULT_WORKFLOW`, 체크포인트는 `CANON_COMFY_CKPT`)을 쓴다
- 틀의 글 칸에 적은 자리표 `{{prompt}}` · `{{negative}}` · `{{seed}}` · `{{width}}` · `{{height}}` · `{{checkpoint}}` 를 채운다(`fill`, 한 줄 프롬프트만 쓰는 `workflow`)
- 인물을 영역별로 그리는 틀(리저널)은 기본 칸 `{{main}}` 과 인물 칸 `{{char1}}` ~ `{{char3}}` 를 쓴다
- 인물이 둘 이상이고 틀에 인물 칸이 둘 이상이면 인물을 자리 순(왼쪽 → 가운데 → 오른쪽)으로 인물 칸에 넣고 기본 칸에는 장면만 둔다
- 그렇지 않으면 기본 칸에 모두 넣고 인물 칸은 비운다. 인물 칸보다 인물이 많으면 남는 인물은 기본 칸에 넣고 알린다
- `{{multi:A:B}}` 는 인물을 인물 칸에 나눠 넣으면 A, 아니면 B 다(예: 리저널 모드 번호 `{{multi:3:1}}`)
- 칸 값이 숫자 자리표 하나뿐이면 정수로 바꾼다. 글 안의 자리표는 글로 바꾼다("masterpiece, {{prompt}}")
- `{{prompt}}` 가 없는 틀은 `positive` · `negative` 입력을 따라가 그 노드의 `text` 칸을 채우고, `seed` · `noise_seed` 칸에 시드를 넣는다
- 크기는 `CANON_COMFY_SIZE`(기본 832x1216), 기다리는 시간은 `CANON_COMFY_TIMEOUT`(기본 600초)
- NovelAI용으로 조립한 프롬프트를 SD 태그 조각으로 옮긴다(`parts_of` → `Parts`: 기본 태그 · 자리 순 인물 태그 · 영어 문장 · 부정 태그)
- 인물을 한 줄로 합쳐 보낼 때는 인물이 둘 이상이면 섞일 수 있다고 알린다(`MIXED`, 한 줄 프롬프트는 `prompt_of`)
- 인물 칸의 girl · boy · other 는 인물 수 태그와 겹쳐 뺀다
- 가중치 `1.2::tag ::` 는 `(tag:1.2)`, `{tag}` · `[tag]` 는 1.05배씩 · 1/1.05배씩으로 옮긴다. 0 이하 가중치 태그는 빼고 알린다(`sd_tag`)
- `source#` · `target#` · `mutual#` 를 떼고, 태그 속 괄호는 `\(` `\)` 로 막는다
- `rating:general` · `sensitive` · `explicit` 는 같은 낱말로, `questionable` 은 `nsfw` 로 옮긴다
- '품질 태그 직접 넣기'로 붙은 NovelAI 품질 태그는 뺀다. 체크포인트에 맞는 품질 태그는 틀에 적는다
- 영어 장면 문장은 그 문장을 넣는 모델(V5)로 조립했을 때만 끝에 한 덩어리로 붙인다
- 그리기(`render`): `/prompt` 로 보내고 `/history/<id>` 를 1초마다 보고, 저장 노드(`type: output`) 그림을 `/view` 로 받는다
- 그림을 여러 번 저장하는 틀은 제목에 '최종' · 'final' 이 든 노드의 그림을 받는다(`FINAL_TITLES`)
- ComfyUI 오류 응답은 `error.message` 와 노드 오류를 한 줄로 옮긴다(`_reason`). 그리다 난 오류는 `execution_error` 의 `exception_message` 를 싣는다
- 작업을 멈추거나 시간을 넘기면 ComfyUI 대기열에서 빼고 끊는다(`_drop`: `/queue` delete, `/interrupt`)
- 그림 기록은 `Illustration.images`(`IllustImage`: 파일 · 시드 · 보낸 프롬프트 · 틀 이름 · 알림)이고 삽화마다 `IMAGES_KEEP`(8)장까지 남긴다
- 파일 이름은 16자리 16진수 `.png` 다. 그 밖의 이름은 열지 않는다(`image_path`)
- 작품 데이터가 가리키지 않는 그림 파일은 `prune` 이 지운다. 그림을 더하거나 지울 때, 삽화를 지울 때 부른다
- 파일 쓰기 · 그림 기록 · `prune` 은 한 작품 잠금(`web._edit`) 안에서 한다. 밖에서 하면 함께 도는 그리기의 새 파일을 다른 정리가 지운다
- 그리는 동안 그 삽화가 지워졌으면 파일을 쓰지 않고 작업이 실패한다

### `canon/dynamics.py`

- 관계 역학
- 사건(`StoryEvent`)으로 방향 관계(`Tie`)를 계산
- 긴장도
- 스냅샷 재생(`replay`, 다시 계산 `pipeline.recalc` 가 씀): 1화 뒤에 생긴 관계(작가가 설정 화면에서 더한 관계, 상태 변경안이 더한 새 쌍)는 그 화 스냅샷이 있으면 그 화를 돌린 뒤 스냅샷 값으로 잇고, 스냅샷이 지워졌으면 지금 반영과 같은 차례로 만든다(`_late_relations` · `seed_ties`). 사건 없이 수치만 온 예전 변경안도 그때 반영과 같게 다룬다. 계수를 바꾸지 않았으면 다시 계산이 지금 관계를 그대로 내야 한다(단계 그래프 고침 같은 규칙 변화만 다르게)
- 예전 방식(사건이 없으면 관계 바뀜의 affinity 로 온기를 맞춤)은 `StateDelta.legacy_rel` 이 참인 기록(2026-11-05 전 반영)에만 쓴다. 지금 반영은 수치를 쓰지 않으므로 기록을 거짓으로 남긴다
- 숫자를 말로 바꾸기
- 단계에 들어온 화(`Tie.stage_since`, `run_episode` 가 적고 `replay` 가 다시 채움)를 관계 줄에 '(n화부터)'로(`since`)
- 말로 고른 보는 방식(`VIEWS`)으로 시작 관계 만들기
- 단계 칸 수 `stage_steps`(`STAGE_EDGES` 너비 우선, `pace` · `blueprint` 가 씀)
- LLM 을 부르지 않는 순수 계산

### `canon/elements.py`

- 인과율
- 작가가 언제든 더하는 이야기 요소(`StoryElement`)의 관련 화 지도(`links`)
- 화별로 넣을 요소(`episode_block`)
- 시점 설명
- 본문 · 플롯에서 처음 나온 장소(`NewPlace`)를 '장소' 요소로 등록(`clean_places`, `add_places`, 반영 취소 `unregister_places`, 플롯 후보 `place_candidates`)
- 장편은 그런 장소를 예산(`context.BUDGET["places"]`)까지만
- 비슷한 지명은 `naming.similar_place`
- LLM 호출 없음
- 영향 분석과 반영은 `pipeline.analyze_impact` / `apply_impact`

### `canon/foreshadows.py`

- 복선 센터
- 복선을 본문 문장에 건다(`ForeshadowClue`, `Project.foreshadow_clues`, 본문은 바꾸지 않음)
- AI 문장 정리(`clean_delta`)와 반영 · 되돌리기
- 이미 회수한 복선을 또 회수하는 제안의 경고(`resolved_warnings`, features 정리 훅)
- 작가가 걸기 · 복선 고치기(그 화 이후 스냅샷도)
- 더하기 · 고치기는 완급 계획 갈래(`kind`, `KINDS`)와 판돈 드러남(`public`)도 받는다
- 센터 계산(`center`: 회수율, 끊어진 연결, 예정 지남, 오래 묵음, 플롯 회수 계획)
- 명령줄 `foreshadows`
- LLM 호출 없음

### `canon/genres.py`

- 장르 목록(`CATALOG`)과 장르별 안내
- 프롬프트의 장르 안내(`guide`, 수위 지시는 넣지 않는다)
- 설정 화면의 장르별 로그라인 예시(`Genre.logline`)

### `canon/heatplan.py`

- 완급 계획: 화마다 긴장과 보상(열)을 얼마나(`HeatStep.level` 0~5), 어떤 몫(`role`: 쌓기 · 미루기 · 터뜨리기 · 뒷날 · 쉬기)으로 쓰나
- 단편은 작품 전체에 계획 하나(`Project.heat` · `heat_rule` · `heat_turn`)를 둔다. 장편은 아크마다 하나(`StoryArc.heat` · …)를 둔다
- 계획이 덮는 범위 `Scope`(`scopes` · `scope_for`): 단편은 작품 전체, 장편은 계획이 있는 아크마다. `plan(p, n)` 은 장편이면 n화가 든 아크의 계획
- 화 번호로 찾기 `step`, 뒤집힘(`HeatTurn`: 반격을 심은 화 · 들킨 화 · 상대가 쥐는 것) `turn`
- 계획 정리 `fit`: 범위 밖 화 · 같은 화 두 번째 줄을 버리고 빠진 화를 `FILL_LEVEL` · `FILL_ROLE` 로 채우고 눈금을 0~5 로 자름. 빈 계획은 그대로
- 뒤집힘 정리 `fit_turn`: 범위 밖이거나 들킨 화가 심은 화보다 앞서면 비움
- 경고 `warnings`(`HeatWarn`, 막지 않음): 기복이 작음 · 이른 정점 · 판돈 없는 정점 · 관객 · 제약 없는 정점 · 같은 종류 정점 · 커지지 않은 판돈 · 관객이 본 일의 결과 없음 · 늦은 뒤집힘 · 쌓기 화의 높은 긴장(`WARN_CODES`)
- 장편 경고는 아크마다 따로 본다(`_scope_warnings`). 기복 경고는 아크 첫 화를, 이른 정점은 아크 안 앞쪽인지를 본다
- 잇닿은 터뜨리기 화는 한 정점으로 묶는다(`peak_runs`). 종류 · 판돈 견주기는 정점끼리 한다
- 기복은 세기 눈금 변동계수가 `CV_MIN` 미만이면 경고한다(`FLAT_MIN_EPS` 화 넘는 계획만). 이른 정점은 기 구간이나 작품 앞 `EARLY_SHARE` 안
- 관객 결과는 관객 복선을 처음 거둔 화의 다음 화 플롯(요약 · 사건 · 회수 id)에 그 복선 id 가 있는지로만 본다
- 한 화를 가리키는 경고와 계획 전체 경고 `warnings_for`. 명령줄 `confirm` 이 확정한 화의 경고를 보인다
- 실제 열 참고값 `actual`(`HeatActual`): 절정 낱말 밀도 `density`(`Settings.heat_words`, 공백 뺀 1천 자당) · 큐 긴장 평균 `cue_tension`(목표 글자 수로 가중, 건너뛴 시트는 뺌)
- 판돈 · 제약 · 관객 · 금지선은 복선 갈래(`Foreshadow.kind`)로 둔다. 판돈이 남에게 드러났는지는 `Foreshadow.public`
- 설정 `Settings.heat_plan`(기본 끔)을 켜면 단편은 기승전결과(`HeatArcPlan`), 장편은 다음 아크와(`HeatArcProposal`) 함께 완급 계획을 받는다. 화면은 `static/heatplan.js`, 프롬프트는 `prompts.heat_*`
- 이미 있는 기승전결이나 아크 위에 완급 계획만 받기는 `pipeline.propose_heat`(응답 `HeatProposal`, 웹 작업 `heat`, 명령줄 `heat`)
- LLM 호출 없음

### `canon/illust.py`

- NovelAI 삽화 프롬프트 조립
- AI 원안(`IllustDraft`)에 저장된 인물 외형 태그(`Project.visuals`)
- 인물 수
- 등급
- 모델별 품질 태그(`MODELS`)를 붙여 기본 · 인물 · 부정 프롬프트로(`assemble`)
- 태그 정리(`clean`)
- n화 삽화에 넣을 인물 상태(`states_at`): 반영이 n-1화까지면 지금 상태, 더 뒤까지 반영했으면 n-1화 이하 가장 가까운 스냅샷
- 장편은 스냅샷을 0화 · 아크 끝 · 최근 20화만 남긴다(`pipeline.prune_snapshots`). 옛 화 삽화는 더 앞 시점의 차림 · 위치가 들어갈 수 있다
- n-1화 스냅샷이 지워져 더 앞 스냅샷을 쓰면 그 화를 `Illustration.draft_notes` 에 남긴다
- 맞는 스냅샷이 없으면 지금 상태를 쓰고 'n화보다 뒤 상태'를 `Illustration.draft_notes` 에 남긴다
- `assemble` 은 `draft_notes` 를 `notes` 앞에 둔다. 다시 조립해도 원안을 받을 때의 알림이 남는다
- AI 가 옮긴 장면 인용 대조(`match_quote`): 본문에 그대로 있으면 두고, 띄어쓰기 · 줄바꿈만 다르면 원문으로 바꾼다(`elements.find`)
- 그대로 없으면 연속 1~3문장 창과 견준다. 따옴표 · 문장 부호만 다른 창(`findings.in_text`)이 먼저다
- 다음은 같은 문장으로 보는 창(`findings.same_quote`) 가운데 길이가 가장 가까운 것이다. 글 조각이 인용의 절반보다 적은 창은 견주지 않는다
- 글 조각이 `QUOTE_MIN_GRAMS`(8)보다 적은 짧은 인용은 비슷한 창으로 바꾸지 않는다
- 맞는 창이 없으면 인용을 비우고 `draft_notes` 에 알린다
- 대조 범위는 프롬프트에 넣은 본문 범위와 같다(`prompts.illust_scope`: 고른 부분 앞뒤, 없으면 앞 `ILLUST_FULL_LIMIT` 자)
- LLM 호출 없음
- AI 호출은 `pipeline.illustrate` / `suggest_look` (`illustration` 단계)

### `canon/knows.py`

- 인물이 아는 정보(`CharacterState.knows`)
- 알게 된 화(`learned`, 반영 기록에서 셈, 저장 안 함)
- 장편 프롬프트 보기(`view`: 접은 줄 + '(n화)' 붙인 고른 줄, `prompts.state_view` 가 부름)
- 상태 변경안이 따라 적은 표시 떼기(features 훅 `clean_delta`)
- 아크 요약 뒤 접기 대상(`targets`) · 정리(`clean_fold`) · 적용(`apply_fold`, `CharacterState.knows_folded`, 기록 `Project.knows_folds`) · 되돌리기(`undo_fold`, 반영 취소 훅 `revert`)
- LLM 호출 없음
- 접기 제안은 `pipeline.fold_knows`(작업 `fold_knows`, 프롬프트 `prompts.fold_prompt`, 응답 `KnowsFoldSet`)
- 화면은 `static/knows.js` (`knowsFoldBox`, 아크 카드 요약 칸 아래, `KNOWS_KEEP` 은 `context.KNOWS_KEEP` 과 같음 `tests/test_knows.py`)

### `canon/library.py`

- 문체 라이브러리
- 작품과 따로 `projects/.styles/<id>.json` 에 문체(원문, 프로필, 기준 지표)를 저장
- `save` 는 `store.write_atomic` 으로 바꿔치기해 쓴다. 쓰다 멈춰도 옛 항목이 남는다
- 작품에 적용하면 복사하고 `Project.style_id` · `style_version` 으로 출처만 기억
- 저장마다 버전(`StyleVersion`)
- 칸별 비교(`diff`)
- 작품에서 올리기(`push_project`)는 가져온 뒤 다른 작품이 올린 변경을 덮지 않고 합친다(`merge`). 작품 문체도 합친 것으로 맞춘다
- 합치기는 한쪽만 바꾼 칸은 바꾼 쪽, 목록 칸은 양쪽에서 더한 것을 모두 둔다. 글 칸을 양쪽에서 다르게 고쳤으면 올리지 않는다
- 되돌리기(`restore`)

### `canon/logline.py`

- 로그라인 다섯 칸 합치기(`compose`, 조사 자동)
- 조사 고르기(`josa`)는 앞말의 받침을 본다. 숫자는 읽는 소리로 본다
- '으로' · '로' 쌍은 받침 ㄹ 과 숫자 끝 1 · 7 · 8 에 '로'를 붙인다(서울로, 7로)
- 끝의 따옴표 · 낫표는 건너뛰고 그 앞 글자로 고른다('서윤'이)
- 한글도 숫자도 아닌 끝 글자(로마자 등)는 '이(가)' · '(으)로' 처럼 괄호로 둔다
- 화면 · 서버 문구에서 이름 뒤 조사는 '이(가)'처럼 박지 않고 `josa` 로 고른다. LLM 프롬프트와 서버 로그는 이 규칙 밖이다
- 형식 점검(`checks`)
- 톤 다이얼 문장(`tone_text`)
- LLM 호출 없음
- `static/setup.js` 에 같은 규칙이 있어 함께 고친다(`tests/test_logline_js.py`)
- `josa` 의 화면 쪽은 `static/app.js` 에 있다(여러 화면이 쓴다)

### `canon/naming.py`

- 이름·지명 무작위 생성(세계관별 스타일, 나이에 맞는 한국 이름)과 출연진 이름 점검
- 새 인물을 들일 때의 이름 점검 · 한 화 새 인물 수(`new_cast_warnings`, 상태 변경안 정리 `features._new_cast_names`)
- LLM 을 부르지 않는다
- 자료와 출처는 `canon/naming_data.py`

### `canon/offscreen.py`

- 오래 나오지 않은 인물의 화면 밖 근황(`CharacterState.offscreen`, 시점 화 `offscreen_ep`). 장편 전용
- 대상(`targets`): 다음 아크 시작 화 앞에서 `context.RETURN_GAP` 화 넘게 나오지 않은 인물(`context.last_seen`), 주역 → 조연 → 단역 순서로 `OFFSCREEN_MAX` 명
- 대상에서 빼는 인물: 나온 적 없는 인물 · '넣지 않음' 인물 · 아직 본문이 없는 기획한 화의 플롯 인물
- 제안 정리(`clean`: 대상 인물만, 인물마다 한 줄, `TEXT_MAX` 자) · 저장(`apply`, 시점 화는 다음 아크 시작 화 바로 앞 화) · 지우기(`clear`)
- 물을 수 있는지(`ready`)는 작업을 띄우기 전에도 본다. 저장 전 `check_fresh` 가 제안의 시점 화(`OffscreenSet.at`)가 바뀌었으면 막고 그사이 대상에서 빠진 인물을 뺀다
- 쓰기의 '오랜만에 다시 나오는 인물'(`prompts.return_lines`)과 다음 아크 기획(`listed` → `prompts.offscreen_block`)에 시점 화와 함께 들어간다
- 아크 중간에 돌아오는 인물은 근황이 낡을 수 있어 시점 화를 늘 함께 보인다. 쓰기 블록은 어긋나면 줄거리 · 현재 상태를 따르라고 적는다
- 그 인물이 나온 화(플롯 인물 · 상태 변경안이 다룸)를 반영하면 비운다(features 훅 `apply_delta`, 등장 인물 붙이기 뒤라 `cast_added` 도 든다)
- 본문에 이름만 나온 화는 비우지 않는다. 플롯 밖 인물의 이름은 대개 회상 · 언급이라 공백 판정(`context.last_seen`)보다 좁게 본다
- 반영 취소는 스냅샷이 상태와 함께 되돌린다. 스냅샷 뒤에 저장한 근황은 그 화를 되돌리면 사라진다
- `notes` 와의 차이: `notes` 는 상태 변경안이 화마다 고치는 메모로 인물 현재 상태 칸에 늘 들어간다
- `offscreen` 은 작가가 고른 공백기 이야기라 상태 변경안이 고치지 않고 상태 칸 직렬화에도 없다. 다시 나올 때까지만 쓴다
- LLM 호출 없음
- 근황 제안은 `pipeline.plan_offscreen`(작업 `offscreen`, 프롬프트 `prompts.offscreen_prompt`, 응답 `OffscreenSet` · `OffscreenLine`)
- 명령줄 명령은 없다. 화면에서만 받는다

### `canon/pace.py`

- 관계 속도: 상태 변경안의 관계 유형 · 설명이 반영 뒤 관계 단계와 반대인지 본다(features 훅 `clean_delta`, 등장 인물 붙이기 뒤)
- 사건을 사본에 돌린 반영 뒤 단계(`_after`, `dynamics.run_episode`), 두 방향 단계의 극성(`STAGE_SIGN`, 엇갈리면 0)
- 글 극성(`polarity`: 낱말 사전 `POSITIVE` · `NEGATIVE`, 바로 뒤 '않 · 못 · 없'은 뒤집음), 관계 극성(`rel_polarity`: 유형 먼저, 중립이면 대사와 두 사람 밖 인물이 나온 문장을 뺀 설명 `_others`)
- 반대인 유형 바뀜의 차례 `StateDelta.rel_flagged` → 상태 승인 화면 기본 체크 해제(`review.js` `setDelta`), 사람 검토 없이 반영할 때는 빼기(`hold`, 남긴 개수로 세지 않음)
- `hold` 는 `StateDelta.drop_rel_rows` 로 뺀다. 범위 밖 차례(옛 변경안)는 무시한다
- `hold` 가 뺀 유형 바뀜은 반영 기록의 빼 둔 항목(`StateDelta.dismissed.relationship_updates`)에 남는다
- 두 층 감정(`prompts.LAYER`)으로 상대를 적은 쌍은 빼기(`_masked`)
- 한 쌍 한 화 결정적(3) 사건 `BIG`(3)개 이상 경고
- 쓰기 전 플롯: 화 플롯이 바라는 관계 바뀜(`plot_shifts`: 바뀜 말 `SHIFTS` · 가장 뒤 말 `_last_shift` · 이름 `name_forms`)
- 지금 단계에서 칸 수가 쓸 수 있는 칸보다 많으면 경고(`plot_warnings` · 안 쓴 화 모두 `plan_warnings`)
- 플롯이 설계도의 관계 이정표를 앞지르면 경고(`milestone_warnings`, `plot_warnings` 끝에 붙음): 바라는 단계의 이정표가 모두 이 화보다 뒤일 때
- 보이는 곳은 `board.checks` 와 `static/plot.js` `pacePlot`(같은 규칙, `tests/test_plot_pace_js.py`)
- LLM 호출 없음

### `canon/pairlog.py`

- 두 사람 사이 이력(장편)
- 승인된 관계 사건(`Project.events`)을 쌍마다 모으기(`history`)
- 쓰기 블록(`write_block` · `write_lines`: 이번 화 플롯 인물끼리 한 줄 라벨, 근거 문장 없음, 예산 `context.BUDGET['pairs']`)
- `write_block(trace=)` · `write_lines(trace=)` 는 예산으로 뺀 줄을 보기의 'pairs' 블록에 적는다(`context.trace_drops`)
- 검수 블록(`check_block`: 갈래별 처음 일어난 화와 근거 문장, 예산 `check_pairs`, `prompts.pair_check_block`) · 확인할 것(`check_rule`)
- 새 데이터 없음
- LLM 호출 없음

### `canon/play.py`

- 플레이 모드(작업 중, 명령줄 `play`, 웹 화면 `static/play.js`)
- 세계 작품을 복사한 플레이 사본(`start` → `prepare`, `play.json`, `PlayInfo`, `store.load_play` · `save_play`, 함께 저장 `save`)
- 세계의 마지막 반영 화(`world_ep`) 뒤를 지우고 단편이면 아크 1 로 묶어 `serial` 로
- 시간 단위는 세계의 화 사이 날수로(`pick_unit`)
- 시간이 흐르는 구간(코드 이름은 턴 `PlayTurn`, Episode 하나)마다 흘러간 일(`PlayScene.beats`) + 있으면 결정 장면(`text` · `choices` · `lean`)을 쓴다
  - `scene`
  - `play` 단계
  - `prompts.play_scene_prompt`
  - 본문 `segment_text`
  - 막기 `check_turn`
  - 결정 대기 `waiting`
  - 선택 `choice_action` · 자동 결정 `auto_action`
- 플레이어가 닿은 구간(`see`, `PlayInfo.seen`)보다 한 구간 넘게 앞서 쓰지 않는다(비용 상한)
- 흐르는 중 행동하면 보지 않은 구간을 버린다(`drop_unseen`)
- 상태 반영(`settle`, `prompts.play_state_prompt`, `clean_delta` → `charlog.hold` → `apply_delta` → `Episode.auto`, 실패는 `PlayTurn.state` failed 로 두고 다시)
- `settle` 은 변경안을 만들기 전에 반영 전제 `pipeline.check_applicable` 을 본다
- 장(StoryArc)은 다음 구간을 덮게 미리 연다(`open_chapter`, `CHAPTER_LEN` 20, 세계에 부가 있으면 '플레이' 부)
- 장을 다 반영하면 요약으로 접는다(`fold`, `pipeline.recap`)
- 되감기(`rewind` · `trim_after`)
- 다르게 해 보기(`fork`: 폴더 복사 + `rewind`, play.json 은 옮기고 branch.json 은 안 옮김)
- 운(`roll_luck`, 시드 · 구간으로 정함, 숨김)
- 결말(`PlayTurn.ending` · 구간 수 · 결정 수 · 날수 한도 `_limit_reason` → `end`)
- 설계는 DESIGN.md 10장

### `canon/publish.py`

- 복사 · 내보내기
- 본문을 다른 사이트에 붙여 넣기 좋게 다듬기(줄바꿈 형식 `FORMATS`, 마크다운 흔적 지우기, HTML)
- 여러 화 잇기(`export`)
- 작품이 켠 정규식 규칙 묶음의 내보내기 규칙(`type = "export"`)은 `export` 가 화마다 본문을 꺼낸 뒤 글 · HTML 로 정리하기 전에 건다(`regexrules.export_text`)
- 내보내기 규칙은 저장 전 화면 본문(`drafts`)에도 걸고, 원문 그대로(`raw`) 형식에는 걸지 않는다. 저장된 본문은 바뀌지 않는다
- 고정 정리(폭 없는 글자 · 마크다운 흔적 · 공백)는 코드로 두고 규칙 묶음으로 옮기지 않는다
- LLM 호출 없음
- 화면은 `static/publish.js`

### `canon/renumber.py`

- 화 끼워 넣기 · 빼기
- 반영하지 않은 화의 번호를 옮길 때 함께 옮길 곳(플롯, 구간 · 아크 · 부 범위, 복선, 인과율 요소, 줄기, 인물 첫 등장 화, 대화 주제, 문체 대화 · 에이전트 턴의 화, 복선 근거 문장, 검수 지적 근거 화)
- 옮길 수 없는 화 `last_fixed`: 기본은 본문이 있거나 반영한 화, `move_text` 면 반영했거나 연재처에 올린 화만(본문만 있는 화는 함께 민다, `has_text`). 갈래 · 플레이 작품은 기본 규칙(`store.shares_text`)
- LLM 호출 없음
- 검사와 새 화는 `pipeline.insert_episode` / `remove_episode`
- 새 화 AI 초안은 `draft_episode`(`prompts.episode_plot_prompt`)
- 본문이 있거나 반영한 마지막 화 지우기는 `delete_last`(반영 취소 → 본문 비우기 → 화 빼기, 웹은 `before-delete-<화>.json` 백업)
- 화 번호를 품은 칸을 새로 만들면 `move_points` 에도 넣는다
- 이 작품의 문체로 고른 화 번호도 옮긴다(`anchor.move`)
- 설계도의 화 범위도 옮긴다(`blueprint.move`, 알림 '설계도 줄 n개')
- 화면은 `static/insert.js` (넣을 수 있는 자리 `lastFixed` 는 `last_fixed` 와 같은 규칙, `tests/test_insert_js.py`)
- `insert.js` 의 화 지우기 버튼을 막은 이유(AI 작업 중, 자동 집필 중, 스냅샷 없음)를 버튼 아래 글로도 보인다
- 화 지우기 확인 창은 지우기 전 작품을 설정 › 백업에서 되돌릴 수 있다고 알린다
- 앞 화 스냅샷이 없어 막힌 경우는 '반영 직후의 상태 기록(스냅샷)'이라 풀어 쓰고, 장편이면 남기는 규칙과 설정의 '스냅샷 모두 남기기'를 알린다

### `canon/routes/play.py`

- 플레이 모드 웹 라우트(`/api/projects/{name}/play/...`, 출생 배경)
- `GET /api/projects/{name}/play` 는 플레이 사본이 아닌 작품에 200 과 `null` 을 돌려준다. 작품 홈이 화면을 옮길 때마다 묻기 때문이다
- 쓰기 경로(`play/advance` · `see` · `rewind` · `end` · `fork` · `settings`)와 `play/life` 는 플레이 사본이 아니면 `_play` 가 400 을 낸다
- 작품 목록 카드의 플레이 요약(`_play_card` · `_play_days`)은 `web.py` 에 남는다
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 공용 도우미(`_load` · `_save` · `_edit` 등)는 `..web` 에서 불러 쓴다
- 다음 구간 미리 쓰기(`_play_continue`)는 서버가 다시 시작하려고 기다리는 중(`jobs.Draining`)이면 쓰지 않고 넘어간다. 끝난 구간 작업과 `play/see` 저장은 성공으로 남는다

### `canon/setupchat.py`

- 설정 도우미 대화(대화 주제 `setup`)
- AI 변경안(`SetupRevision`: 기본 정보 · 세계관 칸 `SetupEdit`, 인물 칸 `CharacterEdit`, 새 인물, 관계, 방향 여러 안) 정리(`clean`)
- 고른 부분만 적용(`apply`, 부분 id `part_ids`)
- 변경안 단위 적용 취소(`undo`, `ChatMessage.setup_before`)
- 적용 · 적용 취소의 몸통은 `apply_revision` · `undo_revision` 이다. 대화 에이전트의 설정 도구(`agent_setup`)도 같은 함수를 쓴다
- 기록(`record`)
- AI 는 칸 · 인물 · 관계를 지우지 않는다
- 첫 반영 뒤에는 AI 가 관계의 시작 방식과 수치를 바꾸지 않는다
- 관계의 가 닿을 곳(`destination`)은 AI 가 비워 보내면 지금 값을 지킨다
- 1화 반영 뒤 바꾼 인물 칸은 `charlog.record_author` 로 남긴다
- 인물 다른 이름(`aliases`)은 `secrets` 와 같은 목록 칸이다(`CHAR_LIST_FIELDS`). 한 글자 말은 `clean` 이 뺀다
- 다른 이름은 `charlog.LOG_FIELDS` 밖이라 `record_author` 기록에 남지 않는다
- LLM 호출은 `pipeline.revise_setup`
- 프롬프트는 `prompts.setup_chat_prompt`
- 명령줄 `setupchat`

### `canon/stateedit.py`

- 반영 뒤 지금 상태 고치기: 작가가 인물의 감정 · 목표 · 위치 · 차림(`FIELDS`)을 상태 반영 뒤에도 고친다(`set_state`)
- 고친 것은 마지막으로 반영한 화(`statwin.last_done`)의 작가 기록(`Project.state_log`: 화, 칸, 반영 값, 고친 값)으로 남기고 그 화 스냅샷도 맞춘다(`dynamics.take_snapshot`, `statwin.set_stats` 와 같은 방식)
- 같은 화 뒤에 같은 칸을 또 고치면 한 기록으로 합치고, 반영 값으로 돌아오면 기록을 지운다
- 그래서 기록이 있으면 마지막 반영 값과 다르다
- 1화를 반영하기 전에는 1화 시작 전(0화) 상태를 고치고 0화 기록으로 남긴다
- 스냅샷 0 은 있을 때만 맞춘다(없으면 첫 반영이 고친 값으로 만든다)
- 화 되돌리기는 n화 뒤 기록을 자르기만 한다(`revert`, features 훅 `REVERT_LAST`)
- n화 뒤 기록을 n화로 옮기지 않는다: 지금 상태는 그 화 시점에만 맞아 뒤 화 상태가 앞 화 프롬프트에 들어간다
- 인물 화면이 스냅샷을 지운 화를 다시 계산할 때(`cast._apply_gap`)도 그 화 기록의 고친 값을 덮는다
- 아는 정보 · 메모 · 상태창 수치(`statwin`) · 관계 수치(`수동보정` 사건)는 다루지 않는다
- 웹 `PUT /api/projects/{name}/state/{cid}`(빠진 칸은 그대로, 빈 글은 비움)
- 화면은 `static/cast.js` 의 지금 상태 카드
- LLM 호출 없음

### `canon/static/abilities.js`

- 스킬 도감 화면(사이드바 도구, 공용 목차 틀 `outline.js`)
- 주소 `abilities`(개요) · `abilities/_missing`(도감에 없는 조각) · `abilities/_new`(새 항목) · `abilities/<항목 id>`
- 왼쪽 목차 `abToc`(찾기 칸, 개요, 도감에 없는 조각, 상태창 항목별 묶음 `abGroups`, 줄 끝 `abTail`)
- 개요 `abOverview`(수 타일, 손볼 것, 도감에 없는 조각 다섯)
- 도감에 없는 조각 쪽 `abMissingPage`(상태창 항목 거르기, 가진 인물, '도감에 만들기')
- 항목 쪽 `abItemPage`: 머리(⋯ 메뉴에 지우기) · 설명 · 효과 · 대가 · 등급별 효과 · 가진 인물(바뀐 걸음 `abSteps`) · AI 에게 보이는 줄
- 카드는 읽기 먼저이고 '고치기'로 그 카드만 편다(`S.abEdit`: base · grades · new)
- 고치는 카드는 연 때의 값(`S.abEdit.orig`)과 견줘 다르면 `S.editDrafts.ab` 를 켠다(`abDraftMark`). 다른 항목 · 화면으로 가면 `app.js` 가 묻는다
- 같은 화면에서 다른 카드나 새 항목 칸을 열 때 고치던 글이 있으면 먼저 묻는다(`abDropOk`, `tests/test_statwin_js.py`)
- 넣기 방식 `context` 는 나눔 버튼으로 바로 저장한다(`abContext`)
- 넣는 방식 `stat_window.prompt` 가 lines 가 아니면 AI 에게 보이는 줄 카드가 알린다
- 인물 카드 · 상태창 수치의 상태창 칩(`abChip`)을 누르면 뜨는 도감 카드(`abShow`, 공통 대화상자 `showDialog`)
- 칩의 '도감에 설명 없음' 점은 `abNoDoc`(`abFindLocal` 은 `abilities.find` 와 같다)
- 목록 이름 `AB_LIST_NAMES` 는 `abilities.LIST_NAMES` 와 같다(`tests/test_statwin_js.py`)
- `abSplit` · `abKey` 는 `abilities.split` · `key` 와 같다(`tests/test_statwin_js.py`)

### `canon/static/agent.js`

- 대화 에이전트 패널. 작품 안 모든 화면에 하나다(`chat.js` 의 `chatPanel()` 이 부르고, `app.js` `drawApp` 이 `chatDock` 으로 셸 끝에 붙인다)
- 다음 턴의 대상은 `agentTarget`: 고정한 세션은 세션 대상, 아니면 화면 대상(`agentScreenTarget` = `S.chatHere.target`)
- 턴은 `agentTurnScope` 로 화면 대상을 함께 보낸다(고정한 세션은 빼고). 연 구간 · 화 · 다음 아크 초안은 플롯 화면에서만 보낸다
- 턴은 보던 화면 이름(`screen`, 작품 홈은 'home')도 보낸다. 서버가 `agent.SCREENS` 로 확인한다
- 상태 줄의 대상이 바뀌면 `agentAfterDraw` 가 `.foot-target` 을 한 번 강조(`flash`)하고 `chatSay` 로 `#chat-live` 에 알린다. 패널을 처음 그릴 때는 알리지 않는다
- 상태 줄의 핀(`agentPin`)과 다듬을 곳 메뉴(`agentTarget`)는 세션을 고정한다. `/대상` 은 고정을 풀고 화면 대상으로 돌린다
- 문체 대상의 빈 세션은 문체 도구 안내를 보인다. 옛 문체 대화에서 빌려 오던 예시 알약은 04e 에서 그 대화와 함께 뺐다(예시는 일감 10)
- 빈 세션의 예시 요청은 `agentExamples(대상)` 이 틀 문장에 작품 값(인물 이름 · 화 번호 · 아크 번호)을 채워 둘까지 낸다. AI 를 부르지 않는다(`tests/test_ai_tells_js.py`)
- 채울 값이 없으면 예시 버튼 줄을 그리지 않고(`agentExampleRow`) 입력칸 예시 글만 남는다. 본문 · 문체 대상은 예시가 없다
- 본문 대상의 빈 세션은 '드래그하면 재료로 붙고, `/` 빠른 요청을 고르면 후보를 골라 넣는다' 안내를 보인다
- 설정 대상의 빈 세션은 `agentSetupIntro`(설정 도구 안내와 예시)를 보인다
- 세션 동작 `agentAct(fn, { save })` 와 말 보내기 `agentStartTurn`: AI가 작품을 읽거나 고치는 동작은 저장하지 않은 변경이 있으면 저장할지 묻는다. 세션 만들기 · 대상 · 권한 모드 · 이름 · 보관은 `save: false` 로 묻지도 저장하지도 않는다
- `agentAct` 는 응답의 `project` 가 객체일 때만 `S.project` 를 바꾼다. 이어 하기 응답은 작업 정보라 `project` 가 작품 이름 글이다
- 세션 머리와 목록(보관함, '이전 대화'는 옛 `Project.chats` 를 `chatLog` 로)
- '이전 대화 · 플롯'(`legacy`)은 예전처럼 골라 적용 · 취소한다. 설정 · 문체 · 본문 고치기(`legacy:<주제>`)는 `chatLog(주제, { readOnly: true })` 로 읽기만 한다
- 읽기만 하는 설정 · 문체 기록도 적용한 변경안은 '적용 취소'를 둔다(`chat.js` `chatReadOnlyCard`). 본문 고치기 기록의 안내는 집필 화면 수정 기록에서 되돌리라고 적는다
- 턴마다 단계 줄 · 바로 쓴 것(항목 · 턴 되돌리기) · 승인 카드 · 되묻기 카드
- 설정 도구의 승인 카드(`Approval.setup`)와 쓴 것 비교(`WriteRecord.setup`)는 `agentsetup.js` 가 그린다(`agentApproval` · `agentItemDiff` 가 넘긴다)
- `agentDecide` 는 설정 카드면 `agentSetupPicks`(체크했고 막히지 않은 부분)를 보낸다
- 문체 변경안 카드 `agentStyleApproval`: 칸마다 체크 · 지금 값과 비교(`stylechat.js` `styleEditDiff`) · 시험 문단(`sampleBlock`)을 보인다. '이 세션에서 묻지 않기'는 그리지 않는다
- 적용한 문체 기록은 칸별 되돌리기 없이 '적용 취소' 하나로 턴의 기록을 돌린다
- 정규식 규칙 제안 카드 `agentRegexApproval`: 규칙 칸(고치기면 칸마다 전 · 뒤), 동작 문구, 시험 줄과 바뀐 곳(`regexrules.js` `ruleChangeHtml`) · 걸린 곳
- 규칙 카드는 다른 작품 수 · 새 묶음 안내 · 알림(`notices`)을 보이고 '이 세션에서 묻지 않기'는 그리지 않는다. 규칙 키는 `in` 과 `in_` 을 다 읽는다
- 규칙 카드를 적용하면 언제부터 걸리는지 알린다(`agentRxDone`). 턴이 끝나므로 '이어서 돌아요'가 없다
- 적용한 규칙 항목은 '적용함'으로 보이고 '바뀐 칸 보기'는 적용 전 · 뒤 규칙 칸이다(`agentItemDiff` 의 `w.regex`)
- 입력 상자(+ 재료, `/` 빠른 요청 `AGENT_CMDS`, 보내기 · 멈추기)와 상태 줄(권한 모드 · 대상 · 대상 고정 · 모델 · 단계 상한)
- 재료 칩(`agentMats`, `S.agentMaterial`): 집필 화면에서 고른 본문이 입력 상자 위에 붙는다. 붙이기는 `agentAttach`(`passage.js` 가 부른다), 떼기는 ✕(`agentMaterialDrop`)
- 본문에서 사라진 재료는 칩을 감추고 보내지 않는다(`agentMaterialNow`)
- '+ 재료' 메뉴는 집필 화면에서 고른 본문(`curSel`)이 있으면 '고른 본문'을 붙인다
- 본문 빠른 요청(`S.presets`, 서버 `prompts.PASSAGE_PRESETS`)은 `/더 짧게` 같은 `/` 명령이다(`agentTextCmds`). 본문 대상이거나 재료가 붙었을 때만 뜬다
- `/` 명령은 띄어쓰기 없이 써도 받는다(`agentParsePreset`). '/' 목록은 띄어쓰기를 빼고 견준다
- 재료가 붙은 말은 `selection`, 빠른 요청은 `preset` 으로 보낸다. 서버가 에이전트 단계 없이 본문 고치기를 바로 부른다. 보낸 재료는 뗀다
- 본문 고치기 카드(`agentTextApproval`): 후보마다 원문과 낱말 비교(`wordDiff`), '이걸로 넣기' · '손봐서 넣기', 아래 '모두 넣지 않기'
- 늘 묻는 종류(`AGENT_ALWAYS`, 서버 `agent.ALWAYS_ASK`)의 카드는 '이 세션에서 묻지 않기'를 두지 않는다
- `AGENT_ALWAYS` 는 `agent.ALWAYS_ASK` 와 같다(`tests/test_agent_js.py`)
- 카드에 답하기(`agentTextDecide`)는 그 화 본문 초안을 먼저 저장한다(`flushText`). 넣으면 넣은 글을, 넣지 않으면 고른 부분을 재료로 다시 붙인다
- 바로 쓴 것의 본문 고치기 항목은 수정 기록(`agentTextEdit`)으로 바뀐 글을 보인다. 수정 기록에서 되돌렸으면 되돌린 것으로 보인다
- 마지막 턴이 본문 후보를 기다리면 패널에 `has-cands` 를 단다(휴대폰 시트가 높아진다)
- 본문 고치기 카드를 연 턴이 끝나면 작품을 다시 받는다(`agentJobUpdate` → `agentRefreshProject('')`). 카드가 남긴 부분 수정 대화를 화면 저장이 옛 사본으로 덮지 않게
- `agentOpenText`: 집필 화면 머리의 'AI에게 고치기'. 대화 에이전트를 열고 고른 본문을 재료로 붙인다. 열려 있으면 닫는다
- Enter 보내기(`chat.js`)는 `agentSend` 를 바로 부른다. 옛 `chatSend` 를 가로채던 줄은 04e 에서 지웠다
- 문체 대상이면 '+ 재료'에서 참고할 화(`epSelect('styleRefEp')`)를 골라 입력 상자 위 칩(`agentRefChip`)으로 붙인다. 턴의 `episode` 로 간다(`agentTurnScope`)
- 진행은 `pollJobs` 가 `agentJobUpdate` 로 알린다
- 도는 턴의 단계 줄은 지금 하는 일(`agentStepNow`: `Job.retry` 가 있으면 그 사정, 없으면 'AI 응답을 기다리는 중')과 직전 단계의 생각(`Job.note`)을 보인다
- 지금 하는 일과 늦음 안내는 1초마다 그 자리만 고친다. `Job.retry` 가 보이는 동안 일반 늦음 안내는 숨긴다
- 끝난 턴은 '끝났어요 · N단계 · 걸린 시간'(`agentTurnTook`, `at` 부터 `ended` 까지) 줄을 보인다
- 화면 낭독기에 알릴 새 답은 `agentLastReply`(끝났거나 묻는 중인 턴의 답)이고 `chat.js` `chatAnnounce` 가 알린다
- 권한 이름 `AGENT_MODES` · `AGENT_KINDS` 는 `agent.MODE_LABELS` · `KIND_LABELS` 와 같다(`tests/test_agent_js.py`)

### `canon/static/agentsetup.js`

- 대화 에이전트의 설정 도구 카드(서버 `agent_setup.py`)
- 칸마다 지금 값과 나란히 보인다. 비교는 `setupchat.js` 의 `setupKeyValue` · `setupRelDiff` · `setupNewCard` 와 `chat.js` 의 `diffField` 를 쓴다
- 처음 체크는 서버의 `Approval.defaults` 다(`agentSetupPicked`). 채운 칸에는 '채운 칸 바꿈', 인물 칸에는 '인물 설정 바꿈' 칩을 단다
- 고르지 않은 새 인물과 이어진 관계는 끈다(`agentSetupBlocked`). 새 인물 체크를 바꾸면 패널을 다시 그린다
- '이 세션에서 묻지 않기' 칸은 없다. 넷 이상인 카드는 모두 고르기 · 모두 빼기(`agentSetupPickAll`)
- 쓴 뒤 비교는 쓰기 전 설정(`WriteRecord.setup_before`)과 한다(`agentSetupItemDiff`)
- 설정 대상의 빈 세션 안내와 예시(`agentSetupIntro`, 예시는 `agent.js` `agentExamples('setup')`)

### `canon/static/aliases.js`

- 다른 이름 고르기 카드(서버 `aliases.py`, 작업 `aliases`)
- 작업 표(`JOB_PAGES` · `JOB_LINK` · `JOB_DONE_MSG` · `SCREEN_ONLY_JOBS` · `JOB_BTNS.aliasAI` · `JOB_RESULT`)에 `aliases` 를 등록한다
- `JOB_PAGES.aliases` 는 작업 대상에 따라 화면을 고르는 함수다: 인물(`c:`)은 설정, 요소(`e:`)는 인과율. `app.js` 의 `jobPages` 가 함수 값을 푼다
- 결과는 작업 대상을 열쇠로 `S.aliasSug` 에 놓는다. 항목 하나(`c:<id>` · `e:<id>`)는 그 카드에, 여러 항목(`c:` · `e:`)은 목록 머리에 보인다
- `aliasCard(scope)` 는 칩마다 체크 칸 · 화 수(`aliasHitText`) · 겹침('‹이름›과 겹쳐요')을 그린다. 기본으로 체크하지 않는다
- 이미 칸에 있는 말은 '이미 있어요'로 끈다
- '고른 다른 이름 적용'(`aliasApply`)은 고른 말을 칸에 더하고 저장 띠로 저장하게 한다. 따로 적용 엔드포인트가 없다
- 칩 줄은 `.proposal` 안의 `.body-sug` 줄을 다시 쓴다(새 컴포넌트 없음)

### `canon/static/anchor.js`

- 문체 화면의 '이 작품의 문체' 카드(`anchorCard`, 목차 줄 `anchorTocWord`)
- 고르기 전 · 저장한 뒤는 구역(`.sec`), 고르는 동안은 카드다. '화 고르기' · '이 작품의 문체로 저장'은 보조 버튼이다(문체 화면 주 버튼 하나)
- 화 칩으로 고르기 · 대표 문단 후보 고르기(4개까지) · 저장 · 다시 재기 · 지우기(`anchorChooser`)
- 다시 고를 때 후보를 열지 않으면 지금 대표 문단을 그대로 저장한다(`anchorBody`)
- 후보를 열면 지금 대표 문단을 맨 앞에 체크해 둔다. 저장할 때 지금 문단이 빠지면 묻는다
- 이 작품의 문체와 레퍼런스 기준 비교 표(`anchorCompare`)
- 화별 문체 거리 추이 SVG(`anchorChart`: 사람 연재 띠 · 경고 점선 · 최근 5화 평균 선 · 문체를 바꾼 화 세로선)
- 서버는 `web.py` 의 '2-0. 작품 정착 문체'

### `canon/static/blueprint.js`

- 설계도 쪽(사이드바 도구 '설계도', 🧭): 공용 목차 + 카드 한 열(스킬 도감과 같은 틀 `.ab-wrap`)
- 주소 `blueprint`(개요) · `blueprint/<쌍 키>`. 쌍 키는 두 인물 id 를 정렬해 `~` 로 이은 것(`bpKey`)
- 쌍 목록 `bpPairs`: 관계 설정의 쌍(그 차례와 a · b 차례)에 설계도에만 있는 쌍을 더한다
- 개요: 수 타일 · 경고 · 설계 원칙 카드 · 쌍 목록
- 쌍 쪽: 계획 띠 `bpBand`(두 방향 이정표 · 접촉 사다리, 아크 · 구간 경계, 마지막 반영 화) · 그 쌍의 경고 · 관계 이정표 카드 · 접촉 사다리 카드
- 계획 띠 기본 범위 `bpSpan`: 기획한 화와 그 쌍 설계도 끝 화 가운데 큰 것. '작품 전체'(`S.bpWide`)로 바꾼다
- 카드는 읽는 모양이 기본이고 '고치기'로 그 카드만 편다(`S.bpEdit`: 설계도 사본, 저장하지 않은 글은 `S.editDrafts.bp`)
- 사다리 칸의 부위 · 동작 · 장소는 접는 칩 묶음 `bpChips`(펴 둔 묶음은 `S.bpPickOpen`)
- 저장 `bpSave` 는 서버 설계도에 고친 카드 몫만 바꿔 넣어(`bpMerged`) `PUT …/blueprint` 로 보낸다. 칸을 다 지운 사다리는 뺀다
- 단계 말 `BP_STAGES` 는 `schema.RelStage` 와 같다(`tests/test_blueprint_js.py`)
- 쌍 쪽 맨 아래 'AI로 설계도 받기' `bpExtractCard`: 메모 · 부 고르기 · 'AI로 짜기'(작업 `blueprint_draft`), 플롯이 있으면 '지금 플롯에서 뽑기'(작업 `blueprint`, 장편은 아크 고르기)
- 제안 카드 제목은 결과의 `mode` 로 'AI가 짠 설계도' · 'AI가 뽑은 설계도'
- 개요의 관계 목록 줄마다 '여정 짜기' 버튼(그 쌍 쪽으로)
- 도착한 제안은 `S.bpDraft` 로 계획 띠 · 경고 다음 카드 `bpDraftCard`(줄마다 고르기 · 근거). '고른 줄 더하기'는 `POST …/blueprint/apply`
- 본문에서 닿은 칸 `bpReached`(서버 `blueprint.reached` 와 같다): 사다리 카드의 'n화에 닿음', 계획 띠의 '본문에서 닿음' 줄
- 남겨 둔 닿은 칸 카드 `bpHeldCard`(개요 · 쌍 쪽, '기록하기' · '버리기' → `POST …/blueprint/held/{i}/{take|drop}`)
- 상태 승인 화면 '직접 정할 것'의 닿은 칸 줄 `contactDeltaRows`(review.js 가 부른다, 체크 키 'u')

### `canon/static/branches.js`

- 갈래 화면
- 작품 머리 띠(`branchStrip`)
- 띠는 화면 머리 아래 한 줄이고 집안 작품 열기는 ⋯ 메뉴(넣는 자리 `branchPlace`, 머리로 시작하지 않는 화면은 맨 위)
- 갈래 만들기 칸을 편 동안 `branchPlace` 는 머리와 본문의 주 버튼을 보조로 낮춘다(주 버튼은 칸의 만들기 하나)
- 함께 쓰는 앞 화를 고친 경고와 남겨 둔 본문 이어 가기는 띠 아래 Note
- 사이드바 갈래 줄(`branchSideTag`)
- 갈래 만들기 칸(`branchFormCard`, 폴더 이름 `branchFolder` 는 `home.js` `folderOf` 와 같은 규칙)
- 만들기 칸은 화면 머리 아래에서 펴고 시작 화를 화 칸 띠로 보이며 폴더 이름은 접어 둔다
- 작품 목록 묶기(`branchGroups`)
- 작품 홈 갈래 카드(`branchHomeCard`: 비교 버튼, ⋯ 메뉴에 작품 열기 · 본편으로 올리기 · 갈래 끊기)
- 갈래 지도 줄(`branchMapRows`)은 작품 홈 갈래 카드와 갈래 비교 화면이 함께 쓴다
- 갈래 비교 화면(`viewBranches`, 공용 목차 틀 `outline.js`)
- 갈래 비교 목차(`bcToc`): 견줄 작품(집안 나무) · 이 비교(갈라진 길 · 화별 줄거리 · n화 본문 · n화 반영 뒤 상태)
- 갈래 비교 본문은 문단을 맞춰 나란히 둔다(`bcParaDiff`, 기본은 다른 문단만 `S.bcAll`)
- 갈래 비교 화면 · 띠 · 만들기 칸 시험은 `tests/test_tools_js.py`
- 이름 없는 갈래는 폴더 이름으로 부른다(`branchName`, 명령줄 `branches` 와 같은 규칙, `tests/test_branches_js.py`)

### `canon/static/cast.js`

- 인물 · 관계도 화면(공용 목차 틀 `outline.js`)
- 인물 카드의 등장 띠 칸을 누르면(`castStripGo`) 그 화를 반영한 시점으로 옮기고(재생은 멈춤), 없으면 그 화에서 할 일 화면(`epGo`)으로 간다. 등장표 칸은 그 화를 연다
- 추이 그래프는 둘째 선부터 점선으로도 가르고, 그래프 아래에 고른 시점 값과 사건을 글로 보인다(`.cc-read`)
- 인물 쪽 `castCharPage` 는 남겨 둔 설정 바꾸기 제안이 있으면 설정 카드를, 남겨 둔 호칭이 있으면 그 카드를 머리 바로 아래에 둔다
- 왼쪽 목차 `castToc`(관계도 · 등장표 · 비중별 인물, 단역이 많으면 접음 `castMinorFold`)
- 오른쪽 한 열의 쪽 `castPage`(`S.castView`: map · table · char · pair, 옮기기 `castShow`, 주소 `cast/<map · table · c:id · p:a|b>?f=` 와 옛 `?tab=` 은 `castParse`)
- 열 맨 위 시점 띠 `castBar`(좁은 칸은 아래에 붙음)
- 시점 띠가 400px 이하 칸이면 글에서 '반영 뒤'(`.cast-bar-after`)를 빼 화 번호가 잘리지 않게 한다
- 관계도 `castMapPage`(SVG, 화별 재생, 칸 폭에 맞추고 크게 보기 `CAST_ZOOM`, 누르면 고르기만 `castMapPick` · 고른 줄 `castMapSel`, 끌어 옮긴 배치는 localStorage)
- 인물 끌기가 끊기면(`pointercancel`) `castDrag` 를 지운다
- 관계도 선(`.cg-edge`) · 긴장 점(`.cg-tension`) · 추이 그래프 칸(`.cc-col`)도 `tabindex="0"` · `role="button"` · `aria-label` 을 달고 Enter · Space 로 누른다
- 추이 그래프 SVG 는 안에 버튼이 있어서 `role="group"` 이다
- 시점 · 크기를 바꿔 관계도나 쪽을 다시 그리면 포커스를 같은 `data-action` · `data-arg` 요소로 돌린다(`castSwap`)
- 640px 이하 관계도는 600px보다 좁게 줄이지 않고 옆으로 굴린다(이름이 5px로 줄지 않게, app.css)
- 관계도 온기 다섯 단계 선 색은 `WARMTH_BANDS`(적대 `--warm-hostile`, 반감 `--bad`, 무덤덤 `--warm-mid`, 호감 `--good`, 아낌 `--warm-deep`)
- 인물 쪽 `castCharPage`
  - 머리 `castHead` · 보는 시점의 상태 · 상태창 수치(바뀐 양 `castStatDelta`, 카드 | 시스템 창 보기는 localStorage, 창 모양은 작품 스킨 `stat_window.skin`) · 관계 줄 `castSheetRels`(온기 막대 `castMeter`) · 비밀 · 설정과 남겨 둔 제안 · 읽기 먼저인 'AI · 서술 · 신체 · 삽화' 카드 `castEditCard`
    - 지금 상태 카드 `castSheetState` 는 마지막 시점에서만 '고치기'를 보인다(`S.castStateEdit`, 저장 `castStateSave` → `PUT …/state/<인물>`)
    - 고친 칸(`castStateLog`: 그 시점 화의 `state_log` 기록)은 '직접 고침'과 반영 값을 보이고, 마지막 시점이면 되돌리기 `castStateUndo` 로 반영 값을 다시 보낸다
    - 지금 상태 저장 · 되돌리기는 저장하지 않은 작품 변경을 먼저 저장한다(뒤에 저장하면 옛 상태로 덮는다)
    - 상태창 칸 모양은 `statwin.js` `swStatsBody` 와 같이 쓴다
    - 고치기 `S.castEdit`: AI에 넣기 `charContextField` · 서술 말투 `plot.js` `voiceField` · 신체 프로필 `bodyFields` · 삽화 외형 태그 `illust.js` `visualFields`
    - AI 제안 동작은 `research.js` `bodyAI`
  - 타임라인(앞뒤 `CAST_TL_NEAR` 화)
- 두 사람 쪽 `castPairDetail`(추이 그래프 · 보정 · 호칭)
- 관계 보정 `tieFix` 는 저장하지 않은 변경이 있으면 저장하고 보정할지 먼저 묻는다
- 등장표
- 인물 원은 목차 24 · 줄 36 · 머리 64px(`castAva`)
- 온기 색 구간은 `dynamics.warmth_word` 경계와 같다(`tests/test_labels_js.py`)
- 주소 읽기는 `tests/test_cast_js.py`

### `canon/static/causal.js`

- 인과율 화면(주소 `causal[/<요소 id>]`, `viewCausal`, 라우터가 부르는 `causalPick`)
- 공용 목차 틀(`outline.js`, 목차 `causalToc`: 개요 · 손볼 것 · 종류별 요소) 위에 쪽 둘: 개요 · 요소 하나
- 개요: 손볼 것 `causalTodoCard` → 모든 요소 `causalListCard`
- 모든 요소 카드 머리의 '빈 다른 이름 제안'은 작업 `aliases`(대상 `e:`)를 띄우고 결과 카드(`aliasCard('e:')`)를 그 아래에 둔다
- 요소 내용 카드의 '다른 이름 제안'(고치는 중)은 대상 `e:<요소 id>` 다. 받은 카드는 읽기 · 고치기 모두에서 보인다
- 요소 하나(`causalDetail`): 요소 내용 읽기 카드 `causalInfoCard`(고치기 `S.causalEdit`) → 관련 화 `causalLinksCard` → 영향 분석 `causalImpact`
- 관련 화는 30화씩 칸 줄(`CZ_CHUNK`)과 나눔 버튼 `S.causalLinkTab` 으로 거른 줄 목록
- 640px 이하는 칸 줄이 한 줄 10화다(`czChunk`). 칸은 버튼이고 화 번호 · 표시를 `aria-label` 로 읽는다. 손가락 기기 · 640px 이하에서 높이 32px
- 칸 · 줄을 누르면(`causalCell`) 영향 분석의 그 화 칸으로, 없으면 그 화로 간다
- 칸 상자는 `aria-hidden` 이라 칸 버튼은 Tab 에서 뺀다(`tabindex=-1`). 키보드는 줄 목록으로 간다
- 줄 목록은 12줄까지 보이고 '모두 보기'(`causalLinkAll`, `S.causalLinkAll`)로 편다
- 영향 분석은 화별로 어긋나는 곳과 고칠 것을 묶는다(`causalImpactBody`, 고르기 키 `pickId` 는 그대로)
- 쪽을 옮길 때 해시 대신 `history.replaceState`(`causalGoTo`)라 저장하지 않은 고침을 묻지 않는다
- `causalStatus` · `causalCells` 는 순수 함수(`tests/test_causal_js.py`)
- `elements.basis` 와 같은 모양(`elBasis`)으로 분석이 지났는지 본다(`tests/test_causal_js.py`)
- CSS 는 JS 에서 주입

### `canon/static/charlog.js`

- 상태 승인 화면 '직접 정할 것'의 인물 설정 바꾸기 줄(`scDeltaRows`, 키 `t`, 기본으로 체크하지 않음, 값 고치기)
- 반영 기록(`scHistory`)
- 인물 화면의 남겨 둔 제안(`scHeldCard`) · 설정 변경 기록(`scLogCard`) · 보는 시점의 설정(`scAt`)
- 칸 이름 `SC_LABELS` 는 `charlog.LOG_FIELDS` 와 같다(`tests/test_labels_js.py`)

### `canon/static/foreshadow.js`

- 복선 센터 화면(주소 `foreshadow[/<복선 id>]`, `viewForeshadow`, 불러오기 `fsLoad`)
- 640px 이하 복선 걸기 시트는 키보드 위에 선다(`bottom: var(--kb)`, 높이 `85svh - --kb`)
- 칸 폭 480px 이하 복선 지도 축(`.fs-axis`)은 첫 화 · 지금 · 마지막 눈금만 보인다(이름표 겹침 막기). 복선 하나의 축은 그대로
- 공용 목차 틀(`outline.js`, 목차 `fsToc`: 개요 · 손볼 것 · 열린 복선 · 접은 회수한 복선 `S.fsDoneOpen`) 위에 쪽 셋: 개요 · 복선 하나 · 빈 화면
- 개요
  - 수치 `fsStats` → 손볼 것 `fsTodoCard` → 복선 지도 `fsMapCard`: 화 축 하나
  - 아크 · 구간 띠 `fsBands`
  - 줄마다 `fsTrack`
  - 거르기는 Seg `S.fsTab` · `S.fsScope` → 앞으로 회수할 것 `fsAheadCard`
- 복선 하나(`fsDetail`: 축 → 본문에 걸린 문장과 흐름 `fsFlowCard` → 회수 계획 읽기 카드 `fsPlanCard`, 고치기 `S.fsEdit`, 회수로 표시 `S.fsResolving`)
- 더하기 칸과 회수 계획 칸에 적던 값은 `S.fsAddDraft` · `S.fsEditDraft` 에 두어 다시 그려도 남는다(`fsDraftInput`)
- 그 칸에 저장하지 않은 글이 있으면 `S.editDrafts.fs` 를 켠다(`fsDraftMark`)
- 더하기 · 저장 · 회수로 표시는 서버가 받은 뒤에만 칸을 닫는다(`fsCall` 의 `done`, 실패하면 다시 그리지 않음)
- `fsCall` 과 `fsLinkSave` 는 저장하지 않은 변경이 있으면 먼저 묻는다(`fsAskSave`, 취소하면 보내지 않음)
- 연결 지우기(`fsClueDrop`)는 먼저 묻는다
- 본문에서 고른 문장을 거는 칸은 본문 부분 수정 도구(`passage.js` `#sel-tool`)의 mode 'foreshadow'
  - `fsLinkShow` · `fsLinkHtml`: 이미 있는 복선 찾기 · 이 화 가까이 나온 후보 `fsCandidates` / 새 복선
  - 고치는 본문은 메뉴에 '복선으로 걸기'
  - 반영한 화의 읽기 전용 본문은 `illust.js` 도구에 '복선으로 걸기'
  - 640px 이하 아래 시트
- 상태 승인 화면의 복선 문장 고르기(`fsClueRows`, `q` 항목)
- `fsBands` · `fsAt` · `fsMarks` · `fsFlag` · `fsTail` · `fsAttention` · `fsTodo` · `fsTocRows` · `fsFlow` · `fsAhead` · `fsTicks` · `fsCandidates` 는 순수 함수(`tests/test_foreshadow_js.py`)
- CSS 는 JS 에서 주입

### `canon/static/heatplan.js`

- 완급 계획 카드 `heatCard(p, arc)`: 단편은 기승전결 보드 위, 장편은 고른 아크의 보드 위. 다루는 범위와 저장 경로는 `heatHost` · `heatNowHost`(장편은 `S.selArc`)
- 완급 계획은 카드 없이 구역(`.sec.heat-card`)이다. 제안 `heatDraftCard` 만 카드다
- 계획이 없으면 '직접 적기'(`heatStart`)가 기승전결 구간으로 밑그림을 깐다(`heatDefaultFor`: 앞은 쌓기, 13화 이상이면 승 끝 낮은 정점, 전 끝 큰 정점, 결은 뒷날 · 쉬기)
- 'AI로 완급 계획 받기'(`heatPropose`, 작업 `heat`, 장편은 아크 번호)의 결과는 카드 안 제안 `heatDraftCard`(`S.heatDraft`)로 두고, 고르면(`heatDraftUse`) 넣는다
- 화마다 막대 하나(`heatBar`, 높이는 열 0~5, 터뜨리기는 amber). 쓴 화는 큐 긴장 평균을 가로 눈금으로 겹친다
- 막대를 누르면(`heatPick`) 눈금 · 몫 나눔 버튼(`heatLevel` · `heatRole`)과 정점 종류 · 한 줄 칸(`heat.<i>.kind` · `note`)을 편다
- 몫을 터뜨리기 밖으로 바꾸면 정점 종류를 지운다
- 경고 `heatWarnings`(범위마다 `heatScopes` · `heatScopeWarnings`) · 재기 `heatDensity` · `heatCueTension` 은 `heatplan.warnings` · `density` · `cue_tension` 과 같은 규칙(`tests/test_heatplan_js.py` · `test_heat_arcs.py`)
- 판돈 · 제약 · 관객 · 금지선 목록(`heatStakes`): 갈래 풀기 · 판돈 드러남(`heatKind` · `heatPublic`, 복선 고치기 API)
- 열린 단서 복선에 갈래 붙이기, 새로 심기(`heatAddStake`, 복선 더하기 API, 플롯이 있는 화에만)
- 뒤집힘 칸(`heat_turn.plant_ep` · `fail_ep` · `gain`)과 열 원칙 칸(`heat_rule`)
- 지우기 `heatClear`
- 구조 제안 미리보기 `heatProposalPart`(누를 수 없는 막대), 고르기 `heatApply`, 'AI로 구조 만들기 · 다시 제안'의 켜기 칸 `heatPlanToggle`(`settings.heat_plan`)
- 다음 아크 제안 카드도 완급 계획 미리보기를 붙이고, 다음 아크 기획 칸에 켜기 칸을 둔다

### `canon/static/illust.js`

- 집필 화면 삽화 프롬프트 카드(칸별 복사, 다시 조립, 외형 고정)
- '고른 부분으로 만들기'는 보조 버튼이다. 집필 화면의 주 버튼은 머리의 다음 일 하나다
- 서버에 ComfyUI를 이어 두면(`GET /api/comfy` 의 `on`, `S.comfy`) 카드 아래 줄에 'ComfyUI로 그리기' · '다시 그리기'(`illDraw`)를 둔다
- ComfyUI가 켜져 있으면 패널 제목에 'ComfyUI 연결됨', 삽화 설정에 워크플로 틀 이름과 체크포인트를 보인다. 틀과 주소는 서버 설정 파일의 `comfy_*` 칸에서 바꾼다고 알린다
- 만들기 버튼 아래 '만든 뒤 바로 ComfyUI로 그리기'(`#ill-draw`, `S.illDraw`)를 켜면 작업 `illust` 에 `draw` 를 보낸다. 보는 사람마다 localStorage `canon.illDraw` 에 기억한다
- 그리기는 화면을 막지 않는 작업 `illust_render`(대상은 삽화 id, 화는 `ep`)다. 끝나면 그 화를 받아 온다
- 그린 그림은 카드에 새것부터 가로로 늘어놓는다(`ilImages`). 그림을 누르면 새 탭에서 크게 보고, 그림마다 지우기(`illImgDelete`)가 있다
- 맨 새 그림의 알림과 ComfyUI에 보낸 프롬프트 · 틀 이름은 접어 둔다
- 삽화 프롬프트 만들기(`ilMake`, 고른 부분 · AI가 장면 고르기)는 화면을 막지 않는 작업 `illust` 다. 끝나면 그 화를 받아 오고, 그 화를 보고 있으면 새 삽화로 내려간다
- 카드의 인용 칸은 고른 부분, 없으면 AI 인용이다. 둘 다 비면(인용을 본문에서 못 찾음) 그리지 않는다
- 읽기 전용 본문에서 고르는 도구
- 도구 자리도 왼쪽을 0으로 두고 너비를 잰다(`passage.js` 의 `placeTool` 과 같은 규칙)
- 인물 화면 인물 카드의 삽화 외형 태그(`visualFields`)
- 외형 태그 AI 제안(`lookAI`)은 화면을 막지 않는 작업 `char_look`(대상 인물 id)이다. 그 인물의 외형 칸을 고치는 중이거나 시작한 뒤 고쳤으면 덮지 않고 알림의 '넣기'로 넣는다
- 고치는 본문의 도구 버튼은 `passage.js`

### `canon/static/lines.js`

- 이야기 줄기 화면(주소 `lines[/<줄기 id>]`, `viewLines`, 라우터가 부르는 `lineLoad`)
- 공용 목차 틀(`outline.js`, 목차 `lineToc`: 노선도 · 손볼 것 · 메인에서 갈라짐 · 본편 밖 · AI 제안) 위에 쪽 둘: 노선도 · 줄기 하나
- 노선도 쪽: SVG 노선도 `lineMapCard` → 손볼 것 `lineTodoCard` → AI 제안 `lineSuggestPanel`
- 노선도 줄 차례는 `lineOrder`: 범위 시작 차례, 갈라짐 · 합류가 없는 외전은 아래 '본편 밖'
- 다른 줄을 지나는 선은 흰 틈(`.lm-halo`)을 두고 지나간다
- 보이는 화 `S.lineRange`(플롯 있는 화 · 전체), 폭 `S.lineZoom`(맞춤 · 크게 28px)
- 칸 폭 560px 아래는 세로 노선도 `lineMapTall`
- 줄기 하나(`lineDetail`): 앞뒤만 크게 그린 노선도 `lineZoomMap`(한 화 44) → 줄기 내용 읽기 카드 `lineInfoCard`(고치기 `S.lineEdit`) → 붙은 화 `lineEpsCard`
- 화 붙이기는 붙은 화 카드의 메뉴: 붙이는 방식 `S.lineTagRole`, 가까운 화 후보 `lineCandidates`, 번호 칸
- 줄기 지우기 `lineDelete` 는 저장하지 않은 변경이 있으면 지우기 확인 뒤 저장하고 지울지 한 번 더 묻는다
- 쪽을 옮길 때 해시 대신 `history.replaceState`(`lineGoTo`)라 저장하지 않은 고침을 묻지 않는다
- `lineOrder` · `lineTodo` 는 순수 함수(`tests/test_lines_js.py`)
- CSS 는 JS 에서 주입(노선도 기본 모양 `.line-map` · `.lm-*` 은 app.css, 인물 화면 등장표도 쓴다)
- 플롯 편집기의 줄기 칸(`lineField`)과 화 카드 표시(`lineBadge`)도 여기 있다
- `storylines.span` · `tag` 와 같은 규칙이라 함께 고친다(`tests/test_lines_js.py`)

### `canon/static/offscreen.js`

- 화면 밖 근황 칸(`offscreenBox`): 다음 아크 기획 칸(`plot.js` `nextArcPanel`)의 'AI로 다음 아크 제안' 버튼 위
- 다음 아크가 `RETURN_GAP` 화 뒤에 시작하거나 저장한 근황 · 제안이 있을 때만 그린다. `RETURN_GAP` 은 `context.RETURN_GAP` 과 같다(`tests/test_offscreen.py`)
- 저장한 근황은 인물마다 시점 화와 지우기 버튼을 보인다
- 제안(`S.offscreenDraft`, 작업 `offscreen` 결과)은 인물마다 체크 · 종류 칩 · 고칠 칸. '고른 근황 저장'은 고른 인물의 빈 칸이 아닌 근황만 보낸다(`offscreenPicked`)
- 모양은 아는 정보 접기 칸(`.knows-fold` · `.change`)과 같다. 새 CSS 없음

### `canon/static/play.js`

- 플레이 화면(DESIGN.md 10.4, 시안 안 A)
- 작품 홈의 '이 세계로 플레이' 줄(`playHomeCard`)은 구역(`.sec`)이다. 플레이 사본의 '플레이로 돌아가기'는 보조 버튼이다(머리 주 버튼과 같은 일)
- 1100px 이하(한 열)에서 시계 줄(`.pclock`)은 위쪽 띠 아래에 붙는다. 높이 500px 이하(가로 휴대폰)에서는 붙이지 않는다
- 멈춘 상태 글은 손가락 기기에서 '▶를 누르면 다시' 다(`playKeys`)
- 손가락 기기(`pointer: coarse`)에서는 숫자 키 · Ctrl+Enter · 아무 키 안내를 숨긴다(`playKeys`)
- 새 플레이(`#/play/new[/세계]`, 출생 카드 · 새 세계)
- 플레이(`#/play/<폴더>`: 시간 흐름 막대, 흘러간 일, 결정 장면, 끼어들기, 옆 패널)
- 지난 일 · 되감기(`/past`, `<dialog>`)
- 생애 기록(`/life`)
- 작품 홈 카드(`playHomeCard`)
- `/play` 가 `null` 이면 작품 홈(`playHomeLoad`)은 플레이 사본이 아닌 것으로 둔다. 플레이 화면(`playLoad`)은 오류를 내고, 다시 묻기(`playRefresh`)는 실패와 같게 4초 뒤 다시 묻는다
- 시계 규칙은 DOM 없는 순수 함수(`playItems` · `playGap` · `playClockStart` · `playPhase` · `playTick` · `playClock`, `tests/test_play_js.py`)
- 서버는 `routes/play.py` 의 `/api/projects/{이름}/play…` 와 `/api/play/worlds`: 구간 작업 `play_turn`(남은 반영 → 장면 → 반영, 플레이 잠금 `_play_lock`, 다음 흐름 `_play_continue`)
- 배경 `play_sketch`
- 새 세계 `play_world`
- 앞 둘은 작업 목록에 넣지 않는다(`app.js` `QUIET_JOBS`)

### `canon/static/publish.js`

- 집필 화면 본문 띠의 분할 복사 버튼(`copySplit`: 복사 + ▾ 메뉴 `copyMenu` 의 줄바꿈 형식 · 제목 줄 · .txt)과 '여러 화 내보내기' 대화상자(`exportDialogHtml`)
- 640px 이하 집필 화면에서 복사 버튼은 아이콘(`COPY_ICON`)만 보이고, `copyMenu` 는 머리 ⋯ 메뉴에 '복사할 때 줄바꿈 형식'(`legend` 인자)으로 들어간다
- 텍스트와 HTML 을 함께 클립보드에 넣는다(보안 연결이 아니면 복사 이벤트로)
- 클립보드가 막히면 .txt 내려받기
- `exportAll`: 다음 할 일 '완결 원고 내보내기'(`home.js` `nextStep`)가 부른다. 범위를 본문이 있는 첫 화 ~ 마지막 화로 두고 형식 목록이 없으면 받아 같은 대화상자를 연다
- 집필 화면 밖(작품 홈)에서 연 '여러 화 내보내기' 대화상자는 형식을 '집필 화면의 복사 ▾ 메뉴'에서 바꾼다고 알린다

### `canon/static/setupchat.js`

- 설정 변경안을 읽는 도우미: 칸 이름 · 지금 값(`setupKeyValue`) · 부분 이름(`setupLabel`) · 관계 비교(`setupRelDiff`) · 새 인물 카드(`setupNewCard`). 대화 에이전트의 설정 카드(`agentsetup.js`)가 쓴다
- 옛 설정 대화(주제 `setup`)의 적용 취소 `setupChatUndo`. 대화 에이전트의 '이전 대화'(`chat.js` `chatReadOnlyCard`)에서 부른다
- 옛 설정 대화의 패널 · 보내기 · 변경안 카드 · 적용 · 방향 여러 안은 04e 에서 지웠다
- 칸 이름(`SETUP_KEYS`, `SETUP_CHAR_LABEL`)과 부분 id 는 `setupchat.KEY_LABELS` · `CHAR_LABELS` · `part_ids` 와 같다

### `canon/static/statwin.js`

- 상태창 수치 화면(공용 목차 틀 `outline.js`)
  - 주소 `statwin/<인물 id>` · `statwin/_frame` · `statwin/_decor`
  - 왼쪽 목차 `swToc`(작품 틀 · 처음 수치, 꾸미기, 비중별 인물, 상태창 없는 인물 접음, 스킬 도감)
  - 인물 쪽 `swPersonPage`: 머리 `swHead` · 지금 상태창 `swNowCard` · 본문에 넣을 상태창 `swTextCard` · 화별 변화 `swLogCard`
  - 지금 상태창은 읽기 먼저이고 '고치기'로 이 카드만 편다(`S.swEdit`, `swEditor`)
  - 고치기 칸에 저장하지 않은 항목이 있으면 `S.editDrafts.sw` 를 켠다(`swDraftMark`). 다른 인물 · 쪽 · 화면으로 가면 `app.js` 가 묻고, 버리면 칸을 닫는다
  - 고치는 칸 옆 계산 값 `swCalc`
  - 항목 고치기 · 순서 `swMove`
  - 틀 · 작품 틀
  - 복사
  - 화별 변화는 바뀐 화 목록(`swChangeParts`, 목록은 같은 이름끼리 짝지음) | 표
  - 작품 틀 · 처음 수치 쪽 `swFramePage`: 작품 틀 · 인물별 처음 수치 표 `swInitCard` · AI 처음 수치 제안
  - 꾸미기 안 · 처음 수치 AI 제안(`swSuggest` · `swInitAI`)은 화면을 막지 않는 작업 `statwin_suggest` · `statwin_init` 이다. 결과는 제안 카드(`S.swSug` · `S.swInitSug`)에만 놓는다
  - 1화 반영 뒤 잠금 `swLocked`, 잠긴 표는 0화 기록의 시작 값 `swStartValues`
  - 틀 `SW_PRESETS` 는 `statwin.PRESETS` 와 같음
  - 꾸미기 쪽 `swDecorPage`: 창 이름 · 본문 서식(읽기 카드) · 화면 스킨 `SW_SKINS` · AI 안 고르기와 적용 취소
- 상태창 칸 모양 `swStatsBody`(카드 칸 | 작품 스킨 창, 칩은 `abChip`)는 인물 화면 `cast.js` `castSheetStats` 와 함께 쓴다
- 상태 승인 화면의 상태창 줄(`swDeltaRows`)
- `swResolve` 는 `statwin.resolve` 와 같은 규칙(`tests/test_statwin_js.py` 가 node 로 맞춰 본다)

### `canon/static/timeline.js`

- 작품 속 시간 화면(`viewTimeline`)
- 칸 폭 560px 이하 열흘 띠는 열흘을 모두 두고 옆으로 밀어 본다(칸 64px 이상)
- 공용 목차 틀(`outline.js`, 목차 `tlTocHtml`: 지금 · 기한 · 시간 흐름 묶음 · 설정, 스크롤로 `S.tlCur`)
- 지금 `tlNowCard`: 마지막 반영 화 끝 시점과 앞으로 열흘 띠
- 기한 `tlDlCard`: 나눔 버튼 `S.tlDlTab`, 줄마다 ⋯ 메뉴, 지난 기한은 닫기 · 날 바꾸기
- 기한 칸에 적던 값은 `S.tlDraft` 에 두어 다시 그려도 남는다
- 기한 칸에 저장하지 않은 글이 있으면 `S.editDrafts.tl` 을 켠다(`tlDraftMark`)
- 기한 칸은 서버가 받은 뒤에만 닫는다(`tlPut` 의 `form`, 실패하면 다시 그리지 않음)
- 다른 기한의 닫기 · 다시 열기는 열린 기한 칸을 닫지 않는다
- 기한 저장(`tlPut`)과 지우기는 저장하지 않은 변경이 있으면 먼저 묻는다(`tlAskSave`, 취소하면 보내지 않음)
- 시간 흐름 `tlGroupCard`: 아크 · 기승전결 구간마다 읽기 카드, 고치기 `S.tlEditGroup`, 접기 `S.tlFold`
- 설정 `tlSetCard`: 읽기 카드, 고치기 `S.tlSetEdit`
- `tlGroups` · `tlDeadlineRows` · `tlShort` 는 순수 함수(`tests/test_timeline_js.py`)
- CSS 는 JS 에서 주입

### `canon/static/tofix.js`

- 고칠 곳 화면(사이드바 도구, 주소 `tofix`, `viewToFix`: 남음 · 고침 · 모두, 메모 고치기, 본문에서 고치기 `tofixGo`)
- 고칠 곳 화면은 공용 목차 틀이다(화별 목차 `tofixToc`, 화마다 카드 한 장)
- 거르기는 머리의 나눔 버튼(Seg)이다
- 줄은 앞뒤 문맥과 함께 보인다(`tofixContext`)
- 메모는 읽는 글이고 ⋯ '메모 고치기'로 그 줄만 칸을 편다(`S.tofixEdit`, Ctrl+Enter 저장 · Esc 취소)
- 고치던 메모는 `S.tofixEdit.note` 에 두어 다시 그려도 남는다
- 고치던 메모가 원래 메모와 다르면 `S.editDrafts.tofix` 를 켠다(`tofixDraftMark`)
- 지우기(`tofixDelete`)는 메모가 없어도 먼저 묻는다
- 본문 도구의 '나중에 고치기'와 메모 칸(`showTool` 을 감싼다, mode `tofix`)
- 본문 띠의 '고칠 곳 N' 버튼(`tofixBtn`)은 640px 이하에서 깃발 아이콘(`TOFIX_ICON`)과 수만 보인다
- 밑줄(`tofixRanges` 를 `marks.js` `allRanges` 가 함께 그림)
- 집필 화면 본문 띠의 '고칠 곳 N'(`tofixBtn`, `tofixNext`)
- 서버 응답은 to_fix 만 가져온다(`takeToFix`)
- `tofixSpot` · `tofixList` 는 `tofix.spot` · `collect` 와 같은 규칙(`tests/test_tofix_js.py`)

### `canon/statwin.py`

- 상태창 수치
- 인물의 수치(`CharacterState.stats`)가 하나라도 있으면 켜짐
- 바뀐 항목만 합치기(`merge`, `+3` · 단위 붙은 돈 `+300` · 한도 붙은 수 `4.3/60L` + `-0.7` · 목록 `+독 내성` / `-은신` 계산은 `resolve`)
- 기록(`Project.stat_log`, 목록은 더한 것 · 뺀 것 `diff`)
- 작가 수정(`set_stats`)
- 화별 비교표
- 본문 상태창 글(`render`, 서식 `Project.stat_window`)
- 본문 상태창 읽기 · 대조(`read_windows`, `window_warnings`: 반영하면 될 값 `after_delta` 와 다르면 변경안 정리 `pipeline.clean_delta` 가 경고로)
- 0 아래 · 한도 위 경고(`out_of_range`, `range_warnings`)
- 두 경고는 (글, 인물 id) 로 돌려준다(`features.clean` 이 `StateDelta.warn_to` 에 넣는다)
- 처음 수치 AI 제안 정리(`clean_init`, AI 호출은 `pipeline.suggest_initial_stats`, 1화 반영 뒤에는 막음, 프롬프트 `prompts.stat_init_prompt`)
- 꾸미기(AI 안 정리 `clean_options`, 화면 스킨 `SKINS`, 창 이름 · 작품 틀은 `StatWindow.title` · `names`, AI 호출은 `pipeline.suggest_stat_window`, 프롬프트 `prompts.stat_window_prompt`)
- 프롬프트 규칙
  - `write_rule(p, n)`: 넣는 방식 `Project.stat_window.prompt` 가 json 이면 지금처럼
  - `write_rule` 은 lines 면 이번 화 인물(`episode_cast`)의 수치 줄과 도감 줄을 예산 `context.BUDGET['stat_lines']` 까지 넣는 `lines_block`(서식 예시는 플롯에 상태창 장면이 있을 때만 `wants_window`)
  - `write_rule(budget=)` · `lines_block(budget=)` 은 도감 줄 예산을 받는다. 본문 쓰기 요청이 작품 예산(`context.budget`)을 넘긴다
  - `write_rule(trace=)` · `lines_block(trace=)` 는 예산으로 뺀 도감 줄을 보기의 'instructions' 블록에 적는다
  - `write_rule` 은 none 이면 빈 글
  - 쓰기 컨텍스트의 인물 상태는 `prompts.write_states` 가 lines · none 에서 stats 를 뺀다
  - `state_rule`
  - 검수 `check_rule`: 직전 화 수치와 대조
  - 인벤토리 항목이 있으면 꺼내 쓰는 물건과 지금 차림 나누기 `inventory`
- 명령줄 `statwin`
- LLM 호출 없음

### `canon/storylines.py`

- 이야기 줄기
- 메인에서 갈라졌다 합류하는 서브플롯 · 과거 회상 · 외전 · 인물 이야기(`Storyline`)
- 화의 줄기는 `EpisodePlot.storyline`(주로 따라가는 줄기, 비면 메인)과 `threads`(끼어드는 장면)
- 범위(`span`)
- 프롬프트 블록(`plan_block`, `episode_block`, `state_rule`)
- 장편 프롬프트는 줄기마다 붙은 화를 최근 `EPS_KEEP`(10)개만 적고 앞 화는 수와 첫 화로 줄인다
- 장편 기획 블록(`plan_block`)이 `context.BUDGET["storylines"]` 를 넘으면 합류가 끝난 줄기를 합류가 이른 것부터 빼고 뺀 수를 적는다. 단편은 그대로다
- 명령줄 노선도(`ascii_map`)
- LLM 호출 없음
- 제안과 반영은 `pipeline.suggest_storyline` / `apply_storyline`

### `canon/timeline.py`

- 작품 속 시간
- 화가 끝난 시점(`Episode.time`, `StoryTime`: 날수 · 시간대 · 날짜)
- 플롯의 시점(`EpisodePlot.time`)
- 기한(`Timeline.deadlines`, `Deadline`)과 남은 날(`left`)
- 기한 예산(`deadline_lines`)은 오늘에서 가까운 기한(지났든 남았든)부터 넣는다. 줄 차례는 지난 기한 → 가까운 기한 그대로다
- 쓰기 블록 `episode_block(budget=)` 은 기한 예산을 `deadline_lines` 에 넘긴다. 쓰기 가족만 작품 예산(`context.budget`)을 넘긴다
- `deadline_lines(trace=, block=)` 는 예산으로 뺀 기한을 보기의 그 블록('time' 또는 'board')에 적는다. `episode_block(trace=)` 는 'time' 으로 넘긴다
- 그래서 오래 지나 닫히지 않은 기한이 쌓여도 다가오는 기한이 프롬프트에서 빠지지 않는다
- 상태 변경안 정리 · 반영 · 되돌리기(`clean_delta`, `apply_delta`, `revert`, 기한은 `Snapshot.deadlines`)
- 작가가 기한 고치기(`upsert`, `remove`)
- 프롬프트 블록(쓰기 · 검수 `episode_block`, 요약 줄 `tag`, 기획 `plan_block`, 상태 `state_block` · `state_rule`, 검수 `check_rule`, 기한은 `context.BUDGET["deadlines"]`)
- 날짜 · 요일 계산(1일째 날짜 `Timeline.start_date` 가 있으면 날짜로 보임 `dated`, `calendar`, `day_label`, `when`, 본문 날짜 → 날수 `day_from_text`, 쓰기 블록의 요일 셈 `weekday_hint`. 저장은 날수)
- 기록이 없거나 꺼지면 블록이 빈다
- 명령줄 `time`
- LLM 호출 없음
- 화면은 `static/timeline.js` (`tlLeft` · `tlDay` · `tlCalendar` · `tlDayLabel` · `tlWhen` · `tlISO` · `tlDayOf` 는 `left` · `current_day` · `calendar` · `day_label` · `when` · `date_of` 와 같은 규칙, `tests/test_timeline_js.py`)

### `canon/tofix.py`

- 고칠 곳
- 작가가 본문 글에 단 '나중에 고칠 곳' 표시와 메모(`Episode.to_fix`, `ToFix`, 상태 open · done)
- 글 찾기(`spot`, 담을 때 자리에 가까운 것)
- 달기(`add`, 저장된 본문에 있는 글만 · 같은 자리면 메모만 바꿈) · 고치기(`update`) · 지우기(`remove`)
- 모으기(`collect`)
- 본문을 바꾸지 않아 웹 `…/tofix` 는 자동 집필 중에도 받는다(작품 잠금 안에서 `_edit`)
- 화면의 작품 전체 저장(`_save`)은 디스크 표시를 지킨다
- 프롬프트에 넣지 않는다
- 명령줄 `tofix`
- 명령줄 `tofix` 도 `jobs.project_lock` 안에서 다시 읽고 고쳐 저장한다. 웹 서버의 자동 집필이 도는 동안 달아도 서로 덮지 않는다
- LLM 호출 없음
