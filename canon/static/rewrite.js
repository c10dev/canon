/* 다시 생성 (집필 화면). app.js 의 S, actions, api, render, startJob, jobBtn 과 passage.js 의 wordDiff, flushText 를 그대로 쓴다.
   '다시 생성'을 누르면 패널이 열려 피드백, 빠른 요청, 함께 넣을 재료(검수 결과 등), 방식(처음부터 / 고쳐 쓰기), 살릴 부분을 고른다.
   새 판은 본문을 덮지 않고 Episode.candidate 에 와서 지금 판과 나란히 또는 바뀐 곳으로 비교해 고른다.
   바꾸기 전 판과 고르지 않은 판은 Episode.versions 에 남아 되돌릴 수 있다. 서버는 web.py 의 '4-0. 다시 생성'. */
'use strict';

Object.assign(S, {
  rwOpen: null,      // 다시 생성 패널을 연 화
  rwInfo: {},        // 화 → GET /rewrite (빠른 요청, 재료)
  rw: {},            // 화 → 고르는 중인 요청 { feedback, presets, materials, mode, keep }
  rwPrompt: null,    // 패널에서 펼친 프롬프트 원문
  rwView: 'side',    // 새 판 비교: side(나란히) | diff(바뀐 곳)
  rwPeek: null,      // 이전 판 목록에서 펼친 판 id
  rwVersionsOpen: false,
  rwSync: true,      // 나란히 비교의 두 칸을 함께 스크롤
});

JOB_DONE_MSG.write = (j) => (j.result && j.result.candidate ? `${j.ep}화 새 판이 나왔어요. 지금 판과 비교해 고르세요.` : `${j.ep}화 본문을 저장했어요.`);

const RW_MODES = [
  ['fresh', '처음부터 새로', '지난 판은 보내지 않고 같은 플롯으로 새로 써요. 전개를 크게 바꾸고 싶을 때.'],
  ['revise', '지난 판 고쳐 쓰기', '지난 판 전문을 함께 보내 흐름과 좋은 문장은 살리고 고쳐요. 대체로 괜찮고 몇 군데만 아쉬울 때.'],
];
const RW_KIND = { previous: '바꾸기 전', rejected: '고르지 않은 새 판' };

async function rwLoad(n) {
  S.rwInfo[n] = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/rewrite`).catch(() => null);
}

/** 처음 열 때의 요청. 검수 결과와 흡입력 판정은 있으면(오래되지 않았으면) 넣는다. */
function rwReq(n) {
  if (!S.rw[n]) {
    const info = S.rwInfo[n];
    const on = info ? info.materials.filter((m) => ['issues', 'hook'].includes(m.id) && m.lines.length && !m.note).map((m) => m.id) : [];
    S.rw[n] = { feedback: '', presets: [], materials: on, mode: 'fresh', keep: [] };
  }
  return S.rw[n];
}

function rwPresetLabel(n, id) {
  const x = ((S.rwInfo[n] || {}).presets || []).find((p) => p.id === id);
  return x ? x.label : id;
}

/** 요청을 짧게: 빠른 요청 이름과 피드백 앞부분. */
function rwReqLabel(n, r) {
  if (!r) return '';
  const bits = r.presets.map((id) => `<span class="chip ai">${esc(rwPresetLabel(n, id))}</span>`);
  if (r.mode === 'revise') bits.push('<span class="chip">고쳐 쓰기</span>');
  if (r.feedback) bits.push(`<span class="small">${esc(clip(r.feedback, 60))}</span>`);
  return bits.join(' ');
}

// ----- 문단 단위 비교 -----

function rwSimilar(a, b) {
  const A = new Set(tokens(a).filter((t) => t.trim()));
  const B = tokens(b).filter((t) => t.trim());
  if (!A.size || !B.length) return false;
  return B.filter((t) => A.has(t)).length / Math.max(A.size, B.length) >= 0.4;
}

/** 본문 두 판을 줄(문단)로 맞춰 보고, 바뀐 문단끼리 닮았으면 단어 단위로, 아니면 통째로 지운 글 · 더한 글로 보여 준다. */
function textDiff(a, b) {
  const A = a.split('\n');
  const B = b.split('\n');
  if (A.length * B.length > 250000) return `<del>${esc(a)}</del><ins>${esc(b)}</ins>`;
  const L = Array.from({ length: A.length + 1 }, () => new Uint16Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--) {
    for (let j = B.length - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  }
  const out = [];
  let changes = 0;
  let dels = [];
  let adds = [];
  const flush = () => {
    if (dels.length || adds.length) changes++;  // 바뀐 곳: 연달아 바뀐 문단 묶음 하나
    const k = Math.min(dels.length, adds.length);
    for (let x = 0; x < k; x++) {
      out.push(rwSimilar(dels[x], adds[x]) ? wordDiff(dels[x], adds[x]) : `${dels[x] ? `<del>${esc(dels[x])}</del>` : ''}${dels[x] && adds[x] ? '\n' : ''}${adds[x] ? `<ins>${esc(adds[x])}</ins>` : ''}`);
    }
    dels.slice(k).forEach((t) => out.push(t ? `<del>${esc(t)}</del>` : ''));
    adds.slice(k).forEach((t) => out.push(t ? `<ins>${esc(t)}</ins>` : ''));
    dels = [];
    adds = [];
  };
  let i = 0;
  let j = 0;
  while (i < A.length || j < B.length) {
    if (i < A.length && j < B.length && A[i] === B[j]) {
      flush();
      out.push(esc(A[i]));
      i++;
      j++;
    } else if (j >= B.length || (i < A.length && L[i + 1][j] >= L[i][j + 1])) dels.push(A[i++]);
    else adds.push(B[j++]);
  }
  flush();
  textDiff.changes = changes;
  return out.join('\n');
}

/** 바뀐 곳 비교와 그 머리: 바뀐 곳 개수, 이전 · 다음 바뀐 곳으로 가기. 긴 본문에서 바뀐 곳을 찾느라 끝까지 내리지 않게 한다. */
function diffBox(a, b, cls, note) {
  const html = textDiff(a, b);
  const n = textDiff.changes;
  const nav = n ? `<span class="row" style="gap:6px"><span class="small">바뀐 곳 ${n}곳</span><button type="button" class="btn small" data-diff-jump="-1" aria-label="이전 바뀐 곳">↑</button><button type="button" class="btn small" data-diff-jump="1" aria-label="다음 바뀐 곳">↓</button></span>` : '<span class="small">바뀐 곳이 없어요</span>';
  return `<div class="diff-box"><div class="between"><div class="small">${note}</div>${nav}</div><div class="pdiff ${cls} rw-text">${html}</div></div>`;
}

// ----- 다시 생성 패널 -----

function rewritePanel(n) {
  if (S.rwOpen !== n) return '';
  const info = S.rwInfo[n];
  if (!info) return rwColumn(n, '<div class="small">불러오는 중…</div>', '');
  const r = rwReq(n);
  const busy = !!jobFor('write', n);
  const chips = info.presets.map((x) => `<button type="button" class="btn small${r.presets.includes(x.id) ? ' on' : ''}" aria-pressed="${r.presets.includes(x.id)}" data-action="rwPreset" data-arg="${esc(x.id)}">${esc(x.label)}</button>`).join('');
  const mats = info.materials.map((m) => {
    const none = !m.lines.length;
    return `<label class="check-row${none ? ' done' : ''}"><input type="checkbox" data-rw-mat="${esc(m.id)}"${r.materials.includes(m.id) && !none ? ' checked' : ''}${none ? ' disabled' : ''}>
      <span style="flex:1;min-width:0"><strong>${esc(m.label)}</strong> <span class="small">${none ? '없음' : `${m.lines.length}개`}</span>
        ${m.note ? `<br><span class="small" style="color:var(--amber-ink)">${esc(m.note)}</span>` : ''}
        ${none ? '' : `<details><summary class="small">넣을 내용 보기</summary><div class="small rw-lines">${m.lines.map(esc).join('<br>')}</div></details>`}</span></label>`;
  }).join('');
  const modes = RW_MODES.map(([id, label]) => `<button type="button" aria-pressed="${r.mode === id}" data-action="rwMode" data-arg="${id}">${label}</button>`).join('');
  const keep = r.keep.map((k, i) => `<li class="between" style="gap:8px;align-items:flex-start"><blockquote>${esc(clip(k, 200))}</blockquote><button type="button" class="btn small" data-action="rwDropKeep" data-arg="${i}" aria-label="살릴 부분 빼기">빼기</button></li>`).join('');
  return rwColumn(n, `<p class="small" style="margin:0">무엇이 아쉬웠는지 알려 주면 새 판을 쓸 때 참고해요. 지금 본문은 그대로 두고, 새 판이 오면 비교해서 골라요.</p>
    <div class="field"><span class="small">빠른 요청 (여러 개 고를 수 있어요)</span><div class="row rw-chips" style="gap:6px">${chips}</div></div>
    <div class="field"><label class="small" for="rw-feedback">피드백</label>
      <textarea id="rw-feedback" data-rw-feedback="${n}" rows="3" placeholder="예: ${esc(exName(0))}이(가) 너무 빨리 마음을 연다. 중간에 한 번 더 밀어내게 해 줘">${esc(r.feedback)}</textarea></div>
    <div class="field"><span class="small">함께 넣을 것</span><div class="grid-2">${mats}</div></div>
    <div class="field"><span class="small">방식</span><div class="seg" role="group" aria-label="다시 쓰는 방식">${modes}</div>
      <span class="small">${RW_MODES.find((m) => m[0] === r.mode)[2]}</span></div>
    <div class="field"><span class="small">살릴 부분 ${r.keep.length}/${info.keep_max}</span>
      ${keep ? `<ol class="rw-keep">${keep}</ol>` : ''}
      <span class="small">마음에 드는 문장이나 장면은 본문에서 드래그한 뒤 '살리기'를 누르면 담겨요. 새 판에 거의 그대로 들어가요.</span></div>
    ${busy ? '<div class="small">다른 화면으로 옮겨 가도 계속 써요. 끝나면 알려 드려요.</div>' : ''}
    ${S.rwPrompt ? `<pre class="brief mono" style="max-height:420px">${esc(S.rwPrompt)}</pre>` : ''}`,
    `<button type="button" class="btn small" data-action="rwShowPrompt" data-arg="${n}">${S.rwPrompt ? '프롬프트 닫기' : '보낼 프롬프트 보기'}</button>
      ${((b) => `<button type="button" class="btn primary" data-action="rwSubmit" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('write', n, '새 판 만들기'))}`);
}

/** 다시 생성 열: 대화 패널 자리(오른쪽, 휴대폰은 아래 시트)에 뜬다. 본문을 아래로 밀지 않아 고르며 '살리기'를 담을 수 있다. */
function rwColumn(n, body, foot) {
  return `<aside class="tool-col rw-panel" aria-label="${n}화 다시 생성">
    <div class="chat-head"><h2>${n}화 다시 생성</h2><button type="button" class="btn icon-btn" data-action="rwClose" aria-label="닫기">✕</button></div>
    <div class="tool-body">${body}</div>
    ${foot ? `<div class="tool-foot between">${foot}</div>` : ''}
  </aside>`;
}

// ----- 새 판 비교 -----

function candidateCard(n) {
  const e = ep(n);
  const c = e && e.candidate;
  if (!c || !editableEp(e)) return '';
  const cur = textNow(n);
  const side = S.rwView === 'side';
  const body = side
    ? `<div class="rw-side">
        <div><div class="small">지금 판 · ${cur.length.toLocaleString()}자</div><div class="rw-text">${esc(cur)}</div></div>
        <div><div class="small">새 판 · ${c.text.length.toLocaleString()}자</div><div class="rw-text">${esc(c.text)}</div></div></div>`
    : diffBox(cur, c.text, '', '지금 판에서 지운 글은 빨강, 새 판에 더한 글은 초록이에요.');
  return `<section class="card rw-compare" aria-label="새 판 비교">
    <div class="between"><div><h3>새 판이 나왔어요</h3><div class="row" style="gap:6px">${rwReqLabel(n, c.request)}<span class="small">${editTime(c.at)}</span></div></div>
      <div class="row" style="gap:6px">${side ? `<button type="button" class="btn small" aria-pressed="${S.rwSync}" data-action="rwSyncToggle" title="한 칸을 내리면 다른 칸도 같은 비율로 내려가요">스크롤 함께</button>` : ''}<div class="seg" role="group" aria-label="비교 방식"><button type="button" aria-pressed="${side}" data-action="rwViewAs" data-arg="side">나란히</button><button type="button" aria-pressed="${!side}" data-action="rwViewAs" data-arg="diff">바뀐 곳</button></div></div></div>
    ${body}
    ${(c.meta_cut || []).length ? `<div class="small">새 판을 쓸 때 AI가 붙인 작업 설명 ${c.meta_cut.length}문단을 뗐어요. 새 판으로 바꾸면 집필 화면에서 보고 되살릴 수 있어요.</div>` : ''}
    <div class="between"><span class="small" style="flex:1;min-width:200px">바꾸면 지금 판은 아래 '이전 판'에 남아 되돌릴 수 있어요(화마다 최근 6개, 고르지 않은 판부터 지워요). 검수 결과는 새 판 기준으로 다시 하세요.</span>
      <span class="row"><button type="button" class="btn" data-action="rwDrop" data-arg="${n}">지금 판 두기</button><button type="button" class="btn" data-action="rwAgain" data-arg="${n}">요청 고쳐 다시 받기</button><button type="button" class="btn primary" data-action="rwAdopt" data-arg="${n}">새 판으로 바꾸기</button></span></div>
  </section>`;
}

// ----- 이전 판 -----

function versionsPanel(e) {
  const list = [...(e.versions || [])].reverse();
  if (!list.length) return '';
  const n = e.plot.number;
  const cur = textNow(n);
  const can = editableEp(e) && S.textDraft[n] === undefined;
  const rows = list.map((v) => `<li class="edit-row">
      <div class="between"><span class="row" style="gap:6px"><span class="chip${v.kind === 'rejected' ? '' : ' ai'}">${RW_KIND[v.kind] || v.kind}</span><span class="small">${v.text.length.toLocaleString()}자</span>${rwReqLabel(n, v.request)}<span class="small">${editTime(v.at)}</span></span>
        <span class="row" style="gap:6px"><button type="button" class="btn small" data-action="rwPeekAt" data-arg="${esc(v.id)}">${S.rwPeek === v.id ? '접기' : '지금 판과 비교'}</button>
        ${can ? `<button type="button" class="btn small" data-action="rwRestore" data-arg="${esc(v.id)}">이 판으로 복원</button>` : ''}</span></div>
      ${S.rwPeek === v.id ? diffBox(cur, v.text, 'small-diff', '빨강은 지금 판에만, 초록은 이 판에만 있는 글이에요.') : ''}</li>`).join('');
  return `<details class="card edits"${S.rwVersionsOpen ? ' open' : ''} data-rw-versions>
    <summary><strong>이전 판</strong> <span class="small">${list.length}개 · 다시 생성으로 바꾸기 전 본문과 고르지 않은 새 판. 최근 6개까지 남고, 넘치면 고르지 않은 판부터 지워요${editableEp(e) && !can ? ' (저장하지 않은 본문이 있으면 먼저 저장하세요)' : ''}</span></summary>
    <ol class="edit-list">${rows}</ol></details>`;
}

// ----- 본문 칸의 떠 있는 도구 -----

// 다시 생성 패널이 열려 있으면 passage.js 의 도구 메뉴 끝에 '살리기'를 붙인다
const rwShowTool = showTool;
showTool = function showToolWithKeep() {
  rwShowTool();
  const t = S.selTool;
  const el = document.getElementById('sel-tool');
  const ta = t && document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta || !el || el.hidden || t.mode !== 'menu' || S.rwOpen !== t.n) return;
  el.insertAdjacentHTML('beforeend', '<button type="button" class="btn small" data-action="selKeep" title="다시 생성할 때 이 부분을 거의 그대로 살린다">살리기</button>');
  placeTool(ta, t);  // 버튼이 늘어 폭이 바뀌었다
};

// ----- 입력 -----

document.addEventListener('input', (e) => {
  const n = e.target.dataset && e.target.dataset.rwFeedback;
  if (n !== undefined) rwReq(Number(n)).feedback = e.target.value;
});

document.addEventListener('change', (e) => {
  const id = e.target.dataset && e.target.dataset.rwMat;
  if (id === undefined || S.rwOpen == null) return;
  const r = rwReq(S.rwOpen);
  r.materials = e.target.checked ? [...new Set([...r.materials, id])] : r.materials.filter((x) => x !== id);
  S.rwPrompt = null;
});

// 나란히 비교: 한 칸을 내리면 다른 칸도 같은 비율로 맞춘다. 맞추느라 생긴 스크롤은 다시 따라가지 않는다
let rwSyncing = null;
document.addEventListener('scroll', (e) => {
  const a = e.target;
  if (!S.rwSync || !(a.matches && a.matches('.rw-side .rw-text'))) return;
  if (rwSyncing === a) { rwSyncing = null; return; }
  const b = [...a.closest('.rw-side').querySelectorAll('.rw-text')].find((x) => x !== a);
  const max = a.scrollHeight - a.clientHeight;
  if (!b || max <= 0) return;
  const top = Math.round((a.scrollTop / max) * (b.scrollHeight - b.clientHeight));
  if (Math.abs(b.scrollTop - top) < 1) return;
  rwSyncing = b;
  b.scrollTop = top;
  requestAnimationFrame(() => { if (rwSyncing === b) rwSyncing = null; });  // 끝에 닿아 스크롤이 안 일어난 때
}, true);

document.addEventListener('toggle', (e) => {
  if (e.target.matches && e.target.matches('[data-rw-versions]')) S.rwVersionsOpen = e.target.open;
}, true);

// 바뀐 곳 사이를 오간다. 상자마다 지금 몇 번째인지 기억한다
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-diff-jump]');
  if (!b) return;
  const box = b.closest('.diff-box');
  // 지운 글 바로 뒤에 넣은 글이 붙어 있으면 한 곳으로 센다
  const marks = [...box.querySelectorAll('.pdiff del, .pdiff ins')].filter((m) => !(m.tagName === 'INS' && m.previousSibling && m.previousSibling.nodeName === 'DEL'));
  if (!marks.length) return;
  const cur = Number(box.dataset.at ?? -1);
  const next = (cur + Number(b.dataset.diffJump) + marks.length) % marks.length;
  box.dataset.at = next;
  const m = marks[next];
  m.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  m.classList.remove('flash');
  void m.offsetWidth;
  m.classList.add('flash');
});

Object.assign(actions, {
  async rwOpen(n) {
    n = Number(n);
    if (S.rwOpen === n) return actions.rwClose();
    S.rwOpen = n;
    S.rwPrompt = null;
    S.chatOpen = false;  // 다시 생성 열은 대화 패널 자리에 뜬다. 하나만 연다
    render();
    await rwLoad(n);  // 재료는 본문과 수정 기록에 따라 바뀌니 열 때마다 새로 받는다
    render();
    const box = $('#rw-feedback');
    if (box) box.focus({ preventScroll: true });
  },
  rwClose() {
    S.rwOpen = null;
    S.rwPrompt = null;
    render();
  },
  rwPreset(id) {
    const r = rwReq(S.rwOpen);
    r.presets = r.presets.includes(id) ? r.presets.filter((x) => x !== id) : [...r.presets, id];
    S.rwPrompt = null;
    render();
  },
  rwMode(m) {
    rwReq(S.rwOpen).mode = m;
    S.rwPrompt = null;
    render();
  },
  rwDropKeep(i) {
    rwReq(S.rwOpen).keep.splice(Number(i), 1);
    S.rwPrompt = null;
    render();
  },
  selKeep() {  // 본문 칸의 떠 있는 도구에서
    const t = S.selTool;
    hideTool();
    const r = rwReq(t.n);
    const max = (S.rwInfo[t.n] || {}).keep_max || 5;
    if (r.keep.includes(t.text)) return toast('이미 담은 부분이에요');
    if (r.keep.length >= max) return toast(`살릴 부분은 ${max}개까지예요. 하나를 빼고 담으세요`, true);
    r.keep.push(t.text);
    S.rwPrompt = null;
    render();
  },
  async rwShowPrompt(n) {
    if (S.rwPrompt) {
      S.rwPrompt = null;
      return render();
    }
    await run('불러오는 중', async () => {
      await flushText(Number(n));
      const x = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/rewrite/prompt`, rwReq(Number(n)));
      S.rwPrompt = `[시스템]\n${x.system}\n\n[프롬프트]\n${x.prompt}`;
    });
  },
  async rwSubmit(n) {
    n = Number(n);
    const r = rwReq(n);
    try {
      await flushText(n);  // 고쳐 쓰기는 저장한 본문을 보낸다
    } catch (e) {
      return toast(e.message, true);
    }
    S.rwOpen = null;
    S.rwPrompt = null;
    await startJob('write', n, { rewrite: { ...r, keep: [...r.keep] } });
  },
  rwSyncToggle() {
    S.rwSync = !S.rwSync;
    render();
  },
  rwViewAs(v) {
    S.rwView = v;
    render();
  },
  async rwAdopt(n) {
    await run('바꾸는 중', async () => {
      await flushText(Number(n));
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/candidate/adopt`);
      delete S.rw[n];
      toast("새 판으로 바꿨어요. 지금까지의 본문은 아래 '이전 판'에 남았어요.");
    });
  },
  async rwDrop(n) {
    await run('정리하는 중', async () => {
      S.project = await api('DELETE', `/projects/${enc(S.name)}/episodes/${n}/candidate`);
      toast("새 판을 고르지 않았어요. 버린 판도 '이전 판'에 남아요 (6개가 넘으면 고르지 않은 판부터 지워요).");
    });
  },
  async rwAgain(n) {
    n = Number(n);
    const c = ep(n).candidate;
    if (c && c.request) S.rw[n] = { ...c.request, presets: [...c.request.presets], materials: [...c.request.materials], keep: [...c.request.keep] };
    S.rwOpen = null;
    await actions.rwOpen(n);
  },
  rwPeekAt(id) {
    S.rwPeek = S.rwPeek === id ? null : id;
    render();
  },
  async rwRestore(id) {
    const n = Number(S.route[3]) || currentEp();
    if (!confirm('지금 본문을 이전 판에 남기고 이 판으로 되돌릴까요?')) return;
    await run('되돌리는 중', async () => {
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/versions/${enc(id)}/restore`);
      S.rwPeek = null;
      toast('되돌렸어요. 검수 결과는 이 판 기준으로 다시 하세요.');
    });
  },
});
