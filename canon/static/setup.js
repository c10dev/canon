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
  const slots = LOGLINE_SLOTS.map(([k, label, hint]) => {
    const path = 'meta.logline_parts.' + k;
    return `<div class="slot">${input(label, path, { hint, beside: ideaBtn(path), after: ideaList(path) })}${slotExamples(k, label)}</div>`;
  }).join('');
  return `<div class="logline-box">
    <div class="logline-out"><p id="logline-preview" class="logline-preview" aria-live="polite">${esc(m.logline || LOGLINE_EMPTY)}</p><ul id="logline-checks" class="logline-checks" aria-label="로그라인 점검">${loglineChecksHtml(m)}</ul></div>
    ${legacy ? '<div class="note plain">지금 로그라인은 한 문장으로만 저장되어 있어요. 칸을 채우면 칸 내용으로 바뀌어요.</div>' : ''}
    <div class="slots">${slots}</div>
    <p class="small">다섯 칸을 채우면 한 문장으로 합쳐요. 점선 예시를 누르면 빈 칸에 들어가요.</p>
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

// 카드 접힌 줄(.row-sum): 왼쪽 표시 · 이름과 한 줄 요약 · 상태 칩 · 오른쪽 접힘 표시. 앱 CSS 의 summary 는 flex 라 기본 삼각형이 없어 직접 그린다
const foldMark = (open) => (open ? '▾' : '▸');
const foldTail = (open) => `<span class="fold-mark" aria-hidden="true">${foldMark(open)}</span>`;

/** 같은 인물끼리면 'same', 앞선 관계와 같은 쌍이면 그 관계 번호(0부터), 아니면 null. 서버는 이런 관계를 저장하지 않는다 (pipeline.validate_relationships) */
function relIssue(p, r, i) {
  if (r.a === r.b) return 'same';
  const j = p.relationships.findIndex((x, k) => k !== i && [x.a, x.b].sort().join('|') === [r.a, r.b].sort().join('|'));
  return j >= 0 ? j : null;
}

/** 볼 것이 있는 관계: 사이가 비었거나, 고칠 점이 있거나, 첫 반영 전인데 서로 보는 방식을 하나도 고르지 않았다 */
function relWork(p, r, i) {
  return !r.type.trim() || relIssue(p, r, i) !== null || (!p.snapshots.length && !(r.a_view || []).length && !(r.b_view || []).length);
}

/** 관계 접힌 줄의 둘째 줄: 서로 보는 방식과 목표 충돌, 첫 반영 뒤에는 지금 호감 · 긴장 */
function relViews(r) {
  if (P().snapshots.length) return `지금 호감 ${r.affinity} · 긴장 ${r.tension}`;
  const a = charName(r.a) || r.a;
  const b = charName(r.b) || r.b;
  const v = [(r.a_view || []).length ? `${a} → ${b}: ${r.a_view.join(' · ')}` : '', (r.b_view || []).length ? `${b} → ${a}: ${r.b_view.join(' · ')}` : ''].filter(Boolean);
  const c = conflictWord(r.goal_conflict || 0);
  if (c !== '아니다') v.push(`원하는 게 ${c === '조금' ? '조금 ' : '정면으로 '}부딪침`);
  return v.join(' / ') || '서로 보는 방식을 고르지 않았어요';
}

/** 관계 카드 접힌 줄: 두 인물 · 사이 · 보는 방식, 상태 칩 */
function relSummary(r, i, open) {
  const work = relWork(P(), r, i);
  return `<span class="who"><strong>${esc(charName(r.a) || r.a)} ↔ ${esc(charName(r.b) || r.b)}</strong> <span class="small" data-rel-sub="${i}">· ${esc(r.type.trim() || '사이를 정하지 않음')}</span>
    <span class="sub">${esc(relViews(r))}</span></span>
    <span class="chip ${work ? 'warn' : 'finalized'}">${work ? '확인 필요' : '채움'}</span>${foldTail(open)}`;
}

/** 비었거나 고칠 점이 있는 관계 (화면의 작품) */
function relNeedsWork(r, i) {
  return relWork(P(), r, i);
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
  const open = cardOpen(relKey(r), false);
  return `<details class="rel-card" id="rel-${i}" data-open-key="${esc(relKey(r))}"${open ? ' open' : ''}>
    <summary class="row-sum">${relSummary(r, i, open)}</summary>
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
    </div>
  </details>`;
}

/** 같은 인물끼리이거나 앞선 관계와 같은 쌍이면 알린다 (relIssue) */
function relProblem(r, i) {
  const j = relIssue(P(), r, i);
  if (j === 'same') return '<div class="note warn" role="status">같은 인물끼리는 관계를 만들 수 없어요. 인물 B를 바꾸세요.</div>';
  return j !== null ? `<div class="note warn" role="status">이 두 인물의 관계가 ${j + 1}번째에도 있어요. 하나만 남기세요.</div>` : '';
}

function refreshRel(i) {
  if (wizOn()) { redrawWizRels(); return; }
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

/** 인물 카드의 비중 칸. 비중 안내는 인물 구역 머리에 한 번만 둔다 (플롯 서랍은 plot.js 의 tierSelect) */
function setupTier(c, b, id) {
  return `<div class="field"><label for="${id}">비중${c.first_ep ? ` <span class="hint">${c.first_ep}화에 처음 나옴</span>` : ''}</label>
    <select id="${id}" data-bind="${b}.tier">${TIERS.map(([v, l]) => `<option value="${v}"${(c.tier || 'main') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>`;
}

// 인물 카드 접힌 줄의 AI에 넣기 표시. 고르는 칸은 인물 화면의 인물 카드에 있다 (cast.js charContextField)
const EYE = '<path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z"/><circle cx="8" cy="8" r="2"/>';
const eyeIcon = (off) => `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true" style="vertical-align:-2px">${EYE}${off ? '<path d="M2 14L14 2"/>' : ''}</svg>`;

/** 인물 카드 접힌 줄의 넣기 표시. 등장할 때(기본)는 표시하지 않는다 */
function charCtxMark(c) {
  const k = c.context || 'auto';
  if (k === 'auto') return '';
  const label = k === 'always' ? '항상 AI에 넣음' : 'AI에 넣지 않음';
  return ` <span class="small" title="${label}" style="color:var(--${k === 'always' ? 'accent-ink' : 'muted'})">· ${eyeIcon(k === 'off')} ${label}</span>`;
}

// 인물 줄의 '빈 칸 n' 으로 세는 칸
const CHAR_CORE = ['name', 'role', 'goal', 'wound', 'speech_style'];

/** 인물 접힌 줄의 역할 · 비중 · 나이 · 성별 */
function charSub(c) {
  const tier = (TIERS.find(([v]) => v === (c.tier || 'main')) || [])[1] || '';
  return [String(c.role || '').trim() || '역할을 정하지 않음', tier, String(c.age || '').trim(), String(c.gender || '').trim()].filter(Boolean).join(' · ');
}

/** 비어 있는 핵심 칸 수 (CHAR_CORE) */
const charGaps = (c) => CHAR_CORE.filter((k) => !String(c[k] || '').trim()).length;

/** 인물 접힌 줄의 상태 칩: 이름 점검 지적, 빈 칸 수, 다 채움 */
function charChip(c) {
  const issues = ((S.nameCheck || {}).issues || []).filter((x) => (x.ids || []).includes(c.id)).length;
  const gaps = charGaps(c);
  if (issues) return `<span class="chip warn">이름 점검 ${issues}</span>`;
  return gaps ? `<span class="chip warn">빈 칸 ${gaps}</span>` : '<span class="chip finalized">채움</span>';
}

/** 인물 접힌 줄 왼쪽 원: 이름 첫 글자, 색은 비중 (인물 화면의 인물 원과 같은 --ava-*) */
function charAva(c) {
  const t = { main: 'main', support: 'support', minor: 'minor' }[c.tier || 'main'] || 'main';
  return `<span class="row-ava t-${t}" aria-hidden="true">${esc([...String(c.name || '').trim()][0] || '?')}</span>`;
}

/** 이름 후보처럼 카드 안에서만 보이는 결과가 있는 인물. 그 카드는 펼쳐 둔다 */
function charNeedsWork(c) {
  return !!S.names['c:' + c.id];
}

// ----- 새 작품 마법사: 필수 칸 여섯 개를 여섯 걸음으로 묻는다. 다 채운 작품과 반영을 시작한 작품은 기획서(viewSetupDoc)로 연다 -----

const WIZ_STEPS = ['제목 · 장르', '로그라인', '세계', '인물', '관계', '마무리'];
// 필수 칸과 그 칸을 묻는 걸음. 순서는 setupReqs 와 같다
const WIZ_REQ = [['제목', 0], ['장르', 0], ['로그라인', 1], ['세계 배경', 2], ['인물 2명 이상', 3], ['관계 1개', 4]];

/** 필수 칸 여섯 개를 채웠나: 제목, 장르, 로그라인, 배경, 이름 있는 인물 둘, 서로 다른 두 인물의 관계 하나 */
function setupReqs(p) {
  const ids = new Set(p.characters.map((c) => c.id));
  return [
    !!p.meta.title.trim(),
    p.meta.genres.length > 0,
    !!p.meta.logline.trim(),
    !!p.world.setting.trim(),
    p.characters.filter((c) => (c.name || '').trim()).length >= 2,
    p.relationships.some((r) => r.a !== r.b && ids.has(r.a) && ids.has(r.b)),
  ];
}

/** 필수 칸이 빈 첫 걸음. 다 채웠으면 마무리 걸음 */
function wizFirstGap(p) {
  const k = setupReqs(p).findIndex((ok) => !ok);
  return k < 0 ? 5 : WIZ_REQ[k][1];
}

/** 걸음 막대 한 칸의 상태: 'done' 그 걸음의 필수를 다 채움, 'miss' 들렀는데 빈 필수가 남음, '' 아직. seen 은 들른 걸음 번호 */
function wizStepState(p, i, seen) {
  const r = setupReqs(p);
  const need = i === 5 ? r : r.filter((_, k) => WIZ_REQ[k][1] === i);
  if (need.every(Boolean)) return 'done';
  return seen.includes(i) ? 'miss' : '';
}

// 세계 종류: 고르면 배경 칸 맨 앞에 첫 문장이 들어간다. 뒤에 쓴 글은 그대로 둔다 (저장은 지금처럼 world.setting 글)
const WORLD_KINDS = [
  ['현대 한국', '지금의 한국.'],
  ['현대 판타지', '지금의 한국에 게이트와 각성자가 나타난 세계.'],
  ['서양풍 제국', '귀족과 황실이 다스리는 서양풍 제국.'],
  ['중세 판타지 왕국', '검과 마법이 있는 중세풍 왕국.'],
  ['동양 무협', '문파와 강호가 얽힌 무림.'],
  ['궁중 사극', '왕실과 궁궐을 중심으로 한 옛 한국.'],
  ['학원 · 아카데미', '능력자를 길러 내는 학원.'],
  ['근미래 도시', '기술이 조금 앞선 가까운 미래의 도시.'],
  ['디스토피아', '무너진 질서 위에 세워진 통제 사회.'],
  ['우주 SF', '여러 행성을 오가는 우주 시대.'],
  ['현대 해외', '지금의 해외 도시.'],
];
// 시대: 고르면 world.era 에 이 말이 그대로 들어간다
const ERAS = ['현대', '근미래', '먼 미래', '근대 · 개화기', '조선', '고려 이전', '중세풍', '근세풍', '고대풍', '시대를 정하지 않음'];
// 장르 id(genres.CATALOG)마다 앞에 둘 [세계 종류, 시대]
const WORLD_REC = {
  romance: [['현대 한국'], ['현대']],
  drama: [['현대 한국'], ['현대']],
  office: [['현대 한국'], ['현대']],
  healing: [['현대 한국'], ['현대']],
  sports: [['현대 한국'], ['현대']],
  romance_fantasy: [['서양풍 제국', '중세 판타지 왕국'], ['중세풍', '근세풍']],
  fantasy: [['중세 판타지 왕국', '서양풍 제국'], ['중세풍']],
  light_novel: [['중세 판타지 왕국', '학원 · 아카데미'], ['중세풍', '현대']],
  modern_fantasy: [['현대 판타지'], ['현대']],
  martial_arts: [['동양 무협'], ['고대풍']],
  alt_history: [['궁중 사극'], ['조선', '근대 · 개화기']],
  sf: [['우주 SF', '근미래 도시', '디스토피아'], ['근미래', '먼 미래']],
  academy: [['학원 · 아카데미'], []],
  mystery: [['현대 한국'], ['현대', '근대 · 개화기']],
  thriller: [['현대 한국', '근미래 도시'], ['현대']],
  horror: [['현대 한국'], ['현대']],
};

/** 배경 글이 고른 세계 종류 문장으로 시작하면 그 종류 이름 */
function worldKindOf(setting) {
  const w = WORLD_KINDS.find(([, s]) => (setting || '').startsWith(s));
  return w ? w[0] : '';
}

/** 세계 종류를 고른 뒤의 배경 글: 앞의 종류 문장만 바꾸고 뒤 글은 남긴다. 고른 종류를 다시 고르면 종류 문장만 뺀다 */
function withWorldKind(setting, label) {
  const cur = WORLD_KINDS.find(([l]) => l === worldKindOf(setting));
  const rest = (cur ? setting.slice(cur[1].length) : setting || '').trim();
  const pick = WORLD_KINDS.find(([l]) => l === label);
  if (!pick || (cur && cur[0] === label)) return rest;
  return pick[1] + (rest ? ' ' + rest : '');
}

/** 고른 장르 순서대로 모은 추천 (k 0 세계 종류, 1 시대) */
function worldRecs(genres, k) {
  const out = [];
  genres.forEach((g) => ((WORLD_REC[g] || [[], []])[k]).forEach((x) => { if (!out.includes(x)) out.push(x); }));
  return out;
}

/** 이 작품의 설정 화면 보기: 'wizard' 마법사, 'doc' 기획서. 처음 열 때 정하고 그 세션에서는 바뀌지 않는다 (다 채워도 마법사가 갑자기 닫히지 않게) */
function setupMode() {
  S.setupModes = S.setupModes || {};
  if (!S.setupModes[S.name]) S.setupModes[S.name] = P().snapshots.length || setupReqs(P()).every(Boolean) ? 'doc' : 'wizard';
  return S.setupModes[S.name];
}

/** 마법사 걸음과 들른 걸음. 처음에는 필수 칸이 빈 첫 걸음에서 연다 */
function wizState() {
  S.wiz = S.wiz || {};
  if (!S.wiz[S.name]) {
    const step = wizFirstGap(P());
    S.wiz[S.name] = { step, seen: [step] };
  }
  return S.wiz[S.name];
}

const wizOn = () => S.route[2] === 'setup' && !!P() && setupMode() === 'wizard';

/** 필수 칸 수 막대 (목차 맨 위) */
function wizMeter() {
  const n = setupReqs(P()).filter(Boolean).length;
  return `<span class="req-meter" id="wiz-meter"><span class="bar" aria-hidden="true"><i style="width:${(n / 6) * 100}%"></i></span>필수 ${n}/6</span>`;
}

/** 마법사 목차: 기획서 목차(docToc)와 같은 공용 목차 틀(outline.js)이고, 줄이 걸음이다. 좁은 폭에서는 걸음 막대와 'n/6 · 걸음'만 */
function wizStepper() {
  const w = wizState();
  const steps = WIZ_STEPS.map((s, i) => {
    const st = wizStepState(P(), i, w.seen);
    const word = st === 'done' ? ', 채움' : st === 'miss' ? ', 빈 필수 칸 있음' : '';
    const mark = st === 'done' ? '✓' : i + 1;
    return `<button type="button" class="outline-item ${st}" data-action="wizGo" data-arg="${i}"${i === w.step ? ' aria-current="step"' : ''} aria-label="${i + 1}. ${s}${word}"><i class="bar" aria-hidden="true"></i><span class="n" aria-hidden="true">${mark}</span><span class="tl">${s}</span><span class="st${st === 'miss' ? ' warn' : ''}">${st === 'miss' && i !== w.step ? '빈 필수' : ''}</span></button>`;
  }).join('');
  return outlineNav({ id: 'wiz-steps', label: '설정 걸음', cls: 'steps',
    body: `${wizMeter()}${steps}<p class="small outline-note">필수를 다 채우면 같은 목차로 모든 칸을 한 장에서 고쳐요.</p>`,
    after: `<span class="wiz-now" aria-hidden="true">${w.step + 1}/6 · ${WIZ_STEPS[w.step]}<span>필수 ${setupReqs(P()).filter(Boolean).length}/6</span></span>` });
}

/** 필수 칸 표시. 칸을 채우면 refreshWiz 가 글자를 바꾼다 */
function wizTag(k) {
  const ok = setupReqs(P())[k];
  return `<span class="req-tag${ok ? ' ok' : ''}" data-wiz-req="${k}">${ok ? '채움' : '필수'}</span>`;
}

const wizQ = (title, desc) => `<div class="wiz-q"><h2 id="wiz-q" tabindex="-1">${title}</h2><p>${desc}</p></div>`;

/** 추천 줄과 나머지 줄로 나눈 고르기 칩 */
function wizChips(id, all, rec, on, action, labId) {
  const btn = (x) => `<button type="button" aria-pressed="${on(x)}" data-action="${action}" data-arg="${esc(x)}">${esc(x)}</button>`;
  const rest = all.filter((x) => !rec.includes(x));
  const recRow = rec.length ? `<div class="genre-opts"><span class="chip ai wiz-rec">장르에 맞춰 추천</span>${rec.map(btn).join('')}</div>` : '';
  return `<div class="wiz-chips" id="${id}" role="group" aria-labelledby="${labId}">${recRow}<div class="genre-opts">${rest.map(btn).join('')}</div></div>`;
}

function wizBasics() {
  const m = P().meta;
  return `${wizQ('어떤 이야기인가요?', '제목과 장르를 정해요. 둘 다 나중에 바꿀 수 있어요.')}
    <div class="field"><div class="lab-row"><label for="f-meta-title">제목 ${wizTag(0)}</label>${ideaBtn('meta.title', '제목 후보')}</div><input id="f-meta-title" type="text" value="${esc(m.title)}" data-bind="meta.title" data-kind="text" placeholder="예: 소금 정원의 계약">${ideaList('meta.title')}</div>
    <div class="row">${wizTag(1)}<span class="small">장르를 하나 이상 골라요</span></div>
    ${genrePicker()}
    ${serial() ? input('총 화수', 'meta.target_episodes', { type: 'number', min: 1, max: 1000, hint: '늘리거나 줄이면 마지막 부 끝 화가 따라가요' }) : input('총 화수', 'meta.target_episodes', { type: 'number', min: 4, max: 40, hint: '단편은 10~20화를 권해요 · 4~40화' })}
    ${adultCheck(`data-bind="meta.adult" data-kind="bool"${m.adult ? ' checked' : ''}`)}`;
}

function wizLogline() {
  return `${wizQ('한 문장으로 줄이면요?', '다섯 칸을 채우면 로그라인 한 문장이 돼요. AI가 플롯을 짤 때 가장 먼저 읽는 문장이에요.')}
    <div class="row">${wizTag(2)}<span class="small">합친 문장이 생기면 채워져요</span></div>
    ${loglineBuilder()}`;
}

function wizWorld() {
  const w = P().world;
  const g = P().meta.genres;
  const kind = worldKindOf(w.setting);
  return `${wizQ('어디서 벌어지나요?', '세계 종류를 고르면 시작할 수 있어요. 고른 뒤 한두 문장을 더 적으면 AI가 더 잘 맞춰요.')}
    <div class="field"><span class="label-text" id="wiz-world-lab">세계 종류 ${wizTag(3)} <span class="hint">고르면 배경 칸 첫 문장이 돼요</span></span>
      ${wizChips('wiz-world-chips', WORLD_KINDS.map(([l]) => l), worldRecs(g, 0), (x) => x === kind, 'wizWorld', 'wiz-world-lab')}</div>
    ${input('배경', 'world.setting', { rows: 3, hint: '고르지 않고 직접 써도 돼요', placeholder: '예: 소금이 돈을 대신하는 북방 왕국 헤른', aside: ideaBtn('world.setting', '배경 후보'), after: ideaList('world.setting') })}
    <div class="field"><span class="label-text" id="wiz-era-lab">시대 <span class="hint">선택</span></span>
      ${wizChips('wiz-era-chips', ERAS, worldRecs(g, 1), (x) => x === w.era, 'wizEra', 'wiz-era-lab')}
      <input id="wiz-era-custom" type="text" value="${esc(ERAS.includes(w.era) ? '' : w.era)}" data-bind="world.era" data-kind="text" aria-label="시대 직접 쓰기" placeholder="직접 쓰기: 예) 중세풍, 증기 기관이 막 들어오는 때"></div>`;
}

const WIZ_ROLES = ['주인공', '상대역', '조력자', '라이벌', '악역'];

function wizPerson(c, i) {
  const b = `characters.${i}`;
  const who = esc(c.name || `${i + 1}번 인물`);
  return `<div class="wiz-person" id="wiz-char-${i}">
    <div class="between"><strong data-char-head="${i}">${esc(c.name || '이름 없음')}</strong>
      <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보</button><button type="button" class="ai-mini" data-action="nameAI" data-arg="${esc(c.id)}" title="AI가 이 인물 이름을 골라요">✦ AI 이름 추천</button>
      <button type="button" class="btn small danger" data-action="removeCharacter" data-arg="${i}" aria-label="${who} 빼기">빼기</button></div></div>
    ${namePicks('c:' + c.id, 'useName', (n) => `${c.id}|${n}`)}
    <div class="wiz-row3">${input('이름', b + '.name')}${input('나이', b + '.age', { placeholder: '예: 22' })}${input('성별', b + '.gender', { placeholder: '여' })}</div>
    ${nameIssuesFor(c.id)}
    ${input('역할', b + '.role', { placeholder: '주인공, 상대역, 조력자…' })}
    <div class="genre-opts ex-opts" role="group" aria-label="${who} 역할 예시">${WIZ_ROLES.map((r) => `<button type="button" aria-pressed="${c.role === r}" data-action="wizRole" data-arg="${i}|${r}">${r}</button>`).join('')}</div>
    ${input('원하는 것', b + '.goal', { hint: '한 줄', placeholder: '예: 염전을 되찾아 동생을 지키고 싶다' })}
  </div>`;
}

function wizCast() {
  const p = P();
  const n = p.characters.filter((c) => (c.name || '').trim()).length;
  return `${wizQ('누가 나오나요?', '주요 인물 두세 명만 적어요. 두려운 것 · 숨기는 것 · 말투 같은 상세는 마친 뒤 기획서에서 채워요.')}
    <div class="row">${wizTag(4)}<span class="small">이름 있는 인물 ${n}명</span><button type="button" class="btn small ghost" data-action="checkNames">이름 점검</button></div>
    ${nameCheckBox()}
    <div class="wiz-people">${p.characters.map(wizPerson).join('') || '<div class="note plain">아직 인물이 없어요. 로그라인에 나온 사람부터 적어 보세요.</div>'}</div>
    <div class="row"><button type="button" class="btn ghost" data-action="addCharacter">+ 인물 더하기</button><button type="button" class="btn" data-action="dexRoll" title="원형 · 상처 · 말투 · 비틀기 · 이름을 섞어 3안을 보여 줘요">원형 도감 주사위</button></div>
    ${dexRollBox()}`;
}

function wizRel(r, i) {
  const p = P();
  const b = `relationships.${i}`;
  const opts = (sel) => (p.characters.some((c) => c.id === sel) ? '' : `<option value="${esc(sel)}" selected>(없는 인물: ${esc(sel)})</option>`)
    + p.characters.map((c) => `<option value="${esc(c.id)}"${c.id === sel ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('');
  const chips = (vals, on, act) => vals.map(([label, arg]) => `<button type="button" aria-pressed="${on(label)}" data-action="${act}" data-arg="${esc(`${i}|${arg}`)}">${esc(label)}</button>`).join('');
  const a = charName(r.a) || r.a;
  const bn = charName(r.b) || r.b;
  const view = (side, from, to) => `<div class="field"><span class="label-text">${esc(from)}${josa(from, '은', '는')} ${esc(to)}${josa(to, '을', '를')}</span>
    <div class="genre-opts" role="group" aria-label="${esc(from)}이(가) ${esc(to)}을(를) 보는 방식">${chips(VIEWS.map((w) => [w, `${side}|${w}`]), (w) => (r[side] || []).includes(w), 'toggleView')}</div></div>`;
  return `<div class="wiz-rel" id="wiz-rel-${i}">
    <div class="between"><strong>관계 ${i + 1}</strong><button type="button" class="btn small danger" data-action="removeRelationship" data-arg="${i}" aria-label="관계 ${i + 1} 빼기">빼기</button></div>
    <div class="wiz-pair"><div class="field"><label for="ra${i}">인물 A</label><select id="ra${i}" data-bind="${b}.a">${opts(r.a)}</select></div><span aria-hidden="true">↔</span><div class="field"><label for="rb${i}">인물 B</label><select id="rb${i}" data-bind="${b}.b">${opts(r.b)}</select></div></div>
    ${relProblem(r, i)}
    ${input('어떤 사이', b + '.type', { placeholder: '예: 계약 부부, 오빠의 친구' })}
    <div class="genre-opts ex-opts" role="group" aria-label="어떤 사이 예시">${chips(REL_TYPES.map((t) => [t, t]), (t) => r.type === t, 'setRelType')}</div>
    ${p.snapshots.length ? `<div class="small">지금 호감 ${r.affinity} · 긴장 ${r.tension}. 첫 반영 뒤에는 본문의 관계 사건으로 바뀌어요.</div>` : `${view('a_view', a, bn)}${view('b_view', bn, a)}`}
    <div class="field"><span class="label-text">원하는 게 부딪치나요</span><div class="seg" role="group" aria-label="목표 충돌">${chips(CONFLICTS, (w) => conflictWord(r.goal_conflict || 0) === w, 'setConflict')}</div></div>
  </div>`;
}

function wizRelList() {
  const rels = P().relationships.map(wizRel).join('') || '<div class="note plain">관계가 없어요. 아래에서 더해요.</div>';
  return autoOn() ? `<fieldset disabled class="lockset" aria-describedby="rel-lock">${rels}</fieldset>` : rels;
}

function wizRels() {
  const n = P().characters.filter((c) => (c.name || '').trim()).length;
  const q = wizQ('두 사람은 어떤 사이인가요?', '관계 하나면 시작할 수 있어요. 여기서 고른 시작 관계는 1화를 반영하면 잠겨요.');
  if (n < 2) {
    return `${q}<div class="note plain">관계를 만들려면 이름이 있는 인물이 둘 있어야 해요. 지금은 ${n}명이에요.
      <button type="button" class="btn small" data-action="wizGo" data-arg="3">인물 걸음으로</button></div>`;
  }
  return `${q}<div class="row">${wizTag(5)}</div>
    ${autoOn() ? `<div class="note warn" id="rel-lock">자동 집필이 도는 동안은 관계를 고칠 수 없어요. 고치려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : ''}
    <div id="wiz-rels" class="wiz-people">${wizRelList()}</div>
    <div><button type="button" class="btn ghost" data-action="addRelationship"${autoOn() ? ' disabled' : ''}>+ 관계 더하기</button></div>`;
}

function wizFinish() {
  const p = P();
  const r = setupReqs(p);
  const all = r.every(Boolean);
  const named = p.characters.filter((c) => (c.name || '').trim());
  const vals = [p.meta.title, p.meta.genres.map((id) => (genreById(id) || {}).name || id).join(', '), p.meta.logline, p.world.setting,
    named.map((c) => c.name).join(', '), p.relationships.filter((x) => x.a !== x.b).map((x) => `${charName(x.a) || x.a} ↔ ${charName(x.b) || x.b}${x.type ? ' · ' + x.type : ''}`).join(' / ')];
  const rows = WIZ_REQ.map(([label, step], i) => `<li><span class="mark ${r[i] ? 'ok' : 'no'}" aria-hidden="true">${r[i] ? '✓' : '!'}</span><span class="small">${label}</span>
    <span class="v small${r[i] ? '' : ' muted'}">${esc(vals[i]) || '비어 있어요'}</span><button type="button" class="btn small${r[i] ? '' : ' on'}" data-action="wizGo" data-arg="${step}" aria-label="${label} ${r[i] ? '고치기' : '채우기'}">${r[i] ? '고치기' : '채우기'}</button></li>`).join('');
  return `${wizQ(all ? '뼈대가 섰어요' : '필수 칸이 남았어요', all ? '나머지 칸은 지금 더하거나, 마친 뒤 기획서에서 언제든 채워요.' : '남은 칸을 채우면 문체 단계로 넘어갈 수 있어요.')}
    <ul class="wiz-sum">${rows}</ul>
    <details class="wiz-more"><summary>더 채우면 좋아요 <span class="small">주제 · 톤 · 세계 규칙 · 장소 · 이름 스타일 · 분량 · 메모</span></summary><div class="wiz-more-body">
      ${input('주제', 'meta.theme', { hint: '이 이야기가 끝까지 묻는 질문 하나', placeholder: '예: 떠난 사람을 이해하면 용서할 수 있나?' })}
      ${toneBox()}
      ${input('깨면 안 되는 규칙', 'world.rules', { kind: 'list' })}
      ${input('장소', 'world.locations', { kind: 'list' })}
      ${nameStyleField()}
      ${input('이름 규칙', 'world.name_rules', { kind: 'list', rows: 2, placeholder: "예: 북부 귀족은 성 앞에 '폰'을 붙인다" })}
      ${input('화당 분량', 'meta.words_per_episode', { type: 'number', hint: '공백 포함 글자 수' })}
      ${input('메모', 'meta.notes', { rows: 2 })}
    </div></details>
    <div class="note plain">인물 상세(두려운 것 · 숨기는 것 · 말투 · 성격 · 외모), 신체 프로필, 삽화 외형, AI에 넣기, 상태창 처음 수치는 기획서에서 고쳐요.</div>`;
}

/** 마법사 아래에 붙는 버튼 줄: 이전 · 지금 걸음 · 다음. 마무리 걸음은 기획서로 보기 · 문체 레퍼런스로 */
function wizFoot(step) {
  const back = `<button type="button" class="btn" data-action="wizGo" data-arg="${step - 1}"${step === 0 ? ' disabled' : ''}>이전</button>`;
  const where = `<span class="small foot-where">${step + 1}/6 · ${WIZ_STEPS[step]}${step < 5 ? ` · 다음은 ${WIZ_STEPS[step + 1]}` : ''}</span>`;
  if (step < 5) return `<div class="setup-foot">${back}${where}<span class="sp"></span><button type="button" class="btn primary" data-action="wizGo" data-arg="${step + 1}">다음</button></div>`;
  const gaps = WIZ_REQ.filter((_, k) => !setupReqs(P())[k]).map(([l]) => l);
  const next = gaps.length
    ? `<button type="button" class="btn primary" aria-disabled="true" disabled aria-describedby="wiz-gaps">문체 레퍼런스로</button>`
    : `<a class="btn primary" href="${base()}/style">문체 레퍼런스로</a>`;
  return `<div class="setup-foot">${back}${where}<span class="sp"></span><button type="button" class="btn" data-action="setupMode" data-arg="doc">기획서로 보기</button>${next}
    ${gaps.length ? `<span class="wiz-why small" id="wiz-gaps">남은 필수 칸: ${gaps.join(', ')}</span>` : ''}</div>`;
}

function viewSetupWizard() {
  const w = wizState();
  const bodies = [wizBasics, wizLogline, wizWorld, wizCast, wizRels, wizFinish];
  const right = `${chatButton('setup')}<button type="button" class="btn ghost" data-action="setupMode" data-arg="doc">한 장으로 모두 보기</button>`;
  return `${header('1단계 · 새 작품', '설정 도우미', '', right)}
    ${aiNote()}
    ${S.suggestion ? viewSuggestion() : ''}
    ${outlineDoc(wizStepper(), `<div class="setup-secs"><section class="card wiz-card" aria-labelledby="wiz-q">${bodies[w.step]()}</section></div>`)}
    ${wizFoot(w.step)}${chatPanel('setup')}`;
}

/** 칸을 고치면 필수 칸 수, 목차, 필수 표시, 기획서 머리 요약만 다시 그린다 (입력 중인 칸의 포커스 유지) */
function refreshWiz() {
  if (S.route[2] !== 'setup' || !P()) return;
  if ($('#wiz-steps')) outlineRefresh('wiz-steps', wizStepper());
  if ($('#setup-toc')) outlineRefresh('setup-toc', docToc());
  const r = setupReqs(P());
  document.querySelectorAll('[data-wiz-req]').forEach((el) => {
    const ok = r[Number(el.dataset.wizReq)];
    el.className = 'req-tag' + (ok ? ' ok' : '');
    el.textContent = ok ? '채움' : '필수';
  });
  const st = docStatus(P());
  document.querySelectorAll('[data-sec-n]').forEach((el) => {
    const x = st[Number(el.dataset.secN)];
    el.className = 'sec-n' + (x.done ? ' ok' : '');
    el.textContent = x.done ? '✓' : Number(el.dataset.secN) + 1;
  });
  const sum = $('#setup-sum');
  if (sum) sum.textContent = docSummary(P());
}

/** 세계 종류 · 시대 칩만 다시 그린다 */
function refreshWizChips() {
  const w = P().world;
  const g = P().meta.genres;
  const kind = worldKindOf(w.setting);
  const wc = $('#wiz-world-chips');
  if (wc) wc.outerHTML = wizChips('wiz-world-chips', WORLD_KINDS.map(([l]) => l), worldRecs(g, 0), (x) => x === kind, 'wizWorld', 'wiz-world-lab');
  const ec = $('#wiz-era-chips');
  if (ec) ec.outerHTML = wizChips('wiz-era-chips', ERAS, worldRecs(g, 1), (x) => x === w.era, 'wizEra', 'wiz-era-lab');
}

/** 관계 카드만 다시 그린다. 고르던 칸(인물 A · B 같은)에 포커스를 돌려준다 */
function redrawWizRels() {
  const box = $('#wiz-rels');
  if (!box) return;
  const id = document.activeElement && document.activeElement.id;
  box.innerHTML = wizRelList();
  const el = id && document.getElementById(id);
  if (el) el.focus({ preventScroll: true });
  refreshWiz();
}

// 마법사에서 칸을 고치면 필수 표시를 바꾸고, 배경 · 시대 글이 바뀌면 칩 고르기도 맞춘다
['input', 'change'].forEach((type) => document.addEventListener(type, (e) => {
  if (!e.target.dataset || !e.target.dataset.bind || S.route[2] !== 'setup' || !P()) return;
  refreshWiz();
  if (/^world\.(setting|era)$/.test(e.target.dataset.bind)) refreshWizChips();
  const role = e.target.dataset.bind.match(/^characters\.(\d+)\.role$/);
  if (role) document.querySelectorAll(`[data-action="wizRole"][data-arg^="${role[1]}|"]`).forEach((btn) => btn.setAttribute('aria-pressed', String(btn.dataset.arg === `${role[1]}|${e.target.value}`)));
}));

// 마법사에서 대화 패널에 보이는 시작 문장 (걸음마다)
const WIZ_CHAT = [
  ['제목 후보를 다섯 개 내 줘', '이 장르에 어울리는 제목으로 바꿔 줘'],
  ['로그라인 빈 칸을 채워 줘', '로그라인이 밋밋해, 걸린 것을 키워 줘'],
  ['배경을 두세 문장으로 구체적으로 써 줘', '세계관 규칙을 세 개쯤 채워 줘'],
  ['로그라인에 나온 인물을 만들어 줘', '라이벌을 한 명 넣어 줘'],
  ['주인공과 상대역의 관계를 제안해 줘', '인물 사이 관계를 채워 줘'],
  ['남은 빈칸을 채워 줘', '주인공의 약점을 더 어둡게'],
];

/** 1단계 화면: 필수 칸이 빈 새 작품은 마법사, 그 밖은 기획서 */
function viewSetup() {
  // 인물 화면의 '기본 설정 고치기'(setup/<인물 id>)와 명령 팔레트의 설정 칸(palette.js)은 그 칸이 있는 기획서로 연다
  if (/^#f-(meta|world|characters)-/.test(String(S.jumpTo || ''))) { setupMode(); S.setupModes[S.name] = 'doc'; }
  return setupMode() === 'wizard' ? viewSetupWizard() : viewSetupDoc();
}

// ----- 기획서: 왼쪽 목차와 오른쪽 카드 한 열. 마법사와 같은 공용 목차 틀(outline.js)이고, 목차 줄이 구역이다 -----

/** 기획서 구역 [카드 id, 이름]. 목차와 카드가 이 순서다 */
const DOC_SECS = [['setup-basic', '기본 정보'], ['setup-logline', '로그라인'], ['setup-world', '세계'], ['setup-chars', '인물'], ['setup-rels', '관계'], ['setup-more', '더 채우기']];

/** 구역마다 목차 한 줄: done 필수를 채웠고 볼 것이 없음, text 상태 글, warn 볼 것이 있음. 순수 함수 (tests/test_setup_wizard_js.py) */
function docStatus(p) {
  const r = setupReqs(p);
  const gaps = p.characters.filter((c) => charGaps(c) > 0).length;
  const work = p.relationships.filter((x, i) => relWork(p, x, i)).length;
  const more = [p.meta.theme, p.meta.tone, p.meta.notes].filter((v) => String(v || '').trim()).length;
  const n = p.meta.logline.trim().length;
  return [
    { done: r[0] && r[1], text: `${p.meta.target_episodes}화`, warn: false },
    { done: r[2], text: n ? `${n}자` : '비어 있음', warn: !n },
    { done: r[3], text: p.world.locations.length ? `장소 ${p.world.locations.length}` : '', warn: false },
    { done: r[4] && !gaps, text: gaps ? `빈 칸 ${gaps}명` : `${p.characters.length}명`, warn: !!gaps || !r[4] },
    { done: r[5] && !work, text: work ? `확인 ${work}` : `${p.relationships.length}개`, warn: !!work || !r[5] },
    { done: false, text: `${more}/3`, warn: false },
  ];
}

/** 기획서 머리 한 줄: 남은 필수 칸, 아니면 남은 할 일 */
function docSummary(p) {
  const r = setupReqs(p);
  const miss = WIZ_REQ.filter((_, k) => !r[k]).map(([l]) => l);
  if (!p.characters.length) return '인물이 없어요. 빈칸 AI 제안으로 빈 칸과 인물 · 관계를 한 번에 받아 보세요.';
  if (miss.length) return `필수 칸이 ${miss.length}개 남았어요: ${miss.join(', ')}`;
  const st = docStatus(p);
  const left = [st[3].warn ? `인물 ${st[3].text}` : '', st[4].warn ? `관계 ${st[4].text}` : ''].filter(Boolean);
  return left.length ? `필수 여섯 칸을 다 채웠어요. 남은 것: ${left.join(', ')}` : '필수 여섯 칸을 다 채웠어요. 문체 레퍼런스로 넘어가도 돼요.';
}

// 목차에서 지금 보이는 구역 (스크롤로 바뀐다). 작품을 바꾸면 처음 구역
let tocCur = 0;

/** 기획서 목차(공용 목차 틀 outline.js). 좁은 폭(틀 720px 이하)에서는 위에 붙는 '지금 구역 ▾' 버튼으로 접는다 */
function docToc() {
  const st = docStatus(P());
  const items = DOC_SECS.map(([id, l], i) => `<button type="button" class="outline-item" data-action="tocGo" data-arg="${id}"${i === tocCur ? ' aria-current="true"' : ''}>
    <span class="n${st[i].done ? ' ok' : ''}" aria-hidden="true">${st[i].done ? '✓' : i + 1}</span><span class="tl">${l}</span><span class="st${st[i].warn ? ' warn' : ''}">${esc(st[i].text)}</span></button>`).join('');
  const cur = DOC_SECS[tocCur];
  return outlineNav({ id: 'setup-toc', label: '기획서 목차',
    now: `${tocCur + 1} · ${cur[1]} <span class="${st[tocCur].warn ? 'warn-text' : 'small'}">${esc(st[tocCur].text)}</span>`,
    body: `${wizMeter()}${items}<span class="outline-sep" aria-hidden="true"></span>
      <button type="button" class="outline-item" data-action="setupMode" data-arg="wizard"><span class="n" aria-hidden="true">↻</span><span class="tl">걸음으로 보기</span><span class="st"></span></button>` });
}

/** 구역 카드 머리: 번호(필수를 채우면 ✓) · 제목 · 오른쪽 버튼 */
function secHead(i, title, right = '') {
  const x = docStatus(P())[i];
  return `<div class="sec-head"><div class="sec-title"><span class="sec-n${x.done ? ' ok' : ''}" data-sec-n="${i}" aria-hidden="true">${x.done ? '✓' : i + 1}</span><h2 id="h-${DOC_SECS[i][0]}">${title}</h2></div>${right}</div>`;
}

/** 장르 칸: 고른 장르가 있으면 칩과 '장르 바꾸기'만, 누르면 목록을 그 자리에서 편다 */
function genreField() {
  const m = P().meta;
  if (!m.genres.length || (S.genreOpen || {})[S.name]) {
    return `${genrePicker()}${m.genres.length ? '<div><button type="button" class="btn small ghost" data-action="genreEdit" aria-expanded="true" aria-controls="genre-picker">장르 목록 접기</button></div>' : ''}`;
  }
  const names = m.genres.map((id) => (genreById(id) || {}).name || id);
  return `<div class="field"><span class="label-text">장르</span><div class="row">${names.map((x) => `<span class="chip confirmed">${esc(x)}</span>`).join('')}
    <button type="button" class="btn small ghost" data-action="genreEdit" aria-expanded="false">장르 바꾸기</button></div></div>`;
}

const episodesInput = () => (serial()
  ? input('총 화수', 'meta.target_episodes', { type: 'number', min: 1, max: 1000, hint: '늘리거나 줄이면 마지막 부 끝 화가 따라가요' })
  : input('총 화수', 'meta.target_episodes', { type: 'number', min: 4, max: 40, hint: '단편 4~40화, 10~20화를 권해요' }));

/** 인물 카드의 '더 자세히' 칸 + ✦ 후보 (ideas.js). 펼침은 openMap 의 'cd:<id>' 가 기억해 다시 그려도 접히지 않는다 */
const charIdeaInput = (label, path, opt) => input(label, path, { ...opt, aside: ideaBtn(path), after: ideaList(path) });

/** 인물 한 줄. 누르면 그 자리에서 펴고, 다른 인물은 접는다 (한 번에 하나) */
function charRow(c, i) {
  const b = `characters.${i}`;
  const open = cardOpen(charKey(c), charNeedsWork(c));
  return `<details class="char-card" id="char-${i}" data-open-key="${esc(charKey(c))}"${open ? ' open' : ''}>
    <summary class="row-sum">${charAva(c)}<span class="who"><strong data-char-head="${i}">${esc(c.name || '이름 없음')}</strong>${charCtxMark(c)}
      <span class="sub" data-char-sub="${i}">${esc(charSub(c))}</span></span><span data-char-chip="${i}">${charChip(c)}</span>${foldTail(open)}</summary>
    <div class="row-body">
      <div class="grid-3">${input('이름', b + '.name')}${input('역할', b + '.role', { placeholder: '주인공, 상대역, 조력자…' })}${setupTier(c, b, 'tier-' + i)}</div>
      ${nameIssuesFor(c.id)}
      <div class="grid-2">${input('나이', b + '.age', { placeholder: '예: 17세, 40대 초반' })}${input('성별', b + '.gender', { placeholder: '남 / 여' })}</div>
      <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보 뽑기</button><button type="button" class="btn small" data-action="nameAI" data-arg="${esc(c.id)}">✦ AI 이름 추천</button></div>
      ${namePicks('c:' + c.id, 'useName', (n) => `${c.id}|${n}`)}
      <div class="grid-2">${input('원하는 것', b + '.goal', { hint: '작품 전체에서' })}${input('두려운 것 · 약점', b + '.wound')}</div>
      <div class="grid-2">${input('숨기는 것', b + '.secrets', { kind: 'list', rows: 2 })}${input('말투 (대사)', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 한 줄' })}</div>
      <details data-open-key="${esc('cd:' + c.id)}"${cardOpen('cd:' + c.id, false) ? ' open' : ''}><summary>더 자세히: 성격, 배경, 외모, 아크</summary><div class="row-more">
        ${charIdeaInput('성격', b + '.personality', { rows: 2 })}${charIdeaInput('배경', b + '.background', { rows: 2 })}${charIdeaInput('외모', b + '.appearance')}
        ${charIdeaInput('아크', b + '.arc', { hint: '시작 → 결말' })}${input('id', b + '.id', { hint: '관계와 플롯이 인물을 찾는 값이라 바꿀 수 없어요', readonly: true })}
      </div></details>
      <div class="between"><span class="small">AI에 넣기, 서술 말투, 신체 프로필, 삽화 외형 태그는 <a href="${base()}/cast/${enc(c.id)}?tab=sheet">인물 카드</a>에서 고쳐요.</span>
        <button type="button" class="btn small danger" data-action="removeCharacter" data-arg="${i}" aria-label="${esc(c.name || c.id)} 삭제">삭제</button></div>
    </div>
  </details>`;
}

function viewSetupDoc() {
  const p = P();
  // 인물 화면의 '기본 설정 고치기'나 명령 팔레트로 인물 칸에 왔으면 그 인물 카드를 펼친다 (app.js 가 그 칸으로 포커스를 옮긴다)
  const jump = String(S.jumpTo || S.focusTarget || '').match(/^#f-characters-(\d+)-/);
  if (jump && p.characters[Number(jump[1])]) openMap()[charKey(p.characters[Number(jump[1])])] = true;
  if (tocCur >= DOC_SECS.length) tocCur = 0;
  const rels = p.relationships.map(relRow).join('');
  const lock = autoOn() ? `<div class="note warn" id="rel-lock">자동 집필이 도는 동안은 관계를 고칠 수 없어요. 반영하는 관계와 겹치지 않게 서버가 받지 않아요. 고치려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : '';

  // 인물이 없으면 첫 할 일은 AI 제안이다. 인물이 생기면 다음 단계(문체)를 앞세운다
  const first = !p.characters.length;
  const sug = ((b) => `<button type="button" class="btn${first ? ' primary' : ''}" data-action="suggest"${b.attr} title="비어 있는 칸과 새 인물 · 관계를 한 번에 제안해요. 채운 칸은 건드리지 않고, 고른 것만 적용해요">✦ ${b.label}</button>`)(jobBtn('suggest', null, '빈칸 AI 제안받기'));
  const go = (cls) => `<a class="btn${first ? '' : ' primary'} ${cls}" href="${base()}/style">문체 레퍼런스로</a>`;
  return `${header('1단계 · 기획서', '설정 도우미', `<span id="setup-sum">${esc(docSummary(p))}</span>`, `${sug}${chatButton('setup')}${go('setup-go')}`)}
    ${aiNote()}
    ${S.suggestion ? viewSuggestion() : ''}
    ${outlineDoc(docToc(), `<div class="setup-secs">
      <section class="card" id="setup-basic" aria-labelledby="h-setup-basic">
        ${secHead(0, '기본 정보')}
        <div class="grid-2">${input('제목', 'meta.title', { aside: ideaBtn('meta.title', '제목 후보'), after: ideaList('meta.title') })}${episodesInput()}</div>
        ${genreField()}
        ${adultCheck(`data-bind="meta.adult" data-kind="bool"${p.meta.adult ? ' checked' : ''}`)}
      </section>
      <section class="card" id="setup-logline" aria-labelledby="h-setup-logline">
        ${secHead(1, '로그라인', '<span class="small">AI가 플롯을 짤 때 가장 먼저 읽어요</span>')}
        ${loglineBuilder()}
      </section>
      <section class="card" id="setup-world" aria-labelledby="h-setup-world">
        ${secHead(2, '세계')}
        <div class="field"><span class="label-text" id="wiz-world-lab">세계 종류 <span class="hint">고르면 배경 칸 첫 문장이 돼요</span></span>
          ${wizChips('wiz-world-chips', WORLD_KINDS.map(([l]) => l), worldRecs(p.meta.genres, 0), (x) => x === worldKindOf(p.world.setting), 'wizWorld', 'wiz-world-lab')}</div>
        ${input('배경', 'world.setting', { rows: 2, aside: ideaBtn('world.setting', '배경 후보'), after: ideaList('world.setting') })}
        <div class="grid-2">${input('시대', 'world.era', { placeholder: '예: 중세풍, 현대' })}${nameStyleField()}</div>
        <div class="grid-2">${input('깨면 안 되는 규칙', 'world.rules', { kind: 'list' })}${input('장소', 'world.locations', { kind: 'list' })}</div>
        <div class="row"><select id="place-kind" aria-label="지명 종류" data-local="placeKind" style="width:auto;min-width:120px">${placeKindOptions()}</select>
          <button type="button" class="btn small" data-action="placeCandidates">지명 후보 뽑기</button><button type="button" class="btn small" data-action="placeAI">✦ AI 지명 추천</button></div>
        ${namePicks('place', 'addPlace', (n) => n)}
        ${input('이름 규칙', 'world.name_rules', { kind: 'list', rows: 2, placeholder: "예: 북부 귀족은 성 앞에 '폰'을 붙인다" })}
      </section>
      <section class="card" id="setup-chars" aria-labelledby="h-setup-chars">
        ${secHead(3, `인물 <span class="small">${p.characters.length}명</span>`, `<div class="row"><button type="button" class="btn small ghost" data-action="checkNames" title="글자가 겹치는 이름, 나이와 안 맞는 이름, AI가 자주 짓는 이름을 찾아요">이름 점검</button><button type="button" class="btn small" data-action="dexRoll" title="원형 · 상처 · 말투 · 비틀기 · 이름을 무작위로 섞어 3안을 보여 줘요">도감 주사위</button><button type="button" class="btn small" data-action="addCharacter">+ 인물</button></div>`)}
        <p class="small">이름 · 말투 · 성격은 고정 설정이에요. 화마다 바뀌는 감정과 목표는 상태 승인에서 관리해요. 주역은 매 화, 조연 · 단역은 나오는 화에만 AI에 들어가요.</p>
        ${nameCheckBox()}
        ${dexRollBox()}
        ${p.characters.length ? `<div class="setup-rows">${p.characters.map(charRow).join('')}</div>` : '<div class="note plain">인물이 없어요. 직접 더하거나 빈칸 AI 제안을 받으세요.</div>'}
      </section>
      ${setupStatLink()}
      <section class="card" id="setup-rels" aria-labelledby="h-setup-rels">
        ${secHead(4, `관계 <span class="small">${p.relationships.length}개</span>`, `<button type="button" class="btn small" data-action="addRelationship"${autoOn() ? ' disabled' : ''}>+ 관계</button>`)}
        <p class="small">${p.snapshots.length ? '첫 반영 뒤에는 본문의 관계 사건으로 계산돼요.' : '서로 어떻게 보는지 고르면 시작 관계를 계산해요. 긴장은 자동 계산이에요.'}</p>
        ${lock}
        ${rels ? `<div class="setup-rows">${autoOn() ? `<fieldset disabled class="lockset" aria-describedby="rel-lock">${rels}</fieldset>` : rels}</div>` : '<div class="note plain">관계가 없어요.</div>'}
      </section>
      <section class="card" id="setup-more" aria-labelledby="h-setup-more">
        ${secHead(5, '더 채우면 좋아요', '<span class="small">비워도 시작할 수 있어요</span>')}
        ${input('주제', 'meta.theme', { hint: '이 이야기가 끝까지 묻는 질문 하나', placeholder: '예: 떠난 사람을 이해하면 용서할 수 있나?' })}
        ${toneBox()}
        <div class="grid-2">${input('화당 분량', 'meta.words_per_episode', { type: 'number', hint: '공백 포함 글자 수' })}${input('메모', 'meta.notes', { rows: 2 })}</div>
      </section>
    </div>`)}
    ${first ? '' : `<div class="setup-foot phone-only">${go('')}</div>`}${chatPanel('setup')}`;
}

/** 상태창을 쓰는 작품이면 상태창 수치 화면으로 가는 줄. 작품 틀과 처음 수치는 그 화면에서 정한다 */
function setupStatLink() {
  const p = P();
  if (!swWanted(p) && !(swWin().names || []).length && !p.states.some((s) => (s.stats || []).length)) return '';
  return `<section class="card tight" id="setup-stats"><div class="between"><span><strong>상태창</strong> <span class="small">레벨 · 스킬처럼 본문 상태창에 나오는 값은 작품 틀과 처음 수치를 상태창 수치 화면에서 정해요</span></span>
    <a class="btn small" href="${base()}/statwin">상태창 수치</a></div></section>`;
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

// 이미 있는 인물에게 채우는 빈 칸 (pipeline.FILL_CHAR_FIELDS 와 같다, tests/test_setup_fill.py)
const SUG_FILL_FIELDS = [['role', '역할'], ...SUG_CHAR_FIELDS];
const blankVal = (v) => (Array.isArray(v) ? !v.some((x) => String(x).trim()) : !String(v || '').trim());

/** 제안 인물 c 가 이미 있는 인물이면, 그 인물의 빈 칸 중 제안에 값이 있는 칸 [[키, 칸 이름, 값 글], …]. 아니면 [] */
function sugFills(c) {
  const old = sameChar(c) && P().characters.find((x) => x.id === c.id);
  if (!old) return [];
  return SUG_FILL_FIELDS.filter(([k]) => blankVal(old[k]) && !blankVal(c[k]))
    .map(([k, label]) => [k, label, Array.isArray(c[k]) ? c[k].filter((x) => String(x).trim()).join(', ') : String(c[k]).trim()]);
}

/** 이미 있는 인물 카드: 채울 빈 칸마다 고르기 (기본은 모두 고름, 키 scf:<제안 번호>:<칸>) */
function sugFillCard(c, i) {
  const fills = sugFills(c);
  const rows = fills.map(([k, label, v]) => `<label class="row sug-field"><input type="checkbox" data-pick="scf:${i}:${k}"${S.picks[`scf:${i}:${k}`] !== false ? ' checked' : ''}><strong>${label}</strong> <span>${esc(v)}</span></label>`).join('');
  return `<div class="char-card suggested"><div class="row"><strong>${esc(c.name || P().characters.find((x) => x.id === c.id).name)}</strong><span class="small">${esc(c.role)} · ${esc(c.id)} · 이미 있음${fills.length ? ` · 빈칸 ${fills.length}개 채움` : ''}</span></div>
    ${fills.length ? `<div class="sug-fields" role="group" aria-label="${esc(c.name || c.id)} 빈칸 채우기">${rows}</div>` : '<span class="small">채울 빈칸이 없어요</span>'}</div>`;
}

/** 제안 인물의 모든 칸. 체크박스 label 밖에 두어 펼쳐도 고르기가 바뀌지 않는다 */
function sugCharDetails(c) {
  const rows = SUG_CHAR_FIELDS.map(([k, label]) => [label, Array.isArray(c[k]) ? c[k].join(', ') : String(c[k] || '').trim()])
    .filter(([, v]) => v);
  if (!rows.length) return '';
  return `<details><summary class="small">모든 칸 보기 (${rows.length})</summary><dl style="margin:6px 0 0;font-size:0.8125rem;line-height:1.5">${rows.map(([l, v]) => `<dt style="font-weight:700">${l}</dt><dd style="margin:0 0 6px">${esc(v)}</dd>`).join('')}</dl></details>`;
}

/** 적용 요청에 보낼 제안: 고르지 않은 칸 · 인물 · 관계를 뺀다 (서버 pipeline.apply_setup 은 빈 칸만 채운다) */
function sugPayload() {
  const s = structuredClone(S.suggestion);
  // 고르지 않은 칸은 비워 보낸다. 서버는 빈 칸을 건너뛴다
  SUG_FIELDS.forEach(([k]) => {
    if (S.picks['sf:' + k] !== false) return;
    if (k.startsWith('world.')) s.world[k.slice(6)] = Array.isArray(s.world[k.slice(6)]) ? [] : '';
    else s[k] = '';
  });
  s.characters = s.characters.map((c, i) => {
    if (!sameChar(c)) return S.picks['sc' + i] ? c : null;
    // 이미 있는 인물: 고르지 않은 빈 칸은 비워 보낸다. 서버는 빈 칸만 채운다 (fill_character)
    SUG_FILL_FIELDS.forEach(([k]) => { if (S.picks[`scf:${i}:${k}`] === false) c[k] = Array.isArray(c[k]) ? [] : ''; });
    return c;
  }).filter(Boolean);
  s.relationships = s.relationships.filter((r, i) => S.picks['sr' + i] && sugEnd(r.a) && sugEnd(r.b));
  return s;
}

function viewSuggestion() {
  const s = S.suggestion;
  const exists = (c) => sameChar(c);
  const clash = (c) => !sameChar(c) && P().characters.some((x) => x.id === c.id);
  return `<section class="card" style="border:2px solid var(--accent)">
    <div class="between"><h2>AI 제안 <span class="chip ai">적용 전</span></h2>${proposalActions(['dropSuggestion'], ['applySuggestion'])}</div>
    <p class="small">주제, 톤, 세계관, 이미 있는 인물은 비어 있는 칸에만 들어가요. 적어 둔 칸은 그대로예요.</p>
    <div class="sug-fields">${SUG_FIELDS.map(([k, label]) => {
    const v = sugValue(s, k);
    if (!v.length) return '';
    const have = sugValue(P(), k).length > 0;
    return `<label class="row sug-field${have ? ' skip' : ''}"><input type="checkbox" data-pick="sf:${k}"${!have && S.picks['sf:' + k] !== false ? ' checked' : ''}${have ? ' disabled' : ''}><strong>${label}</strong> <span>${esc(v)}</span>${have ? ' <span class="small">이미 있음 · 건너뜀</span>' : ''}</label>`;
  }).join('')}</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">
      ${s.characters.map((c, i) => exists(c) ? sugFillCard(c, i) : `<div class="char-card suggested"><label class="row" style="cursor:pointer"><input type="checkbox" data-pick="sc${i}"${S.picks['sc' + i] ? ' checked' : ''}><strong>${esc(c.name)}</strong><span class="small">${esc(c.role)} · ${esc(c.id)}${clash(c) ? ' · 이미 있는 다른 인물과 겹쳐 따로 넣어요' : ''}</span></label>
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


// 인물 칸 · 관계 사이를 고치면 접힌 줄(요약 · 상태 칩)도 바로 바꾼다 (이름은 app.js 가 data-char-head 를 바꾼다)
['input', 'change'].forEach((type) => document.addEventListener(type, (e) => {
  if (S.route[2] !== 'setup' || !P()) return;
  const bind = e.target.dataset.bind || '';
  const c = bind.match(/^characters\.(\d+)\./);
  const ch = c && P().characters[Number(c[1])];
  if (ch) {
    const sub = document.querySelector(`[data-char-sub="${c[1]}"]`);
    if (sub) sub.textContent = charSub(ch);
    const chip = document.querySelector(`[data-char-chip="${c[1]}"]`);
    if (chip) chip.innerHTML = charChip(ch);
  }
  const r = bind.match(/^relationships\.(\d+)\.type$/);
  const card = r && document.getElementById(`rel-${r[1]}`);
  if (card) card.querySelector(':scope > summary').innerHTML = relSummary(P().relationships[Number(r[1])], Number(r[1]), card.open);
}));

// 인물 · 관계 줄은 한 번에 하나만 편다: 접힌 줄을 누르면 같은 목록의 다른 펼친 줄을 접는다 (작가가 누를 때만, 다시 그릴 때는 기억대로)
document.addEventListener('click', (e) => {
  const sum = e.target.closest && e.target.closest('details.char-card > summary, details.rel-card > summary');
  if (!sum || S.route[2] !== 'setup') return;
  const d = sum.parentElement;
  if (d.open) return;
  const list = d.closest('.setup-rows');
  if (!list) return;
  list.querySelectorAll(`details.${d.classList.contains('char-card') ? 'char-card' : 'rel-card'}[open]`).forEach((x) => { x.open = false; });
});

// 기획서 목차의 지금 구역: 화면 위에서 120px 아래를 지난 마지막 구역(맨 아래면 마지막 구역). 바뀌면 목차만 다시 그린다
outlineSpy('setup-toc', {
  targets: () => DOC_SECS.map(([id], i) => [i, document.getElementById(id)]),
  set(cur) {
    if (cur === tocCur) return;
    tocCur = cur;
    outlineRefresh('setup-toc', docToc());
  },
});

Object.assign(actions, {
  // 새 작품 마법사
  async wizGo(arg) {
    const i = Number(arg);
    const w = wizState();
    if (!(i >= 0 && i <= 5) || i === w.step) return;
    // 앞으로 갈 때 저장한다. 저장하지 못하면 그 걸음에 남는다
    if (i > w.step && S.dirty && !(await run('저장 중', save, { render: 'none' }))) return;
    w.step = i;
    if (!w.seen.includes(i)) w.seen.push(i);
    render();
    window.scrollTo(0, 0);
    $('#wiz-q')?.focus({ preventScroll: true });
  },
  setupMode(mode) {
    S.setupModes = S.setupModes || {};
    S.setupModes[S.name] = mode === 'wizard' ? 'wizard' : 'doc';
    if (mode === 'wizard' && S.wiz) delete S.wiz[S.name];  // 다시 열면 필수 칸이 빈 첫 걸음부터
    render();
    window.scrollTo(0, 0);
  },
  wizWorld(label) {
    const w = P().world;
    w.setting = withWorldKind(w.setting, label);
    const el = $('#f-world-setting');
    if (el) el.value = w.setting;
    markDirty();
    refreshWizChips();
    refreshWiz();
    checkNames();
  },
  wizEra(label) {
    const w = P().world;
    w.era = w.era === label ? '' : label;
    const el = $('#wiz-era-custom');
    if (el) el.value = '';
    markDirty();
    refreshWizChips();
    checkNames();
  },
  wizRole(arg) {
    const [i, role] = arg.split('|');
    const c = P().characters[Number(i)];
    if (!c) return;
    c.role = role;
    const el = $(`#f-characters-${i}-role`);
    if (el) el.value = c.role;
    markDirty();
    document.querySelectorAll(`[data-action="wizRole"][data-arg^="${i}|"]`).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.arg === `${i}|${c.role}`)));
  },
  // 설정 도우미
  async suggest() {
    await startJob('suggest');
  },
  dropSuggestion() {
    if (!confirmDrop('AI 설정 제안')) return;
    S.suggestion = null;
    render();
  },
  async applySuggestion() {
    const s = sugPayload();
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
    refreshWiz();
  },
  addCustomGenre() {
    const el = $('#genre-custom');
    const v = el.value.trim();
    if (!v) return;
    const hit = (S.genres || []).find((g) => g.name === v || g.id === v);
    const id = hit ? hit.id : v;
    if (!genreTarget().genres.includes(id)) genreTarget().genres.push(id);
    syncGenre();
    refreshWiz();
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
    // 인물 칸 ✦ 후보는 번호로 칸을 찾아서, 번호가 밀리면 다른 인물 칸 아래에 뜬다
    Object.keys(S.ideas || {}).filter((k) => k.startsWith('characters.')).forEach((k) => delete S.ideas[k]);
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
  /** 기획서 목차에서 구역으로 간다. 좁은 폭에서 펼친 목차는 공용 목차 틀이 닫는다 */
  tocGo(id) {
    const i = DOC_SECS.findIndex(([x]) => x === id);
    if (i >= 0) tocCur = i;
    actions.jumpTo(id);
  },
  /** 기획서 장르 칸: 고른 장르만 보기 ↔ 목록 펴기 */
  genreEdit() {
    S.genreOpen = { ...S.genreOpen, [S.name]: !(S.genreOpen || {})[S.name] };
    render();
    $('#setup-basic [data-action="genreEdit"]')?.focus({ preventScroll: true });
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
