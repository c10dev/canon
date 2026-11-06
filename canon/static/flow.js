/* 한 화 흐름: 집필 · 검수 · 상태 승인을 한 화의 세 단계로 잇는다. 세 화면(write · check · review/<화>)은 주소가 단계 이름이고,
   머리 바로 아래 같은 단계 띠(flowBar)가 단계 사이를 옮기며 단계마다 지금 할 일을 짧게 적는다.
   '검수하기'(flowCheck)는 첫 검수일 때 상태 변경안도 함께 만든다 (자동 집필 autorun._review 와 같은 짝, 끌 수 있음).
   단계 글은 DOM 없는 순수 함수 flowSteps (tests/test_flow_js.py). app.js 의 S, actions, startJob, jobFor, home.js 의 checkState 를 쓴다. */
'use strict';

/** 단계: [주소, 이름, 사이드바 번호]. 이름과 번호는 사이드바와 같다 (app.js stepLabel · navItems) */
const FLOW_STAGES = [['write', '집필', 4], ['check', '검수', 5], ['review', '상태 승인', 6]];
// 640px 이하 집필 머리 한 줄에서 보이는 짧은 이름 (app.css .fl-s). 낭독은 칸의 aria-label 이 온 이름을 말한다
const FLOW_SHORT = { review: '승인' };

/** 단계 셋의 글. e: 화, run: { checking, stating, delta: { picked, total } | null, stale }.
    stale: 변경안을 만든 뒤 본문을 고쳤다 (저장했든 안 했든). 상태 승인 칸을 볼 것 남음으로 표시한다.
    done 끝남 · warn 볼 것 남음 · off 아직 갈 수 없음(본문이 없음). 검수 단계는 home.js checkState 의 done 과 같다 */
function flowSteps(e, run = {}) {
  const st = checkState(e);
  const text = (e.text || '').length;
  const written = !!e.text && e.status !== 'draft';
  const fin = e.status === 'finalized';
  const open = st.open;
  const found = (e.findings || []).length;
  const write = { key: 'write', done: written, warn: false, off: false,
    sub: !written ? '본문 없음' : st.stale ? `${text.toLocaleString()}자 · 검수 뒤 고침` : `${text.toLocaleString()}자` };
  const check = { key: 'check', done: written && st.done, warn: written && (open > 0 || st.stale), off: !written,
    sub: !written ? '본문을 쓴 뒤' : run.checking ? '검수하는 중' : !st.checked ? '아직 안 했어요'
      : open ? `열린 지적 ${open}` : st.stale ? '검수 뒤 본문을 고쳤어요' : found ? `지적 ${found} 처리` : '어긋난 곳 없음' };
  const stale = !fin && !!run.delta && !!run.stale;
  const review = { key: 'review', done: fin, warn: written && stale, off: !written,
    sub: !written ? '본문을 쓴 뒤' : fin ? '반영 완료' : run.stating ? '변경안 만드는 중'
      : stale ? '본문 고침' : run.delta ? `${run.delta.picked}/${run.delta.total} 고름` : '변경안 없음' };
  return [write, check, review].map((s, i) => ({ ...s, label: FLOW_STAGES[i][1], num: FLOW_STAGES[i][2] }));
}

/** 세 단계 화면 머리의 위치 줄: '전(轉) 구간 · 14 / 240화' (집필 화면과 같은 줄) */
function flowEyebrow(n) {
  const act = actOf(n);
  return `${act ? actLabel(act.name) + ' 구간 · ' : ''}${n} / ${P().meta.target_episodes}화`;
}

/** 머리 바로 아래 단계 띠. cur: 지금 화면 ('write' | 'check' | 'review'). 플롯 초안 화는 그리지 않는다 */
function flowBar(n, cur) {
  const e = ep(n);
  if (!e || e.status === 'draft') return '';
  const d = S.deltas[n];
  const steps = flowSteps(e, {
    checking: !!jobFor('check', n), stating: !!jobFor('state', n),
    delta: d && e.status === 'written' ? { picked: deltaPicked(), total: deltaCount(d) } : null,
    // 변경안을 만든 뒤 본문을 고쳤다: 저장한 본문이 변경안의 본문과 다르거나, 저장하지 않은 고침이 있다 (review.js 의 stale 알림과 같은 셈)
    stale: !!d && (textUnsaved(n) || (S.deltaBase[n] !== undefined && S.deltaBase[n] !== e.text)),
  });
  const cell = (s) => {
    const mark = s.done ? '<span class="fl-n ok" aria-hidden="true">✓</span>' : `<span class="fl-n" aria-hidden="true">${s.num}</span>`;
    const inner = `${mark}<span class="fl-t"><strong>${FLOW_SHORT[s.key] ? `<span class="fl-l">${s.label}</span><span class="fl-s" aria-hidden="true">${FLOW_SHORT[s.key]}</span>` : s.label}</strong><span class="fl-sub${s.warn ? ' warn' : ''}">${esc(s.sub)}</span></span>`;
    const label = `${s.num}단계 ${s.label}${s.done ? ' (끝남)' : ''}: ${s.sub}`;
    return `<li>${s.off && s.key !== cur ? `<span class="fl-cell off" aria-label="${esc(label)}">${inner}</span>`
      : `<a class="fl-cell${s.key === cur ? ' cur' : ''}" href="${base()}/${s.key}/${n}" aria-label="${esc(label)}"${s.key === cur ? ' aria-current="step"' : ''}>${inner}</a>`}</li>`;
  };
  return `<ol class="flow-bar" aria-label="${n}화 진행">${steps.map(cell).join('')}</ol>`;
}

/** 첫 검수 때 상태 변경안도 함께 만들까 (브라우저에 기억, 처음은 켬) */
function flowWithState() {
  try { return localStorage.getItem('canon.flowState') !== '0'; } catch { return true; }
}

/** 첫 검수 칸의 '상태 변경안도 함께 만들기' 체크 */
function flowStateToggle() {
  return `<label class="fl-toggle"><input type="checkbox" data-flow-state${flowWithState() ? ' checked' : ''}><span>상태 변경안도 함께 만들기<span class="small">검수를 마치고 바로 승인할 수 있어요</span></span></label>`;
}

if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  document.addEventListener('change', (e) => {
    if (!e.target.dataset || e.target.dataset.flowState === undefined) return;
    try { localStorage.setItem('canon.flowState', e.target.checked ? '1' : '0'); } catch { /* 기억하지 못해도 이번에는 따른다 */ }
  });
}

/** 상태 변경안을 검수와 함께 만들까: 첫 검수, 쓴 화, 아직 변경안 · 받아 둔 결과 · 도는 작업이 없음 */
function flowStateToo(n) {
  const e = ep(n);
  const pend = Object.values((S.pending && S.pending.name === S.name && S.pending.results) || {}).some((r) => r.kind === 'state' && r.ep === n);
  return flowWithState() && !!e && e.status === 'written' && !(e.rounds || []).length && S.deltas[n] === undefined && !pend && !jobFor('state', n);
}

Object.assign(actions, {
  /** 검수하기: 검수 단계로 옮겨 검수를 시작하고, 첫 검수면 상태 변경안도 함께 만든다 */
  async flowCheck(n) {
    n = Number(n);
    // 검수는 저장된 작품과 본문을 읽는다. 저장하지 않은 변경과 본문 초안을 먼저 저장한다 (app.js checkReady)
    if (!(await checkReady(n))) return;
    const both = flowStateToo(n);
    if (S.route[2] !== 'check') location.hash = `${base()}/check/${n}`;
    await startJob('check', n);
    if (both && jobFor('check', n)) await startJob('state', n);
  },
});
