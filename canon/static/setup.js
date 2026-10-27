/* 1단계 설정 도우미: 기본 정보 · 로그라인 · 세계관 · 인물 · 관계, 이름 · 지명 후보, AI 빈칸 제안. app.js 의 S, actions, api, render, input, header 를 그대로 쓴다.
   인물 · 관계 카드는 접힌 요약 줄로 그리고, 펼침 상태는 S.setupOpen 에 작품마다 기억한다. */
'use strict';

// ----- 1. 설정 도우미 -----

// 로그라인 다섯 칸과 톤 다이얼. canon/logline.py, Swift 앱 FeatureSetup/Logline.swift 와 같은 규칙이라 함께 고친다.
const LOGLINE_SLOTS = [
  ['who', '누가', '이름보다 특징이 먼저 보이게'],
  ['why', '무엇 때문에', '이야기를 시작하게 만드는 일'],
  ['goal', '무엇을 하려 하나', "눈에 보이는 행동, '~한다'로 끝내기"],
  ['block', '무엇이 막나', '사람이나 힘'],
  ['stake', '무엇이 걸렸나', '선택, 비워도 돼요'],
];

// 숫자는 한국어로 읽은 받침이 있나: 영 일 이 삼 사 오 육 칠 팔 구 (logline.DIGIT_FINAL)
const DIGIT_FINAL = '1101001110';

function josa(word, withFinal, withoutFinal) {
  const w = word.trim();
  if (!w) return '';
  const digit = DIGIT_FINAL['0123456789'.indexOf(w[w.length - 1])];
  if (digit) return digit === '1' ? withFinal : withoutFinal;
  const code = w.charCodeAt(w.length - 1);
  if (code < 0xAC00 || code > 0xD7A3) return `${withFinal}(${withoutFinal})`;
  return (code - 0xAC00) % 28 ? withFinal : withoutFinal;
}

function composeLogline(p) {
  const [who, why, goal, block, stake] = LOGLINE_SLOTS.map(([k]) => (p[k] || '').trim().replace(/\.+$/, ''));
  let out = '';
  if (who) out += who + josa(who, '이', '가') + ' ';
  if (why) out += why + ' ';
  if (goal) out += goal + '.';
  if (block) out += (out ? ' 하지만 ' : '') + block + '.';
  if (stake) out += ' ' + stake + '.';
  return out.trim();
}

function loglineChecks(p) {
  const n = composeLogline(p).length;
  return [
    [p.who.trim().split(/\s+/).length > 1, '주인공에게 이름 말고 특징이 있다'],
    [!!p.why.trim(), '이야기를 시작하게 만드는 일이 있다'],
    [p.goal.trim().endsWith('다'), "목표가 눈에 보이는 행동이다 ('~한다'로 끝남)"],
    [!!p.block.trim(), '목표를 막는 사람이나 힘이 있다'],
    [n >= 40 && n <= 150, '길이가 40~150자 사이다'],
  ];
}

const TONE_DIALS = [['dark', '밝다', '어둡다'], ['serious', '가볍다', '진지하다'], ['slow', '빠르다', '느리다']];
const TONE_WORDS = {
  dark: [['밝고', '밝다'], ['조금 밝고', '조금 밝다'], ['조금 어둡고', '조금 어둡다'], ['어둡고', '어둡다']],
  serious: [['가볍고', '가볍다'], ['조금 가볍고', '조금 가볍다'], ['조금 진지하고', '조금 진지하다'], ['진지하고', '진지하다']],
  slow: [['호흡이 빠르다', '호흡이 빠르다'], ['호흡이 조금 빠르다', '호흡이 조금 빠르다'], ['호흡이 조금 느리다', '호흡이 조금 느리다'], ['호흡이 느리다', '호흡이 느리다']],
};

function toneText(d) {
  const words = TONE_DIALS.map(([k]) => (d[k] >= 1 && d[k] <= 4 ? TONE_WORDS[k][d[k] - 1] : null)).filter(Boolean);
  return words.map((w, i) => (i === words.length - 1 ? w[1] : w[0])).join(' ');
}

/** 고른 장르의 로그라인 예시. 장르를 안 골랐으면 미스터리와 현대 드라마 예시 */
function loglineExamples() {
  const ids = P().meta.genres.filter(genreById);
  return (ids.length ? ids : ['mystery', 'drama']).flatMap((id) => (genreById(id) || {}).logline || []);
}

function loglineBuilder() {
  const m = P().meta;
  const parts = m.logline_parts;
  const exs = loglineExamples();
  const legacy = !Object.values(parts).some((v) => v.trim()) && m.logline.trim();
  const slots = LOGLINE_SLOTS.map(([k, label, hint]) => `<div class="slot">${input(label, 'meta.logline_parts.' + k, { hint })}${slotExamples(k, label)}</div>`).join('');
  return `<div class="logline-box"><span class="label-text">로그라인 <span class="hint">다섯 칸을 채우면 한 문장으로 합쳐요. 점선 예시를 누르면 빈 칸에 들어가요</span></span>
    ${legacy ? '<div class="note plain">지금 로그라인은 한 문장으로만 저장되어 있어요. 칸을 채우면 칸 내용으로 바뀌어요.</div>' : ''}
    ${slots}
    <div class="logline-out"><p id="logline-preview" class="logline-preview" aria-live="polite">${esc(m.logline || LOGLINE_EMPTY)}</p><ul id="logline-checks" class="logline-checks">${loglineChecksHtml(m)}</ul></div>
    ${exs.length ? `<details><summary>예시 로그라인 ${exs.length}개 보기</summary><div class="ex-list">${exs.map((e, i) => `<div class="ex-item"><span>${esc(composeLogline(e))}</span><button type="button" class="btn small" data-action="useExample" data-arg="${i}">이 예시로 채우기</button></div>`).join('')}</div></details>` : ''}
    <div id="logline-manual">${loglineManualHtml(m)}</div>
    <details${legacy || loglineManual(m) ? ' open' : ''}><summary>한 문장으로 직접 고쳐 쓰기</summary>${input('로그라인 문장', 'meta.logline', { rows: 3, hint: '직접 고친 문장은 칸을 고쳐도 그대로 둬요' })}</details>
  </div>`;
}

/** 그 칸의 예시 값 (고른 장르 예시에서 겹치지 않게 셋까지) */
const slotValues = (k) => [...new Set(loglineExamples().map((e) => e[k]).filter(Boolean))].slice(0, 3);

/** 로그라인 칸 아래 예시 칩. 채운 칸은 칩을 숨기고 '다른 예시' 링크만 둔다 (S.loglineMore 로 다시 펼친다).
    data-st 는 채움 · 펼침 상태: updateLogline 이 상태가 바뀐 칸만 다시 그린다 */
function slotExamples(k, label) {
  const vals = slotValues(k);
  const filled = !!(P().meta.logline_parts[k] || '').trim();
  const more = !!(S.loglineMore || {})[k];
  const st = `${filled ? 1 : 0}${more ? 1 : 0}`;
  if (!vals.length) return `<div id="slot-ex-${k}" data-st="${st}"></div>`;
  const link = (text) => `<button type="button" class="link-btn small" data-action="slotExamples" data-arg="${k}" aria-expanded="${more}">${text}</button>`;
  if (filled && !more) return `<div id="slot-ex-${k}" data-st="${st}">${link('다른 예시')}</div>`;
  const chips = vals.map((v) => `<button type="button" data-action="fillSlot" data-arg="${esc(k + '|' + v)}">${esc(v)}</button>`).join('');
  return `<div id="slot-ex-${k}" data-st="${st}" style="display:flex;flex-direction:column;gap:4px;align-items:flex-start"><div class="genre-opts ex-opts" role="group" aria-label="${esc(label)} 예시">${chips}</div>${filled ? link('예시 접기') : ''}</div>`;
}

/** 채움 · 펼침 상태가 바뀐 칸의 예시 칩만 다시 그린다. 그 안에 포커스가 있었으면 새 칸의 첫 버튼으로 옮긴다 */
function refreshSlotExamples() {
  LOGLINE_SLOTS.forEach(([k, label]) => {
    const el = $(`#slot-ex-${k}`);
    if (!el) return;
    const html = slotExamples(k, label);
    if (el.dataset.st === html.match(/data-st="(\d+)"/)[1]) return;
    const had = el.contains(document.activeElement);
    el.outerHTML = html;
    const btn = had && $(`#slot-ex-${k} button`);
    if (btn) btn.focus();
  });
}

/** 직접 고친 문장을 쓰는 중: 칸 내용과 다르다. 옛 작품처럼 칸이 모두 비었으면 칸을 채울 때 칸 내용으로 바꾼다 */
function loglineManual(m) {
  const parts = m.logline_parts;
  return Object.values(parts).some((v) => v.trim()) && !!m.logline.trim() && m.logline !== composeLogline(parts);
}

function loglineManualHtml(m) {
  return loglineManual(m) ? '<div class="note info row" role="status"><span>직접 고친 문장을 쓰고 있어요. 칸을 고쳐도 이 문장은 바뀌지 않아요.</span><button type="button" class="btn small" data-action="rebuildLogline">칸 내용으로 다시 만들기</button></div>' : '';
}

const LOGLINE_EMPTY = '칸을 채우면 여기에 로그라인이 만들어져요.';

function loglineChecksHtml(m) {
  const parts = m.logline_parts;
  if (!Object.values(parts).some((v) => v.trim())) return '';
  return loglineChecks(parts).map(([ok, t]) => `<li class="${ok ? 'ok' : ''}">${esc(t)}</li>`).join('') + `<li class="len">${m.logline.length}자 · 점검은 참고용이에요</li>`;
}

/** 로그라인 칸이 바뀌면 합친 문장, 점검, 직접 쓰기 칸만 다시 그린다 (입력 중인 칸의 포커스 유지).
    prev 는 바뀌기 전 칸으로 합친 문장: 지금 문장이 그것과 같거나 비었을 때만 새 칸 내용으로 바꾼다 (직접 고친 문장은 남긴다) */
function updateLogline(prev) {
  const m = P().meta;
  const parts = m.logline_parts;
  const empty = !Object.values(parts).some((v) => v.trim());
  if (!empty && (prev === undefined || !m.logline.trim() || m.logline === prev)) {
    m.logline = composeLogline(parts);
    const raw = $('#f-meta-logline');
    if (raw) raw.value = m.logline;
  }
  const pv = $('#logline-preview');
  if (pv) pv.textContent = m.logline || LOGLINE_EMPTY;
  const ck = $('#logline-checks');
  if (ck) ck.innerHTML = loglineChecksHtml(m);
  const mn = $('#logline-manual');
  if (mn) mn.innerHTML = loglineManualHtml(m);
  refreshSlotExamples();
}

function toneBox() {
  const m = P().meta;
  const d = m.tone_dials;
  const rows = TONE_DIALS.map(([k, l, r]) => `<div class="dial" role="group" aria-label="${l}, ${r}"><span>${l}</span>${[1, 2, 3, 4].map((v) => `<button type="button" aria-pressed="${d[k] === v}" aria-label="${l}에서 ${r} 사이 ${v}단계: ${TONE_WORDS[k][v - 1][1]}" title="${TONE_WORDS[k][v - 1][1]}" data-action="setDial" data-arg="${k}|${v}"></button>`).join('')}<span>${r}</span><span class="dial-now">${d[k] >= 1 && d[k] <= 4 ? TONE_WORDS[k][d[k] - 1][1] : ''}</span></div>`).join('');
  const dialText = toneText(d);
  const offer = dialText && m.tone.trim() && m.tone !== dialText
    ? `<div class="row"><span class="small">다이얼 문장: ${esc(dialText)}</span><button type="button" class="btn small" data-action="useToneText">다이얼 문장으로 바꾸기</button></div>` : '';
  return `<div id="tone-box" class="field"><span class="label-text">톤 <span class="hint">양 끝 중 어디에 가까운가. 왼쪽부터 1~4단계이고, 고른 단계를 다시 누르면 꺼져요. 문장은 직접 고쳐도 되고, 직접 쓴 문장은 다이얼이 덮지 않아요</span></span>${rows}${input('톤 문장', 'meta.tone', { placeholder: '예: 조금 어둡고 진지하고 호흡이 느리다' })}${offer}</div>`;
}

// 관계를 말로 고르기. VIEWS 는 canon/dynamics.py 의 VIEWS 와 같은 목록이다.
const VIEWS = ['믿는다', '좋아한다', '경계한다', '미워한다', '빚졌다', '얕본다', '잘 모른다'];
const REL_TYPES = ['가족', '친구', '동료', '연인', '옛 연인', '라이벌', '사제', '상사와 부하'];
const CONFLICTS = [['아니다', 0], ['조금', 0.4], ['정면으로', 0.8]];

function conflictWord(v) {
  return v >= 0.6 ? '정면으로' : v > 0 ? '조금' : '아니다';
}

// 인물 · 관계 카드 펼침. 작품마다 카드 키(인물 'c:<id>', 관계 'r:<두 인물>')로 기억한다.
// 기억이 없으면 새로 추가했거나 빈 칸이 있는 카드만 펼친다. 전체 다시 그리기에도 남도록 S 에 둔다
function openMap() {
  S.setupOpen = S.setupOpen || {};
  return (S.setupOpen[S.name] = S.setupOpen[S.name] || {});
}
const charKey = (c) => 'c:' + c.id;
const relKey = (r) => 'r:' + [r.a, r.b].sort().join('|');
function cardOpen(key, dflt) {
  const v = openMap()[key];
  return v === undefined ? !!dflt : v;
}

// 펼치고 접은 것을 기억하고 접힘 표시를 바꾼다 (toggle 은 버블되지 않아 capture 로 받는다)
document.addEventListener('toggle', (e) => {
  const k = e.target.dataset && e.target.dataset.openKey;
  if (!k || !S.name) return;
  openMap()[k] = e.target.open;
  const mark = e.target.querySelector(':scope > summary > .fold-mark');
  if (mark) mark.textContent = foldMark(e.target.open);
}, true);

// 카드 접힌 줄. 앱 CSS 의 summary 는 flex 라 기본 삼각형이 없어 직접 그린다
const FOLD_SUMMARY = 'style="display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 6px;min-height:40px;padding:4px 0"';
const foldMark = (open) => (open ? '▾' : '▸');
const foldHead = (open) => `<span class="fold-mark" aria-hidden="true" style="width:1em">${foldMark(open)}</span>`;

/** 관계 카드 접힌 줄: 두 인물 · 사이, 고칠 점이 있으면 표시 */
function relSummary(r, i, open) {
  const warn = relProblem(r, i) ? ' <span class="small" style="color:var(--amber-ink)">· 확인 필요</span>' : '';
  return `${foldHead(open)}<strong>${esc(charName(r.a) || r.a)} ↔ ${esc(charName(r.b) || r.b)}</strong> <span class="small" data-rel-sub="${i}">· ${esc(r.type.trim() || '사이를 정하지 않음')}</span>${warn}`;
}

/** 비었거나 고칠 점이 있는 관계는 펼쳐 둔다 */
function relNeedsWork(r, i) {
  return !r.type.trim() || !!relProblem(r, i) || (!P().snapshots.length && !(r.a_view || []).length && !(r.b_view || []).length);
}

function relRow(r, i) {
  const p = P();
  const b = `relationships.${i}`;
  // 없는 인물을 가리키면 첫 인물이 고른 것처럼 보이지 않게 그 id 를 따로 보인다
  const opts = (sel) => (p.characters.some((c) => c.id === sel) ? '' : `<option value="${esc(sel)}" selected>(없는 인물: ${esc(sel)})</option>`)
    + p.characters.map((c) => `<option value="${esc(c.id)}"${c.id === sel ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('');
  const started = p.snapshots.length > 0; // 첫 상태 반영 뒤에는 관계 사건으로 계산한다
  const chips = (vals, on, act) => vals.map(([label, arg]) => `<button type="button" aria-pressed="${on(label)}" data-action="${act}" data-arg="${esc(`${i}|${arg}`)}">${esc(label)}</button>`).join('');
  const view = (side, from, to) => `<div class="rel-line"><span class="label-text">${esc(charName(from) || from)} → ${esc(charName(to) || to)}</span>
      <div class="genre-opts" role="group" aria-label="${esc(charName(from) || from)}이(가) ${esc(charName(to) || to)}을(를) 보는 방식">${chips(VIEWS.map((w) => [w, `${side}|${w}`]), (w) => (r[side] || []).includes(w), 'toggleView')}</div></div>`;
  const open = cardOpen(relKey(r), relNeedsWork(r, i));
  return `<details class="rel-card" id="rel-${i}" data-open-key="${esc(relKey(r))}" style="display:block"${open ? ' open' : ''}>
    <summary ${FOLD_SUMMARY}>${relSummary(r, i, open)}</summary>
    <div class="rel-body" style="display:flex;flex-direction:column;gap:10px;padding-top:10px">
    <div class="rel-top">
      <div class="field"><label for="ra${i}">인물 A</label><select id="ra${i}" data-bind="${b}.a">${opts(r.a)}</select></div>
      <div class="field"><label for="rb${i}">인물 B</label><select id="rb${i}" data-bind="${b}.b">${opts(r.b)}</select></div>
      ${input('어떤 사이', b + '.type', { placeholder: '오빠의 친구, 남매…' })}
      <button class="btn icon-btn danger" data-action="removeRelationship" data-arg="${i}" aria-label="관계 삭제">✕</button>
    </div>${relProblem(r, i)}
    <div class="genre-opts ex-opts" role="group" aria-label="어떤 사이 예시">${chips(REL_TYPES.map((t) => [t, t]), (t) => r.type === t, 'setRelType')}</div>
    ${input('설명', b + '.description', { rows: 2, hint: '두 사람 사이의 사정. 매 화 프롬프트에 들어가요', placeholder: '예: 겉으로는 깍듯하지만 서로 약점을 쥐고 있다' })}
    ${started ? `<div class="small">지금 호감 ${r.affinity} · 긴장 ${r.tension}. 첫 반영 뒤에는 본문의 관계 사건으로 바뀌어요.</div>` : `${view('a_view', r.a, r.b)}${view('b_view', r.b, r.a)}`}
    <div class="rel-line"><span class="label-text">원하는 게 부딪치나</span><div class="genre-opts" role="group" aria-label="목표 충돌">${chips(CONFLICTS, (w) => conflictWord(r.goal_conflict || 0) === w, 'setConflict')}</div></div>
    ${started ? '' : `<details><summary>숫자로 직접 정하기</summary><div class="grid-2" style="padding-top:8px">
      <div class="field"><label for="raf${i}">시작 호감 <output id="raf${i}o">${r.affinity}</output> <span class="hint">보는 방식을 고른 방향은 고른 말이 우선</span></label><input id="raf${i}" type="range" min="-5" max="5" value="${r.affinity}" data-bind="${b}.affinity" data-kind="int" data-out="raf${i}o"></div>
      <div class="field"><label for="rg${i}">목표 충돌 <output id="rg${i}o">${r.goal_conflict || 0}</output></label><input id="rg${i}" type="range" min="0" max="1" step="0.1" value="${r.goal_conflict || 0}" data-bind="${b}.goal_conflict" data-kind="float" data-out="rg${i}o"></div>
    </div></details>`}
    </div>
  </details>`;
}

/** 같은 인물끼리이거나 앞선 관계와 같은 쌍이면 알린다. 서버는 이런 관계를 저장하지 않는다 (pipeline.validate_relationships). */
function relProblem(r, i) {
  if (r.a === r.b) return '<div class="note warn" role="status">같은 인물끼리는 관계를 만들 수 없어요. 인물 B를 바꾸세요.</div>';
  const j = P().relationships.findIndex((x, k) => k !== i && [x.a, x.b].sort().join('|') === [r.a, r.b].sort().join('|'));
  return j >= 0 ? `<div class="note warn" role="status">이 두 인물의 관계가 ${j + 1}번째에도 있어요. 하나만 남기세요.</div>` : '';
}

function refreshRel(i) {
  // 인물을 바꾸면 다른 관계와 겹치는지도 바뀐다. 바꾼 줄은 다시 그리고, 다른 줄은 알림과 접힌 줄만 고친다
  P().relationships.forEach((r, k) => {
    const el = $(`#rel-${k}`);
    if (!el) return;
    if (k === i) {
      openMap()[relKey(r)] = true;  // 고치는 중인 카드: 인물이 바뀌어 키가 달라져도 펼친 채로
      el.outerHTML = relRow(r, k);
      return;
    }
    const old = el.querySelector('.rel-body > .note.warn');
    if (old) old.remove();
    const note = relProblem(r, k);
    if (note) el.querySelector('.rel-top').insertAdjacentHTML('afterend', note);
    el.querySelector('summary').innerHTML = relSummary(r, k, el.open);
  });
}

async function loadNames(key, req, ai) {
  await run(ai ? 'AI가 고르는 중' : '후보 뽑는 중', async () => {
    const r = await api('POST', `/projects/${enc(S.name)}/names`, { ...req, ai, n: 8, project: P() });
    S.names[key] = { ...r, ai };
    if (S.nameCheck) Object.assign(S.nameCheck, { style: r.style, detected: r.detected });
  });
}

/** 이름 점검에 필요한 칸만 (작품 전체를 보내지 않는다, web.NameCheckIn). */
const nameCheckBody = () => ({ meta: P().meta, world: P().world, characters: P().characters, cast_candidates: P().cast_candidates });

let nameSeq = 0;
async function checkNames(show = false) {
  const my = ++nameSeq;
  const busy = $('#name-check');
  if (show && busy) busy.innerHTML = '<span class="small">이름을 점검하는 중…</span>';
  const r = await api('POST', `/projects/${enc(S.name)}/names/check`, nameCheckBody()).catch(() => null);
  if (my !== nameSeq) return;  // 더 나중에 보낸 점검이 있으면 그 결과를 쓴다
  if (!r) {  // 실패: 이전 경고를 그대로 두지 않고 못 했다고 알린다
    S.nameCheck = { failed: true, detected: (S.nameCheck || {}).detected };
    const box = $('#name-check');
    if (box) box.outerHTML = nameCheckBox();
    if (show) toast('이름 점검을 못 했어요. 잠시 뒤 다시 해 보세요', true);
    return;
  }
  S.nameCheck = r;
  const box = $('#name-check');
  if (box) box.outerHTML = nameCheckBox();
  document.querySelectorAll('[data-name-issues]').forEach((el) => { el.outerHTML = nameIssuesFor(el.dataset.nameIssues); });
  const auto = $('#name-style-auto');
  if (auto) auto.textContent = `자동 (지금: ${styleLabel(r.detected)})`;
  if (show) toast(r.warnings.length ? `이름 점검: ${r.warnings.length}건` : '이름 점검: 문제 없음');
}

function styleLabel(id) {
  const st = (S.namingStyles || []).find((x) => x.id === id);
  return st ? st.label : id || '';
}

/** 이름 점검 묶음: 종류별 소제목, 같은 이름 · 같은 성 뺀 이름만 경고 색, 나머지는 안내 색. 줄마다 그 인물 이름 칸으로 가는 버튼. */
function nameCheckBox() {
  const nc = S.nameCheck || {};
  const issues = nc.issues || (nc.warnings || []).map((text) => ({ kind: 'other', level: 'warn', text, ids: [] }));
  const live = 'role="status" aria-live="polite"';
  if (nc.failed) return `<div id="name-check" class="note warn" ${live}>이름 점검을 못 했어요. <button type="button" class="link-btn small" data-action="checkNames">다시 시도</button></div>`;
  if (!issues.length) return `<div id="name-check" ${live}>${S.nameCheck ? '<span class="small">이름 점검: 문제 없음</span>' : ''}</div>`;
  const kinds = nc.kinds || {};
  const order = ['same', 'given', 'confusable', 'era', 'style', 'overused', 'other'];
  const warn = issues.some((i) => i.level === 'warn');
  const groups = order.map((k) => [k, issues.filter((i) => i.kind === k)]).filter(([, l]) => l.length);
  const body = groups.map(([k, list]) => `<div class="small" style="margin-top:6px;font-weight:700">${esc(kinds[k] || '기타')}</div>
    <ul style="margin:2px 0 0;padding-left:18px">${list.map((i) => `<li>${esc(i.text)} ${nameJump(i.ids)}</li>`).join('')}</ul>`).join('');
  const head = `이름 점검 ${issues.length}건${warn ? ` · 같은 이름 ${issues.filter((i) => i.level === 'warn').length}건` : ''}`;
  return `<div id="name-check" class="note ${warn ? 'warn' : 'info'}" ${live}>${issues.length > 3
    ? `<details${warn ? ' open' : ''}><summary><strong>${head}</strong></summary>${body}</details>` : `<strong>${head}</strong>${body}`}</div>`;
}

/** 경고 줄의 인물 이름 버튼: 누르면 그 인물 카드의 이름 칸으로 간다 (후보 인물은 카드가 없어 이름만 보인다). */
function nameJump(ids) {
  return (ids || []).map((id) => {
    const i = P().characters.findIndex((c) => c.id === id);
    return i < 0 ? '' : `<button type="button" class="link-btn small" data-action="focusName" data-arg="${i}" aria-label="${i + 1}번 인물 ${esc(P().characters[i].name || id)} 이름 칸으로">${i + 1}번 ${esc(P().characters[i].name || id)}</button>`;
  }).join(' ');
}

/** 인물 카드 · 플롯 서랍의 새 인물 칸 아래: 그 인물에 해당하는 이름 점검만 작게 (위 묶음이 화면 밖이어도 보이게). */
function nameIssuesFor(id) {
  const list = ((S.nameCheck || {}).issues || []).filter((i) => (i.ids || []).includes(id));
  return `<div data-name-issues="${esc(id)}">${list.map((i) => `<div class="small" style="color:${i.level === 'warn' ? 'var(--amber-ink)' : 'var(--muted)'}">${esc(i.text)}</div>`).join('')}</div>`;
}

// 후보 칩. AI 추천이면 이유를, 코드 후보면 시대·종류 메모를 같이 보여 준다
function namePicks(key, action, argOf) {
  const r = S.names[key];
  if (!r) return '';
  const items = r.ai ? (r.options || []).map((o) => ({ name: o.name, note: o.reason }))
    : (r.candidates || []).map((c) => ({ name: c.name, note: [c.kind, c.note].filter(Boolean).join(' · ') }));
  const chips = items.map((x) => `<button type="button" class="name-pick" data-action="${action}" data-arg="${esc(argOf(x.name))}" title="${esc(x.note)}">${esc(x.name)}${x.note ? `<small>${esc(x.note)}</small>` : ''}</button>`).join('');
  return `<div class="name-picks-box">
    <div class="between"><span class="small">${r.ai ? 'AI 추천' : '무작위 후보'} · ${esc(r.style_label)} · 눌러서 ${key === 'place' ? '장소에 추가' : '이름으로 쓰기'}</span>
      <button type="button" class="btn small ghost" data-action="closeNames" data-arg="${esc(key)}">닫기</button></div>
    <div class="name-picks">${chips || '<span class="small">후보가 없어요</span>'}</div></div>`;
}

function nameStyleField() {
  const w = P().world;
  const det = (S.nameCheck || {}).detected;
  const opts = (S.namingStyles || []).map((st) => `<option value="${esc(st.id)}"${w.name_style === st.id ? ' selected' : ''}>${esc(st.label)}</option>`).join('');
  const cur = (S.namingStyles || []).find((st) => st.id === (w.name_style || det));
  return `<div class="field"><label for="f-name-style">이름 스타일 <span class="hint">이름과 지명 후보를 뽑는 기준</span></label>
    <select id="f-name-style" data-bind="world.name_style" data-kind="text"><option value="" id="name-style-auto">자동 (지금: ${esc(styleLabel(det))})</option>${opts}</select>
    ${cur ? `<div class="small">${esc(cur.summary)}</div>` : ''}</div>`;
}

function placeKindOptions() {
  const sid = P().world.name_style || (S.nameCheck || {}).style;
  const st = (S.namingStyles || []).find((x) => x.id === sid);
  return ['<option value="">종류 무관</option>', ...((st && st.place_kinds) || []).map((k) => `<option value="${esc(k)}"${S.placeKind === k ? ' selected' : ''}>${esc(k)}</option>`)].join('');
}

/** 설정 도우미 인물 카드의 신체 프로필. 미성년 인물은 쓰리사이즈 칸을 두지 않는다 */
function bodyFields(c, b) {
  if (!c.body || typeof c.body !== 'object') c.body = {};  // 예전 화면에서 만든 인물도 칸을 고칠 수 있게
  const minor = isMinorAge(c.age);
  const filled = bodyRows(c).length;
  const open = (S.bodySug || {})[c.id] || (S.bodyOpen || {})[c.id];  // 제안을 받거나 적용한 뒤 다시 그려도 펼친 채로
  return `<details${open ? ' open' : ''}><summary>신체 프로필 <span class="small">${filled ? `· ${filled}칸 채움 ` : ''}· 인물 카드에만 보여요</span></summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
    <div class="grid-2">${input('키', b + '.body.height', { placeholder: '예: 165cm' })}${input('몸무게', b + '.body.weight', { placeholder: '예: 48kg' })}</div>
    <div class="grid-2">${input('체형', b + '.body.build', { placeholder: '예: 마른 근육형' })}${minor ? '' : input('쓰리사이즈', b + '.body.measurements', { placeholder: '예: 84-58-86' })}</div>
    ${minor ? '<div class="small">나이로 보아 미성년 인물이라 쓰리사이즈 칸은 두지 않아요.</div>' : ''}
    ${input('신체 특징', b + '.body.features', { rows: 2, placeholder: '예: 왼손잡이, 오른쪽 어깨에 화상 자국' })}
    <div class="row"><button type="button" class="btn small" data-action="bodyAI" data-arg="${esc(c.id)}">AI 제안</button><span class="small">설정에 맞춰 칸을 제안해요. 고른 칸만 적용해요${minor ? ' · 쓰리사이즈는 제안하지 않아요' : ''}</span></div>
    ${bodySuggestCard(c)}
    <div class="small">AI 프롬프트에는 넣지 않아요. 본문에 이어지게 할 외모는 위 '외모' 칸에 적어요.</div></div></details>`;
}

/** 신체 프로필 AI 제안: 칸별로 지금 값과 비교해 고른다. 비어 있는 칸만 기본으로 고른다 */
function bodySuggestCard(c) {
  const s = (S.bodySug || {})[c.id];
  if (!s) return '';
  const minor = isMinorAge(c.age);
  const rows = BODY_FIELDS.filter(([k]) => (s[k] || '').trim() && !(k === 'measurements' && minor)).map(([k, label]) => {
    const now = ((c.body || {})[k] || '').trim();
    const same = now === s[k].trim();
    return `<label class="body-sug"><input type="checkbox" data-body-pick="${esc(c.id)}" value="${k}"${now || same ? '' : ' checked'}${same ? ' disabled' : ''}>
      <span><strong>${label}</strong> ${now ? `<span class="before">${esc(now)}</span> → ` : ''}<span class="after">${esc(s[k])}</span>${same ? ' <span class="small">지금과 같아요</span>' : ''}</span></label>`;
  }).join('');
  return `<div class="note info" style="display:flex;flex-direction:column;gap:8px"><strong>AI 제안</strong>${s.note ? `<span>${esc(s.note)}</span>` : ''}
    ${rows || '<span>제안한 칸이 없어요</span>'}
    <div class="row"><button type="button" class="btn small primary" data-action="bodyApply" data-arg="${esc(c.id)}"${rows ? '' : ' disabled'}>고른 칸 적용</button><button type="button" class="btn small" data-action="bodyDismiss" data-arg="${esc(c.id)}">닫기</button></div></div>`;
}

/** 인물 카드의 비중 칸. 비중 안내는 인물 구역 머리에 한 번만 둔다 (플롯 서랍은 plot.js 의 tierSelect) */
function setupTier(c, b, id) {
  return `<div class="field"><label for="${id}">비중${c.first_ep ? ` <span class="hint">${c.first_ep}화에 처음 나옴</span>` : ''}</label>
    <select id="${id}" data-bind="${b}.tier">${TIERS.map(([v, l]) => `<option value="${v}"${(c.tier || 'main') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>`;
}

// 인물을 AI에 넣는 방식 (Character.context). 인과율 요소 화면(causal.js)의 'AI에 넣기'와 같은 고르기이고,
// 인물은 '관련 있을 때' 대신 '등장할 때'다. 고르는 규칙은 서버 context.core_ids · off_ids
const CHAR_CTX = [['auto', '등장할 때'], ['always', '항상'], ['off', '넣지 않음']];
const CHAR_CTX_HINT = {
  auto: '등장할 때: 주역은 매 화, 조연 · 단역은 플롯에 나오는 화에만 넣어요.',
  always: '항상: 비중과 상관없이 매 화 설정을 넣어요. 장편에서 글자 예산을 넘기면 그 화 조연 · 단역 설정을 대신 빼요.',
  off: '넣지 않음: 본문 쓰기, 검수, 상태 정리, 플롯 기획에 설정 · 상태 · 관계를 넣지 않아요. 플롯에 나오면 이름만 넣어요.',
};
const EYE = '<path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z"/><circle cx="8" cy="8" r="2"/>';
const eyeIcon = (off) => `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true" style="vertical-align:-2px">${EYE}${off ? '<path d="M2 14L14 2"/>' : ''}</svg>`;

/** 인물 카드 접힌 줄의 넣기 표시. 등장할 때(기본)는 표시하지 않는다 */
function charCtxMark(c) {
  const k = c.context || 'auto';
  if (k === 'auto') return '';
  const label = k === 'always' ? '항상 AI에 넣음' : 'AI에 넣지 않음';
  return ` <span class="small" title="${label}" style="color:var(--${k === 'always' ? 'accent-ink' : 'muted'})">· ${eyeIcon(k === 'off')} ${label}</span>`;
}

/** 인물 카드의 AI에 넣기 고르기 */
function charContextField(c, i) {
  const now = c.context || 'auto';
  return `<div class="field"><span class="label">AI에 넣기</span><div class="seg" role="group" aria-label="AI에 넣기">${CHAR_CTX.map(([k, l]) => `<button type="button" aria-pressed="${now === k}" data-action="charContext" data-arg="${i}|${k}">${l}</button>`).join('')}</div>
    <span class="small">${CHAR_CTX_HINT[now]}</span></div>`;
}

// 비어 있으면 카드를 펼쳐 두는 인물 칸
const CHAR_CORE = ['name', 'role', 'goal', 'wound', 'speech_style'];

/** 인물 카드 접힌 줄의 역할 · 비중 */
function charSub(c) {
  const tier = (TIERS.find(([v]) => v === (c.tier || 'main')) || [])[1] || '';
  return [String(c.role || '').trim() || '역할을 정하지 않음', tier].filter(Boolean).join(' · ');
}

/** 펼쳐 둘 인물: 빈 칸이 있거나, 이름 후보 · 신체 제안처럼 카드 안에서만 보이는 결과가 있다 */
function charNeedsWork(c) {
  return CHAR_CORE.some((k) => !String(c[k] || '').trim()) || !!S.names['c:' + c.id] || !!(S.bodySug || {})[c.id];
}

function viewSetup() {
  const p = P();
  // 인물 화면의 '설정에서 고치기'로 왔으면 그 인물 카드를 펼친다 (app.js 가 이름 칸으로 포커스를 옮긴다)
  const jump = String(S.jumpTo || S.focusTarget || '').match(/^#f-characters-(\d+)-name$/);
  if (jump && p.characters[Number(jump[1])]) openMap()[charKey(p.characters[Number(jump[1])])] = true;
  const chars = p.characters.map((c, i) => {
    const b = `characters.${i}`;
    const issues = ((S.nameCheck || {}).issues || []).filter((x) => (x.ids || []).includes(c.id)).length;
    const open = cardOpen(charKey(c), charNeedsWork(c));
    return `<details class="char-card" id="char-${i}" data-open-key="${esc(charKey(c))}" style="display:block"${open ? ' open' : ''}>
      <summary ${FOLD_SUMMARY}>${foldHead(open)}<strong style="font-size:1rem" data-char-head="${i}">${esc(c.name || '이름 없음')}</strong> <span class="small" data-char-sub="${i}">· ${esc(charSub(c))}</span>${charCtxMark(c)}${issues ? ` <span class="small" style="color:var(--amber-ink)">· 이름 점검 ${issues}건</span>` : ''}</summary>
      <div style="display:flex;flex-direction:column;gap:10px;padding-top:10px">
      <div class="row" style="justify-content:flex-end"><button class="btn small danger" data-action="removeCharacter" data-arg="${i}" aria-label="${esc(c.name || c.id)} 삭제">삭제</button></div>
      <div class="grid-2">${input('이름', b + '.name')}${input('역할', b + '.role', { placeholder: '주인공, 상대역, 조력자…' })}</div>
      ${nameIssuesFor(c.id)}
      <div class="grid-2">${input('나이', b + '.age', { placeholder: '예: 17세, 40대 초반' })}${input('성별', b + '.gender', { placeholder: '남 / 여' })}</div>
      ${setupTier(c, b, 'tier-' + i)}
      ${charContextField(c, i)}
      <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보 뽑기</button><button type="button" class="btn small" data-action="nameAI" data-arg="${esc(c.id)}">AI 이름 추천</button></div>
      ${namePicks('c:' + c.id, 'useName', (n) => `${c.id}|${n}`)}
      ${dexField(c)}
      ${input('원하는 것', b + '.goal', { hint: '작품 전체에서' })}
      ${input('두려운 것 · 약점', b + '.wound')}
      ${input('숨기는 것', b + '.secrets', { kind: 'list', rows: 2 })}
      ${input('말투 (대사)', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 한 줄' })}
      ${voiceField(c, b)}
      <details><summary>더 자세히: 성격, 배경, 외모, 아크</summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
        ${input('성격', b + '.personality', { rows: 2 })}${input('배경', b + '.background', { rows: 2 })}${input('외모', b + '.appearance')}
        ${input('아크', b + '.arc', { hint: '시작 → 결말' })}${input('id', b + '.id', { hint: '관계와 플롯이 인물을 찾는 값이라 바꿀 수 없어요', readonly: true })}
      </div></details>
      ${bodyFields(c, b)}
      ${visualFields(c)}
      </div>
    </details>`;
  }).join('');

  const rels = p.relationships.map(relRow).join('');

  // 인물이 없으면 첫 할 일은 AI 제안이다. 인물이 생기면 다음 단계(문체)를 앞세운다
  const first = !p.characters.length;
  return `${header('1단계', '설정 도우미', '기본 정보, 세계관, 인물, 관계를 정해요. AI 도움은 아래 두 가지예요.', `${((b) => `<button class="btn${first ? ' primary' : ''}" data-action="suggest"${b.attr}>${b.label}</button>`)(jobBtn('suggest', null, '빈칸 AI 제안받기'))}${chatButton('setup')}<a class="btn${first ? '' : ' primary'}" href="${base()}/style">문체로</a>`)}
    ${aiPaths(first)}
    ${aiNote()}
    ${S.suggestion ? viewSuggestion() : ''}
    <nav class="jump-nav" aria-label="설정 구역">${[['setup-basic', '기본 정보'], ['setup-world', '세계관'], ['setup-chars', `인물 ${p.characters.length}`], ['setup-rels', `관계 ${p.relationships.length}`], ['setup-stats', '상태창']]
      .map(([id, l]) => `<button type="button" class="btn small ghost" data-action="jumpTo" data-arg="${id}">${l}</button>`).join('')}</nav>
    <div class="cols">
      <div class="col">
        <section class="card" id="setup-basic">
          <h2>기본 정보</h2>
          ${input('제목', 'meta.title')}
          ${genrePicker()}
          ${adultCheck(`data-bind="meta.adult" data-kind="bool"${P().meta.adult ? ' checked' : ''}`)}
          ${serial() ? input('총 화수', 'meta.target_episodes', { type: 'number', min: 1, max: 1000, hint: '늘리거나 줄이면 마지막 부 끝 화가 따라가요' }) : input('총 화수', 'meta.target_episodes', { type: 'number', min: 4, max: 40, hint: '단편은 10~20화를 권해요 · 4~40화' })}
          ${loglineBuilder()}
          ${input('주제', 'meta.theme', { hint: '이 이야기가 끝까지 묻는 질문 하나', placeholder: '예: 떠난 사람을 이해하면 용서할 수 있나?' })}
          ${toneBox()}
          ${input('화당 분량', 'meta.words_per_episode', { type: 'number', hint: '공백 포함 글자 수' })}
          ${input('메모', 'meta.notes', { rows: 2 })}
        </section>
        <section class="card" id="setup-world">
          <h2>세계관</h2>
          ${input('배경', 'world.setting', { rows: 2 })}${input('시대', 'world.era')}
          ${input('깨면 안 되는 규칙', 'world.rules', { kind: 'list' })}${input('장소', 'world.locations', { kind: 'list' })}
          <div class="row"><select id="place-kind" aria-label="지명 종류" data-local="placeKind" style="width:auto;min-width:120px">${placeKindOptions()}</select>
            <button type="button" class="btn small" data-action="placeCandidates">지명 후보 뽑기</button><button type="button" class="btn small" data-action="placeAI">AI 지명 추천</button></div>
          ${namePicks('place', 'addPlace', (n) => n)}
          ${nameStyleField()}
          ${input('이름 규칙', 'world.name_rules', { kind: 'list', rows: 2, placeholder: "예: 북부 귀족은 성 앞에 '폰'을 붙인다" })}
        </section>
      </div>
      <div class="col wide">
        <section class="card" id="setup-chars">
          <div class="between"><h2>인물 <span class="small">${p.characters.length}명</span></h2><div class="row"><button class="btn small" data-action="dexRoll" title="원형 · 상처 · 말투 · 비틀기 · 이름을 무작위로 섞어 3안을 보여 줘요">도감 주사위</button><button class="btn small" data-action="addCharacter">+ 인물 추가</button></div></div>
          <p class="small">이름, 말투, 성격은 고정 설정이에요. 회차가 지나며 바뀌는 감정과 목표는 상태 승인 화면에서 관리해요.<br>비중: 주역은 매 화 설정 전체가 들어가고, 조연 · 단역은 나오는 화에만 들어가요.${p.characters.length ? '<br>카드를 누르면 펼쳐져요. 빈 칸이 있는 카드는 펼쳐 둬요.' : ''}</p>
          <div class="row"><button type="button" class="btn small ghost" data-action="checkNames">이름 점검</button><span class="small">글자가 겹치는 이름, 나이와 안 맞는 이름, AI가 자주 짓는 이름을 찾아요</span></div>
          ${nameCheckBox()}
          ${dexRollBox()}
          ${chars ? `${openAllBtn('c')}<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;align-items:start">${chars}</div>` : '<div class="note plain">인물이 없어요. 직접 추가하거나 AI 제안을 받으세요.</div>'}
        </section>
        ${typeof swSetupCard === 'function' ? swSetupCard() : ''}
        <section class="card" id="setup-rels">
          <div class="between"><h2>관계</h2><div class="row"><span class="small">${P().snapshots.length ? '첫 반영 뒤에는 관계 사건으로 계산돼요' : '서로 어떻게 보는지 고르면 시작 관계를 계산해요. 긴장은 자동 계산'}</span><button class="btn small" data-action="addRelationship"${autoOn() ? ' disabled' : ''}>+ 관계 추가</button></div></div>
          ${autoOn() ? `<div class="note warn" id="rel-lock">자동 집필이 도는 동안은 관계를 고칠 수 없어요. 반영하는 관계와 겹치지 않게 서버가 받지 않아요. 고치려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : ''}
          ${rels ? openAllBtn('r') : ''}
          ${rels ? (autoOn() ? `<fieldset disabled class="lockset" aria-describedby="rel-lock">${rels}</fieldset>` : rels) : '<div class="small">관계가 없어요.</div>'}
        </section>
      </div>
    </div>${chatPanel('setup')}`;
}

/** AI로 채우는 두 길을 나눠 보인다. 빈 작품은 빈칸 제안을 앞에 두고 '처음에 추천'으로 표시한다 */
function aiPaths(empty) {
  const sug = `<div class="note ${empty ? 'info' : 'plain'}"><strong>빈칸 AI 제안받기</strong>${empty ? ' <span class="chip ai">처음에 추천</span>' : ''}<br><span class="small">비어 있는 칸과 새 인물 · 관계를 한 번에 제안해요. 채운 칸은 건드리지 않아요. 원하는 것만 골라 적용해요.</span></div>`;
  const chat = `<div class="note plain"><strong>대화로 다듬기</strong><br><span class="small">바꾸고 싶은 점을 말하면 바꿀 칸만 지금 값과 나란히 보여 줘요. 이미 채운 칸도 고칠 수 있고, 고른 것만 적용해요.</span></div>`;
  return `<div class="grid-2" style="margin-bottom:12px">${empty ? sug + chat : chat + sug}</div>`;
}

/** 인물 · 관계 구역의 모두 펼치기 · 모두 접기 */
function openAllBtn(kind) {
  const b = (on, text) => `<button type="button" class="link-btn small" data-action="setupOpenAll" data-arg="${kind}|${on}">${text}</button>`;
  return `<div class="row" style="justify-content:flex-end;gap:12px">${b(1, '모두 펼치기')}${b(0, '모두 접기')}</div>`;
}

/** 지금 있는 인물 · 관계 카드 키 */
function setupCardKeys() {
  return new Set([...P().characters.map(charKey), ...P().relationships.map(relKey)]);
}

/** AI 제안 · 대화로 다듬기로 새로 들어온 인물 · 관계 카드를 펼친다 */
function openNewCards(before) {
  setupCardKeys().forEach((k) => { if (!before.has(k)) openMap()[k] = true; });
}

/** 제안 인물이 이미 있는 인물과 같은 사람이다: id 가 같고 이름도 같다 (이름이 다르면 서버가 새 id 로 넣는다, pipeline.apply_setup). */
function sameChar(c) {
  const old = P().characters.find((x) => x.id === c.id);
  return !!old && (!(c.name || '').trim() || (old.name || '').trim() === c.name.trim());
}

/** 제안 관계의 한쪽 인물. 고른 제안 인물이면 그 인물, 아니면 이미 있는 인물. 고르지 않은 제안 인물이면 null (관계를 넣지 않는다). */
function sugEnd(id) {
  const s = S.suggestion;
  const i = s.characters.findIndex((c) => c.id === id);
  if (i >= 0 && !sameChar(s.characters[i])) return S.picks['sc' + i] ? s.characters[i] : null;
  return P().characters.find((c) => c.id === id) || null;
}

// 설정 제안에서 칸마다 고르는 기본 정보 · 세계관 (pipeline.apply_setup 은 빈 칸만 채운다)
const SUG_FIELDS = [['theme', '주제'], ['tone', '톤'], ['world.setting', '배경'], ['world.era', '시대'], ['world.rules', '규칙'], ['world.locations', '장소'], ['world.name_style', '이름 스타일'], ['world.name_rules', '이름 규칙']];
/** 제안(SetupSuggestion)이나 작품(Project)의 그 칸 글. 작품의 주제 · 톤은 meta 에 있다. */
function sugValue(o, k) {
  const v = k.startsWith('world.') ? o.world[k.slice(6)] : (o.meta ? o.meta[k] : o[k]);
  return Array.isArray(v) ? v.join(', ') : String(v || '');
}

// 제안 인물 카드에서 펼쳐 보는 칸 (이름 · 역할은 카드 머리에 있다). 칸 이름은 인물 카드와 같다
const SUG_CHAR_FIELDS = [['age', '나이'], ['gender', '성별'], ['goal', '원하는 것'], ['wound', '두려운 것 · 약점'], ['secrets', '숨기는 것'],
  ['speech_style', '말투 (대사)'], ['personality', '성격'], ['background', '배경'], ['appearance', '외모'], ['arc', '아크']];

/** 제안 인물의 모든 칸. 체크박스 label 밖에 두어 펼쳐도 고르기가 바뀌지 않는다 */
function sugCharDetails(c) {
  const rows = SUG_CHAR_FIELDS.map(([k, label]) => [label, Array.isArray(c[k]) ? c[k].join(', ') : String(c[k] || '').trim()])
    .filter(([, v]) => v);
  if (!rows.length) return '';
  return `<details><summary class="small">모든 칸 보기 (${rows.length})</summary><dl style="margin:6px 0 0;font-size:0.8125rem;line-height:1.5">${rows.map(([l, v]) => `<dt style="font-weight:700">${l}</dt><dd style="margin:0 0 6px">${esc(v)}</dd>`).join('')}</dl></details>`;
}

function viewSuggestion() {
  const s = S.suggestion;
  const exists = (c) => sameChar(c);
  const clash = (c) => !sameChar(c) && P().characters.some((x) => x.id === c.id);
  return `<section class="card" style="border:2px solid var(--accent)">
    <div class="between"><h2>AI 제안 <span class="chip ai">적용 전</span></h2>${proposalActions(['dropSuggestion'], ['applySuggestion'])}</div>
    <p class="small">주제, 톤, 세계관은 비어 있는 칸에만 들어가요. 이미 있는 인물은 건너뛰어요.</p>
    <div class="sug-fields">${SUG_FIELDS.map(([k, label]) => {
    const v = sugValue(s, k);
    if (!v.length) return '';
    const have = sugValue(P(), k).length > 0;
    return `<label class="row sug-field${have ? ' skip' : ''}"><input type="checkbox" data-pick="sf:${k}"${!have && S.picks['sf:' + k] !== false ? ' checked' : ''}${have ? ' disabled' : ''}><strong>${label}</strong> <span>${esc(v)}</span>${have ? ' <span class="small">이미 있음 · 건너뜀</span>' : ''}</label>`;
  }).join('')}</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">
      ${s.characters.map((c, i) => `<div class="char-card suggested"><label class="row" style="cursor:pointer"><input type="checkbox" data-pick="sc${i}"${S.picks['sc' + i] ? ' checked' : ''}${exists(c) ? ' disabled' : ''}><strong>${esc(c.name)}</strong><span class="small">${esc(c.role)} · ${esc(c.id)}${exists(c) ? ' · 이미 있음' : clash(c) ? ' · 이미 있는 다른 인물과 겹쳐 따로 넣어요' : ''}</span></label>
        <span style="font-size:0.8125rem;line-height:1.5">목표: ${esc(c.goal)}<br>말투: ${esc(c.speech_style)}</span>${sugCharDetails(c)}</div>`).join('')}
    </div>
    ${s.relationships.map((r, i) => {
    const a = sugEnd(r.a);
    const b = sugEnd(r.b);
    const nm = (c, id) => esc(c ? c.name || c.id : id);
    const off = !a || !b;
    return `<label class="row" style="font-size:0.8125rem"><input type="checkbox" data-pick="sr${i}"${S.picks['sr' + i] && !off ? ' checked' : ''}${off ? ' disabled' : ''}>${nm(a, r.a)} ↔ ${nm(b, r.b)} · ${esc(r.type)} · ${(r.a_view || []).length || (r.b_view || []).length ? `${nm(a, r.a)}→${nm(b, r.b)} ${esc((r.a_view || []).join(', ') || '-')} · ${nm(b, r.b)}→${nm(a, r.a)} ${esc((r.b_view || []).join(', ') || '-')}` : `호감 ${r.affinity} · 긴장 ${r.tension}`}${off ? ' <span class="small">(고르지 않은 인물이라 넣지 않아요)</span>' : ''}</label>`;
  }).join('')}
  </section>`;
}


// 인물 역할 · 비중, 관계 사이를 고치면 접힌 줄도 바로 바꾼다 (이름은 app.js 가 data-char-head 를 바꾼다)
['input', 'change'].forEach((type) => document.addEventListener(type, (e) => {
  if (S.route[2] !== 'setup') return;
  const bind = e.target.dataset.bind || '';
  const c = bind.match(/^characters\.(\d+)\.(role|tier)$/);
  const cs = c && document.querySelector(`[data-char-sub="${c[1]}"]`);
  if (cs) cs.textContent = '· ' + charSub(P().characters[Number(c[1])]);
  const r = bind.match(/^relationships\.(\d+)\.type$/);
  const rs = r && document.querySelector(`[data-rel-sub="${r[1]}"]`);
  if (rs) rs.textContent = '· ' + (P().relationships[Number(r[1])].type.trim() || '사이를 정하지 않음');
}));

Object.assign(actions, {
  // 설정 도우미
  async suggest() {
    await startJob('suggest');
  },
  charContext(arg) {
    const [i, k] = String(arg).split('|');
    const c = P().characters[Number(i)];
    if (!c) return;
    c.context = k;
    markDirty();
    render();
  },
  dropSuggestion() {
    if (!confirmDrop('AI 설정 제안')) return;
    S.suggestion = null;
    render();
  },
  async applySuggestion() {
    const s = structuredClone(S.suggestion);
    // 고르지 않은 칸은 비워 보낸다. 서버는 빈 칸을 건너뛴다
    SUG_FIELDS.forEach(([k]) => {
      if (S.picks['sf:' + k] !== false) return;
      if (k.startsWith('world.')) s.world[k.slice(6)] = Array.isArray(s.world[k.slice(6)]) ? [] : '';
      else s[k] = '';
    });
    s.characters = s.characters.filter((_, i) => S.picks['sc' + i]);
    s.relationships = s.relationships.filter((r, i) => S.picks['sr' + i] && sugEnd(r.a) && sugEnd(r.b));
    await run('적용하는 중', async () => {
      await saveIfDirty();
      const before = setupCardKeys();
      S.project = await api('POST', `/projects/${enc(S.name)}/suggest/apply`, s);
      openNewCards(before);
      S.suggestion = null;
      toast('빈칸을 채웠어요. 기존 입력은 그대로예요.');
    });
    checkNames();  // 더한 인물 이름도 점검한다
  },
  toggleGenre(id) {
    const m = genreTarget();
    m.genres = m.genres.includes(id) ? m.genres.filter((g) => g !== id) : [...m.genres, id];
    syncGenre();
  },
  addCustomGenre() {
    const el = $('#genre-custom');
    const v = el.value.trim();
    if (!v) return;
    const hit = (S.genres || []).find((g) => g.name === v || g.id === v);
    const id = hit ? hit.id : v;
    if (!genreTarget().genres.includes(id)) genreTarget().genres.push(id);
    syncGenre();
    $('#genre-custom').focus();
  },
  // 이름 · 지명 후보 (코드가 무작위로 뽑고, AI 추천은 '이름·지명' 단계 모델이 그중에서 고른다)
  async nameCandidates(id) { await loadNames('c:' + id, { character: id }, false); },
  async nameAI(id) { await loadNames('c:' + id, { character: id }, true); },
  async placeCandidates() { await loadNames('place', { place_kind: S.placeKind || '' }, false); },
  async placeAI() { await loadNames('place', { place_kind: S.placeKind || '' }, true); },
  useName(arg) {
    const [id, ...rest] = arg.split('|');
    const c = P().characters.find((x) => x.id === id);
    if (!c) return;
    c.name = rest.join('|');
    delete S.names['c:' + id];
    markDirty();
    render();
    checkNames();
  },
  addPlace(name) {
    const w = P().world;
    if (!w.locations.includes(name)) w.locations.push(name);
    S.names.place.candidates = (S.names.place.candidates || []).filter((x) => x.name !== name);
    S.names.place.options = (S.names.place.options || []).filter((x) => x.name !== name);
    markDirty();
    render();
  },
  closeNames(key) {
    delete S.names[key];
    render();
  },
  async checkNames() { await checkNames(true); },

  addCharacter() {
    // id 는 관계와 플롯이 인물을 찾는 열쇠라 자동으로 짓고 화면에서는 접어 둔다
    const cs = P().characters;
    const ids = new Set(cs.map((c) => c.id));
    let id = ids.has('hero') ? '' : 'hero';
    for (let n = cs.length + 1; !id; n++) if (!ids.has('char' + n)) id = 'char' + n;
    openMap()['c:' + id] = true;
    cs.push({ id, name: '', role: id === 'hero' ? '주인공' : '조연', age: '', gender: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '', body: {}, context: 'auto' });
    markDirty();
    render();
  },
  removeCharacter(i) {
    const c = P().characters[i];
    // 플롯 · 반영 기록에 남은 id 는 지우지 않는다. 지우면 그 화의 등장 인물과 관계 사건이 id 로만 보인다
    const inPlots = P().episodes.filter((e) => e.plot.characters.includes(c.id)).map((e) => e.plot.number);
    const inHistory = [...new Set(P().history.filter((h) => (h.events || []).some((ev) => ev.actor === c.id || ev.target === c.id) || h.character_updates.some((u) => u.character_id === c.id)).map((h) => h.episode))];
    const used = [inPlots.length ? `${rangeText(inPlots)}화 플롯의 등장 인물` : '', inHistory.length ? `${rangeText(inHistory)}화 반영 기록` : ''].filter(Boolean);
    const warn = used.length ? `\n이 인물은 ${used.join('과 ')}에 남아 있어요. 그곳에는 이름 대신 id(${c.id})로 보여요.${inHistory.length ? ' 이미 반영한 화에 나온 인물이면 지우기보다 비중을 단역으로 낮추는 편이 안전해요.' : ''}` : '';
    if (!confirm(`${c.name || c.id} 인물을 삭제할까요? 관계와 지금 상태도 함께 삭제돼요. 저장하기 전에는 아래 띠에서 되살릴 수 있어요.${warn}`)) return;
    rememberRemoved(`인물 ${c.name || c.id}`, ['characters', 'relationships', 'states']);
    P().characters.splice(i, 1);
    P().relationships = P().relationships.filter((r) => r.a !== c.id && r.b !== c.id);
    P().states = P().states.filter((s) => s.character_id !== c.id);
    markDirty();
    render();
    checkNames();  // 지운 인물과 겹친다던 경고를 걷어 낸다
  },
  addRelationship() {
    const cs = P().characters;
    if (cs.length < 2) return toast('인물이 두 명 이상 있어야 해요', true);
    const has = new Set(P().relationships.map((r) => [r.a, r.b].sort().join('|')));
    const pair = cs.flatMap((x, i) => cs.slice(i + 1).map((y) => [x.id, y.id])).find(([a, b]) => !has.has([a, b].sort().join('|')));
    if (!pair) return toast('모든 인물 쌍에 관계가 이미 있어요', true);
    openMap()[relKey({ a: pair[0], b: pair[1] })] = true;
    P().relationships.push({ a: pair[0], b: pair[1], type: '', description: '', affinity: 0, tension: 0, goal_conflict: 0, a_view: [], b_view: [] });
    markDirty();
    render();
  },
  removeRelationship(i) {
    const r = P().relationships[i];
    rememberRemoved(`관계 ${charName(r.a) || r.a} ↔ ${charName(r.b) || r.b}`, ['relationships']);
    P().relationships.splice(i, 1);
    markDirty();
    render();
  },
  fillSlot(arg) {
    const [k, ...rest] = arg.split('|');
    const v = rest.join('|');
    const now = (P().meta.logline_parts[k] || '').trim();
    // 작가가 쓴 글은 묻고 바꾼다. 비었거나 예시 그대로면 바로 바꾼다
    if (now && now !== v && !slotValues(k).includes(now)) {
      const label = LOGLINE_SLOTS.find(([x]) => x === k)[1];
      if (!confirm(`'${label}' 칸에 쓴 글을 이 예시로 바꿀까요?\n지금: ${now}\n예시: ${v}`)) return;
    }
    const prev = composeLogline(P().meta.logline_parts);
    P().meta.logline_parts[k] = v;
    const el = $(`#f-meta-logline_parts-${k}`);
    if (el) el.value = P().meta.logline_parts[k];
    markDirty();
    updateLogline(prev);
  },
  setupOpenAll(arg) {
    const [kind, on] = arg.split('|');
    // details 를 바로 열고 닫는다. toggle 이벤트가 openMap 에 기억한다
    document.querySelectorAll(kind === 'c' ? '#setup-chars details.char-card' : '#setup-rels details.rel-card').forEach((d) => {
      d.open = on === '1';
      openMap()[d.dataset.openKey] = d.open;
    });
  },
  focusName(i) {
    // app.js 의 focusName 과 같고, 접힌 카드면 먼저 펼친다
    const card = document.getElementById(`char-${i}`);
    if (card) { card.open = true; openMap()[card.dataset.openKey] = true; }
    const el = document.getElementById(`f-characters-${i}-name`);
    if (el) { el.scrollIntoView({ block: 'center' }); el.focus(); }
  },
  slotExamples(k) {
    S.loglineMore = { ...S.loglineMore, [k]: !(S.loglineMore || {})[k] };
    refreshSlotExamples();
  },
  rebuildLogline() {
    const m = P().meta;
    m.logline = composeLogline(m.logline_parts);
    const raw = $('#f-meta-logline');
    if (raw) raw.value = m.logline;
    markDirty();
    updateLogline();
    toast('칸 내용으로 로그라인을 다시 만들었어요');
  },
  useExample(i) {
    const parts = P().meta.logline_parts;
    if (Object.values(parts).some((v) => v.trim()) && !confirm('지금 쓴 다섯 칸을 이 예시로 바꿀까요?')) return;
    Object.assign(parts, loglineExamples()[i]);
    LOGLINE_SLOTS.forEach(([k]) => { const el = $(`#f-meta-logline_parts-${k}`); if (el) el.value = parts[k]; });
    markDirty();
    updateLogline();
  },
  setDial(arg) {
    const [k, v] = arg.split('|');
    const m = P().meta;
    const prev = toneText(m.tone_dials);
    m.tone_dials[k] = m.tone_dials[k] === Number(v) ? 0 : Number(v);
    // 직접 쓴 톤 문장은 덮지 않는다. 다이얼 문장이 다르면 칸 아래 '다이얼 문장으로 바꾸기'로 권한다
    if (!m.tone.trim() || m.tone === prev) m.tone = toneText(m.tone_dials);
    markDirty();
    $('#tone-box').outerHTML = toneBox();
  },
  useToneText() {
    const m = P().meta;
    m.tone = toneText(m.tone_dials);
    markDirty();
    $('#tone-box').outerHTML = toneBox();
  },
  setRelType(arg) {
    const [i, type] = arg.split('|');
    const now = (P().relationships[i].type || '').trim();
    // 직접 쓴 사이는 묻고 바꾼다. 비었거나 다른 예시를 고른 것이면 바로 바꾼다
    if (now && now !== type && !REL_TYPES.includes(now) && !confirm(`'어떤 사이' 칸에 쓴 글을 이 예시로 바꿀까요?\n지금: ${now}\n예시: ${type}`)) return;
    P().relationships[i].type = type;
    markDirty();
    refreshRel(Number(i));
  },
  toggleView(arg) {
    const [i, side, word] = arg.split('|');
    const r = P().relationships[i];
    r[side] = r[side].includes(word) ? r[side].filter((w) => w !== word) : [...r[side], word];
    markDirty();
    refreshRel(Number(i));
  },
  setConflict(arg) {
    const [i, v] = arg.split('|');
    P().relationships[i].goal_conflict = Number(v);
    markDirty();
    refreshRel(Number(i));
  },
});
