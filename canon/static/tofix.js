/* 고칠 곳 (서버 tofix.py). app.js 의 S, actions, api, render, header, esc, ep, P, base, toast, autoOn, fmtDateTime 과
   passage.js 의 showTool · placeTool · hideTool · toolEl · textNow · flushText · clip, marks.js 의 allRanges 를 쓴다.
   본문에서 글을 고르면 뜨는 도구에 '나중에 고치기'를 붙이고, 메모를 적어 담는다. 본문을 바꾸지 않아 자동 집필이 도는 동안에도 담는다.
   남은 표시는 본문에 점선 밑줄로 보이고(marks.js allRanges), 누르면 같은 도구가 떠서 바로 고치거나 고침으로 바꾼다.
   '고칠 곳' 화면(주소 tofix)은 모든 화의 표시를 모아 본다. 서버 응답에서는 화마다 to_fix 만 가져와, 화면에서 고치던 다른 칸은 그대로 둔다.
   tofixSpot · tofixRanges · tofixList · tofixAt 은 DOM 없는 순수 함수 (tests/test_tofix_js.py). */
'use strict';

Object.assign(S, {
  tofixFilter: 'open',  // 고칠 곳 화면 거르기: open | done | all
  tofixIdx: {},         // 화별 '고칠 곳' 버튼으로 마지막에 고른 순서
  tofixEdit: null,      // 고칠 곳 화면에서 메모를 고치는 줄 { name, key: '화:id', note }
});

const TOFIX_STATUS = { open: '남음', done: '고침' };  // tofix.STATUS 와 같다
const TOFIX_NOTE_MAX = 500;  // tofix.MAX_NOTE

/** 본문에서 quote 가 있는 자리 {a, b} (start 에 가장 가까운 것). 없으면 null. tofix.spot 과 같은 규칙. */
function tofixSpot(text, quote, start = 0) {
  const q = (quote || '').trim();
  if (!q) return null;
  let best = -1;
  for (let i = text.indexOf(q); i !== -1; i = text.indexOf(q, i + 1)) {
    if (best === -1 || Math.abs(i - start) < Math.abs(best - start)) best = i;
  }
  return best === -1 ? null : { a: best, b: best + q.length };
}

/** 본문 밑줄 칠 곳: 남은 표시만. marks.js allRanges 가 문체 · 검수 밑줄과 함께 그린다. */
function tofixRanges(e, text) {
  const out = [];
  for (const m of (e && e.to_fix) || []) {
    if (m.status !== 'open') continue;
    const s = tofixSpot(text, m.quote, m.start);
    if (s) out.push({ a: s.a, b: s.b, kind: 'tofix', key: `t:${m.id}`, title: `고칠 곳 · ${m.note || '메모 없음'}` });
  }
  return out.sort((x, y) => x.a - y.a);
}

/** 화를 가로질러 모은 표시 (tofix.collect 와 같은 순서). status 는 open · done · all. found 는 지금 본문에서 찾았는지. */
function tofixList(episodes, status) {
  const out = [];
  [...episodes].sort((x, y) => x.plot.number - y.plot.number).forEach((e) => {
    (e.to_fix || []).forEach((m) => {
      if (status !== 'all' && m.status !== status) return;
      out.push({ n: e.plot.number, title: e.plot.title, m, found: !!tofixSpot(e.text || '', m.quote, m.start) });
    });
  });
  return out;
}

/** 본문 text 의 start 에서 len 글자를 덮는 남은 표시. 없으면 null. */
function tofixAt(e, text, start, len) {
  return ((e && e.to_fix) || []).find((m) => {
    if (m.status !== 'open') return false;
    const s = tofixSpot(text, m.quote, m.start);
    return s && s.a === start && s.b === start + len;
  }) || null;
}

const tofixOpen = (e) => ((e && e.to_fix) || []).filter((m) => m.status === 'open');

/** 서버가 돌려준 작품에서 화마다 to_fix 만 가져온다. */
function takeToFix(pj) {
  pj.episodes.forEach((src) => {
    const e = ep(src.plot.number);
    if (e) e.to_fix = src.to_fix || [];
  });
}

async function tofixCall(method, n, path, body, done) {
  try {
    takeToFix(await api(method, `/projects/${enc(S.name)}/episodes/${n}/tofix${path}`, body));
    if (done) toast(done);
    render();
    return true;
  } catch (err) {
    toast(err.message, true);
    return false;
  }
}

// ----- 집필 화면 -----

/** 본문 띠의 '고칠 곳 N' 버튼: 누를 때마다 이 화의 다음 남은 표시를 골라 도구를 띄운다. 남은 것이 없으면 빈 글. */
function tofixBtn(n) {
  const k = tofixOpen(ep(n)).length;
  return k ? `<button type="button" class="btn small" data-action="tofixNext" data-arg="${n}" title="남은 고칠 곳을 차례로 골라요" aria-label="고칠 곳 ${k}개"><span class="lbl-l">고칠 곳</span><span class="lbl-s">고칠</span> ${k}</button>` : '';
}

/** 메모 칸 도구 (mode 'tofix'). 새로 담을 때는 id 가 없다. */
function tofixPanel() {
  const t = S.selTool;
  const ta = document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta) return hideTool();
  if (typeof mentionClose === 'function') mentionClose();
  const m = t.id ? (ep(t.n).to_fix || []).find((x) => x.id === t.id) : null;
  const el = toolEl();
  el.classList.add('edit');
  el.classList.remove('finding');
  el.setAttribute('aria-label', '나중에 고칠 곳');
  el.innerHTML = `<label class="small" for="tofix-note">${m ? '고칠 곳 메모' : `나중에 고칠 곳으로 담기 · ${t.text.length.toLocaleString()}자`}</label>
    <blockquote class="tofix-q">${esc(clip(t.text, 120))}</blockquote>
    <textarea id="tofix-note" rows="2" maxlength="${TOFIX_NOTE_MAX}" placeholder="무엇이 어색한지 적어 두세요 (비워도 돼요)">${esc(m ? m.note : '')}</textarea>
    <div class="between"><span class="small">${matchMedia('(pointer: coarse)').matches ? '' : 'Ctrl+Enter 저장 · Esc 닫기'}</span><span class="row" style="gap:6px"><button type="button" class="btn small" data-action="selCancel">취소</button><button type="button" class="btn small primary" data-action="tofixSave">${m ? '저장' : '담기'}</button></span></div>`;
  el.hidden = false;
  placeTool(ta, t);
  $('#tofix-note').focus();
}

// 고치는 본문 칸의 떠 있는 도구(passage.js)에 '나중에 고치기'. 고른 글이 남은 표시와 같으면 메모 고치기 · 고침으로
const tofixShowTool = showTool;
showTool = function showToolWithToFix() {
  const t = S.selTool;
  if (t && t.mode === 'tofix') return tofixPanel();
  const m = t && t.mode === 'menu' ? tofixAt(ep(t.n), textNow(t.n), t.start, t.text.length) : null;
  if (m && !t.hint) t.hint = `고칠 곳 · ${clip(m.note || '메모 없음', 40)}`;
  tofixShowTool();
  const el = document.getElementById('sel-tool');
  const ta = t && document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta || !el || el.hidden || t.mode !== 'menu') return;
  el.insertAdjacentHTML('beforeend', m
    ? `<button type="button" class="btn small" data-action="tofixEdit" data-arg="${esc(m.id)}">메모 고치기</button><button type="button" class="btn small" data-action="tofixDone" data-arg="${t.n}:${esc(m.id)}">고침으로 표시</button>`
    : '<button type="button" class="btn small" data-action="tofixNew" title="이 글을 나중에 고칠 곳으로 담아요. 본문은 바꾸지 않아 자동 집필 중에도 돼요">나중에 고치기</button>');
  placeTool(ta, t);
};

document.addEventListener('keydown', (e) => {
  if (e.target.id === 'tofix-note' && e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) {
    e.preventDefault();
    actions.tofixSave();
  }
});

// 고칠 곳 화면의 메모 칸: Ctrl+Enter 저장, Esc 취소
document.addEventListener('keydown', (e) => {
  const k = e.target.dataset && e.target.dataset.tofixNote;
  if (k === undefined || e.isComposing) return;
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    actions.tofixNoteSave(k);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    actions.tofixNoteCancel(k);
  }
});

// ----- 고칠 곳 화면 (화별 목차 + 카드 한 열, outline.js) -----

/** 고른 글 앞뒤 문맥: { pre, q, post }. 앞뒤로 span 글자까지, 줄바꿈에서 끊고 잘렸으면 … 을 붙인다 */
function tofixContext(text, a, b, span = 60) {
  const cut = (x, back) => {
    const nl = back ? x.lastIndexOf('\n') : x.indexOf('\n');
    if (nl !== -1) return back ? x.slice(nl + 1) : x.slice(0, nl);
    return back ? (a - span > 0 ? `…${x}` : x) : (b + span < text.length ? `${x}…` : x);
  };
  return { pre: cut(text.slice(Math.max(0, a - span), a), true), q: text.slice(a, b), post: cut(text.slice(b, b + span), false) };
}

const tofixKey = (n, m) => `${n}:${m.id}`;
const tofixEditing = (k) => S.tofixEdit && S.tofixEdit.name === S.name && S.tofixEdit.key === k;

function tofixItem(x) {
  const { n, m, found } = x;
  const arg = `${n}:${esc(m.id)}`;
  const btn = (action, label, cls = '') => `<button type="button" class="btn small${cls}" data-action="${action}" data-arg="${arg}">${label}</button>`;
  const open = m.status === 'open';
  const text = (ep(n) && ep(n).text) || '';
  const s = found ? tofixSpot(text, m.quote, m.start) : null;
  const c = s ? tofixContext(text, s.a, s.b) : null;
  const quote = c
    ? `<p class="tofix-ctx"><span class="ctx">${esc(c.pre)}</span><mark>${esc(c.q)}</mark><span class="ctx">${esc(c.post)}</span></p>`
    : `<p class="tofix-ctx lost">${esc(clip(m.quote, 240))}</p>`;
  const lost = !found && open ? '<div class="row tofix-lost"><span class="chip warn">본문에서 못 찾음</span><span class="small">본문에서 이 글을 찾지 못했어요. 이미 고쳤으면 고침으로 표시해요.</span></div>' : '';
  const k = tofixKey(n, m);
  const note = tofixEditing(k)
    ? `<div class="field"><label for="tofix-n-${arg}">메모 · 고치는 중</label><textarea id="tofix-n-${arg}" rows="2" maxlength="${TOFIX_NOTE_MAX}" data-tofix-note="${arg}" placeholder="무엇이 어색한지 적어 두세요">${esc(S.tofixEdit.note ?? m.note)}</textarea></div>
      <div class="between"><span class="small">${matchMedia('(pointer: coarse)').matches ? '' : 'Ctrl+Enter 저장 · Esc 취소'}</span><span class="row">${btn('tofixNoteCancel', '취소')}${btn('tofixNoteSave', '메모 저장')}</span></div>`
    : `<div class="tofix-note${m.note ? '' : ' none'}">${m.note ? esc(m.note) : '메모 없음'}</div>`;
  const more = menuBtn(`tf-${k}`, '⋯', () => `${open ? `<button type="button" class="pop-item" data-action="tofixNoteEdit" data-arg="${arg}">메모 고치기</button>` : ''}<button type="button" class="pop-item danger" data-action="tofixDelete" data-arg="${arg}">지우기</button>`, { cls: 'btn small ghost', aria: '이 고칠 곳 더 보기' });
  const acts = open
    ? `${found ? `<button type="button" class="btn small" data-action="tofixGo" data-arg="${arg}">본문에서 고치기</button>` : ''}${btn('tofixDone', '고침으로 표시')}`
    : btn('tofixReopen', '다시 남음으로');
  return `<li class="tofix-item${open ? '' : ' done'}${tofixEditing(k) ? ' editing' : ''}">
    ${lost}${quote}${note}
    ${tofixEditing(k) ? '' : `<div class="between"><span class="small">${open ? `${fmtDateTime(m.at)} 담음` : `${fmtDateTime(m.done_at || m.at)} 고침`}</span><span class="row">${acts}${more}</span></div>`}
  </li>`;
}

/** 화별 묶음 [{ n, title, items, lost }] */
function tofixGroups(rows) {
  const groups = [];
  rows.forEach((x) => {
    if (!groups.length || groups[groups.length - 1].n !== x.n) groups.push({ n: x.n, title: x.title, items: [], lost: 0 });
    const g = groups[groups.length - 1];
    g.items.push(x);
    if (!x.found && x.m.status === 'open') g.lost += 1;
  });
  return groups;
}

let tofixTocGroups = [];  // 마지막으로 그린 목차 묶음 (스크롤 때 목차만 다시 그린다)
let tofixTocCur = null;

function tofixToc(groups = tofixTocGroups) {
  tofixTocGroups = groups;
  const cur = groups.find((g) => g.n === tofixTocCur) || groups[0];
  const names = { open: '남은 고칠 곳', done: '고친 곳', all: '모든 고칠 곳' };
  const body = `<span class="outline-h">${names[S.tofixFilter]} · ${groups.length}화</span>${groups.map((g) => `<button type="button" class="outline-item${g.lost ? ' warn' : ''}" data-action="tofixEp" data-arg="${g.n}"${g === cur ? ' aria-current="true"' : ''}><span class="tl">${g.n}화 ${esc(g.title)}</span><span class="st${g.lost ? ' warn' : ''}">${g.lost ? `못 찾음 ${g.lost}` : g.items.length}</span></button>`).join('')}
    <div class="outline-sep"></div><p class="outline-note small">집필 화면 본문 띠의 '고칠 곳 N'으로도 차례로 옮겨 다녀요.</p>`;
  return outlineNav({ id: 'tf-toc', label: '화별 고칠 곳', now: cur ? `${cur.n}화 ${esc(cur.title)} <span class="small">${cur.items.length}</span>` : '', body });
}

outlineSpy('tf-toc', {
  targets: () => tofixTocGroups.map((g) => [g.n, document.getElementById(`tf-ep-${g.n}`)]),
  set(cur) {
    if (cur === tofixTocCur) return;
    tofixTocCur = cur;
    outlineRefresh('tf-toc', tofixToc());
  },
});

/** 빈 화면에서 갈 집필 화면: 본문이 있는 마지막 화, 없으면 첫 화 */
function tofixWriteHref() {
  const eps = P().episodes;
  const withText = eps.filter((e) => e.text).map((e) => e.plot.number);
  const n = withText.length ? Math.max(...withText) : Math.min(...eps.map((e) => e.plot.number));
  return { n, href: `${base()}/write/${n}` };
}

function viewToFix() {
  const eps = P().episodes;
  const all = tofixList(eps, 'all');
  const count = { open: all.filter((x) => x.m.status === 'open').length, done: all.filter((x) => x.m.status === 'done').length, all: all.length };
  const seg = all.length ? `<div class="seg" role="group" aria-label="고칠 곳 거르기">${[['open', '남음'], ['done', '고침'], ['all', '모두']].map(([k, l]) => `<button type="button" aria-pressed="${S.tofixFilter === k}" data-action="tofixFilter" data-arg="${k}">${l} ${count[k]}</button>`).join('')}</div>` : '';
  const head = header('작품 도구', '고칠 곳', '집필 화면에서 글을 골라 \'나중에 고치기\'로 담은 곳이에요. 본문은 그대로 두고, AI에게는 보내지 않아요.', seg);
  if (!eps.length) return head + noEpisode();
  const rows = all.filter((x) => S.tofixFilter === 'all' || x.m.status === S.tofixFilter);
  if (!rows.length) {
    if (!all.length) {
      const w = tofixWriteHref();
      return `${head}<div class="card empty"><p>아직 담은 곳이 없어요. 집필 화면에서 어색한 글을 드래그해 고른 뒤 '나중에 고치기'를 누르면 여기 모여요.</p><div><a class="btn primary" href="${w.href}">${w.n}화 집필 화면으로</a></div></div>`;
    }
    return S.tofixFilter === 'open'
      ? `${head}<div class="card empty"><p>남은 고칠 곳이 없어요. 담은 ${count.done}곳을 모두 고쳤어요.</p><div><button type="button" class="btn primary" data-action="tofixFilter" data-arg="done">고친 곳 보기</button></div></div>`
      : `${head}<div class="card empty"><p>아직 고친 곳이 없어요.</p><div><button type="button" class="btn primary" data-action="tofixFilter" data-arg="open">남은 곳 보기</button></div></div>`;
  }
  const groups = tofixGroups(rows);
  if (!groups.some((g) => g.n === tofixTocCur)) tofixTocCur = null;
  const main = `<div class="tofix-col">${groups.map((g) => `<section class="card" id="tf-ep-${g.n}" aria-labelledby="tf-h-${g.n}">
      <div class="between"><h2 id="tf-h-${g.n}" tabindex="-1">${g.n}화 ${esc(g.title)}</h2><a class="btn small ghost" href="${base()}/write/${g.n}">${g.n}화 집필 화면</a></div>
      <ol class="tofix-list">${g.items.map(tofixItem).join('')}</ol></section>`).join('')}</div>`;
  return `${head}${outlineDoc(tofixToc(groups), main, { cls: 'tofix-wrap' })}`;
}

/** n 화 표시 m 의 글을 집필 화면 본문 칸에서 고르고 도구를 띄운다 (passage.js syncPassage 가 다시 그린 뒤 연다). */
function tofixFocus(n, m) {
  const s = tofixSpot(textNow(n), m.quote, m.start);
  if (!s) {
    toast('본문에서 이 글을 찾지 못했어요. 이미 고쳤으면 고침으로 표시해요', true);
    return false;
  }
  S.selFocus = { n, start: s.a, end: s.b, menu: true };
  return true;
}

const tofixArg = (arg) => {
  const [n, id] = String(arg).split(':');
  return { n: Number(n), id };
};

Object.assign(actions, {
  tofixNew() {
    S.selTool = { ...S.selTool, mode: 'tofix', id: '', hint: '' };
    showTool();
  },
  tofixEdit(id) {
    S.selTool = { ...S.selTool, mode: 'tofix', id };
    showTool();
  },
  async tofixSave() {
    const t = S.selTool;
    if (!t || t.mode !== 'tofix') return;
    const note = ($('#tofix-note').value || '').trim();
    if (t.id) {
      if (await tofixCall('PUT', t.n, `/${enc(t.id)}`, { note }, '메모를 저장했어요')) hideTool();
      return;
    }
    // 저장된 본문에 없는 글(저장하지 않은 고친 글)은 먼저 저장한다. 자동 집필 중에는 본문을 저장할 수 없다
    if (!(ep(t.n).text || '').includes(t.text)) {
      if (autoOn()) return toast('저장하지 않은 본문의 글이에요. 자동 집필이 도는 동안은 저장된 본문의 글만 담을 수 있어요', true);
      try {
        await flushText(t.n);
      } catch (err) {
        return toast(err.message, true);
      }
    }
    if (await tofixCall('POST', t.n, '', { quote: t.text, note, start: t.start }, '고칠 곳에 담았어요')) hideTool();
  },
  tofixDone(arg) {
    const { n, id } = tofixArg(arg);
    if (S.selTool) hideTool();
    tofixCall('PUT', n, `/${enc(id)}`, { status: 'done' }, '고침으로 표시했어요');
  },
  tofixReopen(arg) {
    const { n, id } = tofixArg(arg);
    tofixCall('PUT', n, `/${enc(id)}`, { status: 'open' }, '다시 남음으로 바꿨어요');
  },
  tofixDelete(arg) {
    const { n, id } = tofixArg(arg);
    const m = (ep(n).to_fix || []).find((x) => x.id === id);
    if (m && m.note && !confirm('메모가 있는 고칠 곳이에요. 지울까요?')) return;
    tofixCall('DELETE', n, `/${enc(id)}`, undefined, '지웠어요');
  },
  tofixFilter(k) {
    S.tofixFilter = k;
    tofixTocCur = null;
    render();
  },
  /** 목차 줄: 그 화 카드로 옮기고 제목에 포커스 */
  tofixEp(n) {
    const el = document.getElementById(`tf-ep-${n}`);
    if (!el) return;
    tofixTocCur = Number(n);
    outlineRefresh('tf-toc', tofixToc());
    el.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    document.getElementById(`tf-h-${n}`)?.focus({ preventScroll: true });
  },
  /** 고칠 곳 화면: 그 줄만 메모 칸을 편다 (Card 읽기 먼저) */
  tofixNoteEdit(arg) {
    S.tofixEdit = { name: S.name, key: String(arg), note: null };
    S.focusTarget = `[data-tofix-note="${CSS.escape(String(arg))}"]`;
    render();
  },
  tofixNoteCancel(arg) {
    S.tofixEdit = null;
    S.focusTarget = `[data-action="menuToggle"][data-arg="tf-${CSS.escape(String(arg))}"]`;
    render();
  },
  async tofixNoteSave(arg) {
    const { n, id } = tofixArg(arg);
    const el = document.querySelector(`[data-tofix-note="${CSS.escape(String(arg))}"]`);
    const note = el ? el.value.trim() : '';
    if (S.tofixEdit) S.tofixEdit.note = el ? el.value : null;  // 저장이 실패하면 고치던 글을 남긴다
    if (!(await tofixCall('PUT', n, `/${enc(id)}`, { note }, '메모를 저장했어요'))) return;
    S.tofixEdit = null;
    S.focusTarget = `[data-action="menuToggle"][data-arg="tf-${CSS.escape(String(arg))}"]`;
    render();
  },
  /** 고칠 곳 화면에서: 그 화 집필 화면으로 가서 글을 고른다. */
  tofixGo(arg) {
    const { n, id } = tofixArg(arg);
    const m = (ep(n).to_fix || []).find((x) => x.id === id);
    if (!m || !tofixFocus(n, m)) return;
    location.hash = `${base()}/write/${n}`;
  },
  /** 집필 화면 '고칠 곳 N': 이 화의 다음 남은 표시를 본문 순서대로 고른다. */
  tofixNext(n) {
    n = Number(n);
    const text = textNow(n);
    const list = tofixRanges(ep(n), text);
    if (!list.length) return toast('본문에서 남은 고칠 곳을 찾지 못했어요. 고칠 곳 화면에서 확인하세요', true);
    const i = ((S.tofixIdx[n] ?? -1) + 1) % list.length;
    S.tofixIdx[n] = i;
    S.selFocus = { n, start: list[i].a, end: list[i].b, menu: true };
    render();
  },
});
