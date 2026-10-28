/* 집필 화면의 문체 표시: 이번 화 '가끔 쓰는 장치' 배지와 본문 밑줄(장치 글자, 금지 표현).
   app.js 의 S, P, actions, render 와 passage.js 의 textNow, editableEp, readSel, showTool 을 그대로 쓴다.
   장치를 쓴 화 세기는 metrics.device_hits / device_used / device_last 와 같은 규칙이라 함께 고친다
   (알아보는 글자 앞뒤 공백과 ~-… 를 떼고, 한 화에 합쳐 DEVICE_HITS 번 이상 나오면 쓴 화). 쉬는 화 판정은 prompts.device_block 과 같다.
   고치는 본문은 투명한 본문 칸 뒤에 같은 모양의 칸을 깔아 밑줄을 그린다. 밑줄을 누르면 그 문장으로 부분 수정 도구가 떠서,
   고친 것이 수정 기록에 남고 '내 수정에서 배우기' 에 쓰인다.
   본문 속 인물 · 장소 이름 밑줄(mentions.js 의 mentionsFor)도 같은 칸에 함께 그린다. 문체 밑줄은 쪼개지 않고, 걸치는 이름 밑줄을 쪼갠다. */
'use strict';

Object.assign(S, {
  markIdx: {},  // 밑줄 묶음('d0', 'b') → '보기' 로 마지막에 간 곳
});

let marksOn = true;  // 본문 밑줄 켜기 (브라우저에 기억)
try { marksOn = localStorage.getItem('canon.marks') !== '0'; } catch { /* 저장 못 해도 켜 둔다 */ }

const DEVICE_HITS = 2;
const cueText = (c) => String(c || '').trim().replace(/^[~\-…]+|[~\-…]+$/g, '').trim();

function countIn(text, m) {
  let k = 0;
  if (m) for (let i = text.indexOf(m); i !== -1; i = text.indexOf(m, i + m.length)) k++;
  return k;
}

const deviceHits = (text, cues) => cues.reduce((s, c) => s + countIn(text || '', cueText(c)), 0);
const deviceUsed = (text, cues) => !!text && deviceHits(text, cues) >= DEVICE_HITS;

/** before 화 앞에서 장치를 마지막으로 쓴 화. 저장된 본문으로 센다 (프롬프트와 같은 기준). */
function deviceLast(cues, before) {
  return Math.max(0, ...P().episodes.filter((e) => e.plot.number < before && deviceUsed(e.text, cues)).map((e) => e.plot.number));
}

/** n 화의 장치별 상태. text 는 지금 본문 칸의 글 (저장 전이어도). */
function deviceStates(n, text) {
  return (P().style.devices || []).map((d, i) => ({ d, i })).filter(({ d }) => (d.name || '').trim()).map(({ d, i }) => {
    const cues = (d.cues || []).map(cueText).filter(Boolean);
    const last = cues.length ? deviceLast(d.cues, n) : 0;
    const hits = cues.length ? deviceHits(text, d.cues) : 0;
    return { d, i, cues, last, hits, rest: !!(d.every && last && n - last < d.every), used: !!text && hits >= DEVICE_HITS };
  });
}

const bannedList = () => [...new Set((P().style.banned_phrases || []).map((x) => x.trim()).filter(Boolean))];

/** 본문에서 밑줄 칠 곳. 장치는 쓴 화로 셀 만큼 나왔을 때만, 금지 표현은 나올 때마다. 겹치면 앞의 것만. */
function markRanges(n, text) {
  const out = [];
  const add = (m, kind, key, title) => {
    for (let i = text.indexOf(m); i !== -1; i = text.indexOf(m, i + m.length)) out.push({ a: i, b: i + m.length, kind, key, title });
  };
  deviceStates(n, text).forEach((s) => {
    if (!s.used) return;
    const title = s.rest ? `${s.d.name} · 이번 화는 쉬는 화예요` : `${s.d.name} · 가끔 쓰는 장치`;
    s.cues.forEach((c) => add(c, s.rest ? 'rest' : 'device', `d${s.i}`, title));
  });
  bannedList().forEach((b) => add(b, 'banned', 'b', `금지 표현 '${b}'`));
  out.sort((x, y) => x.a - y.a || y.b - x.b);
  let end = 0;
  return out.filter((r) => (r.a >= end ? ((end = r.b), true) : false));
}

/** 문체 밑줄(ranges)과 이름 밑줄(names, 글 순서 · 겹치지 않음)을 함께 그린다. 문체 밑줄 하나는 늘 mark 하나다 (markNext 가 순서로 찾는다).
    live 면 이름을 누르고 키보드로 고를 수 있게 한다 (읽기 전용 본문). */
function markHtml(text, ranges, names = [], live = false) {
  let j = 0;
  const piece = (a, b) => {  // a~b 글자, 그 안의 이름은 span 으로
    let out = '';
    let at = a;
    while (j < names.length && names[j].b <= a) j++;
    for (let k = j; k < names.length && names[k].a < b; k++) {
      const m = names[k];
      const s = Math.max(m.a, a);
      const t = Math.min(m.b, b);
      const attrs = live ? ` data-mention-at="${m.a}" tabindex="0" role="button" aria-haspopup="dialog"` : '';
      out += `${esc(text.slice(at, s))}<span class="mn ${m.kind}" data-mention="${esc(m.id)}"${attrs}>${esc(text.slice(s, t))}</span>`;
      at = t;
    }
    return out + esc(text.slice(at, b));
  };
  let html = '';
  let at = 0;
  ranges.forEach((r) => {
    html += `${piece(at, r.a)}<mark class="hl ${r.kind}" data-hl="${r.key}" title="${esc(r.title)}">${piece(r.a, r.b)}</mark>`;
    at = r.b;
  });
  return html + piece(at, text.length);
}

/** 밑줄 칠 곳 모두: 문체 밑줄(켰을 때)과 검수 화면의 지적 문장(check.js findingRanges). 겹치면 앞의 것만. */
function allRanges(n, text) {
  const out = [...(marksOn && markable() ? markRanges(n, text) : []), ...(typeof findingRanges === 'function' ? findingRanges(n, text) : [])];
  out.sort((x, y) => x.a - y.a || y.b - x.b);
  let end = 0;
  return out.filter((r) => (r.a >= end ? ((end = r.b), true) : false));
}
const findingMarked = (n, text) => typeof findingRanges === 'function' && findingRanges(n, text).length > 0;

/** 이름 밑줄 (mentions.js). 꺼 두었거나 mentions.js 가 없으면 []. */
const nameRanges = (text, quick = false) => (typeof mentionsFor === 'function' ? mentionsFor(text, quick) : []);
const nameable = () => typeof mentionLive === 'function' && mentionLive();

/** 읽기 전용 본문 (상태 반영이 끝난 화). */
function readHtml(n, text) {
  const names = nameRanges(text);
  const ranges = allRanges(n, text);
  return ranges.length || names.length ? markHtml(text, ranges, names, true) : esc(text);
}

/** 고치는 본문 칸. 밑줄을 켜면 뒤에 같은 모양의 칸을 깐다. */
function draftBox(n, text) {
  // AI가 본문을 처음 쓰는 중이면 끝날 때 칸이 AI 본문으로 바뀐다. 그동안 쓴 글을 잃지 않게 잠근다 (viewWrite 의 locked 와 같은 조건)
  const e = typeof ep === 'function' ? ep(n) : null;
  const locked = typeof jobFor === 'function' && !!jobFor('write', n) && !(e && e.text);
  const ta = `<textarea aria-label="${n}화 본문" data-draft="${n}"${locked ? ' readonly aria-describedby="draft-lock"' : ''} placeholder="여기에 본문을 쓰세요">${esc(text)}</textarea>`;
  return (marksOn && markable()) || nameable() || findingMarked(n, text) ? `<div class="hl-wrap"><div class="hl-layer" aria-hidden="true"><div class="hl-in"></div></div>${ta}</div>` : ta;
}

const markable = () => (P().style.devices || []).some((d) => (d.name || '').trim()) || bannedList().length > 0;

// ----- 이번 화 배지 (집필 화면 왼쪽) -----

/** 집필 화면 왼쪽: 문체 표시와 본문 속 이름 (mentions.js). */
function deviceBadges(n) {
  return styleBadges(n) + (typeof mentionBox === 'function' ? mentionBox(n) : '');
}

function styleBadges(n) {
  if (!markable()) return '';
  const text = textNow(n);
  const editable = editableEp(ep(n));
  const go = (key, k) => (k && text ? ` <button type="button" class="btn small" data-action="markNext" data-arg="${key}">${editable ? '고르기' : '보기'}</button>` : '');
  const rows = deviceStates(n, text).map((s) => {
    const { d } = s;
    let chip;
    let info;
    if (s.rest) {
      chip = s.used ? '<span class="chip dev-warn">쉬는 화인데 씀</span>' : '<span class="chip">이번 화는 쉼</span>';
      info = `${s.last}화에 썼고 ${d.every}화에 한 번까지 · ${s.last + d.every}화부터 다시`;
    } else {
      chip = s.used ? '<span class="chip ai">이번 화에 씀</span>' : '<span class="chip finalized">상황이 오면 한 번</span>';
      info = [(d.when || '').trim(), d.every ? `${d.every}화에 한 번까지` : '', s.cues.length ? (s.last ? `마지막 ${s.last}화` : '아직 안 씀') : ''].filter(Boolean).join(' · ');
    }
    const count = !s.cues.length ? '<div class="small">알아보는 글자가 없어 쓴 화를 세지 못해요</div>'
      : s.hits ? `<div class="small">이번 화에 알아보는 글자 ${s.hits}번${s.used ? '' : ` (${DEVICE_HITS}번부터 쓴 화로 셈)`}${s.used ? go(`d${s.i}`, s.hits) : ''}</div>` : '';
    return `<li class="dev-badge${s.rest ? ' rest' : ''}"><div class="row" style="gap:6px">${chip}<strong>${esc(d.name)}</strong></div>${info ? `<div class="small">${esc(info)}</div>` : ''}${count}</li>`;
  });
  const banned = bannedList();
  if (banned.length) {
    const k = banned.reduce((s, b) => s + countIn(text, b), 0);
    rows.push(`<li class="dev-badge"><div class="row" style="gap:6px">${k ? `<span class="chip dev-ban">금지 표현 ${k}곳</span>` : '<span class="chip">금지 표현 없음</span>'}</div><div class="small">${esc(banned.slice(0, 4).join(', '))}${banned.length > 4 ? ` 외 ${banned.length - 4}개` : ''}${go('b', k)}</div></li>`);
  }
  return `<div class="field" id="style-marks"><div class="between"><span class="small">가끔 쓰는 장치 · 금지 표현</span>
      <button type="button" class="btn small" data-action="marksToggle" aria-pressed="${marksOn}" title="본문 밑줄 켜고 끄기">밑줄 ${marksOn ? '끄기' : '켜기'}</button></div>
    <ul class="dev-list">${rows.join('')}</ul>
    <a href="${base()}/style" style="font-size:0.75rem">문체 화면에서 장치 고치기</a></div>`;
}

// ----- 본문 칸 뒤 밑줄 -----

const LAYER_STYLE = ['boxSizing', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing', 'textIndent',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'tabSize', 'wordBreak', 'overflowWrap', 'whiteSpace'];

let layerObs = null;

// 밑줄 칸이 본문 칸 스크롤을 따라가는 방법. 되는 브라우저는 CSS 스크롤 타임라인(app.css 의 hl-follow)으로 그리기 스레드에서 함께 움직인다.
// scroll 이벤트로 맞추면 본문 칸이 먼저 움직이고 밑줄은 한 프레임 이상 늦게 따라온다. 안 되는 브라우저만 그 방법을 쓴다
const HL_TIMELINE = typeof CSS !== 'undefined' && !!CSS.supports && CSS.supports('animation-timeline', '--hl-ta') && CSS.supports('timeline-scope', '--hl-ta');

/** quick 이면 (글자를 치는 중) 이름은 앞서 찾은 자리를 옮겨 쓴다. 잠시 멈추면 다시 찾는다 (아래 input). */
function paintLayer(quick = false) {
  const ta = document.querySelector('.hl-wrap textarea[data-draft]');
  const layer = ta && ta.parentElement.querySelector('.hl-layer');
  if (!layer) return;
  const cs = getComputedStyle(ta);
  LAYER_STYLE.forEach((k) => { layer.style[k] = cs[k]; });
  layer.style.width = `${ta.clientWidth}px`;
  layer.style.height = `${ta.clientHeight}px`;
  const ranges = allRanges(Number(ta.dataset.draft), ta.value);
  layer.firstElementChild.innerHTML = `${markHtml(ta.value, ranges, nameRanges(ta.value, quick))}\n`;
  // 스크롤 타임라인은 0~1 로 움직이니 끝까지 내렸을 때 옮길 거리를 준다
  layer.style.setProperty('--hl-max', `${Math.max(0, ta.scrollHeight - ta.clientHeight)}px`);
  if (!HL_TIMELINE) layer.scrollTop = ta.scrollTop;
}

/** render() 직후에 부른다. */
function syncMarks() {
  if (layerObs) layerObs.disconnect();
  const ta = document.querySelector('.hl-wrap textarea[data-draft]');
  if (typeof mentionSync === 'function') mentionSync();
  if (!ta) return;
  paintLayer();
  if (window.ResizeObserver) {
    layerObs = new ResizeObserver(() => paintLayer());
    layerObs.observe(ta);
    // 웹 폰트는 처음 보는 글자가 나올 때 늦게 들어와 줄을 다시 바꾼다. 본문 칸 크기는 그대로라 칸만 지켜보면
    // 끝까지 내렸을 때 옮길 거리(--hl-max)가 옛 값으로 남아 밑줄이 아래로 밀린다. 밑줄 글의 높이도 지켜본다
    const inner = ta.parentElement.querySelector('.hl-in');
    if (inner) layerObs.observe(inner);
  }
}

// 글자를 칠 때마다 밑줄 칸은 다음 그리기에 맞추고 (이름은 옮겨 쓴다), 이름 다시 찾기와 왼쪽 배지는 치기를 멈춘 뒤에 한 번
const MARK_IDLE = 150;
let markFrame = 0;
let markIdle = 0;
document.addEventListener('input', (e) => {
  if (!(e.target.matches && e.target.matches('textarea[data-draft]'))) return;
  const n = Number(e.target.dataset.draft);
  cancelAnimationFrame(markFrame);
  markFrame = requestAnimationFrame(() => paintLayer(true));
  clearTimeout(markIdle);
  markIdle = setTimeout(() => {
    paintLayer();
    const box = document.getElementById('style-marks');
    if (box) box.outerHTML = styleBadges(n);
    const names = document.getElementById('name-marks');
    if (names && typeof mentionBox === 'function') names.outerHTML = mentionBox(n);
  }, MARK_IDLE);
});

document.addEventListener('scroll', (e) => {
  if (HL_TIMELINE || !(e.target.matches && e.target.matches('.hl-wrap textarea[data-draft]'))) return;
  const layer = e.target.parentElement.querySelector('.hl-layer');
  if (layer) layer.scrollTop = e.target.scrollTop;
}, true);

/** 밑줄 칠 곳을 품은 문장. 문장이 너무 길면 밑줄 칠 곳만. */
function sentenceAt(text, a, b) {
  const stop = /[.!?…\n]/;
  let s = a;
  while (s > 0 && !stop.test(text[s - 1])) s--;
  let t = b;
  while (t < text.length && !stop.test(text[t])) t++;
  while (t < text.length && /[.!?…"'”’」』)]/.test(text[t])) t++;
  while (s < a && (/\s/.test(text[s]) || (/["”’」』)]/.test(text[s]) && /\s/.test(text[s + 1] || '')))) s++;
  while (t > b && /\s/.test(text[t - 1])) t--;
  return t - s > 400 ? { start: a, end: b } : { start: s, end: t };
}

function markHint(r) {
  return r.kind === 'banned' ? `${r.title} · 이 문장을` : `${r.title.split(' · ')[0]} · 이 문장을`;
}

/** 고치는 본문에서 밑줄 친 곳을 누르면 (고른 것 없이) 그 문장으로 부분 수정 도구를 띄운다. 글자를 치면 도구는 닫힌다. */
document.addEventListener('click', (e) => {
  const ta = e.target;
  if (!(ta.matches && ta.matches('.hl-wrap textarea[data-draft]')) || !editableEp(ep(Number(ta.dataset.draft)))) return;
  setTimeout(() => {  // passage.js 가 고른 것 없는 클릭으로 도구를 닫은 뒤에
    if (ta.selectionStart !== ta.selectionEnd || (S.selTool && S.selTool.mode === 'edit')) return;
    const p = ta.selectionStart;
    const name = typeof mentionAt === 'function' && mentionAt(ta, p);
    if (name) return mentionFromTa(ta, name);  // 이름을 누르면 이름 카드가 먼저다. 그 문장을 고치려면 드래그해 고른다
    const n = Number(ta.dataset.draft);
    const r = allRanges(n, ta.value).find((x) => x.a <= p && p <= x.b);
    if (!r) return;
    if (r.key.startsWith('i:')) return actions.chkOpen(r.key.slice(2));  // 검수 화면: 그 지적을 고르고 문장에서 고치는 창을 띄운다 (check.js)
    const s = sentenceAt(ta.value, r.a, r.b);
    S.selTool = { n, start: s.start, text: ta.value.slice(s.start, s.end), mode: 'menu', hint: markHint(r) };
    showTool();
  }, 0);
});

Object.assign(actions, {
  marksToggle() {
    marksOn = !marksOn;
    try { localStorage.setItem('canon.marks', marksOn ? '1' : '0'); } catch { /* 이번 화면에서만 */ }
    render();
  },
  /** 배지의 '고르기' · '보기': 그 묶음의 다음 곳으로 간다. 고치는 본문이면 그 문장을 골라 부분 수정 도구를 띄운다. */
  markNext(key) {
    const n = Number(S.route[3]) || currentEp();
    const text = textNow(n);
    // 한 문장에 알아보는 글자가 여럿이면 그 문장은 한 번만 고른다. i 는 밑줄(mark) 순서
    const list = [];
    markRanges(n, text).forEach((r, i) => {
      if (r.key !== key) return;
      const s = sentenceAt(text, r.a, r.b);
      if (!list.length || list[list.length - 1].s.start !== s.start) list.push({ r, s, i: list.length ? list[list.length - 1].i + list[list.length - 1].k : 0, k: 1 });
      else list[list.length - 1].k++;
    });
    if (!list.length) return toast('본문에서 찾을 수 없어요', true);
    const k = (S.markIdx[key] ?? -1) + 1;
    S.markIdx[key] = k % list.length;
    const { r, s, i } = list[S.markIdx[key]];
    if (!editableEp(ep(n))) {
      const el = document.querySelectorAll(`.read mark[data-hl="${key}"]`)[i];
      if (!el) return toast('밑줄을 켜면 본문에서 볼 수 있어요', true);
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.remove('flash');
      void el.offsetWidth;
      el.classList.add('flash');
      return;
    }
    S.selFocus = { n, start: s.start, end: s.end };
    render();
    const ta = document.querySelector(`textarea[data-draft="${n}"]`);
    const sel = ta && readSel(ta);
    if (sel) {
      S.selTool = { ...sel, mode: 'menu', hint: `${markHint(r)} · 문장 ${S.markIdx[key] + 1}/${list.length}` };
      showTool();
    }
  },
});
