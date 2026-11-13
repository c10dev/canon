/* 가려 읽기 묶음 (작품 밖 화면 #/blind[/<묶음 id>[/<번호>]]). 서버는 canon/blindset.py · routes/blindset.py, 엔드포인트는 /api/blind.
   판(지시 · 규칙 · 모델)이 다른 글 여러 편을 섞어 둔 묶음을 한 편씩 읽고 1~5점을 매긴다. 어느 글이 어느 판인지는 결과를 열기 전까지 서버가 보내지 않는다.
   결과를 열면 판마다 평균과, 같은 글 두 편의 점수 차로 잰 흔들림을 보인다. 연 뒤에는 점수를 고칠 수 없다.
   묶음은 실험 스크립트나 명령줄(canon blind import)이 넣는다. 화면에는 넣는 칸이 없다. 사이드바에는 없고 찾기 팔레트에서 연다 (palette.js PAL_TOOLS).
   결과를 연 뒤에는 긋기 화면(#/blind/<id>/marks[/<대목 차례>])에서 같은 대목의 글을 나란히 놓고 거슬린 문장을 눌러 긋는다. 판 이름은 그 화면에 보이지 않는다.
   blNext · blProgress · blArmNote · blMarkCount · blColHead 는 DOM 없는 순수 함수 (tests/test_blindset.py). CSS 는 JS 에서 주입 */

Object.assign(S, {
  blHome: null,  // 묶음 목록 (GET /blind)
  bl: null,      // 연 묶음 (GET /blind/<id>)
  blNo: '',      // 읽고 있는 글 번호
  blPiece: -1,   // 긋기 화면에서 보는 대목 차례 (-1 은 긋기 화면이 아님)
});

async function blLoad(id, no, sub) {
  if (!id) { S.bl = null; S.blHome = await api('GET', '/blind'); return; }
  if (!S.bl || S.bl.id !== id) S.bl = await api('GET', `/blind/${enc(id)}`);
  S.blPiece = -1;
  if (no === 'marks' && S.bl.result && (S.bl.pieces || []).length) {
    S.blPiece = Math.min(Math.max(Number(sub) || 0, 0), S.bl.pieces.length - 1);
    S.blNo = '';
    return;
  }
  const first = blNext(S.bl.texts, '');
  S.blNo = S.bl.texts.some((t) => t.no === no) ? no : (S.bl.result ? '' : first);
}

/** 다음에 읽을 번호: 지금 번호 뒤의 첫 '안 매긴 글', 없으면 앞에서부터 첫 안 매긴 글, 다 매겼으면 ''. 순수 함수 */
function blNext(texts, cur) {
  const at = texts.findIndex((t) => t.no === cur);
  const after = texts.slice(at + 1).find((t) => !t.score);
  const any = texts.find((t) => !t.score);
  return (after || any || { no: '' }).no;
}

/** 진행 한 줄 ('7 / 11편 매김'). 순수 함수 */
function blProgress(b) {
  return `${b.scored} / ${b.items}편 매김`;
}

/** 판 한 줄의 풀이: 가장 높은 판과의 차가 흔들림 안인지. 순수 함수 */
function blArmNote(arm, top, noise) {
  if (arm.mean === top) return '가장 높아요';
  const gap = Math.round((top - arm.mean) * 100) / 100;
  if (noise == null) return `가장 높은 판보다 ${gap}점 낮아요`;
  return arm.close ? `${gap}점 낮지만 흔들림(${noise}) 안이에요` : `${gap}점 낮고 흔들림(${noise})보다 커요`;
}

/** 그은 문장 수 (같은 글 두 편은 한 번만 센다). piece 를 주면 그 대목만. 순수 함수 */
function blMarkCount(b, piece) {
  return (b.pieces || []).filter((g, i) => piece == null || i === piece).reduce((n, g) => n + g.texts.reduce((m, t) => m + t.marks.length, 0), 0);
}

/** 긋기 화면의 글 머리 ('02번 · 09번 · 3점'). 같은 글 두 편의 점수가 다르면 둘 다 적는다. 순수 함수 */
function blColHead(t) {
  const scores = [...new Set(t.scores)];
  return `${t.nos.map((n) => `${n}번`).join(' · ')} · ${scores.join(' · ')}점`;
}

function viewBlind() {
  return S.bl ? blSetView() : blHomeView();
}

function blHomeView() {
  const list = (S.blHome && S.blHome.sets) || [];
  const head = header('작품 밖 도구', '가려 읽기 묶음', '판이 다른 글을 섞어 둔 묶음을 읽고 점수를 매겨요. 어느 글이 어느 판인지는 결과를 열 때 보여요.');
  if (!list.length) {
    return `${head}<section class="card empty"><h2>아직 묶음이 없어요</h2><p class="small">묶음은 실험이 만들어 넣어요. 명령줄에서는 <code>canon blind import &lt;폴더&gt;</code>로 넣어요.</p></section>`;
  }
  const rows = list.map((b) => `<a class="bl-card" href="#/blind/${b.id}"><div class="between"><strong>${esc(b.title)}</strong>
      <span class="chip${b.revealed_at ? ' ok' : ''}">${b.revealed_at ? '결과 엶' : esc(blProgress(b))}</span></div>
      <div class="small">${b.items}편 · ${fmtDateTime(b.created_at)}${b.note ? ` · ${esc(b.note)}` : ''}</div></a>`).join('');
  return `${head}<div class="bl-list">${rows}</div>`;
}

function blNav(b) {
  return `<nav class="bl-nav" aria-label="글 번호">${b.texts.map((t) => `<a href="#/blind/${b.id}/${esc(t.no)}" class="bl-no${t.no === S.blNo ? ' on' : ''}${t.score ? ' done' : ''}"${t.no === S.blNo ? ' aria-current="true"' : ''}>${esc(t.no)}${t.score ? `<span class="bl-score">${t.score}</span>` : ''}</a>`).join('')}</nav>`;
}

function blReader(b) {
  const t = b.texts.find((x) => x.no === S.blNo);
  if (!t) return '';
  const locked = !!b.result;
  const row = locked ? (b.result.rows.find((r) => r.no === t.no) || {}) : {};
  const paras = t.text.split(/\n\s*\n/).map((p) => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  const btns = Array.from({ length: b.scale }, (_, i) => i + 1).map((n) => `<button type="button" aria-pressed="${t.score === n}" data-action="blScore" data-arg="${n}"${locked ? ' disabled' : ''}>${n}</button>`).join('');
  const i = b.texts.findIndex((x) => x.no === t.no);
  const prev = b.texts[i - 1];
  const next = b.texts[i + 1];
  return `<section class="card bl-read"><div class="between"><div><h2>${esc(t.no)}번</h2><span class="small">${t.chars.toLocaleString()}자${locked && row.arm ? ` · ${esc(row.arm)}${row.piece ? ` · ${esc(row.piece)}` : ''}` : ''}</span></div>
      <div class="row">${prev ? `<a class="btn small" href="#/blind/${b.id}/${esc(prev.no)}">‹ ${esc(prev.no)}</a>` : ''}${next ? `<a class="btn small" href="#/blind/${b.id}/${esc(next.no)}">${esc(next.no)} ›</a>` : ''}</div></div>
    <div class="bl-body">${paras}</div>
    <div class="bl-rate"><div class="seg" role="group" aria-label="${esc(t.no)}번 점수 (1 가장 낮음 · ${b.scale} 가장 높음)">${btns}</div>
      <label class="sr-only" for="bl-note">한마디</label><input id="bl-note" type="text" data-bl-note="${esc(t.no)}" value="${esc(t.note)}" placeholder="한마디 (안 적어도 돼요)" maxlength="300"${locked ? ' disabled' : ''}></div></section>`;
}

function blResult(b) {
  const r = b.result;
  const top = r.arms.length ? r.arms[0].mean : 0;
  const arms = r.arms.map((a) => `<tr><td>${esc(a.arm)}</td><td class="num">${a.mean}</td><td class="num">${a.texts}</td><td class="num">${a.low}~${a.high}</td><td>${esc(blArmNote(a, top, r.noise))}</td></tr>`).join('');
  const pairs = r.pairs.length ? r.pairs.map((p) => `${esc(p.a)}번 · ${esc(p.b)}번 차 ${p.diff}`).join(', ') : '';
  const rows = r.rows.map((x) => `<tr><td><a href="#/blind/${b.id}/${esc(x.no)}">${esc(x.no)}</a></td><td class="num">${x.score}</td><td>${esc(x.arm)}</td><td>${esc(x.piece)}</td><td>${esc(x.note)}</td></tr>`).join('');
  const noise = r.noise == null ? '같은 글을 두 번 넣은 짝이 없어 흔들림을 재지 못했어요.' : `같은 글 두 편의 점수 차는 평균 ${r.noise}점이에요 (${pairs}). 판 사이 차이가 이보다 작으면 어느 쪽이 낫다고 말할 수 없어요.`;
  return `<section class="card"><h2>결과</h2>${r.arms.length ? `<div class="bl-table-wrap"><table class="bl-table"><thead><tr><th scope="col">판</th><th scope="col">평균</th><th scope="col">글 수</th><th scope="col">범위</th><th scope="col">풀이</th></tr></thead><tbody>${arms}</tbody></table></div>` : '<p class="small">열쇠가 없는 묶음이라 판별 평균은 없어요.</p>'}
    <p class="small">${esc(noise)}</p></section>
    ${(b.pieces || []).length ? `<section class="card between"><div><h2>거슬린 문장 긋기</h2><span class="small">같은 대목의 글을 나란히 놓고 거슬린 문장을 눌러요 · 그은 문장 ${blMarkCount(b)}개</span></div><a class="btn" href="#/blind/${b.id}/marks">긋기</a></section>` : ''}
    <section class="card"><h2>글마다</h2><div class="bl-table-wrap"><table class="bl-table"><thead><tr><th scope="col">번호</th><th scope="col">점수</th><th scope="col">판</th><th scope="col">대목</th><th scope="col">한마디</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function blMarks(b) {
  const g = b.pieces[S.blPiece];
  const tabs = b.pieces.map((p, i) => `<a href="#/blind/${b.id}/marks/${i}" class="bl-no${i === S.blPiece ? ' on' : ''}"${i === S.blPiece ? ' aria-current="true"' : ''}>${esc(p.piece || `대목 ${i + 1}`)}<span class="bl-score" data-bl-count="${i}">${blMarkCount(b, i) || ''}</span></a>`).join('');
  const cols = g.texts.map((t) => {
    let idx = -1;
    const on = new Set(t.marks);
    const paras = t.paras.map((sents) => `<p>${sents.map((s) => { idx += 1; return `<span class="bl-s" role="button" tabindex="0" aria-pressed="${on.has(idx)}" data-bl-mark="${esc(t.nos[0])}" data-idx="${idx}">${esc(s)}</span>`; }).join(' ')}</p>`).join('');
    return `<section class="card bl-col"><h2>${esc(blColHead(t))}</h2><div class="bl-body">${paras}</div></section>`;
  }).join('');
  return `<nav class="bl-nav" aria-label="대목">${tabs}</nav><p class="small">거슬린 문장을 누르면 줄이 그어지고, 다시 누르면 지워져요. 이유는 적지 않아도 돼요.</p><div class="bl-cols">${cols}</div>`;
}

async function blToggleMark(el) {
  const b = S.bl;
  const on = el.getAttribute('aria-pressed') !== 'true';
  el.setAttribute('aria-pressed', String(on));  // 다시 그리지 않는다: 긴 글 가운데에서 눌러도 읽던 자리가 그대로다
  try {
    S.bl = await api('PUT', `/blind/${enc(b.id)}/items/${enc(el.dataset.blMark)}/marks`, { idx: Number(el.dataset.idx), on });
  } catch (e) { el.setAttribute('aria-pressed', String(!on)); return showError(e); }
  for (const c of document.querySelectorAll('[data-bl-count]')) c.textContent = blMarkCount(S.bl, Number(c.dataset.blCount)) || '';
}

document.addEventListener('click', (e) => {
  const el = e.target.closest && e.target.closest('[data-bl-mark]');
  if (el && S.bl && S.blPiece >= 0) blToggleMark(el);
});
document.addEventListener('keydown', (e) => {
  if ((e.key !== 'Enter' && e.key !== ' ') || !e.target.dataset || !e.target.dataset.blMark) return;
  e.preventDefault();
  blToggleMark(e.target);
});

function blSetView() {
  const b = S.bl;
  if (S.blPiece >= 0) {
    return `${header('가려 읽기 묶음', b.title, '거슬린 문장 긋기 · 판 이름은 여기서 보이지 않아요.', `<a class="btn" href="#/blind/${b.id}">결과로 돌아가기</a>`)}${blMarks(b)}`;
  }
  const done = b.scored === b.items;
  const menu = menuBtn('bl-more', '⋯', () => `<div class="pop-sec pop-danger"><details><summary class="small">이 묶음 지우기</summary>
      <div class="small">글과 점수가 함께 사라져요.</div><button type="button" class="pop-item danger" data-action="blDelete">지우기</button></details></div>`, { aria: '묶음 더보기' });
  const right = `<a class="btn" href="#/blind">목록으로</a>${!b.result && done ? '<button type="button" class="btn primary" data-action="blReveal">결과 보기</button>' : ''}${menu}`;
  const desc = b.result ? `결과를 ${fmtDateTime(b.revealed_at)}에 열었어요. 점수는 고칠 수 없어요.`
    : `${blProgress(b)} · 한 자리에서 차례대로 읽어 주세요. 같은 글이 두 번 섞여 있을 수 있어요.`;
  const head = header('가려 읽기 묶음', b.title, esc(desc), right);
  return `${head}${blNav(b)}${b.result && !S.blNo ? blResult(b) : ''}${blReader(b)}${b.result && S.blNo ? `<div class="row"><a class="btn" href="#/blind/${b.id}">결과로 돌아가기</a></div>` : ''}`;
}

Object.assign(actions, {
  async blScore(arg) {
    const b = S.bl;
    const t = b.texts.find((x) => x.no === S.blNo);
    if (!t || b.result) return;
    const n = Number(arg);
    const note = ($('#bl-note') || {}).value || t.note || '';
    try {
      S.bl = await api('PUT', `/blind/${enc(b.id)}/items/${enc(t.no)}`, { score: t.score === n ? 0 : n, note });
    } catch (e) { return showError(e); }
    const next = blNext(S.bl.texts, t.no);
    // 점수를 매기면 다음 안 매긴 글로 넘어간다. 점수를 지웠거나 다 매겼으면 그 자리에 둔다
    if (S.bl.texts.find((x) => x.no === t.no).score && next) location.hash = `#/blind/${b.id}/${next}`;
    else render();
  },
  async blReveal() {
    if (!(await askConfirm('결과를 열면 어느 글이 어느 판인지 보이고, 점수는 고칠 수 없어요. 열까요?', { ok: '결과 보기' }))) return;
    await run('결과를 여는 중', async () => {
      S.bl = await api('POST', `/blind/${enc(S.bl.id)}/reveal`);
      S.blNo = '';
      location.hash = `#/blind/${S.bl.id}`;
    });
  },
  async blDelete() {
    if (!(await askConfirm(`'${S.bl.title}' 묶음을 지울까요? 글과 점수가 함께 사라져요.`, { ok: '지우기', danger: true }))) return;
    await run('묶음을 지우는 중', async () => {
      await api('DELETE', `/blind/${enc(S.bl.id)}`);
      S.bl = null;
      location.hash = '#/blind';
    }, { render: 'never' });
  },
});

// 한마디는 칸을 벗어날 때 저장한다 (점수가 있는 글만. 점수 없이 한마디만 적은 것은 점수를 누를 때 함께 간다)
document.addEventListener('change', async (e) => {
  const no = (e.target.dataset || {}).blNote;
  if (!no || !S.bl || S.bl.result) return;
  const t = S.bl.texts.find((x) => x.no === no);
  if (!t) return;
  t.note = e.target.value;
  if (!t.score) return;
  try { S.bl = await api('PUT', `/blind/${enc(S.bl.id)}/items/${enc(no)}`, { score: t.score, note: t.note }); } catch (err) { showError(err); }
});

const BL_CSS = `
.bl-list { display: grid; gap: var(--space-12); }
.bl-card { display: block; padding: var(--space-16); border: 1px solid var(--line); border-radius: var(--radius-12); background: var(--surface); color: inherit; text-decoration: none; }
.bl-card:hover { border-color: var(--line-strong); }
.bl-nav { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-bottom: var(--space-16); }
.bl-no { display: inline-flex; align-items: center; gap: var(--space-4); min-width: var(--touch-min); min-height: 38px; padding: 0 var(--space-8); justify-content: center; border: 1px solid var(--line); border-radius: var(--radius-8); background: var(--surface); color: var(--text-2); text-decoration: none; font-size: 0.8125rem; }
.bl-no.done { background: var(--chip); }
.bl-no.on { border-color: var(--text); color: var(--text); font-weight: 700; }
.bl-score { font-weight: 700; color: var(--text); }
.bl-body { font-family: var(--serif); line-height: 1.9; margin: var(--space-16) 0; max-width: 42rem; }
.bl-body p { margin: 0 0 var(--space-12); }
.bl-rate { display: flex; flex-wrap: wrap; gap: var(--space-12); align-items: center; position: sticky; bottom: 0; padding: var(--space-12) 0; background: var(--surface); border-top: 1px solid var(--line); }
.bl-rate input { flex: 1; min-width: 12rem; }
.bl-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr)); gap: var(--space-12); align-items: start; }
.bl-col .bl-body { max-width: none; }
.bl-s { cursor: pointer; border-radius: var(--radius-4, 4px); }
.bl-s:hover { background: var(--chip); }
.bl-s:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.bl-s[aria-pressed="true"] { background: var(--accent-soft); text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 3px; }
.bl-table-wrap { overflow-x: auto; }
.bl-table { width: 100%; border-collapse: collapse; }
.bl-table th, .bl-table td { padding: var(--space-8); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.bl-table .num { text-align: right; font-variant-numeric: tabular-nums; }
`;
(() => { const st = document.createElement('style'); st.textContent = BL_CSS; document.head.appendChild(st); })();
