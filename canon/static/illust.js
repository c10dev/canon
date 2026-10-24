/* 삽화 프롬프트 (NovelAI). 집필 화면에서 본문 일부를 고르면 그 장면을 NovelAI 에 붙여 넣을 프롬프트로 만든다.
   AI는 장면을 태그로 옮기기만 하고, 인물 외형 · 인물 수 · 등급 · 품질 태그는 서버 canon/illust.py 가 붙인다.
   인물 외형 태그(Project.visuals)는 설정 화면의 인물 카드에서 정해 두면 화가 바뀌어도 같은 모습으로 나온다.
   고치는 본문 칸에서는 passage.js 의 떠 있는 도구에 '삽화 프롬프트' 가 붙고, 반영이 끝난 읽기 전용 본문에서는 여기서 작은 도구를 띄운다. */
'use strict';

Object.assign(S, {
  illModels: null,  // 서버 illust.MODELS
  illSel: null,     // 그릴 부분 { n, start, text }
  illAsk: '',       // 덧붙일 요청
  illScroll: false, // 다시 그린 뒤 삽화 카드로 내려갈지
  illRebuild: {},   // 삽화 id → 다시 조립할 모델
  looks: {},        // 인물 id → AI 외형 태그 제안 메모
});

const IL_SUBJECT = { girl: '여성 (girl)', boy: '남성 (boy)', other: '그 밖 (other)' };
const IL_RATING = { general: '전연령', sensitive: '약한 노출', questionable: '노출', explicit: '성인' };

function splitTags(v) {
  return String(v || '').split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
}

const ilModel = (id) => (S.illModels || []).find((m) => m.id === id) || { id, label: id };
const ilCast = (n) => {
  const ids = ep(n).plot.characters || [];
  return P().characters.filter((c) => ids.includes(c.id));
};
const ilVisual = (cid) => (P().visuals || []).find((v) => v.character_id === cid);

function ilSel(n) {
  return S.illSel && S.illSel.n === n ? S.illSel : null;
}

/** 텍스트만 복사한다. 보안 연결이 아니면 복사 이벤트로 넣는다. */
async function copyPlain(text) {
  if (window.isSecureContext && navigator.clipboard) {
    try { await navigator.clipboard.writeText(text); return; } catch { /* 아래 방법으로 */ }
  }
  const put = (e) => { e.clipboardData.setData('text/plain', text); e.preventDefault(); };
  document.addEventListener('copy', put, { once: true });
  const ok = document.execCommand('copy');
  document.removeEventListener('copy', put);
  if (!ok) throw new Error('브라우저가 복사를 막았어요. 칸을 눌러 직접 복사해 주세요');
}

// ----- 설정 화면: 인물 카드의 외형 태그 -----

/** 프롬프트를 조립할 때 빠지는 태그 (illust.clean 과 같은 규칙: 한글, 인물 수, 등급, 성별 태그). 함께 고친다. */
function dropTags(text) {
  return splitTags(text).map((t) => t.trim().replace(/\.$/, '')).filter((t) => t && !t.includes('::')).filter((t) => {
    const x = t.toLowerCase().replace(/(?<=[a-z0-9])_(?=[a-z0-9(])/g, ' ').replace(/\s+/g, ' ');
    return /[ㄱ-ㆎ가-힣]/.test(x) || /^(\d+\+?|multiple|no)\s*(girls?|boys?|others?|humans)$/.test(x) || x.startsWith('rating:') || ['girl', 'boy', 'other'].includes(x);
  });
}

const dropNote = (text) => {
  const d = dropTags(text);
  return d.length ? `삽화에서 빠지는 태그: ${d.map(esc).join(', ')} (한글 · 인물 수 · 성별 · 등급은 프로그램이 따로 붙여요)` : '';
};

/** 인물 카드 아래 '삽화 외형 태그'. visuals 항목은 처음 고칠 때 만든다. */
function visualFields(c) {
  const v = ilVisual(c.id) || {};
  const id = (k) => `vis-${esc(c.id)}-${k}`;
  const has = (v.look || []).length > 0;
  const sub = v.subject || '';
  const area = (k, label, hint, ph) => `<div class="field"><label for="${id(k)}">${label} <span class="hint">${hint}</span></label>
    <textarea id="${id(k)}" rows="2" class="mono" data-vis="${esc(c.id)}" data-vis-key="${k}" placeholder="${ph}">${esc((v[k] || []).join(', '))}</textarea>
    <div class="small warn-text" data-vis-drop="${esc(c.id)}:${k}">${dropNote((v[k] || []).join(', '))}</div></div>`;
  const note = S.looks[c.id];
  return `<details class="vis"><summary>삽화 외형 태그 <span class="small">${has ? `${v.look.length - dropTags(v.look.join(', ')).length}개 · 화마다 같은 모습으로 그려요` : 'NovelAI 삽화용, 아직 없음'}</span></summary>
    <div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
      <div class="between"><span class="small">영어 태그를 쉼표로 나눠 적어요. 삽화 프롬프트마다 그대로 들어가요.</span>
        <button type="button" class="btn small" data-action="lookAI" data-arg="${esc(c.id)}">설정에서 AI로 만들기</button></div>
      ${note ? `<div class="note info">${esc(note)}</div>` : ''}
      <div class="field"><label for="${id('subject')}">그림 속 성별 <span class="hint">비우면 성별 칸으로 정해요</span></label>
        <select id="${id('subject')}" data-vis="${esc(c.id)}" data-vis-key="subject"><option value="">자동</option>${Object.entries(IL_SUBJECT).map(([k, l]) => `<option value="${k}"${sub === k ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
      ${area('look', '외형', '머리, 눈, 체형, 나이대처럼 바뀌지 않는 것', 'black hair, short hair, brown eyes, slim, teenage')}
      ${area('outfit', '기본 옷차림', '장면에서 다른 옷을 입으면 그 장면 것을 써요', 'school uniform, cardigan')}
      ${area('negative', '섞이면 안 되는 것', '다른 인물 특징이 옮아올 때 (인물 칸 부정 태그)', 'long hair, glasses')}
    </div></details>`;
}

function setVisual(cid, key, value) {
  const p = P();
  p.visuals = p.visuals || [];
  let v = ilVisual(cid);
  if (!v) {
    v = { character_id: cid, subject: '', look: [], outfit: [], negative: [] };
    p.visuals.push(v);
  }
  v[key] = key === 'subject' ? value : splitTags(value);
  markDirty();
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.vis) {
    setVisual(el.dataset.vis, el.dataset.visKey, el.value);
    const d = document.querySelector(`[data-vis-drop="${CSS.escape(`${el.dataset.vis}:${el.dataset.visKey}`)}"]`);
    if (d) d.innerHTML = dropNote(el.value);
  }
  if (el.id === 'ill-ask') S.illAsk = el.value;
});

document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.illRebuild) S.illRebuild[el.dataset.illRebuild] = el.value;
});

// ----- 집필 화면: 삽화 카드 -----

function ilField(label, text, rows = 3, extra = '') {
  return `<div class="ill-field"><div class="between"><span class="small"><strong>${label}</strong>${extra}</span>
      <button type="button" class="btn small" data-action="illCopy" data-arg="${esc(text)}">복사</button></div>
    <textarea class="mono" rows="${rows}" data-autogrow readonly aria-label="${esc(label)}">${esc(text)}</textarea></div>`;
}

function ilCard(n, x) {
  const m = ilModel(x.model);
  const names = Object.fromEntries(P().characters.map((c) => [c.id, c.name]));
  const pick = S.illRebuild[x.id] || x.model;
  const chars = x.characters.map((c, k) => ilField(`인물 ${k + 1} · ${esc(c.name || '이름 없는 인물')}`, c.prompt, 2,
    `${c.position ? ` <span class="chip">${esc(c.position)}</span>` : ''}${c.negative ? ` <span class="small">부정: ${esc(c.negative)}</span>` : ''}`)).join('');
  // 만들 때 외형이 없던 인물. 그 뒤 설정에 외형을 저장했으면 고정 대신 다시 조립을 권한다 (고정하면 저장한 태그를 덮는다)
  const missing = (x.missing_look || []).map((cid) => (((ilVisual(cid) || {}).look || []).length
    ? `<div class="note info between"><span>${esc(names[cid] || cid)}: 이 삽화를 만든 뒤 설정에 외형 태그가 생겼어요. 다시 조립하면 저장된 태그가 들어가요.</span>
      <button type="button" class="btn small" data-action="illRebuild" data-arg="${esc(x.id)}">다시 조립</button></div>`
    : `<div class="note warn between"><span>${esc(names[cid] || cid)}: 외형 태그가 저장되지 않아 AI가 붙인 태그를 썼어요. 다음 삽화에서 모습이 달라질 수 있어요.</span>
      <button type="button" class="btn small" data-action="illKeepLook" data-arg="${esc(x.id)}|${esc(cid)}">이 태그로 고정</button></div>`)).join('');
  return `<article class="ill-card">
    <div class="row" style="gap:6px"><strong>${esc(x.draft.scene || '장면')}</strong>
      <span class="chip">${esc(m.label)}</span><span class="chip${x.rating === 'general' ? '' : ' written'}">${IL_RATING[x.rating] || x.rating}</span>
      <span class="small">${x.selection ? '고른 부분' : 'AI가 고른 장면'} · ${editTime(x.at)}</span></div>
    <blockquote class="ill-quote">${esc((x.selection && x.selection.text.length <= 400 ? x.selection.text : x.draft.quote) || '')}</blockquote>
    ${x.request ? `<div class="small">요청: ${esc(x.request)}</div>` : ''}
    ${missing}
    ${(x.notes || []).map((t) => `<div class="note plain">${esc(t)}</div>`).join('')}
    ${ilField('기본 프롬프트 (Prompt)', x.base, 2)}
    ${chars}
    ${ilField('부정 프롬프트 (Undesired Content)', x.negative, 2)}
    ${x.characters.length ? `<details><summary class="small">인물 칸 없이 한 칸에 붙여 넣기 (| 로 나눔)</summary>${ilField('한 칸 프롬프트', x.combined, 4)}</details>` : ''}
    <div class="row ill-foot" style="gap:6px">
      <select aria-label="다시 조립할 모델" data-ill-rebuild="${esc(x.id)}">${(S.illModels || []).map((o) => `<option value="${esc(o.id)}"${o.id === pick ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>
      <button type="button" class="btn small" data-action="illRebuild" data-arg="${esc(x.id)}">다시 조립</button>
      <span class="small" style="flex:1 1 200px">AI를 다시 부르지 않고 고른 모델과 지금 외형 태그 · 화풍으로 다시 맞춰요</span>
      <button type="button" class="btn small danger" data-action="illDelete" data-arg="${esc(x.id)}">삭제</button></div>
  </article>`;
}

function illustPanel(n) {
  const e = ep(n);
  const s = P().illust || {};
  const sel = ilSel(n);
  const busy = !S.illModels;
  const cast = ilCast(n);
  const castLine = cast.map((c) => {
    const ok = ((ilVisual(c.id) || {}).look || []).length;
    return `<span class="chip${ok ? ' finalized' : ''}" title="${ok ? '외형 태그 있음' : '외형 태그 없음: 설정 도우미 인물 카드에서 정해 두면 화마다 같은 모습으로 나와요'}">${esc(c.name)}${ok ? '' : ' · 태그 없음'}</span>`;
  }).join(' ');
  // 가장 최근 것만 펼치고, 앞서 만든 것은 접어 둔다
  const list = [...(e.illustrations || [])].reverse().map((x, k) => (k === 0 ? ilCard(n, x)
    : `<details class="ill-old"><summary><strong>${esc(x.draft.scene || '장면')}</strong> <span class="small">${esc(ilModel(x.model).label)} · ${editTime(x.at)} · ${esc(clip((x.selection ? x.selection.text : x.draft.quote) || '', 40))}</span></summary>${ilCard(n, x)}</details>`)).join('');
  return `<section class="card" id="ill-panel" aria-label="삽화 프롬프트">
    <div class="between"><h2>삽화 프롬프트 <span class="small">NovelAI</span></h2>
      <span class="small">본문을 드래그해 '삽화 프롬프트'를 누르거나, 장면을 AI에게 맡기세요</span></div>
    <div class="cols" style="gap:16px">
      <div style="flex:2 1 420px;min-width:0;display:flex;flex-direction:column;gap:10px">
        ${sel ? `<div class="sel-target" style="padding:0;border:0"><div class="between"><span class="small">그릴 부분 · ${sel.text.length.toLocaleString()}자</span><button type="button" class="btn small" data-action="illClear">고른 것 풀기</button></div>
          <blockquote>${esc(clip(sel.text, 300))}</blockquote></div>`
        : '<div class="note plain">본문에서 그릴 부분을 드래그해 고르면 여기에 담겨요. 고르지 않으면 AI가 이 화에서 그림이 될 장면을 골라요.</div>'}
        <div class="field"><label for="ill-ask">바라는 것 <span class="hint">선택. 예: 뒷모습으로, 비 오는 밤, 두 사람만</span></label>
          <input id="ill-ask" type="text" value="${esc(S.illAsk)}" placeholder="비우면 장면 그대로"></div>
        <div class="row" style="gap:6px">
          <button type="button" class="btn primary" data-action="illMake" data-arg="sel"${sel && !busy ? '' : ' disabled'}>고른 부분으로 만들기</button>
          <button type="button" class="btn" data-action="illMake" data-arg="auto"${busy ? ' disabled' : ''}>AI가 장면 고르기</button></div>
        ${cast.length ? `<div class="small">이 화 인물 외형 태그: ${castLine} <a href="${base()}/setup">설정에서 고치기</a></div>` : ''}
      </div>
      <div style="flex:1 1 260px;min-width:0;display:flex;flex-direction:column;gap:8px">
        <div class="field"><label for="ill-model">NovelAI 모델</label>
          <select id="ill-model" data-bind="illust.model" data-kind="text">${(S.illModels || []).map((o) => `<option value="${esc(o.id)}"${o.id === s.model ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select></div>
        ${input('화풍 태그', 'illust.style', { kind: 'tags', rows: 2, hint: '모든 삽화에 들어가요', placeholder: 'watercolor, soft lighting' })}
        ${input('공통 부정 태그', 'illust.negative', { kind: 'tags', rows: 2, placeholder: 'blurry, multiple views' })}
        <label class="row small" style="gap:6px"><input type="checkbox" data-bind="illust.quality" data-kind="bool"${s.quality ? ' checked' : ''}><span style="flex:1 1 0;min-width:0">품질 태그 직접 넣기 (NovelAI 의 Add Quality Tags 를 끈 경우)</span></label>
        <label class="row small" style="gap:6px"><input type="checkbox" data-bind="illust.basic_negative" data-kind="bool"${s.basic_negative ? ' checked' : ''}><span style="flex:1 1 0;min-width:0">기본 부정 태그 넣기 (UC 프리셋을 끈 경우)</span></label>
        <span class="small">${P().meta.adult ? '성인 작품이라 장면에 맞는 등급(rating)을 붙여요.' : '전연령 작품이라 등급을 general · sensitive 로 묶고 부정 프롬프트에 nsfw 를 넣어요.'} 바꾼 설정은 저장한 뒤 새로 만들거나 '다시 조립'하면 들어가요.</span>
      </div>
    </div>
    ${list ? `<div class="ill-list">${list}</div>` : ''}
  </section>`;
}

// ----- 읽기 전용 본문(반영한 화)에서 고르기 -----

function ilTool() {
  let el = document.getElementById('ill-tool');
  if (!el) {
    el = document.createElement('div');
    el.id = 'ill-tool';
    el.className = 'sel-tool';
    el.hidden = true;
    el.innerHTML = '<button type="button" class="btn small primary" data-action="illFromRead">삽화 프롬프트</button>';
    document.body.appendChild(el);
  }
  return el;
}

function hideIlTool() {
  const el = document.getElementById('ill-tool');
  if (el) el.hidden = true;
}

/** 읽기 칸 안에서 고른 부분의 글자 위치. 앞뒤 공백은 뺀다. */
function readRangeSel(div) {
  const s = window.getSelection();
  if (!s || s.isCollapsed || !s.rangeCount) return null;
  const r = s.getRangeAt(0);
  if (!div.contains(r.startContainer) || !div.contains(r.endContainer)) return null;
  const pre = document.createRange();
  pre.setStart(div, 0);
  pre.setEnd(r.startContainer, r.startOffset);
  let a = pre.toString().length;
  let b = a + r.toString().length;
  const v = div.textContent;
  while (a < b && /\s/.test(v[a])) a++;
  while (b > a && /\s/.test(v[b - 1])) b--;
  return b > a ? { n: Number(div.dataset.read), start: a, text: v.slice(a, b), rect: r.getBoundingClientRect() } : null;
}

/** 읽기 전용 본문에서 고르면 삽화 도구를 띄운다. 마우스, 터치(길게 눌러 고르기), Shift+방향키 모두 같은 처리를 탄다. */
function onReadSelect(e, showOnly = false) {
  if (e && e.target && e.target.closest && e.target.closest('#ill-tool')) return;
  setTimeout(() => {
    const div = document.querySelector('.read[data-read]');
    const s = div && readRangeSel(div);
    if (!s) return showOnly ? undefined : hideIlTool();
    S.illPending = s;
    const el = ilTool();
    el.hidden = false;
    const w = el.offsetWidth || 120;
    el.style.left = `${Math.min(Math.max(8, s.rect.right - w), document.documentElement.clientWidth - w - 8) + window.scrollX}px`;
    el.style.top = `${s.rect.bottom + 6 + window.scrollY}px`;
  }, 0);
}

document.addEventListener('mouseup', onReadSelect);
document.addEventListener('touchend', onReadSelect);
document.addEventListener('keyup', (e) => { if (e.shiftKey || e.key === 'Shift') onReadSelect(e); });
// 휴대폰은 손잡이로 범위를 바꿀 때 selectionchange 만 온다. 여기서는 띄우기만 하고 닫지는 않는다 (도구 버튼을 누를 때 고른 것이 풀려도 남게)
let readSelTimer = 0;
document.addEventListener('selectionchange', () => {
  clearTimeout(readSelTimer);
  readSelTimer = setTimeout(() => onReadSelect(null, true), 200);
});

/** render() 직후: 떠 있는 도구를 닫고, 방금 만든 삽화가 보이게 내려간다. */
function syncIllust() {
  hideIlTool();
  if (!S.illScroll) return;
  S.illScroll = false;
  const card = document.querySelector('#ill-panel .ill-card');
  (card || document.getElementById('ill-panel'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function ilEpNum() {
  return Number(S.route[3]) || currentEp();
}

async function ilMake(n, sel) {
  await run(sel ? '장면을 태그로 옮기는 중' : '그릴 장면을 고르는 중', async () => {
    await saveIfDirty();
    if (typeof flushText === 'function') await flushText(n);
    const body = { request: S.illAsk, model: (P().illust || {}).model || '' };
    if (sel) body.selection = { start: sel.start, text: sel.text };
    S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/illust`, body);
    S.illScroll = true;
    const last = ep(n).illustrations[ep(n).illustrations.length - 1];
    toast(last && last.missing_look.length ? '만들었어요. 외형 태그가 없는 인물은 고정해 두세요' : '삽화 프롬프트를 만들었어요');
  });
}

Object.assign(actions, {
  selIllust() {  // 고치는 본문 칸의 떠 있는 도구에서
    const t = S.selTool;
    S.illSel = { n: t.n, start: t.start, text: t.text };
    hideTool();
    ilMake(t.n, S.illSel);
  },
  illFromRead() {
    const s = S.illPending;
    hideIlTool();
    window.getSelection()?.removeAllRanges();
    if (!s) return;
    S.illSel = { n: s.n, start: s.start, text: s.text };
    ilMake(s.n, S.illSel);
  },
  illMake(kind) {
    const n = ilEpNum();
    if (kind === 'sel' && !ilSel(n)) return toast('본문에서 그릴 부분을 먼저 드래그해 고르세요', true);
    ilMake(n, kind === 'sel' ? ilSel(n) : null);
  },
  illClear() {
    S.illSel = null;
    render();
  },
  async illCopy(text) {
    try {
      await copyPlain(String(text));
      toast('복사했어요. NovelAI 의 같은 칸에 붙여 넣으세요');
    } catch (e) {
      toast(e.message, true);
    }
  },
  async illRebuild(id) {
    const n = ilEpNum();
    await run('다시 조립하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/illust/${enc(id)}/rebuild`, { model: S.illRebuild[id] || '' });
      toast('지금 외형 태그와 설정으로 다시 조립했어요');
    });
  },
  async illDelete(id) {
    if (!confirm('이 삽화 프롬프트를 지울까요?')) return;
    const n = ilEpNum();
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/episodes/${n}/illust/${enc(id)}`);
    });
  },
  async illKeepLook(arg) {
    const [id, cid] = String(arg).split('|');
    const n = ilEpNum();
    const have = ((ilVisual(cid) || {}).look || []).join(', ');
    // 이미 저장한 외형이 있으면 지금 값과 AI 값을 보여 주고 묻는다. 서버도 확인(force) 없이는 덮지 않는다
    const ill = (ep(n).illustrations || []).find((x) => x.id === id);
    const ai = ill ? ((ill.draft.characters.find((c) => c.id === cid) || {}).look || []).join(', ') : '';
    const force = !!have;
    if (force && !confirm(`${charName(cid)}의 외형 태그를 바꿀까요?\n\n지금: ${have}\nAI: ${ai}`)) return;
    await run('외형 태그 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/illust/${enc(id)}/keep-look`, { character_id: cid, force });
      toast(`${charName(cid)}의 외형 태그로 저장했어요. 설정 도우미 인물 카드에서 고칠 수 있어요`);
    });
  },
  async lookAI(cid) {
    const v = ilVisual(cid);
    const filled = v ? [['외형', v.look], ['기본 옷차림', v.outfit]].filter(([, x]) => (x || []).length).map(([k]) => k) : [];
    if (v && v.subject) filled.push('그림 속 성별');
    if (filled.length && !confirm(`지금 적힌 ${filled.join(' · ')}을(를) AI 제안으로 바꿀까요? 저장하기 전에는 '변경 모두 버리기'로 되돌릴 수 있어요`)) return;
    await run('외형 태그 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 인물 설정을 읽는다. 방금 고친 설정이나 새 인물도 보게 먼저 저장한다
      const s = await api('POST', `/projects/${enc(S.name)}/characters/${enc(cid)}/look`);
      setVisual(cid, 'look', s.look.join(', '));
      if (s.outfit.length) setVisual(cid, 'outfit', s.outfit.join(', '));
      // '자동'은 성별 칸으로 정한다(illust.subject_of). 같은 값이면 자동으로 둬서 성별 칸을 고치면 따라가게 한다
      const c = P().characters.find((x) => x.id === cid);
      const g = ((c && c.gender) || '').trim().toLowerCase();
      const auto = g.startsWith('여') || ['f', 'female', 'woman', 'girl'].includes(g) ? 'girl' : g.startsWith('남') || ['m', 'male', 'man', 'boy'].includes(g) ? 'boy' : 'other';
      if ((ilVisual(cid) || {}).subject || s.subject !== auto) setVisual(cid, 'subject', s.subject);
      S.looks[cid] = s.note || '';
      toast('제안을 칸에 넣었어요. 고친 뒤 저장하세요');
    });
    const d = document.querySelector(`[data-vis="${CSS.escape(cid)}"]`)?.closest('details');
    if (d) d.open = true;
  },
});
