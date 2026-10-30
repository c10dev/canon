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

/** 작품 카드의 다음 할 일 한 줄: '3화 검수 대기', '3화 상태 승인 대기', '완결', '플롯 없음' (web.list_projects 의 open_ep · open_status · open_checked).
    본문을 쓴 화는 사이드바 · 작품 홈의 다음 할 일(nextStep)처럼 검수가 끝나야 상태 승인 차례다 */
function projectNext(x) {
  if (!x.open_ep) return x.planned && x.finalized >= x.episodes ? '완결' : x.planned ? `${x.planned + 1}화부터 플롯 만들기` : '플롯 없음';
  const written = x.open_checked ? '상태 승인 대기' : '검수 대기';
  return `${x.open_ep}화 ${{ draft: '플롯 확정 대기', confirmed: '쓰기 대기', written }[x.open_status] || ''}`;
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
  return aiWarning() ? `<div class="note warn" role="status">${esc(aiWarning())} <a href="#/settings/ai" style="color:inherit;font-weight:700">AI 연결 설정</a></div>` : '';
}

// 작품 목록은 머리(새 작품 · 새 플레이 · 도구 링크) → 새 작품 칸(누르면 편다) → 이어 쓰기 → 모든 작품 한 줄 목록 순서다.
// 목록은 찾기 · 거르기 · 정렬을 거친다. 계산 plStatus · plRows 는 화면을 모르는 순수 함수다 (tests/test_projects_js.py).

const PL_RECENT = 3;  // 이어 쓰기 카드 수. 작품이 이보다 많을 때만 보인다
const PL_FILTERS = [['all', '전체'], ['writing', '쓰는 중'], ['fresh', '시작 전'], ['done', '완결']];
const PL_SORTS = [['updated', '고친 때'], ['title', '제목'], ['progress', '진행']];

/** 작품 카드의 상태: done 완결(projectNext 의 '완결'과 같은 규칙), fresh 반영한 화 없음, writing 그 밖 */
function plStatus(x) {
  if (x.planned && x.finalized >= x.episodes) return 'done';
  return x.finalized ? 'writing' : 'fresh';
}

/** 목록 줄 묶음: 본편 카드 하나에 갈래(branchGroups)와 플레이 사본을 붙이고, 찾기(q: 제목 · 폴더 · 장르, 갈래 · 플레이 이름도) ·
    거르기(filter: plStatus) · 정렬(sort)을 한다. counts 는 찾기만 거친 묶음의 상태별 수. lost 는 세계 작품을 찾지 못한 플레이 */
function plRows(list, { q = '', filter = 'all', sort = 'updated' } = {}) {
  const works = list.filter((x) => !x.play);
  const playsOf = (name) => list.filter((y) => y.play && y.play.world === name);
  const lost = list.filter((y) => y.play && !works.some((x) => x.name === y.play.world));
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const text = (x) => [x.title, x.name, x.genre, x.branch && x.branch.label, x.play && x.play.title].filter(Boolean).join(' ').toLowerCase();
  const hit = (xs) => !words.length || words.every((w) => xs.some((x) => text(x).includes(w)));
  const groups = branchGroups(works).map((g) => ({ ...g, plays: playsOf(g.card.name), status: plStatus(g.card) }))
    .filter((g) => hit([g.card, ...g.branches.map((b) => b.card), ...g.plays]));
  const counts = { all: groups.length, writing: 0, fresh: 0, done: 0 };
  groups.forEach((g) => { counts[g.status] += 1; });
  const shown = groups.filter((g) => filter === 'all' || g.status === filter);
  const rate = (x) => (x.episodes ? x.finalized / x.episodes : 0);
  if (sort === 'title') shown.sort((a, b) => (a.card.title || a.card.name).localeCompare(b.card.title || b.card.name, 'ko'));
  if (sort === 'progress') shown.sort((a, b) => rate(b.card) - rate(a.card) || b.card.finalized - a.card.finalized);
  return { groups: shown, counts, lost: lost.filter((y) => hit([y])) };
}

/** ⋯ 관리 메뉴: 복제 · 폴더 이름 바꾸기 · 삭제 (app.js menuBtn) */
function plManage(x, label) {
  const dots = '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="9" r="1.6"></circle><circle cx="9" cy="9" r="1.6"></circle><circle cx="14" cy="9" r="1.6"></circle></svg>';
  return menuBtn(`pl:${x.name}`, dots, () => `<button type="button" class="pop-item" data-action="dupProject" data-arg="${esc(x.name)}">복제</button>
      <button type="button" class="pop-item" data-action="renameProject" data-arg="${esc(x.name)}">폴더 이름 바꾸기</button>
      <div class="pop-sep" role="separator"></div>
      <button type="button" class="pop-item danger" data-action="deleteProject" data-arg="${esc(x.name)}">삭제</button>`, { cls: 'btn icon-btn', aria: `${label} 관리` });
}

const plBar = (fin, total) => `<span class="pl-prog"><i role="img" aria-label="${total}화 중 ${fin}화 반영"><b style="width:${total ? Math.min(100, Math.round((fin / total) * 100)) : 0}%"></b></i><span>${fin} / ${total}화</span></span>`;
const plNextChip = (x) => `<span class="chip ${{ done: 'finalized', fresh: 'draft', writing: x.open_status || 'draft' }[plStatus(x)]}">${esc(projectNext(x))}</span>`;
const plWhen = (x) => (x.updated_at ? fmtDateTime(x.updated_at) : '');

function plRow(x, { depth = 0, kind, title, href, tags = '', next, prog } = {}) {
  const label = title || x.title || x.name;
  return `<li class="pl-row${depth ? ' sub' : ''}" style="--depth:${depth}">
    <div class="pl-title"><a href="${href || `#/p/${enc(x.name)}`}"><strong>${esc(label)}</strong></a>${tags}<span class="small">폴더 ${esc(x.name)}</span></div>
    <span class="pl-kind small">${kind}</span>
    ${prog === undefined ? plBar(x.finalized, x.episodes) : prog}
    <span class="pl-next">${next || plNextChip(x)}</span>
    <span class="pl-when small">${plWhen(x)}</span>
    ${plManage(x, label)}</li>`;
}

function plGroupRows(g) {
  const x = g.card;
  const tags = [g.branches.length ? `갈래 ${g.branches.length}` : '', g.plays.length ? `플레이 ${g.plays.length}` : ''].filter(Boolean).map((t) => `<span class="chip">${t}</span>`).join('');
  const playRow = (y, depth) => {
    const p = y.play;
    const sub = [p.origin === 'random' ? '무작위 출생' : '세계 인물', p.days ? `작품 속 ${p.days}일` : '', `결정 ${p.decisions}번`].filter(Boolean).join(' · ');
    return plRow(y, { depth, kind: `플레이 · ${esc(sub)}`, title: p.title, href: `#/play/${enc(y.name)}${p.ending ? '/life' : ''}`, prog: '<span class="pl-prog small">-</span>',
      next: `<span class="chip${p.ending ? '' : ' finalized'}">${esc(p.ending || (p.waiting ? '결정을 기다리는 중' : '진행 중'))}</span>` });
  };
  return plRow(x, { kind: `${x.form === 'serial' ? '장편' : '단편'} · ${esc(x.genre || '장르 미정')}`, tags })
    + g.branches.map(({ card: y, depth }) => plRow(y, { depth: depth + 1, kind: `갈래 · ${y.branch.from_ep}화부터`, title: y.branch.label || y.name })).join('')
    + g.plays.map((y) => playRow(y, 1)).join('');
}

/** 모든 작품 목록 몸통. 찾기 칸을 칠 때는 이것만 다시 그려 한글 조합을 끊지 않는다 */
function plBody() {
  const r = plRows(S.projects || [], { q: S.plQuery || '', filter: S.plFilter || 'all', sort: S.plSort || 'updated' });
  const seg = `<div class="seg" role="group" aria-label="상태로 거르기">${PL_FILTERS.map(([k, l]) => `<button type="button" aria-pressed="${(S.plFilter || 'all') === k}" data-action="plFilter" data-arg="${k}">${l} ${r.counts[k]}</button>`).join('')}</div>`;
  const rows = r.groups.map(plGroupRows).join('') + r.lost.map((y) => plRow(y, { kind: '플레이 · 세계 작품을 찾지 못함', title: y.play.title, href: `#/play/${enc(y.name)}`, prog: '<span class="pl-prog small">-</span>',
    next: '<span class="chip">세계 작품 없음</span>' })).join('');
  return `${seg}${rows ? `<ul class="pl-list" aria-label="작품 ${r.groups.length}개"><li class="pl-row pl-headrow" aria-hidden="true"><span>제목</span><span>형식 · 장르</span><span>진행</span><span>다음 할 일</span><span>고친 때</span><span></span></li>${rows}</ul>`
    : `<p class="note plain">${S.plQuery ? `'${esc(S.plQuery)}'에 맞는 작품이 없어요.` : '이 상태의 작품이 없어요.'}</p>`}`;
}

function newProjectForm(open) {
  const f = newForm();
  const err = S.newErr || {};
  const errOf = (k) => (err.field === k ? `<div class="small field-err" id="np-${k}-err" role="alert">${esc(err.msg)}</div>` : '');
  const bad = (k) => (err.field === k ? ` aria-invalid="true" aria-describedby="np-${k}-err"` : '');
  return `<form class="card np-card" id="np-form" novalidate aria-labelledby="np-h"${open ? '' : ' hidden'}>
      <div class="between"><h2 id="np-h">새 작품</h2>${newFormUsed(f) ? '<span class="row"><span class="small">이전에 적던 내용을 이어서 보여요</span><button type="button" class="btn small ghost" data-action="clearNewForm">비우기</button></span>' : '<span class="small">로그라인과 인물은 다음 화면에서 채워요</span>'}</div>
      <div class="grid-2">
        <div class="field"><label for="np-title">제목 <span class="hint">필수</span></label><input id="np-title" type="text" placeholder="예: 바다 끝 등대" required value="${esc(f.title)}"${bad('title')}>${errOf('title')}</div>
        <div class="field"><label for="np-eps">총 화수 <span class="hint">단편 10~20, 장편 100~300</span></label><input id="np-eps" type="number" min="4" max="1000" value="${esc(f.eps)}"${bad('eps')}>${errOf('eps')}</div>
      </div>
      <details${err.field === 'name' || f.nameEdited ? ' open' : ''}><summary class="small">폴더 이름 (주소): ${esc(f.name || folderOf(f.title) || '제목에서 만들어요')}</summary>
        <div class="field" style="padding-top:8px"><label for="np-name">폴더 이름 <span class="hint">projects/ 아래 폴더와 화면 주소에 쓰여요. 비우면 제목으로 만들고, 나중에 작품 줄의 ⋯ 에서 바꿀 수 있어요</span></label>
          <input id="np-name" type="text" placeholder="${esc(folderOf(f.title) || 'lighthouse')}" value="${esc(f.name)}"${bad('name')}>${errOf('name')}</div></details>
      <fieldset class="field form-pick"><legend class="label">형식</legend>
        <label class="row"><input type="radio" name="np-form" id="np-short" value="short"${f.form === 'serial' ? '' : ' checked'}><span><strong>단편</strong> <span class="small">작품 전체를 기승전결 하나로 짜고 모든 화의 플롯을 한 번에 만들어요</span></span></label>
        <label class="row"><input type="radio" name="np-form" id="np-serial" value="serial"${f.form === 'serial' ? ' checked' : ''}><span><strong>장편 연재</strong> <span class="small">부 → 아크(5~30화) → 화로 나눠, 다음 아크의 플롯만 그때그때 만들어요. 200~300화 웹소설용</span></span></label>
      </fieldset>
      ${genrePicker()}
      ${adultCheck(`id="np-adult"${f.adult ? ' checked' : ''}`)}
      ${(S.libs || []).length ? `<div class="field"><label for="np-style">문체 <span class="hint">라이브러리에서 고르면 문체 단계를 건너뛸 수 있어요. 나중에 바꿔도 돼요</span></label>
        <select id="np-style"><option value="">나중에 정하기</option>${S.libs.map((x) => `<option value="${esc(x.id)}"${f.style === x.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('')}</select></div>` : ''}
      <div class="row np-actions">${(S.projects || []).length ? '<button type="button" class="btn" data-action="npToggle">닫기</button>' : ''}<button type="submit" class="btn primary">만들고 설정 시작</button></div>
    </form>`;
}

function viewProjects() {
  const list = S.projects || [];
  const f = newForm();
  // 새 작품 칸: 오류가 있거나 작품이 없으면 늘 편다. 그 밖에는 작가가 연 · 닫은 대로, 정하지 않았으면 적던 내용이 있을 때 편다
  const open = !!S.newErr || !list.length || (S.npOpen ?? newFormUsed(f));
  const recent = list.length > PL_RECENT ? plRows(list).groups.filter((g) => g.status !== 'done').slice(0, PL_RECENT) : [];
  const card = (g) => {
    const x = g.card;
    const more = [g.branches.length ? `갈래 ${g.branches.length}` : '', g.plays.length ? `플레이 ${g.plays.length}` : ''].filter(Boolean).join(' · ');
    return `<article class="card tight pl-recent"><div class="between"><h3><a href="#/p/${enc(x.name)}">${esc(x.title || x.name)}</a></h3><span class="small">${plWhen(x)}</span></div>
      <span class="small">${x.form === 'serial' ? '장편' : '단편'} · ${esc(x.genre || '장르 미정')}${more ? ` · ${more}` : ''}</span>
      ${plBar(x.finalized, x.episodes)}
      <a class="btn small pl-go" href="#/p/${enc(x.name)}">${esc(projectNext(x))} →</a></article>`;
  };
  const tools = '<a class="btn ghost" href="#/styles">문체 라이브러리</a><a class="btn ghost" href="#/usage">사용량 · 비용</a><a class="btn ghost" href="#/settings">설정</a>';
  return `${header('Canon', '작품', '인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편부터 300화 장편 연재까지 써요.',
    `${tools}<a class="btn" href="#/play/new">새 플레이</a><button type="button" class="btn${open ? ' on' : ' primary'}" data-action="npToggle" aria-expanded="${open}" aria-controls="np-form">${open && list.length ? '새 작품 닫기' : '새 작품'}</button>`)}
    ${aiWarning() ? `<div class="note warn">${esc(aiWarning())} <a href="#/settings/ai" style="color:inherit;font-weight:700">AI 연결 설정</a></div>` : ''}
    ${newProjectForm(open)}
    ${recent.length ? `<section class="pl-section" aria-labelledby="pl-recent-h"><h2 id="pl-recent-h">이어 쓰기</h2><div class="grid-auto">${recent.map(card).join('')}</div></section>` : ''}
    ${list.length ? `<section class="card pl-card" aria-labelledby="pl-h">
      <div class="pl-tools"><h2 id="pl-h">모든 작품 <span class="small">${plRows(list).counts.all}</span></h2>
        <label class="pl-find"><span>작품 찾기</span><input id="pl-q" type="search" placeholder="제목 · 장르 · 폴더" value="${esc(S.plQuery || '')}" autocomplete="off"></label>
        <label class="pl-sort"><span>정렬</span><select id="pl-sort">${PL_SORTS.map(([k, l]) => `<option value="${k}"${(S.plSort || 'updated') === k ? ' selected' : ''}>${l}</option>`).join('')}</select></label></div>
      <div id="pl-body">${plBody()}</div>
    </section>` : ''}`;
}

Object.assign(actions, {
  npToggle() {
    S.npOpen = !$('#np-form') || $('#np-form').hidden;  // 닫아도 적던 내용은 남는다 (비우기는 칸 안의 버튼)
    S.newErr = null;
    S.focusTarget = S.npOpen ? '#np-title' : '#app [data-action="npToggle"]';
    render();
  },
  plFilter(k) { S.plFilter = k; render(); },
});

// 찾기 칸은 목록 몸통만 다시 그린다(입력칸을 다시 그리면 한글 조합이 끊긴다). 정렬은 화면을 다시 그린다
document.addEventListener('input', (e) => {
  if (e.target.id !== 'pl-q') return;
  S.plQuery = e.target.value;
  const box = $('#pl-body');
  if (box) box.innerHTML = plBody();
});
document.addEventListener('change', (e) => {
  if (e.target.id !== 'pl-sort') return;
  S.plSort = e.target.value;
  render();
});

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
  if (typeof playCopy === 'function' && playCopy()) return ['플레이로 돌아가기', `#/play/${enc(S.name)}`];  // 플레이 사본은 구간을 플레이 화면에서 이어 간다
  if (!p.characters.length) return ['설정 시작', base() + '/setup'];
  if (serial()) {
    const open = p.episodes.find((e) => e.status !== 'finalized');
    if (!open && plannedUntil() < p.meta.target_episodes) return [`다음 아크 기획 (${plannedUntil() + 1}화부터)`, base() + '/arc'];
  }
  if (!beats().length || !p.episodes.length) return [`${stepLabel('arc')} 만들기`, base() + '/arc'];
  const e = ep(currentEp());
  if (e.status === 'draft') return [`${e.plot.number}화 플롯 확정`, base() + '/arc'];
  if (e.status === 'confirmed') return [`${e.plot.number}화 쓰기`, `${base()}/write/${e.plot.number}`];
  if (e.status === 'written') return [`${e.plot.number}화 ${stepLabel(epStage(e))}`, `${base()}/${epStage(e)}/${e.plot.number}`];
  return ['완결 원고 보기', `${base()}/write/${e.plot.number}`];
}

/** 한 화를 열 때 갈 화면: 플롯 초안은 플롯(arc), 본문을 쓴 화는 검수가 끝났으면 상태 승인(review) 아니면 검수(check), 그 밖은 집필(write).
    다음 할 일 · 작품 홈 화 칸 · 명령 팔레트가 같은 규칙을 쓴다 (작품 목록은 서버 findings.check_done) */
function epStage(e) {
  if (e.status === 'draft') return 'arc';
  if (e.status === 'written') return checkState(e).done ? 'review' : 'check';
  return 'write';
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

/** 화 하나의 네 단계: 플롯 확정 · 집필 · 검수 · 상태 승인 (이름은 사이드바 · 한 화 흐름 띠와 같다). 검수는 마지막 검수 뒤에 본문을 고치지 않았고 열린 지적이 없을 때 끝난 것으로 본다
    (checkState). 검수 없이, 또는 열린 지적을 두고 반영한 화는 검수 칸이 빈 채로 남는다. */
function epSteps(e) {
  const rank = { draft: 0, confirmed: 1, written: 2, finalized: 3 }[e.status] || 0;
  return [['plot', '플롯 확정', rank >= 1], ['write', '집필', rank >= 2], ['check', '검수', rank >= 2 && checkState(e).done], ['review', '상태 승인', rank >= 3]]
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

// 작품 홈은 위에서부터 지금 화 · 확인할 것 → 화별 진행 → 줄인 목록(인물 · 복선 · 사실) 순서다.
// 목록은 몇 개만 보이고 전체는 그 화면으로 보낸다. 아래 home* 계산 함수는 P() 대신 작품을 받는다 (tests/test_home_js.py).

const HOME_CAST = 4;    // 주요 인물 수
const HOME_FS = 5;      // 열린 복선 수
const HOME_FACTS = 5;   // 확정 사실 수
const HOME_SOON = 3;    // 기한이 이 날수 안이면 확인할 것에 올린다

/** 화 상태별 수: 전 화수 막대와 그 아래 글. none 은 아직 플롯이 없는 화 */
function homeCounts(p) {
  const n = (st) => p.episodes.filter((e) => e.status === st).length;
  const target = Math.max(p.meta.target_episodes, p.episodes.length);
  const c = { target, finalized: n('finalized'), written: n('written'), confirmed: n('confirmed'), draft: n('draft'),
    checked: p.episodes.filter((e) => e.status !== 'draft' && checkState(e).done).length };
  c.none = Math.max(0, target - p.episodes.length);
  return c;
}

/** 주요 인물: 매 화 설정을 넣는 인물(context.core_ids 와 같은 규칙: 주역 · '항상', '넣지 않음' 빼기)을 앞에, 모자라면 설정 순서대로 */
function homeCast(p, n = HOME_CAST) {
  const core = p.characters.filter((c) => c.context === 'always' || (c.tier === 'main' && c.context !== 'off'));
  const rest = p.characters.filter((c) => !core.includes(c) && c.context !== 'off');
  return [...core, ...rest].slice(0, n);
}

/** 열린 복선을 심은 화 순서로. age 는 반영한 마지막 화에서 몇 화째인지, overdue 는 foreshadows.center 의 '예정 지남'과 같은 규칙 */
function homeForeshadows(p) {
  const done = Math.max(0, ...p.episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));
  return p.foreshadows.filter((f) => f.status === 'open')
    .map((f) => ({ ...f, age: Math.max(0, done - f.planted_ep), overdue: f.due_ep != null && f.due_ep < done }))
    .sort((a, b) => a.planted_ep - b.planted_ep || (a.id < b.id ? -1 : 1));
}

/** 본문이 없는 첫 화에 나오는 인물(플롯 인물 + 주역 · '항상', '넣지 않음' 빼고) 가운데 말투(speech_style)가 빈 인물. 없으면 null.
 * 말투가 비면 쓰기 프롬프트에 기준이 없어 AI 기본 말투로 흐른다 (2026-10-30 인물 진단) */
function homeSpeechGaps(p) {
  const e = p.episodes.filter((x) => !x.text).sort((a, b) => a.plot.number - b.plot.number)[0];
  if (!e) return null;
  const ids = new Set(e.plot.characters || []);
  const cast = p.characters.filter((c) => c.context !== 'off'
    && (ids.has(c.id) || c.context === 'always' || c.tier === 'main'));
  const gaps = cast.filter((c) => !(c.speech_style || '').trim());
  return gaps.length ? { n: e.plot.number, chars: gaps } : null;
}

/** 본문이 없는 첫 화의 시점 인물이 서술 말투(narration_voice)가 비었으면 { n, c }, 아니면 null.
 * povOf(n) 는 그 화의 시점 인물 (화면은 plot.js povChar: 화 → 구간 · 아크 → 작품 기본, 없으면 화에 정한 인물만).
 * 서술 말투가 비면 시점 인물이 바뀌어도 지문이 같은 목소리로 흐른다 (prompts.voice_line 이 넣을 것이 없다) */
function homeVoiceGap(p, povOf) {
  const e = p.episodes.filter((x) => !x.text).sort((a, b) => a.plot.number - b.plot.number)[0];
  if (!e) return null;
  const c = povOf ? povOf(e.plot.number) : p.characters.find((x) => x.id === e.plot.pov);
  return c && c.context !== 'off' && !(c.narration_voice || '').trim() ? { n: e.plot.number, c } : null;
}

/** 끝났는데 요약이 없는 아크 · 부 (부 · 아크 화면 경고 줄, pipeline.pending_recaps 와 같은 규칙). 요약이 없으면 줄거리가 접히지 않는다 */
function homeRecaps(p) {
  if (p.meta.form !== 'serial') return { arcs: [], parts: [] };
  const fin = new Set(p.episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));
  const finished = (a) => { for (let n = a.start_ep; n <= a.end_ep; n++) if (!fin.has(n)) return false; return true; };
  const summed = p.parts.filter((x) => x.summary);
  const arcs = [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep)
    .filter((a) => !a.summary && finished(a) && !summed.some((x) => x.start_ep <= a.start_ep && a.start_ep <= x.end_ep));
  return { arcs, parts: p.parts.filter((x) => !x.summary && finished(x)) };
}

/** 확인할 것: 반영 때 검수 경고, 요약 없는 아크 · 부, 다가오거나 지난 기한, 회수 예정이 지난 복선.
    [{ tag, kind: 'warn' | 'info', label, sub, href, link }] 순서대로. home 은 작품 주소(base()) */
function homeTodos(p, home, povOf = null) {
  const out = [];
  const last = p.history.length ? p.history[p.history.length - 1] : null;
  const warns = last ? last.warnings || [] : [];
  if (warns.length) out.push({ tag: '경고', kind: 'warn', label: `${last.episode}화 반영 때 검수 경고 ${warns.length}개`,
    sub: warns[0] + (warns.length > 1 ? ` 외 ${warns.length - 1}개` : ''), href: `${home}/write/${last.episode}`, link: `${last.episode}화 보기` });
  const r = homeRecaps(p);
  const recapN = r.arcs.length + r.parts.length;
  if (recapN) {
    const first = r.arcs.length ? `아크 ${r.arcs[0].number}` : `${r.parts[0].number}부`;
    out.push({ tag: '할 일', kind: 'info', label: recapN > 1 ? `요약이 없는 아크 · 부 ${recapN}개` : `${first} 요약이 없어요`,
      sub: '요약해야 줄거리가 접혀요', href: r.arcs.length ? `${home}/arc/a${r.arcs[0].number}` : `${home}/arc`, link: `${first} 요약` });
  }
  const tl = p.timeline || {};
  if (tl.enabled !== false) {
    const done = p.episodes.filter((e) => e.status === 'finalized' && e.time && e.time.day > 0).sort((a, b) => b.plot.number - a.plot.number)[0];
    const day = done ? done.time.day : 0;
    const soon = (tl.deadlines || []).filter((d) => !(d.done_ep > 0) && d.day > 0 && day > 0 && d.day - day <= HOME_SOON)
      .sort((a, b) => a.day - b.day);
    if (soon.length) {
      const d = soon[0];
      const gap = d.day - day;
      const when = gap > 0 ? `${gap}일 남았어요` : gap === 0 ? '오늘이에요' : `${-gap}일 지났어요`;
      out.push({ tag: '기한', kind: 'warn', label: `${d.what} · ${when}`, sub: `${done.plot.number}화 끝 · ${day}일째 기준${soon.length > 1 ? ` · 다른 기한 ${soon.length - 1}개` : ''}`,
        href: `${home}/timeline`, link: '작품 속 시간' });
    }
  }
  const voice = homeVoiceGap(p, povOf);
  if (voice) out.push({ tag: '인물', kind: 'info', label: `${voice.n}화 시점 인물 ${voice.c.name || voice.c.id}의 서술 말투가 비었어요`,
    sub: '시점 인물마다 지문 말투를 정해 두면 시점이 바뀔 때 목소리가 갈려요', href: `${home}/cast/${voice.c.id}`, link: '인물 카드' });
  const gap = homeSpeechGaps(p);
  if (gap) out.push({ tag: '인물', kind: 'info', label: `${gap.n}화 인물 ${gap.chars.length}명의 말투가 비었어요`,
    sub: `${gap.chars.map((c) => c.name || c.id).join(', ')} · 비워 두면 AI가 기본 말투로 써요`,
    href: `${home}/cast/${gap.chars[0].id}`, link: '인물 카드' });
  const late = homeForeshadows(p).filter((f) => f.overdue);
  if (late.length) out.push({ tag: '복선', kind: 'info', label: `회수 예정이 지난 복선 ${late.length}개`,
    sub: `${late[0].planted_ep}화 「${late[0].description}」 · ${late[0].due_ep}화에 회수 예정이었어요`, href: `${home}/foreshadow`, link: '복선 센터' });
  return out;
}

/** 머리 아래 '지금 화' 카드: 다음 할 일이 한 화의 단계면 그 화의 네 단계와 바로 가는 링크, 아니면 다음 할 일 한 줄 */
function homeNowCard(nextLabel, nextHref) {
  const p = P();
  const cur = currentEp();
  const e = ep(cur);
  const onEp = e && e.status !== 'finalized' && !autoOn() && nextLabel.startsWith(`${cur}화 `);  // nextStep 의 '14화 플롯 확정' 같은 화 단계
  if (!onEp) {
    const why = nextHref.endsWith('/setup') ? '인물과 세계를 정하면 이야기 구조를 짤 수 있어요.'
      : nextHref.endsWith('/auto') ? (autoOn() ? '자동 집필이 쓰는 동안에는 손으로 쓰거나 반영하지 않아요.' : '자동 집필이 사람의 검토를 기다려요.')
      : nextHref.endsWith('/arc') ? (serial() && p.story_arcs.length ? `${plannedUntil()}화까지 기획했어요. 다음 아크를 기획하면 이어서 쓸 수 있어요.` : '구조를 짜면 화별 플롯을 만들 수 있어요.')
      : `${p.meta.target_episodes}화를 모두 반영했어요.`;
    return `<section class="card home-now" aria-labelledby="home-now-h"><span class="eyebrow">다음 할 일</span><h2 id="home-now-h">${esc(nextLabel)}</h2><p class="desc">${why}</p></section>`;
  }
  const t = e.plot.title;
  const arc = serial() ? arcOf(cur) : null;
  const act = !serial() && actOf(cur);
  const where = arc ? `아크 ${arc.number}${arc.title ? ` 「${esc(arc.title)}」` : ''}` : act ? `${esc(act.name)} 구간` : '';
  const steps = epSteps(e);
  const at = steps.findIndex((s) => !s.done);
  const verb = { plot: '플롯을 확정할 차례예요', write: '본문을 쓸 차례예요', check: '검수할 차례예요', review: '상태를 승인할 차례예요' }[steps[at].key];
  const after = ep(cur + 1) ? ` 상태를 승인하면 ${cur + 1}화를 쓸 수 있어요.` : ' 상태를 승인하면 이 화까지 반영돼요.';
  const ck = checkState(e);
  const why = e.status === 'draft' ? '플롯을 확정하면 본문을 쓸 수 있어요.'
    : e.status === 'confirmed' ? '본문을 쓰면 검수와 상태 승인이 이어져요.'
    : !ck.done ? `본문 ${e.text.length.toLocaleString()}자를 썼어요.${ck.open ? ` 열린 지적이 ${ck.open}개 있어요.` : ck.stale ? ' 검수한 뒤 본문을 고쳤어요.' : ''}${after}`
    : `검수를 마쳤어요.${after}`;
  const nx = ep(cur + 1);
  return `<section class="card home-now" aria-labelledby="home-now-h">
    <span class="eyebrow">지금 화${where ? ` · ${where}` : ''} · ${cur} / ${p.meta.target_episodes}화</span>
    <h2 id="home-now-h">${cur}화${t ? ` 「${esc(t)}」` : ''} · ${verb}</h2>
    <p class="desc">${why}</p>
    <ol class="home-steps" aria-label="${cur}화 진행: ${esc(stepText(e))}">${steps.map((s, i) => `<li class="${s.done ? 'done' : i === at ? 'now' : ''}"${i === at ? ' aria-current="step"' : ''}><i></i><span>${s.done ? '✓ ' : ''}${s.key === 'review' ? stepLabel('review') : s.label}${i === at ? ' · 지금' : ''}</span></li>`).join('')}</ol>
    <div class="row">${e.text ? `<a class="btn small" href="${base()}/write/${cur}">본문 열기</a>` : ''}<a class="btn small" href="${base()}/arc/${cur}">${cur}화 플롯</a>${nx ? `<a class="btn small ghost" href="${base()}/arc/${cur + 1}">다음 화 ${cur + 1}화${nx.plot.title ? ` 「${esc(nx.plot.title)}」` : ''}</a>` : ''}</div>
  </section>`;
}

function homeTodoCard() {
  const items = homeTodos(P(), base(), typeof povChar === 'function' ? (n) => povChar(n).c : null);
  return `<section class="card home-todo" aria-labelledby="home-todo-h"><div class="between"><h2 id="home-todo-h">확인할 것</h2><span class="small">${items.length ? `${items.length}개` : ''}</span></div>
    ${items.length ? `<ul>${items.map((x) => `<li><span class="home-tag ${x.kind}">${x.tag}</span><div><strong>${esc(x.label)}</strong><div class="small">${esc(x.sub)}</div></div><a class="btn small" href="${x.href}">${esc(x.link)}</a></li>`).join('')}</ul>`
    : '<p class="small">확인할 것이 없어요. 반영 때 검수 경고, 요약 없는 아크, 다가오는 기한, 회수 예정이 지난 복선이 여기 모여요.</p>'}</section>`;
}

/** 전 화수를 상태별로 나눈 막대와 수. 예전 '진행 단계' 카드의 수도 여기 한 줄로 */
function homeProgress(p) {
  const c = homeCounts(p);
  const parts = [['finalized', '반영', c.finalized], ['written', '작성됨', c.written], ['confirmed', '확정', c.confirmed], ['draft', '초안', c.draft], ['none', '플롯 없음', c.none]];
  const pct = (x) => `${Math.round((x / c.target) * 1000) / 10}%`;
  const hasStyle = !!(p.style.narration_pov || p.style.sample_passages.length);
  return `<div class="home-bar" role="img" aria-label="전 ${c.target}화: ${parts.filter(([, , x]) => x).map(([, l, x]) => `${l} ${x}`).join(' · ')}">${parts.slice(0, 4).filter(([, , x]) => x).map(([k, , x]) => `<i class="${k}" style="width:${pct(x)}"></i>`).join('')}</div>
    <div class="legend home-legend">${parts.map(([k, l, x]) => `<span><i class="hb-${k}"></i>${l} <strong>${x}</strong></span>`).join('')}
      <span><span class="legend-steps" aria-hidden="true"><b></b><b></b><b class="off"></b><b class="off"></b></span>플롯 확정 · 집필 · 검수 · 상태 승인</span><span>↑ 올린 화</span></div>
    <div class="small">검수 끝난 화 ${c.checked} · <a href="${base()}/setup">인물 ${p.characters.length} · 관계 ${p.relationships.length}</a> · <a href="${base()}/style">${hasStyle ? `대표 문단 ${p.style.sample_passages.length}개` : '문체 정하지 않음'}</a></div>`;
}

function viewHome() {
  const p = P();
  const m = p.meta;
  const eps = p.episodes;
  const fin = eps.filter((e) => e.status === 'finalized').length;
  const cur = currentEp();
  const [nextLabel, nextHref] = nextStep();

  // 단편 기승전결: 칸 폭을 지키려고 칸은 장편처럼 줄을 바꿔 놓고, 구간은 칸 위 띠 대신 칸 아래 테두리 색과 이 머리 줄로 보인다
  const actBand = p.arc.length && !serial() ? `<div class="act-rail">${actGroups(p.arc).map((g) => `<span class="act-chip ${actClass(g.names[0])}">${g.names.join('·')} ${epRange(g.start, g.end)}</span>`).join('')}</div>` : '';
  // 장편은 지금 쓰는 부(없으면 지금 아크 근처 60화)만 칸으로 보인다
  const curPart = serial() ? partOf(cur) : null;
  const shown = !serial() ? eps : curPart ? eps.filter((e) => e.plot.number >= curPart.start_ep && e.plot.number <= curPart.end_ep)
    : eps.filter((e) => Math.abs(e.plot.number - cur) <= 30);
  const recaps = homeRecaps(p).arcs;
  const arcBand = serial() && p.story_arcs.length ? `<div class="arc-rail">${p.story_arcs.filter((a) => shown.some((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep)).map((a) => `<a class="arc-chip${arcOf(cur) === a ? ' sel' : ''}" href="${base()}/arc/a${a.number}"><strong>아크 ${a.number}</strong> <span>${a.start_ep}~${a.end_ep}화 ${esc(a.title)}</span>${recaps.includes(a) ? '<em class="home-tag info">요약 필요</em>' : ''}</a>`).join('')}${curPart && plannedUntil() < curPart.end_ep ? `<a class="arc-chip next" href="${base()}/arc">${plannedUntil() + 1}~${curPart.end_ep}화 아크 없음 · 다음 아크 기획</a>` : ''}</div>` : '';
  const released = releasePlan(p).released;
  const cells = shown.map((e) => {
    const n = e.plot.number;
    const href = `${base()}/${epStage(e)}/${n}`;
    const act = !serial() && actOf(n);
    const st = e.auto ? '자동 반영' : STATUS[e.status].replace('플롯 ', '').replace('본문 ', '');
    const now = n === cur && e.status !== 'finalized';
    // 좁은 폭에서는 상태 글자를 눈으로만 감춘다. 이름은 aria-label 로 늘 '3화 작성됨 · 제목'
    const up = n <= released;
    return `<a class="ep-cell ${e.status}${now ? ' current' : ''}${up ? ' released' : ''}${act ? ' ' + actClass(act.name) + '-edge' : ''}" href="${href}" title="${esc(`${e.plot.title ? e.plot.title + ' · ' : ''}${stepText(e)}`)}" aria-label="${esc(`${n}화 ${st} · ${stepText(e)}${up ? ' · 올린 화' : ''}${now ? ' · 지금 화' : ''}${e.plot.title ? ' · ' + e.plot.title : ''}`)}"><strong>${n}</strong><span>${st}</span>${stepBar(e)}</a>`;
  }).join('');

  const states = homeCast(p).map((c) => {
    const s = p.states.find((x) => x.character_id === c.id) || {};
    const lines = [['감정', s.emotional_state], ['목표', s.current_goal], ['위치', s.location]].filter(([, v]) => v).slice(0, 2);
    return `<li><span class="home-ava t-${esc(c.tier || 'minor')}" aria-hidden="true">${esc((c.name || '?').slice(0, 1))}</span><div><strong>${esc(c.name)}</strong> <span class="small">${esc(c.role)}</span>${lines.map(([k, v]) => `<div class="line">${k}: ${esc(v)}</div>`).join('') || '<div class="line small">아직 변화 없음</div>'}</div></li>`;
  }).join('');
  const openFs = homeForeshadows(p);
  const fsRows = openFs.slice(0, HOME_FS).map((f) => `<li><span class="chip">${f.planted_ep}화</span><span class="home-fs-d">${esc(f.description)}</span><span class="small${f.overdue ? ' home-late' : ''}">${f.overdue ? `${f.due_ep}화 예정 지남` : f.due_ep ? `${f.due_ep}화 회수 예정` : `${f.age}화째`}</span></li>`).join('');
  const facts = [...p.facts].reverse();

  return `${header(`${esc(m.genre || '장르 미정')}${m.adult ? ' · 성인' : ''} · ${serial() ? '장편 연재 · ' : ''}전 ${m.target_episodes}화 · 화당 ${Number(m.words_per_episode).toLocaleString()}자`, m.title || S.name, m.logline ? `<span class="home-logline" title="${esc(m.logline)}">${esc(m.logline)}</span>` : '', `${!serial() && fin && fin === m.target_episodes ? `<a class="btn" href="${base()}/convert">장편으로 늘리기</a>` : ''}${nextHref === `${base()}/arc` ? '' : `<a class="btn" href="${base()}/arc">${stepLabel('arc')}</a>`}${fin ? '<button type="button" class="btn" data-action="branchOpen" title="이 작품은 그대로 두고, 사본에서 다른 전개를 써요">갈래 만들기</button>' : ''}<a class="btn primary" href="${nextHref}">${esc(nextLabel)}</a>`)}
    ${autoLockNote()}
    ${aiNote()}
    <div class="home-top">${homeNowCard(nextLabel, nextHref)}${homeTodoCard()}</div>
    <section class="card" aria-labelledby="home-eps-h">
      <div class="between"><h2 id="home-eps-h">화별 진행</h2>${curPart ? `<span class="small">${curPart.number}부 ${esc(curPart.title)} ${epRange(curPart.start_ep, curPart.end_ep)}만 보여요 · <a href="${base()}/arc">전체는 ${stepLabel('arc')}</a></span>` : ''}</div>
      ${homeProgress(p)}
      ${eps.length ? releaseRow(p) : ''}
      ${eps.length ? `${actBand}${arcBand}<div class="ep-grid">${cells}</div>` : `<div class="note plain">아직 화별 플롯이 없어요. 다음 할 일: <a href="${nextHref}">${esc(nextLabel)}</a></div>`}
      ${serial() ? snapshotRow(p) : ''}
    </section>
    ${branchHomeCard()}
    ${playHomeCard()}
    <div class="grid-auto home-lists">
      <section class="card" aria-labelledby="home-cast-h"><div class="between"><h2 id="home-cast-h">주요 인물</h2><span class="small">${fin ? fin + '화 기준' : '시작 시점'}${p.characters.length > HOME_CAST ? ` · ${p.characters.length}명 중 ${HOME_CAST}명` : ''}</span></div>
        ${states ? `<ul class="home-list">${states}</ul>` : '<div class="small">인물이 없어요</div>'}<a class="card-more" href="${base()}/cast">인물 ${p.characters.length}명 · 관계 ${p.relationships.length}개 모두 보기</a></section>
      <section class="card" aria-labelledby="home-fs-h"><div class="between"><h2 id="home-fs-h">열린 복선</h2><span class="small">${openFs.length > HOME_FS ? `${openFs.length}개 중 오래된 ${HOME_FS}개` : `${openFs.length}개`}</span></div>
        ${fsRows ? `<ul class="home-list home-fs">${fsRows}</ul>` : '<div class="small">없음</div>'}<a class="card-more" href="${base()}/foreshadow">복선 ${p.foreshadows.length}개 · 복선 센터</a></section>
      <section class="card" aria-labelledby="home-fact-h"><div class="between"><h2 id="home-fact-h">확정 사실</h2><span class="small">${p.facts.length > HOME_FACTS ? `${p.facts.length}개 중 최근 ${HOME_FACTS}개` : `${p.facts.length}개`}</span></div>
        ${facts.length ? `<ul class="home-facts">${facts.slice(0, HOME_FACTS).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '<div class="small">없음</div>'}
        ${p.facts.length > HOME_FACTS ? `<details><summary class="small">전체 ${p.facts.length}개 보기</summary><ol class="home-facts all">${p.facts.map((f) => `<li>${esc(f)}</li>`).join('')}</ol></details>` : ''}
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
