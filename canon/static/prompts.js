/* 프롬프트 관리 (작품 밖 화면 #/prompts[/<갈래>|/topic/<꼬리표>|/piece/<조각>|/sets|/set/<판>]). 서버는 canon/routes/prompts.py, 표는 prompts.KINDS · PIECES.
   Canon 이 AI 에게 보내는 프롬프트를 호출 갈래(갈래별)와 주제 꼬리표(주제별)로 찾아 읽는다. 조각마다 자리 · 코드 출처 · 견본 글을 보인다.
   견본은 놀이터의 예시 작품(빈 값) · 예시 장편(':serial') · 고른 작품이고, 작품은 읽기만 한다.
   실험 판(promptset.py)은 조각 글을 고친 판이다. 견본 요청 · 놀이터에만 끼우고 실제 집필 요청에는 넣지 않는다. 판 칸은 S.pcSetForm, 칸을 벗어나면 저장한다.
   상태: S.pcReg 표(한 번 읽음), S.pcView 'kind' · 'topic' · 'piece' · 'sets' · 'set', S.pcData 지금 보는 응답, S.pcSets 판 목록, S.pcSample 견본, S.pcQ 찾기 글, S.pcOpen 펼친 조각 */
'use strict';

S.pcOpen = new Set();
S.pcSample = '';
S.pcQ = '';

const PC_SERIAL = ':serial';
// 자리 머리의 캐시 설명 (prompts.PLACES 차례)
const PC_PLACE_NOTE = {
  system: '캐시 앞부분 · 작품마다 같아요', front: '캐시 앞부분 · 작품마다 같아요', tail: '화마다 바뀌어요', instruction: '화마다 바뀌어요',
  second: '따로 부르는 호출이에요', send: 'Gemini · 로컬 백엔드가 보내기 직전에 붙여요',
};

async function pcLoad(a, b) {
  if (!S.pcReg) S.pcReg = await api('GET', '/prompts/kinds');
  const q = S.pcSample ? `?project=${enc(S.pcSample)}` : '';
  const [view, path] = a === 'topic' ? ['topic', `/prompts/topics/${enc(b || 'style')}`]
    : a === 'piece' && b ? ['piece', `/prompts/pieces/${enc(b)}`]
      : a === 'sets' ? ['sets', '/promptsets'] : a === 'set' && b ? ['set', `/promptsets/${enc(b)}`] : ['kind', `/prompts/kinds/${enc(a || 'episode')}`];
  const ticket = (S.pcTicket = (S.pcTicket || 0) + 1);
  const [data, list] = await Promise.all([api('GET', path + (view === 'sets' ? '' : q)), view === 'set' ? api('GET', '/promptsets') : null]);
  if (ticket !== S.pcTicket) return;  // 그 사이 다른 화면이나 견본을 골랐다. 늦게 온 응답은 버린다 (보기와 데이터를 함께 바꾼다)
  S.pcView = view;
  S.pcData = data;
  if (view === 'sets') S.pcSets = data.sets;
  if (list) S.pcSets = list.sets;
  if (view === 'set') pcSetPut(data);
}

/** 판 미리보기를 받아 칸(S.pcSetForm)을 맞춘다. 저장한 뒤에만 부르므로 잃는 고침은 없다 */
function pcSetPut(d) {
  S.pcData = d;
  const ps = d.set;
  S.pcSetForm = { name: ps.name, kind: ps.kind, note: ps.note, changes: ps.changes.map((c) => ({ piece: c.piece, text: c.text })) };
  S.pcSetDirty = false;
}

/** 왼쪽 갈래 목록 (순수 함수, tests/test_prompts_page_js.py): 조립 보기가 있는 갈래를 묶음 차례로, 나머지는 '표에만' 아래에 묶음별로.
    q 를 주면 이름 · 열쇠 · 요청 함수에 그 글이 든 갈래만 */
function pcGroups(reg, q = '') {
  const t = q.trim().toLowerCase();
  const hit = (k) => !t || [k.label, k.id, k.request, k.system].some((x) => String(x || '').toLowerCase().includes(t));
  const pick = (view) => reg.groups.map((g) => ({ group: g, kinds: reg.kinds.filter((k) => k.group === g && !!k.view === view && hit(k)) }))
    .filter((x) => x.kinds.length);
  return { view: pick(true), table: pick(false) };
}

/** 한 꼬리표를 단 조각을 자리 차례로 모은다 (순수 함수). 조각마다 들어가는 갈래 이름을 붙인다. 보내기 직전 조각은 '모든 갈래' */
function pcTopic(reg, tag) {
  const order = reg.places.map(([id]) => id);
  const label = Object.fromEntries(reg.kinds.map((k) => [k.id, k.label]));
  return reg.pieces.filter((x) => x.tags.includes(tag))
    .map((x, i) => ({ ...x, i, kindLabels: reg.send.includes(x.id) ? ['모든 갈래'] : x.kinds.map((k) => label[k] || k) }))
    .sort((a, b) => (order.indexOf(a.place) - order.indexOf(b.place)) || (a.i - b.i));
}

/** 꼬리표마다 조각 수 (순수 함수) */
function pcTagCounts(reg) {
  return Object.fromEntries(reg.tags.map(([id]) => [id, reg.pieces.filter((x) => x.tags.includes(id)).length]));
}

// 횟수 처방: '열에 셋쯤', '화에 셋까지', '한두 번', '3~7개', '세 줄 넘게' 같은 숫자 지시. 표시만 하고 판정에 쓰지 않는다
const PC_COUNT_RX = /열에\s*[가-힣]+쯤|(?:화|장면|문단|아크)(?:에|마다)\s*(?:[가-힣]+|\d+)\s*(?:번|개|줄)?\s*(?:까지|이하|안팎)|한두\s*번|\d+\s*~\s*\d+\s*(?:개|번|줄|문장|자|화)|(?:한|두|세|네|다섯|\d+)\s*(?:줄|번|개|문장)\s*(?:넘게|이하|까지)/g;

/** 조각 글 속 횟수 처방 (순수 함수): 처음 나온 차례로 겹치지 않게, 다섯까지 */
function pcCounts(text) {
  const out = [];
  for (const m of String(text || '').matchAll(PC_COUNT_RX)) {
    const s = m[0].replace(/\s+/g, ' ').trim();
    if (!out.includes(s)) out.push(s);
    if (out.length >= 5) break;
  }
  return out;
}

/** 찾기 글이 조각에 맞는지 (순수 함수): 이름 · 코드 이름 · 글 */
function pcMatch(x, q) {
  const t = (q || '').trim().toLowerCase();
  return !t || [x.title, x.source, x.id, x.text].some((v) => String(v || '').toLowerCase().includes(t));
}

const pcKindName = (id) => esc((S.pcReg.kinds.find((k) => k.id === id) || {}).label || id);
const pcNum = (v) => Number(v || 0).toLocaleString();
const pcTagChips = (tags) => tags.map((t) => `<a class="chip" href="#/prompts/topic/${enc(t)}">${esc((S.pcReg.tags.find(([id]) => id === t) || [t, t])[1])}</a>`).join('');

function viewPrompts() {
  const reg = S.pcReg;
  if (!reg || !S.pcData) return header('작품 밖 도구', '프롬프트 관리', '');
  const topic = S.pcView === 'topic';
  const sets = S.pcView === 'sets' || S.pcView === 'set';
  const axis = sets ? 'sets' : topic ? 'topic' : 'kind';
  const segBtn = (id, label) => `<button type="button" data-action="pcAxis" data-arg="${id}" aria-pressed="${axis === id}">${label}</button>`;
  const seg = `<div class="seg" role="group" aria-label="보는 축">${segBtn('kind', '갈래별')}${segBtn('topic', '주제별')}${segBtn('sets', '실험 판')}</div>`;
  const head = header('작품 밖 도구', '프롬프트 관리', 'Canon이 AI에게 보내는 프롬프트를 실제 요청과 같은 함수로 조립해 갈래와 주제로 찾아 읽어요.', seg);
  const works = (S.projects || []).filter((x) => !x.play);
  const opt = (v, label) => `<option value="${esc(v)}"${v === S.pcSample ? ' selected' : ''}>${esc(label)}</option>`;
  const bar = `<div class="row pc-bar"><div class="field"><label for="pc-q">찾기</label><input id="pc-q" type="search" data-pc="q" value="${esc(S.pcQ)}" placeholder="갈래 · 조각 이름이나 글"></div>
    <div class="field"><label for="pc-sample">견본</label><select id="pc-sample" data-pc="sample">${opt('', '예시 작품 (6화 단편)')}${opt(PC_SERIAL, '예시 장편')}${works.map((w) => opt(w.name, w.title || w.name)).join('')}</select></div></div>`;
  const body = S.pcView === 'piece' ? pcPieceView(S.pcData) : topic ? pcTopicView(S.pcData) : S.pcView === 'set' ? pcSetView(S.pcData)
    : S.pcView === 'sets' ? pcSetsHome() : pcKindView(S.pcData);
  const nav = sets ? pcSetNav() : topic ? pcTagNav() : pcKindNav();
  return `${head}${bar}<div class="cols"><nav class="col pc-nav" aria-label="${sets ? '실험 판' : topic ? '주제' : '갈래'} 목록">${nav}</nav><div class="col wide">${body}</div></div>`;
}

function pcKindNav() {
  const { view, table } = pcGroups(S.pcReg, S.pcQ);
  const cur = S.pcView === 'kind' && S.pcData.kind ? S.pcData.kind.id : '';
  const link = (k) => `<a href="#/prompts/${enc(k.id)}"${k.id === cur ? ' aria-current="page"' : ''}>${esc(k.label)}</a>`;
  const block = (rows) => rows.map((g) => `<h3 class="small">${esc(g.group)}</h3>${g.kinds.map(link).join('')}`).join('');
  const rest = table.reduce((n, g) => n + g.kinds.length, 0);
  return `<section class="card">${block(view) || '<p class="small">맞는 갈래가 없어요.</p>'}
    ${rest ? `<details${S.pcQ.trim() || table.some((g) => g.kinds.some((k) => k.id === cur)) ? ' open' : ''}><summary class="small">표에만 · ${rest}갈래</summary>${block(table)}</details>` : ''}</section>`;
}

function pcTagNav() {
  const counts = pcTagCounts(S.pcReg);
  const cur = S.pcData.tag;
  return `<section class="card">${S.pcReg.tags.map(([id, label]) => `<a href="#/prompts/topic/${enc(id)}"${id === cur ? ' aria-current="page"' : ''}>${esc(label)} <span class="small">${counts[id]}</span></a>`).join('')}</section>`;
}

/** 조각 줄 하나: 이름 · 꼬리표 · 코드 이름 · 글자 수(추정 토큰) · 횟수 처방. 펼치면 들어가는 조건과 견본 글 */
function pcPieceRow(x, extra = '') {
  const counts = pcCounts(x.text);
  const miss = x.found === false ? '<span class="chip">이 견본에는 없음</span>' : '';
  const size = x.chars ? `<span class="small">${pcNum(x.chars)}자${x.tokens ? ` · 약 ${pcNum(x.tokens)}토큰` : ''}</span>` : '<span class="small">빈 글</span>';
  const mark = counts.length ? `<span class="chip warn" title="${esc(counts.join(' · '))}">횟수 처방</span>` : '';
  const key = `${S.pcView}:${x.id}`;
  return `<details class="pc-piece" data-pc-open="${esc(key)}"${S.pcOpen.has(key) ? ' open' : ''}>
    <summary><strong>${esc(x.title)}</strong> ${pcTagChips(x.tags)} <code>${esc(x.source)}</code> ${size} ${mark} ${miss}</summary>
    <div class="pc-more">${extra}${x.when ? `<p class="small">들어가는 조건: ${esc(x.when)}</p>` : ''}${counts.length ? `<p class="small">횟수 처방: ${esc(counts.join(' · '))}</p>` : ''}
      ${x.text ? `<pre class="brief mono" tabindex="0">${esc(x.text)}</pre>` : `<p class="small">${x.id.endsWith('_req') ? '요청 전체를 만드는 함수예요. 아래 요청 전문에서 보세요.' : '이 견본에서는 들어갈 조건이 맞지 않아 비어 있어요.'}</p>`}
      <a class="small" href="#/prompts/piece/${enc(x.id)}">이 조각만 보기</a></div></details>`;
}

function pcKindView(d) {
  const k = d.kind;
  const meta = [k.stage && `단계 ${k.stage}`, `응답 ${k.response || '글'}`, `시스템 <code>${esc(k.system)}</code>`, `요청 <code>${esc(k.request)}</code>`,
    k.caller && `호출 <code>${esc(k.caller)}</code>`].filter(Boolean).join(' · ');
  const also = k.also.length ? `<p class="small">경우에 따라: ${k.also.map((x) => `<code>${esc(x)}</code>`).join(' · ')}</p>` : '';
  const top = `<section class="card"><h2>${esc(k.label)}</h2><p class="small">${meta}</p>${also}`;
  if (!k.view) {
    const rows = (d.pieces || []).map((x) => pcPieceRow(x)).join('');
    return `${top}<p class="small">이 갈래는 표에만 있어요. 조립한 견본은 다음 단계에서 보여요.</p>${rows}</section>`;
  }
  const s = d.sample;
  const where = `견본: ${esc(s.title)}${s.n ? ` ${s.n}화` : ''}`;
  if (d.error) return `${top}<p class="small">${where}</p><div class="note warn" role="alert">${esc(d.error)}</div></section>`;
  const places = S.pcReg.places.map(([id, label]) => {
    const rows = d.pieces.filter((x) => x.place === id && pcMatch(x, S.pcQ));
    if (!rows.length) return '';
    const chars = rows.filter((x) => x.found !== false).reduce((n, x) => n + x.chars, 0);
    return `<section class="card"><div class="between"><h3>${esc(label)}</h3><span class="small">${PC_PLACE_NOTE[id]}${id === 'send' ? '' : ` · ${pcNum(chars)}자`}</span></div>${rows.map((x) => pcPieceRow(x)).join('')}</section>`;
  }).join('');
  const full = S.pcFull ? `<pre class="brief mono" tabindex="0" aria-label="요청 전문">[시스템]\n${esc(d.system)}\n\n[요청]\n${esc(d.prompt)}</pre>` : '';
  return `${top}<p class="small">${where} · 합계 ${pcNum(d.chars)}자 · 약 ${pcNum(d.tokens)}토큰(추정)${d.schema ? ` · 응답 스키마 ${esc(d.schema)}` : ''}</p>
    <div class="row"><button type="button" class="btn" data-action="pcPlayground">놀이터에서 열기</button><button type="button" class="btn" data-action="pcSetNew" data-arg="${esc(k.id)}">이 갈래로 실험 판 만들기</button><button type="button" class="btn ghost" data-action="pcFull">${S.pcFull ? '요청 전문 닫기' : '요청 전문 보기'}</button></div>${full}</section>
    ${places || '<section class="card empty"><p class="small">찾기에 맞는 조각이 없어요.</p></section>'}`;
}

function pcTopicView(d) {
  const reg = S.pcReg;
  const meta = Object.fromEntries(pcTopic(reg, d.tag).map((x) => [x.id, x]));
  const label = Object.fromEntries(reg.places);
  const rows = d.pieces.map((x) => ({ ...x, ...meta[x.id], text: x.text, chars: x.chars })).filter((x) => pcMatch(x, S.pcQ))
    .sort((a, b) => (reg.places.findIndex(([id]) => id === a.place) - reg.places.findIndex(([id]) => id === b.place)) || (a.i - b.i));
  const where = (x) => `<p class="small">${esc(label[x.place])} · ${x.kindLabels.length ? x.kindLabels.map(esc).join(', ') : '어느 갈래 표에도 없음'}${x.sample_kind ? ` · 견본은 ${pcKindName(x.sample_kind)}${josa(pcKindName(x.sample_kind), '으로', '로')} 조립` : ''}</p>`;
  const marked = rows.filter((x) => pcCounts(x.text).length).length;
  return `<section class="card"><h2>${esc(d.label)}</h2><p class="small">조각 ${rows.length}개 · 횟수 처방 ${marked}개 · 같은 뜻의 지시가 여러 자리에 있으면 여기서 나란히 견줘요.</p>
    ${rows.map((x) => pcPieceRow(x, where(x))).join('') || '<p class="small">찾기에 맞는 조각이 없어요.</p>'}</section>`;
}

function pcPieceView(d) {
  const label = Object.fromEntries(S.pcReg.places);
  const kinds = d.kinds.map((k) => { const v = S.pcReg.kinds.find((x) => x.id === k); return `<a href="#/prompts/${enc(k)}">${esc(v ? v.label : k)}</a>`; }).join(' · ');
  const counts = pcCounts(d.text);
  return `<section class="card"><h2>${esc(d.title)}</h2>
    <p class="small">${esc(label[d.place])} · 코드 <code>${esc(d.source)}</code>${d.when ? ` · ${esc(d.when)}` : ''}</p><div class="row">${pcTagChips(d.tags)}</div>
    <p class="small">들어가는 갈래: ${kinds || '없음'}</p>${counts.length ? `<p class="small">횟수 처방: ${esc(counts.join(' · '))}</p>` : ''}
    ${d.text ? `<pre class="brief mono" tabindex="0">${esc(d.text)}</pre>` : '<p class="small">견본 글이 없어요.</p>'}</section>`;
}

// 펼친 조각을 기억한다 (다시 그려도 남긴다). details 의 toggle 은 거품이 없어 잡는 단계에서 듣는다
document.addEventListener('toggle', (e) => {
  const id = e.target.dataset && e.target.dataset.pcOpen;
  if (id === undefined) return;
  if (e.target.open) S.pcOpen.add(id);
  else S.pcOpen.delete(id);
}, true);

document.addEventListener('input', (e) => {
  if (!e.target.dataset || e.target.dataset.pc !== 'q' || S.route[0] !== 'prompts') return;
  S.pcQ = e.target.value;
  render();
  const el = $('#pc-q');
  if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
});
document.addEventListener('change', (e) => {
  if (!e.target.dataset || e.target.dataset.pc !== 'sample' || S.route[0] !== 'prompts') return;
  S.pcSample = e.target.value;
  run('견본을 조립하는 중', () => pcLoad(...S.route.slice(1)));
});

Object.assign(actions, {
  pcAxis(axis) {
    location.hash = axis === 'topic' ? '#/prompts/topic/style' : axis === 'sets' ? '#/prompts/sets' : '#/prompts';
  },
  pcFull() {
    S.pcFull = !S.pcFull;
    render();
  },
  /** 조립한 시스템 · 요청을 새 놀이터 세션으로 연다. 놀이터의 불러오기와 같은 조립이라 출처 · 응답 스키마 · 단계가 남는다 */
  async pcPlayground() {
    const d = S.pcData;
    const s = d.sample;
    await run('놀이터 세션을 만드는 중', async () => {
      const x = await api('POST', '/promptlab', {});
      await api('POST', `/promptlab/${enc(x.id)}/load`, { kind: d.kind.id, project: s.project, n: s.n });
      location.hash = `#/promptlab/${enc(x.id)}`;
    }, { render: 'never' });
  },
});

// ----- 실험 판 -----

/** 줄 단위 차이 (순수 함수, tests/test_prompts_page_js.py): 원래 글 a 와 고친 글 b 의 줄을 LCS 로 맞춰 [{op, text}] (op ' ' 같음 · '-' 뺌 · '+' 더함) */
function pcLineDiff(a, b) {
  const x = String(a || '').split('\n');
  const y = String(b || '').split('\n');
  const n = x.length;
  const m = y.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) for (let j = m - 1; j >= 0; j -= 1) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { out.push({ op: ' ', text: x[i] }); i += 1; j += 1; } else if (L[i + 1][j] >= L[i][j + 1]) { out.push({ op: '-', text: x[i] }); i += 1; } else { out.push({ op: '+', text: y[j] }); j += 1; }
  }
  while (i < n) { out.push({ op: '-', text: x[i] }); i += 1; }
  while (j < m) { out.push({ op: '+', text: y[j] }); j += 1; }
  return out;
}

/** 차이를 그린다: 바뀐 줄과 그 앞뒤 한 줄만, 나머지 같은 줄은 '… n줄 같음'으로 접는다 */
function pcDiffHtml(a, b) {
  const rows = pcLineDiff(a, b);
  if (!rows.some((r) => r.op !== ' ')) return '<p class="small">원래 글과 같아요.</p>';
  const near = (k) => rows.slice(Math.max(0, k - 1), k + 2).some((r) => r.op !== ' ');
  const out = [];
  let hid = 0;
  rows.forEach((r, k) => {
    if (r.op === ' ' && !near(k)) { hid += 1; return; }
    if (hid) { out.push(`<div class="pc-diff-skip">… ${hid}줄 같음</div>`); hid = 0; }
    const word = r.op === '+' ? '더한 줄: ' : r.op === '-' ? '뺀 줄: ' : '';
    out.push(`<div class="pc-diff-${r.op === '+' ? 'add' : r.op === '-' ? 'del' : 'same'}"><span aria-hidden="true">${r.op}</span>${word ? `<span class="sr-only">${word}</span>` : ''} ${esc(r.text)}</div>`);
  });
  if (hid) out.push(`<div class="pc-diff-skip">… ${hid}줄 같음</div>`);
  return `<div class="pc-diff mono" role="group" aria-label="줄 단위 차이">${out.join('')}</div>`;
}

const PC_SET_STATE = { applied: ['바꿈', 'ok'], same: ['원래 글과 같음', ''], absent: ['이 견본에는 없음', 'warn'], missing: ['없는 조각', 'bad'] };

function pcSetNav() {
  const list = S.pcSets || [];
  const cur = S.pcView === 'set' && S.pcData.set ? S.pcData.set.id : '';
  return `<section class="card">${list.map((x) => `<a href="#/prompts/set/${enc(x.id)}"${x.id === cur ? ' aria-current="page"' : ''}>${esc(x.name)} <span class="small">${esc(x.kind_label)} · ${x.changes.length}조각</span></a>`).join('') || '<p class="small">아직 실험 판이 없어요.</p>'}
    <button type="button" class="btn small" data-action="pcSetNew" data-arg="episode">+ 새 실험 판 만들기</button></section>`;
}

function pcSetsHome() {
  const list = S.pcSets || [];
  if (!list.length) {
    return `<section class="card empty"><h2>아직 실험 판이 없어요</h2><p class="small">조각 글을 고친 판을 만들어 견본 요청에 끼워 보고, 놀이터에서 원래 판과 블라인드로 견줘요. 판은 실제 집필 요청에는 들어가지 않아요.</p></section>`;
  }
  return `<div class="grid-auto">${list.map((x) => `<a class="card" href="#/prompts/set/${enc(x.id)}"><h3>${esc(x.name)}</h3><div class="small">${esc(x.kind_label)} · 바꾼 조각 ${x.changes.length}개${x.missing.length ? ` · 없는 조각 ${x.missing.length}개` : ''} · ${esc(fmtDateTime(x.updated_at))}</div></a>`).join('')}</div>`;
}

function pcSetView(d) {
  const f = S.pcSetForm;
  const reg = S.pcReg;
  const rows = Object.fromEntries((d.rows || []).map((r) => [r.piece, r]));
  const pieces = Object.fromEntries((d.pieces || []).map((x) => [x.id, x]));
  const kinds = reg.kinds.filter((k) => k.view).map((k) => `<option value="${esc(k.id)}"${k.id === f.kind ? ' selected' : ''}>${esc(k.label)}</option>`).join('');
  const head = `<section class="card"><div class="grid-2"><div class="field"><label for="pc-set-name">이름</label><input id="pc-set-name" type="text" data-pc-set="name" value="${esc(f.name)}" maxlength="60"></div>
      <div class="field"><label for="pc-set-kind">견본 갈래</label><select id="pc-set-kind" data-pc-set="kind">${kinds}</select></div></div>
      <div class="field"><label for="pc-set-note">메모</label><input id="pc-set-note" type="text" data-pc-set="note" value="${esc(f.note)}" maxlength="400" placeholder="무엇을 바꿔 보려는지"></div>
      <p class="small">판은 놀이터와 블라인드 비교에만 끼우고 실제 집필 요청에는 넣지 않아요.</p>
      <div class="row"><button type="button" class="btn primary" data-action="pcSetOpen" data-arg="blind">놀이터에서 원래 판과 견주기</button><button type="button" class="btn" data-action="pcSetOpen" data-arg="">놀이터에서 열기</button>
        <span class="small" id="pc-set-saved">${S.pcSetDirty ? '저장하지 않은 고침이 있어요' : '칸을 벗어나면 저장해요'}</span></div></section>`;
  if (d.error) return `${head}<div class="note warn" role="alert">${esc(d.error)}</div>`;
  const cards = f.changes.map((c, i) => {
    const r = rows[c.piece] || { state: reg.pieces.some((x) => x.id === c.piece) ? 'absent' : 'missing', original: (pieces[c.piece] || {}).text || '' };
    const [label, cls] = PC_SET_STATE[r.state] || ['', ''];
    const title = (reg.pieces.find((x) => x.id === c.piece) || {}).title || c.piece;
    return `<section class="card"><div class="between"><h3>${esc(title)} <code>${esc(c.piece)}</code></h3><div class="row"><span class="chip${cls ? ` ${cls}` : ''}">${label}</span>
        <button type="button" class="btn small" data-action="pcSetDrop" data-arg="${i}">빼기</button></div></div>
      ${r.state === 'missing' ? '<p class="small">코드에서 사라진 조각이라 끼우지 않아요.</p>' : ''}
      <div class="field"><label for="pc-set-text-${i}" class="sr-only">${esc(title)} 바꾼 글</label><textarea id="pc-set-text-${i}" class="mono" rows="6" data-pc-set="text" data-i="${i}">${esc(c.text)}</textarea></div>
      ${r.state === 'missing' ? '' : pcDiffHtml(r.original, c.text)}</section>`;
  }).join('');
  const used = new Set(f.changes.map((c) => c.piece));
  const free = (d.pieces || []).filter((x) => !used.has(x.id) && x.text);
  const add = free.length ? `<section class="card"><div class="row"><div class="field"><label for="pc-set-add">조각 더하기</label><select id="pc-set-add">${free.map((x) => `<option value="${esc(x.id)}">${esc(x.title)} (${esc((reg.places.find(([id]) => id === x.place) || ['', ''])[1])})</option>`).join('')}</select></div>
      <button type="button" class="btn" data-action="pcSetAdd">더하기</button></div></section>` : '';
  const s = d.sample;
  const full = S.pcFull ? `<pre class="brief mono" tabindex="0" aria-label="판을 끼운 요청 전문">[시스템]\n${esc(d.applied.system)}\n\n[요청]\n${esc(d.applied.prompt)}</pre>` : '';
  const preview = `<section class="card"><div class="between"><h3>판을 끼운 견본 요청</h3><span class="small">${esc(s.title)}${s.n ? ` ${s.n}화` : ''} · ${pcNum(d.chars)}자 · 약 ${pcNum(d.tokens)}토큰(추정)</span></div>
      <div class="row"><button type="button" class="btn ghost" data-action="pcFull">${S.pcFull ? '요청 전문 닫기' : '요청 전문 보기'}</button><button type="button" class="btn small" data-action="pcSetCopy">복제</button><button type="button" class="btn small danger" data-action="pcSetDelete">지우기</button></div>${full}</section>`;
  return `${head}${cards || '<section class="card empty"><p class="small">아래에서 바꿀 조각을 더해요.</p></section>'}${add}${preview}`;
}

/** 판 칸을 저장하고 미리보기를 다시 받는다. quiet 면 덮개 없이 (칸을 벗어날 때) */
async function pcSetSave(quiet = false) {
  if (!S.pcSetForm || !S.pcData.set) return;
  const id = S.pcData.set.id;
  const q = S.pcSample ? `?project=${enc(S.pcSample)}` : '';
  const save = async () => { const d = await api('PUT', `/promptsets/${enc(id)}${q}`, S.pcSetForm); if (S.pcData.set && S.pcData.set.id === id) pcSetPut(d); };
  if (!quiet) return run('실험 판을 저장하는 중', save);
  try { await save(); render(); } catch (e) { toast(e.message, true); }
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.pcSet || S.route[0] !== 'prompts' || !S.pcSetForm) return;
  if (el.dataset.pcSet === 'text') S.pcSetForm.changes[Number(el.dataset.i)].text = el.value;
  else S.pcSetForm[el.dataset.pcSet] = el.value;
  S.pcSetDirty = true;
  const m = $('#pc-set-saved');
  if (m) m.textContent = '저장하지 않은 고침이 있어요';
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.pcSet || S.route[0] !== 'prompts' || !S.pcSetForm) return;
  if (el.dataset.pcSet === 'kind') S.pcSetForm.kind = el.value;
  pcSetSave(true);
});

Object.assign(actions, {
  async pcSetNew(kind) {
    await run('실험 판을 만드는 중', async () => {
      const ps = await api('POST', '/promptsets', { kind: kind || 'episode' });
      S.pcSets = null;
      location.hash = `#/prompts/set/${enc(ps.id)}`;
    }, { render: 'never' });
  },
  async pcSetAdd() {
    const sel = $('#pc-set-add');
    const x = sel && (S.pcData.pieces || []).find((p) => p.id === sel.value);
    if (!x) return;
    S.pcSetForm.changes.push({ piece: x.id, text: x.text });  // 원래 견본 글에서 시작한다
    await pcSetSave();
  },
  async pcSetDrop(i) {
    S.pcSetForm.changes.splice(Number(i), 1);
    await pcSetSave();
  },
  async pcSetCopy() {
    await run('실험 판을 복제하는 중', async () => {
      if (S.pcSetDirty) await pcSetSave(true);
      const ps = await api('POST', `/promptsets/${enc(S.pcData.set.id)}/duplicate`);
      location.hash = `#/prompts/set/${enc(ps.id)}`;
    }, { render: 'never' });
  },
  async pcSetDelete() {
    const ps = S.pcData.set;
    if (!(await askConfirm(`'${ps.name}' 실험 판을 지울까요? 놀이터에 남은 시도는 그대로예요.`, { ok: '지우기', danger: true }))) return;
    await run('실험 판을 지우는 중', async () => {
      await api('DELETE', `/promptsets/${enc(ps.id)}`);
      location.hash = '#/prompts/sets';
    }, { render: 'never' });
  },
  /** 판을 끼운 프롬프트로 새 놀이터 세션. blind 면 원래 판도 함께 돌려 가려 읽는다 */
  async pcSetOpen(blind) {
    await run('놀이터 세션을 만드는 중', async () => {
      if (S.pcSetDirty) await pcSetSave(true);
      const s = S.pcData.sample;
      const x = await api('POST', `/promptsets/${enc(S.pcData.set.id)}/playground`, { project: s.project, n: s.n, blind: !!blind });
      location.hash = `#/promptlab/${enc(x.id)}`;
    }, { render: 'never' });
  },
});
