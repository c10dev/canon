/* 6단계 상태 승인: 상태 변경안 고르기 · 반영, 관계 계산 미리보기, 관계 표시(숫자/말). app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
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
const DELTA_PICK = /^[cesrfpxnqlkot]\d+$/;
/** 상태 변경안에서 하나씩 골라 반영하는 목록 (StateDelta 의 목록 칸 중 warnings 를 뺀 것, tests/test_delta_count.py 가 맞춰 본다) */
const DELTA_LISTS = ['character_updates', 'events', 'secrets_added', 'relationship_updates', 'new_facts', 'foreshadow_planted', 'foreshadow_resolved', 'foreshadow_clues', 'new_characters', 'new_places', 'deadlines_added', 'deadlines_done', 'setting_changes'];
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
  S.rvPage = null;  // 좁은 화면 카드 넘기기는 첫 장부터
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

// ----- 5. 상태 승인 -----

function viewReview(n) {
  const e = ep(n);
  if (!e) return header('6단계', '상태 승인', '') + noEpisode();
  const top = (desc, right = '') => `<header class="page-head"><div class="row" style="gap:12px">${epNav('review', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)}</div><h1 style="font-size:1.5rem">상태 승인</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>${autoLockNote()}${desc ? `<p class="desc">${desc}</p>` : ''}`;

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
      `${ep(n + 1) ? `<div class="note info">${n}화 상태를 반영해야 ${n + 1}화를 쓸 수 있어요.</div>` : ''}<div class="cols"><section class="card col"><h2>AI로 만들기</h2><p class="desc">${n}화 본문을 읽고 변경안을 만들어요.${S.config && S.config.stages ? ` <span class="small">모델: ${esc(S.config.stages.state.model)}</span>` : ''}</p><div>${((b) => `<button class="btn primary" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 만들기'))}</div></section>
       <section class="card col"><h2>채팅 앱에서 받은 JSON</h2><p class="desc">상태 승인 지시서를 채팅 앱에 붙여 넣고 받은 JSON을 가져와요.</p><div><a class="btn" href="${base()}/brief/${n}" data-action="openStateBrief" data-arg="${n}">상태 승인 지시서 열기</a></div></section></div>`;
  }

  const p = P();
  const remake = ((b) => `<button class="btn small" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 다시 만들기'));
  const stale = textUnsaved(n)
    ? `<section class="note warn">${n}화 본문에 저장하지 않은 수정이 있어요. 반영해도 그 수정은 저장되지 않아요. 변경안을 다시 만들면 본문을 먼저 저장해요. ${remake} <a href="${base()}/write/${n}">본문으로</a></section>`
    : S.deltaBase[n] !== undefined && S.deltaBase[n] !== e.text
      ? `<section class="note warn">이 변경안을 만든 뒤 본문을 고쳤어요. 고친 내용이 상태에 영향을 준다면 변경안을 다시 만드세요. ${remake}</section>` : '';
  // 열린 검수 지적이 남았거나 검수하지 않았으면 반영 전에 알린다 (검수 뒤 본문을 고쳤으면 지난 결과라고 밝힌다). 막지는 않는다
  const cs = checkState(e);
  const issues = cs.open
    ? `<section class="note warn">열린 검수 지적 ${cs.open}곳이 남아 있어요${cs.stale ? ' (검수 뒤 본문을 고쳤어요)' : ''}. <a href="${base()}/check/${n}">검수에서 보기</a></section>`
    : !cs.checked ? `<section class="note plain">${n}화는 아직 검수하지 않았어요. 반영해도 되지만, 앞 화와 어긋나는 곳이 있는지 <a href="${base()}/check/${n}">검수</a>에서 먼저 볼 수 있어요.</section>` : '';
  const total = deltaCount(d);
  if (!S.preview || S.preview.n !== n) refreshPreview(n);
  const picked = deltaPicked();
  const box = (key, label) => `<input type="checkbox" id="pk-${key}" data-pick="${key}"${label ? ` aria-label="${esc(label)}"` : ''}${S.picks[key] ? ' checked' : ''}>`;
  const orig = (S.deltaOrig[n] && S.deltaOrig[n].delta) || d;
  // 고칠 수 있는 칸: data-dedit 입력이 S.deltas[n] 의 data-dpath 칸을 바로 고친다 (아래 input 처리)
  const edit = (path, key) => `data-dedit="${n}" data-dpath="${path}" data-dmark="${key}"`;
  const diff = (before, after) => before && before !== after
    ? `<div class="row"><span class="before">${esc(before)}</span><span class="small">→</span><span class="after">${esc(after)}</span></div>`
    : `<div class="row"><span class="after">${esc(after)}</span></div>`;
  const chip = (k, v) => `<span class="rv-chip"><span class="k">${k}</span> ${v}</span>`;

  // 인물 상태: 바뀐 칸을 한 줄 칩으로 접어 보이고, '고치기'를 누르면 그 자리에서 칸을 편다
  const chars = d.character_updates.map((u, i) => {
    const cur = p.states.find((s) => s.character_id === u.character_id) || {};
    const ou = orig.character_updates[i] || u;
    const name = charName(u.character_id);
    const was = (now) => now ? `<div class="row"><span class="before">${esc(now)}</span><span class="small">→</span></div>` : '';
    // 이미 아는 정보는 반영해도 그대로라 보이지 않는다. 받은 글로 거르고, 고친 칸은 u.knows 의 같은 자리를 바꾼다
    const knowIdx = u.knows.map((k, j) => [k, j]).filter(([k, j]) => !(cur.knows || []).includes((ou.knows || [])[j] ?? k));
    const stats = (u.stats || []).filter((s) => s.name && s.name.trim());
    const unknown = !p.characters.some((c) => c.id === u.character_id) && !(d.new_characters || []).some((c) => c.id === u.character_id);
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
    return `<div class="change rv-char${open ? ' open' : ''}">${box('c' + i)}<div class="body"><div class="rv-row-head"><label for="pk-c${i}" class="rv-name">${esc(name)}${unknown ? ' <span class="chip draft">설정에 없는 인물</span>' : ''}</label>${edited && !open ? '<span class="chip warn">고침</span>' : ''}
      <button type="button" class="btn small rv-edit" data-action="rvOpen" data-arg="${n}:c${i}" aria-expanded="${open}"${open ? ` aria-controls="rv-ed-c${i}"` : ''} aria-label="${esc(name)} 상태 ${open ? '접기' : '고치기'}">${open ? '접기' : '고치기'}</button></div>${inner}</div></div>`;
  }).join('');

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
  const newChars = (d.new_characters || []).map((c, i) => `<div class="change">${box('n' + i)}<label for="pk-n${i}" style="font-size:0.8125rem;line-height:1.55"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}으로 추가</span><br>${esc(c.personality || c.appearance || c.goal)}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}</label></div>`).join('');
  const newPlaces = (d.new_places || []).map((x, i) => `<div class="change">${box('l' + i)}<label for="pk-l${i}" style="font-size:0.8125rem;line-height:1.55">${placeLabel(x)}</label></div>`).join('');
  const secrets = d.secrets_added.map((x, i) => `<div class="change">${box('s' + i)}<label for="pk-s${i}" style="font-size:0.8125rem;line-height:1.55"><strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}<br><span class="small">모르는 인물: ${x.hidden_from.map(charName).map(esc).join(', ') || '없음'}</span></label></div>`).join('');
  const rels = d.relationship_updates.map((r, i) => {
    const cur = p.relationships.find((x) => (x.a === r.a && x.b === r.b) || (x.a === r.b && x.b === r.a));
    return `<div class="change">${box('r' + i)}<div class="body"><label for="pk-r${i}" style="font-size:0.875rem;font-weight:700">${esc(charName(r.a))} ↔ ${esc(charName(r.b))}</label>
      ${diff(cur && cur.type, r.type)}${r.description ? diff(cur && cur.description, r.description) : ''}</div></div>`;
  }).join('');

  const facts = d.new_facts.map((f, i) => `<div class="change">${box('f' + i, `확정 사실 ${i + 1} 반영`)}<div class="body"><div class="row" style="gap:6px;flex-wrap:nowrap"><input id="fv-${i}" aria-label="확정 사실 ${i + 1}" ${edit(`new_facts.${i}`, 'f' + i)} value="${esc(f)}" placeholder="비우면 빼요" style="flex:1;min-width:0;font-size:0.8125rem">${editMark(n, 'f' + i)}</div></div></div>`).join('');
  const fs = [
    ...d.foreshadow_planted.map((f, i) => `<div class="change">${box('p' + i)}<label for="pk-p${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip confirmed">심음</span> ${esc(f.description)} <span class="small">${esc(f.id)}</span></label></div>`),
    ...d.foreshadow_resolved.map((id, i) => {
      const f = p.foreshadows.find((x) => x.id === id);
      return `<div class="change">${box('x' + i)}<label for="pk-x${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip finalized">회수</span> ${esc(f ? f.description : id)} ${f ? `<span class="small">${f.planted_ep}화에 심음</span>` : '<span class="small">알 수 없는 id</span>'}</label></div>`;
    }),
    fsClueRows(d, box, n),
  ].join('');
  const castLink = toolLink('cast', '인물 · 관계도');
  /** 갈래 카드: 머리에 아이콘 · 이름 · 설명 · 도구 링크 */
  const section = (key, title, sub, body, foot = '') => `<section class="card rv-card"><div class="rv-card-head"><h2><span class="tf" aria-hidden="true">${RV_ICON[key]}</span> ${title}</h2>${sub ? `<span class="small">${sub}</span>` : ''}</div>${body || '<div class="small">변경 없음</div>'}${foot}</section>`;
  /** 다른 파일이 그린 카드는 첫 제목에 아이콘만 붙인다 */
  const iconed = (key, html) => html ? html.replace('<h2>', `<h2><span class="tf" aria-hidden="true">${RV_ICON[key]}</span> `) : '';

  const deck = narrowScreen();
  const relSide = `${relationHeader('반영하면 이렇게 계산돼요')}<p class="small">AI는 사건만 적고 관계 수치는 Canon이 계산해요. 체크를 바꾸면 바로 다시 계산하고, 저장은 반영할 때만 돼요.</p><div id="rel-preview">${relationLines(S.preview && S.preview.n === n ? S.preview : null, true)}</div>`;
  const quote = S.rvQuote && S.rvQuote.n === n && S.rvQuote.name === S.name ? S.rvQuote : null;
  const sidePanel = quote && !deck ? rvQuotePanel(n, quote) : `<section class="card rv-preview">${relSide}</section>`;
  // 카드 묶음: [키, 이름, 글]. 빈 글은 그리지 않는다. 넓은 화면은 왼쪽 목차로 건너뛰고, 좁은 화면은 탭으로 한 장씩 본다
  const cards = [
    ['chars', '인물 상태', section('chars', '인물 상태', `${d.character_updates.length}명 · 바뀐 칸만 보여요 · '고치기'로 그 자리에서 고쳐요`, chars, toolFoot(castLink, statLink(d.character_updates)))],
    ['setting', '인물 설정 바꾸기', iconed('setting', withFoot(scDeltaCard(n, d, box), castLink))],
    ['newchars', '새로 나온 인물', newChars ? section('newchars', '새로 나온 인물', '', newChars, toolFoot(castLink)) : ''],
    ['places', '새로 나온 장소', newPlaces ? section('places', '새로 나온 장소', '반영하면 인과율에 장소로 등록돼요. 그 뒤로는 이 장소가 나오는 화를 쓸 때 설명이 함께 들어가요.', newPlaces) : ''],
    ['rel', '관계 사건', section('rel', '관계 사건', '종류와 강도만 고르고, 관계 수치는 Canon이 계산해요', events || '<div class="small">이번 화에 관계 사건이 없어요</div>', toolFoot(castLink))
      + (deck ? `<section class="card rv-preview">${relSide}</section>` : '')],
    ['secrets', '비밀 · 관계 유형', secrets || rels ? section('secrets', '비밀 · 관계 유형', '', `${secrets ? `<h3>새로 생긴 비밀</h3>${secrets}` : ''}${rels ? `<h3>관계 유형 · 설명 변경</h3>${rels}` : ''}`, toolFoot(castLink)) : ''],
    ['facts', '확정 사실', section('facts', '확정 사실', '', facts)],
    ['fs', '복선', section('fs', '복선', '', fs, toolFoot(toolLink('foreshadow', '복선 센터')))],
    ['time', '작품 속 시간', iconed('time', withFoot(tlDeltaCard(n, d, box), toolLink('timeline', '작품 속 시간')))],
    ['sum', `${n}화 요약`, `<section class="card rv-card"><div class="rv-card-head"><h2><span class="tf" aria-hidden="true">${RV_ICON.sum}</span> <label for="dsum">${n}화 요약</label></h2><span class="small"><span id="dsum-count">${d.summary.length.toLocaleString()}</span>자 · 다음 화 생성에 이 요약이 들어가요</span></div>
      <textarea id="dsum" rows="4" data-autogrow data-delta-summary="${n}">${esc(d.summary)}</textarea>
      <div class="row"><button class="btn small" data-action="dropDelta" data-arg="${n}">변경안 버리기</button><a class="btn small" href="${base()}/write/${n}">본문으로</a></div></section>`],
  ].filter(([, , html]) => html);
  const counts = rvCounts(n);
  const pg = deck ? rvPageAt(n, cards.length) : 0;
  const railItem = ([key, label], i) => {
    const flag = key === 'setting' ? '<span class="rv-flag amber">직접</span>' : counts[key].edited ? `<span class="rv-flag" data-rv-flag="${key}">고침 ${counts[key].edited}</span>` : `<span class="rv-flag" data-rv-flag="${key}" hidden></span>`;
    const inner = `<span class="tf" aria-hidden="true">${RV_ICON[key]}</span><span class="rv-label">${esc(label)}</span>${flag}<span class="rv-count" data-rv-count="${key}">${counts[key].text}</span>`;
    return deck
      ? `<button type="button" role="tab" id="rv-t-${i}" class="rv-tab" aria-selected="${i === pg}" aria-controls="rv-p-${i}" tabindex="${i === pg ? 0 : -1}" data-action="rvPage" data-arg="${i}">${inner}</button>`
      : `<button type="button" class="rv-rail-item" data-action="rvJump" data-arg="${key}" data-rv-item="${key}"${(S.rvSpy && counts[S.rvSpy] && cards.some(([k]) => k === S.rvSpy) ? key === S.rvSpy : !i) ? ' aria-current="true"' : ''}>${inner}</button>`;
  };
  const source = (S.deltaOrig[n] || {}).source === 'chat' ? '채팅 앱에서 가져온' : 'AI가 본문에서 뽑은';
  const applyBtn = (label) => `<button class="btn primary" data-action="applyDelta" data-arg="${n}"${autoOn() ? ' disabled' : ''}>${label}</button>`;
  const warn = d.warnings.length ? `<details class="note warn rv-warn"${S.rvWarnOpen ? ' open' : ''}><summary><strong><span class="tf" aria-hidden="true">⚠️</span> 경고 ${d.warnings.length}건</strong> · 반영 전에 본문을 고칠지 확인하세요</summary><ul>${warnItems(n, d.warnings)}</ul><a href="${base()}/write/${n}">본문으로</a></details>` : '';
  // 머리: 반영 버튼과 저장 칸은 넓은 화면만. 좁은 화면은 아래 한 줄 반영 바에 둔다
  const head = `<header class="page-head rv-head"><div class="row" style="gap:12px">${epNav('review', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)}</div><h1 style="font-size:1.5rem">상태 승인</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div>
    <div class="row rv-actions">${remake}<div class="savebar-slot"></div>${deck ? '' : applyBtn(`<span><span class="pick-count">${picked}</span>건 반영하고 ${n}화 완료</span>`)}</div></header>${autoLockNote()}`;

  if (deck) {
    rvStyle();
    const tabs = `<div class="rv-tabs" role="tablist" aria-label="변경안 갈래">${cards.map(railItem).join('')}</div>`;
    const pages = cards.map(([, label, html], i) => `<div class="rv-page" id="rv-p-${i}" data-rv-page="${i}" data-rv-label="${esc(label)}" role="tabpanel" aria-labelledby="rv-t-${i}"${i === pg ? '' : ' hidden'}>${html}</div>`).join('');
    return head + stale + issues + warn + tabs + (quote ? rvQuotePanel(n, quote) : '') + pages +
      `<div class="apply-bar rv-deck-bar" role="region" aria-label="반영"><span class="small"><strong class="pick-count" style="color:var(--text)">${picked}</strong>/${total} 선택</span>${applyBtn(`반영하고 ${n}화 완료`)}</div>`;
  }
  const rail = `<nav class="rv-rail" aria-label="변경안 갈래"><div class="rv-rail-top"><strong>변경안 ${total}건</strong><span class="small"><strong class="pick-count" style="color:var(--text)">${picked}</strong>건 선택</span></div>
    ${cards.map(railItem).join('')}
    <div class="rv-rail-foot small"><span>${source} 변경안이에요. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요.</span><span id="review-keys"><kbd>j</kbd> <kbd>k</kbd> 다음 · 이전 항목, <kbd>x</kbd> 체크. 입력칸 밖에서 써요.</span></div></nav>`;
  const list = cards.map(([key, , html]) => `<div class="rv-group" id="rv-g-${key}" data-rv-group="${key}">${html}</div>`).join('');
  return head + stale + issues + warn + `<div class="rv-grid">${rail}<div class="rv-list">${list}</div><aside class="rv-side" aria-label="${quote ? '본문 근거' : '반영하면 이렇게 계산돼요'}">${sidePanel}</aside></div>`;
}

// ----- 갈래 목차 · 탭 -----

/** 갈래마다 붙이는 토스페이스 이모지 */
const RV_ICON = { chars: '👤', setting: '✏️', newchars: '🙋', places: '📍', rel: '🤝', secrets: '🤫', facts: '📌', fs: '🧩', time: '⏰', sum: '📝' };
/** 갈래마다 세는 체크 키 앞 글자 (DELTA_PICK 의 글자). 키 → StateDelta 목록 */
const RV_GROUP_KEYS = { chars: 'c', setting: 't', newchars: 'n', places: 'l', rel: 'e', secrets: 'sr', facts: 'f', fs: 'pxq', time: 'ko', sum: '' };
const PICK_LISTS = { c: 'character_updates', e: 'events', s: 'secrets_added', r: 'relationship_updates', f: 'new_facts', p: 'foreshadow_planted', x: 'foreshadow_resolved', q: 'foreshadow_clues', n: 'new_characters', l: 'new_places', k: 'deadlines_added', o: 'deadlines_done', t: 'setting_changes' };

/** 인물 i 의 감정 · 차림 · 알게 된 정보 중 고친 칸이 있다 */
const charEdited = (n, i) => {
  const u = S.deltas[n].character_updates[i];
  return ['em' + i, 'at' + i, ...(u.knows || []).map((_, j) => `kn${i}.${j}`)].some((k) => itemEdited(n, k));
};

/** 갈래마다 '고른 수/모두'와 고친 항목 수. 요약은 글자 수 */
function rvCounts(n) {
  const d = S.deltas[n];
  const out = {};
  for (const [key, letters] of Object.entries(RV_GROUP_KEYS)) {
    let all = 0;
    let on = 0;
    for (const c of letters) {
      const len = (d[PICK_LISTS[c]] || []).length;
      all += len;
      for (let i = 0; i < len; i++) if (S.picks[c + i]) on++;
    }
    const edited = key === 'chars' ? d.character_updates.filter((_, i) => charEdited(n, i)).length
      : key === 'rel' ? d.events.filter((_, i) => itemEdited(n, 'e' + i)).length
        : key === 'facts' ? d.new_facts.filter((_, i) => itemEdited(n, 'f' + i)).length : 0;
    out[key] = { text: key === 'sum' ? `${d.summary.length.toLocaleString()}자` : all ? `${on}/${all}` : '', edited };
  }
  return out;
}

/** 체크 · 고친 칸이 바뀌면 목차 · 탭의 수만 그 자리에서 바꾼다 (다시 그리지 않는다) */
function rvRailRefresh(n) {
  if (!S.deltas[n] || !document.querySelectorAll) return;
  const counts = rvCounts(n);
  document.querySelectorAll('#app [data-rv-count]').forEach((el) => { el.textContent = counts[el.dataset.rvCount].text; });
  document.querySelectorAll('#app [data-rv-flag]').forEach((el) => {
    const k = counts[el.dataset.rvFlag].edited;
    el.textContent = k ? `고침 ${k}` : '';
    el.hidden = !k;
  });
}

/** 두 칸 배치: 목차 칸이 아래에 쌓인 작업 목록 · 알림(--rvj) 위에서 끝나게 높이를 맞춘다. 화면을 내려 목차가 붙는 동안에도 다시 잰다 */
function rvRailFit() {
  const rail = document.querySelector('#app .rv-rail');
  if (!rail) return;
  const below = parseFloat(document.body.style.getPropertyValue('--rvj')) || 0;
  rail.style.maxHeight = below ? `${Math.max(120, Math.floor(window.innerHeight - Math.max(16, rail.getBoundingClientRect().top) - 16 - below))}px` : '';
}

/** 목차에서 지금 보는 갈래를 표시한다 */
function rvSpy(key) {
  S.rvSpy = key;
  document.querySelectorAll('#app [data-rv-item]').forEach((el) => {
    if (el.dataset.rvItem === key) el.setAttribute('aria-current', 'true');
    else el.removeAttribute('aria-current');
  });
}

// 화면을 내리면 머리가 위쪽(140px)을 지난 마지막 갈래를 목차에 표시한다
if (typeof window !== 'undefined' && window.addEventListener) {
  let spyQueued = false;
  window.addEventListener('scroll', () => {
    if (spyQueued || S.route[2] !== 'review') return;
    spyQueued = true;
    requestAnimationFrame(() => {
      spyQueued = false;
      rvRailFit();
      const gs = [...document.querySelectorAll('#app .rv-group')];
      if (!gs.length) return;
      const past = gs.filter((g) => g.getBoundingClientRect().top <= 140);
      rvSpy((past.length ? past[past.length - 1] : gs[0]).dataset.rvGroup);
    });
  }, { passive: true });
}

// ----- 본문 근거 -----
// 사건 · 설정 바꾸기 · 복선 문장의 근거 문장을 본문에서 찾아 앞뒤 단락과 함께 보인다. 넓은 화면은 오른쪽 열(관계 미리보기 자리), 좁은 화면은 탭 바로 아래

/** 근거 문장을 따옴표로 감싼다. 대사처럼 이미 따옴표가 있으면 그대로 */
const quoted = (q) => (/^["“'‘「『]/.test(q.trim()) ? esc(q) : `“${esc(q)}”`);

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

function rvQuotePanel(n, q) {
  const found = rvQuoteFind(ep(n) ? ep(n).text : '', q.q);
  return `<section class="card rv-quote-panel" aria-label="본문 근거"><div class="rv-card-head"><h2><span class="tf" aria-hidden="true">📖</span> 본문 근거</h2><span class="small">${n}화 · ${esc(q.label)}</span>
      <button type="button" class="btn small rv-close" data-action="rvQuote" data-arg="" aria-label="본문 근거 닫기"><span class="tf" aria-hidden="true">✖️</span></button></div>
    ${found ? `<div class="rv-quote-text">${found.map((x) => `<p>${x}</p>`).join('')}</div>` : `<div class="note plain">본문에서 이 문장을 그대로 찾지 못했어요. AI가 문장을 조금 바꿔 옮겼을 수 있어요.<div class="rv-quote">${quoted(q.q)}</div></div>`}
    ${found && editableEp(ep(n)) ? `<div class="row"><span class="small" style="flex:1">이 문장을 바꾸려면 집필 화면에서 고쳐요</span><button type="button" class="btn small" data-action="rvQuoteGo" data-arg="${n}">집필에서 이 문장 고르기</button></div>` : ''}</section>`;
}

// ----- 좁은 화면 카드 넘기기 -----
// 640px 이하에서 변경안 카드를 한 장씩 보인다. 체크와 고친 값은 S.picks · S.deltas 에 있어 장을 넘겨도 남는다

/** 지금 보는 장. 화가 바뀌거나 새 변경안을 받으면 첫 장으로 (setDelta) */
function rvPageAt(n, count) {
  if (!S.rvPage || S.rvPage.n !== n || S.rvPage.name !== S.name) S.rvPage = { n, name: S.name, i: 0 };
  S.rvPage.i = Math.min(Math.max(S.rvPage.i, 0), count - 1);
  return S.rvPage.i;
}

/** i 장으로 넘긴다. 넘긴 장의 머리가 화면 위로 지나갔으면 끌어 올리고, 화면 낭독기에 몇 번째 장인지 알린다 */
function rvGo(i, focus = null) {
  const pages = document.querySelectorAll('#app .rv-page');
  if (!pages.length || !S.rvPage) return;
  S.rvPage.i = Math.min(Math.max(i, 0), pages.length - 1);
  if (focus) S.focusTarget = focus;
  render();
  const page = $(`#app .rv-page[data-rv-page="${S.rvPage.i}"]`);
  if (!page) return;
  const tab = $('#app .rv-tab[aria-selected="true"]');
  if (tab) tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });  // 옆으로 넘친 탭 줄에서 고른 탭이 보이게
  const top = page.getBoundingClientRect().top;
  if (top < 0 || top > window.innerHeight * 0.6) window.scrollBy(0, top - 16);
  const live = $('#sr-live');
  if (live) live.textContent = `${S.rvPage.i + 1} / ${pages.length} · ${page.dataset.rvLabel}`;
}

/** 화면 폭이 640px 를 넘나들면 카드 넘기기를 켜고 끈다 */
if (typeof window !== 'undefined' && window.matchMedia) {
  window.matchMedia('(max-width: 640px)').addEventListener('change', () => {
    if (S.route[2] === 'review' && S.deltas[S.route[3]] && !isTyping()) render();
  });
}

// 옆으로 밀어 넘기기. 입력칸에서 시작한 밀기(글 고르기)와 위아래 스크롤은 넘기지 않는다
let rvTouch = null;
if (typeof document.addEventListener === 'function') {
  document.addEventListener('touchstart', (e) => {
    const t = e.target;
    rvTouch = e.touches.length === 1 && t.closest && t.closest('#app .rv-page') && !t.closest('input, textarea, select, [contenteditable]')
      ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
  }, { passive: true });
  document.addEventListener('touchend', (e) => {
    if (!rvTouch || !S.rvPage) return;
    const dx = e.changedTouches[0].clientX - rvTouch.x;
    const dy = e.changedTouches[0].clientY - rvTouch.y;
    rvTouch = null;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    rvGo(S.rvPage.i + (dx < 0 ? 1 : -1));
  }, { passive: true });
}

// ----- 반영 직후 되돌리기 알림 -----
// 반영하면 다음 화 화면으로 넘어간다. 그 화면 아래 알림 줄(#toast)에 'n화를 반영했어요 · 되돌리기'를 10초 띄운다.
// #toast 안에 두어 stackBottom 이 쌓는 저장 띠 · 반영 줄 · 작업 목록 위에 놓이고, #toast 의 aria-live 로 읽힌다.
// 클래스를 .t 로 두지 않아 toast() 가 오래된 알림을 내릴 때 함께 내려가지 않는다

const RV_UNDO_MS = 10000;
let rvUndoTimer = null;

/** 화면 아래 되돌리기 알림과 좁은 화면 탭의 장 모양. 갈래 목차 · 탭 · 한 줄 반영 바는 app.css 에 있다 */
function rvStyle() {
  if (document.getElementById('rv-style')) return;
  const el = document.createElement('style');
  el.id = 'rv-style';
  el.textContent = `
#toast .rv-undo { display: flex; gap: 12px; align-items: center; padding: 8px 8px 8px 16px; border-radius: 10px; background: var(--inverse-bg); color: var(--inverse-ink); font-size: 0.8125rem; line-height: 1.5; box-shadow: 0 6px 24px rgba(0,0,0,0.2); border: 1px solid transparent; }
#toast .rv-undo span { flex: 1; }
#toast .rv-undo .btn { min-height: 40px; white-space: nowrap; }
#toast .rv-undo .x { border: none; background: transparent; color: inherit; cursor: pointer; font-size: 0.875rem; min-width: 40px; min-height: 40px; }
@media (forced-colors: active) { #toast .rv-undo { border-color: CanvasText; } }
.rv-page[hidden] { display: none; }
.rv-page { display: flex; flex-direction: column; gap: 22px; }`;
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
      ${(h.new_places || []).length ? `<section class="card"><h2>새로 나온 장소</h2>${li(h.new_places.map(placeLabel))}</section>` : ''}
      ${withFoot(tlHistory(h), toolLink('timeline', '작품 속 시간'))}${withFoot(scHistory(h), cast)}
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
  /** 좁은 화면 탭: 장 번호, 또는 'prev' · 'next'. 누른 탭에 포커스를 둔다 */
  rvPage(arg) {
    if (!S.rvPage) return;
    const i = arg === 'prev' ? S.rvPage.i - 1 : arg === 'next' ? S.rvPage.i + 1 : Number(arg);
    const count = document.querySelectorAll('#app .rv-page').length;
    const to = Math.min(Math.max(i, 0), count - 1);
    rvGo(to, `#rv-t-${to}`);
  },
  /** 넓은 화면 목차: 그 갈래로 건너뛰고 제목에 포커스 */
  rvJump(key) {
    const g = document.getElementById(`rv-g-${key}`);
    if (!g) return;
    g.scrollIntoView({ block: 'start' });
    const h = g.querySelector('h2');
    if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
    rvSpy(key);
  },
  /** 인물 칸 펴기 · 접기 ('n:c0') */
  rvOpen(key) {
    S.rvOpen = S.rvOpen || {};
    S.rvOpen[key] = !S.rvOpen[key];
    S.focusTarget = `#app [data-action="rvOpen"][data-arg="${key}"]`;
    render();
  },
  /** 본문 근거 열기 · 닫기. arg: JSON [화, 문장, 이름] 또는 '' (닫기) */
  rvQuote(arg) {
    const [n, q, label] = arg ? JSON.parse(arg) : [];
    const same = S.rvQuote && S.rvQuote.q === q && S.rvQuote.n === n;
    const back = S.rvQuote && S.rvQuote.from;
    S.rvQuote = q && !same ? { n, q, label, name: S.name, from: arg } : null;
    S.focusTarget = S.rvQuote ? '#app .rv-quote-panel .rv-close' : back ? `#app [data-action="rvQuote"][data-arg="${CSS.escape(back)}"]` : null;
    render();
    const panel = $('#app .rv-quote-panel');
    if (panel && narrowScreen()) panel.scrollIntoView({ block: 'nearest' });
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
  rvRailRefresh(n);
});

// 체크를 바꾸면 목차 · 탭의 고른 수를 맞춘다 (전체 고른 수 .pick-count 는 app.js 가 맞춘다)
document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.pick && DELTA_PICK.test(el.dataset.pick) && S.route[2] === 'review') rvRailRefresh(Number(S.route[3]));
});

// 경고 띠를 펴 두었으면 다시 그려도 펴 둔다 (toggle 은 거품이 일지 않아 잡는 단계에서 받는다)
document.addEventListener('toggle', (e) => {
  if (e.target.classList && e.target.classList.contains('rv-warn')) S.rvWarnOpen = e.target.open;
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
  const boxes = [...document.querySelectorAll('#app .change input[data-pick]')].filter((b) => DELTA_PICK.test(b.dataset.pick) && !b.disabled);
  const row = t.closest && t.closest('#app .change');
  const i = boxes.findIndex((b) => b === t || (row && row.contains(b)));
  if (!boxes.length || (step === 0 && i < 0)) return;
  e.preventDefault();
  if (step === 0) {
    boxes[i].click();  // change 가 S.picks · 고른 수 · 관계 미리 보기를 맞춘다
    return;
  }
  const next = boxes[i < 0 ? (step > 0 ? 0 : boxes.length - 1) : Math.min(Math.max(i + step, 0), boxes.length - 1)];
  // 좁은 화면에서 다음 항목이 다른 장에 있으면 그 장으로 넘긴 뒤 포커스를 옮긴다
  const page = next.closest('.rv-page[hidden]');
  if (page) {
    rvGo(Number(page.dataset.rvPage), `#${CSS.escape(next.id)}`);
    const b = document.getElementById(next.id);
    if (b) { b.style.scrollMargin = '96px 0 120px'; b.scrollIntoView({ block: 'nearest' }); }
    return;
  }
  next.style.scrollMargin = '96px 0 120px';  // 위 머리 줄과 아래 반영 줄에 가리지 않게
  next.focus();
  next.scrollIntoView({ block: 'nearest' });
});
