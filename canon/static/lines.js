/* 이야기 줄기 화면. app.js 의 S, actions, api, render, input 을 그대로 쓴다.
   메인 줄기에서 갈라졌다 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기를 노선도로 그리고 고친다.
   화가 어느 줄기인지는 화 플롯의 storyline(그 화가 주로 따라가는 줄기, 비면 메인)과 threads(끼어드는 장면)에 적는다.
   줄기 고치기와 화 붙이기는 작품 저장(PUT)으로, AI 제안은 백그라운드 작업 'storyline' 과 /storylines/apply 로 한다.
   서버 canon/storylines.py 의 span, episodes_of 와 같은 규칙이라 함께 고친다. */
'use strict';

const LINE_KINDS = ['서브플롯', '과거 회상', '외전', '인물 이야기'];
const LINE_KIND_HINT = {
  '서브플롯': '메인과 같은 시간에 다른 인물이나 다른 곳에서 진행되는 이야기',
  '과거 회상': '인물의 과거를 보여 주는 화나 장면',
  '외전': '본편 밖의 시간이나 인물을 다루는 이야기',
  '인물 이야기': '조연 한 명을 깊게 다루는 이야기',
};
// 줄기 색: 흰 배경에서 대비 4.5 이상인 색만
const LINE_COLORS = ['#B4570A', '#7A3FB0', '#1C6E45', '#B42318', '#0E6F7C', '#6E5A00', '#A3367A', '#3E5C14'];
const DOT_FILL = { draft: 'var(--surface)', confirmed: 'var(--accent-soft)', written: 'var(--amber-soft)', finalized: 'var(--green-soft)' };

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
  lineSel: null,                  // 고른 줄기 id
  lineDraft: null,                // AI 제안 (반영 전)
  lineForm: { note: '', kind: '' }, // AI에게 바라는 것
  lineZoom: 0,                    // 한 화의 가로 폭(px). 0 이면 화수에 맞춰 정한다
});
DRAFT_ROOTS.lineDraft = () => S.lineDraft;
DRAFT_ROOTS.lineForm = () => S.lineForm;

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

/** 화 카드에 붙는 줄기 표시 (app.js epCard 가 부른다) */
function lineBadge(e) {
  const ids = [e.plot.storyline, ...(e.plot.threads || [])].filter(Boolean);
  return ids.map((id) => {
    const s = lineOf(id);
    if (!s) return '';
    const scene = id !== e.plot.storyline;
    return `<span class="line-badge${scene ? ' scene' : ''}" style="--lc:${lineColor(id)}"><i aria-hidden="true"></i>${scene ? '장면 · ' : ''}${esc(s.title || s.kind)}</span>`;
  }).join('');
}

// ----- 노선도 -----

function lineMap() {
  const p = P();
  const lines = p.storylines || [];
  const total = Math.max(p.meta.target_episodes, ...p.episodes.map((e) => e.plot.number), 1);
  const step = S.lineZoom || (total <= 40 ? 30 : total <= 120 ? 16 : 9);
  const left = 168;
  const X = (n) => left + (n - 0.5) * step;
  const bandY = 8;
  const mainY = 64;
  const gap = 58;
  const laneY = (i) => mainY + gap * (i + 1);
  const width = left + total * step + 24;
  const height = laneY(lines.length) - gap + 46;
  const r = Math.max(3.5, Math.min(7, step / 3.2));
  const byNo = new Map(p.episodes.map((e) => [e.plot.number, e]));
  const lastPlot = Math.max(0, ...p.episodes.map((e) => e.plot.number));
  const out = [];

  // 위쪽 띠: 장편은 아크, 단편은 기승전결
  const bands = serial() ? (p.story_arcs || []).map((a) => [a.start_ep, a.end_ep, `아크 ${a.number} ${a.title}`, 'act-' + (((a.number - 1) % 4) + 1)])
    : (p.arc || []).map((a) => [a.start_ep, a.end_ep, a.name, actClass(a.name)]);
  bands.forEach(([a, b, label, cls]) => {
    const x = left + (a - 1) * step;
    const w = Math.max(2, (b - a + 1) * step - 2);
    out.push(`<g class="lm-band ${cls}"><rect x="${x + 1}" y="${bandY}" width="${w}" height="22" rx="5"></rect>
      <text x="${x + 7}" y="${bandY + 15}" clip-path="url(#lm-clip-${a})">${esc(label)}</text>
      <clipPath id="lm-clip-${a}"><rect x="${x + 1}" y="${bandY}" width="${Math.max(0, w - 6)}" height="22"></rect></clipPath></g>`);
  });

  // 화 번호 눈금
  const every = step >= 24 ? 1 : step >= 14 ? 5 : 10;
  for (let n = 1; n <= total; n++) {
    if (n === 1 || n % every === 0) out.push(`<text class="lm-tick" x="${X(n)}" y="${height - 10}" text-anchor="middle">${n}</text>`);
  }

  // 메인 줄기
  out.push(`<text class="lm-label" x="12" y="${mainY + 4}"><tspan font-weight="700">메인 줄기</tspan></text>`);
  if (lastPlot) out.push(`<line class="lm-main" x1="${X(1)}" y1="${mainY}" x2="${X(Math.min(lastPlot, total))}" y2="${mainY}"></line>`);
  if (lastPlot < total) out.push(`<line class="lm-main future" x1="${X(Math.max(1, lastPlot))}" y1="${mainY}" x2="${X(total)}" y2="${mainY}"></line>`);

  // 갈라지는 줄기
  lines.forEach((s, i) => {
    const y = laneY(i);
    const c = lineColor(s.id);
    const sel = s.id === S.lineSel;
    const [lo, hi] = lineSpan(s);
    const dash = linePast(s) ? ' stroke-dasharray="7 5"' : '';
    const label = `${s.title || '이름 없음'}`;
    out.push(`<g class="lm-lane${sel ? ' sel' : ''}" data-action="lineSelect" data-arg="${esc(s.id)}" tabindex="0" role="button" aria-label="${esc(`${s.kind} ${label} 고치기`)}">
      <rect x="4" y="${y - 17}" width="${left - 12}" height="34" rx="6" class="lm-hit"></rect>
      <rect x="12" y="${y - 6}" width="12" height="12" rx="3" fill="${c}"></rect>
      <text class="lm-label" x="30" y="${y - 2}" clip-path="url(#lm-lclip)">${esc(label)}</text>
      <text class="lm-sub" x="30" y="${y + 12}">${esc(s.kind)}${s.when ? ' · ' + esc(s.when) : ''}</text></g>`);
    if (!lo) {
      out.push(`<text class="lm-sub" x="${left + 6}" y="${y + 4}">아직 붙은 화가 없어요. 아래에서 화를 붙이세요.</text>`);
      return;
    }
    const xs = X(lo);
    const xe = X(hi);
    const k = Math.min(step * 0.9, 22);
    let d;
    if (s.branch_ep) {
      const xb = X(s.branch_ep);
      d = `M ${xb} ${mainY} C ${xb} ${y} ${xb} ${y} ${xb + k} ${y}`;
    } else d = `M ${xs} ${y}`;
    if (s.join_ep) {
      const xj = X(s.join_ep);
      d += ` L ${Math.max(xj - k, xs)} ${y} C ${xj} ${y} ${xj} ${y} ${xj} ${mainY}`;
    } else d += ` L ${xe + step * 0.6} ${y}`;
    out.push(`<path class="lm-path${sel ? ' sel' : ''}" d="${d}" stroke="${c}"${dash}></path>`);
    if (!s.join_ep) out.push(`<text class="lm-sub" x="${xe + step * 0.6 + 6}" y="${y + 4}">열림</text>`);
    if (s.branch_ep) out.push(`<circle class="lm-node" cx="${X(s.branch_ep)}" cy="${mainY}" r="${r + 1.5}" stroke="${c}"></circle>`);
    if (s.join_ep) out.push(`<circle class="lm-node" cx="${X(s.join_ep)}" cy="${mainY}" r="${r + 1.5}" stroke="${c}"></circle>`);
    lineEpisodes(s.id).forEach(({ n, role }) => {
      const e = byNo.get(n);
      const title = `${n}화 ${e ? e.plot.title : ''} · ${s.title}${role === 'thread' ? ' (장면)' : ''} · ${e ? STATUS[e.status] : ''}`;
      out.push(`<g class="lm-dot" data-action="lineEp" data-arg="${n}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title>
        <circle cx="${X(n)}" cy="${y}" r="${role === 'thread' ? r - 1 : r + 1}" fill="${role === 'thread' ? 'var(--surface)' : DOT_FILL[e ? e.status : 'draft']}" stroke="${c}" stroke-width="${role === 'thread' ? 2 : 3}"${role !== 'thread' && (!e || e.status === 'draft') ? ' stroke-dasharray="3 2"' : ''}></circle>${role === 'thread' ? '' : statusMark(X(n), y, r + 1, e ? e.status : 'draft')}</g>`);
    });
  });

  // 메인 화 점 (줄기를 따라가는 화는 메인에서 비운다)
  for (let n = 1; n <= Math.min(lastPlot, total); n++) {
    const e = byNo.get(n);
    if (!e) continue;
    const side = e.plot.storyline && lineOf(e.plot.storyline);
    const title = `${n}화 ${e.plot.title} · ${side ? `${side.title} 줄기를 따라감` : '메인'} · ${STATUS[e.status]}`;
    if (side) {
      out.push(`<circle class="lm-gap" cx="${X(n)}" cy="${mainY}" r="${r - 1.5}"><title>${esc(title)}</title></circle>`);
      continue;
    }
    out.push(`<g class="lm-dot" data-action="lineEp" data-arg="${n}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title>
      <circle cx="${X(n)}" cy="${mainY}" r="${r}" fill="${DOT_FILL[e.status]}" class="lm-main-dot ${e.status}"${e.status === 'draft' ? ' stroke-dasharray="3 2"' : ''}></circle>${statusMark(X(n), mainY, r, e.status)}</g>`);
  }

  const defs = `<defs><clipPath id="lm-lclip"><rect x="0" y="0" width="${left - 14}" height="${height}"></rect></clipPath></defs>`;
  const svg = `<svg class="line-map" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="이야기 줄기 노선도">${defs}${out.join('')}</svg>`;
  const zoom = `<div class="seg" role="group" aria-label="노선도 폭">${[[0, '맞춤'], [9, '좁게'], [16, '보통'], [30, '넓게']].map(([z, l]) => `<button type="button" aria-pressed="${S.lineZoom === z}" data-action="lineZoom" data-arg="${z}">${l}</button>`).join('')}</div>`;
  const legend = `<div class="legend">${statusKey('draft', '플롯 초안')}${statusKey('confirmed', '플롯 확정')}${statusKey('written', '본문 있음')}${statusKey('finalized', '반영 완료')}<span><i style="border-radius:50%;border:2px solid var(--text-2);background:var(--surface)"></i>작은 점: 메인 화에 끼어드는 장면</span><span><i style="border-top:2px dashed var(--text-2);height:0;width:16px;border-radius:0"></i>다른 시점(과거 · 외전)</span></div>`;
  return `<div class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="between"><h2>노선도</h2>${zoom}</div>
    <div class="line-map-wrap">${svg}</div>${legend}
    <div class="small">점을 누르면 그 화 플롯을 열고, 왼쪽 줄기 이름을 누르면 줄기를 고쳐요. 메인에서 갈라지는 화와 합류하는 화는 메인 줄 위의 테두리 원이에요.</div>
  </div>`;
}

// ----- 줄기 편집 -----

function lineList() {
  const items = (P().storylines || []).map((s) => {
    const [lo, hi] = lineSpan(s);
    const n = lineEpisodes(s.id).length;
    return `<button type="button" class="el-item${s.id === S.lineSel ? ' sel' : ''}" data-action="lineSelect" data-arg="${esc(s.id)}">
      <span class="between"><span class="line-badge" style="--lc:${lineColor(s.id)}"><i aria-hidden="true"></i>${esc(s.kind)}</span><span class="small">${lo ? `${lo}~${hi}화` : '화 없음'}</span></span>
      <strong>${esc(s.title) || '이름 없음'}</strong>
      <span class="small">${s.focus.map(charName).map(esc).join(', ') || '중심 인물 없음'}${s.when ? ' · ' + esc(s.when) : ''} · ${n}화</span></button>`;
  }).join('');
  return `<div class="el-list">${items}</div>`;
}

function lineEditor(s) {
  const i = lineIndex(s.id);
  const b = `storylines.${i}`;
  const chars = P().characters.map((c) => `<label class="row" style="font-size:0.8125rem;gap:6px"><input type="checkbox" data-line-focus="${esc(c.id)}"${s.focus.includes(c.id) ? ' checked' : ''}>${esc(c.name || c.id)}</label>`).join('');
  const eps = lineEpisodes(s.id);
  const chips = eps.map(({ n, role }) => `<span class="line-ep"><button type="button" class="btn small" data-action="lineEp" data-arg="${n}">${n}화${role === 'thread' ? ' 장면' : ''}</button><button type="button" class="btn small icon-btn" data-action="lineUntag" data-arg="${n}" aria-label="${n}화를 이 줄기에서 빼기">✕</button></span>`).join('');
  return `<div class="card" style="display:flex;flex-direction:column;gap:14px">
    <div class="between"><h2>줄기</h2><button class="btn small danger" data-action="lineDelete">삭제</button></div>
    <div class="grid-2">
      <div class="field"><label for="line-kind">종류 <span class="hint">${esc(LINE_KIND_HINT[s.kind] || '')}</span></label><select id="line-kind" data-line-kind>${LINE_KINDS.map((k) => `<option${k === s.kind ? ' selected' : ''}>${k}</option>`).join('')}</select></div>
      ${input('이름', b + '.title', { placeholder: `예: ${exName(1)}이(가) 진 빚` })}
    </div>
    <div class="field"><span class="label">중심 인물</span><div class="row">${chars || '<span class="small">인물이 아직 없어요.</span>'}</div></div>
    <div class="grid-2">
      ${input('이야기 속 시점', b + '.when', { placeholder: '예: 10년 전', hint: '메인과 같은 시간이면 비워 두세요' })}
      ${input('풀어 갈 것', b + '.goal', { placeholder: '이 줄기가 답할 질문' })}
    </div>
    <div class="grid-2">
      ${input('갈라지는 화', b + '.branch_ep', { type: 'number', min: 0, hint: '메인에서 이 줄기를 부르는 계기가 나오는 화. 0 이면 정하지 않음' })}
      ${input('합류하는 화', b + '.join_ep', { type: 'number', min: 0, hint: '메인으로 돌아오는 화. 0 이면 아직 열림' })}
    </div>
    ${input('합류할 때 메인에 남기는 것', b + '.rejoin', { rows: 2, autogrow: true, placeholder: '드러나는 비밀, 바뀐 관계, 얻거나 잃는 것' })}
    ${input('줄기 요약', b + '.summary', { rows: 3, autogrow: true, hint: '비워 두면 이 줄기 화들의 요약을 써요' })}
    <div class="field"><span class="label">붙은 화</span><div class="row">${chips || '<span class="small">아직 없어요.</span>'}</div></div>
    <div class="row">
      <label class="row" style="gap:6px">화 <input type="text" id="line-tag-eps" style="width:120px" placeholder="예: 7, 8"></label>
      <button type="button" class="btn small" data-action="lineTag" data-arg="main">이 줄기를 따라가는 화로</button>
      <button type="button" class="btn small" data-action="lineTag" data-arg="thread">메인 화에 장면으로</button>
    </div>
    <div class="small">${linePast(s) ? '다른 시점의 줄기예요. 이 줄기 화를 쓸 때 AI에게 그 시점에 몰랐던 것을 알지 않도록 지시하고, 상태 반영 때 인물의 지금 감정과 위치는 바꾸지 않아요.' : '메인과 같은 시간의 줄기예요. 이 줄기 화를 쓸 때 줄기 정보와 앞 화 요약이 함께 들어가요.'}</div>
  </div>`;
}

// ----- AI 제안 -----

function lineSuggestPanel() {
  const job = jobFor('storyline');
  const btn = job ? `<button class="btn" disabled aria-busy="true">${esc(job.label)} 중…</button>`
    : '<button class="btn primary" data-action="lineSuggest">AI에게 줄기 제안받기</button>';
  const kinds = `<select id="line-ai-kind" data-line-ai-kind><option value="">AI가 고름</option>${LINE_KINDS.map((k) => `<option${S.lineForm.kind === k ? ' selected' : ''}>${k}</option>`).join('')}</select>`;
  return `<div class="card" style="display:flex;flex-direction:column;gap:12px">
    <h2>AI 제안</h2>
    <div class="small">비밀, 열린 복선, 인물의 결핍처럼 작품이 이미 품고 있는 것에서 줄기를 찾아, 갈라지는 화와 합류하는 화, 붙일 화까지 제안해요. 플롯 내용은 바꾸지 않아요.</div>
    ${input('바라는 것', 'note', { root: 'lineForm', rows: 2, placeholder: `예: ${exName(1)}의 과거를 7화쯤에 두 화 정도` })}
    <div class="row"><label class="row" style="gap:6px" for="line-ai-kind">종류 ${kinds}</label>${btn}</div>
    ${S.lineDraft ? lineDraftCard() : ''}
  </div>`;
}

function lineDraftCard() {
  const d = S.lineDraft;
  const s = d.storyline;
  const box = (n, kind) => `<label class="row" style="gap:6px;font-size:0.8125rem"><input type="checkbox" data-line-pick="${kind}:${n}"${(d.picks || {})[`${kind}:${n}`] !== false ? ' checked' : ''}>${n}화${ep(n) ? ' ' + esc(ep(n).plot.title) : ''}</label>`;
  return `<div class="proposal card" style="display:flex;flex-direction:column;gap:10px">
    ${d.reply ? `<div class="msg-text">${esc(d.reply)}</div>` : ''}
    <div class="grid-2">
      <div class="field"><label for="line-d-kind">종류</label><select id="line-d-kind" data-line-draft-kind>${LINE_KINDS.map((k) => `<option${k === s.kind ? ' selected' : ''}>${k}</option>`).join('')}</select></div>
      ${input('이름', 'storyline.title', { root: 'lineDraft' })}
    </div>
    <div class="small">중심 인물: ${s.focus.map(charName).map(esc).join(', ') || '없음'}</div>
    <div class="grid-2">${input('이야기 속 시점', 'storyline.when', { root: 'lineDraft' })}${input('풀어 갈 것', 'storyline.goal', { root: 'lineDraft' })}</div>
    <div class="grid-2">${input('갈라지는 화', 'storyline.branch_ep', { root: 'lineDraft', type: 'number', min: 0 })}${input('합류하는 화', 'storyline.join_ep', { root: 'lineDraft', type: 'number', min: 0 })}</div>
    ${input('합류할 때 메인에 남기는 것', 'storyline.rejoin', { root: 'lineDraft', rows: 2 })}
    ${d.episodes.length ? `<div class="field"><span class="label">이 줄기를 따라갈 화</span><div class="row">${d.episodes.map((n) => box(n, 'main')).join('')}</div></div>` : ''}
    ${d.threads.length ? `<div class="field"><span class="label">메인 화에 장면을 끼울 화</span><div class="row">${d.threads.map((n) => box(n, 'thread')).join('')}</div></div>` : ''}
    ${proposalActions(['lineDrop'], ['lineApply'], '이 줄기 더하기')}
  </div>`;
}

// ----- 화면 -----

function viewLines() {
  const lines = P().storylines || [];
  if (S.lineSel && !lineOf(S.lineSel)) S.lineSel = null;
  if (!S.lineSel && lines.length) S.lineSel = lines[0].id;
  const s = lineOf(S.lineSel);
  const add = '<button class="btn" data-action="lineNew">+ 줄기 추가</button>';
  const desc = '메인 줄기에서 갈라졌다 다시 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기를 한눈에 봐요. 화마다 어느 줄기를 따라가는지, 메인 화 안에 어느 줄기 장면이 끼어드는지 표시하면 본문을 쓸 때 AI가 그 줄기의 맥락과 시점을 지켜요.';
  const noPlots = P().episodes.length ? '' : '<div class="note info">화별 플롯이 생기면 화를 줄기에 붙일 수 있어요. 줄기는 지금 만들어 둬도 돼요.</div>';
  return `${header('메인 · 서브플롯 · 회상 · 외전', '이야기 줄기', desc, add)}${noPlots}
    ${lineMap()}
    <div class="causal">${lines.length ? lineList() : `<div class="card empty"><p>아직 갈라진 줄기가 없어요.</p><div class="small">예: ${esc(exName(1))}의 빚(서브플롯), ${esc(exName(0))}이(가) 떠난 밤(과거 회상, 10년 전)</div></div>`}
      <div class="causal-main">${s ? lineEditor(s) : ''}${lineSuggestPanel()}</div></div>`;
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

Object.assign(actions, {
  lineSelect(id) {
    S.lineSel = String(id);
    render();
  },
  lineZoom(z) {
    S.lineZoom = Number(z) || 0;
    render();
  },
  lineEp(n) {
    S.selEp = Number(n);
    S.selAct = null;
    if (serial()) {
      const a = arcOf(Number(n));
      if (a) S.selArc = a.number;
    }
    location.hash = base() + '/arc';
  },
  async lineNew() {
    const id = newLineId();
    P().storylines.push({ id, kind: '서브플롯', title: '', focus: [], when: '', goal: '', branch_ep: 0, join_ep: 0, rejoin: '', summary: '' });
    S.lineSel = id;
    markDirty();
    render();
    document.getElementById(`f-storylines-${lineIndex(id)}-title`)?.focus();
  },
  async lineDelete() {
    const s = lineOf(S.lineSel);
    if (!s || !confirm(`'${s.title || '이름 없음'}' 줄기를 지울까요? 붙은 화는 메인으로 돌아가고, 플롯과 본문은 그대로예요.`)) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/storylines/${enc(s.id)}`);
      S.lineSel = null;
    });
  },
  lineTag(role) {
    const s = lineOf(S.lineSel);
    const eps = parseEps($('#line-tag-eps') && $('#line-tag-eps').value);
    if (!eps.length) return toast('붙일 화 번호를 적으세요', true);
    const missing = eps.filter((n) => !ep(n));
    if (missing.length) return toast(`플롯이 없는 화예요: ${missing.join(', ')}화`, true);
    eps.forEach((n) => tagEp(n, s.id, role));
    markDirty();
    render();
  },
  lineUntag(n) {
    const plot = ep(Number(n)).plot;
    if (plot.storyline === S.lineSel) plot.storyline = '';
    plot.threads = (plot.threads || []).filter((x) => x !== S.lineSel);
    markDirty();
    render();
  },
  async lineSuggest() {
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
    await run('더하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/storylines/apply`, {
        proposal: d, episodes: picked('main', d.episodes), threads: picked('thread', d.threads),
      });
      S.lineSel = S.project.storylines[S.project.storylines.length - 1].id;
      S.lineDraft = null;
      toast('줄기를 더했어요. 기승전결 · 플롯 화면에서 그 화들을 다듬으세요.');
    });
  },
});

/** 플롯 편집기에 붙는 줄기 선택 (app.js plotEditor 가 부른다). 줄기가 없으면 아무것도 그리지 않는다 */
function lineField(e) {
  const lines = P().storylines || [];
  if (!lines.length) return '';
  const n = e.plot.number;
  const busy = jobOwns(n);
  const opts = [['', '메인 줄기'], ...lines.map((s) => [s.id, `${s.kind} · ${s.title || s.id}`])]
    .map(([id, l]) => `<option value="${esc(id)}"${(e.plot.storyline || '') === id ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const scenes = lines.filter((s) => s.id !== e.plot.storyline).map((s) => `<label class="row" style="font-size:0.8125rem;gap:6px"><input type="checkbox" data-line-thread="${n}" value="${esc(s.id)}"${(e.plot.threads || []).includes(s.id) ? ' checked' : ''}${busy ? ' disabled' : ''}>${esc(s.title || s.id)}</label>`).join('');
  return `<div class="field"><label for="line-ep-${n}">이야기 줄기 <span class="hint">이 화가 주로 따라가는 줄기</span></label>
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
  if (t.dataset.lineAiKind !== undefined) { S.lineForm.kind = t.value; return; }
  if (t.dataset.linePick) { S.lineDraft.picks = { ...(S.lineDraft.picks || {}), [t.dataset.linePick]: t.checked }; return; }
  if (t.dataset.lineDraftKind !== undefined) { S.lineDraft.storyline.kind = t.value; return; }
  if (S.route[2] !== 'lines') return;
  const s = lineOf(S.lineSel);
  if (!s) return;
  if (t.dataset.lineKind !== undefined) s.kind = t.value;
  else if (t.dataset.lineFocus) s.focus = t.checked ? [...new Set([...s.focus, t.dataset.lineFocus])] : s.focus.filter((x) => x !== t.dataset.lineFocus);
  else {
    // 글을 고친 칸은 다시 그리지 않는다 (커서를 잃지 않게). 범위와 시점은 노선도에 바로 보이도록 다시 그린다
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
