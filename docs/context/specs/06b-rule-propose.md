# 06b. 대화 에이전트의 정규식 규칙 제안 (작가가 적용)

상태: 진행 (claude/rule-propose, #459) · 계획: [plan.md](../plan.md) 의 6b번 · 먼저: 6

## 목표

작가가 대화 패널에서 "말줄임표를 하나로 맞추는 규칙 만들어 줘"처럼 말하면 에이전트가 정규식 규칙 하나를 제안한다.
제안은 승인 카드로 오고, 작가가 적용해야 규칙 묶음에 들어간다.
카드는 규칙 칸과 지금 본문에 걸어 본 결과를 보인다.
적용한 제안은 대화 패널의 '바뀐 것'에서 되돌릴 수 있다.
이 일감이 따르는 정한 규칙은 [README.md](../README.md) 의 2026-11-08 결정 Q12 · Q21 · Q29 · Q33 이다.
Q29: 대화 에이전트는 정규식 규칙을 제안만 하고 작가가 적용한다.
Q33: 정규식 규칙 제안은 6 뒤의 조각 6b 가 맡는다.
06 의 정할 것 12 (2026-11-08 정함): 6b 는 07 의 정할 것 9 와 같은 꼴로 만든다(`propose_rule` 도구, 쓰기 종류 `rule` 은 늘 'ask').
07 의 정할 것 9 는 기존 단계 `chat` 을 쓰고 새 `get_llm` 단계를 두지 않는다.
아래 정할 것 1 · 2 는 06 의 정할 것 12 가 정한 도구 이름과 길을 바꾼다.
선행 일감 6 은 머지됐다(`e742acde`, #446).

## 정할 것

시작 전에 사용자와 정할 것이다.
추천안을 먼저 쓴다.
앞 질문의 답이 뒤 질문의 전제가 되도록 차례를 두었다.
2026-11-09: 1~18 을 모두 추천안대로 정했다(사용자 결정). 정할 것 1 의 하위 결정은 안 1 이다.

1. 도구 이름이 07 의 `propose_rule` 과 겹친다 — 정함(2026-11-09, 추천안): 6b 는 `propose_regex`, 07 은 `propose_rule` 을 그대로 쓴다. 쓰기 종류는 둘 다 `rule` 이다.
   - 07 의 정할 것 9 도 `propose_rule` 을 쓴다(`docs/context/specs/07-rules.md`).
   - 07 은 06 과 이름을 나누는 원칙을 이미 적었다(07 의 '바꿀 곳' 아래 줄: `RuleChange` 와 `StateRule`, `rules` 와 `staterules`).
   - `canon/agent.py` 의 `CARD_TOOLS` 는 도구 이름 하나에 모듈 하나를 둔다(`{m.TOOL: m ...}`). 두 도구가 저장소(전역 `.rules/` 와 `Project.state_rules`)와 카드 모양이 달라 모듈을 나누는 편이 맞다.
   - 06 의 정할 것 12 의 도구 이름 `propose_rule` 을 바꾸므로, 이 안을 고르면 06 의 그 줄도 고친다.
   - 쓰기 종류 `rule` 은 06 의 정할 것 12 가 정한 이름이라 바꾸지 않는다.
   - 두 모듈이 같은 `KIND` 를 써서 `agent.ALWAYS_ASK` 에 `rule` 이 두 번 들어도 동작은 같다. `ALWAYS_ASK` 는 `in` 과 `set` 으로만 쓴다(`agent.decide_kind` · `agent.decide`).
   - 07 이 `CARD_TOOLS` 꼴을 따를지는 07 쪽에서 정한다.
   - 하위 결정 — 쓰기 종류의 이름표: `agent.KIND_LABELS` 와 `static/agent.js` 의 `AGENT_KINDS` 는 종류 하나에 이름표 하나를 둔다.
   - 카드 머리는 `AGENT_KINDS[k]` 를 보이므로(`agent.js` 의 `agentApproval`) 07 의 선언형 규칙 카드에도 같은 이름표가 나온다.
   - 추천(안 1): 종류 이름을 `rule` 하나로 두고 이름표를 두 도구에 맞는 '규칙'으로 짓는다.
   - 안 2: 종류를 `regex` 와 `rule` 로 나눈다. 고르면 06 의 정할 것 12 의 '쓰기 종류 `rule`' 문구를 함께 고친다.
   - 다른 안: 도구 하나 `propose_rule` 에 인자 `kind`(regex · state)를 둔다. 한 모듈이 두 저장소와 두 카드를 다뤄야 하고, 6b 와 07 이 같은 파일을 고치게 된다.
2. 도구의 꼴 — 정함(2026-11-09, 추천안): 늘 카드로 묻는 도구 모듈(`CARD_TOOLS`) 꼴로 새 파일 `canon/agent_regex.py` 를 둔다. 작가가 카드에 답하면 턴을 끝낸다.
   - 07 의 정할 것 9 는 '`renumber` 의 길'을 적었다. 그 뒤 04b~04d 에서 늘 묻는 도구는 `CARD_TOOLS` 모듈 꼴이 되었다(`canon/agent_text.py` 모듈 머리글의 훅 이름).
   - 06 의 정할 것 12 는 07 의 정할 것 9 의 길을 따르게 정했다. 이 안을 고르면 06 의 그 줄도 고친다.
   - `CARD_TOOLS` 에 등록하면 그 `KIND` 가 저절로 `agent.ALWAYS_ASK` 에 든다(`canon/agent.py` 의 `ALWAYS_ASK`).
   - `agent.decide` 는 `CARD_TOOLS` 카드를 그 모듈의 `decide` 에 넘기고 턴을 이어 돌리지 않는다(`canon/agent.py` 의 `decide`).
   - `renumber` 꼴은 승인 뒤 같은 턴을 이어 돌린다(`agent.resume`). 규칙 하나를 넣은 뒤 AI 가 더 할 일이 없으므로 이어 돌릴 까닭이 없다.
   - 다른 안: `RENUMBER_TOOLS` 처럼 `agent._step` 에 갈래를 더한다. `agent.decide` · `agent.undo` 에도 갈래가 늘어난다.
3. 규칙 글(in · out)을 누가 만드는가 — 정함(2026-11-09, 추천안): 에이전트 단계(`PlotAgentStep`)가 도구 인자로 바로 채운다. `prepare` 는 AI 를 부르지 않는다.
   - 그러면 LLM 호출은 에이전트의 기존 단계 호출(`web._run_agent` 의 `get_llm("chat")`) 하나뿐이다. 06 의 정할 것 12 · 07 의 정할 것 9 와 맞는다.
   - [README.md](../README.md) 의 'LLM 호출과 시험'은 규칙 제안을 '새 LLM 호출'이라 적었다. 이 안을 고르면 그 줄을 '기존 `chat` 호출 안의 도구'로 고친다.
   - 다른 안: `edit_setup` · `edit_style` 처럼 `prepare` 가 따로 AI 를 부른다(`canon/agent_style.py` 의 `prepare`, 단계 `plan`). 새 응답 형식과 가짜 응답이 늘고, Q33 의 '새 단계 없음'과 견줘 다시 정해야 한다.
4. 인자와 응답 형식 — 정함(2026-11-09, 추천안): 새 응답 형식을 두지 않고 `PlotAgentStep.args`(`list[ToolArg]`, 이름 · 값 모두 글)로 받는다.
   - 인자: `bundle`(묶음 id, 비우면 정할 것 6 의 규칙), `rule`(고칠 규칙 id, 비우면 새 규칙), `comment`, `in`, `out`, `action`, `type`, `flag`, `enabled`.
   - 고치기에서 비운 인자는 지금 규칙 값을 그대로 둔다.
   - 새 규칙에서 비운 인자는 `schema.RegexRule` 의 기본값(`action="warn"`, `type="output"`, `flag="g"`)을 쓴다.
   - `RegexRule` 은 'LLM 이 채우지 않는다'고 적힌 모델이고 `in_` 에 별칭 `in` 이 있다(`canon/schema.py` 의 `RegexRule`). 응답 형식에 넣지 않으므로 별칭이 구조화 출력 스키마에 어떻게 나가는지 따질 일이 없다.
   - 글 인자라 dict 칸이 생기지 않는다(`tests/test_schema_nodict.py`).
   - 다른 안: `PlotAgentStep` 에 새 칸(규칙 모양 모델)을 더한다. 모든 단계 응답이 그 칸을 싣고, `id` · `enabled` 를 `SkipJsonSchema` 로 빼야 한다.
5. 제안 하나가 담을 수 있는 것 — 정함(2026-11-09, 추천안): 도구 한 번에 규칙 하나를 더하거나 고친다. 규칙 지우기는 하지 않는다.
   - 규칙 끄기는 `enabled` 를 `false` 로 고치는 고치기로 한다. 되돌릴 수 있고 기록 · 지적의 규칙 id 가 그대로 남는다.
   - 규칙 지우기와 묶음 지우기는 작가가 규칙 묶음 화면(`#/rules`)에서 한다. `regexrules.delete` 는 파일을 지우므로 되돌릴 수 없다(`canon/regexrules.py` 의 `delete`).
   - 새 묶음은 정할 것 6 의 경우에만 만든다.
   - 여러 규칙을 한 카드에 담지 않는다. 카드 하나에 시험 결과 하나를 보여야 작가가 판단하기 쉽다.
   - 다른 안: 인자를 `|` 로 나눠 규칙 여럿을 한 카드에 담는다(`insert_episodes` 의 `titles` 꼴). 카드와 되돌리기가 규칙마다 부분(`keys`)을 가져야 한다.
6. 새 규칙을 넣을 묶음 — 정함(2026-11-09, 추천안): 이 작품이 켠 묶음 가운데서만 고른다.
   - `bundle` 인자가 있으면 그 묶음이다. 이 작품의 `Settings.rule_bundles` 에 없거나 찾을 수 없는 id 면 막고 까닭을 AI 에게 돌려준다.
   - `bundle` 이 비고 켠 묶음(`regexrules.bundles_of(p)`)이 하나면 그 묶음이다.
   - `bundle` 이 비고 켠 묶음이 둘 이상이면 막고 묶음 이름 목록을 AI 에게 돌려준다. AI 는 고르거나 작가에게 묻는다(`ask`).
   - 켠 묶음이 없으면 새 묶음을 만든다. 이름은 '<작품 제목> 규칙'이다.
   - 고치기는 그 규칙이 든 묶음이다. 규칙 id 가 켠 묶음 어디에도 없으면 막는다.
   - 카드에서 묶음을 바꾸는 고르기는 두지 않는다. 바꾸려면 작가가 대화로 말한다(새 턴을 보내면 기다리던 카드는 `denied` 가 된다, `agent.add_turn`).
   - 다른 안: 카드에 '새 묶음에 넣기' 고르기를 둔다. 카드 화면과 `decide` 의 `picked` 뜻이 늘어난다.
7. 다른 작품도 켠 묶음을 고쳐도 되는가 — 정함(2026-11-09, 추천안): 된다. 카드에 그 묶음을 켠 다른 작품 수를 보인다.
   - 묶음은 전역이고 고치면 켠 작품 모두에 바로 걸린다(Q21, `canon/regexrules.py` 모듈 머리글).
   - 작가가 카드에서 적용해야 들어가므로 작가가 규칙 화면에서 고치는 것과 같은 권한이다(Q29).
   - 켠 작품은 `regexrules.used_by(bid)` 로 찾는다. 카드는 '다른 작품 N개에도 걸려요'를 보인다.
   - `used_by` 는 디스크의 모든 `project.json` 을 읽어 작품 폴더 이름을 돌려주므로 이 작품도 든다. N 은 그 목록에서 이 작품(폴더 이름 `name`)을 뺀 수다.
   - 다른 안: 이 작품만 켠 묶음(`used_by` 가 이 작품 하나)만 고치고, 나머지는 새 묶음을 만든다. 같은 뜻의 묶음이 작품마다 늘어난다.
8. 작품에서 묶음 켜기 — 정함(2026-11-09, 추천안): 정할 것 6 으로 새로 만든 묶음만 적용할 때 이 작품의 `Settings.rule_bundles` 끝에 켠다. 이미 있는 묶음을 켜거나 끄지 않는다.
   - 켜지 않으면 새 묶음의 규칙이 이 작품에 걸리지 않아 제안이 쓸모없다.
   - 06 의 '대화 에이전트' 줄은 에이전트가 `Settings.rule_bundles` 를 어느 모드에서도 고치지 않는다고 적었다. 작가가 카드로 적용한 경우만 예외로 고친다.
   - 이미 있는 묶음 켜기 · 끄기 · 차례 바꾸기는 지금처럼 설정 화면(`static/settings.js` 의 `setRulesSave`)과 명령줄 `rules use` · `rules drop` 이 한다.
   - 다른 안: 새 묶음도 켜지 않고, 카드에 '설정에서 켜세요'를 보인다.
9. 에이전트가 제안할 수 있는 동작 — 정함(2026-11-09, 추천안): `regexrules.validate` 가 받는 조합을 모두 받는다(output · warn, output · fix, export · fix).
   - `action` 을 비우면 `warn` 이다. 새 규칙이 적용하자마자 본문을 바꾸지 않게 하려는 06 의 기본값 취지와 같다.
   - fix 규칙 카드는 '적용하면 다음에 본문을 쓸 때부터 본문을 바꿔요'를 보인다.
   - export 규칙 카드는 '내보낼 때만 걸려요'를 보인다.
   - export · warn 은 `validate` 가 막는다.
   - 다른 안: warn 만 받는다. 말줄임표 통일 같은 06 의 대표 예(고침)를 대화로 만들 수 없다.
10. 카드를 띄우기 전 검사 — 정함(2026-11-09, 추천안): `prepare` 가 규칙 하나를 `regexrules.validate` 로, 넣은 뒤 묶음 전체를 `regexrules.check` 로 검사한다. 오류가 있으면 카드를 띄우지 않는다.
   - 막히면 `record` 가 `StepRecord(kind="block")` 를 남기고 까닭을 `why` 에 적고 오류 문구를 `result` 로 AI 에게 돌려준다. AI 는 같은 턴에서 고쳐 다시 부를 수 있다(`agent_style.record` 가 막혔을 때 `""` 를 돌려주는 꼴).
   - 다시 부르기는 `agent.MAX_STEPS` 안에서만 돈다.
   - 저장을 막지 않는 알림(`regexrules.notices`, 예: fix 규칙의 `out` 에 든 `{{…}}`)은 카드에 보인다.
   - `in` 이 빈 규칙은 `validate` 가 통과시키지만 걸리지 않으므로 막는다.
   - 끄기만 하는 카드(`regexrules.switched_off`: `enabled` 말고 바뀐 칸이 없음)는 그 규칙을 `validate` · `check` 하지 않는다(2026-11-09 리뷰).
   - 까닭: `_nested` 처럼 검사가 생기기 전에 저장한 옛 규칙은 지금 검사에 걸린다. 검사하면 그 규칙을 끄는 카드도 막힌다.
   - 같은 까닭으로 `regexrules.set_rule` 도 저장한 규칙을 끄기만 하면 그 규칙을 `check` 에서 건너뛴다. 다시 켜는 되돌리기는 검사에 걸려 `kept` 로 남는다.
   - 다른 안: 검사하지 않고 카드에 오류를 보인다. 적용할 수 없는 카드가 생긴다.
11. 카드의 시험 결과 — 정함(2026-11-09, 추천안): `prepare` 가 제안한 규칙 하나만 `regexrules.trial([rule], text)` 로 걸어 본다. 시간이 넘으면 카드를 띄우지 않는다.
   - 본문은 이 차례로 고른다: 세션 대상이 본문(`text:N`)이면 그 화, 아니면 턴이 실어 온 화(`AgentTurn.episode`)에 본문이 있으면 그 화, 아니면 본문이 있는 가장 뒤 화.
   - 대상은 `pipeline.chat_focus(p, s.target)` 로 푼다(`agent_text._focus_ep` 와 같은 길).
   - 본문이 있는 화가 없으면 시험 없이 카드를 띄우고 '시험할 본문이 없어요'를 보인다.
   - 규칙 하나만 거는 까닭: 카드가 보이는 바뀐 곳 · 걸린 곳이 이 규칙 때문인지 바로 보이게 하려는 것이다.
   - `trial` 은 저장하지 않고 자식 프로세스에서 돈다(`canon/regexrules.py` 의 `trial` · `_call`). `prepare` 는 작품 잠금 밖에서 돌므로 잠금을 오래 잡지 않는다.
   - 시간이 넘으면 막는다. 지금 `trial` 의 `skipped` 는 고침 규칙을 걸 때(`_apply`)만 채워진다.
   - 경고 규칙은 `_issues(..., strict=False)` 라 시간이 넘어도 빈 목록만 돌려주고 `skipped` 는 `""` 다(`regexrules._issues`).
   - 내보내기 규칙은 `_apply(...)[0]` 만 써서 건너뜀을 버린다(`regexrules.trial`).
   - 그래서 `trial` 에 `strict` 인자를 더해 세 경로(고침 · 경고 · 내보내기)의 건너뜀을 모두 `skipped` 에 담는다. `prepare` 는 그 값으로 막는다.
   - 느린 규칙을 넣으면 걸 때마다 그 작품이 켠 모든 묶음의 같은 종류 규칙이 건너뛰어진다. 그 묶음을 켠 다른 작품도 같다(`regexrules.run` · `hits` 가 켠 묶음 전체를 `_call` 한 번으로 건다).
   - 끄기 카드(`enabled=false`)는 `_pick` 이 켠 규칙만 골라 결과가 늘 0 이다. 그래서 끄기는 적용 전 규칙(`before`)을 걸어 '적용하면 더 걸리지 않을 곳'으로 보인다.
   - 끄기 카드는 그 시험이 시간 한도를 넘어도 막지 않는다(2026-11-09 리뷰). 끄면 그 규칙은 더 걸리지 않으므로 위의 '느린 규칙을 넣으면' 까닭이 없다.
   - 그때 카드에 `timed_out` 을 남기고 바뀐 곳 · 걸린 곳은 비운다.
   - 그 밖의 고치기는 적용 뒤 규칙만 건다.
   - 카드에 남기는 바뀐 곳 · 걸린 곳은 각 10개까지다. 시작 값이고 카드 높이를 보고 다시 정한다. 전체 수는 따로 적는다.
   - 다른 안: 묶음 전체에 새 규칙을 더해 건다(`trial(기존 rules + [rule], text, bid, name)`). 다른 규칙의 결과가 섞인다.
12. 적용하면 이미 쓴 화에 다시 거는가 — 정함(2026-11-09, 추천안): 다시 걸지 않는다. 06 그대로다.
   - 고침 규칙은 본문을 만드는 입구들(`pipeline.apply_rules`, `reshape.propose_rework` 의 고쳐 쓰기, `pipeline.revise_passage(rules=True)`)에서 `regexrules.run` 으로 건다. 묶음을 고쳐도 이미 저장한 본문에 다시 거는 코드는 없다.
   - 경고 규칙은 검수할 때마다 지금 본문에서 찾으므로(`regexrules.hits`) 다음 검수부터 이미 쓴 화에도 걸린다.
   - 카드와 적용 뒤 단계 줄이 이 차이를 적는다.
   - 다른 안: 적용할 때 켠 작품의 모든 화에 다시 건다. 작가가 보지 않은 본문 수정이 여러 작품에 생긴다.
13. 적용한 제안의 되돌리기 — 정함(2026-11-09, 추천안): `WriteRecord` 에 규칙 하나의 적용 전 · 뒤 값을 남기고, 지금 규칙이 적용 뒤 값과 같을 때만 그 규칙 하나를 돌린다.
   - 남기는 값: 묶음 id, 규칙 id, 적용 전 규칙(새 규칙이면 없음), 적용 뒤 규칙, 새로 만든 묶음인지.
   - 새 규칙 되돌리기는 그 규칙을 묶음에서 뺀다. 고치기 되돌리기는 적용 전 규칙으로 바꾼다.
   - 묶음의 다른 규칙은 건드리지 않는다. 묶음 전체를 적용 전 목록으로 돌리면 그 뒤 작가가 고친 다른 규칙이 사라진다.
   - 지금 규칙이 적용 뒤 값과 다르면 `kept` 로 남긴다. 까닭은 '그 뒤에 다시 고친 규칙이라 그대로 뒀어요'다(`agent_style.KEPT` 꼴).
   - 묶음을 지웠거나 규칙이 없으면 `kept` 로 남긴다.
   - 새로 만든 묶음의 되돌리기는 이 작품의 `Settings.rule_bundles` 에서 끄고, 묶음에 그 규칙만 남아 있고 다른 작품이 켜지 않았으면 묶음 파일도 지운다. 아니면 묶음은 남긴다.
   - 되돌리기도 묶음에 새 버전을 남긴다(`regexrules.save` 의 `_snapshot`). 메모는 '대화 에이전트 제안 되돌림'이다.
   - `regexrules.restore(bid, number)` 는 쓰지 않는다. 버전은 `VERSION_KEEP` = 30 개만 남고 묶음 전체를 돌린다.
   - 오래된 턴(`agent.UNDO_TURNS` = 20)의 전 · 뒤 값은 `compact` 가 지우고 남은 부분을 `kept` 로 둔다(`agent_style.compact` 꼴).
   - 다른 안: 적용 직후 버전 번호를 남기고 `restore` 로 돌린다. 그 뒤 다른 규칙을 고쳤으면 그것까지 사라지거나 되돌리기를 못 한다.
14. 규칙 화면과 동시에 고칠 때 — 정함(2026-11-09, 추천안): `decide` 가 적용하는 순간 묶음을 다시 읽어 그 위에 규칙 하나를 넣는다. 고치기 대상 규칙이 카드를 만든 뒤 바뀌었으면 막는다. 규칙 화면의 저장에는 버전 검사를 더하지 않는다.
   - 막을 때는 `ValueError`('그 사이 규칙이 바뀌었어요. 다시 요청해 주세요')를 내고 카드는 그대로 둔다(`agent_style.decide` 와 같은 길, 웹은 400).
   - `decide` 는 그 묶음이 아직 `p.settings.rule_bundles` 에 있는지도 다시 본다. 없으면 '이 작품에서 그 묶음을 껐어요'로 막고 카드를 둔다.
   - 설정 화면(`routes/regexrules.py` 의 `put_rule_bundles`)으로 끄면 묶음 파일은 남아 `regexrules.exists` 검사를 통과하므로 이 검사가 따로 필요하다.
   - 규칙 저장소는 파일을 잠그지 않고 `update` 가 읽기 → 고치기 → 저장 사이에 잠금이 없다(`canon/regexrules.py` 의 `update`). 파일은 `store.write_atomic` 이라 깨지지 않는다.
   - 규칙 화면은 묶음 전체를 PUT 하나로 보낸다(`routes/regexrules.py` 의 `put_rules`). 화면이 옛 사본을 저장하면 에이전트가 넣은 규칙이 사라질 수 있다.
   - 그때 되돌리기는 규칙을 찾지 못해 `kept` 로 남는다. 잃는 것은 제안 하나이고 작가가 다시 요청할 수 있다.
   - 다른 안: `RuleBundleIn` 에 `version` 을 더하고 다르면 409 로 막는다. 규칙 화면(`static/regexrules.js`)도 고쳐야 해서 6b 밖의 일이 커진다. 써 본 뒤 필요하면 장기 후보로 둔다.
15. 에이전트가 기존 규칙을 보는 길 — 정함(2026-11-09, 추천안): 새 읽기 도구 `read_rules` 를 둔다. 매 단계 프롬프트에 규칙 블록을 넣지 않는다.
   - `read_rules`(args 없음)는 이 작품이 켠 묶음마다 id · 이름 · 켠 작품 수와 규칙마다 id · `comment` · `in` · `out` · `action` · `type` · `enabled` 를 돌려준다.
   - 결과는 다른 읽기 도구처럼 `agent.RESULT_LIMIT` = 2,500자에서 자른다(`agent._cut`).
   - 이 작품이 켜지 않은 묶음은 보이지 않는다(정할 것 6).
   - `docs/modules/core.md` 의 `canon/regexrules.py` 절은 '에이전트는 규칙 묶음을 읽지도 쓰지도 않는다'고 적었다. 이 안을 고르면 그 줄을 고친다.
   - 다른 안: `agent_plot_prompt` 에 켠 묶음 이름과 규칙 수 한 줄을 늘 넣는다. 규칙과 관계없는 턴에도 프롬프트가 커진다.
16. 어느 화면 · 대상에서 부르는가 — 정함(2026-11-09, 추천안): 대상과 상관없이 모든 작품 화면의 대화 패널에서 부를 수 있다. 새 대상 종류나 `agent_focus_block` 갈래를 두지 않는다.
   - 규칙 묶음 화면(`#/rules`)은 작품 밖 화면이라 대화 패널이 없다(`static/app.js` 의 `outside('rules', …)`).
   - 대화 패널은 작품마다 세션을 둔다(`Project.agent_sessions`). 묶음은 정할 것 6 · 7 로 이 작품이 켠 것에만 닿는다.
   - 쓰기 종류 `outside`(다듬을 곳 밖)는 플롯 쓰기의 종류라 이 도구와 관계없다(`agent.outside`).
   - 07 의 정할 것 9 와 06 의 '대화 에이전트' 줄은 에이전트가 `plot` 주제만 돈다고 적었다. 지금은 `agent.TOPICS = ("agent", "plot")` 이고 패널이 하나로 합쳐졌다. 두 줄을 함께 고친다.
   - 다른 안: 본문 대상(`text:N`)과 검수 화면에서만 부른다. 규칙은 작품 전체에 걸리므로 화면으로 막을 까닭이 약하다.
17. 가짜 응답의 자리 — 정함(2026-11-09, 추천안): `canon/mock.py` 의 `_agent_step` 에 갈래를 더한다. `mock_<기능>.py` 를 따로 두지 않는다.
   - 가짜 응답은 응답 형식마다 함수 하나다(`mock.responds` 가 `RESPONDERS[schema] = fn`). `PlotAgentStep` 은 이미 `_agent_step` 이 맡아 다른 파일이 등록하면 덮어쓴다.
   - 갈래: 말에 '규칙'과 «…»(찾을 글)이 들고 이번 턴에 `propose_regex` 를 부르지 않았으면 `propose_regex` 를 부른다. 말에 '고침'이 들면 `action=fix` 다.
   - 이 갈래는 `revise_text` · `edit_setup` · `edit_style` 갈래보다 앞에 둔다. 본문 대상(`text:N`)에서 «…» 가 든 말은 지금 `revise_text` 갈래가 먼저 받는다(`mock._agent_step`).
   - 막힘 시험용 갈래: 말에 '나쁜 규칙'이 들면 `in` 에 `(a+)+` 를 넣는다(`regexrules._nested` 가 막음).
   - 다른 안: `mock_regex.py` 에 도움 함수를 두고 `_agent_step` 이 부른다. 갈래가 둘뿐이라 파일을 나눌 만큼 크지 않다.
18. 명령줄 — 정함(2026-11-09, 추천안): 더하지 않는다.
   - 대화 에이전트는 웹에서만 돈다(`web._run_agent`).
   - 명령줄 `rules` 명령(`cli.cmd_rules`)의 목록 · 시험 · 켜기 · 끄기는 그대로다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/agent_regex.py` (새 파일) | `TOOL = "propose_regex"`, `KIND = "rule"`, `LABEL = "정규식 규칙 제안"`, `KEPT` 문구 |
| `canon/agent_regex.py` | `shortcut(turn)`: 늘 `None` (지름길 없음) |
| `canon/agent_regex.py` | `prepare(name, p, s, turn, step)`: 인자로 `RegexRule` 을 만들고 묶음을 고르고(정할 것 6) 검사(10)와 시험(11)을 한다. AI 를 부르지 않는다. 결과는 새 `RegexCard` 또는 막힌 까닭(글) |
| `canon/agent_regex.py` | `record(p, s, turn, step, prepared)`: 잠근 작품에서 카드 `Approval(tool, regex, keys=["rule"], kinds=["rule"])` 를 남기고 `"wait"` 를 돌려준다. 막혔으면 까닭을 `why` 에도 넣은 `block` 단계를 남기고 `""`(`agent_style.record` 꼴) |
| `canon/agent_regex.py` | `decide(p, s, turn, approve, picked, text)`: 묶음을 다시 읽어 규칙 하나를 넣는다. 이 작품이 끈 묶음이면 막는다(14). 새 묶음이면 만들고 `Settings.rule_bundles` 에 켠다(8). `WriteRecord.regex` 를 남기고 턴을 끝낸다 |
| `canon/agent_regex.py` | `undo(p, rec, items)`: 정할 것 13. 다른 작품 수는 `used_by(bid)` 의 수에서, 지금 작품(`p.settings.rule_bundles`)이 그 묶음을 켰으면 1을 뺀 수로 센다. 복제 · 이름 바꾸기로 폴더 이름이 `RegexCard.project` 와 달라져도 맞다. `compact(rec, reason)`: 오래된 턴의 전 · 뒤 값을 지운다 |
| `canon/agent.py` | `CARD_TOOLS` 에 `agent_regex` 한 줄, `KIND_LABELS` 에 `"rule": "규칙"`(정할 것 1 의 하위 결정 안 1) |
| `canon/agent.py` | `READ_TOOLS` 에 `read_rules`, `read` 에 그 갈래(15). 모듈 머리글에 도구 줄 |
| `canon/regexrules.py` | 새 함수 `set_rule(bid, rid, rule, note)`: 묶음을 읽어 id 가 `rid` 인 규칙을 `rule` 로 바꾸고(없으면 끝에 더하고, `rule` 이 `None` 이면 뺀다) `check` 뒤 저장한다. 저장한 규칙을 끄기만 하면(`switched_off`) 그 규칙은 `check` 에서 건너뛴다. `check` 에 건너뛸 규칙 id 인자 `skip` |
| `canon/regexrules.py` | `trial` 에 `strict` 인자: 참이면 경고 규칙은 `_issues(..., strict=True)` 의 `RuleSkipped` 를, 내보내기 규칙은 `_apply` 의 세 번째 값을 `skipped` 에 담는다(정할 것 11). 규칙 화면의 시험은 지금처럼 거짓 |
| `canon/schema.py` | `AGENT_TOOL_NAMES` 에 `"propose_regex"` · `"read_rules"`. 새 모델 `RegexCard`. `Approval.regex` · `WriteRecord.regex` |
| `canon/schema.py` | `PlotAgentStep.args` 의 설명에 인자를 받는 도구 이름 `propose_regex` 를 더한다 |
| `canon/prompts.py` | `AGENT_PLOT_TOOLS` 에 `propose_regex` · `read_rules` 줄 |
| `canon/prompts.py` | `AGENT_PLOT_TOOLS` 의 '[작가가 화면에서 할 수 있는 일]' 에 규칙 묶음 화면 줄 |
| `canon/prompts.py` | `_agent_turn_line` 에 `a.regex` 갈래(규칙 이름). 지금은 카드를 `keys` 로 적어 '물음(…): rule' 만 남는다 |
| `canon/mock.py` | `_agent_step` 에 `propose_regex` 갈래(정할 것 17). `revise_text` · `edit_setup` · `edit_style` 갈래보다 앞에 둔다 |
| `canon/static/agent.js` | `AGENT_KINDS` 에 `rule`, `AGENT_ALWAYS` 에 `'rule'`, `agentToolName` 에 `propose_regex` · `read_rules` |
| `canon/static/agent.js` | `agentApproval` 맨 앞에 `if (a.regex) return agentRegexApproval(t, i, last)`. 새 함수 `agentRegexApproval` |
| `canon/static/agent.js` | `agentItemDiff` 에 `w.regex` 갈래(적용 전 · 뒤 규칙 칸) |
| `canon/static/agent.js` | `agentDecide` 의 알림에 `a.regex` 갈래. 지금 문구 '승인한 곳을 썼어요. 이어서 돌아요'는 턴을 끝내는 규칙 카드와 맞지 않는다(`web.agent_approval` 이 job `None`) |
| `canon/static/agent.js` | `agentWrites` 의 표시를 `w.regex` 에서도 '적용함'으로 둔다(지금은 `w.style` 만) |

- `canon/web.py` 는 고치지 않는다. 승인과 되돌리기는 지금 길목(`agent_approval` · `agent_undo`)이 `CARD_TOOLS` 로 넘긴다.
- `decide` · `undo` 는 작품 잠금(`jobs.project_lock`) 안에서 돌지만 작품 밖 파일(`.rules/<id>.json`)도 고친다. 규칙 저장소에는 잠금이 없다(정할 것 14).
- LLM 호출은 새로 생기지 않는다. 에이전트의 기존 단계 호출(`get_llm("chat")`)이 도구 인자를 채운다(정할 것 3).
- 새 단계 이름을 `settings.STAGES` 에 더하지 않는다.
- 07 도 `canon/agent.py` 의 `CARD_TOOLS` · `KIND_LABELS` 와 `static/agent.js` 의 같은 표를 고친다. 동시에 하면 고칠 줄을 먼저 견준다.
- 07 이 나중에 머지되면 `ALWAYS_ASK` 의 `rule` 겹침을 07 이 정리한다(정할 것 1).
- 카드의 시험 결과는 `canon/static/regexrules.js` 의 `ruleChangeHtml` 을 다시 쓴다. 이 파일은 고치지 않는다.

## 데이터 · 스키마

새 모델 `RegexCard` (`canon/schema.py`, AI 가 채우지 않는다):

- `bundle: str` 묶음 id. 새 묶음 카드는 `""` 이고 적용하면 만든 id 를 채운다
- `bundle_name: str = ""` 카드에 보일 묶음 이름
- `new_bundle: bool = False` 정할 것 6 으로 새 묶음을 만드는 카드
- `project: str = ""` 카드를 만든 이 작품의 폴더 이름. `prepare` 가 `name` 으로 채운다. `Project` 에는 폴더 이름 칸이 없고 `undo` 는 `name` 을 받지 않는다
- `used_by: list[str] = []` 카드를 만들 때 그 묶음을 켠 작품 폴더 이름(`regexrules.used_by`). `prepare` 가 이 작품을 빼고 채운다
- `rule: RegexRule` 넣을 규칙(적용 뒤 값)
- `before: Optional[RegexRule] = None` 고치기의 적용 전 규칙. 새 규칙이면 `None`
- `episode: int = 0` 시험한 화. 0 이면 시험하지 않음
- `changes: list[RuleChange] = []` 시험에서 바뀐 곳(10개까지)
- `hits: list[ConsistencyIssue] = []` 시험에서 걸린 곳(10개까지)
- `change_count: int = 0` 시험에서 바뀐 곳 전체 수
- `hit_count: int = 0` 시험에서 걸린 곳 전체 수
- `export_changed: bool = False` 내보내기 규칙 카드에서 `trial` 의 `exported` 가 `text` 와 다른지. `trial` 은 내보내기 규칙의 바뀐 곳을 돌려주지 않아 `changes` 는 늘 빈다
- `timed_out: bool = False` 끄기 카드에서 적용 전 규칙의 시험이 시간 한도를 넘었는지(정할 것 11)
- `notices: list[str] = []` 저장을 막지 않는 알림(`regexrules.notices`)
- `version: int = 0` 적용한 뒤 묶음 버전. 카드에서는 0

바꾸는 모델:

- `Approval.regex: Optional[RegexCard] = None` 규칙 제안 카드(tool `propose_regex`)
- `WriteRecord.regex: Optional[RegexCard] = None` 적용 기록. 되돌리기는 `agent_regex.undo`
- 기본값이 `None` 이라 옛 `project.json` 이 그대로 읽힌다.
- `RegexCard` 는 `.json(…)` 응답 형식에 들지 않으므로 `SkipJsonSchema` 가 필요 없다.

저장 모양:

- 작품은 `store.save` 의 `model_dump_json()` 으로 저장하므로 카드 안 규칙의 키는 `in` 이 아니라 `in_` 이다.
- `RegexRule` 은 `populate_by_name=True` 라 두 키 모두 읽힌다.
- 화면이 받는 키는 응답마다 다르다. `web.get_project` 는 `model_dump(mode="json")` 이라 `in_` 이다.
- `web.agent_approval` · `web.agent_undo` 의 `{"project": p}` 와 `web.agent_sessions` 는 FastAPI 직렬화(by_alias)라 `in` 이다. `agent.js` 의 `agentAct` 는 그 `res.project` 로 `S.project` 를 바꾼다.
- 그래서 카드 화면은 `r.in ?? r.in_` 처럼 두 키를 다 읽는다.
- 규칙 묶음 파일은 `regexrules._dump`(`by_alias=True`)로 써서 키가 `in` 이다. 이 일감은 묶음 파일 모양을 바꾸지 않는다.
- 새 전역 저장소와 새 환경 변수는 없다. 묶음은 06 의 `<CANON_HOME>/.rules/<id>.json`(`CANON_RULES`) 그대로다.
- [compat.md](../compat.md) 는 고치지 않는다. 규칙 필드를 바꾸지 않는다.

## 규칙

승인 흐름:

- 에이전트가 `propose_regex` 를 부르면 `prepare` 가 잠금 밖에서 규칙을 만들고 검사하고 시험한다.
- 막히면 카드 없이 까닭을 AI 에게 돌려준다. 턴은 이어 간다.
- 통과하면 `record` 가 카드를 남기고 턴이 `wait` 로 멈춘다.
- 카드는 권한 모드(`ask` · `draft` · `all`)와 상관없이 늘 묻는다. `rule` 이 `agent.ALWAYS_ASK` 에 들기 때문이다(`agent.permit`).
- '이 세션에서 묻지 않기'는 카드에 없다. 화면은 `AGENT_ALWAYS` 종류에서 그 체크를 숨기고, 서버는 `ALWAYS_ASK` 를 `auto_kinds` 에 넣지 않는다(`agent.decide`).
- 작가가 적용하면 `decide` 가 규칙 하나를 묶음에 넣고 턴을 끝낸다. AI 를 다시 부르지 않는다.
- 작가가 적용하지 않으면 카드는 `denied` 가 되고 턴을 끝낸다.
- 새 턴을 보내면 기다리던 카드는 `denied` 가 된다(`agent.add_turn`).
- 자동 집필과 `-y` 는 이 도구와 관계없다. 대화 에이전트만 이 도구를 부른다.

적용의 효과:

- 고침 규칙은 다음에 본문을 쓸 때부터 걸린다(정할 것 12).
- 경고 규칙은 다음 검수부터 이미 쓴 화에도 걸린다.
- 내보내기 규칙은 다음 내보내기부터 걸린다(`publish.py` → `regexrules.export_text`).
- 묶음을 켠 다른 작품에도 같은 때부터 걸린다(정할 것 7).
- 적용은 묶음에 새 버전을 남긴다. 메모는 '대화 에이전트 제안: <규칙 이름>'이다. 규칙 화면의 버전 목록에서 보이고 되살릴 수 있다(`regexrules.restore`).

경계 사례:

- 고칠 규칙이 카드를 만든 뒤 바뀌었으면 적용을 막고 카드를 둔다(정할 것 14).
- 묶음을 카드를 만든 뒤 지웠으면 적용을 막고 카드를 둔다. 문구는 '그 묶음을 찾을 수 없어요'다.
- 카드를 만든 뒤 이 작품에서 그 묶음을 껐으면 적용을 막고 카드를 둔다. 문구는 '이 작품에서 그 묶음을 껐어요'다(정할 것 14).
- 새 묶음 카드를 적용할 때 이 작품이 그 사이 다른 묶음을 켰어도 새 묶음을 만든다. 카드가 보인 대로 적용한다.
- 같은 규칙(같은 `in` · `out` · `action` · `type` · `flag`)이 이미 묶음에 있으면 `prepare` 가 막고 그 규칙 id 를 AI 에게 돌려준다.

되돌리기:

- 정할 것 13.
- 되돌리기는 지금 길목 `POST /api/projects/{name}/sessions/{sid}/turns/{t}/undo` 를 쓴다(`web.agent_undo` → `agent.undo` → `agent_regex.undo`).
- 되돌려도 그 사이 고침 규칙이 바꾼 본문은 그대로다. 본문의 고침은 화마다 규칙 걸기 기록(`Episode.rule_runs`)에서 따로 되돌린다(`regexrules.undo_run`).

권한 모드:

- 대화 에이전트는 어느 권한 모드에서도 규칙 묶음과 `Settings.rule_bundles` 를 바로 쓰지 않는다.
- 쓰기는 작가가 카드에서 적용할 때만 일어난다(Q29).
- 에이전트가 이미 있는 묶음을 켜고 끄거나 차례를 바꾸지 않는다(정할 것 8).

단편 · 장편:

- 단편과 장편에서 똑같이 동작한다. 규칙 제안은 컨텍스트 예산과 관계없다.

## 화면 · 명령줄 · 프롬프트

승인 카드(`agentRegexApproval`, 새):

- 머리 줄: '정규식 규칙 · <묶음 이름>' 또는 '정규식 규칙 · 새 묶음 <이름>'.
- 새 규칙이면 규칙 칸(이름, 찾을 정규식, 바꿀 글, 동작, 적용 범위, 플래그)을 보인다.
- 새 규칙의 칸은 값만 보인다. `diffField` 의 '바꾸면' 머리말을 붙이지 않는다(견줄 전 값이 없다).
- 고치기면 칸마다 전 · 뒤를 보인다(`diffField` 꼴).
- 동작 문구: 경고는 '검수할 때 걸린 곳을 보여요', 고침은 '적용하면 다음에 본문을 쓸 때부터 본문을 바꿔요', 내보내기는 '내보낼 때만 걸려요'.
- 시험 줄: '<N>화에 걸어 보면 바뀌는 곳 <a>곳 · 걸리는 곳 <b>곳이에요'. 바뀐 곳은 `ruleChangeHtml` 로 보인다.
- 걸린 곳은 규칙 화면의 시험(`regexrules.js` 의 `ruleTestCard`)처럼 `.rx-name` 에 `description`, `.rx-diff` 에 `current_quote` 를 보인다.
- 내보내기 규칙 카드는 시험 줄 대신 `export_changed` 로 '<N>화를 내보낼 때 글이 바뀌어요' 또는 '<N>화를 내보낼 때 바뀌는 곳이 없어요'를 보인다.
- 끄기 카드의 시험 줄은 '<N>화에서 적용하면 더 걸리지 않을 곳 <a>곳 · <b>곳이에요'다(정할 것 11).
- `timed_out` 인 끄기 카드는 시험 줄 대신 '<N>화에 걸어 보니 시험 시간이 넘었어요. 끄면 이 규칙은 더 걸리지 않아요'를 보인다.
- 시험하지 않았으면 '시험할 본문이 없어요'.
- 다른 작품이 켠 묶음이면 '다른 작품 <N>개에도 걸려요'.
- 새 묶음이면 '적용하면 새 묶음을 만들고 이 작품에서 켜요'.
- 알림(`notices`)은 카드 아래 줄로 보인다.
- 버튼은 다른 카드와 같다(적용 · 적용 안 함). '이 세션에서 묻지 않기'는 없다.
- 적용한 뒤 알림은 규칙에 따라 다르다(`agentDecide` 의 `a.regex` 갈래, `agentRxDone`). 정할 것 12 의 '언제부터 걸리는지'를 따른다.
- 고침 규칙은 '규칙을 넣었어요. 다음에 본문을 쓸 때부터 걸려요'다.
- 경고 규칙은 '규칙을 넣었어요. 다음 검수부터 걸려요'다.
- 내보내기 규칙은 '규칙을 넣었어요. 다음에 내보낼 때부터 걸려요'다.
- 끄기 카드는 '규칙을 껐어요. 다음 걸기부터 걸리지 않아요'다.
- 규칙 카드는 턴을 끝내므로 '이어서 돌아요'를 보이지 않는다.
- 답한 뒤에는 다른 카드처럼 `.approval.settled` 로 접는다.

'바뀐 것' 목록:

- 항목 이름은 '정규식 규칙 · <규칙 이름>'이다.
- '바뀐 칸 보기'는 적용 전 · 뒤 규칙 칸이다(`agentItemDiff` 의 `w.regex` 갈래).
- 적용한 항목의 표시는 '바로 씀'이 아니라 '적용함'이다. 작가가 카드로 적용했기 때문이다(`agentWrites` 의 `w.style` 꼴).
- 되돌리기 버튼은 다른 항목과 같다.

디자인 문서:

- 카드는 기존 클래스(`.approval` · `.prop-part` · `.diff`)와 `ruleChangeHtml` · `ruleTestCard` 의 클래스(`.rx-name` · `.rx-diff` · `.rx-changes` · `.rx-change`)만 쓴다.
- 이 클래스들은 `canon/static/app.css` 에만 있고 `docs/design/components/bundle.css` 에 없다. 그래서 `docs/design/` 을 고치지 않는다.
- 새 클래스를 더하게 되면 `docs/design/layout.md` 의 대화 패널 줄을 함께 고친다.

프롬프트:

- `canon/prompts.py` 의 `AGENT_PLOT_TOOLS` 에 두 줄을 더한다.
- `read_rules` 줄: '이 작품이 켠 정규식 규칙 묶음과 규칙. 규칙을 고치거나 겹치지 않게 더할 때 먼저 봅니다'.
- `propose_regex` 줄: 인자(정할 것 4), JavaScript 정규식 꼴, 규칙 하나만, 늘 작가에게 묻고 턴이 끝남, 적용 전에는 걸리지 않음.
- '[작가가 화면에서 할 수 있는 일]' 에 '규칙 묶음 화면: 규칙 · 묶음 지우기, 설정 화면: 묶음 켜기 · 끄기' 줄을 더한다. 그 목록은 '이 목록에 있는 것만 말합니다'라서 없으면 AI 가 정할 것 5 의 지우기를 안내하지 못한다.
- `_agent_turn_line` 은 규칙 카드를 규칙 이름으로 적는다. 지금 꼴(`', '.join(t.approval.keys)`)이면 다음 턴 프롬프트에 '물음(…): rule' 만 남는다.
- `AGENT_PLOT_TOOLS` 는 `agent_plot_prompt` 에만 들고, 에이전트 프롬프트는 `canon/agent.py` 만 쓴다. 작업지시서(`brief`) 출력은 바뀌지 않는다.
- 새 블록을 넣지 않으므로 `context.BUDGET` 은 바뀌지 않는다.
- 단편 · 장편의 쓰기 프롬프트는 바뀌지 않는다.
- 도구 설명은 Canon 의 글로 쓴다. RisuAI 코드와 기본 프롬프트 글은 옮기지 않는다(Q4).

명령줄 · 웹:

- 명령줄은 바꾸지 않는다(정할 것 18).
- 새 웹 엔드포인트는 없다.
- `python scripts/make_openapi.py` 를 돌리지 않는다. `swift/` 를 고치지 않는다.

## 시험

새 시험 `tests/test_agent_regex.py`:

- `propose_regex` · `read_rules` 가 `schema.AGENT_TOOL_NAMES` 에 있다.
- `CARD_TOOLS["propose_regex"] is agent_regex` 이고 `"rule" in agent.ALWAYS_ASK` 다.
- 'all' 모드에서도 카드로 묻고, `remember=True` 로 적용해도 `auto_kinds` 에 `rule` 이 들지 않는다(`test_agent_style.py` 의 `test_all_mode_still_asks_and_remember_is_ignored` 꼴).
- 적용하면 켠 묶음에 규칙이 하나 늘고 묶음 `version` 이 오른다.
- 켠 묶음이 없으면 새 묶음을 만들고 `Settings.rule_bundles` 끝에 켠다.
- 켠 묶음이 둘이고 `bundle` 이 비면 카드 없이 막히고 `block` 단계의 `why` 에 묶음 이름이 든다.
- 켜지 않은 묶음 id 를 주면 막힌다.
- 나쁜 정규식(`(a+)+`)은 카드 없이 `block` 단계가 남고 그 `why` 에 `regexrules.REFUSE` 문구가 든다. 턴이 끝나면 `agent._strip` 이 `result` 를 지우므로 `result` 로 보지 않는다.
- 시간 한도를 넘는 경고 규칙(기본 `action=warn`)은 카드 없이 막힌다(`trial(strict=True)`).
- 시간 한도를 넘는 켠 규칙을 끄는 카드는 막히지 않고 `timed_out` 이 든다. 적용하면 규칙이 꺼진다.
- 지금 `validate` 를 통과하지 못하는 옛 규칙(`(a+)+`)도 끄기 카드로 끌 수 있다. 같은 규칙의 다른 칸을 고치면 막힌다.
- 카드에 시험 결과(바뀐 곳 수 · 걸린 곳 수 · 시험한 화)가 든다.
- 내보내기 규칙 카드에 `export_changed` 가 든다.
- 끄기 카드(`enabled=false`)의 시험 결과는 적용 전 규칙으로 건 값이다.
- 본문 대상(`text:N`) 세션에서 '규칙'과 «…» 가 든 말이 `revise_text` 가 아니라 `propose_regex` 를 부른다.
- 카드를 만든 뒤 이 작품에서 그 묶음을 끄면 적용이 400 이고 카드가 `wait` 로 남는다.
- 카드의 `used_by` 에 이 작품이 들지 않는다.
- 적용 뒤 이미 쓴 화의 본문(`Episode.text`)과 `rule_runs` 가 바뀌지 않는다.
- 되돌리면 새 규칙이 빠지고, 고치기는 적용 전 규칙으로 돌아간다.
- 적용 뒤 같은 규칙을 다시 고쳤으면 되돌리기가 `kept` 로 남긴다.
- 묶음을 지웠으면 되돌리기가 `kept` 로 남긴다.
- 새 묶음 되돌리기는 작품에서 끄고, 묶음에 그 규칙만 남아 있고 다른 작품이 켜지 않았으면 묶음 파일을 지운다.
- 그때 디스크의 이 작품은 아직 그 묶음을 켠 채라 `used_by` 에 들지만, 지금 작품이 켰으면 1을 빼고 세므로 묶음 파일을 지운다.
- 복제한 작품에서 그 묶음을 끄고 되돌려도 원본이 켠 묶음 파일은 지우지 않는다.
- 이름을 바꾼 작품에서 되돌리면 묶음 파일을 지운다.
- 카드를 만든 뒤 고칠 규칙을 바꾸면 적용이 400 이고 카드가 `wait` 로 남는다.
- 적용 · 되돌리기에서 LLM 을 부르지 않는다(`test_agent_style.py` 의 `_usage_calls` 꼴).
- 긴 `read_rules` 결과는 `agent._cut` 을 거쳐 `RESULT_LIMIT` 자 뒤에 자름 안내 줄('… (예산 2500자에서 잘랐어요)')로 끝난다.
- `- propose_regex (args:` 줄과 `- read_rules` 줄이 `prompts.AGENT_PLOT_TOOLS` 에 있다(`test_agent_style.py` 의 같은 꼴).
- 옛 `project.json`(`Approval` · `WriteRecord` 에 `regex` 가 없음)이 읽힌다.

고치는 시험:

- `tests/test_agent_text.py` 의 `ALWAYS_ASK == ("renumber", "text", "setup", "style")` 에 `"rule"` 을 더한다.
- `tests/test_agent_js.py` 의 `test_mode_and_kind_labels_match_server` 는 고치지 않아도 `AGENT_KINDS` 와 `KIND_LABELS` 를 견준다.
- `tests/test_agent_js.py` 에 규칙 카드를 그리는 시험을 더한다: `data-agent-remember` 가 없고, 시험 줄과 묶음 이름이 보인다.
- 그 시험은 `regexrules.js` 를 함께 싣는다. 지금 `FILES` 는 `app.js` · `chat.js` · `agent.js` · `agentsetup.js` 라 `ruleChangeHtml` 이 없어 `ReferenceError` 가 난다.
- 규칙 카드 시험은 규칙 키가 `in` 인 모양과 `in_` 인 모양을 둘 다 그린다(저장 모양 절).
- `agentDecide` 의 규칙 카드 알림 글과 `agentWrites` 의 '적용함' 표시를 확인한다.
- `AGENT_ALWAYS`(`static/agent.js`)와 `agent.ALWAYS_ASK` 를 견주는 시험을 더한다. 지금은 없다.

돌리기:

- 고친 기능만: `CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_agent_regex.py tests/test_agent.py tests/test_agent_text.py tests/test_agent_js.py`.
- 전체: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- 정적 검사: `ruff check canon tests scripts`.
- `tests/conftest.py` 가 이미 `CANON_RULES` 를 지우므로 규칙 저장소는 시험 폴더의 `.rules` 다. 새 환경 변수와 새 모듈 캐시는 없다.

## 문서

- `docs/modules/story.md` 의 `### canon/agent.py` 절: `CARD_TOOLS` · `ALWAYS_ASK` 줄에 `agent_regex` 와 `rule`, 읽기 도구 목록 줄('도구는 읽기(`read_plots` · …')에 `read_rules`.
- 같은 절의 쓰기 도구 줄(`revise_text` · `edit_setup` · `edit_style`) 뒤에 '규칙 제안 도구는 `propose_regex`(`agent_regex.py`)다' 줄을 더한다.
- `docs/modules/story.md` 에 새 절 `### canon/agent_regex.py` 를 `canon/agent.py` 와 `canon/agent_setup.py` 사이에 더한다(`tests/test_agents_docs.py`).
- `docs/modules/story.md` 의 `### canon/static/agent.js` 절: 규칙 카드와 `AGENT_ALWAYS` 줄.
- `docs/modules/core.md` 의 `### canon/regexrules.py` 절: '대화 에이전트는 … 읽지도 쓰지도 않는다' 줄을 '읽기 도구로 켠 묶음을 읽고, 작가가 카드로 적용할 때만 쓴다'로 고친다. `set_rule` 줄과 `trial` 의 `strict` 줄을 더한다.
- `docs/modules/core.md` 의 `### canon/static/regexrules.js` 절: '`ruleChangeHtml` 은 대화 에이전트의 규칙 카드(`agent.js`)도 쓴다' 줄을 더한다.
- [06-regex-rules.md](06-regex-rules.md) 의 정할 것 12: 도구 이름(`propose_regex`)과 길(`CARD_TOOLS` 꼴)을 정할 것 1 · 2 의 결과로 고친다.
- `docs/modules/ai.md` 의 `### canon/mock.py` 절: `_agent_step` 의 `propose_regex` 갈래 한 줄.
- `DESIGN.md` 의 정규식 규칙 절: '대화 에이전트는 규칙 묶음과 켠 묶음을 읽지도 쓰지도 않는다' 문장을 고친다.
- `DESIGN.md` 의 대화 에이전트 절: 04b~04d 줄과 같은 꼴로 `propose_regex` 줄을 더한다.
- `README.md` 의 정규식 규칙 묶음 절: '대화 패널에서 규칙을 제안받고 카드로 적용' 줄을 더한다.
- 이 폴더의 [plan.md](../plan.md): 6 의 상태를 끝(#446)으로, 6b 의 명세서 칸을 이 파일로 고친다.
- [06-regex-rules.md](06-regex-rules.md): 머리 줄 상태, 정할 것 12 에 이 명세서 링크, '대화 에이전트' 절의 첫 두 줄.
- [07-rules.md](07-rules.md) 의 정할 것 9: 6b 가 `propose_regex` 를 쓰고 쓰기 종류 `rule` 을 함께 쓴다는 줄, `renumber` 의 길 대신 `CARD_TOOLS` 꼴이라는 줄, `plot` 주제만 돈다는 줄을 고친다.
- 이 폴더의 [README.md](../README.md): 정한 것을 날짜와 함께 정한 규칙에 더한다. 'LLM 호출과 시험'의 '규칙 제안은 새 LLM 호출' 줄을 정할 것 3 의 결과로 고친다.
- `docs/design/` 은 고치지 않는다(카드가 기존 클래스만 쓰면).

## 확인하지 못할 것

- 실제 모델(Gemini 등)이 `propose_regex` 를 맞는 때에 부르고 JavaScript 정규식을 바르게 쓰는지는 가짜 응답 시험으로 확인하지 못한다. 키가 있을 때만 확인할 수 있다.
- 카드 문구와 시험 결과 보기가 작가에게 판단하기 쉬운지는 작가의 취향 판단이다.
- 규칙 화면과 대화 패널을 두 탭에서 함께 쓸 때 사라지는 제안이 실제로 문제가 되는지는 써 봐야 안다(정할 것 14).

사용자가 할 단계:

1. 머지 뒤 작품 하나에서 대화 패널에 "말줄임표 '...' 을 '…' 로 바꾸는 고침 규칙 만들어 줘"라고 보낸다.
2. 카드에 규칙 칸 · 시험 결과 · 묶음 이름이 보이는지 본다.
3. 적용한 뒤 규칙 묶음 화면(`#/rules`)에서 규칙과 새 버전을 확인한다.
4. 대화 패널의 '바뀐 것'에서 되돌리고 규칙이 빠졌는지 확인한다.
5. 다음 화를 써서 고침이 걸리는지 본다.

## 비용

- LLM 비용 없음.
- 시험은 가짜 응답(mock)만 쓴다.
- 이 도구는 새 LLM 호출을 만들지 않는다. 에이전트 단계 호출의 출력에 인자 몇 개가 늘 뿐이다(정할 것 3).
