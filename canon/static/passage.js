/* 본문 부분 수정 (집필 화면). app.js 의 S, actions, api, render 와 chat.js 의 대화 패널을 그대로 쓴다.
   본문에서 드래그로 고르면 작은 도구가 뜬다. '직접 수정' 은 그 자리에서 고쳐 바로 저장하고,
   'AI에게 고치기' 는 오른쪽 대화 패널(topic 'text:<화>')을 열어 후보 2~3개를 받는다. 후보는 고른 것만 본문에 들어간다.
   상태 정리 경고가 가리킨 문장의 'AI에게 고치기' 는 대화 패널을 거치지 않고 첫 후보를 바로 넣는다 (aiFixNow).
   기다리는 동안 화면을 잠그지 않고 그 화 본문 칸만 잠근다. 경고 문장이 본문에 그대로 한 번만 있을 때만 바로 넣는다.
   고친 것은 모두 서버의 Episode.edits 에 남아 하나씩 되돌릴 수 있다. */
'use strict';

Object.assign(S, {
  sel: null,         // AI에게 맡길 부분 { n, start, text }
  selTool: null,     // 떠 있는 도구 { n, start, text, mode: 'menu' | 'edit' | 'finding', hint?, fid? } (hint: marks.js 의 밑줄에서 띄웠을 때 무엇인지,
                     //   finding: 검수 화면에서 지적 fid 를 고치는 창 check.js fixPanel)
  selFocus: null,    // 다시 그린 뒤 본문에서 골라 보여 줄 자리 { n, start, end }
  taScroll: {},      // 화별 본문 칸 스크롤 위치 (다시 그려도 읽던 자리를 지킨다)
  presets: null,     // 빠른 요청 목록 (서버 prompts.PASSAGE_PRESETS)
  candEdit: {},      // '메시지:후보' → 손보는 중인 후보 글
  aiFix: null,       // 경고의 'AI에게 고치기'가 AI를 기다리는 중 { name, n, w } (aiFixNow). 그동안 그 화 본문 칸을 잠근다
});

CHAT_TOPICS.text = {
  title: 'AI에게 고치기',
  intro: '본문에서 고칠 부분을 드래그하거나 길게 눌러 고른 뒤, 바라는 것을 적거나 아래 빠른 요청을 누르세요. AI가 후보를 2~3개 내고, 고른 후보만 본문에 들어가요. 넣은 뒤에도 수정 기록에서 되돌릴 수 있어요.',
  examples: [],
  placeholder: '예: 주인공이 더 망설이게 해 줘',
  clearAsk: '이 화의 부분 수정 대화를 지울까요? 본문과 수정 기록은 그대로예요.',
  ready() {
    if (curSel()) return true;
    toast('본문에서 고칠 부분을 먼저 드래그하거나 길게 눌러 고르세요', true);
    return false;
  },
  presetLabel: (id) => ((S.presets || []).find((x) => x.id === id) || {}).label || id,
  async beforeSend() {
    await flushText(S.sel.n);
  },
  body: (text, preset) => ({ message: text, preset, selection: { start: S.sel.start, text: S.sel.text } }),
  userMsg: (m) => `${m.selection ? `<span class="msg-quote">${esc(clip(m.selection.text, 80))}</span>` : ''}${m.preset && m.text !== CHAT_TOPICS.text.presetLabel(m.preset) ? `<span class="chip">${esc(CHAT_TOPICS.text.presetLabel(m.preset))}</span> ` : ''}${esc(m.text)}`,  // 빠른 요청과 함께 적은 글이 있으면 둘 다 보인다
  proposal: passageProposal,
  // 시트를 높이는 것은 지금 고른 부분의 후보일 때만이다. 다른 부분을 새로 골라 열면 옛 후보 때문에 본문이 가려지지 않게
  candsFor: (m) => { const s = curSel(); return !!s && !!m.selection && m.selection.text === s.text; },
  inputExtra: selTarget,
};

const clip = (t, n) => (t.length > n ? t.slice(0, n) + '…' : t);
// 반영이 끝난 화도 고친다. 반영된 상태는 그대로 두고 서버가 반영 뒤 고침으로 표시한다 (restate.js)
const editableEp = (e) => e && (e.status === 'confirmed' || e.status === 'written' || e.status === 'finalized');
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
  S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, textBody(n, S.textDraft[n]));  // 다른 곳이 먼저 저장했으면 409(stale_text)로 멈춘다
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
    : '<div class="small">본문에서 고칠 부분을 드래그하거나 길게 눌러 고르면 여기에 담겨요.</div>'}
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
    <div class="row"><button class="btn small" data-action="chatDismiss" data-arg="${i}">모두 넣지 않기</button></div></div>`;
}

// ----- 집필 화면 블록 -----

/** 본문 위 안내: 고친 뒤라 다시 해야 할 단계. */
function passageNotes(n) {
  const out = [];
  if (S.deltas[n] && S.deltaBase[n] !== undefined && S.deltaBase[n] !== textNow(n)) {
    out.push(`<div class="note warn">상태 변경안을 만든 뒤 본문을 고쳤어요. 변경안은 고치기 전 본문 기준이라 <a href="${base()}/review/${n}">상태 승인</a>에서 다시 만드는 게 좋아요.</div>`);
  }
  return out.join('');
}

/** 경고 글의 «» · 따옴표 안 문구. 두 글자 이상, 긴 것부터. */
function warnQuotes(w) {
  const quotes = [];
  for (const re of [/«([^»]+)»/g, /[“"]([^”"]+)[”"]/g, /[‘']([^’']+)[’']/g, /「([^」]+)」/g, /『([^』]+)』/g]) {
    for (const m of String(w || '').matchAll(re)) quotes.push(m[1].trim());
  }
  return quotes.filter((q) => q.length >= 2).sort((a, b) => b.length - a.length);
}

/** 경고 문장 q 와, 그 글이 경고에 그대로 옮겨 적혀 있고 본문에 한 번만 있는지(exact).
    exact 가 아니면 비슷한 문장이거나 여러 자리라 AI가 엉뚱한 곳을 고칠 수 있다. 'AI에게 고치기'는 바로 넣지 않고 대화 패널로 보낸다 */
function warnSpot(w, text) {
  const q = warnQuote(w, text);
  const exact = !!q && warnQuotes(w).includes(q) && text.indexOf(q) === text.lastIndexOf(q);
  return { q, exact };
}

const warnMsg = (w) => `상태 정리 경고: ${w}`;
/** 경고 w 를 'AI에게 고치기'로 고쳤고 되돌리지 않았는가. 수정 기록의 요청 글로 안다 (따로 저장하지 않는다) */
const warnFixed = (n, w) => ((ep(n) || {}).edits || []).some((e) => e.source === 'ai' && !e.undone && e.instruction === warnMsg(w));
/** n화 경고를 AI가 고치는 중인가 (w 를 주면 그 경고만) */
const aiFixing = (n, w) => !!S.aiFix && S.aiFix.name === S.name && S.aiFix.n === n && (w === undefined || S.aiFix.w === w);

/** 경고 한 줄 뒤에 붙는 것: 고치는 중 · AI가 고침 표시, 아니면 '이 문장 고르기' · 'AI에게 고치기' (warnItems · review.js rvWarnLine) */
function warnTools(n, k, w, inline = false) {
  if (aiFixing(n, w)) return '<span class="small" role="status">AI가 고치는 중이에요</span>';
  if (warnFixed(n, w)) return '<span class="chip ok">AI가 고침</span>';
  const text = textNow(n);
  const { q, exact } = editableEp(ep(n)) ? warnSpot(w, text) : { q: '' };
  if (!q) return '';
  const title = exact ? 'AI가 고친 글을 바로 본문에 넣어요. 알림의 되돌리기로 취소할 수 있어요' : '경고와 똑같은 문장이 없거나 여러 곳이라, 가장 비슷한 문장을 골라 대화 패널에서 보내게 해요';
  return `<span class="row" style="gap:6px${inline ? ';display:inline-flex' : ''}"><button type="button" class="btn small" data-action="warnPick" data-arg="${n}:${k}">이 문장 고르기</button><button type="button" class="btn small" data-action="warnPick" data-arg="${n}:${k}:ask" title="${title}">AI에게 고치기</button></span>`;
}

/** 상태 변경안 경고 속 본문 문장. «» · 따옴표 안 문구를 길이 순으로 본문에서 찾고, 그대로 없으면 낱말이 가장 많이 겹치는 문장. 못 찾으면 ''. */
function warnQuote(w, text) {
  if (!w || !text) return '';
  const qs = warnQuotes(w);
  const exact = qs.find((q) => text.includes(q));
  if (exact) return exact;
  // AI가 문장을 조금 바꿔 옮겼을 때: 낱말 열에 여섯 이상 들어 있는 문장
  const sentences = text.split(/\n+|(?<=[.!?…]['"’”」』]?)\s+/).map((s) => s.trim()).filter(Boolean);
  let best = '';
  let score = 0;
  for (const q of qs) {
    const words = [...new Set(q.split(/[\s,.!?…'"“”‘’()]+/).filter((x) => x.length >= 2))];
    if (words.length < 2) continue;
    const need = Math.max(2, Math.ceil(words.length * 0.6));
    for (const s of sentences) {
      const k = words.filter((x) => s.includes(x)).length;
      if (k >= need && k > score) { score = k; best = s; }
    }
  }
  return best;
}

/** 상태 변경안 경고 목록. 본문 문장이 걸린 경고에는 그 문장을 골라 부분 수정 도구를 여는 버튼을 단다. */
function warnItems(n, warnings) {
  return warnings.map((w, k) => {
    const tools = warnTools(n, k, w, true);
    return `<li>${esc(w)}${tools ? ` ${tools}` : ''}</li>`;
  }).join('');
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
    el.setAttribute('role', 'toolbar');
    el.setAttribute('aria-label', '고른 부분 도구');
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
  ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing', 'textIndent',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'tabSize', 'wordBreak', 'overflowWrap'].forEach((k) => { div.style[k] = cs[k]; });
  // 글이 줄을 바꾸는 폭은 스크롤바를 뺀 안쪽 폭(clientWidth)이다. 테두리는 빼고 재서 아래에서 clientLeft · clientTop 으로 더한다
  Object.assign(div.style, { position: 'absolute', visibility: 'hidden', whiteSpace: 'pre-wrap', top: '0', left: '-9999px',
    boxSizing: 'border-box', width: `${ta.clientWidth}px`, border: '0' });
  div.textContent = ta.value.slice(0, pos);
  const mark = document.createElement('span');
  mark.textContent = ta.value.slice(pos, pos + 1) || '.';
  div.appendChild(mark);
  document.body.appendChild(div);
  const r = ta.getBoundingClientRect();
  const out = { x: r.left + ta.clientLeft + mark.offsetLeft - ta.scrollLeft, y: r.top + ta.clientTop + mark.offsetTop - ta.scrollTop, h: parseFloat(cs.lineHeight) || 28, r };
  div.remove();
  return out;
}

/** 고른 부분 끝 줄 바로 아래에 둔다. 화면 아래로 넘치면 고른 첫 줄 위에 둔다. 고치기 칸은 넓어서 왼쪽을 본문 칸에 맞춘다. */
function placeTool(ta, t) {
  const el = toolEl();
  const c = caretXY(ta, t.start + t.text.length);
  let y = Math.min(Math.max(c.y, c.r.top), c.r.bottom) + c.h + 4;
  if (y + el.offsetHeight > window.innerHeight) {
    const top = caretXY(ta, t.start).y - el.offsetHeight - 4;
    if (top >= 0) y = top;
  }
  el.style.left = '0px';  // 옛 자리에서 재면 오른쪽 남은 폭만큼 줄어든 너비가 나온다
  const w = el.offsetWidth || 240;
  const left = t.mode !== 'menu' ? Math.max(c.r.left, Math.min(caretXY(ta, t.start).x, c.x) - 12) : c.x - 40;
  const x = Math.min(Math.max(8, left), document.documentElement.clientWidth - w - 8);
  el.style.left = `${x + window.scrollX}px`;
  el.style.top = `${y + window.scrollY}px`;
}

function showTool() {
  const t = S.selTool;
  const ta = document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta) return hideTool();
  if (typeof mentionClose === 'function') mentionClose();  // 고른 부분 도구와 이름 카드(mentions.js)는 한 번에 하나만
  const el = toolEl();
  el.classList.toggle('edit', t.mode === 'edit');
  el.classList.toggle('finding', t.mode === 'finding');
  el.setAttribute('aria-label', t.mode === 'finding' ? '검수 지적 고치기' : '고른 부분 도구');
  if (t.mode === 'finding') {
    const html = typeof fixPanel === 'function' ? fixPanel(t.n, t.fid) : '';
    if (!html) return hideTool();
    el.innerHTML = html;
    el.hidden = false;
    placeTool(ta, t);
    return;
  }
  el.innerHTML = t.mode === 'edit'
    ? `<label class="small" for="sel-edit">고른 부분 고치기 · ${t.text.length.toLocaleString()}자</label>
       <textarea id="sel-edit" rows="${Math.min(10, Math.max(3, Math.ceil(t.text.length / 40)))}">${esc(t.text)}</textarea>
       <div class="between"><span class="small">${matchMedia('(pointer: coarse)').matches ? '' : 'Ctrl+Enter 바꾸기 · Esc 닫기'}</span><span class="row" style="gap:6px"><button type="button" class="btn small" data-action="selCancel">취소</button><button type="button" class="btn small primary" data-action="selSave">바꾸기</button></span></div>`
    : `${t.hint ? `<span class="small sel-hint">${esc(t.hint)}</span>` : ''}<span class="sr-only">본문 칸에서 Alt+Enter로 이 도구에 오고 Esc로 돌아가요.</span><button type="button" class="btn small" data-action="selManual">직접 수정</button><button type="button" class="btn small primary" data-action="selAi">AI에게 고치기</button><button type="button" class="btn small" data-action="selIllust">삽화 프롬프트 만들기</button>`;
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

const isDraftTa = (el) => !!el && !!el.matches && el.matches('textarea[data-draft]');
// 본문 칸 밖(도구 밖)에서 시작한 마지막 터치 시각. 그 터치의 touchend · 뒤따르는 mouseup 은 본문 칸에 남은 선택으로 도구를 띄우지 않는다
let outsideTouch = 0;

function onSelect(e) {
  const isText = isDraftTa;
  if ((e.type === 'touchend' || e.type === 'mouseup') && outsideTouch && Date.now() - outsideTouch < 1500) return;
  // 도구 버튼을 누르고 뗀 것은 고르기가 아니다. 버튼이 도구를 닫은 뒤 본문 칸에 남은 선택으로 도구가 다시 떴다
  if (e.target && e.target.closest && e.target.closest('#sel-tool')) return;
  const ta = isText(e.target) ? e.target : document.activeElement;  // 본문 밖에서 손을 떼도 본문에서 고른 것
  if (!isText(ta) || !P() || !editableEp(ep(Number(ta.dataset.draft)))) return;  // 작품 목록으로 옮기는 사이에 남은 본문 칸
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
// 휴대폰에서 본문 밖을 누르면 떠 있던 메뉴를 닫는다. iOS 는 포커스를 받지 않는 곳을 눌러도 본문 칸 포커스와 선택을 그대로 두어,
// 누를 때마다 남은 선택으로 도구가 다시 떠 본문을 덮었다
document.addEventListener('touchstart', (e) => {
  const t = e.target;
  const out = !isDraftTa(t) && !(t.closest && t.closest('#sel-tool'));
  outsideTouch = out ? Date.now() : 0;
  if (out && S.selTool && S.selTool.mode === 'menu') hideTool();
}, { capture: true, passive: true });
// 휴대폰에서 손잡이를 끌어 고른 범위를 넓히면 selectionchange 만 온다. 메뉴가 떠 있으면 새 범위로 바꾼다
let selTimer = 0;
document.addEventListener('selectionchange', () => {
  clearTimeout(selTimer);
  selTimer = setTimeout(() => {
    const ta = document.activeElement;
    if (!(ta && ta.matches && ta.matches('textarea[data-draft]')) || !S.selTool || S.selTool.mode !== 'menu') return;
    const s = readSel(ta);
    if (!s || (s.start === S.selTool.start && s.text === S.selTool.text)) return;
    S.selTool = { ...S.selTool, ...s };
    showTool();
  }, 150);
});

document.addEventListener('mousedown', (e) => {
  if (!S.selTool || e.target.closest('#sel-tool') || (e.target.matches && e.target.matches('textarea[data-draft]'))) return;
  if (S.selTool.mode === 'menu') hideTool();
});

document.addEventListener('keydown', (e) => {
  if (!S.selTool || e.isComposing) return;
  if (e.key === 'Escape') {
    // 도구 안에서 닫으면 본문 칸으로 돌아간다. 읽기 전용 본문에서 연 복선 걸기 칸(foreshadow.js)은 그 본문으로
    const n = S.selTool.n;
    const back = e.target.closest && e.target.closest('#sel-tool') && (document.querySelector(`textarea[data-draft="${n}"]`) || document.querySelector(`.read[data-read="${n}"]`));
    hideTool();
    if (back) {
      if (!back.matches('textarea') && !back.hasAttribute('tabindex')) back.setAttribute('tabindex', '-1');
      back.focus({ preventScroll: true });
    }
    return;
  }
  // 도구는 문서 끝에 떠 있어 Tab 으로 닿기 어렵다. 본문 칸에서 Alt+Enter 로 첫 버튼에 간다
  if (e.altKey && e.key === 'Enter' && S.selTool.mode !== 'edit' && e.target.matches && e.target.matches('textarea[data-draft]')) {
    const b = document.querySelector('#sel-tool button');
    if (b) { e.preventDefault(); b.focus(); }
    return;
  }
  if (e.target.id === 'sel-edit' && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    actions.selSave();
  }
});

document.addEventListener('scroll', (e) => {
  const ta = e.target;
  if (ta.matches && ta.matches('textarea[data-draft]')) {
    S.taScroll[ta.dataset.draft] = ta.scrollTop;
    if (S.selTool && S.selTool.mode === 'menu' && !taScrolling) hideTool();  // 고른 곳으로 옮기느라 낸 스크롤은 사람이 굴린 것이 아니다
    else if (S.selTool && S.selTool.mode === 'finding' && String(S.selTool.n) === ta.dataset.draft) placeTool(ta, S.selTool);  // 고치는 창은 문장을 따라간다
  }
}, true);

document.addEventListener('input', (e) => {
  const k = e.target.dataset && e.target.dataset.candEdit;
  if (k !== undefined) S.candEdit[k] = e.target.value;
  if (e.target.matches && e.target.matches('textarea[data-draft]') && S.selTool) hideTool();
});

document.addEventListener('toggle', (e) => {
  if (e.target.matches && e.target.matches('[data-edits-toggle]')) S.editsOpen = e.target.open;
  if (e.target.matches && e.target.matches('[data-ctx-toggle]')) S.ctxOpen = e.target.open;  // 집필 화면 'AI에게 보내는 컨텍스트' 목록
}, true);

/** render() 직후에 부른다: 도구를 닫고, 본문 칸의 스크롤과 방금 고친 자리를 되살린다.
    '직접 수정' 칸과 검수 지적 창은 #app 밖에 있어 다시 그려도 남는다. 그 화 본문 칸이 아직 있으면 쓰던 글째로 자리만 다시 맞춘다
    (showTool 은 칸을 새로 만들어 쓰던 글을 지운다). */
let taScrolling = false;
/** 코드가 본문 칸을 굴린다. 그 스크롤 이벤트가 방금 띄운 도구를 닫지 않게 잠깐 표시해 둔다. */
function scrollTa(ta, top) {
  taScrolling = true;
  ta.scrollTop = top;
  setTimeout(() => { taScrolling = false; }, 150);
}

function syncPassage() {
  const t = S.selTool;
  const keep = t && t.mode !== 'menu' && !t.read && (t.mode !== 'finding' || S.route[2] === 'check') && editableEp(ep(t.n))
    && document.querySelector(`textarea[data-draft="${t.n}"]`);  // 검수 지적 창은 검수 화면에만 남긴다 (집필 화면에도 같은 본문 칸이 있다)
  // 읽기 전용 본문(반영한 화)에서 연 복선 걸기 칸(foreshadow.js)은 그 본문이 남아 있으면 둔다
  const read = t && t.mode === 'foreshadow' && t.read && document.querySelector(`.read[data-read="${t.n}"]`);
  if (!keep && !read) hideTool();
  const ta = document.querySelector('textarea[data-draft]');
  if (!ta) return;
  const n = ta.dataset.draft;
  if (S.taScroll[n]) scrollTa(ta, S.taScroll[n]);
  const f = S.selFocus;
  if (f && String(f.n) === n) {
    S.selFocus = null;
    // 손가락 기기에서 검수 지적을 열 때와 AI가 바로 고친 뒤(f.quiet)에는 본문 칸에 포커스하지 않는다: 키보드가 올라와 화면을 덮고,
    // 포커스가 남은 동안은 다시 그리기를 미룬다(isTyping). 문장 자리만 고르고 옮긴다
    const quiet = ((S.selTool && S.selTool.mode === 'finding') || f.quiet) && typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
    if (!quiet) ta.focus({ preventScroll: true });
    ta.setSelectionRange(f.start, f.end);
    let c = caretXY(ta, f.start);
    if (c.y < c.r.top || c.y > c.r.bottom - c.h) scrollTa(ta, ta.scrollTop + c.y - c.r.top - c.r.height / 3);
    // 본문 칸 자체가 화면 밖이면 페이지도 굴려 고른 문장과 도구가 보이게 한다. 휴대폰 아래 시트가 열려 있으면 시트 위까지만 보이는 자리다
    c = caretXY(ta, f.start);
    const sheet = window.innerWidth <= BP.narrow && document.querySelector('.chat-panel, .tool-col');
    const bottom = sheet ? Math.min(window.innerHeight, sheet.getBoundingClientRect().top) : window.innerHeight;
    const top = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--band')) || 0;  // 900px 이하 위쪽 띠
    if (c.y < top || c.y + c.h * 2 > bottom) window.scrollBy(0, c.y - top - (bottom - top) / 3);
    const s = f.menu && readSel(ta);  // 경고에서 온 것은 다른 화면에서 넘어와 다시 그린 뒤에 도구를 연다
    if (s) {
      S.selTool = { ...s, mode: 'menu' };
      showTool();
    }
  }
  // 남기는 도구는 본문 칸 스크롤을 맞춘 뒤에 자리를 잡는다. 검수 지적 창은 지적 상태가 바뀌었을 수 있어 새로 그린다
  if (keep && S.selTool === t) {
    if (t.mode === 'finding') showTool();
    else placeTool(keep, t);
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

/** 방금 한 수정을 바로 되돌리는 버튼이 붙은 알림. 수정 기록은 본문 아래 접혀 있어 찾기 어렵다. 보통 알림보다 오래 둔다.
    toast 의 동작 알림이라 누르거나 포커스가 있는 동안은 닫히지 않고, 알림 창 '최근 알림'에도 남는다. */
function undoToast(msg, id) {
  toast(msg, false, { actions: [{ label: '되돌리기', run: () => actions.undoEdit(id) }] });
}

/** 경고 w 가 가리킨 문장(q, 본문 at 자리)을 AI에게 고치게 하고 첫 후보를 바로 본문에 넣는다 (POST …/fix-now: 후보 받기와 넣기를 서버가 한 번에).
   다른 후보는 부분 수정 대화에 남는다. 넣은 수정은 알림의 되돌리기나 수정 기록으로 취소한다.
   AI를 기다리는 동안 화면을 잠그지 않는다: 다른 화면으로 가도 되고, 그 화 본문 칸만 잠근다(S.aiFix). 끝나면 알림으로 알린다 */
async function aiFixNow(n, q, at, w) {
  if (S.aiFix) return toast('다른 경고를 AI가 고치는 중이에요. 끝난 뒤에 다시 눌러 주세요', true);
  const name = S.name;
  // 서버는 저장된 본문을 고친다. 저장하지 않은 작품 · 본문이 있으면 먼저 저장한다 (짧은 요청이라 기다림 상자를 쓴다)
  if ((S.dirty || S.textDraft[n] !== undefined) && !(await run('본문 저장하는 중', async () => { await saveIfDirty(); await flushText(n); }, { render: 'success' }))) return;
  S.aiFix = { name, n, w };
  render();
  const gen = S.gen;
  let out;
  try {
    out = await api('POST', `/projects/${enc(name)}/episodes/${n}/fix-now`, { message: warnMsg(w), selection: { start: at, text: q } });
  } catch (e) {
    S.aiFix = null;
    if (S.name === name) render();
    return showError(e, { retry: () => aiFixNow(n, q, at, w) });
  }
  S.aiFix = null;
  if (S.name !== name) return toast(out.edit ? `'${name}' ${n}화 경고 문장을 AI가 고쳤어요. 그 작품의 수정 기록에서 되돌릴 수 있어요` : `'${name}' ${n}화 경고에 AI가 고친 글을 내지 않았어요`, !out.edit);
  const took = takeEdited(out.project, n, gen);
  const here = S.route[2] === 'write' && Number(S.route[3]) === n;
  if (!out.edit) {
    // 본문이 맞다고 본 답(후보 없이 근거만)도 여기로 온다. 집필 화면이면 대화 패널을 열어 답을 보이고, 요청을 더 적어 이어 고칠 수 있게 골라 둔다
    if (here) Object.assign(S, { sel: { n, start: at, text: q }, chatOpen: true, chatScroll: true });
    render();
    return toast(here ? 'AI가 고친 글을 내지 않았어요. 대화 패널에서 답을 보세요' : `AI가 ${n}화 경고 문장을 고친 글을 내지 않았어요. 집필 화면 대화 패널에서 답을 보세요`, true);
  }
  if (!took) {
    render();
    return toast(`AI가 ${n}화 경고 문장을 고쳤지만, 이 화면에 저장하지 않은 ${n}화 변경이 있어 본문을 바꾸지 않았어요. 저장 띠에서 다시 불러오면 보여요`, true);
  }
  const edit = ep(n).edits.find((x) => x.id === out.edit);
  if (edit && here) {
    S.sel = { n, start: edit.start, text: edit.after };  // 이어서 '더 짧게' 같은 요청을 하면 넣은 글을 고친다
    if (focusText(n, edit.after, edit.start) !== -1) S.selFocus.quiet = true;
  }
  render();
  const acts = [{ label: '되돌리기', run: () => actions.undoEdit(out.edit) }];
  if (!(S.route[2] === 'review' && Number(S.route[3]) === n)) acts.push({ label: '상태 승인으로', run: () => { location.hash = `${base()}/review/${n}`; } });
  toast(`AI가 ${n}화 경고 문장을 고쳤어요.`, false, { actions: acts });
}

Object.assign(actions, {
  /** 본문 칸 머리의 '수정 기록 N': 접힌 기록을 펴고 그리로 내려간다. */
  openEdits() {
    S.editsOpen = true;
    render();
    const d = document.querySelector('[data-edits-toggle]');
    if (d) {
      d.open = true;
      d.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      d.querySelector('summary').focus({ preventScroll: true });
    }
  },
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
      undoToast('고쳤어요.', edit.id);
    });
  },
  selAi() {
    const t = S.selTool;
    S.sel = { n: t.n, start: t.start, text: t.text };
    hideTool();
    S.chatOpen = true;
    S.chatScroll = true;
    try { localStorage.setItem('canon.chat', '1'); } catch { /* 저장 못 해도 동작에는 상관없다 */ }
    // 휴대폰에서는 아래 시트가 본문 아래쪽을 덮는다. 고른 글이 시트 위에 보이게 다시 고르고 굴린다 (syncPassage)
    if (focusText(t.n, t.text, t.start) !== -1) S.selFocus.quiet = true;
    if (touchFirst() && isDraftTa(document.activeElement)) document.activeElement.blur();  // 본문 칸 포커스가 남으면 키보드가 오르고 다시 그리기가 밀린다
    render();
    if (!touchFirst()) $('#chat-input')?.focus();  // 손가락 기기는 빠른 요청만 누를 수 있게 키보드를 올리지 않는다
  },
  selShow() {
    const s = curSel();
    if (s && focusText(s.n, s.text, s.start) === -1) return toast('본문에서 찾을 수 없어요. 다시 골라 주세요', true);
    render();
  },
  /** 검수 지적(id)의 문장을 고르고, 검수가 낸 고칠 방향을 대화 입력칸에 넣는다. 보내기는 작가가 한다 */
  issueAsk(id) {
    const n = Number(S.route[3]) || currentEp();
    const x = (ep(n).findings || []).find((f) => f.id === id);
    if (!x) return;
    S.chatDraft = `검수 지적: ${x.description} → ${x.suggestion}`;
    actions.selectIssue(id);
  },
  /** 상태 정리 경고가 가리킨 문장을 집필 화면 본문에서 고르고 부분 수정 도구를 연다. ask 면 경고대로 AI가 바로 고친다 */
  warnPick(arg) {
    const [n, k, ask] = String(arg).split(':');
    const num = Number(n);
    const w = ((S.deltas[num] || {}).warnings || [])[Number(k)];
    const { q, exact } = warnSpot(w, textNow(num));
    if (!q || !textNow(num).includes(q)) return toast('본문에서 그 문장을 찾을 수 없어요', true);
    if (ask && S.aiFix) return toast('다른 경고를 AI가 고치는 중이에요. 끝난 뒤에 다시 눌러 주세요', true);
    const go = () => {
      if (S.route[2] !== 'write' || Number(S.route[3]) !== num) return;
      const at = focusText(num, q, 0);
      if (at === -1) return;
      if (ask) S.selFocus.quiet = true;  // AI가 실패해 이 자리만 남아도 손가락 기기에서 키보드를 올리지 않는다
      if (ask && exact) return aiFixNow(num, q, at, w);
      if (ask) {
        // 비슷한 문장이거나 같은 글이 여러 곳: 바로 넣지 않는다. 문장을 골라 두고 경고를 대화 입력칸에 넣는다. 보내기는 작가가 한다
        Object.assign(S, { sel: { n: num, start: at, text: q }, chatDraft: warnMsg(w), chatOpen: true, chatScroll: true });
        render();
        return toast('경고와 똑같은 문장이 없거나 여러 곳이라, 가장 비슷한 문장을 골랐어요. 맞으면 대화 패널에서 보내세요');
      }
      S.selFocus.menu = true;
      render();
    };
    if (S.route[2] === 'write' && Number(S.route[3]) === num) return go();
    // 상태 승인 화면에서 왔다: 집필 화면을 다 그리고 맨 위로 굴린 뒤에 고른다
    goThen(`${base()}/write/${num}`, go);
  },
  /** 검수 지적(id)의 문장을 본문에서 고르고 부분 수정 도구를 띄운다 (검수 화면 check.js) */
  selectIssue(id) {
    const n = Number(S.route[3]) || currentEp();
    const x = (ep(n).findings || []).find((f) => f.id === id);
    if (!x) return;
    if (S.chkSel) S.chkSel[n] = id;
    if (!x.current_quote || focusText(n, x.current_quote.trim(), 0) === -1) { render(); return toast('본문에서 그 문장을 찾을 수 없어요', true); }
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
      if (focusText(n, edit.after, edit.start) !== -1) S.selFocus.quiet = true;  // 넣은 글을 시트 위로 굴려 보인다. 손가락 기기는 키보드를 올리지 않는다
      undoToast(`${k + 1}번 후보를 넣었어요.`, edit.id);
    });
  },
  async undoEdit(id) {
    const n = Number(S.route[3]) || currentEp();
    const edit = (ep(n) && ep(n).edits || []).find((x) => x.id === id);
    if (!edit) return toast('그 수정이 있는 화의 집필 화면에서 되돌리세요', true);  // 알림의 '되돌리기'를 다른 화면에서 누를 때
    // 칸의 초안이 서버 본문을 가린다. 먼저 저장해야 취소한 결과가 화면에 보이고, 나중에 초안을 저장해도 되살아나지 않는다
    if ((textUnsaved(n) || S.dirty) && !(await askConfirm(`${textUnsaved(n) ? '저장하지 않은 본문 수정이 있어요. 먼저 저장하고' : '저장하지 않은 다른 변경도 함께 저장하고'} 이 수정을 취소할까요?`, { ok: '수정 취소', cancel: '닫기' }))) return;
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
    if (textUnsaved(n) && !(await askConfirm('저장하지 않은 본문 수정이 있어요. 먼저 저장하고 이 수정을 다시 넣을까요?', { ok: '다시 넣기' }))) return;
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
