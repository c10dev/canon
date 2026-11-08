# 06. 정규식 규칙 묶음 (경고 · 고침)

상태: 설계 · 계획: [plan.md](../plan.md) 의 6번 · 먼저: —

## 목표

작가가 정규식 규칙을 묶음으로 만들어 두고, 작품마다 켤 묶음을 고른다.
AI 가 본문을 쓰면 작가가 보기 전에 고침(`fix`) 규칙이 본문을 정해진 대로 바꾸고, 바꾼 곳을 모두 기록해 되돌릴 수 있게 한다.
경고(`warn`) 규칙은 본문을 바꾸지 않고 검수 결과와 함께 걸린 곳을 보여 준다.
예: 말줄임표 표기 통일(고침), 작가가 싫어하는 상투 표현 찾기(경고), 영어 따옴표를 한국어 따옴표로 바꾸기(고침).
이 일감이 따르는 정한 규칙은 [README.md](../README.md) 의 2026-11-08 결정 Q2 · Q4 · Q12 · Q21 · Q26 · Q29 다.

## 정할 것

시작 전에 사용자와 정할 것이다.
추천안을 먼저 쓴다.

1. 고침 기록의 모양 — 추천: 새 기록 `RuleRun` 을 `Episode.rule_runs` 에 둔다. 규칙을 한 번 건 것(규칙 걸기 한 번)이 기록 하나이고, 그 안에 바뀐 곳마다 `RuleChange` 를 둔다.
   - 이유: 본문 수정 기록 `Episode.edits` 는 `pipeline.EDIT_KEEP` = 50 개만 남긴다. 규칙 하나가 한 화에서 수십 곳을 바꾸면 작가가 직접 고친 기록이 밀려난다.
   - 다른 안: `TextEdit` 에 `source = "rule"` 을 더하고 `group` 으로 묶어 `pipeline.undo_fix` 꼴로 되돌린다. 기존 수정 기록 화면을 그대로 쓰지만 위 밀려남 문제가 있다.
2. 규칙을 거는 자리 — 추천: `pipeline.py` 의 `write_episode` · `rewrite_episode` · `polish_episode` · `revise_passage` 가 바뀐 곳 목록 인자(`ruled`)를 받을 때만 규칙을 건다. `_write` 안에서는 걸지 않는다.
   - 이유: 실험 · 비교 호출자도 `write_episode` 를 부른다(`promptlab.py` · `stattrial.py` · `blocktrial.py` · `opening.py` · `pipeline.compare_drafts`). 실험 결과가 작품의 규칙 묶음에 따라 달라지면 비교가 흐려진다.
   - 이 호출자들은 `ruled` 를 넘기지 않으므로 규칙이 걸리지 않는다.
   - 이 모양은 `_write` 의 `cut` 인자(뗀 작업 설명 문단을 채워 돌려줌)와 같다.
   - 규칙은 가장 바깥 입구에서 한 번만 건다. `rewrite_episode` 는 다듬기 모드에서 `polish_episode` 를 부르므로(`pipeline.py` 의 `rewrite_episode`) 받은 `ruled` 를 그대로 넘기고 자기는 걸지 않는다. 두 번 걸거나 두 번 기록하지 않는다.
   - 저장하는 호출자가 인자를 빠뜨리지 않게, 본문을 저장하는 모든 길을 시험이 하나씩 본다(아래 시험).
3. 작품이 묶음을 가리키는 방식 — 추천: id 로 가리킨다(`Settings.rule_bundles`). 묶음을 고치면 켠 작품 모두에 바로 적용된다. 규칙 걸기 기록에 묶음 id 와 버전을 남겨 어느 판의 규칙이 바꿨는지 알 수 있게 한다.
   - 다른 안: 문체 라이브러리처럼 작품에 복사한다(`library.apply` 꼴). 작품마다 따로 굳지만, 표기 규칙을 고칠 때마다 작품마다 다시 가져와야 한다.
4. 바꿀 글(`out`)의 문법 — 추천: RisuAI 정규식 스크립트와 같은 JavaScript 꼴(`$1` · `$&` · `$<이름>` · `$$`)로 저장하고, `canon/regexrules.py` 의 한 함수가 Python `re` 꼴로 바꾼다. 가져오기 · 내보내기 길을 열어 두는 결정(Q26)과 맞는다.
   - `$n` 은 [compat.md](../compat.md) 2-3 과 같이 줄바꿈으로 바꾼다.
   - `@@` 로 시작하는 RisuAI 특수 명령은 받지 않는다. 저장할 때 막고 이유를 보여 준다.
   - 다른 안: Python 꼴(`\1` · `\g<이름>`)로 저장한다. 구현은 짧지만 대응표에 바꾸는 규칙을 따로 적어야 한다.
5. 받지 않는 플래그 — 추천: 규칙 묶음 화면에서 저장할 때 막는다. `y`(sticky) · `v`(유니코드 집합)는 Python `re` 에 맞는 뜻이 없다.
   - `d` 는 막지 않고 무시한다. Canon 은 자리를 늘 센다.
   - RisuAI 의 `<order N>` · `<cbs>` 같은 꺾쇠 메타도 저장할 때 막는다. 차례는 목록 차례로 대신한다.
   - 가져오기(지금 범위 밖, Q26)는 이 검사와 따로 compat.md 2-3 대로 한다: `<order N>` 은 목록 차례로 옮기고, 받지 않는 값은 날것 보관하고 규칙을 꺼 둔 채 넣고 경고한다.
   - 다른 안: 조용히 무시하고 경고만 남긴다. 작가가 기대한 동작과 달라질 수 있다.
   - 이 문서가 정규식 규칙 모델의 원본이다. compat.md 2-1 · 2-3 은 이 문서에 맞춰 두었다(`ableFlag` 는 필드 없음, `d` 는 버림, `<order N>` 은 목록 차례). 이 문서를 바꾸면 같은 변경 안에서 compat.md 2절도 고친다.
6. 느린 정규식 막기 — 추천: 세 겹으로 막는다.
   - 저장할 때: `in` 은 500자까지, 컴파일 오류는 저장을 막는다. 겹친 반복(`(a+)+` · `(a|a)*` 꼴)을 정적으로 찾아 막는다.
   - 걸 때: 한 번의 규칙 걸기를 자식 프로세스에서 돌리고 시간 한도를 2초로 둔다. 넘으면 그 걸기를 건너뛰고 원문을 그대로 두고, 화면과 서버 기록에 어느 묶음에서 멈췄는지 남긴다.
   - 500자와 2초는 출발값이다. 실제 묶음으로 재고 고친다.
   - 비용: macOS 의 기본 시작 방식은 spawn 이라 자식 프로세스마다 새 인터프리터를 띄운다. `revise_passage` 는 후보마다, 자동 집필은 화마다 건다.
   - 걸기 한 번에 드는 덧비용(프로세스 띄우기 시간)을 시작할 때 잰다.
   - 견줄 안: 오래 사는 일꾼 프로세스 하나를 여러 걸기에 다시 쓴다. 또는 프로세스 풀을 쓴다. 한도를 넘은 일꾼은 끝내고 새로 띄운다.
   - 다른 안 1: `regex` 패키지의 시간 한도 인자를 쓴다. 새 의존성이 생기고 `requirements.lock` 을 다시 만들어야 한다. 지금 잠금 파일에 `regex` 는 없다.
   - 다른 안 2: 저장 때 한도와 정적 검사만 둔다. 자식 프로세스 비용은 없지만 정적 검사가 놓친 패턴이 서버를 묶을 수 있다.
7. 경고를 검수 결과에 넣는 방식 — 추천: `pipeline.apply_check` 가 장면 연출 규칙 지적(`stage.episode_issues`)을 합치는 자리에서 경고 규칙 지적도 `Finding` 으로 합친다.
   - `ConsistencyIssue.origin` 에 `"regex"` 를 더한다. `SkipJsonSchema` 라 LLM 응답 형식은 그대로다.
   - 지금 `origin = "rule"` 은 장면 연출 규칙 판정이다(`check.js` 의 '규칙' 표시). 7번 일감의 선언형 규칙 제안도 '규칙' 표시를 쓴다(Q22).
   - 그래서 이 일감은 이름과 표시에 '규칙' 만 쓰지 않는다. 프로그램만 채우는 새 칸은 `regex_rule`(묶음 id · 규칙 id)이다.
   - `source_quote` 는 꼭 있어야 하는 칸이다. 경고 지적은 규칙의 `in` 패턴을 넣는다.
   - 이유: 작가가 '그대로 둠' · '잘못 짚음'으로 정한 지적은 다시 나와도 그대로 두는 `findings.merge` 의 규칙을 그대로 쓴다.
   - 시작 전에 확인할 것: `ConsistencyIssue.type` 은 `IssueType` 값이 꼭 있어야 한다. `IssueType` 에 '표기' 를 더하면 LLM 응답 형식에도 보인다. 응답 형식에서 빼는 방법이나 다른 값을 고른다.
   - 다른 안: 검수 화면에 '규칙 경고' 칸을 따로 두고 `Episode` 에 따로 저장한다. 지적 코드는 건드리지 않지만 그대로 둠 · 잘못 짚음 처리를 새로 만들어야 한다.
8. 자동 집필에서 경고 — 추천: 경고 규칙 지적은 자동 집필의 멈춤 규칙(`Policy.max_issues` 등)에 세지 않는다. 새 정책 칸도 더하지 않는다. 고침 규칙은 손으로 쓸 때와 똑같이 건다.
9. 내보내기 규칙과 `publish.py` — 추천: `publish.py` 의 고정 정리(폭 없는 글자 지우기, 마크다운 제목 · 굵게 풀기, 공백 정리)는 코드로 둔다.
   - 내보내기 규칙(`type = "export"`)은 `publish.export` 가 화마다 본문을 꺼낸 뒤, `format_text` 와 `format_html` 에 넘기기 전에 건다. 글과 HTML 두 결과가 같은 본문에서 나온다.
   - 저장 전 화면 본문(`export` 의 `drafts`)에도 똑같이 건다.
   - `raw` 형식에는 걸지 않는다('Canon 에 저장된 본문 그대로'라는 뜻을 지킨다).
   - 다른 안: 고정 정리를 기본 내보내기 묶음으로 옮긴다. 작가가 끌 수 있지만, 문단 나누기(`publish.paragraphs`)처럼 정규식 하나로 안 되는 정리가 남고 `format_html` 과 함께 맞춰야 한다.
   - 함께 정할 것: RisuAI `editdisplay` 를 `export` 에 맞출지. `editdisplay` 는 화면에 보일 때만 바꾸는 것이라 내보내기와 뜻이 같지 않다.
   - 추천: `export` 에 맞추되 가져올 때 꺼 둔 채 넣고 경고한다. 저장 글을 바꾸지 않는 Canon 자리는 내보내기뿐이다. 정하면 compat.md 2-2 의 `editdisplay` 줄을 맞춘다.
10. 작업지시서로 받은 본문 — 추천: `cli.py` 의 `cmd_import` 처럼 밖에서 받은 본문(`written_by = "import"`)에도 고침 규칙을 건다.
   - 이유: 밖의 AI 가 쓴 본문이라 '본문 생성 직후'에 든다.
   - 작가가 직접 친 본문(웹 `PUT .../text`, `source = "typed"`)에는 걸지 않는다.
   - 어긋남: 웹에서 채팅 앱 본문을 붙여 넣는 길도 `PUT .../text` 다. 코드도 친 글과 붙여 넣은 글을 가리지 못한다(`web.py` 의 본문 저장 주석).
   - 그래서 같은 밖의 AI 글이 명령줄 `import` 로 오면 규칙이 걸리고 웹으로 오면 안 걸린다.
   - 안 1(추천): 웹 본문 칸에 '채팅 앱에서 붙여 넣기' 길을 두고, 그 길로 넣은 본문에만 규칙을 건다. 명령줄과 웹이 같아지고 작가가 친 글은 그대로다.
   - 안 2: 가져온 본문에는 어디서도 걸지 않는다. 명령줄 `import` 도 뺀다. 가장 작지만 밖의 AI 글이 규칙을 거치지 않는다.
   - 안 3: 어긋남을 받아들이고 지금 추천(명령줄만)을 그대로 둔다.
11. 바꿀 글(`out`) 안의 CBS 읽기 매크로(`{{...}}`) — 추천: 지금은 풀지 않는다. 글 그대로 저장하고 저장할 때 경고한다.
   - compat.md 2-3 이 이 결정을 이 명세서로 미뤘다.
   - 5번 일감(CBS 읽기 매크로, Q20 · Q25)이 끝난 뒤 고침 결과에 매크로를 풀지 다시 정한다. 풀면 같은 본문에 같은 결과를 내는지(Q12) 함께 본다.
12. 대화 에이전트의 규칙 제안 — 정함(2026-11-08, Q33): 이 일감(6)에서 만들지 않고 6 뒤의 조각 6b 가 맡는다.
   - 6b 는 07 의 정할 것 9(`propose_rule` 도구, 쓰기 종류 `rule` 은 늘 'ask')와 같은 꼴로 만든다.
   - 6b 는 6 의 저장소 모양이 머지된 뒤 시작한다([plan.md](../plan.md) 의 6b).

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/regexrules.py` (새 파일) | 규칙 묶음 저장소(`root` · `load` · `save` · `entries` · `delete` · `versions` · `restore`, `canon/library.py` 와 같은 꼴) |
| `canon/regexrules.py` | 규칙 검사 `validate`(컴파일, 플래그, `out` 문법, 길이, 겹친 반복) |
| `canon/regexrules.py` | 규칙 걸기 `run(p, text, kind)` → (바뀐 본문, `RuleChange` 목록), 경고 찾기 `hits(p, text)` → 지적 목록 |
| `canon/regexrules.py` | `out` 을 Python 꼴로 바꾸는 `to_python`, 플래그를 `re` 값으로 바꾸는 `flags` |
| `canon/regexrules.py` | 되돌리기 `undo_run(p, n, rid)` · `undo_change(p, n, rid, k)` |
| `canon/schema.py` | `RegexRule` · `RuleBundle` · `RuleBundleVersion` · `RuleChange` · `RuleRun` 모델, `Settings.rule_bundles`, `Episode.rule_runs`, `TextVersion.rule_runs` |
| `canon/schema.py` | `ConsistencyIssue.origin` 에 `"regex"`, 프로그램 칸 `regex_rule` (정할 것 7) |
| `canon/schema.py` | `PassageCandidate` 에 프로그램 칸 `ruled: SkipJsonSchema[list[RuleChange]]` |
| `canon/pipeline.py` | `write_episode` · `rewrite_episode` · `polish_episode` · `revise_passage` 에 `ruled` 인자 (정할 것 2) |
| `canon/pipeline.py` | `replace_text` 에 `rule_runs` 인자: 지난 본문의 기록은 `TextVersion` 으로 따라가고 새 본문의 기록을 넣는다(`meta_cut` 과 같은 길) |
| `canon/pipeline.py` | `set_candidate` · `adopt_candidate`: 새 판 후보의 기록을 후보와 함께 두고, 채택할 때 화로 옮긴다 |
| `canon/pipeline.py` | `apply_passage`: 고른 후보의 `ruled` 를 본문 안 자리로 옮겨 `RuleRun` 하나로 남긴다 |
| `canon/pipeline.py` | `apply_passage`: 작가가 후보 글을 고쳐 넣으면 `pipeline.locate` 로 아직 찾히는 바뀐 곳만 남긴다. 하나도 없으면 `RuleRun` 을 남기지 않는다 |
| `canon/pipeline.py` | `apply_first`: `apply_passage` 를 거치므로 부분 수정과 같이 첫 후보의 `ruled` 를 남긴다 |
| `canon/pipeline.py` | `adopt_draft`: 비교에서 고른 본문에 고침 규칙을 걸고 `replace_text` 에 `rule_runs` 를 넘긴다 |
| `canon/pipeline.py` | `propose_rework`: 재구성 다듬기 결과에 고침 규칙을 걸고 바뀐 곳을 제안과 함께 돌려준다 |
| `canon/reshape.py` | `accept_rework`: 제안의 바뀐 곳을 `Episode.rule_runs` 에 넣는다. 작가가 고친 글이면 `apply_passage` 와 같이 아직 찾히는 곳만 남긴다 |
| `canon/pipeline.py` | `_delete_last`: `ep.edits` · `ep.meta_cut` 을 비우는 자리에서 `ep.rule_runs` 도 비운다. 본문을 비우는 다른 길도 같다 |
| `canon/pipeline.py` | `apply_check`: 경고 규칙 지적을 합친다 (정할 것 7) |
| `canon/autorun.py` | `AutoRunner._write`: `replace_text` 를 거치지 않고 `put` 에서 본문을 바로 넣으므로 `put` 에서 `ep.rule_runs` 도 넣는다 |
| `canon/autorun.py` | `AutoRunner._polish`: `pipeline.replace_text` 를 부르므로 `rule_runs` 를 그 인자로 넘긴다 |
| `canon/web.py` | `_job_write` 의 `save`, 동기 `write_episode`, 새 판 후보 · 부분 수정 경로에 `ruled` 를 넘긴다 |
| `canon/web.py` | `fix_now` · `_job_rework` · 비교 채택 경로가 위 함수의 바뀐 곳을 넘긴다 |
| `canon/web.py` | 웹 붙여 넣기 길 (정할 것 10) |
| `canon/web.py` 또는 새 `canon/routes/regexrules.py` | 묶음 엔드포인트, 규칙 시험 엔드포인트, 고침 되돌리기 엔드포인트 |
| `canon/cli.py` | `write` · `import` 가 규칙을 건다. 새 명령 `rules` |
| `canon/publish.py` | `export` 가 화마다 내보내기 규칙을 건다 (정할 것 9) |
| `canon/static/regexrules.js` (새 파일) | 묶음 목록 · 편집 · 시험 화면 |
| `canon/static/settings.js` | 작품 설정에 켤 묶음 고르기 |
| `canon/static/write.js` · `canon/static/rewrite.js` | 뗀 작업 설명 문단 알림 곁에 고침 알림과 되돌리기 |
| `canon/static/check.js` | 경고 규칙 지적 표시(묶음 · 규칙 이름) |
| `canon/static/app.js` | `#/rules` 길, 아래 메뉴에 '규칙 묶음' |
| `tests/conftest.py` | `_isolate` 가 지우는 목록에 `CANON_RULES` |
| `tests/conftest.py` | `regexrules` 가 모듈 캐시를 두면 `_fresh_caches` 의 목록에 더한다 |

- 프롬프트(`canon/prompts.py`)는 고치지 않는다. 규칙은 본문을 쓴 뒤에 건다.
- 이 일감은 LLM 을 부르지 않는다. `canon/mock.py` 는 고치지 않는다.
- 판정(활성화 조건) 코드가 아니므로 `canon/context.py` 는 고치지 않는다.
- 3(프롬프트 보기) · 8(접은 줄거리)과 고치는 파일이 겹치지 않는다. `canon/schema.py` 는 여러 일감이 고치므로 머지 전에 서로 맞춘다.
- 7(선언형 규칙)은 규칙 묶음 저장소의 꼴을 빌려 쓸 수 있다. 7 이 시작하기 전에 이 일감의 저장소 모양이 굳어야 한다.

## 데이터 · 스키마

전역 저장소:

- 경로는 `<CANON_HOME>/.rules/<id>.json` 이다. 환경 변수 `CANON_RULES` 로 바꾼다(`CANON_STYLES` 와 같은 꼴).
- 묶음 하나가 파일 하나다. id 는 `uuid4().hex[:12]`, 검사 식은 `library.ID_RE` 와 같다.
- 쓰기는 `store.write_atomic` 을 거친다. 깨진 파일은 목록에서 건너뛴다.
- 추천: 모듈 캐시를 두지 않고 부를 때마다 파일을 읽는다.
- 캐시를 두면 `tests/conftest.py` 의 `_fresh_caches` 목록에 더한다.

`RegexRule` (RisuAI 정규식 스크립트의 필드를 따른다, Q26):

| 필드 | 타입 | 기본값 | 뜻 |
|---|---|---|---|
| `id` | str | 새로 만든 짧은 id | 기록 · 지적이 가리키는 이름 |
| `comment` | str | `""` | 규칙 이름. 화면과 지적에 보인다 |
| `in_` (JSON 키 `in`) | str | `""` | 찾을 정규식. 비면 걸지 않는다 |
| `out` | str | `""` | 바꿀 글(정할 것 4). 경고 규칙에서는 쓰지 않는다 |
| `type` | `Literal["output", "export"]` | `"output"` | `output`: 쓴 본문에 건다. `export`: 내보낼 때만 건다 |
| `flag` | str | `"g"` | 플래그 글자 |
| `action` | `Literal["warn", "fix"]` | `"warn"` | Canon 이 더한 필드. 경고 또는 고침 |
| `enabled` | bool | `True` | 묶음 안에서 이 규칙만 끈다 |

- `in` 은 Python 예약어라 필드 이름은 `in_` 로 하고 JSON 키는 별칭 `in` 으로 둔다.
- 시작 전에 확인할 것: 저장소 코드는 지금 별칭으로 내보내는 곳이 없다(`by_alias` 를 쓰는 곳 없음). `regexrules.save` 와 응답 모델이 별칭으로 내보내는지 시험으로 본다.
- `action` 기본값을 `warn` 으로 둔다. 새 규칙이 저장하자마자 본문을 바꾸지 않게 하려는 것이다.
- `type = "export"` 인 규칙은 `action = "fix"` 만 뜻이 있다. 저장할 때 `warn` 이면 막는다.

`RuleBundle`:

- `id`, `name`, `notes`, `rules: list[RegexRule]`, `created_at`, `updated_at`, `version`, `versions: list[RuleBundleVersion]`.
- `RuleBundleVersion` 은 `number`, `at`, `note`, `rules` 다. 규칙 목록이 바뀔 때만 새 버전을 남긴다(`library._snapshot` 과 같은 꼴).
- 남기는 버전 수는 `library.VERSION_KEEP` = 30 과 같게 시작한다.

작품 쪽:

- `Settings.rule_bundles: list[str] = []`: 켠 묶음 id. 목록 차례가 거는 차례다.
- 기본값이 빈 목록이라 옛 `project.json` 은 고치지 않고 읽히고 동작도 그대로다.
- 지워진 묶음 id 는 건너뛰고 화면에 '찾을 수 없는 묶음' 으로 알린다(`Settings.model_preset` 이 지워진 프리셋을 다루는 방식과 같다).

고침 기록 (정할 것 1의 추천안):

- `RuleChange`: `bundle`(묶음 id), `version`(묶음 버전), `rule`(규칙 id), `start`(그 단계의 본문 안 자리), `before`, `after`, `undone: bool = False`.
- `RuleRun`: `id`(`r<N>`), `at`, `kind: Literal["write", "rewrite", "polish", "passage", "import", "auto"]`, `changes: list[RuleChange]`, `skipped: str = ""`(시간 한도로 건너뛴 묶음).
- `Episode.rule_runs: list[RuleRun] = []`, `TextVersion.rule_runs: list[RuleRun] = []`.
- 화마다 남기는 기록 수는 정할 때 함께 정한다. 출발값은 `EDIT_KEEP` 과 같은 50 이다.
- 본문을 비우는 길(`pipeline._delete_last` 등)은 `ep.edits` · `ep.meta_cut` 과 함께 `ep.rule_runs` 를 비운다. 지운 본문의 기록이 남지 않게 하려는 것이다.
- 이 모델들은 LLM 이 채우지 않는다. dict 필드를 쓰지 않는다.

이름 대응:

- RisuAI 정규식 스크립트와 Canon 필드의 1:1 대응은 이 폴더의 [compat.md](../compat.md) 2절에 있다. 이 문서를 바꾸면 compat.md 2절의 해당 줄도 고친다.
- 맞출 줄: `in` → `in_`(JSON `in`), `out` → `out`, `type` → `type`, `flag` → `flag`, `comment` → `comment`, 대응 없음 → `action` · `enabled` · `id`.
- `ableFlag` → 대응 없음. Canon 은 늘 `flag` 를 읽는다. compat.md 2-1 은 '가져올 때 거짓이면 `flag` 를 `g` 로 바꾼다'로 적었다.
- `type` 값: `editoutput` → `output`, `editinput` · `editprocess` → 대응 없음(Canon 에 대화 입력이 없고, 프롬프트 문구는 `prompts.py` 가 정한다).
- `editdisplay` → `export` 는 정할 것 9 에서 정한다.

## 규칙

거는 차례:

1. `Settings.rule_bundles` 의 차례대로 묶음을 연다.
2. 묶음 안에서는 목록 차례대로 `enabled` 이고 `type` 이 맞는 규칙만 건다.
3. 각 규칙은 앞 규칙이 바꾼 본문에 걸린다.
4. 고침 규칙은 `flag` 에 `g` 가 있으면 모든 자리를, 없으면 첫 자리만 바꾼다.
5. 바뀐 곳이 하나도 없으면 `RuleRun` 을 남기지 않는다.

플래그 대응 (`regexrules.flags`):

| 글자 | Python `re` |
|---|---|
| `g` | 모든 자리(없으면 `count=1`) |
| `i` | `re.IGNORECASE` |
| `m` | `re.MULTILINE` |
| `s` | `re.DOTALL` |
| `u` | 무시한다. Python 문자열은 늘 유니코드다 |
| `d` | 무시한다. Canon 은 자리를 늘 센다 |
| `y` · `v` | 받지 않는다 (정할 것 5) |

- 시작 전에 확인할 것: JavaScript 와 Python 정규식의 차이(이름 붙은 묶음 `(?<이름>…)` 문법, `\d` · `\w` 가 유니코드 숫자 · 글자를 받는지, `\p{…}` 지원)를 Python 3.12 에서 재고 대응표와 검사 함수에 적는다.

거는 자리 (Q21):

- 처음 쓰기: `write_episode` 의 결과를 저장하기 전에 고침 규칙을 건다. `metatail.parts` 가 작업 설명 문단을 뗀 뒤다.
- 다시 생성: `rewrite_episode` 의 결과를 새 판 후보(`Episode.candidate`)에 넣기 전에 건다.
- 다듬기: `polish_episode` 의 검사(`polish_problem` · `polish_tics`)를 통과한 결과에 건다. 검사가 규칙이 바꾼 글자 수 때문에 다시 부르지 않게 하려는 것이다.
- 부분 수정: `revise_passage` 의 후보마다 걸어 작가가 고르기 전에 바뀐 후보를 보여 준다.
- 작가가 후보 글을 고쳐 넣으면(`apply_passage` 의 `text`) 아직 찾히는 바뀐 곳만 남긴다.
- 'AI에게 고치기'(`web.fix_now` → `pipeline.apply_first`): 첫 후보가 바로 본문에 들어간다. 부분 수정과 같이 건다.
- 비교 채택(`pipeline.adopt_draft`): `compare_drafts` 는 `ruled` 없이 쓰므로 고른 본문에 채택할 때 건다.
- 재구성 다듬기(`pipeline.propose_rework` → `reshape.accept_rework`, 웹 `_job_rework`): AI 가 다듬은 글이므로 제안을 만들 때 건다.
- 자동 집필: `AutoRunner._write` 와 `_polish` 가 같은 함수를 부른다. 손으로 쓸 때와 결과가 같다.
- 가져오기: 정할 것 10.
- 작가가 직접 고친 본문, 검수 고침안(`apply_fix`), 인과율 영향 분석 수정에는 걸지 않는다. 그 글은 작가가 고른 것이다.

승인과 권한:

- 고침 규칙은 승인 없이 건다. 작가가 직접 쓰고 직접 켠 규칙이고, 같은 본문에는 늘 같은 결과를 내기 때문이다(설계 원칙 '작가가 고른 권한 안에서만 저장').
- 바꾼 곳은 모두 `RuleRun` 에 남긴다. 화면이 몇 곳을 바꿨는지 알린다.
- 경고 규칙은 본문을 바꾸지 않는다. 검수할 때 지금 본문(작가가 고친 뒤 본문 포함)에서 찾는다.
- 경고 지적의 `current_quote` 는 걸린 곳을 품은 문장이다. `description` 은 규칙의 `comment` 다. 심각도는 `low` 로 시작한다.
- 검수 모델이 같은 문장을 짚었으면 경고 지적을 뺀다(`apply_check` 가 장면 연출 규칙 지적에 쓰는 `_same_quote` 와 같다).
- 자동 집필: 정할 것 8. `Episode.auto` 표시는 바꾸지 않는다.

되돌리기:

- 바뀐 곳 하나: `after` 를 `start` 근처에서 찾아(`pipeline.locate`) `before` 로 되돌린다. `pipeline.undo_edit` 과 같은 길이다.
- 규칙 걸기 한 번: 바뀐 곳을 거꾸로 하나씩 되돌린다. 그 뒤 작가가 같은 자리를 고쳐 찾지 못한 곳은 남기고 몇 곳을 남겼는지 알린다(`pipeline.undo_fix` 와 같은 처리).
- 되돌리기는 `before_change` 를 부른다. 상태 반영이 끝난 화도 다른 본문 수정과 똑같이 다룬다.
- 본문이 새 판으로 바뀌면(`replace_text`) 지난 본문의 기록은 그 판(`TextVersion.rule_runs`)으로 따라간다.

느린 정규식:

- 정할 것 6.
- 걸기를 건너뛰면 본문은 원문 그대로 저장한다. 쓰기를 실패로 돌리지 않는다.

대화 에이전트 (Q29):

- `canon/agent.py` 는 규칙 묶음을 쓰거나 고치지 않고, 작품의 `Settings.rule_bundles` 도 고치지 않는다. 어느 권한 모드에서도 같다.
- 에이전트가 규칙을 제안하고 작가가 적용하는 길(Q29)은 정할 것 12 에서 정한다. 지금 에이전트는 플롯 주제만 맡는다(`agent.TOPICS`).

단편 · 장편:

- 단편과 장편에서 똑같이 동작한다. 규칙은 컨텍스트 예산과 관계없다.

## 화면 · 명령줄 · 프롬프트

규칙 묶음 화면 (`#/rules`, `canon/static/regexrules.js`):

- 아래 메뉴의 '문체 라이브러리' 곁에 '규칙 묶음' 을 둔다.
- 목록: 묶음 이름, 규칙 수(경고 · 고침), 켠 작품 수.
- 편집: 규칙마다 이름 · 찾을 정규식 · 바꿀 글 · 플래그 · 경고/고침 · 쓴 본문/내보내기 · 켬.
- 시험: 붙여 넣은 글이나 작품의 한 화를 골라 걸면 바뀐 곳과 걸린 곳을 보여 준다. 저장하지 않는다.
- 저장할 때 검사에 걸리면 '이 정규식은 저장할 수 없어요: …' 처럼 이유를 보여 준다.
- 버전 목록과 '이 버전으로 되돌리기' 는 문체 라이브러리와 같은 모양이다.

작품 설정 (`canon/static/settings.js`):

- '정규식 규칙' 칸에 묶음을 켜고 끄는 체크와 차례 바꾸기를 둔다.
- 지워진 묶음은 '찾을 수 없는 묶음이에요' 로 보인다.

쓰기 · 새 판 화면:

- 본문을 쓴 뒤 '규칙으로 N곳 고쳤어요' 를 뗀 작업 설명 문단 알림 곁에 보여 준다.
- 펼치면 바뀐 곳마다 규칙 이름과 전 · 뒤 글, '되돌리기' 가 있다. '모두 되돌리기' 도 있다.
- 시간 한도로 건너뛰었으면 '규칙 묶음 ○○을 거는 데 너무 오래 걸려서 건너뛰었어요' 를 보여 준다.

검수 화면:

- 경고 규칙 지적은 다른 지적과 같은 목록에 나오고 '정규식 · {규칙 이름}' 표시가 붙는다.
- '규칙' 표시는 지금처럼 장면 연출 규칙 판정(`origin = "rule"`)에만 쓴다.

엔드포인트 (이름은 구현 때 정한다):

- `GET` · `POST /api/rules`, `GET` · `PUT` · `DELETE /api/rules/{bid}`.
- `GET /api/rules/{bid}/versions`, `POST /api/rules/{bid}/versions/{number}/restore`.
- `POST /api/rules/test`: 묶음이나 규칙과 글을 받아 걸어 본 결과를 돌려준다. 저장하지 않는다.
- `POST /api/projects/{name}/episodes/{n}/rule-runs/{rid}/undo`, `POST .../rule-runs/{rid}/changes/{k}/undo`.
- 작품의 켠 묶음은 지금 작품 설정 저장 경로로 바꾼다.

명령줄:

- `python -m canon rules list`: 묶음 목록.
- `python -m canon rules test <묶음 id> <파일>`: 글 파일에 걸어 본 결과를 찍는다.
- `python -m canon rules use <작품> <묶음 id>` · `rules drop <작품> <묶음 id>`: 작품에서 켜고 끈다.
- `write` · `import` 는 고친 곳 수를 '규칙으로 N곳 고쳤어요' 로 찍는다.

프롬프트:

- 바꾸지 않는다. 규칙 내용을 쓰기 프롬프트에 넣지 않는다(블록 문구는 `prompts.py` 가 정한다, Q10).
- `brief` 출력도 바뀌지 않는다.

디자인 문서:

- 새 화면과 알림 모양은 `docs/design/layout.md` 와 쓰는 컴포넌트 문서에 더한다.

## 시험

- 새 시험 `tests/test_regexrules.py`:
  - 저장소: 만들기 · 읽기 · 고치기 · 버전 · 되돌리기 · 지우기, 깨진 파일 건너뛰기, `CANON_RULES` 경로.
  - JSON 키가 `in` 으로 저장되고 읽히는지.
  - 검사: 컴파일 오류, 받지 않는 플래그, RisuAI 전용 `out`, 길이 한도, 겹친 반복을 막는지.
  - `to_python`: `$1` · `$&` · `$<이름>` · `$$` · `$n`(줄바꿈) 바꾸기.
  - 플래그 대응: `g` 없음은 첫 자리만, `i` · `m` · `s`.
  - 거는 차례: 묶음 차례, 규칙 차례, 앞 규칙 결과에 뒤 규칙이 걸림, 꺼진 규칙 · `export` 규칙은 쓰기에서 안 걸림.
  - 되돌리기: 하나 · 한 번 전체, 뒤에 작가가 고친 자리는 남김.
  - 시간 한도: 느린 패턴이 한도 안에 끝나고 원문이 그대로 남는지.
- 저장 경로 시험: 웹 쓰기 작업, 동기 쓰기, 명령줄 쓰기 · 가져오기, 새 판 후보 · 채택, 부분 수정 적용, 자동 집필 쓰기 · 다듬기가 모두 규칙을 걸고 기록을 남기는지 하나씩 본다.
- 같은 저장 경로 시험에 'AI에게 고치기'(`apply_first`), 비교 채택(`adopt_draft`), 재구성 다듬기(`propose_rework` · `accept_rework`)도 넣는다.
- 다듬기 모드의 `rewrite_episode` 가 규칙을 한 번만 걸고 `RuleRun` 을 하나만 남기는지 본다.
- 작가가 후보 글을 고쳐 `apply_passage` 로 넣으면 찾히지 않는 바뀐 곳이 기록에서 빠지는지 본다.
- `_delete_last` 뒤에 `ep.rule_runs` 가 비는지 본다.
- 실험 경로(`write_episode` 를 부르는 `promptlab` · `stattrial` · `blocktrial` · `opening` · `compare_drafts`)는 `ruled` 를 넘기지 않아 규칙이 걸리지 않는지 본다.
- 검수: 경고 규칙 지적이 `origin = "regex"` 로 합쳐지고, 그대로 둠으로 정한 지적이 다시 나와도 그대로인지.
- 내보내기: `export` 규칙이 걸리고 `raw` 형식에는 안 걸리며 저장된 본문은 그대로인지.
- 내보내기: 글(`text`)과 HTML(`html`) 결과에 같은 규칙이 걸리는지, `drafts` 본문에도 걸리는지.
- 옛 동작: `Settings.rule_bundles` 가 비면 본문 · 기록 · 검수 결과가 지금과 같은지, 옛 `project.json` 이 읽히는지.
- 응답 형식: `PassageCandidate.ruled` 가 LLM 응답 형식에 없는지(`tests/test_schema_nodict.py` 와 같은 꼴).
- `tests/conftest.py` 의 지우는 목록에 `CANON_RULES` 를 더한다.
- 고친 기능만: `CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_regexrules.py`.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- 정적 검사: `ruff check canon tests scripts`.

## 문서

- `docs/modules/core.md` 에 새 절 `### canon/regexrules.py` 를 경로 차례 자리(`canon/prompts.py` 와 `canon/reshape.py` 사이)에 더한다.
- `docs/modules/core.md` 에 `canon/static/regexrules.js` 절을 더한다(기능의 py 와 화면 js 는 같은 갈래 파일).
- `docs/modules/core.md` 의 `canon/pipeline.py` · `canon/autorun.py` · `canon/web.py` · `canon/cli.py` 절에 규칙 걸기 줄을 더한다.
- `docs/modules/ai.md` 의 환경 변수 목록에 `CANON_RULES` 를 가나다 · 알파벳 차례로 더한다.
- `publish.py` 를 다루는 절에 내보내기 규칙 줄을 더한다.
- README.md 에 규칙 묶음 기능을 더한다.
- DESIGN.md 에 규칙을 거는 자리, 승인 없이 거는 이유, 되돌리기를 더한다.
- 이 폴더의 [compat.md](../compat.md) 2절에서 이 문서와 어긋나는 줄을 고친다(정할 것 5 · 9, 이름 대응).
- 이 폴더의 [plan.md](../plan.md) 상태 칸과 [README.md](../README.md) 정한 규칙을 고친다.
- 정할 것 12 의 결과에 따라 [plan.md](../plan.md) 에 에이전트 규칙 제안의 일감 줄이나 장기 후보 줄을 더한다.

## 확인하지 못할 것

- 작가가 실제로 쓸 규칙(말줄임표, 따옴표, 상투 표현)이 실제 본문에서 잘못 바꾸는 곳이 있는지는 작가가 봐야 한다.
- 시간 한도 2초와 패턴 길이 500자가 실제 묶음에 맞는지는 묶음이 생긴 뒤에 잰다.
- RisuAI 정규식 스크립트를 그대로 옮겨 왔을 때 같은 결과가 나는지는 가져오기 코드가 없어 지금 확인하지 않는다(Q26).

사용자가 할 단계:

1. 정할 것 1~12 를 정한다.
2. 구현 뒤 자주 쓰는 표기 규칙으로 묶음 하나를 만들고 작품 하나에 켠다.
3. 한 화를 쓰고 '규칙으로 N곳 고쳤어요' 의 바뀐 곳을 읽어 잘못 바뀐 곳이 없는지 본다.
4. 바뀐 곳 하나와 한 번 전체를 되돌려 본다.

## 비용

- 이 일감은 LLM 을 부르지 않는다. LLM 비용 없음.
