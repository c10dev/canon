/* 대화로 다듬기 패널. app.js 의 S, actions, api, render 를 그대로 쓴다.
   작가가 말하면 AI 가 답과 변경안을 내고, 변경안은 바뀌는 칸만 보여 준다. 작가가 고른 부분만 반영한다.
   기승전결 · 플롯 화면(topic 'plot')과 집필 화면의 본문 부분 수정(topic 'text:<화>', passage.js)에 붙어 있다.
   다른 화면에 붙일 때는 CHAT_TOPICS 에 항목을 더하고 서버 web.py 의 _chat 과 변경안 반영 함수를 함께 늘린다.
   주제마다 body(요청 내용), proposal(변경안 그리기), userMsg, inputExtra 를 바꿔 끼울 수 있다. */
'use strict';

const CHAT_TOPICS = {
  plot: {
    title: '대화로 다듬기',
    intro: '구조나 플롯이 마음에 들지 않으면 말로 알려 주세요. AI 가 바꿀 부분을 변경안으로 보여 주고, 고른 것만 반영합니다. 본문이 있는 화는 바뀌지 않아요.',
    examples: ['3화 전개가 너무 빨라', '결말을 비극으로 바꿔 줘', '승 구간을 한 화 늘려 줘', '주인공이 더 늦게 진실을 알게 해 줘'],
    placeholder: '예: 3화 전개가 너무 빨라',
    clearAsk: '이 작품의 대화 기록을 지울까요? 반영한 구조와 플롯은 그대로입니다.',
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
});

const PLOT_FIELDS = [
  ['title', '제목'], ['summary', '요약'], ['events', '사건 순서'], ['characters', '등장 인물'],
  ['emotional_shift', '감정 변화'], ['ending_hook', '엔딩 훅'], ['foreshadow_plant', '심을 복선'], ['foreshadow_payoff', '회수할 복선'],
  ['storyline', '이야기 줄기'], ['threads', '끼어드는 줄기'], ['pov', '시점 인물'], ['pov_mode', '서술 방식'],
];
const ACT_FIELDS = [['goal', '구간 목표'], ['key_turn', '전환점'], ['pov', '서술 시점']];
const LOCKED_STATUS = ['written', 'finalized'];

function chatMessages(topic) {
  const c = (P().chats || []).find((x) => x.topic === topic);
  return c ? c.messages : [];
}

/** 'text:3' 처럼 화 번호가 붙은 주제는 앞부분('text')의 설정을 쓴다. */
function chatConf(topic) {
  return CHAT_TOPICS[String(topic).split(':')[0]];
}

function chatButton(topic = 'plot') {
  return `<button class="btn${S.chatOpen ? ' on' : ''}" data-action="toggleChat" aria-pressed="${S.chatOpen}">${chatConf(topic).title}</button>`;
}

// ----- 변경안 비교 -----

function fieldText(key, v) {
  if (key === 'storyline') return v ? lineName(v) : '메인';
  if (!Array.isArray(v)) return String(v ?? '');
  return (key === 'characters' ? v.map(charName) : key === 'threads' ? v.map(lineName) : v).join(', ');
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
    const name = (x) => esc(key === 'characters' ? charName(x) : key === 'threads' ? lineName(x) : x);
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

function actsDiff(rev) {
  const rows = rev.acts.map((a) => {
    const cur = P().arc.find((x) => x.name === a.name) || {};
    const range = cur.start_ep === a.start_ep && cur.end_ep === a.end_ep ? ''
      : `<div class="diff-row"><span class="act-label">범위</span>${cur.name ? `<del>${cur.start_ep}–${cur.end_ep}화</del>` : ''}<ins>${a.start_ep}–${a.end_ep}화</ins></div>`;
    const body = range + ACT_FIELDS.map(([k, l]) => diffField(l, k, cur[k], a[k])).join('');
    return body ? `<div class="diff-act"><span class="chip ${actClass(a.name)}">${a.name}</span>${body}</div>` : '';
  }).join('');
  const total = rev.total_episodes ? `<div class="diff-row"><span class="act-label">총 화수</span><del>${P().meta.target_episodes}화</del><ins>${rev.total_episodes}화</ins></div>` : '';
  return total + rows;
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
    m.revision.episodes.forEach((e) => {
      const k = pickKey(i, e.number);
      const cur = ep(e.number);
      if (S.chatPicks[k] === undefined) S.chatPicks[k] = !cur || cur.status === 'draft';
    });
  });
}

function proposal(m, i) {
  const rev = m.revision;
  const open = !m.outcome;
  const box = (k, disabled) => open ? `<input type="checkbox" data-chat-pick="${k}"${S.chatPicks[k] && !disabled ? ' checked' : ''}${disabled ? ' disabled' : ''}>` : '';
  const parts = [];
  if (rev.acts.length) {
    // 변경안을 받은 뒤 화수가 바뀌었으면 이 구조는 더 이상 맞지 않는다
    const stale = !rev.total_episodes && rev.acts[rev.acts.length - 1].end_ep !== P().meta.target_episodes;
    parts.push(`<div class="prop-part"><label class="prop-head">${box(pickKey(i, 'acts'), stale)}<strong>기승전결 구조</strong>${rev.total_episodes ? `<span class="chip written">화수 바뀜</span>` : ''}</label>
      ${stale && open ? `<div class="note plain">그 뒤에 총 화수가 ${P().meta.target_episodes}화로 바뀌어 이 구조는 반영할 수 없어요.</div>` : ''}
      <div class="diff">${actsDiff(rev) || '<div class="small">지금 구조와 같아요.</div>'}</div></div>`);
  }
  rev.episodes.forEach((e) => {
    const cur = ep(e.number);
    const locked = cur && LOCKED_STATUS.includes(cur.status);
    const note = locked ? '<div class="note plain">본문이 생겨서 이제는 바꿀 수 없어요.</div>'
      : cur && cur.status === 'confirmed' && open ? '<div class="note warn">확정한 화예요. 반영하면 초안으로 돌아가 다시 확정해야 해요.</div>' : '';
    parts.push(`<div class="prop-part">
      <div class="between"><label class="prop-head">${box(pickKey(i, e.number), locked)}<strong>${e.number}화</strong> ${esc(e.title)}${cur ? ` <span class="chip ${cur.status}">${STATUS[cur.status]}</span>` : ' <span class="chip ai">새 화</span>'}</label>
        ${cur ? `<button type="button" class="btn small" data-action="selectEp" data-arg="${e.number}">지금 플롯</button>` : ''}</div>
      ${note}<div class="diff">${plotDiff(e)}</div></div>`);
  });
  if ((rev.new_characters || []).length) {
    parts.push(`<div class="prop-part"><strong>새 인물</strong>
      ${rev.new_characters.map((c) => `<div class="note plain"><strong>${esc(c.name || c.id)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}</span>${c.personality || c.goal ? `<br>${esc(c.personality || c.goal)}` : ''}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}</div>`).join('')}
      <div class="small">고른 화에 나오는 인물만 새 인물 후보로 들어가요. 그 화를 확정하거나 플롯 편집기에서 등록하면 인물이 돼요.</div></div>`);
  }
  const done = m.outcome === 'applied'
    ? `<span class="chip finalized">반영함 · ${m.applied.map((x) => (x === 'acts' ? '구조' : `${x}화`)).join(', ')}</span>`
    : m.outcome === 'dismissed' ? '<span class="chip">반영 안 함</span>' : '';
  if (!open) {
    return `<details class="proposal done"><summary>${done} 변경안 다시 보기</summary>${parts.join('')}</details>`;
  }
  return `<div class="proposal">${parts.join('')}
    <div class="row"><button class="btn small primary" data-action="chatApply" data-arg="${i}">고른 것 반영</button><button class="btn small" data-action="chatDismiss" data-arg="${i}">반영 안 함</button></div></div>`;
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
      <textarea id="chat-input" rows="2" data-local="chatDraft" aria-label="AI 에게 할 말" placeholder="${esc(t.placeholder)}"${S.chatPending ? ' disabled' : ''}>${esc(S.chatDraft)}</textarea>
      <button type="button" class="btn primary" data-action="chatSend"${S.chatPending ? ' disabled' : ''}>보내기</button>
    </div>
    <div class="small chat-hint">Enter 보내기 · Shift+Enter 줄바꿈 · 대화는 작품에 저장돼요</div>
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
    const text = (S.chatDraft || '').trim();
    preset = typeof preset === 'string' ? preset : '';
    if ((!text && !preset) || S.chatPending) return;
    if (t.ready && !t.ready()) return;
    S.chatPending = text || (t.presetLabel ? t.presetLabel(preset) : preset);
    S.chatDraft = '';
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
      S.chatDraft = text;
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
    const box = document.querySelector(`[data-chat-pick="${pickKey(i, 'acts')}"]`);
    const acts = !!(box && box.checked && !box.disabled);
    const episodes = m.revision.episodes.map((e) => e.number).filter((n) => {
      const el = document.querySelector(`[data-chat-pick="${pickKey(i, n)}"]`);
      return el && el.checked && !el.disabled;
    });
    if (!acts && !episodes.length) return toast('반영할 부분을 고르세요', true);
    await run('변경안을 반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/${enc(S.chatTopic)}/${i}/apply`, { acts, episodes });
      toast(`반영했습니다: ${[acts ? '구조' : '', ...episodes.map((n) => `${n}화`)].filter(Boolean).join(', ')}`);
    });
  },
  async chatDismiss(i) {
    await run('정리하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/${enc(S.chatTopic)}/${i}/dismiss`);
    });
  },
  async chatClear() {
    if (!confirm(chatConf(S.chatTopic).clearAsk)) return;
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
  e.preventDefault();
  actions.chatSend();
});
