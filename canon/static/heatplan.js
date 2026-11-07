// 열 계획 카드 (canon/heatplan.py 의 화면). 단편 기승전결 보드 위에 둔다.
// 화마다 막대 하나(열 0~5), 막대를 누르면 눈금 · 몫 · 정점 종류 · 한 줄을 고친다. 경고 규칙은 heatplan.warnings 와 같다 (tests/test_heatplan_js.py).

const HEAT_ROLES = { build: '쌓기', hold: '미루기', peak: '터뜨리기', after: '뒷날', rest: '쉬기' };
const HEAT_ROLE_WHY = {
  build: '열 없이 판돈 · 약점 · 관계를 심어요', hold: '터질 듯 막아요. 시한 · 금지선 · 들킬 뻔한 순간', peak: '심은 것을 거두며 열을 써요',
  after: '터진 일의 결과. 상대 시점으로 다시 겪거나 관객이 본 일이 돌아와요', rest: '숨을 고르며 다음 판돈을 심어요',
};
const HEAT_KINDS = { clue: '단서', stake: '판돈', constraint: '제약', audience: '관객', ban: '금지선' };
const HEAT_KIND_WHY = { stake: '잃을 수 있는 것', constraint: '행위를 막는 조건: 시한, 소리 금지, 계약', audience: '보거나 들을 수 있는 사람', ban: '오래 미루는 금지선' };
const HEAT_CV_MIN = 0.5;
const HEAT_FLAT_MIN = 4;
const HEAT_EARLY = 0.3;
const HEAT_HOT_CUE = 4;
const HEAT_MAX = 5;

Object.assign(S, { heatSel: 0, heatNewD: '', heatNewEp: '', heatNewKind: 'stake' });

// ----- 순수 계산 (heatplan.py 와 같은 규칙) -----

function heatPlan(p) {
  return p.meta && p.meta.form === 'serial' ? [] : (p.heat || []);
}

function heatTurn(p) {
  const t = p.meta && p.meta.form === 'serial' ? null : p.heat_turn;
  return t && t.plant_ep > 0 ? t : null;
}

/** 잇닿은 터뜨리기 화를 한 정점으로 묶는다 (heatplan.peak_runs) */
function heatPeakRuns(steps) {
  const runs = [];
  [...steps].sort((a, b) => a.ep - b.ep).forEach((s) => {
    if (s.role !== 'peak') return;
    const last = runs[runs.length - 1];
    if (last && last[last.length - 1].ep === s.ep - 1) last.push(s);
    else runs.push([s]);
  });
  return runs;
}

function heatPlotOf(p, n) {
  const e = (p.episodes || []).find((x) => x.plot.number === n);
  return e ? e.plot : null;
}

function heatPaid(p, run, fs, kinds) {
  const out = new Set();
  run.forEach((s) => {
    const plot = heatPlotOf(p, s.ep);
    ((plot && plot.foreshadow_payoff) || []).forEach((i) => { if (fs[i] && kinds.includes(fs[i].kind || 'clue')) out.add(i); });
  });
  return out;
}

/** 경고 [{ ep, code, text }]. 계획이 없으면 빈 목록 (heatplan.warnings) */
function heatWarnings(p) {
  const steps = heatPlan(p);
  if (!steps.length) return [];
  const out = [];
  const warn = (ep, code, text) => out.push({ ep, code, text });
  const fs = Object.fromEntries((p.foreshadows || []).map((f) => [f.id, f]));
  const levels = steps.map((s) => s.level);
  if (steps.length >= HEAT_FLAT_MIN) {
    const m = levels.reduce((a, b) => a + b, 0) / levels.length;
    const sd = Math.sqrt(levels.reduce((a, b) => a + (b - m) ** 2, 0) / levels.length);
    const cv = m ? sd / m : 0;
    if (cv < HEAT_CV_MIN) warn(0, 'flat', `열 눈금의 기복이 작아요 (변동계수 ${cv.toFixed(2)}, ${HEAT_CV_MIN} 이상을 권해요). 아끼는 화와 터뜨리는 화의 차이를 키워 보세요`);
  }
  const total = Math.max(p.meta.target_episodes || 0, ...steps.map((s) => s.ep));
  const gi = (p.arc || []).find((a) => a.name === '기');
  const runs = heatPeakRuns(steps);
  runs.forEach((run) => {
    run.forEach((s) => {
      if (s.ep <= total * HEAT_EARLY || (gi && gi.start_ep <= s.ep && s.ep <= gi.end_ep)) warn(s.ep, 'early_peak', `${s.ep}화의 터뜨리기가 일러요. 앞쪽은 쌓기 · 미루기로 열을 아껴요`);
    });
    const first = run[0].ep;
    if (!(p.foreshadows || []).some((f) => f.kind === 'stake' && f.planted_ep < first && (f.status === 'open' || (f.payoff_ep || 0) >= first))) {
      warn(first, 'no_stake', `${first}화 정점 전에 심은 판돈(stake)이 없어요. 잃을 수 있는 것을 앞 화에 심어 보세요`);
    }
    run.forEach((s) => {
      if (heatPlotOf(p, s.ep) && !heatPaid(p, [s], fs, ['audience', 'constraint']).size) warn(s.ep, 'no_pressure', `${s.ep}화 플롯이 거두는 관객(audience)이나 제약(constraint) 복선이 없어요`);
    });
  });
  const seen = {};
  runs.forEach((run) => {
    const hit = run.find((s) => (s.kind || '').trim());
    const k = hit ? hit.kind.replace(/\s+/g, ' ').trim() : '';
    if (k && seen[k] !== undefined) warn(run[0].ep, 'same_kind', `${run[0].ep}화 정점이 ${seen[k]}화 정점과 종류가 같아요 (${k}). 정점마다 종류를 바꿔 보세요`);
    if (seen[k] === undefined) seen[k] = run[0].ep;
  });
  if (runs.length >= 2) {
    const last = heatPaid(p, runs[runs.length - 1], fs, ['stake']);
    const before = new Set(runs.slice(0, -1).flatMap((r) => [...heatPaid(p, r, fs, ['stake'])]));
    if (last.size && [...last].every((i) => before.has(i))) warn(runs[runs.length - 1][0].ep, 'same_stake', `${runs[runs.length - 1][0].ep}화 큰 정점의 판돈이 앞 정점과 같아요. 남에게 드러나는 쪽으로 키워 보세요`);
  }
  const shown = new Set();
  [...(p.episodes || [])].sort((a, b) => a.plot.number - b.plot.number).forEach((e) => {
    const first = (e.plot.foreshadow_payoff || []).filter((i) => fs[i] && fs[i].kind === 'audience' && !shown.has(i));
    first.forEach((i) => shown.add(i));
    const nxt = heatPlotOf(p, e.plot.number + 1);
    if (!nxt) return;
    const text = [nxt.summary, ...(nxt.events || []), ...(nxt.foreshadow_payoff || [])].join(' ');
    first.forEach((i) => { if (!text.includes(i)) warn(nxt.number, 'no_aftermath', `${e.plot.number}화에서 거둔 관객 '${fs[i].description}'이 본 일의 결과가 ${nxt.number}화 플롯에 없어요`); });
  });
  const t = heatTurn(p);
  if (t && runs.length && t.fail_ep >= runs[runs.length - 1][0].ep) warn(t.fail_ep, 'late_turn', `반격이 ${t.fail_ep}화에 들켜요. 큰 정점(${runs[runs.length - 1][0].ep}화) 전에 들켜야 판돈이 커져요`);
  steps.forEach((s) => {
    const e = (p.episodes || []).find((x) => x.plot.number === s.ep);
    const sheet = e && e.cue_sheet;
    if ((s.role === 'build' || s.role === 'rest') && sheet && (sheet.cues || []).some((c) => c.tension >= HEAT_HOT_CUE)) warn(s.ep, 'hot_cue', `${s.ep}화는 ${HEAT_ROLES[s.role]} 화인데 큐 시트에 긴장도 ${HEAT_HOT_CUE} 이상 큐가 있어요`);
  });
  return out.map((w, i) => [w, i]).sort((a, b) => a[0].ep - b[0].ep || a[1] - b[1]).map(([w]) => w);  // 파이썬 sorted 처럼 같은 화는 순서를 지킨다
}

/** 열 낱말 수 / 공백 뺀 1천 자 (heatplan.density) */
function heatDensity(text, words) {
  const ws = (words || []).map((w) => w.trim()).filter(Boolean);
  const chars = (text || '').replace(/\s/g, '').length;
  if (!ws.length || !chars) return null;
  const hits = ws.reduce((a, w) => a + text.split(w).length - 1, 0);
  return Math.round(hits * 1000 / chars * 100) / 100;
}

/** 큐 긴장도를 목표 글자 수로 가중한 평균 (heatplan.cue_tension) */
function heatCueTension(sheet) {
  const cues = sheet && !sheet.skipped ? (sheet.cues || []) : [];
  if (!cues.length) return null;
  const weights = cues.some((c) => c.length > 0) ? cues.map((c) => c.length) : cues.map(() => 1);
  const total = weights.reduce((a, w) => a + Math.max(w, 0), 0);
  if (!total) return null;
  return Math.round(cues.reduce((a, c, i) => a + Math.min(Math.max(c.tension, 1), 5) * Math.max(weights[i], 0), 0) / total * 100) / 100;
}

/** 본문이 있는 화마다 실제 열 참고값 { ep: { density, tension } } */
function heatActual(p) {
  const out = {};
  (p.episodes || []).forEach((e) => {
    if (e.text) out[e.plot.number] = { density: heatDensity(e.text, (p.settings || {}).heat_words), tension: heatCueTension(e.cue_sheet) };
  });
  return out;
}

/** 손으로 적기 시작할 때의 밑그림: 기승전결 구간으로 앞은 쌓고 전 끝에서 터뜨린다 (reports 의 단편 열 설계 16화 예시를 줄인 것) */
function heatDefault(p) {
  const total = p.meta.target_episodes;
  const act = (n) => ((p.arc || []).find((a) => a.start_ep <= n && n <= a.end_ep) || {}).name || '';
  const range = (name) => (p.arc || []).find((a) => a.name === name);
  const seung = range('승');
  const jeon = range('전');
  const steps = [];
  for (let n = 1; n <= total; n++) {
    const a = act(n);
    let s = { ep: n, level: 1, role: 'build', kind: '', note: '' };
    if (a === '기') s.level = n === 1 ? 0 : 1;
    else if (a === '승') {
      s = seung && total >= 13 && n === seung.end_ep ? { ...s, level: 3, role: 'peak' } : { ...s, level: seung && n > (seung.start_ep + seung.end_ep) / 2 ? 2 : 1, role: seung && n > (seung.start_ep + seung.end_ep) / 2 ? 'hold' : 'build' };
    } else if (a === '전') {
      const hot = jeon && jeon.end_ep - jeon.start_ep >= 2 ? 2 : 1;
      if (jeon && n > jeon.end_ep - hot) s = { ...s, level: n === jeon.end_ep ? 5 : 4, role: 'peak' };
      else if (steps.length && steps[steps.length - 1].role === 'peak') s = { ...s, level: 1, role: 'after' };
      else s = { ...s, level: n === (jeon && jeon.start_ep) ? 2 : 3, role: 'hold' };
    } else if (a === '결') {
      const k = range('결');
      s = { ...s, level: k && n !== k.start_ep && n !== k.end_ep ? 1 : 2, role: k && n !== k.start_ep && n !== k.end_ep ? 'rest' : 'after' };
    }
    steps.push(s);
  }
  return steps;
}

// ----- 화면 -----

function heatBar(s, act, sel, warned, still = false) {
  const pct = (v) => `${Math.round((v / HEAT_MAX) * 100)}%`;
  const real = act && act.tension != null ? `<span class="heat-real" style="bottom:${pct(act.tension)}" aria-hidden="true"></span>` : '';
  const label = `${s.ep}화 열 ${s.level} · ${HEAT_ROLES[s.role]}${s.kind ? ` · ${s.kind}` : ''}${act ? ` · 실제 큐 긴장 ${act.tension ?? '없음'}, 열 낱말 ${act.density ?? '없음'}` : ''}${warned ? ' · 경고 있음' : ''}`;
  const body = `<span class="heat-track"><span class="heat-fill ${s.role}" style="height:${pct(s.level)}"></span>${real}</span>
      <span class="heat-ep">${s.ep}${warned ? '<span class="heat-dot" aria-hidden="true"></span>' : ''}</span>`;
  if (still) return `<span class="heat-col" title="${esc(label)}">${body}</span>`;  // 제안 미리보기: 누를 수 없다
  return `<button type="button" class="heat-col${sel ? ' sel' : ''}" data-action="heatPick" data-arg="${s.ep}" aria-pressed="${sel}" aria-label="${esc(label)}" title="${esc(label)}">${body}</button>`;
}

function heatEditor(p, n) {
  const i = (p.heat || []).findIndex((s) => s.ep === n);
  if (i < 0) return '';
  const s = p.heat[i];
  const seg = (label, items, cur, action) => `<div class="field"><span class="heat-lab">${label}</span><div class="seg heat-seg" role="group" aria-label="${n}화 ${label}">
    ${items.map(([v, t, why]) => `<button type="button" class="btn small" data-action="${action}" data-arg="${n}:${v}" aria-pressed="${String(v) === String(cur)}"${why ? ` title="${esc(why)}"` : ''}>${t}</button>`).join('')}</div></div>`;
  return `<div class="heat-edit" role="group" aria-label="${n}화 열 계획">
    ${seg('열', Array.from({ length: HEAT_MAX + 1 }, (_, k) => [k, String(k)]), s.level, 'heatLevel')}
    ${seg('몫', Object.entries(HEAT_ROLES).map(([k, t]) => [k, t, HEAT_ROLE_WHY[k]]), s.role, 'heatRole')}
    <p class="small">${esc(HEAT_ROLE_WHY[s.role])}</p>
    ${s.role === 'peak' ? input('정점 종류', `heat.${i}.kind`, { placeholder: '예: 맨정신의 흥정, 관객 앞 촬영', hint: '정점이 둘 이상이면 종류가 달라야 해요' }) : ''}
    ${input('이 화가 열에서 하는 일', `heat.${i}.note`, { placeholder: '예: 다은이 처음 의심한다. 노골 장면 없음' })}</div>`;
}

function heatStakes(p) {
  const eps = (p.episodes || []).map((e) => e.plot.number);
  const marked = (p.foreshadows || []).filter((f) => (f.kind || 'clue') !== 'clue');
  const open = (p.foreshadows || []).filter((f) => (f.kind || 'clue') === 'clue' && f.status === 'open');
  const chip = (f) => `<span class="chip heat-kind ${f.kind}" title="${esc(HEAT_KIND_WHY[f.kind] || '')}">${HEAT_KINDS[f.kind]}</span>`;
  const row = (f) => `<li class="heat-stake"><span>${chip(f)} ${esc(f.description)} <span class="small">${f.planted_ep}화에 심음${f.status === 'resolved' ? ` · ${f.payoff_ep}화에 거둠` : f.due_ep ? ` · ${f.due_ep}화에 거둘 예정` : ''}${f.public ? ' · 드러남' : ''}</span></span>
      <span class="row">${f.kind === 'stake' ? `<button type="button" class="btn small" data-action="heatPublic" data-arg="${esc(f.id)}" aria-pressed="${!!f.public}">${f.public ? '드러남' : '숨김'}</button>` : ''}<button type="button" class="btn small" data-action="heatKind" data-arg="${esc(f.id)}:clue">갈래 풀기</button></span></li>`;
  const kinds = Object.entries(HEAT_KINDS).filter(([k]) => k !== 'clue');
  return `<div class="heat-stakes"><span class="heat-h">판돈 · 제약 · 관객 · 금지선 ${marked.length}</span>
    ${marked.length ? `<ul class="plain">${marked.map(row).join('')}</ul>` : '<p class="small">아직 없어요. 정점은 앞 화에 심은 판돈 하나와 관객이나 제약 하나가 받쳐요.</p>'}
    ${open.length ? `<details class="heat-more"><summary>열린 복선에 갈래 붙이기 (${open.length})</summary><ul class="plain">${open.map((f) => `<li class="heat-stake"><span>${esc(f.description)} <span class="small">${f.planted_ep}화</span></span><span class="row">${kinds.map(([k, t]) => `<button type="button" class="btn small" data-action="heatKind" data-arg="${esc(f.id)}:${k}" title="${esc(HEAT_KIND_WHY[k])}">${t}</button>`).join('')}</span></li>`).join('')}</ul></details>` : ''}
    ${eps.length ? `<div class="heat-add">
      <div class="field"><label for="heat-new-d">새로 심을 것</label><input id="heat-new-d" type="text" data-local="heatNewD" value="${esc(S.heatNewD)}" placeholder="예: 단톡방에 올라갈 수 있는 사진"></div>
      <div class="field"><label for="heat-new-ep">심는 화</label><select id="heat-new-ep" data-local="heatNewEp">${eps.map((n) => `<option value="${n}"${String(n) === String(S.heatNewEp) ? ' selected' : ''}>${n}화</option>`).join('')}</select></div>
      <div class="field"><label for="heat-new-kind">갈래</label><select id="heat-new-kind" data-local="heatNewKind">${kinds.map(([k, t]) => `<option value="${k}"${k === S.heatNewKind ? ' selected' : ''}>${t}</option>`).join('')}</select></div>
      <button type="button" class="btn small" data-action="heatAddStake">더하기</button></div>` : '<p class="small">화별 플롯을 만들면 그 화에 판돈을 심을 수 있어요.</p>'}</div>`;
}

/** 단편 플롯 화면의 열 계획 카드. 장편이나 구조가 없으면 비운다 */
function heatCard(p) {
  if (p.meta.form === 'serial' || !(p.arc || []).length) return '';
  const steps = heatPlan(p);
  if (!steps.length) {
    return `<section class="card heat-card" aria-label="열 계획"><div class="between"><h2>열 계획</h2>
      <button type="button" class="btn small" data-action="heatStart">직접 적기</button></div>
      <p class="small">기승전결이 무슨 일이 일어나는지 정한다면, 열 계획은 열(긴장과 보상)을 언제 아끼고 언제 쓸지 정해요. 화마다 열을 적으면 정점 앞뒤에 판돈 · 관객 · 결과가 있는지 알려 줘요.</p></section>`;
  }
  const warns = heatWarnings(p);
  const warned = new Set(warns.map((w) => w.ep));
  const actual = heatActual(p);
  const sel = steps.some((s) => s.ep === S.heatSel) ? S.heatSel : 0;
  const t = p.heat_turn || {};
  return `<section class="card heat-card" aria-label="열 계획"><div class="between"><h2>열 계획</h2>
      <button type="button" class="btn small" data-action="heatClear">열 계획 지우기</button></div>
    ${input('열 원칙', 'heat_rule', { placeholder: '예: 앞 절반은 열 없이 쌓고, 큰 정점은 전 구간 끝 두 화' })}
    <div class="heat-bars" role="group" aria-label="화별 열 막대. 누르면 그 화를 고쳐요">${steps.map((s) => heatBar(s, actual[s.ep], s.ep === sel, warned.has(s.ep))).join('')}</div>
    <p class="small heat-legend"><span class="heat-key peak"></span>터뜨리기 <span class="heat-key build"></span>그 밖 <span class="heat-key real"></span>쓴 화의 큐 긴장(참고값)</p>
    ${sel ? heatEditor(p, sel) : '<p class="small">막대를 누르면 그 화의 열과 몫을 고쳐요.</p>'}
    ${warns.length ? `<div class="note warn" role="status"><strong>확인할 것 ${warns.length}</strong><ul class="plain">${warns.map((w) => `<li>${esc(w.text)}</li>`).join('')}</ul></div>` : ''}
    ${heatStakes(p)}
    <div class="heat-turn"><span class="heat-h">뒤집힘</span>
      <p class="small">반격을 심고, 큰 정점 전에 들키게 해요. 들킨 대가로 상대가 새 판돈을 쥐어요.${t.plant_ep > 0 && t.fail_ep < t.plant_ep ? ' 들키는 화가 심는 화보다 앞이면 저장할 때 지워져요.' : ''}</p>
      <div class="grid-2">${input('반격을 심는 화', 'heat_turn.plant_ep', { type: 'number', min: 0, zeroBlank: true, placeholder: '없음' })}${input('들키는 화', 'heat_turn.fail_ep', { type: 'number', min: 0, zeroBlank: true, placeholder: '없음' })}</div>
      ${input('들킨 대가로 상대가 쥐는 것', 'heat_turn.gain', { placeholder: '예: 지운 줄 알았던 녹음의 백업' })}</div></section>`;
}

/** 'AI로 구조 만들기 · 다시 제안'에 열 계획도 함께 받을지 (Settings.heat_plan). 단편만 */
function heatPlanToggle(cls) {
  const on = !!(P().settings || {}).heat_plan;
  return `<label class="${cls} row small heat-toggle"><input type="checkbox" data-bind="settings.heat_plan" data-kind="bool"${on ? ' checked' : ''}><span>구조를 제안받을 때 열 계획(화별 열 · 판돈 · 뒤집힘)도 함께 받기</span></label>`;
}

/** AI 구조 제안 카드 안 열 계획 미리보기. 고르면 heatApply 가 넣는다 */
function heatProposalPart(h) {
  const t = h.heat_turn || {};
  return `<div class="heat-proposal"><span class="heat-h">열 계획 <span class="chip ai">함께 바뀜</span></span>
    ${h.heat_rule ? `<p class="small">${esc(h.heat_rule)}</p>` : ''}
    <div class="heat-bars" aria-hidden="true">${h.heat.map((s) => heatBar(s, null, false, false, true)).join('')}</div>
    <ul class="plain small">${h.heat.filter((s) => s.role === 'peak').map((s) => `<li>${s.ep}화 터뜨리기 · 열 ${s.level}${s.kind ? ` · ${esc(s.kind)}` : ''}</li>`).join('')}
      ${(h.stakes || []).map((f) => `<li>${HEAT_KINDS[f.kind] || f.kind} · ${esc(f.description)} (${f.planted_ep}화에 심음)</li>`).join('')}
      ${t.plant_ep > 0 ? `<li>뒤집힘 · ${t.plant_ep}화에 심고 ${t.fail_ep}화에 들킴${t.gain ? ` · ${esc(t.gain)}` : ''}</li>` : ''}</ul>
    <p class="small">${P().heat && P().heat.length ? '이 구조로 바꾸면 지금 열 계획도 이것으로 바뀌어요. ' : ''}판돈 · 관객은 복선 목록에 새로 더해요.</p></div>`;
}

/** 열 계획 제안 넣기 (pipeline.apply_heat_plan 과 같다) */
function heatApply(p, h) {
  p.heat = h.heat;
  p.heat_rule = h.heat_rule || '';
  p.heat_turn = h.heat_turn || { plant_ep: 0, fail_ep: 0, gain: '' };
  const have = new Set((p.foreshadows || []).map((f) => f.id));
  p.foreshadows = [...(p.foreshadows || []), ...(h.stakes || []).filter((f) => !have.has(f.id))];
}

function heatSet(n, key, value) {
  const s = (P().heat || []).find((x) => x.ep === Number(n));
  if (!s) return;
  s[key] = value;
  if (key === 'role' && value !== 'peak') s.kind = '';
  markDirty();
  S.focusTarget = `#app .heat-edit [data-action="${key === 'level' ? 'heatLevel' : 'heatRole'}"][data-arg="${n}:${value}"]`;
  render();
}

async function heatForeshadow(id, body) {
  await run('복선을 고치는 중', async () => {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/foreshadows/${enc(id)}`, body);
  });
}

Object.assign(actions, {
  heatStart() {
    P().heat = heatDefault(P());
    S.heatSel = 0;
    markDirty();
    S.focusTarget = '#app .heat-bars .heat-col';
    render();
  },
  heatClear() {
    Object.assign(P(), { heat: [], heat_rule: '', heat_turn: { plant_ep: 0, fail_ep: 0, gain: '' } });
    S.heatSel = 0;
    markDirty();
    S.focusTarget = '#app [data-action="heatStart"]';
    render();
  },
  heatPick(n) {
    S.heatSel = S.heatSel === Number(n) ? 0 : Number(n);
    S.focusTarget = `#app .heat-col[data-arg="${n}"]`;
    render();
  },
  heatLevel(arg) { const [n, v] = arg.split(':'); heatSet(n, 'level', Number(v)); },
  heatRole(arg) { const [n, v] = arg.split(':'); heatSet(n, 'role', v); },
  async heatKind(arg) {
    const k = arg.lastIndexOf(':');
    await heatForeshadow(arg.slice(0, k), { kind: arg.slice(k + 1) });
  },
  async heatPublic(id) {
    const f = (P().foreshadows || []).find((x) => x.id === id);
    if (f) await heatForeshadow(id, { public: !f.public });
  },
  async heatAddStake() {
    const d = (S.heatNewD || '').trim();
    if (!d) { toast('새로 심을 것을 적어 주세요'); return; }
    const first = (P().episodes || [])[0];
    const ep = Number(S.heatNewEp) || (first ? first.plot.number : 1);
    await run('복선을 더하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/foreshadows`, { description: d, episode: ep, kind: S.heatNewKind || 'stake' });
      S.heatNewD = '';
    });
  },
});
