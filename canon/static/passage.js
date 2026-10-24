/* 본문 부분 수정 (집필 화면). app.js 의 S, actions, api, render 와 chat.js 의 대화 패널을 그대로 쓴다.
   본문에서 드래그로 고르면 작은 도구가 뜬다. '직접 수정' 은 그 자리에서 고쳐 바로 저장하고,
   'AI에게 고치기' 는 오른쪽 대화 패널(topic 'text:<화>')을 열어 후보 2~3개를 받는다. 후보는 고른 것만 본문에 들어간다.
   고친 것은 모두 서버의 Episode.edits 에 남아 하나씩 되돌릴 수 있다. */
'use strict';

Object.assign(S, {
  sel: null,         // AI에게 맡길 부분 { n, start, text }
  selTool: null,     // 떠 있는 도구 { n, start, text, mode: 'menu' | 'edit', hint? } (hint: marks.js 의 밑줄에서 띄웠을 때 무엇인지)
  selFocus: null,    // 다시 그린 뒤 본문에서 골라 보여 줄 자리 { n, start, end }
  taScroll: {},      // 화별 본문 칸 스크롤 위치 (다시 그려도 읽던 자리를 지킨다)
  presets: null,     // 빠른 요청 목록 (서버 prompts.PASSAGE_PRESETS)
  candEdit: {},      // '메시지:후보' → 손보는 중인 후보 글
});

CHAT_TOPICS.text = {
  title: 'AI에게 고치기',
  intro: '본문에서 고칠 부분을 드래그해 고른 뒤, 바라는 것을 적거나 아래 빠른 요청을 누르세요. AI가 후보를 2~3개 내고, 고른 후보만 본문에 들어가요. 넣은 뒤에도 수정 기록에서 되돌릴 수 있어요.',
  examples: [],
  placeholder: '예: 주인공이 더 망설이게 해 줘',
  clearAsk: '이 화의 부분 수정 대화를 지울까요? 본문과 수정 기록은 그대로예요.',
  ready() {
    if (curSel()) return true;
    toast('본문에서 고칠 부분을 먼저 드래그해 고르세요', true);
    return false;
  },
  presetLabel: (id) => ((S.presets || []).find((x) => x.id === id) || {}).label || id,
  async beforeSend() {
    await flushText(S.sel.n);
  },
  body: (text, preset) => ({ message: text, preset, selection: { start: S.sel.start, text: S.sel.text } }),
  userMsg: (m) => `${m.selection ? `<span class="msg-quote">${esc(clip(m.selection.text, 80))}</span>` : ''}${esc(m.text)}`,
  proposal: passageProposal,
  inputExtra: selTarget,
};

const clip = (t, n) => (t.length > n ? t.slice(0, n) + '…' : t);
const editableEp = (e) => e && (e.status === 'confirmed' || e.status === 'written');
/** 고칠 수 있는 화의 본문 초안. 반영이 끝난 화에 남은 초안은 본문이 아니다 (집필 화면이 따로 꺼내 보인다). */
const liveDraft = (n) => (editableEp(ep(n)) ? S.textDraft[n] : undefined);
const textNow = (n) => liveDraft(n) ?? (ep(n) ? ep(n).text : '');

function curSel() {
  const n = Number(S.route[3]) || currentEp();
  return S.sel && S.sel.n === n ? S.sel : null;
}

/** 본문 칸에서 고친 내용이 저장 전이면 먼저 저장한다. 고른 위치는 서버가 원문으로 다시 찾는다. */
async function flushText(n) {
  if (S.textDraft[n] === undefined) return;
  S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] });
  delete S.textDraft[n];
}

// ----- 단어 단위 비교 -----

function tokens(t) {
  return t.match(/\s+|[^\s.,!?…"'“”‘’]+|[.,!?…"'“”‘’]/g) || [];
}

/** 원문과 후보를 단어 단위로 비교해 지운 것은 <del>, 더한 것은 <ins> 로 보여 준다. */
function wordDiff(a, b) {
  const A = tokens(a);
  const B = tokens(b);
  if (A.length * B.length > 400000) return `<del>${esc(a)}</del><ins>${esc(b)}</ins>`;
  const L = Array.from({ length: A.length + 1 }, () => new Uint16Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--) {
    for (let j = B.length - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  }
  const out = [];
  const push = (kind, t) => {
    const last = out[out.length - 1];
    if (last && last[0] === kind) last[1] += t;
    else out.push([kind, t]);
  };
  let i = 0;
  let j = 0;
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) { push('=', A[i]); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) push('-', A[i++]); else push('+', B[j++]);
  }
  while (i < A.length) push('-', A[i++]);
  while (j < B.length) push('+', B[j++]);
  // 바뀐 곳 사이의 띄어쓰기는 바뀐 곳에 붙여, 지운 글과 더한 글을 덩어리로 읽게 한다
  let html = '';
  let del = '';
  let ins = '';
  const flush = () => {
    html += (del ? `<del>${esc(del)}</del>` : '') + (ins ? `<ins>${esc(ins)}</ins>` : '');
    del = ins = '';
  };
  out.forEach(([k, t], x) => {
    const gap = k === '=' && /^\s*$/.test(t) && (del || ins) && out[x + 1] && out[x + 1][0] !== '=';
    if (k === '-' || gap) del += t;
    if (k === '+' || gap) ins += t;
    if (k === '=' && !gap) {
      flush();
      html += esc(t);
    }
  });
  flush();
  return html;
}

// ----- 대화 패널: 고칠 부분과 빠른 요청, 후보 -----

function selTarget() {
  const s = curSel();
  const busy = !!S.chatPending;
  const presets = (S.presets || []).map((x) => `<button type="button" class="btn small" data-action="passagePreset" data-arg="${esc(x.id)}"${s && !busy ? '' : ' disabled'}>${esc(x.label)}</button>`).join('');
  return `<div class="sel-target">
    ${s ? `<div class="between"><span class="small">고칠 부분 · ${s.text.length.toLocaleString()}자</span><button type="button" class="btn small" data-action="selShow">본문에서 보기</button></div>
      <blockquote>${esc(clip(s.text, 220))}</blockquote>`
    : '<div class="small">본문에서 고칠 부분을 드래그해 고르면 여기에 담겨요.</div>'}
    <div class="row" style="gap:6px">${presets}</div>
  </div>`;
}

function passageProposal(m, i) {
  const n = Number(S.chatTopic.split(':')[1]);
  const orig = m.selection.text;
  const open = !m.outcome;
  const lost = open && !textNow(n).includes(orig);
  const cards = m.passage.candidates.map((c, k) => {
    const key = `${i}:${k}`;
    const editing = S.candEdit[key] !== undefined;
    const body = editing
      ? `<textarea rows="5" data-cand-edit="${key}" aria-label="후보 ${k + 1} 손보기">${esc(S.candEdit[key])}</textarea>`
      : `<div class="pdiff">${wordDiff(orig, c.text)}</div>`;
    const chosen = m.outcome === 'applied' && m.applied[0] === String(k);
    const btns = !open || lost ? '' : editing
      ? `<button class="btn small primary" data-action="passageApply" data-arg="${key}">손본 글로 바꾸기</button><button class="btn small" data-action="passageTweak" data-arg="${key}">취소</button>`
      : `<button class="btn small primary" data-action="passageApply" data-arg="${key}">이걸로 바꾸기</button><button class="btn small" data-action="passageTweak" data-arg="${key}">손봐서 넣기</button>`;
    return `<div class="cand${chosen ? ' chosen' : ''}"><div class="between"><strong>후보 ${k + 1}${chosen ? ' · 넣음' : ''}</strong><span class="small">${(c.text.length - orig.length >= 0 ? '+' : '') + (c.text.length - orig.length)}자</span></div>
      ${c.note ? `<div class="small">${esc(c.note)}</div>` : ''}${body}${btns ? `<div class="row">${btns}</div>` : ''}</div>`;
  }).join('');
  const done = m.outcome === 'applied' ? `<span class="chip finalized">${Number(m.applied[0]) + 1}번 후보를 넣음</span>`
    : m.outcome === 'dismissed' ? '<span class="chip">넣지 않음</span>' : '';
  if (!open) return `<details class="proposal done"><summary>${done} 후보 다시 보기</summary>${cards}${m.outcome === 'dismissed' ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="chatReopen" data-arg="${i}">다시 검토</button></div>` : ''}</details>`;
  return `<div class="proposal">${lost ? '<div class="note plain">그사이 이 부분이 바뀌어 후보를 넣을 수 없어요. 다시 골라 요청하세요.</div>' : ''}${cards}
    <div class="row"><button class="btn small" data-action="chatDismiss" data-arg="${i}">모두 넣지 않음</button></div></div>`;
}

// ----- 집필 화면 블록 -----

/** 본문 위 안내: 고친 뒤라 다시 해야 할 단계. */
function passageNotes(n) {
  const e = ep(n);
  const out = [];
  const lastEdit = [...(e.edits || [])].reverse().find((x) => !x.undone);
  if (S.deltas[n] && S.deltaBase[n] !== undefined && S.deltaBase[n] !== textNow(n)) {
    out.push(`<div class="note warn">상태 변경안을 만든 뒤 본문을 고쳤어요. 변경안은 고치기 전 본문 기준이라 <a href="${base()}/review/${n}">상태 승인</a>에서 다시 만드는 게 좋아요.</div>`);
  }
  if (e.issues && e.issues.length && lastEdit && lastEdit.at > (e.checked_at || '')) {
    out.push(`<div class="note plain">검수에서 찾은 ${e.issues.length}곳은 고치기 전 본문 기준이에요. 이미 고친 곳일 수 있어요.</div>`);
  }
  return out.join('');
}

/** 검수에서 찾은 곳. 누르면 본문에서 그 문장을 골라 바로 고칠 수 있게 한다. */
function issuesBlock(e) {
  if (!e.issues || !e.issues.length) return '';
  const n = e.plot.number;
  const text = textNow(n);
  return `<div class="field"><span class="small">검수에서 찾은 곳 ${e.issues.length}</span><ol class="issue-list">${e.issues.map((x, k) => `<li>
      <span class="chip">${esc(x.type)}</span> ${esc(x.description)}
      ${x.current_quote && text.includes(x.current_quote) && editableEp(e) ? `<button type="button" class="btn small" data-action="selectIssue" data-arg="${k}">이 문장 고르기</button>` : ''}</li>`).join('')}</ol></div>`;
}

const SOURCE = { manual: '직접', ai: 'AI', typed: '본문 저장', impact: '인과율' };

function editTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? fmtDateTime(iso).slice(11) : fmtDate(iso);  // 오늘이면 시각만
}

function editHistory(e) {
  const list = [...(e.edits || [])].reverse().slice(0, 30);
  if (!list.length) return '';
  const n = e.plot.number;
  const text = textNow(n);
  const can = editableEp(e) && S.textDraft[n] === undefined;
  const rows = list.map((x) => {
    const findable = x.after ? text.includes(x.after) : true;
    const redoable = x.before ? text.includes(x.before) : true;  // 다시 넣기는 취소로 돌아온 글을 찾는다 (pipeline.redo_edit)
    return `<li class="edit-row${x.undone ? ' undone' : ''}">
      <div class="between"><span class="row" style="gap:6px"><span class="chip${x.source === 'ai' ? ' ai' : ''}">${SOURCE[x.source] || x.source}</span>${x.instruction ? `<span class="small">${esc(clip(x.instruction, 40))}</span>` : ''}<span class="small">${editTime(x.at)}</span>${x.undone ? '<span class="chip">취소함</span>' : ''}</span>
        ${!x.undone && can ? `<button type="button" class="btn small" data-action="undoEdit" data-arg="${esc(x.id)}"${findable ? '' : ' disabled title="그 뒤에 같은 자리를 다시 고쳐서 취소할 수 없어요"'}>수정 취소</button>` : ''}${x.undone && can ? `<button type="button" class="btn small" data-action="redoEdit" data-arg="${esc(x.id)}"${redoable ? '' : ' disabled title="그 뒤에 같은 자리를 다시 고쳐서 다시 넣을 수 없어요"'}>다시 넣기</button>` : ''}</div>
      <div class="pdiff small-diff">${wordDiff(clip(x.before, 400), clip(x.after, 400))}</div></li>`;
  }).join('');
  return `<details class="card edits"${S.editsOpen ? ' open' : ''} data-edits-toggle>
    <summary><strong>수정 기록</strong> <span class="small">${e.edits.length}건 · 하나씩 되돌릴 수 있어요${can ? '' : ' (저장하지 않은 본문이 있으면 먼저 저장하세요)'}</span></summary>
    <ol class="edit-list">${rows}</ol></details>`;
}

// ----- 떠 있는 도구 -----

function toolEl() {
  let el = document.getElementById('sel-tool');
  if (!el) {
    el = document.createElement('div');
    el.id = 'sel-tool';
    el.className = 'sel-tool';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

function hideTool() {
  S.selTool = null;
  const el = document.getElementById('sel-tool');
  if (el) el.hidden = true;
}

/** 본문 칸 안 글자 위치의 화면 좌표. 같은 모양의 숨은 칸에 글을 채워 잰다. */
function caretXY(ta, pos) {
  const cs = getComputedStyle(ta);
  const div = document.createElement('div');
  ['boxSizing', 'width', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing', 'textIndent',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'tabSize', 'wordBreak', 'overflowWrap'].forEach((k) => { div.style[k] = cs[k]; });
  Object.assign(div.style, { position: 'absolute', visibility: 'hidden', whiteSpace: 'pre-wrap', top: '0', left: '-9999px' });
  div.textContent = ta.value.slice(0, pos);
  const mark = document.createElement('span');
  mark.textContent = ta.value.slice(pos, pos + 1) || '.';
  div.appendChild(mark);
  document.body.appendChild(div);
  const r = ta.getBoundingClientRect();
  const out = { x: r.left + mark.offsetLeft - ta.scrollLeft, y: r.top + mark.offsetTop - ta.scrollTop, h: parseFloat(cs.lineHeight) || 28, r };
  div.remove();
  return out;
}

/** 고른 부분 끝 줄 바로 아래에 둔다. 고치기 칸은 넓어서 왼쪽을 본문 칸에 맞춘다. */
function placeTool(ta, t) {
  const el = toolEl();
  const c = caretXY(ta, t.start + t.text.length);
  const y = Math.min(Math.max(c.y, c.r.top), c.r.bottom) + c.h + 4;
  const w = el.offsetWidth || 240;
  const left = t.mode === 'edit' ? Math.max(c.r.left, Math.min(caretXY(ta, t.start).x, c.x) - 12) : c.x - 40;
  const x = Math.min(Math.max(8, left), document.documentElement.clientWidth - w - 8);
  el.style.left = `${x + window.scrollX}px`;
  el.style.top = `${y + window.scrollY}px`;
}

function showTool() {
  const t = S.selTool;
  const ta = document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta) return hideTool();
  const el = toolEl();
  el.classList.toggle('edit', t.mode === 'edit');
  el.innerHTML = t.mode === 'edit'
    ? `<label class="small" for="sel-edit">고른 부분 고치기 · ${t.text.length.toLocaleString()}자</label>
       <textarea id="sel-edit" rows="${Math.min(10, Math.max(3, Math.ceil(t.text.length / 40)))}">${esc(t.text)}</textarea>
       <div class="between"><span class="small">Ctrl+Enter 바꾸기 · Esc 닫기</span><span class="row" style="gap:6px"><button type="button" class="btn small" data-action="selCancel">취소</button><button type="button" class="btn small primary" data-action="selSave">바꾸기</button></span></div>`
    : `${t.hint ? `<span class="small sel-hint">${esc(t.hint)}</span>` : ''}<button type="button" class="btn small" data-action="selManual">직접 수정</button><button type="button" class="btn small primary" data-action="selAi">AI에게 고치기</button><button type="button" class="btn small" data-action="selIllust">삽화 프롬프트</button>`;
  el.hidden = false;
  placeTool(ta, t);
  if (t.mode === 'edit') {
    const box = $('#sel-edit');
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  }
}

/** 본문 칸에서 고른 부분. 앞뒤 공백은 뺀다. */
function readSel(ta) {
  let a = ta.selectionStart;
  let b = ta.selectionEnd;
  const v = ta.value;
  while (a < b && /\s/.test(v[a])) a++;
  while (b > a && /\s/.test(v[b - 1])) b--;
  return b > a ? { n: Number(ta.dataset.draft), start: a, text: v.slice(a, b) } : null;
}

function onSelect(e) {
  const isText = (el) => el && el.matches && el.matches('textarea[data-draft]');
  const ta = isText(e.target) ? e.target : document.activeElement;  // 본문 밖에서 손을 떼도 본문에서 고른 것
  if (!isText(ta) || !editableEp(ep(Number(ta.dataset.draft)))) return;
  setTimeout(() => {  // 클릭으로 고른 것이 풀리는 것까지 본 뒤에
    const s = readSel(ta);
    if (!s) return S.selTool && S.selTool.mode === 'menu' ? hideTool() : undefined;
    if (S.selTool && S.selTool.mode === 'edit') return;
    S.selTool = { ...s, mode: 'menu' };
    showTool();
  }, 0);
}

document.addEventListener('mouseup', onSelect);
document.addEventListener('keyup', (e) => { if (e.shiftKey || e.key === 'Shift' || (e.key === 'a' && (e.ctrlKey || e.metaKey))) onSelect(e); });
document.addEventListener('touchend', onSelect);

document.addEventListener('mousedown', (e) => {
  if (!S.selTool || e.target.closest('#sel-tool') || (e.target.matches && e.target.matches('textarea[data-draft]'))) return;
  if (S.selTool.mode === 'menu') hideTool();
});

document.addEventListener('keydown', (e) => {
  if (!S.selTool || e.isComposing) return;
  if (e.key === 'Escape') { hideTool(); return; }
  if (e.target.id === 'sel-edit' && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    actions.selSave();
  }
});

document.addEventListener('scroll', (e) => {
  const ta = e.target;
  if (ta.matches && ta.matches('textarea[data-draft]')) {
    S.taScroll[ta.dataset.draft] = ta.scrollTop;
    if (S.selTool && S.selTool.mode === 'menu') hideTool();
  }
}, true);

document.addEventListener('input', (e) => {
  const k = e.target.dataset && e.target.dataset.candEdit;
  if (k !== undefined) S.candEdit[k] = e.target.value;
  if (e.target.matches && e.target.matches('textarea[data-draft]') && S.selTool) hideTool();
});

document.addEventListener('toggle', (e) => {
  if (e.target.matches && e.target.matches('[data-edits-toggle]')) S.editsOpen = e.target.open;
}, true);

/** render() 직후에 부른다: 도구를 닫고, 본문 칸의 스크롤과 방금 고친 자리를 되살린다.
    '직접 수정' 칸은 #app 밖에 있어 다시 그려도 남는다. 그 화 본문 칸이 아직 있으면 쓰던 글째로 자리만 다시 맞춘다
    (showTool 은 칸을 새로 만들어 쓰던 글을 지운다). */
function syncPassage() {
  const t = S.selTool;
  const keep = t && t.mode === 'edit' && editableEp(ep(t.n)) && document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (keep) placeTool(keep, t);
  else hideTool();
  const ta = document.querySelector('textarea[data-draft]');
  if (!ta) return;
  const n = ta.dataset.draft;
  if (S.taScroll[n]) ta.scrollTop = S.taScroll[n];
  const f = S.selFocus;
  if (f && String(f.n) === n) {
    S.selFocus = null;
    ta.focus({ preventScroll: true });
    ta.setSelectionRange(f.start, f.end);
    const c = caretXY(ta, f.start);
    if (c.y < c.r.top || c.y > c.r.bottom - c.h) ta.scrollTop += c.y - c.r.top - c.r.height / 3;
  }
}

/** 서버가 돌려준 본문에서 글을 start 가까이에서 찾아 본문 칸에 골라 보여 준다. */
function focusText(n, text, start) {
  const body = textNow(n);
  let at = -1;
  for (let i = body.indexOf(text); i !== -1; i = body.indexOf(text, i + 1)) {
    if (at === -1 || Math.abs(i - start) < Math.abs(at - start)) at = i;
  }
  if (at !== -1) S.selFocus = { n, start: at, end: at + text.length };
  return at;
}

Object.assign(actions, {
  selManual() {
    S.selTool.mode = 'edit';
    showTool();
  },
  selCancel() {
    hideTool();
  },
  async selSave() {
    const t = S.selTool;
    const after = ($('#sel-edit').value || '').trim();
    if (!after) return toast('고친 글이 비었어요. 지우려면 본문에서 직접 지우세요', true);
    if (after === t.text) return hideTool();
    await run('고치는 중', async () => {
      await saveIfDirty();
      await flushText(t.n);
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${t.n}/edits`, { selection: { start: t.start, text: t.text }, after });
      hideTool();  // 바꿨으니 닫는다. 실패하면 칸을 남겨 쓰던 글을 지킨다 (syncPassage 가 edit 모드 칸은 남긴다)
      const edit = ep(t.n).edits[ep(t.n).edits.length - 1];
      focusText(t.n, after, edit.start);
      if (S.sel && S.sel.n === t.n) S.sel = { n: t.n, start: edit.start, text: after };
      toast('고쳤어요. 수정 기록에서 되돌릴 수 있어요');
    });
  },
  selAi() {
    const t = S.selTool;
    S.sel = { n: t.n, start: t.start, text: t.text };
    hideTool();
    S.chatOpen = true;
    S.chatScroll = true;
    try { localStorage.setItem('canon.chat', '1'); } catch { /* 저장 못 해도 동작에는 상관없다 */ }
    render();
    $('#chat-input')?.focus();
  },
  selShow() {
    const s = curSel();
    if (s && focusText(s.n, s.text, s.start) === -1) return toast('본문에서 찾을 수 없어요. 다시 골라 주세요', true);
    render();
  },
  selectIssue(k) {
    const n = Number(S.route[3]) || currentEp();
    const q = ep(n).issues[k].current_quote;
    if (focusText(n, q, 0) === -1) return toast('본문에서 그 문장을 찾을 수 없어요', true);
    render();
    const ta = document.querySelector(`textarea[data-draft="${n}"]`);
    const s = ta && readSel(ta);
    if (s) {
      S.selTool = { ...s, mode: 'menu' };
      showTool();
    }
  },
  passagePreset(id) {
    actions.chatSend(String(id));
  },
  passageTweak(key) {
    const [i, k] = String(key).split(':').map(Number);
    if (S.candEdit[key] !== undefined) delete S.candEdit[key];
    else S.candEdit[key] = chatMessages(S.chatTopic)[i].passage.candidates[k].text;
    render();
  },
  async passageApply(key) {
    const [i, k] = String(key).split(':').map(Number);
    const topic = S.chatTopic;
    const n = Number(topic.split(':')[1]);
    const body = { candidate: k };
    if (S.candEdit[key] !== undefined) body.text = S.candEdit[key];
    await run('본문에 넣는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/${enc(topic)}/${i}/apply`, body);
      delete S.candEdit[key];
      const edit = ep(n).edits[ep(n).edits.length - 1];
      S.sel = { n, start: edit.start, text: edit.after };  // 이어서 '더 짧게' 같은 요청을 하면 넣은 글을 고친다
      focusText(n, edit.after, edit.start);
      toast(`${k + 1}번 후보를 넣었어요. 수정 기록에서 되돌릴 수 있어요`);
    });
  },
  async undoEdit(id) {
    const n = Number(S.route[3]) || currentEp();
    const edit = ep(n).edits.find((x) => x.id === id);
    // 칸의 초안이 서버 본문을 가린다. 먼저 저장해야 취소한 결과가 화면에 보이고, 나중에 초안을 저장해도 되살아나지 않는다
    if (textUnsaved(n) && !confirm('저장하지 않은 본문 수정이 있어요. 먼저 저장하고 이 수정을 취소할까요?')) return;
    await run('수정을 취소하는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/edits/${enc(id)}/undo`);
      if (edit.before) focusText(n, edit.before, edit.start);
      if (S.sel && S.sel.n === n && !textNow(n).includes(S.sel.text)) S.sel = null;
      toast('수정을 취소했어요. 기록의 \'다시 넣기\'로 되돌릴 수 있어요');
    });
  },
  async redoEdit(id) {
    const n = Number(S.route[3]) || currentEp();
    const edit = ep(n).edits.find((x) => x.id === id);
    if (textUnsaved(n) && !confirm('저장하지 않은 본문 수정이 있어요. 먼저 저장하고 이 수정을 다시 넣을까요?')) return;
    await run('다시 넣는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/edits/${enc(id)}/redo`);
      if (edit.after) focusText(n, edit.after, edit.start);
      if (S.sel && S.sel.n === n && !textNow(n).includes(S.sel.text)) S.sel = null;
      toast('수정을 다시 넣었어요');
    });
  },
});
