/* 대화로 다듬기 패널. app.js 의 S, actions, api, render 를 그대로 쓴다.
   작가가 말하면 AI가 답과 변경안을 내고, 변경안은 바뀌는 칸만 보여 준다. 작가가 고른 부분만 반영한다.
   기승전결 · 플롯 화면(topic 'plot')과 집필 화면의 본문 부분 수정(topic 'text:<화>', passage.js)에 붙어 있다.
   다른 화면에 붙일 때는 CHAT_TOPICS 에 항목을 더하고 서버 web.py 의 _chat 과 변경안 반영 함수를 함께 늘린다.
   주제마다 body(요청 내용), proposal(변경안 그리기), userMsg, inputExtra 를 바꿔 끼울 수 있다. */
'use strict';

const CHAT_TOPICS = {
  plot: {
    title: '대화로 다듬기',
    get intro() {
      if (!serial()) return '구조나 플롯이 마음에 들지 않으면 말로 알려 주세요. 구조가 없으면 대화로 함께 짤 수도 있어요. AI가 바꿀 부분을 변경안으로 보여 주고, 고른 것만 적용해요. 본문이 있는 화는 바뀌지 않아요.';
      return S.selArc === 'next'
        ? '다음 아크를 말로 함께 짜요. 받은 안은 아래 초안에 들어가고, 초안을 두고 계속 고칠 수 있어요. 작품에는 \'이 아크 적용\'을 눌러야 들어가요.'
        : '고른 아크의 칸과 구간, 화별 플롯, 부 구성을 말로 고쳐요. 아크 줄에서 + 다음 아크를 고르면 다음 아크를 대화로 짤 수 있어요. 본문이 있는 화는 바뀌지 않아요.';
    },
    get examples() {
      if (!serial()) return ['3화 전개가 너무 빨라', '결말을 비극으로 바꿔 줘', '승 구간을 한 화 늘려 줘', '주인공이 더 늦게 진실을 알게 해 줘'];
      return S.selArc === 'next'
        ? ['15화짜리로, 라이벌과 처음 손잡는 아크', '무대를 학교 밖으로 넓혀 줘', '갈등을 더 개인적인 걸로']
        : ['이 아크 갈등을 더 개인적인 걸로', '아크를 3화 늘려 줘', '승 구간 전개가 느려', '2부 목표를 복수에서 구원으로'];
    },
    placeholder: '예: 3화 전개가 너무 빨라',
    clearAsk: '이 작품의 대화 기록을 지울까요? 반영한 구조와 플롯은 그대로예요.',
    body: (text) => ({ message: text, ...plotScope(), mode: S.chatOptions ? 'options' : '' }),
    userMsg: (m) => `${m.where ? `<span class="msg-quote">${esc(m.where)}</span>` : ''}${m.mode === 'options' ? '<span class="chip">방향 여러 안</span> ' : ''}${esc(m.text)}`,
    inputExtra: () => plotScopeBar(),
  },
};

Object.assign(S, {
  chatOpen: (() => { try { return localStorage.getItem('canon.chat') === '1'; } catch { return false; } })(),
  chatDraft: '',
  chatPending: null,  // 보내는 중인 메시지
  chatPicks: {},      // '메시지번호:acts' 또는 '메시지번호:화' → 반영할지
  chatScroll: true,   // 다음 그리기 때 맨 아래로 내릴지
  chatScrollTop: 0,   // 화면을 다시 그려도 읽던 자리를 지킨다
  chatTopic: 'plot',  // 지금 열린 패널의 주제 ('plot' 또는 'text:<화>')
  chatOptions: false, // 플롯 대화: 변경안 대신 방향 여러 안을 받는다
});

const PLOT_FIELDS = [
  ['title', '제목'], ['opening', '여는 장면'], ['summary', '요약'], ['events', '사건 순서'], ['characters', '등장 인물'],
  ['emotional_shift', '감정 변화'], ['ending_hook', '엔딩 훅'], ['foreshadow_plant', '심을 복선'], ['foreshadow_payoff', '회수할 복선'],
  ['storyline', '이야기 줄기'], ['threads', '끼어드는 줄기'], ['pov', '시점 인물'], ['pov_mode', '서술 방식'],
];
const ACT_FIELDS = [['goal', '구간 목표'], ['key_turn', '전환점'], ['pov', '서술 시점']];
const ARC_FIELDS = [['title', '제목'], ['goal', '아크 목표'], ['conflict', '갈등'], ['payoff', '보상 (사이다)'], ['cast', '주요 인물'], ['payoffs', '회수할 복선'], ['pov', '서술 시점']];
const PART_FIELDS = [['title', '제목'], ['goal', '부 목표'], ['key_turn', '전환점'], ['arc_ideas', '아크 후보']];
const clone = (x) => JSON.parse(JSON.stringify(x));
const LOCKED_STATUS = ['written', 'finalized'];

/** 손가락이 주 입력인 기기(휴대폰 · 태블릿). 하드웨어 키보드를 붙인 태블릿도 여기에 들지만 버튼으로 보낼 수 있다. */
const touchFirst = () => window.matchMedia('(pointer: coarse)').matches;

function chatMessages(topic) {
  const c = (P().chats || []).find((x) => x.topic === topic);
  return c ? c.messages : [];
}

/** 'text:3' 처럼 화 번호가 붙은 주제는 앞부분('text')의 설정을 쓴다. */
function chatConf(topic) {
  return CHAT_TOPICS[String(topic).split(':')[0]];
}

// ----- 플롯 대화의 대상: 화면에서 고른 아크(장편) · 다음 아크 초안, 연 구간과 화 (서버 pipeline.chat_target · chat_where) -----

function plotTargetArc(target) {
  const m = /^arc:(\d+)$/.exec(target || '');
  return m ? P().story_arcs.find((a) => a.number === Number(m[1])) || null : null;
}

/** 서버로 보내는 대상. 장편은 아크 줄에서 고른 아크나 '다음 아크', 단편은 작품 전체. 다음 아크면 화면의 초안을 함께 보낸다. */
function plotScope() {
  const s = { target: '', act: '', episode: Number(S.selEp) || 0, draft: null };
  let acts = P().arc;
  if (serial()) {
    if (S.selArc === 'next') {
      s.target = 'next';
      s.draft = S.arcDraft || null;
      acts = [];
    } else if (S.selArc != null) {
      s.target = `arc:${S.selArc}`;
      acts = (plotTargetArc(s.target) || {}).acts || [];
    }
  }
  if (S.selAct != null && acts[S.selAct]) s.act = acts[S.selAct].name;
  return s;
}

function scopeText() {
  const s = plotScope();
  const a = plotTargetArc(s.target);
  const out = [];
  if (a) out.push(`아크 ${a.number}${a.title ? ` ${a.title}` : ''}`);
  else if (s.target === 'next') out.push(S.arcDraft ? `다음 아크 초안${S.arcDraft.arc.title ? ` (${S.arcDraft.arc.title})` : ''}` : `다음 아크 기획 (${plannedUntil() + 1}화부터)`);
  else out.push(serial() ? '본문이 없는 첫 아크' : '작품 전체');
  if (s.act) out.push(`${s.act} 구간`);
  if (s.episode) out.push(`${s.episode}화`);
  return out.join(' · ');
}

function plotScopeBar() {
  return `<div class="chat-scope between">
    <span class="small">대상 · <strong>${esc(scopeText())}</strong></span>
    <button type="button" class="btn small${S.chatOptions ? ' on' : ''}" data-action="toggleChatOptions" aria-pressed="${S.chatOptions}" title="변경안 대신 서로 다른 방향 2~3개를 먼저 받아 고르거나 섞어요">방향 여러 안</button>
  </div>`;
}

/** 변경안이 비교할 지금 값. 기록에 대상이 없는 옛 변경안(장편)은 본문이 없는 첫 아크로 본다 (pipeline.focus_arc). */
function revBase(m) {
  if (m.target === 'next') return { arc: S.arcDraft ? S.arcDraft.arc : null, acts: S.arcDraft ? S.arcDraft.arc.acts : [], next: true };
  if (!serial()) return { arc: null, acts: P().arc };
  const locked = (n) => { const e = ep(n); return e && LOCKED_STATUS.includes(e.status); };
  const arcs = [...P().story_arcs].sort((x, y) => x.start_ep - y.start_ep);
  const a = m.target ? plotTargetArc(m.target)
    : arcs.find((x) => { for (let n = x.start_ep; n <= x.end_ep; n++) if (!locked(n)) return true; return false; }) || arcs[arcs.length - 1];
  return { arc: a || null, acts: a ? a.acts : [], missing: !!m.target && !a };
}

function chatAppliedLabel(m, x) {
  return { acts: '구조', arc: m.target === 'next' ? '다음 아크 초안' : '아크 칸', parts: '부 구성' }[x] || `${x}화`;
}

/** 다음 아크 변경안을 화면의 초안(S.arcDraft) 모양으로. 시작 화와 번호는 지금 기획한 끝에 맞춘다. */
function draftFromRev(m) {
  const r = m.revision;
  const { end_ep, ...fields } = clone(r.arc);
  return { arc: { ...fields, number: P().story_arcs.length + 1, start_ep: plannedUntil() + 1, end_ep, summary: '', acts: clone(r.acts) },
    new_characters: clone(r.new_characters || []), reply: m.text };
}

function nextStale(m) {
  return m.target === 'next' && m.revision.acts.length > 0 && m.revision.acts[0].start_ep !== plannedUntil() + 1;
}

function chatButton(topic = 'plot') {
  return `<button class="btn${S.chatOpen ? ' on' : ''}" data-action="toggleChat" aria-pressed="${S.chatOpen}">${chatConf(topic).title}</button>`;
}

// ----- 변경안 비교 -----

function fieldText(key, v) {
  if (key === 'storyline') return v ? lineName(v) : '메인';
  if (!Array.isArray(v)) return String(v ?? '');
  return (key === 'characters' || key === 'cast' ? v.map(charName) : key === 'threads' ? v.map(lineName) : v).join(', ');
}

function lineName(id) {
  const s = (P().storylines || []).find((x) => x.id === id);
  return s ? s.title || id : id;
}

/** 한 칸의 바뀐 내용. 목록은 빠진 것과 더해진 것을, 글은 이전과 새 글을 보여 준다. */
function diffField(label, key, before, after) {
  if (JSON.stringify(before ?? '') === JSON.stringify(after ?? '')) return '';
  if (Array.isArray(after) && Array.isArray(before) && key !== 'events') {
    const gone = before.filter((x) => !after.includes(x));
    const added = after.filter((x) => !before.includes(x));
    if (!gone.length && !added.length) return '';
    const name = (x) => esc(key === 'characters' || key === 'cast' ? charName(x) : key === 'threads' ? lineName(x) : x);
    return `<div class="diff-row"><span class="act-label">${label}</span>
      ${gone.map((x) => `<del>${name(x)}</del>`).join('')}${added.map((x) => `<ins>${name(x)}</ins>`).join('')}</div>`;
  }
  if (key === 'events') {
    return `<div class="diff-row"><span class="act-label">${label}</span>
      ${before && before.length ? `<del><ol>${before.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></del>` : ''}
      <ins><ol>${after.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></ins></div>`;
  }
  const b = fieldText(key, before);
  return `<div class="diff-row"><span class="act-label">${label}</span>${b ? `<del>${esc(b)}</del>` : ''}<ins>${esc(fieldText(key, after)) || '(비움)'}</ins></div>`;
}

function actsDiff(rev, base = P().arc) {
  const rows = rev.acts.map((a) => {
    const cur = base.find((x) => x.name === a.name) || {};
    const range = cur.start_ep === a.start_ep && cur.end_ep === a.end_ep ? ''
      : `<div class="diff-row"><span class="act-label">범위</span>${cur.name ? `<del>${cur.start_ep}~${cur.end_ep}화</del>` : ''}<ins>${a.start_ep}~${a.end_ep}화</ins></div>`;
    const body = range + ACT_FIELDS.map(([k, l]) => diffField(l, k, cur[k], a[k])).join('');
    return body ? `<div class="diff-act"><span class="chip ${actClass(a.name)}">${a.name}</span>${body}</div>` : '';
  }).join('');
  const total = rev.total_episodes ? `<div class="diff-row"><span class="act-label">총 화수</span><del>${P().meta.target_episodes}화</del><ins>${rev.total_episodes}화</ins></div>` : '';
  return total + rows;
}

function arcDiff(rev, cur, start) {
  const e = rev.arc;
  const range = e.end_ep && (!cur || cur.end_ep !== e.end_ep)
    ? `<div class="diff-row"><span class="act-label">범위</span>${cur ? `<del>${cur.start_ep}~${cur.end_ep}화</del>` : ''}<ins>${cur ? cur.start_ep : start}~${e.end_ep}화</ins></div>` : '';
  return range + ARC_FIELDS.map(([k, l]) => diffField(l, k, cur ? cur[k] : (Array.isArray(e[k]) ? [] : ''), e[k])).join('');
}

function partsDiff(rev) {
  const now = P().parts;
  const rows = rev.parts.map((x) => {
    const cur = now.find((y) => y.number === x.number);
    const range = cur && cur.start_ep === x.start_ep && cur.end_ep === x.end_ep ? ''
      : `<div class="diff-row"><span class="act-label">범위</span>${cur ? `<del>${cur.start_ep}~${cur.end_ep}화</del>` : ''}<ins>${x.start_ep}~${x.end_ep}화</ins></div>`;
    const body = range + PART_FIELDS.map(([k, l]) => diffField(l, k, cur ? cur[k] : (k === 'arc_ideas' ? [] : ''), x[k])).join('');
    return body ? `<div class="diff-act"><span class="chip">${x.number}부</span>${body}</div>` : '';
  }).join('');
  const gone = now.filter((y) => !rev.parts.some((x) => x.number === y.number));
  return rows + (gone.length ? `<div class="diff-row"><span class="act-label">없어지는 부</span>${gone.map((y) => `<del>${y.number}부 ${esc(y.title)}</del>`).join('')}</div>` : '');
}

/** 방향 여러 안: 고르면 그 방향으로, 여럿 고르면 섞어서 변경안을 청한다 (보내는 말은 그대로 대화에 남는다). */
function optionsCard(m, i) {
  const busy = S.chatPending ? ' disabled' : '';
  const cards = m.revision.options.map((o, k) => `<div class="prop-part">
    <label class="prop-head"><input type="checkbox" data-chat-pick="${pickKey(i, `opt${k}`)}"${S.chatPicks[pickKey(i, `opt${k}`)] ? ' checked' : ''}><strong>${k + 1}안 · ${esc(o.title)}</strong></label>
    <div>${esc(o.idea)}</div>
    ${o.changes.length ? `<ul class="small option-changes">${o.changes.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${o.tradeoff ? `<div class="small">얻는 것과 잃는 것 · ${esc(o.tradeoff)}</div>` : ''}
    <div class="row"><button type="button" class="btn small" data-action="chatDirection" data-arg="${i}|${k}"${busy}>이 방향으로 변경안</button></div>
  </div>`).join('');
  return `<div class="proposal">${cards}
    <div class="row proposal-actions"><button type="button" class="btn small primary" data-action="chatMixDirections" data-arg="${i}"${busy}>고른 안 섞어서 변경안</button>
    <span class="small">입력칸에 적어 둔 말이 있으면 함께 보내요.</span></div></div>`;
}

function plotDiff(plot) {
  const cur = ep(plot.number);
  if (!cur) return PLOT_FIELDS.map(([k, l]) => diffField(l, k, k === 'events' ? [] : (Array.isArray(plot[k]) ? [] : ''), plot[k])).join('');
  return PLOT_FIELDS.map(([k, l]) => diffField(l, k, cur.plot[k], plot[k])).join('') || '<div class="small">지금 플롯과 같아요.</div>';
}

function pickKey(i, part) {
  return `${i}:${part}`;
}

/** 처음 보는 변경안은 구조와 초안 화를 고른 채로, 확정된 화는 고르지 않은 채로 시작한다. */
function initPicks(topic) {
  chatMessages(topic).forEach((m, i) => {
    if (!m.revision || m.outcome) return;
    if (m.revision.acts.length && S.chatPicks[pickKey(i, 'acts')] === undefined) S.chatPicks[pickKey(i, 'acts')] = true;
    if (m.revision.arc && m.revision.arc.title && S.chatPicks[pickKey(i, 'arc')] === undefined) S.chatPicks[pickKey(i, 'arc')] = true;
    if ((m.revision.parts || []).length && S.chatPicks[pickKey(i, 'parts')] === undefined) S.chatPicks[pickKey(i, 'parts')] = true;
    m.revision.episodes.forEach((e) => {
      const k = pickKey(i, e.number);
      const cur = ep(e.number);
      if (S.chatPicks[k] === undefined) S.chatPicks[k] = !cur || cur.status === 'draft';
    });
  });
}

function proposal(m, i) {
  const rev = m.revision;
  if ((rev.options || []).length) return optionsCard(m, i);
  const open = !m.outcome;
  const box = (k, disabled) => open ? `<input type="checkbox" data-chat-pick="${k}"${S.chatPicks[k] && !disabled ? ' checked' : ''}${disabled ? ' disabled' : ''}>` : '';
  const base = revBase(m);
  const hasArc = !!(rev.arc && rev.arc.title);
  // 다음 아크 안과 끝 화가 바뀌는 아크 칸은 구조와 한 덩어리로 들어간다 (pipeline.apply_revision)
  const linked = hasArc && (base.next || !!rev.arc.end_ep);
  const parts = [];
  if (base.missing && open) parts.push('<div class="note plain">이 변경안을 만든 아크가 이제 없어요. 구조와 아크 칸은 적용할 수 없어요.</div>');
  if ((rev.parts || []).length) {
    parts.push(`<div class="prop-part"><label class="prop-head">${box(pickKey(i, 'parts'), false)}<strong>부 구성</strong></label>
      <div class="diff">${partsDiff(rev) || '<div class="small">지금 부 구성과 같아요.</div>'}</div></div>`);
  }
  if (hasArc) {
    const stale = base.missing || nextStale(m);
    const title = base.next ? '다음 아크 안' : `아크 ${base.arc ? base.arc.number : ''} 칸`;
    const note = !open ? '' : stale && base.next ? '<div class="note plain">그 사이 아크가 바뀌어 이 안의 시작 화가 맞지 않아요. 다시 청해 주세요.</div>'
      : base.next ? `<div class="note info">적용하면 아래 다음 아크 초안${S.arcDraft ? '을 이 안으로 바꿔요' : '에 들어가요'}. 작품에는 '이 아크 적용'을 눌러야 들어가요.</div>`
      : rev.arc.end_ep ? '<div class="note info">끝 화가 바뀌어 구간 범위도 함께 적용돼요.</div>' : '';
    const acts = linked && rev.acts.length ? `<div class="diff">${actsDiff(rev, base.acts) || ''}</div>` : '';
    parts.push(`<div class="prop-part"><label class="prop-head">${box(pickKey(i, 'arc'), stale)}<strong>${title}</strong>${rev.arc.end_ep && !base.next ? '<span class="chip written">끝 화 바뀜</span>' : ''}</label>
      ${note}<div class="diff">${arcDiff(rev, base.arc, plannedUntil() + 1) || '<div class="small">지금 아크와 같아요.</div>'}</div>${acts}</div>`);
  }
  if (rev.acts.length && !linked) {
    // 변경안을 받은 뒤 화수나 아크 범위가 바뀌었으면 이 구조는 더 이상 맞지 않는다
    const end = rev.acts[rev.acts.length - 1].end_ep;
    const stale = base.missing || (serial() ? !base.arc || end !== base.arc.end_ep : !rev.total_episodes && end !== P().meta.target_episodes);
    const head = serial() && base.arc ? `아크 ${base.arc.number} 기승전결` : '기승전결 구조';
    parts.push(`<div class="prop-part"><label class="prop-head">${box(pickKey(i, 'acts'), stale)}<strong>${head}</strong>${rev.total_episodes ? `<span class="chip written">화수 바뀜</span>` : ''}</label>
      ${stale && open ? `<div class="note plain">${serial() ? '그 뒤에 아크 범위가 바뀌어' : `그 뒤에 총 화수가 ${P().meta.target_episodes}화로 바뀌어`} 이 구조는 적용할 수 없어요.</div>` : ''}
      <div class="diff">${actsDiff(rev, base.acts) || '<div class="small">지금 구조와 같아요.</div>'}</div></div>`);
  }
  rev.episodes.forEach((e) => {
    const cur = ep(e.number);
    const locked = cur && LOCKED_STATUS.includes(cur.status);
    const note = locked ? '<div class="note plain">본문이 생겨서 이제는 바꿀 수 없어요.</div>'
      : cur && cur.status === 'confirmed' && open ? '<div class="note warn">확정한 화예요. 적용하면 초안으로 돌아가 다시 확정해야 해요.</div>' : '';
    // 화가 많으면 길어진다: 새 화는 접고, 바뀌는 화는 3화까지만 펼친다
    const fold = !cur || rev.episodes.length > 3;
    parts.push(`<div class="prop-part">
      <div class="between"><label class="prop-head">${box(pickKey(i, e.number), locked)}<strong>${e.number}화</strong> ${esc(e.title)}${cur ? ` <span class="chip ${cur.status}">${STATUS[cur.status]}</span>` : ' <span class="chip ai">새 화</span>'}</label>
        ${cur ? `<button type="button" class="btn small" data-action="selectEp" data-arg="${e.number}">지금 플롯</button>` : ''}</div>
      ${note}${fold ? `<details><summary class="small">바뀌는 칸 보기</summary><div class="diff">${plotDiff(e)}</div></details>` : `<div class="diff">${plotDiff(e)}</div>`}</div>`);
  });
  if ((rev.new_characters || []).length) {
    parts.push(`<div class="prop-part"><strong>새 인물</strong>
      ${rev.new_characters.map((c) => `<div class="note plain"><strong>${esc(c.name || c.id)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}</span>${c.personality || c.goal ? `<br>${esc(c.personality || c.goal)}` : ''}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}</div>`).join('')}
      <div class="small">${base.next && hasArc ? '다음 아크 안과 함께 초안에 들어가고, 아크를 적용하면 조연 · 단역으로 등록돼요.' : '고른 화에 나오는 인물만 새 인물 후보로 들어가요. 그 화를 확정하거나 플롯 편집기에서 등록하면 인물이 돼요.'}</div></div>`);
  }
  if ((rev.new_places || []).length) {
    parts.push(`<div class="prop-part"><strong>새 장소</strong>
      ${rev.new_places.map((x) => `<div class="note plain">${placeLabel(x)}</div>`).join('')}
      <div class="small">고른 화에 나오는 장소만 새 장소 후보로 들어가요. 그 화를 확정하면 인과율에 장소로 등록돼요.</div></div>`);
  }
  const done = m.outcome === 'applied'
    ? `<span class="chip finalized">적용함 · ${m.applied.map((x) => chatAppliedLabel(m, x)).join(', ')}</span>`
    : m.outcome === 'dismissed' ? '<span class="chip">버림</span>' : '';
  if (!open) {
    const again = m.outcome === 'dismissed' ? `<button type="button" class="btn small" data-action="chatReopen" data-arg="${i}">다시 검토</button>`
      : base.next && m.applied.includes('arc') && !S.arcDraft && !nextStale(m) ? `<button type="button" class="btn small" data-action="chatRestoreDraft" data-arg="${i}">다음 아크 초안에 다시 넣기</button>` : '';
    return `<details class="proposal done"${again && !S.arcDraft && base.next ? ' open' : ''}><summary>${done} 변경안 다시 보기</summary>${parts.join('')}${again ? `<div class="row proposal-actions">${again}</div>` : ''}</details>`;
  }
  // 맨 위 요약: 무엇이 바뀌는지 한 줄로 보고, 여러 화를 한 번에 고르거나 뺀다. 버튼 줄은 아래에 붙어 있다 (.proposal-actions)
  const nums = rev.episodes.map((e) => e.number);
  const fresh = rev.episodes.filter((e) => !ep(e.number)).length;
  const sum = [(rev.parts || []).length ? '부 구성' : '', hasArc ? (base.next ? '다음 아크' : '아크 칸') : '', rev.acts.length && !linked ? '구조' : '',
    nums.length ? `${rangeText(nums)}화${fresh ? `(새 화 ${fresh})` : ''}` : ''].filter(Boolean).join(' · ');
  const many = nums.length > 3 ? `<button type="button" class="btn small" data-action="chatPickAll" data-arg="${i}|1">모두 고르기</button><button type="button" class="btn small" data-action="chatPickAll" data-arg="${i}|0">모두 빼기</button>` : '';
  return `<div class="proposal"><div class="between prop-sum"><strong>${esc(sum)}</strong><span class="row">${many}</span></div>${parts.join('')}
    ${proposalActions(['chatDismiss', i], ['chatApply', i])}</div>`;
}

/** 고른 방향으로 변경안을 청한다. 방향 여러 안은 끄고, 입력칸에 적어 둔 말은 덧붙인다. */
function sendDirection(text) {
  if (S.chatPending) return;
  const extra = (S.chatDraft || '').trim();
  S.chatOptions = false;
  S.chatDraft = extra ? `${text} ${extra}` : text;
  actions.chatSend();
}

// ----- 패널 -----

function chatPanel(topic) {
  if (!S.chatOpen) return '';
  const t = chatConf(topic);
  if (S.chatTopic !== topic) S.chatScroll = true;
  S.chatTopic = topic;
  initPicks(topic);
  const msgs = chatMessages(topic);
  const list = msgs.map((m, i) => m.role === 'user'
    ? `<div class="msg user">${t.userMsg ? t.userMsg(m) : esc(m.text)}</div>`
    : `<div class="msg ai"><div class="msg-text">${esc(m.text)}</div>${m.revision ? proposal(m, i) : m.passage && t.proposal ? t.proposal(m, i) : ''}</div>`).join('');
  const empty = msgs.length || S.chatPending ? '' : `<div class="note info">${esc(t.intro)}</div>
    ${t.examples.length ? `<div class="row">${t.examples.map((x) => `<button type="button" class="btn small" data-action="chatExample" data-arg="${esc(x)}">${esc(x)}</button>`).join('')}</div>` : ''}`;
  const pending = S.chatPending ? `<div class="msg user">${esc(S.chatPending)}</div><div class="msg ai pending" role="status"><span class="spinner small" aria-hidden="true"></span>생각하는 중… (최대 1분)</div>` : '';
  return `<aside class="chat-panel" aria-label="${esc(t.title)}">
    <div class="chat-head"><h2>${esc(t.title)}</h2><div class="row" style="gap:4px">
      ${msgs.length ? '<button type="button" class="btn small" data-action="chatClear">기록 지우기</button>' : ''}
      <button type="button" class="btn icon-btn" data-action="toggleChat" aria-label="닫기">✕</button></div></div>
    <div class="chat-log" id="chat-log">${empty}${list}${pending}</div>
    ${t.inputExtra ? t.inputExtra(topic) : ''}
    <div class="chat-input">
      <textarea id="chat-input" rows="2" data-local="chatDraft" aria-label="AI에게 할 말" enterkeyhint="${touchFirst() ? 'enter' : 'send'}" placeholder="${esc(t.placeholder)}"${S.chatPending ? ' disabled' : ''}>${esc(S.chatDraft)}</textarea>
      <button type="button" class="btn primary" data-action="chatSend"${S.chatPending ? ' disabled' : ''}>보내기</button>
    </div>
    <div class="small chat-hint">${touchFirst() ? '보내기 버튼으로 보내요 · 대화는 작품에 저장돼요' : 'Enter 보내기 · Shift+Enter 줄바꿈 · 대화는 작품에 저장돼요'}</div>
  </aside>`;
}

/** 대화 패널만 다시 그린다. 패널 밖 입력칸(본문, 플롯 서랍)은 건드리지 않는다. */
function redrawChat() {
  const el = document.querySelector('.chat-panel');
  if (!el) return;
  const html = chatPanel(S.chatTopic);
  if (html) el.outerHTML = html;
  else el.remove();
  syncChat();
}

/** render() 직후에 부른다: 패널이 있으면 본문 자리를 비우고, 새 메시지가 오면 맨 아래로 내린다. */
function syncChat() {
  const open = !!document.querySelector('.chat-panel');
  document.body.classList.toggle('chat-open', open);
  const log = $('#chat-log');
  if (!log) return;
  log.scrollTop = S.chatScroll ? log.scrollHeight : S.chatScrollTop;
  S.chatScroll = false;
}

Object.assign(actions, {
  toggleChat() {
    S.chatOpen = !S.chatOpen;
    S.chatScroll = true;
    try { localStorage.setItem('canon.chat', S.chatOpen ? '1' : '0'); } catch { /* 저장 못 해도 동작에는 상관없다 */ }
    render();
    if (S.chatOpen) $('#chat-input')?.focus();
  },
  chatExample(text) {
    S.chatDraft = String(text);
    render();
    $('#chat-input')?.focus();
  },
  async chatSend(preset = '') {
    const topic = S.chatTopic;
    const t = chatConf(topic);
    preset = typeof preset === 'string' ? preset : '';
    // 빠른 요청은 그 요청만 보낸다. 입력칸에 쓰던 글은 보내지 않고 칸에 남긴다 (기록에 한쪽만 보이던 문제)
    const text = preset ? '' : (S.chatDraft || '').trim();
    if ((!text && !preset) || S.chatPending) return;
    if (t.ready && !t.ready()) return;
    S.chatPending = text || (t.presetLabel ? t.presetLabel(preset) : preset);
    if (!preset) S.chatDraft = '';
    S.chatScroll = true;
    render();
    try {
      await saveIfDirty();
      if (t.beforeSend) await t.beforeSend();
      const body = t.body ? t.body(text, preset) : { message: text };
      const name = S.name;
      const res = await api('POST', `/projects/${enc(name)}/chat/${enc(topic)}`, body);
      // 서버는 대화 기록만 바꾼다. 기다리는 동안 다른 칸을 고쳤으면(저장 전) 그 입력을 지우지 않게 대화 기록만 받아 온다
      if (name !== S.name) return;
      if (S.dirty) P().chats = res.chats;
      else S.project = res;
    } catch (e) {
      toast(e.message, true);
      if (!preset) S.chatDraft = text;
    } finally {
      S.chatPending = null;
      S.chatScroll = true;
      // 다른 칸에 입력하는 중이면(한글 조합 포함) 그 칸을 다시 그리거나 포커스를 빼앗지 않고 대화 패널만 바꾼다
      if (isTyping() && document.activeElement.id !== 'chat-input') redrawChat();
      else {
        render();
        $('#chat-input')?.focus();
      }
    }
  },
  async chatApply(i) {
    const m = chatMessages(S.chatTopic)[i];
    // 화면에 보이는 체크 상태를 그대로 쓴다 (바꿀 수 없게 된 칸은 꺼져 있다)
    const picked = (k) => {
      const el = document.querySelector(`[data-chat-pick="${pickKey(i, k)}"]`);
      return !!(el && el.checked && !el.disabled);
    };
    const arc = picked('arc');
    const parts = picked('parts');
    const next = m.target === 'next';
    // 다음 아크 안과 끝 화가 바뀌는 아크 칸은 구조 칸 없이 아크 칸 하나로 고른다
    const acts = m.revision.arc && m.revision.arc.title && (next || m.revision.arc.end_ep) ? arc : picked('acts');
    const episodes = m.revision.episodes.map((e) => e.number).filter((n) => picked(n));
    if (!acts && !arc && !parts && !episodes.length) return toast('적용할 부분을 고르세요', true);
    if (next && arc && S.arcDraft && !confirm('지금 다음 아크 초안을 이 안으로 바꿀까요? 초안에서 손본 칸도 이 안으로 바뀌어요.')) return;
    const lost = parts ? P().parts.filter((x) => x.summary && !m.revision.parts.some((y) => y.start_ep === x.start_ep && y.end_ep === x.end_ep)) : [];
    if (lost.length && !confirm(`범위가 바뀌어 저장된 ${lost.map((x) => `${x.number}부`).join(', ')} 요약이 사라져요. 적용할까요?`)) return;
    const draft = next && arc ? draftFromRev(m) : null;
    await run('변경안을 적용하는 중', async () => {
      await saveIfDirty();
      const body = next ? { episodes, parts, draft: arc ? ['arc'] : [] } : { acts, arc, parts, episodes };
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/${enc(S.chatTopic)}/${i}/apply`, body);
      if (draft) {
        S.arcDraft = draft;
        S.selArc = 'next';
      }
      const done = chatMessages(S.chatTopic)[i];
      toast(`적용했어요: ${(done ? done.applied : []).map((x) => chatAppliedLabel(m, x)).join(', ')}${draft ? '. 초안을 살펴보고 \'이 아크 적용\'을 누르세요' : ''}`);
    });
  },
  chatRestoreDraft(i) {
    const m = chatMessages(S.chatTopic)[Number(i)];
    S.arcDraft = draftFromRev(m);
    S.selArc = 'next';
    render();
    toast('다음 아크 초안에 다시 넣었어요');
  },
  toggleChatOptions() {
    S.chatOptions = !S.chatOptions;
    redrawChat();
    $('#chat-input')?.focus();
  },
  chatDirection(arg) {
    const [i, k] = String(arg).split('|').map(Number);
    const o = chatMessages(S.chatTopic)[i].revision.options[k];
    sendDirection(`${k + 1}안 '${o.title}' 방향으로 변경안을 만들어 줘.`);
  },
  chatMixDirections(i) {
    const opts = chatMessages(S.chatTopic)[Number(i)].revision.options;
    const ks = opts.map((_, k) => k).filter((k) => S.chatPicks[pickKey(Number(i), `opt${k}`)]);
    if (!ks.length) return toast('섞을 안을 체크해서 고르세요', true);
    const names = ks.map((k) => `${k + 1}안 '${opts[k].title}'`);
    sendDirection(ks.length === 1 ? `${names[0]} 방향으로 변경안을 만들어 줘.` : `${names.join('과 ')}을 섞어서 변경안을 만들어 줘. 각 안에서 살릴 것을 골라 하나의 흐름으로 이어 줘.`);
  },
  chatPickAll(arg) {
    const [i, on] = String(arg).split('|');
    const m = chatMessages(S.chatTopic)[Number(i)];
    m.revision.episodes.forEach((e) => {
      const cur = ep(e.number);
      if (!(cur && LOCKED_STATUS.includes(cur.status))) S.chatPicks[pickKey(Number(i), e.number)] = on === '1';
    });
    redrawChat();
  },
  async chatDismiss(i) {
    // 손보던 후보 글이 있으면 묻는다. 버린 뒤에도 '다시 검토'로 다시 열 수 있다
    const also = S.dirty ? ' 저장하지 않은 다른 변경도 함께 저장해요.' : '';
    if (Object.keys(S.candEdit || {}).some((k) => k.startsWith(`${i}:`))) {
      if (!confirm(`손보던 후보 글이 있어요. 버릴까요? 다시 검토로 열면 후보는 다시 보이지만 손본 글은 남지 않아요.${also}`)) return;
    } else if (also && !confirm(`이 변경안을 버릴까요?${also}`)) return;
    await run('정리하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/${enc(S.chatTopic)}/${i}/dismiss`);
    });
  },
  async chatReopen(i) {
    await run('다시 여는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/${enc(S.chatTopic)}/${i}/reopen`);
    });
  },
  async chatClear() {
    const open = chatMessages(S.chatTopic).filter((m) => m.revision && !m.outcome && !(m.revision.options || []).length).length;
    if (!confirm(chatConf(S.chatTopic).clearAsk + (open ? `\n아직 고르지 않은 변경안 ${open}개도 함께 지워져요.` : '') + (S.dirty ? '\n저장하지 않은 다른 변경도 함께 저장해요.' : ''))) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/chat/${enc(S.chatTopic)}`);
      S.chatPicks = {};
    });
  },
});

document.addEventListener('scroll', (e) => {
  if (e.target.id === 'chat-log') S.chatScrollTop = e.target.scrollTop;
}, true);

document.addEventListener('change', (e) => {
  const k = e.target.dataset && e.target.dataset.chatPick;
  if (k) S.chatPicks[k] = e.target.checked;
});

document.addEventListener('keydown', (e) => {
  if (e.target.id !== 'chat-input' || e.key !== 'Enter' || e.shiftKey || e.isComposing || e.keyCode === 229) return;
  if (touchFirst()) return;  // 터치 키보드에는 Shift 가 없다. 줄바꿈은 Enter 로, 보내기는 버튼으로
  e.preventDefault();
  actions.chatSend();
});

// Esc 로 대화 패널을 닫고, 패널을 연 버튼으로 포커스를 돌린다. 다른 층이 먼저 Esc 를 받는다:
// 플롯 서랍(app.js)과 본문 부분 수정 도구(passage.js). 그 처리기들이 상태를 지우기 전에 보려고 capture 로 듣는다
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || e.isComposing || e.keyCode === 229 || !S.chatOpen || !document.querySelector('.chat-panel')) return;
  if (S.selTool) return;
  if (S.route[2] === 'arc' && (S.selEp || S.selAct != null || S.editArc || S.selPart != null)) return;
  e.preventDefault();
  actions.toggleChat();
  document.querySelector('[data-action="toggleChat"]')?.focus();
}, true);
