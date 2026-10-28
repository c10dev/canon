# NN. 일감 이름

상태: 설계 | 진행 (브랜치, PR) | 끝 (PR) · 계획: [plan.md](../plan.md) 의 NN번

## 목표

작가에게 무엇이 달라지는지 한두 문장. 동작이 바뀌지 않는 일감이면 그렇다고 쓴다.

## 정할 것

시작 전에 사용자와 정할 것. 추천안을 먼저 쓴다. 정하면 결과를 적고 [README.md](../README.md) 의 정한 규칙에도 더한다.

1. 질문 — 추천: …

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|

## 지도 데이터

[layout.md](../layout.md) 에서 읽는 키, 새로 내거나 바꾸는 키. 생성기 `VERSION` · `bldgs.VERSION` 을 올리는지.

## 규칙

계산 규칙과 경계 사례. 숫자에는 근거를 단다.

## 화면 · 명령줄 · 프롬프트

화면 문구는 해요체. 프롬프트에 넣으면 예산(`context.BUDGET`)과 자리(화마다 바뀌는 쪽).

## 시험

- 새 시험: 파일과 무엇을 보는지.
- 스냅샷: 바뀌면 이유.
- 화면 계산은 node 시험(`tests/test_atlas_js.py` 꼴).
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q tests`.
- 웹 엔드포인트나 응답 모델이 바뀌면 `python scripts/make_openapi.py`.

## 문서

README.md · DESIGN.md · AGENTS.md 의 고칠 줄, 이 폴더의 [plan.md](../plan.md) 상태.

## 확인하지 못할 것

실제 Gemini 호출, Swift 빌드(맥), 실제 데이터처럼 이 서버에서 돌릴 수 없는 것과 사용자가 할 단계.
