/* 단편 → 장편 전환 화면 (#/p/<이름>/convert). app.js 의 S, actions, api, render, input 과 chat.js 의 plotDiff,
   passage.js 의 wordDiff 를 그대로 쓴다. 두 방식이 있다.
   - 이어 쓰기: 단편 전체가 아크 1이 되고, AI 전환 계획(백그라운드 작업 'convert')에서 고른 것만 반영한다.
   - 재구성: 단편을 씨앗으로 장편 앞부분을 다시 짠다(작업 'rebuild'). 새 화마다 옛 화를 그대로 · 다듬기 · 재료로 새로 쓰기 · 새 화
     중 하나로 쓰고, 상태는 1화 시작 전으로 돌아간다. 다듬기 화는 집필 화면에서 AI 다듬기(작업 'rework')를 받는다.
   전환 직전 작품은 서버가 before-serial.json 으로 남겨 되돌릴 수 있다. */
'use strict';

const ENDINGS = [
  ['', 'AI가 고름', '이야기를 보고 둘 중 맞는 쪽을 골라요'],
  ['keep', '닫고 다음 이야기로', '단편 결말은 아크 1의 결말로 그대로 두고, 결말 뒤에 새로 생긴 문제로 이어 가요'],
  ['reopen', '결말 다시 열기', '풀린 줄 알았던 갈등이 더 크게 돌아와요. 이미 쓴 본문은 그대로 두고 떡밥과 사실로 열어요'],
];
const TIER_LABEL = { main: '주역', support: '조연', minor: '단역' };
const ENDING_AT = [
  ['', 'AI가 고름', '이야기 크기를 보고 셋 중 맞는 곳에 둬요'],
  ['arc', '첫 아크 끝', '단편 결말이 장편 첫 고비가 되고, 그 뒤로 더 큰 이야기가 열려요'],
  ['part', '1부 끝', '단편 사건을 1부 내내 늘려 1부 마지막에 결말을 터뜨려요'],
  ['series', '작품 끝', '단편 결말은 작품 마지막으로 미루고, 앞부분은 거기까지 가는 시작이 돼요'],
];
const REBUILD_USE = {
  keep: ['그대로', '옛 화 본문을 그대로 옮겨요. 상태 승인은 단편 때 승인한 변경안을 다시 써요'],
  revise: ['다듬기', '옛 화 본문을 새 자리에 맞게 조금 고쳐요. 집필 화면에서 AI 다듬기를 받아 비교하고 넣어요'],
  rewrite: ['새로 쓰기', '옛 화를 원고 재료로 새로 써요. 본문을 만들 때 옛 원고가 함께 들어가요'],
  new: ['새 화', '단편에 없던 화예요'],
};

Object.assign(S, {
  convStatus: null,   // 서버 /convert: 화수 범위, 전환 기록, 되돌리기를 막는 이유
  convForm: { total: 0, ending: '', note: '' },
  convDraft: null,    // AI 전환 계획 (반영 전)
  convPicks: {},      // 'fs:0', 'sc:0', 'fact:0', 'tier:0', 'ep:12' → 반영할지
  convMode: 'continue',  // continue: 이어 쓰기 / rebuild: 재구성
  rbForm: { total: 0, span: 0, ending_at: '', note: '' },
  rbDraft: null,      // AI 재구성 계획 (반영 전)
  rbNotes: [],        // 재구성 반영 뒤 서버가 알려 준 옮기지 못한 것
  reworks: {},        // 화 번호 → AI 다듬기 제안 { text, reply }
});

// app.js 의 작업 표와 입력 바인딩에 이 화면을 붙인다
JOB_DONE_MSG.convert = '장편 전환 계획이 도착했어요. 확인하고 고른 것만 적용하세요.';
JOB_PAGES.convert = ['convert'];
JOB_LINK.convert = (j) => `#/p/${enc(j.project)}/convert`;
DRAFT_ROOTS.convDraft = () => S.convDraft;
DRAFT_ROOTS.convForm = () => S.convForm;
JOB_DONE_MSG.rebuild = '재구성 계획이 도착했어요. 화 지도를 확인하고 적용하세요.';
JOB_PAGES.rebuild = ['convert'];
JOB_LINK.rebuild = (j) => `#/p/${enc(j.project)}/convert`;
DRAFT_ROOTS.rbDraft = () => S.rbDraft;
DRAFT_ROOTS.rbForm = () => S.rbForm;
JOB_DONE_MSG.rework = (j) => `${j.ep}화 다듬기 제안이 도착했어요. 집필 화면에서 비교하세요.`;
JOB_PAGES.rework = ['write'];
JOB_LINK.rework = (j) => `#/p/${enc(j.project)}/write/${j.ep}`;

async function convertLoad() {
  S.convStatus = await api('GET', `/projects/${enc(S.name)}/convert`).catch(() => null);
  const st = S.convStatus;
  if (st && !S.convForm.total) S.convForm.total = Math.max(st.min, 200);
  if (st && st.rebuild && !S.rbForm.span) Object.assign(S.rbForm, { total: Math.max(st.min, 200), span: st.rebuild.default });
}

function convertResult(j) {
  if (j.kind === 'rebuild') {
    S.rbDraft = j.result;
    S.rbBad = {};
    S.convMode = 'rebuild';
  } else if (j.kind === 'rework') {
    S.reworks[j.ep] = j.result;
  } else {
    S.convDraft = j.result;
    // 확정한 화의 플롯 수정은 작가가 고를 때만 넣는다 (확정된 것은 덮어쓰지 않는다)
    S.convPicks = Object.fromEntries((j.result.episodes || []).filter((e) => ep(e.number) && ep(e.number).status === 'confirmed').map((e) => ['ep:' + e.number, false]));
  }
}

function convPicked(key) {
  return S.convPicks[key] !== false;
}

function convBox(key, label) {
  return `<label class="row" style="align-items:flex-start"><input type="checkbox" data-conv-pick="${esc(key)}"${convPicked(key) ? ' checked' : ''}><span>${label}</span></label>`;
}

function viewConvert() {
  const p = P();
  const st = S.convStatus;
  if (serial()) {
    const c = p.conversion;
    if (!c) return `${header('장편', '장편으로 전환', '이 작품은 처음부터 장편 연재예요.', `<a class="btn" href="${base()}/arc">부 · 아크로</a>`)}`;
    const why = (st && st.undo_blockers) || [];
    const eps = (st && st.undo_eps) || {};
    const rebuilt = c.mode === 'rebuild';
    const links = (list, page) => list.map((n) => `<a href="${base()}/${page}/${n}">${n}화</a>`).join(', ');
    // 이유마다 그 화로 가는 링크와 푸는 방법을 단다. 서버 detail 이 없으면(백업 없음 등) 글로만 보인다
    const whyList = (eps.applied || []).length || (eps.changed || []).length ? `<ul style="padding-left:18px;margin:6px 0 0">
        ${(eps.applied || []).length ? `<li>전환한 뒤 상태를 반영한 화: ${links(eps.applied, 'review')}. 마지막 화부터 상태 승인 화면의 '반영 취소'로 되돌릴 수 있어요.</li>` : ''}
        ${(eps.changed || []).length ? `<li>전환한 뒤 쓰거나 고친 본문: ${links(eps.changed, 'write')}. 집필 화면의 수정 기록에서 되돌리거나, 새로 쓴 본문은 지워야 해요.</li>` : ''}
      </ul>` : `<div>${why.map(esc).join(' / ')}</div>`;
    const desc = rebuilt ? `${fmtDate(c.at)}에 ${c.from_total}화 단편을 씨앗으로 장편 앞부분을 다시 짰어요.`
      : `${fmtDate(c.at)}에 ${c.from_total}화 단편을 장편으로 바꿨어요. 단편 1~${c.arc_end}화가 아크 1이에요.`;
    return `${header('장편', rebuilt ? '단편에서 재구성한 작품' : '단편에서 전환한 작품', desc, `<a class="btn primary" href="${base()}/arc">부 · 아크로</a>`)}
      ${rebuilt ? rebuildStatus(p) : ''}
      <section class="card">
        <h2>되돌리기</h2>
        <div class="small">${rebuilt ? `단편 결말: ${esc(ENDING_AT.find((x) => x[0] === c.ending)?.[1] || c.ending)}` : `결말 처리: ${esc(ENDINGS.find((x) => x[0] === c.ending)?.[1] || c.ending)}`}</div>
        ${why.length ? `<div class="note warn" id="undo-why">되돌리면 잃는 것이 있어 막아 두었어요.${whyList}</div>`
          : '<div class="note plain">전환한 뒤 새로 쓰거나 반영한 화가 없어서 전환 전 단편으로 그대로 돌아갈 수 있어요. 전환한 뒤 고친 설정과 플롯은 사라지고 전환 직전 값으로 돌아가요.</div>'}
        <div class="row"><button class="btn danger" data-action="convertUndo"${why.length ? ' disabled aria-describedby="undo-why"' : ''}>단편으로 되돌리기</button></div>
      </section>`;
  }
  const written = p.episodes.filter((e) => e.text).length;
  const end = st ? st.end : 0;
  const keepList = [
    `본문 ${written}화와 화별 요약`,
    `인물 ${p.characters.length}명과 지금 상태`,
    `관계 ${p.relationships.length}쌍과 사건 기록`,
    '문체 프로필',
    `인과율 요소 ${(p.elements || []).length}개`,
    `복선 ${p.foreshadows.length}개와 확정 사실 ${p.facts.length}개`,
  ];
  const form = S.convForm;
  const canRebuild = !!(st && st.rebuild);
  const mode = canRebuild ? S.convMode : 'continue';
  const modes = canRebuild ? `<div class="seg" role="group" aria-label="전환 방식">
      <button type="button" aria-pressed="${mode === 'continue'}" data-action="convertMode" data-arg="continue">이어 쓰기</button>
      <button type="button" aria-pressed="${mode === 'rebuild'}" data-action="convertMode" data-arg="rebuild">재구성</button></div>` : '';
  const top = header('장편', '장편으로 전환', '다 쓴 단편이나 쓰는 중인 단편을 200~300화 장편 연재로 늘려요.', `${modes}<a class="btn" href="${base()}/arc">기승전결로</a>`);
  if (mode === 'rebuild') return `${top}${rebuildForm(p, st)}${S.rbDraft ? rebuildProposal(S.rbDraft) : ''}`;
  const btn = jobBtn('convert', null, S.convDraft ? '전환 계획 다시 받기' : 'AI로 전환 계획 만들기');
  const formCard = `<section class="card">
      <h2>단편 → 장편 · 이어 쓰기</h2>
      ${canRebuild ? '<div class="small">단편을 그대로 앞에 두고 뒤로 늘려요. 단편을 장편 흐름에 맞게 다시 짜려면 위에서 <strong>재구성</strong>을 고르세요.</div>' : ''}
      ${end ? `<div class="note info">단편 1~${end}화가 그대로 <strong>아크 1</strong>이 되고, 그 뒤를 부와 아크로 늘려요. 이미 쓴 화의 구조는 바꾸지 않아요.</div>`
        : '<div class="note warn">아직 기승전결 구조가 없어요. 전환하면 빈 장편이 되고, 부 · 아크 화면에서 처음부터 기획해요.</div>'}
      <div class="grid-2">
        <div class="field"><span class="label">그대로 남는 것</span><ul class="small" style="margin:4px 0 0;padding-left:18px">${keepList.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
        <div class="field"><span class="label">바뀌는 것</span><ul class="small" style="margin:4px 0 0;padding-left:18px">
          <li>형식: 단편 → 장편 연재 (부 → 아크 → 화)</li><li>총 화수: ${p.meta.target_episodes}화 → 아래에서 정한 화수</li>
          <li>작품 전체 기승전결 → 아크 1의 기승전결</li><li>고른 인물 비중, 복선 범위, 새 떡밥과 사실</li></ul></div>
      </div>
      <div class="grid-2">${input(`장편 총 화수${st ? ` (${st.min}~${st.max})` : ''}`, 'total', { root: 'convForm', type: 'number', min: st ? st.min : 8, max: st ? st.max : 1000 })}<div></div></div>
      <div class="field"><span class="label">결말 처리</span>
        ${ENDINGS.map(([k, label, hint]) => `<label class="row"><input type="radio" name="conv-ending" data-conv-ending="${k}"${form.ending === k ? ' checked' : ''}><span><strong>${label}</strong> <span class="small">${hint}</span></span></label>`).join('')}
      </div>
      ${input('장편에 바라는 것 (선택)', 'note', { root: 'convForm', rows: 3, autogrow: true, placeholder: '예: 무대를 바다 건너 북부로 넓히고, 오빠가 살아 있다는 쪽으로' })}
      <div class="row"><button class="btn primary" data-action="convertPlan"${btn.attr}>${btn.label}</button><span class="small">적용 전에 미리 보고 고를 수 있어요. 전환 직전 작품은 따로 남겨 되돌릴 수 있어요.</span></div>
    </section>`;
  return `${top}
    ${formCard}${S.convDraft ? convertProposal(S.convDraft) : ''}`;
}

function convertProposal(d) {
  const p = P();
  const a = d.arc;
  const ending = ENDINGS.find((x) => x[0] === d.ending);
  const fsIds = new Map(p.foreshadows.map((f) => [f.id, f]));
  const sections = [];
  if (p.arc.length) {
    sections.push(`<div class="field"><span class="label">아크 1 (단편 1~${a.end_ep}화)</span>
      <div class="grid-2">${input('아크 제목', 'arc.title', { root: 'convDraft' })}${input('보상 (사이다)', 'arc.payoff', { root: 'convDraft', rows: 2, autogrow: true })}</div>
      <div class="grid-2">${input('아크 목표', 'arc.goal', { root: 'convDraft', rows: 2, autogrow: true })}${input('갈등', 'arc.conflict', { root: 'convDraft', rows: 2, autogrow: true })}</div>
      <div class="act-strip">${a.acts.map((x) => `<div class="act-head ${actClass(x.name)}"><div class="between"><strong>${x.name}</strong><span class="act-meta">${x.start_ep}~${x.end_ep}화</span></div><div class="small">${esc(x.goal)}</div></div>`).join('')}</div>
      ${a.summary ? input('아크 1 요약 (다 쓴 단편이라 함께 제안했어요. 앞으로 이 구간 대신 프롬프트에 들어가요)', 'arc.summary', { root: 'convDraft', rows: 5, autogrow: true }) : '<div class="small">단편을 다 쓰고 상태까지 반영하면 아크 1 요약을 만들 수 있어요.</div>'}
    </div>`);
  }
  sections.push(d.parts.length ? `<div class="field"><span class="label">부 구성 (총 ${d.total_episodes}화)</span>
      ${d.parts.map((x, i) => `<div class="part-draft">
        <div class="grid-2">${input(`${x.number}부 제목`, `parts.${i}.title`, { root: 'convDraft' })}<div class="grid-2">${input('시작 화', `parts.${i}.start_ep`, { root: 'convDraft', type: 'number' })}${input('끝 화', `parts.${i}.end_ep`, { root: 'convDraft', type: 'number' })}</div></div>
        ${input('부 목표', `parts.${i}.goal`, { root: 'convDraft', rows: 2, autogrow: true })}
        ${input('아크 후보 (새 인물 계획 포함)', `parts.${i}.arc_ideas`, { root: 'convDraft', kind: 'list', rows: 3, autogrow: true })}
      </div>`).join('')}</div>` : '<div class="note warn">부 구성이 없어요. 전환한 뒤 부 · 아크 화면에서 부 구성을 제안받을 수 있어요.</div>');
  if (d.foreshadows.length) {
    sections.push(`<div class="field"><span class="label">새 장기 떡밥</span>${d.foreshadows.map((f, i) => convBox('fs:' + i,
      `<strong>${esc(f.description)}</strong> <span class="small">${esc(f.id)} · ${f.scope === 'series' ? '작품 끝까지' : '한 부 안에서'} · ${f.planted_ep}화에 실마리</span>`)).join('')}</div>`);
  }
  if (d.scopes.length) {
    sections.push(`<div class="field"><span class="label">열린 복선 범위 넓히기</span>${d.scopes.map((s, i) => convBox('sc:' + i,
      `${esc(fsIds.get(s.id)?.description || s.id)} <span class="small">${esc(fsIds.get(s.id)?.scope || '')} → ${esc(s.scope)}${s.reason ? ' · ' + esc(s.reason) : ''}</span>`)).join('')}</div>`);
  }
  if (d.facts.length) {
    sections.push(`<div class="field"><span class="label">더할 확정 사실</span>${d.facts.map((f, i) => convBox('fact:' + i, esc(f))).join('')}</div>`);
  }
  if (d.tiers.length) {
    sections.push(`<div class="field"><span class="label">인물 비중 <span class="hint">주역은 매 화 설정 전체가 들어가고, 조연 · 단역은 나오는 화에만 들어가요</span></span>${d.tiers.map((t, i) => {
      const c = p.characters.find((x) => x.id === t.id);
      return convBox('tier:' + i, `<strong>${esc(c ? c.name : t.id)}</strong> ${TIER_LABEL[c ? c.tier : 'main']} → ${TIER_LABEL[t.tier]}${t.reason ? ` <span class="small">${esc(t.reason)}</span>` : ''}`);
    }).join('')}</div>`);
  }
  if (d.episodes.length) {
    sections.push(`<div class="field"><span class="label">본문이 없는 화의 플롯 수정 <span class="hint">확정한 화도 바꾸면 다시 초안이 돼요</span></span>${d.episodes.map((e) =>
      `<div class="diff-act">${convBox('ep:' + e.number, `<strong>${e.number}화</strong> ${esc(e.title)}${ep(e.number) && ep(e.number).status === 'confirmed' ? ' <span class="chip confirmed">확정한 화 · 기본으로 빼 둠</span>' : ''}`)}<div class="diff">${plotDiff(e)}</div></div>`).join('')}</div>`);
  }
  return `<section class="card proposal">
      <div class="between"><h2>전환 계획 <span class="chip ai">적용 전</span> <span class="chip">${esc(ending ? ending[1] : d.ending)}</span></h2>
        <div class="row"><button class="btn small" data-action="convertDrop">버리기</button><button class="btn small primary" data-action="convertApply">고른 것으로 장편 전환</button></div></div>
      ${d.reply ? `<div class="note info">${esc(d.reply).replace(/\n/g, '<br>')}</div>` : ''}
      ${sections.join('')}
      <div class="small">전환하면 부 · 아크 화면에서 ${p.arc.length ? `${a.end_ep + 1}화부터 ` : ''}다음 아크를 기획해 이어 가요.</div>
    </section>`;
}

Object.assign(actions, {
  async convertPlan() {
    const total = Number(S.convForm.total) || 0;
    const st = S.convStatus;
    if (st && (total < st.min || total > st.max)) return toast(`장편 총 화수는 ${st.min}~${st.max}화로 정하세요`, true);
    await startJob('convert', null, { length: total, ending: S.convForm.ending, note: S.convForm.note || '' });
  },
  convertDrop() {
    if (!confirmDrop('AI 전환 계획')) return;
    S.convDraft = null;
    render();
  },
  async convertApply() {
    const d = JSON.parse(JSON.stringify(S.convDraft));
    const keep = (prefix) => (_, i) => convPicked(prefix + i);
    d.foreshadows = d.foreshadows.filter(keep('fs:'));
    d.scopes = d.scopes.filter(keep('sc:'));
    d.facts = d.facts.filter(keep('fact:'));
    d.tiers = d.tiers.filter(keep('tier:'));
    d.episodes = d.episodes.filter((e) => convPicked('ep:' + e.number));
    if (!confirm(`총 ${d.total_episodes}화 장편으로 전환할까요? 전환 직전 작품은 따로 남겨 되돌릴 수 있어요.`)) return;
    await run('전환하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/convert/apply`, d);
      S.convDraft = null;
      S.convPicks = {};
      // 단편(아크 1)을 다 반영하지 않았으면 남은 화부터 마치도록 아크 1을 연다. 다음 아크 기획은 반영된 줄거리를 읽는다
      const end = (P().conversion && P().conversion.arc_end) || 0;
      const left = Array.from({ length: end }, (_, i) => i + 1).filter((n) => !ep(n) || ep(n).status !== 'finalized');
      S.selArc = left.length ? 1 : 'next';
      toast(left.length ? `장편으로 바꿨어요. 단편은 아크 1이 됐어요. 아크 1의 남은 화(${rangeText(left)}화)를 마친 뒤 다음 아크를 기획하세요.`
        : '장편으로 바꿨어요. 단편은 아크 1이 됐어요. 이제 다음 아크를 기획하세요.');
      location.hash = `${base()}/arc`;
    });
  },
  async convertUndo() {
    if (!confirm('전환 전 단편으로 되돌릴까요? 전환한 뒤 고친 설정과 플롯은 사라지고 전환 직전 값으로 돌아가요.')) return;
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/convert/undo`);
      S.selArc = null;
      toast('단편으로 되돌렸어요.');
      location.hash = `${base()}/arc`;
    });
  },
});

// ----- 재구성 -----

function rebuildForm(p, st) {
  const f = S.rbForm;
  const r = st.rebuild;
  const btn = jobBtn('rebuild', null, S.rbDraft ? '재구성 계획 다시 받기' : 'AI로 재구성 계획 만들기');
  const old = p.episodes.length;
  return `<section class="card">
      <h2>단편 → 장편 · 재구성</h2>
      <div class="note info">단편 ${old}화를 <strong>씨앗</strong>으로 장편 앞부분(아크 몇 개)을 다시 짜요. 옛 화 하나가 보통 새 2~4화로 늘어나고,
        1~3화는 웹소설 첫 화 훅에 맞게 다시 열어요. 옛 본문은 화마다 그대로 · 다듬기 · 재료로 새로 쓰기 중 하나로 써요.</div>
      <div class="grid-2">
        <div class="field"><span class="label">그대로 남는 것</span><ul class="small" style="margin:4px 0 0;padding-left:18px">
          <li>설정, 인물(말투 · 성격), 문체 프로필</li><li>옛 단편 원고 전부 (보관함에 남아 재료로 씀)</li>
          <li>인과율 요소 · 이야기 줄기 (새 화 번호로 옮김)</li></ul></div>
        <div class="field"><span class="label">바뀌는 것</span><ul class="small" style="margin:4px 0 0;padding-left:18px">
          <li>화 번호와 순서 (새 화 지도대로)</li><li>인물 상태 · 관계 · 확정 사실 · 복선: 1화 시작 전으로 돌린 뒤 새 순서대로 다시 반영</li>
          <li>그대로 둔 화는 단편 때 승인한 상태 변경안을 번호만 바꿔 다시 써요 (AI를 부르지 않아요)</li></ul></div>
      </div>
      <div class="grid-2">${input(`장편 총 화수 (${st.min}~${st.max})`, 'total', { root: 'rbForm', type: 'number', min: st.min, max: st.max })}
        ${input(`다시 짤 앞부분 화수 (${r.min}~${r.max}, 기본 ${r.default})`, 'span', { root: 'rbForm', type: 'number', min: r.min, max: r.max })}</div>
      <div class="field"><span class="label">단편 결말을 둘 곳</span>
        ${ENDING_AT.map(([k, label, hint]) => `<label class="row"><input type="radio" name="rb-ending" data-rb-ending="${k}"${f.ending_at === k ? ' checked' : ''}><span><strong>${label}</strong> <span class="small">${hint}</span></span></label>`).join('')}
      </div>
      ${input('재구성에 바라는 것 (선택)', 'note', { root: 'rbForm', rows: 3, autogrow: true, placeholder: `예: 1화는 사건 한가운데서 열고, ${exName(1)}의 비밀은 1부 중반까지 감춰 줘` })}
      <div class="row"><button class="btn primary" data-action="rebuildPlan"${btn.attr}>${btn.label}</button><span class="small">적용 전에 화 지도를 보고 고칠 수 있어요. 재구성 직전 작품은 따로 남겨 되돌릴 수 있어요.</span></div>
    </section>`;
}

function rbUseSelect(i, use) {
  return `<select aria-label="쓰는 방식" data-rb-use="${i}">${Object.entries(REBUILD_USE).map(([k, [label]]) => `<option value="${k}"${k === use ? ' selected' : ''}>${label}</option>`).join('')}</select>`;
}

function rebuildProposal(d) {
  const p = P();
  const where = ENDING_AT.find((x) => x[0] === d.ending_at);
  const old = new Map(p.episodes.map((e) => [e.plot.number, e]));
  const count = (u) => d.episodes.filter((x) => x.use === u).length;
  const arcs = d.arcs.map((a, i) => `<div class="part-draft">
      <div class="grid-2">${input(`아크 ${a.number} 제목 (${a.start_ep}~${a.end_ep}화)`, `arcs.${i}.title`, { root: 'rbDraft' })}${input('보상 (사이다)', `arcs.${i}.payoff`, { root: 'rbDraft', rows: 2, autogrow: true })}</div>
      <div class="grid-2">${input('아크 목표', `arcs.${i}.goal`, { root: 'rbDraft', rows: 2, autogrow: true })}${input('갈등', `arcs.${i}.conflict`, { root: 'rbDraft', rows: 2, autogrow: true })}</div>
      <div class="act-strip">${a.acts.map((x) => `<div class="act-head ${actClass(x.name)}"><div class="between"><strong>${x.name}</strong><span class="act-meta">${x.start_ep}~${x.end_ep}화</span></div><div class="small">${esc(x.goal)}</div></div>`).join('')}</div>
    </div>`).join('');
  const parts = d.parts.length ? d.parts.map((x, i) => `<div class="part-draft">
      <div class="grid-2">${input(`${x.number}부 제목`, `parts.${i}.title`, { root: 'rbDraft' })}<div class="grid-2">${input('시작 화', `parts.${i}.start_ep`, { root: 'rbDraft', type: 'number' })}${input('끝 화', `parts.${i}.end_ep`, { root: 'rbDraft', type: 'number' })}</div></div>
      ${input('부 목표', `parts.${i}.goal`, { root: 'rbDraft', rows: 2, autogrow: true })}
    </div>`).join('') : '<div class="note warn">부 구성이 없어요. 재구성한 뒤 부 · 아크 화면에서 부 구성을 제안받을 수 있어요.</div>';
  const rows = d.episodes.map((x, i) => {
    const src = x.sources.map((s) => `<a href="#" data-action="rbPeek" data-arg="${s}" title="${esc(old.get(s)?.plot.title || '')}">${s}화</a>`).join(', ');
    return `<tr class="rb-${x.use}">
      <td class="mono" data-label="새 화">${x.number}</td>
      <td data-label="쓰는 방식">${rbUseSelect(i, x.use)}</td>
      <td data-label="단편 화"><input aria-label="쓰는 단편 화" value="${esc(x.sources.join(', '))}" data-rb-src="${i}" placeholder="없음" style="width:72px"${x.use === 'new' ? ' disabled title="새 화는 단편 화를 쓰지 않아요"' : ''}>${src ? `<div class="small">${src}</div>` : ''}${((S.rbBad || {})[i] || []).length ? `<div class="small warn-text">단편에 없는 화: ${S.rbBad[i].join(', ')}화</div>` : ''}</td>
      <td data-label="제목 · 내용"><input aria-label="제목" value="${esc(x.title)}" data-bind="episodes.${i}.title" data-kind="text" data-root="rbDraft">
        <textarea aria-label="내용" rows="2" data-bind="episodes.${i}.summary" data-kind="text" data-root="rbDraft">${esc(x.summary)}</textarea>
        ${x.use === 'revise' || x.use === 'rewrite' ? `<input aria-label="메모" value="${esc(x.note)}" data-bind="episodes.${i}.note" data-kind="text" data-root="rbDraft" placeholder="${x.use === 'revise' ? '무엇을 고칠지' : '옛 화에서 살릴 것'}">` : ''}</td>
    </tr>`;
  }).join('');
  const peek = S.rbPeek && old.get(S.rbPeek);
  const fsBox = d.foreshadows.length ? `<div class="field"><span class="label">새 장기 떡밥</span>${d.foreshadows.map((f, i) => convBox('rbfs:' + i,
    `<strong>${esc(f.description)}</strong> <span class="small">${esc(f.id)} · ${f.scope === 'series' ? '작품 끝까지' : '한 부 안에서'} · 새 ${f.planted_ep}화에 실마리</span>`)).join('')}</div>` : '';
  const tierBox = d.tiers.length ? `<div class="field"><span class="label">인물 비중</span>${d.tiers.map((t, i) => {
    const c = p.characters.find((x) => x.id === t.id);
    return convBox('rbtier:' + i, `<strong>${esc(c ? c.name : t.id)}</strong> ${TIER_LABEL[c ? c.tier : 'main']} → ${TIER_LABEL[t.tier]}${t.reason ? ` <span class="small">${esc(t.reason)}</span>` : ''}`);
  }).join('')}</div>` : '';
  return `<section class="card proposal">
      <div class="between"><h2>재구성 계획 <span class="chip ai">적용 전</span> <span class="chip">단편 결말 → ${esc(where ? where[1] : d.ending_at)}</span></h2>
        <div class="row"><button class="btn small" data-action="rebuildDrop">버리기</button><button class="btn small primary" data-action="rebuildApply">이 계획으로 재구성</button></div></div>
      ${d.reply ? `<div class="note info">${esc(d.reply).replace(/\n/g, '<br>')}</div>` : ''}
      <div class="small">총 ${d.total_episodes}화 중 앞 ${d.episodes.length}화를 다시 짰어요 · 그대로 ${count('keep')} · 다듬기 ${count('revise')} · 새로 쓰기 ${count('rewrite')} · 새 화 ${count('new')}${d.dropped.length ? ` · 쓰지 않는 단편 화 ${d.dropped.join(', ')}` : ''}</div>
      <div class="field"><span class="label">앞 아크</span>${arcs}</div>
      <div class="field"><span class="label">부 구성</span>${parts}</div>
      <div class="field"><span class="label">화 지도 <span class="hint">${Object.values(REBUILD_USE).map(([a, b]) => `${a}: ${b}`).join(' · ')}</span></span>
        <div class="table-wrap rb-wrap"><table class="rb-map"><thead><tr><th>새 화</th><th>쓰는 방식</th><th>단편 화</th><th>제목 · 내용</th></tr></thead><tbody>${rows}</tbody></table></div>
        ${peek ? `<div class="note plain"><div class="between"><strong>단편 ${S.rbPeek}화 ${esc(peek.plot.title)}</strong><button class="btn small" data-action="rbPeek" data-arg="0">닫기</button></div><div class="small">${esc(peek.summary || peek.plot.summary)}</div></div>` : ''}
      </div>
      ${fsBox}${tierBox}
      <div class="small">재구성하면 새 화(초안)의 플롯은 부 · 아크 화면에서 'AI로 플롯 초안'으로 채워요. 지도 내용이 프롬프트에 들어가요.</div>
    </section>`;
}

function rebuildStatus(p) {
  const a = p.archive;
  if (!a) return '';
  const by = new Map(p.episodes.map((e) => [e.plot.number, e]));
  const todo = (u) => a.map.filter((x) => x.use === u);
  // 다듬기 화 중 본문이 옛 원문과 다르면 이미 다듬었다 (rebuildNote 의 done 과 같은 규칙)
  const reworked = (x) => {
    const e = by.get(x.number);
    const orig = a.episodes.find((o) => o.plot.number === x.sources[0]);
    return !!e && !!orig && e.text !== orig.text;
  };
  const open = todo('revise').filter((x) => by.get(x.number) && by.get(x.number).status !== 'finalized');
  const revise = open.filter((x) => !reworked(x));
  const polished = open.filter(reworked);
  const drafts = a.map.filter((x) => by.get(x.number) && by.get(x.number).status === 'draft').length;
  // 반영 직후 받은 목록이 없으면(새로 불러옴) 작품에 남긴 목록을 쓴다
  const kept = S.rbNotes.length ? S.rbNotes : (p.conversion && p.conversion.notes) || [];
  const notes = kept.length ? `<div class="note warn"><strong>옮기지 못한 것</strong><ul style="padding-left:18px;margin-top:6px">${kept.map((n) => `<li>${esc(n)}</li>`).join('')}</ul></div>` : '';
  return `${notes}<section class="card">
      <h2>재구성한 앞부분 (${a.map.length}화)</h2>
      <div class="small">그대로 ${todo('keep').length} · 다듬기 ${todo('revise').length} · 새로 쓰기 ${todo('rewrite').length} · 새 화 ${todo('new').length}${a.dropped.length ? ` · 쓰지 않는 단편 화 ${a.dropped.join(', ')}` : ''}</div>
      <ol class="small" style="padding-left:18px;margin:6px 0 0;line-height:1.7">
        ${drafts ? `<li>플롯 초안이 필요한 화 ${drafts}개: <a href="${base()}/arc">부 · 아크</a>에서 아크마다 'AI로 플롯 초안'을 받고 확정하세요.</li>` : ''}
        ${revise.length ? `<li>다듬기 화 ${revise.map((x) => `<a href="${base()}/write/${x.number}">${x.number}화</a>`).join(', ')}: 집필 화면에서 AI 다듬기를 받아 비교하고 넣으세요.</li>` : ''}
        ${polished.length ? `<li>다듬음: ${polished.map((x) => `<a href="${base()}/write/${x.number}">${x.number}화</a>`).join(', ')}. 다듬은 본문이 들어가 있어요. 차례가 되면 상태를 반영하세요.</li>` : ''}
        <li>1화부터 차례로 쓰고 상태를 반영해요. 그대로 둔 화는 상태 승인에서 단편 때 변경안이 바로 나와요.</li>
      </ol>
    </section>`;
}

/** 집필 화면 위쪽 안내: 재구성에서 이 화를 어떻게 쓰기로 했는지, 다듬기 화면 AI 다듬기. */
function rebuildNote(n) {
  const a = P().archive;
  const x = a && a.map.find((m) => m.number === n);
  if (!x || x.use === 'new') return '';
  const e = ep(n);
  const src = x.sources.map((s) => `단편 ${s}화`).join(', ');
  if (x.use === 'keep') return `<div class="note plain">재구성: ${src} 본문을 <strong>그대로</strong> 옮긴 화예요. 상태 승인에서 단편 때 승인한 변경안을 번호만 바꿔 다시 써요.</div>`;
  if (x.use === 'rewrite') {
    return e.text ? '' : `<div class="note plain">재구성: ${src}를 <strong>재료로 새로 쓰는</strong> 화예요. 본문을 만들 때 옛 원고가 '원고 재료'로 함께 들어가요.${x.note ? ` 살릴 것: ${esc(x.note)}` : ''}</div>`;
  }
  if (e.status === 'finalized') return '';
  const rw = S.reworks[n];
  const orig = a.episodes.find((o) => o.plot.number === x.sources[0]);
  const done = orig && e.text !== orig.text;  // 이미 다듬었거나 직접 고쳤다
  const b = jobBtn('rework', n, rw || done ? '다시 다듬기' : 'AI로 다듬기');
  const head = `<div class="between"><span>재구성: ${src} 본문을 <strong>다듬어</strong> 쓰는 화예요.${done && !rw ? ' 다듬은 본문이 들어가 있어요.' : ''}${x.note ? ` 고칠 것: ${esc(x.note)}` : ''}</span>
    <button class="btn small${rw || done ? '' : ' primary'}" data-action="reworkPlan" data-arg="${n}"${b.attr}>${b.label}</button></div>`;
  if (!rw) return `<div class="note ${done ? 'plain' : 'info'}">${head}</div>`;
  return `<div class="note info" style="display:flex;flex-direction:column;gap:8px">${head}
    ${rw.reply ? `<div class="small">${esc(rw.reply)}</div>` : ''}
    <div class="small" data-rework-basis="${n}">${reworkBasis(rw)}</div>
    <div class="pdiff" data-rework-diff="${n}" style="max-height:360px;overflow:auto;white-space:pre-wrap;font-family:var(--serif);font-size:0.875rem;line-height:1.8">${reworkDiff(e.text, rw.edited ?? rw.text)}</div>
    <details><summary class="small">넣기 전에 손보기</summary><textarea rows="10" data-rework="${n}" aria-label="다듬은 본문">${esc(rw.edited ?? rw.text)}</textarea></details>
    <div class="row"><button class="btn small" data-action="reworkDrop" data-arg="${n}">버리기</button><button class="btn small primary" data-action="reworkAccept" data-arg="${n}">이 본문으로 바꾸기</button><span class="small">고치기 전후는 수정 기록에 남아 되돌릴 수 있어요.</span></div>
  </div>`;
}

/** 비교가 무엇을 기준으로 하는지. 손보기 칸을 고쳤으면 실제로 들어갈 손본 글과 비교한다. */
function reworkBasis(rw) {
  return rw.edited != null && rw.edited !== rw.text ? '<strong>손본 글 기준</strong> · 지금 본문과 넣을 글을 비교해요' : '지금 본문과 AI 다듬기 제안을 비교해요';
}

/** 긴 본문 비교: 앞뒤 같은 부분은 접고 바뀐 가운데만 단어 단위로 비교한다. */
function reworkDiff(a, b) {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  let j = 0;
  while (j < a.length - i && j < b.length - i && a[a.length - 1 - j] === b[b.length - 1 - j]) j++;
  const cut = (t) => (t.length > 300 ? `<span class="small">… (같은 부분 ${t.length.toLocaleString()}자 접음) …</span>` : esc(t));
  const head = a.slice(0, i);
  const tail = a.slice(a.length - j);
  const keepHead = head.lastIndexOf('\n', head.length - 1) + 1;  // 바뀐 곳이 든 문단 처음부터 보여 준다
  return cut(head.slice(0, keepHead)) + wordDiff(a.slice(keepHead, a.length - j), b.slice(keepHead, b.length - j)) + cut(tail);
}

Object.assign(actions, {
  convertMode(mode) {
    S.convMode = mode;
    render();
  },
  async rebuildPlan() {
    const f = S.rbForm;
    const st = S.convStatus;
    const total = Number(f.total) || 0;
    const span = Number(f.span) || 0;
    if (st && (total < st.min || total > st.max)) return toast(`장편 총 화수는 ${st.min}~${st.max}화로 정하세요`, true);
    if (st && st.rebuild && (span < st.rebuild.min || span > Math.min(st.rebuild.max, total))) return toast(`다시 짤 앞부분은 ${st.rebuild.min}~${Math.min(st.rebuild.max, total)}화로 정하세요`, true);
    await startJob('rebuild', null, { length: total, span, ending: f.ending_at, note: f.note || '' });
  },
  rebuildDrop() {
    if (!confirmDrop('AI 재구성 계획')) return;
    S.rbDraft = null;
    S.rbPeek = 0;
    render();
  },
  rbPeek(n) {
    S.rbPeek = Number(n) || 0;
    render();
  },
  async rebuildApply() {
    const d = JSON.parse(JSON.stringify(S.rbDraft));
    d.foreshadows = d.foreshadows.filter((_, i) => convPicked('rbfs:' + i));
    d.tiers = d.tiers.filter((_, i) => convPicked('rbtier:' + i));
    if (!confirm(`총 ${d.total_episodes}화 장편으로 재구성할까요? 화 번호가 바뀌고 인물 상태와 관계는 1화 시작 전으로 돌아가요. 재구성 직전 작품은 따로 남겨 되돌릴 수 있어요.`)) return;
    await run('재구성하는 중', async () => {
      await saveIfDirty();
      const out = await api('POST', `/projects/${enc(S.name)}/convert/rebuild/apply`, d);
      S.project = out.project;
      S.rbNotes = out.notes;
      S.rbDraft = null;
      S.convPicks = {};
      S.reworks = {};
      await convertLoad();
      toast('재구성했어요. 새 화 플롯 초안을 받고 1화부터 차례로 쓰세요.');
      render();
    });
  },
  async reworkPlan(n) {
    await startJob('rework', Number(n));
  },
  reworkDrop(n) {
    if (!confirmDrop(`${n}화 AI 다듬기 제안`)) return;
    delete S.reworks[n];
    render();
  },
  async reworkAccept(n) {
    const rw = S.reworks[n];
    if (!rw) return;
    await run('바꾸는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/rework`, { text: rw.edited ?? rw.text, proposed: rw.text });
      delete S.reworks[n];
      delete S.textDraft[n];
      toast(`${n}화 본문을 다듬은 글로 바꿨어요.`);
      render();
    });
  },
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (!(t.dataset && t.dataset.rework && S.reworks[t.dataset.rework])) return;
  const n = t.dataset.rework;
  const rw = S.reworks[n];
  rw.edited = t.value;
  // 손보는 칸은 다시 그리지 않고 비교 칸만 바꾼다 (입력 중 포커스 · 커서를 지킨다)
  clearTimeout(S.reworkDiffTimer);
  S.reworkDiffTimer = setTimeout(() => {  // 긴 본문이라 타자마다 비교하지 않고 잠깐 멈췄을 때 한 번
    const diff = document.querySelector(`[data-rework-diff="${n}"]`);
    const basis = document.querySelector(`[data-rework-basis="${n}"]`);
    if (diff && ep(Number(n))) diff.innerHTML = reworkDiff(ep(Number(n)).text, rw.edited);
    if (basis) basis.innerHTML = reworkBasis(rw);
  }, 200);
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || S.route[2] !== 'convert') return;
  if (t.dataset.rbEnding !== undefined && t.checked) S.rbForm.ending_at = t.dataset.rbEnding;
  if (t.dataset.rbUse !== undefined && S.rbDraft) {
    const x = S.rbDraft.episodes[Number(t.dataset.rbUse)];
    x.use = t.value;
    if (x.use === 'new') x.sources = [];  // 새 화는 단편 화를 쓰지 않는다 (칸도 꺼진다)
    render();
  }
  if (t.dataset.rbSrc !== undefined && S.rbDraft) {
    const nums = [...new Set(t.value.split(/[^0-9]+/).filter(Boolean).map(Number))];
    const have = new Set(P().episodes.map((x) => x.plot.number));
    S.rbDraft.episodes[Number(t.dataset.rbSrc)].sources = nums.filter((n) => have.has(n));
    // 단편에 없는 화는 서버가 말없이 버린다. 빼 두고 그 칸 아래에 알린다
    S.rbBad = { ...(S.rbBad || {}), [t.dataset.rbSrc]: nums.filter((n) => !have.has(n)) };
    render();
  }
  if (t.dataset.convPick) S.convPicks[t.dataset.convPick] = t.checked;
  if (t.dataset.convEnding !== undefined && t.checked) S.convForm.ending = t.dataset.convEnding;
});
