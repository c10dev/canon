/* 본문 속 이름: 집필 화면 본문에서 인물 · 장소 이름을 찾아 옅은 밑줄을 긋고, 누르면 작은 카드를 띄운다.
   app.js 의 S, P, actions, api, base, enc, esc, charName, passage.js 의 caretXY · editableEp · textNow,
   cast.js 의 castStateOf · castPresent · tieOf · pairOf · tieText · tensionText · SHEET_STATE · TIER_NAME 을 그대로 쓴다.
   밑줄은 marks.js 가 문체 밑줄과 함께 그린다(markHtml). 이름은 정규식 하나로 찾고, 글자를 치는 동안은 앞서 찾은 자리를 옮겨 쓰다가 잠시 멈추면 다시 찾는다.
   찾는 이름: 인물 이름(Character 에 별칭 칸이 없어 이름만), 인과율 '장소' 요소의 이름 · 다른 이름, 설정 장소 칸(atlas.places 와 같은 키).
   카드의 인물 상태와 관계는 서버 /cast 의 화별 프레임에서 '이 화 시작 시점'(이 화보다 앞에 반영한 마지막 화)을 골라 읽는다. 새로 계산하지 않는다.
   받은 프레임은 S.mnCast 에 따로 둔다 (S.cast 에 두면 인물 화면이 주소의 시점을 새로 받은 것으로 보지 않는다). */
'use strict';

let mentionsOn = true;  // 이름 표시 (브라우저에 기억)
try { mentionsOn = localStorage.getItem('canon.mentions') !== '0'; } catch { /* 저장 못 해도 켜 둔다 */ }

// 이름 뒤에 붙어도 이름으로 보는 말. 호칭(씨 · 님 · 이) + 조사 + 보조사 순서로 하나씩, 그 뒤는 글자가 아니어야 한다.
// 여기 없는 글자가 이어지면(서윤호, 등대지기) 더 긴 다른 단어로 보고 밑줄을 긋지 않는다
const MN_TITLES = ['씨', '님', '이'];
const MN_JOSA = ['이', '가', '은', '는', '을', '를', '의', '에', '에게', '에게서', '한테', '한테서', '께', '께서', '와', '과', '랑', '이랑', '하고',
  '도', '만', '까지', '부터', '보다', '처럼', '같이', '로', '으로', '로서', '으로서', '로써', '으로써', '에서', '아', '야', '여', '이여',
  '나', '이나', '며', '이며', '든', '이든', '란', '이란', '라', '이라', '라고', '이라고', '라는', '이라는', '라면', '이라면', '야말로', '이야말로',
  '마저', '조차', '밖에', '뿐', '쯤', '다', '이다', '였다', '이었다', '예요', '이에요', '였던', '이었던', '던', '이던', '지만', '이지만', '고', '이고',
  '요', '이요', '야', '이야', '에겐', '한텐', '들', '네'];
const MN_FOCUS = ['은', '는', '도', '만', '요', '가', '를', '을', '의', '에', '들', '이'];
const MN_MIN = 2;  // 한 글자 이름(성, 숲)은 낱말 속에 너무 자주 나와 찾지 않는다

const mnAlt = (list) => [...new Set(list)].sort((a, b) => b.length - a.length).map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
const MN_TAIL = `(?:${mnAlt(MN_TITLES)})?(?:${mnAlt(MN_JOSA)})?(?:${mnAlt(MN_FOCUS)})?(?![\\p{L}\\p{N}])`;

/** naming.place_base: 설정 장소 칸의 '등대: 설명' 이면 '등대'. */
const mnPlaceBase = (x) => String(x || '').split(/[:(（\-–—,]/)[0].trim();
/** naming.place_key: 띄어쓰기와 가운뎃점, 따옴표를 뺀 비교용 이름. */
const mnPlaceKey = (x) => String(x || '').replace(/[\s·・\-_'"“”‘’]+/g, '');

/** atlas.places 와 같은 장소 목록 (키 · 이름 · 다른 이름 · 설명). 인과율 장소 요소 먼저, 그다음 요소와 겹치지 않는 설정 장소 칸. */
function mentionPlaces(p = P()) {
  const out = [];
  const seen = new Set();
  (p.elements || []).forEach((el) => {
    if (el.kind !== '장소' || !(el.name || '').trim()) return;
    const aliases = (el.aliases || []).filter((a) => a.trim());
    [el.name, ...aliases].forEach((t) => seen.add(mnPlaceKey(t)));
    out.push({ key: el.id, name: el.name.trim(), aliases, description: el.description || '', source: '인과율 장소' });
  });
  ((p.world || {}).locations || []).forEach((raw) => {
    const name = mnPlaceBase(raw);
    const k = mnPlaceKey(name);
    if (!k || seen.has(k)) return;
    seen.add(k);
    const description = String(raw).trim().slice(name.length).trim().replace(/^[:：\-–—,]+/, '').trim();
    out.push({ key: `w:${name}`, name, aliases: [], description, source: '설정 장소' });
  });
  return out;
}

/** 본문에서 찾을 이름. 같은 글자는 앞의 것(인물 → 장소)만 쓴다. id 는 'c:<인물 id>' · 'p:<장소 키>'. */
function mentionTerms(p = P()) {
  const out = [];
  const have = new Set();
  const add = (term, kind, id, name) => {
    const t = String(term || '').trim();
    if ([...t].length < MN_MIN || have.has(t)) return;
    have.add(t);
    out.push({ term: t, kind, id, name });
  };
  (p.characters || []).forEach((c) => add(c.name, 'person', `c:${c.id}`, c.name));
  mentionPlaces(p).forEach((pl) => [pl.name, ...pl.aliases].forEach((t) => add(t, 'place', `p:${pl.key}`, pl.name)));
  return out;
}

let mnIndex = { sig: null, re: null, by: new Map() };

/** 이름 전체를 긴 것부터 묶은 정규식 하나. 이름이 그대로면 다시 만들지 않는다. */
function mentionIndex() {
  const terms = mentionTerms();
  const sig = terms.map((t) => `${t.id}\u0001${t.term}`).join('\u0002');
  if (sig !== mnIndex.sig) {
    mnIndex = {
      sig,
      re: terms.length ? new RegExp(`(?<![\\p{L}\\p{N}])(${mnAlt(terms.map((t) => t.term))})(?=${MN_TAIL})`, 'gu') : null,
      by: new Map(terms.map((t) => [t.term, t])),
    };
  }
  return mnIndex;
}

/** 본문에서 이름이 나온 곳 [{a, b, kind, id, name}]. 글 순서, 겹치지 않는다. 밑줄은 이름만 (조사는 뺀다). */
function mentionRanges(text) {
  const { re, by } = mentionIndex();
  if (!re || !text) return [];
  const out = [];
  re.lastIndex = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    const t = by.get(m[1]);
    out.push({ a: m.index, b: m.index + m[1].length, kind: t.kind, id: t.id, name: t.name });
  }
  return out;
}

/** 글을 고친 뒤 앞서 찾은 자리를 옮긴다. 고친 곳에 닿은 이름은 다시 찾을 때까지 뺀다 (앞뒤 글자가 바뀌면 이름인지가 바뀐다). */
function mentionShift(old, ranges, now) {
  const max = Math.min(old.length, now.length);
  let p = 0;
  while (p < max && old[p] === now[p]) p++;
  let s = 0;
  while (s < max - p && old[old.length - 1 - s] === now[now.length - 1 - s]) s++;
  const end = old.length - s;
  const d = now.length - old.length;
  return ranges.filter((r) => r.b < p || r.a > end).map((r) => (r.a > end ? { ...r, a: r.a + d, b: r.b + d } : r));
}

let mnLast = { sig: null, text: null, ranges: [] };

/** marks.js 가 밑줄을 그릴 때 부른다. quick 이면 (글자를 치는 중) 앞서 찾은 자리를 옮겨 쓴다. 꺼 두었으면 []. */
function mentionsFor(text, quick = false) {
  if (!mentionsOn || !text) return [];
  const { sig } = mentionIndex();
  if (mnLast.sig === sig && mnLast.text === text) return mnLast.ranges;
  if (quick && mnLast.sig === sig && mnLast.text !== null) return mentionShift(mnLast.text, mnLast.ranges, text);
  mnLast = { sig, text, ranges: mentionRanges(text) };
  return mnLast.ranges;
}

/** 찾을 이름이 있는지 (본문 칸 뒤 밑줄 칸을 깔지). */
const mentionLive = () => mentionsOn && mentionIndex().re !== null;

// ----- 집필 화면 왼쪽: 이름 표시 켜기 · 끄기, 이번 화에 나온 이름 -----

/** 이번 화 본문에 나온 이름 목록. 누르면 카드가 뜬다 (키보드로 카드를 여는 길). */
function mentionBox(n) {
  if (mentionIndex().re === null) return '';
  const toggle = `<button type="button" class="btn small" data-action="mentionsToggle" aria-pressed="${mentionsOn}" title="본문 속 인물 · 장소 이름 밑줄 켜고 끄기">이름 표시 ${mentionsOn ? '끄기' : '켜기'}</button>`;
  let body = '<div class="small">켜면 본문에 나온 인물 · 장소 이름에 밑줄을 긋고, 누르면 이 화 시작 때 상태를 보여 줘요.</div>';
  if (mentionsOn) {
    const count = new Map();
    mentionsFor(textNow(n)).forEach((r) => {
      const x = count.get(r.id) || { r, k: 0 };
      x.k++;
      count.set(r.id, x);
    });
    const list = [...count.values()].sort((x, y) => (x.r.kind === y.r.kind ? y.k - x.k : x.r.kind === 'person' ? -1 : 1));
    body = list.length
      ? `<div class="mn-list">${list.map(({ r, k }) => `<button type="button" class="btn small mn-pick ${r.kind}" data-action="mentionPick" data-arg="${esc(r.id)}" aria-haspopup="dialog">${esc(r.name)} <span class="small">${k}</span></button>`).join('')}</div>
        <div class="small">본문의 이름을 누르거나, 본문 칸에서 이름에 커서를 두고 Alt+Enter를 눌러도 떠요.</div>`
      : '<div class="small">이번 화 본문에 나온 인물 · 장소 이름이 없어요.</div>';
  }
  return `<div class="field" id="name-marks"><div class="between"><span class="small">본문 속 이름</span>${toggle}</div>${body}</div>`;
}

// ----- 카드 -----

S.mnCast = null;  // 카드용 /cast 프레임 { name, src: 받을 때의 S.project, frames | error }
let mnOpen = null;  // 떠 있는 카드 { id, n, anchor: { ta, a } | { sel }, back: 닫으면 포커스를 돌려줄 곳 }
let mnCastBusy = null;

function mnCardEl() {
  let el = document.getElementById('mn-card');
  if (!el) {
    el = document.createElement('div');
    el.id = 'mn-card';
    el.className = 'mn-card';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-labelledby', 'mn-title');
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

/** n 화 시작 시점의 프레임: n 화보다 앞에 반영한 마지막 화 (0 은 1화 시작 전). [프레임, 번호] */
function mentionFrame(n) {
  const fs = (S.mnCast && S.mnCast.frames) || [];
  let i = -1;
  fs.forEach((f, k) => { if (f.episode < n) i = k; });
  return i < 0 ? [null, -1] : [fs[i], i];
}

/** /cast 를 지금 작품으로 받아 둔다. 작품이 바뀌었으면 (반영 · 저장으로 S.project 가 새로 오면) 다시 받는다. */
const mnCastFresh = () => !!S.mnCast && S.mnCast.name === S.name && S.mnCast.src === S.project;

async function mnCastEnsure() {
  if (mnCastFresh()) return;
  if (!mnCastBusy) {
    const name = S.name;
    const src = S.project;
    mnCastBusy = api('GET', `/projects/${enc(name)}/cast`)
      .then((r) => ({ name, src, frames: r.frames || [] }), (e) => ({ name, src, error: e.message, frames: [] }))
      .then((c) => { if (S.name === name) S.mnCast = c; })
      .finally(() => { mnCastBusy = null; });
  }
  await mnCastBusy;
}

function mnPersonCard(c, n) {
  const c0 = S.mnCast && S.mnCast.name === S.name ? S.mnCast : null;  // 새로 받는 동안은 앞서 받은 것을 보인다
  const ready = c0 && !c0.error;
  const head = `<div class="between"><strong id="mn-title">${esc(c.name || c.id)}</strong><button type="button" class="btn small" data-action="mentionClose">닫기</button></div>
    <div class="small">${[TIER_NAME[c.tier || 'main'], c.role].filter(Boolean).map(esc).join(' · ')}</div>`;
  if (!ready) return `${head}<div class="small" role="status">${c0 && c0.error && mnCastFresh() ? `상태를 불러오지 못했어요: ${esc(c0.error)}` : '이 화 시작 때 상태를 불러오는 중이에요…'}</div>`;
  const [f, fi] = mentionFrame(n);
  const when = `${n}화 시작 시점 · ${f && f.episode ? `${f.episode}화까지 반영한 상태` : '1화 시작 전 설정'}`;
  const link = `<a class="btn small" href="${base()}/cast/c:${enc(c.id)}?tab=sheet${fi >= 0 ? `&f=${fi}` : ''}">인물 · 관계도에서 보기</a>`;
  if (!castPresent(c, f)) {
    return `${head}<div class="small">${esc(when)}</div><div class="note plain">${c.first_ep === n ? '이번 화에 처음 나오는 인물이라 앞선 상태가 없어요.' : `${c.first_ep}화에 처음 나오는 인물이에요.`}</div><div class="row">${link}</div>`;
  }
  const st = castStateOf(f, c.id);
  const rows = SHEET_STATE.map(([label, k]) => `<dt>${label}</dt><dd${st && st[k] ? '' : ' class="small"'}>${esc((st && st[k]) || '기록 없음')}</dd>`).join('');
  const knows = st ? st.knows || [] : [];
  const KNOW_MAX = 4;
  const know = knows.length
    ? `<dt>아는 것 ${knows.length}</dt><dd><span class="mn-chips">${knows.slice(0, KNOW_MAX).map((k) => `<span class="csh-know">${esc(k)}</span>`).join('')}${knows.length > KNOW_MAX ? `<span class="small">외 ${knows.length - KNOW_MAX}개</span>` : ''}</span></dd>`
    : '<dt>아는 것</dt><dd class="small">기록 없음</dd>';
  const ties = (f ? f.ties : []).filter((t) => t.source === c.id).sort((x, y) => y.familiarity - x.familiarity);
  const REL_MAX = 4;
  const rels = ties.slice(0, REL_MAX).map((t) => {
    const pr = pairOf(f, c.id, t.target);
    return `<li><div class="between"><strong>→ ${esc(charName(t.target))}${pr && pr.type ? ` <span class="small">${esc(pr.type)}</span>` : ''}</strong><span class="small">${tensionText(pr)}</span></div><div class="small">${tieText(t)}</div></li>`;
  }).join('');
  return `${head}<div class="small">${esc(when)}</div>
    <dl class="mn-state">${rows}${know}</dl>
    <div class="mn-sec"><span class="small">이 화까지의 관계</span>${rels ? `<ul class="mn-rels">${rels}</ul>${ties.length > REL_MAX ? `<div class="small">외 ${ties.length - REL_MAX}명</div>` : ''}` : '<div class="small">아직 관계가 없어요</div>'}</div>
    <div class="row">${link}</div>`;
}

function mnPlaceCard(pl) {
  return `<div class="between"><strong id="mn-title">${esc(pl.name)}</strong><button type="button" class="btn small" data-action="mentionClose">닫기</button></div>
    <div class="small">${esc(pl.source)}${pl.aliases.length ? ` · 다른 이름 ${esc(pl.aliases.join(', '))}` : ''}</div>
    <p class="mn-desc${pl.description ? '' : ' small'}">${esc(pl.description || '설명이 없어요')}</p>
    <div class="row"><a class="btn small" href="${base()}/atlas" data-action="mentionAtlas" data-arg="${esc(pl.key)}">지도에서 보기</a></div>`;
}

function mnCardHtml(id, n) {
  if (id.startsWith('c:')) {
    const c = P().characters.find((x) => x.id === id.slice(2));
    return c ? mnPersonCard(c, n) : '';
  }
  const pl = mentionPlaces().find((x) => x.key === id.slice(2));
  return pl ? mnPlaceCard(pl) : '';
}

/** 카드 자리의 화면 좌표 (본문 칸 글자 위치나 누른 요소). 없어졌으면 null. */
function mnAnchorRect(anchor) {
  if (anchor.ta) {
    const ta = document.querySelector(`textarea[data-draft="${anchor.ta}"]`);
    if (!ta) return null;
    const c = caretXY(ta, anchor.a);
    return { left: c.x, top: c.y, bottom: c.y + c.h };
  }
  const el = document.querySelector(anchor.sel);
  return el ? el.getBoundingClientRect() : null;
}

/** 이름 바로 아래에 둔다. 화면 아래로 넘치면 위에, 좌우는 화면 안에. */
function mnPlace() {
  const el = mnCardEl();
  const r = mnAnchorRect(mnOpen.anchor);
  if (!r) return mentionClose();
  const vw = document.documentElement.clientWidth;
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  let y = r.bottom + 6;
  if (y + h > window.innerHeight && r.top - h - 6 >= 0) y = r.top - h - 6;
  const x = Math.min(Math.max(8, r.left - 16), vw - w - 8);
  el.style.left = `${Math.max(8, x) + window.scrollX}px`;
  el.style.top = `${y + window.scrollY}px`;
}

/** 카드를 띄운다. focus 면 카드의 닫기 버튼으로 간다 (키보드로 연 경우). */
function mentionShow(id, n, anchor, back, focus) {
  const html = mnCardHtml(id, n);
  if (!html) return;
  if (S.selTool && S.selTool.mode === 'menu' && typeof hideTool === 'function') hideTool();  // 부분 수정 메뉴와 겹쳐 뜨지 않게
  mnOpen = { id, n, anchor, back };
  const el = mnCardEl();
  el.innerHTML = html;
  el.hidden = false;
  mnPlace();
  if (focus) el.querySelector('button, a').focus({ preventScroll: true });
  if (id.startsWith('c:') && !mnCastFresh()) {
    mnCastEnsure().then(() => {
      if (!mnOpen || mnOpen.id !== id || mnOpen.n !== n) return;
      const had = el.contains(document.activeElement);
      el.innerHTML = mnCardHtml(id, n);
      mnPlace();
      if (had) el.querySelector('button, a').focus({ preventScroll: true });
    });
  }
}

function mentionClose(restore = false) {
  const was = mnOpen;
  mnOpen = null;
  const el = document.getElementById('mn-card');
  if (el) el.hidden = true;
  if (!restore || !was || !was.back) return;
  const back = typeof was.back === 'string' ? document.querySelector(was.back) : was.back;
  if (back && document.contains(back)) back.focus({ preventScroll: true });
}

/** 본문 칸 커서 자리의 이름. 고친 뒤 아직 다시 찾지 않았으면 지금 찾는다. */
function mentionAt(ta, p) {
  if (!mentionsOn) return null;
  return mentionsFor(ta.value).find((r) => r.a <= p && p <= r.b) || null;
}

/** 고치는 본문 칸에서 고른 것 없이 이름을 눌렀을 때 (marks.js 의 클릭에서 부른다). 포커스는 본문 칸에 둔다. */
function mentionFromTa(ta, r, focus = false) {
  const n = Number(ta.dataset.draft);
  mentionShow(r.id, n, { ta: n, a: r.a }, `textarea[data-draft="${n}"]`, focus);
}

/** render() 직후 (marks.js 의 syncMarks): 떠 있는 카드를 새 화면에 다시 맞추고, 자리가 없어졌으면 닫는다. */
function mentionSync() {
  if (!mnOpen) return;
  const n = Number(S.route[3]) || currentEp();
  if (S.route[2] !== 'write' || n !== mnOpen.n || !mentionsOn) return mentionClose();
  const el = mnCardEl();
  if (!el.contains(document.activeElement)) el.innerHTML = mnCardHtml(mnOpen.id, mnOpen.n) || el.innerHTML;
  mnPlace();
}

// 읽기 전용 본문: 이름을 누르면 (드래그로 고른 것이 없을 때) 카드
document.addEventListener('click', (e) => {
  const m = e.target.closest && e.target.closest('.read [data-mention]');
  if (!m) return;
  setTimeout(() => {  // 두 번 눌러 낱말을 고른 것까지 본 뒤에
    const s = window.getSelection();
    if (s && !s.isCollapsed) return mentionClose();
    const div = m.closest('.read');
    mentionShow(m.dataset.mention, Number(div.dataset.read), { sel: `.read [data-mention-at="${m.dataset.mentionAt}"]` }, `.read [data-mention-at="${m.dataset.mentionAt}"]`, false);
  }, 0);
});

document.addEventListener('keydown', (e) => {
  if (e.isComposing) return;
  if (e.key === 'Escape' && mnOpen) {
    const inCard = e.target.closest && e.target.closest('#mn-card');
    mentionClose(true);
    if (inCard) e.preventDefault();
    return;
  }
  const m = e.target.closest && e.target.closest('.read [data-mention]');
  if (m && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    const sel = `.read [data-mention-at="${m.dataset.mentionAt}"]`;
    mentionShow(m.dataset.mention, Number(m.closest('.read').dataset.read), { sel }, sel, true);
    return;
  }
  // 본문 칸: 이름에 커서를 두고 Alt+Enter. 고른 것이 있으면 부분 수정 도구의 몫이다 (passage.js)
  const ta = e.target;
  if (e.altKey && e.key === 'Enter' && !S.selTool && ta.matches && ta.matches('textarea[data-draft]') && ta.selectionStart === ta.selectionEnd) {
    const r = mentionAt(ta, ta.selectionStart);
    if (r) {
      e.preventDefault();
      mentionFromTa(ta, r, true);
    }
  }
});

document.addEventListener('mousedown', (e) => {
  if (!mnOpen || (e.target.closest && e.target.closest('#mn-card'))) return;
  mentionClose();
});

document.addEventListener('input', (e) => {
  if (mnOpen && e.target.matches && e.target.matches('textarea[data-draft]')) mentionClose();
});

document.addEventListener('scroll', (e) => {
  if (mnOpen && e.target.matches && e.target.matches('textarea[data-draft]')) mentionClose();
}, true);

window.addEventListener('resize', () => { if (mnOpen) mnPlace(); });
window.addEventListener('hashchange', () => mentionClose());

Object.assign(actions, {
  mentionsToggle() {
    mentionsOn = !mentionsOn;
    try { localStorage.setItem('canon.mentions', mentionsOn ? '1' : '0'); } catch { /* 이번 화면에서만 */ }
    mentionClose();
    render();
    document.querySelector('[data-action="mentionsToggle"]')?.focus({ preventScroll: true });
  },
  mentionClose() {
    mentionClose(true);
  },
  /** 왼쪽 '본문 속 이름' 목록에서 고른 이름. 카드는 그 버튼 옆에 뜨고, 닫으면 버튼으로 돌아온다. */
  mentionPick(id) {
    const n = Number(S.route[3]) || currentEp();
    const sel = `[data-action="mentionPick"][data-arg="${CSS.escape(id)}"]`;
    if (mnOpen && mnOpen.id === id && typeof mnOpen.back === 'string' && mnOpen.back === sel) return mentionClose(true);
    mentionShow(id, n, { sel }, sel, true);
  },
  /** 지도로 가서 그 장소를 고른다. */
  mentionAtlas(key) {
    mentionClose();
    const go = () => {
      if (S.route[2] !== 'atlas' || !S.atlas || !(S.atlas.places || []).some((pl) => pl.key === key)) return;
      S.atlasSel = key;
      atlasRefresh();
    };
    if (S.route[2] === 'atlas') return go();
    window.addEventListener('hashchange', () => routeQueue.then(go), { once: true });
    location.hash = `${base()}/atlas`;
  },
});

(function mentionStyle() {
  if (!document.head) return;  // node 시험 (tests/test_mentions_js.py)
  const css = `
:root { --mn-person: color-mix(in srgb, var(--green) 80%, transparent); --mn-place: color-mix(in srgb, var(--act-3-ink) 70%, transparent); }
@media (prefers-color-scheme: dark) { :root { --mn-person: color-mix(in srgb, var(--green-ink) 75%, transparent); --mn-place: color-mix(in srgb, var(--act-3-ink) 75%, transparent); } }
.mn { text-decoration-line: underline; text-decoration-thickness: 1.5px; text-underline-offset: 8px; text-decoration-skip-ink: none; }
mark.hl .mn { text-underline-offset: 11px; }  /* 문체 밑줄(물결 포함) 아래로 비켜 둘 다 보이게 */
.mn.person { text-decoration-style: dotted; text-decoration-color: var(--mn-person); }
.mn.place { text-decoration-style: dashed; text-decoration-color: var(--mn-place); }
.read .mn { cursor: pointer; border-radius: 2px; }
.read .mn:hover { background: var(--chip); }
.mn-list { display: flex; flex-wrap: wrap; gap: 4px; }
.mn-pick.person { border-bottom: 2px dotted var(--mn-person); }
.mn-pick.place { border-bottom: 2px dashed var(--mn-place); }
.mn-card { position: absolute; z-index: 60; width: min(340px, calc(100vw - 16px)); max-height: min(70vh, 480px); overflow: auto; padding: 12px 14px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--surface); color: var(--text); box-shadow: 0 8px 24px rgba(0,0,0,.14); display: flex; flex-direction: column; gap: 8px; font-size: 0.8125rem; line-height: 1.5; box-sizing: border-box; }
.mn-card[hidden] { display: none; }
.mn-state { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 0; }
.mn-state dt { color: var(--muted); white-space: nowrap; }
.mn-state dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.mn-chips { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.mn-sec { display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--line); padding-top: 8px; }
.mn-rels { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.mn-desc { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());
