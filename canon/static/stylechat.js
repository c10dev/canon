/* 대화로 문체 다듬기와 '이 문체로 쓴 예시' (작품 문체 화면). app.js 의 S, actions, api, run, render 와
   chat.js 의 대화 패널(topic 'style'), passage.js 의 wordDiff 를 그대로 쓴다.
   작가가 말하면 AI가 스타일 프로필에서 바꿀 칸과 시험 문단을 내고, 고른 칸만 작품 문체에 들어간다.
   서버는 pipeline.revise_style · apply_style_chat · undo_style_chat · style_example, 엔드포인트는 web.py 3-1 · 2-2. */
'use strict';

Object.assign(S, {
  styleRefEp: '',   // 문체 대화에서 참고할 화 (본문이 있는 화)
  styleExScene: '', // 예시 칸: 바라는 장면
  styleExEp: '',    // 예시 칸: 고쳐 쓸 화
});

// 칸 순서와 이름 (pipeline.STYLE_KEYS, prompts.STYLE_KEY_LABELS 와 같다)
const STYLE_KEYS = [
  ['narration_pov', '시점'], ['tense', '시제'], ['sentence_rhythm', '문장 리듬'], ['description_density', '묘사 밀도'],
  ['dialogue_ratio', '대사 비율'], ['dialogue_style', '대사 방식'], ['inner_monologue', '내면 독백'], ['pacing', '전개 속도'],
  ['scene_transition', '장면 전환'], ['vocabulary', '어휘'], ['dos', '지킬 것'], ['donts', '피할 것'],
  ['banned_phrases', '금지 표현'], ['markers', '문체 표지'], ['devices', '가끔 쓰는 장치'],
];
const STYLE_LABEL = Object.fromEntries(STYLE_KEYS);
const STYLE_LISTS = ['dos', 'donts', 'banned_phrases'];

/** 본문이 있는 화 번호들 (참고할 화로 고를 수 있다). */
const textEps = () => P().episodes.filter((e) => (e.text || '').trim()).map((e) => e.plot.number).sort((a, b) => a - b);

function epSelect(local, value, label) {
  const eps = textEps();
  if (!eps.length) return '';
  return `<select data-local="${local}" aria-label="${label}" style="width:auto;min-width:120px">
    <option value="">${local === 'styleRefEp' ? '참고할 화 없음' : '새 장면으로'}</option>
    ${eps.map((n) => `<option value="${n}"${String(n) === String(value) ? ' selected' : ''}>${n}화${local === 'styleRefEp' ? ' 참고' : ' 고쳐 쓰기'}</option>`).join('')}</select>`;
}

CHAT_TOPICS.style = {
  title: '대화로 다듬기',
  intro: '문체를 말로 고쳐요. AI가 스타일 프로필에서 바꿀 칸을 지금 값과 나란히 보여 주고, 바뀐 문체로 쓴 시험 문단도 함께 내요. 고른 칸만 이 작품 문체에 들어가고, 적용한 뒤에도 취소할 수 있어요. 아래에서 참고할 화를 고르면 그 화를 보고 판단하고 한 대목을 새 문체로 고쳐 써 봐요.',
  examples: ['대사를 더 짧게 끊어 줘', '묘사가 너무 많아, 반으로 줄이고 싶어', '내면 독백을 1인칭 반말로', '이 문체에 어울리는 가끔 쓰는 장치 하나 추천해 줘'],
  placeholder: '예: 대사를 더 짧게 끊어 줘',
  clearAsk: '이 작품의 문체 대화 기록을 지울까요? 적용한 문체는 그대로예요. 기록을 지우면 적용 취소는 할 수 없어요.',
  body: (text) => ({ message: text, episode: Number(S.styleRefEp) || 0 }),
  userMsg: (m) => `${m.where ? `<span class="msg-quote">${esc(m.where)}</span>` : ''}${esc(m.text)}`,
  proposal: styleProposal,
  inputExtra: () => {
    const sel = epSelect('styleRefEp', S.styleRefEp, '참고할 화');
    return sel ? `<div class="chat-scope between"><span class="small">본문을 보고 말하려면</span>${sel}</div>` : '';
  },
};

/** 목록 칸 한 줄 (library._item 과 같은 모양): 표지는 '글자 (쓰임)', 장치는 '이름 (상황, N화에 한 번, 글자)'. */
function styleItem(x) {
  if (typeof x === 'string') return x;
  if (x.cues) {
    const info = [x.when, x.every ? `${x.every}화에 한 번` : '', (x.cues || []).join('/')].filter(Boolean);
    return x.name + (info.length ? ` (${info.join(', ')})` : '');
  }
  return x.text + (x.note ? ` (${x.note})` : '');
}

function styleEditValue(e) {
  if (STYLE_LISTS.includes(e.key)) return e.items;
  if (e.key === 'markers') return e.markers;
  if (e.key === 'devices') return e.devices;
  return e.text;
}

/** 한 칸의 바뀐 내용. 글 칸은 지금 → 바꾸면, 목록 칸은 빠지는 것과 더해지는 것. */
function styleEditDiff(e, before) {
  const after = styleEditValue(e);
  if (!Array.isArray(after)) return diffField(STYLE_LABEL[e.key], e.key, before || '', after);
  const out = diffField(STYLE_LABEL[e.key], e.key, (before || []).map(styleItem), after.map(styleItem));
  return out || '<div class="small">순서나 빈도만 바뀌어요.</div>';
}

/** 시험 문단 · 예시 글. 원래 대목이 있으면 접어 두고 비교해 볼 수 있게 한다. */
function sampleBlock(text, source, n) {
  return `<div class="pdiff style-sample">${esc(text)}</div>
    ${source ? `<details><summary class="small">${n ? `${n}화 ` : ''}원래 대목과 비교</summary><div class="pdiff small-diff">${wordDiff(source, text)}</div></details>` : ''}`;
}

function linkPushBox(id) {
  const l = S.styleLink;
  if (!l || !['same', 'changed'].includes(l.state)) return '';
  const theirs = l.theirs || [];
  return `<label class="check-row"><input type="checkbox" id="${id}"${l.state === 'same' && !theirs.length ? ' checked' : ''}><span>라이브러리 '${esc(l.name)}' 에도 새 버전으로 올리기<br><span class="small">다른 작품은 다시 적용하기 전까지 그대로예요${theirs.length ? `. 라이브러리가 ${l.version}번 버전으로 더 새로워서, 올리면 그쪽에서 바뀐 칸(${theirs.map((c) => esc(c.label)).join(', ')})이 덮여요` : ''}</span></span></label>`;
}

function styleProposal(m, i) {
  const rev = m.style;
  const open = !m.outcome;
  const asked = chatMessages('style')[i - 1];
  const ref = asked && asked.episode;
  // 적용한 변경안은 적용하기 전 문체와, 아직 고르지 않은 것은 지금 문체와 비교한다
  const base = m.outcome === 'applied' && m.style_before ? m.style_before : P().style;
  const rows = rev.edits.map((e) => {
    const k = pickKey(i, e.key);
    if (open && S.chatPicks[k] === undefined) S.chatPicks[k] = true;
    const box = open ? `<input type="checkbox" data-chat-pick="${k}"${S.chatPicks[k] ? ' checked' : ''}>` : '';
    const done = m.outcome === 'applied' && m.applied.includes(e.key) ? ' <span class="chip finalized">적용함</span>' : '';
    return `<div class="prop-part"><label class="prop-head">${box}<strong>${esc(STYLE_LABEL[e.key] || e.key)}</strong>${done}</label>
      ${e.why ? `<div class="small">${esc(e.why)}</div>` : ''}<div class="diff">${styleEditDiff(e, base[e.key])}</div></div>`;
  }).join('');
  const preview = rev.preview ? `<div class="prop-part"><strong>시험 문단 <span class="small" style="font-weight:400">바뀐 문체로 쓴 글이에요. 본문에는 들어가지 않아요</span></strong>
    ${sampleBlock(rev.preview, rev.preview_source, ref)}</div>` : '';
  if (m.outcome === 'applied') {
    const chip = `<span class="chip finalized">적용함 · ${m.applied.map((x) => STYLE_LABEL[x] || x).join(', ')}</span>`;
    return `<details class="proposal done"><summary>${chip} 변경안 다시 보기</summary>${rows}${preview}
      ${linkPushBox(`style-undo-push-${i}`)}
      <div class="row proposal-actions"><button type="button" class="btn small" data-action="styleChatUndo" data-arg="${i}">적용 취소</button></div></details>`;
  }
  if (m.outcome === 'dismissed') {
    return `<details class="proposal done"><summary><span class="chip">버림</span> 변경안 다시 보기</summary>${rows}${preview}
      <div class="row proposal-actions"><button type="button" class="btn small" data-action="chatReopen" data-arg="${i}">다시 검토</button></div></details>`;
  }
  const sum = rev.edits.map((e) => STYLE_LABEL[e.key] || e.key).join(' · ');
  return `<div class="proposal"><div class="prop-sum"><strong>${esc(sum)}</strong></div>${rows}${preview}
    ${linkPushBox(`style-push-${i}`)}
    ${proposalActions(['chatDismiss', i], ['styleChatApply', i], '고른 칸 적용')}</div>`;
}

// ----- 이 문체로 쓴 예시 (문체 화면 카드) -----

/** 예시를 쓴 뒤 문체가 바뀌었는지. 서버가 저장한 같은 모양끼리 비교한다. */
const exampleStale = (ex) => JSON.stringify(ex.profile) !== JSON.stringify(P().style);

function styleExampleCard() {
  const ex = P().style_example;
  const blank = styleBlank(P().style);
  const sel = epSelect('styleExEp', S.styleExEp, '고쳐 쓸 화');
  const how = ex ? [ex.by === 'chat' ? '대화의 시험 문단' : '', ex.episode ? `${ex.episode}화 한 대목을 고쳐 씀` : '', ex.scene ? `장면: ${ex.scene}` : '', fmtDateTime(ex.at)].filter(Boolean).join(' · ') : '';
  const body = ex ? `${exampleStale(ex) ? '<div class="note warn">이 예시를 쓴 뒤 문체가 바뀌었어요. 다시 쓰면 지금 문체로 써요.</div>' : ''}
      ${sampleBlock(ex.text, ex.source, ex.episode)}
      <div class="between"><span class="small">${esc(how)} · ${ex.text.length.toLocaleString()}자</span><button type="button" class="btn small" data-action="styleExampleClear">지우기</button></div>`
    : `<div class="small">${blank ? '문체를 만든 뒤 예시를 써 볼 수 있어요.' : '아직 예시가 없어요. 지금 문체로 짧은 장면을 써서 실제로 어떻게 읽히는지 보여 줘요.'}</div>`;
  return `<section class="card pf-sec" id="pf-example" tabindex="-1">
      <div class="pf-head"><h2>이 문체로 쓴 예시</h2><span class="small">본문에는 들어가지 않아요</span></div>
      ${body}
      <div class="row sty-ex-row">
        <input type="text" data-local="styleExScene" value="${esc(S.styleExScene || '')}" aria-label="바라는 장면" placeholder="바라는 장면 (비우면 AI가 골라요), 예: 비 오는 날 두 사람이 다툼" style="flex:1 1 240px;min-width:0"${blank ? ' disabled' : ''}>
        ${sel}
        <button type="button" class="btn small" style="flex:none" data-action="styleExampleWrite"${blank ? ' disabled' : ''}>${ex ? '다시 쓰기' : '예시 쓰기'}</button>
      </div>
    </section>`;
}

Object.assign(actions, {
  async styleChatApply(i) {
    i = Number(i);
    const m = chatMessages('style')[i];
    const fields = m.style.edits.map((e) => e.key).filter((k) => {
      const el = document.querySelector(`[data-chat-pick="${pickKey(i, k)}"]`);
      return !!(el && el.checked);
    });
    if (!fields.length) return toast('적용할 칸을 고르세요', true);
    const push = !!($(`#style-push-${i}`) && $(`#style-push-${i}`).checked);
    await run('문체에 적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/style/${i}/apply`, { fields, push });
      if (push) S.libs = await api('GET', '/styles').catch(() => S.libs);
      await loadStyleLink();
      toast(`적용했어요: ${fields.map((k) => STYLE_LABEL[k]).join(', ')}${push && S.styleLink && S.styleLink.version ? ` · 라이브러리 ${S.styleLink.version}번 버전` : ''}. 다음 화부터 이 문체로 써요`);
    });
  },
  async styleChatUndo(i) {
    i = Number(i);
    const push = !!($(`#style-undo-push-${i}`) && $(`#style-undo-push-${i}`).checked);
    if (!confirm(`이 변경안 적용을 취소할까요? 적용한 칸을 적용하기 전으로 돌려요. 그 뒤에 다시 고친 칸은 그대로 둬요.${S.dirty ? ' 저장하지 않은 다른 변경도 함께 저장해요.' : ''}`)) return;
    await run('적용을 취소하는 중', async () => {
      await saveIfDirty();
      const res = await api('POST', `/projects/${enc(S.name)}/chat/style/${i}/undo`, { push });
      S.project = res.project;
      if (push) S.libs = await api('GET', '/styles').catch(() => S.libs);
      await loadStyleLink();
      const label = (xs) => xs.map((k) => STYLE_LABEL[k] || k).join(', ');
      toast(res.restored.length ? `되돌렸어요: ${label(res.restored)}${res.kept.length ? ` · 그 뒤에 고친 칸은 그대로 뒀어요: ${label(res.kept)}` : ''}`
        : `그 뒤에 모두 다시 고쳐서 되돌린 칸이 없어요: ${label(res.kept)}`, !res.restored.length);
    });
  },
  async styleExampleWrite() {
    await run('지금 문체로 예시를 쓰는 중… (최대 1분)', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/example`, { scene: S.styleExScene || '', episode: Number(S.styleExEp) || 0 });
      toast('예시를 썼어요');
    });
  },
  async styleExampleClear() {
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/style/example`);
    });
  },
});
