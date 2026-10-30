/* 6단계 상태 승인 (한 화 흐름 집필 → 검수 → 상태 승인의 마지막 단계, flow.js): 왼쪽 본문 · 오른쪽 변경안(직접 정할 것 · 요약 · 그대로 반영할 것 · 관계 계산),
   변경안 고르기 · 반영, 관계 계산 미리보기, 관계 표시(숫자/말). app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';


/** 체크한 항목만 남긴 변경안. 반영과 관계 미리 보기에 같이 쓴다. */
function pickedDelta(n) {
  const d = S.deltas[n];
  const pick = (prefix, list) => list.filter((_, i) => S.picks[prefix + i]);
  // 화면에서 고친 글은 앞뒤 공백을 지우고, 비운 사실 · 알게 된 정보는 뺀다 (빈 감정은 서버가 지금 감정을 그대로 둔다)
  const clean = (list) => list.map((x) => x.trim()).filter(Boolean);
  return {
    ...d,
    character_updates: pick('c', d.character_updates).map((u) => ({ ...u, emotional_state: u.emotional_state.trim(), knows: clean(u.knows) })),
    events: pick('e', d.events),
    secrets_added: pick('s', d.secrets_added),
    relationship_updates: pick('r', d.relationship_updates),
    new_facts: clean(pick('f', d.new_facts)),
    foreshadow_planted: pick('p', d.foreshadow_planted),
    foreshadow_resolved: pick('x', d.foreshadow_resolved),
    new_characters: pick('n', d.new_characters || []),
    new_places: pick('l', d.new_places || []),
    foreshadow_clues: pick('q', d.foreshadow_clues || []),
    deadlines_added: pick('k', d.deadlines_added || []),
    deadlines_done: pick('o', d.deadlines_done || []),
    setting_changes: pick('t', d.setting_changes || []),
    cast_added: pick('a', d.cast_added || []),
    address_changes: pick('h', d.address_changes || []),
  };
}

/** 화 플롯 글 (서버 elements.plot_text 와 같은 칸). */
const plotText = (pl) => [pl.title, pl.summary, ...pl.events, pl.emotional_shift, pl.ending_hook, ...(pl.foreshadow_plant || [])].join('\n');

/** 이 화 플롯에 나오는 장소 후보 (AI 플롯이 지은 새 장소). 확정하면 인과율 장소로 등록된다 (pipeline.confirm_plot). */
function placeCandNotes(e) {
  const text = plotText(e.plot);
  const cands = (P().place_candidates || []).filter((x) => [x.name, ...(x.aliases || [])].some((t) => t && text.includes(t)));
  return cands.length ? `<div class="field"><span class="label">새 장소</span>${cands.map((x) => `<div class="note info"><strong>새 장소 제안 · ${esc(x.name)}</strong>${x.kind ? ` <span class="small">${esc(x.kind)}</span>` : ''}${x.description ? `<br>${esc(x.description)}` : ''}
    <br><span class="small">AI 플롯이 지은 장소예요. 이 화를 확정하면 인과율에 장소로 등록돼요. 빼려면 플롯에서 이름을 지우세요.</span></div>`).join('')}</div>` : '';
}

/** 새 장소 한 줄: 이름, 종류, 다른 이름, 설명. 상태 승인 · 다시 맞추기 화면이 같이 쓴다. */
const placeLabel = (x) => `<strong>${esc(x.name)}</strong>${x.kind ? ` <span class="small">${esc(x.kind)}</span>` : ''}${(x.aliases || []).length ? ` <span class="small">다른 이름: ${x.aliases.map(esc).join(', ')}</span>` : ''}${x.description ? `<br>${esc(x.description)}` : ''}`;

let previewTimer = null;
/** 고른 변경안으로 관계를 다시 계산해 미리 보기만 바꾼다 (저장 안 함). */
function refreshPreview(n) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    if (!S.deltas[n]) return;
    try {
      S.preview = { n, ...(await api('POST', `/projects/${enc(S.name)}/episodes/${n}/preview`, pickedDelta(n))) };
    } catch (e) {
      S.preview = { n, error: e.message };
    }
    const box = $('#rel-preview');
    if (box) box.innerHTML = relationLines(S.preview, true);
  }, 250);
}

/** 상태 변경안 항목 체크 키 ('c0', 'e1' …). 설정 제안 키('sc0', 'sf:logline')와 섞이지 않게 센다. */
const DELTA_PICK = /^[cesrfpxnqlkotah]\d+$/;
/** 상태 변경안에서 하나씩 골라 반영하는 목록 (StateDelta 의 목록 칸 중 warnings 를 뺀 것, tests/test_delta_count.py 가 맞춰 본다) */
const DELTA_LISTS = ['character_updates', 'events', 'secrets_added', 'relationship_updates', 'new_facts', 'foreshadow_planted', 'foreshadow_resolved', 'foreshadow_clues', 'new_characters', 'new_places', 'deadlines_added', 'deadlines_done', 'setting_changes', 'cast_added', 'address_changes'];
/** 변경안 항목 수. 상태 승인 화면의 'n건 중'과 반영 확인창의 '0건'이 같은 셈을 쓴다 */
const deltaCount = (d) => DELTA_LISTS.reduce((s, k) => s + (d[k] || []).length, 0);
const deltaPicked = () => Object.entries(S.picks).filter(([k, v]) => v && DELTA_PICK.test(k)).length;

/** source: 변경안을 어디서 받았나 ('chat' 이면 채팅 앱에서 가져온 JSON). 상태 승인 화면 설명에 쓴다 */
function setDelta(n, d, source = 'ai') {
  S.deltas[n] = d;
  S.deltaBase[n] = ep(n) ? ep(n).text : '';
  // S.picks 는 설정 제안(sc · sr · sf: 키)과 같이 쓴다. 변경안 키만 지워 설정 화면의 체크를 남긴다
  for (const k of Object.keys(S.picks)) if (DELTA_PICK.test(k)) delete S.picks[k];
  S.preview = null;
  S.rvOpen = {};  // 펼친 인물 칸과 본문 근거는 닫는다
  S.rvQuote = null;
  // 설정에도 이번 새 인물에도 없는 id 의 상태는 기본으로 빼 둔다. 반영하면 누구의 것도 아닌 상태가 남는다
  const known = new Set([...P().characters.map((c) => c.id), ...(d.new_characters || []).map((c) => c.id)]);
  d.character_updates.forEach((u, i) => { S.picks['c' + i] = known.has(u.character_id); });
  d.events.forEach((_, i) => { S.picks['e' + i] = true; });
  d.secrets_added.forEach((_, i) => { S.picks['s' + i] = true; });
  d.relationship_updates.forEach((_, i) => { S.picks['r' + i] = true; });
  d.new_facts.forEach((_, i) => { S.picks['f' + i] = true; });
  d.foreshadow_planted.forEach((_, i) => { S.picks['p' + i] = true; });
  d.foreshadow_resolved.forEach((id, i) => { S.picks['x' + i] = P().foreshadows.some((f) => f.id === id); });
  (d.new_characters || []).forEach((_, i) => { S.picks['n' + i] = true; });
  (d.new_places || []).forEach((_, i) => { S.picks['l' + i] = true; });
  (d.foreshadow_clues || []).forEach((_, i) => { S.picks['q' + i] = true; });
  (d.deadlines_added || []).forEach((_, i) => { S.picks['k' + i] = true; });
  (d.deadlines_done || []).forEach((id, i) => { S.picks['o' + i] = P().timeline.deadlines.some((x) => x.id === id) || (d.deadlines_added || []).some((x) => x.id === id); });
  (d.setting_changes || []).forEach((_, i) => { S.picks['t' + i] = false; });  // 인물 설정은 작가가 직접 골라야 바뀐다
  (d.cast_added || []).forEach((_, i) => { S.picks['a' + i] = true; });  // 본문에 나온 인물은 기본으로 그 화 등장 인물에 붙인다
  (d.address_changes || []).forEach((_, i) => { S.picks['h' + i] = false; });  // 호칭 · 말씨도 작가가 직접 골라야 바뀐다
  // 받은 그대로의 요약과 체크. 다시 만들 때 고친 것을 버리는지 묻는다 (기본으로 뺀 항목은 고친 것이 아니다)
  S.deltaOrig[n] = { summary: d.summary, picks: Object.fromEntries(Object.entries(S.picks).filter(([k]) => DELTA_PICK.test(k))), source, delta: structuredClone(d) };
}

/** 사건 종류 (schema.EventKind). 수동보정은 작가가 관계를 직접 고칠 때만 쓰고 반영에서 빠져 고르지 않는다 (tests/test_delta_count.py 가 맞춰 본다) */
const EVENT_KINDS = ['도움', '희생', '약속이행', '칭찬', '진심고백', '사과', '공동경험', '거짓말발각', '배신', '모욕', '위협', '거절', '경쟁승리', '비밀폭로'];

/** 상태 승인 화면에서 고칠 수 있는 칸만 모은 모양. 받은 그대로(S.deltaOrig[n].delta)와 비교해 다시 만들기 전에 묻는다 */
const deltaEditable = (d) => JSON.stringify([
  d.events.map((e) => [e.kind, e.intensity]), d.new_facts,
  d.character_updates.map((u) => [u.emotional_state, u.attire, u.knows]),
  d.time ? [d.time.day || 0, d.time.part || '', d.time.label || ''] : [0, '', ''],  // tlDeltaCard 가 빈 시점을 채워도 고친 것이 아니다
  (d.setting_changes || []).map((x) => x.value),
]);
const deltaEdited = (n) => !!(S.deltas[n] && S.deltaOrig[n] && S.deltaOrig[n].delta) && deltaEditable(S.deltas[n]) !== deltaEditable(S.deltaOrig[n].delta);

/** 항목 하나의 고칠 수 있는 값. 키: e0 사건 종류 · 강도, f0 사실, em0 감정, at0 차림, kn0.1 알게 된 정보 */
function editValue(d, key) {
  const [, k, i, j] = key.match(/^([a-z]+)(\d+)(?:\.(\d+))?$/);
  const ev = d.events[i];
  const u = d.character_updates[i] || {};
  return JSON.stringify({ e: ev && [ev.kind, ev.intensity], f: d.new_facts[i], em: u.emotional_state, at: u.attire, kn: (u.knows || [])[j] }[k]);
}
const itemEdited = (n, key) => !!(S.deltaOrig[n] && S.deltaOrig[n].delta) && editValue(S.deltas[n], key) !== editValue(S.deltaOrig[n].delta, key);
/** '고침' 표시. 입력 중에는 다시 그리지 않으니 showEdited 가 그 자리에서 켜고 끈다 */
const editMark = (n, key) => `<span class="chip warn" data-edited="${key}"${itemEdited(n, key) ? '' : ' style="display:none"'}>고침</span>`;
function showEdited(n, key) {
  const m = document.querySelector(`#app [data-edited="${CSS.escape(key)}"]`);
  if (m) m.style.display = itemEdited(n, key) ? '' : 'none';
}
const kindStyle = (kind) => GOOD_EVENTS.includes(kind) ? 'background:var(--green-soft);color:var(--green)' : 'background:var(--red-soft);color:var(--red)';

/** 승인한 값이 쌓이는 도구로 가는 링크. 카드 아래 오른쪽에 둔다 */
const toolLink = (page, label) => `<a class="small" href="${base()}/${page}">${label}에서 보기 →</a>`;
const toolFoot = (...links) => `<div class="row" style="justify-content:flex-end;gap:12px;margin-top:4px">${links.filter(Boolean).join('')}</div>`;
/** 다른 파일이 그린 카드(빈 글이면 그리지 않음) 아래에 링크를 붙인다 */
const withFoot = (html, ...links) => html ? html.replace(/<\/section>\s*$/, `${toolFoot(...links)}</section>`) : '';
/** 상태창 수치를 쓰는 작품이면 상태창 화면 링크 (statwin.js 의 켜짐 규칙: 수치가 하나라도 있음) */
const statLink = (updates) => (updates.some((u) => (u.stats || []).length) || P().states.some((s) => (s.stats || []).length)) ? toolLink('statwin', '상태창 수치') : '';

// ----- 6. 상태 승인 (한 화 흐름의 마지막 단계) -----
// 왼쪽은 이 화 본문(읽기 전용, 변경안의 근거 문장에 밑줄), 오른쪽은 변경안: 직접 정할 것 → 요약 → 그대로 반영할 것(갈래마다 접힘) → 관계 계산.
// 901px 아래는 오른쪽 칸만 먼저 보이고 본문은 접어 둔다. 반영 버튼은 넓은 폭은 머리, 좁은 폭은 아래 반영 줄

/** 본문을 옆에 두는 폭 (901px 이상). 좁으면 근거 문장은 오른쪽 칸 위 근거 카드로 보인다 */
const rvWide = () => !(typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(max-width: 900px)').matches);

/** 경고를 인물 줄에 붙인다. names: character_updates 순서의 인물 이름. 경고 글이 인물 이름으로 시작하면 그 인물 줄(by[i]),
    아니면 '본문 점검'(rest). 상태창 · 이동 시간 경고는 '이름 상태창:' · '이름이 너무 빨리'로 시작한다 (statwin · travel). 값은 경고 번호 */
function rvWarnSplit(warnings, names) {
  const order = names.map((nm, i) => [String(nm || '').trim(), i]).filter(([nm]) => nm.length >= 2).sort((a, b) => b[0].length - a[0].length);
  const by = {};
  const rest = [];
  (warnings || []).forEach((w, k) => {
    const hit = order.find(([nm]) => String(w).trim().startsWith(nm));
    if (hit) (by[hit[1]] = by[hit[1]] || []).push(k);
    else rest.push(k);
  });
  return { by, rest };
}

/** 경고 한 줄과 본문에서 그 문장 고르기 · AI에게 고치기 (passage.js warnPick, k 는 d.warnings 번호) */
function rvWarnLine(n, w, k) {
  const q = editableEp(ep(n)) && warnQuote(w, textNow(n));
  return `<div class="rv-warnline"><span>${esc(w)}</span>${q ? `<span class="row" style="gap:6px"><button type="button" class="btn small" data-action="warnPick" data-arg="${n}:${k}">이 문장 고르기</button><button type="button" class="btn small" data-action="warnPick" data-arg="${n}:${k}:ask">AI에게 고치기</button></span>` : ''}</div>`;
}

/** 갈래 고른 수 '고른/모두'. keys: 체크 키 목록 ('c0', 'e1' …) */
const rvKeyCount = (keys) => `${keys.filter((k) => S.picks[k]).length}/${keys.length}`;

/** 머리 ⋯ 메뉴: 다시 만들기 · 채팅 앱 지시서 · 버리기 */
function rvMenu(n) {
  const b = jobBtn('state', n, '변경안 다시 만들기');
  const dots = '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="9" r="1.6"></circle><circle cx="9" cy="9" r="1.6"></circle><circle cx="14" cy="9" r="1.6"></circle></svg>';
  return menuBtn('review', dots, () => `<button type="button" class="pop-item" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}<span class="small">AI 비용이 들어요</span></button>
    <a class="pop-item" href="${base()}/brief/${n}" data-action="openStateBrief" data-arg="${n}">상태 승인 지시서 열기</a>
    <div class="pop-sep" role="separator"></div><div class="pop-sec pop-danger"><button type="button" class="pop-item" data-action="dropDelta" data-arg="${n}">변경안 버리기</button></div>`, { cls: 'btn icon-btn', aria: `${n}화 변경안 더보기` });
}

function viewReview(n) {
  const e = ep(n);
  if (!e) return header('6단계', '상태 승인', '') + noEpisode();
  const top = (desc, right = '') => `<header class="page-head"><div class="row" style="gap:12px">${epNav('review', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${flowEyebrow(n)}</div><h1 style="font-size:1.5rem">${n}화 ${esc(e.plot.title)}</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>${flowBar(n, 'review')}${autoLockNote()}${desc ? `<p class="desc">${desc}</p>` : ''}`;

  if (e.status === 'finalized') {
    const h = [...P().history].reverse().find((d) => d.episode === n);
    const canRevert = P().snapshots.some((s) => s.episode === n - 1);
    // 반영 취소는 n화와 그 뒤 반영한 화를 모두 되돌린다. 되돌리는 범위를 버튼에 적는다 (revertFrom 과 같은 셈)
    const undo = P().episodes.filter((x) => x.status === 'finalized' && x.plot.number >= n).map((x) => x.plot.number);
    return top('이 화는 상태 반영이 끝났어요. 반영된 내용이에요.', `<button class="btn" data-action="branchOpen" data-arg="${n}" title="이 작품은 그대로 두고, 사본에서 ${n}화부터 다른 전개를 써요">${n}화부터 갈래 만들기</button>${canRevert ? `<button class="btn danger" data-action="revertFrom" data-arg="${n}">${rangeText(undo)}화 반영 취소</button>` : ''}${nextStepBtn()}`) + restateCard(n) + (h ? historyView(h) : '<div class="note plain">반영 기록이 없어요.</div>');
  }
  if (e.status !== 'written') {
    return top('') + `<div class="card empty"><p>${n}화 본문이 아직 없어요. 본문을 쓴 뒤 상태를 정리해요.</p><a class="btn primary" href="${base()}/write/${n}">${n}화 집필로</a></div>`;
  }
  const d = S.deltas[n];
  const ar = S.auto && S.auto.run;
  if (!d && ar && ar.status === 'review' && ar.ep === n && ar.pending) {
    // 자동 집필이 이미 만든 변경안이 있다. 다시 만들면 AI 비용이 또 든다
    return top('자동 집필이 이 화에서 멈추고 만든 변경안이 있어요. 불러와 고른 항목만 반영한 뒤 자동 집필에서 이어 가세요.') +
      `<div class="card"><div class="row"><button class="btn primary" data-action="autoOpenReview">자동 집필 변경안 불러오기</button><a class="btn" href="${base()}/auto">자동 집필로</a></div></div>`;
  }
  if (!d) {
    return top('AI가 본문에서 인물 상태, 관계, 확정 사실, 복선을 뽑아 변경안을 만들어요. 승인한 항목만 데이터에 반영돼요.') +
      `${ep(n + 1) ? `<div class="note info">${n}화 상태를 반영해야 ${n + 1}화를 쓸 수 있어요.</div>` : ''}<div class="cols"><section class="card col"><h2>AI로 만들기</h2><p class="desc">${n}화 본문을 읽고 변경안을 만들어요.${S.config && S.config.stages ? ` <span class="small">모델: ${esc(projectStage('state').model)}</span>` : ''}</p><div>${((b) => `<button class="btn primary" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 만들기'))}</div></section>
       <section class="card col"><h2>채팅 앱에서 받은 JSON</h2><p class="desc">상태 승인 지시서를 채팅 앱에 붙여 넣고 받은 JSON을 가져와요.</p><div><a class="btn" href="${base()}/brief/${n}" data-action="openStateBrief" data-arg="${n}">상태 승인 지시서 열기</a></div></section></div>`;
  }

  const p = P();
  const remake = ((b) => `<button class="btn small" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 다시 만들기'));
  const stale = textUnsaved(n)
    ? `<section class="note warn">${n}화 본문에 저장하지 않은 수정이 있어요. 반영해도 그 수정은 저장되지 않아요. 변경안을 다시 만들면 본문을 먼저 저장해요. ${remake} <a href="${base()}/write/${n}">본문으로</a></section>`
    : S.deltaBase[n] !== undefined && S.deltaBase[n] !== e.text
      ? `<section class="note warn">이 변경안을 만든 뒤 본문을 고쳤어요 (검수에서 고친 문장도 들어가요). 고친 내용이 상태에 영향을 준다면 변경안을 다시 만드세요. ${remake}</section>` : '';
  // 열린 검수 지적이 남았거나 검수하지 않았으면 반영 전에 알린다 (검수 뒤 본문을 고쳤으면 지난 결과라고 밝힌다). 막지는 않는다
  const cs = checkState(e);
  const issues = cs.open
    ? `<section class="note warn">열린 검수 지적 ${cs.open}곳이 남아 있어요${cs.stale ? ' (검수 뒤 본문을 고쳤어요)' : ''}. <a href="${base()}/check/${n}">검수 단계에서 보기</a></section>`
    : !cs.checked && !jobFor('check', n) ? `<section class="note plain">${n}화는 아직 검수하지 않았어요. 반영해도 되지만, 앞 화와 어긋나는 곳이 있는지 <a href="${base()}/check/${n}">검수</a>에서 먼저 볼 수 있어요.</section>` : '';
  if (!S.preview || S.preview.n !== n) refreshPreview(n);
  const total = deltaCount(d);
  const picked = deltaPicked();
  const box = (key, label) => `<input type="checkbox" id="pk-${key}" data-pick="${key}"${label ? ` aria-label="${esc(label)}"` : ''}${S.picks[key] ? ' checked' : ''}>`;
  const orig = (S.deltaOrig[n] && S.deltaOrig[n].delta) || d;
  // 고칠 수 있는 칸: data-dedit 입력이 S.deltas[n] 의 data-dpath 칸을 바로 고친다 (아래 input 처리)
  const edit = (path, key) => `data-dedit="${n}" data-dpath="${path}" data-dmark="${key}"`;
  const diff = (before, after) => before && before !== after
    ? `<div class="row"><span class="before">${esc(before)}</span><span class="small">→</span><span class="after">${esc(after)}</span></div>`
    : `<div class="row"><span class="after">${esc(after)}</span></div>`;
  const chip = (k, v) => `<span class="rv-chip"><span class="k">${k}</span> ${v}</span>`;
  const warns = rvWarnSplit(d.warnings, d.character_updates.map((u) => charName(u.character_id)));
  const unknownChar = (u) => !p.characters.some((c) => c.id === u.character_id) && !(d.new_characters || []).some((c) => c.id === u.character_id);

  // 인물 상태: 바뀐 칸을 한 줄 칩으로 접어 보이고, '고치기'를 누르면 그 자리에서 칸을 편다. 붙은 경고는 줄 아래
  const charRow = (u, i) => {
    const cur = p.states.find((s) => s.character_id === u.character_id) || {};
    const ou = orig.character_updates[i] || u;
    const name = charName(u.character_id);
    const was = (now) => now ? `<div class="row"><span class="before">${esc(now)}</span><span class="small">→</span></div>` : '';
    // 이미 아는 정보는 반영해도 그대로라 보이지 않는다. 받은 글로 거르고, 고친 칸은 u.knows 의 같은 자리를 바꾼다
    const knowIdx = u.knows.map((k, j) => [k, j]).filter(([k, j]) => !(cur.knows || []).includes((ou.knows || [])[j] ?? k));
    const stats = (u.stats || []).filter((s) => s.name && s.name.trim());
    const open = !!(S.rvOpen && S.rvOpen[`${n}:c${i}`]);
    const fields = [['목표', 'current_goal'], ['위치', 'location'], ['메모', 'notes']].filter(([, f]) => u[f]);
    let inner;
    if (open) {
      // 감정 · 알게 된 정보 · 차림은 AI 가 틀리게 적었으면 여기서 고쳐 반영한다. 받은 변경안에 있던 칸만 보인다
      const emotion = ou.emotional_state || u.emotional_state ? `<div class="small"><label for="em-${i}">감정</label> ${editMark(n, 'em' + i)}</div>${cur.emotional_state !== u.emotional_state ? was(cur.emotional_state) : ''}<input id="em-${i}" ${edit(`character_updates.${i}.emotional_state`, 'em' + i)} value="${esc(u.emotional_state)}" placeholder="비우면 지금 감정을 그대로 둬요">` : '';
      const rows = fields.map(([k, f]) => `<div class="small">${k}</div>${diff(cur[f], u[f])}`).join('');
      const knows = knowIdx.map(([k, j]) => `<div class="row" style="gap:6px;flex-wrap:nowrap"><span class="after">+</span><input id="kn-${i}-${j}" aria-label="${esc(name)}이 알게 된 정보 ${j + 1}" ${edit(`character_updates.${i}.knows.${j}`, `kn${i}.${j}`)} value="${esc(k)}" placeholder="비우면 빼요" style="flex:1;min-width:0">${editMark(n, `kn${i}.${j}`)}</div>`).join('');
      const attire = u.attire || ou.attire ? `<div class="small"><label for="at-${i}">차림</label> ${editMark(n, 'at' + i)}</div>${cur.attire !== u.attire ? was(cur.attire) : ''}<input id="at-${i}" data-attire="${i}" data-attire-ep="${n}" data-dmark="at${i}" value="${esc(u.attire)}">` : '';
      inner = `<div class="rv-editor" id="rv-ed-c${i}">${emotion}${rows}${attire}${swDeltaRows(u, cur)}${knows ? `<div class="small">알게 된 정보</div>${knows}` : ''}</div>`;
    } else {
      const now = Object.fromEntries((cur.stats || []).map((s) => [s.name, s.value]));
      const statText = stats.slice(0, 2).map((s) => {
        const b = now[s.name.trim()] || '';
        const a = s.value.trim() ? swResolve(b, s.value) : '지움';
        return `${esc(s.name)} ${b ? `${esc(b)} → ` : ''}${esc(a)}`;
      }).join(' · ') + (stats.length > 2 ? ` 외 ${stats.length - 2}` : '');
      const chips = [
        u.emotional_state && chip('감정', `${cur.emotional_state && cur.emotional_state !== u.emotional_state ? `${esc(cur.emotional_state)} → ` : ''}${esc(u.emotional_state)}`),
        ...fields.map(([k, f]) => chip(k, `${cur[f] && cur[f] !== u[f] && f === 'location' ? `${esc(cur[f])} → ` : ''}${esc(u[f])}`)),
        u.attire && chip('차림', esc(u.attire)),
        stats.length && chip('상태창', statText),
        knowIdx.length && chip('알게 된', `+${knowIdx.length}`),
      ].filter(Boolean).join('');
      inner = `<div class="rv-chips">${chips || '<span class="small">바뀐 칸이 없어요</span>'}</div>`;
    }
    const edited = charEdited(n, i);
    const ws = (warns.by[i] || []).map((k) => rvWarnLine(n, d.warnings[k], k)).join('');
    return `<div class="change rv-char${open ? ' open' : ''}">${box('c' + i)}<div class="body"><div class="rv-row-head"><label for="pk-c${i}" class="rv-name">${esc(name)}${unknownChar(u) ? ' <span class="chip draft">설정에 없는 인물</span>' : ''}</label>${edited && !open ? '<span class="chip warn">고침</span>' : ''}
      <button type="button" class="btn small rv-edit" data-action="rvOpen" data-arg="${n}:c${i}" aria-expanded="${open}"${open ? ` aria-controls="rv-ed-c${i}"` : ''} aria-label="${esc(name)} 상태 ${open ? '접기' : '고치기'}">${open ? '접기' : '고치기'}</button></div>${inner}${ws ? `<div class="rv-warns" role="group" aria-label="${esc(name)} 경고">${ws}</div>` : ''}</div></div>`;
  };
  const charIdx = d.character_updates.map((_, i) => i);
  const decideChar = (i) => unknownChar(d.character_updates[i]) || !!warns.by[i];

  // 사건 종류 · 강도는 고를 수 있다. 관계 수치는 여전히 Canon 이 사건으로 계산한다
  const events = d.events.map((ev, i) => {
    const wit = ev.witnesses.length ? `목격: ${ev.witnesses.map(charName).map(esc).join(', ')}` : '';
    const sec = ev.reveals_secret ? `드러난 비밀: ${esc(secretLabel(ev.reveals_secret, d))}` : '';
    const kinds = EVENT_KINDS.includes(ev.kind) ? EVENT_KINDS : [ev.kind, ...EVENT_KINDS];
    const who = `${esc(charName(ev.actor))} → ${esc(charName(ev.target))}`;
    const sel = (id, label, path, opts, val, style = '') => `<select id="${id}" aria-label="${who} ${label}" ${edit(path, 'e' + i)} style="width:auto;font-size:0.8125rem;font-weight:700;padding:4px 8px;${style}">${opts.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(val) ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
    return `<div class="change">${box('e' + i)}<div class="body"><div class="rv-row-head"><label for="pk-e${i}" class="rv-name">${who}</label>${sel(`ek-${i}`, '사건 종류', `events.${i}.kind`, kinds.map((k) => [k, k]), ev.kind, kindStyle(ev.kind))}${sel(`ei-${i}`, '강도', `events.${i}.intensity`, [1, 2, 3].map((v) => [v, INTENSITY[v]]), ev.intensity)}${editMark(n, 'e' + i)}${rvQuoteBtn(n, ev.quote, `${charName(ev.actor)} → ${charName(ev.target)} ${ev.kind}`)}</div>
      ${wit || sec ? `<div class="small">${[wit, sec].filter(Boolean).join(' · ')}</div>` : ''}
      ${ev.quote ? `<div class="rv-quote">${quoted(ev.quote)}</div>` : ''}</div></div>`;
  }).join('');
  const newChars = (d.new_characters || []).map((c, i) => `<div class="change">${box('n' + i)}<div class="body"><div class="rv-row-head"><label for="pk-n${i}" class="rv-name">${esc(c.name)}</label><span class="chip confirmed">새 인물 · ${c.tier === 'minor' ? '단역' : '조연'}으로 추가</span><span class="small">${esc(c.id)} · ${esc(c.role)}</span></div><div class="small" style="font-size:0.8125rem;color:var(--text-2)">${esc(c.personality || c.appearance || c.goal)}${c.speech_style ? `<br>말투: ${esc(c.speech_style)}` : ''}</div></div></div>`).join('');
  // 플롯 등장 인물에 없지만 본문에 이름이 나오고 이 변경안이 다룬 인물 (cast.cast_to_add). 체크를 풀면 붙이지 않는다
  const castAdd = (d.cast_added || []).map((id, i) => `<div class="change">${box('a' + i)}<label for="pk-a${i}" style="font-size:0.8125rem;line-height:1.55"><strong>${esc(charName(id))}</strong> <span class="small">${n}화 등장 인물에 붙여요</span></label></div>`).join('');
  const castAddBox = castAdd ? `<h3>본문에 나와 등장 인물에 붙일 인물</h3><p class="small">플롯 등장 인물에는 없지만 본문에 이름이 나오고 이번 변경안이 상태나 관계 사건을 다룬 인물이에요. 붙이면 등장 화와 다음 기획에 잡혀요. 이름만 나온 회상이면 체크를 푸세요.</p>${castAdd}` : '';
  const newPlaces = (d.new_places || []).map((x, i) => `<div class="change">${box('l' + i)}<label for="pk-l${i}" style="font-size:0.8125rem;line-height:1.55">${placeLabel(x)}</label></div>`).join('');
  const secrets = d.secrets_added.map((x, i) => `<div class="change">${box('s' + i)}<label for="pk-s${i}" style="font-size:0.8125rem;line-height:1.55"><strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}<br><span class="small">모르는 인물: ${x.hidden_from.map(charName).map(esc).join(', ') || '없음'}</span></label></div>`).join('');
  const rels = d.relationship_updates.map((r, i) => {
    const cur = p.relationships.find((x) => (x.a === r.a && x.b === r.b) || (x.a === r.b && x.b === r.a));
    return `<div class="change">${box('r' + i)}<div class="body"><label for="pk-r${i}" style="font-size:0.875rem;font-weight:700">${esc(charName(r.a))} ↔ ${esc(charName(r.b))}</label>
      ${diff(cur && cur.type, r.type)}${r.description ? diff(cur && cur.description, r.description) : ''}</div></div>`;
  }).join('');
  const facts = d.new_facts.map((f, i) => `<div class="change">${box('f' + i, `확정 사실 ${i + 1} 반영`)}<div class="body"><div class="row" style="gap:6px;flex-wrap:nowrap"><input id="fv-${i}" aria-label="확정 사실 ${i + 1}" ${edit(`new_facts.${i}`, 'f' + i)} value="${esc(f)}" placeholder="비우면 빼요" style="flex:1;min-width:0;font-size:0.8125rem">${editMark(n, 'f' + i)}</div></div></div>`).join('');
  // 회수한다는 복선 id 를 모르면 '직접 정할 것'으로 (기본으로 빼 둔다, setDelta)
  const resolvedRow = (id, i) => {
    const f = p.foreshadows.find((x) => x.id === id);
    return `<div class="change">${box('x' + i)}<label for="pk-x${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip finalized">회수</span> ${esc(f ? f.description : id)} ${f ? `<span class="small">${f.planted_ep}화에 심음</span>` : '<span class="small">알 수 없는 복선 id 예요. 고르지 않으면 회수하지 않아요</span>'}</label></div>`;
  };
  const knownFs = (id) => p.foreshadows.some((x) => x.id === id);
  const fs = [
    ...d.foreshadow_planted.map((f, i) => `<div class="change">${box('p' + i)}<label for="pk-p${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip confirmed">심음</span> ${esc(f.description)} <span class="small">${esc(f.id)}</span></label></div>`),
    ...d.foreshadow_resolved.map((id, i) => (knownFs(id) ? resolvedRow(id, i) : '')),
    fsClueRows(d, box, n),
  ].join('');
  const castLink = toolLink('cast', '인물 · 관계도');

  // 직접 정할 것: AI 혼자 정하지 않는 것(설정 바꾸기 · 호칭 · 말씨 바뀜 · 새 인물 · 설정에 없는 인물 · 모르는 복선)과 경고가 붙은 인물, 인물에 붙지 않은 경고
  const decideRows = [
    charIdx.filter(decideChar).map((i) => charRow(d.character_updates[i], i)).join(''),
    scDeltaRows(n, d, box),
    addressDeltaRows(n, d, box),
    newChars,
    d.foreshadow_resolved.map((id, i) => (knownFs(id) ? '' : resolvedRow(id, i))).join(''),
    warns.rest.length ? `<div class="change rv-check"><span class="rv-bang" aria-hidden="true">!</span><div class="body"><div class="rv-row-head"><strong class="rv-name">본문 점검</strong><span class="small">반영과 따로, 본문을 고칠지 봐요</span></div>${warns.rest.map((k) => rvWarnLine(n, d.warnings[k], k)).join('')}</div></div>` : '',
  ].join('');
  const decideCount = charIdx.filter(decideChar).length + (d.setting_changes || []).length + (d.address_changes || []).length + (d.new_characters || []).length
    + d.foreshadow_resolved.filter((id) => !knownFs(id)).length + (warns.rest.length ? 1 : 0);
  const decide = decideRows ? `<section class="card rv-card rv-decide" aria-labelledby="rv-decide-h"><div class="rv-card-head"><h2 id="rv-decide-h">직접 정할 것 <span class="chip warn">${decideCount}</span></h2><span class="small">AI가 혼자 정하지 않는 것과 경고가 붙은 것이에요</span></div>${decideRows}</section>` : '';

  const sum = `<section class="card rv-card"><div class="rv-card-head"><h2><label for="dsum">${n}화 요약</label></h2><span class="small"><span id="dsum-count">${d.summary.length.toLocaleString()}</span>자 · 다음 화를 쓸 때 이 요약이 들어가요</span></div>
      <textarea id="dsum" rows="4" data-autogrow data-delta-summary="${n}">${esc(d.summary)}</textarea></section>`;

  // 그대로 반영할 것: 갈래마다 접어 두고 한 줄 요약과 고른 수만 보인다. 펴면 지금과 같은 칸에서 고치고 뺀다
  const keys = (letter, list, keep = () => true) => (list || []).map((_, i) => letter + i).filter((_, i) => keep(i));
  const short = (s, k = 18) => (s.length > k ? `${s.slice(0, k)}…` : s);
  const tl = tlDeltaCard(n, d, box);
  const groups = [
    ['chars', '인물 상태', charIdx.filter((i) => !decideChar(i)).map((i) => charRow(d.character_updates[i], i)).join('') + castAddBox,
      [...keys('c', d.character_updates, (i) => !decideChar(i)), ...keys('a', d.cast_added)],
      charIdx.filter((i) => !decideChar(i)).map((i) => charName(d.character_updates[i].character_id)).join(', '), toolFoot(castLink, statLink(d.character_updates))],
    ['rel', '관계 사건', events, keys('e', d.events), d.events.slice(0, 2).map((ev) => `${charName(ev.actor)} → ${charName(ev.target)} ${ev.kind}`).join(' · '), toolFoot(castLink)],
    ['secrets', '비밀 · 관계 유형', `${secrets ? `<h3>새로 생긴 비밀</h3>${secrets}` : ''}${rels ? `<h3>관계 유형 · 설명 변경</h3>${rels}` : ''}`, [...keys('s', d.secrets_added), ...keys('r', d.relationship_updates)],
      [...d.secrets_added.map((x) => short(x.content)), ...d.relationship_updates.map((r) => `${charName(r.a)} ↔ ${charName(r.b)}`)].join(' · '), toolFoot(castLink)],
    ['facts', '확정 사실', facts, keys('f', d.new_facts), d.new_facts.map((f) => short(f)).join(' · '), ''],
    ['fs', '복선', fs, [...keys('p', d.foreshadow_planted), ...keys('x', d.foreshadow_resolved, (i) => knownFs(d.foreshadow_resolved[i])), ...keys('q', d.foreshadow_clues)],
      [...d.foreshadow_planted.map((f) => `심음 ${short(f.description, 12)}`), ...d.foreshadow_resolved.filter(knownFs).map((id) => `회수 ${short(p.foreshadows.find((x) => x.id === id).description, 12)}`)].join(' · '), toolFoot(toolLink('foreshadow', '복선 센터'))],
    ['places', '새로 나온 장소', newPlaces ? `<p class="small">반영하면 인과율에 장소로 등록돼요. 그 뒤로는 이 장소가 나오는 화를 쓸 때 설명이 함께 들어가요.</p>${newPlaces}` : '', keys('l', d.new_places), (d.new_places || []).map((x) => x.name).join(', '), ''],
    ['time', '작품 속 시간', tl, [...keys('k', d.deadlines_added), ...keys('o', d.deadlines_done)], d.time && d.time.day > 0 ? `${d.time.day}일째${d.time.part ? ` ${d.time.part}` : ''}` : '', toolFoot(toolLink('timeline', '작품 속 시간'))],
  ];
  const shown = groups.filter(([, , html]) => html.replace(/<[^>]+>/g, '').trim());
  const empty = groups.filter((g) => !shown.includes(g)).map(([, label]) => label);
  const keepCount = shown.reduce((s, g) => s + g[3].length, 0);
  const grp = ([key, label, html, ks, peek, foot]) => {
    const open = !!(S.rvOpen && S.rvOpen[`${n}:g:${key}`]);
    return `<details class="rv-grp" data-rv-grp="${n}:g:${key}"${open ? ' open' : ''}><summary><span class="tf" aria-hidden="true">${RV_ICON[key]}</span><strong>${label}</strong>${ks.length ? `<span class="rv-count" data-rv-keys="${ks.join(',')}">${rvKeyCount(ks)}</span>` : ''}<span class="rv-peek">${esc(peek)}</span></summary>
      <div class="rv-grp-body">${html}${foot}</div></details>`;
  };
  const keep = `<section class="card rv-card rv-keep" aria-labelledby="rv-keep-h"><div class="rv-card-head"><h2 id="rv-keep-h">그대로 반영할 것 <span class="chip">${keepCount}</span></h2><span class="small">갈래를 펴서 고치거나 뺄 수 있어요</span></div>
    ${shown.map(grp).join('')}${empty.length ? `<div class="small rv-none">변경 없음: ${empty.join(' · ')}</div>` : ''}</section>`;

  const rel = `<section class="card rv-preview">${relationHeader('반영하면 이렇게 계산돼요')}<p class="small">AI는 사건만 적고 관계 수치는 Canon이 계산해요. 체크를 바꾸면 바로 다시 계산하고, 저장은 반영할 때만 돼요.</p><div id="rel-preview">${relationLines(S.preview && S.preview.n === n ? S.preview : null, true)}</div></section>`;
  const quote = S.rvQuote && S.rvQuote.n === n && S.rvQuote.name === S.name ? S.rvQuote : null;
  const wide = rvWide();
  const source = (S.deltaOrig[n] || {}).source === 'chat' ? '채팅 앱에서 가져온' : 'AI가 본문에서 뽑은';
  const applyBtn = (label) => `<button class="btn primary" data-action="applyDelta" data-arg="${n}"${autoOn() ? ' disabled' : ''}>${label}</button>`;
  const head = top('', `<div class="savebar-slot"></div>${rvMenu(n)}${wide ? applyBtn(`<span><span class="pick-count">${picked}</span>건 반영하고 ${n}화 완료</span>`) : ''}`).replace('<header class="page-head">', '<header class="page-head rv-head">');
  const lead = `<p class="small rv-lead">${source} 변경안 ${total}건이에요. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요. <span id="review-keys"><kbd>j</kbd> <kbd>k</kbd> 다음 · 이전 항목, <kbd>x</kbd> 체크.</span></p>`;
  const text = `<div class="read" data-read="${n}">${readHtml(n, e.text)}</div>`;
  const body = wide
    ? `<section class="card w-body rv-text" aria-label="${n}화 본문"><div class="w-bar"><span class="w-fill">밑줄은 변경안의 근거 문장이에요. 누르면 그 항목으로 가요</span><a class="btn small" href="${base()}/write/${n}">집필에서 고치기</a></div><div class="prose">${text}</div></section>`
    : `<details class="card rv-text rv-fold"><summary>${n}화 본문 보기</summary><div class="prose">${text}</div></details>`;
  const panel = `<div class="rv-panel">${quote && !wide ? rvQuotePanel(n, quote) : ''}${decide}${sum}${keep}${rel}</div>`;
  return head + stale + issues + lead + `<div class="rv-grid">${panel}${body}</div>` +
    (wide ? '' : `<div class="apply-bar rv-deck-bar" role="region" aria-label="반영"><span class="small"><strong class="pick-count" style="color:var(--text)">${picked}</strong>/${total} 고름</span>${applyBtn(`반영하고 ${n}화 완료`)}</div>`);
}

/** 갈래 아이콘 (토스페이스) */
const RV_ICON = { chars: '👤', places: '📍', rel: '🤝', secrets: '🤫', facts: '📌', fs: '🧩', time: '⏰' };

/** 인물 i 의 감정 · 차림 · 알게 된 정보 중 고친 칸이 있다 */
const charEdited = (n, i) => {
  const u = S.deltas[n].character_updates[i];
  return ['em' + i, 'at' + i, ...(u.knows || []).map((_, j) => `kn${i}.${j}`)].some((k) => itemEdited(n, k));
};

/** 체크가 바뀌면 갈래의 고른 수만 그 자리에서 바꾼다 (다시 그리지 않는다). 전체 고른 수 .pick-count 는 app.js 가 맞춘다 */
function rvCountRefresh() {
  if (typeof document === 'undefined' || !document.querySelectorAll) return;
  document.querySelectorAll('#app [data-rv-keys]').forEach((el) => { el.textContent = rvKeyCount(el.dataset.rvKeys.split(',')); });
}

// ----- 본문 근거 -----
// 사건 · 설정 바꾸기 · 복선 문장의 근거를 왼쪽 본문에 밑줄로 긋는다 (marks.js allRanges 가 rvRanges 를 함께 그린다).
// 항목의 '본문'을 누르면 본문이 그 문장으로 옮겨 가고, 밑줄을 누르면 그 항목으로 간다. 좁은 폭은 오른쪽 칸 위 근거 카드로 보인다

/** 근거 문장을 따옴표로 감싼다. 대사처럼 이미 따옴표가 있으면 그대로 */
const quoted = (q) => (/^["“'‘「『]/.test(q.trim()) ? esc(q) : `“${esc(q)}”`);

/** 변경안의 근거 문장: [체크 키, 문장, 이름]. 사건 · 설정 바꾸기 · 복선 문장 */
function rvQuotes(d) {
  return [
    ...d.events.map((ev, i) => [`e${i}`, ev.quote, `${charName(ev.actor)} → ${charName(ev.target)} ${ev.kind}`]),
    ...(d.setting_changes || []).map((x, i) => [`t${i}`, x.quote, `${charName(x.character_id)} 설정 바꾸기`]),
    ...(d.foreshadow_clues || []).map((c, i) => [`q${i}`, c.quote, '복선 문장']),
  ].filter(([, q]) => q && q.trim());
}

/** 상태 승인 단계의 본문 밑줄. 문장이 본문에 그대로 있을 때만, 고른 근거는 sel */
function rvRanges(n, text) {
  if (!S.route || S.route[2] !== 'review' || !S.deltas[n] || !text) return [];
  const sel = S.rvQuote && S.rvQuote.n === n ? S.rvQuote.q : null;
  const out = [];
  rvQuotes(S.deltas[n]).forEach(([key, q, label]) => {
    const at = text.indexOf(q.trim());
    if (at !== -1) out.push({ a: at, b: at + q.trim().length, kind: `src${q === sel ? ' sel' : ''}`, key: `r:${key}`, title: `${label} 근거` });
  });
  return out;
}

/** 근거 문장 버튼. 문장이 없으면 그리지 않는다 */
function rvQuoteBtn(n, quote, label) {
  if (!quote) return '';
  const on = S.rvQuote && S.rvQuote.n === n && S.rvQuote.q === quote;
  return `<button type="button" class="btn small rv-src" data-action="rvQuote" data-arg="${esc(JSON.stringify([n, quote, label]))}" aria-pressed="${!!on}" aria-label="${esc(label)} 본문 근거 보기"><span class="tf" aria-hidden="true">📖</span> 본문</button>`;
}

/** 본문에서 문장이 든 단락과 앞뒤 단락. 못 찾으면 null */
function rvQuoteFind(text, quote) {
  const paras = (text || '').split(/\n+/).map((x) => x.trim()).filter(Boolean);
  const at = paras.findIndex((x) => x.includes(quote));
  if (at < 0) return null;
  return paras.slice(Math.max(0, at - 1), at + 2).map((x) => x === paras[at]
    ? esc(x).replace(esc(quote), `<mark>${esc(quote)}</mark>`) : esc(x));
}

/** 좁은 폭의 근거 카드 */
function rvQuotePanel(n, q) {
  const found = rvQuoteFind(ep(n) ? ep(n).text : '', q.q);
  return `<section class="card rv-quote-panel" aria-label="본문 근거"><div class="rv-card-head"><h2><span class="tf" aria-hidden="true">📖</span> 본문 근거</h2><span class="small">${n}화 · ${esc(q.label)}</span>
      <button type="button" class="btn small rv-close" data-action="rvQuote" data-arg="" aria-label="본문 근거 닫기"><span class="tf" aria-hidden="true">✖️</span></button></div>
    ${found ? `<div class="rv-quote-text">${found.map((x) => `<p>${x}</p>`).join('')}</div>` : `<div class="note plain">본문에서 이 문장을 그대로 찾지 못했어요. AI가 문장을 조금 바꿔 옮겼을 수 있어요.<div class="rv-quote">${quoted(q.q)}</div></div>`}
    ${found && editableEp(ep(n)) ? `<div class="row"><span class="small" style="flex:1">이 문장을 바꾸려면 집필 화면에서 고쳐요</span><button type="button" class="btn small" data-action="rvQuoteGo" data-arg="${n}">집필에서 이 문장 고르기</button></div>` : ''}</section>`;
}

/** 체크 키(e0 · t1 · q0 …)의 항목으로 간다: 접힌 갈래면 펴고, 체크 상자에 포커스 */
function rvGoItem(n, key) {
  const grp = { e: 'rel', q: 'fs', c: 'chars' }[key[0]];
  const box = () => document.getElementById(`pk-${key}`);
  if (grp && box() && box().closest('details:not([open])')) {
    S.rvOpen = S.rvOpen || {};
    S.rvOpen[`${n}:g:${grp}`] = true;
    render();
  }
  const b = box();
  if (!b) return;
  b.style.scrollMargin = '96px 0 120px';
  b.focus({ preventScroll: true });
  b.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
}

// 본문의 근거 밑줄을 누르면 그 항목으로 간다
if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  document.addEventListener('click', (ev) => {
    const m = ev.target.closest && ev.target.closest('.rv-text .read mark.hl[data-hl^="r:"]');
    if (!m || S.route[2] !== 'review') return;
    rvGoItem(Number(S.route[3]), m.dataset.hl.slice(2));
  });
}

// 화면 폭이 900px 를 넘나들면 본문 칸을 옆에 두고 빼기를 바꾼다
if (typeof window !== 'undefined' && window.matchMedia) {
  window.matchMedia('(max-width: 900px)').addEventListener('change', () => {
    if (S.route[2] === 'review' && S.deltas[S.route[3]] && !isTyping()) render();
  });
}

// ----- 반영 직후 되돌리기 알림 -----
// 반영하면 다음 화 화면으로 넘어간다. 그 화면의 알림 말풍선 자리(#toast, 알림 버튼 아래)에 'n화를 반영했어요 · 되돌리기'를 10초 띄운다.
// #toast 안에 두어 다른 말풍선과 같은 자리에 놓이고(hub.js placeHub), #toast 의 aria-live 로 읽힌다.
// 클래스를 .t 로 두지 않아 toast() 가 오래된 알림을 내릴 때 함께 내려가지 않는다

const RV_UNDO_MS = 10000;
let rvUndoTimer = null;

/** 화면 아래 되돌리기 알림 모양. 상태 승인 화면의 칸 · 갈래 · 한 줄 반영 바는 app.css 에 있다 */
function rvStyle() {
  if (document.getElementById('rv-style')) return;
  const el = document.createElement('style');
  el.id = 'rv-style';
  el.textContent = `
#toast .rv-undo { display: flex; gap: 12px; align-items: center; padding: 8px 8px 8px 16px; border-radius: 10px; background: var(--inverse-bg); color: var(--inverse-ink); font-size: 0.8125rem; line-height: 1.5; box-shadow: 0 6px 24px rgba(0,0,0,0.2); border: 1px solid transparent; }
#toast .rv-undo span { flex: 1; }
#toast .rv-undo .btn { min-height: 40px; white-space: nowrap; }
#toast .rv-undo .x { border: none; background: transparent; color: inherit; cursor: pointer; font-size: 0.875rem; min-width: 40px; min-height: 40px; }
@media (forced-colors: active) { #toast .rv-undo { border-color: CanvasText; } }`;
  document.head.appendChild(el);
}

function rvUndoClose(focusBack = true) {
  clearTimeout(rvUndoTimer);
  const el = document.querySelector('#toast .rv-undo');
  if (!el) return;
  const had = el.contains(document.activeElement);
  el.remove();
  if (had && focusBack) { const m = document.getElementById('main'); if (m) m.focus({ preventScroll: true }); }
}

function rvUndoArm() {
  clearTimeout(rvUndoTimer);
  rvUndoTimer = setTimeout(() => rvUndoClose(), RV_UNDO_MS);
}

/** 반영 직후 알림. 마우스를 올리거나 포커스가 들어가 있는 동안은 닫지 않는다 */
function rvUndoShow(n) {
  rvStyle();
  rvUndoClose(false);
  const el = document.createElement('div');
  el.className = 'rv-undo';
  el.dataset.name = S.name;
  el.innerHTML = `<span>${n}화를 반영했어요</span><button type="button" class="btn small" data-action="rvUndo" data-arg="${n}">되돌리기</button><button type="button" class="x" data-rv-close aria-label="알림 닫기">✕</button>`;
  el.querySelector('[data-rv-close]').addEventListener('click', () => rvUndoClose());
  el.addEventListener('mouseenter', () => clearTimeout(rvUndoTimer));
  el.addEventListener('mouseleave', () => { if (!el.contains(document.activeElement)) rvUndoArm(); });
  el.addEventListener('focusin', () => clearTimeout(rvUndoTimer));
  el.addEventListener('focusout', (e) => { if (!el.contains(e.relatedTarget) && !el.matches(':hover')) rvUndoArm(); });
  $('#toast').appendChild(el);
  rvUndoArm();
}

function historyView(h) {
  const cast = toolLink('cast', '인물 · 관계도');
  const li = (arr) => arr.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${arr.map((x) => `<li>${x}</li>`).join('')}</ul>` : '<div class="small">없음</div>';
  return `<section class="card"><h2>요약</h2><p style="font-size:0.875rem;line-height:1.7">${esc(h.summary)}</p></section>
    <div class="grid-auto">
      <section class="card"><h2>인물 상태</h2>${li(h.character_updates.map((u) => `<strong>${esc(charName(u.character_id))}</strong> ${esc([u.emotional_state, u.current_goal, u.location].filter(Boolean).join(' / '))}${u.attire ? ` · 차림: ${esc(u.attire)}` : ''}${u.knows.length ? ` · 앎: ${esc(u.knows.join(', '))}` : ''}`))}${toolFoot(cast, statLink(h.character_updates))}</section>
      <section class="card"><h2>관계 사건</h2>${li((h.events || []).map((ev) => `${esc(charName(ev.actor))} → ${esc(charName(ev.target))} · ${esc(ev.kind)} ${INTENSITY[ev.intensity] || ''}${ev.witnesses && ev.witnesses.length ? ` · 목격: ${ev.witnesses.map(charName).map(esc).join(', ')}` : ''}${ev.reveals_secret ? ` · 드러난 비밀: ${esc(secretLabel(ev.reveals_secret, h))}` : ''}${ev.quote ? `<br><span class="small">“${esc(ev.quote)}”</span>` : ''}`))}${toolFoot(cast)}</section>
      <section class="card"><h2>사실과 복선</h2>${li([...h.new_facts.map(esc), ...h.foreshadow_planted.map((f) => '심음: ' + esc(f.description)), ...h.foreshadow_resolved.map((id) => { const f = P().foreshadows.find((x) => x.id === id); return '회수: ' + esc(f ? f.description : id); })])}${toolFoot(toolLink('foreshadow', '복선 센터'))}</section>
      ${(h.new_characters || []).length ? `<section class="card"><h2>새로 나온 인물</h2>${li(h.new_characters.map((c) => `<strong>${esc(c.name || c.id)}</strong> <span class="small">${esc(c.role || '')}</span>`))}</section>` : ''}
      ${(h.cast_added || []).length ? `<section class="card"><h2>등장 인물에 붙인 인물</h2>${li(h.cast_added.map((id) => `<strong>${esc(charName(id))}</strong> <span class="small">본문에 나와 붙였어요</span>`))}</section>` : ''}
      ${(h.new_places || []).length ? `<section class="card"><h2>새로 나온 장소</h2>${li(h.new_places.map(placeLabel))}</section>` : ''}
      ${withFoot(tlHistory(h), toolLink('timeline', '작품 속 시간'))}${withFoot(scHistory(h), cast)}${withFoot(addressHistory(h), cast)}
      ${(h.secrets_added || []).length ? `<section class="card"><h2>새로 생긴 비밀</h2>${li(h.secrets_added.map((x) => `<strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}`))}</section>` : ''}
      ${(h.relationship_updates || []).length ? `<section class="card"><h2>관계 유형 · 설명 변경</h2>${li(h.relationship_updates.map((r) => `${esc(charName(r.a))} ↔ ${esc(charName(r.b))} · ${esc(r.type)}${r.description ? ` · ${esc(r.description)}` : ''}`))}</section>` : ''}
    </div>`;
}

// ----- 관계 표시 (숫자/말) -----

const GOOD_EVENTS = ['도움', '희생', '약속이행', '칭찬', '진심고백', '사과', '공동경험'];
const INTENSITY = { 1: '가벼움', 2: '보통', 3: '결정적' };

function secretLabel(id, d) {
  const x = [...P().secrets, ...((d && d.secrets_added) || [])].find((s) => s.id === id);
  return x ? x.content : id;
}

function relationHeader(title) {
  const num = !!P().settings.show_numbers;
  return `<div class="between"><h2>${title}</h2><div class="seg" role="group" aria-label="관계 보기 방식">
    <button type="button" aria-pressed="${!num}" data-action="toggleNumbers" data-arg="words">말로</button>
    <button type="button" aria-pressed="${num}" data-action="toggleNumbers" data-arg="numbers">숫자로</button></div></div>`;
}

/** fold: 그대로인 줄은 접어 두고 바뀌는 줄만 펼친다 (상태 승인 미리보기) */
function relationLines(rel, fold = false) {
  if (!rel) return '<div class="small">계산하는 중…</div>';
  if (rel.error) return `<div class="note err">${esc(rel.error)}</div>`;
  const key = P().settings.show_numbers ? 'numbers' : 'words';
  const text = rel[key];
  if (!text) return '<div class="small">관계가 없어요. 설정 도우미에서 관계를 추가하세요.</div>';
  if (!rel.before) return `<ul class="rel-lines">${text.split('\n').map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
  // 미리보기: 줄마다 지금 값과 비교한다. 줄 앞 '도현 → 서윤' 같은 쌍으로 맞춘다
  const pair = (l) => l.split(':')[0].split(' (')[0].split(' 서로')[0].trim();
  const now = new Map((rel.before[key] || '').split('\n').filter(Boolean).map((l) => [pair(l), l]));
  const lines = text.split('\n').filter(Boolean);
  const changed = lines.filter((l) => now.get(pair(l)) !== l).length;
  const li = (l) => {
    const was = now.get(pair(l));
    return was === l ? `<li class="same">${esc(l)}</li>` : `<li class="changed"><ins>${esc(l)}</ins>${was ? `<div class="small">지금: ${esc(was)}</div>` : '<div class="small">새 관계</div>'}</li>`;
  };
  const same = lines.filter((l) => now.get(pair(l)) === l);
  const shown = fold && changed ? lines.filter((l) => now.get(pair(l)) !== l) : lines;
  return `<div class="small">${changed ? `반영하면 ${changed}줄이 바뀌어요. 바뀌는 줄 아래에 지금 값을 함께 보여요.` : '반영해도 관계는 그대로예요.'}</div>
    <ul class="rel-lines">${shown.map(li).join('')}</ul>${fold && changed && same.length ? `<details class="rel-same"><summary>그대로인 ${same.length}줄 보기</summary><ul class="rel-lines">${same.map(li).join('')}</ul></details>` : ''}`;
}


Object.assign(actions, {
  // 상태 변경안
  async extractState(n) {
    const d = S.deltas[n];
    const o = S.deltaOrig[n];
    // S.picks 는 설정 제안 화면과 같이 쓴다. 변경안을 받을 때 있던 칸만 비교한다
    const edited = d && o && (d.summary !== o.summary || Object.entries(o.picks).some(([k, v]) => S.picks[k] !== v) || deltaEdited(n));
    if (edited && !confirm('고친 요약 · 항목과 체크를 버리고 변경안을 다시 만들까요?')) return;
    if (S.textDraft[n] !== undefined) {
      try {
        S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] });
        delete S.textDraft[n];
      } catch (e) {
        return toast(e.message, true);
      }
    }
    await startJob('state', n);
  },
  async applyDelta(n) {
    const out = pickedDelta(n);
    // 평소에는 바로 반영한다. 고른 항목이 없거나, 경고가 남았거나, 변경안을 만든 뒤 본문을 고쳤으면 한 번 묻는다
    const count = deltaCount(out);
    const why = [
      count ? '' : '고른 항목이 0건이에요. 요약만 저장하고',
      (out.warnings || []).length ? `경고 ${out.warnings.length}건이 남아 있어요.` : '',
      S.deltaBase[n] !== undefined && ep(n) && S.deltaBase[n] !== ep(n).text ? '변경안을 만든 뒤 본문을 고쳤어요.' : '',
    ].filter(Boolean);
    if (why.length && !confirm(`${why.join(' ')} ${n}화를 마칠까요? 반영하면 반영 취소로만 돌아갈 수 있어요.`)) return;
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/apply`, out);
      delete S.deltas[n];
      const r = S.auto && S.auto.run;
      const forAuto = r && r.status === 'review' && r.ep === n;
      // 넘어간 화면 아래에 되돌리기 알림을 띄운다. 자동 집필이 맡은 화와 되돌릴 스냅샷이 없는 화는 알림만 띄운다
      if (!forAuto && !(ep(n) || {}).auto && P().snapshots.some((s) => s.episode === n - 1)) rvUndoShow(n);
      else toast(ep(n + 1) && ep(n + 1).status === 'confirmed' ? `${n}화를 마쳤어요. ${n + 1}화 집필로 왔어요` : `${n}화를 마쳤어요`);
      // 자동 집필이 이 화에서 검토를 기다리고 있었으면 자동 집필 화면으로 돌아가 이어 가게 한다.
      // 아니면 다음 할 일로 바로 간다: 다음 화가 확정이면 그 화 집필, 초안이면 플롯, 없으면 홈 (nextStep)
      const next = ep(n + 1);
      location.hash = forAuto ? `${base()}/auto` : next && ['confirmed', 'draft'].includes(next.status) ? nextStep()[1] : base();
    });
  },
  async toggleNumbers(v) {
    const show = v === 'numbers';
    P().settings.show_numbers = show;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/view`, { show_numbers: show });
    } catch (e) {
      toast(e.message, true);
    }
  },
  /** 인물 칸 펴기 · 접기 ('n:c0') */
  rvOpen(key) {
    S.rvOpen = S.rvOpen || {};
    S.rvOpen[key] = !S.rvOpen[key];
    S.focusTarget = `#app [data-action="rvOpen"][data-arg="${key}"]`;
    render();
  },
  /** 본문 근거 열기 · 닫기. arg: JSON [화, 문장, 이름] 또는 '' (닫기). 넓은 폭은 왼쪽 본문의 그 밑줄로 옮겨 가고, 좁은 폭은 근거 카드 */
  rvQuote(arg) {
    const [n, q, label] = arg ? JSON.parse(arg) : [];
    const same = S.rvQuote && S.rvQuote.q === q && S.rvQuote.n === n;
    const back = S.rvQuote && S.rvQuote.from;
    S.rvQuote = q && !same ? { n, q, label, name: S.name, from: arg } : null;
    const wide = rvWide();
    S.focusTarget = S.rvQuote && !wide ? '#app .rv-quote-panel .rv-close' : back && !S.rvQuote ? `#app [data-action="rvQuote"][data-arg="${CSS.escape(back)}"]` : null;
    render();
    if (!S.rvQuote) return;
    const at = wide ? $('#app .rv-text mark.hl.src.sel') : $('#app .rv-quote-panel');
    if (at) at.scrollIntoView({ block: wide ? 'center' : 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    else if (wide) toast('본문에서 이 문장을 그대로 찾지 못했어요. AI가 문장을 조금 바꿔 옮겼을 수 있어요', true);
  },
  /** 본문 근거 문장을 집필 화면 본문에서 고른다 (passage.js warnPick 과 같은 길) */
  rvQuoteGo(n) {
    const num = Number(n);
    const q = S.rvQuote && S.rvQuote.q;
    if (!q || !textNow(num).includes(q)) return toast('본문에서 그 문장을 찾을 수 없어요', true);
    const go = () => {
      if (S.route[2] !== 'write' || Number(S.route[3]) !== num || focusText(num, q, 0) === -1) return;
      S.selFocus.menu = true;
      render();
    };
    window.addEventListener('hashchange', () => routeQueue.then(go), { once: true });
    location.hash = `${base()}/write/${num}`;
  },
  /** 반영 직후 알림의 '되돌리기'. 확인 창은 revertFrom 이 띄운다. 취소하면 알림을 다시 10초 둔다 */
  async rvUndo(n) {
    const el = document.querySelector('#toast .rv-undo');
    if (!el || el.dataset.name !== S.name || !P() || (ep(n) || {}).status !== 'finalized') {
      rvUndoClose();
      return toast('이 알림의 화는 이미 바뀌었어요. 상태 승인 화면에서 반영 취소를 써 주세요', true);
    }
    clearTimeout(rvUndoTimer);
    if (!(await actions.revertFrom(n))) {
      if (el.isConnected && !el.matches(':hover') && !el.contains(document.activeElement)) rvUndoArm();
      return;
    }
    rvUndoClose(false);
    location.hash = `${base()}/review/${n}`;  // 다시 고를 변경안이 있는 화면으로
  },
  dropDelta(n) {
    if (!confirm('이 변경안을 버릴까요?')) return;
    delete S.deltas[n];
    render();
  },
});

// 상태 승인 화면에서 고친 사건 · 사실 · 감정 · 알게 된 정보를 변경안에 바로 넣는다. 반영과 관계 미리 보기가 그대로 쓴다.
// 차림 칸(data-attire)은 app.js 가 값을 넣고, 여기서는 '고침' 표시만 바꾼다. select 도 값을 고르면 input 이 온다
document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.dmark) return;
  const n = el.dataset.dedit || el.dataset.attireEp;
  const d = S.deltas[n];
  if (!d) return;
  if (el.dataset.dpath) {
    const keys = el.dataset.dpath.split('.');
    const last = keys.pop();
    const at = keys.reduce((o, k) => o && o[k], d);
    if (!at) return;
    at[last] = last === 'intensity' ? Number(el.value) : el.value;
    if (last === 'kind') {  // 좋은 사건은 초록, 나쁜 사건은 빨강 (kindStyle)
      const good = GOOD_EVENTS.includes(el.value);
      el.style.background = good ? 'var(--green-soft)' : 'var(--red-soft)';
      el.style.color = good ? 'var(--green)' : 'var(--red)';
    }
    if (keys[0] === 'events') refreshPreview(Number(n));
  }
  showEdited(n, el.dataset.dmark);
});

// 체크를 바꾸면 갈래의 고른 수를 맞춘다 (전체 고른 수 .pick-count 는 app.js 가 맞춘다)
document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.pick && DELTA_PICK.test(el.dataset.pick) && S.route[2] === 'review') rvCountRefresh();
});

// 펴 둔 갈래는 다시 그려도 펴 둔다 (toggle 은 거품이 일지 않아 잡는 단계에서 받는다)
document.addEventListener('toggle', (e) => {
  const g = e.target.dataset && e.target.dataset.rvGrp;
  if (!g) return;
  S.rvOpen = S.rvOpen || {};
  S.rvOpen[g] = e.target.open;
}, true);

/** 상태 승인 단축키: j · k 다음 · 이전 항목, x 지금 항목 체크. 한글 자판이면 같은 자리 ㅓ · ㅏ · ㅌ 로 온다 */
const REVIEW_KEYS = { j: 1, 'ㅓ': 1, k: -1, 'ㅏ': -1, x: 0, 'ㅌ': 0 };
document.addEventListener('keydown', (e) => {
  if (e.isComposing || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || e.key.length !== 1) return;
  const step = REVIEW_KEYS[e.key.toLowerCase()];
  if (step === undefined || S.route[2] !== 'review' || !S.deltas[S.route[3]]) return;
  // 입력칸 안에서는 글자를 쳐야 한다. 체크 상자는 입력칸이 아니라 j · k 로 옮겨 다닌다
  const t = e.target;
  if (t.closest && t.closest('input:not([type="checkbox"]), textarea, select, [contenteditable]:not([contenteditable="false"])')) return;
  // 접힌 갈래 안의 항목은 건너뛴다 (펴면 들어간다)
  const boxes = [...document.querySelectorAll('#app .change input[data-pick]')].filter((b) => DELTA_PICK.test(b.dataset.pick) && !b.disabled && !b.closest('details:not([open])'));
  const row = t.closest && t.closest('#app .change');
  const i = boxes.findIndex((b) => b === t || (row && row.contains(b)));
  if (!boxes.length || (step === 0 && i < 0)) return;
  e.preventDefault();
  if (step === 0) {
    boxes[i].click();  // change 가 S.picks · 고른 수 · 관계 미리 보기를 맞춘다
    return;
  }
  const next = boxes[i < 0 ? (step > 0 ? 0 : boxes.length - 1) : Math.min(Math.max(i + step, 0), boxes.length - 1)];
  next.style.scrollMargin = '96px 0 120px';  // 위 머리 줄과 아래 반영 줄에 가리지 않게
  next.focus();
  next.scrollIntoView({ block: 'nearest' });
});
