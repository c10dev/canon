/* 설정 칸 하나의 AI 후보 (✦). app.js 의 S, P, api, enc, esc, setPath, markDirty, render, toast, actions 와
   setup.js 의 composeLogline, updateLogline 을 쓴다.
   칸 옆 ✦ 버튼(ideaBtn)을 누르면 서버(pipeline.suggest_field)가 후보 셋을 주고, 칸 바로 아래(ideaList)에 펼친다.
   기다리는 동안 화면을 막지 않고 그 자리에 '후보를 만들고 있어요'를 보인다. 고르기 전에는 칸을 바꾸지 않는다.
   여러 칸을 바꾸는 제안은 '대화로 다듬기'(setupchat.js)가 맡는다.
   키는 칸의 data-bind 경로이고 prompts.FIELD_IDEAS 의 키와 같다 (tests/test_ideas_js.py).
   인물 칸은 경로가 characters.<번호>.<칸> 이라 번호 자리를 * 로 바꿔 찾는다 (ideaKey, prompts.idea_key 와 같은 규칙). */
'use strict';

const IDEA_FIELDS = {
  'meta.title': '제목',
  'meta.logline_parts.who': '누가',
  'meta.logline_parts.why': '무엇 때문에',
  'meta.logline_parts.goal': '무엇을 하려 하나',
  'meta.logline_parts.block': '무엇이 막나',
  'meta.logline_parts.stake': '무엇이 걸렸나',
  'world.setting': '배경',
  'characters.*.personality': '성격',
  'characters.*.background': '배경',
  'characters.*.appearance': '외모',
  'characters.*.arc': '아크',
};

/** 칸 경로 → IDEA_FIELDS 키 ('characters.2.arc' → 'characters.*.arc') */
const ideaKey = (path) => path.replace(/^characters\.\d+\./, 'characters.*.');

/** 그 칸의 인물 (인물 칸이 아니면 null) */
function ideaChar(path) {
  const m = path.match(/^characters\.(\d+)\./);
  return m ? P().characters[Number(m[1])] || null : null;
}

/** 칸 이름. 인물 칸은 인물 이름을 붙인다 ('서윤 성격'). 후보를 받을 수 없는 칸이면 '' */
function ideaLabel(path) {
  const label = IDEA_FIELDS[ideaKey(path)];
  if (!label) return '';
  const c = ideaChar(path);
  return c ? `${c.name || c.id} ${label}` : label;
}

/** 후보 칸의 id ('meta.logline_parts.who' → 'ideas-meta-logline_parts-who'). 입력 칸 id(f-…)와 같은 규칙 */
const ideaId = (path) => 'ideas-' + path.replace(/\./g, '-');

/** 칸 옆 ✦ 버튼. text 는 버튼 글자 ('제목 후보', 로그라인 칸은 '후보'). 후보가 펼쳐져 있으면 aria-expanded 로 알린다 */
function ideaBtn(path, text = '후보') {
  const label = ideaLabel(path);
  if (!label) return '';
  const open = !!(S.ideas || {})[path];
  return `<button type="button" class="ai-mini" data-action="fieldIdeas" data-arg="${esc(path)}" aria-controls="${ideaId(path)}" aria-expanded="${open}" aria-label="${esc(label)} AI 후보 세 개 받기" title="AI가 이 칸 후보를 세 개 내요">✦ ${esc(text)}</button>`;
}

/** 칸 바로 아래 후보 목록. 누르면 칸에 넣는다. 받기 전에는 빈 자리만 둔다 (aria-controls 대상) */
function ideaList(path) {
  const r = (S.ideas || {})[path];
  if (!r) return `<div id="${ideaId(path)}" hidden></div>`;
  const label = ideaLabel(path);
  const body = r.loading
    ? '<span class="loading" role="status"><i aria-hidden="true"></i>후보를 만들고 있어요</span>'
    : r.options.map((o, i) => `<button type="button" class="opt" data-action="useIdea" data-arg="${esc(path + '|' + i)}">${esc(o.text)}${o.reason ? `<small>${esc(o.reason)}</small>` : ''}</button>`).join('')
      || '<span class="small">후보가 없어요. 다시 받아 보세요</span>';
  const acts = r.loading ? '' : `<div class="acts"><button type="button" class="btn small" data-action="fieldIdeas" data-arg="${esc(path)}">다시 받기</button><button type="button" class="btn small" data-action="closeIdeas" data-arg="${esc(path)}">닫기</button></div>`;
  return `<div id="${ideaId(path)}" class="cands" role="group" aria-label="${esc(label)} AI 후보"><div class="ch"><span>✦ 후보 · 고르면 칸에 들어가요</span></div>${body}${acts}</div>`;
}

Object.assign(actions, {
  async fieldIdeas(path) {
    if (!ideaLabel(path) || ((S.ideas || {})[path] || {}).loading) return;
    const name = S.name;
    const c = ideaChar(path);
    const mine = { loading: true, cid: c ? c.id : '' };
    S.ideas = { ...S.ideas, [path]: mine };
    render();
    try {
      // 저장 전 화면 값을 함께 보낸다: 방금 고친 다른 칸에 맞춘 후보가 오게
      const r = await api('POST', `/projects/${enc(name)}/field-ideas`, { field: path, project: P() });
      if (S.name !== name || S.ideas[path] !== mine) return;  // 그사이 다른 작품으로 갔거나 닫았다
      S.ideas[path] = { ...r, cid: mine.cid };
      if (!isTyping()) S.focusTarget = `#${ideaId(path)} .opt`;
    } catch (e) {
      if (S.ideas[path] === mine) delete S.ideas[path];
      toast(e.message, true);
    }
    render();
  },
  useIdea(arg) {
    const i = arg.lastIndexOf('|');
    const path = arg.slice(0, i);
    const r = (S.ideas || {})[path] || {};
    const o = (r.options || [])[Number(arg.slice(i + 1))];
    if (!o) return;
    const c = ideaChar(path);
    if ((c ? c.id : '') !== (r.cid || '')) {  // 그사이 인물을 빼서 번호가 다른 인물을 가리킨다
      delete S.ideas[path];
      toast('인물 목록이 바뀌었어요. 후보를 다시 받아 주세요', true);
      render();
      return;
    }
    const slot = path.startsWith('meta.logline_parts.');
    const prev = slot ? composeLogline(P().meta.logline_parts) : '';
    setPath(P(), path, o.text);
    delete S.ideas[path];
    markDirty();
    if (slot) updateLogline(prev);  // 합친 로그라인 문장도 새 칸 내용으로 (직접 고친 문장은 그대로)
    S.focusTarget = '#f-' + path.replace(/\./g, '-');
    render();
  },
  closeIdeas(path) {
    delete (S.ideas || {})[path];
    S.focusTarget = `#app [data-action="fieldIdeas"][data-arg="${path}"]`;
    render();
  },
});
