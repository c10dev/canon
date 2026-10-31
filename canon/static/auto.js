/* 자동 집필 화면. app.js 의 S, actions, api, render 를 그대로 쓴다. 서버 로직은 canon/autorun.py.
   목표 화까지 본문 → 검수 + 상태 변경안 → 반영을 반복하고, 승인 정책에 걸리면 그 화에서 멈춘다.
   배치(Gemini Batch API)는 켜고 끌 수 있다. 돌고 있을 때 바꾸면 다음 단계부터 적용된다. */
'use strict';

const AUTO_STATUS = {
  running: ['진행 중', 'confirmed'], paused: ['일시정지', 'written'], review: ['검토 대기', 'written'],
  stopped: ['중지됨', 'draft'], done: ['끝남', 'finalized'], error: ['오류로 멈춤', 'written'],
};
const AUTO_STEP = { board: '스토리보드 만드는 중', cues: '큐 시트 만드는 중', write: '본문 쓰는 중', review: '검수와 상태 변경안 만드는 중', confirm: '플롯 확정', applied: '반영 완료' };
// 관계 변화 민감도: 한 인물이 다른 인물을 보는 온기나 신뢰가 한 화에 이만큼 넘게 바뀌면 멈춘다
const AUTO_SHIFT = [[0.2, '민감하게 (작은 변화에도 멈춤)'], [0.3, '보통'], [0.45, '둔하게 (큰 변화에만 멈춤)'], [0, '보지 않음']];

Object.assign(S, {
  auto: null,      // GET /auto 결과 { run, active, batch_stages }
  autoForm: null,  // 새로 시작할 때의 목표 화, 배치, 정책
  autoEst: null,   // { off, on } 배치 끔/켬 추정
  autoTimer: null,
  autoFormOpen: false,
  autoRunPolicy: null,      // 멈춘 실행의 정책을 고치는 중인 값 { started, policy }
  autoRunPolicyOpen: false, // 그 칸을 펼쳐 둘지
});

/** 집필 · 상태 승인 · 홈 화면 위쪽 안내: 자동 집필이 돌고 있어 손으로 진행할 수 없다. 돌지 않으면 빈 문자열. */
function autoLockNote() {
  if (!autoOn()) return '';
  const n = autoEp();
  return `<div class="note warn" role="status">자동 집필이 ${n ? `${n}화를 ` : ''}쓰는 중이에요. 손으로 쓰거나 반영하려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>`;
}

/** 목표 화로 고를 수 있는 첫 화: 반영하지 않은 첫 화 (autorun._todo 와 같은 기준). 다 반영했으면 마지막 화 */
function autoFirstOpen() {
  const p = P();
  const done = new Set(p.episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));
  let n = 1;
  while (done.has(n)) n += 1;
  return Math.min(n, p.meta.target_episodes);
}

function autoDefaults() {
  const p = P();
  const last = S.auto && S.auto.run;
  const lastPlot = p.episodes.length ? Math.max(...p.episodes.map((e) => e.plot.number)) : p.meta.target_episodes;
  return {
    target: Math.max(lastPlot, autoFirstOpen()),  // 플롯이 있는 마지막 화까지. 다 반영했으면 고를 수 있는 첫 화
    batch: last ? last.batch : false,
    policy: last ? { cue_sheet: true, ...last.policy } : {
      check: true, max_issues: 0, ignore_minor: false, stop_on_critical: true, max_shift: 0.3, stop_on_stage: false, stop_on_warnings: false, confirm_plots: false, review_every: 0, hand_pick_opening: true,
      storyboard: true, stop_on_board_warnings: true, cue_sheet: true,
    },
  };
}

async function autoLoad(withEstimate = true) {
  if (!S.name) return;
  S.auto = await api('GET', `/projects/${enc(S.name)}/auto`).catch(() => null);
  if (!S.autoForm || S.autoForm.project !== S.name) S.autoForm = { ...autoDefaults(), project: S.name };
  // 추정은 남은 화가 많으면 몇 초 걸린다. 화면을 먼저 그리고('추정하는 중…') 끝나면 다시 그린다
  if (withEstimate) {
    const name = S.name;
    S.autoEst = null;
    autoEstimate().then(() => {
      if (name === S.name && S.route[2] === 'auto' && !isTyping()) render();
    });
  }
  autoPoll();
}

async function autoEstimate() {
  const f = S.autoForm;
  const body = (batch) => ({ target: f.target, batch, policy: f.policy });
  const name = S.name;
  try {
    const [off, on] = await Promise.all([false, true].map((b) => api('POST', `/projects/${enc(name)}/auto/estimate`, body(b))));
    if (name === S.name && f === S.autoForm) S.autoEst = { off, on };  // 기다리는 사이 다른 작품으로 옮겼으면 버린다
  } catch (e) {
    if (name === S.name && f === S.autoForm) S.autoEst = { error: e.message };
  }
}

// 자동 집필 화면을 보고 있거나 실행이 돌고 있으면 3초마다 상태를 묻는다. 진행이 바뀌면 작품도 다시 받는다.
// 시작 · 이어 가기 직후에는 첫 단계가 바로 보이게 1초 뒤에 묻는다.
function autoPoll(delay = 3000) {
  clearTimeout(S.autoTimer);
  const watching = S.route[2] === 'auto' || (S.auto && S.auto.active) || S.autoOffline;
  if (!watching || !S.name) return;
  S.autoTimer = setTimeout(async () => {
    // updated 는 초 단위라 같은 초 안의 일시정지 · 중지 · 끝남을 놓친다. 보이는 값들을 함께 비교한다
    const sig = (r) => (r ? [r.updated, r.status, r.ep, r.step, (r.log || []).length].join('|') : '');
    const before = sig(S.auto && S.auto.run);
    const wasActive = !!(S.auto && S.auto.active);
    const restarts = S.auto && S.auto.run ? S.auto.run.restarts || 0 : null;
    const name = S.name;
    let fresh;
    try {
      fresh = await api('GET', `/projects/${enc(name)}/auto`);
    } catch {
      // 서버와 연결이 끊겼다. 마지막 상태를 진행 중으로 두지 않고 '연결 끊김'으로 보인 뒤 계속 다시 묻는다
      if (name === S.name && !S.autoOffline) { S.autoOffline = true; if (S.route[2] === 'auto' && !isTyping()) render(); }
      autoPoll();
      return;
    }
    if (name !== S.name) return;
    if (S.autoOffline) {
      S.autoOffline = false;
      if (fresh && fresh.active) toast('서버에 다시 연결됐어요. 자동 집필을 이어서 보여 드려요');
    }
    // 서버가 다시 시작돼 하던 단계를 처음부터 다시 하면 한 번 알린다 (끊긴 호출 비용은 실행 비용에 없다)
    if (restarts != null && fresh && fresh.run && (fresh.run.restarts || 0) > restarts) {
      toast('서버가 다시 시작돼 자동 집필을 이어 가요. 끊긴 단계는 처음부터 다시 해요. 진행 기록에서 확인해요');
    }
    S.auto = fresh;
    const changed = fresh && fresh.run && (sig(fresh.run) !== before || !!fresh.active !== wasActive);
    if (changed && !S.dirty) {
      const gen = S.gen;
      const p = await api('GET', `/projects/${enc(name)}`).catch(() => null);
      // 받는 사이 입력 · 저장이 있었으면 이 작품이 더 오래됐을 수 있다. 화는 작업 폴링(mergeEpisodes)이 맞춘다
      if (p && name === S.name && !S.dirty && gen === S.gen) S.project = p;
    }
    if (changed && !fresh.active && S.route[2] === 'auto') await autoEstimate();  // 멈추거나 끝나면 남은 화 추정을 새로
    if (changed && !isTyping() && S.route[0] === 'p' && ['auto', 'home', ''].includes(S.route[2] || '')) render();
    autoPoll();
  }, delay);
}

/** 자동 집필이 쓸 화에 저장하지 않은 본문 초안이 있으면 먼저 저장할지 묻는다. 자동 집필이 그 화를 쓰고 반영하면 초안은 본문이 될 수 없다.
    저장하면 그 화는 작성 상태가 되어 자동 집필이 그 본문을 검수한다. 취소하면 false (시작하지 않는다). */
async function autoFlushDrafts(upTo) {
  const nums = Object.keys(S.textDraft).map(Number).filter((n) => n <= upTo && textUnsaved(n) && editableEp(ep(n))).sort((a, b) => a - b);
  if (!nums.length) return true;
  // 앞 화 반영 전인 화에 처음 쓰는 본문은 서버가 저장하지 않는다 (순서 규칙). 그 초안은 자동 집필이 그 화를 쓴 뒤 집필 화면에 따로 남는다
  const stuck = nums.filter((n) => ep(n).status === 'confirmed' && blockedBefore(n).length);
  const save = nums.filter((n) => !stuck.includes(n));
  const ask = [
    save.length ? `${save.join(', ')}화에 저장하지 않은 본문이 있어요. 먼저 저장하고 이어 갈까요? 저장한 본문은 자동 집필이 검수해요.` : '',
    stuck.length ? `${stuck.join(', ')}화 초안은 앞 화 반영 전이라 지금 저장할 수 없어요. 자동 집필이 그 화를 쓰면 초안은 집필 화면에 따로 남아 복사할 수 있어요.` : '',
  ].filter(Boolean).join('\n\n');
  if (!confirm(`${ask}\n\n취소하면 시작하지 않아요.`)) return false;
  try {
    for (const n of save) await flushText(n);
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

/** 검토 대기 변경안을 만든 뒤 그 화 본문이 바뀌었다 (서버도 그대로 반영을 막는다, autorun.resume). */
function pendingStale(r) {
  const e = r.pending && r.pending_text && ep(r.ep);
  return !!e && (e.text || '').trim() !== r.pending_text.trim();
}

function autoDuration(s) {
  if (s == null) return '';
  if (s >= 86400 * 2) return `${Math.round(s / 86400)}일`;
  if (s >= 3600) return `${(s / 3600).toFixed(1)}시간`;
  if (s < 60) return s > 0 ? `${Math.max(1, Math.round(s))}초` : '0초';
  return `${Math.round(s / 60)}분`;
}

function autoCost(c) {
  if (c == null) return '가격 모름';
  if (c === 0) return '$0';
  return c < 0.01 ? '$0.01 미만' : `$${c.toFixed(2)}`;
}

/** 플롯이 없는 n화를 쓰려면 할 일. 장편은 다음 아크를 짜야 플롯이 생긴다 */
function autoPlotHint(n) {
  if (!serial()) return '먼저 플롯을 만드세요.';
  const planned = plannedUntil();
  if (n > planned && planned < P().meta.target_episodes) return `장편은 다음 아크를 짜야 플롯이 생겨요. <a class="btn small" href="${base()}/arc">다음 아크 기획 (${planned + 1}화부터)</a>`;
  return `<a href="${base()}/arc">부 · 아크 · 플롯</a>에서 플롯을 만드세요.`;
}

/** 목표 화까지 쓸 수 있는 화가 없을 때 안내: 목표 화를 늘리거나, 장편은 다음 아크를 짠다 */
function autoNothingNote(x) {
  const p = P();
  const lastPlot = Math.max(0, ...p.episodes.map((ep) => ep.plot.number));
  if (x.missing.length) return `<div class="note warn">${rangeText(x.missing)}화는 플롯이 없어 쓸 수 없어요. ${autoPlotHint(x.missing[0])}</div>`;
  let next;
  if (x.to < lastPlot) next = '더 쓰려면 위에서 목표 화를 늘리세요.';
  else if (x.to >= p.meta.target_episodes) next = '마지막 화까지 모두 반영했어요.';
  else next = autoPlotHint(x.to + 1);
  return `<div class="note plain">${x.to}화까지 남은 화가 없어요. ${next}</div>`;
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
  // 쓸 수 있는 화가 없으면 시간 · 비용을 적지 않고 시작 버튼도 끈다 (viewAuto)
  if (!x.episodes) return autoNothingNote(x);
  const local = Object.entries(x.stages).filter(([, v]) => v === 'local').map(([k]) => ({ plan: '스토리보드', write: '본문', check: '검수', state: '상태' }[k]));
  return `<div class="small">${x.episodes ? `${x.from}~${x.to}화 ${x.episodes}화 남음 · 호출 ${x.calls.plan ? `스토리보드 ${x.calls.plan} · ` : ''}본문 ${x.calls.write} · 검수 ${x.calls.check} · 상태 ${x.calls.state} · 토큰 입력 약 ${x.tokens_in.toLocaleString()} / 출력 약 ${x.tokens_out.toLocaleString()}` : `${x.to}화까지 남은 화가 없어요`}</div>
    <div class="grid-2">${col(e.off, false)}${col(e.on, true)}</div>
    ${x.missing.length ? `<div class="note warn">플롯이 없는 화(${rangeText(x.missing)}화)에서 멈춰요. ${autoPlotHint(x.missing[0])}</div>` : ''}
    ${(x.drafts || []).length ? `<div class="note warn">플롯이 초안인 ${rangeText(x.drafts)}화에서 멈춰요. 추정은 끝까지 쓴다고 보고 셌어요. 확정하거나 '초안 플롯도 자동으로 확정하고 쓰기'를 켜세요.</div>` : ''}
    ${local.length ? `<div class="small">${local.join(', ')} 단계는 로컬 모델이라 비용이 없고 배치도 쓰지 않아요.</div>` : ''}
    <div class="small">${x.measured ? '지난 실행에서 잰 출력량과 시간을 썼어요.' : '처음이라 화당 목표 분량으로 추정했어요.'} 가격은 <a href="#/usage">사용량 · 비용</a> 화면의 가격표(${esc(x.model)} 기준)로 계산한 추정치이고, 생각(thinking) 토큰이 많으면 더 나올 수 있어요.${x.unpriced && x.unpriced.length ? ` 가격표에 없는 모델(${x.unpriced.map(esc).join(', ')})이 있어 비용을 몰라요.` : ''}</div>`;
}

/** 승인 정책 칸. '진행 방식'(켜면 더 하거나 덜 멈추는 동작)과 '멈출 때'(켜면 더 멈추는 조건)로 나눈다.
    bind 는 'auto'(새로 시작 폼, S.autoForm) 또는 'auto-run'(멈춘 실행의 정책, S.autoRunPolicy). id 가 겹치지 않게 앞에 붙인다. */
function autoPolicyForm(f, disabled, bind = 'auto') {
  const p = f.policy;
  const dis = disabled ? ' disabled' : '';
  const id = (x) => `${bind}-${x}`;
  const chk = (key, label, hint) => `<label class="check-row"><input type="checkbox" data-${bind}="policy.${key}"${p[key] ? ' checked' : ''}${dis}><span>${label}${hint ? `<br><span class="small">${hint}</span>` : ''}</span></label>`;
  const opts = (list, cur) => list.map(([v, l]) => `<option value="${v}"${Number(cur) === v ? ' selected' : ''}>${l}</option>`).join('');
  return `<div class="auto-policy">
    <h3 class="auto-h">진행 방식</h3>
    <div class="grid-2">
      ${chk('check', '화마다 검수하기', '앞선 본문·설정과 어긋나는 곳을 찾아요. 끄면 비용과 시간이 줄지만 모순을 놓칠 수 있어요.')}
      ${chk('confirm_plots', '초안 플롯도 자동으로 확정하고 쓰기', '켜면 덜 멈춰요. 끄면 초안 플롯을 만난 화에서 멈춰요')}
      ${P().settings.storyboard ?? P().meta.form === 'serial' ? chk('storyboard', '화마다 스토리보드를 만들고 쓰기', '쓰기 전에 장면 순서와 이번 화 확정 값(시간 · 상태창 수치 · 차림)을 정해요. 화당 AI 호출이 하나 늘어요') : ''}
      ${cueOn() ? chk('cue_sheet', '화마다 큐 시트를 만들고 쓰기', '쓰기 전에 큐마다 긴장 · 템포 · 편성 · 핵심 대사 · 분량을 정해요. 화당 AI 호출이 하나 늘어요. 작가가 고친 큐 시트는 그대로 써요') : ''}
    </div>
    <h3 class="auto-h">이럴 때는 멈추고 기다려요</h3>
    <p class="desc">걸리는 게 없으면 상태 변경안을 검토 없이 반영하고 다음 화로 가요. 반영한 화는 표시해 두고, 화마다 남는 스냅샷으로 되돌릴 수 있어요.</p>
    <div class="grid-2">
      <div class="field"><label for="${id('issues')}">검수에서 어긋난 곳이 몇 개를 넘으면 멈출까요</label><select id="${id('issues')}" data-${bind}="policy.max_issues"${dis || (p.check ? '' : ' disabled')}>${opts([[0, '하나라도 있으면 멈춤'], [1, '1개까지 넘어감'], [2, '2개까지 넘어감'], [5, '5개까지 넘어감']], p.max_issues)}</select></div>
      <div class="field"><label for="${id('shift')}">관계가 크게 움직이면 멈추기</label><select id="${id('shift')}" data-${bind}="policy.max_shift"${dis}>${opts(AUTO_SHIFT, p.max_shift)}</select></div>
    </div>
    <div class="grid-2">
      ${chk('stop_on_critical', '치명적인 어긋남이 있으면 멈추기', '위 개수와 상관없이, 검수가 치명으로 본 곳이 하나라도 있으면 멈춰요')}
      ${chk('ignore_minor', '사소한 어긋남은 세지 않기', '물건 색처럼 사소한 곳은 위 개수에 넣지 않아요. 켜면 덜 멈추지만 작은 어긋남이 쌓일 수 있어요')}
    </div>
    <div class="grid-2">
      ${chk('stop_on_stage', '관계 단계가 바뀌면 멈추기', '호감 → 신뢰, 신뢰 → 균열처럼 관계의 단계가 바뀔 때')}
      ${chk('stop_on_warnings', '상태 변경안에 경고가 있으면 멈추기', '플롯 사건 누락, 설정이나 말투 위반을 AI가 적었을 때')}
      ${chk('hand_pick_opening', '1~3화는 반영하기 전에 멈추기', '독자가 계속 읽을지 정하는 초반 화라 직접 읽고, 필요하면 여는 방식을 비교해 고르세요')}
      ${p.storyboard ? chk('stop_on_board_warnings', '스토리보드가 이번 화 플롯과 어긋나면 멈추기', '플롯 숫자가 지금 상태에서 닿을 수 없을 때처럼. 다음 화 플롯 경고는 기록만 해요') : ''}
    </div>
    <div class="field" style="max-width:360px"><label for="${id('every')}">몇 화마다 멈춰서 읽어 볼까요</label><select id="${id('every')}" data-${bind}="policy.review_every"${dis}>${opts([[0, '멈추지 않음'], [1, '매 화'], [2, '2화마다'], [3, '3화마다'], [5, '5화마다']], p.review_every)}</select></div>
  </div>`;
}

/** 멈춘 이유를 고칠 화면으로 가는 버튼 (Run.halt 는 autorun._Halt 의 kind). */
function autoHaltLinks(r) {
  const n = r.ep;
  if (!n) return '';
  const go = (href, label) => `<a class="btn small" href="${href}">${label}</a>`;
  switch (r.halt) {
    case 'plot_draft': return go(`${base()}/arc/${n}`, `${n}화 플롯 확정하러 가기`);
    case 'plot_missing': return go(`${base()}/arc`, `${n}화 플롯 만들러 가기`);
    case 'review': return (ep(n) && checkState(ep(n)).open ? go(`${base()}/check/${n}`, `${n}화 검수 결과 보기`) : go(`${base()}/write/${n}`, `${n}화 본문 읽기`));
    case 'every': return go(`${base()}/write/${n}`, `${n}화 읽으러 가기`);
    case 'changed': return go(`${base()}/write/${n}`, `${n}화 집필 화면 보기`);
    case 'board': case 'board_stale': return go(`${base()}/write/${n}`, `${n}화 스토리보드 보기`);
    default: return '';
  }
}

/** 멈춘 이유 한 줄에서 갈 곳 (review_reasons 의 문장 머리로 고른다). 없으면 null */
function autoReasonLink(reason, n) {
  if (!n) return null;
  if (/^검수에서/.test(reason)) return { href: `${base()}/check/${n}`, label: `${n}화 검수 결과 보기` };
  if (/^관계/.test(reason)) return { href: `${base()}/cast`, label: '관계도 보기' };
  if (/초반 화/.test(reason)) return { href: `${base()}/write/${n}`, label: `${n}화 읽으러 가기` };
  return null;
}

/** 승인 정책을 세 줄로: [이름, 글]. 읽기 카드 (autoPolicyForm 의 칸과 같은 뜻) */
function autoPolicySummary(p) {
  const on = [];
  const off = [];
  const go = [p.check ? '화마다 검수' : '검수 안 함'];
  if (p.storyboard && (P().settings.storyboard ?? P().meta.form === 'serial')) go.push('스토리보드를 만들고 쓰기');
  if (p.cue_sheet && cueOn()) go.push('큐 시트를 만들고 쓰기');
  go.push(p.confirm_plots ? '초안 플롯도 확정하고 쓰기' : '초안 플롯에서 멈춤');
  if (p.check) on.push(p.max_issues ? `검수 어긋남 ${p.max_issues + 1}개부터${p.ignore_minor ? '(사소한 것 빼고)' : ''}` : `검수 어긋남 1개부터${p.ignore_minor ? '(사소한 것 빼고)' : ''}`);
  (p.check && p.stop_on_critical ? on : off).push('치명 지적');
  (p.max_shift ? on : off).push(p.max_shift ? `관계 ${p.max_shift} 넘게 움직임` : '관계 움직임');
  (p.stop_on_stage ? on : off).push('관계 단계 바뀜');
  (p.stop_on_warnings ? on : off).push('변경안 경고');
  (p.hand_pick_opening ? on : off).push('1~3화 직접 고름');
  (p.review_every ? on : off).push(p.review_every ? `${p.review_every}화마다 읽기` : 'n화마다 읽기');
  return [['진행', go.join(' · ')], ['멈추는 때', on.join(' · ') || '없음'], ['멈추지 않음', off.join(' · ') || '없음']];
}

/** 화 칸 띠에 그릴 화: [{ n, cls, label }]. 화가 많으면 지금 화 둘레 40칸만 */
function autoCells(p, r) {
  const total = r.target;
  const applied = new Set(r.applied || []);
  const at = Math.min(r.ep || total, total);
  const from = total > 40 ? Math.max(1, Math.min(at - 9, total - 39)) : 1;
  const to = Math.min(total, from + 39);
  const out = [];
  for (let n = from; n <= to; n += 1) {
    const e = p.episodes.find((x) => x.plot.number === n);
    const st = e ? e.status : 'none';
    const cls = st === 'finalized' ? (applied.has(n) ? 'auto' : 'finalized') : st === 'none' ? '' : st;
    out.push({ n, cls: `${cls}${n === r.ep && ['review', 'paused', 'error', 'running'].includes(r.status) ? ' cur' : ''}`, label: STATUS[st] || '플롯 없음' });
  }
  return out;
}

function autoBatchToggle(on, attrs = '') {
  return `<div class="seg" role="group" aria-label="배치"><button type="button" aria-pressed="${!on}" data-action="autoBatch" data-arg="off"${attrs}>배치 끔 · 빠르게</button><button type="button" aria-pressed="${on}" data-action="autoBatch" data-arg="on"${attrs}>배치 켬 · 절반 비용</button></div>`;
}

const autoMan = (x) => new Intl.NumberFormat('ko-KR', { notation: 'compact', maximumFractionDigits: 1 }).format(x || 0);

function autoRunCard(r, active) {
  // 서버와 연결이 끊기면 마지막 상태를 '진행 중'으로 두지 않는다 (autoPoll 이 S.autoOffline 을 정한다)
  const [label, cls] = S.autoOffline ? ['연결 끊김', 'draft'] : AUTO_STATUS[r.status] || [r.status, ''];
  const p = P();
  const total = r.target;
  const done = p.episodes.filter((e) => e.plot.number <= total && e.status === 'finalized').length;
  const waiting = Object.keys(r.batches || {});
  // 시작 직후에는 ep 가 아직 없다. 빈칸 대신 준비 중이라고 보인다
  const step = !active ? '' : r.ep ? `${r.ep}화 ${AUTO_STEP[r.step] || r.step}${waiting.length ? ' · 배치 결과 기다리는 중' : ''}` : '첫 화를 준비하는 중';
  const cells = autoCells(p, r);
  const strip = `<ol class="auto-cells" style="--n:${cells.length}" aria-label="${cells[0].n}~${cells[cells.length - 1].n}화">${cells.map((c) => `<li class="${c.cls}" title="${c.n}화 · ${c.label}${c.cls.startsWith('auto') ? ' · 이번 실행에서 자동 반영' : ''}"><span class="sr-only">${c.n}화 ${c.label}</span><span aria-hidden="true">${c.n}</span></li>`).join('')}</ol>`;
  const legend = `<div class="auto-legend small" aria-hidden="true"><span><i class="auto"></i>이번 실행에서 자동 반영</span><span><i class="finalized"></i>반영 완료</span><span><i class="written"></i>작성됨 · 검토 대기</span><span><i class="confirmed"></i>플롯 확정</span><span><i class="draft"></i>플롯 초안</span></div>`;
  const tiles = `<div class="auto-tiles">
      <div><span class="small">반영</span><b>${done} / ${total}화</b></div>
      <div><span class="small">이번 실행 자동 반영</span><b>${r.applied.length}화</b></div>
      <div><span class="small">토큰 입력 / 출력</span><b>${autoMan(r.tokens_in)} / ${autoMan(r.tokens_out)}</b></div>
      <div><span class="small">비용</span><b>약 ${autoCost(r.cost)}</b>${r.restarts ? `<span class="small" title="서버가 다시 시작돼 하던 단계를 처음부터 다시 했어요. 끊긴 호출 비용은 여기에 없어요">서버 재시작 ${r.restarts}번</span>` : ''}</div>
    </div>`;
  return `<section class="card" id="au-run" aria-labelledby="au-run-h">
    <div class="between"><h2 id="au-run-h" tabindex="-1">${total}화까지 자동 집필 <span class="chip ${cls}">${label}</span></h2>${autoBatchToggle(r.batch, r.status === 'done' || r.status === 'stopped' ? ' disabled' : '')}</div>
    ${S.autoOffline ? '<div class="note warn" role="status">서버와 연결이 끊겼어요. 다시 연결되면 이어서 보여 드려요. 서버가 다시 시작되면 자동 집필은 서버에서 이어 가요.</div>' : ''}
    ${step ? `<div class="row" role="status"><span class="spinner sm" aria-hidden="true"></span><strong>${esc(step)}</strong></div>` : ''}
    ${active && r.batch ? '<div class="small">배치 결과는 몇 분에서 길게는 몇 시간 뒤에 와요. 창을 닫아도 서버가 계속 기다려요.</div>' : ''}
    ${strip}${legend}${tiles}
  </section>`;
}

/** 멈춘 이유와 이어 가는 길. 돌고 있거나 끝난 실행은 그리지 않는다 */
function autoHaltCard(r, active) {
  if (active || S.autoOffline || !['paused', 'review', 'error'].includes(r.status)) return '';
  const reviewDone = r.status === 'review' && !r.pending;
  const stale = r.status === 'review' && pendingStale(r);
  const keyErr = r.status === 'error' && r.reasons.some((x) => /API 키|연결|quota|429|403|401/i.test(x));
  const halt = autoHaltLinks(r);
  const rows = r.reasons.map((x) => {
    const go = autoReasonLink(x, r.ep);
    return `<div class="auto-reason"><div class="grow">${esc(x)}</div>${go ? `<a class="btn small" href="${go.href}">${go.label}</a>` : ''}</div>`;
  }).join('');
  const linked = r.reasons.some((x) => autoReasonLink(x, r.ep));
  const ways = r.status === 'review' && !reviewDone
    ? `<h3>어떻게 이어 갈까요</h3><ul class="auto-ways">
        <li><div class="grow"><strong>변경안을 검토하고 이어 가기</strong><span class="small">상태 승인 화면에서 고른 항목만 반영한 뒤 여기로 돌아와 이어 가요 · 머리의 '${r.ep}화 변경안 검토하기'</span></div></li>
        <li><div class="grow"><strong>그대로 반영하고 이어 가기</strong><span class="small">걸린 이유를 남긴 채 다음 화로 가요</span></div><button type="button" class="btn small" data-action="autoResume" data-arg="approve"${stale ? ' disabled aria-describedby="auto-stale"' : ''}>그대로 반영</button></li>
        <li><div class="grow"><strong>${r.ep}화 다시 쓰기</strong><span class="small">본문부터 새로 써요. 지금 본문은 이전 판으로 남고, AI 비용이 다시 들어요</span></div><button type="button" class="btn small" data-action="autoResume" data-arg="rewrite">다시 쓰기</button></li>
      </ul>` : '';
  return `<section class="card" id="au-halt" aria-labelledby="au-halt-h">
    <div class="between"><h2 id="au-halt-h" tabindex="-1">${r.ep ? `${r.ep}화에서 ` : ''}${r.status === 'error' ? '오류로 멈춘 이유' : '멈춘 이유'}</h2>${r.updated ? `<span class="small">${fmtDateTime(r.updated)}</span>` : ''}</div>
    ${rows}
    ${keyErr ? '<div class="note warn"><a href="#/settings/ai">AI 연결 설정</a>에서 키와 모델을 확인한 뒤 이어 가세요.</div>' : ''}
    ${halt && !linked ? `<div class="row">${halt}</div>` : ''}
    ${reviewDone ? `<div class="note ok">${r.ep}화를 상태 승인 화면에서 반영했어요. 이어 가기를 누르세요.</div>` : ''}
    ${stale ? `<div class="note warn" id="auto-stale">변경안을 만든 뒤 ${r.ep}화 본문을 고쳤어요. 그대로 반영하면 옛 본문 기준의 요약 · 인물 상태 · 사건이 들어가서 막아 두었어요. 검토하기에서 변경안을 다시 만들거나 다시 쓰기를 고르세요.</div>` : ''}
    ${ways}
  </section>`;
}

function autoAppliedCard(active, r) {
  const all = P().episodes.filter((e) => e.auto);
  if (!all.length) return '';
  const withOpen = all.filter((e) => checkState(e).open);
  const only = S.autoOpenOnly && withOpen.length;
  const list = only ? withOpen : all;
  // 로그에만 남는 문체 · 초반 경고를 화별로 센다 (autorun._write 가 'N화 본문' 다음에 남긴다)
  const style = {};
  for (const x of (r && r.log) || []) if (x.level === 'warn' && x.ep && /^(문체|초반):/.test(x.message)) style[x.ep] = (style[x.ep] || 0) + 1;
  const rows = list.map((e) => `<li><div class="grow"><a href="${base()}/write/${e.plot.number}"><strong>${e.plot.number}화</strong> ${esc(e.plot.title)}</a></div>${checkState(e).open ? `<a class="btn small" href="${base()}/check/${e.plot.number}">열린 지적 ${checkState(e).open}</a>` : ''}${style[e.plot.number] ? `<span class="chip written" title="진행 기록의 문체 · 초반 경고">문체 경고 ${style[e.plot.number]}</span>` : ''}${active ? '' : `<button type="button" class="btn small ghost" data-action="autoRevert" data-arg="${e.plot.number}">${e.plot.number}화부터 반영 취소</button>`}</li>`).join('');
  const seg = withOpen.length ? `<div class="seg" role="group" aria-label="반영한 화 거르기"><button type="button" aria-pressed="${!only}" data-action="autoOpenOnly" data-arg="all">모두 · ${all.length}</button><button type="button" aria-pressed="${!!only}" data-action="autoOpenOnly" data-arg="open">열린 지적 · ${withOpen.length}</button></div>` : `<span class="small">${all.length}화</span>`;
  return `<section class="card" id="au-applied" aria-labelledby="au-applied-h"><div class="between"><h2 id="au-applied-h" tabindex="-1">검토 없이 반영한 화</h2>${seg}</div>
    <p class="desc">읽어 보고 문제가 있으면 그 화부터 반영을 취소해요. 그 화 직전 상태로 돌아가고, 본문은 남아 상태 승인부터 다시 해요.</p>
    <ul class="auto-list">${rows}</ul></section>`;
}

/** 이번 실행 기록을 화별로 묶는다: [{ ep, lines, warns, tin, tout, sec }] 최신 화부터. 화가 없는 줄(시작 · 끝)은 뺀다 */
function autoLogGroups(log) {
  let from = 0;
  log.forEach((x, i) => { if (x.step === 'start') from = i; });
  const by = new Map();
  log.slice(from).forEach((x) => {
    if (!x.ep) return;
    if (!by.has(x.ep)) by.set(x.ep, { ep: x.ep, lines: [], warns: [], tin: 0, tout: 0, sec: 0 });
    const g = by.get(x.ep);
    if (x.level === 'info') g.lines.push(`${x.message}${x.seconds ? ` ${autoDuration(x.seconds)}` : ''}${x.batch ? ' · 배치' : ''}`);
    else g.warns.push(x);
    g.tin += x.tokens_in || 0;
    g.tout += x.tokens_out || 0;
    g.sec += x.seconds || 0;
  });
  return [...by.values()].sort((a, b) => b.ep - a.ep);
}

function autoLogCard(r) {
  if (!r || !r.log.length) return '';
  const byEp = S.autoLogView !== 'all';
  const seg = `<div class="seg" role="group" aria-label="기록 보기"><button type="button" aria-pressed="${byEp}" data-action="autoLogView" data-arg="ep">화별</button><button type="button" aria-pressed="${!byEp}" data-action="autoLogView" data-arg="all">모든 줄</button></div>`;
  let body;
  if (byEp) {
    const groups = autoLogGroups(r.log);
    const start = [...r.log].reverse().find((x) => x.step === 'start');
    body = groups.length
      ? `<ol class="auto-log-eps">${groups.map((g) => `<li><strong>${g.ep}화</strong><div class="auto-log-lines"><span>${g.lines.map(esc).join(' · ') || '기다리는 중'}</span>${g.warns.map((x) => `<span class="${x.level === 'error' ? 'err-text' : 'warn-text'}">${esc(x.message)}</span>`).join('')}</div><span class="small">${g.tin || g.tout ? `${autoMan(g.tin)} / ${autoMan(g.tout)}` : ''}</span></li>`).join('')}</ol>`
      : '<p class="small">이번 실행에서 아직 쓴 화가 없어요.</p>';
    body += `<p class="small">${start ? `${fmtDateTime(start.at)}에 시작했어요. ` : ''}토큰은 입력 / 출력이에요. 지난 실행 기록은 '모든 줄'에서 봐요.</p>`;
  } else {
    const shown = S.autoLogAll ? r.log : r.log.slice(-30);
    const today = new Date().toDateString();
    const rows = shown.slice().reverse().map((e) => {
      const d = new Date(e.at);
      const clock = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      // 오늘이 아닌 줄은 날짜를 붙인다 (배치는 하루를 넘길 수 있고, 지난 실행 로그도 이어 붙는다)
      const t = d.toDateString() === today ? clock : `${fmtDate(e.at)} ${clock}`;
      const tok = e.tokens_in || e.tokens_out ? `${e.tokens_in.toLocaleString()} / ${e.tokens_out.toLocaleString()}` : '';
      const cls = `lv-${e.level}${e.step === 'start' ? ' run-start' : ''}`;
      return `<tr class="${cls}"><td class="small" data-label="시각">${t}</td><td data-label="화">${e.ep ? e.ep + '화' : ''}</td><td data-label="내용">${esc(e.message)}${e.batch ? ' <span class="chip">배치</span>' : ''}</td><td class="small" data-label="토큰">${tok}</td><td class="small" data-label="걸린 시간">${e.seconds ? autoDuration(e.seconds) : ''}</td></tr>`;
    }).join('');
    body = `<div class="small">위가 최신이에요. 굵은 선 아래는 지난 실행이에요.</div><div class="rs-scroll"><table class="rs-table auto-log"><thead><tr><th>시각</th><th>화</th><th>내용</th><th>토큰 입력 / 출력</th><th>걸린 시간</th></tr></thead><tbody>${rows}</tbody></table></div>${r.log.length > shown.length ? `<div><button class="btn small" data-action="autoLogAll">이전 기록 ${r.log.length - shown.length}줄 더 보기</button></div>` : ''}`;
  }
  return `<section class="card" id="au-log" aria-labelledby="au-log-h"><div class="between"><h2 id="au-log-h" tabindex="-1">진행 기록</h2>${seg}</div>${body}</section>`;
}

/** 승인 정책 카드: 읽기가 기본이고, 멈춘 실행에서만 '고치기'로 그 카드 안에 칸을 편다 (Card 읽기 카드와 고치기 카드) */
function autoPolicyCard(r, active) {
  const canEdit = !active && !S.autoOffline && ['paused', 'review', 'error'].includes(r.status);
  const editing = canEdit && (S.autoRunPolicyOpen || r.halt === 'plot_draft');
  if (editing && (!S.autoRunPolicy || S.autoRunPolicy.started !== r.started)) S.autoRunPolicy = { started: r.started, policy: { ...r.policy } };
  const changed = editing && JSON.stringify(S.autoRunPolicy.policy) !== JSON.stringify(r.policy);
  const read = `<dl class="pf-dl">${autoPolicySummary(r.policy).map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`;
  const btn = canEdit ? `<button type="button" class="btn small" data-action="autoPolicyEdit" aria-expanded="${editing}">${editing ? '닫기' : '고치기'}</button>` : '';
  const body = editing
    ? `<p class="small">바꾼 정책은 다음 판정부터 적용돼요. ${r.status === 'review' ? `지금 검토를 기다리는 ${r.ep}화 변경안은 그대로 남아요.` : '검토 대기와 기다리던 배치는 그대로예요.'}</p>
      ${autoPolicyForm(S.autoRunPolicy, false, 'auto-run')}
      <div class="row"><button type="button" class="btn" data-action="autoSetPolicy"${changed ? '' : ' disabled'}>정책 적용</button></div>`
    : `${read}${canEdit ? '' : `<p class="small">${active ? '돌고 있는 동안은 고칠 수 없어요. 일시정지하면 고칠 수 있어요.' : '새로 시작할 때 시작 칸에서 정해요.'}</p>`}`;
  return `<section class="card${editing ? ' editing' : ''}" id="au-policy" aria-labelledby="au-policy-h"><div class="between"><h2 id="au-policy-h" tabindex="-1">승인 정책${editing ? ' <span class="small">고치는 중</span>' : ''}</h2>${btn}</div>${body}</section>`;
}

/** 새로 시작 칸 (실행이 없거나, 끝났거나, '실행 ▾ → 설정을 바꿔 새로 시작') */
function autoStartCard(r, f, primary) {
  const a = S.auto || {};
  const first = autoFirstOpen();
  const eps = Array.from({ length: P().meta.target_episodes - first + 1 }, (_, i) => first + i);
  const nothingLeft = !!(S.autoEst && S.autoEst.off && !S.autoEst.off.episodes);
  const batchNote = a.batch_stages && a.batch_stages.length
    ? '배치를 켜면 Gemini Batch API로 보내 비용이 절반이에요. 대신 단계마다 몇 분에서 길게는 24시간까지 기다려요. 화는 앞 화가 반영돼야 쓸 수 있어 한 화씩 차례로 가고, 한 화의 검수와 상태 변경안은 함께 보내요.'
    : '지금 단계들이 Gemini가 아니라서 배치를 켜도 일반 호출로 돌아요.';
  return `<section class="card" id="au-start" aria-labelledby="au-start-h">
      <div class="between"><h2 id="au-start-h" tabindex="-1">${r ? '새로 시작' : '시작하기'}</h2>${r && r.status !== 'done' && r.status !== 'stopped' ? '<span class="small">새로 시작하면 지금 실행의 검토 대기와 기다리던 배치는 버려요</span>' : ''}</div>
      <div class="grid-2">
        <div class="field"><label for="auto-target">어디까지 쓸까요</label><select id="auto-target" data-auto="target">${eps.map((n) => `<option value="${n}"${n === f.target ? ' selected' : ''}>${n}화까지</option>`).join('')}</select></div>
        <div class="field"><span class="label">배치</span>${autoBatchToggle(f.batch)}<span class="small">${batchNote}</span></div>
      </div>
      ${autoPolicyForm(f, false)}
      <h3>예상 비용과 시간</h3>
      <div id="auto-est">${autoEstCard()}</div>
      ${primary ? '' : `<div class="row"><button type="button" class="btn" data-action="autoStart"${nothingLeft ? ' disabled aria-describedby="auto-est"' : ''}>${f.target}화까지 새로 시작</button><button type="button" class="btn ghost" data-action="autoFormClose">닫기</button></div>`}
    </section>`;
}

let autoTocCur = null;

/** 목차 줄: [열쇠, 이름, 꼬리, warn] */
function autoTocRows(r, form) {
  const rows = [];
  if (r) {
    const [label] = S.autoOffline ? ['연결 끊김'] : AUTO_STATUS[r.status] || [r.status];
    rows.push(['run', '지금 실행', label]);
    if (!(S.auto || {}).active && !S.autoOffline && ['paused', 'review', 'error'].includes(r.status)) rows.push(['halt', r.ep ? `${r.ep}화에서 멈춘 이유` : '멈춘 이유', String(r.reasons.length || ''), true]);
    const n = P().episodes.filter((e) => e.auto).length;
    if (n) rows.push(['applied', '검토 없이 반영한 화', `${n}화`]);
    if (r.log.length) rows.push(['log', '진행 기록', '']);
    rows.push(['policy', '승인 정책', '']);
  }
  if (form) rows.push(['start', r ? '새로 시작' : '시작하기', '']);
  return rows;
}

let autoTocLast = [];

function autoToc(rows = autoTocLast) {
  autoTocLast = rows;
  const cur = rows.find(([k]) => k === autoTocCur) || rows[0];
  const body = rows.map(([k, l, st, warn]) => `<button type="button" class="outline-item${warn ? ' warn' : ''}" data-action="autoGo" data-arg="${k}"${k === cur[0] ? ' aria-current="true"' : ''}><span class="tl">${esc(l)}</span><span class="st${warn ? ' warn' : ''}">${esc(st || '')}</span></button>`).join('');
  return outlineNav({ id: 'au-toc', label: '자동 집필 목차', now: esc(cur[1]), body });
}

outlineSpy('au-toc', {
  targets: () => autoTocLast.map(([k]) => [k, document.getElementById(`au-${k}`)]),
  set(cur) {
    if (cur === autoTocCur) return;
    autoTocCur = cur;
    outlineRefresh('au-toc', autoToc());
  },
});

function viewAuto() {
  const a = S.auto || {};
  const r = a.run;
  const active = !!a.active && !S.autoOffline;
  if (!S.autoForm || S.autoForm.project !== S.name) S.autoForm = { ...autoDefaults(), project: S.name };
  const f = S.autoForm;
  // 멈춘 실행이 있으면 이어 가기가 먼저라 새로 시작하는 칸은 접어 둔다
  const ended = !r || ['done', 'stopped'].includes(r.status);
  const canStart = !active && (ended || S.autoFormOpen);
  // 목표 화는 반영하지 않은 첫 화부터 고른다. 다 쓴 실행 뒤 남은 목표가 그보다 앞이면 끌어올리고 다시 추정한다
  const first = autoFirstOpen();
  if (canStart && f.target < first) {
    f.target = first;
    autoEstimate().then(render);
  }
  const nothingLeft = !!(S.autoEst && S.autoEst.off && !S.autoEst.off.episodes);
  const desc = '목표 화까지 본문 · 검수 · 상태 변경안 · 반영을 알아서 반복해요. 정해 둔 기준에 걸리면 그 화에서 멈추고 기다려요.';
  // 머리 주 버튼: 그 실행에서 지금 할 일 하나
  let primary = '';
  if (r && !S.autoOffline) {
    if (active) primary = '<button type="button" class="btn" data-action="autoPause">일시정지</button>';
    else if (r.status === 'review' && r.pending) primary = `<button type="button" class="btn primary" data-action="autoOpenReview">${r.ep}화 변경안 검토하기</button>`;
    else if (['paused', 'review', 'error'].includes(r.status)) primary = '<button type="button" class="btn primary" data-action="autoResume">이어 가기</button>';
  }
  const startPrimary = canStart && ended && !nothingLeft;
  if (startPrimary) primary = `<button type="button" class="btn primary" data-action="autoStart"${S.autoEst ? '' : ' aria-disabled="true"'}>${f.target}화까지 자동 집필 시작</button>`;
  const menu = r && !ended && !S.autoOffline ? menuBtn('auto-run', '실행 ▾', () => `<button type="button" class="pop-item danger" data-action="autoStop">중지</button>${active ? '' : '<button type="button" class="pop-item" data-action="autoFormOpen">설정을 바꿔 새로 시작</button>'}`, { aria: '실행 더 보기' }) : '';
  const head = header('자동', '자동 집필', desc, `${menu}${primary}`);
  // 쓸 화가 없으면 시작 칸 대신 빈 화면 하나 (막힌 이유 + 풀 길)
  if (canStart && ended && nothingLeft && !r) return head + autoEmpty();
  const form = canStart ? (ended && nothingLeft ? autoEmpty() : autoStartCard(r, f, startPrimary)) : '';
  if (!r) return `${head}<div class="auto-col auto-one">${form}</div>`;  // 실행이 없으면 시작 칸 하나라 목차를 두지 않는다
  const main = `<div class="auto-col">${autoRunCard(r, active)}${autoHaltCard(r, active)}${autoAppliedCard(active, r)}${autoLogCard(r)}${autoPolicyCard(r, active)}${form}</div>`;
  const rows = autoTocRows(r, !!form && form !== autoEmpty());
  if (!rows.some(([k]) => k === autoTocCur)) autoTocCur = null;
  return head + outlineDoc(autoToc(rows), main, { cls: 'auto-wrap' });
}

/** 쓸 화가 없을 때 빈 화면: 막힌 이유 한 문장과 풀 길 버튼 하나 */
function autoEmpty() {
  const x = S.autoEst && S.autoEst.off;
  if (!x) return '';
  const p = P();
  if (x.missing.length || (x.drafts || []).length) {
    const n = x.missing.length ? x.missing[0] : x.drafts[0];
    const why = x.missing.length ? `${rangeText(x.missing)}화는 플롯이 없어 쓸 수 없어요.` : `${n}화 플롯이 아직 초안이에요. 확정하거나 '초안 플롯도 자동으로 확정하고 쓰기'를 켜야 써요.`;
    return `<div class="card empty" id="au-start"><p>${why}</p><div><a class="btn primary" href="${base()}/arc${x.missing.length ? '' : `/${n}`}">${n}화 플롯 ${x.missing.length ? '만들러' : '확정하러'} 가기</a></div></div>`;
  }
  if (x.to >= p.meta.target_episodes) return `<div class="card empty" id="au-start"><p>마지막 화까지 모두 반영했어요. 더 쓸 화가 없어요.</p><div><a class="btn primary" href="${base()}">작품 홈으로</a></div></div>`;
  return `<div class="card empty" id="au-start"><p>${x.to}화까지 남은 화가 없어요.</p><div>${autoPlotHint(x.to + 1).replace('btn small', 'btn primary')}</div></div>`;
}

document.addEventListener('change', (e) => {
  const run = e.target.dataset && e.target.dataset.autoRun;
  if (run && S.autoRunPolicy) {  // 멈춘 실행의 정책: '정책 적용'을 누를 때 보낸다
    const el = e.target;
    S.autoRunPolicy.policy[run.split('.')[1]] = el.type === 'checkbox' ? el.checked : Number(el.value);
    S.autoRunPolicyOpen = true;
    render();
    return;
  }
  const key = e.target.dataset && e.target.dataset.auto;
  if (!key || !S.autoForm) return;
  const el = e.target;
  const v = el.type === 'checkbox' ? el.checked : Number(el.value);
  if (key === 'target') S.autoForm.target = v;
  else S.autoForm.policy[key.split('.')[1]] = v;
  autoEstimate().then(render);
});

Object.assign(actions, {
  autoOpenOnly(v) {
    S.autoOpenOnly = v === 'open';
    render();
  },
  autoLogView(v) {
    S.autoLogView = v;
    render();
  },
  autoPolicyEdit() {
    S.autoRunPolicyOpen = !S.autoRunPolicyOpen;
    if (!S.autoRunPolicyOpen) S.autoRunPolicy = null;
    S.focusTarget = '[data-action="autoPolicyEdit"]';
    render();
  },
  autoFormClose() {
    S.autoFormOpen = false;
    S.focusTarget = '#au-run-h';
    render();
  },
  /** 목차 줄: 그 카드로 옮기고 제목에 포커스 */
  autoGo(k) {
    const el = document.getElementById(`au-${k}`);
    if (!el) return;
    autoTocCur = k;
    outlineRefresh('au-toc', autoToc());
    el.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    (document.getElementById(`au-${k}-h`) || el).focus({ preventScroll: true });
  },
  autoLogAll() {
    S.autoLogAll = true;
    render();
  },
  async autoFormOpen() {
    S.autoFormOpen = true;
    await autoEstimate();
    S.focusTarget = '#au-start-h';
    render();
  },
  async autoBatch(v) {
    const on = v === 'on';
    const r = S.auto && S.auto.run;
    if (r && ['running', 'paused', 'review', 'error'].includes(r.status)) {
      try {
        S.auto = await api('PUT', `/projects/${enc(S.name)}/auto/batch`, { batch: on });
        toast(on ? '배치를 켰어요. 다음 단계부터 배치로 보내요.' : '배치를 껐어요. 다음 단계부터 일반 호출이에요.');
      } catch (e) { toast(e.message, true); }
    }
    if (S.autoForm) S.autoForm.batch = on;
    render();
  },
  async autoStart() {
    const f = S.autoForm;
    if (!(await autoFlushDrafts(f.target))) return;
    const est = S.autoEst && (f.batch ? S.autoEst.on : S.autoEst.off);
    const lines = [`${f.target}화까지 자동으로 써요.`];
    if (est && !est.error) {
      lines.push(`남은 화 ${est.episodes}화 (${est.from}~${est.to}화)`);
      lines.push(`예상 시간 ${est.batch_rounds ? `${autoDuration(est.seconds_min)}~${autoDuration(est.seconds_max)} (배치는 한 번에 최대 24시간까지 걸릴 수 있어요)` : `약 ${autoDuration(est.seconds_min)}`}`);
      lines.push(`예상 비용 ${est.cost == null ? '알 수 없어요 (가격표에 없는 모델)' : autoCost(est.cost)}`);
    }
    lines.push('정해 둔 멈춤 조건에 걸리지 않은 화는 검토 없이 상태를 반영해요.', '시작할까요?');
    if (!confirm(lines.join('\n'))) return;
    await run('자동 집필을 시작하는 중', async () => {
      await saveIfDirty();
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/start`, { target: f.target, batch: f.batch, policy: f.policy });
      S.autoFormOpen = false;
      toast('자동 집필을 시작했어요. 다른 화면으로 옮겨 가도 계속 돌아요.');
      pollJobs(true);
      autoPoll(1000);
    });
  },
  async autoPause() {
    try {
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/pause`);
      toast(S.auto.run.batch ? '멈추는 중이에요. 기다리던 배치는 취소하지 않아, 이어 가면 결과를 받아 와요.' : '지금 단계가 끝나면 멈춰요.');
    } catch (e) { toast(e.message, true); }
    render();
  },
  async autoStop() {
    if (!confirm('자동 집필을 중지할까요? 기다리던 배치 작업이 있으면 취소해요. 이미 반영한 화는 그대로예요.')) return;
    try {
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/stop`);
    } catch (e) { toast(e.message, true); }
    render();
  },
  async autoResume(how) {
    const body = { approve: how === 'approve', rewrite: how === 'rewrite' };
    const r = S.auto.run;
    if (how === 'approve' && !confirm(`${r.ep}화 변경안을 보지 않고 그대로 반영할까요?`)) return;
    if (how === 'rewrite' && !confirm(`${r.ep}화를 다시 쓸까요? 지금 본문은 이전 판으로 남아 집필 화면에서 되돌릴 수 있어요.`)) return;
    if (!(await autoFlushDrafts(r.target))) return;
    await run('이어 가는 중', async () => {
      await saveIfDirty();
      S.auto = await api('POST', `/projects/${enc(S.name)}/auto/resume`, body);
      S.project = await api('GET', `/projects/${enc(S.name)}`);
      S.autoRunPolicyOpen = false;
      pollJobs(true);
      autoPoll(1000);
    });
  },
  autoOpenReview() {
    const r = S.auto.run;
    setDelta(r.ep, structuredClone(r.pending));
    // 변경안을 만든 본문을 기준으로 둔다. 그 뒤 본문을 고쳤으면 상태 승인 화면이 '이 변경안을 만든 뒤 본문을 고쳤어요'를 알린다
    if (r.pending_text) S.deltaBase[r.ep] = r.pending_text;
    // 상태 승인 화면의 '불러오기'는 이미 그 주소라 hashchange 가 생기지 않는다. 그때는 여기서 다시 그린다
    const was = location.hash;
    location.hash = `${base()}/review/${r.ep}`;
    if (location.hash === was) render();
  },
  async autoRevert(n) {
    if (!(await actions.revertFrom(n))) return;  // 상태 승인 화면의 '반영 취소'와 같은 동작
    // 서버가 실행 기록(자동 반영 목록, 로그, 끝남 → 일시정지)도 맞췄다
    S.auto = await api('GET', `/projects/${enc(S.name)}/auto`).catch(() => S.auto);
    await autoEstimate();
    render();
  },
  async autoSetPolicy() {
    try {
      S.auto = await api('PUT', `/projects/${enc(S.name)}/auto/policy`, S.autoRunPolicy.policy);
      S.autoRunPolicy = null;
      S.autoRunPolicyOpen = false;
      toast('승인 정책을 바꿨어요. 다음 판정부터 적용돼요.');
    } catch (e) { toast(e.message, true); }
    render();
  },
});
