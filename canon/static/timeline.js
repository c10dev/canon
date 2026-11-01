/* 작품 속 시간. app.js 의 S, actions, api, run, render, header, esc, P, input, base, ep, epIndex, saveIfDirty, toast, menuBtn 과 outline.js 의 공용 목차 틀을 쓴다.
   화가 끝난 시점(Episode.time)과 앞으로 올 기한(Project.timeline.deadlines)을 보고 고친다. 서버는 canon/timeline.py.
   화면은 공용 목차 틀이다: 왼쪽 목차(지금 · 기한 · 시간 흐름 묶음 · 설정), 오른쪽 카드 한 열.
   지금(마지막 반영 화 끝 · 앞으로 열흘 띠) → 기한(나눔 버튼 열림 · 닫힘 · 모두, 줄마다 ⋯ 메뉴) → 시간 흐름(장편은 아크, 단편은 기승전결 구간마다 카드, 읽기가 기본이고 '고치기'로 그 카드만) → 설정(읽기 · 고치기).
   켜고 끄기 · 기준 · 화별 시점은 작품 저장(저장 띠)으로, 기한은 /timeline/deadlines 로 고친다(스냅샷도 함께).
   남은 날 · 지금 날수 계산(tlLeft, tlDay)은 timeline.left · current_day 와 같은 규칙이라 함께 고친다.
   tlGroups · tlDeadlineRows · tlShort 는 순수 함수(tests/test_timeline_js.py).
   상태 승인 화면의 시점 칸과 기한 고르기(tlDeltaCard, 키 k · o), 반영 기록(tlHistory), 집필 화면 플롯 띠의 시간 줄(tlLines)도 여기 있다. */
'use strict';

Object.assign(S, {
  tlEdit: '',        // 고치는 기한 id. 'new' 는 새 기한 칸
  tlEditGroup: '',   // 끝난 시점을 고치는 시간 흐름 묶음 열쇠
  tlSetEdit: false,  // 설정 카드를 고치는 중
  tlFold: {},        // 묶음 열쇠 → 펼침(작가가 고른 것). 없으면 지금 화 · 거꾸로 간 화가 있는 묶음만 편다
  tlDlTab: 'open',   // 기한 거르기: open | closed | all
  tlCur: 'tl-now',   // 목차의 지금 구역
});

(function tlStyle() {
  const bars = [1, 2, 3, 4, 5, 6, 7].map((k) => `.tl-gap .w${k} { width: ${k * 8}px; }`).join('\n');
  const css = `
.tl-col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.tl-col > .card { scroll-margin-top: calc(var(--band, 0px) + 16px); }
.tl-big { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em; }
.tl-days { display: grid; grid-template-columns: repeat(10, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.tl-days > div { min-height: 76px; padding: 6px 4px; border-left: 1px solid var(--rule); display: flex; flex-direction: column; gap: 4px; font-size: 0.6875rem; color: var(--muted); min-width: 0; }
.tl-days > div:first-child { border-left: none; }
.tl-days b { font-size: 0.8125rem; color: var(--text-2); }
.tl-days .now { background: var(--accent-soft); }
.tl-days .now b { color: var(--accent-ink); }
.tl-flag { padding: 2px 4px; border-radius: 4px; background: var(--chip); color: var(--text-2); font-weight: 700; line-height: 1.3; word-break: keep-all; overflow-wrap: anywhere; }
.tl-flag.hot { background: var(--accent); color: var(--on-accent); }
@container outline (max-width: 560px) { .tl-days { grid-template-columns: repeat(7, minmax(0, 1fr)); } .tl-days > div:nth-child(n+8) { display: none; } .tl-flag { font-size: 0.625rem; word-break: keep-all; } }
.tl-dls { display: flex; flex-direction: column; }
.tl-dl { min-height: 56px; padding: 8px 0; border-top: 1px solid var(--rule); display: grid; grid-template-columns: 56px minmax(0, 1fr) auto auto; gap: 12px; align-items: center; }
.tl-dl:first-child { border-top: none; }
.tl-dl.warn { margin: 0 -12px; padding: 10px 12px; border-radius: 10px; border-top-color: transparent; background: var(--amber-soft); }
.tl-dl.warn + .tl-dl { border-top-color: transparent; }
.tl-dl.done { color: var(--muted); }
.tl-dl-t { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.tl-dl-t .row { margin-top: 4px; }
.tl-warn { font-size: 0.8125rem; color: var(--amber-ink); }
.tl-q { font-family: var(--serif); }
.tl-dbox { text-align: center; line-height: 1.2; }
.tl-dbox b { display: block; font-size: 1.0625rem; }
.tl-dbox span { font-size: 0.75rem; color: var(--muted); }
@container outline (max-width: 560px) {
  .tl-dl { grid-template-columns: 44px minmax(0, 1fr) auto; }
  .tl-dl > .chip { grid-column: 2; grid-row: 2; justify-self: start; }
  .tl-dl > .menu { grid-column: 3; grid-row: 1; }
}
.tl-rows { display: flex; flex-direction: column; }
.tl-row { min-height: 48px; padding: 8px 0; border-top: 1px solid var(--rule); display: grid; grid-template-columns: 52px minmax(0, 1fr) minmax(0, 190px) 120px; gap: 12px; align-items: center; }
.tl-row:first-child { border-top: none; }
.tl-row .n { font-weight: 700; color: var(--text-2); }
.tl-row .t { font-weight: 700; }
.tl-row .s { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
.tl-row.back { margin: 0 -12px; padding: 10px 12px; border-radius: 10px; border-top-color: transparent; background: var(--red-soft); }
.tl-row.back + .tl-row { border-top-color: transparent; }
.tl-row.back .s.why { color: var(--err-ink); }
.tl-gap { display: flex; align-items: center; gap: 6px; font-size: 0.75rem; color: var(--muted); white-space: nowrap; }
.tl-gap i { display: inline-block; height: 6px; border-radius: 3px; background: var(--line-strong); }
.tl-gap.back { color: var(--err-ink); font-weight: 700; }
.tl-gap.back i { background: var(--red); }
${bars}
@container outline (max-width: 560px) {
  .tl-row { grid-template-columns: 44px minmax(0, 1fr); gap: 2px 10px; }
  .tl-row > :nth-child(n+3) { grid-column: 2; }
}
.tl-in { display: grid; grid-template-columns: 52px minmax(0, 1fr) 170px 120px minmax(0, 1fr); gap: 8px; align-items: center; padding: 6px 0; border-top: 1px solid var(--rule); }
.tl-in.head { border-top: none; font-size: 0.75rem; color: var(--muted); }
.tl-in input { width: 100%; min-width: 0; }
.tl-in .small.wide { grid-column: 2 / -1; }
@container outline (max-width: 560px) {
  .tl-in { grid-template-columns: 44px minmax(0, 1fr) minmax(0, 1fr); }
  .tl-in.head { display: none; }
  .tl-in > :nth-child(n+4) { grid-column: 2 / -1; }
}
.tl-time { display: grid; grid-template-columns: 96px minmax(0, 1fr) minmax(0, 1.4fr); gap: 8px; }
@media (max-width: 640px) { .tl-time { grid-template-columns: 1fr; } }
.tl-wrap .check-row { min-height: var(--touch-min); display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
.tl-start { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 12px; }
@container outline (max-width: 560px) { .tl-start { grid-template-columns: 1fr; } }
.tl-form { display: grid; grid-template-columns: minmax(0, 2fr) 150px minmax(0, 2fr) auto; gap: 8px; align-items: end; padding: 10px 0; border-top: 1px solid var(--rule); }
.tl-form:first-child { border-top: none; }
@container outline (max-width: 720px) { .tl-form { grid-template-columns: 1fr; } }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

const tlOn = () => !!(P().timeline || {}).enabled;

/** timeline.fmt 와 같은 모양: '3일째 밤 (3월 5일 화요일)'. */
function tlFmt(t) {
  if (!t) return '';
  const head = [t.day > 0 ? `${t.day}일째` : '', (t.part || '').trim()].filter(Boolean).join(' ');
  const label = (t.label || '').trim();
  return head && label ? `${head} (${label})` : head || label;
}

// ----- 달력: timeline.calendar · day_label · when 과 같은 규칙 -----
const TL_WEEKDAYS = '월화수목금토일';

/** y년 m월 d일의 Date(UTC). 2월 30일 같은 날은 null. */
function tlMake(y, m, d) {
  const x = new Date(Date.UTC(2000, m - 1, d));
  x.setUTCFullYear(y, m - 1, d);  // Date.UTC 는 0~99년을 1900년대로 읽는다
  return x.getUTCMonth() === m - 1 && x.getUTCDate() === d ? x : null;
}

/** { first: 1일째 Date(UTC) | null, year: 연도를 아는지, wd: 1일째 요일 0=월 | null }. 날짜 칸(start_date)이 먼저, 없으면 기준 글. */
function tlCalendar() {
  const tl = P().timeline || {};
  const iso = (tl.start_date || '').match(/^\s*(\d{1,4})-(\d{1,2})-(\d{1,2})\s*$/);
  const firstIso = iso && tlMake(+iso[1], +iso[2], +iso[3]);
  if (firstIso) return { first: firstIso, year: true, wd: (firstIso.getUTCDay() + 6) % 7 };
  const text = tl.start || '';
  const w = text.match(/([월화수목금토일])요일/);
  const wd = w ? TL_WEEKDAYS.indexOf(w[1]) : null;
  const make = tlMake;
  let m = text.match(/(\d{1,4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일/);
  if (m) {
    const first = make(+m[1], +m[2], +m[3]);
    return first ? { first, year: true, wd: (first.getUTCDay() + 6) % 7 } : { first: null, year: false, wd };
  }
  m = text.match(/(\d{1,2})\s*월\s*(\d{1,2})\s*일/);
  if (m) return { first: make(+m[1] === 2 && +m[2] === 29 ? 2000 : 2001, +m[1], +m[2]), year: false, wd };
  return { first: null, year: false, wd };
}

/** 날수의 날짜와 요일 ('3월 31일 화요일'). 모르면 ''. */
function tlDayLabel(day) {
  if (!(day > 0)) return '';
  const c = tlCalendar();
  const out = [];
  if (c.first) {
    const x = new Date(c.first.getTime() + (day - 1) * 86400000);
    out.push(`${c.year && x.getUTCFullYear() !== c.first.getUTCFullYear() ? `${x.getUTCFullYear()}년 ` : ''}${x.getUTCMonth() + 1}월 ${x.getUTCDate()}일`);
  }
  if (c.wd != null) out.push(TL_WEEKDAYS[(c.wd + day - 1) % 7] + '요일');
  return out.join(' ');
}

/** 1일째 날짜를 알아 화마다 날짜로 보이는지 (timeline.dated). */
const tlDated = () => !!tlCalendar().first;

/** 날수의 날짜 'YYYY-MM-DD' (날짜 입력칸 값). 모르면 ''. */
function tlISO(day) {
  const c = tlCalendar();
  if (!c.first || !(day > 0)) return '';
  const x = new Date(c.first.getTime() + (day - 1) * 86400000);
  const pad = (v, k) => String(v).padStart(k, '0');
  return `${pad(x.getUTCFullYear(), 4)}-${pad(x.getUTCMonth() + 1, 2)}-${pad(x.getUTCDate(), 2)}`;
}

/** 날짜 입력칸 값의 날수. 1일째보다 앞이거나 모르면 0. */
function tlDayOf(iso) {
  const c = tlCalendar();
  const m = (iso || '').match(/^(\d{1,4})-(\d{1,2})-(\d{1,2})$/);
  const x = m && tlMake(+m[1], +m[2], +m[3]);
  if (!c.first || !x) return 0;
  const day = Math.round((x - c.first) / 86400000) + 1;
  return day > 0 ? day : 0;
}

/** 시점 한 줄 (timeline.when). 날짜를 알면 날짜가 앞('3월 6일 수요일 밤 (3일째)'), 요일만 알면 '3일째 밤 (수요일)'. */
function tlWhen(t) {
  const cal = t ? tlDayLabel(t.day) : '';
  if (!cal) return tlFmt(t);
  let extra = (t.label || '').trim();
  if (/\d+\s*(?:년|월|일)|요일/.test(extra)) extra = '';
  if (tlDated()) return `${[cal, (t.part || '').trim()].filter(Boolean).join(' ')} (${t.day}일째${extra ? `, ${extra}` : ''})`;
  const head = [`${t.day}일째`, (t.part || '').trim()].filter(Boolean).join(' ');
  return `${head} (${cal}${extra ? `, ${extra}` : ''})`;
}

/** 날수 한 칸: 날짜를 알면 '3월 10일 일요일', 아니면 '9일째'. */
const tlAt = (day) => (day > 0 ? (tlDated() ? tlDayLabel(day) : `${day}일째`) : '');

const tlKnown = (t) => !!(t && (t.day > 0 || (t.part || '').trim() || (t.label || '').trim()));

/** n화보다 앞에서 시점을 아는 마지막 화 (timeline.prev_end). */
function tlPrev(n) {
  return [...P().episodes].filter((e) => e.plot.number < n && tlKnown(e.time)).sort((a, b) => b.plot.number - a.plot.number)[0] || null;
}

/** n화 직전의 날수 (timeline.current_day). 모르면 0. */
function tlDay(n) {
  const e = [...P().episodes].filter((x) => x.plot.number < n && x.time && x.time.day > 0).sort((a, b) => b.plot.number - a.plot.number)[0];
  return e ? e.time.day : 0;
}

/** timeline.left 와 같은 규칙. */
function tlLeft(d, day) {
  if (!(d.day > 0) || !(day > 0)) return '';
  const gap = d.day - day;
  return gap > 0 ? `${gap}일 남음` : gap === 0 ? '오늘' : `${-gap}일 지남`;
}

const tlLastDone = () => Math.max(0, ...P().episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));

/** timeline.is_open: n화를 쓸 때 열린 기한. */
const tlIsOpen = (d, n) => d.set_ep < n && !(d.done_ep > 0 && d.done_ep < n);

// ----- 화면 계산 (순수) -----

/** 날수의 짧은 글: 날짜를 알면 '3월 21일 수', 아니면 '18일째 · 수'(요일을 알 때). 모르면 ''. */
function tlShort(day) {
  if (!(day > 0)) return '';
  const c = tlCalendar();
  const wd = c.wd != null ? TL_WEEKDAYS[(c.wd + day - 1) % 7] : '';
  if (!c.first) return `${day}일째${wd ? ` · ${wd}` : ''}`;
  const x = new Date(c.first.getTime() + (day - 1) * 86400000);
  return `${c.year && x.getUTCFullYear() !== c.first.getUTCFullYear() ? `${x.getUTCFullYear()}년 ` : ''}${x.getUTCMonth() + 1}월 ${x.getUTCDate()}일${wd ? ` ${wd}` : ''}`;
}

/** 시간 흐름 묶음: 장편은 아크, 단편은 기승전결 구간, 묶음 밖의 화는 '그 밖의 화'(묶음이 없으면 '모든 화').
    줄마다 gap(날수를 아는 앞 화와의 차, 모르면 null)과 back(거꾸로 감). lo · hi 는 묶음 안 날수의 처음과 끝 */
function tlGroups(p) {
  const bands = p.meta && p.meta.form === 'serial'
    ? (p.story_arcs || []).map((a) => ({ key: `a${a.number}`, label: `아크 ${a.number} ${a.title || ''}`.trim(), s: a.start_ep, e: a.end_ep }))
    : (p.arc || []).map((a, i) => ({ key: `k${i}`, label: `${a.name} 구간`, s: a.start_ep, e: a.end_ep }));
  const groups = bands.map((b) => ({ ...b, rows: [] }));
  const rest = { key: 'rest', label: bands.length ? '그 밖의 화' : '모든 화', s: 0, e: 0, rows: [] };
  let last = 0;
  [...p.episodes].sort((a, b) => a.plot.number - b.plot.number).forEach((e) => {
    const n = e.plot.number;
    const day = (e.time && e.time.day) || 0;
    const gap = day > 0 && last > 0 ? day - last : null;
    if (day > 0) last = day;
    (groups.find((g) => g.s <= n && n <= g.e) || rest).rows.push({ n, day, gap, back: gap != null && gap < 0 });
  });
  if (rest.rows.length) groups.push({ ...rest, s: rest.rows[0].n, e: rest.rows[rest.rows.length - 1].n });
  return groups.filter((g) => g.rows.length).map((g) => {
    const days = g.rows.map((r) => r.day).filter((d) => d > 0);
    return { ...g, back: g.rows.filter((r) => r.back).length, lo: days.length ? Math.min(...days) : 0, hi: days.length ? Math.max(...days) : 0 };
  });
}

/** 기한 줄: state 는 overdue(지남) · today · soon(사흘 안) · open · unknown(날 모름) · closed, left 는 꼬리 글.
    day 는 다음에 쓸 화 직전의 날수(tlDay). 지난 것 · 오늘 · 사흘 안 · 열림 · 날 모름 · 닫힘 차례 */
function tlDeadlineRows(list, day) {
  const order = { overdue: 0, today: 1, soon: 2, open: 3, unknown: 4, closed: 5 };
  return list.map((d) => {
    if (d.done_ep > 0) return { d, state: 'closed', left: `${d.done_ep}화에 닫힘` };
    if (!(d.day > 0)) return { d, state: 'unknown', left: '날 모름' };
    if (!(day > 0)) return { d, state: 'open', left: '열림' };
    const gap = d.day - day;
    return { d, state: gap < 0 ? 'overdue' : gap === 0 ? 'today' : gap <= 3 ? 'soon' : 'open', left: tlLeft(d, day) };
  }).sort((a, b) => order[a.state] - order[b.state] || (a.d.day || 0) - (b.d.day || 0) || a.d.set_ep - b.d.set_ep);
}

// ----- 화면 -----

const TL_DL_CHIP = { overdue: 'warn', today: 'hot', soon: '', open: '', unknown: '', closed: 'ok' };

/** 기한 줄 앞 날짜 칸: '4/6 금', 날짜가 없으면 '18 일째', 모르면 '?' */
function tlDateBox(day) {
  if (!(day > 0)) return '<span class="tl-dbox" aria-hidden="true"><b>?</b><span>날 모름</span></span>';
  const c = tlCalendar();
  const wd = c.wd != null ? TL_WEEKDAYS[(c.wd + day - 1) % 7] : '';
  if (!c.first) return `<span class="tl-dbox" aria-hidden="true"><b>${day}</b><span>일째${wd ? ` · ${wd}` : ''}</span></span>`;
  const x = new Date(c.first.getTime() + (day - 1) * 86400000);
  return `<span class="tl-dbox" aria-hidden="true"><b>${x.getUTCMonth() + 1}/${x.getUTCDate()}</b><span>${wd}</span></span>`;
}

/** 다음에 쓸 화. 반영한 화 다음 */
const tlNext = () => tlLastDone() + 1;

/** 묶음을 펴 둘지: 작가가 고른 것, 아니면 고치는 중 · 지금 화가 든 묶음 · 거꾸로 간 화가 있는 묶음 */
function tlGroupOpen(g, n) {
  if (S.tlEditGroup === g.key) return true;
  if (S.tlFold[g.key] !== undefined) return S.tlFold[g.key];
  return g.back > 0 || (g.s <= n && n <= g.e) || (g.s <= n - 1 && n - 1 <= g.e);
}

function tlTocHtml() {
  const p = P();
  const tl = p.timeline;
  const n = tlNext();
  const day = tlDay(n);
  const groups = tlGroups(p);
  const dl = tlDeadlineRows(tl.deadlines, day);
  const over = dl.filter((r) => r.state === 'overdue').length;
  const open = dl.filter((r) => r.state !== 'closed').length;
  const item = (id, label, tail, warn) => `<button type="button" class="outline-item${warn ? ' warn' : ''}" data-action="tlGo" data-arg="${id}"${S.tlCur === id ? ' aria-current="true"' : ''}><span class="tl">${esc(label)}</span>${tail ? `<span class="st">${esc(tail)}</span>` : ''}</button>`;
  const prev = tlPrev(n);
  const body = [
    item('tl-now', '지금', prev && prev.time.day > 0 ? `${prev.time.day}일째` : ''),
    item('tl-dl', '기한', [over ? `지남 ${over}` : '', `열림 ${open}`].filter(Boolean).join(' · '), over > 0),
    groups.length ? `<span class="outline-h">시간 흐름</span>${groups.map((g) => item(`tl-g-${g.key}`, g.label, g.back ? `거꾸로 ${g.back}` : `${g.s}~${g.e}화`, g.back > 0)).join('')}` : '',
    '<div class="outline-sep"></div>',
    item('tl-set', '설정', !tl.enabled ? '꺼짐' : tlDated() ? '날짜로 셈' : '며칠째로 셈', !tl.enabled),
  ].join('');
  const cur = { 'tl-now': '지금', 'tl-dl': '기한', 'tl-set': '설정' }[S.tlCur] || (groups.find((g) => `tl-g-${g.key}` === S.tlCur) || {}).label || '지금';
  return outlineNav({ id: 'tl-toc', label: '작품 속 시간 목차', now: esc(cur), body });
}

function tlNowCard(n, day, dl) {
  const p = P();
  const prev = tlPrev(n);
  const t = prev && prev.time;
  const e = ep(n);
  const big = !t ? '<p class="small">아직 끝난 시점을 기록한 화가 없어요. 화를 반영하면 여기에 보여요.</p>'
    : `<div><div class="tl-big">${esc(t.day > 0 ? [tlDated() ? tlDayLabel(t.day) : `${t.day}일째`, (t.part || '').trim()].filter(Boolean).join(' ') : tlFmt(t))}</div>
      <div class="small">${esc([t.day > 0 && tlDated() ? `${t.day}일째` : t.day > 0 ? tlDayLabel(t.day) : '', (t.label || '').trim(), e ? `${n}화 플롯: ${e.plot.time || '바로 이어짐'}` : ''].filter(Boolean).join(' · '))}</div></div>`;
  let strip = '';
  if (day > 0) {
    const flags = (d) => dl.filter((r) => r.state !== 'closed' && r.d.day === d).map((r) => `<span class="tl-flag${d === day ? ' hot' : ''}">${esc(r.d.what)}</span>`).join('');
    const c = tlCalendar();
    const cells = Array.from({ length: 10 }, (_, i) => {
      const d = day + i;
      const x = c.first && new Date(c.first.getTime() + (d - 1) * 86400000);
      const num = x ? (i === 0 || x.getUTCDate() === 1 ? `${x.getUTCMonth() + 1}/${x.getUTCDate()}` : `${x.getUTCDate()}`) : `${d}일째`;
      const wd = c.wd != null ? TL_WEEKDAYS[(c.wd + d - 1) % 7] : '';
      return `<div${i === 0 ? ' class="now"' : ''}><b>${num}</b>${esc([wd, i === 0 ? '지금' : ''].filter(Boolean).join(' · '))}${flags(d)}</div>`;
    }).join('');
    strip = `<div class="tl-days" role="img" aria-label="${esc(`앞으로 열흘: ${dl.filter((r) => r.d.day >= day && r.d.day < day + 10 && r.state !== 'closed').map((r) => `${tlShort(r.d.day)} ${r.d.what}`).join(', ') || '기한 없음'}`)}">${cells}</div>`;
  }
  const near = dl.filter((r) => ['overdue', 'today', 'soon'].includes(r.state) && tlIsOpen(r.d, n)).length;
  const off = !p.timeline.enabled ? '<div class="note warn">기록이 꺼져 있어요. 상태 변경안에 시점을 적지 않고, 쓰기 · 검수에 시간 블록을 넣지 않아요. 설정에서 켜요.</div>' : '';
  return `<section class="card" id="tl-now"><div class="pf-head"><h2>지금</h2><span class="small">${prev ? `${prev.plot.number}화가 끝난 시점 · 다음은 ${n}화` : `다음은 ${n}화`}</span></div>
    ${off}${big}${strip}
    ${p.timeline.enabled && e ? `<p class="small">${n}화를 쓸 때 AI에게는 직전 화 끝 시점, ${n}화 플롯의 시점, 사흘 안 · 지난 기한 ${near}개만 들어가요.</p>` : ''}</section>`;
}

function tlDlRow(r) {
  const d = r.d;
  if (S.tlEdit === d.id) return tlForm(d);
  const done = d.done_ep > 0;
  const closeAt = Math.max(tlLastDone(), d.set_ep);
  const more = menuBtn(`tl-dl-${d.id}`, '<span aria-hidden="true">⋯</span>', () => `
    <button type="button" class="pop-item" data-action="tlEditOpen" data-arg="${esc(d.id)}">고치기</button>
    <button type="button" class="pop-item" data-action="${done ? 'tlReopen' : 'tlClose'}" data-arg="${esc(d.id)}">${done ? '다시 열기' : `닫기<span class="small">${closeAt}화에 닫힘으로</span>`}</button>
    <div class="pop-sep"></div>
    <button type="button" class="pop-item danger" data-action="tlDrop" data-arg="${esc(d.id)}">지우기</button>`, { cls: 'btn small icon-btn', aria: `${d.what} 더 보기` });
  const warn = r.state === 'overdue';
  const when = d.day > 0 ? tlShort(d.day) : '';
  return `<div class="tl-dl${warn ? ' warn' : ''}${done ? ' done' : ''}">${tlDateBox(d.day)}
    <div class="tl-dl-t"><strong>${esc(d.what)}</strong><span class="sr-only">${esc(when)}</span>
      <span class="small">${d.note ? `<span class="tl-q">“${esc(d.note)}”</span> · ` : ''}${d.set_ep ? `${d.set_ep}화에 생김` : '처음부터'}</span>
      ${warn ? `<span class="tl-warn">날이 지났는데 열려 있어요. 일이 일어났으면 닫고, 미뤘으면 날을 바꾸세요.</span>
        <span class="row"><button type="button" class="btn small" data-action="tlClose" data-arg="${esc(d.id)}">닫기</button><button type="button" class="btn small" data-action="tlEditOpen" data-arg="${esc(d.id)}">날 바꾸기</button></span>` : ''}</div>
    <span class="chip${TL_DL_CHIP[r.state] ? ` ${TL_DL_CHIP[r.state]}` : ''}">${esc(r.left)}</span>${more}</div>`;
}

function tlForm(d) {
  const x = d || { id: '', what: '', day: 0, note: '' };
  return `<form class="tl-form" data-tl-form="${esc(x.id)}">
    <div class="field"><label for="tl-what">무엇의 기한</label><input id="tl-what" type="text" value="${esc(x.what)}" placeholder="예: 왕성 축제 첫날, 빚 갚을 날"></div>
    ${tlDated() ? `<div class="field"><label for="tl-date">날짜</label><input id="tl-date" type="date" min="${tlISO(1)}" value="${tlISO(x.day)}"></div>`
    : `<div class="field"><label for="tl-day">며칠째</label><input id="tl-day" type="number" min="0" value="${x.day > 0 ? x.day : ''}" placeholder="모름"></div>`}
    <div class="field"><label for="tl-note">본문에 나온 말</label><input id="tl-note" type="text" value="${esc(x.note)}" placeholder="예: 사흘 뒤 자정까지"></div>
    <span class="row"><button type="button" class="btn small" data-action="tlEditOpen" data-arg="">취소</button><button type="submit" class="btn small primary">${x.id ? '저장' : '더하기'}</button></span></form>`;
}

function tlDlCard(dl) {
  const counts = { open: dl.filter((r) => r.state !== 'closed').length, closed: dl.filter((r) => r.state === 'closed').length, all: dl.length };
  const tab = S.tlDlTab;
  const rows = dl.filter((r) => tab === 'all' || (tab === 'closed') === (r.state === 'closed'));
  const seg = dl.length ? `<div class="seg" role="group" aria-label="기한 거르기">${[['open', '열림'], ['closed', '닫힘'], ['all', '모두']].map(([k, l]) => `<button type="button" aria-pressed="${tab === k}" data-action="tlDlTab" data-arg="${k}">${l} ${counts[k]}</button>`).join('')}</div>` : '';
  const empty = !rows.length && S.tlEdit !== 'new' ? `<p class="small">${dl.length ? (tab === 'closed' ? '닫힌 기한이 없어요.' : '열린 기한이 없어요.') : '기한이 없어요. 축제, 결혼식, \'사흘 안에\' 같은 약속을 더하면 남은 날을 Canon이 세요.'}</p>` : '';
  return `<section class="card" id="tl-dl"><div class="pf-head"><h2>기한</h2>${seg}</div>
    <div class="tl-dls">${S.tlEdit === 'new' ? tlForm(null) : ''}${rows.map(tlDlRow).join('')}</div>${empty}
    <p class="small">AI가 본문에서 찾은 기한은 상태 승인에서 골라 반영돼요. 직접 더한 기한은 ${tlLastDone() || 0}화에 생긴 것으로 기록돼요.</p></section>`;
}

/** 묶음 안 한 화의 읽기 줄 */
function tlRowRead(r, g) {
  const e = ep(r.n);
  const t = e.time || {};
  const fin = e.status === 'finalized';
  const born = P().timeline.deadlines.filter((d) => d.set_ep === r.n).map((d) => d.what);
  const sub = [`플롯: ${e.plot.time || '바로 이어짐'}`, born.length ? `기한 생김: ${born.join(', ')}` : ''].filter(Boolean).join(' · ');
  let when;
  if (!fin) when = `<span class="small">${esc(STATUS[e.status])}${e.status === 'written' ? ' · 반영하면 채워져요' : ''}</span>`;
  else if (r.day > 0) when = `${esc([tlShort(r.day), (t.part || '').trim()].filter(Boolean).join(' '))}${(t.label || '').trim() ? `<div class="s">${esc(t.label.trim())}</div>` : ''}`;
  else if (tlKnown(t)) when = `${esc([(t.part || '').trim(), (t.label || '').trim()].filter(Boolean).join(' · '))}<div class="s">날 셈에서 빠짐</div>`;
  else when = '<span class="small">기록 없음</span>';
  const w = r.gap == null ? 0 : Math.min(7, Math.abs(r.gap));
  const gap = r.gap == null ? '' : r.gap < 0 ? `<i class="w${w}"></i>${-r.gap}일 거꾸로` : r.gap === 0 ? '같은 날' : `<i class="w${w}"></i>+${r.gap}일`;
  const why = r.back ? `<div class="s why">플롯은 ‘${esc(e.plot.time || '바로 이어짐')}’인데 끝난 날이 앞 화보다 ${-r.gap}일 앞이에요.</div>` : '';
  const end = r.back ? `<button type="button" class="btn small" data-action="tlFixDay" data-arg="${esc(g.key)}|${r.n}">날 고치기</button>` : `<span class="tl-gap">${gap}</span>`;
  return `<div class="tl-row${r.back ? ' back' : ''}"><a class="n" href="${base()}/review/${r.n}">${r.n}화</a>
    <div><div class="t">${esc(e.plot.title)}</div><div class="s">${esc(sub)}</div>${why}</div>
    <div>${when}</div>${r.back ? `<div><span class="tl-gap back"><i class="w${w}"></i>${-r.gap}일 거꾸로</span>${end}</div>` : end}</div>`;
}

/** 묶음 안 한 화의 고치기 줄: 반영한 화만 끝난 시점을, 본문이 없는 화는 플롯의 시점을 고친다 (저장은 저장 띠) */
function tlRowEdit(r) {
  const n = r.n;
  const e = ep(n);
  const i = epIndex(n);
  const t = e.time || {};
  const b = `episodes.${i}.time`;
  const cell = (path, kind, ph, aria) => `<input type="${kind === 'int' ? 'number' : 'text'}"${kind === 'int' ? ' min="0"' : ''} id="tl-${path}-${n}" data-bind="${b}.${path}" data-kind="${kind}" value="${esc(kind === 'int' ? (t[path] > 0 ? t[path] : '') : t[path] || '')}" placeholder="${ph}" aria-label="${n}화 ${aria}">`;
  const plot = e.text ? `<span class="small">${esc(e.plot.time || '바로 이어짐')}</span>`
    : `<input type="text" data-bind="episodes.${i}.plot.time" data-kind="text" value="${esc(e.plot.time || '')}" placeholder="바로 이어짐" aria-label="${n}화 플롯의 시점">`;
  if (e.status !== 'finalized') return `<div class="tl-in"><b>${n}화</b>${plot}<span class="small wide">${e.text ? '본문이 있어요. 상태 승인에서 반영하면 끝난 시점이 채워져요.' : '반영한 뒤에 끝난 시점을 적어요.'}</span></div>`;
  const dayCell = tlDated() ? `<input type="date" id="tl-day-${n}" min="${tlISO(1)}" data-tl-date="${b}.day" value="${tlISO(t.day)}" aria-label="${n}화 끝난 날짜">` : cell('day', 'int', '모름', '끝난 날수');
  return `<div class="tl-in"><b>${n}화</b>${plot}${dayCell}${cell('part', 'text', '시간대', '끝난 시간대')}${cell('label', 'text', tlDated() ? '계절 · 날씨' : '날짜 · 계절', '끝난 날의 메모')}</div>`;
}

function tlGroupCard(g, n) {
  const editing = S.tlEditGroup === g.key;
  const open = tlGroupOpen(g, n);
  const fin = g.rows.some((r) => ep(r.n).status === 'finalized' || !ep(r.n).text);
  const span = g.lo ? `${tlDated() ? `${tlShort(g.lo)} ~ ${tlShort(g.hi)} (${g.lo}~${g.hi}일째, ` : `${g.lo}~${g.hi}일째 (`}${g.hi - g.lo + 1}일 동안)` : '끝난 시점 기록 없음';
  const fold = editing ? '' : `<button type="button" class="btn small ghost" data-action="tlFold" data-arg="${esc(g.key)}" aria-expanded="${open}" aria-controls="tl-g-${esc(g.key)}-rows">${open ? '접기' : '펼치기'}</button>`;
  const edit = fin && open ? `<button type="button" class="btn small" data-action="tlEditGroupToggle" data-arg="${esc(g.key)}" aria-expanded="${editing}">${editing ? '다 고쳤어요' : '고치기'}</button>` : '';
  const head = `<div class="pf-head"><div><h2>${esc(g.label)}${editing ? ' <span class="small pf-state">고치는 중</span>' : ''}${!open && g.back ? ` <span class="chip bad">거꾸로 ${g.back}</span>` : ''}</h2>
    <div class="small">${g.s}~${g.e}화 · ${esc(span)}</div></div><span class="row">${fold}${edit}</span></div>`;
  if (!open) return `<section class="card pf-sec" id="tl-g-${esc(g.key)}">${head}</section>`;
  const rows = editing
    ? `<div class="tl-in head" aria-hidden="true"><span>화</span><span>플롯의 시점</span><span>끝난 ${tlDated() ? '날짜' : '날수'}</span><span>시간대</span><span>${tlDated() ? '계절 · 날씨' : '날짜 · 계절'}</span></div>${g.rows.map(tlRowEdit).join('')}`
    : `<div class="tl-rows">${g.rows.map((r) => tlRowRead(r, g)).join('')}</div>`;
  return `<section class="card pf-sec${editing ? ' editing' : ''}" id="tl-g-${esc(g.key)}">${head}
    <div id="tl-g-${esc(g.key)}-rows">${rows}</div>${editing ? '<p class="small">고치면 화면 아래 저장 띠로 저장해요. 날짜 · 요일 · 지난 날은 Canon이 다시 세요.</p>' : ''}</section>`;
}

function tlSetCard() {
  const tl = P().timeline;
  const editing = S.tlSetEdit;
  const head = `<div class="pf-head"><h2>설정${editing ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2><button type="button" class="btn small" data-action="tlSetToggle" aria-expanded="${editing}">${editing ? '다 고쳤어요' : '고치기'}</button></div>`;
  if (!editing) {
    const first = tlDated() ? tlDayLabel(1).replace(/^(\d+월)/, `${tlCalendar().first.getUTCFullYear()}년 $1`) : (tl.start || '').trim();
    return `<section class="card pf-sec" id="tl-set">${head}<dl class="pf-dl">
      <dt>기록</dt><dd>${tl.enabled ? '켜짐 · 상태 변경안에 끝난 시점과 새 기한을 적어요' : '꺼짐 · 상태 변경안에 시점을 적지 않고, 쓰기 · 검수에 시간 블록을 넣지 않아요'}</dd>
      <dt>1일째</dt><dd>${first ? esc(first) : '<span class="muted">정하지 않음</span>'}</dd>
      ${tlDated() && (tl.start || '').trim() ? `<dt>덧붙일 말</dt><dd>${esc(tl.start)}</dd>` : ''}
      <dt>세는 법</dt><dd>${tlDated() ? '날짜로 세요. 날짜를 비우면 ‘며칠째’로 세요.' : '‘며칠째’로 세요. 1일째 날짜를 정하면 ‘3월 6일 수요일 밤’처럼 날짜로 진행하고, 본문에 나온 날짜도 날수로 바꿔요.'}</dd></dl></section>`;
  }
  return `<section class="card pf-sec editing" id="tl-set">${head}
    <label class="check-row"><input type="checkbox" data-bind="timeline.enabled" data-kind="bool"${tl.enabled ? ' checked' : ''}> 작품 속 시간 기록하기 <span class="small">끄면 상태 변경안에 시점을 적지 않고, 쓰기 · 검수에 시간 블록을 넣지 않아요</span></label>
    <div class="tl-start">${input('1일째 날짜', 'timeline.start_date', { type: 'date', hint: '정해 두면 화마다 날짜로 보이고 요일 · 남은 날은 Canon이 세요. 판타지 달력처럼 날짜가 없으면 비워 두세요' })}
    ${input(tlDated() ? '덧붙일 말' : '1일째가 언제인가요 (글로)', 'timeline.start', { hint: tlDated() ? '계절, 시대처럼 날짜 밖의 것' : '예: 늦겨울, 왕국력 312년. 여기 적은 날짜 · 요일도 읽어요', placeholder: tlDated() ? '예: 초봄, 장마 직전' : '예: 늦겨울, 왕국력 312년' })}</div>
    <p class="small">켜고 끄기와 1일째는 화면 아래 저장 띠로 저장해요.</p></section>`;
}

function viewTimeline() {
  const p = P();
  const tl = p.timeline;
  const add = '<button type="button" class="btn primary" data-action="tlEditOpen" data-arg="new">+ 기한 더하기</button>';
  const head = (right) => header('작품 도구', '작품 속 시간', '화가 끝난 시점과 앞으로 올 기한이에요. 날짜 · 요일 · 남은 날은 Canon이 세요.', right);
  const n = tlNext();
  const day = tlDay(n);
  const dl = tlDeadlineRows(tl.deadlines, day);
  if (!p.episodes.some((e) => e.status === 'finalized') && !tl.deadlines.length) {
    const empty = S.tlEdit === 'new' ? `<section class="card" id="tl-dl"><h2>기한</h2>${tlForm(null)}</section>`
      : `<section class="card csh-empty"><div class="empty"><p>아직 반영한 화가 없어요. 화를 반영하면 끝난 시점이 여기에 쌓여요.</p>
        <p class="small">축제나 약속처럼 미리 정한 날은 지금 더해 둘 수 있어요.</p>${add}</div></section>`;
    return `${head('')}<div class="outline-wrap tl-wrap"><div class="tl-col">${empty}${tlSetCard()}</div></div>`;
  }
  const groups = tlGroups(p);
  const main = `<div class="tl-col">${tlNowCard(n, day, dl)}${tlDlCard(dl)}${groups.map((g) => tlGroupCard(g, n)).join('')}${tlSetCard()}</div>`;
  return `${head(S.tlEdit === 'new' ? '' : add)}${outlineDoc(tlTocHtml(), main, { cls: 'tl-wrap' })}`;
}

outlineSpy('tl-toc', {
  targets: () => [...document.querySelectorAll('#app .tl-col > .card[id]')].map((el) => [el.id, el]),
  set(key) {
    if (!key || key === S.tlCur) return;
    S.tlCur = key;
    outlineRefresh('tl-toc', tlTocHtml());
  },
});

document.addEventListener('submit', async (e) => {
  const f = e.target.closest('[data-tl-form]');
  if (!f) return;
  e.preventDefault();
  const id = f.dataset.tlForm;
  const cur = (P().timeline.deadlines || []).find((d) => d.id === id) || {};
  const body = { id, what: $('#tl-what').value.trim(), day: $('#tl-date') ? tlDayOf($('#tl-date').value) : parseInt($('#tl-day').value, 10) || 0, note: $('#tl-note').value.trim(), done_ep: cur.done_ep || 0 };
  if (!body.what) return toast('무엇의 기한인지 적어 주세요', true);
  await tlPut(body, id ? '기한을 고쳤어요' : '기한을 더했어요');
});

async function tlPut(body, msg) {
  await run('기한 저장하는 중', async () => {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/timeline/deadlines`, body);
    S.tlEdit = '';
    toast(msg);
  });
}

const tlFind = (id) => P().timeline.deadlines.find((d) => d.id === id);

Object.assign(actions, {
  tlEditOpen(id) {
    S.tlEdit = id || '';
    if (S.tlEdit && S.tlEdit !== 'new' && S.tlDlTab !== 'all') S.tlDlTab = (tlFind(S.tlEdit) || {}).done_ep > 0 ? 'closed' : 'open';
    S.focusTarget = S.tlEdit ? '#tl-what' : '#tl-dl h2';
    render();
  },
  tlDlTab(k) { S.tlDlTab = k; render(); },
  tlGo(id) {
    S.tlCur = id;
    outlineRefresh('tl-toc', tlTocHtml());
    actions.jumpTo(id);
  },
  tlFold(key) {
    const g = tlGroups(P()).find((x) => x.key === key);
    S.tlFold[key] = !(g && tlGroupOpen(g, tlNext()));
    render();
  },
  tlEditGroupToggle(key) {
    S.tlEditGroup = S.tlEditGroup === key ? '' : key;
    S.focusTarget = `#tl-g-${CSS.escape(key)} [data-action="tlEditGroupToggle"]`;
    render();
  },
  tlFixDay(arg) {
    const [key, n] = String(arg).split('|');
    S.tlEditGroup = key;
    S.focusTarget = `#tl-day-${n}`;
    render();
  },
  tlSetToggle() {
    S.tlSetEdit = !S.tlSetEdit;
    S.focusTarget = '#tl-set [data-action="tlSetToggle"]';
    render();
  },
  async tlClose(id) {
    const d = tlFind(id);
    await tlPut({ ...d, done_ep: Math.max(tlLastDone(), d.set_ep) }, `${d.what} 기한을 닫았어요`);
  },
  async tlReopen(id) { await tlPut({ ...tlFind(id), done_ep: 0 }, '기한을 다시 열었어요'); },
  async tlDrop(id) {
    const d = tlFind(id);
    if (!confirm(`'${d.what}' 기한을 지울까요? 되돌리기 기록에서도 지워져요.`)) return;
    await run('기한 지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/timeline/deadlines/${enc(id)}`);
      toast('기한을 지웠어요');
    });
  },
});

// ----- 상태 승인 화면 -----

/** 변경안의 끝난 시점(고칠 수 있음)과 기한 (새 기한 k, 닫힌 기한 o). 꺼졌고 변경안에도 없으면 빈칸. */
function tlDeltaCard(n, d, box) {
  const t = d.time || (d.time = { day: 0, part: '', label: '' });
  const added = d.deadlines_added || [];
  const done = d.deadlines_done || [];
  if (!tlOn() && !tlKnown(t) && !added.length && !done.length) return '';
  const prev = tlPrev(n);
  const day = t.day > 0 ? t.day : tlDay(n);
  const gap = t.day > 0 && prev && prev.time.day > 0 ? t.day - prev.time.day : null;
  const cell = (f, kind, label, ph) => (kind === 'int' && tlDated()
    ? `<div class="field"><label for="tl-d-${f}">날짜</label><input id="tl-d-${f}" type="date" min="${tlISO(1)}" data-tl-time="${f}" data-tl-ep="${n}" value="${tlISO(t[f])}"></div>`
    : `<div class="field"><label for="tl-d-${f}">${label}</label><input id="tl-d-${f}" type="${kind === 'int' ? 'number' : 'text'}"${kind === 'int' ? ' min="0"' : ''} data-tl-time="${f}" data-tl-ep="${n}" value="${esc(kind === 'int' ? (t[f] > 0 ? t[f] : '') : t[f] || '')}" placeholder="${ph}"></div>`);
  const have = P().timeline.deadlines;
  const rows = [
    ...added.map((x, i) => {
      const old = have.find((y) => y.id === x.id);
      return `<div class="change">${box('k' + i)}<label for="pk-k${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip confirmed">${old ? '날 바뀜' : '새 기한'}</span> <strong>${esc(x.what)}</strong>
        ${x.day > 0 ? `<span class="small">${old && old.day > 0 && old.day !== x.day ? `${esc(tlAt(old.day))} → ` : ''}${esc(tlAt(x.day))}${tlLeft(x, day) ? ` · ${tlLeft(x, day)}` : ''}</span>` : '<span class="small">날 모름</span>'}${x.note ? `<br><span class="small">“${esc(x.note)}”</span>` : ''}</label></div>`;
    }),
    ...done.map((id, i) => {
      const x = have.find((y) => y.id === id) || added.find((y) => y.id === id);
      return `<div class="change">${box('o' + i)}<label for="pk-o${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip finalized">닫힘</span> ${esc(x ? x.what : id)} <span class="small">${x && x.day > 0 ? esc(tlAt(x.day)) : ''}</span></label></div>`;
    }),
  ].join('');
  return `<section class="card"><div class="between"><h2>작품 속 시간</h2><span class="small">${prev ? `직전 ${prev.plot.number}화 끝: ${esc(tlWhen(prev.time))}` : '앞 화 시점 기록 없음'}${ep(n) && ep(n).plot.time ? ` · 플롯: ${esc(ep(n).plot.time)}` : ''}</span></div>
    <div class="small">${n}화가 끝난 시점이에요. 반영하면 다음 화를 쓸 때 들어가요. 틀렸으면 고치세요.${gap != null ? ` <strong style="color:${gap < 0 ? 'var(--red)' : 'inherit'}">직전 화에서 ${gap < 0 ? `${-gap}일 거꾸로` : gap === 0 ? '같은 날' : `${gap}일 지남`}</strong>` : ''}</div>
    ${tlDayLabel(t.day) ? `<div class="small">${tlDated() ? `${esc(tlDayLabel(t.day))}, ${t.day}일째예요` : `${t.day}일째는 ${esc(tlDayLabel(t.day))}이에요 (기준으로 계산)`}</div>` : ''}
    <div class="tl-time">${cell('day', 'int', '며칠째', '모름')}${cell('part', 'text', '시간대', '예: 밤, 오후 3시쯤')}${cell('label', 'text', tlDated() ? '계절 · 날씨' : '날짜 · 계절', tlDated() ? '예: 늦봄, 비 옴' : '예: 3월 5일 화요일, 늦봄')}</div>
    ${rows ? `<h3 style="margin-top:6px">기한</h3>${rows}` : ''}</section>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.tlTime) return;
  const d = S.deltas[el.dataset.tlEp];
  if (!d) return;
  d.time = d.time || { day: 0, part: '', label: '' };
  d.time[el.dataset.tlTime] = el.dataset.tlTime !== 'day' ? el.value : el.type === 'date' ? tlDayOf(el.value) : parseInt(el.value, 10) || 0;
});

// 화별 시점 표의 날짜 칸: 날짜를 날수로 바꿔 작품에 적는다 (저장은 저장 막대)
document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.bind === 'timeline.start_date') return render();  // 날짜로 세기 · 며칠째로 세기가 바뀐다
  if (!el.dataset || !el.dataset.tlDate) return;
  setPath(P(), el.dataset.tlDate, tlDayOf(el.value));
  markDirty();
  render();
});

/** 반영 기록의 시점과 기한 (없으면 빈칸). */
function tlHistory(h) {
  const items = [
    ...(tlKnown(h.time) ? [`끝난 시점: ${esc(tlWhen(h.time))}`] : []),
    ...(h.deadlines_added || []).map((x) => `기한: ${esc(x.what)}${x.day > 0 ? ` (${esc(tlAt(x.day))})` : ''}`),
    ...(h.deadlines_done || []).map((id) => { const x = P().timeline.deadlines.find((y) => y.id === id); return `기한 닫힘: ${esc(x ? x.what : id)}`; }),
  ];
  return items.length ? `<section class="card"><h2>작품 속 시간</h2><ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${items.map((x) => `<li>${x}</li>`).join('')}</ul></section>` : '';
}

// ----- 집필 화면 -----

/** 이번 화 플롯 칸의 시간 줄: 직전 화 끝, 플롯의 시점, 이 화가 끝난 시점, 사흘 안 · 지난 기한. */
/** 집필 화면 플롯 띠의 '작품 속 시간' 값: 직전 화 끝 · 플롯 시점 · 이 화 끝 · 사흘 안 기한을 줄마다. 없으면 빈 글 */
function tlLines(n) {
  if (!tlOn()) return '';
  const e = ep(n);
  const prev = tlPrev(n);
  const day = tlDay(n);
  const near = P().timeline.deadlines.filter((d) => tlIsOpen(d, n) && d.day > 0 && day > 0 && d.day - day <= 3);
  const parts = [
    prev ? `직전 화 끝: ${esc(tlWhen(prev.time))}` : '',
    e.plot.time ? `플롯: ${esc(e.plot.time)}` : '',
    tlKnown(e.time) ? `이 화 끝: ${esc(tlWhen(e.time))}` : '',
    ...near.map((d) => `${esc(d.what)} ${esc(tlLeft(d, day))}`),
  ].filter(Boolean);
  return parts.join('<br>');
}
