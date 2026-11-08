# 02. 활성화 묶음(`Activation`) 모델과 판정

상태: 설계 · 계획: [plan.md](../plan.md) 의 2번 · 먼저: 1번

## 목표

작가가 이야기 요소 · 인물 · 복선 · 확정된 사실마다 키워드와 조건을 적어, 그 항목이 어느 화의 프롬프트에 들어갈지 정한다.
조건을 적지 않은 항목은 지금과 똑같이 들어간다. 옛 `project.json` 도 고치지 않고 읽힌다.
넣을지 정하는 판정은 `canon/context.py` 한 곳에서 하고, 예산을 넘겨 뺀 항목의 이름은 프롬프트 보기(03번)에 넘긴다.
용어는 [README.md](../README.md) 용어표를 따른다: 키워드, 보조 키, 제외 키, 재귀, 유지, 넣기 방식, 판정.
따르는 정한 규칙: [README.md](../README.md) 의 2026-11-08 결정 Q2 · Q7 · Q8 · Q9 · Q13(x) · Q17 · Q18 · Q27.

## 정할 것

시작 전에 사용자와 정할 것이다.
추천안을 먼저 쓴다.

1. 키워드를 지금 있는 다른 이름(`aliases`)과 합칠지
   - 추천: 합치지 않는다. `Activation.keys` 는 프롬프트에 보이지 않는 '찾기만 하는 키워드'로 더한다.
   - 이름과 `StoryElement.aliases` 는 지금처럼 키워드로도 쓴다.
   - 까닭: `elements.describe` 가 `aliases` 를 '다른 이름'으로 프롬프트에 찍는다. 찾기용 낱말을 섞으면 프롬프트가 바뀐다.
2. 확정된 사실에 `Activation` 을 어떻게 붙일지
   - 추천: `Project.facts`(`list[str]`)의 타입은 바꾸지 않는다.
   - 추천: 사실 글을 열쇠로 하는 곁 목록 `Project.fact_activations: list[FactActivation]` 을 둔다.
   - 지금 코드: 사실 모델은 따로 없다.
   - 지금 코드: `StateDelta.new_facts` · `Snapshot.facts` · 되돌리기(`pipeline.revert`)가 사실을 문자열로 쓴다.
3. 곁 목록의 사실 글이 바뀌거나 지워지면
   - 추천: 글이 똑같은 사실만 맞춘다. 맞는 사실이 없는 `FactActivation` 은 판정에서 무시한다.
   - 지금 코드: 사실 편집 화면은 없다. 확정 사실은 `static/home.js` 가 읽기만 한다.
   - 지금 코드: 사실은 상태 승인(`review.js`)과 영향 적용(`causal.js`)으로만 더해진다.
   - 사실 글을 고치는 화면이 생기면 그 저장 경로가 곁 목록의 글도 함께 고친다.
4. 보조 키(`secondary_keys`) 안에서 하나만 있으면 되는지 모두 있어야 하는지
   - 추천: 하나만 있으면 된다(키워드 하나 그리고 보조 키 하나).
   - 까닭: CCv3 의 `selective` + `secondary_keys` 와 같아 [compat.md](../compat.md) 대응표가 1:1 이 된다.
5. 새 키워드의 맞추기 방식
   - 추천: `Activation.keys` · `secondary_keys` · `exclude_keys` 는 조사를 아는 맞추기로 찾는다.
   - 그 맞추기는 `context.name_pattern` 의 규칙을 낱말 하나에 쓰도록 뗀 함수다.
   - 이야기 요소의 이름 · `aliases` 는 지금처럼 부분 문자열로 찾는다(`elements.terms` · `elements.relevant`).
   - 01번 측정에서 부분 문자열의 헛맞춤이 많으면 그때 바꾼다.
   - 01번 측정(2026-11-08): 조사를 보는 맞추기로 바꿔도 본문에 '나옴'이 바뀐 요소는 0개였다.
   - 01번 측정의 표본 20화에서 헛맞춤은 1건이었다(다른 요소 이름 '교양 강의동' 속 '강의동').
6. (없앰) 조건만 적은 항목을 '늘'로 세는 규칙은 두지 않는다.
   - 까닭: 이름과 `aliases` 가 늘 키워드로 쓰이므로 '키워드가 없는 항목'을 가를 수 없다.
   - 조건이 맞을 때 늘 넣으려면 넣기 방식 `always` 와 `conditions` 를 함께 적는다.
7. 키워드가 있고 조건도 있는 항목
   - 추천: 조건은 문이다. 조건이 하나라도 맞지 않으면 키워드 직접 발견 · 재귀 · 유지로 넣지 않는다.
   - 넣기 방식 `always` 인 항목도 조건이 있으면 조건이 모두 맞을 때만 넣는다.
8. 재귀 칸의 뜻: 사용자가 고른다.
   - 안 가: 항목마다 켠다(`recursive: bool = False`). 켠 항목이 이번 화에 들어가면 그 글에서 다른 항목의 키워드를 한 번 더 찾는다.
   - 안 가의 근거: 기본값 False 면 재귀가 일어나지 않는다. 그래서 지금 동작(재귀 없음)을 지킨다.
   - 안 나: 작품 전체가 늘 한 단계 재귀하고, 항목마다 끄기만 둔다.
   - [compat.md](../compat.md) 1-1 · 1-2 · 1-3 의 재귀 줄은 지금 안 가(`activation.recursive`)로 적었다. 안 나를 고르면 그 줄들을 고친다.
   - 안 나는 기본값에서도 재귀로 들어가는 항목이 생겨 프롬프트가 바뀐다. 지금 동작을 지키려면 작품 설정으로 재귀를 꺼 두는 기본값이 더 있어야 한다.
   - Q8 은 '재귀는 한 단계까지만'을 정했다. 항목별 켜기나 끄기는 정하지 않았다.
   - 두 안 모두 찾는 글은 이야기 요소의 `description` 과 복선의 `description` 이다. 인물 글은 판정에 쓰지 않는다.
   - 두 안 모두 재귀로 넣은 항목의 글은 또 찾지 않는다(한 단계).
   - 01번 측정(2026-11-08): 요소 글만 되부르면 놓침 −11%, 낭비 +17%였다. 권장 문턱을 넘지 못했다.
   - 고른 안이 안 가가 아니면 compat.md 1-1 · 1-2 · 1-3 의 재귀 줄과 이 명세 '데이터 · 스키마' 의 재귀 줄을 함께 고친다.
9. 유지(`sticky_episodes`)를 무엇으로 셀지
   - 추천: 저장하지 않고 다시 센다.
   - 앞 N화(n-N … n-1) 각각의 찾는 범위에서 키워드로 직접 발견했으면 이번 화에 '유지'로 넣는다.
   - 01번 측정(2026-11-08): 유지 1 · 2 · 3 · 5화는 놓침 −31 · −49 · −58 · −74%, 낭비 +47 · +86 · +114 · +153%였다. 권장 문턱을 넘지 못했다.
   - 까닭: 화 기록을 따로 두지 않으니 되돌리기 · 다시 쓰기에도 맞는다.
   - CCv3 는 한 번 맞으면 끝까지 이어 간다. Canon 은 N화로 끊는다. 이 차이는 [compat.md](../compat.md) '정할 것' 2 가 다룬다.
10. 지금 규칙으로 들어가는 항목이 예산 차례의 어디에 서는지
   - 추천: 이번 화 플롯이 정한 것은 '늘'로 센다.
   - 플롯이 정한 것: `EpisodePlot.characters`, `StoryElement.episodes`, `StoryElement.characters` 와 플롯 인물의 겹침, 아크 `payoffs` 의 복선.
   - 지금 이름 찾기(`named_ids`)와 이야기 요소 이름 찾기는 '키워드 직접 발견'으로 센다.
   - 점수로 고르는 지금 규칙(`pick_facts`, `rank_foreshadows`, `pick_knows`)은 그 블록의 바탕으로 먼저 돌리고 차례를 바꾸지 않는다.
   - 점수로 고른 항목의 이유: 추천은 '늘'이다. 지금 블록이 이미 예산 안에서 고른 것이라 기본값 프롬프트를 지킨다.
   - `exclude_keys` 의 범위: 추천은 키워드 이유(직접 발견 · 재귀 · 유지)에만 쓰는 것이다.
   - 추천안에서는 점수 · 플롯 · 넣기 방식 `always` 로 들어온 항목을 제외 키가 막지 않는다.
   - 다른 안은 점수로 고른 항목도 제외 키가 막는 것이다. 이 안이면 제외 키를 적은 작품의 사실 · 복선 블록이 지금과 달라진다.
   - 키워드로 찾은 항목의 자리: 추천은 점수 목록 뒤다.
   - 추천안에서는 점수 목록과 최근 `FACTS_RECENT` 개를 지금처럼 먼저 넣고, 남은 예산에 키워드로 찾은 항목을 넣는다.
11. 이야기 요소 블록에 예산을 둘지
   - 추천: 장편에만 새 키 `BUDGET["elements"]` 를 둔다. 단편은 예산을 두지 않는다.
   - 값은 01번 측정에서 지금 데이터가 하나도 잘리지 않는 크기로 정한다.
   - 01번 측정(2026-11-08): 장편 4편 81화에서 이야기 요소 블록은 화마다 최대 754자, 평균 274자였다. 1,000자면 하나도 잘리지 않는다.
   - 지금 코드: `elements.episode_block` 에는 예산이 없다.
12. 찾는 범위를 작품 설정으로 둘지
   - 추천: 두지 않는다. 01번 측정이 고른 범위를 `context.py` 의 상수 하나(`SCAN`)로 둔다.
   - 작품마다 바꾸는 일은 03번 블록 설정이 굳은 뒤 다시 본다.
13. 조건 계산을 어디에 둘지
   - 추천: `context.py` 의 함수 `holds(p, n, cond)` 하나로 둔다. 07번 선언형 규칙도 이 함수를 부른다.
   - 까닭: 템플릿의 '판정은 `canon/context.py` 에만 둔다'와 맞는다.
14. 같은 이유 안의 차례
   - 추천: 지금 블록이 고르는 항목끼리는 지금 차례를 그대로 쓴다.
   - 지금 차례: `fit_cast` · `fit_named` 는 비중(단역 먼저 뺌) 다음 목록 차례다. 복선은 `rank_foreshadows`, 사실은 `pick_facts` 점수다.
   - 최근 언급 차례(Q17)는 새 이유(키워드 직접 발견 · 재귀 · 유지)로 들어온 항목끼리만 쓴다.
   - `fit_cast` 의 규칙 "'항상' 조연 · 단역이 없으면(used 0) 다 넣는다"도 그대로 둔다.
   - 까닭: 지금 `fit_cast` · `fit_named` 는 언급 화를 보지 않는다. 플롯 인물을 최근 언급 차례로 남기면 기본값에서도 프롬프트가 바뀐다.
15. 키워드로 들어온 사실 · 복선과 지금 거르기 · 상한
   - 지금 코드: 단편도 사실이 `FACTS_FILTER_FROM` 개를 넘으면 `prompts.relevant_facts` 가 거른다.
   - 지금 코드: 그 거르기는 이번 화 인물 이름이 든 사실과 최근 `FACTS_RECENT` 개만 남긴다.
   - 지금 코드: 장편 복선은 글자 예산이 아니라 `relevant_foreshadows` 의 keep 규칙과 개수 상한 `FORESHADOW_CAP`(`rank_foreshadows`)으로 뺀다.
   - 추천: 단편 사실은 키워드로 찾은 사실을 거르기의 남기는 이유에 더한다.
   - 추천: 장편 복선은 키워드로 찾은 복선도 `FORESHADOW_CAP` 상한 안에서 이유 차례로 남긴다.
   - 다른 안은 키워드로 들어온 항목이 거르기와 상한을 건너뛰는 것이다. 이 안이면 키워드를 적은 작품의 블록이 상한보다 커진다.
16. 복선 · 사실의 늘 넣기와 끄기를 어떻게 적을지
   - 지금 코드: `Foreshadow` 에는 `context` 필드가 없다. 사실의 `FactActivation` 안은 이 명세에서 새로 두는 것이다.
   - 추천: `Foreshadow` 와 `FactActivation` 에 `context: Literal["auto", "always", "off"] = "auto"` 를 둔다. 네 항목이 한 모양을 쓴다.
   - 추천안에서는 `FactActivation.always` 를 두지 않고 `context = "always"` 로 적는다.
   - 추천안의 `Foreshadow.context` 는 `SkipJsonSchema` 로 응답 형식에서 뺀다. `Foreshadow` 는 LLM 응답 형식에 들어 있다.
   - 다른 안: 복선은 늘 `auto` 로 두고 장편 keep 규칙을 '늘'로 센다. 사실은 `FactActivation.always` 만 두고 끄기는 두지 않는다.
17. 사실의 `Activation` 을 저장할 길
   - 지금 코드: `web.py` 에는 사실을 고치는 엔드포인트가 없다.
   - 후보 가: 사실 곁 목록 한 줄을 고치는 새 엔드포인트.
   - 후보 나: 통째 저장(`PUT /api/projects/{name}`)으로 `fact_activations` 를 함께 보낸다.
   - 후보 다: 사실 활성화를 이 일감에서 빼고 뒤 일감으로 미룬다.
   - 추천: 후보 나. 이야기 요소와 인물도 지금 통째 저장으로 고친다. 새 엔드포인트가 필요 없다.
18. 판정을 쓰는 프롬프트 범위
   - 추천: 이 일감은 본문 쓰기(`build_episode_context` · `serial_episode_context`, 장편 `write_head`)와 부분 고치기(`passage_head`)만 바꾼다.
   - 추천안에서 검수, 상태 변경안, 플롯 초안(`plot_facts_states`), 다음 아크 기획(`plan_facts`), 영향 분석, 플레이는 지금 규칙을 둔다.
   - 추천안에서 그 요청들의 예산 키(`check_facts` · `state_secrets` · `plot_facts` · `plot_states` · `plan_facts` · `impact_facts`)도 바꾸지 않는다.
   - 까닭: 검수는 앞선 본문 전체를 보는 예외다. 다른 요청이 같은 항목을 보게 맞추는 일은 01번 측정 뒤 따로 본다.
19. 인물 · 복선 · 사실의 시작 화
   - 지금 코드: 시작 화 필드(`since_ep` · `reveal_ep`)는 `StoryElement` 에만 있다. 복선에는 `planted_ep` 가 있다.
   - 추천: 새 시작 화 필드를 두지 않는다. 복선은 `planted_ep` 를 시작 화로 쓴다.
   - 추천: 인물 · 사실에 시작 화가 필요하면 조건 `episode`(화 범위, Q27)로 적는다.
   - 까닭: Q8 은 시작 화에 이미 있는 필드를 쓰기로 정했다. 같은 뜻의 필드를 둘 두지 않는다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | 새 모델 `Activation` · `Condition` · `FactActivation`, `StoryElement` · `Character` · `Foreshadow` 에 `activation` 필드, `Project.fact_activations` |
| `canon/schema.py` | `Character._prompt_view` 의 pop 목록에 `activation` 을 더한다 |
| `canon/schema.py` | `Foreshadow` 에 `Character._prompt_view` 와 같은 꼴의 직렬화기를 더해 프롬프트용 직렬화에서 `activation`(과 정할 것 16의 `context`)을 뺀다 |
| `canon/schema.py` | `StoryElement` 가 `llm.dump` 로 프롬프트에 찍히는 길이 있으면 같은 꼴의 직렬화기를 더한다 |
| `canon/context.py` | 판정 함수 `activate`, 조건 계산 `holds`, 낱말 맞추기 함수(`name_pattern` 에서 뗌), 찾는 범위 상수 `SCAN`, 예산 차례 `REASONS`, 장편 `BUDGET["elements"]` |
| `canon/elements.py` | `for_episode` · `relevant` 가 판정 결과를 받는다. 판정 자체는 두지 않는다 |
| `canon/prompts.py` | `build_episode_context` · `serial_episode_context` · `passage_head` 가 판정 결과로 이야기 요소 · 곁 인물 · 복선 · 사실을 고른다. 뺀 개수를 블록에 적는다 |
| `canon/prompts.py` | 인물 목록을 직접 `model_dump(exclude={...})` 하는 줄(지금 324행 `"body", "context"`)의 exclude 집합에 `activation` 을 더한다 |
| `canon/foreshadows.py` | `update` 가 `activation`(과 정할 것 16의 `context`)을 받는다. `_copies` 규칙대로 지금 목록과 스냅샷 사본에 함께 적는다 |
| `canon/web.py` | 복선 편집 `PUT /api/projects/{name}/foreshadows/{fid}` 의 요청 모델 `ForeshadowEdit` 에 `activation` 칸을 더한다 |
| `canon/web.py` | 이야기 요소 · 인물 · 사실 곁 목록은 통째 저장 `PUT /api/projects/{name}` 으로 저장한다(정할 것 17). 응답에 `activation` 이 실리는지 확인한다 |
| `canon/static/` 의 편집 화면 | 이야기 요소 · 인물 · 복선 편집 칸에 '언제 넣을까요' 접는 칸 |
| `canon/static/` 의 편집 화면 | 사실은 지금 편집 화면이 없다. 정할 것 17을 정한 뒤 칸을 둘 자리를 정한다 |

- 03번(프롬프트 보기)과 08번(접은 줄거리 고르기)이 `context.py` 의 `BUDGET` 을 고친다. 이 일감은 1번 측정이 끝난 뒤 시작하고, 시작하기 전에 03 · 08 의 브랜치와 고칠 줄을 견준다.
- 04 · 05 · 07 은 이 일감의 `Activation` 모델이 머지된 뒤 시작한다([plan.md](../plan.md)).

## 데이터 · 스키마

새 모델은 LLM 이 채우지 않는다.
`Character` 와 `Foreshadow` 는 여러 LLM 응답 형식 안에 있다. 이 모델이 들어 있는 모든 응답 형식에서 `activation` 필드는 `SkipJsonSchema` 로 뺀다.
`Character` 가 든 응답 형식의 예: `StateDeltaAI.new_characters`, `ArcProposal`, `SetupSuggestion`. `Foreshadow` 가 든 예: `StateDelta.foreshadow_planted`, 시리즈 기획의 `foreshadows`.
`tests/test_schema_nodict.py` 가 `.json(…)` 으로 받는 모든 응답 형식과 그 안의 모델을 본다.
`StoryElement` 는 응답 형식에 없다. 뒤에 응답 형식에 들어가도 막으려고 `StoryElement.activation` 도 `SkipJsonSchema` 로 둔다.
dict 타입 필드는 쓰지 않는다. 조건은 종류(`kind`)와 납작한 칸으로 적는다.

```python
class Condition(BaseModel):
    kind: Literal["stat", "tie", "episode", "foreshadow", "in_plot"]
    character: str = ""       # stat · tie · in_plot: 인물 id
    target: str = ""          # tie: 상대 인물 id
    name: str = ""            # stat: 상태창 항목 이름 / tie: warmth|trust|status|familiarity|grievance
    op: Literal["ge", "le", "gt", "lt", "eq", "ne", "has"] = "ge"
    value: str = ""           # 견줄 값 (문자열로 두고 숫자면 숫자로 견준다)
    from_ep: int = 0          # episode: 0 = 처음부터
    to_ep: int = 0            # episode: 0 = 끝까지
    foreshadow: str = ""      # foreshadow: 복선 id
    status: Literal["open", "resolved"] = "open"   # foreshadow

class Activation(BaseModel):
    keys: list[str] = []            # 찾기만 하는 키워드 (이름 · aliases 에 더함)
    secondary_keys: list[str] = []  # 보조 키: 하나 이상 함께 있어야 함
    exclude_keys: list[str] = []    # 제외 키: 하나라도 있으면 키워드 이유로 넣지 않음
    recursive: bool = False         # 재귀: 이 항목의 글에서 다른 항목을 한 단계 더 찾음 (정할 것 8의 안 가)
    sticky_episodes: int = 0        # 유지: 키워드로 찾은 뒤 N화 더 넣음
    conditions: list[Condition] = []  # 모두 맞아야 함

class FactActivation(BaseModel):
    text: str                 # Project.facts 의 글과 똑같아야 맞춘다
    context: Literal["auto", "always", "off"] = "auto"   # 넣기 방식 (정할 것 16의 추천안)
    activation: Activation = Activation()
```

- `StoryElement.activation: SkipJsonSchema[Activation] = Field(default_factory=Activation)`.
- `Character.activation: SkipJsonSchema[Activation] = Field(default_factory=Activation)`.
- `Foreshadow.activation: SkipJsonSchema[Activation] = Field(default_factory=Activation)`.
- `Project.fact_activations: list[FactActivation] = Field(default_factory=list)` (정할 것 2).
- 지금의 넣기 방식 `context` 필드(`auto|always|off`)는 `Activation` 안으로 옮기지 않는다. '늘'과 '끔'은 지금처럼 `context` 가 정한다.
- 정할 것 16의 추천안이면 `Foreshadow.context: SkipJsonSchema[Literal["auto", "always", "off"]] = "auto"` 를 더한다.
- 기본값(빈 목록, False, 0)이면 판정 결과가 지금 규칙과 같다. 옛 `project.json` 은 고치지 않고 읽힌다.
- 프롬프트용 직렬화는 `activation` 을 뺀다(`Character` 의 `body` · `context` 를 빼는 지금 규칙과 같다).
- 까닭: `llm.dump` 는 모델을 통째로 직렬화한다. `prompts.py` 는 `dump(p.characters)`, `dump(static_characters(p))`, 열린 복선 목록을 그대로 프롬프트에 넣는다.
- 직렬화기가 빼지 않으면 기본값이라도 빈 `activation` 객체가 프롬프트에 찍혀 스냅샷 시험이 깨진다.
- `elements.basis`(영향 낡음 판단)에는 `activation` 을 넣지 않는다. `context` 를 넣지 않는 지금 규칙과 같다.
- `Activation` 은 설정이지 상태가 아니다. `Snapshot` 에 따로 칸을 두지 않는다.
- `Snapshot.foreshadows` 는 `Foreshadow` 사본이라 `activation` 이 함께 실린다. 편집은 `foreshadows._copies` 로 모든 사본에 같이 적어 되돌려도 값이 남게 한다.
- 조건 어휘은 2026-11-08 결정 Q27 의 다섯 가지다. 시간(`Timeline`) 조건은 미뤘다.
- 확률, N화마다, 정규식 키워드는 넣지 않는다(Q8). 등장 시작 화는 `since_ep` 이 이미 맡는다.
- [compat.md](../compat.md) 1절은 아래 대응으로 적어 두었다. 이 절을 바꾸면 compat.md 도 함께 고친다.
  - 가져올 때 CCv3 `keys` 는 첫 키를 이름으로, 나머지를 `Activation.keys` 로 넣는다. `aliases` 에 넣지 않는 까닭은 프롬프트를 바꾸지 않으려는 것이다(정할 것 1).
  - 내보낼 때 CCv3 `keys` 에는 이름, `aliases`, `Activation.keys` 를 차례로 넣는다.
  - `secondary_keys` ↔ CCv3 `secondary_keys` + `selective`
  - `exclude_keys` ↔ `@@exclude_keys`
  - 재귀 줄은 정할 것 8에서 고른 안을 따른다. 안 가면 `recursive` ↔ `@@recursive`, 안 나면 항목별 끄기 ↔ `@@unrecursive` 다.
  - `sticky_episodes` ↔ `@@keep_activate_after_match` (Canon 은 N화로 끊음, compat.md '정할 것' 2)
  - `context = "always"` ↔ CCv3 `constant`
  - `context = "off"` ↔ CCv3 `enabled = false`

## 규칙

판정은 `context.activate(p, n, kind)` 하나가 한다.
결과는 항목마다 (id, 이유, 뺐는지)이고 프롬프트 조립(`prompts.py`)과 프롬프트 보기(03번)가 같은 결과를 쓴다.

### 넣는 이유

이유는 넷이고 예산을 넘으면 이 차례로 남긴다(Q17).

1. 늘: 넣기 방식 `always`, 정할 것 10의 이번 화 플롯이 정한 항목과 점수로 고른 항목.
2. 키워드 직접 발견: 찾는 범위에서 이름 · `aliases` · `keys` 가운데 하나가 나오고, `secondary_keys` 가 있으면 그 가운데 하나도 나오고, `exclude_keys` 는 하나도 나오지 않음.
3. 재귀: 1 · 2 로 들어간 재귀 대상 항목의 글에서 2와 같은 규칙으로 찾음. 한 단계만. 재귀 대상은 정할 것 8에서 고른 안이 정한다.
4. 유지: 앞 `sticky_episodes` 화 안에 그 화의 찾는 범위에서 2로 찾은 적이 있음.

- 넣기 방식 `off` 인 항목은 어느 이유로도 넣지 않는다. 복선 · 사실의 넣기 방식은 정할 것 16을 따른다.
- `exists_at` 을 넘지 못한 이야기 요소(`since_ep > n`)는 넣지 않는다.
- `conditions` 가 하나라도 맞지 않으면 넣기 방식 `always` · 2 · 3 · 4 로 넣지 않는다(정할 것 7).
- 한 항목이 여러 이유에 맞으면 가장 앞 이유 하나만 적는다.
- 우선순위 필드는 두지 않는다(Q17).

### 같은 이유끼리

- 지금 블록이 고르는 항목끼리는 지금 차례를 그대로 쓴다(정할 것 14).
- 예산 안에 다 못 들어가면 새 이유(키워드 직접 발견 · 재귀 · 유지)로 들어온 항목끼리는 가장 최근에 언급된 항목을 남긴다.
- '언급'은 `context.last_seen` 과 같게 n 보다 앞의, 본문이 있는 화만 센다. 플롯 글만 있는 화는 세지 않는다.
- 인물은 지금 `context.last_seen` 을 쓴다. 이 함수는 플롯 인물이거나 본문에 이름이 나온 화를 센다.
- 이야기 요소 · 복선 · 사실은 같은 규칙(본문에 이름 · `aliases` · `keys` 가 나옴)으로 세는 함수를 `context.py` 에 둔다.
- 언급된 화가 같으면 지금 블록의 기존 차례(인물은 support → minor, 앞 차례 먼저)를 따른다.

### 찾는 범위

- 기본값은 01번 측정 결과로 정한다(Q9). 측정이 견주는 셋: 플롯 글만, 플롯 글 + 스토리보드, 여기에 직전 화 끝부분.
- 01번 측정(2026-11-08) 결과: 기본값은 지금 범위다. 넓힌 범위는 문턱을 넘지 못했다(플롯 + 스토리보드 + 끝 1,500자는 놓침 −35%, 낭비 +40%).
- 01번 전의 지금 범위: 장편 인물은 `elements.plot_text(ep)` + 직전 화 끝 1,500자(`NAMED_TAIL`), 이야기 요소는 `plot_text(ep)` 만, 단편 인물은 찾지 않는다.
- 단편의 범위는 지금 그대로 둔다(Q18).
- 단편 인물(곁 인물)은 지금 이름으로 찾지 않는다. `keys` 를 적은 인물만 `plot_text(ep)` 에서 찾는다.
- 단편 이야기 요소는 지금처럼 `elements.relevant` 가 이름 · `aliases` 로 `plot_text(ep)` 에서 찾는다.

### 조건 계산 (`context.holds`)

모든 조건은 읽기만 한다. 값을 쓰는 함수(`dynamics.get_tie` 처럼 없으면 만드는 함수)는 부르지 않는다.

- `stat`: `p.state_of(character)` 의 `stats` 에서 `name` 값을 읽는다. 값과 `value` 가 둘 다 숫자로 읽히면 숫자로 견주고, 아니면 글로 견준다. `has` 는 목록 값(`statwin.resolve` 의 `+항목` 꼴)에 그 항목이 있는지 본다.
- `stat` 값을 숫자로 읽는 규칙(단위 · 쉼표 · `80/100` 의 앞 숫자)은 `statwin.resolve` 와 같게 한다.
- `tie`: `dynamics.find_tie(p.ties, character, target)` 로 읽는다. 없으면 맞지 않는다. `trust` 는 `Tie.trust` 속성을 쓴다.
- `episode`: `from_ep <= n` 이고 `to_ep` 가 0 이거나 `n <= to_ep`.
- `foreshadow`: 그 id 의 `Foreshadow.status` 가 `status` 와 같다. 없는 id 면 맞지 않는다.
- `in_plot`: `character` 가 `p.episode(n).plot.characters` 에 있다.
- 상태창 · 관계 · 복선 상태는 n-1화를 반영한 뒤의 값으로 견준다.
- n-1 이 마지막 반영 화이면 지금 `p.states` · `p.ties` · `p.foreshadows` 를 읽는다.
- n-1 이 마지막 반영 화보다 앞이면 `p.snapshot(n-1)` 의 `states` · `ties` · `foreshadows` 를 읽는다. 앞 화를 다시 쓰거나 새 판을 만들거나 프롬프트 보기 · 작업지시서로 앞 화를 볼 때다.
- 그 스냅샷이 없으면 지금 값을 쓰고, 판정 결과에 지금 값을 썼다고 적는다.
- 07번 선언형 규칙도 같은 `holds` 를 쓴다.

### 단편과 장편

- 두 형식 모두 판정을 거친다(Q18).
- 기본값이면 두 형식 모두 프롬프트가 한 글자도 바뀌지 않는다. 정할 것 14 · 10을 따라 지금 블록의 차례와 규칙을 그대로 쓰기 때문이다.
- 단편은 지금 거르는 규칙(사실의 `FACTS_FILTER_FROM` 거르기)만 쓴다. 키워드로 찾은 사실은 정할 것 15를 따른다.
- 장편은 각 블록의 글자 예산(`cast`, `facts`, `secrets` 와 새 `elements`) 안에서 위 차례로 남긴다.
- 장편 복선은 글자 예산이 아니라 `FORESHADOW_CAP` 개수 상한 안에서 위 차례로 남긴다.

### 승인과 에이전트

- `Activation` 은 작가가 편집 화면에서 적는다. AI 가 키워드를 제안하는 일은 04번이고, 작가가 적용해야 저장한다(Q16).
- 대화 에이전트(`canon/agent.py`)는 이 일감에서 바뀌지 않는다. 키워드 편집 도구는 04번이 더한다(Q29).
- 판정 결과는 저장하지 않으므로 되돌릴 기록이 없다.

## 화면 · 명령줄 · 프롬프트

- 블록 자리는 바뀌지 않는다. 이야기 요소는 '# 확정된 사실' 뒤 '# 이야기 요소', 곁 인물은 '# 이번 화 등장 인물', 복선은 '# 열린 복선', 사실은 '# 확정된 사실' 이다.
- 모두 `static_context()` 뒤의 화마다 바뀌는 쪽이다. 캐시 앞부분(`static_context`, 장편 `write_head`)은 그대로다.
- 인물의 `Activation` 은 곁 인물만 바꾼다. 주역과 '늘' 인물은 지금처럼 `static_context` 의 '# 인물 설정' 에 있다.
- 장편에서 예산을 넘겨 뺀 항목이 있으면 블록에 '(분량 때문에 N개 뺐어요)' 꼴이 아니라 지금 프롬프트 문구 꼴('(… N개 생략)')로 개수를 적는다. 문구는 `prompts.py` 가 정한다.
- 뺀 항목의 이름은 프롬프트에 넣지 않고 판정 결과로 03번 프롬프트 보기에 넘긴다(Q17).
- 편집 화면의 접는 칸 이름: '언제 넣을까요'.
- 칸 문구: '찾을 키워드', '함께 나와야 할 키워드', '나오면 빼는 키워드', '넣은 글에서 한 번 더 찾기', '찾은 뒤 이어 넣을 화 수', '조건'.
- 칸 문구와 용어의 대응: 찾을 키워드 = 키워드, 함께 나와야 할 키워드 = 보조 키, 나오면 빼는 키워드 = 제외 키, 넣은 글에서 한 번 더 찾기 = 재귀, 찾은 뒤 이어 넣을 화 수 = 유지.
- 조건 고르기 문구: '상태창 값', '관계 값', '화 범위', '복선 상태', '이번 화 플롯에 나오는 인물'.
- 안내 문구: '비워 두면 지금처럼 이름이 나올 때 넣어요.'
- 화면 모양을 바꾸면 `docs/design/` 의 해당 컴포넌트 문서를 고친다.
- 명령줄 명령은 더하지 않는다.
- 고친 뒤 `brief` 출력(작업지시서)을 기본값 작품과 키워드를 적은 작품에서 본다.

## 시험

- `tests/test_activation.py`: 기본값 작품에서 단편 · 장편의 `episode_prompt` 와 `episode_brief` 가 바뀌기 전과 같은지.
- 같은 파일: 옛 `project.json`(`activation` 없음)이 읽히고 다시 저장해도 다른 필드가 바뀌지 않는지.
- 같은 파일: `keys` · `secondary_keys`(하나만 있어도 맞음) · `exclude_keys` 의 맞음 · 안 맞음.
- 같은 파일: `recursive` 가 한 단계에서 멈추는지(A → B → C 에서 C 는 들어가지 않음).
- 같은 파일: `sticky_episodes = 2` 면 찾은 화 다음 두 화에 들어가고 세 번째 화에는 들어가지 않는지.
- 같은 파일: 예산을 넘으면 늘 → 키워드 직접 발견 → 재귀 → 유지 차례로 남고, 새 이유끼리는 최근 언급이 남는지.
- 같은 파일: 플롯 인물만 있는 장편 작품에서 `fit_cast` · `fit_named` 의 지금 차례가 그대로인지(정할 것 14).
- 같은 파일: 뺀 개수가 블록 문구에 적히고 뺀 이름이 판정 결과에 있는지.
- 같은 파일: 조건 다섯 가지의 `holds` 와, 관계가 없을 때 `p.ties` 에 새 관계가 생기지 않는지.
- 같은 파일: 5화까지 반영한 뒤 3화 프롬프트의 `stat` 조건이 `p.snapshot(2)` 의 값으로 판정되는지.
- 같은 파일: 인물 · 복선의 프롬프트용 `dump` 결과에 `activation` 낱말이 없는지.
- 같은 파일: 조사를 아는 맞추기(정할 것 5)가 1음절 키워드 · 조사 붙은 키워드를 지금 `name_pattern` 시험과 같게 다루는지.
- `tests/test_schema_nodict.py` 가 그대로 통과하는지(응답 형식에 `activation` 이 없음).
- 프롬프트 스냅샷은 바뀌지 않아야 한다. 바뀌면 기본값이 지금 동작을 지키지 못한 것이다.
- LLM 응답 형식이 바뀌지 않으므로 `canon/mock.py` 는 고치지 않는다. 바뀌면 함께 고친다.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- 정적 검사: `ruff check canon tests scripts`.

## 문서

- DESIGN.md 4장 '컨텍스트 조립': 활성화 묶음, 넣는 이유 넷과 예산 차례.
- README.md: 이야기 요소 · 인물 편집의 '언제 넣을까요' 한 줄.
- `docs/modules/core.md` 의 `### canon/context.py` 절: `activate` · `holds` · `SCAN` · `REASONS` 줄을 하나씩.
- `docs/modules/story.md` 의 `### canon/elements.py` 절: `for_episode` 가 판정 결과를 받는다는 줄.
- 정할 것 8 · 16 을 추천과 다르게 정하면 이 폴더의 [compat.md](../compat.md) 1절의 재귀 줄과 사실 줄을 고친다.
- 이 폴더의 [plan.md](../plan.md) 02번 상태 칸.
- 정할 것을 정하면 [README.md](../README.md) 정한 규칙에 날짜와 함께 더한다.

## 확인하지 못할 것

- 서버 vocado-dev 의 실제 작품에서 기본값 프롬프트가 같은지는 이 일감의 시험이 보지 못한다. 시험은 가짜 작품만 쓴다.
- 키워드 · 조건을 적었을 때 본문 일관성이 나아지는지는 실제 모델 호출과 작가의 읽기가 있어야 안다.
- `BUDGET["elements"]` 의 값은 01번 측정 결과가 있어야 정한다.

사용자가 할 단계:

1. 01번 측정 결과를 보고 정할 것 5 · 11 · 12 를 정한다.
2. 실제 작품 하나를 임시 `CANON_HOME` 에 복사해 이 브랜치로 띄우고, 이야기 요소 하나에 키워드를 적어 작업지시서에 들어가는지 본다.
3. 몇 화를 써 본 뒤 '언제 넣을까요' 칸이 쓰기 쉬운지 판단한다.

## 비용

- 이 일감은 LLM 호출을 더하지 않는다.
- 시험은 가짜 응답(mock)만 쓴다. LLM 비용 없음.
