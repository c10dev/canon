# 10. 설계도에 적은 신체 특징을 인물 신체 프로필 제안으로

상태: 진행 (claude/body-from-blueprint, [#486](https://github.com/c10dev/canon/pull/486)) · 계획: [plan.md](../plan.md) 의 10번 · 먼저: 9

## 목표

작가가 설계도의 사다리 칸 메모 · 칸 이름이나 이정표 라벨 · 계기에만 적은 신체 특징(예: '왼쪽 옆구리 흉터를 처음 본다')을, 인물 신체 프로필에 넣을 후보로 받는다.
일감 9 는 신체 프로필(`Character.body`)에 적힌 특징만 몸이 드러나는 화에 넣는다. 설계도에만 적고 프로필에 옮기지 않은 특징은 요청에 들어가지 않았다. 이 일은 그 틈을 메운다.
README 2026-11-10 규칙 '인물 신체 프로필은 평소 프롬프트에 넣지 않고, 이야기가 몸을 쓰는 화에만 골라 넣는다'와 이 일감에서 정한 규칙을 따른다.
2026-11-10 에 사용자가 이 방향('설계도에서 만든 특징을 기반으로 인물 설정')을 말했다.

## 정할 것

1. 특징을 찾는 방법 — 정함(2026-11-10, 사용자가 추천안을 고름): LLM 으로 뽑는다. 메모는 자유 글이라 낱말 목록으로는 목록 밖 특징과 체형을 놓친다. 그 인물이 든 설계도 줄만 모아 한 번 부르고(단계 `plan`), 줄이 없으면 부르지 않는다.
2. 버튼 자리 — 정함(2026-11-10, 사용자가 '두 곳 다'를 고름): 인물 화면 신체 프로필 칸에 '설계도에서 가져오기' 버튼과 제안 카드를 둔다. 설계도 쌍 쪽에는 그 인물의 신체 프로필 칸을 펴 주는 버튼만 둔다(카드는 인물 화면에만).

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/blueprint.py` | `BODY_LINES_MAX`, `body_lines(p, cid)`(재료 줄, LLM 없음) |
| `canon/schema.py` | `BodyFeatureDraft` · `BlueprintBodyDraft`(LLM 응답), `BodySuggestion.evidence`(`SkipJsonSchema`) |
| `canon/prompts.py` | `body_blueprint_prompt`, 갈래 `body_blueprint` |
| `canon/pipeline.py` | `suggest_body_from_blueprint` |
| `canon/mock.py` | `_r_blueprint_body` |
| `canon/web.py` | 작업 `char_body_bp`(`_job_char_ai`), `POST /api/projects/{name}/characters/{cid}/body/blueprint` |
| `canon/static/research.js` | 작업 등록 `char_body_bp`, 동작 `bodyBpAI` |
| `canon/static/cast.js` | `bodyBpHas`, `bodyFields` 의 버튼, `bodySuggestCard` 의 제목 · 근거 |
| `canon/static/blueprint.js` | `bpBodyRow`, 동작 `bpBodyGo` |

## 데이터 · 스키마

- 작품에 새 필드는 없다. 옛 `project.json` 은 고치지 않고 읽힌다.
- LLM 응답 `BlueprintBodyDraft`: `features`(목록: `text` 특징, `quote` 근거 구절), `build`, `build_quote`, `note`. dict 칸은 없다.
- 응답 형식에 키 · 몸무게 · 쓰리사이즈 칸이 없다.
- 화면에 주는 값은 지금 신체 프로필 제안과 같은 `BodySuggestion` 이다. 근거 줄 `evidence` 는 서버가 채우고 `SkipJsonSchema` 로 AI 응답 형식에서 뺀다.

## 규칙

- 재료 줄: 이 인물이 보는 쪽이나 보이는 쪽인 이정표의 라벨 · 계기, 이 인물이 든 사다리의 칸 이름 · 메모. 작가 글이 없는 줄은 뺀다.
- 사다리 메모는 쌍의 것이라 누구 몸인지 적혀 있지 않을 수 있다. 줄에 두 인물 이름을 두고, 프롬프트는 이 인물 몸만 적고 누구 것인지 모르면 note 에 적으라고 한다.
- 재료 줄은 `BODY_LINES_MAX`(60줄)까지다. 넘으면 뒤를 빼고 뺀 줄 수를 프롬프트에 적는다. 설계도 줄 수에 묶여 화수에 따라 커지지 않는다.
- 줄이 없으면 LLM 을 부르지 않고 빈 제안과 안내를 돌려준다.
- 제안하는 칸은 체형 · 신체 특징뿐이다. 키 · 몸무게 · 쓰리사이즈는 내지 않는다. 미성년 인물(`cast.is_minor_age`)도 쓰리사이즈가 비고, 프롬프트에 몸매를 성적으로 묘사하지 말라는 줄이 붙는다.
- 정리: 근거 구절이 재료 줄에 글자 그대로 없으면 뺀다. 지금 특징 묶음(`cast.body_items`)과 띄어쓰기를 빼고 겹치면 뺀다. 같은 답 안에서 겹쳐도 뺀다.
- 체형은 근거가 재료 줄에 있고 지금 체형과 다를 때만 낸다.
- 특징 칸의 제안 값은 지금 값 뒤에 새 특징을 쉼표로 이은 값이다. 화면의 적용(`bodyApply`)이 칸을 통째로 바꾸므로, 적용해도 지금 특징이 남는다. 새 특징이 없으면 특징 칸을 내지 않는다.
- 승인: 제안은 저장하지 않는다. 지금 신체 프로필 제안 카드와 같이 칸별로 지금 값과 견주고, 지금 값이 있는 칸은 기본으로 고르지 않는다. 고른 칸만 `Character.body` 에 넣고 작품 저장으로 남는다.
- 자동 집필과 `-y` 는 이 제안을 부르지 않는다. 화면 전용 작업(`SCREEN_ONLY_JOBS`)이라 `pending.json` 에도 남기지 않는다.
- 작업지시서(`brief`)에는 넣지 않는다. 지금 신체 프로필 제안처럼 화면 전용이다.
- 바뀌지 않는 블록(작품 · 인물 · 지금 체형 · 특징)이 앞, 설계도 줄이 뒤, 요청이 맨 뒤다.
- LLM 호출은 `get_llm("plan")` 뒤의 `llm.json` 이라 `usage.record` 에 잡힌다.
- 인물 화면 버튼은 그 인물의 재료 줄이 있을 때만 보인다(`bodyBpHas`, `blueprint.body_lines` 와 같은 규칙). 설계도 쌍 쪽 버튼도 같다.

## 시험

- `tests/test_body_blueprint.py`: 재료 줄(두 방향 이정표, 쌍의 두 쪽, 상대 이름, 빈 줄 빼기, 상한), 줄이 없으면 부르지 않음, mock 으로 찾고 지금 특징 뒤에 잇기, 근거 없는 · 이미 있는 · 겹친 특징 빼기, 체형 규칙, 프롬프트 차례 · 미성년 줄, 응답 형식에 숫자 칸 · 근거 없음, 웹 경로 · 작업이 저장하지 않음, 화면 버튼 · 카드 · 설계도 쪽 버튼, `bodyBpHas` 와 서버 규칙 대조.
- `tests/test_ai_jobs.py`: 새 작업 `char_body_bp` 와 버튼 `bodyBpAI` 등록.

## 확인하지 않은 것

- 실제 Gemini 호출은 하지 않았다. mock 과 가짜 응답으로만 확인했다.

## 넣지 않는 것

- 설계도 메모를 신체 프로필로 자동으로 옮기기. 작가가 골라야만 바뀐다.
- 키 · 몸무게 · 쓰리사이즈 제안. 이 칸은 지금 'AI 제안 받기'가 맡는다.
- 설계도 쌍 쪽의 제안 카드. 사용자가 고른 '두 곳 다'는 인물 화면에 카드, 설계도 쪽에 길만 둔다.
