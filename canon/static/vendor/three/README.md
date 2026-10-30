# three.js (바깥 라이브러리, 고치지 않음)

장면 연출 3D 보기가 쓰는 three.js. 설계는 [docs/stage/3d/specs/06-three.md](../../../../docs/stage/3d/specs/06-three.md).
평소 화면은 이 폴더를 읽지 않는다. 3D 보기를 처음 열 때 `canon/static/stage3d-load.js` 의 `load3d()` 가 `import()` 로 읽는다.

- 판: 0.170.0 (r170)
- 받은 곳: npm `three@0.170.0` 패키지 tarball `https://registry.npmjs.org/three/-/three-0.170.0.tgz`
  - tarball sha1 `6087f97aab79e9e9312f9c89fcef6808642dfbb7`, integrity `sha512-FQK+LEpYc0fBD+J8g6oSEyyNzjp+Q7Ks1C568WWaoMRLW+TkNNWmenWeGgJjV105Gd+p/2ql1ZcjYvNiPZBhuQ==` (레지스트리 값과 같음)
- 받은 날: 2026-10-29
- 라이선스: MIT (`LICENSE`, 패키지의 원문 그대로)

## 파일

| 파일 | 패키지 안 경로 | 바이트 | sha256 |
|---|---|---|---|
| `three.module.min.js` | `build/three.module.min.js` | 691648 | `08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7` |
| `OrbitControls.js` | `examples/jsm/controls/OrbitControls.js` | 32150 | `e9c4f26866d39a36c8c9e8215e7d2a90a8a0b50ea6d44a005906e3d1fc726b8f` |
| `CSS2DRenderer.js` | `examples/jsm/renderers/CSS2DRenderer.js` | 4717 | `56657baddba4075609807e5d6a3e7cf042538699df089d4dc604fd29225d1836` |
| `LICENSE` | `LICENSE` | 1081 | `4c40a1ef62450b857c3b2aaf294936304cd552d965fbcd9d32d4c5bcf4ba4454` |

표의 크기와 sha256 은 이 폴더의 파일 값이다. `tests/test_stage3d_vendor.py` 가 맞춰 본다.

## 고친 줄

두 addon 의 import 경로 한 줄만 바꿨다. 브라우저에는 import map 이 없어 `'three'` 를 찾지 못한다.

```
- } from 'three';
+ } from './three.module.min.js';
```

고치기 전 원본 값: `OrbitControls.js` 32134 바이트 sha256 `80efaadea4f8a636a65fb0bd08bfef62f3d93a0bb94e2e7500f23176c5c07f4e`, `CSS2DRenderer.js` 4701 바이트 sha256 `7de0bb70e3c1d6da58416353ed7140a7a7743ece99d73b56eb62bc2dd79bfed5`. `three.module.min.js` 와 `LICENSE` 는 원본 그대로다.

## 올리는 법

1. 새 판의 npm tarball 을 빈 임시 폴더에 받고, 레지스트리의 `dist.integrity` 와 맞춰 본다.
2. 위 표의 네 파일을 꺼내 이 폴더에 덮는다. 두 addon 의 `from 'three'` 줄을 위처럼 바꾼다.
3. 이 README 의 판 · 받은 날 · tarball 값 · 표(크기, sha256) · 원본 값을 고친다.
4. `tests/test_stage3d_vendor.py` 와 전체 시험을 돌린다.
5. 3D 보기를 브라우저에서 열어 05 렌더러 확인을 다시 한다(`docs/stage/3d/specs/05-render.md`). 새 판의 `three.module.min.js` 가 다른 파일을 import 하면 그 파일도 함께 넣는다(0.170.0 은 import 가 없다).
