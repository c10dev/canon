/* 프롬프트 관리 (작품 밖 화면 #/prompts[/<갈래>|/topic/<꼬리표>|/piece/<조각>]). 서버는 canon/routes/prompts.py, 표는 prompts.KINDS · PIECES.
   Canon 이 AI 에게 보내는 프롬프트를 호출 갈래(갈래별)와 주제 꼬리표(주제별)로 찾아 읽는다. 조각마다 자리 · 코드 출처 · 견본 글을 보인다.
   견본은 놀이터의 예시 작품(빈 값) · 예시 장편(':serial') · 고른 작품이고, 작품은 읽기만 한다. 이 화면은 아무것도 저장하지 않는다.
   상태: S.pcReg 표(한 번 읽음), S.pcView 'kind' · 'topic' · 'piece', S.pcData 지금 보는 응답, S.pcSample 견본, S.pcQ 찾기 글, S.pcOpen 펼친 조각 */
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
    : a === 'piece' && b ? ['piece', `/prompts/pieces/${enc(b)}`] : ['kind', `/prompts/kinds/${enc(a || 'episode')}`];
  const ticket = (S.pcTicket = (S.pcTicket || 0) + 1);
  const data = await api('GET', path + q);
  if (ticket !== S.pcTicket) return;  // 그 사이 다른 화면이나 견본을 골랐다. 늦게 온 응답은 버린다 (보기와 데이터를 함께 바꾼다)
  S.pcView = view;
  S.pcData = data;
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
  const seg = `<div class="seg" role="group" aria-label="보는 축"><button type="button" data-action="pcAxis" data-arg="kind" aria-pressed="${!topic}">갈래별</button><button type="button" data-action="pcAxis" data-arg="topic" aria-pressed="${topic}">주제별</button></div>`;
  const head = header('작품 밖 도구', '프롬프트 관리', 'Canon이 AI에게 보내는 프롬프트를 실제 요청과 같은 함수로 조립해 갈래와 주제로 찾아 읽어요.', seg);
  const works = (S.projects || []).filter((x) => !x.play);
  const opt = (v, label) => `<option value="${esc(v)}"${v === S.pcSample ? ' selected' : ''}>${esc(label)}</option>`;
  const bar = `<div class="row pc-bar"><div class="field"><label for="pc-q">찾기</label><input id="pc-q" type="search" data-pc="q" value="${esc(S.pcQ)}" placeholder="갈래 · 조각 이름이나 글"></div>
    <div class="field"><label for="pc-sample">견본</label><select id="pc-sample" data-pc="sample">${opt('', '예시 작품 (6화 단편)')}${opt(PC_SERIAL, '예시 장편')}${works.map((w) => opt(w.name, w.title || w.name)).join('')}</select></div></div>`;
  const body = S.pcView === 'piece' ? pcPieceView(S.pcData) : topic ? pcTopicView(S.pcData) : pcKindView(S.pcData);
  return `${head}${bar}<div class="cols"><nav class="col pc-nav" aria-label="${topic ? '주제' : '갈래'} 목록">${topic ? pcTagNav() : pcKindNav()}</nav><div class="col wide">${body}</div></div>`;
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
    <div class="row"><button type="button" class="btn" data-action="pcPlayground">놀이터에서 열기</button><button type="button" class="btn ghost" data-action="pcFull">${S.pcFull ? '요청 전문 닫기' : '요청 전문 보기'}</button></div>${full}</section>
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
    location.hash = axis === 'topic' ? '#/prompts/topic/style' : '#/prompts';
  },
  pcFull() {
    S.pcFull = !S.pcFull;
    render();
  },
  /** 조립한 시스템 · 요청을 새 놀이터 세션으로 연다. 작업지시서 갈래는 놀이터의 불러오기(출처 · 응답 스키마가 남음), 그 밖은 글 그대로 */
  async pcPlayground() {
    const d = S.pcData;
    const s = d.sample;
    const viaLoad = d.kind.brief && s.project !== PC_SERIAL;
    await run('놀이터 세션을 만드는 중', async () => {
      const title = `${d.kind.label} · ${s.title}${s.n ? ` ${s.n}화` : ''}`.slice(0, 60);
      let x = await api('POST', '/promptlab', viaLoad ? {} : { title, system: d.system, prompt: d.prompt });
      if (viaLoad) x = await api('POST', `/promptlab/${enc(x.id)}/load`, { kind: d.kind.id, project: s.project, n: s.n });
      location.hash = `#/promptlab/${enc(x.id)}`;
    }, { render: 'never' });
  },
});
