/* 명령 팔레트. app.js 의 S, actions, P, base, esc, navItems, currentEp, saveShortcut, toast, focusMark, findMark, focusEl, STATUS 와
   home.js 의 nextStep 을 쓴다.
   Ctrl+K (macOS 는 ⌘K) 또는 좁은 화면 사이드바 머리의 '찾기'로 연다. 입력칸 안에서도 열린다.
   작품 안에서는 사이드바 화면(navItems 와 같은 이름), 화, 인물, 설정 칸(칸 이름과 값), 자주 쓰는 동작(다음 할 일, 저장)을 찾는다.
   설정 칸을 고르면 S.jumpTo 에 그 칸을 두고 설정 도우미로 간다. 설정 화면(setup.js)이 기획서로 열고 칸이 든 카드를 펼친다.
   작품 밖(작품 목록, 설정 등)에서는 작품 목록과 설정 화면만 찾는다.
   포커스는 검색 칸에만 두고, 위아래 화살표로 고른 항목은 aria-activedescendant 로 알린다.
   화면을 다시 그려도 남게 #app 밖(body)에 둔다. 닫으면 연 자리로 포커스를 돌린다. */
'use strict';

const PAL_LIMIT = 40;  // 한 번에 보이는 항목 수
const PAL_KIND = { act: '동작', screen: '화면', char: '인물', field: '설정 칸', ep: '화' };
// 찾는 설정 칸: [data-bind 경로, 칸 이름]. 이름은 기획서(setup.js)의 칸 이름과 같다
const PAL_SETUP = [
  ['meta.title', '제목'], ['meta.logline_parts.who', '로그라인 · 누가'], ['meta.logline_parts.why', '로그라인 · 무엇 때문에'],
  ['meta.logline_parts.goal', '로그라인 · 무엇을 하려 하나'], ['meta.logline_parts.block', '로그라인 · 무엇이 막나'],
  ['meta.logline_parts.stake', '로그라인 · 무엇이 걸렸나'], ['meta.logline', '로그라인 문장'], ['meta.theme', '주제'], ['meta.tone', '톤 문장'],
  ['meta.notes', '메모'], ['world.setting', '배경'], ['world.era', '시대'], ['world.rules', '깨면 안 되는 규칙'], ['world.locations', '장소'],
  ['world.name_rules', '이름 규칙'],
];
// 인물 카드의 칸: '<인물 이름> · <칸 이름>' 으로 찾는다
const PAL_CHAR_FIELDS = [
  ['role', '역할'], ['age', '나이'], ['goal', '원하는 것'], ['wound', '두려운 것 · 약점'], ['secrets', '숨기는 것'], ['speech_style', '말투 (대사)'],
  ['personality', '성격'], ['background', '배경'], ['appearance', '외모'], ['arc', '아크'],
];
const PAL_HINT = 40;  // 칸 값을 보이는 글자 수
const PAL_CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';

(function palStyle() {
  const css = `
.pal-back { position: fixed; inset: 0; z-index: 45; display: flex; justify-content: center; align-items: flex-start; padding: 12vh 16px 16px; background: var(--overlay); }
.pal { width: min(560px, 100%); max-height: 70vh; display: flex; flex-direction: column; background: var(--surface); color: var(--text); border: 1px solid var(--line-strong); border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,0.22); overflow: hidden; }
.pal input#pal-q { min-height: 52px; border: none; border-bottom: 1px solid var(--line); border-radius: 0; padding: 0 16px; font-size: 1rem; }
.pal input#pal-q:focus { outline: none; box-shadow: inset 0 -2px 0 var(--accent); }
.pal ul { list-style: none; margin: 0; padding: 6px; overflow-y: auto; }
.pal li[role="option"] { min-height: 44px; padding: 8px 12px; border-radius: 8px; display: flex; align-items: center; gap: 10px; cursor: pointer; }
.pal li[role="option"][aria-selected="true"] { background: var(--accent-soft); color: var(--accent-ink); }
.pal .pal-label { flex: 1 1 auto; min-width: 0; font-weight: 500; }
.pal .pal-hint { flex: 0 1 auto; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; max-width: 45%; }
.pal .pal-kind { flex: none; padding: 2px 8px; border-radius: 999px; background: var(--chip); color: var(--text-2); font-size: 0.6875rem; }
.pal .pal-empty { padding: 16px 12px; color: var(--muted); }
.pal .pal-foot { padding: 8px 16px; border-top: 1px solid var(--line); }
@media (max-width: 640px) { .pal-back { padding-top: 16px; } .pal { max-height: calc(100vh - 32px); } .pal .pal-foot { display: none; } }
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

/** 맞춰 보기 좋게 소문자로 바꾸고 띄어쓰기 · 가운뎃점 · 괄호를 뺀다. */
function palNorm(t) {
  return String(t || '').toLowerCase().replace(/[\s·・()]/g, '');
}

/** 한글 음절을 초성으로 ('인물' → 'ㅇㅁ'). 한글이 아닌 글자는 그대로 둔다. */
function palChosung(t) {
  return [...String(t || '')].map((ch) => {
    const c = ch.charCodeAt(0) - 0xAC00;
    return c >= 0 && c < 11172 ? PAL_CHO[Math.floor(c / 588)] : ch;
  }).join('');
}

/** 설정 칸 목록 { path, label, value }. 목록 칸은 ' / ' 로 잇는다. 이름 없는 인물의 칸은 뺀다 (부를 이름이 없다). */
function palSetupFields(p) {
  const text = (v) => (Array.isArray(v) ? v.join(' / ') : String(v ?? '')).trim();
  const get = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), p);
  const out = PAL_SETUP.map(([path, label]) => ({ path, label, value: text(get(path)) }));
  p.characters.forEach((c, i) => {
    if (!c.name) return;
    PAL_CHAR_FIELDS.forEach(([k, label]) => out.push({ path: `characters.${i}.${k}`, label: `${c.name} · ${label}`, value: text(c[k]) }));
  });
  return out;
}

/** 지금 화면에서 찾을 재료. 팔레트를 열 때 한 번 모은다 (paletteItems 는 이것만 본다). */
function palContext() {
  if (S.route[0] !== 'p' || !P()) return { inProject: false };
  const next = typeof nextStep === 'function' ? nextStep() : null;
  return {
    inProject: true,
    base: base(),
    nav: navItems(),
    next,
    canSave: saveShortcut(true),
    episodes: P().episodes.map((e) => ({ n: e.plot.number, title: e.plot.title || '', status: e.status })),
    characters: P().characters.filter((c) => c.name).map((c) => ({ id: c.id, name: c.name })),
    fields: palSetupFields(P()),
  };
}

/** 찾을 항목 목록 { kind, label, hint, words, href | act, n, focus }. 순서: 동작 → 화면 → 인물 → 설정 칸 → 화.
    설정 칸은 값으로도 찾고(words), focus 는 그 칸의 입력 요소 (setup.js input 의 id 규칙 'f-' + 경로). 검색어가 없을 때는 동작 · 화면만 보인다. */
function paletteItems(ctx) {
  const settings = { kind: 'screen', label: '모델 · API 키 설정', hint: '', words: '설정', href: '#/settings' };
  if (!ctx.inProject) return [{ kind: 'screen', label: '작품 목록', hint: '', words: '', href: '#/' }, settings];
  const out = [];
  if (ctx.next) out.push({ kind: 'act', label: `다음 할 일 · ${ctx.next[0]}`, hint: '', words: ctx.next[0], href: ctx.next[1] });
  if (ctx.canSave) out.push({ kind: 'act', label: '저장', hint: 'Ctrl+S', words: '', act: 'save' });
  const { steps, auto, tools, apart, foot } = ctx.nav;
  steps.forEach(([, href, num, label]) => out.push({ kind: 'screen', label, hint: /\d/.test(num) ? `단계 ${num}` : '', words: '', href }));
  out.push({ kind: 'screen', label: auto[3], hint: '', words: '', href: auto[1] });
  tools.forEach(([, href, , label]) => out.push({ kind: 'screen', label, hint: '작품 도구', words: '', href }));
  apart.forEach(([, href, , label]) => out.push({ kind: 'screen', label, hint: '본편과 분리', words: '', href }));
  foot.forEach(([href, label]) => out.push(href === '#/settings' ? settings : { kind: 'screen', label, hint: '', words: '', href }));
  ctx.characters.forEach((c) => out.push({ kind: 'char', label: c.name, hint: '인물 · 관계도', words: '', href: `${ctx.base}/cast/${encodeURIComponent('c:' + c.id)}` }));
  (ctx.fields || []).forEach((f) => {
    const hint = f.value ? (f.value.length > PAL_HINT ? f.value.slice(0, PAL_HINT) + '…' : f.value) : '비어 있음';
    out.push({ kind: 'field', label: f.label, hint, words: f.value, href: `${ctx.base}/setup`, focus: '#f-' + f.path.replace(/\./g, '-') });
  });
  ctx.episodes.forEach((e) => {
    const hint = [e.title, (typeof STATUS === 'object' && STATUS[e.status]) || ''].filter(Boolean).join(' · ');
    const write = { kind: 'ep', n: e.n, label: `${e.n}화 집필`, hint, words: e.title, href: `${ctx.base}/write/${e.n}` };
    // 본문을 쓰고 반영을 기다리는 화는 상태 승인을 앞에 둔다
    if (e.status === 'written') out.push({ kind: 'ep', n: e.n, label: `${e.n}화 상태 승인`, hint, words: e.title, href: `${ctx.base}/review/${e.n}` });
    out.push(write);
  });
  return out;
}

/** 검색어에 맞는 항목을 맞는 정도 순으로 (같으면 목록 순서). '12화' · '12' 는 그 화, '1' 은 1 · 10~19화처럼 번호가 그 숫자로 시작하는 화.
    글자는 이름이 같음 → 이름으로 시작 → 이름에 들어 있음 → 제목 등 다른 말에 들어 있음 → 초성('ㅇㅁ' → 인물) 순서. */
function paletteMatch(items, q) {
  const raw = String(q || '').trim();
  if (!raw) return items.filter((it) => it.kind === 'act' || it.kind === 'screen').slice(0, PAL_LIMIT);
  const num = raw.match(/^(\d+)\s*화?$/);
  const nq = palNorm(raw);
  const cho = /^[ㄱ-ㅎ]+$/.test(nq);
  const scored = [];
  items.forEach((it, i) => {
    let s = -1;
    if (num && it.kind === 'ep') {
      if (String(it.n) === num[1]) s = 0;
      else if (String(it.n).startsWith(num[1])) s = 1;
    } else if (!num || it.kind !== 'ep') {
      const label = palNorm(it.label);
      if (label === nq) s = 0;
      else if (label.startsWith(nq)) s = 1;
      else if (label.includes(nq)) s = 2;
      else if (nq && palNorm(it.words).includes(nq)) s = 3;
      else if (cho && palChosung(label).includes(nq)) s = 4;
    }
    if (s >= 0) scored.push([s, i, it]);
  });
  return scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, PAL_LIMIT).map((x) => x[2]);
}

const pal = { items: [], shown: [], sel: 0, opener: null, mark: null };
const PAL_BEHIND = ['#app', '#jobs', '#savebar'];  // 열린 동안 누를 수 없게 둔다. 알림(#toast)은 계속 읽히게 둔다

function paletteOpen() {
  const open = document.getElementById('palette');
  if (open) { document.getElementById('pal-q').focus(); return; }
  const busy = document.getElementById('busy');
  if (busy && !busy.hidden) return;  // 작업 중 창이 떠 있으면 열지 않는다
  pal.opener = document.activeElement;
  pal.mark = focusMark();
  pal.items = paletteItems(palContext());
  pal.sel = 0;
  const box = document.createElement('div');
  box.id = 'palette';
  box.className = 'pal-back';
  const where = pal.items.some((it) => it.kind === 'field') ? '화면 · 화 번호 · 인물 이름 · 설정 칸' : '화면';
  box.innerHTML = `<div class="pal" role="dialog" aria-modal="true" aria-labelledby="pal-title">
    <h2 id="pal-title" class="sr-only">찾기</h2>
    <input id="pal-q" type="text" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-autocomplete="list" aria-describedby="pal-help" autocomplete="off" spellcheck="false" placeholder="${where} 찾기">
    <ul id="pal-list" role="listbox" aria-label="찾은 항목"></ul>
    <div id="pal-help" class="pal-foot small">↑↓ 고르기 · Enter 이동 · Esc 닫기</div>
    <div id="pal-count" class="sr-only" role="status"></div>
  </div>`;
  document.body.appendChild(box);
  PAL_BEHIND.forEach((sel) => { const el = document.querySelector(sel); if (el) el.inert = true; });
  const input = document.getElementById('pal-q');
  input.addEventListener('input', () => { pal.sel = 0; palDraw(); });
  input.addEventListener('keydown', palKey);
  const list = document.getElementById('pal-list');
  list.addEventListener('mousedown', (e) => e.preventDefault());  // 누르는 동안 포커스를 검색 칸에 둔다
  list.addEventListener('click', (e) => {
    const li = e.target.closest('[data-pal]');
    if (li) palPick(pal.shown[Number(li.dataset.pal)]);
  });
  list.addEventListener('mousemove', (e) => {
    const li = e.target.closest('[data-pal]');
    if (li && Number(li.dataset.pal) !== pal.sel) palSelect(Number(li.dataset.pal), false);
  });
  box.addEventListener('mousedown', (e) => { if (e.target === box) { e.preventDefault(); paletteClose(); } });
  palDraw();
  input.focus();
}

function palDraw() {
  const input = document.getElementById('pal-q');
  const list = document.getElementById('pal-list');
  if (!input || !list) return;
  pal.shown = paletteMatch(pal.items, input.value);
  pal.sel = Math.min(pal.sel, Math.max(0, pal.shown.length - 1));
  list.innerHTML = pal.shown.length
    ? pal.shown.map((it, i) => `<li role="option" id="pal-o-${i}" data-pal="${i}" aria-selected="${i === pal.sel}"><span class="pal-label">${esc(it.label)}</span>${it.hint ? `<span class="pal-hint small">${esc(it.hint)}</span>` : ''}<span class="pal-kind">${PAL_KIND[it.kind]}</span></li>`).join('')
    : '<li class="pal-empty" role="presentation">찾은 항목이 없어요</li>';
  if (pal.shown.length) input.setAttribute('aria-activedescendant', `pal-o-${pal.sel}`);
  else input.removeAttribute('aria-activedescendant');
  document.getElementById('pal-count').textContent = input.value.trim() ? (pal.shown.length ? `${pal.shown.length}개 찾았어요` : '찾은 항목이 없어요') : '';
}

function palSelect(i, scroll = true) {
  const list = document.getElementById('pal-list');
  const prev = list.querySelector('[aria-selected="true"]');
  if (prev) prev.setAttribute('aria-selected', 'false');
  pal.sel = i;
  const li = document.getElementById(`pal-o-${i}`);
  if (!li) return;
  li.setAttribute('aria-selected', 'true');
  document.getElementById('pal-q').setAttribute('aria-activedescendant', li.id);
  if (scroll) li.scrollIntoView({ block: 'nearest' });
}

function palKey(e) {
  const n = pal.shown.length;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (n) palSelect((pal.sel + (e.key === 'ArrowDown' ? 1 : -1) + n) % n);
  } else if (e.key === 'Enter') {
    if (e.isComposing || e.keyCode === 229) return;  // 한글 조합을 끝내는 Enter 는 고르지 않는다
    e.preventDefault();
    palPick(pal.shown[pal.sel]);
  } else if (e.key === 'Escape') {
    if (e.isComposing) return;
    e.preventDefault();
    e.stopPropagation();  // 플롯 서랍 닫기 같은 문서의 Esc 처리를 함께 부르지 않는다
    paletteClose();
  } else if (e.key === 'Tab') {
    e.preventDefault();  // 대화 상자 안에서 포커스를 받는 것은 검색 칸 하나다
  }
}

/** 닫고 연 자리로 포커스를 돌린다. 그 사이 화면을 다시 그려 연 요소가 없어졌으면 같은 표시의 새 요소를 찾는다. */
function paletteClose() {
  const box = document.getElementById('palette');
  if (!box) return;
  box.remove();
  PAL_BEHIND.forEach((sel) => { const el = document.querySelector(sel); if (el) el.inert = false; });
  const back = pal.opener && pal.opener.isConnected ? pal.opener : pal.mark && findMark(pal.mark);
  if (back && back !== document.body) focusEl(back);
  pal.opener = null;
  pal.mark = null;
}

/** 고른 항목으로 간다. 다른 화면으로 옮기면 화면 이동이 제목으로 포커스를 옮긴다 (routeNow). */
function palPick(it) {
  if (!it) return;
  paletteClose();
  if (it.focus) {
    S.focusTarget = S.jumpTo = it.focus;
    if (location.hash !== it.href) location.hash = it.href;
    else { render(); S.jumpTo = null; }  // 이미 설정 도우미: 화면 이동 없이 다시 그려 그 칸으로
  } else if (it.href) {
    if (location.hash !== it.href) location.hash = it.href;
  } else if (it.act === 'save' && !saveShortcut()) {
    toast('저장할 변경이 없어요');
  }
}

Object.assign(actions, {
  openPalette() {
    paletteOpen();
  },
});

// Ctrl+K (macOS 는 ⌘K): 입력칸 안에서도 연다. 브라우저 주소창 검색으로 가지 않게 막는다. 열려 있으면 닫는다
window.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
  if ((e.key || '').toLowerCase() !== 'k' && e.code !== 'KeyK') return;
  e.preventDefault();
  if (document.getElementById('palette')) paletteClose();
  else paletteOpen();
}, true);
