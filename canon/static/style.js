/* 2단계 문체 레퍼런스와 문체 라이브러리. app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 2. 문체 -----

function emptyProfile() {
  return {
    narration_pov: '', tense: '', sentence_rhythm: '', description_density: '', dialogue_ratio: '', dialogue_style: '',
    inner_monologue: '', pacing: '', scene_transition: '', vocabulary: '', dos: [], donts: [], banned_phrases: [], markers: [], devices: [], sample_passages: [],
  };
}

/** 스타일 프로필 편집 칸. 작품 화면(base='style')과 라이브러리 화면(base='profile', root='lib')이 같이 쓴다. */
function profileFields(base, root) {
  const o = (x = {}) => (root ? { ...x, root } : x);
  const prof = getPath(bindRoot(root), base);
  const act = root ? 'libRemovePassage' : 'removePassage';
  const passages = prof.sample_passages.map((_, i) => `<div class="field-row">
      <div class="fr-grow">${input(`대표 문단 ${i + 1}`, `${base}.sample_passages.${i}`, o({ rows: 3 }))}</div>
      <button class="btn icon-btn danger" data-action="${act}" data-arg="${i}" aria-label="대표 문단 ${i + 1} 삭제">✕</button></div>`).join('');
  prof.markers = prof.markers || [];
  // 좁은 폭에서는 표지 · 쓰임을 한 줄씩 펼친다 (한 줄에 넷을 두면 표지 칸이 40px 남짓으로 눌린다)
  const markers = prof.markers.map((_, i) => `<div class="field-row mk-row">
      <div class="mk-text">${input(`표지 ${i + 1}`, `${base}.markers.${i}.text`, o({ placeholder: '원문에 적힌 그대로, 예: 것이었다' }))}</div>
      <div class="mk-note">${input('쓰임', `${base}.markers.${i}.note`, o())}</div>
      <div class="mk-rate">${input('1,000자당', `${base}.markers.${i}.per_1k`, o({ kind: 'float' }))}</div>
      <button class="btn icon-btn danger" data-action="${root ? 'libRemoveMarker' : 'removeMarker'}" data-arg="${i}" aria-label="표지 ${i + 1} 삭제">✕</button></div>`).join('');
  const f = (label, key, x) => input(label, `${base}.${key}`, o(x));
  return `<div class="grid-2">
      ${f('시점', 'narration_pov')}${f('시제', 'tense')}
      ${f('문장 리듬', 'sentence_rhythm', { rows: 2 })}${f('묘사 밀도', 'description_density', { rows: 2 })}
      ${f('대사 비율', 'dialogue_ratio')}${f('대사 방식', 'dialogue_style')}
      ${f('내면 독백', 'inner_monologue')}${f('전개 속도', 'pacing')}
      ${f('장면 전환', 'scene_transition')}${f('어휘', 'vocabulary')}
    </div>
    <div class="grid-2">
      <div class="note ok">${f('지킬 것', 'dos', { kind: 'list', rows: 4 })}</div>
      <div class="note err">${f('피할 것', 'donts', { kind: 'list', rows: 4 })}</div>
    </div>
    ${f('금지 표현', 'banned_phrases', { kind: 'list', rows: 2, placeholder: '본문에 나오면 경고할 표현, 한 줄에 하나씩' })}
    <div class="between"><h3>문체 표지 <span class="small" style="font-weight:400">어미, 조사, 말버릇과 원문 빈도. 넘치거나 빠지면 경고</span></h3><button class="btn small" data-action="${root ? 'libAddMarker' : 'addMarker'}">+ 표지</button></div>
    ${markers || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 빈도를 세어요.</div>'}
    ${deviceFields(base, root)}
    <div class="between"><h3>대표 문단 <span class="small" style="font-weight:400">본문 생성 때 그대로 보여줄 원문 예시, 2~4개</span></h3><button class="btn small" data-action="${root ? 'libAddPassage' : 'addPassage'}">+ 문단</button></div>
    ${passages || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 넣어요.</div>'}`;
}

/** 작품 문체 화면 위쪽: 라이브러리에서 가져오기, 라이브러리에 저장하기 */
/** 라이브러리와 다를 때 어느 쪽이 바뀌었는지 (library.link_state 의 mine · theirs). */
function styleChangeWho(l) {
  const mine = (l.mine || []).length > 0;
  const theirs = (l.theirs || []).length > 0;
  if (!l.base_known) return l.applied && l.version > l.applied ? `이 작품은 ${l.applied}번 버전, 라이브러리는 ${l.version}번 버전이에요` : '이 작품에서 고쳤거나 라이브러리가 바뀌었어요';
  if (mine && theirs) return `이 작품도 고쳤고, 라이브러리도 ${l.applied}번 → ${l.version}번 버전으로 바뀌었어요`;
  if (theirs) return `라이브러리가 ${l.applied}번 → ${l.version}번 버전으로 바뀌었어요. 이 작품은 그대로예요`;
  return '이 작품에서 고쳤어요. 라이브러리는 가져온 버전 그대로예요';
}

function styleLibraryCard() {
  const libs = S.libs || [];
  const l = S.styleLink || { state: 'none' };
  const opts = libs.map((x) => `<option value="${esc(x.id)}"${x.id === l.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('');
  const blank = styleBlank(P().style);
  const status = {
    none: blank ? '<span class="small">아직 문체가 없어요. 아래에 원문을 붙여 넣어 분석하거나 라이브러리에서 고르세요.</span>' : '<span class="small">이 작품에서 직접 만든 문체예요.</span>',
    missing: '<span class="small">가져온 라이브러리 항목이 지워졌어요. 작품에 복사된 문체는 그대로 써요.</span>',
    same: `<span class="chip finalized">라이브러리와 같음</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${l.version}번 버전</span>`,
    changed: `<span class="chip written">라이브러리와 다름</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${styleChangeWho(l)}</span>`,
  }[l.state] || '';
  const fields = (list) => list.map((c) => esc(c.label)).join(', ');
  const detail = l.state === 'changed' && ((l.mine || []).length || (l.theirs || []).length)
    ? `<details><summary class="small">어느 칸이 다른지</summary><div class="small" style="padding-top:6px">${(l.mine || []).length ? `<div>이 작품에서 고친 칸: ${fields(l.mine)}</div>` : ''}${(l.theirs || []).length ? `<div>라이브러리 ${l.version}번 버전에서 바뀐 칸: ${fields(l.theirs)}</div>` : ''}<div>올리기는 작품 쪽을 라이브러리 새 버전으로, 가져오기 · 되돌리기는 라이브러리 쪽을 작품에 가져와요.</div></div></details>` : '';
  // 라이브러리가 더 새 버전이면 '가져오기', 작품만 고쳤으면 '되돌리기'
  const newer = (l.theirs || []).length > 0 || (!l.base_known && l.applied && l.version > l.applied);
  const linkBtns = l.state === 'changed'
    ? `<button class="btn small" data-action="pushStyle">라이브러리 새 버전으로 올리기</button><button class="btn small" data-action="pullStyle">${newer ? '라이브러리 최신 버전 가져오기' : '라이브러리 버전으로 되돌리기'}</button>`
    : '';
  // 빈 문체는 저장하지 않는다 (web.keep_style 도 막는다). 프로필 칸을 채우면 아래 input 처리가 버튼을 켠다
  const keepOff = blank;
  return `<section class="card tight">
      <div class="between"><h2>문체 라이브러리</h2><a class="small" href="#/styles">라이브러리 열기</a></div>
      <div class="row">${status}</div>${detail}
      <div class="row" style="flex-wrap:nowrap">
        ${libs.length
          ? `<select id="style-pick" aria-label="라이브러리 문체" style="flex:1"><option value="">라이브러리에서 고르기</option>${opts}</select><button class="btn small" style="flex:none" data-action="useLibStyle">적용</button>`
          : `<span class="small" style="flex:1">라이브러리가 비어 있어요. ${blank ? '문체를 만든 뒤 저장해 두면' : '이 작품의 문체를 저장해 두면'} 다른 작품에서 다시 쓸 수 있어요.</span>`}
      </div>
      <div class="row">${linkBtns}<button class="btn small" data-action="keepStyle"${keepOff ? ' disabled aria-describedby="keep-off"' : ''}>이 문체를 라이브러리에 새로 저장</button><span class="small" id="keep-off"${keepOff ? '' : ' hidden'}>문체 분석이나 프로필을 채운 뒤 저장할 수 있어요</span></div>
    </section>`;
}

// 작품 문체 칸을 채우거나 비우면 '라이브러리에 새로 저장' 버튼을 켜고 끈다 (다시 그리지 않고)
document.addEventListener('input', (e) => {
  if (S.route[2] !== 'style' || !(e.target.dataset.bind || '').startsWith('style.')) return;
  const btn = $('[data-action="keepStyle"]');
  if (!btn) return;
  btn.disabled = styleBlank(P().style);
  const why = $('#keep-off');
  if (why) why.hidden = !btn.disabled;
});

/** 스타일 프로필 칸이 모두 비었다 (library.blank 와 같은 규칙) */
const styleBlank = (st) => !Object.values(st || {}).some((v) => (typeof v === 'string' ? v.trim() : Array.isArray(v) ? v.length : v));

function viewStyle() {
  // 문체가 비었으면 예시 원문 붙여 넣기가 지금 할 일이다: 그 카드를 맨 위로 올리고 '문체 분석'을 primary 로 둔다
  const blank = styleBlank(P().style);
  const next = stepLabel('arc');
  const sample = `<section class="card">
          <div class="between"><h2>예시 원문</h2><span class="small"><span id="sample-count">${S.styleSample.length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
          <label for="sample" class="small">소설 본문을 붙여 넣으세요. 원문은 작품에 저장되지 않고 고른 대표 문단만 남아요. 이 칸에 원문이 남아 있을 때 라이브러리에 저장하면 원문도 함께 보관해요. 새로고침하면 이 칸은 비어요.</label>
          <textarea id="sample" rows="16" data-local="styleSample" oninput="document.getElementById('sample-count').textContent=this.value.length.toLocaleString()" style="font-family:var(--serif);font-size:0.9375rem;line-height:1.9">${esc(S.styleSample)}</textarea>
          <div><button class="btn ${blank ? 'primary' : 'dark'}" data-action="analyzeStyle">문체 분석</button></div>
          <div class="note plain">원문은 문체 분석과 예시 문단으로만 쓰여요. 내용이나 인물은 작품에 가져오지 않아요.</div>
        </section>`;
  return `${header('2단계', stepLabel('style'), '닮고 싶은 소설 문단을 붙여 넣으면 문체 규칙을 뽑아요. 규칙과 원문 예시가 매 화 본문 생성에 함께 들어가요. 라이브러리에 저장한 문체를 그대로 가져올 수도 있고, 대화로 다듬어 갈 수도 있어요.', `${chatButton('style')}<a class="btn${blank ? '' : ' primary'}" href="${base()}/arc">${next}${josa(next, '으로', '로')}</a>`)}
    <div class="cols">
      <div class="col">
        ${blank ? sample : ''}
        ${styleLibraryCard()}
        ${learnCard()}
        ${blank ? '' : sample}
        <section class="card tight"><h2>기준 지표</h2><div class="small">본문 문체 경고는 이 값과 비교해요.</div>${baselineRows(P().style_baseline)}</section>
      </div>
      <div class="col wide">
        ${styleExampleCard()}
        <section class="card">
          <div class="between"><h2>스타일 프로필</h2><span class="small">모든 칸은 직접 고칠 수 있어요</span></div>
          ${profileFields('style')}
        </section>
      </div>
    </div>${chatPanel('style')}`;
}

// ----- 문체 라이브러리 -----

/** 날짜 'YYYY.MM.DD' 와 날짜 시각 'YYYY.MM.DD HH:mm'. 서버는 UTC 로 적으므로 이 기기의 시간대로 바꿔 보인다. */
function fmtDate(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return iso || '';
  const p2 = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}.${p2(d.getMonth() + 1)}.${p2(d.getDate())}`;
}

function fmtDateTime(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return iso || '';
  const p2 = (x) => String(x).padStart(2, '0');
  return `${fmtDate(iso)} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/** 예시 문구에 넣을 인물 이름: 이 작품의 i번째 인물. 없으면 '주인공', '조연' (특정 작품의 이름을 박아 두지 않는다) */
const exName = (i = 0) => (P() && P().characters[i] && P().characters[i].name) || ['주인공', '조연', '악역'][i] || '인물';

/** 화 범위 'a~b화' (한 화면 'a화'). 범위 기호는 물결표 하나로 쓴다. */
const epRange = (a, b) => (a === b ? `${a}화` : `${a}~${b}화`);

function viewLibrary() {
  const list = S.libs || [];
  const cards = list.map((x) => `<article class="card tight">
      <div class="between"><h3><a href="#/styles/${esc(x.id)}" style="color:inherit;text-decoration:none">${esc(x.name)}</a></h3><span class="small">${fmtDate(x.updated_at)}</span></div>
      ${x.source ? `<div class="small">${esc(x.source)}</div>` : ''}
      <div class="row">
        ${x.narration_pov ? `<span class="chip">${esc(x.narration_pov)}</span>` : ''}${x.tense ? `<span class="chip">${esc(x.tense)}</span>` : ''}
        <span class="chip">대표 문단 ${x.passages}</span><span class="chip">지킬·피할 것 ${x.rules}</span>${[['금지 표현', x.banned], ['표지', x.markers], ['장치', x.devices]].filter(([, v]) => v).map(([k, v]) => `<span class="chip">${k} ${v}</span>`).join('')}
        ${x.sample_chars ? `<span class="chip">원문 ${x.sample_chars.toLocaleString()}자</span>` : ''}
      </div>
      ${x.notes ? `<div class="small" style="white-space:pre-line">${esc(x.notes)}</div>` : ''}
      <div class="small">${x.used_by.length ? `쓰는 작품: ${x.used_by.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요'}</div>
      <div class="row"><a class="btn small" href="#/styles/${esc(x.id)}">열기</a><button class="btn small" data-action="libDuplicate" data-arg="${esc(x.id)}">복제</button><button class="btn small danger" data-action="libDelete" data-arg="${esc(x.id)}">삭제</button></div>
    </article>`).join('');
  // 비었을 때는 빈 카드의 버튼 하나만 주 버튼으로 둔다
  return `${header('Canon', '문체 라이브러리', '붙여 넣은 원문에서 뽑은 문체를 작품과 따로 모아 둬요. 작품에 적용하면 그 시점의 문체가 작품에 복사되고, 라이브러리를 고쳐도 쓰고 있는 작품은 다시 적용하기 전까지 그대로예요.', `<a class="btn" href="#/">작품 목록</a>${list.length ? '<a class="btn primary" href="#/styles/new">+ 새 문체</a>' : ''}`)}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : `<div class="card empty"><div>아직 저장한 문체가 없어요.</div><div class="small">새 문체를 만들거나, 작품의 문체 레퍼런스 화면에서 '이 문체를 라이브러리에 새로 저장'을 누르세요.</div><a class="btn primary" href="#/styles/new">+ 새 문체</a></div>`}`;
}

function baselineRows(b) {
  if (!b) return '<div class="small">원문을 넣고 저장하면 문장 길이, 대사 비율 같은 기준 지표를 재요. 본문을 쓴 뒤 문체가 얼마나 벗어났는지 비교하는 기준이 돼요.</div>';
  const pct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);
  const rows = [
    ['문장 평균 길이', `${b.sentence_len_mean.toFixed(1)}자`],
    ['문장 길이 변화폭', b.sentence_len_cv.toFixed(2)],
    ['문단 평균 길이', `${Math.round(b.paragraph_len_mean)}자`],
    ['대사 비율', pct(b.dialogue_ratio)],
    ['과거형 비율', pct(b.past_tense_ratio)],
    ['어휘 다양도', b.mattr == null ? '–' : b.mattr.toFixed(2)],
    ['쉼표 문장 비율', pct(b.comma_sentence_ratio)],
  ];
  return `<dl class="metric-list">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

function viewLibEntry() {
  const e = S.lib;
  const isNew = !e.id;
  const used = e.used_by || [];
  const others = (S.projects || []).filter((x) => !used.includes(x.name));
  const right = `<a class="btn" href="#/styles">목록으로</a>${isNew ? '' : `<button class="btn" data-action="libDuplicate" data-arg="${esc(e.id)}">복제</button><button class="btn danger" data-action="libDelete" data-arg="${esc(e.id)}">삭제</button><button class="btn" data-action="libRevert"${S.libDirty ? '' : ' disabled'}>저장 전으로</button>`}<button class="btn primary" data-action="libSave">저장</button>`;
  const apply = isNew ? '' : `<section class="card tight">
      <h2>작품에 적용</h2>
      <div class="small">${used.length ? `쓰는 작품: ${used.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요.'}</div>
      ${used.length ? '<div class="small">여기서 고친 내용은 작품의 문체 화면에서 \'라이브러리 최신 버전 가져오기\'를 눌러야 그 작품에 들어가요.</div>' : ''}
      ${(S.projects || []).length ? `<div class="row" style="flex-wrap:nowrap"><select id="lib-target" aria-label="적용할 작품" style="flex:1"><option value="">작품 고르기</option>${[...others, ...(S.projects || []).filter((x) => used.includes(x.name))].map((x) => `<option value="${esc(x.name)}">${esc(x.title || x.name)}${used.includes(x.name) ? ' (다시 적용)' : ''}</option>`).join('')}</select><button class="btn small" style="flex:none" data-action="libApplyTo">적용</button></div>` : ''}
    </section>`;
  return `${header('문체 라이브러리', isNew ? '새 문체' : e.name || '이름 없음', isNew ? '원문을 붙여 넣고 분석하거나, 프로필을 직접 채운 뒤 저장하세요.' : `만든 날 ${fmtDate(e.created_at)} · 고친 날 ${fmtDate(e.updated_at)}`, right)}
    <div class="cols lib-cols">
      <div class="col lib-left">
        <section class="card lib-o1">
          ${input('이름', 'name', { root: 'lib', placeholder: '예: 건조한 1인칭 하드보일드' })}
          ${input('출처', 'source', { root: 'lib', hint: '작가, 작품 등 메모', placeholder: '예: 직접 쓴 단편 「등대」' })}
          ${input('메모', 'notes', { root: 'lib', rows: 2, placeholder: '어떤 작품에 어울리는지 등' })}
        </section>
        <section class="card lib-o2">
          <div class="between"><h2>원문</h2><span class="small"><span id="lib-sample-count">${(e.sample || '').length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
          ${input('분석할 소설 본문', 'sample', { root: 'lib', rows: 14, style: 'font-family:var(--serif);font-size:0.9375rem;line-height:1.9', hint: '이 컴퓨터의 라이브러리 폴더에만 저장돼요' })}
          <div><button class="btn dark" data-action="libAnalyze">문체 분석</button></div>
        </section>
        <section class="card tight"><h2>기준 지표</h2>${baselineRows(e.baseline)}</section>
        ${apply}
        ${isNew ? '' : versionsCard()}
      </div>
      <section class="card col wide lib-o3">
        <div class="between"><h2>스타일 프로필</h2><span class="small">모든 칸은 직접 고칠 수 있어요</span></div>
        ${profileFields('profile', 'lib')}
      </section>
    </div>`;
}


Object.assign(actions, {
  // 문체
  async analyzeStyle() {
    if (S.styleSample.trim().length < 200) { focusEl($('#sample')); return toast('예시 원문을 200자 이상 넣어 주세요', true); }  // 서버(web.analyze_style)와 같은 기준
    const has = P().style.narration_pov || P().style.sample_passages.length;
    const l = S.styleLink || {};
    const unlink = ['same', 'changed'].includes(l.state) ? `\n라이브러리 '${l.name}' 연결도 끊겨요. 라이브러리 항목은 그대로예요.` : '';
    if ((has || unlink) && !confirm(`분석 결과로 지금 스타일 프로필을 바꿀까요? 저장하기 전에는 '변경 모두 버리기'로 되돌릴 수 있어요.${unlink}`)) return;
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      await saveIfDirty();
      const prof = await api('POST', `/projects/${enc(S.name)}/style`, { text: S.styleSample });
      P().style = prof;
      P().style_baseline = await api('POST', '/metrics', { text: S.styleSample });  // stats 가 원문 전체와 비교하도록
      P().style_id = '';  // 새로 분석한 문체는 라이브러리 항목과 연결을 끊는다
      P().style_version = 0;
      S.styleLink = { state: 'none' };  // 저장하면 서버도 같은 상태가 된다. 그 전에도 카드가 끊긴 연결을 그대로 보이지 않게
      S.dirty = true;
      toast('분석 결과를 불러왔어요. 확인하고 저장하세요.');
    });
  },
  addPassage() {
    P().style.sample_passages.push('');
    markDirty();
    render();
  },
  removePassage(i) {
    rememberRemoved(`예시 문단 ${Number(i) + 1}`, ['style.sample_passages']);
    P().style.sample_passages.splice(i, 1);
    markDirty();
    render();
  },
  addMarker() {
    P().style.markers.push({ text: '', note: '', per_1k: 0 });
    markDirty();
    render();
  },
  removeMarker(i) {
    rememberRemoved('문체 표지', ['style.markers']);
    P().style.markers.splice(i, 1);
    markDirty();
    render();
  },
  async useLibStyle() {
    const id = $('#style-pick').value;
    if (!id) return toast('적용할 문체를 고르세요', true);
    const e = (S.libs || []).find((x) => x.id === id);
    const l = S.styleLink || { state: 'none' };
    const lost = l.state === 'same' ? '' : '\n지금 문체는 라이브러리에 없어서 되돌릴 수 없어요. 남겨 두려면 취소하고 \'이 문체를 라이브러리에 새로 저장\'을 먼저 누르세요.';
    if (!confirm(`'${e ? e.name : id}' 문체를 이 작품에 적용할까요? 지금 작품의 스타일 프로필은 바뀌어요.${lost}`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: id });
      await loadStyleLink();
      toast('라이브러리 문체를 적용했어요');
    });
  },
  async keepStyle() {
    const bare = S.styleSample.trim() ? '' : '\n(이 화면에 붙여 넣은 원문이 없어 원문 없이 저장돼요)';
    const l = S.styleLink || {};
    const moved = ['same', 'changed'].includes(l.state) ? `\n이 작품은 새 항목에 연결되고, 지금 연결된 '${l.name}' 연결은 끊겨요. '${l.name}' 항목은 그대로 남아요.` : '';
    const name = prompt(`라이브러리에 저장할 문체 이름${bare}${moved}`, `${P().meta.title || S.name} 문체`);
    if (name === null) return;
    await run('라이브러리에 저장하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { name: name.trim(), sample: S.styleSample });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리에 '${r.entry.name}' 로 저장했어요`);
    });
  },
  async pushStyle() {
    const l = S.styleLink || {};
    const users = ((S.libs || []).find((x) => x.id === l.id) || {}).used_by || [];
    const others = users.filter((n) => n !== S.name);
    const warn = (others.length ? `\n다른 작품(${others.join(', ')})은 다시 적용하기 전까지 바뀌지 않아요.` : '')
      + ((l.theirs || []).length ? `\n라이브러리 ${l.version}번 버전에서 바뀐 칸(${l.theirs.map((c) => c.label).join(', ')})은 이 작품 값으로 덮여요.` : '');
    const note = prompt(`이 작품의 문체를 라이브러리 '${l.name}' 의 새 버전으로 올려요. 예전 버전은 남아 있어 되돌릴 수 있어요.${warn}\n\n버전 메모 (비워도 돼요)`, '');
    if (note === null) return;
    await run('라이브러리에 올리는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { update: true, note: note.trim() });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리 '${r.entry.name}' 을 ${r.entry.version}번 버전으로 올렸어요`);
    });
  },
  async pullStyle() {
    const l = S.styleLink || {};
    const lost = (l.mine || []).length || !l.base_known ? ' 작품에서 고친 내용은 사라져요.' : '';
    if (!confirm(`이 작품의 문체를 라이브러리 '${l.name}' ${l.version}번 버전으로 바꿀까요?${lost}`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: l.id });
      await loadStyleLink();
      toast(`라이브러리 '${l.name}' ${l.version}번 버전을 가져왔어요`);
    });
  },

  // 문체 라이브러리
  async libAnalyze() {
    if ((S.lib.sample || '').trim().length < 200) return toast('원문을 200자 이상 넣어 주세요', true);
    const has = S.lib.profile.narration_pov || S.lib.profile.sample_passages.length;
    if (has && !confirm('분석 결과로 지금 프로필을 바꿀까요? 저장 전까지는 되돌릴 수 있어요.')) return;
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      S.lib.profile = await api('POST', '/styles/analyze', { text: S.lib.sample });
      S.libDirty = true;
      toast('분석 결과를 불러왔어요. 확인하고 저장하세요.');
    });
  },
  async libSave() {
    if (!S.lib.name.trim()) return toast('문체 이름을 입력하세요', true);
    const body = { name: S.lib.name, source: S.lib.source, notes: S.lib.notes, sample: S.lib.sample, profile: S.lib.profile, note: S.libNote || '' };
    await run('저장 중', async () => {
      const isNew = !S.lib.id;
      S.lib = isNew ? await api('POST', '/styles', body) : await api('PUT', `/styles/${S.lib.id}`, body);
      S.lib.used_by = S.lib.used_by || [];
      S.libDirty = false;
      S.libNote = '';
      await libVersionsLoad();
      toast(isNew ? '라이브러리에 저장했어요' : `저장했어요 (지금 ${S.lib.version}번 버전)`);
      if (isNew) location.hash = `#/styles/${S.lib.id}`;
    });
  },
  async libRevert() {
    if (!S.libDirty) return;
    if (!confirm(S.lib.id ? '저장하지 않은 변경을 버리고 저장된 문체로 되돌릴까요?' : '적은 내용을 모두 지우고 빈 문체로 돌아갈까요?')) return;
    if (!S.lib.id) {  // 아직 저장하지 않은 새 문체: 돌아갈 저장본이 없다
      S.lib = { name: '', source: '', notes: '', sample: '', profile: emptyProfile(), used_by: [] };
      S.libDirty = false;
      render();
      return;
    }
    await run('불러오는 중', async () => {
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      S.libDirty = false;
    });
  },
  async libDuplicate(id) {
    if (S.libDirty && !confirm('저장하지 않은 변경이 있어요. 저장한 뒤 그 버전으로 복제할까요?')) return;
    if (S.libDirty) {
      await actions.libSave();
      if (S.libDirty) return;  // 저장하지 못했다 (토스트가 이유를 알린다)
    }
    await run('복제하는 중', async () => {
      const e = await api('POST', `/styles/${id}/duplicate`);
      S.libDirty = false;
      toast(`'${e.name}' 을 만들었어요. 구별하기 쉽게 이름을 바꿔 보세요`);
      location.hash = `#/styles/${e.id}`;
      // 새 항목 화면이 그려지면 이름 칸을 골라 둔다 (화면 이동은 제목으로 포커스를 옮기므로 그 뒤에)
      const until = Date.now() + 5000;
      const pick = () => {
        const el = $('#f-name');
        if (el && el.value === e.name) { el.focus(); el.select(); } else if (Date.now() < until) setTimeout(pick, 100);
      };
      setTimeout(pick, 100);
    });
  },
  async libDelete(id) {
    const e = (S.libs || []).find((x) => x.id === id) || S.lib || {};
    const used = e.used_by || [];
    const note = used.length ? `\n이 문체를 쓰는 작품(${used.join(', ')})은 복사해 둔 문체를 그대로 써요.` : '';
    if (!confirm(`'${e.name}' 문체를 라이브러리에서 지울까요? 되돌릴 수 없어요.${note}`)) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/styles/${id}`);
      S.libDirty = false;
      S.libs = await api('GET', '/styles');
      toast('지웠어요');
      if (S.route[0] === 'styles' && S.route[1]) location.hash = '#/styles';
    });
  },
  async libApplyTo() {
    const name = $('#lib-target').value;
    if (!name) return toast('적용할 작품을 고르세요', true);
    if (S.libDirty) return toast('먼저 저장하세요. 저장된 문체가 작품에 복사돼요.', true);
    if (!confirm(`'${S.lib.name}' 문체를 '${name}' 작품에 적용할까요? 그 작품의 스타일 프로필은 바뀌어요.\n그 작품의 지금 문체를 라이브러리에 저장해 두지 않았다면 되돌릴 수 없어요.`)) return;
    await run('적용하는 중', async () => {
      await api('POST', `/projects/${enc(name)}/style/apply`, { style_id: S.lib.id });
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      toast(`'${name}' 에 적용했어요`);
    });
  },
  libAddPassage() {
    S.lib.profile.sample_passages.push('');
    S.libDirty = true;
    render();
  },
  libRemovePassage(i) {
    S.lib.profile.sample_passages.splice(i, 1);
    S.libDirty = true;
    render();
  },
  libAddMarker() {
    S.lib.profile.markers.push({ text: '', note: '', per_1k: 0 });
    S.libDirty = true;
    render();
  },
  libRemoveMarker(i) {
    S.lib.profile.markers.splice(i, 1);
    S.libDirty = true;
    render();
  },
});
