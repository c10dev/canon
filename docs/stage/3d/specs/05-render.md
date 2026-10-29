# 05. 렌더러 · 화면 (읽기 전용 3D 보기)

상태: 명세 · 지도: [../README.md](../README.md) 의 05 · 먼저: [01-body.md](01-body.md), [06-three.md](06-three.md) · 시안: [../../mockup-3d.html](../../mockup-3d.html)

## 목표

장면 연출 화면의 평면도 칸에서 '평면도 | 3D' 를 바꾼다. 3D 는 서버가 낸 관절 좌표(`frames`)와 3D 판정 결과를 그리기만 한다. 고치기는 평면도에서만 한다.

## 정할 것

[../README.md](../README.md) 의 정할 것 2(vendor), 3(3D 에서 고치지 않음), 8(안기는 그림에서만 붙임)을 따른다. 이 모듈만의 것:

1. 3D 를 언제 받나 — 추천: '3D' 를 누를 때 `GET …/stage/{n}/{sid}/frames` 를 한 번 받는다. 평면도에서 고치면 3D 칸에 '바뀐 것이 있어요 · 다시 그리기' 띠를 보이고 누르면 다시 받는다(고칠 때마다 서버를 부르지 않는다).
2. 빠진 자세 · 장소 모듈 — 추천: 자세 모듈이 없는 인물은 회색 원기둥과 '이 자세는 아직 3D 가 없어요' 이름표, 장소 모듈이 없으면 종류 기본값 상자로 그린다(01 이 이미 그렇게 낸다).

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/static/stage3d.js` (새) | `import()` 로 three.js 를 늦게 읽고(06), 방 상자 · 마네킹(관절 사이 캡슐) · 접촉 선 · 이름표를 그린다. 카메라 버튼 셋(비스듬히 · 위에서 · 문에서), 재생 슬라이더는 평면도와 같은 `S.stg.beat` 를 쓴다. 박자 사이 0.6초 보간은 관절 좌표를 섞는다. 다크 모드 다시 칠하기, `prefers-reduced-motion`, WebGL 실패 문구. DOM 없는 순수 함수(`s3Frame` 관절 → 캡슐 목록, `s3Mix` 보간, `s3Flags` 판정 → 빨간 접촉 · 인물)는 node 시험 대상 |
| `canon/static/stage.js` | 평면도 칸 머리의 `seg` 에 '3D' 단추 하나, `S.stgView`(plan · 3d), 3D 칸 자리(`<div id="stg-3d">`), 3D 일 때 `stage3d.js` 의 `s3Mount` 를 부른다. 몇 줄만 |
| `canon/web.py` | `GET /api/projects/{name}/stage/{n}/{sid}/frames` → `{"frames": stage3d.frames(...).to_dict(), "violations3d": [...], "missing": stage3d.missing()}`. 기존 stage 엔드포인트 옆에 하나 |
| `tests/test_stage3d_js.py` (새) | node 로 순수 함수 |
| `tests/test_stage3d_web.py` (새) | 엔드포인트 응답 모양, 없는 장면 404 |

`index.html` 은 고치지 않는다(늦게 읽음). `canon/stage3d/` 의 계산 파일은 읽기만 한다.

## 계약 (입력 · 출력)

- 입력: [01-body.md](01-body.md) 의 `Frames.to_dict()` JSON, 04 의 `Violation` 목록(이 박자 · 이 인물 · `contact`).
- 출력: 화면. 좌표 바꾸기는 (x, y, z) → three.js (x, z, y).
- 빨강: 판정이 짚은 박자 · 인물의 이름표, `contact` 가 있으면 그 접촉 선만. 마네킹 팔이 모자란 틈은 회색 점선(시안 규칙, 3D 가 두 번째 판정기가 되지 않게).
- 그림에서만 하는 것: 안다 · 끌어안다 두 사람을 0.34 · 0.30m 로 붙인다(정할 것 8). 판정 값과 다르다고 화면 아래에 적는다.

## 규칙

- 시안의 겉모습을 따른다: 앱 CSS 변수에서 색을 읽고, 이름표는 DOM 글자(`CSS2DRenderer`), 접촉 선은 몸에 가려도 보이게.
- 접근성: 캔버스 `role="img"` 와 박자마다 바뀌는 `aria-label`, `aria-live` 글 요약, 카메라 버튼, 캔버스 초점 때 방향키. 같은 내용을 평면도 화면의 박자 · 인물 칸이 이미 글로 보인다.
- 좁은 화면(900px 이하)은 평면도 칸과 같은 자리 · 같은 탭을 쓴다.
- 문구 해요체.

## 시험

- `tests/test_stage3d_js.py`(node): `s3Frame` 이 관절 JSON 을 캡슐 목록으로, `s3Mix` 가 두 박자 사이를 섞고 끝값이 같고, `s3Flags` 가 `contact` 가 있으면 그 선만 빨갛게.
- `tests/test_stage3d_web.py`: 가짜 등록부로 frames 응답 키, `missing` 목록, 404.
- 브라우저: 넓은 · 375px, 다크 모드, 재생, 콘솔 오류 없음(시안 때와 같은 확인). 사진을 PR 에 붙인다.
- 전체 시험.

## 문서

AGENTS.md 표에 `static/stage3d.js` 줄. README.md · DESIGN.md 의 장면 연출 절에 3D 보기 한 문단. 이 폴더 README 상태 표.

## 확인하지 못할 것

실제 휴대폰 성능 · 발열, 화면 읽기 프로그램. 사용자에게 휴대폰에서 한 번 열어 보라고 적는다.
