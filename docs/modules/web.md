# 모듈 지도: 웹 화면 뼈대와 공용 화면 파일

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/static/app.css`

- 웹 화면 CSS 한 파일
- 색 토큰은 두 `:root` 블록(밝은 · 어두운)에 있고 `docs/design/tokens.json` 과 같다(`tests/test_design_tokens.py`)
- 간격 · 모서리 · 크기 · 그림자 · 쌓는 층은 맨 위 `:root` 의 변수(`--space-*` · `--radius-*` · `--shadow-*` · `--z-*`)로 쓴다(같은 시험)
- z-index 는 `--z-*` 사다리만 쓴다(`docs/design/layout.md` '쌓는 층')
- 손가락 기기 · 640px 이하에서 작은 누름 영역을 44px 로 키우는 규칙은 '휴대폰' 절 바로 앞 한 블록에 모은다
- 높이 500px 이하(가로 휴대폰) 규칙은 `@media (max-height: 500px)` 로 건다. 붙여 두는 칸을 풀고 대화 시트를 키운다(`docs/design/layout.md` '오른쪽 패널')
- `html` 에 `text-size-adjust: 100%` 를 둔다. iOS Safari 가 가로 화면에서 글자를 키우지 않게 한다
- 첫 칸이 짧은 행 이름인 연구 표(`.rs-table.rs-pin`, 연구 화별 표)는 옆으로 굴려도 첫 칸이 왼쪽에 붙어 있다
- 떠 있는 칸 · 시트 · 메뉴(대화 기록, 펼침 메뉴, 설정 대화상자, 목차 펼침 등)는 `overscroll-behavior: contain` 이다. 끝까지 굴려도 뒤 페이지가 구르지 않는다
- 기능마다 `/* ----- 이름 (파일.js) ----- */` 절로 나눈다
- 공용 목차 틀의 화면별 칸 규칙은 `@container outline` 으로 건다
- 컴포넌트 규칙을 바꾸면 `docs/design/components/bundle.css` 의 그 줄도 같게 고친다
- 몇몇 화면(`palette.js` · `foreshadow.js` · `stage.js` · `revlab.js` 등)은 CSS 를 JS 에서 주입한다

### `canon/static/app.js`

- 웹 화면의 뼈대
- 이름 뒤 조사 `josa`(여러 화면이 쓴다, `logline.josa` 와 같은 규칙, `tests/test_logline_js.py`)
- 900px 이하에서 알림 창 · 찾기 팔레트 · 대화 시트 · 서랍 메뉴를 열면 기록을 하나 더해(`panelOn` · `panelOff`, state.panel) 뒤로 가기가 그 창만 닫는다. 닫을 때 되돌리기는 한 박자 미뤄 다른 창이 이어 쓰고, 주소가 바뀐 popstate 는 창을 닫지 않고, 창 없이 남은 기록은 움직인 쪽(뒤 · 앞)으로 건너뛰고, 저장하지 않은 변경이 있으면 건너뛰지 않는다. 열린 채 그려진 대화 시트는 그 시트를 처음 누를 때 `panelSync` 가 기록을 붙인다
- 지운 것 되살리기는 최근 10개까지 쌓는다(`rememberRemoved`, `S.removed`). 지우기 사이에 다른 고침(`S.editSeq`)이 있으면 앞 기록을 버린다. 저장 띠의 '되살리기'는 가장 최근 것부터 하나씩
- 휴대폰 키보드가 열리면 html 에 `kb-open` 을 단다(`--kb` 80px 이상). 640px 이하에서 집필 머리를 붙여 두지 않는다
- 글 칸(`DIALOG_TEXT`)이 있는 대화상자는 바깥(배경)을 눌러도 닫지 않는다. Esc · 취소는 닫는다
- 그린 뒤 화마다 한 열인 넓은 표(`.at-table-wrap`, 상태창 화별 `.sw-table-wrap`)를 지금 화(`.cur`) 또는 마지막 열로 옆으로 굴려 둔다
- 작품 안 모르는 화면 이름(옛 북마크, 손으로 친 주소)은 작품 홈을 그리고 위에 "'이름' 화면은 없어요" 안내와 작품 홈 주소로 가는 버튼을 둔다
- 같은 화의 한 화 화면에서 칸만 바꾸면(`flowSwitch`: 집필 · 검수 · 상태 승인) 스크롤 자리를 지키고 포커스를 제목 대신 단계 띠의 지금 칸에 둔다
- 반영 취소(`revertFrom`) 확인은 저장하지 않은 변경이 있으면 먼저 저장한다고 말하고 버튼을 '저장하고 반영 취소'로 쓴다
- 반영 취소(`revertFrom`) 확인이 '빠지는 인물'로 적는 새 인물은 그 화 전에 이미 있던 인물(`first_ep` 가 0인 설정 단계 인물과 앞 화 반영 기록의 새 인물)을 뺀다(`pipeline.revert` 와 거의 같다)
- 반영 취소(`revertFrom`)는 뒤 화들의 반영 기록이 검토를 기다리는 변경안으로 남으니(`web._revert_kept`) 취소 뒤 `loadPending` 으로 받는다
- 서버 오류 문구 `fmtErr`: 검증 오류(detail 이 목록)는 영어 원문 대신 `VALIDATION_REASON`(web.py `_VALIDATION_REASON` 과 같음, `tests/test_fmterr_js.py`)과 칸 이름 `FIELD_NAME` 으로 쓴다
- 저장하지 않고 이동하면 묻는 창은 작품 변경만 있을 때 '저장하고 이동'(askConfirm 의 `alt`)을 주 버튼으로 준다
- 화면 이동 확인은 `leaveUnsaved`(작품 · 라이브러리 · 장면 연출 변경, `S.editDrafts`)를 본다
- `goThen(hash, fn)` 은 화면을 옮기고 `routeNow` 가 그 주소를 다 그린 뒤 `fn` 을 한 번 부른다. 이동 확인에서 '취소'를 고르면 버린다
- 새로고침 · 탭 닫기(`beforeunload`)는 `hasUnsaved` 를 본다: `leaveUnsaved` 에 본문 초안 · 지시서 결과 · 상태 변경안 · 문체 예시 · 가격표(`S.priceDirty`)를 더한다
- `hasUnsaved` 는 화면을 옮겨도 S 에 남는 고치던 입력도 더한다: 모듈이 `onKeptDraft(함수)` 로 맡긴 검사가 하나라도 true 면 묻는다(`keptDraftOpen`)
- `onKeptDraft` 검사는 화면 이동 확인에 넣지 않는다. 그 입력은 화면을 옮겨도 사라지지 않는다
- 큐 시트 고침(`S.cueEdits` 의 `dirty`)은 `app.js` 가 직접 `onKeptDraft` 에 맡긴다. 집필 · 실험 · 역설계가 함께 쓴다
- 가격표는 화면을 옮겨도 남아(`pricesLoad`) 화면 이동 확인에는 넣지 않는다
- `S.editDrafts` 약속: 인라인 편집기를 가진 모듈은 저장하지 않은 입력이 생기면 `S.editDrafts.<키>` 를 true 로, 저장 · 버리기 · 닫기 때 false 로 둔다
- `S.editDrafts` 의 키는 그 모듈이 정한다. `app.js` 는 키를 쓰지 않고 true 인 값이 있는지만 본다(`editDraftOpen`)
- 화면 이동이 이어지면(버리고 이동을 골랐거나 남은 입력이 없음) `app.js` 가 `S.editDrafts` 를 `{}` 로 비운다. 떠난 화면의 편집기는 이미 사라졌다
- 버리고 이동을 고르면 true 인 키마다 그 모듈이 `onEditDiscard(키, 함수)` 로 맡긴 함수를 불러 초안도 버린다(`discardEditDrafts`). 돌아왔을 때 버린 글이 되살아나지 않는다
- 시작할 때 읽는 집필 방식(`S.mode`, localStorage `canon.mode`)은 try 로 감싼다. 저장소를 막은 브라우저도 기본값 api 로 연다(`tests/test_app_core_js.py`)
- `showError` 는 키 없음(`no_key`)과 키 틀림(`bad_key`) 모두 설정을 열지 묻는다
- `run` 이 실패를 알릴 때 다시 시도할 만한 실패(`retryable`: status 0 · 429 · 5xx)면 같은 `run(label, fn, opt)` 을 다시 부르는 '다시 시도'를 붙인다
- `run` 의 `opt.retry: false` 는 '다시 시도'를 붙이지 않는다. 저장하고 이동(hashchange)이 쓴다: 저장만 되풀이하면 이동이 이어지지 않는다
- 기다리지 않기(`aborted`) · 입력 확인(4xx) · 화면 안에서 던진 오류에는 '다시 시도'를 붙이지 않는다
- `showError` 는 글에 API 키 · 연결이 있으면 '설정'을 붙인다(`hub.js` `hubAttention` 과 같은 기준)
- 서버에 닿지 못한 실패(status 0)에는 '설정'을 붙이지 않는다. AI 설정으로 고칠 수 없다
- 보통 알림 `toast` 는 글 길이만큼(`toastLife`, 최대 10초) 남고 마우스 · 포커스가 있으면 멈춘다. 동작 버튼(`.t.act`)을 붙일 수 있고, AI 작업이 끝나면 결과 화면이 아닐 때 '가서 보기'를 붙인다
- `proposalActions(drop, apply, label, disabled)` 는 AI 제안 버튼 줄 하나뿐이다. 인물 설정 · 신체 · 호칭 · 설정 기록 · 장면 연출 비교도 이것을 쓴다
- 상태 `S`
- 서버 호출 `api`
- 작품 저장 `save` 는 받은 판(`projectBase` 의 `keys` · `eps`)과 달라진 칸 · 화만 `PATCH` 로 보낸다(`patchBody`)
- 서버가 본문 있는 화를 지켜 `X-Canon-Kept` 에 `episode` · `text` 를 담으면 `save` 는 토스트로 알리고 '저장했어요'를 띄우지 않는다
- 빠진 화(`episode`)는 '본문이 있는 화를 빼는 저장이라' 토스트에 화 지우기를 알려 준다
- 비운 본문(`text`)은 대개 이 화면의 옛 사본이라 '서버에는 본문이 있는 화라' 중립 토스트로 알린다. 같은 화를 플롯 보호(`locked`) 토스트가 이미 알렸으면 띄우지 않는다
- 본문 고침을 시작한 저장 본문은 `TEXT_BASE`('작품:화')에 적는다(`markTextBase` · `textBase`). 본문 저장 요청 몸은 `textBody`(서버 `Text.base`)
- 작품 전체 GET 은 받은 판을 `projectCache` 에 두고 304 면 그 복사본을 쓴다
- `isProjectJson`(`meta` 와 `episodes` 배열)인 답만 작품으로 받고 보관한다. 보관한 판으로 물었는데 아니면 보관한 것을 버리고 조건 없이 다시 받는다(`tests/test_project_cache_js.py`)
- 작품 GET 이 돌려준 작품 객체는 화를 뺀 나머지의 판(`X-Project-Rest`)을 `restOf` 에 둔다
- 한 화 작업(본문 쓰기 · 스토리보드 · 큐 시트 · 한 화 플롯 · 검수 · 고침안)이 끝나면 `mergeEpisodes` 가 그 화만 받는다(`touchedEpisodes`, `GET /episodes`)
- 쓴 뒤 바로 검수하는 작업 `write` 는 본문을 저장한 걸음(`step_ep` 가 그 화)에서 그 화를 먼저 받고 `S.jobsMerged` 에 걸음을 적는다
- 화만 받기는 나머지 판 · `edit_rev` · `saved_by` · 화 번호 목록이 서버와 같을 때만 쓴다. 하나라도 다르거나 요청이 실패하면 작품 전체를 받는다(`tests/test_merge_episodes_js.py`)
- 화면을 잠그지 않은 요청이 돌려준 작품은 `takeEdited` 가 받는다. 그사이 입력이 있었으면 그 화와 대화 기록 · `edit_rev` 만 받아 저장하지 않은 다른 입력을 지킨다
- 저장 응답(`X-Project-ETag`)으로 보관할 때도 `X-Project-Rest` 를 함께 보관한다. 반영 → 304 → 한 화 작업 끝에서도 화만 받는다
- 화만 받으면 `patchCache` 가 `projectCache` 의 그 화를 고치고 판을 화 GET 의 `etag` 로 올린다. 다음 화면 이동의 작품 GET 이 304 로 끝난다
- `patchCache` 는 보관한 것의 나머지 판 · `edit_rev` · `saved_by` · 화 번호 목록이 화 GET 답과 같을 때만 고친다. 아니면 옛 판을 둬서 다음 작품 GET 이 전체를 받는다
- 화만 받기는 요청하지 않은 화를 맞춰 보지 않는다. 저장 기록을 올리지 않는 쓰기(명령줄)가 다른 화를 바꾸면 그 화는 다음 파일 변경까지 옛것이다
- 화 상태 칩 · 범례 · 툴팁 글자 `STATUS`(초안 · 확정 · 작성됨 · 반영 완료). 서버 `autorun.EP_STATUS` 와 같은 글자
- 본문을 쓴 모델 글자 `writerLabel`(`Episode.written_by` · `TextVersion.model` → '모델 · 백엔드', 백엔드 이름 `WRITER_BACKEND`, `tests/test_write_js.py`)
- 단계 이름 `stepLabel`(사이드바와 같은 이름, 다른 화면 문구도 이것을 쓴다)
- 작품 밖 화면(작품 목록 · 새 작품 `#/new` · 사용량 · 문체 라이브러리 · 레퍼런스 원고 · 역설계 실험 · 쇠맛 실험실)의 사이드바 `outSidebar`
  - 항목은 순수 함수 `outNav`: 작품 목록 · 새 작품 · 새 플레이, 최근 작품 셋, 작품 밖 도구(아직 열지 않은 화면 자리는 `.nav-off`)
  - 본문 `.out-main` 폭 `--out-w` · `@container out`
  - 작품을 읽지 못한 화면(주소가 틀림 · 불러오기 오류)도 작품 밖 사이드바 안에 그린다(본문 720px)
- 사이드바
  - `sidebar`: 맨 위 줄 `sideTop` · 작품 칸 · 단계 · 접는 묶음 `navFold`(작품 도구 · 아직 안 쓴 도구 · 실험, 펼침 `navFoldOpen`) · 아래 고정 줄 `sideFoot`(설정 · ⋯ 메뉴)
  - 줄 끝 배지 `navBadges`(순수 함수, `tests/test_sidebar_js.py`) · `navBadge`
  - 64px 레일로 접기 `toggleRail` · `syncRail`(901~1599px 에서 대화 패널을 열면 저절로)
  - 900px 이하는 위쪽 띠와 왼쪽 서랍 `drawerHead`
- 창 폭 경계 `BP`(phone 640 · narrow 900 · chatRail 1599)와 `mq(이름)`: app.css `@media` 와 같은 값이다. `hub.js` · `review.js` 도 이것을 쓴다
- 휴대폰 키보드 높이 `--kb`(`visualViewport`, 80px 아래와 두 손가락 확대는 0): 아래 시트 · 찾기 팔레트가 키보드 위에 선다
- 숫자 칸 자판 `numberKeypads`: `inputmode` 가 없는 `type=number` 칸에 붙인다(소수 `step` 은 decimal, 아니면 numeric). `MutationObserver` 로 그려질 때마다 한곳에서 붙인다
- 사이드바 아이콘(`navItems` · `navMark`: 단계는 번호, 그 밖은 토스페이스 이모지 `.tf`, 출처 문구는 사이드바 아래, Swift `Screen.mark` 와 같은 글자)
- 사이드바 작품 칸(`workCard`: 제목 · 갈래 · 플레이 사본(`play.js` `playSideTag`) · 장편은 지금 부 · 아크(`partOf` · `arcOf`), 화 칸 띠는 단편 전체 · 장편 지금 아크, 다음 할 일은 `home.js` `nextStep`, 좁은 폭 위쪽 띠 줄이기는 `app.css` `.work-card`)
- 한 화 화면(집필 · 검수 · 상태 승인)이면 작품 칸에 화 제목 · 작품 이름 · 화 상태 줄(`.work-ep`)을 더한다. 640px 이하 위쪽 띠에서만 보인다
- `.work-ep` 둘째 줄 끝에 시점 인물(`plot.js` `povChar`)을 '이름 시점'으로 붙인다. `povChar` 가 없으면(시험에서 plot.js 를 안 읽음) 뺀다
- 4 · 5 · 6 줄이 가리키는 화(`navEp`: 한 화 흐름 `FLOW_PAGES` · 작업지시서는 보는 화)
- 900px 이하 위쪽 띠는 화면 위에 붙고 높이 `--band` 만큼 본문의 붙는 칸을 내린다
- 서랍을 연 동안 뒤는 `inert`(`syncRail`)
- body 바로 아래 층(칸 밖 저장 띠 `#savebar`, 알림 창 `#hub-pop`)도 서랍을 연 동안 `inert`다. 알림 말풍선 `#toast`(닫기 · 할 일 버튼)는 뺀다
- 백그라운드 작업 · 검토 대기 결과
- 검토 대기 상태 변경안에 초안이 있으면 `loadPending` 이 받은 그대로를 놓은 뒤 초안의 변경안 · 체크로 바꾼다(`restoreDeltaDraft`)
- 초안을 되살려도 본문을 고쳤다는 알림은 그대로 뜬다
- 멈췄지만 AI 응답을 기다리는 작업(`S.jobsHeld`)이 있는 화는 `jobBtn` 이 `EP_AI_KINDS` 버튼을 '응답 기다리는 중'으로 잠근다(`epWaiting` · `epWaitNote`, 서버 `jobs.waiting_on` 과 같은 셈)
- 멈춘 스토리보드 작업의 응답이 오면 `JOB_LATE.board` 가 남겼는지 알리고, 남겼으면 그 화를 다시 받는다
- 짧은 기다림 가림막 `run`(`#busy`): 상자 이름은 작업 이름(`#busy-label`)이고, 1초마다 바뀌는 경과 초(`#busy-sec`)는 낭독하지 않는다
- `run` 은 가림막을 바로 띄우되 400ms(`BUSY_DELAY`) 동안 투명하게(`busy-wait`) 둔다. 그 안에 끝나면 화면이 어두워지지 않고, `inert` · 상자 포커스는 바로 걸며, 누른 버튼에는 `aria-busy` 와 돌림표(`run-wait`)를 단다. `opt.now` 는 바로 어둡게 그린다
- 알림 말풍선(`toast`, 작업 실패는 '다시 시도' · '설정' 버튼, 기록과 자리는 `hub.js`)
- 말풍선 글은 `toastSay` 가 숨은 낭독 칸에 넣는다: 오류는 `#sr-alert`(`role=alert`), 보통 알림은 `#sr-live`(polite)
- `toastSay` 는 글마다 새 줄을 덧붙이고 8초 뒤 지운다. 이어 온 알림도 모두 읽힌다
- 저장 띠의 '저장하지 않은 변경이 있어요' 안내도 `toastSay` 로 덧붙인다
- `#toast` 는 낭독 칸이 아니다. 알림 창이 열려 말풍선을 숨겨도 낭독은 들린다
- 작업 목록을 받을 때마다 `notify.js` 의 `notifyJobs` 를 부르고, 탭 제목에 안 본 알림 수를 붙인다(`notifyTitle`)
- 입력 바인딩(`data-bind`)
- 공통 동작(`actions` 의 저장 · 되돌리기 · 작품 관리)
- 펼침 메뉴(`menuBtn`, 열린 메뉴 `S.popMenu`, Esc · 바깥 누르기로 닫기)와 `#app` 밖 대화상자(`showDialog`)
- 확인 대화상자 `askConfirm`(Promise<boolean>) · `askText`(Promise<string|null>): 브라우저 `confirm` · `prompt` 대신 쓴다(디자인 시스템 Dialog)
- 확인 대화상자를 부르는 동작은 `async` 로 두고 `await` 로 답을 기다린다
- `danger` 이고 `alt` · 입력칸이 없으면 첫 포커스는 취소 버튼이다. 열자마자 Enter 로 위험한 동작을 고르지 않게 한다
- `confirmDrop` · `confirmRedraft` 도 Promise 를 돌려준다
- 화면 이동 확인(저장하지 않은 변경): 묻는 동안 주소를 이전 주소로 되돌려 두고, 이동을 고르면 새 주소로 바꿔 이어 간다
- 화면 파일에 브라우저 `confirm` · `prompt` 가 남지 않았는지 `tests/test_ask_js.py` 가 본다
- 라우팅
- 사이드바
- 다시 그리기와 포커스
- `drawApp` 은 `paintApp` 으로 `#app` 을 그린다. `data-keep` 칸은 그 칸과 조상을 제자리에 두고 형제만 새 것으로 바꾼다(`keepSwap`)
- Chrome 은 요소를 문서에서 떼거나 옮기기만 해도(`moveBefore` 포함) 그 칸의 Ctrl+Z 기록을 지운다. 그래서 `data-keep` 칸은 떼었다 끼우지 않는다
- `keepSwap` 은 키가 새 HTML 에 없거나, 조상 깊이 · 태그가 다르거나, `value` 가 다르면 지키지 않고 `#app` 을 통째로 바꾼다(`tests/test_keep_editor_js.py`)
- `afterDraw` 는 포커스가 그대로 남은 칸(지킨 칸)의 커서 · 칸 안 스크롤을 다시 옮기지 않는다
- 화면 코드는 화면 파일(`settings.js` · `home.js` · `setup.js` · `style.js` · `plot.js` · `write.js` · `review.js` · `research.js` 등)에 있다
- 화면 파일은 `viewX` 와 `Object.assign(actions, {...})` 로 붙는다
- 화면 파일은 `index.html` 에서 `app.js` 바로 뒤에 읽는다
- 화면 파일이 모두 실행된 뒤(`DOMContentLoaded`) 첫 화면을 그린다

### `canon/static/board.js`

- 집필 화면 스토리보드 카드(`write.js` 의 `viewWrite` 가 부른다)
- 본문 없는 화의 만들기 · 바로 쓰기 · 스토리보드 없이 쓰기(`boardStart`)
- 만든 카드(`boardCard`: 어긋남 · 확정 값 · 넘겨받을 것 · 깨지 않을 것 · 장면, 낡음 표시, 다시 만들기 · 이대로 쓰기)
- 고치기(`boardForm`, 칸 글 읽기 `boardParse`, `tests/test_storyboard.py`)
- 만든 카드는 중심 장면(`focus`)에 '중심 장면' 칩을 단다. 고치기에는 중심 장면 번호 칸이 있고, 장면을 빼면 번호를 맞춘다(`boardScene`)
- 저장한 것과 다른 고치기 칸과 보내지 않은 'AI에게 고치기' 요청은 페이지를 떠날 때 묻는다(`boardUnsaved`, `app.js` `onKeptDraft`)
- 쓴 화의 접은 카드(`boardPanel`)
- 계산 값은 `GET …/storyboard`(`board.view`)

### `canon/static/chat.js`

- 화면에 붙는 AI 대화 패널(플롯 대화는 `agent.js` 가 그린다)(901~1599px 은 사이드바를 레일로 접고 400px, 900px 이하는 아래 시트, 규칙은 `app.css` 의 `body.chat-open`. 기승전결 · 플롯 화면 `plot`, 집필 화면 `text:<화>`)
- 답을 기다리는 줄은 경과 초를 1초마다 고치고(`chatWaitTick`), 5초가 지나면 '기다리지 않기'(`chatStop`, AbortController)를 보인다. 기다리지 않기는 오류가 아닌 보통 알림이다. 초는 알림 칸(role=status) 밖에 둔다
- 보내기(`chatSend`)는 저장하지 않은 변경이 있으면 기다림 줄을 놓기 전에 묻는다. 취소하면 보내지 않고 쓴 글은 입력칸에 남는다
- `#chat-log` 는 `role="log"` 이지만 패널을 통째로 다시 그려서 `aria-live="off"` 다
- 새 답이 오면 맨 아래로 내리되, 마지막 AI 답이 칸보다 길면 그 답의 첫 줄로 간다(`chatLandAt`)
- 마지막 AI 답에 고르지 않은 본문 후보가 있으면 패널에 `has-cands` 를 단다. 주제의 `candsFor` 가 있으면 그것도 참이어야 한다
- 손가락 기기(`touchFirst`)에서는 패널을 열 때와 답이 온 뒤 입력칸에 포커스하지 않는다
- 주제의 `foldFrom(msgs)` 가 돌려준 번호 앞 메시지는 '지난 요청 N개'(`.chat-fold`) 아래로 접는다. 연 상태는 `S.chatFoldOpen` 에 둔다
- 다 접혔고 주제에 `foldNote` 가 있으면 그 안내를 보인다
- 새 AI 답만 패널 밖 숨은 알림 칸 `#chat-live`(role=status)에 넣는다(`chatAnnounce`, 처음 연 패널 · 다른 대화의 옛 답은 알리지 않음)
- 변경안을 칸별로 지금 값과 비교해 보여 주고 고른 것만 반영 요청
- 주제마다 요청 내용과 변경안 그리기를 `CHAT_TOPICS` 에서 바꿔 끼운다
- 플롯 대화는 대상(`plotScope`: 고른 아크 · 다음 아크 초안, 연 구간 · 화)을 함께 보낸다
- 플롯 대화가 그리는 것: 아크 칸 · 부 구성 변경안, 방향 여러 안(`optionsCard`), 다음 아크 안을 초안으로 놓기(`draftFromRev`)
- 적용한 플롯 변경안의 적용 취소(`chatUndo`, 서버 `pipeline.undo_plot_chat`)
- 서버 `pipeline.chat_target` · `chat_where` 와 같은 규칙(`tests/test_chat_js.py`)
- 화면 본체는 `plot.js` · `write.js`

### `canon/static/check.js`

- 5단계 검수 칸(한 화 화면의 검수 칸, 주소 `check/<화>`, `viewCheck` 는 `write.js` `viewEpisode(n, 'check')`)
- `checkPanel` 이 머리 보조 버튼 · 주 버튼 · 회차 띠 · 오른쪽 칸 `.c-side`(목록과 상세)를 돌려준다. 본문 칸은 `viewEpisode` 가 그린다
- 한꺼번에 검토(`fbView`)는 `checkPanel` 의 `full` 로 본문과 칸 자리를 차지한다
- 회차 띠(누르면 그 회차가 바꾼 지적 `roundChanges`, 새 판 구분) · 처리 상태 거르기
- 지적 목록(탭: 모순 지적 · 초반 점검 `openingChecks` · 문체 지표 `GET …/style`, 심각도 순 · 딸린 지적은 부모 아래 `findingOrder`)
- 본문(`draftBox` · `readHtml`, 지적 문장 밑줄 `findingRanges` 를 `marks.js` 의 `allRanges` 가 함께 그림, 바뀐 문장은 비슷한 문장 `nearQuote`)
- 지적 상세(심각도 `setSeverity`, 처리 상태 `setFinding`, 메모, 처리 기록)
- 메모 초안은 지적마다(`S.chkNotes`, 키 '화:id') 남아 다른 지적을 골라도 잃지 않는다
- 저장한 메모와 다른 초안이 있으면 `S.editDrafts.chkNote` 를 켠다
- `chkPut` 은 성공 여부를 돌려준다. 메모 저장이 실패하면 초안을 그대로 두고 저장했다고 알리지 않는다
- 문장에서 뜨는 고치는 창(`fixPanel`, `passage.js` 떠 있는 도구 mode `finding`: 고침안 `fixGet` · 딸린 곳 빼기 `fixSkip` · 적용 `fixApply` · 묶음 되돌리기 `fixUndo` · 이 지적만 다시 검수 `chkRecheck` · 다른 처리 길)
- 이 지적만 다시 검수의 결과(아직 어긋남 · 딸린 지적 더함)는 보통 알림이다. 아직 어긋나면 '처리 기록 보기' 버튼을 붙인다
- 고침안 한꺼번에의 띠(`fbBar`): 열린 지적 모두 고침안 받기 `fixAll`(작업 `fixes`), 한꺼번에 검토 열기 `fbOpen`
- 그 아래 더 거르기 칸(`chkNarrow`): 심각도 `S.chkSev` · 종류 `S.chkType` · 문장 바뀜 `S.chkChanged`, 수는 다른 칸의 거르기를 적용해 센다. 지적이 셋 미만이고 거르지 않았으면 두지 않는다
- 열림 목록을 더 걸렀으면 '거른 지적 N개를 한꺼번에' 줄(`chkBulk`)이 그대로 둠 · 잘못 짚음을 묻고 `PUT …/findings`(web `set_findings`)로 한 번에 정한다
- 한꺼번에 검토 화면(`fbView`): 지적마다 고르기 `fbPick` · 안 고르기 `fbOpt` · 딸린 곳 `fbSkip` · 모두 고르기 `fbAll`
- 한꺼번에 검토의 '고른 N개 넣고 다시 보기'(`fbApply`)는 모두 넣으면 검토 화면을 닫고 작업 `recheck` 를 바로 시작한다. 못 넣은 안이 있으면 화면을 남기고 시작하지 않는다
- 같은 문장을 바꾸는 안 표시(`fbClash`), 넣기 `fbApply`(`POST …/fixes/apply`), 되돌리기 `fbUndo`
- 고르기는 기본으로 켜지 않는다. 작업이 끝나면 `fixesJobResult` 가 검토 화면을 연다
- `fbNeed` 는 서버 `pipeline.fix_targets` 와 같은 셈
- 지난 검수 뒤 고침안을 넣은 열린 지적이 있으면 머리의 주 버튼은 '고친 곳만 다시 보기 · 지적 N'(`fixRecheck`, 작업 `recheck`, 대상 `home.js` `fixRecheckTargets`)이고 다시 검수 버튼은 보조 버튼으로 남는다
- `fixRecheck` 도 `app.js` `checkReady` 로 저장하지 않은 작품 변경을 먼저 묻고 본문을 저장한 뒤 작업을 시작한다
- 그때 회차 띠 아래 안내(`chkStrip` 의 `fast`)는 고친 문장과 앞뒤 문단만 보낸다고 알린다. 작업 결과 알림은 `JOB_DONE_MSG.recheck`
- 고침안과 함께 직접 고친 곳이 있으면(`chkOtherEdits`) 안내는 고친 곳만 다시 보기로 먼저 닫고 직접 고친 곳은 다시 검수로 보라고 알린다
- 마지막 회차가 바뀐 곳만 새로 짚었으면 회차 띠에 '바뀐 곳만'을 붙이고, 넣지 않은 새 지적(`CheckRound.outside`)이 있으면 그 수와 끄는 곳을 알린다
- 장면 연출 규칙 지적은 '규칙' 표시(`ruleChip`)와 '장면 연출에서 보기'(`stageLink`, `stgGo`)
- 다시 검수 버튼은 '판정 다시 보기'(LLM 없음)
- 머리의 '검수 옵션 ▾' 메뉴(`checkOptsMenu`): 넓혀 찾기(장편, `Settings.check_widen`) · 동선 따로 보기(`Settings.check_motion`) · 연출 함께 뽑기(`Settings.stage_extract`)를 체크 줄과 설명으로 모은다. 머리 줄에는 검수 · 상태 승인 버튼만 둔다
- `checkOptsMenu` 에는 쓴 뒤 바로 검수(`Settings.check_after_write`, `toggleCheckAfterWrite`)와 바뀐 곳만 새로 짚기(`Settings.check_scope`, `toggleCheckScope`)도 있다
- 표시 `findingFlag` · 밑줄 `findingMarks` · `findingOrder` · `roundChanges` · `nearQuote` · `fixMissing` 은 순수 함수(`tests/test_check_js.py`)

### `canon/static/convert.js`

- 단편 → 장편 전환 화면
- 이어 쓰기(총 화수 · 결말 처리, AI 전환 계획에서 항목 골라 반영)와 재구성(화 지도 고치기, 반영)
- 받은 그대로의 계획을 `S.convOrig` · `S.rbOrig` 에 둔다. 칸이나 체크를 고친 뒤 '다시 받기'를 누르면 먼저 묻는다(`planEdited` · `planRefetchOk`, `tests/test_convert_js.py`)
- 되돌리기
- 집필 화면의 재구성 안내 · 다듬기 비교(`rebuildNote`)도 여기 있다

### `canon/static/flow.js`

- 한 화 흐름
- 집필 · 검수 · 상태 승인 한 화 화면(주소 `write` · `check` · `review/<화>`, `write.js` `viewEpisode`)의 머리 아래 단계 띠(`flowBar`, 단계 글은 순수 함수 `flowSteps`, 이름 · 번호는 사이드바와 같음 `FLOW_STAGES`, 위치 줄 `flowEyebrow`)
- 상태 승인 칸은 변경안을 만든 뒤 본문을 고쳤으면(`S.deltaBase` · 저장하지 않은 고침) '본문 고침'으로 볼 것 남음 표시를 한다(`flowSteps` 의 `run.stale`)
- 짧은 이름 `FLOW_SHORT`(상태 승인 → 승인)는 640px 이하 한 화 화면 머리 한 줄에서만 보인다(`.fl-s`). 다른 화면 · 폭은 온 이름(`.fl-l`)이다
- '검수하기'(`flowCheck`: 검수 단계로 옮겨 검수, 첫 검수면 상태 변경안도 함께 `flowStateToo`, 끄기 `flowStateToggle` · localStorage `canon.flowState`)
- `flowCheck` 와 `app.js` `checkEp`(다시 검수)는 검수를 시작하기 전에 저장하지 않은 본문 초안을 저장한다(`passage.js` `flushText`, `check.js` `fixAll` 과 같다)
- 둘 다 `app.js` `checkReady` 를 쓴다: 저장하지 않은 작품 변경이 있으면 `startJob` 과 같은 물음으로 먼저 저장한 뒤 본문을 저장한다. 본문 저장이 `S.project` 를 서버 것으로 바꾸기 때문이다
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
- 다음 할 일 `nextStep`: 플롯 전이면 설정 필수 칸(`setupReqs`)이 빌 때 '설정 마저 채우기', 문체를 정하지 않았고 문체 화면에 안 들렀으면(`styleVisited`, localStorage `canon.styleVisited.<작품>`) 문체 정하기를 먼저 권한다
- `nextStep` 은 [글, 주소, 동작, 동작 글]을 돌려준다. 동작과 동작 글은 있을 때만 붙는다
- `nextStep` 의 글은 버튼 이름이라 동사이거나 화면으로 가는 '~로'다(자동 집필이 돌면 '자동 집필로')
- 주소만 읽는 곳(사이드바 `workCard` · 팔레트 · 장편 플롯 머리 `serialHead`)은 [글, 주소]만 쓴다. 그래서 글은 그 주소로 가는 일에 맞춘다
- 단편의 플롯 초안 화에서 다음 할 일 'n화 플롯 확정'은 그 화 플롯 페이지(`/arc/n`)로 간다
- 장편의 플롯 초안 화에서 'n화 플롯 확정'은 아크 화면(`/arc`)으로 간다. `plot.js` `serialHead` 가 이 주소를 보고 '아크 N 초안 k화 모두 확정'을 primary 로 둔다
- 모든 화를 반영하면 다음 할 일 버튼은 '완결 원고 내보내기'다(동작 글)
- '완결 원고 내보내기'는 동작 `exportAll`(`publish.js`)을 부른다. 이 동작이 전체 범위로 '여러 화 내보내기' 대화상자를 연다
- 모든 화를 반영했을 때 주소만 읽는 곳은 글 '완결 원고 보기'로 마지막 화 집필 화면에 간다
- 버튼에 쓰는 글 `nextStepLabel`: 동작이 있으면 동작 글, 없으면 글
- 다음 할 일 버튼 `nextStepHtml`: 동작이 있으면 `data-action` button, 없으면 a
- `nextStepHtml` 은 작품 홈 머리와 집필 머리(`write.js` `nextStepBtn`)가 쓴다
- 작품 홈 머리는 다음 할 일이 이야기 구조 화면(`/arc`, `/arc/n`, `isArcHref`)이면 이야기 구조 보조 버튼을 두지 않는다
- 작품 홈 '다음 할 일' 카드는 자동 집필이 돌 때 제목을 '자동 집필이 n화를 쓰는 중이에요'로 쓴다. '자동 집필로'는 버튼과 링크에만 쓴다
- 사이드바 자동 집필 메뉴 이름 `autoMenuLabel`: 돌면 '자동 집필 · 쓰는 중', 멈추면 그 까닭
- 작품 목록 `projectGo` 는 플롯 전 작품의 설정 필수 칸이 비면(`setup_ready` false) '설정 마저 채우기'로 보낸다
- `aiWarning` 은 Anthropic 키가 없거나(`claude_api` false) Claude 구독을 쓸 수 없으면(`claude` install · login · error) 첫 작업 전에 알린다
- `aiWarning` 의 글은 사이드바 아래 줄(`app.js` `sideFoot` 의 `.side-warn`)과 본문 안내 상자(`aiNote`)가 함께 쓴다
- `aiNote` 상자(`.ai-note`)는 사이드바가 펴진 901px 이상에서 숨는다. 레일 · 900px 이하에서만 보여 한 화면에 한 번만 나온다
- 사이드바가 없는 새 플레이 화면은 `aiNote(true)` 로 상자를 늘 보인다
- 작품 홈
  - 지금 화 `homeNowCard` · 확인할 것 `homeTodos`(말투 빈 인물 `homeSpeechGaps`, 시점 인물 서술 말투 빈칸 `homeVoiceGap`) · 전 화수 막대 `homeProgress` · 줄인 목록 `homeCast` · `homeForeshadows`
  - 계산 함수는 작품을 받는 순수 함수 `tests/test_home_js.py`
  - 확정 사실 줄 끝의 'n화' 링크는 그 화 상태 승인 기록(`/review/n`)으로 간다. 들어온 화는 `factsLearned`(`context.facts_learned` 와 같은 규칙)
- 장르 · 화 진행 막대와 연재 일정(`epSteps`, 검수 칸 `checkState`, 화를 열 단계 화면 `epStage`: 다음 할 일 · 화 칸 · 팔레트, 작품 목록 다음 할 일 `projectNext` 는 서버 `findings.check_done`, `releasePlan`, `Project.release`)
- 연재 일정 줄의 'n화 올림으로 표시'(`releaseOne`)는 올린 화를 하나 늘려 저장한다
- 저장한 뒤 알림에 '되돌리기'(`releaseUndo`)를 둔다
- `releaseUndo` 는 같은 작품이 열려 있고 올린 화 값이 그사이 바뀌지 않았을 때만 하나 줄여 다시 저장한다
- 고친 곳만 다시 볼 지적 `fixRecheckTargets`(서버 `findings.fix_recheck_targets` 와 같은 셈, `check.js` 머리 버튼이 쓴다)
- `fixRecheckTargets` 는 직접 고친 곳이 함께 있어도 고침안을 넣은 지적을 돌려준다

### `canon/static/hub.js`

- 알림
- 진행 줄은 AI 호출이 기다리거나 다시 부르는 중이면 `Job.retry` 를 note 대신 보이고 남은 시간 어림을 뺀다
- 손가락 기기에서는 알림 창 아래 'Esc로 닫아요' 안내를 비운다
- AI 작업과 알림을 버튼 하나에 모은다
- 버튼(`hubButton`, 사이드바 · 작품 밖 사이드바의 `#hub-slot`)
- 버튼 아래 창(`#hub-pop`: 확인할 것 · 진행하는 중 · 최근 알림 · 접힌 끝난 작업과 지난 알림, `hubOpen` · `hubClose`)
- 말풍선과 창 자리(`placeHub`, `#toast`)
- 실패한 작업 줄 제목은 '<작업> · 끝내지 못했어요'다(끝내지 못한 지난 시도 줄과 같은 꼴)
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
- 작가가 쓴 칸을 다른 후보로 바꿀 때는 묻는다(목록 칸은 한 줄 더하기라 묻지 않음)
- 칸 목록 `IDEA_FIELDS` 는 `prompts.FIELD_IDEAS` 와 같다(`tests/test_ideas_js.py`)
- 목록 칸 `IDEA_LISTS`(숨기는 것)는 고른 후보를 목록에 한 줄 더한다(`prompts.IDEA_LISTS` 와 같다)
- 인물 칸(성격 · 배경 · 외모 · 아크)은 경로 번호를 `*` 로 찾는다(`ideaKey`, 이름 붙은 칸 이름 `ideaLabel`)
- 받은 때의 인물 id 가 다르면 넣지 않는다(`tests/test_setup_fill.py`)
- 서버는 `pipeline.suggest_field`

### `canon/static/index.html`

- 웹 화면 한 쪽
- 화면 파일을 `<script>` 로 읽는다
- 브라우저 탭 아이콘은 `static/favicon.svg` 다(먹색 C 와 귤색 점, 색은 `docs/design/tokens.json` 의 `logo` · `brand-2`, 어두운 모드 값은 SVG 안 `prefers-color-scheme`)
- 읽는 차례: `app.js` → `outline.js` → `hub.js` → `notify.js` → 화면 파일들(`check.js` 바로 뒤 `flow.js`, `atlas.js` 바로 뒤 `atlas-*.js`)
- 새 화면 파일을 더하면 여기에 `<script>` 를 넣는다

### `canon/static/marks.js`

- 집필 화면 문체 표시
- 손가락 기기에서 밑줄 친 곳은 같은 자리를 2초 안에 한 번 더 눌러야 이름 카드 · 도구를 띄운다(`markTap`). 빠른 두 번 누름으로 낱말이 골라지면 그것도 두 번째 누름으로 친다
- 손가락 기기에서 글이 있는 본문 칸은 읽기 전용 고르기 칸이다(`draftBox` 의 `data-pick`, 문장 고르기는 `passage.js`). AI가 처음 쓰는 중이라 잠긴 칸과 빈 본문은 그대로다
- `draftBox` 의 본문 칸은 `data-keep="draft-<화>"` 다(`app.js` `paintApp`)
- 장치마다 이번 화 배지(`deviceBadges`, 본문 띠의 '문체 장치' 메뉴 `styleMenu`)
- `styleMenu` 버튼은 640px 이하 집필 화면에서 `Aa` 아이콘만 보인다(이름은 `aria-label`)
- 본문에서 장치 글자 · 금지 표현 밑줄(고치는 본문은 textarea 뒤에 깐 칸 `hl-layer`, 스크롤은 CSS 스크롤 타임라인 `hl-follow` 로 따라가고 안 되는 브라우저만 `scrollTop`, 읽기 전용은 `<mark>`)
- 밑줄에서 부분 수정 도구 띄우기
- 경고의 'AI에게 고치기'가 그 화를 고치는 동안 `draftBox` 는 본문 칸을 잠근다(`aiFixing`)
- 쓴 화 세기와 쉬는 화 판정은 `metrics.device_hits` · `device_last` · `prompts.device_block` 과 같은 규칙이라 함께 고친다(`tests/test_marks_js.py` 가 node 로 맞춰 본다)

### `canon/static/mentions.js`

- 집필 화면 본문 속 이름
- 손가락 기기에서는 이름 목록 안내에서 Alt+Enter 를 빼고 '본문의 이름을 누르면 떠요' 만 보인다
- 인물 이름 · 장소(`atlas.places` 와 같은 목록 `mentionPlaces`)를 정규식 하나로 찾기(`mentionRanges`, 조사 · 긴 낱말 규칙, 치는 중에는 자리 옮기기 `mentionShift`)
- 밑줄은 `marks.js` 의 `markHtml` 이 함께 그림
- 이름 카드 자리 `mnPlace` 도 왼쪽을 0으로 두고 너비를 잰다(`passage.js` 의 `placeTool` 과 같은 규칙)
- 이름 카드(이 화 시작 시점 `/cast` 프레임을 `S.mnCast` 에 따로 받아 `cast.js` 함수로 읽음, 장소는 설명과 지도)
- 켜기 · 끄기(localStorage)
- 규칙은 `tests/test_mentions_js.py` 가 node 로 맞춰 본다

### `canon/static/mystyle.js`

- 나만의 문체
- 스타일 프로필의 가끔 쓰는 장치 고치는 칸(`deviceFields`)
- 문체 화면의 맨 위 '확인할 것' 카드(고르지 않은 규칙 후보 `learnTodoCard`)와 재료 묶음의 '내 수정에서 배우기' 카드(`learnCard`, 서버 `pipeline.learn_style` / `apply_learning`)
- 라이브러리 항목의 버전 목록
- 장치의 쓴 화 세기는 `metrics.device_last` 와 같은 규칙

### `canon/static/notify.js`

- 작업이 끝나면 알리기
- 알림을 꺼 두어도 탭이 뒤에 있으면 탭 제목 앞에 끝난 수를 붙인다(`notifyWays`). 브라우저 알림은 켰을 때만
- 처음 AI 작업을 시작할 때 한 번만 시작 말풍선에 '브라우저 알림 켜기'를 붙인다(`notifyOffer`, localStorage `canon.notify.asked`)
- 탭이 뒤에 있거나 창에 포커스가 없을 때 브라우저 알림(Notification API)을 보내고 탭 제목 앞에 수를 붙인다
- 탭을 보고 있으면 `app.js` 의 말풍선이 이미 알리므로 보내지 않는다
- 자동 집필의 화별 반영(서버 `Job.step_ep`)은 말풍선이 없어 탭을 보고 있으면 말풍선을 띄운다
- 알림을 누르면 그 탭으로 와서 결과 화면(`JOB_LINK`)을 연다
- 켜기 · 끄기와 알릴 작업 묶음(`NOTIFY_GROUPS`: 본문 쓰기 · 다시 생성 · 검수 · 상태 변경안 · 자동 집필 · 그 밖)은 localStorage `canon.notify`
- 권한은 설정 › 이 브라우저 › 알림에서 켤 때만 묻는다(`notifyTurnOn`)
- https 나 localhost 가 아닌 주소는 브라우저 알림을 쓸 수 없어 탭 제목에만 표시한다(`notifyPermission` 'unsupported')
- 켜 두면 도는 작업이 없어도 30초마다 작업 목록을 묻는다(다른 탭 · 기기 · 명령줄에서 시작한 작업)
- 계산은 순수 함수 `notifyPrefs` · `notifyGroup` · `notifyEvent` · `notifyWays` · `notifyTitle`(`tests/test_notify_js.py`)
- `index.html` 에서 `hub.js` 바로 뒤, `settings.js` 앞에 읽는다

### `canon/static/opening.js`

- 초반 1~3화
- 집필 화면의 초반 점검 카드(지표 경고, 흡입력 판정, 여는 방식 비교본, 반영 끝난 화는 비교를 감춤)
- 플롯 편집기의 여는 방식별 플롯 안(고르기 전 플롯은 `Episode.opening_prev`, 되돌리기 `pipeline.undo_opening`)
- 서버는 `pipeline.opening_metrics` · `check_hook` · `suggest_openings` · `apply_opening` · `research.run_opening_compare`
- 규칙은 `prompts.opening_rules` / `OPENING_APPROACHES`
- 지표는 `metrics.measure_opening`

### `canon/static/outline.js`

- 공용 목차 틀
- 왼쪽 목차 + 오른쪽 카드 한 열
- 쓰는 화면은 `docs/design/components/Outline/README.md` 의 '쓰는 화면'에만 적는다
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
- 640px 이하는 찾기 칸 오른쪽에 닫기 버튼 `.pal-x`(화면을 거의 다 덮고 Esc 가 없다)
- 찾기 칸은 휴대폰 키보드 Enter 가 '이동'(`enterkeyhint="go"`)
- 손가락 기기에서는 '저장' 줄의 Ctrl+S 안내를 숨긴다
- CSS 는 JS 에서 주입

### `canon/static/passage.js`

- 본문 부분 수정
- 손가락 기기에서 검수 지적을 열면 본문 칸에 포커스하지 않는다(키보드가 고치는 창을 덮지 않게). 문장 자리만 고른다
- 손가락 기기에서 경고의 'AI에게 고치기'로 고친 뒤에도 본문 칸에 포커스하지 않는다(`S.selFocus.quiet`). 포커스가 남으면 키보드가 올라오고 다시 그리기가 밀린다
- 본문 밖에서 시작한 터치는 떠 있던 메뉴를 닫고, 그 터치의 touchend · mouseup 은 본문 칸에 남은 선택으로 도구를 다시 띄우지 않는다(`outsideTouch`)
- 도구 버튼을 누르고 뗀 것(`#sel-tool` 안)은 고르기로 보지 않는다
- 손가락 기기의 고르기 전용 본문(`textarea[data-pick]`)은 문장 단위로 고른다: 짧게 누르면 그 문장, `PICK_HOLD`(200ms) 누른 채 끌면 지나간 문장들, 누르자마자 끌면 화면을 굴린다
- 문장 범위는 `sentenceRanges`(줄바꿈과 . ! ? … 닫는 따옴표까지), 손가락 자리의 문장은 `sentenceRects` 로 한 번에 재고 `pickAt` 이 찾는다
- 고른 문장을 2초 안에 다시 누르면 고르기를 풀고 그 자리(`pickOffset`)에 커서를 둔다. 그 클릭은 `marks.js` 가 두 번째 누름으로 쳐(`pickAgain`) 밑줄 이름 카드 · 도구를 띄운다
- 900px 이하에서 메뉴와 직접 수정 칸은 화면 아래에 붙는다(`toolDocked`, `.sel-tool.docked`). 고른 부분 끝이 도구에 가리면 페이지를 굴린다
- 도구의 'AI에게 고치기'(`selAi`)와 후보 넣기(`passageApply`)는 그 글을 다시 골라 휴대폰 시트 위에 보이게 굴린다. 손가락 기기는 본문 칸 포커스를 푼다
- 본문을 굴릴 때 900px 이하에서 시트가 열려 있으면 위쪽 띠(`--band`)와 시트 사이를 보이는 자리로 본다(`syncPassage`)
- `text` 주제의 `candsFor` 는 후보가 지금 고른 부분(`curSel`)의 것인지 본다. 다른 부분을 새로 골라 열면 시트를 높이지 않는다
- `text` 주제의 `foldFrom` 은 지금 고른 부분과 이어지는 맨 뒤 대화만 편다(`passageRelated`: 같은 부분이거나, 그 답의 후보를 넣어 고른 부분이 넣은 글이 됨)
- 답의 후보를 넣은 수정 기록은 `passageEdit` 이 찾는다. 그대로 넣으면 `proposed` 가 비고 `after` 가 후보다
- 방금 넣은 답 아래에는 다음에 할 것 줄(`.next-acts`: 되돌리기 · 이어서 고치기 `passageMore` · 닫기)을 둔다. 되돌리면 사라진다
- 수정 되돌리기 · 다시 넣기 뒤에도 손가락 기기에서는 본문 칸에 포커스하지 않는다
- 본문에서 고르면 뜨는 도구(직접 수정, AI에게 고치기)
- 도구 자리 `placeTool` 은 왼쪽을 0으로 두고 너비를 잰다. 옛 자리에서 재면 남은 폭만큼 줄어 화면 오른쪽 끝에 붙는다
- 후보를 원문과 단어 단위로 비교
- 수정 기록과 되돌리기
- 고친 뒤 다시 할 단계 알림
- 상태 정리 경고에서 «» 문장을 찾아 고르기(`warnQuote`, `warnItems`, `warnPick`)
- 경고의 'AI에게 고치기'는 대화 패널을 거치지 않고 첫 후보를 바로 본문에 넣는다(`aiFixNow`: 저장 → `POST …/fix-now` 한 번 → 되돌리기 · 상태 승인으로 알림). 후보가 없으면 대화 패널을 연다
- `aiFixNow` 는 AI를 기다리는 동안 화면을 잠그지 않는다. 그 화 본문 칸만 잠그고(`S.aiFix`, `aiFixing`) 다른 화면으로 가도 끝나면 알린다
- 바로 넣는 것은 경고에 옮겨 적은 글이 본문에 그대로 한 번만 있을 때다(`warnSpot` 의 `exact`). 아니면 그 문장을 골라 경고를 대화 입력칸에 넣고 보내기는 작가가 한다
- 경고 줄 뒤의 버튼 · 표시는 `warnTools` 하나가 그린다(집필 `warnItems` · 상태 승인 `rvWarnLine`): 고치는 중, 'AI가 고침'(`warnFixed`: 되돌리지 않은 AI 수정의 요청 글이 그 경고), 버튼
- 되돌리기 알림 `undoToast` 는 `toast` 의 동작 알림이다. 누르거나 포커스가 있는 동안 닫히지 않고 알림 창 '최근 알림'에 남는다
- 상태 승인 화면의 경고에서 집필 화면으로 옮길 때는 `goThen` 으로 그 화면을 다 그린 뒤에 고른다
- 서버는 `pipeline.edit_text` · `revise_passage` · `apply_passage` · `undo_edit`

### `canon/static/plot.js`

- 3단계 기승전결
  - 공용 목차 틀 `outline.js` 의 왼쪽 목차 + 넓은 보드 `plotLayout`(`wide`)
  - 720px 이하 목차는 위에 붙는 버튼 `plotToc`
  - 목차 안에서 펼침을 지키는 부 접기 · 아크 펼치기 줄은 `data-outline-keep`
  - 목차의 진행 막대 `plotMeter` · 구간 줄 `actTocItems`(누르면 `jumpAct`) · 확인할 것 `plotTodos`(관계를 한 화에 너무 많이 옮기는 화 `pacePlot`, `pace.plot_warnings` 와 같은 규칙 `tests/test_plot_pace_js.py`)
  - 머리의 'AI로 다시 만들기 ▾' `plotAiMenu`(요청 칸 `S.planNote`)
  - 구간 한 줄 머리 + 화 카드 격자 `actBoard`
  - 단편은 보드 위에 열 계획 카드(`heatplan.js` `heatCard`, story.md)
  - 장편은 고른 아크 보드 위에 그 아크의 열 계획 카드(`heatCard(p, arc)`)
  - 구간 · 아크 · 부 고치기는 서랍 없이 그 자리에서 `actEditor` · `arcEditor` · `partEditor`
  - 아크 주요 인물 이름 체크 `arcCastField`
- 640px 이하 사건 줄의 도구(연출 · 위로 · 아래로 · 빼기)는 숨기지 않고 사건 글 아래 줄 오른쪽에 둔다
- 손가락 기기에서는 사건 순서의 'Enter로 다음 사건' 안내를 숨긴다
- 장편(목차가 부 › 아크 › 구간 나무 `serialTree` · `serialTocRow`, 부 펼치기 `S.tocParts`, 부 구성 카드 펼침 `S.arcFull`, 다음 아크 기획 칸의 경고 `planAhead` 는 `pipeline.plan_ahead` 와 같은 규칙 `tests/test_plan_ahead_js.py`)
- 서술 시점
- 화 플롯 페이지
  - `viewPlotPage`
  - 주소 `arc/<화>`
  - 목차는 이웃 화 목록 `epTocItems`
  - 카드 한 열: 이어받는 것 · 줄거리 · 인물 · 시점 · 끝과 이음 · 복선 · 접은 화 도구
  - 사건마다 한 칸 `eventsField`
  - 글이 있는 사건을 빼면(`dropEvent`) 저장 띠의 '방금 지운 n화 사건 k 되살리기'로 그 화 사건 목록을 빼기 전으로 돌린다(`rememberRemoved`)
  - 옮기기 전 저장 `openPlot` · `closePlot`
  - 저장 띠는 아래 붙는 버튼 줄의 `.savebar-slot`
- 플롯 편집기 등장 인물(목차 계산 `tests/test_plot_js.py`)

### `canon/static/research.js`

- 연구 화면
- 마우스가 없으면(`hover: none`) 표 칸 아래에 큰 블록 비중(`.rs-parts`)을 적는다
- 공용 목차 틀 위의 카드 한 열(`.rs-wrap`, 오른쪽 열은 960px 까지)
- 주소 `#/p/<이름>/research[/<쪽>]`(`rsLoad(쪽)` · `rsUrl`)
- 목차: 개요 · 준비(서버 점검) · 실험 여섯(샘플 생성 · 단계 시험 · 컨텍스트 크기 · 검수 시험 · 블라인드 비교 · 상태창 시험) · 기록
- 기록 줄(`rsLogLine`)은 도중에 멈춘 상태창 시험이면 `stopped` 문구를 붙인다
- 목차 꼬리와 개요 카드는 쪽마다 마지막 결과 요약(`rsBrief`, 서버 `latest` · `open_compares`)
- 개요: 이어서 볼 것(고르지 않은 비교본, 한도 넘침) · 실험 카드 · 최근 기록
- 실험 쪽: 설정 카드 → 결과 카드 → 지난 기록(`rsPast`)
- 지난 기록을 열면 같은 결과 카드에 다시 그린다(`rsOpen` · `rsEntry`)
- 머리 주 버튼은 쪽마다 하나(`rsPrimary`)
- 백엔드는 칩으로 고른다(`rsPicker`, 샘플 생성은 여럿 `rsMultiPicker`)
- 칩 후보는 설정값 · 서버 점검 모델 · 기록에 남은 백엔드(`rsCands`)
- 칩에 없는 백엔드는 '+ 다른 백엔드 적기'로 칸을 편다
- 컨텍스트 크기의 화별 표는 기록에 남지 않아 방금 잰 결과(`S.rs.cur`)에만 있다
- 칸 폭 560px 이하(`@container outline`)의 결과 표는 줄마다 칸을 쌓는다(`.rs-stack`, 칸 이름 `data-label`)
- `rsCands` · `rsParse` · `rsBrief` · `rsLogLine` · `rsCheckCalls` 는 순수 함수(`tests/test_research_js.py`)
- 블라인드 비교 고르기(`rsPickDraft`)는 본문으로 채택한 때만 그 화 초안 · 변경안을 거둔다. 채택 전에 저장하지 않은 본문 고침이 있으면 따로 묻는다
- 인물 화면의 신체 프로필 · 서술 말투 AI 동작(`bodyAI` · `voiceAI`)도 이 파일에 있다

### `canon/static/restate.js`

- 반영 뒤 고친 화
- 반영이 끝난 화를 고쳤을 때 집필 화면 알림(`restateNote`, 뒤 화 검수 권유)
- 상태 승인 화면의 다시 맞추기 카드(`restateCard`: 요약 · 새 사실 · 새 복선만 고르기, 그대로 두기)
- '다시 뽑기'(`restateEp`)는 바꾼 체크 · 고친 요약이 있으면 먼저 묻는다(`rsEdited`, 요약은 `S.deltaOrig` 와 견줌)
- '다시 뽑기'는 작품을 말없이 저장하지 않는다. 저장하지 않은 변경은 `startJob` 이 묻고 저장한다(`tests/test_restate_js.py`)
- 다시 맞추기 후보(`restateDelta`)는 고친 본문에서 뽑은 변경안만이다. 변경안을 만든 본문(`S.deltaBase`)이 `final_text` 와 같으면 다시 뽑기를 보인다(서버 `_stale_state` 와 같은 규칙)
- 서버는 `pipeline.apply_restate` · `keep_state`
- 보내는 변경안(`restateBody`)은 고른 새 복선의 plant 근거 문장만 담는다 (`pipeline.apply_restate` 와 같은 규칙)
- 고르기 칸(`rsItems`)은 변경안 안에서 같은 복선 id 가 두 번 오면 앞의 것만 보인다
- 서버가 409(`stale_delta`)를 주면 기다림 상자를 닫고 묻는다. 확인하면 `?force=1` 로 다시 보낸다
- 표시는 `Episode.final_text` (`edited_after_final` 과 같은 규칙, `tests/test_restate_js.py`)

### `canon/static/review.js`

- 6단계 상태 승인 · 관계 표시
  - `DELTA_LISTS`
  - `setDelta`
  - `setDelta` 는 설정에 없는 인물이 끼었거나 같은 인물끼리인 관계 사건 · 관계 바뀜을 기본으로 체크하지 않는다(서버 `validate_delta` 와 같은 규칙)
  - `setDelta` 는 설정에 없는 인물이 주인인 비밀도 기본으로 체크하지 않는다
  - 같은 변경안에서 심고 회수한 복선은 아는 복선으로 세어 기본으로 체크하고 심은 복선 설명으로 보인다(`fsKnown`)
  - 그 심는 복선(`p`) 체크를 풀면 같은 화 회수(`x`)도 풀고 다시 고르면 되돌린다(`plantedCascade`)
  - 새 인물(`n`) 체크를 풀면 그 인물을 다룬 `c` · `e` · `r` · `s` · `t` · `h` · `a` 항목도 풀고 몇 개 풀었는지 알린다(`newCharCascade` · `newCharDeps`)
  - 새 인물을 다시 고르면 그 항목을 기본 체크로 되돌린다(다른 빠진 새 인물도 다룬 항목은 빼 둔다)
  - 새 인물 체크를 바꿔도 관계 미리 보기를 다시 계산한다(`app.js` 의 `[ersn]` 키)
  - 체크를 푼 항목은 `pickedDelta` 가 `dismissed` 로 보낸다(등장 인물 붙이기는 빼고)
  - 체크를 푼 설정 바꾸기(`t`) · 호칭(`h`)도 `dismissed` 로 가서 반영 취소 뒤 체크를 푼 채 다시 놓인다
  - 반영 기록에서 돌아온 변경안(반영 취소 · 단편 다시 쓰기)의 `dismissed` 는 `setDelta` 가 목록 끝에 다시 놓고(`reofferDismissed`) 기본 체크를 풀어 둔다(`d.reoffer`, 화면 전용)
  - 체크를 푼 채 다시 놓인 새 인물 · 심는 복선을 가리키는 항목도 `defaultPicks` 가 기본으로 빼 둔다(`over` 로 지금 `n` · `p` 체크를 주면 그 값을 기준으로 맞춘다)
  - 반영이 끝난 화 기록(`historyView`) 아래 접힌 '빼 둔 항목 N개'(`dismissedView`)
  - 빼 둔 사실마다 '확정 사실에 넣기'(`takeDismissedFact`, `POST …/dismissed-facts/{i}`)
  - 이미 있는 확정 사실과 비슷한 새 사실(`d.fact_near`)은 `defaultPicks` 가 기본으로 빼 두고 그 줄에 옛 사실을 적는다
  - 변경안 체크 `S.picks` 는 한 화 것이다(`S.picksEp`, 작품마다 따로 둔다)
  - 다른 화 변경안을 열면 `pickEp` 가 그 화에서 고친 체크(`S.picksKept`)를 되살린다
  - 고친 체크가 없으면 `pickEp` 가 지금 작품 기준 기본 체크(`defaultPicks`)로 다시 센다
  - 반영 취소에 쓸 앞 화 스냅샷이 없으면 버튼 자리에 까닭을 쓴다(`revertGone`)
  - 장편이 지운 스냅샷은 반영 기록으로 다시 만들지 않는다(기능 훅이 스냅샷 밖 데이터도 바꿔 재생이 정확하지 않다)
  - 체크 · 칸을 바꾸면 잠시 뒤 초안을 서버에 남긴다(`saveDeltaDraft`, `PUT /pending/{key}/draft`)
  - pending.json 에 남아 남기지 못한 초안이 없는 변경안은 페이지를 떠날 때 묻지 않는다(`deltaKept`, app.js `hasUnsaved`)
  - pending.json 에 결과가 없는 변경안은 초안을 남기지 않는다
  - 체크가 다른 화의 것이면(`S.picksEp`) 초안에 체크를 보내지 않는다
  - 받은 그대로에서 바꾼 것(요약 · 체크 · 고칠 수 있는 칸)은 `deltaTouched` 로 센다. 다시 만들기와 자동 집필의 그대로 반영이 버리기 전에 묻는 기준이다
  - 머리 버튼 줄의 반영 버튼 · `.savebar-slot`
  - 변경안 메뉴 `rvMenu`(다시 만들기 · 지시서 · 버리기)는 `write.js` `writeMenu` 의 맨 위 '변경안' 갈래로 들어간다. 머리 ⋯ 메뉴는 하나다
  - 반영 `applyDelta`: 본문을 고친 것을 확인창에서 받았으면 `?force=1` 로 보낸다. 서버가 409(`stale_delta`)를 주면 기다림 상자를 닫고 한 번 더 묻는다
  - `reviewPanel` 이 머리 보조 버튼 · 주 버튼 · 칸 위 알림 · 오른쪽 칸 `.rv-panel` · 좁은 폭 반영 바를 돌려준다(`viewReview` 는 `write.js` `viewEpisode(n, 'review')`)
  - 왼쪽 본문은 `viewEpisode` 가 그리는 고치는 본문이고 근거 밑줄 `rvRanges` 를 긋는다(`marks.js` `rvMarked` 가 밑줄 칸을 깐다)
  - 고치는 본문의 근거 밑줄을 누르면 `marks.js` 가 `rvGoItem` 으로 그 항목에 간다. 항목의 '본문 보기'(`rvQuote`)는 넓은 폭에서 본문 칸의 그 문장을 고른다
  - 반영 `applyDelta` 는 저장하지 않은 본문 고침을 먼저 저장하고(`flushText`) 고친 본문이라 한 번 묻는다
  - 오른쪽 직접 정할 것 · 요약 · 그대로 반영할 것(갈래 접기 `S.rvOpen`, 고른 수 `rvKeyCount`) · 관계 계산
  - 관계 사건 종류 고르기는 색(`kindStyle`) 옆에 칩 `kindTag`(＋ 좋은 사건 · － 나쁜 사건, 기호는 `aria-hidden`)을 둔다. 종류를 바꾸면 칩도 맞춘다
  - 경고를 인물 줄에 붙이기 `rvWarnSplit`
  - '[누락 의심]' 경고는 `rvWarnSplit` 이 따로 모아(`audit`) '변경안 누락 의심' 줄에 둔다. 본문을 고칠 일이 아니라 '이 문장 고르기'만 둔다(`warnTools` 의 `pickOnly`)
  - 경고 줄 `rvWarnLine` 의 버튼과 고치는 중 · 'AI가 고침' 표시는 `passage.js` `warnTools`
  - 대상 인물 id(`StateDelta.warn_to`)가 있으면 그 인물 줄, 없으면(AI 경고 · 예전 변경안) 인물 이름으로 시작하는지로 붙인다
  - 인물 칸 그 자리에서 펴기 `rvOpen`
  - 편 인물 칸은 감정 · 목표 · 위치 · 메모 · 차림을 고친다(`STATE_TEXT`). 빈 칸은 지금 값을 그대로 둔다
  - 지금 값이 있는 칸의 '지우기'(`data-dclear`)는 `CharacterState.cleared` 에 칸 이름을 넣어 반영 때 그 칸을 비운다
  - `tests/test_state_clear.py`
  - 본문 근거 `rvQuote` · `rvGoItem`
  - 900px 이하는 변경안 먼저 `rvWide`. 본문 카드는 접어 아래에 둔다(`fold`, `.ep-fold`)
- 줄 안 고르기 · 확정 사실 칸(`.rv-inp`)은 13px, 손가락 기기에서 16px 다(iOS 확대 막기)

### `canon/static/rewrite.js`

- 다시 생성
- 집필 화면의 다시 생성 열(`rwColumn`, 대화 패널 자리 `.tool-col`에 뜨고 대화 패널과 하나만 열림. 빠른 요청, 피드백, 함께 넣을 재료, 처음부터 / 고쳐 쓰기, 살릴 부분)
- 방식 '서술만 다듬기'(`polish`)는 다른 칸을 감추고 정해진 규칙만 보낸다. 버튼은 '다듬은 판 만들기'
- 새 판 비교(나란히 · 바뀐 곳 `textDiff`)와 고르기. 새 판을 쓸 때 뗀 작업 설명이 있으면 그 수를 한 줄로(`TextVersion.meta_cut`, 고르면 화로 따라감)
- 이전 판 목록과 되돌리기
- 서버는 `pipeline.rewrite_episode` · `set_candidate` · `adopt_candidate` · `drop_candidate` · `restore_version`
- 쓰기 작업 끝 알림(`JOB_DONE_MSG.write`)은 쓴 뒤 바로 검수의 짚은 곳 수나 못 한 까닭(`check_error`)을 함께 알린다
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
  - 설정 API 응답은 `setConfigCall` 이 받는다. 마지막으로 보낸 요청(`SET.seq`)의 응답만 `S.config` 에 넣는다
  - 늦게 온 옛 응답을 버렸으면(`SET.stale`) 기다리는 요청이 다 끝난 뒤 `GET /config` 로 한 번 맞춘다
  - 요청이 `config_broken` 으로 막히거나 새로 시작이 실패해도 끝난 뒤 `GET /config` 로 맞춘다. 맨 위 안내와 단추가 서버 상태와 같게 보인다
  - 설정 파일이 깨졌으면(`config_broken`) 본문 맨 위에 `note warn` 안내(`setBrokenHtml`)와 보관본 경로를 보인다
  - 읽지 못한 파일(`config_unreadable`)이면 새로 시작 단추 없이 파일 권한을 확인하라고 안내한다
  - 안내의 '기본값으로 새로 시작'(`setConfigReset`)은 묻고 `POST /config/reset` 을 보낸다. 그 전에는 서버가 저장을 409 로 막는다
  - 대화상자를 닫으면 작품 밖(작품 목록)도 다시 그린다. `setSave` 뒤 키 점검(`/config/health`)이 닫은 뒤에 오면 그때 다시 그린다
  - 저장 띠 없음
  - 키만 줄 안 '키 저장'
  - 글 칸 `textRow`(모델 이름 · 주소 · 경로)는 휴대폰 키보드 자동 대문자 · 고치기를 끈다
  - Gemini 모델 칸은 고른 모델이 `gemini_cache_unsupported` 에 있으면 설명에 '이 모델은 명시 캐시를 받지 않아요'를 붙인다
  - 작품별 단계 값 `projectStage`
  - 이 작품 › 집필 · 검수의 '상태 변경안 누락 검사'(`audit`, `Settings.state_audit`). 단계 목록에도 `audit` 가 있다
  - '프리셋으로 채우기'는 지금 칸이 어느 프리셋과도 다르면(직접 고른 조합) 덮기 전에 묻고, 그만두면 고른 값을 되돌린다
  - 프리셋으로 채운 뒤 그 줄에 '되돌리기'(`setPresetUndo`, `SET.undo`)가 생겨 고르기 전 단계 칸을 다시 저장한다. 단계 칸을 손으로 고치거나 대화상자를 다시 열면 사라진다
  - 단계 줄의 추론 강도 칸 `effortSelect`: Claude · Gemini 단계에만, 목록은 백엔드가 받는 값(`effortOptions`)
  - Claude 로그인 줄 `claude.js` · Vertex 줄 `vertex.js`
  - Claude 구독 계정 줄(`claudeAccountRow`, 같이 · Canon 전용)과 '로그인 시작' · '로그아웃'(`claude.js`, 띄운 뒤 3초마다 상태를 다시 봄)
  - 이 브라우저 › 알림 갈래의 줄은 `notify.js` 의 값을 그리고 고친다(`notifyPref` · `notifyTurnOn` · `notifyTest`)
  - 집필 묶음의 '되풀이한 구절 피하기' 줄(`echoes`, 장편만, `PUT …/recent-echoes`)
  - 이 작품 › 집필 · 검수의 '프롬프트 블록' 묶음: 블록 켜기 · 끄기(`blocks`, `blockRows`)와 블록 예산(`budgets`, `budgetRows`)
  - 프롬프트 블록은 열 때 `GET …/blocks` 로 받아 `SET.blocks` 에 둔다(`loadBlocks`, 장편만)
  - 단편은 프롬프트 블록 묶음에 블록 설정을 쓰지 않는다는 한 줄만 보인다
  - 끌 수 있는 블록은 스위치(`setBlock`), 잠긴 블록은 잠금 칩과 '이 블록은 끌 수 없어요'
  - 다른 설정이 정하는 블록은 그 설정 이름을 적고, 같은 갈래에 그 줄이 있으면 '그 설정 보기'(`setJump`)로 옮긴다(`BLOCK_NOTE`)
  - 예산 줄은 키마다 숫자 칸(100 단위, 서버가 준 범위)과 기본값 · 범위 · 쓰는 블록, '기본값으로'(`setBudgetReset`). 예산 이름은 `BUDGET_LABEL`(집필 화면 대화상자도 쓴다)
  - 저장 `setBlocksSave` 는 기본값과 다른 것만 모아(`blocksBody`) `PUT …/blocks` 로 두 목록을 통째로 보낸다
  - 블록 저장은 줄을 서서 하나씩 보낸다(`blockSaveChain`). 앞 저장이 끝나야 다음 저장이 그때 화면 값(마지막 변경)을 보낸다
  - 서버가 거절하면 그 저장이 바꾼 값만 되돌리고(뒤에 다시 바꾼 값은 둔다) 서버 문구를 줄 아래에 보인다. 기다리는 저장이 없으면 서버 응답으로 맞춘다(`blocksSync`)
  - 캐시 앞부분 블록(`front`)이나 그 블록이 쓰는 예산을 바꾸면 저장 알림에 '다음 요청부터 캐시가 처음부터 다시 쌓여요'를 붙인다
  - 블록 설정을 저장하면 집필 화면이 든 컨텍스트 블록 표를 다시 받는다(`ctxReload`)
  - `ctxReload` 는 들고 있던 프롬프트 원문(`S.promptText`)과 토큰 센 값(`S.ctxCount`)을 버린다. 다음에 열 때 새 요청을 받는다
  - 이 작품 › 백업 갈래(`backup-list`): 백업마다 한 줄(`backupRows` · `backupDesc`), 열 때 `GET …/backups` 로 받고 되돌리기는 `setRestore`(되돌린 뒤 `PER_PROJECT` 초안 · 변경안을 비움)
  - `tests/test_settings_js.py` · `tests/test_model_preset.py`

### `canon/static/setup.js`

- 1단계 설정 도우미
  - 공용 목차 틀 `outline.js` 의 왼쪽 목차 + 오른쪽 카드 한 열 `.setup-secs`
  - 720px 이하는 위에 붙는 목차 버튼 · 걸음 막대(`.outline.steps`)와 아래 버튼 줄 `.setup-foot`
  - 새 작품 마법사 `viewSetupWizard`: 필수 칸 `setupReqs` · 걸음 목차 `wizStepper` · `wizStepState` · 세계 종류 · 시대 칩 `withWorldKind` · `worldRecs`
  - 다 채운 작품은 기획서 `viewSetupDoc`: 구역 `DOC_SECS` · 목차 상태 `docStatus` · 머리 요약 `docSummary` · 관계 점검 `relIssue` · `relWork` · 가 닿을 곳이 섞인 사이 `relDestNote`
  - 인물 · 관계는 한 줄 목록에서 하나만 편다
  - 이야기 뼈대만: 로그라인 · 관계 · 이름 후보
  - 인물 상세는 `cast.js` 인물 카드
  - 상태창 처음 수치는 `statwin.js` 로 가는 링크 `setupStatLink`
  - `tests/test_setup_wizard_js.py`

### `canon/static/style.js`

- 2단계 문체 · 문체 라이브러리
  - 왼쪽 목차 `styleToc` · 목차 줄 `styleTocItems` + 카드 한 열
  - 프로필 카드 `pfCard`: 읽는 모양 `pfRead` 이 기본
  - '고치기'로 그 카드만 `pfEdit`(기억 `S.styleOpen`, 빈 카드 `styleCardEmpty` 는 바로 고치는 칸)
  - 목차 수 `styleCount`
  - 서술 카드 칸은 `NARR_KEYS`(효과음 표기 포함). 목차 수는 채운 칸 / 전체 칸
  - 기준 지표 `baselineItems` 에 효과음 줄(`sfxRate`: 1,000자당 수와 가장 많은 끝 표시) · '소리' 낱말 밀도
  - 기준 지표 `baselineItems` 에 물결표 대사 줄 비율 · 대사 한 줄 길이(값이 없으면 –)
  - '지킬 · 피할 것' 카드의 열 낱말 칸(`heatWordsRead` · `heatWordsEdit`, `Settings.heat_words` 에 묶음): 작품 화면에만 있고 라이브러리 문체에는 없음
  - 빈 문체는 세 갈래 `stylePickCard` · `styleManual`
  - 프로필 카드 뒤에 작품 정착 문체 카드(`static/anchor.js` 의 `anchorCard`)
  - 라이브러리 항목도 같은 카드
  - 목차 틀은 공용 `outline.js`(`styleToc`)
  - `tests/test_style_js.py`
- 문체 라이브러리 분석도 작업(`lib_style`, project `.styles`, `POST /api/styles/analyze/job` 의 `lib`)이다. 결과(`profile`, `lib`)는 그 항목 화면 맨 위 제안 카드(`libDraftCard`, `S.libDraft`)로 오고 새 항목은 저장하면 그 id 로 옮긴다. 이 탭이 열려 있는 동안 남는다
- '문체 분석'(`analyzeStyle`)은 화면을 막지 않는 작업 `style` 을 시작한다. 버튼은 `jobBtn` 으로 진행을 보이고, 결과는 문체 화면 맨 위 제안 카드(`styleDraftCard`, `S.styleDraft`)로 온다. '이 결과로 바꾸기'(`styleDraftApply`)를 눌러야 작품 문체 · 기준 지표에 들어가고 라이브러리 연결을 끊는다. 문체 라이브러리의 분석은 작품 밖이라 아직 가림막(run)이다

### `canon/static/stylechat.js`

- 문체 화면의 대화로 다듬기(대화 주제 `style`: 칸별 변경안과 지금 값 비교, 시험 문단, 고른 칸 적용 · 적용 취소, 라이브러리 새 버전)와 '이 문체로 쓴 예시' 카드
- 서버는 `pipeline.revise_style` · `apply_style_chat` · `undo_style_chat` · `style_example`
- 칸 이름은 `prompts.STYLE_KEY_LABELS` 와 같다(`tests/test_labels_js.py`)

### `canon/static/write.js`

- 4단계 집필
  - 한 화 화면 `viewEpisode(n, panel)`: 집필 · 검수 · 상태 승인 세 주소가 같은 머리 · 단계 띠 · 본문 칸을 그린다(`viewWrite` · `viewCheck` · `viewReview` 는 감싼 이름)
  - 집필 칸은 오른쪽 칸 없이 본문 칸 하나
  - 검수 · 상태 승인 칸은 `check.js` `checkPanel` · `review.js` `reviewPanel` 의 오른쪽 칸을 `episodeCols` 가 본문 옆에 둔다(`.ep-cols`: 넓은 폭은 왼쪽 본문 · 오른쪽 칸, 좁은 폭은 칸 먼저)
  - 칸을 열면 머리 주 버튼은 그 칸의 것이다. 본문이 없는 화는 칸을 열지 않고 집필처럼 그린 뒤 먼저 쓰라고 알린다
  - 640px 이하는 칸의 보조 버튼을 머리 줄 대신 칸 위 한 줄(`.ep-tools`)에 둔다. 폭이 640px 를 넘나들면 다시 그린다
  - 머리 `.w-stick` 에 붙는 본문 띠와 이번 화 플롯 띠 `plotStrip`(사건 진행 줄: 쓴 사건 체크 `doneEvents` → `Episode.events_done`, 막는 조건 `eventsLock`, 엔딩 훅 도착점) · 펼침 기억 `plotOpenOf`
  - 작가 연출 지시 칸 `dirCard`(집필 칸만): 지금 걸린 아크 지시 · 화 지시를 늘 보이고 '고치기'로 두 칸을 열어 바로 저장한다(`dirSave` → `PUT …/direction`, 막는 조건은 `eventsLock` 과 같다)
  - 머리 높이 `syncWriteTop`
  - 머리 줄에 지금 본문을 쓴 모델(`.w-model`, `writerLabel`). 기록이 없는 화는 보이지 않는다
  - 경고의 'AI에게 고치기'가 그 화를 고치는 동안 본문 칸 위에 잠금 안내(`role="status"`)를 둔다
  - 머리 ⋯ 메뉴 `writeMenu`: 생성 방식 · 컨텍스트 대화상자 · 채팅 앱 작업지시서 .md 내려받기(`briefDownload`) · 화 지우기
  - 프롬프트 원문 보기(`togglePrompt` · `loadPrompt`)는 그 화에 보낸 프롬프트 기록이 있으면 보낸 그대로를 먼저 보인다(`web.prompt` 의 `source=auto`)
  - 원문 위 설명 줄 `promptSource`: 보낸 시각(`fmtDateTime`) · 서버 `note`, 두 갈래를 오가는 버튼 `switchPrompt`('지금 데이터로 다시 만든 것 보기' · '보낸 그대로 보기')
  - 기록이 없는 화는 다시 만든 것만 보이고 설명 줄이 그렇다고 밝힌다. 갈래와 설명은 `S.promptInfo` 에 둔다
  - 컨텍스트 블록 표 `ctxList`: `GET …/context` 의 블록마다 이름 · 글자 · 추정 토큰 · 예산(장편) · 상태 칩 한 줄(`.ctx-tbl`)
  - 블록 상태 `ctxState`: 넣음 · 작가가 끔(`on` 거짓) · 비어 있음(글자 0) · 잠금
  - 컨텍스트 대화상자(`#w-ctx`, `ctxDialogHtml`)는 `ctxList(true)` 로 줄마다 펼친다(`ctxMore`: 상태 까닭 · 예산 · 넣은 항목과 이유 · 뺀 항목과 이유 · 블록 원문)
  - 다른 설정이 정하는 블록(`note`)은 펼친 곳에 그 설정 이름을 적는다(`CTX_NOTE`: 쓰기 재료 · 되풀이한 구절 피하기 · 큐 시트)
  - 펼친 블록은 `S.ctxBlkOpen` 에 남아 대화상자를 다시 채워도 열려 있다
  - 쓰기 시작 칸 · 만든 스토리보드 칸의 펼치는 곳(`details[data-ctx-toggle]`)은 `ctxList()` 요약 줄만 보인다
  - 합계 줄 `ctxTotal`: 'N개 블록 · 합계 X자 · 약 Y토큰(추정)'. 넣은 블록만 세고, `tokens` 가 없는 옛 응답이면 토큰을 빼고 보인다
  - 대화상자의 '실제 토큰 세기'(`ctxCount` → `POST …/count-tokens`)는 결과를 `ctxCountHtml` 줄에 보인다. 셀 수 없는 백엔드는 서버 문구를 그대로 보인다
  - 토큰을 센 결과는 같은 작품 · 화 · 합계 줄일 때만 보인다. 블록 설정을 바꾸면 다시 센다
  - 대화상자의 '블록 설정 바꾸기'(`ctxSettings`, 장편만)는 대화상자를 닫고 설정의 집필 · 검수 갈래를 프롬프트 블록 줄에서 연다
  - 생성 방식 바꾸기(`setMode`)는 localStorage 에 못 적어도 이번 화면에서는 바꾼다
  - 640px 이하 머리(`.w-head`)는 ⋯ 메뉴와 primary 만 남긴다(app.css)
  - 머리와 단계 띠는 `.w-headwrap` 으로 묶는다
  - 640px 이하에서 `.w-headwrap` 은 한 줄이다: 화 앞뒤 버튼 · 단계 띠 · ⋯ · primary. 제목과 칩 묶음(`.w-tl`)은 낭독에만 남긴다
  - 640px 이하 집필 화면의 화 제목은 위쪽 띠 작품 칸이 보인다(`workCard` 의 `.work-ep`)
  - AI 작업이 도는 동안(primary 자리에 진행 줄 `.w-busy`)은 ⋯ 와 진행 줄이 다음 줄을 통째로 쓴다(`.w-headwrap:has(.w-busy)`)
  - `.w-headwrap` · `.w-tl` 은 넓은 폭에서 `display: contents` 라 머리 · 단계 띠 모양이 그대로다
  - 640px 이하에서 본문 위 여백(페이지 위 · 머리 묶음 아래 · 원고 위)을 줄인다(app.css)
  - 640px 이하에서 본문 띠(`.w-bar`)는 `display: contents` 라 글자 수 · 도구 버튼 · 저장 칸이 접힌 플롯 줄과 한 줄(`.w-top`)에 선다
  - 640px 이하에서 접힌 플롯 줄 이름은 `플롯`(`.lbl-s`)이다
  - 640px 이하에서 붙는 줄 도구는 아이콘(`.lbl-i`: 문체 `Aa` · 고칠 곳 `TOFIX_ICON` · 수정 기록 `EDITS_ICON` · 복사 `COPY_ICON`)만 보이는 면 없는 버튼이다(app.css)
  - 640px 이하에서 복사 ▾ 메뉴는 숨기고 같은 내용(`copyMenu`)을 머리 ⋯ 메뉴 맨 위(`writeMenu` 의 `copy`)에 둔다
  - 640px 이하에서 대화 · 다시 생성 버튼은 ⋯ 메뉴 맨 위(`.w-narrow`)로 옮긴다
  - 640px 이하에서 머리의 위치 줄과 쓴 모델은 숨긴다
  - 640px 이하에서 단계 띠는 한 줄 칸이다
  - 640px 이하에서 안내만 하는 반영 끝난 화 알림은 첫 문장을 요약으로 둔 접은 칸(`finNote`, `.w-fin-s`)이다
  - 640px 이하에서 Esc 로 대화를 닫아 포커스가 비면 ⋯ 메뉴 버튼으로 돌린다(머리 줄의 대화 버튼이 숨어 있어서)
  - 반영이 끝난 화의 머리 primary `nextStepBtn` 은 지금 보는 화면으로 가는 일이면 두지 않는다
  - 동작이 있는 다음 할 일(완결 원고 내보내기)은 `nextStepBtn` 이 늘 둔다
  - 본문 없는 화는 AI로 쓰기가 기본이고 머리 primary(`writeGo`, 스토리보드를 만든 화는 `boardGo`, 작업이 돌면 진행 줄 `wsBusy`)와 그 아래 쓰기 시작 칸(`writeStart`: 스토리보드 고르기 `S.wsBoard` · 직접 쓰기 · 컨텍스트)
  - 직접 쓰기(`startManual`)로 빈 칸을 연 화는 본문 칸 위 `manualNote` 의 'AI로 쓰기로 돌아가기'(`backToStart`)로 쓰기 시작 칸에 돌아간다. 쓴 글이 있으면 묻고 임시 보관 초안도 지운다. 그 화에 AI 작업이 돌면 끈다
  - 멈춘 작업이 그 화에서 AI 응답을 기다리면 `writeGo` 가 primary 를 잠그고 쓰기 시작 칸과 만든 스토리보드 칸이 `epWaitNote` 로 까닭을 보인다
  - 본문 띠의 저장 칸 `.savebar-slot`
  - 쓰기가 본문 앞뒤에서 뗀 작업 설명(`Episode.meta_cut`)은 접은 알림 `metaCutNote`: 문단마다 '본문에 되살리기'(`metaCutRestore`, 수정 기록에 남음) · '지우기'(`metaCutDrop`, 되살릴 수 없다고 위험 확인을 묻는다). 자동 집필 중이거나 고칠 수 없는 화는 버튼 없이 보기만(`tests/test_meta_cut.py`)
- 그 화 플롯이 없으면 `noEpisode(n)` 이 몇 화까지 있는지와 마지막 화 · 플롯 만들기로 가는 길을 보인다. 플롯이 하나도 없을 때만 '아직 화별 플롯이 없어요'
- k화로 가는 링크 `epGo(k)`: 플롯 초안이면 플롯 페이지(플롯 확정), 본문이 있으면 검수 · 상태 승인, 나머지는 집필. 순서 안내(`orderNote`)와 검수 · 상태 승인의 빈 화면이 쓴다
- 본문 다시 생성 확인은 지금 본문이 이전 판으로 남는다고 말하고 위험 버튼으로 두지 않는다
- 저장 띠의 '고친 것 버리기'(`dropText`)는 묻고 나서 그 화의 저장하지 않은 본문과 임시 보관 초안을 지운다
- 본문 저장(`saveText`)은 고침을 시작한 저장 본문(`textBase`)을 함께 보낸다. 다른 탭 · 기기가 먼저 저장했으면(409 `stale_text`) `textConflict` 가 묻는다
- 본문 칸은 `data-keep` 칸이라 저장 · 알림으로 다시 그려도 Ctrl+Z 가 듣는다. 서버가 본문을 바꿨거나 밑줄 층(`.hl-wrap`)이 생기거나 사라지면 새 칸이 되어 기록이 사라진다
- `textConflict` 의 '다시 불러오기'는 작품을 다시 받고 칸의 글은 둔다. '내 글로 덮어쓰기'는 `force` 로 다시 보낸다
- 작업지시서(본문 · 검수 · 상태 승인 걸음, `viewBrief`)
- 작업지시서는 화 머리와 공용 목차 틀이다(걸음 목차 `briefToc`: 끝남 ✓ · 지금 · 본문 뒤, 4번째는 상태 승인 화면으로 가는 줄)
- 작업지시서 머리 주 버튼은 그 걸음의 가져오기(n화 본문으로 저장 · 가져오고 검수로 · 확인하고 변경안 검토로)
- 작업지시서 글은 240px 로 접어 보이고 '전체 펼치기'로 편다(`briefFold`)
- 붙여 넣은 JSON 은 화면에서 먼저 읽어 본다(`briefJsonState`, 서버가 다시 확인)
- 본문이 없는 화의 검수 · 상태 승인 걸음은 빈 화면이다

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
