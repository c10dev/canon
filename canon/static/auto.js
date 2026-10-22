/* 자동 집필 화면. app.js 의 S, actions, api, render 를 그대로 쓴다. 서버 로직은 canon/autorun.py.
   목표 화까지 본문 → 검수 + 상태 변경안 → 반영을 반복하고, 승인 정책에 걸리면 그 화에서 멈춘다.
   배치(Gemini Batch API)는 켜고 끌 수 있다. 돌고 있을 때 바꾸면 다음 단계부터 적용된다. */
'use strict';

const AUTO_STATUS = {
  running: ['진행 중', 'confirmed'], paused: ['일시정지', 'written'], review: ['검토 대기', 'written'],
  stopped: ['중지됨', 'draft'], done: ['끝남', 'finalized'], error: ['오류로 멈춤', 'written'],
};
const AUTO_STEP = { write: '본문 쓰는 중', review: '검수와 상태 변경안 만드는 중', confirm: '플롯 확정', applied: '반영함' };
// 관계 변화 민감도: 한 인물이 다른 인물을 보는 온기나 신뢰가 한 화에 이만큼 넘게 바뀌면 멈춘다
const AUTO_SHIFT = [[0.2, '민감하게 (작은 변화에도 멈춤)'], [0.3, '보통'], [0.45, '둔하게 (큰 변화에만 멈춤)'], [0, '보지 않음']];

Object.assign(S, {
  auto: null,      // GET /auto 결과 { run, active, batch_stages }
  autoForm: null,  // 새로 시작할 때의 목표 화, 배치, 정책
  autoEst: null,   // { off, on } 배치 끔/켬 추정
  autoTimer: null,
  autoFormOpen: false,
});

function autoDefaults() {
  const p = P();
  const last = S.auto && S.auto.run;
  return {
    target: p.meta.target_episodes,
    batch: last ? last.batch : false,
    policy: last ? { ...last.policy } : {
      check: true, max_issues: 0, max_shift: 0.3, stop_on_stage: false, stop_on_warnings: false, confirm_plots: false, review_every: 0,
    },
  };
}

async function autoLoad(withEstimate = true) {
  if (!S.name) return;
  S.auto = await api('GET', `/projects/${enc(S.name)}/auto`).catch(() => null);
  if (!S.autoForm || S.autoForm.project !== S.name) S.autoForm = { ...autoDefaults(), project: S.name };
  if (withEstimate) await autoEstimate();
  autoPoll();
}

async function autoEstimate() {
  const f = S.autoForm;
  const body = (batch) => ({ target: f.target, batch, policy: f.policy });
  try {
    const [off, on] = await Promise.all([false, true].map((b) => api('POST', `/projects/${enc(S.name)}/auto/estimate`, body(b))));
    S.autoEst = { off, on };
  } catch (e) {
    S.autoEst = { error: e.message };
  }
}

// 자동 집필 화면을 보고 있거나 실행이 돌고 있으면 3초마다 상태를 묻는다. 진행이 바뀌면 작품도 다시 받는다.
function autoPoll() {
  clearTimeout(S.autoTimer);
  const watching = S.route[2] === 'auto' || (S.auto && S.auto.active);
  if (!watching || !S.name) return;
  S.autoTimer = setTimeout(async () => {
    const before = S.auto && S.auto.run ? S.auto.run.updated : null;
    const name = S.name;
    const fresh = await api('GET', `/projects/${enc(name)}/auto`).catch(() => null);
    if (name !== S.name) return;
    S.auto = fresh;
    const changed = fresh && fresh.run && fresh.run.updated !== before;
    if (changed && !S.dirty) S.project = await api('GET', `/projects/${enc(name)}`).catch(() => S.project);
    if (changed && !fresh.active && S.route[2] === 'auto') await autoEstimate();  // 멈추거나 끝나면 남은 화 추정을 새로
    const typing = document.activeElement && document.activeElement.matches('#app input, #app textarea, #app select');
    if (changed && !typing && ['auto', 'home', ''].includes(S.route[2] || '')) render();
    autoPoll();
  }, 3000);
}

function autoDuration(s) {
  if (s == null) return '';
  if (s >= 86400 * 2) return `${Math.round(s / 86400)}일`;
  if (s >= 3600) return `${(s / 3600).toFixed(1)}시간`;
  if (s < 60) return `${Math.max(1, Math.round(s))}초`;
  return `${Math.round(s / 60)}분`;
}

function autoCost(c) {
  if (c == null) return '가격 모름';
  if (c === 0) return '$0';
  return c < 0.01 ? '$0.01 미만' : `$${c.toFixed(2)}`;
}

function autoEstCard() {
  const e = S.autoEst;
  if (!e) return '<div class="small">추정하는 중…</div>';
  if (e.error) return `<div class="note warn">${esc(e.error)}</div>`;
  const f = S.autoForm;
  const col = (x, on) => {
    const time = x.batch_rounds
      ? `${autoDuration(x.seconds_min)}~${autoDuration(x.seconds_max)}<div class="small">배치 ${x.batch_rounds}번 기다림. 길면 한 번에 24시간까지 걸릴 수 있어요${x.batch_avg_seconds ? ` (지난 평균 ${autoDuration(x.batch_avg_seconds)})` : ''}</div>`
      : `약 ${autoDuration(x.seconds_min)}`;
    return `<div class="auto-opt${on === f.batch ? ' picked' : ''}"><div style="font-weight:700">${on ? '배치 켬' : '배치 끔 (일반 호출)'}${on === f.batch ? ' <span class="chip confirmed">선택</span>' : ''}</div>
      <div class="line">비용 ${autoCost(x.cost)}</div><div class="line">시간 ${time}</div></div>`;
  };
  const x = e.off;
  const local = Object.entries(x.stages).filter(([, v]) => v === 'local').map(([k]) => ({ write: '본문', check: '검수', state: '상태' }[k]));
  return `<div class="small">${x.episodes ? `${x.from}~${x.to}화 ${x.episodes}화 남음 · 호출 본문 ${x.calls.write} · 검수 ${x.calls.check} · 상태 ${x.calls.state} · 토큰 입력 약 ${x.tokens_in.toLocaleString()} / 출력 약 ${x.tokens_out.toLocaleString()}` : `${x.to}화까지 남은 화가 없어요`}</div>
    <div class="grid-2">${col(e.off, false)}${col(e.on, true)}</div>
    ${x.missing.length ? `<div class="note warn">플롯이 없는 화(${x.missing.join(', ')}화)에서 멈춥니다. 먼저 플롯을 만드세요.</div>` : ''}
    ${local.length ? `<div class="small">${local.join(', ')} 단계는 로컬 모델이라 비용이 없고 배치도 쓰지 않아요.</div>` : ''}
    <div class="small">${x.measured ? '지난 실행에서 잰 출력량과 시간을 썼어요.' : '처음이라 화당 목표 분량으로 추정했어요.'} 가격은 ${esc(x.model)} 정가 기준 추정치이고, 생각(thinking) 토큰이 많으면 더 나올 수 있어요.</div>`;
}

function autoPolicyForm(f, disabled) {
  const p = f.policy;
  const dis = disabled ? ' disabled' : '';
  const chk = (key, label, hint) => `<label class="check-row"><input type="checkbox" data-auto="policy.${key}"${p[key] ? ' checked' : ''}${dis}><span>${label}${hint ? `<br><span class="small">${hint}</span>` : ''}</span></label>`;
  const opts = (list, cur) => list.map(([v, l]) => `<option value="${v}"${Number(cur) === v ? ' selected' : ''}>${l}</option>`).join('');
  return `<div class="grid-2">
      <div class="field"><label for="auto-issues">검수에서 어긋난 곳이 몇 개를 넘으면 멈출까요</label><select id="auto-issues" data-auto="policy.max_issues"${dis || (p.check ? '' : ' disabled')}>${opts([[0, '하나라도 있으면 멈춤'], [1, '1개까지 넘어감'], [2, '2개까지 넘어감'], [5, '5개까지 넘어감']], p.max_issues)}</select></div>
      <div class="field"><label for="auto-shift">관계가 크게 움직이면 멈추기</label><select id="auto-shift" data-auto="policy.max_shift"${dis}>${opts(AUTO_SHIFT, p.max_shift)}</select></div>
    </div>
    <div class="grid-2">
      ${chk('check', '화마다 검수하기', '앞선 본문·설정과 어긋나는 곳을 찾아요. 끄면 비용과 시간이 줄지만 모순을 놓칠 수 있어요.')}
      ${chk('stop_on_stage', '관계 단계가 바뀌면 멈추기', '호감 → 신뢰, 신뢰 → 균열처럼 관계의 단계가 바뀔 때')}
      ${chk('stop_on_warnings', '상태 변경안에 경고가 있으면 멈추기', '플롯 사건 누락, 설정이나 말투 위반을 AI 가 적었을 때')}
      ${chk('confirm_plots', '초안 플롯도 자동으로 확정하고 쓰기', '끄면 초안 플롯을 만난 화에서 멈춰요')}
    </div>
    <div class="field" style="max-width:360px"><label for="auto-every">몇 화마다 멈춰서 읽어 볼까요</label><select id="auto-every" data-auto="policy.review_every"${dis}>${opts([[0, '멈추지 않음'], [1, '매 화'], [2, '2화마다'], [3, '3화마다'], [5, '5화마다']], p.review_every)}</select></div>`;
}

function autoBatchToggle(on, attrs = '') {
  return `<div class="seg" role="group" aria-label="배치"><button type="button" aria-pressed="${!on}" data-action="autoBatch" data-arg="off"${attrs}>배치 끔 · 빠르게</button><button type="button" aria-pressed="${on}" data-action="autoBatch" data-arg="on"${attrs}>배치 켬 · 절반 비용</button></div>`;
}

function autoRunCard(r, active) {
  const [label, cls] = AUTO_STATUS[r.status] || [r.status, ''];
  const p = P();
  const total = r.target;
  const done = p.episodes.filter((e) => e.plot.number <= total && e.status === 'finalized').length;
  const waiting = Object.keys(r.batches || {});
  const step = active && r.ep ? `${r.ep}화 ${AUTO_STEP[r.step] || r.step}${waiting.length ? ' · 배치 결과 기다리는 중' : ''}` : '';
  let buttons = '';
  if (active) {
    buttons = `<button class="btn" data-action="autoPause">일시정지</button><button class="btn" data-action="autoStop">중지</button>`;
  } else if (r.status === 'review') {
    buttons = `<button class="btn primary" data-action="autoOpenReview">${r.ep}화 변경안 검토하기</button>
      <button class="btn" data-action="autoResume" data-arg="approve">그대로 반영하고 이어 가기</button>
      <button class="btn" data-action="autoResume" data-arg="rewrite">${r.ep}화 다시 쓰기</button>
      <button class="btn" data-action="autoStop">중지</button>`;
  } else if (['paused', 'error'].includes(r.status)) {
    buttons = `<button class="btn primary" data-action="autoResume">이어 가기</button><button class="btn" data-action="autoStop">중지</button>`;
  }
  const reviewDone = r.status === 'review' && !r.pending;
  return `<section class="card">
    <div class="between"><h2>${total}화까지 자동 집필 <span class="chip ${cls}">${label}</span></h2>
      <div class="row"><span class="small">배치</span>${autoBatchToggle(r.batch, r.status === 'done' || r.status === 'stopped' ? ' disabled' : '')}</div></div>
    <div class="meter" aria-hidden="true"><i style="left:0;width:${Math.round((done / Math.max(total, 1)) * 100)}%;background:var(--green)"></i></div>
    <div class="small">${done} / ${total}화 반영 완료 · 이번 실행에서 자동 반영 ${r.applied.length}화 · 토큰 입력 ${r.tokens_in.toLocaleString()} / 출력 ${r.tokens_out.toLocaleString()} · 비용 약 ${autoCost(r.cost)}</div>
    ${step ? `<div class="row"><span class="spinner sm" aria-hidden="true"></span><strong>${esc(step)}</strong></div>` : ''}
    ${active && r.batch ? '<div class="small">배치 결과는 몇 분에서 길게는 몇 시간 뒤에 와요. 창을 닫아도 서버가 계속 기다립니다.</div>' : ''}
    ${r.reasons.length ? `<div class="note warn">${r.reasons.map((x) => `<div>${esc(x)}</div>`).join('')}</div>` : ''}
    ${reviewDone ? `<div class="note ok">${r.ep}화를 검토 화면에서 반영했어요. 이어 가기를 누르세요.</div>` : ''}
    ${r.status === 'review' && r.pending ? '<div class="small">검토하기: 변경안을 상태 승인 화면에 열어요. 고른 항목만 반영한 뒤 여기로 돌아와 이어 가면 됩니다.</div>' : ''}
    <div class="row">${reviewDone ? '<button class="btn primary" data-action="autoResume">이어 가기</button><button class="btn" data-action="autoStop">중지</button>' : buttons}</div>
  </section>`;
}

function autoAppliedCard(active) {
  const auto = P().episodes.filter((e) => e.auto);
  if (!auto.length) return '';
  const rows = auto.map((e) => `<li class="row"><a href="${base()}/write/${e.plot.number}"><strong>${e.plot.number}화</strong> ${esc(e.plot.title)}</a>${e.issues.length ? `<span class="chip written">검수 ${e.issues.length}</span>` : ''}${active ? '' : `<button class="btn small" data-action="autoRevert" data-arg="${e.plot.number}">이 화부터 되돌리기</button>`}</li>`).join('');
  return `<section class="card"><div class="between"><h2>검토 없이 반영한 화</h2><span class="small">${auto.length}화</span></div>
    <p class="desc">읽어 보고 문제가 있으면 그 화부터 되돌리세요. 그 화 직전 상태로 돌아가고, 본문은 남아 상태 승인부터 다시 할 수 있어요.</p>
    <ul class="auto-list">${rows}</ul></section>`;
}

function autoLogCard(r) {
  if (!r || !r.log.length) return '';
  const shown = S.autoLogAll ? r.log : r.log.slice(-30);
  const rows = shown.slice().reverse().map((e) => {
    const t = new Date(e.at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const tok = e.tokens_in || e.tokens_out ? `${e.tokens_in.toLocaleString()} / ${e.tokens_out.toLocaleString()}` : '';
    return `<tr class="lv-${e.level}"><td class="small">${t}</td><td>${e.ep ? e.ep + '화' : ''}</td><td>${esc(e.message)}${e.batch ? ' <span class="chip">배치</span>' : ''}</td><td class="small">${tok}</td><td class="small">${e.seconds ? autoDuration(e.seconds) : ''}</td></tr>`;
  }).join('');
  return `<section class="card"><h2>진행 로그</h2><div class="rs-scroll"><table class="rs-table"><thead><tr><th>시각</th><th>화</th><th>내용</th><th>토큰 입력 / 출력</th><th>걸린 시간</th></tr></thead><tbody>${rows}</tbody></table></div>${r.log.length > shown.length ? `<div><button class="btn small" data-action="autoLogAll">이전 로그 ${r.log.length - shown.length}줄 더 보기</button></div>` : ''}</section>`;
}

function viewAuto() {
  const p = P();
  const a = S.auto || {};
  const r = a.run;
  const active = !!a.active;
  if (!S.autoForm || S.autoForm.project !== S.name) S.autoForm = { ...autoDefaults(), project: S.name };
  const f = S.autoForm;
  // 멈춘 실행이 있으면 이어 가기가 먼저라 새로 시작하는 칸은 접어 둔다
  const ended = !r || ['done', 'stopped'].includes(r.status);
  const canStart = !active && (ended || S.autoFormOpen);
  const batchNote = a.batch_stages && a.batch_stages.length
    ? '배치를 켜면 Gemini Batch API 로 보내 비용이 절반이에요. 대신 단계마다 몇 분에서 길게는 24시간까지 기다려요. 화는 앞 화가 반영돼야 쓸 수 있어 한 화씩 차례로 가고, 한 화의 검수와 상태 변경안은 함께 보냅니다.'
    : '지금 단계들이 Gemini 가 아니라서 배치를 켜도 일반 호출로 돌아요.';
  const eps = Array.from({ length: p.meta.target_episodes }, (_, i) => i + 1);
  const form = canStart ? `<section class="card">
      <div class="between"><h2>${r ? '새로 시작' : '시작하기'}</h2>${r && r.status !== 'done' && r.status !== 'stopped' ? '<span class="small">새로 시작하면 지금 실행의 검토 대기와 기다리던 배치는 버려요</span>' : ''}</div>
      <div class="grid-2">
        <div class="field"><label for="auto-target">어디까지 쓸까요</label><select id="auto-target" data-auto="target">${eps.map((n) => `<option value="${n}"${n === f.target ? ' selected' : ''}>${n}화까지</option>`).join('')}</select></div>
        <div class="field"><span class="label">배치</span>${autoBatchToggle(f.batch)}<span class="small">${batchNote}</span></div>
      </div>
      <h3 style="font-size:15px;margin:4px 0 0">이럴 때는 멈추고 저에게 물어봐 주세요</h3>
      <p class="desc">걸리는 게 없으면 상태 변경안을 검토 없이 반영하고 다음 화로 갑니다. 반영한 화는 표시해 두고, 화마다 남는 스냅샷으로 되돌릴 수 있어요.</p>
      ${autoPolicyForm(f, false)}
      <h3 style="font-size:15px;margin:4px 0 0">예상 비용과 시간</h3>
      <div id="auto-est">${autoEstCard()}</div>
      <div class="row"><button class="btn primary" data-action="autoStart">${f.target}화까지 자동 집필 시작</button></div>
    </section>` : '';
  const reopen = !active && !ended && !S.autoFormOpen ? '<div><button class="btn" data-action="autoFormOpen">설정을 바꿔 새로 시작</button></div>' : '';
  return `${header('자동', '자동 집필', '목표 화까지 본문 쓰기, 검수, 상태 변경안, 반영을 알아서 반복합니다. 정해 둔 기준에 걸리면 그 화에서 멈추고 검토를 기다려요.')}
    ${r ? autoRunCard(r, active) : ''}
    ${form}${reopen}
    ${autoAppliedCard(active)}
    ${autoLogCard(r)}`;
}

document.addEventListener('change', (e) => {
  const key = e.target.dataset && e.target.dataset.auto;
  if (!key || !S.autoForm) return;
  const el = e.target;
  const v = el.type === 'checkbox' ? el.checked : Number(el.value);
  if (key === 'target') S.autoForm.target = v;
  else S.autoForm.policy[key.split('.')[1]] = v;
  autoEstimate().then(render);
});

Object.assign(actions, {
  autoLogAll() {
    S.autoLogAll = true;
    render();
  },
  async autoFormOpen() {
    S.autoFormOpen = true;
    await autoEstimate();
    render();
  },
  async autoBatch(v) {
    const on = v === 'on';
    const r = S.auto && S.auto.run;
    if (r && ['running', 'paused', 'review', 'error'].includes(r.status)) {
      try {
        S.auto = await api('PUT', `/projects/${enc(S.name)}/auto/batch`, { batch: on });
        toast(on ? '배치를 켰어요. 다음 단계부터 배치로 보냅니다.' : '배치를 껐어요. 다음 단계부터 일반 호출입니다.');
      } catch (e) { toast(e.message, true); }
    }
    if (S.autoForm) S.autoForm.batch = on;
    render();
  },
  async autoStart() {
    const f = S.autoForm;
    const est = S.autoEst && (f.batch ? S.autoEst.on : S.autoEst.off);
    const msg = est && !est.error ? `${f.target}화까지 자동으로 씁니다. 예상 비용 ${autoCost(est.cost)}. 시작할까요?` : `${f.target}화까지 자동으로 씁니다. 시작할까요?`;
    if (!confirm(msg)) return;
    await run('자동 집필을 시작하는 중', async () => {
      await saveIfDirty();
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/start`, { target: f.target, batch: f.batch, policy: f.policy });
      S.autoFormOpen = false;
      toast('자동 집필을 시작했어요. 다른 화면으로 옮겨 가도 계속 돕니다.');
      pollJobs(true);
      autoPoll();
    });
  },
  async autoPause() {
    try {
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/pause`);
      toast(S.auto.run.batch ? '멈추는 중이에요. 기다리던 배치는 취소하지 않아, 이어 가면 결과를 받아 옵니다.' : '지금 단계가 끝나면 멈춰요.');
    } catch (e) { toast(e.message, true); }
    render();
  },
  async autoStop() {
    if (!confirm('자동 집필을 중지할까요? 기다리던 배치 작업이 있으면 취소합니다. 이미 반영한 화는 그대로예요.')) return;
    try {
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/stop`);
    } catch (e) { toast(e.message, true); }
    render();
  },
  async autoResume(how) {
    const body = { approve: how === 'approve', rewrite: how === 'rewrite' };
    const r = S.auto.run;
    if (how === 'approve' && !confirm(`${r.ep}화 변경안을 보지 않고 그대로 반영할까요?`)) return;
    if (how === 'rewrite' && !confirm(`${r.ep}화 본문을 지우고 다시 쓸까요?`)) return;
    await run('이어 가는 중', async () => {
      await saveIfDirty();
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/resume`, body);
      S.project = await api('GET', `/projects/${enc(S.name)}`);
      pollJobs(true);
      autoPoll();
    });
  },
  autoOpenReview() {
    const r = S.auto.run;
    setDelta(r.ep, structuredClone(r.pending));
    location.hash = `${base()}/review/${r.ep}`;
  },
  async autoRevert(n) {
    if (!confirm(`${n}화부터 되돌릴까요? ${n - 1 ? `${n - 1}화 반영 직후` : '1화 시작 전'} 상태로 돌아가고, ${n}화부터의 본문은 남아 상태 승인을 다시 하게 됩니다.`)) return;
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/revert/${n - 1}`);
      toast(`${n}화부터 반영을 취소했어요.`);
      await autoEstimate();
    });
  },
});
