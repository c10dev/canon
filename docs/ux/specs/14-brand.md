# 14. 브랜드 손보기

상태: 설계 · 계획: [plan.md](../plan.md) 의 14번 · 먼저: 11

## 목표

Canon 화면이 흔한 관리 화면과 구별되고, 소설을 쓰는 작업대의 결이 보인다.
README 관찰 서. 취향 판단이 큰 일감이라 시안을 먼저 보고 사용자가 고른다.

## 지금 (2026-11-09)

- 화면 글꼴은 Noto Sans KR 14px, 제목도 같은 글꼴이다. 원고만 Noto Serif KR 이다(`docs/design/README.md` 의 '글자').
- 브랜드 색 '먹 · 귤' 중 귤색(`brand-2`)은 로고 끝 점에만 쓴다.
- 사이드바 도구 아이콘은 토스페이스 이모지다(`docs/design/README.md` 의 '표시와 그림').
- 바탕은 회색 면, 덩어리는 흰 카드다.

## 정할 것

1. 제목 글꼴 — 추천: 화면 제목(`h1`)과 작품 제목만 serif(본문과 같은 Noto Serif KR 또는 다른 한글 명조)로 바꾼 시안을 본다. 화면 글자는 sans 그대로다.
2. 귤색 자리 — 추천: '지금 단계' 표시, 작품 칸의 지금 화 같은 '여기' 표시 한두 곳에 귤색을 쓰는 시안을 본다. 버튼에는 쓰지 않는 지금 규칙은 지킨다.
3. 사이드바 아이콘 — 추천: 이모지 대신 선 아이콘 한 벌(가늘고 같은 굵기)을 시안으로 본다. 대안: 이모지를 두되 실험 묶음 같은 드문 항목은 아이콘 없이 글만 둔다.
4. 바탕 — 추천: 원고 화면(집필 · 검수)은 종이 느낌의 따뜻한 흰 바탕 시안을 본다. 대비 기준(`text` 9:1, `muted` 5.5:1)을 지킨다.
5. 시안 방식 — 추천: `docs/design/` 에 시안 HTML(기존 `preview.html` 꼴) 2~3안을 두고 사용자가 고른다. 고른 뒤 토큰과 app.css 를 고친다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `docs/design/` | 시안, 고른 뒤 README · `tokens.json` |
| `canon/static/app.css` (두 `:root` 블록) · `components/bundle.css` | 고른 값 |
| `canon/static/app.js` | 사이드바 아이콘(`navMark`)을 바꾸면 |
| `canon/static/index.html` | 글꼴을 더하면 Google Fonts 줄 |

- 색 토큰을 바꾸면 app.css 의 두 `:root` 와 `docs/design/tokens.json` 을 함께 고친다(`tests/test_design_tokens.py`).

## 시험

- `tests/test_design_tokens.py`.
- 대비 기준을 보는 시험이 있으면 그대로 통과하는지.

## 문서

- `docs/design/README.md` 의 '색' · '글자' · '표시와 그림' 절.

## 확인하지 못할 것

- 어느 시안이 나은지는 사용자만 정한다.
  1. 시안 HTML 을 브라우저로 연다.
  2. 밝은 · 어두운 테마를 모두 본다.
  3. 고른 안을 알려 준다.

## 비용

LLM 비용 없음.
