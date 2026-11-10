/* 설정 변경안을 읽는 도우미와 옛 설정 대화(topic 'setup')의 적용 취소. app.js 의 S, actions, api, run, render 와 chat.js 의 diffField 를 그대로 쓴다.
   칸 이름 · 지금 값 · 관계 비교는 대화 에이전트의 설정 카드(agentsetup.js)가 쓴다.
   옛 설정 대화의 패널과 보내기 · 적용은 04e 에서 지웠다. 옛 기록은 대화 에이전트의 '이전 대화'에서 읽고, 적용한 변경안은 거기서 취소한다(setupChatUndo).
   서버는 canon/setupchat.py. 부분 id 는 setupchat.part_ids 와 같다: 칸 이름('theme', 'world.rules'), 인물 칸 'c:<id>:<칸>', 새 인물 'new:<id>', 관계 'r:<a>:<b>'. */
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
  speech_style: '말투 (대사)', personality: '성격', background: '배경', appearance: '외모', arc: '아크', aliases: '다른 이름',
};
const SETUP_CHAR_LISTS = ['secrets', 'aliases'];  // setupchat.CHAR_LIST_FIELDS 와 같다

/** 그 칸의 지금 값. o 는 작품이나 적용 전 설정(setup_before): 둘 다 meta, world 가 있다. */
function setupKeyValue(o, k) {
  if (k.startsWith('logline.')) return o.meta.logline_parts[k.slice(8)];
  if (k.startsWith('world.')) return o.world[k.slice(6)];
  return o.meta[k];
}

const setupEditValue = (e) => (SETUP_LISTS.includes(e.key) ? e.items : e.text);
const setupCharValue = (x) => (SETUP_CHAR_LISTS.includes(x.field) ? x.items : x.text);
const setupRelId = (r) => `r:${r.a}:${r.b}`;
const setupFilled = (v) => (Array.isArray(v) ? v.length > 0 : !!String(v || '').trim());
const setupPair = (rels, a, b) => rels.find((r) => (r.a === a && r.b === b) || (r.a === b && r.b === a)) || null;

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

function setupRelDiff(r, cur, rev, base) {
  const before = (k) => (cur ? cur[k] : (Array.isArray(r[k]) ? [] : ''));
  const a = setupName(rev, base, r.a);
  const b = setupName(rev, base, r.b);
  const rows = [diffField('어떤 사이', 'type', before('type'), r.type), diffField('설명', 'description', before('description'), r.description),
    diffField('가 닿을 곳', 'destination', before('destination') || '', r.destination || '')];
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

Object.assign(actions, {
  async setupChatUndo(i) {
    i = Number(i);
    if (!(await askConfirm(`이 변경안 적용을 취소할까요? 적용한 칸을 적용하기 전으로 돌려요. 그 뒤에 다시 고친 칸과 이미 플롯이나 관계에 쓰이는 새 인물은 그대로 둬요.${S.dirty ? ' 저장하지 않은 다른 변경도 함께 저장해요.' : ''}`, { ok: '적용 취소', cancel: '닫기', danger: true }))) return;
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
});
