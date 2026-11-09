# 01. 작은 오류 정리

상태: 끝 (#427) · 계획: [plan.md](../plan.md) 의 01번 · 먼저: —

## 목표

작품 홈을 열 때 콘솔에 오류가 찍히지 않는다.
브라우저 탭에 Canon 아이콘이 보인다.
AI 연결 안내(mock · 키 없음 등)가 한 화면에 한 번만 보인다.
README 관찰 가 · 나 · 다.

## 정할 것

1. 플레이 사본인지 묻는 방법 — 추천: 작품 GET 응답에 이미 플레이 표시가 있으면 그것을 쓰고, 없으면 `GET /api/projects/<이름>/play` 가 플레이가 아닌 작품에 200 과 `null` 을 돌려준다.
   - 지금 `app.js` `routeNow` 는 작품 홈에 올 때마다 `/play` 를 묻는다(`S.homePlayOf`).
   - `routes/play.py` `_play` 는 플레이 사본이 아니면 `ValueError` 를 던지고, 이것이 400 이 된다.
   - `_play` 는 진행 · 되감기 같은 쓰기 경로도 쓰므로 그 경로의 400 은 그대로 둔다. 읽기(`get_play`)만 바꾼다.
2. 아이콘 — 추천: 귤색 점이 붙은 'C' 한 글자 SVG 를 `canon/static/` 에 두고 `index.html` 에 `<link rel="icon">` 을 단다. 색은 `docs/design/tokens.json` 의 `logo` · `brand-2` 값을 쓴다.
3. AI 연결 안내 자리 — 추천: 작품 화면은 사이드바 아래 줄에만 두고, 작품 목록 · 작품 홈 본문의 안내 상자는 사이드바가 접힌 레일 · 900px 이하에서만 보인다.
   - 안내 글은 `home.js` `aiWarning` 한 곳에서 온다.
   - 본문 상자는 `aiNote` 와 작품 목록(`home.js` 의 `warn`), 사이드바 줄은 `app.js` 의 `aiWarning()` 호출이다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/routes/play.py` | `get_play` 가 플레이가 아닌 작품에 `None` 을 돌려준다(응답 모델을 `PlayView \| None`) |
| `canon/static/app.js` | `routeNow` 의 `play` 결과가 `null` 이면 플레이 아님으로 본다 |
| `canon/static/play.js` | `/play` 를 부르는 세 곳이 `null` 을 받으면 지금 400 을 받았을 때와 같게 한다 |
| `canon/static/index.html` | 아이콘 링크 |
| `canon/static/home.js` · `app.js` | 안내 자리 (정할 것 3) |

## 시험

- `tests/` 의 플레이 라우트 시험에 '플레이 아닌 작품의 GET /play 는 200 · null' 을 더한다.
- 쓰기 경로(`/play/advance` 등)가 플레이 아닌 작품에 지금처럼 400 을 돌려주는지 본다.
- 작품 홈을 그리는 JS 시험이 있으면 `null` 경로를 더한다.

## 문서

- `docs/modules/story.md` 의 플레이 라우트 절에 GET 의 새 응답을 한 줄 더한다.
- 안내 자리를 바꾸면 `docs/design/layout.md` 의 사이드바 아래 줄 설명을 고친다.

## 확인하지 못할 것

- 없음. mock 서버와 브라우저 콘솔로 모두 확인할 수 있다.

## 비용

LLM 비용 없음.
