/* 5단계 검수: 한 화의 검수 세션. 회차 띠 · 처리 상태 거르기, 왼쪽 지적 목록(탭: 모순 지적 · 초반 점검 · 문체 지표),
   가운데 본문(지적 문장 밑줄, 부분 수정 도구), 오른쪽 지적 상세(근거 · 처리 상태 · 메모).
   지적과 회차는 서버 findings.merge 가 만든다 (Episode.findings · rounds). 상태 바꾸기는 PUT …/findings/{id}, 문체 지표는 GET …/style.
   app.js 의 S, P, actions, api, render, home.js 의 checkState, write.js 의 epNav · widenToggle · nextStepBtn,
   marks.js 의 draftBox · readHtml, passage.js 의 textNow · editableEp · passageNotes · editTime, opening.js 의 openingChecks 를 그대로 쓴다. */
'use strict';

Object.assign(S, {
  chkSel: {},          // 화 → 고른 지적 id
  chkFilter: 'open',   // 지적 목록 거르기: open · fixed · kept · wrong · all
  chkTab: 'issues',    // 왼쪽 칸 탭: issues · opening · style
  chkStyle: {},        // 화 → 문체 지표 { metrics, warnings } 또는 { error }
  chkNote: '',         // 고른 지적의 메모 칸 (저장 전)
  chkNoteFor: '',      // chkNote 가 어느 지적('화:id')의 메모인지
});

// 서버 schema.FINDING_STATUS 와 같은 이름
const FINDING_STATUS = { open: '열림', fixed: '고침', kept: '그대로 둠', wrong: '잘못 짚음' };
// 칩 색: 열린 지적만 '사람이 볼 것'(.chip.warn). 화 상태 칩(draft · confirmed · written · finalized)은 빌려 쓰지 않는다 (디자인 시스템 Chip)
const FINDING_CHIP = { open: 'warn', fixed: '', kept: '', wrong: '' };
const FINDING_FLAG = { changed: '문장 바뀜', miss: '이번 회차에서 안 짚음', gone: '다시 검수에서 사라짐', again: '다시 나옴 · 결정 그대로' };

/** 지적 옆 표시. findings.merge 가 남긴 칸(first · last · closed_by)과 지금 본문(저장 전 글 포함)으로 센다. */
function findingFlag(e, f, text) {
  const rounds = e.rounds || [];
  const last = rounds.length ? rounds[rounds.length - 1].no : f.last;
  const quote = (f.current_quote || '').trim();
  if (f.status === 'open') {
    if (quote && !text.includes(quote)) return 'changed';
    return f.last < last ? 'miss' : '';
  }
  if (f.status === 'fixed') return f.closed_by === 'recheck' ? 'gone' : '';
  return f.last === last && f.first < last ? 'again' : '';
}

/** 본문 밑줄 칠 지적 문장: 열린 지적과 고른 지적. 문장마다 처음 나온 곳 하나. kind 는 mark 의 class 가 된다. */
function findingMarks(e, text, sel) {
  const out = [];
  for (const f of e.findings || []) {
    const q = (f.current_quote || '').trim();
    if (!q || (f.status !== 'open' && f.id !== sel)) continue;
    const a = text.indexOf(q);
    if (a !== -1) out.push({ a, b: a + q.length, kind: f.id === sel ? 'issue sel' : 'issue', key: `i:${f.id}`, title: `${f.type} · ${f.description}` });
  }
  return out;
}

/** 지금 고른 지적: 고른 적이 있으면 그것, 없으면 첫 열린 지적, 그도 없으면 첫 지적. */
function chkSelected(n) {
  const e = ep(n);
  const list = (e && e.findings) || [];
  const id = S.chkSel[n];
  if (id && list.some((f) => f.id === id)) return id;
  return (list.find((f) => f.status === 'open') || list[0] || {}).id || '';
}

/** marks.js 가 본문 밑줄에 더한다. 검수 화면에서만. */
function findingRanges(n, text) {
  if (S.route[2] !== 'check' || !ep(n)) return [];
  return findingMarks(ep(n), text, chkSelected(n));
}

const srcLabel = (n, f) => (!f.source_episode ? '설정 · 확정 사실' : f.source_episode === n ? '이번 화 앞 문장' : `${f.source_episode}화`);

async function checkLoad(n) {
  const e = ep(n);
  if (!e || !e.text) return;
  if (!S.presets) S.presets = await api('GET', '/passage/presets').catch(() => []);  // 부분 수정 도구의 빠른 요청
  S.chkStyle[n] = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/style`).catch((err) => ({ error: err.message }));
}

/** 서버가 돌려준 작품에서 이 화의 검수 칸만 가져온다. 화면에서 고치던 다른 칸은 그대로 둔다. */
function takeCheck(n, pj) {
  const src = pj.episodes.find((x) => x.plot.number === n);
  if (src) Object.assign(ep(n), { findings: src.findings, rounds: src.rounds, issues: src.issues, checked_at: src.checked_at });
}

function chkStrip(n, e, st) {
  const rounds = e.rounds || [];
  if (!rounds.length) return '';
  const last = rounds[rounds.length - 1];
  const count = (k) => (k === 'all' ? e.findings.length : e.findings.filter((f) => f.status === k).length);
  const filters = [['open', '열림'], ['fixed', '고침'], ['kept', '그대로 둠'], ['wrong', '잘못 짚음'], ['all', '모두']]
    .map(([k, l]) => `<button type="button" aria-pressed="${S.chkFilter === k}" data-action="chkFilter" data-arg="${k}">${l} ${count(k)}</button>`).join('');
  const from = { chat: ' · 채팅 앱', auto: ' · 자동 집필' };
  const chips = rounds.slice(-4).map((r) => `<span class="chk-round${r === last ? ' last' : ''}">${r.no}회차${r.at ? ` · ${editTime(r.at)}` : ''} · 짚은 ${r.found}${r.no > 1 ? ` · 새로 ${r.added}` : ''}${r.kept_again ? ` · 결정 그대로 ${r.kept_again}` : ''}${from[r.source] || ''}${r.widen ? ' · 넓혀 찾기' : ''}</span>`).join('');
  return `<div class="chk-strip"><span class="small">회차</span><div class="row" style="gap:6px">${chips}</div>
      <div class="seg chk-filters" role="group" aria-label="처리 상태로 거르기">${filters}</div></div>
    ${st.stale ? `<div class="note warn">${last.no}회차 뒤에 본문을 고쳤어요. 고친 문장의 지적은 '문장 바뀜'으로 보여요. 고친 곳이 다른 곳과 어긋나지 않는지 보려면 다시 검수하세요.</div>` : ''}`;
}

function chkStyleBox(n) {
  const d = S.chkStyle[n];
  if (!d) return '<div class="small">재는 중…</div>';
  if (d.error) return `<div class="note err">${esc(d.error)}</div>`;
  return `${d.warnings.length ? `<ul class="issue-list">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '<div class="note ok">기준을 넘은 문체 지표가 없어요.</div>'}
    <div class="small">AI 없이 저장한 본문을 레퍼런스 기준과 견줘요. 계산값이라 처리 상태는 두지 않아요.</div>
    <div class="row"><button type="button" class="btn small" data-action="chkStyleReload" data-arg="${n}">다시 재기</button><a href="${base()}/style" style="font-size:0.8125rem">문체 화면</a></div>`;
}

/** 왼쪽 칸 탭. 초반 점검은 1~3화에만 있다. */
function chkTabs(n, e) {
  return [['issues', `모순 지적 ${(e.findings || []).length}`], ...(isOpening(n) ? [['opening', '초반 점검']] : []),
    ['style', `문체 지표${S.chkStyle[n] && S.chkStyle[n].warnings ? ` ${S.chkStyle[n].warnings.length}` : ''}`]];
}
const chkTabNow = (n, e) => (chkTabs(n, e).some(([k]) => k === S.chkTab) ? S.chkTab : 'issues');

function chkList(n, e, text, sel, checkBtn) {
  const tabs = chkTabs(n, e);
  const tab = chkTabNow(n, e);
  const head = `<div class="tabs wrap" role="tablist" aria-label="검수 종류">${tabs.map(([k, l]) => `<button type="button" role="tab" id="chk-tab-${k}" aria-selected="${tab === k}" aria-controls="chk-panel" data-action="chkTab" data-arg="${k}">${l}</button>`).join('')}</div>`;
  let body;
  if (tab === 'opening') body = openingChecks(n);
  else if (tab === 'style') body = chkStyleBox(n);
  else if (!(e.rounds || []).length) {
    body = `<div class="empty" style="padding:16px 8px"><p>아직 검수하지 않았어요.</p><p class="small">앞선 본문 · 설정 · 확정 사실과 어긋나는 곳을 근거 문장과 함께 찾아요.</p>${checkBtn}</div>`;
  } else {
    const list = e.findings.filter((f) => S.chkFilter === 'all' || f.status === S.chkFilter);
    body = list.length ? `<ul class="chk-list">${list.map((f) => {
      const flag = findingFlag(e, f, text);
      return `<li><button type="button" class="chk-item${f.status === 'open' ? '' : ' done'}" aria-current="${f.id === sel}" data-action="chkSel" data-arg="${esc(f.id)}">
        <span class="row" style="gap:4px"><span class="chip">${esc(f.type)}</span><span class="chip ${FINDING_CHIP[f.status]}">${FINDING_STATUS[f.status]}</span>${flag ? `<span class="chip${flag === 'changed' ? ' warn' : ''}">${FINDING_FLAG[flag]}</span>` : ''}</span>
        <span class="chk-desc">${esc(f.description)}</span><span class="small">근거 · ${esc(srcLabel(n, f))}</span></button></li>`;
    }).join('')}</ul>`
      : `<div class="empty" style="padding:16px 8px"><p class="small">${S.chkFilter === 'open' ? '열린 지적이 없어요. 상태 승인으로 넘어가도 돼요.' : '이 상태의 지적이 없어요.'}</p></div>`;
  }
  return `<section class="card tight c-list" aria-label="검수 결과">${head}<div role="tabpanel" id="chk-panel" aria-labelledby="chk-tab-${tab}" class="chk-panel">${body}</div></section>`;
}

function chkDetail(n, e, text, sel) {
  const f = (e.findings || []).find((x) => x.id === sel);
  if (!f || chkTabNow(n, e) !== 'issues') return '';
  const q = (f.current_quote || '').trim();
  const found = !!q && text.includes(q);
  const can = editableEp(e) && !autoOn();
  const key = `${n}:${f.id}`;
  if (S.chkNoteFor !== key) { S.chkNoteFor = key; S.chkNote = f.note || ''; }
  const seg = Object.entries(FINDING_STATUS).map(([k, l]) => `<button type="button" aria-pressed="${f.status === k}" data-action="setFinding" data-arg="${esc(f.id)}:${k}"${autoOn() ? ' disabled' : ''}>${l}</button>`).join('');
  const src = f.source_episode && f.source_episode !== n ? `<a href="${base()}/write/${f.source_episode}">${f.source_episode}화</a>` : esc(srcLabel(n, f));
  const decided = f.status === 'kept' || f.status === 'wrong';
  return `<section class="card tight c-detail" aria-label="지적 상세">
    <div class="row" style="gap:4px"><span class="chip">${esc(f.type)}</span><span class="chip ${FINDING_CHIP[f.status]}">${FINDING_STATUS[f.status]}</span><span class="small">${f.first}회차부터${f.last !== f.first ? ` · 마지막 ${f.last}회차` : ''}</span></div>
    <h3 class="chk-title">${esc(f.description)}</h3>
    ${q ? `<div class="field"><span class="small">이번 화</span><blockquote class="chk-quote now">${esc(q)}</blockquote>${found ? '' : '<div class="small">지금 본문에서 찾을 수 없어요. 이미 고쳤을 수 있어요.</div>'}</div>` : ''}
    ${f.source_quote ? `<div class="field"><span class="small">근거 · ${src}</span><blockquote class="chk-quote">${esc(f.source_quote)}</blockquote></div>` : ''}
    ${f.suggestion ? `<div class="field"><span class="small">고칠 방향</span><div style="font-size:0.8125rem;line-height:1.55">→ ${esc(f.suggestion)}</div></div>` : ''}
    ${found && can ? `<div class="row"><button type="button" class="btn small" data-action="selectIssue" data-arg="${esc(f.id)}">이 문장 고르기</button>${f.suggestion ? `<button type="button" class="btn small" data-action="issueAsk" data-arg="${esc(f.id)}">고칠 방향으로 AI에게</button>` : ''}</div>` : ''}
    <div class="field"><span class="small">처리</span><div class="seg chk-seg" role="group" aria-label="처리 상태">${seg}</div></div>
    ${decided ? `<div class="field"><label class="small" for="chk-note">왜 ${FINDING_STATUS[f.status]}인지 적어 두면 다시 나와도 바로 알아볼 수 있어요</label>
      <textarea id="chk-note" rows="2" data-local="chkNote">${esc(S.chkNote)}</textarea>
      <div><button type="button" class="btn small" data-action="saveFindingNote" data-arg="${esc(f.id)}">메모 저장</button></div></div>` : ''}
    ${f.status === 'fixed' && f.closed_by === 'recheck' ? '<div class="small">다시 검수에서 문장이 사라져 고침으로 바꿨어요.</div>' : ''}
  </section>`;
}

function viewCheck(n) {
  const e = ep(n);
  if (!e) return header('5단계', stepLabel('check'), '') + noEpisode();
  const st = checkState(e);
  const rounds = e.rounds || [];
  const last = rounds[rounds.length - 1];
  const b = jobBtn('check', n, last ? `다시 검수 · ${last.no + 1}회차` : '검수하기');
  // 주 버튼은 한 화면에 하나, 머리 줄 오른쪽 끝에 둔다 (디자인 시스템 Button). 검수 전에는 빈 목록의 '검수하기'가 주 버튼이라 머리에 두지 않는다
  const checkPrimary = !last || st.stale;
  const checkBtn = `<button class="btn${checkPrimary ? ' primary' : ''}" data-action="checkEp" data-arg="${n}"${e.text && !autoOn() ? b.attr : ' disabled'}>${b.label}</button>`;
  const toReview = e.status === 'written'
    ? `<a class="btn${checkPrimary ? '' : ' primary'}" href="${base()}/review/${n}">상태 승인으로${st.open ? ` · 열린 지적 ${st.open}` : ''}</a>`
    : e.status === 'finalized' && !checkPrimary ? nextStepBtn() : '';  // 반영 끝난 화도 검수가 지금 할 일이면 다음 할 일 버튼은 두지 않는다
  const lead = `${serial() ? widenToggle(false) : ''}${S.mode === 'brief' ? `<a class="btn" href="${base()}/brief/${n}" data-action="openCheckBrief" data-arg="${n}">검수 지시서</a>` : ''}`;
  const right = !e.text ? '' : !last ? lead + toReview : checkPrimary ? lead + toReview + checkBtn : lead + checkBtn + toReview;
  const head = `<header class="page-head"><div class="row" style="gap:12px">${epNav('check', n)}<div class="lead" style="gap:2px"><div class="eyebrow">5단계 ${stepLabel('check')} · ${n} / ${P().meta.target_episodes}화</div><h1 style="font-size:1.5rem">${n}화 ${esc(e.plot.title)}</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span>${stepBar(e)}</div><div class="row">${right}</div></header>
    ${autoLockNote()}`;
  if (!e.text) {
    return head + `<div class="card empty"><p>${n}화 본문이 아직 없어요. 본문을 쓴 뒤 검수해요.</p><a class="btn primary" href="${base()}/write/${n}">${n}화 집필로</a></div>`;
  }
  const text = textNow(n);
  const sel = chkSelected(n);
  const editable = editableEp(e);
  const center = editable ? draftBox(n, text) : `<div class="read" data-read="${n}">${readHtml(n, text)}</div>`;
  const notes = passageNotes(n);
  return head + chkStrip(n, e, st) + `<div class="check-cols">
      ${chkList(n, e, text, sel, checkBtn)}
      ${chkDetail(n, e, text, sel)}
      <section class="card w-body c-body" style="padding:0;gap:0" aria-label="본문">
        <div class="w-bar"><span class="w-count"><strong style="color:var(--text)">${text.length.toLocaleString()}</strong> / ${Number(P().meta.words_per_episode).toLocaleString()}자</span>
          ${editable ? '<div class="savebar-slot"></div>' : '<span class="w-fill"></span>'}
          <p class="small w-hint">${editable ? '밑줄 친 문장을 누르면 그 지적을 고르고 부분 수정 도구가 떠요' : '읽기 전용 본문이에요'}</p></div>
        ${notes ? `<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:8px">${notes}</div>` : ''}
        <div class="prose">${center}</div>
      </section>
    </div>
    ${editable ? chatPanel(`text:${n}`) : ''}`;
}

// 읽기 전용 본문의 지적 밑줄을 누르면 그 지적을 고른다 (고치는 본문은 marks.js 가 부분 수정 도구까지 띄운다)
document.addEventListener('click', (ev) => {
  const m = ev.target.closest && ev.target.closest('.read mark.hl.issue');
  if (!m || S.route[2] !== 'check') return;
  S.chkSel[Number(S.route[3])] = m.dataset.hl.slice(2);
  render();
});

Object.assign(actions, {
  chkSel(id) {
    S.chkSel[Number(S.route[3]) || currentEp()] = id;
    render();
  },
  chkFilter(k) {
    S.chkFilter = k;
    render();
  },
  chkTab(k) {
    S.chkTab = k;
    render();
  },
  async chkStyleReload(n) {
    n = Number(n);
    S.chkStyle[n] = null;
    render();
    await checkLoad(n);
    render();
  },
  /** 집필 화면 '여는 방식 비교'에서: 검수 화면의 초반 점검 탭으로 */
  chkOpening(n) {
    S.chkTab = 'opening';
    location.hash = `${base()}/check/${n}`;
  },
  openCheckBrief(n) {
    BRIEF_TABS[`${S.name}:${n}`] = 'check';
    location.hash = `${base()}/brief/${n}`;
  },
  async setFinding(arg) {
    const n = Number(S.route[3]) || currentEp();
    const [id, status] = String(arg).split(':');
    const f = ep(n).findings.find((x) => x.id === id);
    if (!f || f.status === status) return;
    // 고침으로 닫으면 다음 열린 지적으로 넘어간다. 그대로 둠 · 잘못 짚음은 메모를 적을 수 있게 남는다
    const next = status === 'fixed' ? ep(n).findings.find((x) => x.status === 'open' && x.id !== id) : null;
    await chkPut(n, id, { status });
    if (next) S.chkSel[n] = next.id;
    render();
  },
  async saveFindingNote(id) {
    const n = Number(S.route[3]) || currentEp();
    const f = ep(n).findings.find((x) => x.id === id);
    if (!f) return;
    await chkPut(n, id, { status: f.status, note: S.chkNote });
    S.chkNoteFor = '';
    toast('메모를 저장했어요');
    render();
  },
});

async function chkPut(n, id, body) {
  try {
    takeCheck(n, await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}`, body));
  } catch (err) {
    toast(err.message, true);
  }
}
