/* 공용 목차 틀: 왼쪽 목차 + 오른쪽 카드 한 열 (설정 도우미 setup.js · 문체 style.js · 역설계 실험 revlab.js).
   CSS 는 app.css '공용 목차 틀' 절. 넓은 칸은 왼쪽 목록이고, 틀(.outline-wrap)이 720px 이하면 위에 붙는 '지금 구역 ▾' 버튼과 펼친 목록이다.
   열림은 OUTLINE_OPEN 이 기억한다. 목차를 다시 그려도 열림과 aria-expanded 가 맞는다.
   바깥 누르기 · 목록 줄 누르기 · Esc · 주소 바뀜에 닫고, Esc 는 버튼으로 포커스를 돌린다.
   지금 구역은 outlineSpy 로 맡긴 화면마다 스크롤 하나가 센다(outlinePick). outlineNav · outlinePick 은 순수 함수(tests/test_outline_js.py) */

const OUTLINE_OPEN = new Set();   // 좁은 칸에서 펼친 목차 id
const OUTLINE_SPIES = {};         // 목차 id → { targets, set, line, bottom }

/** 틀: 목차 + 카드 열. wide 면 카드 열이 760px 에서 멈추지 않고 남은 폭을 다 쓴다. cls 는 화면 클래스(그 화면 CSS 를 거는 자리) */
const outlineDoc = (toc, main, { wide = false, cls = '' } = {}) =>
  `<div class="outline-wrap${cls ? ` ${cls}` : ''}"><div class="outline-doc${wide ? ' wide' : ''}">${toc}${main}</div></div>`;

/** 목차 nav. now 는 좁은 칸 버튼 글(HTML)이고, 비우면 버튼 없이 목록만 둔다(마법사 걸음 막대). after 는 목록 뒤에 붙는 HTML */
function outlineNav({ id, label, now = '', body = '', cls = '', after = '' }) {
  const open = !!now && OUTLINE_OPEN.has(id);
  const btn = now ? `<button type="button" class="btn outline-now" data-action="outlineToggle" data-arg="${id}" aria-expanded="${open}" aria-controls="${id}-list"><span class="tl">${now}</span><span aria-hidden="true">▾</span></button>` : '';
  return `<nav class="outline${cls ? ` ${cls}` : ''}${open ? ' open' : ''}" id="${id}" aria-label="${label}">${btn}<div class="outline-list" id="${id}-list">${body}</div>${after}</nav>`;
}

/** 지금 구역: [열쇠, 화면 위에서 잰 top] 가운데 top 이 line 을 지난 마지막 것. 아무것도 안 지났으면 맨 위 것(first 가 거짓이면 null),
    맨 아래까지 내렸으면(bottom) 마지막 것. 화면 순서는 top 으로 정한다(목차 순서와 카드 순서가 다를 수 있다) */
function outlinePick(tops, { line = 120, bottom = false, first = true } = {}) {
  if (!tops.length) return null;
  const sorted = [...tops].sort((a, b) => a[1] - b[1]);
  if (bottom) return sorted[sorted.length - 1][0];
  let cur = first ? sorted[0][0] : null;
  sorted.forEach(([k, top]) => { if (top <= line) cur = k; });
  return cur;
}

/** 열기 · 닫기. on 을 안 주면 뒤집는다 */
function outlineToggle(id, on) {
  const open = on === undefined ? !OUTLINE_OPEN.has(id) : !!on;
  if (open) OUTLINE_OPEN.add(id); else OUTLINE_OPEN.delete(id);
  const nav = document.getElementById(id);
  if (!nav) return;
  nav.classList.toggle('open', open);
  const b = nav.querySelector(':scope > .outline-now');
  if (b) b.setAttribute('aria-expanded', String(open));
}

/** 펼친 목차를 모두 닫는다. focus 면 그 버튼으로 포커스를 돌린다. 닫은 것이 있으면 참 */
function outlineClose(focus = false) {
  const ids = [...OUTLINE_OPEN];
  ids.forEach((id) => {
    outlineToggle(id, false);
    if (focus) document.querySelector(`#${id} > .outline-now`)?.focus();
  });
  return ids.some((id) => document.getElementById(id));
}

/** 목차만 다시 그린다(지금 구역 · 칸 상태가 바뀔 때). 목차 안에 있던 포커스는 같은 줄로 돌린다 */
function outlineRefresh(id, html) {
  const nav = document.getElementById(id);
  if (!nav) return;
  const a = document.activeElement;
  let keep = null;
  if (a && nav.contains(a)) {
    if (a.classList.contains('outline-now')) keep = ':scope > .outline-now';
    else if (a.dataset.action) keep = `[data-action="${CSS.escape(a.dataset.action)}"]${a.dataset.arg !== undefined ? `[data-arg="${CSS.escape(a.dataset.arg)}"]` : ''}`;
    else if (a.getAttribute('href')) keep = `[href="${CSS.escape(a.getAttribute('href'))}"]`;
  }
  nav.outerHTML = html;
  if (keep) document.getElementById(id)?.querySelector(keep)?.focus({ preventScroll: true });
}

/** 스크롤로 지금 구역을 센다. spy = { targets: () => [[열쇠, 요소]], set(열쇠), line, bottom, first }.
    목차 id 가 화면에 있을 때만 돈다. set 은 스크롤마다 부르니 같은 열쇠면 화면이 그냥 돌아간다 */
function outlineSpy(id, spy) {
  OUTLINE_SPIES[id] = spy;
}

Object.assign(actions, {
  /** 좁은 칸의 목차 펼치기 · 접기 */
  outlineToggle(id) {
    outlineToggle(id);
  },
});

// 바깥을 누르거나 펼친 목록의 줄을 누르면 닫는다. 줄 동작이 화면을 다시 그리기 전에 닫게 capture 로 듣는다.
// 줄에 data-outline-keep 이 있으면(목록 안 접기 단추 등) 열어 둔다
document.addEventListener('click', (e) => {
  if (!OUTLINE_OPEN.size || !e.target.closest) return;
  [...OUTLINE_OPEN].forEach((id) => {
    const nav = document.getElementById(id);
    if (!nav) { OUTLINE_OPEN.delete(id); return; }
    if (!nav.contains(e.target)) outlineToggle(id, false);
    else if (e.target.closest('.outline-list .outline-item') && !e.target.closest('[data-outline-keep]')) outlineToggle(id, false);
  });
}, true);

// Esc 는 펼친 목차를 닫고 버튼으로 포커스를 돌린다. 열린 메뉴(app.js)는 먼저 닫히고, 대화 패널(chat.js)보다는 먼저 받는다
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || e.isComposing || e.defaultPrevented || !OUTLINE_OPEN.size) return;
  if (!outlineClose(true)) return;
  e.preventDefault();
  e.stopImmediatePropagation();
}, true);

// 다른 화면으로 가면 닫는다
window.addEventListener('hashchange', () => { outlineClose(); });

window.addEventListener('scroll', () => {
  Object.entries(OUTLINE_SPIES).forEach(([id, s]) => {
    if (!document.getElementById(id)) return;
    const t = s.targets().filter(([, el]) => el);
    if (!t.length) return;
    const key = outlinePick(t.map(([k, el]) => [k, el.getBoundingClientRect().top]), {
      line: s.line ?? 120,
      bottom: s.bottom !== false && innerHeight + scrollY >= document.documentElement.scrollHeight - 4,
      first: s.first !== false,
    });
    s.set(key);
  });
}, { passive: true });
