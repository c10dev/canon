# 06. three.js 들이기

상태: 완료 (2026-10-29, `canon/static/vendor/three/`, 로더 `canon/static/stage3d-load.js` 의 `load3d()`) · 지도: [../README.md](../README.md) 의 06 · 먼저: 없음 · 이어서: [05-render.md](05-render.md)

## 목표

05 렌더러가 쓸 three.js 를 저장소에 넣는다. 작가가 3D 를 열지 않으면 내려받지 않는다.

## 정할 것

1. 싣는 방식 — 추천: vendor(저장소 안). 이유: 지금 앱은 스크립트를 CDN 에서 읽지 않는다(글꼴 · 이모지 CSS 만). CDN 이 막히면 그 화면이 돌지 않고, 남의 서버 스크립트가 작품 데이터와 같은 페이지에서 돈다. 다른 안: jsDelivr `three@0.170.0` 고정(저장소가 가볍다).
2. 판 — 추천: 0.170.0(시안이 쓴 판). 올릴 때는 05 의 브라우저 확인을 다시 한다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/static/vendor/three/three.module.min.js` (새) | three.js 0.170.0 `build/three.module.min.js` (691,648 바이트, gzip 170,881) |
| `canon/static/vendor/three/OrbitControls.js` (새) | `examples/jsm/controls/OrbitControls.js`. `import ... from 'three'` 줄을 `./three.module.min.js` 로 바꾼다 |
| `canon/static/vendor/three/CSS2DRenderer.js` (새) | `examples/jsm/renderers/CSS2DRenderer.js`. 같은 방식 |
| `canon/static/vendor/three/LICENSE` (새) | three.js MIT 라이선스 원문 |
| `canon/static/vendor/three/README.md` (새) | 판, 받은 곳(npm `three@0.170.0`), 받은 날, 고친 줄(import 경로), 올리는 법 |

다른 파일은 고치지 않는다. `index.html` 에 넣지 않는다(05 가 `import()` 로 읽는다). 정적 파일 서빙은 지금 `/static` 이 폴더째 내보내는지 확인만 한다.

## 계약 (입력 · 출력)

- 출력: `/static/vendor/three/three.module.min.js` 와 두 addon 이 ES 모듈로 읽힌다. 05 는 `await import('/static/vendor/three/three.module.min.js')` 로 쓴다.
- 파일을 받는 일은 npm 공개 패키지에서 한다. 받은 파일의 sha256 을 README 에 적는다.

## 규칙

- 원본을 줄이거나 고치지 않는다. 두 addon 의 import 경로 한 줄만 바꾸고 README 에 적는다.
- `.gitignore` · 서버 압축 설정은 바꾸지 않는다.

## 시험

- `tests/test_stage3d_vendor.py`(새, 이 파일만): 세 파일이 있고, 크기가 README 에 적은 값과 같고, addon 두 파일에 `from 'three'` 가 남아 있지 않다.
- 브라우저: 개발 서버에서 `import()` 가 오류 없이 된다(콘솔).
- 전체 시험.

## 문서

AGENTS.md 표에 `canon/static/vendor/` 줄(바깥 라이브러리, 고치지 않음). 저장소 README 의 라이선스 · 출처가 있으면 three.js 한 줄.

## 구현 메모

- 05 가 three.js 를 한 곳에서 읽게 작은 로더 `canon/static/stage3d-load.js`(`load3d()`)를 더하고 `index.html` 에 넣었다. 로더는 three.js 를 import 하지 않고, 처음 부를 때 세 모듈을 `import()` 로 읽는다. 05 는 `await load3d()` 로 `{THREE, OrbitControls, CSS2DRenderer, CSS2DObject}` 를 받는다.
- `/static` 은 폴더째 내보내고 `.js` 를 `text/javascript` 로 준다(시험이 확인). 서버는 고치지 않았다.
- 시험은 크기와 sha256 을 함께 맞춰 보고, `index.html` 이 three.js 를 직접 읽지 않는지와 로더 경로도 본다.

## 확인하지 못할 것

없음.
