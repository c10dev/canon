/* 작품 목록 (#/)과 작품 홈, 장르 고르기. app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 작품 목록 -----

/** AI를 쓸 수 있는지 한 줄로 (작품 목록 · 사이드바). 쓸 수 있으면 빈 글. */
function aiWarning() {
  const h = S.health;
  const cfg = S.config || {};
  if (h && h.local === false) return `AI 연결 안 됨: 로컬 모델 서버가 응답하지 않아요 (${h.local_error || '주소를 확인하세요'}).`;
  if (h && h.mock) return 'mock 모드: AI를 부르지 않고 가짜 결과를 내요. 실제로 쓰려면 설정에서 Gemini나 로컬을 고르세요.';
  if (!cfg.has_key && cfg.gemini_auth === 'vertex') return 'Vertex AI 설정이 덜 됐어요. 설정에서 서비스 계정 키 파일 경로와 프로젝트 ID를 확인하세요.';
  if (!cfg.has_key) return 'Gemini API 키가 없어요. 키 없이는 인물 · 설정을 직접 적을 수 있고, 플롯이 생긴 화부터는 채팅 앱 작업지시서로 쓸 수 있어요.';
  return '';
}

/** 작품 카드의 다음 할 일 한 줄: '3화 상태 승인 대기', '완결', '플롯 없음' (web.list_projects 의 open_ep · open_status) */
function projectNext(x) {
  if (!x.open_ep) return x.planned && x.finalized >= x.episodes ? '완결' : x.planned ? `${x.planned + 1}화부터 플롯 만들기` : '플롯 없음';
  return `${x.open_ep}화 ${{ draft: '플롯 확정 대기', confirmed: '쓰기 대기', written: '상태 승인 대기' }[x.open_status] || ''}`;
}

// 새 작품 폼: 다른 화면에 다녀와도 모든 칸을 함께 남기고, 만들면 함께 비운다 (장르는 genreTarget 이 같은 S.newMeta 에 둔다)
const NEW_FORM = { title: '', name: '', eps: '12', form: 'short', adult: false, style: '', nameEdited: false };
const newForm = () => { const m = genreTarget(); Object.keys(NEW_FORM).forEach((k) => { if (!(k in m)) m[k] = NEW_FORM[k]; }); return m; };
const newFormUsed = (m) => !!(m.title || m.name || m.genres.length || m.eps !== NEW_FORM.eps || m.form !== 'short' || m.adult || m.style);

/** 제목으로 폴더 이름 만들기: 폴더에 못 쓰는 글자를 빼고 빈칸은 - 로 (web.NAME_RE) */
const folderOf = (t) => t.trim().replace(/[/\\:*?"<>|]/g, '').replace(/^\.+/, '').replace(/\s+/g, '-').slice(0, 64);
const FOLDER_BAD = /^\.|[/\\:*?"<>|]/;

/** 작품 홈 · 설정 도우미 머리 아래의 AI 연결 안내 (작품 목록과 같은 글, 설정 화면 링크) */
function aiNote() {
  return aiWarning() ? `<div class="note warn" role="status">${esc(aiWarning())} <a href="#/settings" style="color:inherit;font-weight:700">모델 · API 키 설정</a></div>` : '';
}

function viewProjects() {
  const list = S.projects || [];
  const manage = (x, label) => `<details class="proj-more"><summary class="btn small" aria-label="${esc(label)} 관리">⋯ 관리</summary><div class="row" style="padding-top:8px">
        <button type="button" class="btn small" data-action="dupProject" data-arg="${esc(x.name)}">복제</button>
        <button type="button" class="btn small" data-action="renameProject" data-arg="${esc(x.name)}">폴더 이름 바꾸기</button>
        <button type="button" class="btn small danger" data-action="deleteProject" data-arg="${esc(x.name)}">삭제</button></div></details>`;
  // 같은 갈래 집안은 본편 카드 하나에 묶고, 갈래는 카드 안에 갈라진 화 순서로 (branches.js)
  const branchRow = ({ card: y, depth }) => `<li class="branch-row" style="--depth:${depth}">
      <a href="#/p/${enc(y.name)}"><strong>${esc(y.branch.label || y.name)}</strong> <span class="small">${y.branch.from_ep}화부터 · ${y.finalized} / ${y.episodes}화 · ${esc(projectNext(y))}</span></a>
      <span class="small">폴더 ${esc(y.name)}${y.updated_at ? ` · 고친 때 ${fmtDateTime(y.updated_at)}` : ''}</span>
      ${manage(y, y.branch.label || y.name)}</li>`;
  const cards = branchGroups(list).map(({ card: x, branches }) => `<div class="card tight proj-card">
      <a href="#/p/${enc(x.name)}" style="text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:6px">
      <div class="between"><h3>${esc(x.title || x.name)}</h3><span class="small">${x.finalized} / ${x.episodes}화</span></div>
      <div class="small">${x.form === 'serial' ? '장편' : '단편'} · ${esc(projectNext(x))}${branches.length ? ` · 갈래 ${branches.length}개` : ''}</div>
      <div class="small">${esc(x.genre || '장르 미정')} · 폴더 ${esc(x.name)}${x.updated_at ? ` · 고친 때 ${fmtDateTime(x.updated_at)}` : ''}</div></a>
      ${manage(x, x.title || x.name)}
      ${branches.length ? `<details class="branch-list"><summary class="small">갈래 ${branches.length}개 보기</summary><ul>${branches.map(branchRow).join('')}</ul></details>` : ''}
    </div>`).join('');
  const f = newForm();
  const err = S.newErr || {};
  const errOf = (k) => (err.field === k ? `<div class="small field-err" id="np-${k}-err" role="alert">${esc(err.msg)}</div>` : '');
  const bad = (k) => (err.field === k ? ` aria-invalid="true" aria-describedby="np-${k}-err"` : '');
  return `${header('Canon', '작품', '인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편부터 300화 장편 연재까지 써요. 최근에 고친 작품부터 보여요.', `<a class="btn" href="#/styles">문체 라이브러리</a><a class="btn" href="#/usage">사용량 · 비용</a><a class="btn" href="#/settings">모델 · API 키 설정</a>`)}
    ${aiWarning() ? `<div class="note warn">${esc(aiWarning())} <a class="btn" href="#/settings">설정 열기</a></div>` : ''}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : '<div class="note plain">아직 작품이 없어요. 아래에서 새 작품을 만드세요.</div>'}
    <form class="card" id="np-form" style="max-width:720px" novalidate>
      <div class="between"><h2>새 작품</h2>${newFormUsed(f) ? '<span class="row"><span class="small">이전에 적던 내용을 이어서 보여요</span><button type="button" class="btn small ghost" data-action="clearNewForm">비우기</button></span>' : ''}</div>
      <div class="grid-2">
        <div class="field"><label for="np-title">제목 <span class="hint">필수</span></label><input id="np-title" type="text" placeholder="예: 바다 끝 등대" required value="${esc(f.title)}"${bad('title')}>${errOf('title')}</div>
        <div class="field"><label for="np-eps">총 화수 <span class="hint">단편 10~20, 장편 100~300</span></label><input id="np-eps" type="number" min="4" max="1000" value="${esc(f.eps)}"${bad('eps')}>${errOf('eps')}</div>
      </div>
      <details${err.field === 'name' || f.nameEdited ? ' open' : ''}><summary class="small">폴더 이름 (주소): ${esc(f.name || folderOf(f.title) || '제목에서 만들어요')}</summary>
        <div class="field" style="padding-top:8px"><label for="np-name">폴더 이름 <span class="hint">projects/ 아래 폴더와 화면 주소에 쓰여요. 비우면 제목으로 만들고, 나중에 작품 카드의 '관리'에서 바꿀 수 있어요</span></label>
          <input id="np-name" type="text" placeholder="${esc(folderOf(f.title) || 'lighthouse')}" value="${esc(f.name)}"${bad('name')}>${errOf('name')}</div></details>
      <fieldset class="field form-pick"><legend class="label">형식</legend>
        <label class="row"><input type="radio" name="np-form" id="np-short" value="short"${f.form === 'serial' ? '' : ' checked'}><span><strong>단편</strong> <span class="small">작품 전체를 기승전결 하나로 짜고 모든 화의 플롯을 한 번에 만들어요</span></span></label>
        <label class="row"><input type="radio" name="np-form" id="np-serial" value="serial"${f.form === 'serial' ? ' checked' : ''}><span><strong>장편 연재</strong> <span class="small">부 → 아크(5~30화) → 화로 나눠, 다음 아크의 플롯만 그때그때 만들어요. 200~300화 웹소설용</span></span></label>
      </fieldset>
      ${genrePicker()}
      ${adultCheck(`id="np-adult"${f.adult ? ' checked' : ''}`)}
      ${(S.libs || []).length ? `<div class="field"><label for="np-style">문체 <span class="hint">라이브러리에서 고르면 문체 단계를 건너뛸 수 있어요. 나중에 바꿔도 돼요</span></label>
        <select id="np-style"><option value="">나중에 정하기</option>${S.libs.map((x) => `<option value="${esc(x.id)}"${f.style === x.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('')}</select></div>` : ''}
      <div class="row"><button type="submit" class="btn primary">만들고 설정 시작</button><span class="small">로그라인은 다음 화면에서 칸을 채우며 만들어요.</span></div>
    </form>`;
}

// 새 작품 폼: 칸을 고칠 때마다 S.newMeta 에 남기고, 제목을 적으면 손대지 않은 폴더 이름도 따라간다. Enter 는 만들기
function syncNewForm(el) {
  const f = newForm();
  const v = (id) => ($(id) || {}).value || '';
  Object.assign(f, { title: v('#np-title'), name: v('#np-name'), eps: v('#np-eps'), style: v('#np-style'),
    adult: !!($('#np-adult') || {}).checked, form: ($('#np-serial') || {}).checked ? 'serial' : 'short' });
  if (el.id === 'np-name') f.nameEdited = !!f.name.trim();
  if (el.id === 'np-title') {
    const sum = $('#np-form details > summary');
    if (sum && !f.name) sum.textContent = `폴더 이름 (주소): ${folderOf(f.title) || '제목에서 만들어요'}`;
    $('#np-name').placeholder = folderOf(f.title) || 'lighthouse';
  }
  if (S.newErr && el.getAttribute('aria-invalid')) {  // 고치기 시작하면 그 칸의 오류 표시를 걷는다
    el.removeAttribute('aria-invalid');
    const m = $(`#${el.id}-err`);
    if (m) m.remove();
    S.newErr = null;
  }
}
// change 는 형식을 바꿀 때 총 화수 기본값을 바꾼 뒤에도 온다 (위 np-form 처리)
['input', 'change'].forEach((t) => document.addEventListener(t, (e) => { if (e.target.closest && e.target.closest('#np-form')) syncNewForm(e.target); }));
document.addEventListener('submit', (e) => {
  if (e.target.id !== 'np-form') return;
  e.preventDefault();
  actions.createProject();
});

// ----- 작품 홈 -----

/** 사이드바 자동 집필 메뉴: 진행 중이거나 사람을 기다리면 다른 화면에서도 보이게 상태를 붙인다. */
function autoMenuLabel() {
  const r = S.auto && S.auto.run;
  if (S.auto && S.auto.active) return '자동 집필 · 진행 중';
  const wait = r && { review: '검토 대기', paused: '일시정지', error: '오류로 멈춤' }[r.status];
  return wait ? `자동 집필 · ${wait}` : '자동 집필';
}

function nextStep() {
  const p = P();
  const r = S.auto && S.auto.run;
  if (r && r.status === 'review' && r.pending && !S.deltas[r.ep]) return [`${r.ep}화 자동 집필 변경안 검토`, base() + '/auto'];
  if (autoOn()) return [`자동 집필 진행 중${autoEp() ? ` (${autoEp()}화)` : ''}`, base() + '/auto'];
  if (!p.characters.length) return ['설정 시작', base() + '/setup'];
  if (serial()) {
    const open = p.episodes.find((e) => e.status !== 'finalized');
    if (!open && plannedUntil() < p.meta.target_episodes) return [`다음 아크 기획 (${plannedUntil() + 1}화부터)`, base() + '/arc'];
  }
  if (!beats().length || !p.episodes.length) return [`${stepLabel('arc')} 만들기`, base() + '/arc'];
  const e = ep(currentEp());
  if (e.status === 'draft') return [`${e.plot.number}화 플롯 확정`, base() + '/arc'];
  if (e.status === 'confirmed') return [`${e.plot.number}화 쓰기`, `${base()}/write/${e.plot.number}`];
  if (e.status === 'written') return checkState(e).done ? [`${e.plot.number}화 상태 승인`, `${base()}/review/${e.plot.number}`] : [`${e.plot.number}화 검수`, `${base()}/check/${e.plot.number}`];
  return ['완결 원고 보기', `${base()}/write/${e.plot.number}`];
}

/** 한 화의 검수 세션 (check.js 와 진행 막대가 함께 쓴다). checked: 한 번이라도 검수함, stale: 마지막 회차 뒤에 본문을 고침,
    open: 열린 지적 수 (findings.merge 가 합친 지적 중 status open), done: 검수했고 그 뒤 고치지 않았고 열린 지적이 없음. */
function checkState(e) {
  // 이 지적만 다시 검수로 풀린 고침안 묶음은 그 검수가 이미 본 수정이라 '검수 뒤 고침'으로 세지 않는다
  const seen = new Set((e.findings || []).filter((f) => f.closed_by === 'one' && f.fix_group).map((f) => f.fix_group));
  const lastEdit = [...(e.edits || [])].reverse().find((x) => !x.undone && !(x.group && seen.has(x.group)));
  const checked = !!e.checked_at;
  const stale = checked && !!(lastEdit && lastEdit.at > e.checked_at);
  const open = (e.findings || []).filter((f) => f.status === 'open').length;
  return { checked, stale, open, done: checked && !stale && !open };
}

/** 화 하나의 네 단계: 플롯 확정 · 집필 · 검수 · 승인. 검수는 마지막 검수 뒤에 본문을 고치지 않았고 열린 지적이 없을 때 끝난 것으로 본다
    (checkState). 검수 없이, 또는 열린 지적을 두고 반영한 화는 검수 칸이 빈 채로 남는다. */
function epSteps(e) {
  const rank = { draft: 0, confirmed: 1, written: 2, finalized: 3 }[e.status] || 0;
  return [['plot', '플롯 확정', rank >= 1], ['write', '집필', rank >= 2], ['check', '검수', rank >= 2 && checkState(e).done], ['review', '승인', rank >= 3]]
    .map(([key, label, done]) => ({ key, label, done }));
}

/** 화 칸 · 카드 아래의 네 칸 막대. 글은 aria-label 에 따로 적으므로 막대는 눈으로만 본다 */
function stepBar(e) {
  return `<span class="ep-steps" aria-hidden="true">${epSteps(e).map((s) => `<i class="${s.done ? 'on' : ''}" title="${s.label}"></i>`).join('')}</span>`;
}

/** 진행 단계 글: '3/4단계, 검수 전' 처럼 스크린리더와 칸 제목에 쓴다 */
function stepText(e) {
  const steps = epSteps(e);
  const next = steps.find((s) => !s.done);
  const skipped = e.status === 'finalized' && next;
  const left = skipped && checkState(e).open ? ', 열린 지적 두고 반영' : skipped ? ', 검수 없이 반영' : '';
  return `${steps.filter((s) => s.done).length}/4단계${left || (next ? `, ${next.label} 전` : '')}`;
}

/** 연재 일정(Project.release)으로 비축분과 하루 목표를 센다. 올릴 수 있는 화는 1화부터 이어서 반영을 마친 화까지다
    (순서 규칙상 반영은 1화부터 차례로 끝난다). 일정이 없으면(per_week 0) 비축 일수를 계산하지 않는다. */
function releasePlan(p) {
  const r = p.release || {};
  const perWeek = Math.min(70, Math.max(0, Number(r.per_week) || 0));
  const released = Math.max(0, Number(r.released) || 0);
  const fin = new Set(p.episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));
  let ready = 0;
  while (fin.has(ready + 1)) ready += 1;
  const buffer = Math.max(0, ready - released);
  const perDay = perWeek / 7;
  return { perWeek, released, ready, buffer, over: released > ready, perDay, bufferDays: perWeek ? Math.floor(buffer / perDay) : null };
}

/** 장편 스냅샷 줄 (Settings.keep_snapshots): 남은 스냅샷 수와 모두 남기기 켜기 · 끄기. 연구용 작품은 켜 둔다 */
function snapshotRow(p) {
  const on = !!p.settings.keep_snapshots;
  const tip = on ? '끄면 다음 반영 때 0화 · 아크 끝 · 최근 20화만 남기고 지워요. 지운 화는 되살리지 못해요'
    : '켜면 반영할 때마다 찍는 화별 상태를 지우지 않아요. 이미 지운 화는 되살리지 못해요. 연구용 작품에 켜 두세요';
  return `<div class="small">화별 상태 기록(스냅샷) ${p.snapshots.length}개 · ${on ? '모두 남겨요' : '0화 · 아크 끝 · 최근 20화만 남겨요'}
    <button type="button" class="btn small" aria-pressed="${on}" data-action="toggleKeepSnapshots" title="${tip}">모두 남기기 ${on ? '켜짐' : '꺼짐'}</button></div>`;
}

/** 작품 홈 '화별 진행' 카드 머리의 연재 일정 줄: 올린 화 · 비축 · 하루 목표, 접힌 칸에서 일정 고치기 */
function releaseRow(p) {
  const r = releasePlan(p);
  const fmt = (x) => (Math.round(x * 10) / 10).toLocaleString();
  const days = r.bufferDays === null ? '' : ` (약 ${r.bufferDays.toLocaleString()}일분)`;
  const low = r.bufferDays !== null && r.bufferDays < 3;
  const goal = r.perWeek
    ? `하루 목표 ${fmt(r.perDay)}화 (약 ${Math.round(r.perDay * p.meta.words_per_episode).toLocaleString()}자)`
    : '일주일에 올리는 화 수를 정하면 비축 일수와 하루 목표를 계산해요';
  const warn = r.over ? `<div class="note warn">올린 화(${r.released}화)가 반영을 마친 화(${r.ready}화)보다 뒤예요. 올린 화를 고치거나 남은 화를 반영하세요.</div>`
    : low ? `<div class="note warn">비축이 ${r.buffer ? `${r.buffer}화(약 ${r.bufferDays}일분)뿐이에요` : '없어요'}. 오늘 ${Math.max(1, Math.ceil(r.perDay))}화를 반영하면 일정을 지킬 수 있어요.</div>` : '';
  return `<div class="release-row">
      <span><strong>올린 화</strong> ${r.released ? `${r.released}화까지` : '없음'}</span>
      <span><strong>비축</strong> ${r.buffer}화${days}</span>
      <span class="small">${goal}</span>
      <button type="button" class="btn small" data-action="releaseOne"${r.released >= p.episodes.length ? ' disabled' : ''}>${r.released + 1}화를 올렸어요</button>
    </div>
    <details class="release-edit"><summary class="small">연재 일정 고치기</summary><div class="row" style="align-items:flex-end">
      ${input('일주일에 올리는 화 수', 'release.per_week', { type: 'number', min: 0, max: 70, hint: '0이면 정하지 않음' })}
      ${input('올린 마지막 화', 'release.released', { type: 'number', min: 0, max: p.episodes.length })}
    </div></details>${warn}`;
}

function viewHome() {
  const p = P();
  const m = p.meta;
  const eps = p.episodes;
  const count = (st) => eps.filter((e) => e.status === st).length;
  const confirmed = eps.length - count('draft');
  const written = count('written') + count('finalized');
  const fin = count('finalized');
  const hasStyle = !!(p.style.narration_pov || p.style.sample_passages.length);
  const stage = (cls, st, title, sub, href) => `<a class="stage ${cls}" href="${href}"><div class="bar"></div><div class="st">${st}</div><div style="font-size:0.875rem;font-weight:700">${title}</div><div class="small">${sub}</div></a>`;
  const state = (ok, partial) => (ok ? ['done', '완료'] : partial ? ['doing', '진행 중'] : ['', '시작 전']);
  const [s1c, s1t] = state(p.characters.length > 0);
  const [s2c, s2t] = state(hasStyle);
  // 3단계는 구조(기승전결 · 아크)와 플롯 확정을 한 칸에 보인다. 둘 다 끝나야 완료
  const arcDone = serial() ? plannedUntil() >= m.target_episodes : p.arc.length === 4;
  const arcStarted = serial() ? p.story_arcs.length > 0 : p.arc.length > 0;
  const [s3c, s3t] = state(arcDone && eps.length && confirmed === m.target_episodes, arcStarted || confirmed > 0);
  const [s5c, s5t] = state(written === m.target_episodes, written > 0);
  const [s6c, s6t] = state(fin === m.target_episodes, fin > 0);
  const checked = p.episodes.filter((e) => e.status !== 'draft' && checkState(e).done).length;  // 검수 칸이 찬 화
  const [skc, skt] = state(checked === m.target_episodes, checked > 0);
  const cur = currentEp();
  const [nextLabel, nextHref] = nextStep();
  // 장편: 끝났는데 요약이 없는 아크 · 부 (부 · 아크 화면 경고 줄, pipeline.pending_recaps 와 같은 규칙). 요약이 없으면 줄거리가 접히지 않는다
  const summed = serial() ? p.parts.filter((x) => x.summary) : [];
  const recapArcs = serial() ? [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep).filter((a) => !a.summary && arcFinished(a) && !summed.some((x) => x.start_ep <= a.start_ep && a.start_ep <= x.end_ep)) : [];
  const recapParts = serial() ? p.parts.filter((x) => !x.summary && arcFinished(x)) : [];
  const recapN = recapArcs.length + recapParts.length;
  const recapBtn = recapArcs.length ? `<a class="btn" href="${base()}/arc/a${recapArcs[0].number}">아크 ${recapArcs[0].number} 요약</a>`
    : recapParts.length ? `<a class="btn" href="${base()}/arc">${recapParts[0].number}부 요약</a>` : '';

  // 단편 기승전결: 칸 폭을 지키려고 칸은 장편처럼 줄을 바꿔 놓고, 구간은 칸 위 띠 대신 칸 아래 테두리 색과 이 머리 줄로 보인다
  const actBand = p.arc.length && !serial() ? `<div class="act-rail">${actGroups(p.arc).map((g) => `<span class="act-chip ${actClass(g.names[0])}">${g.names.join('·')} ${epRange(g.start, g.end)}</span>`).join('')}</div>` : '';
  // 장편은 지금 쓰는 부(없으면 지금 아크 근처 60화)만 칸으로 보인다
  const curPart = serial() ? p.parts.find((x) => x.start_ep <= cur && cur <= x.end_ep) : null;
  const shown = !serial() ? eps : curPart ? eps.filter((e) => e.plot.number >= curPart.start_ep && e.plot.number <= curPart.end_ep)
    : eps.filter((e) => Math.abs(e.plot.number - cur) <= 30);
  const arcBand = serial() && p.story_arcs.length ? `<div class="arc-rail">${p.story_arcs.filter((a) => shown.some((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep)).map((a) => `<a class="arc-chip" href="${base()}/arc/a${a.number}"><strong>아크 ${a.number}</strong> <span>${a.start_ep}~${a.end_ep}화 ${esc(a.title)}</span></a>`).join('')}</div>` : '';
  const released = releasePlan(p).released;
  const cells = shown.map((e) => {
    const n = e.plot.number;
    const href = e.status === 'draft' ? `${base()}/arc/${n}` : e.status === 'written' ? `${base()}/${checkState(e).done ? 'review' : 'check'}/${n}` : `${base()}/write/${n}`;
    const act = !serial() && actOf(n);
    const st = e.auto ? '자동 반영' : STATUS[e.status].replace('플롯 ', '').replace('본문 ', '');
    const now = n === cur && e.status !== 'finalized';
    // 좁은 폭에서는 상태 글자를 눈으로만 감춘다. 이름은 aria-label 로 늘 '3화 작성됨 · 제목'
    const up = n <= released;
    return `<a class="ep-cell ${e.status}${now ? ' current' : ''}${up ? ' released' : ''}${act ? ' ' + actClass(act.name) + '-edge' : ''}" href="${href}" title="${esc(`${e.plot.title ? e.plot.title + ' · ' : ''}${stepText(e)}`)}" aria-label="${esc(`${n}화 ${st} · ${stepText(e)}${up ? ' · 올린 화' : ''}${now ? ' · 지금 화' : ''}${e.plot.title ? ' · ' + e.plot.title : ''}`)}"><strong>${n}</strong><span>${st}</span>${stepBar(e)}</a>`;
  }).join('');

  const states = p.characters.map((c) => {
    const s = p.states.find((x) => x.character_id === c.id) || {};
    const lines = [['감정', s.emotional_state], ['목표', s.current_goal], ['위치', s.location], ['차림', s.attire]].filter(([, v]) => v);
    return `<div class="kv"><div style="font-size:0.875rem;font-weight:700">${esc(c.name)} <span class="small" style="font-weight:400">${esc(c.role)}</span></div>${lines.map(([k, v]) => `<div class="line">${k}: ${esc(v)}</div>`).join('') || '<div class="line small">아직 변화 없음</div>'}</div>`;
  }).join('');
  const openFs = p.foreshadows.filter((f) => f.status === 'open');
  const last = p.history.length ? p.history[p.history.length - 1] : null;
  const lastWarn = last ? last.warnings : [];

  return `${header(`${esc(m.genre || '장르 미정')}${m.adult ? ' · 성인' : ''} · 전 ${m.target_episodes}화 · 화당 ${Number(m.words_per_episode).toLocaleString()}자`, m.title || S.name, esc(m.logline), `${!serial() && fin && fin === m.target_episodes ? `<a class="btn" href="${base()}/convert">장편으로 늘리기</a>` : ''}${nextHref === `${base()}/arc` ? '' : `<a class="btn" href="${base()}/arc">${stepLabel('arc')}</a>`}${fin ? '<button type="button" class="btn" data-action="branchOpen" title="이 작품은 그대로 두고, 사본에서 다른 전개를 써요">갈래 만들기</button>' : ''}${recapBtn}<a class="btn primary" href="${nextHref}">${esc(nextLabel)}</a>`)}
    ${autoLockNote()}
    ${aiNote()}
    <section class="card" aria-label="진행 단계"><div class="stages">
      ${stage(s1c, s1t, `1 ${stepLabel('setup')}`, `인물 ${p.characters.length} · 관계 ${p.relationships.length}`, base() + '/setup')}
      ${stage(s2c, s2t, `2 ${stepLabel('style')}`, hasStyle ? `대표 문단 ${p.style.sample_passages.length}개` : '선택 사항', base() + '/style')}
      ${stage(s3c, s3t, `3 ${stepLabel('arc')}`, `${serial() ? (p.story_arcs.length ? `아크 ${p.story_arcs.length}개 · ${plannedUntil()}화까지` : '아크 없음') : p.arc.length ? '4구간' : '구조 없음'} · 확정 ${confirmed} / ${m.target_episodes}화${recapN ? ` · 요약 필요 ${recapN}개` : ''}`, base() + '/arc')}
      ${stage(s5c, s5t, `4 ${stepLabel('write')}`, `${written} / ${m.target_episodes}화`, `${base()}/write/${cur}`)}
      ${stage(skc, skt, `5 ${stepLabel('check')}`, `${checked} / ${m.target_episodes}화`, `${base()}/check/${cur}`)}
      ${stage(s6c, s6t, `6 ${stepLabel('review')}`, `${fin} / ${m.target_episodes}화`, `${base()}/review/${cur}`)}
    </div></section>
    <section class="card">
      <div class="between"><h2>화별 진행</h2><div class="legend">
        <span><i style="background:var(--chip);border:1px solid var(--line-strong)"></i>플롯 초안</span>
        <span><i style="background:var(--accent)"></i>플롯 확정</span>
        <span><i style="background:var(--amber)"></i>본문 작성됨</span>
        <span><i style="background:var(--green)"></i>반영 완료</span>
        <span><span class="legend-steps" aria-hidden="true"><b></b><b></b><b class="off"></b><b class="off"></b></span>확정 · 집필 · 검수 · 승인</span>
        <span>↑ 올린 화</span></div></div>
      ${eps.length ? releaseRow(p) : ''}
      ${eps.length ? `${actBand}${arcBand}<div class="ep-grid">${cells}</div>${curPart ? `<div class="small">${curPart.number}부 ${esc(curPart.title)} (${curPart.start_ep}~${curPart.end_ep}화)만 보여요. 전체는 <a href="${base()}/arc">부 · 아크</a>에서 보세요.</div>` : ''}` : `<div class="note plain">아직 화별 플롯이 없어요. 다음 할 일: <a href="${nextHref}">${esc(nextLabel)}</a></div>`}
      ${serial() ? snapshotRow(p) : ''}
      ${lastWarn.length ? `<div class="note warn">${last.episode}화 반영 때 검수 경고: ${lastWarn.map(esc).join(' / ')} <a href="${base()}/write/${last.episode}" style="color:inherit;font-weight:700">${last.episode}화 보기</a></div>` : ''}
      ${eps.some((e) => e.status === 'written') ? `<div class="note warn">${cur}화 본문이 작성됐어요. 상태 변경안을 승인해야 다음 화를 쓸 수 있어요. <a href="${base()}/review/${cur}" style="color:inherit;font-weight:700">${cur}화 상태 승인</a></div>` : ''}
    </section>
    ${branchHomeCard()}
    <div class="grid-auto">
      <section class="card"><div class="between"><h2>인물 현재 상태</h2><span class="small">${fin ? fin + '화 기준' : '시작 시점'}</span></div>${states || '<div class="small">인물이 없어요</div>'}<a class="card-more" href="${base()}/cast">인물 · 관계 전체 보기</a></section>
      <section class="card">${relationHeader('관계')}${p.relationships.length ? relationLines(S.relations) : `<div class="small">관계가 없어요. <a href="${base()}/setup">설정 도우미</a>에서 관계를 추가하세요.</div>`}</section>
      <section class="card"><div class="between"><h2>열린 복선</h2><a class="small" href="${base()}/foreshadow">${openFs.length}개 · 복선 센터</a></div>
        ${openFs.map((f) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap"><span class="chip">${f.planted_ep}화</span><div style="font-size:0.8125rem;line-height:1.5">${esc(f.description)}<br><span class="small">${esc(f.id)}</span></div></div>`).join('') || '<div class="small">없음</div>'}
      </section>
      <section class="card"><div class="between"><h2>확정 사실</h2><span class="small">${p.facts.length}개</span></div>
        ${p.facts.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:8px;font-size:0.8125rem;line-height:1.5;color:var(--text-2)">${p.facts.slice(-8).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '<div class="small">없음</div>'}
        ${p.facts.length > 8 ? `<details><summary class="small">전체 ${p.facts.length}개 보기</summary><ol style="padding-left:22px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5;color:var(--text-2);margin-top:8px">${p.facts.map((f) => `<li>${esc(f)}</li>`).join('')}</ol></details>` : ''}
      </section>
    </div>`;
}

// ----- 장르 -----

function genreById(id) {
  return (S.genres || []).find((g) => g.id === id);
}

function genreLabel(m) {
  return m.genres.map((id) => (genreById(id) ? genreById(id).name : id)).join(' · ') || m.genre || '';
}

// 설정 화면에서는 작품의 meta, 작품 목록의 새 작품 폼에서는 아직 저장하지 않은 S.newMeta
function genreTarget() {
  if (S.route[0] === 'p' && P()) return P().meta;
  if (!S.newMeta) S.newMeta = { genres: [], genre: '' };
  return S.newMeta;
}

// 다른 입력칸을 지우지 않도록 장르 고르기 부분만 다시 그린다
function syncGenre() {
  const m = genreTarget();
  m.genre = genreLabel(m);
  if (m !== S.newMeta) { markDirty(); checkNames(); }  // 장르도 자동 이름 스타일을 정한다 (naming.detect_style)
  const box = $('#genre-picker');
  if (box) box.outerHTML = genrePicker();
  else render();
}

function genreGuide(g) {
  const row = (k, v) => (v && v.length ? `<div class="g-row"><span class="g-k">${k}</span><span>${esc(Array.isArray(v) ? v.join(', ') : v)}</span></div>` : '');
  return `<details class="genre-guide"><summary><strong>${esc(g.name)}</strong><div class="small">${esc(g.summary)}</div></summary>
    ${row('독자가 기대하는 것', g.reader_expects)}${row('관습', g.conventions)}${row('자주 쓰는 소재', g.tropes)}${row('전개 속도', g.pacing)}${row('피할 것', g.avoid)}</details>`;
}

function genrePicker() {
  const m = genreTarget();
  const cat = S.genres || [];
  const opts = (kind) => cat.filter((g) => g.kind === kind).map((g) => `<button type="button" aria-pressed="${m.genres.includes(g.id)}" data-action="toggleGenre" data-arg="${esc(g.id)}" title="${esc(g.summary)}">${esc(g.name)}</button>`).join('');
  const custom = m.genres.filter((id) => !genreById(id));
  const picked = m.genres.map(genreById).filter(Boolean);
  return `<div id="genre-picker" class="genre-picker"><div class="field"><span class="label-text">장르 <span class="hint">여러 개 고를 수 있어요. 고른 장르의 안내가 AI 프롬프트에 들어가요</span></span>
      <div class="genre-opts" role="group" aria-label="장르">${opts('장르')}</div>
      <div class="small" style="margin-top:4px">요소</div>
      <div class="genre-opts" role="group" aria-label="요소">${opts('요소')}${custom.map((c) => `<button type="button" aria-pressed="true" data-action="toggleGenre" data-arg="${esc(c)}" title="직접 적은 장르, 누르면 빠져요">${esc(c)} ✕</button>`).join('')}</div>
      <div class="row" style="flex-wrap:nowrap"><input id="genre-custom" type="text" aria-label="직접 적는 장르" placeholder="목록에 없으면 직접 적기 (예: 오컬트)"><button type="button" class="btn small" style="white-space:nowrap;flex:none" data-action="addCustomGenre">추가</button></div>
    </div>
    ${picked.length ? `<div class="genre-guides">${picked.map(genreGuide).join('')}</div>` : ''}</div>`;
}

function adultCheck(attrs) {
  return `<label class="check-row"><input type="checkbox" ${attrs}><span><strong>성인물</strong> <span class="small">성인 독자 대상. 끄면 노골적인 성적 묘사와 과도한 잔혹 묘사를 피하도록 지시해요</span></span></label>`;
}

Object.assign(actions, {
  /** 장편 스냅샷 모두 남기기 켜기 · 끄기 (Settings.keep_snapshots). 바로 서버에 저장한다 */
  async toggleKeepSnapshots() {
    const on = !P().settings.keep_snapshots;
    P().settings.keep_snapshots = on;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/keep-snapshots`, { on });
    } catch (e) {
      toast(e.message, true);
    }
  },
  /** 연재처에 다음 화를 올렸다고 적고 바로 저장한다 (작품 홈의 연재 일정 줄) */
  async releaseOne() {
    const r = P().release;
    r.released = Math.min((Number(r.released) || 0) + 1, P().episodes.length);
    markDirty();
    await actions.save();
  },
});
