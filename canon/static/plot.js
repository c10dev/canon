/* 3단계 기승전결 · 플롯(단편)과 부 · 아크 · 플롯(장편), 서술 시점, 플롯 편집기의 등장 인물. app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 3. 기승전결 · 플롯 -----

// ----- 서술 시점: 화 플롯 → 구간 → 아크 순서로 찾고, 비면 작품 기본 (prompts.pov_of 와 같은 규칙) -----

const POV_MODES = ['1인칭', '3인칭 제한', '3인칭 전지'];

function povText(n) {
  const e = ep(n);
  if (e && (e.plot.pov || e.plot.pov_mode)) {
    return [e.plot.pov ? charName(e.plot.pov) : '', e.plot.pov_mode || ''].filter(Boolean).join(' · ');
  }
  const act = actOf(n);
  if (act && (act.pov || '').trim()) return act.pov.trim();
  const arc = serial() ? arcOf(n) : null;
  return arc && (arc.pov || '').trim() ? arc.pov.trim() : '';
}

/** 글 속 이름으로 인물 찾기. 긴 이름부터 봐서 '서윤'이 '윤'보다 먼저 맞는다 */
/** 글 속 이름(또는 id)으로 인물 찾기. 먼저 나온 인물, 같은 자리면 긴 이름 (prompts.char_in_text 와 같은 규칙) */
function charInText(text) {
  if (!text) return null;
  let best = null;
  P().characters.forEach((c) => [c.name, c.id].forEach((k) => {
    const i = k ? text.indexOf(k) : -1;
    if (i >= 0 && (!best || i < best.i || (i === best.i && k.length > best.len))) best = { i, len: k.length, c };
  }));
  return best ? best.c : null;
}

/** 시점 글 속 서술 방식 (prompts.mode_in 과 같은 규칙) */
const modeIn = (t) => (t.includes('전지') ? '3인칭 전지' : t.includes('3인칭') ? '3인칭 제한' : t.includes('1인칭') ? '1인칭' : '');

/** n화를 누구 시점으로 쓰는지: 화에 정한 인물 → 구간 · 아크 시점 글 속 인물 → 작품 기본 시점 (주인공이면 역할이 주인공인 인물) */
function povChar(n) {
  const e = ep(n);
  if (e && e.plot.pov) return { c: P().characters.find((c) => c.id === e.plot.pov) || null, omni: false, from: '화' };
  if (e && e.plot.pov_mode) {  // 서술 방식만 적었으면 시점 인물은 물려받는다
    const omni = e.plot.pov_mode.includes('전지');
    return { c: omni ? null : inheritedPov(n).c, omni, from: '화' };
  }
  return inheritedPov(n);
}

/** 화에 적지 않았을 때의 시점: 구간 · 아크 시점 글 → 작품 기본 */
function inheritedPov(n) {
  const act = actOf(n);
  const arc = serial() ? arcOf(n) : null;
  const plan = ((act && act.pov) || (arc && arc.pov) || '').trim();
  if (plan) return { c: charInText(plan), omni: plan.includes('전지'), from: act && act.pov ? '구간' : '아크' };
  const base = P().style.narration_pov || '';
  if (base.includes('전지')) return { c: null, omni: true, from: '작품 기본' };
  const lead = base.includes('주인공') ? P().characters.find((c) => (c.role || '').includes('주인공')) : null;
  return { c: charInText(base) || lead || null, omni: false, from: '작품 기본' };
}

/** 성별은 설정 칸, 비었으면 역할 글(여주 · 남주)로 본다 */
function charGender(c) {
  const role = c.role || '';
  return c.gender || (role.includes('여주') ? '여' : role.includes('남주') ? '남' : '');
}

/** 화 카드 위 시점 배지. 여주인공 핑크, 남주인공 파랑, 그 밖의 인물은 보라, 전지 시점은 회색. 화에 직접 정하지 않고 물려받은 시점은 점선 */
function povBadge(n) {
  const v = povChar(n);
  if (!v.c && !v.omni) return '';
  const kind = v.c ? ((v.c.tier || 'main') === 'main' ? { 여: 'her', 남: 'him' }[charGender(v.c)] || 'other' : 'other') : 'omni';
  const label = v.c ? (v.c.name || v.c.id) : '전지';
  const e = ep(n);
  // 화에 정했으면 '도현 · 1인칭 시점 (이 화에 정함)', 물려받았으면 구간 · 아크 시점 글이 이름과 다를 때만 덧붙인다
  const plan = povText(n);
  const tip = v.from === '화' ? `${[label, e && e.plot.pov_mode].filter(Boolean).join(' · ')} 시점 (${povSource(v.from)})`
    : `${label} 시점 (${povSource(v.from)})${plan && plan !== label ? ' · ' + plan : ''}`;
  return `<span class="pov-chip ${kind}${v.from === '화' ? '' : ' inherit'}" title="${esc(tip)}">${esc(label)}</span>`;
}

/** 시점을 어디서 정했나: 화 · 구간 · 아크 · 작품 기본 */
const povSource = (from) => (from === '화' ? '이 화에 정함' : from === '작품 기본' ? '작품 기본 시점' : `${from}에서 물려받음`);

/** 화 카드 이름에 넣을 시점: '도현 시점(구간에서 물려받음)'. 배지가 없으면 빈 글 */
function povSummary(n) {
  const v = povChar(n);
  if (!v.c && !v.omni) return '';
  return `${v.c ? v.c.name || v.c.id : '전지'} 시점(${povSource(v.from)})`;
}

/** 플롯 보드 위 배지 범례 (색과 점선의 뜻) */
const POV_LEGEND = '<div class="small pov-legend">시점 배지: 실선은 이 화에 정함, 점선은 구간 · 아크 · 작품 기본에서 물려받음. 분홍 여주인공, 파랑 남주인공, 보라 그 밖의 인물, 회색 전지 시점</div>';

/** 인물 화면 인물 카드(cast.js castSheetEdit)의 시점 서술 말투. 이 인물이 시점 인물인 화에만 본문 지시에 들어간다 (prompts.voice_line).
    값도 없고 이 인물 시점인 화도 없으면 접어 둔다 (단역 카드가 길어지지 않게) */
function voiceField(c, b) {
  const note = (S.voices || {})[c.id];
  const eps = P().episodes.map((e) => e.plot.number).filter((n) => (povChar(n).c || {}).id === c.id);
  const body = `${input('서술 말투 (이 인물 시점 화의 지문)', b + '.narration_voice', { rows: 3, autogrow: true, hint: `${c.name || '이 인물'} 시점 화의 지문 · 내면 독백`, placeholder: '예: 서술 어미는 ~했어요, ~인 걸까요? 처럼 부드럽게. 비우면 작품 문체 그대로' })}
    ${note ? `<div class="note info">${esc(note)}</div>` : ''}
    ${eps.length ? `<div class="small">이 말투가 들어가는 화: ${rangeText(eps)}화</div>`
      : (c.narration_voice || '').trim() ? `<div class="note warn">아직 ${esc(c.name || '이 인물')} 시점인 화가 없어서 이 말투는 어느 화에도 들어가지 않아요. <a href="${base()}/arc">${stepLabel('arc')}</a>에서 시점 인물을 정하세요.</div>` : ''}
    <div class="small">대사는 위의 말투(대사)를 따라요. 이 말투로 쓴 화는 어미 관련 문체 경고(과거형 비율, 문체 거리, 표지)를 빼요.</div>
    <div class="row" style="flex-wrap:nowrap"><input type="text" id="voice-req-${esc(c.id)}" aria-label="${esc(c.name || '이 인물')} 서술 말투 AI 요청" placeholder="AI에게 바랄 점 (예: 더 냉소적으로, 문장을 짧게)" style="flex:1">
      <button type="button" class="btn small" style="flex:none" data-action="voiceAI" data-arg="${esc(c.id)}">설정에서 AI로 초안</button></div>`;
  return eps.length || (c.narration_voice || '').trim() || note ? body
    : `<details class="voice-more"><summary>서술 말투 (이 인물 시점 화의 지문) <span class="small">이 인물 시점 화가 생기면 써요</span></summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">${body}</div></details>`;
}

/** 플롯 편집기의 시점 칸. 비우면 구간 · 아크 시점, 그것도 없으면 작품 기본 시점 */
function povField(e, locked) {
  const n = e.plot.number;
  const b = `episodes.${epIndex(n)}.plot`;
  const plan = (() => { const act = actOf(n); const arc = serial() ? arcOf(n) : null; return (act && act.pov) || (arc && arc.pov) || ''; })();
  const from = inheritedPov(n).from;  // 구간 · 아크 · 작품 기본 중 어디서 물려받나
  const fallback = plan ? `${from} 시점 (${plan})` : `작품 기본 (${P().style.narration_pov || '정하지 않음'})`;
  const opts = [['', fallback], ...P().characters.map((c) => [c.id, c.name || c.id])]
    .map(([v, l]) => `<option value="${esc(v)}"${(e.plot.pov || '') === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
  return `<div class="grid-2">
      <div class="field"><label for="pov-ep-${n}">시점 인물 <span class="hint">이 화를 누구 눈으로</span></label>
        <select id="pov-ep-${n}" data-bind="${b}.pov" data-kind="text"${locked ? ' disabled' : ''}>${opts}</select></div>
      ${input('서술 방식', b + '.pov_mode', { readonly: locked, list: 'pov-modes', placeholder: `비우면 ${modeIn(plan) || P().style.narration_pov || '1인칭'}` })}
    </div><datalist id="pov-modes">${POV_MODES.map((m) => `<option value="${m}"></option>`).join('')}</datalist>`;
}

document.addEventListener('change', (e) => {  // 시점 인물을 바꾸면 화 카드 표시도 바로 바꾼다
  if (e.target.id && e.target.id.startsWith('pov-ep-')) render();
});

function epCard(e, sel) {
  return `<button type="button" class="ep-card ${e.status}${sel && sel.plot.number === e.plot.number ? ' sel' : ''}" data-action="selectEp" data-arg="${e.plot.number}" aria-label="${e.plot.number}화 ${esc(e.plot.title)}${povSummary(e.plot.number) ? ' · ' + esc(povSummary(e.plot.number)) : ''} · ${stepText(e)} 플롯 열기">
      <span class="ep-top"><strong>${e.plot.number}화</strong><span class="ep-chips">${povBadge(e.plot.number)}${e.realign ? `<span class="chip written" title="${esc(e.realign)}">다시 맞추기</span>` : ''}${jobOwns(e.plot.number) ? '<span class="chip ai"><span class="spinner sm" aria-hidden="true"></span>새로 만드는 중</span>' : ''}<span class="chip ${e.status}">${STATUS[e.status]}</span></span></span>
      <span class="t">${esc(e.plot.title) || '제목 없음'}</span>${lineBadge(e)}<span class="s">${esc(e.plot.summary)}</span>${e.plot.ending_hook ? `<span class="hook"><strong>엔딩 훅</strong> ${esc(e.plot.ending_hook)}</span>` : ''}${stepBar(e)}</button>`;
}

/** 기승전결 보드: 구간마다 가로 띠를 위에서 아래로 쌓고 그 아래에 화 카드 격자를 둔다. 맨 위 범위 막대로 띠를 건너뛴다.
    단편은 작품 전체 구조, 장편은 고른 아크의 구조를 그린다 */
function actBoard(acts, eps, sel) {
  const slot = (n) => `<div class="ep-slot" aria-hidden="true">${jobOwns(n) ? '<span class="spinner sm"></span> ' : ''}${n}화${jobOwns(n) ? ' 만드는 중' : ''}</div>`;
  // 4화보다 짧은 작품은 이웃 구간이 한 화를 함께 쓴다. 그 화 카드는 앞 구간에만 두고 뒤 구간에는 안내만 둔다
  const owner = (n) => acts.findIndex((x) => x.start_ep <= n && n <= x.end_ep);
  const cols = acts.map((a, i) => {
    const count = Math.max(0, a.end_ep - a.start_ep + 1);
    const all = Array.from({ length: Math.min(count, 60) }, (_, k) => a.start_ep + k);
    const nums = all.filter((n) => owner(n) === i);
    const shared = all.filter((n) => owner(n) !== i);
    const inAct = eps.filter((e) => nums.includes(e.plot.number));
    const share = shared.length ? `<div class="ep-slot shared">${shared.map((n) => `${n}화`).join(', ')}는 ${acts[owner(shared[0])].name} 구간과 한 화에 함께 들어가요</div>` : '';
    const block = (label, text) => `<div class="act-block"><span class="act-label">${label}</span><p class="${text ? '' : 'empty-text'}">${esc(text) || '비어 있음'}</p></div>`;
    const editing = S.selAct === i;
    return `<section class="act-col" id="act-${i}" tabindex="-1" aria-label="${a.name} 구간">
        <div class="act-head ${actClass(a.name)}${editing ? ' sel editing' : ''}">
          <div class="between"><strong>${a.name}</strong><span class="act-meta">${epRange(a.start_ep, a.end_ep)}${count > 1 ? ` · ${count}화` : ''}</span></div>
          ${editing ? `<div class="act-form">${actEditor(i)}</div>` : `${block('구간 목표', a.goal)}${block('전환점', a.key_turn)}${a.pov ? block('서술 시점', a.pov) : ''}`}
          <button type="button" class="btn small act-edit" data-action="${editing ? 'closePanel' : 'selectAct'}" data-arg="${i}" aria-expanded="${editing}">${editing ? '고치기 닫기' : '구간 고치기'}</button>
        </div>
        <div class="act-eps"><span class="act-label">화별 플롯 ${inAct.length ? `${inAct.length}화` : ''}</span>
          ${share}${inAct.length ? inAct.map((e) => epCard(e, sel)).join('') : nums.map(slot).join('')}</div>
      </section>`;
  }).join('');
  // 구간 범위에 빈틈이 생기면 그 화 카드가 어느 열에도 들지 않는다. 사라지지 않게 따로 모아 보인다
  const loose = eps.filter((e) => owner(e.plot.number) < 0);
  const out = loose.length ? `<section class="act-col" aria-label="구간 밖"><div class="act-head"><div class="between"><strong>구간 밖</strong><span class="act-meta">${loose.length}화</span></div>
      <div class="note warn">어느 구간에도 들지 않는 화예요. 구간 범위를 고치면 제자리로 가요.</div></div>
      <div class="act-eps">${loose.map((e) => epCard(e, sel)).join('')}</div></section>` : '';
  const map = acts.length > 1 ? `<nav class="act-map" aria-label="구간으로 건너뛰기">${acts.map((a, i) => {
    const count = Math.max(1, a.end_ep - a.start_ep + 1);
    return `<button type="button" class="${actClass(a.name)}" style="flex:${count} 1 0" data-action="jumpAct" data-arg="${i}" title="${a.name} ${epRange(a.start_ep, a.end_ep)}">${a.name} <span class="act-meta">${epRange(a.start_ep, a.end_ep)}</span></button>`;
  }).join('')}</nav>` : '';
  return `${eps.some((e) => povBadge(e.plot.number)) ? POV_LEGEND : ''}${map}<div class="board">${cols}${out}</div>`;
}

/** 구간 범위가 start~end 화를 빈틈 · 겹침 없이 덮는지. 문제가 있으면 고칠 곳을 문장으로 돌려준다 (서버 validate_arc 가 저장을 막는 경우). */
function actCoverage(acts, start, end) {
  const out = [];
  const short = end - start + 1 < 4;  // 4화보다 짧으면 이웃 구간이 한 화를 함께 써도 된다
  const hits = new Map();
  acts.forEach((a) => { for (let n = a.start_ep; n <= a.end_ep && n - a.start_ep < 2000; n++) hits.set(n, (hits.get(n) || 0) + 1); });
  const gap = [];
  const twice = [];
  for (let n = start; n <= end; n++) {
    if (!hits.get(n)) gap.push(n);
    else if (hits.get(n) > 1 && !short) twice.push(n);
  }
  const beyond = [...hits.keys()].filter((n) => n < start || n > end);
  if (gap.length) out.push(`어느 구간에도 들지 않는 화: ${rangeText(gap)}화`);
  if (twice.length) out.push(`두 구간에 겹친 화: ${rangeText(twice)}화`);
  if (beyond.length) out.push(`범위(${epRange(start, end)}) 밖: ${rangeText(beyond.sort((a, b) => a - b))}화`);
  return out;
}


function viewArc() {
  const p = P();
  const eps = p.episodes;
  if (S.selEp && !ep(S.selEp)) S.selEp = null;
  if (S.selAct != null && !p.arc[S.selAct]) S.selAct = null;
  const sel = S.selEp ? ep(S.selEp) : null;

  let board;
  if (S.arcProposal) {
    board = arcProposalCard();
  } else if (!p.arc.length) {
    // AI 없이도 시작할 수 있게 직접 나누기를 둔다. 설정이 비어 있으면 AI 구조가 막연해지니 먼저 알린다
    const thin = !p.meta.logline.trim() || !p.characters.length;
    board = `<div class="card empty"><p>아직 기승전결 구조가 없어요.</p>
      ${thin ? `<div class="note warn"><a href="${base()}/setup">설정 도우미</a>에서 로그라인과 인물을 먼저 채우면 AI가 더 맞는 구조를 만들어요.</div>` : ''}
      <div class="row">${((b) => `<button class="btn primary" data-action="planArc"${b.attr}>${b.label}</button>`)(jobBtn('arc', null, 'AI로 구조 만들기'))}${noteToggle('arc', 'AI로 구조 만들기')}<button class="btn" data-action="splitArc">직접 나누기</button></div>
      ${planNoteField('arc', 'AI로 구조 만들기')}
      <span class="small">직접 나누면 ${p.meta.target_episodes}화를 기 · 승 · 전 · 결 네 구간으로 나눠요. 구간 목표는 구간 고치기에서 적어요. <strong>대화로 다듬기</strong>에서 말로 함께 짤 수도 있어요.</span></div>`;
  } else {
    const pj = jobFor('plots');
    const note = pj ? `<div class="note info">구간마다 초안을 만드는 중이에요${pj.note ? ` (${esc(pj.note)})` : ''}. 끝난 구간부터 카드가 채워지고, 채워진 화는 바로 고칠 수 있어요.</div>`
      : eps.length ? '' : '<div class="note info">구간을 확인한 뒤 <strong>화별 플롯 초안 만들기</strong>를 누르면 각 구간에 화 카드가 채워져요.</div>';
    board = `<div class="board-wrap">${note}${actBoard(p.arc, eps, sel)}</div>`;
  }


  const drafts = eps.filter((e) => e.status === 'draft').length;
  const end = p.arc.length ? Math.max(...p.arc.map((a) => a.end_ep)) : 0;
  const plotsLabel = eps.length ? '초안 다시 만들기 (확정 화 제외)' : '화별 플롯 초안 만들기';
  const canDraft = needsDraft(1, end) || jobFor('plots');
  const right = p.arc.length
    ? `${((b) => `<button class="btn" data-action="planArc"${b.attr}>${b.label}</button>`)(jobBtn('arc', null, '구조 다시 제안'))}${noteToggle('arc', '구조 다시 제안')}${canDraft ? ((b) => `<button class="btn" data-action="draftPlots"${b.attr}>${b.label}</button>`)(jobBtn('plots', null, plotsLabel)) + noteToggle('plots', plotsLabel) : ''}${drafts ? `<button class="btn primary" data-action="confirmAll"${jobFor('plots') ? ' aria-disabled="true" title="플롯 초안을 만드는 중이에요"' : ''}>초안 ${drafts}화 모두 확정</button>` : writeNextBtn()}`
    : '';
  // 장편으로 늘리기는 모든 화를 반영한 뒤에 쓸 수 있다 (작품 홈과 같은 이름)
  const fin = eps.length && eps.every((e) => e.status === 'finalized') && eps.length === p.meta.target_episodes;
  // 완결: 다음 할 일은 원고 내보내기나 장편으로 늘리기다 (내려받기 형식은 집필 화면 '복사 · 내보내기'에서 고른 것)
  const done = fin ? `<div class="note ok between"><span>모든 화를 반영했어요. 원고를 내보내거나 장편으로 늘려 이어 쓸 수 있어요.</span><span class="row"><button type="button" class="btn small" data-action="downloadTxt" data-arg="1-${p.meta.target_episodes}">전체 .txt 내려받기</button><a class="btn small primary" href="${base()}/convert">장편으로 늘리기</a></span></div>` : '';
  const tools = chatButton() + right;
  return `${header('3단계', stepLabel('arc'), '구간 목표를 확인하고, 화 카드를 눌러 플롯을 다듬은 뒤 확정하세요. 확정된 화만 본문을 쓸 수 있고, 초안을 다시 만들어도 확정된 화는 그대로예요.', tools)}
    ${done}${p.arc.length ? planNoteField('arc', '구조 다시 제안') + (canDraft ? planNoteField('plots', plotsLabel) : '') : ''}${board}${chatPanel('plot')}`;
}

// AI 로 구조 · 부 구성 · 플롯 초안을 다시 받을 때 함께 보낼 한 줄 요청 (S.planNote). 비우면 AI 가 정한다 (prompts.request_block).
// 요청 칸은 버튼 옆 '+ 요청'으로 펼치고, 펼친 버튼 하나에만 실린다. 칸 하나가 여러 버튼에 몰래 실리지 않게 한다
Object.assign(S, { planNoteFor: '' });  // 요청 칸을 펼친 '작품:버튼'. 버튼은 'arc'(구조) · 'plots'(플롯 초안) · 'series'(부 구성)

/** 이 작품에서 그 버튼의 요청 칸을 펼쳤나. 다른 작품으로 옮기면 접힌다 */
const noteOpen = (key) => S.planNoteFor === `${S.name}:${key}`;

/** 펼친 버튼이면 요청, 아니면 빈 글 */
const planNoteOf = (key) => (noteOpen(key) ? S.planNote || '' : '');

function noteToggle(key, what) {
  const on = noteOpen(key);
  return `<button type="button" class="btn small ghost" data-action="togglePlanNote" data-arg="${key}" aria-expanded="${on}"${on ? ` aria-controls="plan-note-${key}"` : ''} aria-label="${esc(what)}에 함께 보낼 요청${on ? ' 접기' : ' 적기'}" title="${esc(what)}에 함께 보낼 요청">${on ? '요청 접기' : '+ 요청'}</button>`;
}

function planNoteField(key, what) {
  if (!noteOpen(key)) return '';
  return `<label class="plan-note" id="plan-note-${key}"><span class="small"><strong>${esc(what)}</strong>에 함께 보낼 요청 (선택) · 이 버튼에만 실려요</span>
    <input type="text" data-local="planNote" value="${esc(S.planNote || '')}" placeholder="예: 3화 안에 첫 반전, 로맨스 비중은 줄이기"></label>`;
}

/** start~end 화 중 플롯 초안 작업이 새로 만들 화가 있다 (없는 화나 초안). 없으면 서버도 '새로 만들 초안이 없어요'로 막는다 (web._plot_ranges). */
function needsDraft(start, end) {
  for (let n = start; n <= end; n++) if (!ep(n) || ep(n).status === 'draft') return true;
  return false;
}

/** 확정해 둔 다음 쓸 화가 있으면 그 화 쓰기 버튼. 모두 확정한 뒤 플롯 화면에서 바로 집필로 간다. 장편은 arc 안의 화일 때만. */
function writeNextBtn(arc) {
  const e = ep(currentEp());
  if (!e || e.status !== 'confirmed' || (arc && (e.plot.number < arc.start_ep || e.plot.number > arc.end_ep))) return '';
  return `<a class="btn primary${arc ? ' small' : ''}" data-write-next href="${base()}/write/${e.plot.number}">${e.plot.number}화 쓰기</a>`;
}

/** 구조 제안: 구간마다 지금 값과 바꿀 값을 나란히 보인다 (대화 변경안과 같은 비교, chat.js actsDiff). */
function arcProposalCard() {
  const has = P().arc.length > 0;
  const diff = has ? actsDiff({ acts: S.arcProposal, total_episodes: 0 }) : '';
  const rows = has ? (diff || '<div class="small">지금 구조와 같아요.</div>')
    : S.arcProposal.map((a) => `<div class="diff-act"><span class="chip ${actClass(a.name)}">${a.name}</span><div class="diff-row"><span class="act-label">범위</span><ins>${epRange(a.start_ep, a.end_ep)}</ins></div>${ACT_FIELDS.map(([k, l]) => diffField(l, k, '', a[k])).join('')}</div>`).join('');
  return `<section class="card proposal" aria-label="AI 구조 제안">
    <div class="between"><h2>AI 구조 제안 <span class="chip ai">적용 전</span></h2>${proposalActions(['dropArcProposal'], ['useArcProposal'], has ? '이 구조로 바꾸기' : '이 구조로 시작')}</div>
    <p class="small">${has ? '지우는 것은 빨강, 새로 넣는 것은 초록이에요. 바꿔도 저장하기 전에는 작품에 들어가지 않아요.' : '고르면 구조가 생기고, 저장하면 작품에 들어가요.'}</p>
    <div class="diff">${rows}</div></section>`;
}

function actEditor(i) {
  const k = serial() ? P().story_arcs.findIndex((x) => x.number === S.selArc) : -1;
  const a = k >= 0 ? P().story_arcs[k].acts[i] : P().arc[i];
  if (!a) return '';
  const b = k >= 0 ? `story_arcs.${k}.acts.${i}` : `arc.${i}`;
  return `<div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number', min: 1 })}${input('끝 화', b + '.end_ep', { type: 'number', min: 1 })}</div>
    <div class="small">${k >= 0 ? '아크 안 기승전결 네 구간이 아크 첫 화부터 끝 화까지 빈틈없이 이어져야 저장돼요.' : '기승전결 네 구간이 1화부터 마지막 화까지 빈틈없이 이어져야 저장돼요.'}</div>
    ${((w) => (w.length ? `<div class="note warn" role="status">${w.map(esc).join('<br>')}</div>` : ''))(k >= 0
      ? actCoverage(P().story_arcs[k].acts, P().story_arcs[k].start_ep, P().story_arcs[k].end_ep)
      : actCoverage(P().arc, 1, P().meta.target_episodes))}
    ${input('구간 목표', b + '.goal', { rows: 3, autogrow: true, hint: '이 구간이 끝날 때 이야기가 어디까지 와 있어야 하나' })}
    ${input('전환점', b + '.key_turn', { rows: 2, autogrow: true, hint: '이 구간을 다음으로 넘기는 사건' })}
    ${input('서술 시점', b + '.pov', { placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})`, hint: `예: ${exName(1)} 1인칭. 화별 플롯을 만들 때 AI가 이 시점을 화마다 채워요` })}`;
}

/** 회수할 복선 고르기: 열린 복선을 설명과 함께 체크로 보인다. id 를 손으로 치다 틀리면 회수가 말없이 끊긴다. */
function payoffPicker(label, path, locked) {
  const p = P();
  const cur = getPath(p, path) || [];
  const open = p.foreshadows.filter((f) => f.status === 'open');
  const extra = cur.filter((id) => !open.some((f) => f.id === id));
  const box = (id, text, on) => `<label class="check-row"><input type="checkbox" data-payoff="${esc(path)}" value="${esc(id)}"${on ? ' checked' : ''}${locked ? ' disabled' : ''}><span>${text}</span></label>`;
  const rows = [
    ...open.map((f) => box(f.id, `${esc(f.description)} <span class="small">${f.planted_ep}화에 심음${f.due_ep ? ` · ${f.due_ep}화 회수 예정` : ''}</span>`, cur.includes(f.id))),
    ...extra.map((id) => { const f = p.foreshadows.find((x) => x.id === id); return box(id, `${esc(f ? f.description : id)} <span class="small">${f ? '이미 회수함' : '없는 복선 id'}</span>`, true); }),
  ];
  return `<fieldset class="field"><legend class="label">${label}</legend>${rows.length ? `<div class="payoff-list">${rows.join('')}</div>` : '<div class="small">회수할 수 있는 열린 복선이 없어요. 복선은 상태 승인에서 심으면 생겨요.</div>'}</fieldset>`;
}

/** 아크 주요 인물: id 를 손으로 치지 않고 이름으로 고른다. 비중별로 묶고, 아직 등록하지 않은 인물 후보(아크 · 플롯이 데려온 인물)는 '후보'로,
    설정이 없는 id 는 빼기만 할 수 있게 남긴다 */
function arcCastField(path) {
  const cur = getPath(P(), path) || [];
  const cs = P().characters;
  const cands = (P().cast_candidates || []).filter((c) => cur.includes(c.id));
  const box = (id, text, on) => `<label class="row" style="font-size:0.8125rem;gap:6px"><input type="checkbox" data-id-list="${esc(path)}" value="${esc(id)}"${on ? ' checked' : ''}>${text}</label>`;
  const groups = TIERS.map(([t, l]) => [l, cs.filter((c) => (c.tier || 'main') === t)]).filter(([, g]) => g.length);
  const unknown = cur.filter((id) => !cs.some((c) => c.id === id) && !cands.some((c) => c.id === id));
  return `<fieldset class="field"><legend class="label">주요 인물</legend>
    ${groups.map(([l, g]) => `<div class="row cast-boxes"><span class="small" style="min-width:32px">${l}</span>${g.map((c) => box(c.id, esc(c.name || `${c.id} (이름 없음)`), cur.includes(c.id))).join('')}</div>`).join('')}
    ${cands.length ? `<div class="row cast-boxes"><span class="small" style="min-width:32px" title="아직 등록하지 않은 인물이에요. 나오는 화를 확정하면 등록돼요">후보</span>${cands.map((c) => box(c.id, esc(c.name || c.id), true)).join('')}</div>` : ''}
    ${unknown.length ? `<div class="row cast-boxes"><span class="small" style="min-width:32px">설정 없음</span>${unknown.map((id) => box(id, esc(id), true)).join('')}</div>` : ''}</fieldset>`;
}

// 체크로 고르는 id 목록: 회수할 복선(payoffPicker)과 아크 주요 인물(arcCastField)
document.addEventListener('change', (e) => {
  const el = e.target;
  const path = el.dataset && (el.dataset.payoff || el.dataset.idList);
  if (!path) return;
  const list = getPath(P(), path) || [];
  setPath(P(), path, el.checked ? [...new Set([...list, el.value])] : list.filter((x) => x !== el.value));
  markDirty();
});

/** 주소가 화 플롯 페이지(#/p/<작품>/arc/<화>)면 그 화 번호, 아니면 0. 'arc/a3'(아크 고르기)와 없는 화는 보드로 간다 */
function plotPageN() {
  const a = S.route[3] || '';
  return S.route[0] === 'p' && S.route[2] === 'arc' && /^\d+$/.test(a) && P() && ep(Number(a)) ? Number(a) : 0;
}

/** 화 플롯 페이지. 서랍 대신 본문 폭으로 펴고 대화 패널은 옆에 그대로 둔다. 이웃 화로 옮기거나 닫을 때는 고친 것을 먼저 저장한다 (openPlot) */
function viewPlotPage(n) {
  const e = ep(n);
  const arc = serial() ? arcOf(n) : null;
  const act = actOf(n);
  // 이웃 화 띠: 장편은 그 아크 안, 단편은 작품 전체
  const nums = P().episodes.map((x) => x.plot.number).filter((x) => !arc || (x >= arc.start_ep && x <= arc.end_ep));
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const navBtn = (to, label) => to ? `<button type="button" class="btn small" data-action="openPlot" data-arg="${to}" aria-label="${label} ${to}화 플롯">${label === '이전' ? `◀ ${to}화` : `${to}화 ▶`}</button>` : '';
  const dot = (x) => {
    const s = ep(x).status;
    return `<button type="button" class="ep-dot ${s}${x === n ? ' cur' : ''}" data-action="openPlot" data-arg="${x}" aria-label="${x}화 ${STATUS[s]}"${x === n ? ' aria-current="page"' : ''}>${x}</button>`;
  };
  const where = [arc ? `아크 ${arc.number}${arc.title ? ' ' + esc(arc.title) : ''}` : '', act ? `${act.name} 구간` : ''].filter(Boolean);
  return `<nav class="crumbs small" aria-label="위치"><a href="${base()}/arc" data-action="closePlot">${stepLabel('arc')}</a>${where.map((x) => ` <span aria-hidden="true">›</span> ${x}`).join('')} <span aria-hidden="true">›</span> <strong>${n}화</strong></nav>
    <header class="page-head plot-head"><div class="row" style="gap:10px;min-width:0">${navBtn(prev, '이전')}<h1>${n}화 ${esc(e.plot.title) || '제목 없음'}</h1>${povBadge(n)}<span class="chip ${e.status}">${STATUS[e.status]}</span>${navBtn(next, '다음')}</div>
      <div class="row">${chatButton()}<button type="button" class="btn" data-action="closePlot">보드로</button></div></header>
    <div class="ep-dots" role="group" aria-label="${arc ? `아크 ${arc.number}의 화` : '화'}">${nums.map(dot).join('')}<span class="small">점선 칸은 아직 초안이에요</span></div>
    <section class="card plot-page" aria-label="${n}화 플롯">${plotEditor(e)}</section>${chatPanel('plot')}`;
}

/** 사건 순서: 사건마다 한 칸. 두 줄로 넘어가도 다음 사건이 어디서 시작하는지 보인다.
    Enter 는 다음 칸을 더하고(Shift+Enter 는 줄바꿈), 빈 칸에서 Backspace 는 그 칸을 뺀다. 비워 둔 칸은 저장 때 빠진다 (schema EpisodePlot.events) */
function eventsField(e, b, locked) {
  const n = e.plot.number;
  const evs = e.plot.events;
  const tool = (k, act, d, label, text, off) => `<button type="button" class="btn icon-btn small" data-action="${act}" data-arg="${n}:${k}${d}" aria-label="사건 ${k + 1} ${label}"${off ? ' disabled' : ''}>${text}</button>`;
  const rows = evs.map((x, k) => `<li class="ev-row"><span class="ev-no" aria-hidden="true">${k + 1}</span>
      <textarea id="ev-${n}-${k}" rows="1" data-autogrow data-bind="${b}.events.${k}" data-kind="text" data-event="${n}:${k}" aria-label="사건 ${k + 1}"${locked ? ' readonly' : ''}>${esc(x)}</textarea>
      <span class="ev-tools"><a class="btn icon-btn small" href="${base()}/stage/${n}/${k + 1}" aria-label="사건 ${k + 1} 장면 연출" title="장면 연출: 자리 · 자세 · 접촉 짜기">${(e.stage || []).some((s) => s.event_text === x) ? '🎬' : '<span aria-hidden="true">＋</span>🎬'}</a>${locked ? '' : `${tool(k, 'moveEvent', ':-1', '위로', '↑', k === 0)}${tool(k, 'moveEvent', ':1', '아래로', '↓', k === evs.length - 1)}${tool(k, 'dropEvent', '', '빼기', '✕', false)}`}</span></li>`).join('');
  return `<fieldset class="field ev-field"><legend class="label">사건 순서 <span class="hint">${locked ? '' : 'Enter로 다음 사건'}</span></legend>
    ${evs.length ? `<ol class="ev-list">${rows}</ol>` : `<span class="small">${locked ? '사건이 없어요' : '아직 사건이 없어요'}</span>`}
    ${locked ? '' : `<button type="button" class="btn small ghost ev-add" data-action="addEvent" data-arg="${n}">+ 사건 더하기</button>`}</fieldset>`;
}

// 사건 칸 키보드: Enter 는 아래에 새 칸, 빈 칸의 Backspace 는 그 칸 빼기 (한글 조합 중에는 받지 않는다)
document.addEventListener('keydown', (e) => {
  const t = e.target;
  if (!t.dataset || t.dataset.event == null || t.readOnly || e.isComposing || e.keyCode === 229) return;
  const [n, k] = t.dataset.event.split(':').map(Number);
  if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    actions.addEvent(n, k + 1);
  } else if (e.key === 'Backspace' && t.value === '' && k > 0) {
    e.preventDefault();
    actions.dropEvent(`${n}:${k}`, true);
  }
});

/** 화 플롯 페이지(viewPlotPage)의 몸통: 맥락(아크 · 구간 목표, 앞 화 엔딩 훅), 플롯 칸, 저장 칸이 든 버튼 줄. 머리와 이웃 화 단추는 페이지가 그린다 */
function plotEditor(e) {
  const n = e.plot.number;
  const i = epIndex(n);
  const b = `episodes.${i}.plot`;
  const busy = jobOwns(n);
  const autoBusy = autoEp() === n;
  const locked = e.status === 'written' || e.status === 'finalized' || busy || autoBusy;
  const ro = { readonly: locked };
  const act = actOf(n);
  const arc = serial() ? arcOf(n) : null;
  const pj = jobFor('plots');
  const before = ep(n - 1);
  return `<div class="plot-ctx">${arc ? `<div class="note plain"><strong>아크 ${arc.number} ${esc(arc.title)}</strong> · ${esc(arc.goal)}</div>` : ''}${act ? `<div class="note info"><strong>${act.name} 구간 목표</strong> · ${esc(act.goal)}</div>` : ''}${before && before.plot.ending_hook ? `<div class="note plain"><strong>${n - 1}화 엔딩 훅</strong> · ${esc(before.plot.ending_hook)}</div>` : ''}</div>
    ${busy ? `<div class="note warn">AI가 이 화의 초안을 새로 만드는 중이라 끝날 때까지 고칠 수 없어요${pj && pj.note ? ` (${esc(pj.note)})` : ''}. 먼저 끝난 구간의 화는 지금 고칠 수 있어요.</div>` : autoBusy ? `<div class="note warn">자동 집필이 ${n}화를 쓰는 중이라 고칠 수 없어요. 고치려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : locked ? '<div class="note plain">본문이 있는 화라 플롯을 고칠 수 없어요.</div>' : ''}
    ${realignNote(e)}
    ${input('제목', b + '.title', ro)}
    ${input('요약', b + '.summary', { ...ro, rows: 3, autogrow: true })}
    ${eventsField(e, b, locked)}
    ${castField(e, locked)}
    ${placeCandNotes(e)}
    ${lineField(e)}
    ${povField(e, locked)}
    ${tlOn() || e.plot.time ? input('작품 속 시점', b + '.time', { ...ro, hint: '직전 화에서 얼마나 지났는지. 바로 이어지면 비워요', placeholder: '예: 다음 날 아침, 사흘 뒤 밤' }) : ''}
    ${n <= 3 || e.plot.opening ? input('여는 장면', b + '.opening', { ...ro, rows: 2, autogrow: true, hint: n <= 3 ? '초반 화는 첫 장면이 독자를 붙잡아요' : '' }) : ''}
    ${input('감정 변화', b + '.emotional_shift', { ...ro, rows: 1, autogrow: true })}
    ${input('엔딩 훅', b + '.ending_hook', { ...ro, rows: 2, autogrow: true })}
    ${n <= 3 || e.plot.reader_question ? input('독자가 들고 갈 질문', b + '.reader_question', { ...ro, rows: 2, autogrow: true, hint: n <= 3 ? '이 화를 읽고 다음 화를 누르게 하는 질문' : '' }) : ''}
    <div class="grid-2">${input('심을 복선', b + '.foreshadow_plant', { ...ro, kind: 'list', rows: 2 })}${payoffPicker('회수할 복선', b + '.foreshadow_payoff', locked)}</div>
    ${insertBlock(e)}
    ${deleteBlock(e)}
    ${fitNextField(e)}
    <div class="row page-actions">
      <div class="savebar-slot"></div>
      ${draftOneBtn(e)}
      ${e.status === 'draft' ? `<button class="btn primary" style="flex:1" data-action="confirmEp" data-arg="${n}"${busy ? ' disabled' : ''}>${n}화 확정</button>` : ''}
      ${e.status === 'confirmed' ? `<button class="btn" style="flex:1" data-action="unconfirmEp" data-arg="${n}">초안으로 되돌리기</button><a class="btn primary" style="flex:1" href="${base()}/write/${n}">${n}화 쓰기</a>` : ''}
      ${locked ? `<a class="btn" style="flex:1" href="${base()}/write/${n}">본문 보기</a>` : ''}
    </div>
    ${openingPlotBlock(e)}`;
}

// 등장 인물: 비중별로 묶고, AI 플롯이 데려온 새 인물 후보와 설정 없는 id 를 따로 보여 준다
const TIERS = [['main', '주역'], ['support', '조연'], ['minor', '단역']];

function castField(e, locked) {
  const n = e.plot.number;
  const cs = P().characters;
  // 이름이 비었거나 이 화에서 처음 나오는 조연 · 단역은 서랍에서 다시 열어 고친다 (접은 뒤에도)
  const reopen = (c) => !locked && c.id !== S.castEdit && (!c.name || (c.tier !== 'main' && c.first_ep === n))
    ? `<button type="button" class="btn small ghost" data-action="editCast" data-arg="${esc(c.id)}" aria-label="${esc(c.name || c.id)} 고치기">고치기</button>` : '';
  const box = (c) => `<label class="row" style="font-size:0.8125rem;gap:6px"><input type="checkbox" value="${esc(c.id)}" data-cast-ep="${n}"${e.plot.characters.includes(c.id) ? ' checked' : ''}${locked ? ' disabled' : ''}>${esc(c.name || `${c.id} (이름 없음)`)}</label>${reopen(c)}`;
  const groups = TIERS.map(([t, l]) => [l, cs.filter((c) => (c.tier || 'main') === t)]).filter(([, g]) => g.length);
  const boxes = groups.length > 1
    ? groups.map(([l, g]) => `<div class="row cast-boxes"><span class="small" style="min-width:32px">${l}</span>${g.map(box).join('')}</div>`).join('')
    : `<div class="row cast-boxes">${cs.map(box).join('')}</div>`;
  const cands = (P().cast_candidates || []).filter((c) => e.plot.characters.includes(c.id));
  const unknown = e.plot.characters.filter((id) => !cs.some((c) => c.id === id) && !cands.some((c) => c.id === id));
  const btns = (pairs) => locked ? '' : `<div class="row" style="margin-top:6px">${pairs.map(([a, l, cls]) => `<button type="button" class="btn small${cls ? ' ' + cls : ''}" data-action="${a}" data-arg="${esc(n + '|' + l[1])}">${l[0]}</button>`).join('')}</div>`;
  const candNotes = cands.map((c) => `<div class="note info"><strong>새 인물 제안 · ${esc(c.name || c.id)}</strong> <span class="small">${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}</span>
    ${c.personality || c.goal ? `<br>${esc(c.personality || c.goal)}` : ''}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}
    <br><span class="small">AI 플롯이나 아크 기획이 데려온 인물이에요. 지금 등록하거나, 이 화를 확정하면 함께 등록돼요.</span>
    ${btns([['registerCast', ['인물로 등록', c.id], 'primary'], ['dropCast', ['이 화에서 빼기', c.id]]])}</div>`).join('');
  const unknownNotes = unknown.map((id) => `<div class="note warn"><strong>설정 없는 인물 · ${esc(id)}</strong><br><span class="small">플롯에 이름만 있고 인물 설정이 없어 본문을 쓸 때 이 인물 정보가 들어가지 않아요.</span>
    ${btns([['makeCast', ['인물로 만들기', id], 'primary'], ['dropCast', ['이 화에서 빼기', id]]])}</div>`).join('');
  const edit = cs.findIndex((c) => c.id === S.castEdit);
  return `<div class="field"><div class="between"><span class="label">등장 인물</span>${locked ? '' : `<button type="button" class="btn small" data-action="newCast" data-arg="${n}">+ 새 인물</button>`}</div>
    ${boxes}${candNotes}${unknownNotes}${edit >= 0 && !locked ? castQuickEdit(edit) : ''}</div>`;
}

// 플롯 편집기에서 바로 만드는 조연 · 단역. 나머지 칸은 설정 화면에서 채운다
function castQuickEdit(i) {
  const c = P().characters[i];
  const b = `characters.${i}`;
  return `<div class="note plain"><div class="between"><strong>${esc(c.name || '새 인물')}</strong><span class="row"><button type="button" class="btn small danger" data-action="dropNewCast" data-arg="${esc(c.id)}">이 인물 지우기</button><button type="button" class="btn small ghost" data-action="closeCastEdit">접기</button></span></div>
    <div class="grid-2">${input('이름', b + '.name')}${input('역할', b + '.role', { placeholder: '여관 주인, 동료 기사…' })}</div>
    ${nameIssuesFor(c.id)}
    <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보 뽑기</button><button type="button" class="btn small" data-action="nameAI" data-arg="${esc(c.id)}">AI 이름 추천</button></div>
    ${namePicks('c:' + c.id, 'useName', (x) => `${c.id}|${x}`)}
    <div class="grid-2">${tierSelect(c, b, 'cast-tier-' + i)}${input('성별', b + '.gender', { placeholder: '남 / 여' })}</div>
    ${input('성격 · 하는 일', b + '.personality', { rows: 2 })}
    ${input('말투', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 한 줄' })}
    <div class="small">${c.first_ep ? `${c.first_ep}화에 처음 나와요. ` : ''}나이, 원하는 것, 배경은 설정 화면에서 채울 수 있어요.</div></div>`;
}

function tierSelect(c, b, id) {
  return `<div class="field"><label for="${id}">비중 <span class="hint">주역은 매 화 설정 전체가 들어가고, 조연 · 단역은 나오는 화에만 들어가요${c.first_ep ? ` · ${c.first_ep}화에 처음 나옴` : ''}</span></label>
    <select id="${id}" data-bind="${b}.tier">${TIERS.map(([v, l]) => `<option value="${v}"${(c.tier || 'main') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>`;
}

// 화를 확정하면 그 화에 나오는 새 인물 후보도 등록된다
function castAddedToast(before) {
  const added = P().characters.slice(before);
  if (added.length) toast(`새 인물도 등록했어요: ${added.map((c) => c.name || c.id).join(', ')}`);
}

function castFirstEp(id) {
  const eps = P().episodes.filter((e) => e.plot.characters.includes(id)).map((e) => e.plot.number);
  return eps.length ? Math.min(...eps) : 0;
}

function newCastId() {
  const ids = new Set([...P().characters, ...(P().cast_candidates || [])].map((c) => c.id));
  for (let k = P().characters.length + 1; ; k++) if (!ids.has('char' + k)) return 'char' + k;
}

// ----- 3'. 장편 연재: 부 → 아크 → 화 -----

function arcFinished(a) {
  for (let n = a.start_ep; n <= a.end_ep; n++) if (!ep(n) || ep(n).status !== 'finalized') return false;
  return true;
}

function arcProgress(a) {
  const nums = a.end_ep - a.start_ep + 1;
  const inArc = P().episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
  return { nums, plotted: inArc.length, done: inArc.filter((e) => e.status === 'finalized').length, drafts: inArc.filter((e) => e.status === 'draft').length };
}

// 장편 화면에서 부 구성 · 아크 줄 카드를 펼쳐 둘지. 접으면 한 줄 띠가 되어 보드가 첫 화면에 온다. 이 브라우저에만 기억한다
Object.assign(S, { arcFull: (() => { try { return localStorage.getItem('canon.arcFull') === '1'; } catch { return false; } })() });

function viewSerial() {
  const p = P();
  const arcs = [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep);
  if (S.selEp && !ep(S.selEp)) S.selEp = null;
  if (S.selArc == null || (S.selArc !== 'next' && !arcs.some((a) => a.number === S.selArc))) {
    const cur = arcOf(currentEp());
    S.selArc = cur ? cur.number : arcs.length ? arcs[arcs.length - 1].number : 'next';
  }
  const arc = arcs.find((a) => a.number === S.selArc);
  if (S.selAct != null && !(arc && arc.acts[S.selAct])) S.selAct = null;
  const sel = S.selEp ? ep(S.selEp) : null;
  const planned = plannedUntil();
  const nextStart = planned + 1;
  // 고치는 부: 서랍 대신 부 칩 바로 아래에 편다 (접은 띠 · 펼친 부 구성 카드 중 보이는 쪽)
  const partEdit = S.selPart != null ? `<div class="part-edit">${partEditor(S.selPart)}</div>` : '';

  // 부 구성
  const partCard = (x) => {
    const inPart = arcs.filter((a) => a.start_ep >= x.start_ep && a.start_ep <= x.end_ep);
    const done = p.episodes.filter((e) => e.status === 'finalized' && e.plot.number >= x.start_ep && e.plot.number <= x.end_ep).length;
    const finished = done === x.end_ep - x.start_ep + 1;
    const here = nextStart >= x.start_ep && nextStart <= x.end_ep;
    return `<button type="button" class="part-card${S.selPart === x.number ? ' sel' : ''}${here ? ' here' : ''}" data-action="selectPart" data-arg="${x.number}" aria-pressed="${S.selPart === x.number}">
      <span class="between"><strong>${x.number}부 ${esc(x.title)}</strong><span class="small">${epRange(x.start_ep, x.end_ep)}</span></span>
      <span class="s">${esc(x.goal)}</span>
      <span class="row">${here ? '<span class="chip confirmed">지금 쓰는 부</span>' : ''}<span class="chip">아크 ${inPart.length}개</span><span class="chip ${done ? 'finalized' : ''}">반영 ${done}/${x.end_ep - x.start_ep + 1}</span>${finished ? (x.summary ? '<span class="chip finalized">요약 있음</span>' : '<span class="chip written">요약 필요</span>') : ''}</span>
    </button>`;
  };
  const lost = S.seriesDraft ? lostPartSummaries() : [];
  const seriesDraft = S.seriesDraft ? `<div class="card proposal">
      <div class="between"><h3>AI 부 구성 제안 <span class="chip ai">적용 전</span></h3><div class="row"><button class="btn small" data-action="dropSeries">버리기</button><button class="btn small primary" data-action="applySeries">이 부 구성 적용</button></div></div>
      ${S.seriesDraft.parts.map((x, i) => `<div class="part-draft">
        <div class="grid-2">${input(`${x.number}부 제목`, `parts.${i}.title`, { root: 'seriesDraft' })}<div class="grid-2">${input('시작 화', `parts.${i}.start_ep`, { root: 'seriesDraft', type: 'number' })}${input('끝 화', `parts.${i}.end_ep`, { root: 'seriesDraft', type: 'number' })}</div></div>
        ${input('부 목표', `parts.${i}.goal`, { root: 'seriesDraft', rows: 2, autogrow: true })}
        ${input('전환점', `parts.${i}.key_turn`, { root: 'seriesDraft', rows: 2, autogrow: true, hint: '부를 마무리하는 큰 사건이나 드러나는 비밀' })}
        ${input('아크 후보', `parts.${i}.arc_ideas`, { root: 'seriesDraft', kind: 'list', rows: 3, autogrow: true })}
      </div>`).join('')}
      <div class="small">부는 1화부터 ${p.meta.target_episodes}화까지 빈틈없이 이어져야 적용돼요. 이미 기획한 아크가 새 부 경계를 넘으면 적용하지 않아요.</div>
      ${lost.length ? `<div class="note warn">이 구성을 적용하면 범위가 바뀌어 저장된 ${lost.map((x) => `${x.number}부(${epRange(x.start_ep, x.end_ep)})`).join(', ')} 요약이 사라져요. 지키려면 그 부의 시작 화와 끝 화를 지금과 같게 두세요.</div>` : ''}
    </div>` : '';
  const seriesLabel = p.parts.length ? '부 구성 다시 제안' : 'AI로 부 구성 만들기';
  const seriesBtn = ((b) => `<button class="btn small" data-action="planSeries"${b.attr}>${b.label}</button>`)(jobBtn('series', null, seriesLabel));
  const series = `<section class="card">
      <div class="between"><h2>부 구성 <span class="small" style="font-weight:400">총 ${p.meta.target_episodes}화 · ${planned}화까지 아크 기획</span></h2><span class="row">${seriesBtn}${noteToggle('series', seriesLabel)}</span></div>
      ${planNoteField('series', seriesLabel)}
      ${p.parts.length ? `<div class="part-strip">${p.parts.map(partCard).join('')}</div>${partEdit}` : '<div class="small">무대와 판이 바뀌는 큰 단위(50~150화)예요. 없어도 아크를 이어 갈 수 있지만, 있으면 아크 기획이 부 목표를 따라가요.</div>'}
      ${seriesDraft}
    </section>`;

  // 아크 목록. 요약이 있는 부의 아크는 부 요약이 대신 들어가 따로 요약할 필요가 없다 (pipeline.pending_recaps 와 같은 규칙)
  const inSummed = (a) => p.parts.some((x) => x.summary && x.start_ep <= a.start_ep && a.start_ep <= x.end_ep);
  const pending = arcs.filter((a) => !a.summary && arcFinished(a) && !inSummed(a));
  const partsPending = p.parts.filter((x) => !x.summary && arcFinished(x));
  const arcChip = (a) => {
    const g = arcProgress(a);
    const folded = g.done === g.nums && !a.summary && inSummed(a);
    const state = g.done === g.nums ? (a.summary || folded ? 'finalized' : 'written') : g.plotted === 0 ? '' : g.drafts ? 'draft' : 'confirmed';
    return `<button type="button" class="arc-chip${S.selArc === a.number ? ' sel' : ''}" data-action="selectArc" data-arg="${a.number}" aria-pressed="${S.selArc === a.number}">
      <strong>아크 ${a.number}</strong> <span>${epRange(a.start_ep, a.end_ep)}</span> <span class="chip ${state}">${g.done === g.nums ? (a.summary ? '완료' : folded ? '부 요약에 포함' : '요약 필요') : g.plotted ? `반영 ${g.done}/${g.nums}` : '플롯 전'}</span></button>`;
  };
  const nextChip = planned < p.meta.target_episodes ? `<button type="button" class="arc-chip next${S.selArc === 'next' ? ' sel' : ''}" data-action="selectArc" data-arg="next">+ 다음 아크 <span>${nextStart}화부터</span></button>` : '';
  const notes = `${pending.length ? `<div class="note warn between"><span>요약이 필요한 끝난 아크 ${pending.length}개 · 가장 오래된 <a href="#" data-action="selectArc" data-arg="${pending[0].number}" style="color:inherit;font-weight:700">아크 ${pending[0].number}</a>부터 받으세요. 요약이 있어야 오래된 줄거리를 짧게 접어 넣을 수 있어요.</span></div>` : ''}
      ${partsPending.length ? `<div class="note warn between"><span>요약이 필요한 끝난 부 ${partsPending.length}개 · ${partsPending.map((x) => `<a href="#" data-action="selectPart" data-arg="${x.number}" style="color:inherit;font-weight:700">${x.number}부</a>`).join(', ')}. 부 요약은 그 부의 아크를 한 덩어리로 접어 프롬프트를 더 줄여요.${pending.some((a) => partsPending.some((x) => x.start_ep <= a.start_ep && a.start_ep <= x.end_ep)) ? ' 그 부의 아크 요약을 먼저 받으면 부 요약에 쓰여요.' : ''}</span></div>` : ''}`;
  // 부 구성 · 아크 줄은 한 줄 띠로 접어 보드를 첫 화면에 둔다. 아크가 없거나 부 구성 제안 · 작업이 있으면 펼친다 (버튼이 그 카드에 있다)
  const forced = !arcs.length || !!S.seriesDraft || !!jobFor('series');
  const full = S.arcFull || forced;
  const fold = forced ? '' : `<button type="button" class="btn small ghost" data-action="toggleArcFull" aria-expanded="${full}">${full ? '한 줄로 접기' : '부 · 아크 전체 보기'}</button>`;
  const rail = `<section class="card">
      <div class="between"><h2>아크</h2><span class="row"><span class="small">아크 하나는 5~30화짜리 작은 이야기예요. 다음 아크의 플롯만 그때그때 만들어요.</span>${fold}</span></div>
      <div class="arc-rail">${railChips(arcs, arcChip)}${nextChip}</div>
      ${notes}
    </section>`;
  const here = arc ? arc.start_ep : nextStart;
  const part = p.parts.find((x) => x.start_ep <= here && here <= x.end_ep);
  const partChip = part
    ? `<button type="button" class="arc-chip${S.selPart === part.number ? ' sel' : ''}" data-action="selectPart" data-arg="${part.number}" aria-pressed="${S.selPart === part.number}"><strong>${part.number}부 ${esc(part.title)}</strong> <span>${epRange(part.start_ep, part.end_ep)}</span></button>`
    : '<button type="button" class="arc-chip next" data-action="toggleArcFull">+ 부 구성</button>';
  const bar = full ? '' : `<div class="arc-bar"><div class="arc-rail">${partChip}<span class="arc-bar-sep" aria-hidden="true">›</span>${railChips(arcs, arcChip)}${nextChip}</div>${fold}</div>${partEdit}${notes}`;

  let body;
  const head = serialHead(pending, partsPending);
  if (S.selArc === 'next' || !arc) body = (bar ? `<section class="card">${bar}</section>` : '') + nextArcPanel(nextStart);
  else body = arcPanel(arc, sel, head, bar);

  const tools = chatButton() + (p.conversion ? `<a class="btn" href="${base()}/convert">단편에서 전환 · 되돌리기</a>` : '') + head.html;
  return `${header('3단계', stepLabel('arc'), '장편은 작품을 부와 아크로 나누고, 다음 아크 하나씩 기획해 그 아크의 플롯만 만들어요. 끝난 아크는 요약으로 접혀서 몇백 화를 써도 프롬프트 크기가 일정해요.', tools)}
    ${full ? series + rail : ''}${body}${chatPanel('plot')}`;
}

/** 장편 화면 머리의 primary: 지금 할 일 하나. 끝난 아크 · 부 요약 → 다음 아크 기획 → 초안 확정, 그 밖에는 다음 할 일(nextStep).
    kind · arc 는 아크 카드가 같은 버튼을 두 번 두지 않게 알려 준다. */
function serialHead(pending, partsPending) {
  const p = P();
  const [label, href] = nextStep();
  const link = { html: `<a class="btn primary" href="${href}">${esc(label)}</a>` };
  if (href === `${base()}/auto`) return link;  // 자동 집필이 돌거나 검토를 기다린다
  // 요약: 받은 제안이 있으면 그 카드에서 저장하는 일이 남았다
  const recap = (kind, x) => {
    const key = (kind === 'arc' ? 'arc' : 'part') + x.number;
    const name = kind === 'arc' ? `아크 ${x.number}` : `${x.number}부`;
    const pick = kind === 'arc' ? 'selectArc' : 'selectPart';
    if (S.recapDrafts[key]) {
      const open = kind === 'arc' ? S.selArc === x.number && !S.selPart : S.selPart === x.number;
      return open ? { html: '' } : { html: `<button class="btn primary" data-action="${pick}" data-arg="${x.number}">${name} 요약 제안 보기</button>` };
    }
    const b = jobBtn(kind === 'arc' ? 'recap_arc' : 'recap_part', x.number, `${name} 요약 받기`);
    return { kind: 'recap_' + kind, arc: x.number, html: `<button class="btn primary" data-action="${kind === 'arc' ? 'recapArc' : 'recapPart'}" data-arg="${x.number}"${b.attr}>${b.label}</button>` };
  };
  if (pending.length) return recap('arc', pending[0]);
  if (partsPending.length) return recap('part', partsPending[0]);
  if (href !== `${base()}/arc`) return { ...link, kind: 'link' };  // n화 쓰기 · 상태 승인
  const e = p.episodes.length ? ep(currentEp()) : null;
  const a = e && e.status === 'draft' ? arcOf(e.plot.number) : null;
  if (a) {
    const drafts = p.episodes.filter((x) => x.status === 'draft' && x.plot.number >= a.start_ep && x.plot.number <= a.end_ep).length;
    return { kind: 'confirm', arc: a.number, html: `<button class="btn primary" data-action="confirmAll" data-arg="${a.number}"${jobFor('plots') ? ' aria-disabled="true" title="플롯 초안을 만드는 중이에요"' : ''}>아크 ${a.number} 초안 ${drafts}화 모두 확정</button>` };
  }
  // 다음 아크 기획: 그 칸을 열면 칸 안의 'AI로 다음 아크 제안'이 primary 다
  if (plannedUntil() < p.meta.target_episodes && S.selArc !== 'next') return { html: `<button class="btn primary" data-action="selectArc" data-arg="next">${esc(label)}</button>` };
  return { html: '' };
}

const PLAN_AHEAD_MAX = 2;  // pipeline.PLAN_AHEAD_MAX

/** 다음 아크 기획 앞 경고: 본문보다 너무 앞서 짠 아크, 요약이 없는 끝난 아크 · 부. 막지 않는다.
    pipeline.plan_ahead 와 같은 규칙 (tests/test_plan_ahead_js.py) */
function planAhead(p) {
  const written = Math.max(0, ...p.episodes.filter((e) => (e.text || '').trim() || e.status === 'written' || e.status === 'finalized').map((e) => e.plot.number));
  const until = Math.max(0, ...p.story_arcs.map((a) => a.end_ep));
  const unwritten = p.story_arcs.filter((a) => a.start_ep > written).length;
  const r = homeRecaps(p);
  const recaps = [...r.arcs.map((a) => ['arc', a.number]), ...r.parts.map((x) => ['part', x.number])];
  const serial = p.meta.form === 'serial';
  const notes = [];
  if (serial && unwritten >= PLAN_AHEAD_MAX) {
    const where = written ? `본문은 ${written}화까지인데` : '본문이 아직 없는데';
    notes.push(`${where} 아크가 ${until}화까지 짜여 있어요 (본문 없는 아크 ${unwritten}개). 앞 아크를 쓰고 요약한 뒤 기획하면 쓰인 줄거리를 보고 짤 수 있어요.`);
  }
  if (serial && recaps.length) {
    const names = recaps.map(([k, n]) => (k === 'arc' ? `아크 ${n}` : `${n}부`)).join(', ');
    notes.push(`끝났는데 요약이 없어요: ${names}. 먼저 요약하면 다음 아크 기획이 그 줄거리를 제대로 봐요. 요약이 없으면 화마다 첫 문장으로만 들어가요.`);
  }
  return { written, planned_until: until, unwritten_arcs: unwritten, recaps, notes };
}

function nextArcPanel(start) {
  const p = P();
  if (start > p.meta.target_episodes) return `<div class="card empty"><p>총 ${p.meta.target_episodes}화까지 아크가 모두 있어요.</p><span class="small">더 쓰려면 <a href="${base()}/setup">설정 도우미</a>에서 총 화수를 늘리세요. 마지막 부 끝 화가 따라 늘어나요.</span></div>`;
  const part = p.parts.find((x) => x.start_ep <= start && start <= x.end_ep);
  const old = p.foreshadows.filter((f) => f.status === 'open' && start - f.planted_ep > 50);
  const d = S.arcDraft;
  if (d) {
    const a = d.arc;
    return `<section class="card proposal">
      <div class="between"><h2>아크 ${a.number} 제안 <span class="chip ai">적용 전</span></h2><div class="row"><button class="btn small" data-action="dropArc">버리기</button><button class="btn small primary" data-action="applyArc">이 아크 적용</button></div></div>
      ${d.reply ? `<div class="note info">${esc(d.reply).replace(/\n/g, '<br>')}</div>` : ''}
      <div class="grid-2">${input('아크 제목', 'arc.title', { root: 'arcDraft' })}<div class="grid-2">${input('시작 화', 'arc.start_ep', { root: 'arcDraft', type: 'number', readonly: true })}${input('끝 화', 'arc.end_ep', { root: 'arcDraft', type: 'number' })}</div></div>
      ${input('아크 목표', 'arc.goal', { root: 'arcDraft', rows: 2, autogrow: true, hint: '아크가 끝날 때 바뀌어 있어야 하는 것' })}
      <div class="grid-2">${input('갈등', 'arc.conflict', { root: 'arcDraft', rows: 2, autogrow: true, hint: '주인공을 막는 문제나 상대' })}${input('보상 (사이다)', 'arc.payoff', { root: 'arcDraft', rows: 2, autogrow: true, hint: '클라이맥스에서 독자가 받는 것' })}</div>
      <div class="act-strip">${a.acts.map((x, i) => `<div class="act-head ${actClass(x.name)}"><div class="between"><strong>${x.name}</strong><span class="act-meta">${epRange(x.start_ep, x.end_ep)}</span></div>${input('구간 목표', `arc.acts.${i}.goal`, { root: 'arcDraft', rows: 3, autogrow: true })}</div>`).join('')}</div>
      ${input('서술 시점', 'arc.pov', { root: 'arcDraft', placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})` })}
      <div class="grid-2">${input('주요 인물 id', 'arc.cast', { root: 'arcDraft', kind: 'list', rows: 3 })}${input('회수할 복선 id', 'arc.payoffs', { root: 'arcDraft', kind: 'list', rows: 3 })}</div>
      ${d.new_characters.length ? `<div class="field"><span class="label">새 인물 (인물 후보로 들어와요. 이 인물이 나오는 화를 확정하면 조연으로 등록돼요)</span>${d.new_characters.map((c) => `<div class="note plain"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)}</span><br>${esc(c.personality || c.goal)}<br><span class="small">말투: ${esc(c.speech_style)}</span></div>`).join('')}</div>` : ''}
      <div class="small">끝 화를 바꾸면 결 구간이 따라 늘거나 줄어요. 다른 구간 범위는 적용한 뒤 구간 고치기에서 바꿀 수 있어요.</div>
    </section>`;
  }
  const btn = jobBtn('nextarc', null, 'AI로 다음 아크 제안');
  return `<section class="card">
    <div class="between"><h2>다음 아크 기획 <span class="small" style="font-weight:400">${start}화부터${part ? ` · ${part.number}부 ${esc(part.title)} (${part.end_ep}화까지)` : ''}</span></h2></div>
    ${part ? `<div class="note plain"><strong>${part.number}부 목표</strong> · ${esc(part.goal)}${part.arc_ideas.length ? `<br><span class="small">아크 후보: ${part.arc_ideas.map(esc).join(' / ')}</span>` : ''}</div>` : ''}
    ${old.length ? `<div class="note warn">50화 넘게 열린 복선이 ${old.length}개 있어요. 이번 아크에서 회수하거나 다시 떠올리도록 AI에게 함께 보여 줘요.</div>` : ''}
    <div class="grid-2">${input('아크 길이 (화)', 'length', { root: 'arcForm', type: 'number', min: 0, zeroBlank: true, placeholder: 'AI가 정함', hint: '비우면 AI가 내용에 맞게 (보통 10~25화)' })}<div></div></div>
    ${input('이번 아크에 바라는 것 (선택)', 'note', { root: 'arcForm', rows: 3, autogrow: true, placeholder: '예: 학교 밖으로 무대를 넓히고, 라이벌과 처음 손잡게' })}
    ${planAhead(p).notes.map((x) => `<div class="note warn">${esc(x)}</div>`).join('')}
    <div class="row"><button class="btn primary" data-action="planNextArc"${btn.attr}>${btn.label}</button><span class="small">지금까지 실제로 쓴 줄거리(요약), 부 목표, 열린 복선을 보고 아크 하나를 제안해요. 적용 전에 고칠 수 있어요.</span></div>
  </section>`;
}

/** 고른 아크 카드와 그 보드. bar 는 접은 부 · 아크 띠로, 있으면 카드 맨 위에 둔다 */
function arcPanel(a, sel, head = {}, bar = '') {
  const p = P();
  const k = p.story_arcs.indexOf(a);
  const g = arcProgress(a);
  const eps = p.episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
  const last = Math.max(...p.story_arcs.map((x) => x.start_ep)) === a.start_ep;
  const finished = arcFinished(a);
  const plotsLabel = g.plotted ? '초안 다시 만들기 (확정 화 제외)' : '화별 플롯 초안 만들기';
  const plotsBtn = jobBtn('plots', a.number, plotsLabel);
  const canDraft = needsDraft(a.start_ep, a.end_ep) || jobFor('plots', a.number);
  const names = (ids) => ids.map((id) => esc(charName(id))).join(', ');
  const rk = 'arc' + a.number;
  const r = S.recapDrafts[rk];
  let recap = '';
  if (finished) {
    const rb = jobBtn('recap_arc', a.number, a.summary ? 'AI로 요약 다시 제안' : 'AI로 요약 제안');
    recap = `<div class="recap">
      <div class="between"><h3>아크 요약 ${a.summary ? '<span class="chip finalized">있음</span>' : '<span class="chip written">필요</span>'}</h3>${head.kind === 'recap_arc' && head.arc === a.number ? '' : `<button class="btn small" data-action="recapArc" data-arg="${a.number}"${rb.attr}>${rb.label}</button>`}</div>
      ${r ? `${input('AI 요약 제안 (고친 뒤 저장)', `${rk}.summary`, { root: 'recaps', rows: 6, autogrow: true })}<div class="row"><button class="btn small" data-action="dropRecap" data-arg="${rk}">버리기</button><button class="btn small primary" data-action="applyRecap" data-arg="${rk}">이 요약 저장</button></div>` : ''}
      ${input('저장된 요약', `story_arcs.${k}.summary`, { rows: 4, autogrow: true, hint: '앞으로 이 아크의 화별 요약 대신 프롬프트에 들어가요. 요약이 없으면 화마다 첫 문장만 들어가 앞 이야기가 흐려져요' })}
    </div>`;
  }
  const right = `<div class="row">
      <button class="btn small" data-action="${S.editArc ? 'closePanel' : 'editArc'}" aria-expanded="${!!S.editArc}">${S.editArc ? '고치기 닫기' : '아크 고치기'}</button>
      ${canDraft ? `<button class="btn small" data-action="draftArcPlots" data-arg="${a.number}"${plotsBtn.attr}>${plotsBtn.label}</button>${noteToggle('plots', `아크 ${a.number} ${plotsLabel}`)}` : ''}
      ${head.kind === 'confirm' && head.arc === a.number ? '' : g.drafts ? `<button class="btn small${head.html ? '' : ' primary'}" data-action="confirmAll" data-arg="${a.number}"${jobFor('plots') ? ' aria-disabled="true" title="플롯 초안을 만드는 중이에요"' : ''}>초안 ${g.drafts}화 모두 확정</button>` : head.kind === 'link' ? '' : writeNextBtn(a)}
      ${last && !eps.some((e) => e.status !== 'draft') ? '<button class="btn small danger" data-action="removeLastArc">지우고 다시 기획</button>' : ''}
    </div>`;
  return `<section class="card">${bar ? `${bar}<hr class="arc-bar-rule">` : ''}
      <div class="between"><h2>아크 ${a.number} ${esc(a.title)} <span class="small" style="font-weight:400">${epRange(a.start_ep, a.end_ep)}${g.nums > 1 ? ` · ${g.nums}화` : ''} · 반영 ${g.done}/${g.nums}</span></h2>${right}</div>
      ${canDraft ? planNoteField('plots', `아크 ${a.number} ${plotsLabel}`) : ''}
      ${S.editArc ? `<div class="arc-form">${arcEditor(a)}</div>` : `<div class="arc-facts">
        <div><span class="act-label">아크 목표</span><p>${esc(a.goal) || '<span class="small">비어 있음</span>'}</p></div>
        <div><span class="act-label">갈등</span><p>${esc(a.conflict) || '<span class="small">비어 있음</span>'}</p></div>
        <div><span class="act-label">보상 (사이다)</span><p>${esc(a.payoff) || '<span class="small">비어 있음</span>'}</p></div>
      </div>
      <div class="small">${a.cast.length ? `주요 인물: ${names(a.cast)}` : ''}${a.payoffs.length ? `${a.cast.length ? ' · ' : ''}회수할 복선: ${a.payoffs.map((id) => esc((P().foreshadows.find((f) => f.id === id) || {}).description || id)).join(', ')}` : ''}</div>`}
      ${recap}
    </section>
    <div class="board-wrap">${((pj) => pj ? `<div class="note info">구간마다 초안을 만드는 중이에요${pj.note ? ` (${esc(pj.note)})` : ''}. 끝난 구간부터 카드가 채워지고, 채워진 화는 바로 고칠 수 있어요.</div>` : '')(jobFor('plots', a.number))}${g.plotted || jobFor('plots', a.number) ? '' : '<div class="note info">구간을 확인한 뒤 <strong>화별 플롯 초안 만들기</strong>를 누르면 이 아크의 화 카드가 채워져요.</div>'}${actBoard(a.acts, eps, sel)}</div>`;
}

function arcEditor(a) {
  const k = P().story_arcs.indexOf(a);
  const b = `story_arcs.${k}`;
  return `${input('제목', b + '.title')}
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number', readonly: true })}${input('끝 화', b + '.end_ep', { type: 'number', min: a.start_ep, readonly: k !== P().story_arcs.length - 1 })}</div>
    <div class="small">${k === P().story_arcs.length - 1 ? '끝 화를 바꾸면 구간도 따라 바뀌어요. 길이를 크게 바꾸려면 이 아크를 지우고 다시 기획하는 편이 쉬워요.' : '마지막 아크만 길이를 바꿀 수 있어요. 뒤 아크가 이 아크 다음 화부터 시작해요.'}</div>
    ${input('아크 목표', b + '.goal', { rows: 3, autogrow: true })}
    ${input('갈등', b + '.conflict', { rows: 2, autogrow: true })}
    ${input('보상 (사이다)', b + '.payoff', { rows: 2, autogrow: true })}
    ${input('서술 시점', b + '.pov', { placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})`, hint: '이 아크를 누구 시점으로 쓸지. 구간마다 다르면 구간 고치기에서' })}
    ${arcCastField(b + '.cast')}
    ${payoffPicker('회수할 복선', b + '.payoffs', false)}`;
}

function partEditor(number) {
  const p = P();
  const i = p.parts.findIndex((x) => x.number === number);
  if (i < 0) return '';
  const x = p.parts[i];
  const b = `parts.${i}`;
  const done = p.episodes.filter((e) => e.status === 'finalized' && e.plot.number >= x.start_ep && e.plot.number <= x.end_ep).length;
  const finished = done === x.end_ep - x.start_ep + 1;
  const rk = 'part' + number;
  const r = S.recapDrafts[rk];
  const rb = jobBtn('recap_part', number, x.summary ? 'AI로 요약 다시 제안' : 'AI로 요약 제안');
  return `<div class="between"><h3>${x.number}부 고치기 <span class="small" style="font-weight:400">${epRange(x.start_ep, x.end_ep)}</span></h3><button type="button" class="btn small" data-action="closePanel">고치기 닫기</button></div>
    ${input('제목', b + '.title')}
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number' })}${input('끝 화', b + '.end_ep', { type: 'number' })}</div>
    <div class="small">부는 1화부터 마지막 화까지 빈틈없이 이어져야 저장돼요.</div>
    ${input('부 목표', b + '.goal', { rows: 3, autogrow: true })}
    ${input('전환점', b + '.key_turn', { rows: 2, autogrow: true })}
    ${input('아크 후보', b + '.arc_ideas', { kind: 'list', rows: 5, autogrow: true, hint: '다음 아크를 기획할 때 참고해요' })}
    ${finished ? `<div class="between"><span class="label">부 요약</span><button class="btn small" data-action="recapPart" data-arg="${number}"${rb.attr}>${rb.label}</button></div>
      ${r ? `${input('AI 요약 제안 (고친 뒤 저장)', `${rk}.summary`, { root: 'recaps', rows: 6, autogrow: true })}<div class="row"><button class="btn small" data-action="dropRecap" data-arg="${rk}">버리기</button><button class="btn small primary" data-action="applyRecap" data-arg="${rk}">이 요약 저장</button></div>` : ''}` : '<div class="small">부의 모든 화가 반영되면 요약을 만들 수 있어요.</div>'}
    ${input('저장된 요약', b + '.summary', { rows: 4, autogrow: true })}`;
}


Object.assign(actions, {
  // 플롯 편집기의 등장 인물: 새 인물 만들기, AI 후보 등록, 설정 없는 id 를 인물로, 이 화에서 빼기
  newCast(n) {
    const id = newCastId();
    P().characters.push({ id, name: '', role: '', age: '', gender: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '', tier: 'minor', first_ep: Number(n) });
    const plot = ep(Number(n)).plot;
    plot.characters = [...plot.characters, id];
    S.castEdit = id;
    markDirty();
    render();
  },
  registerCast(arg) {
    const id = arg.split('|')[1];
    const list = P().cast_candidates || [];
    const c = list.find((x) => x.id === id);
    if (!c) return;
    P().cast_candidates = list.filter((x) => x.id !== id);
    P().characters.push({ ...c, tier: c.tier === 'main' ? 'support' : c.tier, first_ep: castFirstEp(id) });
    markDirty();
    render();
    toast(`${c.name || id}${josa(c.name || id, '을', '를')} ${c.tier === 'minor' ? '단역' : '조연'}으로 등록했어요. 저장하면 작품에 들어가요`);
    checkNames();
  },
  makeCast(arg) {
    const id = arg.split('|')[1];
    if (P().characters.some((c) => c.id === id)) return;
    P().characters.push({ id, name: '', role: '', age: '', gender: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '', tier: 'minor', first_ep: castFirstEp(id) });
    S.castEdit = id;
    markDirty();
    render();
  },
  dropCast(arg) {
    const [n, id] = arg.split('|');
    const plot = ep(Number(n)).plot;
    plot.characters = plot.characters.filter((x) => x !== id);
    markDirty();
    render();
  },
  closeCastEdit() {
    // 이름을 정하지 않고 접으면 'char4' 같은 id 만 남는다. 지울지 묻는다
    const c = P().characters.find((x) => x.id === S.castEdit);
    if (c && !c.name.trim() && confirm('이름 없는 인물을 지울까요? 남기려면 취소를 누르고, 나중에 등장 인물의 고치기로 다시 열어요.')) return actions.dropNewCast(c.id, true);
    S.castEdit = '';
    render();
  },
  editCast(id) {
    S.castEdit = id;
    S.focusTarget = '#app .plot-page .note.plain input';
    render();
  },
  /** 서랍에서 만든 인물을 지운다. 이 인물을 넣은 화의 등장 인물에서도 빼서 '설정 없는 인물'로 남지 않게 한다. 다른 곳에 쓰였으면 설정 화면의 삭제로 보낸다. */
  dropNewCast(id, asked = false) {
    const i = P().characters.findIndex((x) => x.id === id);
    if (i < 0) return;
    const c = P().characters[i];
    const used = P().relationships.some((r) => r.a === id || r.b === id) || P().history.some((h) => h.character_updates.some((u) => u.character_id === id) || (h.events || []).some((ev) => ev.actor === id || ev.target === id));
    if (used) return toast(`${c.name || id}${josa(c.name || id, '은', '는')} 관계나 반영 기록에 쓰여서 여기서 지울 수 없어요. 설정 도우미에서 지우세요`, true);
    const eps = P().episodes.filter((e) => e.plot.characters.includes(id)).map((e) => e.plot.number);
    if (!asked && !confirm(`${c.name || id} 인물을 지울까요? ${eps.length ? `${rangeText(eps)}화 등장 인물에서도 빠져요. ` : ''}저장하기 전에는 아래 띠에서 인물을 되살릴 수 있어요.`)) return;
    rememberRemoved(`인물 ${c.name || id}`, ['characters', 'states']);
    P().characters.splice(i, 1);
    P().states = P().states.filter((x) => x.character_id !== id);
    P().episodes.forEach((e) => { e.plot.characters = e.plot.characters.filter((x) => x !== id); });
    S.castEdit = '';
    markDirty();
    render();
  },
  // 구조와 플롯
  togglePlanNote(key) {
    const open = !noteOpen(key);
    S.planNoteFor = open ? `${S.name}:${key}` : '';
    S.focusTarget = open ? `#plan-note-${key} input` : `#app [data-action="togglePlanNote"][data-arg="${key}"]`;
    render();
  },
  async planArc() {
    await startJob('arc', null, { note: planNoteOf('arc') });  // 도착하면 지금 구조와 비교하는 제안 카드로 보인다. 고르기 전에는 바뀌지 않는다
  },
  splitArc() {
    // AI 없이 총 화수를 기승전결 네 구간으로 나눈다 (pipeline.act_ranges 와 같은 비율). 목표는 구간 고치기에서 적는다
    const r = actRanges(P().meta.target_episodes, 1);
    if (!r) return toast('총 화수를 먼저 정하세요', true);
    P().arc = ACTS.map((name, i) => ({ name, start_ep: r[i][0], end_ep: r[i][1], goal: '', key_turn: '', pov: '' }));
    S.selAct = 0;
    S.focusTarget = '#act-0 .act-form textarea';  // 기 구간 띠의 구간 목표 칸
    markDirty();
    render();
    toast('네 구간으로 나눴어요. 구간마다 목표를 적고 저장하세요');
  },
  useArcProposal() {
    P().arc = S.arcProposal;
    S.arcProposal = null;
    markDirty();
    render();
    toast('구조를 바꿨어요. 저장하면 작품에 들어가요');
  },
  dropArcProposal() {
    if (!confirmDrop('AI 구조 제안')) return;
    S.arcProposal = null;
    render();
  },
  async draftPlots() {
    if (!confirmRedraft(P().episodes)) return;
    await startJob('plots', null, { note: planNoteOf('plots') });
  },
  // 사건 칸 (eventsField). at 자리에 빈 칸을 넣는다 (비우면 끝에)
  addEvent(n, at) {
    const evs = ep(Number(n)).plot.events;
    const k = at == null || at === '' ? evs.length : Number(at);
    evs.splice(k, 0, '');
    markDirty();
    S.focusTarget = `#ev-${n}-${k}`;
    render();
  },
  /** 'n:k' 사건을 뺀다. back 이면 (빈 칸에서 Backspace) 앞 칸 끝으로 포커스를 옮긴다 */
  dropEvent(arg, back = false) {
    const [n, k] = String(arg).split(':').map(Number);
    const evs = ep(n).plot.events;
    evs.splice(k, 1);
    markDirty();
    const to = back ? k - 1 : Math.min(k, evs.length - 1);
    S.focusTarget = to >= 0 ? `#ev-${n}-${to}` : `#app [data-action="addEvent"][data-arg="${n}"]`;
    render();
    const el = back && $(`#ev-${n}-${to}`);
    if (el) el.setSelectionRange(el.value.length, el.value.length);
  },
  /** 'n:k:d' 사건을 d(-1 위, 1 아래)만큼 옮긴다 */
  moveEvent(arg) {
    const [n, k, d] = String(arg).split(':').map(Number);
    const evs = ep(n).plot.events;
    const j = k + d;
    if (j < 0 || j >= evs.length) return;
    [evs[k], evs[j]] = [evs[j], evs[k]];
    markDirty();
    S.focusTarget = `#app [data-action="moveEvent"][data-arg="${n}:${j}:${d}"]`;
    render();
  },
  // 화 카드 · 대화 변경안의 '지금 플롯' 등이 부른다
  selectEp(n) {
    return actions.openPlot(n);
  },
  /** 화 플롯 페이지로 간다. 고친 것은 먼저 저장한다 (주소가 바뀔 때 '저장하지 않고 이동할까요?' 창이 뜨지 않게).
      보드에서 열면 닫을 때 뒤로 가기로 돌아가 보던 자리를 지키고, 페이지끼리는 기록을 늘리지 않고 바꾼다 */
  async openPlot(n) {
    n = Number(n);
    if (S.dirty && !(await run('저장 중', async () => { if (await save() === false) throw new Error('저장하지 못해 옮기지 않았어요'); }, { render: 'never' }))) return;
    const onPage = plotPageN() > 0;
    if (!onPage) S.plotBack = S.route[2] === 'arc';
    S.focusTarget = '#app main h1';  // 페이지 제목으로 들어가 몇 화인지 읽게 한다
    const to = `${base()}/arc/${n}`;
    if (onPage) location.replace(to);
    else location.hash = to;
  },
  /** 화 플롯 페이지를 닫고 보드로. 연 카드로 포커스를 돌린다 */
  async closePlot() {
    const n = plotPageN();
    if (S.dirty && !(await run('저장 중', async () => { if (await save() === false) throw new Error('저장하지 못해 닫지 않았어요'); }, { render: 'never' }))) return;
    S.focusTarget = n ? `#app .ep-card[data-arg="${n}"]` : '#app main h1';
    const back = S.plotBack;
    S.plotBack = false;
    if (back) history.back();
    else location.hash = `${base()}/arc`;
  },
  selectAct(i) {
    S.focusTarget = `#act-${i} .act-form input`;  // 구간 띠 안에 편 칸의 첫 칸으로 들어간다
    S.selAct = Number(i);
    S.selEp = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  closePanel() {
    // 닫으면 고치기를 연 버튼으로 포커스를 돌린다
    S.focusTarget = S.selAct != null ? `#app [data-action="selectAct"][data-arg="${S.selAct}"]` : S.editArc ? '#app [data-action="editArc"]'
      : S.selPart != null ? `#app [data-action="selectPart"][data-arg="${S.selPart}"]` : null;
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  async confirmEp(n) {
    await run('확정하는 중', async () => {
      await saveIfDirty();
      const before = P().characters.length;
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/confirm`);
      castAddedToast(before);
    });
  },
  async unconfirmEp(n) {
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/unconfirm`);
    });
  },
  async confirmAll(arc) {
    const a = arc ? P().story_arcs.find((x) => x.number === Number(arc)) : null;
    const drafts = P().episodes.filter((e) => e.status === 'draft' && (!a || (e.plot.number >= a.start_ep && e.plot.number <= a.end_ep)));
    if (!drafts.length) return toast('확정할 초안이 없어요');
    if (jobFor('plots')) return toast('플롯 초안을 만드는 중이에요. 끝난 뒤에 확정하세요', true);
    if (!confirm(`초안 ${drafts.length}화를 모두 확정할까요?`)) return;
    await run('확정하는 중', async () => {
      await saveIfDirty();
      const before = P().characters.length;
      for (const e of drafts) S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${e.plot.number}/confirm`);
      castAddedToast(before);
      S.focusTarget = '#app [data-write-next]';  // 다음 할 일(그 화 쓰기)로 바로 간다
    });
  },

  // 장편: 부 · 아크
  async planSeries() {
    if (P().parts.length && !confirm('지금 부 구성을 AI 제안으로 바꿀까요? 적용 전에 확인할 수 있어요.')) return;
    await startJob('series', null, { note: planNoteOf('series') });
  },
  dropSeries() {
    if (!confirmDrop('AI 부 구성 제안')) return;
    S.seriesDraft = null;
    render();
  },
  async applySeries() {
    const lost = lostPartSummaries();
    if (lost.length && !confirm(`범위가 바뀌어 저장된 ${lost.map((x) => `${x.number}부`).join(', ')} 요약이 사라져요. 적용할까요?`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      const had = P().story_arcs.length > 0;
      S.project = await api('POST', `/projects/${enc(S.name)}/series/apply`, S.seriesDraft);
      S.seriesDraft = null;
      toast(had ? '부 구성을 바꿨어요. 아크와 반영한 화는 그대로예요.' : '부 구성을 적용했어요. 이제 첫 아크를 기획하세요.');
    });
  },
  // 구간 범위 막대 (actBoard): 그 구간 띠로 내려가고 포커스를 옮긴다
  jumpAct(i) {
    const el = document.getElementById(`act-${i}`);
    if (!el) return;
    el.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    el.focus({ preventScroll: true });
  },
  toggleArcFull() {
    S.arcFull = !S.arcFull;
    try { localStorage.setItem('canon.arcFull', S.arcFull ? '1' : '0'); } catch { /* 기억하지 못하면 이번에만 */ }
    S.focusTarget = '#app [data-action="toggleArcFull"]';
    render();
  },
  selectArc(n) {
    S.selArc = n === 'next' ? 'next' : Number(n);
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  editArc() {
    S.focusTarget = '#app .arc-form input';  // 아크 카드 안에 편 칸의 첫 칸(제목)
    S.editArc = true;
    S.selEp = null;
    S.selAct = null;
    S.selPart = null;
    render();
  },
  selectPart(n) {
    if (S.selPart === Number(n)) return actions.closePanel();  // 같은 부 칩을 다시 누르면 접는다
    S.focusTarget = '#app .part-edit input';
    S.selPart = Number(n);
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    render();
  },
  async planNextArc() {
    await startJob('nextarc', null, { length: Number(S.arcForm.length) || 0, note: S.arcForm.note || '' });
  },
  dropArc() {
    if (!confirmDrop('AI 다음 아크 제안')) return;
    S.arcDraft = null;
    render();
  },
  async applyArc() {
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/arcs/apply`, S.arcDraft);
      S.selArc = S.arcDraft.arc.number;
      S.arcDraft = null;
      S.arcForm = { length: 0, note: '' };
      toast('아크를 적용했어요. 화별 플롯 초안을 만드세요.');
    });
  },
  async removeLastArc() {
    if (!confirm('마지막 아크와 그 아크의 플롯 초안을 지울까요? 다시 기획할 수 있어요.')) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/arcs/last`);
      S.selArc = 'next';
    });
  },
  async draftArcPlots(n) {
    const a = P().story_arcs.find((x) => x.number === Number(n));
    if (a && !confirmRedraft(P().episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep))) return;
    await startJob('plots', Number(n), { note: planNoteOf('plots') });
  },
  async recapArc(n) {
    if (S.recapDrafts['arc' + n] && !confirm(`아크 ${n} 요약 제안이 아직 있어요. 고친 내용을 버리고 새로 받을까요?`)) return;
    await startJob('recap_arc', Number(n));
  },
  async recapPart(n) {
    if (S.recapDrafts['part' + n] && !confirm(`${n}부 요약 제안이 아직 있어요. 고친 내용을 버리고 새로 받을까요?`)) return;
    await startJob('recap_part', Number(n));
  },
  dropRecap(key) {
    if (!confirmDrop('AI 요약 제안')) return;
    delete S.recapDrafts[key];
    render();
  },
  async applyRecap(key) {
    const r = S.recapDrafts[key];
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/recap/${r.kind}/${r.number}`, { summary: r.summary });
      delete S.recapDrafts[key];
      toast('요약을 저장했어요. 앞으로 이 구간 대신 요약이 프롬프트에 들어가요.');
    });
  },
});
