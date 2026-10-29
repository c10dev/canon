/* three.js 늦게 읽기 (설계 docs/stage/3d/specs/06-three.md). 평소 화면은 three.js 를 받지 않는다.
   3D 보기를 처음 열 때 load3d() 가 vendor/three 의 ES 모듈 셋을 import() 로 한 번만 읽고 같은 Promise 를 돌려준다.
   읽기에 실패하면 해요체 오류로 거부하고, 다음 호출에서 다시 읽는다. */
'use strict';

const THREE_DIR = '/static/vendor/three/';
const THREE_FILES = ['three.module.min.js', 'OrbitControls.js', 'CSS2DRenderer.js'];
let three3d = null;

function load3d() {
  if (!three3d) {
    three3d = Promise.all(THREE_FILES.map(f => import(THREE_DIR + f)))
      .then(([THREE, orbit, css2d]) => ({
        THREE,
        OrbitControls: orbit.OrbitControls,
        CSS2DRenderer: css2d.CSS2DRenderer,
        CSS2DObject: css2d.CSS2DObject,
      }))
      .catch(e => {
        three3d = null;
        console.error(e);
        throw new Error('3D 보기를 불러오지 못했어요. 새로고침한 뒤 다시 열어 주세요.');
      });
  }
  return three3d;
}
