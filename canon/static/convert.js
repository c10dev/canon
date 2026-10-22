/* 단편 → 장편 전환 화면 (#/p/<이름>/convert). app.js 의 S, actions, api, render, input 과 chat.js 의 plotDiff 를 그대로 쓴다.
   단편 전체가 아크 1이 되고, AI 전환 계획(백그라운드 작업 'convert')에서 고른 것만 반영한다.
   전환 직전 작품은 서버가 before-serial.json 으로 남겨 되돌릴 수 있다. */
'use strict';

const ENDINGS = [
  ['', 'AI 가 고름', '이야기를 보고 둘 중 맞는 쪽을 골라요'],
  ['keep', '닫고 다음 이야기로', '단편 결말은 아크 1의 결말로 그대로 두고, 결말 뒤에 새로 생긴 문제로 이어 가요'],
  ['reopen', '결말 다시 열기', '풀린 줄 알았던 갈등이 더 크게 돌아와요. 이미 쓴 본문은 그대로 두고 떡밥과 사실로 엽니다'],
];
const TIER_LABEL = { main: '주역', support: '조연', minor: '단역' };

Object.assign(S, {
  convStatus: null,   // 서버 /convert: 화수 범위, 전환 기록, 되돌리기를 막는 이유
  convForm: { total: 0, ending: '', note: '' },
  convDraft: null,    // AI 전환 계획 (반영 전)
  convPicks: {},      // 'fs:0', 'sc:0', 'fact:0', 'tier:0', 'ep:12' → 반영할지
});

// app.js 의 작업 표와 입력 바인딩에 이 화면을 붙인다
JOB_DONE_MSG.convert = '장편 전환 계획이 도착했습니다. 확인하고 고른 것만 반영하세요.';
JOB_PAGES.convert = ['convert'];
JOB_LINK.convert = (j) => `#/p/${enc(j.project)}/convert`;
DRAFT_ROOTS.convDraft = () => S.convDraft;
DRAFT_ROOTS.convForm = () => S.convForm;

async function convertLoad() {
  S.convStatus = await api('GET', `/projects/${enc(S.name)}/convert`).catch(() => null);
  const st = S.convStatus;
  if (st && !S.convForm.total) S.convForm.total = Math.max(st.min, 200);
}

function convertResult(j) {
  S.convDraft = j.result;
  S.convPicks = {};
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
    return `${header('장편', '단편에서 전환한 작품', `${fmtDate(c.at)}에 ${c.from_total}화 단편을 장편으로 바꿨어요. 단편 1~${c.arc_end}화가 아크 1이에요.`, `<a class="btn primary" href="${base()}/arc">부 · 아크로</a>`)}
      <section class="card">
        <h2>되돌리기</h2>
        <div class="small">결말 처리: ${esc(ENDINGS.find((x) => x[0] === c.ending)?.[1] || c.ending)}</div>
        ${why.length ? `<div class="note warn">되돌리면 잃는 것이 있어 막아 두었어요: ${why.map(esc).join(' / ')}</div>`
          : '<div class="note plain">전환한 뒤 새로 쓰거나 반영한 화가 없어서 전환 전 단편으로 그대로 돌아갈 수 있어요. 전환한 뒤 고친 설정과 플롯도 함께 돌아갑니다.</div>'}
        <div class="row"><button class="btn danger" data-action="convertUndo"${why.length ? ' disabled' : ''}>단편으로 되돌리기</button></div>
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
  const btn = jobBtn('convert', null, S.convDraft ? '전환 계획 다시 받기' : 'AI 로 전환 계획 만들기');
  const formCard = `<section class="card">
      <h2>단편 → 장편</h2>
      ${end ? `<div class="note info">단편 1~${end}화가 그대로 <strong>아크 1</strong>이 되고, 그 뒤를 부와 아크로 늘려요. 이미 쓴 화의 구조는 바꾸지 않아요.</div>`
        : '<div class="note warn">아직 기승전결 구조가 없어요. 전환하면 빈 장편이 되고, 부 · 아크 화면에서 처음부터 기획합니다.</div>'}
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
      <div class="row"><button class="btn primary" data-action="convertPlan"${btn.attr}>${btn.label}</button><span class="small">반영 전에 미리 보고 고를 수 있어요. 전환 직전 작품은 따로 남겨 되돌릴 수 있어요.</span></div>
    </section>`;
  return `${header('장편', '장편으로 전환', '다 쓴 단편이나 쓰는 중인 단편을 200~300화 장편 연재로 늘립니다.', `<a class="btn" href="${base()}/arc">기승전결로</a>`)}
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
      <div class="act-strip">${a.acts.map((x) => `<div class="act-head ${actClass(x.name)}"><div class="between"><strong>${x.name}</strong><span class="act-meta">${x.start_ep}–${x.end_ep}화</span></div><div class="small">${esc(x.goal)}</div></div>`).join('')}</div>
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
      `<div class="diff-act">${convBox('ep:' + e.number, `<strong>${e.number}화</strong> ${esc(e.title)}`)}<div class="diff">${plotDiff(e)}</div></div>`).join('')}</div>`);
  }
  return `<section class="card proposal">
      <div class="between"><h2>전환 계획 <span class="chip ai">반영 전</span> <span class="chip">${esc(ending ? ending[1] : d.ending)}</span></h2>
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
      S.selArc = 'next';
      toast('장편으로 바꿨어요. 단편은 아크 1이 됐어요. 이제 다음 아크를 기획하세요.');
      location.hash = `${base()}/arc`;
    });
  },
  async convertUndo() {
    if (!confirm('전환 전 단편으로 되돌릴까요? 전환한 뒤 고친 설정과 플롯도 함께 돌아갑니다.')) return;
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/convert/undo`);
      S.selArc = null;
      toast('단편으로 되돌렸어요.');
      location.hash = `${base()}/arc`;
    });
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || S.route[2] !== 'convert') return;
  if (t.dataset.convPick) S.convPicks[t.dataset.convPick] = t.checked;
  if (t.dataset.convEnding !== undefined && t.checked) S.convForm.ending = t.dataset.convEnding;
});
