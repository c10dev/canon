# 07. 선언형 규칙

상태: 설계 · 계획: [plan.md](../plan.md) 의 7번 · 먼저: —

2026-11-08 부터 일감 2 를 기다리지 않는다(README 의 Q36). 상태 조건으로 항목을 넣는 데 필요한 만큼의 `Activation`(조건 목록과 판정)을 이 일감이 만든다.
모델 모양은 [02-activation.md](02-activation.md) 의 모델 · 판정 절을 따르되, 보조 키 · 제외 키 · 재귀 · 유지 필드는 만들지 않는다.

## 목표

작가가 '조건이 맞으면 이렇게 한다'를 선언형 규칙으로 적는다.
효과는 둘이다.
- (x) 항목을 이번 화 프롬프트에 넣는다. 예: '두 인물의 신뢰가 0.7 이상이면 비밀 이야기 요소를 넣는다'.
- (y) 상태 변경을 제안해 상태 승인 화면에 올린다. 예: '주인공의 마력이 0 이하면 상태창의 상태를 기절로 바꾼다'.

규칙은 상태를 바로 쓰지 않는다.
- (y)의 규칙 제안은 '규칙' 표시를 달고 온다.
- 규칙 제안은 기본으로 체크한 채 온다.
- 작가가 반영해야 데이터에 들어간다.

화면 낱말:
- 이 기능의 화면 낱말은 '상태 규칙'이다. 정규식 규칙(06)의 화면 낱말 '규칙 묶음'과 나눈다.
- 상태 승인 화면의 제안 표시는 Q22 대로 '규칙'이다.

규칙을 하나도 두지 않은 작품은 프롬프트와 상태 변경안이 지금과 같다.
따르는 정한 규칙: [README.md](../README.md) 의 2026-11-08 줄 가운데 Q13 · Q22 · Q27 · Q28 · Q29, 그리고 Q7 · Q17 · Q18.

## 정할 것

1. 선언형 규칙을 어디에 저장하는가 — 추천: 작품 안(`Project.state_rules`)에 둔다.
   - 조건과 효과가 인물 id · 복선 id · 스탯 이름 · 항목 id 를 가리킨다. 이 id 는 작품마다 다르다.
   - 정규식 규칙(06)은 글만 보므로 전역 규칙 묶음이 맞지만, 선언형 규칙은 작품 데이터에 묶인다.
   - 다른 작품으로 옮기는 일은 나중에 '복사' 동작으로 따로 정한다. 이번 일감에서는 만들지 않는다.
2. 효과 (x)를 어디에 적는가 — 추천: 02 가 정한 `Activation.conditions`(`Condition` 목록)에 적는다.
   - Q13 은 '상태 조건이 활성화 조건의 하나가 된다'고 정했다.
   - 판정은 02 의 `context.holds(p, n, cond)` 하나로 한다(Q7, 02 의 정할 것 13).
   - 상태 규칙 화면은 `Project.state_rules`(효과 (y))와 조건이 붙은 활성화 묶음(효과 (x))을 한 목록으로 보인다.
3. 효과 (x)의 조건이 맞을 때의 뜻 — 추천: 02 의 정할 것 6 · 7 을 그대로 따른다.
   - 02 는 '조건만 적은 항목'을 따로 두지 않는다(02 의 정할 것 6). 이름과 다른 이름이 늘 키워드로 쓰이기 때문이다.
   - 조건이 맞을 때 늘 넣으려면 넣기 방식 `always` 와 `conditions` 를 함께 적는다(02 의 정할 것 6 · 7).
   - 키워드가 있는 항목에서 조건은 문이다. 조건이 하나라도 맞지 않으면 키워드로도 넣지 않는다(02 의 정할 것 7).
   - 다른 뜻을 원하면 02 와 07 을 한 결정으로 함께 고치도록 [README.md](../README.md) 의 정할 것에 올린다.
4. 효과 (x)의 활성 이유 — 추천: 새 이유를 두지 않고 Q17 의 네 이유를 그대로 쓴다.
   - 넣기 방식 `always` 와 조건을 함께 적은 항목은 '늘 넣기'로 센다(02 의 정할 것 6).
   - 넣기 방식이 자동인 항목은 키워드로 들어간 이유(키워드 직접 발견 · 재귀 · 유지)로 센다.
5. 효과 (y)가 제안할 수 있는 상태 — 추천: 상태창 값 바꾸기와 복선 회수 둘만 둔다(README 정할 것 5 와 같다).
   - 인물 설정 바꾸기는 '기본으로 체크하지 않음' 원칙이 있어 규칙 제안의 '기본 체크'와 부딪힌다.
   - 관계 수치는 AI · 규칙이 적지 않는다는 원칙이 있다. 조건에서 읽기만 한다(Q27).
   - 복선 심기, 새 사실, 인물 상태 칸(감정 · 목표 · 위치 · 차림)은 나중에 사용자와 정한다.
6. 같은 값을 거듭 제안하지 않기 — 추천: 제안을 반영했을 때의 새 값이 지금 값과 같으면 그 제안을 만들지 않는다.
   - 새 값은 `statwin.resolve(지금 값, value)` 로 계산한다. 이미 회수된 복선의 회수 제안도 만들지 않는다.
   - 새 값(`기절`)을 적은 규칙은 조건이 여러 화 동안 맞아도 값이 바뀌지 않으면 승인 화면에 다시 오지 않는다.
   - 목록 더하기(`+항목`)도 이미 그 항목이 있으면 새 값이 같으므로 다시 오지 않는다.
   - 바뀐 양(`+3`)을 적은 규칙은 새 값이 늘 다르므로 조건이 맞는 화마다 제안이 온다.
   - '한 번만' 필드는 두지 않는다. 바뀐 양 규칙을 한 번만 걸려면 조건에 화 범위를 넣는다.
7. 규칙끼리 잇따라 걸리는가 — 추천: 한 번만 계산한다. 규칙 제안을 반영한 상태로 다시 규칙을 계산하지 않는다.
   - 활성화의 재귀를 한 단계로 묶은 Q8 과 같은 결이다. 끝없이 도는 규칙을 막는다.
   - 같은 스탯을 둘 이상의 규칙이 제안하면 규칙 목록 차례로 뒤의 것을 남기고 경고를 단다.
8. AI 제안과 규칙 제안이 같은 스탯을 바꿀 때 — 추천: 규칙 제안을 AI 제안 뒤에 적용한다.
   - 규칙의 조건은 AI 제안을 반영한 값으로 본다.
   - 두 제안이 같은 스탯이면 규칙 제안 줄에 경고를 단다.
9. 대화 에이전트가 규칙을 제안하는 길 — 추천: 새 도구 `propose_rule` 을 더한다.
   - 쓰기 종류 `rule` 은 어느 권한 모드에서도 'ask' 로 둔다(`renumber` 와 같다).
   - Q29 대로 작가가 대화 패널의 승인 카드에서 적용해야 `Project.state_rules` 에 들어간다.
   - 선언형 규칙 제안은 이 일감(7) 안에 둔다(2026-11-08, Q33). 정규식 규칙 제안은 06 뒤의 조각 6b 가 같은 꼴로 만든다.
   - 6b 는 도구 이름 `propose_regex` 와 쓰기 종류 `rule`(이름표 '규칙')을 쓴다(2026-11-09, 06b 의 정할 것 1). 이 일감은 같은 종류 `rule` 을 함께 쓴다.
   - 6b 는 `renumber` 의 길 대신 늘 묻는 도구 모듈(`CARD_TOOLS`) 꼴로 만들었다(06b 의 정할 것 2). 이 일감도 시작 전에 같은 꼴을 견준다.
   - 지금 대화 패널은 하나로 합쳐졌다(`agent.TOPICS = ("agent", "plot")`). 6b 는 대상과 상관없이 모든 작품 화면에서 부른다(06b 의 정할 것 16).
   - `propose_rule` 은 에이전트의 기존 호출과 단계(`chat`)를 그대로 쓴다. 새 `get_llm` 단계를 두지 않는다.
   - 위 줄이 [README.md](../README.md) 정할 것 10(새 LLM 호출의 단계 이름)의 규칙 쪽 답이다.
   - 승인 카드의 적용 · 되돌리기는 `renumber` 의 길(`Approval` 카드, 적용하면 `WriteRecord` 에 전 · 뒤 값)을 따른다.
10. 자동 집필의 승인 정책 — 추천: 새 정책 칸을 두지 않는다.
    - 규칙 제안은 기본 체크 항목처럼 반영한다.
    - 지금 정책의 복선 회수 검사(`autorun._story_reasons`)가 규칙이 회수한 복선도 본다.
    - 규칙이 바꾼 상태창 값과 회수한 복선은 작업 기록에 경고 한 줄로 남긴다.
    - '규칙 제안이 있으면 멈춤' 칸은 써 본 뒤 필요하면 사용자와 정한다.
11. 상태 규칙 화면의 자리 — 추천: 인과율 화면에 '상태 규칙' 탭을 둔다.
    - 상태창 · 복선 · 이야기 요소와 같은 이야기 데이터 화면이라서다.
    - 시작 전에 `docs/design/layout.md` 의 화면 배치와 견줄 것.
12. 반영할 때 다시 계산한 규칙 제안이 화면이 보인 것과 다르면 — 추천: 409(code `stale_rules`)로 막는다.
    - Q28 은 '반영할 때 한 번 더 계산한다'만 정했다. 다르면 막을지는 이 정할 것이다.
    - 견줄 기준은 화면이 보낸 `rule_proposals` 의 `key` 목록이다. 반영에는 쓰지 않는다.
    - 작가가 확인하면 새 인자 `force_rules` 로 다시 보낸다.
    - 지금 `force` 는 `stale_delta` 를 넘기는 데 쓴다(`web.apply_state`). 한 경고를 확인해 다른 경고까지 넘기지 않게 인자를 나눈다.
    - 다른 길: 막지 않고 다시 계산한 목록을 반영한 뒤, 반영 기록에 화면과 달랐다고 남긴다. 작가가 보지 않은 제안이 기본 체크로 들어가므로 추천하지 않는다.
13. 플레이와 반영 뒤 고침에서 규칙 제안을 계산하는가 — 추천: 계산하지 않는다.
    - 플레이(`play.py` 가 부르는 `pipeline.apply_delta`)는 플레이 자기 흐름의 변경안을 반영한다. 상태 승인 화면을 거치지 않는다.
    - 반영 뒤 고침(`web.apply_restate`)은 이미 반영한 화를 고친다. 규칙 제안을 다시 계산하면 이미 반영한 규칙 제안과 겹친다.
    - 두 길에서는 `rule_proposals` 를 비운 채 반영한다. 필요하면 써 본 뒤 사용자와 정한다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/staterules.py` (새 파일) | `propose_on(sim, p, d, n)`: 흉내 반영한 복사본에서 조건을 보고 규칙 제안 목록을 돌려준다. 조건 판정은 `context.holds` 를 부른다 |
| `canon/staterules.py` | `propose(p, d, n)`: 복사와 흉내 반영을 한 뒤 `propose_on` 을 부른다 |
| `canon/context.py` | 02 의 `holds(p, n, cond)` 를 그대로 쓴다. 효과 (x)는 02 의 활성 이유를 그대로 쓰므로 새 이유를 더하지 않는다(정할 것 3 · 4) |
| `canon/schema.py` | `StateRule` · `RuleProposal` 모델, `Project.state_rules`, `StateDelta.rule_proposals` · `rule_off`, `DismissedItems.rule_proposals` |
| `canon/pipeline.py` | `extract_state` 가 `clean_delta` 뒤에 `staterules.propose` 를 불러 `rule_proposals` 를 채운다. `carried_delta` 길도 옛 `rule_proposals` 를 비우고 다시 채운다. `apply_delta` 는 `features.APPLY_LAST` 를 거쳐 규칙 제안을 반영한다 |
| `canon/statwin.py` | `StatRecord.source` 의 `"rule"` 을 다룬다: 표시 맵 `SOURCE` 에 `"rule"` 문구, 출처 합치기(지금 `"both"`)가 `"rule"` 을 다루는 규칙 |
| `canon/features.py` | `APPLY_LAST` 에 규칙 제안 반영(`staterules.apply_delta`)을 더한다. 되돌리기는 스냅샷과 `statwin.revert` · `foreshadows.revert` 가 맡으므로 새 `REVERT_*` 는 두지 않는다(시작 전에 확인할 것) |
| `canon/web.py` | 상태 규칙 목록 읽기 · 더하기 · 고치기 · 지우기 엔드포인트(`/api/projects/{name}/state-rules`) |
| `canon/web.py` | `preview` 가 `staterules.propose_on` 으로 규칙 제안을 함께 돌려준다. 응답 모델 `RelationPreview` 에 `rule_proposals` 칸을 더한다 |
| `canon/web.py` | `apply_state` 가 최종 선택으로 규칙 제안을 다시 계산하고 인자 `force_rules` 를 받는다(정할 것 12) |
| `canon/static/review.js` | `DELTA_LISTS` · `DISMISS_LISTS` · `DELTA_PICK` 에 규칙 제안 칸을 더한다. 규칙 제안 줄에 '규칙' 표시를 단다. `refreshPreview` 의 응답으로 규칙 제안 목록을 바꾼다 |
| `canon/static/staterules.js` (새 파일) | 상태 규칙 화면: 목록, 조건 · 효과 고치기, 켜고 끄기 |
| `canon/autorun.py` | 자동 반영(`put`)이 규칙 제안을 채워 반영한다. `_story_reasons` 의 복선 회수 검사가 규칙 회수도 본다 |
| `canon/cli.py` | `state -y` 반영이 규칙 제안을 계산해 반영한다. 상태 규칙 목록을 보는 `staterules` 명령을 더한다. 06 의 `rules` 명령과 이름을 나눈다 |
| `canon/agent.py` | `propose_rule` 도구와 쓰기 종류 `rule`(정할 것 9) |
| `canon/mock_staterules.py` (새 파일) | 에이전트의 `propose_rule` 가짜 응답 |

- 판정(조건을 보고 켜거나 제안할지 정하는 일)은 `context.holds(p, n, cond)` 하나로 한다.
- `staterules.py` 는 `holds` 를 부르고 제안을 만들기만 한다.
- 이름은 06 과 겹치지 않게 둔다: 06 은 `RuleChange` 모델, `rules` 명령, `/api/rules` 엔드포인트, `#/rules` 길을 쓴다.
- 이 일감은 `StateRule` · `RuleProposalSpec` · `RuleProposal` 모델, `staterules` 명령, `/api/projects/{name}/state-rules` 엔드포인트를 쓴다.
- 이 일감의 화면은 인과율 화면의 탭이라 새 길을 두지 않는다(정할 것 11).
- 이 일감은 2(`Activation` 모델과 조건 판정)가 머지된 뒤 시작한다([plan.md](../plan.md)).
- 4 · 5 도 `Activation` 과 `context.py` 를 고친다. 동시에 하면 고칠 함수를 먼저 견준다.
- 효과 (x)는 새 활성 이유를 두지 않으므로 3(프롬프트 보기)의 `trace` 를 고치지 않는다.
- LLM 호출은 에이전트 도구에만 생긴다. 에이전트의 기존 단계 `chat` 을 쓴다(정할 것 9).
- 규칙 계산 자체는 LLM 을 부르지 않는다.

## 데이터 · 스키마

- `StateRule` (새 모델, 효과 (y)):
  - `id: str` — `r<N>` 꼴, 작품 안에서 하나.
  - `name: str = ""` — 화면에 보이는 이름.
  - `note: str = ""` — 작가 메모.
  - `on: bool = True` — 끄면 계산하지 않는다.
  - `when: list[Condition]` — 02 의 조건 모델. 모두 맞아야 한다(AND).
  - `changes: list[RuleProposalSpec]` — 조건이 맞으면 제안할 변경.
- `RuleProposalSpec` (새 모델):
  - `kind: Literal["stat", "resolve"]` — 상태창 값 바꾸기, 복선 회수(정할 것 5).
  - `character_id: str = ""` · `stat: str = ""` · `value: str = ""` — `kind = "stat"` 일 때. `value` 는 `StatValue.value` 와 같은 뜻이다(새 값, `+3` 같은 바뀐 양, 빈 값은 지움).
  - `foreshadow_id: str = ""` — `kind = "resolve"` 일 때.
- `RuleProposal` (새 모델, 규칙 제안 한 줄):
  - `rule_id: str` — 제안을 만든 규칙.
  - `key: str` — 같은 제안을 다시 계산해도 같게 나오는 열쇠(`rule_id` + 대상). 작가가 체크를 푼 것을 기억하는 데 쓴다.
  - `kind` · `character_id` · `stat` · `value` · `foreshadow_id` — `RuleProposalSpec` 과 같다.
  - `before: str = ""` — 제안을 만들 때 본 지금 값(화면 표시용).
  - `warning: str = ""` — 같은 스탯을 AI 제안이나 다른 규칙도 바꿀 때(정할 것 7 · 8).
- `Project.state_rules: list[StateRule] = []` — 기본값이 빈 목록이라 옛 `project.json` 이 그대로 읽힌다.
- `StateDelta.rule_proposals: SkipJsonSchema[list[RuleProposal]] = []` — 프로그램만 채운다. `StateDeltaAI` 응답 형식에 들어가지 않는다.
- `StateDelta.rule_off: SkipJsonSchema[list[str]] = []` — 작가가 체크를 푼 규칙 제안의 `key`.
- `DismissedItems.rule_proposals: list[RuleProposal] = []` — 체크를 풀어 반영하지 않은 규칙 제안. 반영 기록에서 다시 보인다.
- 효과 (x)는 02 의 `Activation.conditions` 에 둔다(정할 것 2). 이 일감은 새 필드를 더하지 않는다.
- `StatRecord.source` 의 `Literal["ai", "author"]` 에 `"rule"` 을 더한다. 규칙 제안으로 바뀐 스탯을 기록에서 가려 보인다.
- `statwin.SOURCE` 표시 맵에 `"rule"` 문구(예: ' (규칙)')를 더한다.
- `statwin` 의 출처 합치기는 지금 두 출처가 다르면 `"both"` 로 센다. `"rule"` 이 섞일 때의 표시를 이 일감에서 정한다.
- 조건 값과 규칙 필드는 모두 `str` · `int` · `float` · `list` 로 둔다. dict 타입 필드는 쓰지 않는다. 에이전트가 `StateRule` 을 응답 형식으로 받으면 `tests/test_schema_nodict.py` 가 본다.
- CCv3 · RisuAI 트리거와는 1:1 로 맞지 않는다. [compat.md](../compat.md) 에 'RisuAI 트리거 → 대응 없음, 선언형 규칙으로 옮겨 적음' 한 줄을 더한다.

## 규칙

### 조건 판정

- 조건 어휘는 Q27 의 다섯이다: 상태창 값 비교, 관계 수치 비교(읽기만), 화 번호 · 범위, 복선 상태(심음 · 풀림), 이번 화 플롯에 인물이 나옴.
- 작품 속 시간(`Timeline`) 조건은 미룬다(Q27).
- 조건 판정 함수는 02 가 `context.py` 에 둔 것 하나를 쓴다. 효과 (x)와 (y)가 같은 함수를 부른다.
- 함수는 '어느 상태에서 보는가'를 인자로 받는다. 상태는 `Project` 하나(지금 작품 또는 복사본)와 화 번호 `n` 이다.
- 상태창 값은 `p.state_of(cid)` 의 `stats` 에서 이름으로 읽는다.
- 관계 수치는 `dynamics.find_tie` 로 읽는다. `get_tie` 는 없는 관계를 만들므로 쓰지 않는다.
- 이름이나 id 가 없는 대상(지운 인물, 없는 스탯, 없는 복선)을 가리키는 조건은 맞지 않는 것으로 본다. 상태 규칙 화면에 '없는 대상' 경고를 보인다.

### 효과 (x): 항목 넣기

- 이번 화 `n` 을 쓸 때, 조건은 `n-1` 화 끝의 상태로 본다. 지금 프롬프트가 '인물 현재 상태 (n-1화 종료 시점)'를 쓰는 것과 같다.
- 앞 화를 다시 볼 때 스냅샷을 읽는 규칙은 02 의 '조건 계산' 절을 따른다.
- '이번 화 플롯에 인물이 나옴' 조건은 `n` 화 플롯(`EpisodePlot.characters`)으로 본다.
- 넣기 방식 `always` 와 조건을 함께 적은 항목은 조건이 모두 맞으면 들어가고 활성 이유는 '늘 넣기'다(정할 것 3 · 4).
- 키워드가 있는 항목은 조건이 모두 맞을 때만 키워드로 들어간다. 조건이 하나라도 안 맞으면 들어가지 않는다(정할 것 3).
- 넣기 방식이 끄기(`context = "off"`)인 항목은 규칙으로도 켜지 않는다. 작가가 끈 것을 규칙이 덮지 않는다.
- 예산을 넘기면 Q17 의 활성 이유 차례로 남기고, 뺀 항목의 이름을 프롬프트 보기에 보인다.
- 활성화는 저장된 데이터를 바꾸지 않는다. 판정은 프롬프트 조립 동안 읽기만 한다.
- 단편과 장편 모두에 쓴다(Q18). 효과 (x)의 조건을 하나도 두지 않은 단편은 지금 프롬프트와 같다.

### 효과 (y): 규칙 제안

- AI 가 상태 변경안을 만들면(`pipeline.extract_state`) `clean_delta` 뒤에 `staterules.propose` 가 규칙 제안을 채운다.
- `extract_state` 가 옛 변경안을 이어 쓰는 길(`carried_delta(p, n)` 가 값을 돌려줌)은 `clean_delta` 전에 돌아간다.
- 이 길에서는 옛 `rule_proposals` 를 비우고 `staterules.propose` 로 다시 채운 뒤 돌려준다. 옛 제안은 지금 규칙 · 상태로 계산한 것이 아닐 수 있다.
- 채팅 앱 경로(`web.parse_state`)도 같은 자리에서 채운다.
- 플레이와 반영 뒤 고침은 규칙 제안을 계산하지 않는다(정할 것 13).
- 계산은 두 함수로 나눈다:
  - `staterules.propose_on(sim, p, d, n)` — 이미 흉내 반영한 복사본 `sim` 을 받아 규칙 제안 목록을 돌려준다. `p` 는 반영 전 작품이다.
  - `staterules.propose(p, d, n)` — 복사와 흉내 반영을 한 뒤 `propose_on` 을 부르는 감싸개다.
- `staterules.propose(p, d, n)` 의 계산 차례:
  1. `p` 를 깊은 복사한다(`p.model_copy(deep=True)`).
  2. `d` 에서 규칙 제안을 뺀 복사본을 복사한 작품에 반영한다(`pipeline.apply_delta`). 웹의 `preview` 가 쓰는 흉내 반영과 같은 길이다.
  3. 아래는 `propose_on` 이 한다. 켠 규칙마다 `n` 화 끝의 상태로 조건을 본다.
  4. 조건이 맞은 규칙의 변경을 `RuleProposal` 로 만든다.
  5. 반영 뒤 값과 같은 제안은 버린다(정할 것 6).
  6. 같은 스탯을 바꾸는 제안에 경고를 단다(정할 것 7 · 8).
- 규칙 제안끼리는 잇따라 걸리지 않는다(정할 것 7).
- 저장하지 않는다. 복사본은 버린다.

### 승인 흐름

- 규칙 제안은 상태 승인 화면에 '규칙' 표시를 달고 기본으로 체크한 채 온다(Q22).
- `d.rule_off` 에 있는 `key` 의 제안은 체크를 푼 채 온다. 반영 취소로 돌아온 변경안(`reofferDismissed`)도 같다.
- 작가가 승인 화면에서 체크를 바꿀 때마다 규칙 제안을 다시 계산한다(Q28).
  - 화면은 이미 체크를 바꿀 때마다 `refreshPreview` 로 `POST .../episodes/{n}/preview` 를 부른다(250ms 늦춤).
  - 이 요청이 규칙 제안 목록도 함께 돌려준다.
  - `preview` 는 규칙 제안을 뺀 `d` 로 한 번 흉내 반영한 뒤 `staterules.propose_on` 을 부른다. 흉내 반영과 작품 복사를 한 번만 한다.
  - 화면은 돌아온 목록으로 규칙 제안 줄을 바꾼다. 작가가 체크를 푼 `key` 는 풀린 채 둔다.
- 반영할 때(`web.apply_state`) 최종 선택으로 한 번 더 계산한다(Q28).
  - 반영하는 것은 서버가 고른 항목으로 다시 계산한 목록에서 `rule_off` 를 뺀 것이다.
  - 화면이 보낸 `rule_proposals` 는 반영에 쓰지 않는다. 그 `key` 목록은 다시 계산한 목록과 견주는 데만 쓴다.
  - 두 `key` 목록이 다를 때의 처리는 정할 것 12 다.
  - 체크를 푼 규칙 제안은 `dismissed.rule_proposals` 에 남긴다.
- 규칙 제안의 반영은 `features.APPLY_LAST` 에서 한다.
  - `kind = "stat"` 은 `statwin.merge(p, state, updates, n, source="rule")` 로 반영한다.
  - 바뀐 양(`+3`)도 지금 규칙(`statwin.resolve`) 그대로 값으로 바꾼다.
  - `statwin.merge` 는 `CharacterState` 를 받는다. 흉내 반영 뒤에도 상태(`p.state_of(cid)`)가 없는 인물의 stat 제안은 만들지 않는다.
  - `kind = "resolve"` 는 `foreshadows.resolve(p, fid, n)` 로 반영한다. 이미 회수된 복선은 정할 것 6 으로 제안에 오지 않는다.
- `validate_delta` 는 없는 인물 · 없는 복선을 가리키는 규칙 제안도 막는다.
- 단편과 장편 모두 같다.

### 자동 집필과 `-y`

- 자동 집필은 자기 승인 정책을 따른다(Q22).
- 자동 반영(`autorun` 의 `put`)은 `features.hold` 뒤, `apply_delta` 앞에 `staterules.propose` 로 규칙 제안을 채운다. 기본 체크 항목이므로 그대로 반영한다.
- 멈춤 판정의 복선 회수 검사(`autorun._story_reasons`)는 `delta.foreshadow_resolved` 에 `kind = "resolve"` 인 `rule_proposals` 의 `foreshadow_id` 를 더해 본다.
- 그래야 `stop_on_resolve` · `stop_on_early_resolve` 가 규칙이 회수한 복선에서도 멈춘다.
- 관계 정책(`max_shift` · `stop_on_stage`)의 흉내 반영은 바꾸지 않는다. 규칙 제안은 관계를 바꾸지 않는다.
- 규칙이 바꾼 값과 회수한 복선은 작업 기록에 경고 한 줄로 남긴다(정할 것 10).
- 명령줄 `state -y` 반영도 같은 차례를 쓴다.

### 되돌리기

- 규칙 제안은 상태 변경안의 일부로 반영 기록(`Project.history`)에 남는다.
- 반영 취소(`pipeline.revert`)는 스냅샷으로 상태창 값과 복선을 되돌린다. 상태창 기록은 `statwin.revert`, 복선은 `foreshadows.revert` 가 맡는다.
- 시작 전에 확인할 것: `statwin.revert` 가 `source = "rule"` 기록도 다른 기록과 같이 지우는지.

### 대화 에이전트

- 에이전트는 선언형 규칙을 제안만 한다(Q29). 작가가 적용해야 `Project.state_rules` 에 들어간다.
- 쓰기 종류 `rule` 은 어느 권한 모드에서도 'ask' 다(정할 것 9). `auto_kinds` 로 기억해도 자동이 되지 않는다.
- 적용한 규칙 쓰기는 `renumber` 처럼 `WriteRecord` 에 전 · 뒤 값을 남겨 되돌릴 수 있다(정할 것 9).
- 에이전트는 규칙 제안(승인 화면의 `rule_proposals`)을 만들거나 반영하지 않는다.

## 화면 · 명령줄 · 프롬프트

- 화면 문구는 해요체로 쓴다. 문구 규칙은 `docs/design/README.md` 를 따른다.
- 상태 규칙 화면(정할 것 11):
  - 목록 한 줄: 이름, 켬 · 끔, 조건 요약('주인공 마력 0 이하'), 효과 요약('상태를 기절로 바꾸자고 제안해요').
  - 효과 (x)는 '이 항목을 넣어요: 이야기 요소 이름'으로 보인다. 누르면 그 항목의 활성화 설정으로 간다.
  - 없는 대상을 가리키는 조건 · 변경: '없는 인물이에요' · '없는 스탯이에요' · '없는 복선이에요'.
  - 빈 목록: '아직 규칙이 없어요. 조건과 효과를 골라 규칙을 만들어 보세요.'
- 상태 승인 화면:
  - 규칙 제안은 상태창 · 복선 칸 아래 따로 묶지 않고, 같은 칸에 '규칙' 표시를 달아 둔다. 시작 전에 `docs/design/components/` 의 표시(배지) 컴포넌트를 견줄 것.
  - 줄 문구 예: '규칙 「기절」: 주인공 상태 정상 → 기절'.
  - 경고 예: 'AI 제안도 이 스탯을 바꿔요. 규칙 제안이 나중에 적용돼요.'
  - 409 `stale_rules` 문구(정할 것 12, 확인하면 `force_rules` 로 다시 보냄): '고른 항목이 바뀌어 규칙 제안이 달라졌어요. 다시 확인하고 반영하세요.'
- 화면 모양을 바꾸므로 `docs/design/layout.md` 와 표시 컴포넌트 문서를 고친다.
- 명령줄:
  - `python -m canon staterules <작품>` — 상태 규칙 목록과 켬 · 끔을 보인다. 안내 문구: '상태 규칙 n개 (켬 m개)'.
  - 06 의 `python -m canon rules` 와 하위 명령이 부딪히지 않게 이름을 나눈다.
  - `state` 의 변경안 출력에 규칙 제안 줄을 '[규칙]' 머리로 보인다.
- 프롬프트:
  - 효과 (y)는 프롬프트를 바꾸지 않는다. 상태 변경안 프롬프트(`state_prompt`)에 규칙을 알리지 않는다. 규칙 제안은 프로그램이 따로 만든다.
  - 효과 (x)는 블록 글과 차례를 바꾸지 않는다. 이미 있는 블록(이야기 요소 · 사실 · 인물 · 복선) 안에 들어가는 항목이 늘 뿐이다.
  - 예산은 그 블록이 쓰는 `context.BUDGET` 키 그대로다. 새 키는 두지 않는다.
  - 고친 뒤 `brief` 출력(작업지시서)이 API 요청과 같은지 본다.

## 시험

- 새 시험 `tests/test_staterules.py`:
  - 조건이 맞으면 규칙 제안이 생기고, 안 맞으면 생기지 않는다.
  - 반영 뒤 값과 같은 제안은 생기지 않는다. 새 값 규칙과 이미 있는 항목의 `+항목` 규칙은 조건이 두 화 동안 맞아도 한 번만 걸린다.
  - 바뀐 양(`+3`) 규칙은 조건이 맞는 화마다 걸린다. 화 범위 조건을 넣으면 그 범위에서만 걸린다.
  - 규칙 제안끼리 잇따라 걸리지 않는다.
  - 같은 스탯을 바꾸는 제안에 경고가 붙는다.
  - `staterules.propose` 가 작품을 바꾸지 않는다(호출 전후 `model_dump` 가 같다).
  - 끈 규칙은 계산하지 않는다.
  - 없는 대상을 가리키는 조건은 맞지 않는다.
- `tests/test_staterules.py` 의 승인 흐름:
  - `preview` 응답에 규칙 제안이 있고, 고른 항목에 따라 바뀐다.
  - `apply_state` 가 최종 선택으로 다시 계산하고, 화면이 보낸 `key` 목록과 다르면 409 `stale_rules` 를 돌려준다.
  - `force` 만 보내면 `stale_rules` 를 넘기지 않고, `force_rules` 를 보내야 넘긴다.
  - `rule_off` 의 제안은 반영하지 않고 `dismissed.rule_proposals` 에 남는다.
  - 반영한 스탯 기록의 `source` 가 `"rule"` 이다.
  - 반영 취소가 규칙이 바꾼 스탯과 회수한 복선을 되돌린다.
- 효과 (x): 넣기 방식 `always` 와 상태 조건을 함께 적은 항목은 조건이 맞으면 프롬프트에 들어가고 활성 이유가 '늘 넣기'다.
- 효과 (x): 키워드가 있는 항목은 상태 조건이 안 맞으면 키워드가 나와도 들어가지 않는다.
- 효과 (x): 넣기 방식이 끄기면 들어가지 않는다.
- 자동 집필: 규칙 제안이 반영되고 작업 기록에 경고 줄이 남는다.
- 자동 집필: `stop_on_resolve` 가 규칙이 회수한 복선에서 멈춘다.
- 대화 에이전트: `propose_rule` 이 'all' 모드에서도 'ask' 이고, 적용 뒤 되돌리기가 된다.
- 옛 동작: `Project.state_rules` 가 빈 옛 `project.json` 이 읽히고, 상태 변경안과 프롬프트 스냅샷이 바뀌지 않는다.
- `tests/test_delta_count.py` 가 `review.js` 의 `DELTA_LISTS` 와 `StateDelta` 목록 칸을 맞춰 본다. `rule_proposals` 를 양쪽에 더한다.
- `tests/test_schema_nodict.py` 가 에이전트 응답 형식의 `StateRule` 을 본다.
- 가짜 응답: 에이전트 `propose_rule` 을 `canon/mock_staterules.py` 에 둔다.
- 화면 계산(체크 바꿈 → 규칙 제안 줄 바꿈)은 node 시험 꼴로 본다. 시작 전에 `review.js` 의 기존 node 시험이 있는지 확인할 것.
- 고친 기능의 시험만 빠르게: `CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_staterules.py`.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- 정적 검사: `ruff check canon tests scripts`.

## 문서

- README.md: 기능 목록에 선언형 규칙 한 줄을 더한다.
- DESIGN.md: 상태 변경안 · 승인 흐름 장에 규칙 제안(기본 체크, '규칙' 표시, 다시 계산 두 번)을 더한다.
- DESIGN.md: 컨텍스트 조립 장에 상태 조건이 활성화 조건으로 쓰인다는 줄을 더한다. 새 활성 이유는 없다.
- `docs/modules/story.md`: 새 절 `### canon/staterules.py` 를 경로 차례 자리에 넣는다. `canon/static/staterules.js` 도 같은 갈래 파일에 둔다.
- `docs/modules/story.md`: `canon/statwin.py` · `canon/foreshadows.py` 절에 규칙 제안 반영 줄을 더한다.
- `docs/modules/core.md`: `canon/pipeline.py` 절(`extract_state` · `apply_delta`), `canon/web.py` 절(`preview` · `apply_state` · 상태 규칙 엔드포인트), `canon/autorun.py` 절, `canon/cli.py` 절(`staterules` 명령)을 고친다.
- `docs/modules/ai.md`: 가짜 응답 파일 목록에 `canon/mock_staterules.py` 한 줄을 가나다 · 알파벳 차례 자리에 더한다.
- `docs/modules/story.md` 의 `canon/agent.py` 절에 `propose_rule` 과 쓰기 종류 `rule` 을 더한다.
- `docs/modules/web.md`: `review.js` 절에 규칙 제안 줄과 다시 계산을 더한다.
- `docs/modules/` 는 AGENTS.md 의 '문서 줄 규칙'을 지킨다.
- `docs/design/`: 상태 규칙 화면 배치(`layout.md`)와 '규칙' 표시 컴포넌트.
- 이 폴더: [plan.md](../plan.md) 의 07번 상태, [compat.md](../compat.md) 의 트리거 줄, 정한 것이 생기면 [README.md](../README.md) 의 정한 규칙.

## 확인하지 못할 것

- 에이전트의 `propose_rule` 을 실제 Gemini 로 부르는 확인은 키가 있을 때만 한다. 키가 없으면 가짜 응답으로만 본다.
- 작가가 쓸 만한 규칙이 무엇인지, '규칙' 표시와 기본 체크가 승인 화면에서 헷갈리지 않는지는 작가만 판단한다.
- 실제 장편(vocado-dev 의 작품)에서 규칙이 몇 번 걸리는지는 그 데이터로 따로 본다. 이 일감은 작품 데이터를 바꾸지 않는다.
- 사용자가 할 단계:
  1. 상태창이 있는 작품 하나에 효과 (y) 규칙 하나(예: 스탯이 0 이하면 상태를 바꿈)를 만든다.
  2. 그 스탯이 0 이하가 되는 화의 상태 승인 화면을 연다.
  3. '규칙' 표시 제안이 체크된 채 왔는지 본다.
  4. AI 제안 체크를 바꿔 규칙 제안이 따라 바뀌는지 본다.
  5. 반영한 뒤 상태창 기록에서 그 값이 규칙으로 바뀐 것으로 보이는지 본다.

## 비용

- 규칙 계산은 LLM 을 부르지 않는다.
- 에이전트의 `propose_rule` 은 기존 `chat` 단계 호출 안에서 돈다(정할 것 9). 새 호출 경로는 없다.
- 시험은 가짜 응답(`canon/mock_staterules.py`)만 쓴다. LLM 비용 없음.
