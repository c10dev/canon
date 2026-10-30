# 장면 연출 레퍼런스

장면 연출 3D 를 하나하나 손으로 만들기 전에 가져다 쓰거나 설계를 빌릴 곳을 모은 문서다. 2026-10-30 조사(배치 연구 · 사람 모형 · 접촉 연구 · 라이브러리 · 3D 에셋)를 정리했다. 저장소 정보(라이선스, 마지막 push, 판)는 그날 GitHub · npm · PyPI 에서 읽은 값이다. 쓰기 전에 다시 확인한다.

**라이선스 원칙.** Canon 코드는 MIT 이고 성인 장르를 다룬다. 그래서 아래를 지킨다.

- GPL 코드는 넣지 않는다. 생각만 다시 구현한다.
- 비상업 · 포르노 금지 조항이 있는 모델 · 데이터(SMPL 계열과 그 위의 연구 데이터)는 쓰지 않는다.
- 들일 수 있는 것은 CC0 · CC-BY 에셋과 MIT · BSD · Apache-2.0 코드, 그리고 논문에서 다시 구현한 알고리즘이다.
- 미성년 성적 접촉 막기는 외부 자료가 아니라 Canon 판정 규칙(`stage.blocked`)이 정한다.

## 손으로 그만 만들 것 (순위)

| 순위 | 그만 만들 것 | 대신 쓸 것 | 일감 |
|---|---|---|---|
| 1 | 차 · 벽마다 짠 자리 함수, 절대 좌표로 넓히는 방 | Infinigen 식 '면에 붙는 자식' 데이터(설계만 빌림) | [09-attach.md](specs/09-attach.md) (2026-10-30 구현) |
| 2 | 박자 사이 직선 이동(물건을 뚫음) | 서버에서 shapely `buffer` 로 장애물을 몸 반지름만큼 부풀리고 가시성 그래프(networkx)로 경로. 경유점을 `Frames` · `check` 에 실음 | [10-path.md](specs/10-path.md) (2026-10-30 구현) |
| 3 | AI 기준점 자리 휴리스틱 | Holodeck 격자 DFS 점수 풀이(Apache-2.0, 고지 남김) + Imperative 논문의 한 값씩 고치기 + 풀기 전 방 크기 정하기(I-Design `check_size_conflicts` 생각) | 다음 |
| 4 | 이름표 겹침 무대응 | 화면 투영 + 우선순위 탐욕 배치 + 지시선(약 40줄, 필요하면 rbush) | 다음 |
| 5 | 손으로 짠 사각형 겹침 셈 | shapely 다각형 질의. 3D 캡슐–상자는 원하면 python-fcl 로 맞춰 봄 | 다음 |

사람 모형 바꾸기는 순위에 없다. 쓸 수 있는 대안(CC0 몸)은 그림만 바꾸고 위 문제를 풀지 않는다. 판정은 계속 `stage3d/body.py` 캡슐이 한다.

## 배치 연구: 글 → 관계 → 좌표

모두 Canon 과 같은 분업이다. LLM 은 닫힌 관계 어휘만 내고, LLM 이 아닌 풀이기가 충돌 · 범위 항을 넣어 좌표를 낸다. 차량 · 야외 · 사람 배치를 다루는 시스템은 없다.

| 이름 | 무엇 | Canon 이 가져갈 것 | 라이선스 · 상태 | 링크 |
|---|---|---|---|---|
| Infinigen Indoors | 태그 붙은 면 사이 관계(`StableAgainst`, `SupportedBy`, `CoPlanar`, `CutFrom`), 담금질 풀이. 줄임말 `flush_wall` · `against_wall` · `ontop` · `front_against(check_z=False)` | 부모 · 면 데이터 모양(09). 코드는 Blender 에 묶여 쓰지 않음 | BSD-3, 2026-10-14 push | [relations.py](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/constraint_language/relations.py) · [tags.py](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/tags.py) · [util.py](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/util.py) |
| Holodeck | 관계 11개(전역 · 거리 · 위치 · 정렬 · 향함), 격자 DFS 가 후보를 충돌 · 벽 향함으로 거르고 가중치 점수로 고름. 모르는 관계 이름은 편집 거리로 맞춤 | 순위 3 의 풀이기 | Apache-2.0, 2025-04 push | [prompts.py](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/prompts.py) · [floor_objects.py](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/floor_objects.py) |
| Imperative vs. Declarative (2025) | LLM 이 앞 물건 기준 산식을 쓰고, 네 손실(범위 밖 · 겹침 · 받침 · 벽)로 값 하나씩 고침. Holodeck 보다 94% 선호 | 순위 3 의 마무리 고치기 | 코드 없음 | [arXiv 2504.05482](https://arxiv.org/html/2504.05482v2) |
| Open-Universe (2024) | `mounted_on_wall`, 겹침 기울기를 무게중심 방향으로 | 겹친 상자 밀어내기 | 코드 없음 | [arXiv 2403.09675](https://arxiv.org/html/2403.09675v1) |
| LayoutVLM | 관계 5개(`on_top_of`, `against_wall`, `distance_constraint`, `align_with`, `point_towards`), 벽을 물건으로 | 어휘만 | 라이선스 파일 없음(코드 쓰지 않음) | [constraints.py](https://github.com/sunfanyunn/LayoutVLM/blob/main/src/layoutvlm/constraints.py) |
| I-Design | 전치사 7개와 벽 · 구석을 축별 구간으로, 풀기 전 크기 충돌 거르기 | 방 크기 미리 정하기 | 라이선스 파일 없음 | [schemas.py](https://github.com/atcelen/IDesign/blob/main/schemas.py) |

## 사람 모형과 자세

| 이름 | 무엇 | 쓸 수 있나 | 링크 |
|---|---|---|---|
| mannequin.js | three.js 0.170 ES 모듈 그대로, 뜻 있는 관절 각(`bend` · `turn` · `tilt` …), 자세 JSON, `blend` · `stepOnGround` · `attach`. IK · 충돌 없음 | GPL-3.0 이라 코드는 넣지 않음. 각 이름 · `blend` · `stepOnGround` 생각만 | [repo](https://github.com/boytchev/mannequin.js) · [user guide](https://boytchev.github.io/mannequin.js/docs/userguide.html) |
| Storyboarder / Shot Generator | 자세 프리셋 342개(차 운전 · 차 타기 · 벽에 기대 앉기 · 눕기 · 무릎 꿇기) | 재배포 금지 EULA. 프리셋 이름 목록만 '갖출 자세' 점검표로 | [poses.json](https://github.com/wonderunit/storyboarder/blob/master/src/js/shared/reducers/shot-generator-presets/poses.json) · [license](https://github.com/wonderunit/storyboarder/blob/master/build/license_en.txt) |
| MakeHuman / MPFB2 | 기본 메시 · 타깃 · 스킨이 CC0(프로그램 코드는 AGPL/GPL 로 따로) | 메시가 필요하면 CC0 몸 | [MPFB FAQ](https://static.makehumancommunity.org/mpfb/faq/use_in_closed_source.html) · [mpfb2](https://github.com/makehumancommunity/mpfb2) |
| Mesh2Motion | 코드 MIT, 리그 · 애니메이션 CC0 | 리그 · 동작 참고, CC0 자산 | [repo](https://github.com/Mesh2Motion/mesh2motion-app) |
| three.js 예제 Xbot · Soldier | Mixamo 출처 | 원본 파일 재배포 불가, 쓰지 않음 | [예제](https://github.com/mrdoob/three.js/blob/dev/examples/webgl_animation_skinning_blending.html) |
| SMPL-X · AMASS | 사람 몸 · 모캡 표준 | 비상업 · 포르노 금지 · 재배포 금지, 쓰지 않음 | [SMPL-X license](https://smpl-x.is.tue.mpg.de/modellicense.html) · [AMASS license](https://amass.is.tue.mpg.de/license.html) |
| Anny (NAVER) | MakeHuman 계측에서 나온 몸, 나이 · 키 · 몸무게 매개변수 | Apache-2.0(단 `smplx` 위상 모드는 비상업). 체형 참고 | [arXiv 2511.03589](https://arxiv.org/html/2511.03589v2) |

다음 자세 후보(지금 `stage3d/postures/` 에 없는 것): 차 운전, 차 타기, 벽에 기대 앉기, 침대에 무릎 세워 눕기.

## 접촉 · 상호작용 연구

PROX · POSA · COINS · HUMANISE · CHOIS · TRUMANS · GRAB(사람–물체), InterGen · Inter-X · Hi4D · CHI3D · InterControl(사람–사람)은 모두 SMPL/SMPL-X 위에서 GPU 로 학습한 모델이다. 코드가 MIT 여도 SMPL-X 가중치와 연구 전용 데이터가 있어야 돌고, 그 라이선스가 포르노 용도를 금지한다. 그래서 실행하지 않고 규칙만 가져온다.

| 가져올 것 | 출처 |
|---|---|
| 앉기: 골반이 앉을 수 있는 면 위 점 가까이. 눕기: 몸이 받침 윗면에 닿음 | HUMANISE [arXiv 2210.09729](https://arxiv.org/pdf/2210.09729) |
| '동작–물건' 합성(`sit on-chair+touch-table`) | COINS [repo](https://github.com/zkf1997/COINS) |
| 두 사람 상호작용 = LLM 이 쓴 '관절 쌍 닿음 · 떨어짐' 목록 + IK 로 맞춤. Canon 구조(초안 → 접촉 → `reach_to`)와 같다. '떨어짐'(최소 거리)은 Canon 에 아직 없다 | InterControl [repo](https://github.com/zhenzhiwang/intercontrol) |
| 상호작용마다 핵심 자세 하나 | Ponimator [arXiv 2510.14976](https://arxiv.org/pdf/2510.14976) |
| 평가 지표: 관통 깊이, 발 접촉 | [arXiv 2412.02261](https://arxiv.org/pdf/2412.02261) |

## 라이브러리

판정은 서버 Python 이 하고 브라우저는 그리기만 한다. 그래서 IK · 충돌 · 경로는 Python 쪽에서 고른다. 브라우저 물리 엔진(rapier.js · cannon-es · ammo.js)은 판정을 둘로 만들어 쓰지 않는다.

| 영역 | 고른 것 | 라이선스 · 판 | 링크 |
|---|---|---|---|
| 2D 바닥 기하 | shapely 2.2.0 | BSD-3 | [PyPI](https://pypi.org/project/shapely/) |
| 이동 경로 | extremitypathfinder 2.8.0(Python 3.12+, NumPy 2.3.3+), 또는 networkx 로 가시성 그래프 | MIT / BSD-3 | [extremitypathfinder](https://github.com/jannikmi/extremitypathfinder) · [networkx](https://pypi.org/project/networkx/) |
| 3D 캡슐–상자 | python-fcl 0.7.0.11 (선택) | BSD-3 | [PyPI](https://pypi.org/project/python-fcl/) |
| IK | 지금의 두 마디 해석 IK `reach_to` 를 둔다. three.js `CCDIKSolver` 는 `SkinnedMesh` 가 있어야 하고, ikpy 는 이득이 작다 | — | [CCDIKSolver](https://threejs.org/docs/pages/CCDIKSolver.html) · [ikpy](https://github.com/Phylliade/ikpy) |
| 이름표 겹침 | 직접 쓰는 탐욕 배치(+ rbush, 선택). three.js 에 CSS2D 겹침 정리 기능이 없다 | MIT | [three.js forum](https://discourse.threejs.org/t/how-to-display-multiple-2d-labels-without-overlapping-them/37487) |
| 카메라 프리셋 | camera-controls 3.1.2, 또는 OrbitControls + 짧은 보간 | MIT | [camera-controls](https://github.com/yomotsu/camera-controls) |

npm 의 three.js 부가 패키지는 대개 `import 'three'` 를 맨 이름으로 쓴다. Canon 은 three 를 vendored 했으므로, 들일 때 import 줄을 고치거나 import map 이 필요하다(`static/vendor/README.md`).

## 3D 에셋

그림만 바꾸는 후보다. 판정은 계속 상자 · 캡슐로 하고, 에셋은 기준점 상자 크기에 맞춰 늘이거나 줄여 그린다. 위 넷은 받아서 쟀다(아래 '받아서 잰 것'). 저장소에 넣을 때는 `static/vendor/` 처럼 판 · 받은 곳 · 크기 · sha256 · 라이선스를 적는다.

모든 출처의 라이선스 페이지에 성인물 내용 제한은 없었다(2026-10-30).

| 묶음 | 덮는 종류 | 라이선스 | 형식 · 크기 | 링크 |
|---|---|---|---|---|
| Kenney Furniture Kit | 침대 · 책상 · 의자 · 소파 · 탁자 · 벽(`wall*`) · 창 난 벽(`wallWindow`) · 문틀(`doorway*`) | CC0, 표기 불필요(Kenney 로고만 쓰지 않음) | GLB, 모델 하나 3~40 KB | [furniture-kit](https://kenney.nl/assets/furniture-kit) |
| Kenney Car Kit | 승용차(`sedan`) · 밴 · SUV · 트럭(`truck`, `truck-flat`) · 배달차, 바퀴 따로 | CC0 | GLB, 모델 하나 170~240 KB, 묶음 3.4 MB | [car-kit](https://kenney.nl/assets/car-kit) |
| Kenney Survival Kit | 모닥불 · 표지판 · 나무 · 바위 · 텐트 | CC0 | GLB, 묶음 1.8 MB | [survival-kit](https://kenney.nl/assets/survival-kit) |
| Mesh2Motion 사람 | 사람 몸 `model-human.glb`(365 KB) + 뼈 `rig-human.glb`(21 KB), UE 식 뼈 이름(`pelvis` · `spine_01` · `upperarm_l` …) | 그림 자산 CC0, 코드 MIT. 변형 29개 중 sophia · jay · sintel · bunny 넷은 CC-SA · CC-BY 라 뺀다 | GLB | [mesh2motion-assets](https://github.com/Mesh2Motion/mesh2motion-assets) |
| Quaternius Universal Base Characters (Standard) | 사람 몸 대안(약 13k 삼각형) | CC0. Teen 비율 몸은 미성년으로 보일 수 있어 쓰지 않는다 | glTF, 122 MB | [universalbasecharacters](https://quaternius.com/packs/universalbasecharacters.html) |
| Quaternius Pickup Truck | 픽업 트럭 | CC0 | glTF | [Poly Pizza](https://poly.pizza/m/qn4grQgHm8) |
| KayKit Furniture Bits · City Builder Bits | 가구 · 거리 대안 | CC0 1.0 | glTF | [furniture-bits](https://kaylousberg.itch.io/furniture-bits) · [city-builder-bits](https://kaylousberg.itch.io/city-builder-bits) |
| Poly Haven 모델 | 사실적 가구 · 소품(실제 크기) | CC0 | glTF | [license](https://polyhaven.com/license) |

빈칸: 캠핑카 · 마차 · 차 좌석 · 차 실내는 CC0 저폴리 GLB 를 찾지 못했다. CC BY 3.0 후보만 있다: [RV](https://poly.pizza/m/zrqfTP5xNh), [Caravan](https://poly.pizza/m/aiDmjN8uOmA), [carriage](https://poly.pizza/m/6qE9DrRTExX). 쓰려면 출처 표기를 화면에 둔다. 아니면 지금 상자 그림을 둔다.

주의:
- 같은 Quaternius 모델이 Poly Pizza 에는 CC BY 3.0, 본 사이트에는 CC0 로 적혀 있다. 본 사이트(itch)에서 받는다.
- three.js 예제의 Soldier · Xbot · Michelle 은 Mixamo 출처라 쓰지 않는다. RobotExpressive 는 CC0 다.
- 차 모델에는 실내가 없다. 운전 칸을 비운 그림(09 의 `cab_vehicle`)과 맞추려면 차 모델을 쓰지 않거나, 지붕 · 옆판을 상자로 덧그린다.

### 받아서 잰 것 (2026-10-30)

네 묶음을 받아 GLB 의 노드 변환을 적용한 크기를 쟀다. 받은 판과 sha256 은 아래와 같다. 저장소에는 아직 넣지 않았다.

| 묶음 | 판 · 받은 곳 | 크기 | sha256 |
|---|---|---|---|
| Kenney Furniture Kit | kenney.nl 'Continue without donating' 링크, GLB 140개(GLTF 폴더) | 5.1 MB zip | `e67652d0932cee41683f74711c03d3e192a2af9979ef8e6b237711f5482d46b0` |
| Kenney Car Kit | 3.1 (2026-04-02), GLB 50개 | 4.8 MB zip | `fac7dacac5c7874348cf19729af3ef205f3d366493edaf0a827d93f4fdf3d0c4` |
| Kenney Survival Kit | GLB 80개 | 1.9 MB zip | `c3586341b5932c87eb43d75d915434f47daed168b17ed36a03e8ca9977c7443e` |
| Mesh2Motion `model-human.glb` | `Mesh2Motion/mesh2motion-app` main `static/models/` | 365 KB | `8766a46e82c63c947f7eff70c9d72d6ef0661e2280928048559f8975dcd1086d` |
| Mesh2Motion `rig-human.glb` | 같은 저장소 `static/rigs/` | 21 KB | `3f7ad51c9471458a920dbe373755c3a7223e3672bb572406fa7d2e65deb8f593` |

세 Kenney 묶음 모두 `License.txt` 가 CC0 1.0 이다. 표기는 바라지만 요구하지 않는다.

- **축척은 미터가 아니다.** 모두 Y 위, 장난감 비율이다.
  - 승용차 `sedan` 은 길이 2.55 · 폭 1.5 · 높이 1.3 이다(실제 승용차는 약 4.7 · 1.8 · 1.45).
  - 가구는 약 0.4 배다. 더블 침대 길이 1.12, 의자 높이 0.47, 벽 높이 1.29.
  - 야외 표지는 더 작다. 나무 높이 1.41, 모닥불 0.28.
  - 그래서 그릴 때 기준점 상자 크기에 맞춰 축마다 늘인다. 판정 크기는 지금처럼 기준점 상자다.
- **원점이 다르다.** 차와 야외 표지는 바닥 가운데가 원점이다. 가구는 바닥 한 모서리가 원점이다(x 0 부터, z 음수 쪽). 맞출 때 GLB 의 경계 상자로 가운데를 다시 잡는다.
- **트럭 짐칸:** `truck` 은 짐칸이 열린 픽업이고 `truck-flat` 은 낮은 평판 짐칸이다(Car Kit `Previews/truck.png` · `truck-flat.png`). 둘 다 창이 막혀 있고 실내 좌석이 없다. 캠핑카는 없다. 가장 가까운 것은 짐 상자를 얹은 `delivery`(길이 3.25 · 높이 1.65)다.
- **차 모델은 바퀴가 따로인 노드**(`body`, `wheel-front-left` …)다. 15화의 정비차는 `truck` 으로 그릴 수 있다. 짐칸 구역(09)이 그 열린 짐칸에 맞는다.
- **Mesh2Motion 사람 몸은 스킨이 없는 메시**다. `model-human.glb` 은 T 자세 메시 하나(키 1.83m, 팔 벌린 폭 1.93m)이고 뼈와 가중치가 없다. 뼈는 `rig-human.glb` 의 66개(`pelvis` · `spine_01~03` · `neck_01` · `head` · `clavicle_l` · `upperarm_l` · `lowerarm_l` · `hand_l` · 손가락 · `thigh_l` · `calf_l` · `foot_l` · `ball_l` …, UE 식)다. 둘을 잇는 가중치는 Mesh2Motion 앱이 자동으로 만든다. Canon 이 그대로 쓰려면 그 앱으로 묶은 GLB 를 내보내거나, 마디마다 메시를 나눠 캡슐 대신 붙여야 한다. 키는 Canon 마네킹(1.72m)과 비슷하다.
- Mesh2Motion 앱 저장소의 GitHub 라이선스 칸은 비어 있고(`NOASSERTION`), README 가 '코드 MIT, 그림 자산 CC0'이라 적는다. 자산 저장소 `mesh2motion-assets` 는 CC0-1.0 이다.
