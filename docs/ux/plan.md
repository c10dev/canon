# 쓰는 흐름 계획

단기는 차례가 정해진 일감이다.
장기는 아직 정하지 않은 후보다.
일감을 끝내면 그 명세서의 상태 칸과 이 표의 상태를 고친다. 새로 정한 것은 [README.md](README.md) 의 정한 규칙에 더한다.

## 단기

차례는 2026-11-09 에 사용자와 정했다: 작은 것 먼저.
작고 바로 체감되는 것(01 · 02a · 03)을 먼저 하고, 화면 구조를 바꾸는 것(04 · 06 · 07)을 뒤에 둔다.
대화 패널은 따라오게만 하지 않고 대화 에이전트 하나로 합친다(2026-11-09 사용자 결정). 그래서 04 를 넷으로 나눴다.
묶음마다 worktree 를 따로 써서 함께 시작하고, 묶음이 머지되면 다음 묶음으로 간다(2026-11-09 사용자 결정).

| 차례 | # | 일감 | 상태 | 명세서 | 먼저 끝날 것 |
|---|---|---|---|---|---|
| 1 | 01 | 작은 오류 정리 (작품 홈 400 · favicon 404 · mock 안내 중복) | 끝 ([#427](https://github.com/c10dev/canon/pull/427) 머지) | [01-small-fixes.md](specs/01-small-fixes.md) | — |
| 1 | 02a | 짧은 동작의 가림막 늦추기 | 끝 ([#426](https://github.com/c10dev/canon/pull/426) 머지) | [02-busy.md](specs/02-busy.md) | — |
| 2 | 03 | 다시 그려도 본문 칸 지키기 (저장 뒤 Ctrl+Z) | 끝 ([#428](https://github.com/c10dev/canon/pull/428) 머지) | [03-keep-editor.md](specs/03-keep-editor.md) | — |
| 3 | 02b | 화면을 막는 AI 제안을 작업으로 옮기기 (인물 · 상태창 · 이름 · 문체 8곳) | 끝 ([#431](https://github.com/c10dev/canon/pull/431) 머지) | [02-busy.md](specs/02-busy.md) | 02a |
| 10 | 02c | 남은 AI 호출 작업으로 옮기기 (지도 2 · 검수 2 · 삽화 1 · 플레이 1 · 문단 연습장 4 · 연구 5) | 끝 ([#454](https://github.com/c10dev/canon/pull/454) · [#PRNUM](https://github.com/c10dev/canon/pull/PRNUM)). 플레이 1 은 AI 호출이 이미 작업이라 뺌 | [02-busy.md](specs/02-busy.md) 와 #431 본문의 '남은 AI 호출' 표 | 02b |
| 4 | 04a | 대화 패널 하나: 모든 작품 화면에 에이전트 패널, 화면이 기본 대상을 준다 | 끝 ([#433](https://github.com/c10dev/canon/pull/433) 머지). 정할 것 7 고침은 [#435](https://github.com/c10dev/canon/pull/435) 머지 | [04-one-agent.md](specs/04-one-agent.md) | — |
| 4 | 08 | 휴대폰 대화 시트가 화면을 덮지 않게 | 끝 ([#432](https://github.com/c10dev/canon/pull/432) 머지) | [08-phone-sheet.md](specs/08-phone-sheet.md) | 04a |
| 5 | 04b | 에이전트의 본문 고치기 도구 (후보 카드, 작가가 골라 넣음) | 끝 ([#438](https://github.com/c10dev/canon/pull/438) 머지) | [04-one-agent.md](specs/04-one-agent.md) | 04a |
| 5 | 04c | 에이전트의 설정 도구 (설정 · 인물 변경안 카드) | 끝 ([#440](https://github.com/c10dev/canon/pull/440) 머지) | [04-one-agent.md](specs/04-one-agent.md) | 04a |
| 5 | 04d | 에이전트의 문체 도구 (문체 변경안 카드) | 끝 ([#439](https://github.com/c10dev/canon/pull/439) 머지) | [04-one-agent.md](specs/04-one-agent.md) | 04a |
| 9 | 04e | 옛 대화 셋 정리 (전환 줄 · 옛 패널 · chat_send 세 갈래) | 끝 ([#453](https://github.com/c10dev/canon/pull/453)) | [04-one-agent.md](specs/04-one-agent.md) | 04b · 04c · 04d |
| 6 | 05 | AI 답 흘려 보이기 (본문 쓰기 먼저) | 끝 ([#445](https://github.com/c10dev/canon/pull/445) 머지) | [05-streaming.md](specs/05-streaming.md) | — |
| 7 | 06 | 집필 화면에서 상태 변경안 훑고 고르기 | 끝 ([#448](https://github.com/c10dev/canon/pull/448) 머지) | [06-inline-review.md](specs/06-inline-review.md) | — |
| 8 | 07 | 메뉴 · 버튼 줄이기 | 끝 ([#449](https://github.com/c10dev/canon/pull/449) 머지, 정할 것은 추천안대로) | [07-menu-trim.md](specs/07-menu-trim.md) | — |
| 미정 | 09 | 안내 문구 덜어 내기 (개념 하나에 설명 한 번, 내부 용어 지우기) | 설계 | [09-copy-edit.md](specs/09-copy-edit.md) | — |
| 미정 | 10 | AI 상투 기호 빼기 (✦, 판에 박힌 예시 알약) | 설계 | [10-ai-tells.md](specs/10-ai-tells.md) | — |
| 미정 | 11 | 화면 위계 세우기 (주 버튼 하나, 카드 덜기, 토큰 밖 값) | 설계 | [11-hierarchy.md](specs/11-hierarchy.md) | — |
| 4 | 12 | 숫자와 빈 칸 접기 (지표 칩, "비어 있음" 줄) | 끝 ([#434](https://github.com/c10dev/canon/pull/434) 머지) | [12-quiet-data.md](specs/12-quiet-data.md) | — |
| 미정 | 13 | 빼는 규칙 (디자인 시스템 '덜기' 절과 기준 수 시험) | 설계 | [13-subtract-rule.md](specs/13-subtract-rule.md) | 09 · 11 의 세기 |
| 미정 | 14 | 브랜드 손보기 (제목 글꼴, 귤색 자리, 사이드바 아이콘, 시안 먼저) | 설계 | [14-brand.md](specs/14-brand.md) | 11 |

'차례'가 같은 일감(01 · 02a, 04a · 08, 04b · 04c · 04d)은 한 묶음이다.

09 ~ 14 는 2026-11-09 'AI 가 찍어 낸 화면 같은 인상' 분석(README)에서 더했다. 차례는 아직 사용자와 정하지 않았다.
추천 차례: 10 · 12 를 03 다음 묶음으로 한다. 둘 다 작고, 고치는 파일이 02b · 04a 와 거의 겹치지 않는다.
09 · 11 은 04a 뒤에 한다. 대화 패널 소개 글과 패널 열기 버튼을 04a 가 고치기 때문이다.
13 은 09 · 11 이 세기 스크립트와 시험을 만든 뒤에 한다. 14 는 11 뒤에 시안부터 한다.
10 은 `setup.js` 의 ✦ 버튼을 고치고 02b 도 `setup.js` 의 AI 제안 호출을 고친다. 같은 때에 하면 나중에 머지하는 쪽이 rebase 한다.

'먼저 끝날 것'은 코드가 겹쳐서 먼저 머지되어야 하는 일감이다.
02a 와 03 은 둘 다 `app.js` 를 고친다. 02a 는 `run`, 03 은 `drawApp` · `afterDraw` 다. 나중에 머지하는 쪽이 rebase 한다.
08 은 04a 가 정한 패널 열기 상태 위에서 고친다. 같은 묶음이지만 04a 의 패널 자리 함수를 먼저 머지한다.
04b · 04c · 04d 는 모두 `canon/agent.py` 의 도구 표에 줄을 더한다. 도구 표와 승인 카드 틀은 04a 가 만들어 둔다. 세 일감은 서로 다른 도구 파일(`agent_text.py` 꼴)로 나눠 겹침을 줄인다.
05 는 본문 쓰기를 먼저 흘려 보인다. 에이전트 답은 구조화 응답이라 05 의 첫 대상이 아니다(05 의 정할 것 3).
06 과 07 은 다른 일감과 파일이 겹치지 않는다. 07 은 사이드바(`app.js` `sidebar` · `navItems`)를 고치므로 03 과 같은 때에 하면 rebase 를 견준다.

## 장기 후보

| 후보 | 왜 미루나 |
|---|---|
| 본문 자동 저장 | 지금은 저장해야 '반영 뒤 고침' 알림 · 버전이 생긴다. 저장 시점이 사라지면 버전 · 반영 흐름을 다시 정해야 한다 |
| 다시 그리기를 바뀐 곳만 고치기로 바꾸기 (morph) | 03 이 본문 칸만 지킨다. 다른 칸에서도 같은 문제가 보이면 그때 넓힌다 |
| 작업 판 (자동 집필 · 검수 · 지도 생성처럼 여러 작업을 한눈에) | 지금은 알림 창 · 사이드바 배지가 있다. 동시에 여럿 도는 작업이 늘면 Orca 처럼 한 판에 모은다 |
| 자동 집필 · 새 판(다시 생성 · 서술 다듬기)도 흘려 보이기 | #445 는 집필 화면의 본문 쓰기만 흘려 보인다. 자동 집필은 단계마다 화가 바뀌어 미리보기 자리를 정해야 한다 |
| 에이전트가 인물 · 복선 · 지도 화면의 데이터를 고치는 도구 | 04 는 지금 대화 넷이 하던 일만 옮긴다. 다른 화면의 쓰기 도구는 04 를 써 본 뒤 정한다 |
