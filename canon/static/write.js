/* 4단계 집필 화면과 작업지시서(API 없이). app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 4. 집필 -----

function epNav(page, n) {
  const nums = P().episodes.map((e) => e.plot.number);
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const arrow = (to, label, d) => to ? `<a class="btn icon-btn" href="${base()}/${page}/${to}" aria-label="${label}"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="${d}"></path></svg></a>` : '<span class="btn icon-btn" aria-hidden="true" style="visibility:hidden"></span>';  // 첫 화 · 끝 화는 자리만 남긴다
  return `<nav class="row" aria-label="회차 이동" style="gap:4px">${arrow(prev, '이전 화', 'M10 3 5 8l5 5')}${arrow(next, '다음 화', 'm6 3 5 5-5 5')}</nav>`;
}

function noEpisode() {
  return `<div class="card empty"><p>아직 화별 플롯이 없어요.</p><a class="btn primary" href="${base()}/arc">${stepLabel('arc')} 만들기</a></div>`;
}

/** n화보다 앞인데 상태 반영이 끝나지 않은 화. 있으면 n화 본문을 저장하거나 반영할 수 없다 (서버 pipeline.require_previous). */
const blockedBefore = (n) => P().episodes.filter((x) => x.plot.number < n && x.status !== 'finalized').map((x) => x.plot.number);

function orderNote(blocked) {
  if (!blocked.length) return '';
  const first = ep(blocked[0]);
  return `<div class="note warn">이전 화(${rangeText(blocked)}화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요. <a href="${base()}/${first.status === 'written' ? 'review' : 'write'}/${blocked[0]}">${blocked[0]}화 ${first.status === 'written' ? '상태 승인으로' : '집필로'}</a></div>`;
}

/** 반영이 끝난 화의 머리 primary: 다음 할 일 (nextStep). 지금 보는 화면으로 가는 일이면 두지 않는다 */
function nextStepBtn() {
  const [label, href] = nextStep();
  return href === `${base()}/${S.route.slice(2).map(enc).join('/')}` ? '' : `<a class="btn primary" href="${href}">${esc(label)}</a>`;
}

function viewWrite(n) {
  const e = ep(n);
  if (!e) return header('4단계', '집필', '') + noEpisode();
  const act = actOf(n);
  const blocked = blockedBefore(n);
  const editable = editableEp(e);  // 반영이 끝난 화도 고친다 (restate.js 가 반영 뒤 고침을 알린다)
  // 고칠 수 없는 화(플롯 초안)는 저장된 본문을 보인다. 그 화에 남은 초안이 있으면 따로 꺼내 보인다
  const draft = editable ? S.textDraft[n] : undefined;
  const orphan = !editable && textUnsaved(n);
  const text = draft ?? e.text;
  const isApi = S.mode === 'api';
  const writing = !!jobFor('write', n);
  const locked = writing && !e.text;  // AI가 본문을 처음 쓰는 중: 끝나면 칸이 AI 본문으로 바뀌므로 그동안 쓴 글은 남지 않는다

  let center;
  if (e.status === 'draft') {
    center = `<div class="empty"><p>${n}화 플롯이 아직 초안이에요. 확정해야 쓸 수 있어요.</p><a class="btn primary" href="${base()}/arc" data-action="gotoPlot" data-arg="${n}">${n}화 플롯 확정하러 가기</a></div>`;
  } else if (!e.text && draft === undefined) {
    center = `<div class="empty">
      ${autoLockNote() || orderNote(blocked)}
      ${isApi ? `<p>확정된 플롯과 지금까지의 데이터로 ${n}화를 써요.</p>${((b) => `<button class="btn primary" data-action="writeEp" data-arg="${n}"${blocked.length || autoOn() ? ' disabled' : b.attr}>${b.label}</button>`)(jobBtn('write', n, `${n}화 본문 생성`))}${jobFor('write', n) ? '<div class="small">다른 화면으로 옮겨 가도 계속 써요. 끝나면 알려 드려요.</div>' : ''}`
        : `<p>작업지시서를 채팅 앱에 붙여 넣고, 받은 본문을 가져오세요.</p><a class="btn primary" href="${base()}/brief/${n}">작업지시서 열기</a>`}
      <button class="btn" data-action="startManual" data-arg="${n}"${writing || blocked.length || autoOn() ? ' disabled' : ''}>직접 쓰기</button>
    </div>`;
  } else {
    center = `<div class="prose">${editable
      ? (locked ? `<div class="note info" id="draft-lock" style="margin:12px 16px 0">${n}화 본문을 만드는 중이에요. 끝나면 이 칸이 AI 본문으로 바뀌니 그때 고치세요.</div>` : '') + draftBox(n, text)
      : `<div class="read" data-read="${n}">${readHtml(n, text)}</div>`}</div>`;
  }

  const ctx = S.context ? `<details data-ctx-toggle${S.ctxOpen ? ' open' : ''}><summary>${S.context.length}개 블록 · 합계 ${S.context.reduce((s, c) => s + c.chars, 0).toLocaleString()}자</summary><ol class="panel-list">${S.context.map((c) => `<li><span>${esc(c.title)}</span><span class="small">${c.chars.toLocaleString()}자</span></li>`).join('')}</ol></details>
      <div class="small">이전 본문 전체 대신 이 데이터만 매번 같은 순서로 넣어요.</div>` : '<div class="small">플롯을 확정하면 보여요.</div>';

  // 생성 방식 토글은 설정의 본문 단계 백엔드 이름을 보인다 (설정을 아직 받지 않았으면 이름 없이)
  const wst = ((S.config || {}).stages || {}).write;
  const wname = wst ? ({ gemini: 'Gemini', local: '로컬', mock: 'mock' }[wst.provider] || wst.provider) : '';
  // 쓴 화를 아직 검수하지 않았으면 '검수하기'가 지금 할 일이다. 검수한 뒤에는 '상태 승인으로'를 primary 로 올린다
  const headCheck = e.status === 'written' && !e.checked_at && !autoOn();
  const right = `${e.status !== 'finalized' ? `<div class="seg" role="group" aria-label="생성 방식"><button type="button" aria-pressed="${isApi}" data-action="setMode" data-arg="api" title="${wst ? `본문 모델 ${esc(wst.model || '')} · 설정에서 바꿔요` : '설정에서 바꿔요'}">AI로 쓰기${wname ? ` · ${esc(wname)}` : ''}</button><button type="button" aria-pressed="${!isApi}" data-action="setMode" data-arg="brief">채팅 앱 작업지시서</button></div>` : ''}
    ${e.text && editable ? chatButton(`text:${n}`) : ''}
    ${e.text && editable && (isApi || e.status === 'finalized') ? `${((b) => `<button class="btn${S.rwOpen === n ? ' on' : ''}" data-action="rwOpen" data-arg="${n}" aria-expanded="${S.rwOpen === n}"${b.attr}>${b.label}</button>`)(jobBtn('write', n, '다시 생성'))}` : ''}
    ${editable && !isApi && e.status !== 'finalized' ? `<a class="btn" href="${base()}/brief/${n}">작업지시서</a>` : ''}
    ${headCheck ? ((b) => `<button class="btn primary" data-action="checkEp" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('check', n, '검수하기')) : ''}
    ${e.status === 'written' ? `<a class="btn${headCheck ? '' : ' primary'}" href="${base()}/review/${n}">상태 승인으로</a>` : ''}
    ${e.status === 'finalized' ? nextStepBtn() : ''}`;

  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('write', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${act ? act.name + ' 구간 · ' : ''}${n} / ${P().meta.target_episodes}화</div><h1 style="font-size:1.5rem">${n}화 ${esc(e.plot.title)}</h1></div>${povBadge(n)}<span class="chip ${e.status}">${STATUS[e.status]}</span>${e.auto ? '<span class="chip ai">자동 반영</span>' : ''}</div><div class="row">${right}</div></header>
    ${e.auto ? `<div class="note info">이 화는 자동 집필이 검토 없이 반영했어요. 읽어 보고 문제가 있으면 <a href="${base()}/auto">자동 집필</a>에서 이 화부터 되돌릴 수 있어요.</div>` : ''}
    ${rebuildNote(n)}
    ${e.text ? restateNote(n) : ''}
    ${orphan ? `<div class="note warn">저장하지 않은 ${n}화 초고가 남아 있어요. 이 화는 상태 반영이 끝나 본문으로 저장할 수 없어서, 아래에는 반영된 본문을 보여요.
      <details><summary>남은 초고 보기 (${S.textDraft[n].length.toLocaleString()}자)</summary><textarea readonly id="orphan-${n}" aria-label="${n}화 남은 초고" style="width:100%;min-height:160px;margin-top:6px">${esc(S.textDraft[n])}</textarea></details>
      <div class="row" style="margin-top:6px"><button class="btn small" data-action="copyOrphan" data-arg="${n}">초고 복사</button><button class="btn small danger" data-action="dropOrphan" data-arg="${n}">초고 버리기</button></div></div>` : ''}
    ${editable && autoOn() ? `<div class="note warn">자동 집필이 도는 동안은 본문을 저장할 수 없어요. 쓰던 글은 이 화면에 남아 있어요. 저장하려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : ''}
    ${e.text && editable ? rewritePanel(n) + candidateCard(n) : ''}
    <div class="cols write-cols" style="gap:16px">
      <aside class="card tight w-plot" style="flex:1 1 260px;min-width:0" aria-label="이번 화 플롯">
        <h3>이번 화 플롯</h3>
        ${act ? `<div class="note info"><strong>구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
        <p style="font-size:0.8125rem;line-height:1.6;color:var(--text-2)">${esc(e.plot.summary)}</p>
        <div class="field"><span class="small">사건</span><ol style="padding-left:20px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${e.plot.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></div>
        <div class="field"><span class="small">등장 인물</span><div style="font-size:0.8125rem">${e.plot.characters.map(charName).map(esc).join(', ')}</div></div>
        ${povText(n) ? `<div class="field"><span class="small">서술 시점</span><div style="font-size:0.8125rem">${esc(povText(n))}${povText(n) !== povText(n - 1) && n > 1 ? ' <span class="chip ai">시점 바뀜</span>' : ''}</div></div>` : ''}
        ${tlAside(n)}
        <div class="field"><span class="small">감정 변화</span><div style="font-size:0.8125rem">${esc(e.plot.emotional_shift)}</div></div>
        ${e.plot.opening ? `<div class="field"><span class="small">여는 장면</span><div style="font-size:0.8125rem">${esc(e.plot.opening)}</div></div>` : ''}
        <div class="field"><span class="small">엔딩 훅</span><div style="font-size:0.8125rem">${esc(e.plot.ending_hook)}</div></div>
        ${e.plot.reader_question ? `<div class="field"><span class="small">독자가 들고 갈 질문</span><div style="font-size:0.8125rem">${esc(e.plot.reader_question)}</div></div>` : ''}
        ${e.summary ? `<div class="field"><span class="small">승인된 요약</span><div style="font-size:0.8125rem;line-height:1.6">${esc(e.summary)}</div></div>` : ''}
        ${issuesBlock(e)}
        ${warnBlock(e)}
        ${e.text && !autoOn() && !headCheck ? ((b) => `<button class="btn small" data-action="checkEp" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('check', n, e.checked_at ? '다시 검수' : '검수하기')) : ''}
        ${deviceBadges(n)}
        <a href="${base()}/arc" data-action="gotoPlot" data-arg="${n}" style="font-size:0.8125rem">플롯 보기</a>
      </aside>
      <section class="card w-body" style="flex:3 1 520px;min-width:0;padding:0;gap:0" aria-label="본문">
        <div class="between" style="padding:10px 16px;border-bottom:1px solid var(--line);font-size:0.75rem;color:var(--muted)">
          <span>${e.status === 'draft' ? '플롯을 확정하면 본문을 쓸 수 있어요' : e.text ? '고칠 부분을 드래그하면 직접 고치거나 AI에게 맡기거나 삽화 프롬프트를 만들 수 있어요' : '본문을 직접 고친 뒤 저장할 수 있어요'}</span>
          ${e.status === 'draft' ? '' : `<span class="row">${(e.edits || []).length ? `<button type="button" class="btn small" data-action="openEdits" title="수정 기록을 펼쳐요">수정 기록 ${e.edits.length}</button>` : ''}<span><strong id="char-count" style="color:var(--text)">${(text || '').length.toLocaleString()}</strong> / ${Number(P().meta.words_per_episode).toLocaleString()}자</span>
          ${text ? `<button class="btn small" data-action="copyEp" data-arg="${n}" title="고른 줄바꿈 형식으로 복사 (오른쪽 '복사 · 내보내기'에서 바꿈)">복사</button>` : ''}
          ${editable && (e.text || draft !== undefined) ? `<button class="btn small${textUnsaved(n) && !autoOn() ? ' primary' : ''}" id="save-text" data-action="saveText" data-arg="${n}"${draft === undefined || autoOn() ? ` disabled title="${autoOn() ? '자동 집필이 도는 동안은 저장할 수 없어요' : '고친 내용이 없어요'}"` : ''}>본문 저장</button>` : ''}</span>`}
        </div>
        ${e.text ? passageNotes(n) ? `<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:8px">${passageNotes(n)}</div>` : '' : ''}
        ${center}
      </section>
      <aside class="card tight w-side" style="flex:1 1 260px;min-width:0" aria-label="복사 · 내보내기와 AI에게 보내는 컨텍스트">
        ${exportCard(n)}
        <h3>AI에게 보내는 컨텍스트</h3>
        ${ctx}
        ${S.context ? `<button class="btn small" data-action="togglePrompt" data-arg="${n}">${S.promptText ? '프롬프트 닫기' : '프롬프트 원문 보기'}</button>` : ''}
        ${S.promptText ? `<pre class="brief mono" style="max-height:420px">${esc(S.promptText)}</pre>` : ''}
      </aside>
    </div>
    ${editHistory(e)}
    ${versionsPanel(e)}
    ${e.text ? illustPanel(n) : ''}
    ${openingPanel(n)}
    ${e.text && editable ? chatPanel(`text:${n}`) : ''}`;
}

// ----- 6. 작업지시서 -----

// 화마다 고른 지시서 탭 ('작품:화' → 'episode' | 'state'). 고른 적 없는 화는 상태로 정한다: 본문이 있으면 상태 승인 지시서
const BRIEF_TABS = {};
const briefTabFor = (n) => BRIEF_TABS[`${S.name}:${n}`] || (ep(n).status === 'written' ? 'state' : 'episode');
let briefImportError = null;  // 받은 JSON 가져오기에서 서버가 거절한 이유 { key: '작품:화', msg }

/** 붙여 넣은 본문 글자 수와 목표 분량. 목표의 70%보다 짧으면 채팅 앱 답이 잘렸는지 보라고 한다. */
function importCount(v) {
  const len = v.trim().length;
  const goal = Number(P().meta.words_per_episode) || 0;
  const short = len && goal && len < goal * 0.7;
  return `<strong>${len.toLocaleString()}</strong> / ${goal.toLocaleString()}자${short ? ' <span class="chip written">목표보다 많이 짧아요. 본문이 잘렸는지 확인하세요</span>' : ''}`;
}

function viewBrief(n) {
  const e = ep(n);
  if (!e) return header('작품 도구', '채팅 앱 작업지시서', '') + noEpisode();
  const body = S.briefTab === 'episode';
  const stateBlocked = !body && !e.text;
  // 앞 화 반영이 끝나지 않았으면 받은 본문 저장(처음 쓰는 화)과 변경안 반영을 서버가 막는다. 붙여 넣은 글은 칸에 남는다
  const order = (body ? e.status === 'confirmed' : e.status === 'written') ? blockedBefore(n) : [];
  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('brief', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)} · API 없이 쓰기</div><h1 style="font-size:1.5rem">채팅 앱 작업지시서</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div></header>
    <p class="desc">Claude, Gemini, ChatGPT 구독 앱에 붙여 넣을 지시서예요. API 생성과 똑같은 컨텍스트를 써요.</p>
    <div class="tabs" role="tablist" aria-label="지시서 종류">
      <button type="button" role="tab" aria-selected="${body}" aria-controls="brief-panel" data-action="setBriefTab" data-arg="episode">1 본문 작성 지시서</button>
      <button type="button" role="tab" aria-selected="${!body}" aria-controls="brief-panel" data-action="setBriefTab" data-arg="state">2 상태 승인 지시서</button>
    </div>
    <div class="cols" role="tabpanel" id="brief-panel" aria-label="${body ? '1 본문 작성 지시서' : '2 상태 승인 지시서'}">
      <section class="card" style="flex:1.3 1 480px;min-width:0">
        <div class="between"><h2><span class="small" style="font-weight:400">① </span>복사해서 채팅 앱에 붙여 넣기</h2>
          <div class="row"><button class="btn small" data-action="downloadBrief" data-arg="${n}"${stateBlocked ? ' disabled' : ''}>.md 내려받기</button><button class="btn small dark" data-action="copyBrief"${stateBlocked ? ' disabled' : ''}>복사</button></div></div>
        ${e.status === 'draft' && body ? '<div class="note warn">플롯이 아직 초안이에요. 확정 전 내용으로 지시서가 만들어져요.</div>' : ''}
        ${stateBlocked
          ? `<div class="note plain">${n}화 본문이 아직 없어 상태 승인 지시서를 만들 수 없어요. 본문을 먼저 저장하세요. <button class="btn small" data-action="setBriefTab" data-arg="episode">본문 작성 지시서로</button></div>`
          : `<pre class="brief mono">${esc(S.briefText ?? '불러오는 중…')}</pre>
        ${S.briefText ? `<div class="small">${S.briefText.length.toLocaleString()}자</div>` : ''}`}
      </section>
      <section class="card" style="flex:1 1 380px;min-width:0">
        ${body ? `<h2><span class="small" style="font-weight:400">② </span>받은 본문 가져오기</h2>
          <label for="imp-body" class="small">채팅 앱이 쓴 본문을 그대로 붙여 넣으세요.</label>
          <textarea id="imp-body" rows="12" data-brief="${n}:episode" style="font-family:var(--serif);line-height:1.8"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}>${esc(S.briefDraft[`${S.name}:${n}:episode`] || '')}</textarea>
          <div class="small" id="imp-count">${importCount(S.briefDraft[`${S.name}:${n}:episode`] || '')}</div>
          ${e.status === 'draft' ? '<div class="small">플롯을 확정해야 본문을 저장할 수 있어요.</div>' : ''}${e.status === 'finalized' ? '<div class="small">이미 끝난 화예요.</div>' : ''}
          ${orderNote(order)}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importText" data-arg="${n}"${e.status === 'draft' || e.status === 'finalized' || order.length ? ' disabled' : ''}>${n}화 본문으로 저장</button></div>`
        : `<h2><span class="small" style="font-weight:400">② </span>받은 JSON 가져오기</h2>
          <label for="imp-json" class="small">채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지워요.</label>
          <textarea id="imp-json" rows="12" data-brief="${n}:state" class="mono"${e.status !== 'written' ? ' disabled' : ''}>${esc(S.briefDraft[`${S.name}:${n}:state`] || '')}</textarea>
          ${e.status !== 'written' ? '<div class="small">본문이 작성된 화에서만 쓸 수 있어요.</div>' : ''}
          ${briefImportError && briefImportError.key === `${S.name}:${n}` ? `<div class="note err" role="alert">${esc(briefImportError.msg)}</div>` : ''}
          ${orderNote(order)}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importJson" data-arg="${n}"${e.status !== 'written' || order.length ? ' disabled' : ''}>확인하고 변경안 검토로</button></div>`}
        <div style="padding-top:12px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:8px">
          <strong style="font-size:0.8125rem">순서</strong>
          <ol style="padding-left:20px;display:flex;flex-direction:column;gap:4px;font-size:0.8125rem;line-height:1.55;color:var(--text-2)">
            <li>본문 작성 지시서 → 받은 본문 저장</li><li>상태 승인 지시서 → 받은 JSON 가져오기</li><li>상태 승인 화면에서 반영</li></ol>
        </div>
      </section>
    </div>`;
}


Object.assign(actions, {
  // 집필
  setMode(m) {
    S.mode = m;
    localStorage.setItem('canon.mode', m);
    render();
  },
  async writeEp(n) {
    if (ep(n).text && !confirm(`${n}화 본문을 새로 생성할까요? 지금 본문은 사라져요.`)) return;
    await startJob('write', n);
  },
  async saveText(n) {
    await run('본문 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] ?? ep(n).text });
      delete S.textDraft[n];  // 만들어 둔 상태 변경안은 남기고, 본문이 바뀌었다고 알린다 (passageNotes)
      toast('본문을 저장했어요');
    });
  },
  startManual(n) {
    S.textDraft[n] = '';
    render();
  },
  gotoPlot(n) {
    S.selEp = Number(n);
    location.hash = `${base()}/arc`;
  },
  async togglePrompt(n) {
    if (S.promptText) {
      S.promptText = null;
      return render();
    }
    await run('불러오는 중', async () => {
      const r = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/prompt`);
      S.promptText = `[시스템]\n${r.system}\n\n[프롬프트]\n${r.prompt}`;
    });
  },

  // 작업지시서
  openStateBrief(n) {
    BRIEF_TABS[`${S.name}:${n}`] = 'state';
    location.hash = `${base()}/brief/${n}`;
  },
  setBriefTab(t) {
    BRIEF_TABS[`${S.name}:${S.route[3]}`] = t;
    S.briefTab = t;
    S.briefText = null;
    briefImportError = null;
    render();
  },
  async copyBrief() {
    try {
      await navigator.clipboard.writeText(S.briefText || '');
      toast('복사했어요. 채팅 앱에 붙여 넣으세요.');
    } catch {
      toast('복사하지 못했어요. 내용을 직접 선택해 복사하세요.', true);
    }
  },
  downloadBrief(n) {
    const blob = new Blob([S.briefText || ''], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${S.name}-${String(n).padStart(2, '0')}-${S.briefTab}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  async importText(n) {
    const text = $('#imp-body').value.trim();
    if (!text) return toast('본문을 붙여 넣으세요', true);
    if (ep(n).text && !confirm(`${n}화의 지금 본문을 바꿀까요?`)) return;
    await run('가져오는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text });
      delete S.textDraft[n];
      delete S.deltas[n];
      delete S.briefDraft[`${S.name}:${n}:episode`];
      toast(`${n}화 본문으로 저장했어요`);
      location.hash = `${base()}/write/${n}`;
    });
  },
  async importJson(n) {
    const raw = $('#imp-json').value;
    if (!raw.trim()) return toast('JSON을 붙여 넣으세요', true);
    if (S.deltas[n] && !confirm(`${n}화에 검토 중인 변경안이 있어요. 골라 둔 체크와 함께 가져온 JSON으로 바꿀까요?`)) return;
    await run('확인하는 중', async () => {
      let d;
      try {
        d = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/state/parse`, { raw });
      } catch (e) {
        if (e.status !== 400) throw e;
        briefImportError = { key: `${S.name}:${n}`, msg: e.message };  // 토스트는 사라지니 ② 칸 아래에 남긴다
        return;
      }
      briefImportError = null;
      setDelta(n, d, 'chat');
      delete S.briefDraft[`${S.name}:${n}:state`];
      location.hash = `${base()}/review/${n}`;
    });
  },
});
