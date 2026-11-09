# 05. AI 답 흘려 보이기

상태: 끝 (#445) · 계획: [plan.md](../plan.md) 의 05번 · 먼저: —

## 목표

본문 쓰기가 쓰는 동안 글이 보인다.
대화 패널은 일감 04 로 대화 에이전트 하나가 되므로, 에이전트의 단계 줄과 생각(`Job.note`)으로 진행을 보이는 지금 방식을 따른다.
README 관찰 자.

## 지금 동작 (2026-11-09 확인)

- `canon/llm.py` 의 `LLM` Protocol 은 `json` · `text` 둘뿐이고 둘 다 다 끝난 글을 돌려준다.
- `canon/claude.py` 의 Claude API 경로는 SDK 스트림을 쓰지만 조각을 멈추기 신호 확인에만 쓰고 다 모은 메시지를 돌려준다.
- 화면은 작업 목록을 `pollJobs` 로 받는다. 작업이 도는 동안 800ms 마다 묻는다. 부분 글을 받는 길은 없다.

## 정할 것

1. 서버 → 화면 전달 — 추천: 지금 폴링에 얹는다. `Job` 에 부분 글 필드(`partial: str`)를 두고 작업 하나를 묻는 엔드포인트가 그것을 돌려준다.
   - 대안 SSE(`EventSource`)는 글자가 더 매끄럽다. 다만 프록시 · 휴대폰 백그라운드에서 끊김 처리와 재연결을 새로 만들어야 한다.
   - 폴링 간격 800ms 에서 글이 덩어리로 늘어나 보이는지 먼저 mock 으로 보고, 거슬리면 SSE 로 바꾼다.
2. `LLM` 인터페이스 — 추천: `LLM` Protocol 은 그대로 둔다. 흘려 받을 수 있는 백엔드에만 `text_stream(system, prompt, on_chunk) -> str` 을 둔다.
   - 부르는 쪽은 `getattr(llm, "text_stream", None)` 으로 있으면 쓴다(`research.py` 의 `count_tokens` 꼴).
   - 없는 백엔드(mock 기본, Claude Code, 배치)는 지금처럼 다 끝난 뒤 한 번에 보인다.
   - mock 은 시험용으로 글을 몇 조각으로 나눠 내는 `text_stream` 을 둔다.
3. 구조화 응답(`json`) — 추천: 흘려 보이지 않는다. 대화 에이전트처럼 JSON 을 받는 경로는 지금처럼 단계 줄(`agentStepNow`)로 진행을 보인다.
   - 대화는 일감 04 로 에이전트 하나가 된다(2026-11-09 사용자 결정). 에이전트 단계는 구조화 응답이라 첫 대상이 아니다.
   - 그래서 첫 대상은 본문 쓰기다. 에이전트 답의 글 부분만 흘려 보이는 일은 04 가 끝난 뒤 따로 정한다.
4. 본문 쓰기 — 추천: 쓰는 동안의 글은 본문 칸이 아니라 읽기 전용 미리보기에 보이고, 다 쓴 뒤 지금처럼 저장 · 검수로 이어진다.
5. 사용량 — 추천: `usage.record` 는 끝난 뒤 한 번 부른다. 조각마다 부르지 않는다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/llm.py` | Gemini 백엔드에 `text_stream` (SDK 의 흘려 받기 호출). 로컬(OpenAI 호환) 백엔드에도 `stream=True` 길 |
| `canon/claude.py` | Claude API 백엔드의 `text_stream`: 이미 도는 스트림의 조각을 `on_chunk` 로 넘긴다 |
| `canon/mock.py` | 조각으로 내는 `text_stream` |
| `canon/jobs.py` | `Job.partial` 과 고치는 함수(잠금 아래) |
| `canon/routes/*.py` | 작업 응답에 `partial` |
| `canon/static/app.js` · `write.js` | 도는 쓰기 작업의 `partial` 을 집필 화면의 읽기 전용 미리보기에 그린다. 그 자리만 고치고 화면 전체를 다시 그리지 않는다 |

- LLM 을 부르는 스레드는 지금처럼 `contextvars.copy_context()` 로 띄운다.
- pipeline · cli 에서 SDK 를 바로 부르지 않는다(AGENTS.md).

## 규칙

- 흘려 보이는 글은 아직 저장한 것이 아니다. 끝나지 못하면(멈춤, 오류) 부분 글을 버리고 지금의 실패 알림을 띄운다.
- 멈추기(`cancel`)는 조각 사이에서 듣는다(`claude.py` 의 지금 동작과 같다).
- 부분 글을 그리는 자리는 낭독 칸이 아니다. 다 끝난 답만 지금처럼 `#chat-live` 로 읽는다.

## 시험

- mock `text_stream` 으로 작업의 `partial` 이 늘어나는지, 끝나면 비는지 보는 서버 시험.
- 화면 시험: 도는 쓰기 작업의 `partial` 이 미리보기에 그려지고 다시 그리기 횟수가 늘지 않는지.
- 기존 쓰기 시험(`tests/test_write_js.py`, 쓰기 작업 시험)이 그대로 통과하는지.

## 문서

- `docs/modules/ai.md` 의 `canon/llm.py` 절에 `text_stream` 줄을 더한다.
- `docs/modules/core.md` 의 작업(`canon/jobs.py`) 절에 `partial` 줄을 더한다.
- `docs/modules/web.md` 의 `canon/static/write.js` 절에 부분 글 미리보기 줄을 더한다.
- DESIGN.md 의 LLM 인터페이스 부분을 고친다.

## 확인하지 못할 것

- 실제 Gemini · Claude API 흘려 받기는 키가 있을 때만 확인한다.
- 비용 드는 확인은 AGENTS.md '비용 드는 모델 실험' 규칙 안에서 flash 급 모델 1~2회로 형식만 본다.

## 비용

- mock 으로 개발한다.
- 실호출 확인: flash 급 모델, 본문 쓰기 2회 × 프롬프트 약 20,000자(약 12,000토큰) + 출력 약 5,000자 — 가격표(`python -m canon usage --prices`)로 시작 전에 어림한다.
