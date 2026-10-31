# 모듈 지도: 웹 화면 뼈대와 공용 화면 파일

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/static/app.css`

- 웹 화면 CSS 한 파일
- 색 토큰은 두 `:root` 블록(밝은 · 어두운)에 있고 `docs/design/tokens.json` 과 같다(`tests/test_design_tokens.py`)
- 간격 · 모서리 · 크기 · 그림자 · 쌓는 층은 맨 위 `:root` 의 변수(`--space-*` · `--radius-*` · `--shadow-*` · `--z-*`)로 쓴다(같은 시험)
- z-index 는 `--z-*` 사다리만 쓴다(`docs/design/layout.md` '쌓는 층')
- 손가락 기기 · 640px 이하에서 작은 누름 영역을 44px 로 키우는 규칙은 '휴대폰' 절 바로 앞 한 블록에 모은다
- 기능마다 `/* ----- 이름 (파일.js) ----- */` 절로 나눈다
- 공용 목차 틀의 화면별 칸 규칙은 `@container outline` 으로 건다
- 컴포넌트 규칙을 바꾸면 `docs/design/components/bundle.css` 의 그 줄도 같게 고친다
- 몇몇 화면(`palette.js` · `foreshadow.js` · `stage.js` · `revlab.js` 등)은 CSS 를 JS 에서 주입한다

### `canon/static/app.js`

- 웹 화면의 뼈대
- 상태 `S`
- 서버 호출 `api`
- 작품 밖 화면(작품 목록 · 새 작품 `#/new` · 사용량 · 문체 라이브러리 · 역설계 실험)의 사이드바 `outSidebar`
  - 항목은 순수 함수 `outNav`: 작품 목록 · 새 작품 · 새 플레이, 최근 작품 셋, 작품 밖 도구(쇠맛 실험실은 준비 중 `.nav-off`)
  - 본문 `.out-main` 폭 `--out-w` · `@container out`
- 사이드바
  - `sidebar`: 맨 위 줄 `sideTop` · 작품 칸 · 단계 · 접는 묶음 `navFold`(작품 도구 · 아직 안 쓴 도구 · 실험, 펼침 `navFoldOpen`) · 아래 고정 줄 `sideFoot`(설정 · ⋯ 메뉴)
  - 줄 끝 배지 `navBadges`(순수 함수, `tests/test_sidebar_js.py`) · `navBadge`
  - 64px 레일로 접기 `toggleRail` · `syncRail`(901~1599px 에서 대화 패널을 열면 저절로)
  - 900px 이하는 위쪽 띠와 왼쪽 서랍 `drawerHead`
- 창 폭 경계 `BP`(phone 640 · narrow 900 · chatRail 1599)와 `mq(이름)`: app.css `@media` 와 같은 값이다. `hub.js` · `review.js` 도 이것을 쓴다
- 사이드바 아이콘(`navItems` · `navMark`: 단계는 번호, 그 밖은 토스페이스 이모지 `.tf`, 출처 문구는 사이드바 아래, Swift `Screen.mark` 와 같은 글자)
- 사이드바 작품 칸(`workCard`: 제목 · 갈래 · 플레이 사본(`play.js` `playSideTag`) · 장편은 지금 부 · 아크(`partOf` · `arcOf`), 화 칸 띠는 단편 전체 · 장편 지금 아크, 다음 할 일은 `home.js` `nextStep`, 좁은 폭 위쪽 띠 줄이기는 `app.css` `.work-card`)
- 4 · 5 · 6 줄이 가리키는 화(`navEp`: 한 화 흐름 `FLOW_PAGES` · 작업지시서는 보는 화)
- 900px 이하 위쪽 띠는 화면 위에 붙고 높이 `--band` 만큼 본문의 붙는 칸을 내린다
- 서랍을 연 동안 뒤는 `inert`(`syncRail`)
- 백그라운드 작업 · 검토 대기 결과
- 알림 말풍선(`toast`, 작업 실패는 '다시 시도' · '설정' 버튼, 기록과 자리는 `hub.js`)
- 입력 바인딩(`data-bind`)
- 공통 동작(`actions` 의 저장 · 되돌리기 · 작품 관리)
- 펼침 메뉴(`menuBtn`, 열린 메뉴 `S.popMenu`, Esc · 바깥 누르기로 닫기)와 `#app` 밖 대화상자(`showDialog`)
- 라우팅
- 사이드바
- 다시 그리기와 포커스
- 화면 코드는 화면 파일(`settings.js` · `home.js` · `setup.js` · `style.js` · `plot.js` · `write.js` · `review.js` · `research.js` 등)에 있다
- 화면 파일은 `viewX` 와 `Object.assign(actions, {...})` 로 붙는다
- 화면 파일은 `index.html` 에서 `app.js` 바로 뒤에 읽는다
- 화면 파일이 모두 실행된 뒤(`DOMContentLoaded`) 첫 화면을 그린다

### `canon/static/board.js`

- 집필 화면 스토리보드 카드(`write.js` 의 `viewWrite` 가 부른다)
- 본문 없는 화의 만들기 · 바로 쓰기 · 스토리보드 없이 쓰기(`boardStart`)
- 만든 카드(`boardCard`: 어긋남 · 확정 값 · 넘겨받을 것 · 깨지 않을 것 · 장면, 낡음 표시, 다시 만들기 · 이대로 쓰기)
- 고치기(`boardForm`, 칸 글 읽기 `boardParse`, `tests/test_storyboard.py`)
- 쓴 화의 접은 카드(`boardPanel`)
- 계산 값은 `GET …/storyboard`(`board.view`)

### `canon/static/chat.js`

- 화면에 붙는 AI 대화 패널(플롯 대화는 `agent.js` 가 그린다)(901~1599px 은 사이드바를 레일로 접고 400px, 900px 이하는 아래 시트, 규칙은 `app.css` 의 `body.chat-open`. 기승전결 · 플롯 화면 `plot`, 집필 화면 `text:<화>`)
- 변경안을 칸별로 지금 값과 비교해 보여 주고 고른 것만 반영 요청
- 주제마다 요청 내용과 변경안 그리기를 `CHAT_TOPICS` 에서 바꿔 끼운다
- 플롯 대화는 대상(`plotScope`: 고른 아크 · 다음 아크 초안, 연 구간 · 화)을 함께 보낸다
- 플롯 대화가 그리는 것: 아크 칸 · 부 구성 변경안, 방향 여러 안(`optionsCard`), 다음 아크 안을 초안으로 놓기(`draftFromRev`)
- 적용한 플롯 변경안의 적용 취소(`chatUndo`, 서버 `pipeline.undo_plot_chat`)
- 서버 `pipeline.chat_target` · `chat_where` 와 같은 규칙(`tests/test_chat_js.py`)
- 화면 본체는 `plot.js` · `write.js`

### `canon/static/check.js`

- 5단계 검수 화면(한 화 흐름의 검수 단계, 주소 `check/<화>`, `viewCheck`, 왼쪽 본문 · 오른쪽 칸 `.c-side` 에 목록과 상세)
- 회차 띠(누르면 그 회차가 바꾼 지적 `roundChanges`, 새 판 구분) · 처리 상태 거르기
- 지적 목록(탭: 모순 지적 · 초반 점검 `openingChecks` · 문체 지표 `GET …/style`, 심각도 순 · 딸린 지적은 부모 아래 `findingOrder`)
- 본문(`draftBox` · `readHtml`, 지적 문장 밑줄 `findingRanges` 를 `marks.js` 의 `allRanges` 가 함께 그림, 바뀐 문장은 비슷한 문장 `nearQuote`)
- 지적 상세(심각도 `setSeverity`, 처리 상태 `setFinding`, 메모, 처리 기록)
- 문장에서 뜨는 고치는 창(`fixPanel`, `passage.js` 떠 있는 도구 mode `finding`: 고침안 `fixGet` · 딸린 곳 빼기 `fixSkip` · 적용 `fixApply` · 묶음 되돌리기 `fixUndo` · 이 지적만 다시 검수 `chkRecheck` · 다른 처리 길)
- 장면 연출 규칙 지적은 '규칙' 표시(`ruleChip`)와 '장면 연출에서 보기'(`stageLink`, `stgGo`)
- 다시 검수 버튼은 '판정 다시 보기'(LLM 없음)
- 머리의 '연출 함께 뽑기'(`stageToggle`, `Settings.stage_extract`)
- 표시 `findingFlag` · 밑줄 `findingMarks` · `findingOrder` · `roundChanges` · `nearQuote` · `fixMissing` 은 순수 함수(`tests/test_check_js.py`)

### `canon/static/convert.js`

- 단편 → 장편 전환 화면
- 이어 쓰기(총 화수 · 결말 처리, AI 전환 계획에서 항목 골라 반영)와 재구성(화 지도 고치기, 반영)
- 되돌리기
- 집필 화면의 재구성 안내 · 다듬기 비교(`rebuildNote`)도 여기 있다

### `canon/static/flow.js`

- 한 화 흐름
- 집필 · 검수 · 상태 승인 세 화면(주소 `write` · `check` · `review/<화>`)의 머리 아래 단계 띠(`flowBar`, 단계 글은 순수 함수 `flowSteps`, 이름 · 번호는 사이드바와 같음 `FLOW_STAGES`, 위치 줄 `flowEyebrow`)
- '검수하기'(`flowCheck`: 검수 단계로 옮겨 검수, 첫 검수면 상태 변경안도 함께 `flowStateToo`, 끄기 `flowStateToggle` · localStorage `canon.flowState`)
- `tests/test_flow_js.py`
- `index.html` 에서 `check.js` 바로 뒤에 읽는다

### `canon/static/home.js`

- 작품 목록(작품 밖 사이드바 옆, `tests/test_projects_js.py`)
  - 새 작품 칸 `newProjectForm`(주소 `#/new` 면 펴고 제목 칸으로)
  - 이어 쓰기 카드 `plHeroCard`(고를 작품 `plHero`, 확인할 것 줄 `plAlertHref`)
  - 모든 작품 한 줄 목록: 찾기 · 거르기(확인할 것 포함) · 정렬과 갈래 · 플레이 묶기 `plRows`
  - 상태 `plStatus`
  - 다음 단계 화면 링크 `projectGo`
  - 고친 때 `fmtWhen` · 묶음 `plTimeGroup`(20묶음 넘으면 더 보기 `PL_PAGE`)
  - ⋯ 메뉴 `plManage`(폴더 이름)
  - 작품 없음은 `plStepsCard`
  - 서버 카드의 확인할 것 `alerts` · 부 · 아크 `where` · 화 칸 띠 `strip`(`web.list_projects`)
- 작품 홈
  - 지금 화 `homeNowCard` · 확인할 것 `homeTodos`(말투 빈 인물 `homeSpeechGaps`, 시점 인물 서술 말투 빈칸 `homeVoiceGap`) · 전 화수 막대 `homeProgress` · 줄인 목록 `homeCast` · `homeForeshadows`
  - 계산 함수는 작품을 받는 순수 함수 `tests/test_home_js.py`
- 장르 · 화 진행 막대와 연재 일정(`epSteps`, 검수 칸 `checkState`, 화를 열 단계 화면 `epStage`: 다음 할 일 · 화 칸 · 팔레트, 작품 목록 다음 할 일 `projectNext` 는 서버 `findings.check_done`, `releasePlan`, `Project.release`)

### `canon/static/hub.js`

- 알림
- AI 작업과 알림을 버튼 하나에 모은다
- 버튼(`hubButton`, 사이드바 · 작품 밖 사이드바의 `#hub-slot`)
- 버튼 아래 창(`#hub-pop`: 확인할 것 · 진행 중 · 최근 알림 · 접힌 끝난 작업과 지난 알림, `hubOpen` · `hubClose`)
- 말풍선과 창 자리(`placeHub`, `#toast`)
- 알림 기록(`hubNote`, `S.notes`)
- 버튼 모양과 창에 넣을 것은 순수 함수 `hubState`(`tests/test_hub_js.py` 가 node 로 맞춰 본다)
- 검토 대기 결과 이름 · 화면 `HUB_RESULT` 는 `app.js` `PENDING_KINDS` 와 함께 고친다
- `index.html` 에서 `app.js` 바로 뒤에 읽는다

### `canon/static/ideas.js`

- 설정 칸 하나의 AI 후보(✦)
- 칸 옆 버튼(`ideaBtn`, `.ai-mini`)과 칸 바로 아래 후보 목록(`ideaList`)
- 고르기(`useIdea`, 로그라인 칸이면 합친 문장도) · 다시 받기 · 닫기
- 마법사 · 기획서 칸에는 `input()` 의 `aside` · `beside` · `after` 로 붙인다
- 고르기 전에는 칸을 바꾸지 않는다
- 칸 목록 `IDEA_FIELDS` 는 `prompts.FIELD_IDEAS` 와 같다(`tests/test_ideas_js.py`)
- 인물 칸(성격 · 배경 · 외모 · 아크)은 경로 번호를 `*` 로 찾는다(`ideaKey`, 이름 붙은 칸 이름 `ideaLabel`)
- 받은 때의 인물 id 가 다르면 넣지 않는다(`tests/test_setup_fill.py`)
- 서버는 `pipeline.suggest_field`

### `canon/static/index.html`

- 웹 화면 한 쪽
- 화면 파일을 `<script>` 로 읽는다
- 읽는 차례: `app.js` → `outline.js` → `hub.js` → 화면 파일들(`check.js` 바로 뒤 `flow.js`, `atlas.js` 바로 뒤 `atlas-*.js`)
- 새 화면 파일을 더하면 여기에 `<script>` 를 넣는다

### `canon/static/marks.js`

- 집필 화면 문체 표시
- 장치마다 이번 화 배지(`deviceBadges`, 본문 띠의 '문체 장치' 메뉴 `styleMenu`)
- 본문에서 장치 글자 · 금지 표현 밑줄(고치는 본문은 textarea 뒤에 깐 칸 `hl-layer`, 스크롤은 CSS 스크롤 타임라인 `hl-follow` 로 따라가고 안 되는 브라우저만 `scrollTop`, 읽기 전용은 `<mark>`)
- 밑줄에서 부분 수정 도구 띄우기
- 쓴 화 세기와 쉬는 화 판정은 `metrics.device_hits` · `device_last` · `prompts.device_block` 과 같은 규칙이라 함께 고친다(`tests/test_marks_js.py` 가 node 로 맞춰 본다)

### `canon/static/mentions.js`

- 집필 화면 본문 속 이름
- 인물 이름 · 장소(`atlas.places` 와 같은 목록 `mentionPlaces`)를 정규식 하나로 찾기(`mentionRanges`, 조사 · 긴 낱말 규칙, 치는 중에는 자리 옮기기 `mentionShift`)
- 밑줄은 `marks.js` 의 `markHtml` 이 함께 그림
- 이름 카드(이 화 시작 시점 `/cast` 프레임을 `S.mnCast` 에 따로 받아 `cast.js` 함수로 읽음, 장소는 설명과 지도)
- 켜기 · 끄기(localStorage)
- 규칙은 `tests/test_mentions_js.py` 가 node 로 맞춰 본다

### `canon/static/mystyle.js`

- 나만의 문체
- 스타일 프로필의 가끔 쓰는 장치 고치는 칸(`deviceFields`)
- 문체 화면의 맨 위 '확인할 것' 카드(고르지 않은 규칙 후보 `learnTodoCard`)와 재료 묶음의 '내 수정에서 배우기' 카드(`learnCard`, 서버 `pipeline.learn_style` / `apply_learning`)
- 라이브러리 항목의 버전 목록
- 장치의 쓴 화 세기는 `metrics.device_last` 와 같은 규칙

### `canon/static/opening.js`

- 초반 1~3화
- 집필 화면의 초반 점검 카드(지표 경고, 흡입력 판정, 여는 방식 비교본, 반영 끝난 화는 비교를 감춤)
- 플롯 편집기의 여는 방식별 플롯 안(고르기 전 플롯은 `Episode.opening_prev`, 되돌리기 `pipeline.undo_opening`)
- 서버는 `pipeline.opening_metrics` · `check_hook` · `suggest_openings` · `apply_opening` · `research.run_opening_compare`
- 규칙은 `prompts.opening_rules` / `OPENING_APPROACHES`
- 지표는 `metrics.measure_opening`

### `canon/static/outline.js`

- 공용 목차 틀
- 왼쪽 목차 + 오른쪽 카드 한 열(설정 도우미 · 문체 · 플롯 · 역설계 실험이 함께 쓴다)
- 틀 HTML `outlineDoc`(카드 열 760px, `wide` 는 남은 폭)
- 목차 nav `outlineNav`(좁은 칸 버튼 글 `now`, 없으면 버튼 없이 목록만)
- 열고 닫기 `outlineToggle` · `outlineClose`(열림은 `OUTLINE_OPEN` 이 기억해 다시 그려도 `aria-expanded` 가 맞음, 바깥 누르기 · 목록 줄 누르기 · Esc · 주소 바뀜에 닫고 Esc 는 버튼으로 포커스, 줄에 `data-outline-keep` 이면 열어 두고 줄이 아닌 버튼도 `data-outline-close` 면 닫음)
- 목차만 다시 그리기 `outlineRefresh`(목차 안 포커스 유지)
- 스크롤의 지금 구역 `outlineSpy` · `outlinePick`
- CSS 는 `app.css` '공용 목차 틀' 절(`.outline-wrap` · 컨테이너 `outline` · `.outline-doc` · `.outline` · `.outline-now` · `.outline-list` · `.outline-item` 의 `.n` · `.tl` · `.st`, 720px 이하 한 열 · 위에 붙는 버튼, 줄 38px · 좁은 칸 44px)
- 화면별 칸 규칙도 `@container outline` 으로 건다
- `outlineNav` · `outlinePick` · `outlineDoc` 은 `tests/test_outline_js.py`
- `index.html` 에서 `app.js` 바로 뒤에 읽는다
- node 시험 하네스(`tests/jsvm.py`)도 `app.js` 뒤에 늘 함께 읽는다

### `canon/static/palette.js`

- 명령 팔레트
- Ctrl+K(맥은 ⌘K, 입력칸 안에서도) · 좁은 화면 사이드바 '찾기'(`openPalette`)
- 화면(사이드바 `navItems` 와 같은 이름) · 화 번호 · 인물 이름 · 설정 칸(칸 이름과 값, `palSetupFields`, 고르면 `S.jumpTo` 로 설정 도우미 기획서의 그 칸) · 설정 대화상자의 줄(`SET_ROWS`, 고르면 그 갈래를 연다) · 다음 할 일 · 저장(`saveShortcut`) · 알림 창(`hubOpen`)을 찾는다
- 작품 밖은 작품 목록 · 설정 · 알림 창과 설정 줄만
- 검색 `paletteItems` · `paletteMatch` 는 순수 함수(`tests/test_palette_js.py` 가 node 로 맞춰 본다)
- CSS 는 JS 에서 주입

### `canon/static/passage.js`

- 본문 부분 수정
- 본문에서 고르면 뜨는 도구(직접 수정, AI에게 고치기)
- 후보를 원문과 단어 단위로 비교
- 수정 기록과 되돌리기
- 고친 뒤 다시 할 단계 알림
- 상태 정리 경고에서 «» 문장을 찾아 고르기(`warnQuote`, `warnItems`, `warnPick`)
- 서버는 `pipeline.edit_text` · `revise_passage` · `apply_passage` · `undo_edit`

### `canon/static/plot.js`

- 3단계 기승전결
  - 공용 목차 틀 `outline.js` 의 왼쪽 목차 + 넓은 보드 `plotLayout`(`wide`)
  - 720px 이하 목차는 위에 붙는 버튼 `plotToc`
  - 목차 안에서 펼침을 지키는 부 접기 · 아크 펼치기 줄은 `data-outline-keep`
  - 목차의 진행 막대 `plotMeter` · 구간 줄 `actTocItems`(누르면 `jumpAct`) · 확인할 것 `plotTodos`
  - 머리의 'AI로 다시 만들기 ▾' `plotAiMenu`(요청 칸 `S.planNote`)
  - 구간 한 줄 머리 + 화 카드 격자 `actBoard`
  - 구간 · 아크 · 부 고치기는 서랍 없이 그 자리에서 `actEditor` · `arcEditor` · `partEditor`
  - 아크 주요 인물 이름 체크 `arcCastField`
- 장편(목차가 부 › 아크 › 구간 나무 `serialTree` · `serialTocRow`, 부 펼치기 `S.tocParts`, 부 구성 카드 펼침 `S.arcFull`, 다음 아크 기획 칸의 경고 `planAhead` 는 `pipeline.plan_ahead` 와 같은 규칙 `tests/test_plan_ahead_js.py`)
- 서술 시점
- 화 플롯 페이지
  - `viewPlotPage`
  - 주소 `arc/<화>`
  - 목차는 이웃 화 목록 `epTocItems`
  - 카드 한 열: 이어받는 것 · 줄거리 · 인물 · 시점 · 끝과 이음 · 복선 · 접은 화 도구
  - 사건마다 한 칸 `eventsField`
  - 옮기기 전 저장 `openPlot` · `closePlot`
  - 저장 띠는 아래 붙는 버튼 줄의 `.savebar-slot`
- 플롯 편집기 등장 인물(목차 계산 `tests/test_plot_js.py`)

### `canon/static/research.js`

- 연구 화면

### `canon/static/restate.js`

- 반영 뒤 고친 화
- 반영이 끝난 화를 고쳤을 때 집필 화면 알림(`restateNote`, 뒤 화 검수 권유)
- 상태 승인 화면의 다시 맞추기 카드(`restateCard`: 요약 · 새 사실 · 새 복선만 고르기, 그대로 두기)
- 서버는 `pipeline.apply_restate` · `keep_state`
- 표시는 `Episode.final_text` (`edited_after_final` 과 같은 규칙, `tests/test_restate_js.py`)

### `canon/static/review.js`

- 6단계 상태 승인 · 관계 표시
  - `DELTA_LISTS`
  - `setDelta`
  - 머리 버튼 줄의 반영 버튼 · ⋯ `rvMenu` · `.savebar-slot`
  - 왼쪽 읽기 전용 본문과 근거 밑줄 `rvRanges`
  - 오른쪽 직접 정할 것 · 요약 · 그대로 반영할 것(갈래 접기 `S.rvOpen`, 고른 수 `rvKeyCount`) · 관계 계산
  - 경고를 인물 줄에 붙이기 `rvWarnSplit`
  - 인물 칸 그 자리에서 펴기 `rvOpen`
  - 본문 근거 `rvQuote` · `rvGoItem`
  - 900px 이하는 변경안 먼저 `rvWide`

### `canon/static/rewrite.js`

- 다시 생성
- 집필 화면의 다시 생성 열(`rwColumn`, 대화 패널 자리 `.tool-col`에 뜨고 대화 패널과 하나만 열림. 빠른 요청, 피드백, 함께 넣을 재료, 처음부터 / 고쳐 쓰기, 살릴 부분)
- 새 판 비교(나란히 · 바뀐 곳 `textDiff`)와 고르기
- 이전 판 목록과 되돌리기
- 서버는 `pipeline.rewrite_episode` · `set_candidate` · `adopt_candidate` · `drop_candidate` · `restore_version`
- 프롬프트는 `prompts.rewrite_prompt`

### `canon/static/settings.js`

- 설정 대화상자
  - 화면이 아니라 지금 화면 위의 `<dialog>`
  - `openSettings`
  - 주소 `#/settings[/갈래]` 는 `settingsCat`
  - 갈래는 이 컴퓨터 · 이 작품 · 이 브라우저 `SET_CATS`
  - 찾기 색인 `SET_ROWS` · `settingsMatch`
  - 줄 HTML `setRowHtml`
  - 바로 저장 `setSave`(바꾼 칸만 `PUT /config`) · `setProjectSave`(칸마다 작품 API)
  - 저장 띠 없음
  - 키만 줄 안 '키 저장'
  - 작품별 단계 값 `projectStage`
  - Claude 로그인 줄 `claude.js` · Vertex 줄 `vertex.js`
  - `tests/test_settings_js.py` · `tests/test_model_preset.py`

### `canon/static/setup.js`

- 1단계 설정 도우미
  - 공용 목차 틀 `outline.js` 의 왼쪽 목차 + 오른쪽 카드 한 열 `.setup-secs`
  - 720px 이하는 위에 붙는 목차 버튼 · 걸음 막대(`.outline.steps`)와 아래 버튼 줄 `.setup-foot`
  - 새 작품 마법사 `viewSetupWizard`: 필수 칸 `setupReqs` · 걸음 목차 `wizStepper` · `wizStepState` · 세계 종류 · 시대 칩 `withWorldKind` · `worldRecs`
  - 다 채운 작품은 기획서 `viewSetupDoc`: 구역 `DOC_SECS` · 목차 상태 `docStatus` · 머리 요약 `docSummary` · 관계 점검 `relIssue` · `relWork`
  - 인물 · 관계는 한 줄 목록에서 하나만 편다
  - 이야기 뼈대만: 로그라인 · 관계 · 이름 후보 · 조사 `josa`
  - 인물 상세는 `cast.js` 인물 카드
  - 상태창 처음 수치는 `statwin.js` 로 가는 링크 `setupStatLink`
  - `tests/test_setup_wizard_js.py`

### `canon/static/style.js`

- 2단계 문체 · 문체 라이브러리
  - 왼쪽 목차 `styleToc` · 목차 줄 `styleTocItems` + 카드 한 열
  - 프로필 카드 `pfCard`: 읽는 모양 `pfRead` 이 기본
  - '고치기'로 그 카드만 `pfEdit`(기억 `S.styleOpen`, 빈 카드 `styleCardEmpty` 는 바로 고치는 칸)
  - 목차 수 `styleCount`
  - 빈 문체는 세 갈래 `stylePickCard` · `styleManual`
  - 라이브러리 항목도 같은 카드
  - 목차 틀은 공용 `outline.js`(`styleToc`)
  - `tests/test_style_js.py`

### `canon/static/stylechat.js`

- 문체 화면의 대화로 다듬기(대화 주제 `style`: 칸별 변경안과 지금 값 비교, 시험 문단, 고른 칸 적용 · 적용 취소, 라이브러리 새 버전)와 '이 문체로 쓴 예시' 카드
- 서버는 `pipeline.revise_style` · `apply_style_chat` · `undo_style_chat` · `style_example`
- 칸 이름은 `prompts.STYLE_KEY_LABELS` 와 같다(`tests/test_labels_js.py`)

### `canon/static/write.js`

- 4단계 집필
  - 왼쪽 칸 없이 본문 칸 하나
  - 머리 `.w-stick` 에 붙는 본문 띠와 이번 화 플롯 띠 `plotStrip`(사건 진행 줄: 쓴 사건 체크 `doneEvents` → `Episode.events_done`, 막는 조건 `eventsLock`, 엔딩 훅 도착점) · 펼침 기억 `plotOpenOf`
  - 머리 높이 `syncWriteTop`
  - 머리 ⋯ 메뉴 `writeMenu`: 생성 방식 · 컨텍스트 대화상자 · 채팅 앱 작업지시서 .md 내려받기(`briefDownload`) · 화 지우기
  - 본문 없는 화는 AI로 쓰기가 기본이고 머리 primary(`writeGo`, 스토리보드를 만든 화는 `boardGo`, 작업이 돌면 진행 줄 `wsBusy`)와 그 아래 쓰기 시작 칸(`writeStart`: 스토리보드 고르기 `S.wsBoard` · 직접 쓰기 · 컨텍스트)
  - 본문 띠의 저장 칸 `.savebar-slot`
- 작업지시서(본문 · 검수 · 상태 승인 탭, `viewBrief`)

### `swift/`

- SwiftUI 앱(macOS · iOS · iPadOS)
- 서버에 붙는 클라이언트
- 패키지 `CanonKit`
- 순수 Swift `CanonCore`(오류 문구 · 작업 추적 · 조사 · 날짜 · 사이드바 `Screen`)
- 생성 클라이언트 `CanonAPI`(`Sources/CanonAPI/openapi.json`)
- 화면마다 `Feature*` 모듈
- 앱 뼈대 `CanonAppUI`
- Xcode 껍데기 `App/project.yml`
- 계산 · 프롬프트는 옮기지 않는다
- **지금 개발을 멈췄다(AGENTS.md '규칙')**
- 다시 시작하면 `CanonCore` 의 표시 규칙을 웹 화면 파일(`app.js` 와 화면별 파일)에 맞춘다(표는 `swift/README.md`)
- 설계는 `swift/README.md`
