/* 설정 도우미의 '대화로 다듬기' (topic 'setup'). app.js 의 S, actions, api, run, render 와
   chat.js 의 대화 패널, diffField, optionsCard, pickKey 를 그대로 쓴다.
   작가가 말하면 AI가 로그라인 · 주제 · 톤 · 세계관 · 인물 칸 · 새 인물 · 관계에서 바꿀 것만 내고, 고른 부분만 설정에 들어간다.
   이미 채운 칸을 바꾸는 부분은 처음에 고르지 않은 채로 둔다. '방향 여러 안'을 켜면 변경안 대신 방향 2~3개를 받아 고르거나 섞는다.
   서버는 pipeline.revise_setup 과 canon/setupchat.py (clean · apply · undo). 부분 id 는 setupchat.part_ids 와 같다:
   칸 이름('theme', 'world.rules'), 인물 칸 'c:<id>:<칸>', 새 인물 'new:<id>', 관계 'r:<a>:<b>'. */
'use strict';

// 칸 순서와 이름 (setupchat.KEY_LABELS · CHAR_LABELS 와 같다)
const SETUP_KEYS = [
  ['title', '제목'], ['logline.who', '로그라인 · 누가'], ['logline.why', '로그라인 · 무엇 때문에'], ['logline.goal', '로그라인 · 무엇을 하려 하나'],
  ['logline.block', '로그라인 · 무엇이 막나'], ['logline.stake', '로그라인 · 무엇이 걸렸나'], ['theme', '주제'], ['tone', '톤'], ['notes', '메모'],
  ['world.setting', '배경'], ['world.era', '시대'], ['world.rules', '깨면 안 되는 규칙'], ['world.locations', '장소'], ['world.name_rules', '이름 규칙'],
];
const SETUP_KEY_LABEL = Object.fromEntries(SETUP_KEYS);
const SETUP_LISTS = ['world.rules', 'world.locations', 'world.name_rules'];
const SETUP_CHAR_LABEL = {
  name: '이름', role: '역할', age: '나이', gender: '성별', goal: '원하는 것', wound: '두려운 것 · 약점', secrets: '숨기는 것',
  speech_style: '말투 (대사)', personality: '성격', background: '배경', appearance: '외모', arc: '아크',
};

CHAT_TOPICS.setup = {
  title: '대화로 다듬기',
  intro: '설정을 말로 다듬어요. AI가 로그라인, 주제, 톤, 세계관, 인물, 관계에서 바꿀 칸만 지금 값과 나란히 보여 주고, 고른 것만 설정에 들어가요. 이미 채운 칸을 바꾸는 것은 처음에 꺼져 있어요. 적용한 뒤에도 취소할 수 있어요. 어느 쪽으로 갈지 막막하면 아래 \'방향 여러 안\'을 켜고 보내 보세요.',
  examples: ['주인공의 약점을 더 어둡게', '라이벌을 한 명 넣어 줘', '세계관 규칙을 세 개쯤 채워 줘', '로그라인이 밋밋해, 걸린 것을 키워 줘'],
  placeholder: '예: 주인공의 약점을 더 어둡게',
  clearAsk: '설정 대화 기록을 지울까요? 적용한 설정은 그대로예요. 기록을 지우면 적용 취소는 할 수 없어요.',
  body: (text) => ({ message: text, mode: S.chatOptions ? 'options' : '' }),
  userMsg: (m) => `${m.mode === 'options' ? '<span class="chip">방향 여러 안</span> ' : ''}${esc(m.text)}`,
  proposal: setupProposal,
  inputExtra: () => `<div class="chat-scope between">
    <span class="small">대상 · <strong>설정 전체</strong></span>
    <button type="button" class="btn small${S.chatOptions ? ' on' : ''}" data-action="toggleChatOptions" aria-pressed="${S.chatOptions}" title="변경안 대신 서로 다른 방향 2~3개를 먼저 받아 고르거나 섞어요">방향 여러 안</button>
  </div>`,
};

/** 그 칸의 지금 값. o 는 작품이나 적용 전 설정(setup_before): 둘 다 meta, world 가 있다. */
function setupKeyValue(o, k) {
  if (k.startsWith('logline.')) return o.meta.logline_parts[k.slice(8)];
  if (k.startsWith('world.')) return o.world[k.slice(6)];
  return o.meta[k];
}

const setupEditValue = (e) => (SETUP_LISTS.includes(e.key) ? e.items : e.text);
const setupCharValue = (x) => (x.field === 'secrets' ? x.items : x.text);
const setupRelId = (r) => `r:${r.a}:${r.b}`;
const setupFilled = (v) => (Array.isArray(v) ? v.length > 0 : !!String(v || '').trim());
const setupPair = (rels, a, b) => rels.find((r) => (r.a === a && r.b === b) || (r.a === b && r.b === a)) || null;

/** 변경안의 부분 id 를 보이는 순서로 (setupchat.part_ids). */
function setupPartIds(rev) {
  return [...rev.edits.map((e) => e.key), ...rev.characters.map((x) => `c:${x.id}:${x.field}`),
    ...rev.new_characters.map((c) => `new:${c.id}`), ...rev.relationships.map(setupRelId)];
}

function setupName(rev, base, id) {
  const c = [...base.characters, ...rev.new_characters].find((x) => x.id === id);
  return c ? c.name || id : id;
}

/** 부분 id 를 읽는 이름으로 (setupchat.label). */
function setupLabel(rev, base, pid) {
  if (SETUP_KEY_LABEL[pid]) return SETUP_KEY_LABEL[pid];
  const [kind, ...rest] = pid.split(':');
  if (kind === 'c') return `${setupName(rev, base, rest[0])} ${SETUP_CHAR_LABEL[rest[1]] || rest[1]}`;
  if (kind === 'new') return `새 인물 ${setupName(rev, base, rest[0])}`;
  if (kind === 'r') return `관계 ${setupName(rev, base, rest[0])} ↔ ${setupName(rev, base, rest[1])}`;
  return pid;
}

/** 관계가 고르지 않은 새 인물과 이어져 있으면 그 인물 이름들 (그 관계는 넣을 수 없다). */
function setupRelBlocked(rev, i, r) {
  return [r.a, r.b].filter((id) => rev.new_characters.some((c) => c.id === id) && !S.chatPicks[pickKey(i, `new:${id}`)]);
}

function setupRelDiff(r, cur, rev, base) {
  const before = (k) => (cur ? cur[k] : (Array.isArray(r[k]) ? [] : ''));
  const a = setupName(rev, base, r.a);
  const b = setupName(rev, base, r.b);
  const rows = [diffField('어떤 사이', 'type', before('type'), r.type), diffField('설명', 'description', before('description'), r.description)];
  const gc = cur ? conflictWord(cur.goal_conflict || 0) : '';
  if (cur ? gc !== conflictWord(r.goal_conflict || 0) : r.goal_conflict > 0) rows.push(diffField('원하는 게 부딪치나', 'goal_conflict', gc, conflictWord(r.goal_conflict || 0)));
  rows.push(diffField(`${esc(a)} → ${esc(b)}`, 'a_view', before('a_view'), r.a_view), diffField(`${esc(b)} → ${esc(a)}`, 'b_view', before('b_view'), r.b_view));
  return rows.join('');
}

function setupNewCard(c) {
  const facts = [c.role, c.tier === 'minor' ? '단역' : c.tier === 'support' ? '조연' : '주역', c.gender, c.age].filter(Boolean).map(esc).join(' · ');
  const line = (l, v) => (v ? `<br><span class="small">${l}:</span> ${esc(v)}` : '');
  return `<div class="note plain"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${facts}</span>
    ${line('원하는 것', c.goal)}${line('두려운 것 · 약점', c.wound)}${line('성격', c.personality)}${line('말투', c.speech_style)}${line('배경', c.background)}</div>`;
}

function setupProposal(m, i) {
  const rev = m.setup;
  if ((rev.options || []).length) return optionsCard(m, i);
  const open = !m.outcome;
  // 적용한 변경안은 적용하기 전 설정과, 아직 고르지 않은 것은 지금 설정과 비교한다
  const base = m.outcome === 'applied' && m.setup_before ? m.setup_before : P();
  const box = (pid, def, disabled) => {
    const k = pickKey(i, pid);
    if (open && S.chatPicks[k] === undefined) S.chatPicks[k] = def;
    return open ? `<input type="checkbox" data-chat-pick="${k}"${S.chatPicks[k] && !disabled ? ' checked' : ''}${disabled ? ' disabled' : ''}>` : '';
  };
  const done = (pid) => (m.outcome === 'applied' && m.applied.includes(pid) ? ' <span class="chip finalized">적용함</span>' : '');
  const over = (v) => (open && setupFilled(v) ? ' <span class="chip written">채운 칸 바꿈</span>' : '');
  const why = (t) => (t ? `<div class="small">${esc(t)}</div>` : '');
  const part = (pid, def, head, body, disabled = false) => `<div class="prop-part"><label class="prop-head">${box(pid, def, disabled)}<strong>${head}</strong>${done(pid)}</label>${body}</div>`;
  const parts = [];
  rev.edits.forEach((e) => {
    const cur = setupKeyValue(base, e.key);
    const label = SETUP_KEY_LABEL[e.key] || e.key;
    parts.push(part(e.key, !setupFilled(cur), esc(label) + over(cur), `${why(e.why)}<div class="diff">${diffField(label, e.key, cur, setupEditValue(e))}</div>`));
  });
  rev.characters.forEach((x) => {
    const c = base.characters.find((y) => y.id === x.id);
    const cur = c ? c[x.field] : '';
    const label = SETUP_CHAR_LABEL[x.field] || x.field;
    parts.push(part(`c:${x.id}:${x.field}`, !setupFilled(cur), `${esc(setupName(rev, base, x.id))} · ${esc(label)}${over(cur)}`,
      `${why(x.why)}<div class="diff">${diffField(label, x.field, cur, setupCharValue(x))}</div>`));
  });
  rev.new_characters.forEach((c) => parts.push(part(`new:${c.id}`, true, `새 인물 · ${esc(c.name)}`, setupNewCard(c))));
  rev.relationships.forEach((r) => {
    const cur = setupPair(base.relationships, r.a, r.b);
    const blocked = open ? setupRelBlocked(rev, i, r) : [];
    const head = `관계 · ${esc(setupName(rev, base, r.a))} ↔ ${esc(setupName(rev, base, r.b))}${cur ? (open ? ' <span class="chip written">있는 관계 바꿈</span>' : '') : ' <span class="chip ai">새 관계</span>'}`;
    const note = blocked.length ? `<div class="note plain">새 인물 ${blocked.map((id) => esc(setupName(rev, base, id))).join(', ')}을(를) 함께 골라야 넣을 수 있어요.</div>` : '';
    parts.push(part(setupRelId(r), !cur, head, `${note}<div class="diff">${setupRelDiff(r, cur, rev, base) || '<div class="small">지금 관계와 같아요.</div>'}</div>`, blocked.length > 0));
  });

  if (m.outcome === 'applied') {
    // 고른 것이 많으면 칩 한 줄이 넘친다: 칩에는 개수만, 이름은 펼친 안에
    const names = `<div class="small">적용한 것: ${m.applied.map((x) => esc(setupLabel(rev, base, x))).join(', ')}</div>`;
    return `<details class="proposal done"><summary><span class="chip finalized">적용함 ${m.applied.length}개</span> 변경안 다시 보기</summary>${names}${parts.join('')}
      <div class="row proposal-actions"><button type="button" class="btn small" data-action="setupChatUndo" data-arg="${i}">적용 취소</button></div></details>`;
  }
  if (m.outcome === 'dismissed') {
    return `<details class="proposal done"><summary><span class="chip">버림</span> 변경안 다시 보기</summary>${parts.join('')}
      <div class="row proposal-actions"><button type="button" class="btn small" data-action="chatReopen" data-arg="${i}">다시 검토</button></div></details>`;
  }
  const count = (n, l) => (n ? `${l} ${n}` : '');
  const sum = [count(rev.edits.length, '기본 정보 · 세계관'), count(rev.characters.length, '인물 칸'), count(rev.new_characters.length, '새 인물'), count(rev.relationships.length, '관계')].filter(Boolean).join(' · ');
  const notes = [
    P().episodes.some((e) => e.status === 'finalized') ? '이미 쓴 화의 본문은 바뀌지 않아요. 인물 칸을 바꾸면 인물 설정 변경 기록에 작가가 고친 것으로 남아요.' : '',
    rev.relationships.length && P().snapshots.length ? '첫 반영 뒤라 관계는 사이와 설명만 바뀌어요. 지금 호감과 긴장은 본문의 관계 사건으로 계산돼요.' : '',
  ].filter(Boolean).map((t) => `<div class="note info">${t}</div>`).join('');
  const many = setupPartIds(rev).length > 3 ? `<button type="button" class="btn small" data-action="setupPickAll" data-arg="${i}|1">모두 고르기</button><button type="button" class="btn small" data-action="setupPickAll" data-arg="${i}|0">모두 빼기</button>` : '';
  return `<div class="proposal"><div class="between prop-sum"><strong>${esc(sum)}</strong><span class="row">${many}</span></div>
    ${notes}<div class="small">이미 채운 칸을 바꾸는 것은 꺼 두었어요. 바꾸려면 체크하세요.</div>${parts.join('')}
    ${proposalActions(['chatDismiss', i], ['setupChatApply', i], '고른 것 적용')}</div>`;
}

Object.assign(actions, {
  async setupChatApply(i) {
    i = Number(i);
    const m = chatMessages('setup')[i];
    // 화면에 보이는 체크 상태를 그대로 쓴다 (고르지 않은 새 인물과 이어진 관계는 꺼져 있다)
    const fields = setupPartIds(m.setup).filter((pid) => {
      const el = document.querySelector(`[data-chat-pick="${pickKey(i, pid)}"]`);
      return !!(el && el.checked && !el.disabled);
    });
    if (!fields.length) return toast('적용할 것을 고르세요', true);
    await run('설정에 적용하는 중', async () => {
      await saveIfDirty();
      const before = setupCardKeys();
      S.project = await api('POST', `/projects/${enc(S.name)}/chat/setup/${i}/apply`, { fields });
      // 새로 들어오거나 칸이 바뀐 인물 · 관계 카드는 펼쳐 보인다 (setup.js 의 카드 접기)
      openNewCards(before);
      fields.forEach((pid) => {
        const [kind, a, b] = pid.split(':');
        if (kind === 'c') openMap()['c:' + a] = true;
        if (kind === 'r') openMap()[relKey({ a, b })] = true;
      });
      toast(`적용했어요: ${fields.map((x) => setupLabel(m.setup, P(), x)).join(', ')}`);
    });
    if (S.route[2] === 'setup') checkNames();
  },
  async setupChatUndo(i) {
    i = Number(i);
    if (!confirm(`이 변경안 적용을 취소할까요? 적용한 칸을 적용하기 전으로 돌려요. 그 뒤에 다시 고친 칸과 이미 플롯이나 관계에 쓰이는 새 인물은 그대로 둬요.${S.dirty ? ' 저장하지 않은 다른 변경도 함께 저장해요.' : ''}`)) return;
    const m = chatMessages('setup')[i];
    const base = m.setup_before || P();
    await run('적용을 취소하는 중', async () => {
      await saveIfDirty();
      const res = await api('POST', `/projects/${enc(S.name)}/chat/setup/${i}/undo`);
      S.project = res.project;
      const label = (xs) => xs.map((x) => setupLabel(m.setup, base, x)).join(', ');
      toast(res.restored.length ? `되돌렸어요: ${label(res.restored)}${res.kept.length ? ` · 그대로 둔 것: ${label(res.kept)}` : ''}`
        : `그 뒤에 모두 다시 고쳐서 되돌린 것이 없어요: ${label(res.kept)}`, !res.restored.length);
    });
    if (S.route[2] === 'setup') checkNames();
  },
  setupPickAll(arg) {
    const [i, on] = String(arg).split('|');
    setupPartIds(chatMessages('setup')[Number(i)].setup).forEach((pid) => { S.chatPicks[pickKey(Number(i), pid)] = on === '1'; });
    redrawChat();
  },
});

// 새 인물을 고르거나 빼면 그 인물과 이어진 관계를 고를 수 있는지가 바뀐다
document.addEventListener('change', (e) => {
  const k = e.target.dataset && e.target.dataset.chatPick;
  if (!k || S.chatTopic !== 'setup' || !/^\d+:new:/.test(k)) return;
  S.chatPicks[k] = e.target.checked;
  redrawChat();
});
