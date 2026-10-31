/* 이야기 줄기 화면. app.js 의 S, actions, api, render, input, menuBtn 과 outline.js 의 공용 목차 틀을 쓴다.
   메인 줄기에서 갈라졌다 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기를 노선도로 그리고 고친다.
   화가 어느 줄기인지는 화 플롯의 storyline(그 화가 주로 따라가는 줄기, 비면 메인)과 threads(끼어드는 장면)에 적는다.
   화면은 공용 목차 틀이다: 왼쪽 목차(노선도 · 손볼 것 · 메인에서 갈라진 줄기 · 본편 밖 줄기 · AI 제안), 오른쪽은 노선도 쪽(주소 lines) 또는 줄기 하나(lines/<id>).
   노선도 쪽: 노선도(갈라지는 화 차례로 줄을 놓고, 다른 줄을 지나는 선은 흰 틈을 둔다. 칸이 좁으면 세로로 그린다) → 손볼 것 → AI 제안.
   줄기 하나: 이 줄기 앞뒤만 크게 그린 노선도 → 줄기 내용(읽기 카드, '고치기'로 그 카드만) → 붙은 화(줄마다 ⋯, '+ 화 붙이기' 메뉴).
   줄기 고치기와 화 붙이기는 작품 저장(PUT)으로, AI 제안은 백그라운드 작업 'storyline' 과 /storylines/apply 로 한다.
   서버 canon/storylines.py 의 span, episodes_of, tag 와 같은 규칙이라 함께 고친다(tests/test_lines_js.py).
   lineOrder · lineTodo 는 순수 함수. */
'use strict';

const LINE_KINDS = ['서브플롯', '과거 회상', '외전', '인물 이야기'];
const LINE_KIND_HINT = {
  '서브플롯': '메인과 같은 시간에 다른 인물이나 다른 곳에서 진행되는 이야기',
  '과거 회상': '인물의 과거를 보여 주는 화나 장면',
  '외전': '본편 밖의 시간이나 인물을 다루는 이야기',
  '인물 이야기': '조연 한 명을 깊게 다루는 이야기',
};
// 줄기 색: app.css 의 --story-1~8 토큰. 테마마다 값이 바뀌고 두 테마 모두 바탕 위 대비 4.5 이상
const LINE_COLORS = Array.from({ length: 8 }, (_, i) => `var(--story-${i + 1})`);
const DOT_FILL = { draft: 'var(--surface)', confirmed: 'var(--accent-soft)', written: 'var(--amber-soft)', finalized: 'var(--green-soft)' };
const LINE_BIG = 28;  // '크게' 의 한 화 폭(px)

/** 상태를 색만이 아니라 모양으로도 보인다 (적록 색각 이상, 고대비): 반영 완료는 가운데를 채운 점, 본문 있음은 아래 반을 채운 점,
    초안은 점선 테두리, 확정은 빈 점. 범례도 같은 모양을 쓴다 (statusKey) */
function statusMark(cx, cy, r, status) {
  const k = r * 0.5;
  if (status === 'finalized') return `<circle cx="${cx}" cy="${cy}" r="${k}" fill="var(--green)" pointer-events="none"></circle>`;
  if (status === 'written') return `<path d="M ${cx - k} ${cy} A ${k} ${k} 0 0 0 ${cx + k} ${cy} Z" fill="var(--amber)" pointer-events="none"></path>`;
  return '';
}

function statusKey(status, label) {
  return `<span><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.5" fill="${DOT_FILL[status]}" stroke="var(--text-2)" stroke-width="1.2"${status === 'draft' ? ' stroke-dasharray="2 1.5"' : ''}></circle>${statusMark(7, 7, 5.5, status)}</svg>${label}</span>`;
}

Object.assign(S, {
  lineSel: '',                    // 주소의 줄기 id. 비면 노선도 쪽
  lineEdit: '',                   // 내용을 고치는 줄기 id
  lineDraft: null,                // AI 제안 (반영 전)
  lineForm: { note: '', kind: '' }, // AI에게 바라는 것
  lineZoom: 0,                    // 한 화의 가로 폭(px). 0 이면 칸 폭에 맞춘다
  lineRange: 'plot',              // 노선도에 보이는 화: plot(플롯 있는 화까지) | all(총 화수)
  lineTagRole: 'main',            // 화 붙이기 방식: main(이 줄기를 따라감) | thread(장면으로)
});
DRAFT_ROOTS.lineDraft = () => S.lineDraft;
DRAFT_ROOTS.lineForm = () => S.lineForm;

(function lineStyle() {
  const css = `
.ln-col { display: flex; flex-direction: column; gap: var(--gap-stack); min-width: 0; }
.ln-col > .card { scroll-margin-top: calc(var(--band, 0px) + 16px); }
.ln-wrap .outline-item .sw, .ln-key .sw { width: 12px; height: 12px; border-radius: 3px; flex: none; background: var(--lc); }
.ln-map-wrap { overflow-x: auto; }
.ln-map-wrap .line-map { max-width: none; }
.line-map .lm-halo { fill: none; stroke: var(--surface); stroke-width: 11; stroke-linecap: round; }
.line-map .lm-now { stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 4 3; }
.line-map .lm-nowt { font-size: 0.6875rem; font-weight: 700; fill: var(--accent-ink); }
.line-map .lm-sec { font-size: 0.75rem; font-weight: 700; fill: var(--muted); }
.line-map .lm-rule { stroke: var(--rule); stroke-width: 1; }
.line-map .lm-tie { stroke-width: 1.5; stroke-dasharray: 1 4; stroke-linecap: round; fill: none; }
.line-map .lm-dia { fill: var(--surface); stroke-width: 2.5; }
.line-map .lm-warn { fill: var(--amber-soft); stroke: var(--amber); stroke-width: 2; }
.line-map .lm-pick { fill: transparent; stroke: transparent; stroke-width: 24; }
.line-map .lm-lane:hover .lm-hit { fill: var(--accent-soft); }
.ln-key { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 0.75rem; color: var(--text-2); }
.ln-key span { display: inline-flex; align-items: center; gap: 6px; }
.ln-rows { display: flex; flex-direction: column; }
.ln-row { min-height: 52px; padding: 6px 0; border-top: 1px solid var(--rule); display: grid; grid-template-columns: 52px minmax(0, 1fr) auto auto auto; gap: 10px; align-items: center; }
.ln-row:first-child { border-top: none; }
.ln-row .t { font-weight: 700; }
.ln-row .s { font-size: 0.75rem; color: var(--muted); }
.ln-row.warn { margin: 0 -12px; padding: 8px 12px; border-radius: 10px; border-top-color: transparent; background: var(--amber-soft); }
.ln-row.warn .s { color: var(--amber-ink); }
.ln-row.warn + .ln-row { border-top-color: transparent; }
.ln-todo { grid-template-columns: auto minmax(0, 1fr) auto; }
@container outline (max-width: 560px) {
  .ln-row { grid-template-columns: 44px minmax(0, 1fr) auto; }
  .ln-row > .chip, .ln-row > .line-badge { grid-column: 2; justify-self: start; }
  .ln-todo { grid-template-columns: minmax(0, 1fr) auto; }
  .ln-todo > .line-badge { grid-column: 1 / -1; justify-self: start; }
}
.ln-ai { display: grid; grid-template-columns: minmax(0, 1fr) 180px auto; gap: 12px; align-items: end; }
@container outline (max-width: 640px) { .ln-ai { grid-template-columns: 1fr; } }
.ln-pick { display: flex; flex-direction: column; gap: 2px; max-height: 320px; overflow-y: auto; }
.ln-pick .pop-check .small { display: block; }
.ln-focus { display: flex; flex-wrap: wrap; gap: 4px 14px; }
.ln-focus label { min-height: 36px; display: inline-flex; align-items: center; gap: 6px; font-size: 0.8125rem; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

function lineOf(id) {
  return (P().storylines || []).find((s) => s.id === id);
}

function lineIndex(id) {
  return (P().storylines || []).findIndex((s) => s.id === id);
}

function lineColor(id) {
  const i = lineIndex(id);
  return LINE_COLORS[(i < 0 ? 0 : i) % LINE_COLORS.length];
}

function newLineId() {
  const have = new Set((P().storylines || []).map((x) => x.id));
  let n = (P().storylines || []).length + 1;
  while (have.has(`sl-${String(n).padStart(2, '0')}`)) n++;
  return `sl-${String(n).padStart(2, '0')}`;
}

/** [{ n, role }] role 'main' 은 그 화가 줄기를 따라가고, 'thread' 는 장면만 끼어든다 */
function lineEpisodes(id) {
  return P().episodes.slice().sort((a, b) => a.plot.number - b.plot.number)
    .filter((e) => e.plot.storyline === id || (e.plot.threads || []).includes(id))
    .map((e) => ({ n: e.plot.number, role: e.plot.storyline === id ? 'main' : 'thread' }));
}

function lineSpan(s) {
  const eps = lineEpisodes(s.id).map((x) => x.n);
  const lo = [s.branch_ep, ...eps].filter(Boolean);
  const hi = [s.join_ep, ...eps].filter(Boolean);
  return lo.length ? [Math.min(...lo), Math.max(...hi)] : [0, 0];
}

function linePast(s) {
  return !!(s.when || '').trim() || s.kind === '과거 회상';
}

/** 본편 밖 줄기: 갈라지는 화도 합류하는 화도 없는 외전. 노선도 아래 따로 묶는다 */
const lineOutside = (s) => s.kind === '외전' && !s.branch_ep && !s.join_ep;

/** 노선도 줄 차례: 메인에서 갈라지는 줄기는 범위 시작 차례(범위가 없으면 뒤), 본편 밖 줄기는 그 아래. { inside: [id], outside: [id] } */
function lineOrder(p) {
  const lines = p.storylines || [];
  const start = (s) => {
    const eps = p.episodes.filter((e) => e.plot.storyline === s.id || (e.plot.threads || []).includes(s.id)).map((e) => e.plot.number);
    const lo = [s.branch_ep, ...eps].filter(Boolean);
    return lo.length ? Math.min(...lo) : Infinity;
  };
  const inside = lines.filter((s) => !lineOutside(s)).map((s, i) => ({ id: s.id, k: start(s), i })).sort((a, b) => a.k - b.k || a.i - b.i).map((x) => x.id);
  return { inside, outside: lines.filter(lineOutside).map((s) => s.id) };
}

/** 손볼 것: [{ id, kind, text }]. order 갈라짐이 합류보다 뒤, late 총 화수보다 뒤, outside 범위 밖에 붙은 화, open 합류 화 없이 열림(외전은 빼고).
    저장은 막지 않고 고칠 곳을 알린다 */
function lineTodo(p) {
  const total = Math.max(p.meta.target_episodes || 0, 1);
  const out = [];
  (p.storylines || []).forEach((s) => {
    const eps = p.episodes.filter((e) => e.plot.storyline === s.id || (e.plot.threads || []).includes(s.id)).map((e) => e.plot.number).sort((a, b) => a - b);
    if (s.branch_ep && s.join_ep && s.branch_ep > s.join_ep) out.push({ id: s.id, kind: 'order', text: `갈라지는 화(${s.branch_ep}화)가 합류하는 화(${s.join_ep}화)보다 뒤예요.` });
    const late = [['갈라지는 화', s.branch_ep], ['합류하는 화', s.join_ep]].filter(([, v]) => v > total).map(([k]) => k);
    if (late.length) out.push({ id: s.id, kind: 'late', text: `${late.join(' · ')}가 총 화수(${total}화)보다 뒤예요.` });
    const outside = eps.filter((n) => (s.branch_ep && n < s.branch_ep) || (s.join_ep && n > s.join_ep));
    if (outside.length) out.push({ id: s.id, kind: 'outside', eps: outside, text: `${s.join_ep && outside.some((n) => n > s.join_ep) ? `합류하는 화(${s.join_ep}화) 뒤` : `갈라지는 화(${s.branch_ep}화) 앞`}에 붙은 화가 있어요: ${rangeText(outside)}화` });
    if (s.branch_ep && !s.join_ep && s.kind !== '외전') out.push({ id: s.id, kind: 'open', text: `${s.branch_ep}화에 갈라졌는데 합류하는 화가 없어요. 끝까지 열어 둘 줄기면 그대로 둬도 돼요.` });
  });
  return out;
}

/** 화 카드에 붙는 줄기 표시 (plot.js epCard 가 부른다) */
function lineBadge(e) {
  const ids = [e.plot.storyline, ...(e.plot.threads || [])].filter(Boolean);
  return ids.map((id) => {
    const s = lineOf(id);
    if (!s) return '';
    const scene = id !== e.plot.storyline;
    return `<span class="line-badge${scene ? ' scene' : ''}" style="--lc:${lineColor(id)}"><i aria-hidden="true"></i>${scene ? '장면 · ' : ''}${esc(s.title || s.kind)}</span>`;
  }).join('');
}

/** 줄기의 범위 꼬리: '6~19화', 합류 화 없이 열리면 '30화~', 본편 밖은 '외전', 붙은 화가 없으면 '붙은 화 없음' */
function lineTail(s) {
  const [lo, hi] = lineSpan(s);
  if (s.branch_ep && !s.join_ep) return `${s.branch_ep}화~`;
  if (lo) return lo === hi ? `${lo}화` : `${lo}~${hi}화`;
  return lineOutside(s) ? '외전' : '붙은 화 없음';
}

const lineHref = (id) => `${base()}/lines${id ? `/${enc(id)}` : ''}`;

/** 라우터가 부른다: lines 는 노선도 쪽, lines/<id> 는 그 줄기 쪽 */
function lineLoad(sel) {
  const prev = S.lineSel;
  S.lineSel = sel || '';
  if (prev !== S.lineSel && !S.focusTarget) S.focusTarget = '#app main h1';
  if (S.lineEdit && S.lineEdit !== S.lineSel) S.lineEdit = '';
}

// ----- 노선도 -----

const lineLast = () => Math.max(0, ...P().episodes.map((e) => e.plot.number));
const lineDone = () => Math.max(0, ...P().episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));

/** 위쪽 띠: 장편은 아크, 단편은 기승전결. [시작, 끝, 이름, 클래스] */
function lineBands() {
  const p = P();
  return serial() ? (p.story_arcs || []).map((a) => [a.start_ep, a.end_ep, `아크 ${a.number} ${a.title}`, 'act-' + (((a.number - 1) % 4) + 1)])
    : (p.arc || []).map((a) => [a.start_ep, a.end_ep, a.name, actClass(a.name)]);
}

function lineMap() {
  const p = P();
  const total = Math.max(p.meta.target_episodes, lineLast(), 1);
  const spans = (p.storylines || []).map(lineSpan);
  const shown = S.lineRange === 'all' ? total : Math.max(lineLast(), ...spans.map((x) => x[1]), 1);
  // '맞춤'은 지금 노선도 칸 폭에 맞춘다 (전에 그린 칸이나 본문 폭을 잰다). 칸이 좁으면 세로로 그린다
  const wrapW = S.lineFitW || (document.querySelector('#app .ln-map-wrap') || document.querySelector('#app .ln-col') || document.querySelector('#app main') || { clientWidth: 900 }).clientWidth;
  if (wrapW < 560 && !S.lineZoom) return lineMapTall(shown, total, wrapW);
  const left = 168;
  const step = S.lineZoom || Math.max(4, (wrapW - left - 56) / shown);
  const X = (n) => left + (n - 0.5) * step;
  const { inside, outside } = lineOrder(p);
  const mainY = 64;
  const gap = 48;
  const ys = {};
  inside.forEach((id, i) => { ys[id] = mainY + gap * (i + 1); });
  const secY = mainY + gap * inside.length + (outside.length ? 34 : 0);
  outside.forEach((id, i) => { ys[id] = secY + 48 + gap * i; });
  const height = Math.max(mainY, ...Object.values(ys)) + 46;
  const width = left + shown * step + 52;
  const r = Math.max(3.5, Math.min(7, step / 3.2));
  const byNo = new Map(p.episodes.map((e) => [e.plot.number, e]));
  const lastPlot = Math.min(lineLast(), shown);
  const done = Math.min(lineDone(), shown);
  const out = [];
  // 화 점을 누를 자리: 세로 24px, 가로는 12~24px. 같은 줄의 옆 점과 겹치는 곳은 가운데에서 나눠 가까운 화로 간다
  const hitW = Math.max(12, Math.min(24, step));
  const hit = (n, y, prev, next) => {
    const x0 = Math.max(X(n) - hitW / 2, prev ? (X(prev) + X(n)) / 2 : -Infinity);
    const x1 = Math.min(X(n) + hitW / 2, next ? (X(n) + X(next)) / 2 : Infinity);
    return `<rect class="lm-hit" x="${x0}" y="${y - 12}" width="${x1 - x0}" height="24"></rect>`;
  };
  lineBands().forEach(([a, b, label, cls]) => {
    if (a > shown) return;
    const x = left + (a - 1) * step;
    const w = Math.max(2, (Math.min(b, shown) - a + 1) * step - 2);
    out.push(`<g class="lm-band ${cls}"><rect x="${x + 1}" y="8" width="${w}" height="22" rx="5"></rect>
      <text x="${x + 7}" y="23" clip-path="url(#lm-clip-${a})">${esc(label)}</text>
      <clipPath id="lm-clip-${a}"><rect x="${x + 1}" y="8" width="${Math.max(0, w - 6)}" height="22"></rect></clipPath></g>`);
  });
  const every = step >= 24 ? 1 : step >= 14 ? 5 : 10;
  for (let n = 1; n <= shown; n++) {
    if (n === 1 || n % every === 0) out.push(`<text class="lm-tick" x="${X(n)}" y="${height - 10}" text-anchor="middle">${n}</text>`);
  }
  if (shown < total) out.push(`<text class="lm-tick" x="${left + shown * step + 6}" y="23">${shown + 1}~${total}화</text>`);
  if (done) out.push(`<line class="lm-now" x1="${left + done * step}" y1="36" x2="${left + done * step}" y2="${height - 24}"></line><text class="lm-nowt" x="${left + done * step + 4}" y="46">${done}화까지 반영</text>`);
  out.push(`<text class="lm-label" x="12" y="${mainY + 4}">메인 줄기</text>`);
  if (lastPlot) out.push(`<line class="lm-main" x1="${X(1)}" y1="${mainY}" x2="${X(lastPlot)}" y2="${mainY}"></line>`);
  if (lastPlot < shown) out.push(`<line class="lm-main future" x1="${X(Math.max(1, lastPlot))}" y1="${mainY}" x2="${X(shown)}" y2="${mainY}"></line>`);
  if (outside.length) out.push(`<line class="lm-rule" x1="0" y1="${secY}" x2="${width}" y2="${secY}"></line><text class="lm-sec" x="12" y="${secY + 18}">본편 밖</text>`);
  const rings = [];
  const lane = (s) => {
    const y = ys[s.id];
    const c = lineColor(s.id);
    out.push(`<g class="lm-lane" data-action="lineShow" data-arg="${esc(s.id)}" tabindex="0" role="button" aria-label="${esc(`${s.kind} ${s.title || '이름 없음'} 줄기 쪽 열기`)}">
      <rect x="4" y="${y - 17}" width="${left - 12}" height="34" rx="6" class="lm-hit"></rect>
      <rect x="12" y="${y - 6}" width="12" height="12" rx="3" fill="${c}"></rect>
      <text class="lm-label" x="30" y="${y - 2}" clip-path="url(#lm-lclip)">${esc(s.title || '이름 없음')}</text>
      <text class="lm-sub" x="30" y="${y + 12}" clip-path="url(#lm-lclip)">${esc(`${s.kind}${s.when ? ` · ${s.when}` : ''} · ${lineTail(s)}`)}</text></g>`);
    const dots = lineEpisodes(s.id).filter((x) => x.n <= shown);
    if (lineOutside(s)) {
      dots.forEach(({ n, role }) => {
        const e = byNo.get(n);
        const title = `${n}화 ${e ? e.plot.title : ''} · ${s.title}${role === 'thread' ? ' (장면)' : ''}`;
        if (role === 'thread') out.push(`<line class="lm-tie" x1="${X(n)}" y1="${mainY + 8}" x2="${X(n)}" y2="${y - 9}" stroke="${c}"></line>`);
        out.push(`<g class="lm-dot" data-action="lineEp" data-arg="${n}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title>${hit(n, y)}
          ${role === 'thread' ? `<path class="lm-dia" d="M ${X(n)} ${y - 8} L ${X(n) + 8} ${y} L ${X(n)} ${y + 8} L ${X(n) - 8} ${y} Z" stroke="${c}"></path>` : `<circle cx="${X(n)}" cy="${y}" r="${r + 1}" fill="${DOT_FILL[e ? e.status : 'draft']}" stroke="${c}" stroke-width="3"></circle>`}</g>`);
      });
      if (!dots.length) out.push(`<text class="lm-sub" x="${left + 6}" y="${y + 4}">붙은 화가 없어요</text>`);
      return;
    }
    const [lo, hi] = lineSpan(s);
    if (!lo || lo > shown) {
      out.push(`<text class="lm-sub" x="${left + 6}" y="${y + 4}">${lo ? `${lo}화부터 · 보이는 범위 밖` : '아직 붙은 화가 없어요'}</text>`);
      return;
    }
    const top = Math.min(hi, shown);
    const k = Math.min(step * 0.9, 22);
    const xb = s.branch_ep ? X(s.branch_ep) : X(lo);
    const end = s.join_ep && s.join_ep <= shown ? X(s.join_ep) : null;
    const tailX = s.join_ep ? null : X(top) + Math.max(step * 0.6, 10);
    let d = s.branch_ep ? `M ${xb} ${mainY} C ${xb} ${y} ${xb} ${y} ${xb + k} ${y}` : `M ${xb} ${y}`;
    // 범위 밖에 붙은 화(합류 뒤 장면 등)는 선을 늘리지 않고 노란 점으로만 둔다
    const lineEnd = s.join_ep ? Math.min(s.join_ep, shown) : top;
    d += end ? ` L ${Math.max(end - k, xb)} ${y} C ${end} ${y} ${end} ${y} ${end} ${mainY}` : ` L ${tailX || X(lineEnd)} ${y}`;
    const dash = linePast(s) ? ' stroke-dasharray="7 5"' : '';
    out.push(`<path class="lm-halo" d="${d}"></path><path class="lm-path" d="${d}" stroke="${c}"${dash}></path>`);
    if (!s.join_ep) out.push(`<path d="M ${tailX - 8} ${y - 6} L ${tailX} ${y} L ${tailX - 8} ${y + 6}" fill="none" stroke="${c}" stroke-width="2.5" stroke-linecap="round"></path><text class="lm-sub" x="${tailX + 6}" y="${y + 4}">열림</text>`);
    if (s.branch_ep && s.branch_ep <= shown) rings.push(`<circle class="lm-node" cx="${xb}" cy="${mainY}" r="${r + 1.5}" stroke="${c}"></circle>`);
    if (end) rings.push(`<circle class="lm-node" cx="${end}" cy="${mainY}" r="${r + 1.5}" stroke="${c}"></circle>`);
    dots.forEach(({ n, role }, j) => {
      const e = byNo.get(n);
      const off = (s.branch_ep && n < s.branch_ep) || (s.join_ep && n > s.join_ep);
      const title = `${n}화 ${e ? e.plot.title : ''} · ${s.title}${role === 'thread' ? ' (장면)' : ''} · ${e ? STATUS[e.status] : ''}${off ? ' · 범위 밖' : ''}`;
      const circle = off ? `<circle class="lm-warn" cx="${X(n)}" cy="${y}" r="${Math.max(3.5, r - 1)}"></circle>`
        : `<circle cx="${X(n)}" cy="${y}" r="${role === 'thread' ? r - 1 : r + 1}" fill="${role === 'thread' ? 'var(--surface)' : DOT_FILL[e ? e.status : 'draft']}" stroke="${c}" stroke-width="${role === 'thread' ? 2 : 3}"${role !== 'thread' && (!e || e.status === 'draft') ? ' stroke-dasharray="3 2"' : ''}></circle>${role === 'thread' ? '' : statusMark(X(n), y, r + 1, e ? e.status : 'draft')}`;
      out.push(`<g class="lm-dot" data-action="lineEp" data-arg="${n}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title>${hit(n, y, j && dots[j - 1].n, j + 1 < dots.length && dots[j + 1].n)}${circle}</g>`);
    });
  };
  inside.forEach((id) => lane(lineOf(id)));
  outside.forEach((id) => lane(lineOf(id)));
  // 메인 화 점 (줄기를 따라가는 화는 메인에서 비운다). 갈라짐 · 합류 고리는 점 위에 그린다
  const mainDots = [];
  for (let n = 1; n <= lastPlot; n++) {
    const e = byNo.get(n);
    if (e && !(e.plot.storyline && lineOf(e.plot.storyline))) mainDots.push(n);
  }
  for (let n = 1; n <= lastPlot; n++) {
    const e = byNo.get(n);
    if (!e) continue;
    const side = e.plot.storyline && lineOf(e.plot.storyline);
    const title = `${n}화 ${e.plot.title} · ${side ? `${side.title} 줄기를 따라감` : '메인'} · ${STATUS[e.status]}`;
    if (side) {
      out.push(`<circle class="lm-gap" cx="${X(n)}" cy="${mainY}" r="${Math.max(2, r - 1.5)}"><title>${esc(title)}</title></circle>`);
      continue;
    }
    const i = mainDots.indexOf(n);
    out.push(`<g class="lm-dot" data-action="lineEp" data-arg="${n}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title>${hit(n, mainY, mainDots[i - 1], mainDots[i + 1])}
      <circle cx="${X(n)}" cy="${mainY}" r="${r}" fill="${DOT_FILL[e.status]}" class="lm-main-dot ${e.status}"${e.status === 'draft' ? ' stroke-dasharray="3 2"' : ''}></circle>${statusMark(X(n), mainY, r, e.status)}</g>`);
  }
  out.push(...rings);
  const defs = `<defs><clipPath id="lm-lclip"><rect x="0" y="0" width="${left - 14}" height="${height}"></rect></clipPath></defs>`;
  return `<svg class="line-map" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="이야기 줄기 노선도, 1~${shown}화">${defs}${out.join('')}</svg>`;
}

/** 좁은 칸의 세로 노선도: 위에서 아래로 화가 흐르고, 줄기는 메인 오른쪽 세로줄이다. 점은 작아서 줄기 쪽의 붙은 화 목록에서 연다 */
function lineMapTall(shown, total, wrapW) {
  const p = P();
  const { inside, outside } = lineOrder(p);
  const ids = [...inside, ...outside];
  const top = 20;
  const step = Math.max(8, Math.min(14, 1400 / shown));
  const Y = (n) => top + (n - 0.5) * step;
  const mainX = 44;
  const col = Math.max(28, Math.min(56, (wrapW - mainX - 40) / Math.max(1, ids.length)));
  const xs = {};
  ids.forEach((id, i) => { xs[id] = mainX + col * (i + 1) + (outside.includes(id) ? 10 : 0); });
  const height = Y(shown) + 24;
  const width = Math.max(wrapW, mainX + col * ids.length + 40);
  const byNo = new Map(p.episodes.map((e) => [e.plot.number, e]));
  const lastPlot = Math.min(lineLast(), shown);
  const done = Math.min(lineDone(), shown);
  const out = [];
  lineBands().forEach(([a, b, , cls]) => {
    if (a > shown) return;
    out.push(`<g class="lm-band ${cls}"><rect x="0" y="${top + (a - 1) * step + 1}" width="5" height="${Math.max(2, (Math.min(b, shown) - a + 1) * step - 2)}" rx="2"></rect></g>`);
  });
  const every = step >= 12 ? 5 : 10;
  for (let n = 1; n <= shown; n++) if (n === 1 || n % every === 0) out.push(`<text class="lm-tick" x="12" y="${Y(n) + 3}">${n}</text>`);
  if (done) out.push(`<line class="lm-now" x1="28" y1="${top + done * step}" x2="${width - 4}" y2="${top + done * step}"></line><text class="lm-nowt" x="${width - 4}" y="${top + done * step - 5}" text-anchor="end">${done}화까지 반영</text>`);
  if (lastPlot) out.push(`<line class="lm-main" x1="${mainX}" y1="${Y(1)}" x2="${mainX}" y2="${Y(lastPlot)}"></line>`);
  if (lastPlot < shown) out.push(`<line class="lm-main future" x1="${mainX}" y1="${Y(Math.max(1, lastPlot))}" x2="${mainX}" y2="${Y(shown)}"></line>`);
  const rings = [];
  ids.forEach((id) => {
    const s = lineOf(id);
    const x = xs[id];
    const c = lineColor(id);
    const dots = lineEpisodes(id).filter((d) => d.n <= shown);
    if (lineOutside(s)) {
      dots.forEach(({ n, role }) => {
        if (role === 'thread') out.push(`<line class="lm-tie" x1="${mainX + 6}" y1="${Y(n)}" x2="${x - 8}" y2="${Y(n)}" stroke="${c}"></line><path class="lm-dia" d="M ${x} ${Y(n) - 7} L ${x + 7} ${Y(n)} L ${x} ${Y(n) + 7} L ${x - 7} ${Y(n)} Z" stroke="${c}"></path>`);
        else out.push(`<circle cx="${x}" cy="${Y(n)}" r="5" fill="${DOT_FILL[(byNo.get(n) || {}).status || 'draft']}" stroke="${c}" stroke-width="3"></circle>`);
      });
      return;
    }
    const [lo, hi] = lineSpan(s);
    if (!lo || lo > shown) return;
    const yb = s.branch_ep ? Y(s.branch_ep) : Y(lo);
    const ye = s.join_ep && s.join_ep <= shown ? Y(s.join_ep) : null;
    const tail = Y(Math.min(hi, shown)) + 12;
    let d = s.branch_ep ? `M ${mainX} ${yb} C ${x} ${yb} ${x} ${yb} ${x} ${yb + 10}` : `M ${x} ${yb}`;
    d += ye ? ` L ${x} ${Math.max(ye - 10, yb)} C ${x} ${ye} ${x} ${ye} ${mainX} ${ye}` : ` L ${x} ${tail}`;
    const dash = linePast(s) ? ' stroke-dasharray="7 5"' : '';
    out.push(`<g data-action="lineShow" data-arg="${esc(id)}" tabindex="0" role="button" aria-label="${esc(`${s.title || '이름 없음'} 줄기 쪽 열기`)}"><path class="lm-pick" d="${d}"></path><path class="lm-halo" d="${d}"></path><path class="lm-path" d="${d}" stroke="${c}"${dash}></path></g>`);
    if (!ye) out.push(`<path d="M ${x - 6} ${tail - 8} L ${x} ${tail} L ${x + 6} ${tail - 8}" fill="none" stroke="${c}" stroke-width="2.5" stroke-linecap="round"></path>`);
    if (s.branch_ep) rings.push(`<circle class="lm-node" cx="${mainX}" cy="${yb}" r="6" stroke="${c}"></circle>`);
    if (ye) rings.push(`<circle class="lm-node" cx="${mainX}" cy="${ye}" r="6" stroke="${c}"></circle>`);
    dots.forEach(({ n, role }) => {
      const e = byNo.get(n);
      const off = (s.branch_ep && n < s.branch_ep) || (s.join_ep && n > s.join_ep);
      out.push(off ? `<circle class="lm-warn" cx="${x}" cy="${Y(n)}" r="4"></circle>`
        : `<circle cx="${x}" cy="${Y(n)}" r="${role === 'thread' ? 3.5 : 5.5}" fill="${role === 'thread' ? 'var(--surface)' : DOT_FILL[e ? e.status : 'draft']}" stroke="${c}" stroke-width="${role === 'thread' ? 2 : 3}"></circle>`);
    });
  });
  for (let n = 1; n <= lastPlot; n++) {
    const e = byNo.get(n);
    if (!e) continue;
    const side = e.plot.storyline && lineOf(e.plot.storyline);
    out.push(side ? `<circle class="lm-gap" cx="${mainX}" cy="${Y(n)}" r="2.5"></circle>`
      : `<circle cx="${mainX}" cy="${Y(n)}" r="4" fill="${DOT_FILL[e.status]}" class="lm-main-dot ${e.status}"${e.status === 'draft' ? ' stroke-dasharray="3 2"' : ''}></circle>`);
  }
  out.push(...rings);
  const key = `<div class="ln-key">${ids.map((id) => { const s = lineOf(id); return `<span><i class="sw" style="--lc:${lineColor(id)}"></i>${esc(s.title || '이름 없음')}</span>`; }).join('')}</div>`;
  return `${key}<svg class="line-map" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="세로 노선도, 위에서 아래로 1~${shown}화${total > shown ? ` (전체 ${total}화)` : ''}">${out.join('')}</svg>`;
}

function lineMapCard() {
  const total = Math.max(P().meta.target_episodes, lineLast(), 1);
  const plotEnd = Math.max(lineLast(), 1);
  const range = plotEnd < total ? `<div class="seg" role="group" aria-label="보이는 화">${[['plot', `플롯 있는 화 1~${plotEnd}`], ['all', `${total}화 전체`]].map(([k, l]) => `<button type="button" aria-pressed="${S.lineRange === k}" data-action="lineRange" data-arg="${k}">${l}</button>`).join('')}</div>` : '';
  const zoom = `<div class="seg" role="group" aria-label="노선도 폭">${[[0, '맞춤'], [LINE_BIG, '크게']].map(([z, l]) => `<button type="button" aria-pressed="${S.lineZoom === z}" data-action="lineZoom" data-arg="${z}">${l}</button>`).join('')}</div>`;
  const legend = `<div class="legend">${['finalized', 'written', 'confirmed', 'draft'].map((k) => statusKey(k, STATUS[k])).join('')}<span><i style="border-radius:50%;border:2px solid var(--text-2);background:var(--surface)"></i>작은 점: 장면만 끼어듦</span><span><i style="border-top:2px dashed var(--text-2);height:0;width:16px;border-radius:0"></i>다른 시점(과거 · 외전)</span></div>`;
  return `<section class="card" id="line-map"><div class="pf-head"><h2>노선도</h2><span class="row">${range}${zoom}</span></div>
    <div class="ln-map-wrap">${lineMap()}</div>${legend}
    <p class="small">줄기 이름이나 선을 누르면 그 줄기 쪽으로, 점을 누르면 그 화 플롯으로 가요. 다른 줄을 지나는 선은 흰 틈을 두고 지나가요.</p></section>`;
}

function lineTodoCard() {
  const todo = lineTodo(P());
  if (!todo.length) return '';
  const rows = todo.map((t) => {
    const s = lineOf(t.id);
    const btn = t.kind === 'outside' ? `<button type="button" class="btn small" data-action="lineEp" data-arg="${t.eps[0]}">${t.eps[0]}화 보기</button>`
      : `<button type="button" class="btn small" data-action="lineEditGo" data-arg="${esc(t.id)}">${t.kind === 'open' ? '합류 화 정하기' : '고치기'}</button>`;
    return `<div class="ln-row ln-todo"><span class="line-badge" style="--lc:${lineColor(t.id)}"><i aria-hidden="true"></i>${esc(s.kind)}</span><div><div class="t">${esc(s.title || '이름 없음')}</div><div class="s">${esc(t.text)}</div></div>${btn}</div>`;
  }).join('');
  return `<section class="card" id="line-todo"><h2>손볼 것</h2><div class="ln-rows">${rows}</div></section>`;
}

// ----- 줄기 하나 -----

/** 이 줄기 앞뒤만 크게 그린 노선도. 한 화가 44칸이라 손가락으로도 누른다(칸 폭에 맞춰 줄어든다) */
function lineZoomMap(s) {
  const [lo0, hi0] = lineSpan(s);
  if (!lo0) return '<p class="small">아직 붙은 화가 없어요. 아래 \'붙은 화\'에서 화를 붙여요.</p>';
  const total = Math.max(P().meta.target_episodes, lineLast(), 1);
  const a = Math.max(1, lo0 - 2);
  const b = Math.min(total, Math.max(hi0, s.join_ep || 0) + 3);
  const W = 44;
  const X = (n) => 20 + (n - a + 0.5) * W;
  const width = (b - a + 1) * W + 40;
  const mainY = 34;
  const y = 90;
  const c = lineColor(s.id);
  const byNo = new Map(P().episodes.map((e) => [e.plot.number, e]));
  const out = [];
  const lastPlot = Math.min(lineLast(), b);
  if (lastPlot >= a) out.push(`<line class="lm-main" x1="${X(a)}" y1="${mainY}" x2="${X(lastPlot)}" y2="${mainY}"></line>`);
  if (lastPlot < b) out.push(`<line class="lm-main future" x1="${X(Math.max(a, lastPlot))}" y1="${mainY}" x2="${X(b)}" y2="${mainY}"></line>`);
  const xb = s.branch_ep ? X(s.branch_ep) : X(lo0);
  const end = s.join_ep ? X(s.join_ep) : null;
  const top = s.join_ep ? s.join_ep : hi0;
  let d = s.branch_ep ? `M ${xb} ${mainY} C ${xb} ${y} ${xb} ${y} ${xb + 18} ${y}` : `M ${xb} ${y}`;
  d += end ? ` L ${end - 18} ${y} C ${end} ${y} ${end} ${y} ${end} ${mainY}` : ` L ${X(top) + 24} ${y}`;
  out.push(`<path class="lm-path" d="${d}" stroke="${c}" style="stroke-width:5"${linePast(s) ? ' stroke-dasharray="9 7"' : ''}></path>`);
  if (!end) out.push(`<path d="M ${X(top) + 16} ${y - 7} L ${X(top) + 24} ${y} L ${X(top) + 16} ${y + 7}" fill="none" stroke="${c}" stroke-width="3" stroke-linecap="round"></path>`);
  const mine = new Map(lineEpisodes(s.id).map((x) => [x.n, x.role]));
  for (let n = a; n <= b; n++) {
    const e = byNo.get(n);
    const role = mine.get(n);
    const side = e && e.plot.storyline && lineOf(e.plot.storyline);
    const label = `${n}화${e ? ` ${e.plot.title}` : ''}${role === 'main' ? ' · 이 줄기를 따라감' : role === 'thread' ? ' · 이 줄기 장면' : side ? ` · ${side.title}` : ''}${e ? ` · ${STATUS[e.status]}` : ' · 플롯 없음'}`;
    const marks = [];
    if (e && !side) marks.push(`<circle cx="${X(n)}" cy="${mainY}" r="7" fill="${DOT_FILL[e.status]}" class="lm-main-dot ${e.status}"></circle>${statusMark(X(n), mainY, 7, e.status)}`);
    else if (e) marks.push(`<circle class="lm-gap" cx="${X(n)}" cy="${mainY}" r="4"></circle>`);
    const off = role && ((s.branch_ep && n < s.branch_ep) || (s.join_ep && n > s.join_ep));
    if (off) marks.push(`<line x1="${X(n)}" y1="${mainY + 9}" x2="${X(n)}" y2="${y - 8}" stroke="var(--amber)" stroke-width="1.5" stroke-dasharray="2 3"></line><circle class="lm-warn" cx="${X(n)}" cy="${y}" r="6"></circle>`);
    else if (role === 'main') marks.push(`<circle cx="${X(n)}" cy="${y}" r="9" fill="${DOT_FILL[e.status]}" stroke="${c}" stroke-width="3.5"></circle>${statusMark(X(n), y, 9, e.status)}`);
    else if (role === 'thread') marks.push(`<circle cx="${X(n)}" cy="${y}" r="5" fill="var(--surface)" stroke="${c}" stroke-width="2.5"></circle>`);
    const tick = `<text class="lm-tick" x="${X(n)}" y="${y + 38}" text-anchor="middle"${n === s.branch_ep || n === s.join_ep ? ' style="font-weight:700"' : ''}>${n}${n === s.branch_ep ? ' 갈라짐' : n === s.join_ep ? ' 합류' : ''}</text>`;
    out.push(e ? `<g class="lm-dot" data-action="lineEp" data-arg="${n}" tabindex="0" role="button" aria-label="${esc(label)}"><title>${esc(label)}</title><rect class="lm-hit" x="${X(n) - W / 2}" y="10" width="${W}" height="${y - 2}"></rect>${marks.join('')}</g>${tick}` : tick);
  }
  if (s.branch_ep && s.branch_ep >= a) out.push(`<circle class="lm-node" cx="${xb}" cy="${mainY}" r="9" stroke="${c}" style="stroke-width:3.5"></circle>`);
  if (end) out.push(`<circle class="lm-node" cx="${end}" cy="${mainY}" r="9" stroke="${c}" style="stroke-width:3.5"></circle>`);
  return `<svg class="line-map" viewBox="0 0 ${width} ${y + 50}" width="100%" style="max-width:${width}px;height:auto" role="group" aria-label="${esc(`${s.title || '이름 없음'} 줄기와 메인, ${a}~${b}화`)}">${out.join('')}</svg>`;
}

function lineInfoCard(s) {
  const open = S.lineEdit === s.id;
  const btn = `<button type="button" class="btn small" data-action="lineEditToggle" data-arg="${esc(s.id)}" aria-expanded="${open}">${open ? '다 고쳤어요' : '고치기'}</button>`;
  const head = `<div class="pf-head"><h2>줄기 내용${open ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2>${btn}</div>`;
  const notes = lineTodo(P()).filter((t) => t.id === s.id && t.kind !== 'outside');
  const warn = notes.length ? `<div class="note warn" role="status">${notes.map((t) => esc(t.text)).join('<br>')}</div>` : '';
  const none = '<span class="muted">비어 있음</span>';
  if (!open) {
    return `<section class="card pf-sec" id="line-info">${head}${warn}<dl class="pf-dl">
      <dt>종류</dt><dd>${esc(s.kind)}<div class="small">${esc(LINE_KIND_HINT[s.kind] || '')}</div></dd>
      <dt>중심 인물</dt><dd>${s.focus.length ? esc(s.focus.map(charName).join(', ')) : none}</dd>
      <dt>풀어 갈 것</dt><dd>${s.goal ? esc(s.goal) : none}</dd>
      <dt>이야기 속 시점</dt><dd>${s.when ? esc(s.when) : '메인과 같은 시간'}<div class="small">${linePast(s) ? '이 줄기 화를 쓸 때 AI에게 그 시점에 몰랐던 것을 알지 않도록 지시하고, 상태 반영 때 인물의 지금 감정과 위치는 바꾸지 않아요.' : '이 줄기 화를 쓸 때 줄기 정보와 앞 화 요약이 함께 들어가요.'}</div></dd>
      <dt>갈라짐 · 합류</dt><dd>${s.branch_ep ? `${s.branch_ep}화에서 갈라짐` : '갈라지는 화 정하지 않음'} · ${s.join_ep ? `${s.join_ep}화 합류` : '아직 열림'}</dd>
      <dt>합류 때 남길 것</dt><dd>${s.rejoin ? esc(s.rejoin) : none}</dd>
      <dt>줄기 요약</dt><dd>${s.summary ? esc(s.summary) : '<span class="muted">비어 있어요. 이 줄기 화들의 요약을 써요.</span>'}</dd></dl></section>`;
  }
  const b = `storylines.${lineIndex(s.id)}`;
  const chars = P().characters.map((c) => `<label><input type="checkbox" data-line-focus="${esc(c.id)}"${s.focus.includes(c.id) ? ' checked' : ''}>${esc(c.name || c.id)}</label>`).join('');
  return `<section class="card pf-sec editing" id="line-info">${head}${warn}
    <div class="grid-2">
      <div class="field"><label for="line-kind">종류 <span class="hint">${esc(LINE_KIND_HINT[s.kind] || '')}</span></label><select id="line-kind" data-line-kind>${LINE_KINDS.map((k) => `<option${k === s.kind ? ' selected' : ''}>${k}</option>`).join('')}</select></div>
      ${input('이름', b + '.title', { placeholder: `예: ${exName(1)}의 빚` })}
    </div>
    <div class="field"><span class="label">중심 인물</span><div class="ln-focus">${chars || '<span class="small">인물이 아직 없어요.</span>'}</div></div>
    <div class="grid-2">
      ${input('이야기 속 시점', b + '.when', { placeholder: '예: 10년 전', hint: '메인과 같은 시간이면 비워 두세요' })}
      ${input('풀어 갈 것', b + '.goal', { placeholder: '이 줄기가 답할 질문' })}
    </div>
    <div class="grid-2">
      ${input('갈라지는 화', b + '.branch_ep', { type: 'number', min: 0, zeroBlank: true, placeholder: '정하지 않음', hint: '메인에서 이 줄기를 부르는 계기가 나오는 화' })}
      ${input('합류하는 화', b + '.join_ep', { type: 'number', min: 0, zeroBlank: true, placeholder: '아직 열림', hint: '메인으로 돌아오는 화' })}
    </div>
    ${input('합류할 때 메인에 남기는 것', b + '.rejoin', { rows: 2, autogrow: true, placeholder: '드러나는 비밀, 바뀐 관계, 얻거나 잃는 것' })}
    ${input('줄기 요약', b + '.summary', { rows: 3, autogrow: true, hint: '비워 두면 이 줄기 화들의 요약을 써요' })}
    <p class="small">고친 내용은 화면 아래 저장 띠로 저장해요.</p></section>`;
}

/** 붙일 후보: 아직 안 붙은 플롯 있는 화. 줄기 범위 안과 가까운 화 먼저 */
function lineCandidates(s) {
  const mine = new Set(lineEpisodes(s.id).map((x) => x.n));
  const [lo, hi] = lineSpan(s);
  const a = s.branch_ep || lo;
  const b = s.join_ep || hi || a;
  const far = (n) => (!a ? 0 : n < a ? a - n : n > b ? n - b : 0);
  return P().episodes.map((e) => e.plot.number).filter((n) => !mine.has(n)).sort((x, y) => far(x) - far(y) || x - y).slice(0, 10);
}

function lineEpsCard(s) {
  const eps = lineEpisodes(s.id);
  const role = S.lineTagRole;
  const pick = menuBtn(`line-tag-${s.id}`, '+ 화 붙이기', () => {
    const cands = lineCandidates(s);
    return `<div class="pop-sec"><div class="pop-legend">붙이는 방식</div>
      <label class="pop-radio"><input type="radio" name="line-tag-role" value="main" data-line-tag-role${role === 'main' ? ' checked' : ''}><span>이 줄기를 따라가는 화<span class="small">그 화가 주로 이 줄기를 따라가요</span></span></label>
      <label class="pop-radio"><input type="radio" name="line-tag-role" value="thread" data-line-tag-role${role === 'thread' ? ' checked' : ''}><span>메인 화에 장면으로<span class="small">메인 화 안에 이 줄기 장면이 끼어들어요</span></span></label></div>
      <div class="pop-sep"></div>
      <div class="pop-legend">${s.branch_ep || lineSpan(s)[0] ? '범위 안과 가까운 화 먼저' : '플롯이 있는 화'}</div>
      <div class="ln-pick">${cands.map((n) => { const e = ep(n); return `<label class="pop-check"><input type="checkbox" data-line-cand="${n}"><span>${n}화 ${esc(e.plot.title)}<span class="small">${esc(STATUS[e.status])}${e.plot.storyline && lineOf(e.plot.storyline) ? ` · ${esc(lineOf(e.plot.storyline).title)}` : ''}</span></span></label>`; }).join('') || '<span class="small">붙일 화가 없어요.</span>'}</div>
      <div class="field"><label for="line-tag-eps">화 번호로</label><input type="text" id="line-tag-eps" placeholder="예: 7, 8"></div>
      <div class="row" style="justify-content:flex-end"><button type="button" class="btn small primary" data-action="lineTag">붙이기</button></div>`;
  }, { cls: 'btn small' });
  const rows = eps.map(({ n, role: r }) => {
    const e = ep(n);
    const off = (s.branch_ep && n < s.branch_ep) || (s.join_ep && n > s.join_ep);
    const more = menuBtn(`line-ep-${s.id}-${n}`, '<span aria-hidden="true">⋯</span>', () => `
      <button type="button" class="pop-item" data-action="lineEp" data-arg="${n}">${n}화 플롯 열기</button>
      <button type="button" class="pop-item" data-action="lineRole" data-arg="${n}|${r === 'main' ? 'thread' : 'main'}">${r === 'main' ? '장면으로 바꾸기' : '이 줄기를 따라가는 화로 바꾸기'}</button>
      <div class="pop-sep"></div>
      <button type="button" class="pop-item danger" data-action="lineUntag" data-arg="${n}">이 줄기에서 빼기<span class="small">플롯과 본문은 그대로예요</span></button>`, { cls: 'btn small icon-btn', aria: `${n}화 더 보기` });
    const why = off ? `<div class="s">${s.join_ep && n > s.join_ep ? `합류하는 화(${s.join_ep}화) 뒤예요. 합류를 늦추거나 이 화를 빼세요.` : `갈라지는 화(${s.branch_ep}화) 앞이에요. 갈라짐을 당기거나 이 화를 빼세요.`}</div>` : '';
    return `<div class="ln-row${off ? ' warn' : ''}"><a href="#" data-action="lineEp" data-arg="${n}"><b>${n}화</b></a><div><div class="t">${esc(e.plot.title)}</div>${why}</div>
      <span class="chip ${e.status}">${esc(STATUS[e.status])}</span><span class="line-badge${r === 'thread' ? ' scene' : ''}" style="--lc:${lineColor(s.id)}"><i aria-hidden="true"></i>${r === 'thread' ? '장면' : '따라감'}</span>${more}</div>`;
  }).join('');
  const main = eps.filter((x) => x.role === 'main').length;
  return `<section class="card" id="line-eps"><div class="pf-head"><h2>붙은 화 ${eps.length}${eps.length ? ` <span class="small pf-state">따라감 ${main} · 장면 ${eps.length - main}</span>` : ''}</h2>${P().episodes.length ? pick : ''}</div>
    ${rows ? `<div class="ln-rows">${rows}</div>` : `<p class="small">${P().episodes.length ? '아직 붙은 화가 없어요.' : '화별 플롯이 생기면 화를 붙일 수 있어요.'}</p>`}
    <p class="small">본문이 있는 화도 줄기 표시는 바꿀 수 있어요. 본문은 그대로예요.</p></section>`;
}

function lineDetail(s) {
  const eps = lineEpisodes(s.id);
  const meta = [s.branch_ep ? `${s.branch_ep}화에서 갈라짐` : '', s.join_ep ? `${s.join_ep}화 합류` : s.branch_ep ? '아직 열림' : '', `붙은 화 ${eps.length}`, s.focus.length ? `중심 인물 ${s.focus.map(charName).join(', ')}` : ''].filter(Boolean).join(' · ');
  const more = menuBtn(`line-more-${s.id}`, '<span aria-hidden="true">⋯</span>', () => `<button type="button" class="pop-item danger" data-action="lineDelete" data-arg="${esc(s.id)}">줄기 지우기<span class="small">붙은 화는 메인으로 돌아가요</span></button>`, { cls: 'btn icon-btn', aria: '줄기 더 보기' });
  const badge = `<span class="line-badge" style="--lc:${lineColor(s.id)}"><i aria-hidden="true"></i>${esc(s.kind)}</span>`;
  const head = header(`이야기 줄기 · ${badge}`, s.title || '이름 없음', esc(meta), more);
  const main = `<div class="ln-col"><section class="card" id="line-zoom"><h2 class="sr-only">이 줄기 노선도</h2>${lineZoomMap(s)}</section>${lineInfoCard(s)}${lineEpsCard(s)}</div>`;
  return `${head}${outlineDoc(lineToc(), main, { wide: true, cls: 'ln-wrap' })}`;
}

// ----- 목차 -----

function lineToc() {
  const p = P();
  const { inside, outside } = lineOrder(p);
  const todo = lineTodo(p);
  const item = (id) => {
    const s = lineOf(id);
    const warn = todo.some((t) => t.id === id && t.kind !== 'open');
    return `<button type="button" class="outline-item" data-action="lineShow" data-arg="${esc(id)}"${S.lineSel === id ? ' aria-current="page"' : ''}><i class="sw" style="--lc:${lineColor(id)}" aria-hidden="true"></i><span class="tl">${esc(s.title || '이름 없음')}</span><span class="st${warn ? ' warn' : ''}">${esc(lineTail(s))}</span></button>`;
  };
  const body = [
    `<button type="button" class="outline-item" data-action="lineShow" data-arg=""${S.lineSel ? '' : ' aria-current="page"'}><span class="tl">노선도</span><span class="st">줄기 ${(p.storylines || []).length}</span></button>`,
    todo.length ? `<button type="button" class="outline-item warn" data-action="lineGo" data-arg="line-todo"><span class="tl">손볼 것</span><span class="st">${todo.length}</span></button>` : '',
    inside.length ? `<span class="outline-h">메인에서 갈라짐</span>${inside.map(item).join('')}` : '',
    outside.length ? `<span class="outline-h">본편 밖</span>${outside.map(item).join('')}` : '',
    '<div class="outline-sep"></div>',
    '<button type="button" class="outline-item" data-action="lineGo" data-arg="line-ai"><span class="tl">AI 제안</span></button>',
  ].join('');
  const cur = lineOf(S.lineSel);
  return outlineNav({ id: 'line-toc', label: '이야기 줄기 목차', now: cur ? esc(cur.title || '이름 없음') : '노선도', body });
}

// ----- AI 제안 -----

function lineSuggestPanel() {
  const job = jobFor('storyline');
  const has = P().episodes.length > 0;
  const btn = job ? '<button class="btn" aria-disabled="true" aria-busy="true">줄기를 찾는 중…</button>'
    : `<button class="btn" data-action="lineSuggest"${has ? '' : ' aria-disabled="true"'}>AI에게 줄기 제안받기</button>`;
  const kinds = `<select id="line-ai-kind" data-line-ai-kind><option value="">AI가 고름</option>${LINE_KINDS.map((k) => `<option${S.lineForm.kind === k ? ' selected' : ''}>${k}</option>`).join('')}</select>`;
  return `<section class="card" id="line-ai"><div class="pf-head"><h2>AI 제안</h2><span class="small">플롯 내용은 바꾸지 않아요</span></div>
    <p class="small">비밀, 열린 복선, 인물의 결핍처럼 작품이 이미 품고 있는 것에서 줄기를 찾아, 갈라지는 화와 합류하는 화, 붙일 화까지 제안해요.${has ? '' : ' 화별 플롯이 생기면 쓸 수 있어요.'}</p>
    <div class="ln-ai">${input('바라는 것', 'note', { root: 'lineForm', placeholder: `예: ${exName(1)}의 과거를 7화쯤에 두 화 정도` })}
      <div class="field"><label for="line-ai-kind">종류</label>${kinds}</div>${btn}</div>
    ${S.lineDraft ? lineDraftCard() : ''}</section>`;
}

function lineDraftCard() {
  const d = S.lineDraft;
  const s = d.storyline;
  const box = (n, kind) => `<label class="row" style="gap:6px;font-size:0.8125rem"><input type="checkbox" data-line-pick="${kind}:${n}"${(d.picks || {})[`${kind}:${n}`] !== false ? ' checked' : ''}>${n}화${ep(n) ? ' ' + esc(ep(n).plot.title) : ''}</label>`;
  return `<div class="proposal card">
    ${d.reply ? `<div class="msg-text">${esc(d.reply)}</div>` : ''}
    <div class="grid-2">
      <div class="field"><label for="line-d-kind">종류</label><select id="line-d-kind" data-line-draft-kind>${LINE_KINDS.map((k) => `<option${k === s.kind ? ' selected' : ''}>${k}</option>`).join('')}</select></div>
      ${input('이름', 'storyline.title', { root: 'lineDraft' })}
    </div>
    <div class="field"><span class="label">중심 인물</span><div class="ln-focus">${P().characters.map((c) => `<label><input type="checkbox" data-line-draft-focus="${esc(c.id)}"${s.focus.includes(c.id) ? ' checked' : ''}>${esc(c.name || c.id)}</label>`).join('') || '<span class="small">인물이 아직 없어요.</span>'}</div></div>
    <div class="grid-2">${input('이야기 속 시점', 'storyline.when', { root: 'lineDraft' })}${input('풀어 갈 것', 'storyline.goal', { root: 'lineDraft' })}</div>
    <div class="grid-2">${input('갈라지는 화', 'storyline.branch_ep', { root: 'lineDraft', type: 'number', min: 0, zeroBlank: true, placeholder: '정하지 않음' })}${input('합류하는 화', 'storyline.join_ep', { root: 'lineDraft', type: 'number', min: 0, zeroBlank: true, placeholder: '아직 열림' })}</div>
    ${input('합류할 때 메인에 남기는 것', 'storyline.rejoin', { root: 'lineDraft', rows: 2 })}
    ${d.episodes.length ? `<div class="field"><span class="label">이 줄기를 따라갈 화</span><div class="row">${d.episodes.map((n) => box(n, 'main')).join('')}</div></div>` : ''}
    ${d.threads.length ? `<div class="field"><span class="label">메인 화에 장면을 끼울 화</span><div class="row">${d.threads.map((n) => box(n, 'thread')).join('')}</div></div>` : ''}
    ${proposalActions(['lineDrop'], ['lineApply'], '이 줄기 더하기')}
  </div>`;
}

// ----- 화면 -----

function viewLines() {
  const lines = P().storylines || [];
  const add = '<button type="button" class="btn primary" data-action="lineNew">+ 줄기 더하기</button>';
  const head = (right) => header('메인 · 서브플롯 · 회상 · 외전', '이야기 줄기', '메인에서 갈라졌다 합류하는 줄기와 본편 밖 줄기예요. 화마다 어느 줄기를 따라가는지 붙여 두면 AI가 그 줄기의 맥락과 시점을 지켜요.', right);
  if (!lines.length) {
    return `${head('')}<div class="outline-wrap ln-wrap"><div class="ln-col"><section class="card csh-empty"><div class="empty">
      <p>아직 갈라진 줄기가 없어요. 메인에서 갈라질 서브플롯이나 회상을 하나 더해 보세요.</p>
      <p class="small">예: ${esc(exName(1))}의 빚(서브플롯), ${esc(exName(0))}의 어린 시절(과거 회상, 10년 전)</p>${add}</div></section>
      ${P().episodes.length || S.lineDraft ? lineSuggestPanel() : '<div class="note plain">AI 제안은 화별 플롯이 생기면 쓸 수 있어요. 노선도는 줄기가 하나 생기면 보여요.</div>'}</div></div>`;
  }
  const sel = S.lineSel && lineOf(S.lineSel);
  if (sel) return lineDetail(sel);
  const lost = S.lineSel ? `<div class="note warn" role="status">'${esc(S.lineSel)}' 줄기를 찾지 못했어요. 지워졌을 수 있어요.</div>` : '';
  const main = `<div class="ln-col">${lost}${lineMapCard()}${lineTodoCard()}${lineSuggestPanel()}</div>`;
  return `${head(add)}${outlineDoc(lineToc(), main, { wide: true, cls: 'ln-wrap' })}`;
}

// ----- 동작 -----

function parseEps(text) {
  return [...new Set(String(text || '').split(/[,\s]+/).map((x) => parseInt(x, 10)).filter((x) => x > 0))].sort((a, b) => a - b);
}

/** n화를 줄기에 붙인다. 서버 storylines.tag 와 같은 규칙 */
function tagEp(n, id, role) {
  const plot = ep(n).plot;
  plot.threads = plot.threads || [];
  if (role === 'main') {
    plot.threads = plot.threads.filter((x) => x !== id);
    plot.storyline = id;
  } else if (id && !plot.threads.includes(id) && plot.storyline !== id) {
    plot.threads.push(id);
  }
}

/** 노선도 쪽 · 줄기 쪽을 바꾼다. 저장하지 않은 고침이 있어도 묻지 않게 해시 이동 대신 주소만 바꾼다(cast.js castSyncUrl 과 같다) */
function lineGoTo(id, focus = '#app main h1') {
  lineLoad(id);
  S.focusTarget = focus;
  render();
  try {
    history.replaceState(history.state, '', lineHref(id));
    lastHash = location.hash;
  } catch (e) { /* 주소를 못 고쳐도 화면은 그대로 */ }
  if (!focus || focus === '#app main h1') window.scrollTo(0, 0);
}

Object.assign(actions, {
  lineShow(id) {
    lineGoTo(id ? String(id) : '');
  },
  lineGo(sec) {
    if (S.lineSel) lineGoTo('', `#${sec}`);
    else actions.jumpTo(sec);
  },
  lineEditGo(id) {
    S.lineEdit = String(id);
    lineGoTo(String(id), '#line-info [data-action="lineEditToggle"]');
  },
  lineEditToggle(id) {
    S.lineEdit = S.lineEdit === id ? '' : String(id);
    S.focusTarget = '#line-info [data-action="lineEditToggle"]';
    render();
  },
  lineRange(k) {
    S.lineRange = k;
    S.lineFitW = 0;
    render();
  },
  lineZoom(z) {
    S.lineZoom = Number(z) || 0;
    S.lineFitW = 0;
    render();
  },
  lineEp(n) {
    return actions.openPlot(n);  // 화 플롯 페이지 (plot.js). 장편이면 라우터가 그 화의 아크를 고른다
  },
  lineNew() {
    const id = newLineId();
    P().storylines.push({ id, kind: '서브플롯', title: '', focus: [], when: '', goal: '', branch_ep: 0, join_ep: 0, rejoin: '', summary: '' });
    S.lineEdit = id;
    markDirty();
    lineGoTo(id, `#f-storylines-${lineIndex(id)}-title`);
  },
  async lineDelete(id) {
    const s = lineOf(id || S.lineSel);
    if (!s || !confirm(`'${s.title || '이름 없음'}' 줄기를 지울까요? 붙은 화는 메인으로 돌아가고, 플롯과 본문은 그대로예요.`)) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/storylines/${enc(s.id)}`);
    });
    if (!lineOf(s.id)) lineGoTo('');
  },
  lineTag() {
    const s = lineOf(S.lineSel);
    if (!s) return;
    const picked = [...document.querySelectorAll('[data-line-cand]:checked')].map((el) => Number(el.dataset.lineCand));
    const eps = [...new Set([...picked, ...parseEps($('#line-tag-eps') && $('#line-tag-eps').value)])].sort((a, b) => a - b);
    if (!eps.length) return toast('붙일 화를 고르거나 번호를 적으세요', true);
    const missing = eps.filter((n) => !ep(n));
    if (missing.length) return toast(`플롯이 없는 화예요: ${missing.join(', ')}화`, true);
    eps.forEach((n) => tagEp(n, s.id, S.lineTagRole));
    markDirty();
    S.focusTarget = '#line-eps h2';
    render();
    toast(`${rangeText(eps)}화를 붙였어요. 화면 아래 저장 띠로 저장해요.`);
  },
  lineRole(arg) {
    const [n, role] = String(arg).split('|');
    tagEp(Number(n), S.lineSel, role);
    markDirty();
    render();
  },
  lineUntag(n) {
    const plot = ep(Number(n)).plot;
    if (plot.storyline === S.lineSel) plot.storyline = '';
    plot.threads = (plot.threads || []).filter((x) => x !== S.lineSel);
    markDirty();
    S.focusTarget = '#line-eps h2';
    render();
  },
  async lineSuggest() {
    if (!P().episodes.length) return toast('화별 플롯이 생기면 줄기를 제안받을 수 있어요', true);
    await saveIfDirty();
    await startJob('storyline', null, { note: S.lineForm.note, line_kind: S.lineForm.kind });
  },
  lineDrop() {
    if (!confirmDrop('AI 이야기 줄기 제안')) return;
    S.lineDraft = null;
    render();
  },
  async lineApply() {
    const d = S.lineDraft;
    if (!d.storyline.title.trim()) return toast('줄기 이름을 적으세요', true);
    const picked = (kind, list) => list.filter((n) => (d.picks || {})[`${kind}:${n}`] !== false);
    const ok = await run('더하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/storylines/apply`, {
        proposal: d, episodes: picked('main', d.episodes), threads: picked('thread', d.threads),
      });
      S.lineDraft = null;
      toast(`줄기를 더했어요. ${stepLabel('arc')}에서 그 화들을 다듬어요.`);
    });
    if (ok) lineGoTo(S.project.storylines[S.project.storylines.length - 1].id);
  },
});

/** 플롯 편집기에 붙는 줄기 선택 (plot.js plotEditor 가 부른다). 줄기가 없으면 아무것도 그리지 않는다 */
function lineField(e) {
  const lines = P().storylines || [];
  if (!lines.length) return '';
  const n = e.plot.number;
  const busy = jobOwns(n) || autoEp() === n;
  // 본문이 있는 화도 줄기 표시는 바꿀 수 있다 (노선도에서 화 붙이기와 같다). 플롯 잠금 안내와 헷갈리지 않게 이유를 적는다
  const written = !busy && (e.status === 'written' || e.status === 'finalized');
  const opts = [['', '메인 줄기'], ...lines.map((s) => [s.id, `${s.kind} · ${s.title || s.id}`])]
    .map(([id, l]) => `<option value="${esc(id)}"${(e.plot.storyline || '') === id ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const scenes = lines.filter((s) => s.id !== e.plot.storyline).map((s) => `<label class="row" style="font-size:0.8125rem;gap:6px"><input type="checkbox" data-line-thread="${n}" value="${esc(s.id)}"${(e.plot.threads || []).includes(s.id) ? ' checked' : ''}${busy ? ' disabled' : ''}>${esc(s.title || s.id)}</label>`).join('');
  return `<div class="field"><label for="line-ep-${n}">이야기 줄기 <span class="hint">${written ? '본문이 있는 화도 줄기 표시는 바꿀 수 있어요. 본문은 그대로예요' : '이 화가 주로 따라가는 줄기'}</span></label>
      <select id="line-ep-${n}" data-line-ep="${n}"${busy ? ' disabled' : ''}>${opts}</select></div>
    ${scenes ? `<div class="field"><span class="label">장면으로 끼어드는 줄기</span><div class="row">${scenes}</div></div>` : ''}`;
}

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset) return;
  if (t.dataset.lineEp) {  // 플롯 편집기: 이 화의 줄기
    const plot = ep(Number(t.dataset.lineEp)).plot;
    plot.storyline = t.value;
    plot.threads = (plot.threads || []).filter((x) => x !== t.value);
    markDirty();
    render();
    return;
  }
  if (t.dataset.lineThread) {
    const plot = ep(Number(t.dataset.lineThread)).plot;
    const id = t.value;
    plot.threads = t.checked ? [...new Set([...(plot.threads || []), id])] : (plot.threads || []).filter((x) => x !== id);
    markDirty();
    return;
  }
  if (t.dataset.lineTagRole !== undefined) { S.lineTagRole = t.value; return; }  // 화 붙이기 메뉴: 다시 그리지 않아 고른 칸이 남는다
  if (t.dataset.lineCand) return;
  if (t.dataset.lineAiKind !== undefined) { S.lineForm.kind = t.value; return; }
  if (t.dataset.linePick) { S.lineDraft.picks = { ...(S.lineDraft.picks || {}), [t.dataset.linePick]: t.checked }; return; }
  if (t.dataset.lineDraftKind !== undefined) { S.lineDraft.storyline.kind = t.value; return; }
  if (t.dataset.lineDraftFocus) {
    const f = S.lineDraft.storyline.focus;
    S.lineDraft.storyline.focus = t.checked ? [...new Set([...f, t.dataset.lineDraftFocus])] : f.filter((x) => x !== t.dataset.lineDraftFocus);
    return;
  }
  if (S.route[2] !== 'lines') return;
  const s = lineOf(S.lineSel);
  if (!s) return;
  if (t.dataset.lineKind !== undefined) s.kind = t.value;
  else if (t.dataset.lineFocus) s.focus = t.checked ? [...new Set([...s.focus, t.dataset.lineFocus])] : s.focus.filter((x) => x !== t.dataset.lineFocus);
  else {
    // 글을 고친 칸은 다시 그리지 않는다 (커서를 잃지 않게). 범위와 시점은 목차 · 경고에 보이도록 다시 그린다
    if (/^storylines\.\d+\.(branch_ep|join_ep|when|title)$/.test(t.dataset.bind || '')) render();
    return;
  }
  markDirty();
  render();
});

// 노선도의 점과 줄기 이름은 키보드로도 연다
document.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('svg.line-map [data-action]') && !e.isComposing) {
    e.preventDefault();
    e.target.closest('[data-action]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }
});

/** 그린 뒤에 부른다: '맞춤'인데 노선도 칸 폭이 짐작과 다르면 칸 폭을 재어 한 번 더 그린다 (처음 그릴 때는 칸이 없어 본문 폭으로 짐작한다). */
function syncLines() {
  const wrap = document.querySelector('#app .ln-map-wrap');
  if (!wrap || S.lineZoom || S.lineFitW === wrap.clientWidth) return;
  const svg = wrap.querySelector('svg');
  const tall = !!wrap.querySelector('.ln-key');
  if (svg && !tall && wrap.clientWidth >= 560 && Math.abs(svg.getBoundingClientRect().width - wrap.clientWidth) <= 60) return;
  S.lineFitW = wrap.clientWidth;
  render();
}
window.addEventListener('resize', () => { S.lineFitW = 0; });
