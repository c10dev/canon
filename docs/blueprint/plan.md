# 설계도 계획

단기는 차례가 정해진 일감이다.
미룬 것과 장기 후보는 아래 표에 둔다.
일감을 끝내면 그 명세서의 상태 칸과 이 표의 상태를 고친다. 새로 정한 것은 [README.md](README.md) 의 정한 규칙에 더한다.

## 단기

차례는 2026-11-10 에 사용자와 정했다('설계' 세션의 평가 뒤 고친 안).

| 차례 | # | 일감 | 상태 | 명세서 | 먼저 끝날 것 |
|---|---|---|---|---|---|
| 1 | 1 | 스키마 · 저장 검사 · 화 번호 옮기기 (프롬프트 · 화면 없음, LLM 비용 없음) | 끝 ([#476](https://github.com/c10dev/canon/pull/476) 머지) | [01-schema.md](specs/01-schema.md) | — |
| 2 | 2 | 관계 이정표 경고: 관계 속도 점검(`pace`) 넓히기, 이정표끼리 · 지금에서 다음까지 칸 검사(`blueprint.warnings`, 막지 않음) | 끝 ([#477](https://github.com/c10dev/canon/pull/477) 머지) | [02-milestone-warn.md](specs/02-milestone-warn.md) | 1 |
| 3 | 3 | 설계도 화면: 여정 편집과 계획 띠 (사이드바 도구, 관계 카드에서 링크) | 끝 ([#478](https://github.com/c10dev/canon/pull/478) 머지) | [03-journey.md](specs/03-journey.md) | 1 |
| 4 | 4 | 기획 프롬프트(다음 아크 · 장편 화별 플롯)에 지금 범위와 다음 이정표, 예산, mock, 앞당김 실측 | 끝 ([#479](https://github.com/c10dev/canon/pull/479) 머지) | [04-plan-prompt.md](specs/04-plan-prompt.md) | 1 |
| 5 | 5 | 지금 플롯에서 설계도 거꾸로 뽑기(아크 단위)와 승인 화면 | 끝 ([#480](https://github.com/c10dev/canon/pull/480) 머지) | [05-extract.md](specs/05-extract.md) | 1, 3 |
| 6 | 6a | 스토리보드 · 쓰기 · 검수 연결 (프롬프트 줄) | 끝 ([#481](https://github.com/c10dev/canon/pull/481) 머지) | [06-episode.md](specs/06-episode.md) | 4 |
| 7 | 6b | 실제 접촉 기록: 상태 변경안이 닿은 칸을 닫힌 목록에서 고르고 작가가 승인, 자동 집필 · `-y` 는 남겨 둠 | 끝 ([#482](https://github.com/c10dev/canon/pull/482) 머지) | [07-contact.md](specs/07-contact.md) | 6a |
| 8 | 8 | AI 로 설계도 짜기 (설정 · 부 구성 · 작가 메모, 플롯 없이) | 끝 ([#483](https://github.com/c10dev/canon/pull/483) 머지) | [08-draft.md](specs/08-draft.md) | 5 |
| 9 | 9 | 신체 특징을 몸이 드러나는 화에만 스토리보드 · 쓰기 · 검수에 넣기 (LLM 비용 없음) | 끝 ([#485](https://github.com/c10dev/canon/pull/485) 머지) | [09-body.md](specs/09-body.md) | 6a |
| 10 | 10 | 능력 일정 (인물마다 [화 범위, 능력, 등급, 얻는 조건]): 스키마 · 경고 · 화면 · 프롬프트 줄 (LLM 비용 없음) | 끝 ([#490](https://github.com/c10dev/canon/pull/490) 머지) | [10-ability.md](specs/10-ability.md) | 1 ~ 6 |
| 11 | 11a | 작품 전체 띠(쌍마다 한 줄 + 능력 일정 줄)와 쌍끼리 몰림 계산, 개요 '여정 짜기' 덜기 (LLM 비용 없음) | 끝 ([#504](https://github.com/c10dev/canon/pull/504)) | [11-whole.md](specs/11-whole.md) | 10 |
| 12 | 11b | AI 로 작품 전체 짜기: 관계가 있는 모든 쌍(+ 능력 일정)을 부 하나씩 한 번에, 쌍마다 고르는 제안 카드 | 만드는 중 | [11-whole.md](specs/11-whole.md) | 8, 11a |
| 13 | 12 | 능력 일정을 AI 로 짜기 · 지금 플롯에서 거꾸로 뽑기 (인물 단위: 응답 형식 · 작업 둘 · 제안 카드) | 끝 ([#501](https://github.com/c10dev/canon/pull/501) 머지) | [12-ability-ai.md](specs/12-ability-ai.md) | 5, 8, 10 |
| 14 | 13 | 능력 일정에서 스킬 도감 항목 만들기: AI 제안에 도감 초안 함께 받기, 줄의 '도감에 만들기' 버튼 | 끝 ([#502](https://github.com/c10dev/canon/pull/502) 머지) | [13-ability-codex.md](specs/13-ability-codex.md) | 10, 12 |

- 명세서가 '—'인 일감은 시작할 때 `specs/NN-이름.md` 로 쓴다.
- 4 와 6 은 `prompts.py` 를 고친다. 규칙 층(`Settings.rule_layers`, 브랜치 `claude/style-rule-layers`)도 스토리보드 요청 끝을 고치므로 시작 전에 견준다.

## 미룬 것 · 장기 후보

| 후보 | 상태 | 먼저 필요한 것 |
|---|---|---|
| 작품 전체 짜기(11b)가 능력 일정도 함께 받기: 인물 단위는 12 가 맡고, 11b 는 12 의 능력 줄 모델 · 능력 블록 · 능력 묶음을 가져다 쓴다 | 11b 에서 만듦 (2026-11-11) | 12, 11b |
| 설계도 칸 메모 · 이정표 라벨에 적은 신체 특징을 인물 신체 프로필 제안 카드로 내기 | 장기 후보 (2026-11-10, 9 에서 나눔) | 9 |
| 접촉 사다리의 쓰기 줄(`blueprint_write_line`)도 그 화 플롯에 칸이 나올 때만 넣기 | 끝 (2026-11-11 작가 결정, 규칙은 [specs/06-episode.md](specs/06-episode.md)) | 6a |
| 화 끼워 넣기 · 빼기가 완급 계획(`heat`)의 화 번호도 옮기기 | 장기 후보 (2026-11-10 발견: `renumber.py` 가 `heat` 를 옮기지 않음) | — |

- 접촉 사다리 줄이 생성 프롬프트에 들어가는 일감(4 · 6) 전에 이 미룸을 다시 본다.
