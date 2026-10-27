/* 작품 속 시간. app.js 의 S, actions, api, run, render, header, esc, P, input, base, ep, epIndex, saveIfDirty, toast 를 쓴다.
   화가 끝난 시점(Episode.time)과 앞으로 올 기한(Project.timeline.deadlines)을 보고 고친다. 서버는 canon/timeline.py.
   켜고 끄기 · 기준 · 화별 시점은 작품 저장(저장 띠)으로, 기한은 /timeline/deadlines 로 고친다(스냅샷도 함께).
   남은 날 · 지금 날수 계산(tlLeft, tlDay)은 timeline.left · current_day 와 같은 규칙이라 함께 고친다.
   상태 승인 화면의 시점 칸과 기한 고르기(tlDeltaCard, 키 k · o), 반영 기록(tlHistory), 집필 화면 플롯 칸(tlAside)도 여기 있다. */
'use strict';

Object.assign(S, {
  tlEdit: '',  // 고치는 기한 id. 'new' 는 새 기한 칸
});

(function tlStyle() {
  const css = `
.tl-now { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tl-now .num { font-size: 20px; font-weight: 800; }
.tl-table-wrap { overflow-x: auto; }
.tl-table { border-collapse: collapse; font-size: 13px; width: 100%; }
.tl-table th, .tl-table td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
.tl-table th { font-weight: 700; color: var(--text-2); background: var(--surface); white-space: nowrap; }
.tl-table input { width: 100%; min-width: 0; }
.tl-table input[type="number"] { width: 72px; }
.tl-gap { white-space: nowrap; color: var(--text-2); }
.tl-gap.back { color: var(--red); font-weight: 700; }
.tl-time { display: grid; grid-template-columns: 96px minmax(0, 1fr) minmax(0, 1.4fr); gap: 8px; }
@media (max-width: 640px) { .tl-time { grid-template-columns: 1fr; } }
/* 좁은 폭: 화별 시점 표를 화마다 카드로 쌓고 칸 이름을 위에 적는다 */
@media (max-width: 640px) {
  .tl-table thead { display: none; }
  .tl-table, .tl-table tbody { display: block; }
  .tl-table tr { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px 10px; padding: 12px 0; border-bottom: 1px solid var(--line); }
  .tl-table th, .tl-table td { display: block; padding: 0; border: none; }
  .tl-table th[scope="row"] { background: none; }
  .tl-table td.tl-title { align-self: center; font-weight: 700; }
  .tl-table td.tl-wide { grid-column: 1 / -1; }
  .tl-table td[data-label]::before { content: attr(data-label); display: block; margin-bottom: 2px; font-size: 12px; font-weight: 400; color: var(--muted); }
  .tl-table td.tl-gap:empty { display: none; }
  .tl-table input[type="number"] { width: 100%; }
}
.tl-dl { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line); }
.tl-dl.done { color: var(--muted); }
.tl-form { display: grid; grid-template-columns: minmax(0, 2fr) 96px minmax(0, 2fr) auto; gap: 8px; align-items: end; }
@media (max-width: 720px) { .tl-form { grid-template-columns: 1fr; } }`;
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

/** 기준 글에서 { first: 1일째 Date(UTC) | null, year: 연도를 아는지, wd: 1일째 요일 0=월 | null }. */
function tlCalendar() {
  const text = (P().timeline || {}).start || '';
  const w = text.match(/([월화수목금토일])요일/);
  const wd = w ? TL_WEEKDAYS.indexOf(w[1]) : null;
  const make = (y, m, d) => {
    const x = new Date(Date.UTC(2000, m - 1, d));
    x.setUTCFullYear(y, m - 1, d);  // Date.UTC 는 0~99년을 1900년대로 읽는다
    return x.getUTCMonth() === m - 1 && x.getUTCDate() === d ? x : null;  // 2월 30일 같은 날은 없음
  };
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

/** tlFmt 에 계산한 날짜 · 요일을 붙인다 (timeline.when). */
function tlWhen(t) {
  const cal = t ? tlDayLabel(t.day) : '';
  if (!cal) return tlFmt(t);
  const extra = (t.label || '').trim();
  const head = [`${t.day}일째`, (t.part || '').trim()].filter(Boolean).join(' ');
  return `${head} (${cal}${extra && !/\d+\s*(?:년|월|일)|요일/.test(extra) ? `, ${extra}` : ''})`;
}

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

function tlDeadlineRow(d, day) {
  const done = d.done_ep > 0;
  const left = done ? `${d.done_ep}화에 닫힘` : tlLeft(d, day) || '열림';
  const warn = !done && /지남/.test(left);
  if (S.tlEdit === d.id) return tlForm(d);
  return `<div class="tl-dl${done ? ' done' : ''}"><div><strong>${esc(d.what)}</strong>${d.day > 0 ? ` <span class="small">${d.day}일째${tlDayLabel(d.day) ? ` · ${esc(tlDayLabel(d.day))}` : ''}</span>` : ''}
      <span class="chip${warn ? ' draft' : ''}" style="${warn ? 'background:var(--amber-soft);color:var(--amber-ink)' : ''}">${esc(left)}</span>
      ${d.note ? `<div class="small">“${esc(d.note)}”</div>` : ''}<div class="small">${d.set_ep ? `${d.set_ep}화에 생김` : '처음부터'} · ${esc(d.id)}</div></div>
    <span class="row" style="gap:6px;flex-wrap:nowrap"><button type="button" class="btn small" data-action="tlEditOpen" data-arg="${esc(d.id)}">고치기</button>
      <button type="button" class="btn small" data-action="${done ? 'tlReopen' : 'tlClose'}" data-arg="${esc(d.id)}">${done ? '다시 열기' : '닫기'}</button>
      <button type="button" class="btn small ghost" data-action="tlDrop" data-arg="${esc(d.id)}" aria-label="${esc(d.what)} 지우기">지우기</button></span></div>`;
}

function tlForm(d) {
  const x = d || { id: '', what: '', day: 0, note: '' };
  return `<form class="tl-form" data-tl-form="${esc(x.id)}" style="padding:8px 0;border-bottom:1px solid var(--line)">
    <div class="field"><label for="tl-what">무엇의 기한</label><input id="tl-what" type="text" value="${esc(x.what)}" placeholder="예: 왕성 축제 첫날, 빚 갚을 날"></div>
    <div class="field"><label for="tl-day">며칠째</label><input id="tl-day" type="number" min="0" value="${x.day > 0 ? x.day : ''}" placeholder="모름"></div>
    <div class="field"><label for="tl-note">본문에 나온 말</label><input id="tl-note" type="text" value="${esc(x.note)}" placeholder="예: 사흘 뒤 자정까지"></div>
    <span class="row" style="gap:6px"><button type="submit" class="btn small primary">${x.id ? '저장' : '더하기'}</button><button type="button" class="btn small" data-action="tlEditOpen" data-arg="">취소</button></span></form>`;
}

function tlRows() {
  const eps = [...P().episodes].sort((a, b) => a.plot.number - b.plot.number);
  let last = 0;
  return eps.map((e) => {
    const n = e.plot.number;
    const i = epIndex(n);
    const t = e.time || {};
    const gap = t.day > 0 && last > 0 ? t.day - last : null;
    if (t.day > 0) last = t.day;
    const fin = e.status === 'finalized';
    const b = `episodes.${i}.time`;
    const cell = (path, kind, ph, aria) => `<input type="${kind === 'int' ? 'number' : 'text'}"${kind === 'int' ? ' min="0"' : ''} data-bind="${b}.${path}" data-kind="${kind}" value="${esc(kind === 'int' ? (t[path] > 0 ? t[path] : '') : t[path] || '')}" placeholder="${ph}" aria-label="${n}화 ${aria}">`;
    const gapText = gap == null ? '' : gap < 0 ? `${gap}일 · 거꾸로` : gap === 0 ? '같은 날' : `+${gap}일`;
    return `<tr><th scope="row"><a href="${base()}/review/${n}">${n}화</a></th><td class="tl-title">${esc(e.plot.title)}</td>
      <td class="tl-wide" data-label="플롯의 시점">${e.text ? `<span class="small">${esc(e.plot.time || '바로 이어짐')}</span>` : `<input type="text" data-bind="episodes.${i}.plot.time" data-kind="text" value="${esc(e.plot.time || '')}" placeholder="바로 이어짐" aria-label="${n}화 플롯의 시점">`}</td>
      ${fin ? `<td data-label="며칠째">${cell('day', 'int', '모름', '끝난 날수')}${tlDayLabel(t.day) ? `<div class="small">${esc(tlDayLabel(t.day))}</div>` : ''}</td><td data-label="시간대">${cell('part', 'text', '시간대', '끝난 시간대')}</td><td class="tl-wide" data-label="날짜 · 계절">${cell('label', 'text', '날짜 · 계절', '끝난 날짜')}</td>`
    : '<td colspan="3" class="small tl-wide">반영하면 채워져요</td>'}
      <td class="tl-gap${gap != null && gap < 0 ? ' back' : ''}" data-label="지난 날">${gapText}</td></tr>`;
  }).join('');
}

function viewTimeline() {
  const p = P();
  const tl = p.timeline || { enabled: true, start: '', deadlines: [] };
  const head = header('시간', '작품 속 시간', '화가 끝난 시점(며칠째, 시간대)과 앞으로 올 기한을 기록해요. AI는 상태 변경안에 이번 화가 끝난 시점과 새 기한만 적고, 남은 날은 Canon이 세요. 본문을 쓸 때는 직전 화 끝 시점, 이번 화 플롯의 시점, 열린 기한 몇 줄만 들어가서 화수가 늘어도 프롬프트가 거의 커지지 않아요.');
  const n = tlLastDone() + 1;
  const prev = tlPrev(n);
  const day = tlDay(n);
  const open = tl.deadlines.filter((d) => tlIsOpen(d, n));
  const near = open.filter((d) => d.day > 0 && day > 0 && d.day - day <= 3).length;
  const sum = `<section class="card"><div class="tl-now">
      <div><div class="small">지금 (${prev ? `${prev.plot.number}화 끝` : '기록 없음'})</div><div class="num">${esc(prev ? tlWhen(prev.time) : '-')}</div></div>
      <div><div class="small">열린 기한</div><div class="num">${open.length}</div></div>
      <div><div class="small">사흘 안 · 지난 기한</div><div class="num" style="${near ? 'color:var(--amber)' : ''}">${near}</div></div></div>
    <label class="check-row"><input type="checkbox" data-bind="timeline.enabled" data-kind="bool"${tl.enabled ? ' checked' : ''}> 작품 속 시간 기록하기 <span class="small">끄면 상태 변경안에 시점을 적지 않고, 쓰기 · 검수에 시간 블록을 넣지 않아요</span></label>
    ${input('1일째가 언제인가요', 'timeline.start', { hint: '날짜나 요일을 적으면 날마다 날짜 · 요일은 Canon이 계산해요. 비우면 날수만 세요', placeholder: '예: 2024년 3월 4일 월요일, 초봄' })}
    <div class="small">켜고 끄기와 1일째는 화면 아래 저장 띠로 저장해요. 기한은 바로 저장해요.</div></section>`;
  const sorted = [...tl.deadlines].sort((a, b) => (a.done_ep > 0) - (b.done_ep > 0) || (a.day <= 0) - (b.day <= 0) || a.day - b.day || a.set_ep - b.set_ep);
  const dls = `<section class="card"><div class="between"><h2>기한</h2>${S.tlEdit === 'new' ? '' : '<button type="button" class="btn small" data-action="tlEditOpen" data-arg="new">+ 기한 더하기</button>'}</div>
    <div class="small">축제, 결혼식, '사흘 안에' 같은 약속처럼 앞으로 올 날이에요. AI가 본문에서 찾은 기한은 상태 승인에서 골라 반영돼요. 직접 더한 기한은 ${tlLastDone() || 0}화에 생긴 것으로 기록돼요.</div>
    ${S.tlEdit === 'new' ? tlForm(null) : ''}
    ${sorted.map((d) => tlDeadlineRow(d, day)).join('') || (S.tlEdit === 'new' ? '' : '<div class="small" style="padding:8px 0">기한이 없어요.</div>')}</section>`;
  const table = p.episodes.length ? `<section class="card"><h2>화별 시점</h2>
    <div class="small">플롯의 시점은 직전 화에서 얼마나 지났는지(비우면 바로 이어짐), 끝난 시점은 반영한 화가 끝났을 때예요. 고치면 화면 아래 저장 띠로 저장해요.</div>
    <div class="tl-table-wrap"><table class="tl-table"><thead><tr><th scope="col">화</th><th scope="col">제목</th><th scope="col">플롯의 시점</th><th scope="col">며칠째</th><th scope="col">시간대</th><th scope="col">날짜 · 계절</th><th scope="col">지난 날</th></tr></thead>
    <tbody>${tlRows()}</tbody></table></div></section>` : '';
  return `${head}${sum}${dls}${table}`;
}

document.addEventListener('submit', async (e) => {
  const f = e.target.closest('[data-tl-form]');
  if (!f) return;
  e.preventDefault();
  const id = f.dataset.tlForm;
  const cur = (P().timeline.deadlines || []).find((d) => d.id === id) || {};
  const body = { id, what: $('#tl-what').value.trim(), day: parseInt($('#tl-day').value, 10) || 0, note: $('#tl-note').value.trim(), done_ep: cur.done_ep || 0 };
  if (!body.what) return toast('무엇의 기한인지 적어 주세요', true);
  await tlPut(body, id ? '기한을 고쳤어요' : '기한을 더했어요');
});

async function tlPut(body, msg) {
  await run('기한 저장 중', async () => {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/timeline/deadlines`, body);
    S.tlEdit = '';
    toast(msg);
  });
}

const tlFind = (id) => P().timeline.deadlines.find((d) => d.id === id);

Object.assign(actions, {
  tlEditOpen(id) { S.tlEdit = id || ''; render(); },
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
  const cell = (f, kind, label, ph) => `<div class="field"><label for="tl-d-${f}">${label}</label><input id="tl-d-${f}" type="${kind === 'int' ? 'number' : 'text'}"${kind === 'int' ? ' min="0"' : ''} data-tl-time="${f}" data-tl-ep="${n}" value="${esc(kind === 'int' ? (t[f] > 0 ? t[f] : '') : t[f] || '')}" placeholder="${ph}"></div>`;
  const have = P().timeline.deadlines;
  const rows = [
    ...added.map((x, i) => {
      const old = have.find((y) => y.id === x.id);
      return `<div class="change">${box('k' + i)}<label for="pk-k${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip confirmed">${old ? '날 바뀜' : '새 기한'}</span> <strong>${esc(x.what)}</strong>
        ${x.day > 0 ? `<span class="small">${old && old.day > 0 && old.day !== x.day ? `${old.day}일째 → ` : ''}${x.day}일째${tlLeft(x, day) ? ` · ${tlLeft(x, day)}` : ''}</span>` : '<span class="small">날 모름</span>'}${x.note ? `<br><span class="small">“${esc(x.note)}”</span>` : ''}</label></div>`;
    }),
    ...done.map((id, i) => {
      const x = have.find((y) => y.id === id) || added.find((y) => y.id === id);
      return `<div class="change">${box('o' + i)}<label for="pk-o${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip finalized">닫힘</span> ${esc(x ? x.what : id)} <span class="small">${x && x.day > 0 ? `${x.day}일째` : ''}</span></label></div>`;
    }),
  ].join('');
  return `<section class="card"><div class="between"><h2>작품 속 시간</h2><span class="small">${prev ? `직전 ${prev.plot.number}화 끝: ${esc(tlWhen(prev.time))}` : '앞 화 시점 기록 없음'}${ep(n) && ep(n).plot.time ? ` · 플롯: ${esc(ep(n).plot.time)}` : ''}</span></div>
    <div class="small">${n}화가 끝난 시점이에요. 반영하면 다음 화를 쓸 때 들어가요. 틀렸으면 고치세요.${gap != null ? ` <strong style="color:${gap < 0 ? 'var(--red)' : 'inherit'}">직전 화에서 ${gap < 0 ? `${-gap}일 거꾸로` : gap === 0 ? '같은 날' : `${gap}일 지남`}</strong>` : ''}</div>
    ${tlDayLabel(t.day) ? `<div class="small">${t.day}일째는 ${esc(tlDayLabel(t.day))}이에요 (기준으로 계산)</div>` : ''}
    <div class="tl-time">${cell('day', 'int', '며칠째', '모름')}${cell('part', 'text', '시간대', '예: 밤, 오후 3시쯤')}${cell('label', 'text', '날짜 · 계절', '예: 3월 5일 화요일, 늦봄')}</div>
    ${rows ? `<h3 style="margin-top:6px">기한</h3>${rows}` : ''}</section>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.tlTime) return;
  const d = S.deltas[el.dataset.tlEp];
  if (!d) return;
  d.time = d.time || { day: 0, part: '', label: '' };
  d.time[el.dataset.tlTime] = el.dataset.tlTime === 'day' ? parseInt(el.value, 10) || 0 : el.value;
});

/** 반영 기록의 시점과 기한 (없으면 빈칸). */
function tlHistory(h) {
  const items = [
    ...(tlKnown(h.time) ? [`끝난 시점: ${esc(tlWhen(h.time))}`] : []),
    ...(h.deadlines_added || []).map((x) => `기한: ${esc(x.what)}${x.day > 0 ? ` (${x.day}일째)` : ''}`),
    ...(h.deadlines_done || []).map((id) => { const x = P().timeline.deadlines.find((y) => y.id === id); return `기한 닫힘: ${esc(x ? x.what : id)}`; }),
  ];
  return items.length ? `<section class="card"><h2>작품 속 시간</h2><ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${items.map((x) => `<li>${x}</li>`).join('')}</ul></section>` : '';
}

// ----- 집필 화면 -----

/** 이번 화 플롯 칸의 시간 줄: 직전 화 끝, 플롯의 시점, 이 화가 끝난 시점, 사흘 안 · 지난 기한. */
function tlAside(n) {
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
  return parts.length ? `<div class="field"><span class="small">작품 속 시간</span><div style="font-size:0.8125rem;line-height:1.6">${parts.join('<br>')}</div></div>` : '';
}
