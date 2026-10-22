/* Canon 웹 UI. 빌드 없이 쓰는 단일 파일 SPA.
   화면은 문자열 템플릿으로 그리고, 입력은 data-bind 경로로 S.project 에 바로 반영한다.
   AI 호출이나 저장이 끝나면 화면 전체를 다시 그린다. */
'use strict';

const S = {
  config: null,
  name: null,        // 현재 프로젝트 폴더 이름
  project: null,
  dirty: false,
  route: [],
  suggestion: null,  // 설정 도우미 제안 (반영 전)
  styleSample: '',
  selEp: null,       // 플롯 보드에서 고른 화
  deltas: {},        // 화별 상태 변경안 (반영 전)
  picks: {},         // 변경안 항목 선택 여부
  textDraft: {},     // 화별 본문 편집 중인 값
  context: null,
  promptText: null,
  briefTab: 'episode',
  briefText: null,
  mode: localStorage.getItem('canon.mode') || 'api',
};

const STATUS = { draft: '플롯 초안', confirmed: '플롯 확정', written: '본문 작성됨', finalized: '반영 완료' };
const ACTS = ['기', '승', '전', '결'];

// ---------- 공통 ----------

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const enc = encodeURIComponent;
const P = () => S.project;
const base = () => `#/p/${enc(S.name)}`;

function fmtErr(data, status) {
  const d = data && data.detail;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('\n');
  return d || `요청 실패 (${status})`;
}

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch('/api' + path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(fmtErr(data, r.status));
  return data;
}

function toast(msg, err = false) {
  const el = document.createElement('div');
  el.className = 't' + (err ? ' err' : '');
  el.textContent = msg;
  $('#toast').appendChild(el);
  while ($('#toast').children.length > 3) $('#toast').firstChild.remove();
  setTimeout(() => el.remove(), err ? 8000 : 3500);
}

/** 버튼 동작 공통 처리: 진행 표시, 오류 알림, 다시 그리기 */
async function run(label, fn) {
  $('#busy-text').textContent = label;
  $('#busy').hidden = false;
  try {
    await fn();
  } catch (e) {
    toast(e.message, true);
  } finally {
    $('#busy').hidden = true;
    render();
  }
}

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  const target = keys.reduce((o, k) => o[k], obj);
  target[last] = value;
}

function epIndex(n) {
  return P().episodes.findIndex((e) => e.plot.number === n);
}

function ep(n) {
  return P().episodes.find((e) => e.plot.number === n);
}

function charName(id) {
  const c = P().characters.find((x) => x.id === id);
  return c ? c.name : id;
}

/** 지금 작업해야 할 화: 반영이 끝나지 않은 첫 화 */
function currentEp() {
  const eps = P().episodes;
  if (!eps.length) return 1;
  const open = eps.find((e) => e.status !== 'finalized');
  return open ? open.plot.number : eps[eps.length - 1].plot.number;
}

function actOf(n) {
  return P().arc.find((a) => a.start_ep <= n && n <= a.end_ep);
}

function actClass(name) {
  return 'act-' + (ACTS.indexOf(name) + 1);
}

// ---------- 입력 바인딩 ----------
// data-bind="meta.title" data-kind="text|int|list|bool"

function bindValue(path, kind) {
  const v = getPath(P(), path);
  if (kind === 'list') return (v || []).join('\n');
  return v ?? '';
}

function input(label, path, opt = {}) {
  const id = 'f-' + path.replace(/\./g, '-');
  const kind = opt.kind || (opt.type === 'number' ? 'int' : 'text');
  const val = esc(bindValue(path, kind));
  const hint = opt.hint ? ` <span class="hint">${esc(opt.hint)}</span>` : '';
  const ro = opt.readonly ? ' readonly' : '';
  const ctrl = opt.rows || kind === 'list'
    ? `<textarea id="${id}" rows="${opt.rows || 3}" data-bind="${path}" data-kind="${kind}"${ro} placeholder="${esc(opt.placeholder || (kind === 'list' ? '한 줄에 하나씩' : ''))}">${val}</textarea>`
    : `<input id="${id}" type="${opt.type || 'text'}" value="${val}" data-bind="${path}" data-kind="${kind}"${ro}${opt.min != null ? ` min="${opt.min}"` : ''}${opt.max != null ? ` max="${opt.max}"` : ''} placeholder="${esc(opt.placeholder || '')}">`;
  return `<div class="field${opt.cls ? ' ' + opt.cls : ''}"><label for="${id}">${esc(label)}${hint}</label>${ctrl}</div>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (el.dataset.bind && P()) {
    const kind = el.dataset.kind;
    let v = el.value;
    if (kind === 'int') v = v === '' ? 0 : parseInt(v, 10) || 0;
    if (kind === 'float') v = parseFloat(v) || 0;
    if (kind === 'list') v = v.split('\n').map((s) => s.trim()).filter(Boolean);
    if (kind === 'bool') v = el.checked;
    setPath(P(), el.dataset.bind, v);
    markDirty();
    const out = el.dataset.out && document.getElementById(el.dataset.out);
    if (out) out.textContent = v;
  }
  if (el.dataset.draft) {
    S.textDraft[el.dataset.draft] = el.value;
    const c = $('#char-count');
    if (c) c.textContent = el.value.length.toLocaleString();
    const sb = $('#save-text');
    if (sb) sb.disabled = false;
  }
  if (el.dataset.local) S[el.dataset.local] = el.value;
  if (el.dataset.deltaSummary) S.deltas[el.dataset.deltaSummary].summary = el.value;
});

document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset.pick) {
    S.picks[el.dataset.pick] = el.checked;
    const c = $('#pick-count');
    if (c) c.textContent = Object.values(S.picks).filter(Boolean).length;
    if (S.route[2] === 'review' && /^[ers]\d/.test(el.dataset.pick)) refreshPreview(Number(S.route[3]));
  }
  if (el.dataset.castEp) {
    const plot = ep(Number(el.dataset.castEp)).plot;
    const id = el.value;
    plot.characters = el.checked ? [...new Set([...plot.characters, id])] : plot.characters.filter((x) => x !== id);
    markDirty();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.id === 'genre-custom' && !e.isComposing) {
    e.preventDefault();
    actions.addCustomGenre();
  }
});

function markDirty() {
  if (!S.dirty) {
    S.dirty = true;
    renderSavebar();
  }
}

function renderSavebar() {
  let bar = $('#savebar');
  if (!S.dirty) {
    if (bar) bar.remove();
    return;
  }
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'savebar';
    bar.className = 'savebar';
    bar.innerHTML = '<span>저장하지 않은 변경이 있어요</span><button class="btn small" data-action="revert">되돌리기</button><button class="btn small primary" data-action="save">저장</button>';
    document.body.appendChild(bar);
  }
}

async function save() {
  S.project = await api('PUT', `/projects/${enc(S.name)}`, P());
  S.dirty = false;
}

async function saveIfDirty() {
  if (S.dirty) await save();
}

// ---------- 동작 ----------

const actions = {
  async save() {
    await run('저장 중', async () => { await save(); toast('저장했습니다'); });
  },
  async revert() {
    await run('불러오는 중', async () => { await loadProject(S.name); });
  },
  async createProject() {
    const name = $('#np-name').value.trim();
    if (!name) return toast('프로젝트 이름을 입력하세요', true);
    const meta = {
      title: $('#np-title').value.trim() || name,
      genre: $('#np-genre').value.trim(),
      logline: $('#np-logline').value.trim(),
      target_episodes: parseInt($('#np-eps').value, 10) || 16,
      adult: $('#np-adult').checked,
    };
    await run('만드는 중', async () => {
      await api('POST', '/projects', { name, meta });
      location.hash = `#/p/${enc(name)}/setup`;
    });
  },

  // 설정 도우미
  async suggest() {
    await run('AI 가 설정을 제안하는 중… (최대 1분)', async () => {
      await saveIfDirty();
      S.suggestion = await api('POST', `/projects/${enc(S.name)}/suggest`);
      S.suggestion.characters.forEach((c, i) => { S.picks['sc' + i] = !P().characters.some((x) => x.id === c.id); });
      S.suggestion.relationships.forEach((r, i) => { S.picks['sr' + i] = true; });
    });
  },
  dropSuggestion() {
    S.suggestion = null;
    render();
  },
  async applySuggestion() {
    const s = structuredClone(S.suggestion);
    s.characters = s.characters.filter((_, i) => S.picks['sc' + i]);
    s.relationships = s.relationships.filter((_, i) => S.picks['sr' + i]);
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/suggest/apply`, s);
      S.suggestion = null;
      toast('빈칸을 채웠습니다. 기존 입력은 그대로입니다.');
    });
  },
  toggleGenre(id) {
    const m = P().meta;
    m.genres = m.genres.includes(id) ? m.genres.filter((g) => g !== id) : [...m.genres, id];
    syncGenre();
  },
  addCustomGenre() {
    const el = $('#genre-custom');
    const v = el.value.trim();
    if (!v) return;
    const hit = (S.genres || []).find((g) => g.name === v || g.id === v);
    const id = hit ? hit.id : v;
    if (!P().meta.genres.includes(id)) P().meta.genres.push(id);
    syncGenre();
  },
  addCharacter() {
    const n = P().characters.length + 1;
    P().characters.push({ id: 'char' + n, name: '', role: '조연', age: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '' });
    markDirty();
    render();
  },
  removeCharacter(i) {
    const c = P().characters[i];
    if (!confirm(`${c.name || c.id} 인물을 지울까요? 관계도 함께 지워집니다.`)) return;
    P().characters.splice(i, 1);
    P().relationships = P().relationships.filter((r) => r.a !== c.id && r.b !== c.id);
    P().states = P().states.filter((s) => s.character_id !== c.id);
    markDirty();
    render();
  },
  addRelationship() {
    const cs = P().characters;
    if (cs.length < 2) return toast('인물이 두 명 이상 있어야 합니다', true);
    P().relationships.push({ a: cs[0].id, b: cs[1].id, type: '', description: '', affinity: 0, tension: 0, goal_conflict: 0 });
    markDirty();
    render();
  },
  removeRelationship(i) {
    P().relationships.splice(i, 1);
    markDirty();
    render();
  },

  // 문체
  async analyzeStyle() {
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      await saveIfDirty();
      const prof = await api('POST', `/projects/${enc(S.name)}/style`, { text: S.styleSample });
      P().style = prof;
      S.dirty = true;
      toast('분석 결과를 불러왔습니다. 확인하고 저장하세요.');
    });
  },
  addPassage() {
    P().style.sample_passages.push('');
    markDirty();
    render();
  },
  removePassage(i) {
    P().style.sample_passages.splice(i, 1);
    markDirty();
    render();
  },

  // 구조와 플롯
  async planArc() {
    if (P().arc.length && !confirm('지금 구조를 AI 제안으로 바꿀까요? 저장 전까지는 되돌릴 수 있어요.')) return;
    await run('기승전결 구조를 설계하는 중…', async () => {
      await saveIfDirty();
      const plan = await api('POST', `/projects/${enc(S.name)}/arc`);
      P().arc = plan.acts;
      S.dirty = true;
      toast('구조 제안을 불러왔습니다. 확인하고 저장하세요.');
    });
  },
  async draftPlots() {
    await run('화별 플롯 초안을 만드는 중… (화수에 따라 1~2분)', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/plots`, {});
      toast('플롯 초안을 만들었습니다. 확정된 화는 그대로입니다.');
    });
  },
  selectEp(n) {
    S.selEp = Number(n);
    render();
  },
  async confirmEp(n) {
    await run('확정하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/confirm`);
    });
  },
  async unconfirmEp(n) {
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/unconfirm`);
    });
  },
  async confirmAll() {
    const drafts = P().episodes.filter((e) => e.status === 'draft');
    if (!drafts.length) return toast('확정할 초안이 없습니다');
    if (!confirm(`초안 ${drafts.length}화를 모두 확정할까요?`)) return;
    await run('확정하는 중', async () => {
      await saveIfDirty();
      for (const e of drafts) S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${e.plot.number}/confirm`);
    });
  },

  // 집필
  setMode(m) {
    S.mode = m;
    localStorage.setItem('canon.mode', m);
    render();
  },
  async writeEp(n) {
    if (ep(n).text && !confirm(`${n}화 본문을 새로 생성할까요? 지금 본문은 사라집니다.`)) return;
    await run(`${n}화 본문을 쓰는 중… (최대 2분)`, async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/write`);
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${n}화 본문을 저장했습니다`);
    });
  },
  async saveText(n) {
    await run('본문 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] ?? ep(n).text });
      delete S.textDraft[n];
      delete S.deltas[n];
      toast('본문을 저장했습니다');
    });
  },
  startManual(n) {
    S.textDraft[n] = '';
    render();
  },
  gotoPlot(n) {
    S.selEp = Number(n);
    location.hash = `${base()}/arc`;
  },
  async togglePrompt(n) {
    if (S.promptText) {
      S.promptText = null;
      return render();
    }
    await run('불러오는 중', async () => {
      const r = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/prompt`);
      S.promptText = `[시스템]\n${r.system}\n\n[프롬프트]\n${r.prompt}`;
    });
  },

  // 상태 변경안
  async extractState(n) {
    await run(`${n}화 상태 변경안을 뽑는 중… (최대 1분)`, async () => {
      if (S.textDraft[n] !== undefined) {
        S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] });
        delete S.textDraft[n];
      }
      setDelta(n, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/state`));
    });
  },
  async applyDelta(n) {
    const out = pickedDelta(n);
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/apply`, out);
      delete S.deltas[n];
      toast(`${n}화를 마쳤습니다`);
      location.hash = base();
    });
  },
  async toggleNumbers(v) {
    const show = v === 'numbers';
    P().settings.show_numbers = show;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/view`, { show_numbers: show });
    } catch (e) {
      toast(e.message, true);
    }
  },
  dropDelta(n) {
    if (!confirm('이 변경안을 버릴까요?')) return;
    delete S.deltas[n];
    render();
  },

  // 설정
  async saveSettings() {
    const key = $('#set-key').value.trim();
    const body = {
      provider: $('#set-provider').value, model: $('#set-model').value.trim(),
      local_url: $('#set-local-url').value.trim(), local_model: $('#set-local-model').value.trim(),
      stages: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-${s}`).value])),
    };
    if (key) body.api_key = key;
    const lkey = $('#set-local-key').value.trim();
    if (lkey) body.local_key = lkey;
    await run('저장 중', async () => {
      S.config = await api('PUT', '/config', body);
      toast('설정을 저장했습니다');
    });
  },
  async clearKey() {
    if (!confirm('저장된 API 키를 지울까요?')) return;
    await run('지우는 중', async () => {
      S.config = await api('PUT', '/config', { clear_key: true });
      toast('키를 지웠습니다');
    });
  },
  async testSettings() {
    await run('연결 확인 중', async () => {
      const r = await api('POST', '/config/test');
      toast(r.message);
    });
  },

  // 작업지시서
  openStateBrief(n) {
    S.briefTab = 'state';
    location.hash = `${base()}/brief/${n}`;
  },
  setBriefTab(t) {
    S.briefTab = t;
    S.briefText = null;
    render();
  },
  async copyBrief() {
    try {
      await navigator.clipboard.writeText(S.briefText || '');
      toast('복사했습니다. 채팅 앱에 붙여 넣으세요.');
    } catch {
      toast('복사하지 못했습니다. 내용을 직접 선택해 복사하세요.', true);
    }
  },
  downloadBrief(n) {
    const blob = new Blob([S.briefText || ''], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${S.name}-${String(n).padStart(2, '0')}-${S.briefTab}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  async importText(n) {
    const text = $('#imp-body').value.trim();
    if (!text) return toast('본문을 붙여 넣으세요', true);
    if (ep(n).text && !confirm(`${n}화의 지금 본문을 바꿀까요?`)) return;
    await run('가져오는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text });
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${n}화 본문으로 저장했습니다`);
      location.hash = `${base()}/write/${n}`;
    });
  },
  async importJson(n) {
    const raw = $('#imp-json').value;
    if (!raw.trim()) return toast('JSON 을 붙여 넣으세요', true);
    await run('확인하는 중', async () => {
      setDelta(n, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/state/parse`, { raw }));
      location.hash = `${base()}/review/${n}`;
    });
  },
};

/** 체크한 항목만 남긴 변경안. 반영과 관계 미리 보기에 같이 쓴다. */
function pickedDelta(n) {
  const d = S.deltas[n];
  const pick = (prefix, list) => list.filter((_, i) => S.picks[prefix + i]);
  return {
    ...d,
    character_updates: pick('c', d.character_updates),
    events: pick('e', d.events),
    secrets_added: pick('s', d.secrets_added),
    relationship_updates: pick('r', d.relationship_updates),
    new_facts: pick('f', d.new_facts),
    foreshadow_planted: pick('p', d.foreshadow_planted),
    foreshadow_resolved: pick('x', d.foreshadow_resolved),
  };
}

let previewTimer = null;
/** 고른 변경안으로 관계를 다시 계산해 미리 보기만 바꾼다 (저장 안 함). */
function refreshPreview(n) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    if (!S.deltas[n]) return;
    try {
      S.preview = { n, ...(await api('POST', `/projects/${enc(S.name)}/episodes/${n}/preview`, pickedDelta(n))) };
    } catch (e) {
      S.preview = { n, error: e.message };
    }
    const box = $('#rel-preview');
    if (box) box.innerHTML = relationLines(S.preview);
  }, 250);
}

function setDelta(n, d) {
  S.deltas[n] = d;
  S.picks = {};
  S.preview = null;
  d.character_updates.forEach((_, i) => { S.picks['c' + i] = true; });
  d.events.forEach((_, i) => { S.picks['e' + i] = true; });
  d.secrets_added.forEach((_, i) => { S.picks['s' + i] = true; });
  d.relationship_updates.forEach((_, i) => { S.picks['r' + i] = true; });
  d.new_facts.forEach((_, i) => { S.picks['f' + i] = true; });
  d.foreshadow_planted.forEach((_, i) => { S.picks['p' + i] = true; });
  d.foreshadow_resolved.forEach((_, i) => { S.picks['x' + i] = true; });
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  e.preventDefault();
  const fn = actions[el.dataset.action];
  const arg = el.dataset.arg;
  if (fn) fn(arg !== undefined && /^\d+$/.test(arg) ? Number(arg) : arg);
});

// ---------- 라우팅 ----------

async function loadProject(name) {
  S.project = await api('GET', `/projects/${enc(name)}`);
  S.name = name;
  S.dirty = false;
}

let lastHash = location.hash;
window.addEventListener('hashchange', async () => {
  if (S.dirty && !confirm('저장하지 않은 변경이 있어요. 버리고 이동할까요?')) {
    history.replaceState(null, '', lastHash);
    return;
  }
  lastHash = location.hash;
  await route();
});

async function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  S.route = parts;
  S.context = null;
  S.promptText = null;
  S.briefText = null;
  S.relations = null;
  try {
    if (!S.config) S.config = await api('GET', '/config');
    if (!S.genres && parts[0] === 'p') S.genres = await api('GET', '/genres').catch(() => []);
    if (parts[0] === 'settings') {
      S.config = await api('GET', '/config');
    } else if (parts[0] === 'p' && parts[1]) {
      if (S.name !== parts[1] || S.dirty) await loadProject(parts[1]);
      else S.project = await api('GET', `/projects/${enc(parts[1])}`);
      S.dirty = false;
      const n = Number(parts[3]);
      if (!parts[2] && S.project.relationships.length) {
        S.relations = await api('GET', `/projects/${enc(S.name)}/relations`).catch((e) => ({ error: e.message }));
      }
      if (parts[2] === 'write' && n && ep(n) && ep(n).status !== 'draft') {
        S.context = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/context`).catch(() => null);
      }
      if (parts[2] === 'research') await rsLoad();
      if (parts[2] === 'brief' && n && ep(n)) {
        S.briefText = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`).then((r) => r.text).catch((e) => '※ ' + e.message);
      }
    } else {
      S.name = null;
      S.project = null;
      S.projects = await api('GET', '/projects');
    }
  } catch (e) {
    toast(e.message, true);
    S.name = null;
    S.project = null;
    S.projects = [];
  }
  render();
  window.scrollTo(0, 0);
}

// ---------- 그리기 ----------

function render() {
  renderSavebar();
  const [p, , page, arg] = S.route;
  if (p === 'settings') {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:820px;margin:0 auto">${viewSettings()}</main></div>`;
    return;
  }
  if (p !== 'p' || !P()) {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:1080px;margin:0 auto">${viewProjects()}</main></div>`;
    return;
  }
  const n = Number(arg) || currentEp();
  const views = { setup: viewSetup, style: viewStyle, arc: viewArc, write: viewWrite, review: viewReview, brief: viewBrief, research: viewResearch };
  const body = (views[page] || viewHome)(n);
  $('#app').innerHTML = `<div class="shell">${sidebar(page || 'home')}<main class="main">${body}</main></div>`;
  // 상태 정리 지시서 탭이 바뀌면 다시 불러온다
  if (page === 'brief' && S.briefText === null && ep(n)) {
    api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`)
      .then((r) => r.text).catch((e) => '※ ' + e.message)
      .then((t) => { S.briefText = t; render(); });
  }
}

function sidebar(active) {
  const p = P();
  const done = p.episodes.filter((e) => e.status === 'finalized').length;
  const total = p.meta.target_episodes;
  const cur = currentEp();
  const items = [
    ['home', base(), 'H', '작품 홈'],
    ['setup', base() + '/setup', '1', '설정 도우미'],
    ['style', base() + '/style', '2', '문체 레퍼런스'],
    ['arc', base() + '/arc', '3', '기승전결 · 플롯'],
    ['write', `${base()}/write/${cur}`, '4', '집필'],
    ['review', `${base()}/review/${cur}`, '5', '상태 승인'],
    ['brief', `${base()}/brief/${cur}`, '6', '작업지시서'],
  ];
  const cfg = S.config || {};
  return `<nav class="side" aria-label="작품 메뉴">
    <a class="brand" href="#/">Canon</a>
    <div class="work-card">
      <div class="small">현재 작품</div>
      <div style="font-size:16px;font-weight:700">${esc(p.meta.title || S.name)}</div>
      <div class="small">${esc(p.meta.genre || '장르 미정')} · ${total}화</div>
      <div class="meter" aria-hidden="true"><i style="left:0;width:${Math.round((done / Math.max(total, 1)) * 100)}%;background:var(--green)"></i></div>
      <div class="small">${done} / ${total}화 반영 완료</div>
    </div>
    <div class="nav">${items.map(([id, href, num, label]) => `<a href="${href}"${id === active ? ' aria-current="page"' : ''}><span class="num">${num}</span>${label}</a>`).join('')}</div>
    <div class="nav nav-extra"><span class="small">본편과 분리</span><a href="${base()}/research"${active === 'research' ? ' aria-current="page"' : ''}><span class="num">R</span>연구 · 모델 실험</a></div>
    <div class="side-foot">
      <span class="small">본문 모델</span>
      <strong style="font-size:13px">${esc(cfg.stages ? cfg.stages.write.model : cfg.model || '')}</strong>
      ${cfg.has_key ? '' : '<span style="color:var(--red)">API 키가 없습니다. 설정에서 넣거나 작업지시서를 쓰세요.</span>'}
      <a href="#/settings">모델 · API 키 설정</a>
      <a href="#/">작품 목록</a>
    </div>
  </nav>`;
}

function header(eyebrow, title, desc, right = '') {
  return `<header class="page-head"><div class="lead"><div class="eyebrow">${eyebrow}</div><h1>${esc(title)}</h1>${desc ? `<p class="desc">${desc}</p>` : ''}</div><div class="row">${right}</div></header>`;
}

// ----- 설정 -----

const STAGES = [['plan', '계획 (설정 제안, 문체 분석, 기승전결, 화별 플롯)'], ['write', '본문 쓰기'], ['check', '검수'], ['state', '상태 변경안']];

function providerOptions(cur) {
  return [['gemini', 'Gemini API'], ['local', '로컬 서버 (OpenAI 호환)'], ['mock', 'mock (AI 호출 없이 화면 확인용)']]
    .map(([v, l]) => `<option value="${v}"${cur === v ? ' selected' : ''}>${l}</option>`).join('');
}

function viewSettings() {
  const c = S.config || {};
  const src = { env: '환경 변수', file: '설정 파일', default: '기본값', none: '없음' };
  const envNote = (s, name) => s === 'env' ? `<div class="small">환경 변수 ${name} 가 설정돼 있어 그 값이 우선합니다.</div>` : '';
  const keyState = c.key_source === 'none'
    ? '<span class="chip" style="background:var(--red-soft);color:var(--red)">없음</span>'
    : `<span class="chip finalized">${esc(c.key_hint)}</span> <span class="small">${src[c.key_source]}</span>`;
  return `${header('Canon', '모델 · API 키 설정', '여기서 저장한 값은 이 컴퓨터의 설정 파일에만 들어갑니다. 작품 폴더나 저장소에는 들어가지 않아요.', '<a class="btn" href="javascript:history.back()">돌아가기</a>')}
    <section class="card">
      <div class="field"><label for="set-provider">생성 방식</label>
        <select id="set-provider">
          ${providerOptions(c.provider)}
        </select>${envNote(c.provider_source, 'CANON_LLM')}
        <div class="small">단계별로 다르게 쓰려면 아래 '단계별 백엔드'에서 고르세요.</div></div>
      <div class="field"><label for="set-key">Gemini API 키 <span class="hint">지금: </span>${keyState}</label>
        <input id="set-key" type="password" autocomplete="off" placeholder="${c.key_source === 'none' ? 'AIza… 로 시작하는 키' : '바꿀 때만 입력'}">
        <div class="small"><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>에서 무료로 발급받을 수 있어요. 저장한 키는 화면에 다시 보여주지 않습니다.</div>
        ${envNote(c.key_source, 'GEMINI_API_KEY')}</div>
      <div class="field"><label for="set-model">모델</label>
        <input id="set-model" type="text" list="model-list" value="${esc(c.model_setting || '')}">
        <datalist id="model-list"><option value="gemini-4-argon"></option><option value="gemini-2.5-pro"></option><option value="gemini-2.5-flash"></option></datalist>
        <div class="small">gemini-4-argon 이 기본입니다. 2.5 flash 는 빠르고 저렴합니다.</div>${envNote(c.model_source, 'CANON_MODEL')}</div>
      <h2 style="margin-top:18px">로컬 서버</h2>
      <p class="desc">Ollama, llama.cpp, vLLM, LM Studio 처럼 OpenAI 호환 API 를 여는 서버입니다. 주소는 /v1 까지 적습니다.</p>
      <div class="field"><label for="set-local-url">서버 주소</label>
        <input id="set-local-url" type="text" value="${esc(c.local_url || '')}" placeholder="http://localhost:11434/v1">
        <div class="small">Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1</div>${envNote(c.local_url_source, 'CANON_LOCAL_URL')}</div>
      <div class="field"><label for="set-local-model">모델 이름</label>
        <input id="set-local-model" type="text" value="${esc(c.local_model || '')}" placeholder="비우면 서버에 하나뿐인 모델">${envNote(c.local_model_source, 'CANON_LOCAL_MODEL')}</div>
      <div class="field"><label for="set-local-key">서버 키 <span class="hint">지금: ${c.has_local_key ? '있음' : '없음'}</span></label>
        <input id="set-local-key" type="password" autocomplete="off" placeholder="서버가 키를 요구할 때만"></div>
      <h2 style="margin-top:18px">단계별 백엔드</h2>
      <p class="desc">예: 계획과 검수는 Gemini, 본문은 로컬 모델.</p>
      ${STAGES.map(([s, label]) => {
        const st = (c.stages || {})[s] || {};
        return `<div class="field"><label for="set-stage-${s}">${label} <span class="hint">지금: ${esc(st.model || '')}</span></label>
          <select id="set-stage-${s}"><option value="">위 생성 방식을 따름</option>${providerOptions((c.stage_settings || {})[s])}</select>
          ${st.source === 'env' ? `<div class="small">환경 변수 CANON_LLM_${s.toUpperCase()} 가 우선합니다.</div>` : ''}</div>`;
      }).join('')}
      <div class="row">
        <button class="btn primary" data-action="saveSettings">저장</button>
        <button class="btn" data-action="testSettings">연결 확인</button>
        ${c.key_source === 'file' ? '<button class="btn danger" data-action="clearKey">저장된 키 지우기</button>' : ''}
      </div>
      <div class="small">설정 파일: ${esc(c.path)}</div>
    </section>`;
}

// ----- 작품 목록 -----

function viewProjects() {
  const list = S.projects || [];
  const cards = list.map((x) => `<a class="card tight" href="#/p/${enc(x.name)}" style="text-decoration:none;color:inherit">
      <div class="between"><h3>${esc(x.title || x.name)}</h3><span class="small">${x.finalized} / ${x.episodes}화</span></div>
      <div class="small">${esc(x.genre || '장르 미정')} · 폴더 ${esc(x.name)}</div>
    </a>`).join('');
  const cfg = S.config || {};
  return `${header('Canon', '작품', '인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편을 씁니다.', '<a class="btn" href="#/settings">모델 · API 키 설정</a>')}
    ${cfg.has_key ? '' : '<div class="note warn">Gemini API 키가 없어요. <a href="#/settings" style="color:inherit;font-weight:700">설정</a>에서 넣으면 AI 생성을 쓸 수 있습니다. 키 없이도 채팅 앱 작업지시서로 쓸 수 있어요.</div>'}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : '<div class="note plain">아직 작품이 없어요. 아래에서 새 작품을 만드세요.</div>'}
    <section class="card" style="max-width:720px">
      <h2>새 작품</h2>
      <div class="grid-2">
        <div class="field"><label for="np-name">폴더 이름 <span class="hint">projects/ 아래에 저장</span></label><input id="np-name" type="text" placeholder="lighthouse"></div>
        <div class="field"><label for="np-title">제목</label><input id="np-title" type="text" placeholder="등대"></div>
        <div class="field"><label for="np-genre">장르</label><input id="np-genre" type="text" placeholder="로맨스 판타지, 회귀" aria-describedby="np-genre-hint"><span id="np-genre-hint" class="small">쉼표로 여러 개. 설정 화면에서 목록으로 고를 수 있어요</span></div>
        <div class="field"><label for="np-eps">총 화수 (10~20)</label><input id="np-eps" type="number" min="10" max="20" value="12"></div>
      </div>
      <div class="field"><label for="np-logline">로그라인 <span class="hint">누가, 무엇을 원하고, 무엇이 막는가</span></label><textarea id="np-logline" rows="2"></textarea></div>
      <label class="check-row"><input id="np-adult" type="checkbox"><span><strong>성인물</strong> <span class="small">성인 독자 대상</span></span></label>
      <div><button class="btn primary" data-action="createProject">만들고 설정 시작</button></div>
    </section>`;
}

// ----- 작품 홈 -----

function nextStep() {
  const p = P();
  if (!p.characters.length) return ['설정 시작', base() + '/setup'];
  if (!p.arc.length || !p.episodes.length) return ['기승전결 · 플롯 만들기', base() + '/arc'];
  const e = ep(currentEp());
  if (e.status === 'draft') return [`${e.plot.number}화 플롯 확정`, base() + '/arc'];
  if (e.status === 'confirmed') return [`${e.plot.number}화 쓰기`, `${base()}/write/${e.plot.number}`];
  if (e.status === 'written') return [`${e.plot.number}화 상태 승인`, `${base()}/review/${e.plot.number}`];
  return ['완결 원고 보기', `${base()}/write/${e.plot.number}`];
}

function viewHome() {
  const p = P();
  const m = p.meta;
  const eps = p.episodes;
  const count = (st) => eps.filter((e) => e.status === st).length;
  const confirmed = eps.length - count('draft');
  const written = count('written') + count('finalized');
  const fin = count('finalized');
  const hasStyle = !!(p.style.narration_pov || p.style.sample_passages.length);
  const stage = (cls, st, title, sub, href) => `<a class="stage ${cls}" href="${href}"><div class="bar"></div><div class="st">${st}</div><div style="font-size:14px;font-weight:700">${title}</div><div class="small">${sub}</div></a>`;
  const state = (ok, partial) => (ok ? ['done', '완료'] : partial ? ['doing', '진행 중'] : ['', '시작 전']);
  const [s1c, s1t] = state(p.characters.length > 0);
  const [s2c, s2t] = state(hasStyle);
  const [s3c, s3t] = state(p.arc.length === 4);
  const [s4c, s4t] = state(eps.length && confirmed === m.target_episodes, confirmed > 0);
  const [s5c, s5t] = state(written === m.target_episodes, written > 0);
  const [s6c, s6t] = state(fin === m.target_episodes, fin > 0);
  const cur = currentEp();
  const [nextLabel, nextHref] = nextStep();

  const actBand = p.arc.length ? `<div class="act-band" style="display:grid;grid-template-columns:repeat(${m.target_episodes},minmax(0,1fr));gap:6px">${p.arc.map((a) => `<div class="act-head ${actClass(a.name)}" style="grid-column:span ${a.end_ep - a.start_ep + 1};padding:4px 8px;font-size:12px;font-weight:700">${a.name} ${a.start_ep}–${a.end_ep}화</div>`).join('')}</div>` : '';
  const cells = eps.map((e) => {
    const n = e.plot.number;
    const href = e.status === 'draft' ? base() + '/arc' : e.status === 'written' ? `${base()}/review/${n}` : `${base()}/write/${n}`;
    return `<a class="ep-cell ${e.status}${n === cur && e.status !== 'finalized' ? ' current' : ''}" href="${href}" title="${esc(e.plot.title)}"><strong>${n}</strong><span>${STATUS[e.status].replace('플롯 ', '').replace('본문 ', '')}</span></a>`;
  }).join('');

  const states = p.characters.map((c) => {
    const s = p.states.find((x) => x.character_id === c.id) || {};
    const lines = [['감정', s.emotional_state], ['목표', s.current_goal], ['위치', s.location]].filter(([, v]) => v);
    return `<div class="kv"><div style="font-size:14px;font-weight:700">${esc(c.name)} <span class="small" style="font-weight:400">${esc(c.role)}</span></div>${lines.map(([k, v]) => `<div class="line">${k}: ${esc(v)}</div>`).join('') || '<div class="line small">아직 변화 없음</div>'}</div>`;
  }).join('');
  const openFs = p.foreshadows.filter((f) => f.status === 'open');
  const lastWarn = p.history.length ? p.history[p.history.length - 1].warnings : [];

  return `${header(`${esc(m.genre || '장르 미정')}${m.adult ? ' · 성인' : ''} · 전 ${m.target_episodes}화 · 화당 ${Number(m.words_per_episode).toLocaleString()}자`, m.title || S.name, esc(m.logline), `<a class="btn" href="${base()}/arc">플롯 보드</a><a class="btn primary" href="${nextHref}">${esc(nextLabel)}</a>`)}
    <section class="card" aria-label="진행 단계"><div class="stages">
      ${stage(s1c, s1t, '1 설정', `인물 ${p.characters.length} · 관계 ${p.relationships.length}`, base() + '/setup')}
      ${stage(s2c, s2t, '2 문체', hasStyle ? `대표 문단 ${p.style.sample_passages.length}개` : '선택 사항', base() + '/style')}
      ${stage(s3c, s3t, '3 기승전결', p.arc.length ? '4구간' : '없음', base() + '/arc')}
      ${stage(s4c, s4t, '플롯 확정', `${confirmed} / ${m.target_episodes}화`, base() + '/arc')}
      ${stage(s5c, s5t, '4 집필', `${written} / ${m.target_episodes}화`, `${base()}/write/${cur}`)}
      ${stage(s6c, s6t, '5 상태 반영', `${fin} / ${m.target_episodes}화`, `${base()}/review/${cur}`)}
    </div></section>
    <section class="card">
      <div class="between"><h2>회차 진행</h2><div class="legend">
        <span><i style="background:var(--chip);border:1px solid var(--line-strong)"></i>플롯 초안</span>
        <span><i style="background:var(--accent)"></i>플롯 확정</span>
        <span><i style="background:var(--amber)"></i>본문 작성됨</span>
        <span><i style="background:var(--green)"></i>반영 완료</span></div></div>
      ${eps.length ? `${actBand}<div class="ep-grid" style="grid-template-columns:repeat(${m.target_episodes},minmax(0,1fr))">${cells}</div>` : `<div class="note plain">아직 화별 플롯이 없어요. <a href="${base()}/arc">기승전결 · 플롯</a>에서 만드세요.</div>`}
      ${eps.some((e) => e.status === 'written') ? `<div class="note warn">${cur}화 본문이 작성됐습니다. 상태 변경안을 승인해야 다음 화를 쓸 수 있어요. <a href="${base()}/review/${cur}" style="color:inherit;font-weight:700">${cur}화 변경안 검토</a></div>` : ''}
    </section>
    <div class="grid-auto">
      <section class="card"><div class="between"><h2>인물 현재 상태</h2><span class="small">${fin ? fin + '화 기준' : '시작 시점'}</span></div>${states || '<div class="small">인물이 없습니다</div>'}<a href="${base()}/setup" style="font-size:13px">인물 · 관계 전체 보기</a></section>
      <section class="card">${relationHeader('관계')}${p.relationships.length ? relationLines(S.relations) : '<div class="small">관계가 없어요. 설정 도우미에서 관계를 추가하세요.</div>'}</section>
      <section class="card"><div class="between"><h2>열린 복선</h2><span class="small">${openFs.length}개</span></div>
        ${openFs.map((f) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap"><span class="chip">${f.planted_ep}화</span><div style="font-size:13px;line-height:1.5">${esc(f.description)}<br><span class="small">${esc(f.id)}</span></div></div>`).join('') || '<div class="small">없음</div>'}
      </section>
      <section class="card"><div class="between"><h2>확정 사실</h2><span class="small">${p.facts.length}개</span></div>
        ${p.facts.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;color:var(--text-2)">${p.facts.slice(-8).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '<div class="small">없음</div>'}
        ${lastWarn.length ? `<div class="note warn">최근 경고: ${lastWarn.map(esc).join(' / ')}</div>` : ''}
      </section>
    </div>`;
}

// ----- 장르 -----

function genreById(id) {
  return (S.genres || []).find((g) => g.id === id);
}

function genreLabel(m) {
  return m.genres.map((id) => (genreById(id) ? genreById(id).name : id)).join(' · ') || m.genre || '';
}

function syncGenre() {
  const m = P().meta;
  m.genre = genreLabel(m);
  markDirty();
  render();
}

function genreGuide(g) {
  const row = (k, v) => (v && v.length ? `<div class="g-row"><span class="g-k">${k}</span><span>${esc(Array.isArray(v) ? v.join(', ') : v)}</span></div>` : '');
  return `<details class="genre-guide"><summary><strong>${esc(g.name)}</strong><div class="small">${esc(g.summary)}</div></summary>
    ${row('독자가 기대하는 것', g.reader_expects)}${row('관습', g.conventions)}${row('자주 쓰는 소재', g.tropes)}${row('전개 속도', g.pacing)}${row('피할 것', g.avoid)}</details>`;
}

function genrePicker() {
  const m = P().meta;
  const cat = S.genres || [];
  const opts = (kind) => cat.filter((g) => g.kind === kind).map((g) => `<button type="button" aria-pressed="${m.genres.includes(g.id)}" data-action="toggleGenre" data-arg="${esc(g.id)}" title="${esc(g.summary)}">${esc(g.name)}</button>`).join('');
  const custom = m.genres.filter((id) => !genreById(id));
  const picked = m.genres.map(genreById).filter(Boolean);
  return `<div class="field"><span class="label-text">장르 <span class="hint">여러 개 고를 수 있어요. 고른 장르의 안내가 AI 프롬프트에 들어갑니다</span></span>
      <div class="genre-opts" role="group" aria-label="장르">${opts('장르')}</div>
      <div class="small" style="margin-top:4px">요소</div>
      <div class="genre-opts" role="group" aria-label="요소">${opts('요소')}${custom.map((c) => `<button type="button" aria-pressed="true" data-action="toggleGenre" data-arg="${esc(c)}" title="직접 적은 장르, 누르면 빠집니다">${esc(c)} ✕</button>`).join('')}</div>
      <div class="row" style="flex-wrap:nowrap"><input id="genre-custom" type="text" aria-label="직접 적는 장르" placeholder="목록에 없으면 직접 적기 (예: 오컬트)"><button type="button" class="btn small" style="white-space:nowrap;flex:none" data-action="addCustomGenre">추가</button></div>
    </div>
    ${picked.length ? `<div class="genre-guides">${picked.map(genreGuide).join('')}</div>` : ''}
    <label class="check-row"><input type="checkbox" data-bind="meta.adult" data-kind="bool"${m.adult ? ' checked' : ''}><span><strong>성인물</strong> <span class="small">성인 독자 대상. 끄면 노골적인 성적 묘사와 과도한 잔혹 묘사를 피하도록 지시합니다</span></span></label>`;
}

// ----- 1. 설정 도우미 -----

function viewSetup() {
  const p = P();
  const chars = p.characters.map((c, i) => {
    const b = `characters.${i}`;
    return `<article class="char-card">
      <div class="between"><strong style="font-size:16px">${esc(c.name || '이름 없음')}</strong><button class="btn small danger" data-action="removeCharacter" data-arg="${i}" aria-label="${esc(c.name || c.id)} 삭제">삭제</button></div>
      <div class="grid-2">${input('이름', b + '.name')}${input('id', b + '.id', { hint: '영문 소문자' })}${input('역할', b + '.role')}${input('나이', b + '.age')}</div>
      ${input('목표', b + '.goal')}
      ${input('말투', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 예시' })}
      <details><summary>성격, 배경, 결핍, 비밀, 아크</summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
        ${input('성격', b + '.personality', { rows: 2 })}${input('배경', b + '.background', { rows: 2 })}${input('외모', b + '.appearance')}
        ${input('결핍 · 약점', b + '.wound')}${input('비밀', b + '.secrets', { kind: 'list', rows: 2 })}${input('아크', b + '.arc', { hint: '시작 → 결말' })}
      </div></details>
    </article>`;
  }).join('');

  const opts = (sel) => p.characters.map((c) => `<option value="${esc(c.id)}"${c.id === sel ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('');
  const started = p.snapshots.length > 0; // 첫 상태 반영 뒤에는 관계 사건으로 계산한다
  const rels = p.relationships.map((r, i) => {
    const b = `relationships.${i}`;
    return `<div class="rel-row">
      <div class="field"><label for="ra${i}">인물 A</label><select id="ra${i}" data-bind="${b}.a">${opts(r.a)}</select></div>
      <div class="field"><label for="rb${i}">인물 B</label><select id="rb${i}" data-bind="${b}.b">${opts(r.b)}</select></div>
      ${input('유형', b + '.type', { placeholder: '동료, 남매…' })}
      ${started
        ? `<div class="field"><label>지금</label><div class="small" style="padding-top:10px">호감 ${r.affinity} · 긴장 ${r.tension}</div></div>`
        : `<div class="field"><label for="raf${i}">시작 호감 <output id="raf${i}o">${r.affinity}</output></label><input id="raf${i}" type="range" min="-5" max="5" value="${r.affinity}" data-bind="${b}.affinity" data-kind="int" data-out="raf${i}o"></div>`}
      <div class="field"><label for="rg${i}">목표 충돌 <output id="rg${i}o">${r.goal_conflict || 0}</output></label><input id="rg${i}" type="range" min="0" max="1" step="0.1" value="${r.goal_conflict || 0}" data-bind="${b}.goal_conflict" data-kind="float" data-out="rg${i}o"></div>
      <button class="btn icon-btn danger" data-action="removeRelationship" data-arg="${i}" aria-label="관계 삭제">✕</button>
    </div>`;
  }).join('');

  return `${header('1단계', '설정 도우미', '채운 칸은 그대로 두고, 빈칸만 AI 가 제안합니다. 제안에서 원하는 인물과 관계만 골라 반영하세요.', `<button class="btn" data-action="suggest">빈칸 AI 제안받기</button><a class="btn primary" href="${base()}/style">문체로</a>`)}
    ${S.suggestion ? viewSuggestion() : ''}
    <div class="cols">
      <div class="col">
        <section class="card">
          <h2>기본 정보</h2>
          ${input('제목', 'meta.title')}
          ${genrePicker()}
          ${input('총 화수 (10~20)', 'meta.target_episodes', { type: 'number', min: 1, max: 40 })}
          ${input('로그라인', 'meta.logline', { rows: 3, hint: '누가, 무엇을 원하고, 무엇이 막는가' })}
          ${input('주제', 'meta.theme')}${input('톤', 'meta.tone')}
          ${input('화당 분량', 'meta.words_per_episode', { type: 'number', hint: '공백 포함 글자 수' })}
          ${input('메모', 'meta.notes', { rows: 2 })}
        </section>
        <section class="card">
          <h2>세계관</h2>
          ${input('배경', 'world.setting', { rows: 2 })}${input('시대', 'world.era')}
          ${input('깨면 안 되는 규칙', 'world.rules', { kind: 'list' })}${input('장소', 'world.locations', { kind: 'list' })}
        </section>
      </div>
      <div class="col wide">
        <section class="card">
          <div class="between"><h2>인물 <span class="small">${p.characters.length}명</span></h2><button class="btn small" data-action="addCharacter">+ 인물 추가</button></div>
          <p class="small">이름, 말투, 성격은 고정 설정입니다. 회차가 지나며 바뀌는 감정과 목표는 상태 승인 화면에서 관리합니다.</p>
          ${chars ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px">${chars}</div>` : '<div class="note plain">인물이 없어요. 직접 추가하거나 AI 제안을 받으세요.</div>'}
        </section>
        <section class="card">
          <div class="between"><h2>관계</h2><div class="row"><span class="small">${P().snapshots.length ? '첫 반영 뒤에는 관계 사건으로 계산됩니다' : '시작 호감 -5 ~ 5 · 목표 충돌 0 ~ 1 · 긴장은 자동 계산'}</span><button class="btn small" data-action="addRelationship">+ 관계 추가</button></div></div>
          ${rels || '<div class="small">관계가 없어요.</div>'}
        </section>
      </div>
    </div>`;
}

function viewSuggestion() {
  const s = S.suggestion;
  const exists = (id) => P().characters.some((c) => c.id === id);
  return `<section class="card" style="border:2px solid var(--accent)">
    <div class="between"><h2>AI 제안 <span class="chip ai">반영 전</span></h2><div class="row"><button class="btn small" data-action="dropSuggestion">버리기</button><button class="btn small primary" data-action="applySuggestion">선택 항목 반영</button></div></div>
    <p class="small">주제, 톤, 세계관은 비어 있는 칸에만 들어갑니다. 이미 있는 인물 id 는 건너뜁니다.</p>
    <div class="grid-2"><div class="note plain"><strong>주제</strong> ${esc(s.theme)}<br><strong>톤</strong> ${esc(s.tone)}</div><div class="note plain"><strong>배경</strong> ${esc(s.world.setting)} ${esc(s.world.era)}<br><strong>규칙</strong> ${s.world.rules.map(esc).join(', ')}</div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">
      ${s.characters.map((c, i) => `<label class="char-card suggested" style="cursor:pointer"><span class="row"><input type="checkbox" data-pick="sc${i}"${S.picks['sc' + i] ? ' checked' : ''}${exists(c.id) ? ' disabled' : ''}><strong>${esc(c.name)}</strong><span class="small">${esc(c.role)} · ${esc(c.id)}${exists(c.id) ? ' · 이미 있음' : ''}</span></span>
        <span style="font-size:13px;line-height:1.5">목표: ${esc(c.goal)}<br>말투: ${esc(c.speech_style)}</span></label>`).join('')}
    </div>
    ${s.relationships.map((r, i) => `<label class="row" style="font-size:13px"><input type="checkbox" data-pick="sr${i}"${S.picks['sr' + i] ? ' checked' : ''}>${esc(r.a)} ↔ ${esc(r.b)} · ${esc(r.type)} · 호감 ${r.affinity} · 긴장 ${r.tension}</label>`).join('')}
  </section>`;
}

// ----- 2. 문체 -----

function viewStyle() {
  const st = P().style;
  const passages = st.sample_passages.map((_, i) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap">
      <div style="flex:1">${input(`대표 문단 ${i + 1}`, `style.sample_passages.${i}`, { rows: 3 })}</div>
      <button class="btn icon-btn danger" style="margin-top:26px" data-action="removePassage" data-arg="${i}" aria-label="대표 문단 ${i + 1} 삭제">✕</button></div>`).join('');
  return `${header('2단계', '문체 레퍼런스', '닮고 싶은 소설 문단을 붙여 넣으면 문체 규칙을 뽑습니다. 규칙과 원문 예시가 매 화 본문 생성에 함께 들어갑니다.', `<a class="btn primary" href="${base()}/arc">기승전결로</a>`)}
    <div class="cols">
      <section class="card col">
        <div class="between"><h2>예시 원문</h2><span class="small"><span id="sample-count">${S.styleSample.length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
        <label for="sample" class="small">소설 본문을 붙여 넣으세요. 원문은 저장되지 않고, 고른 대표 문단만 남습니다.</label>
        <textarea id="sample" rows="16" data-local="styleSample" oninput="document.getElementById('sample-count').textContent=this.value.length.toLocaleString()" style="font-family:var(--serif);font-size:15px;line-height:1.9">${esc(S.styleSample)}</textarea>
        <div><button class="btn dark" data-action="analyzeStyle">문체 분석</button></div>
        <div class="note plain">원문은 문체 분석과 예시 문단으로만 쓰입니다. 내용이나 인물은 작품에 가져오지 않습니다.</div>
      </section>
      <section class="card col wide">
        <div class="between"><h2>스타일 프로필</h2><span class="small">모든 칸은 직접 고칠 수 있어요</span></div>
        <div class="grid-2">
          ${input('시점', 'style.narration_pov')}${input('시제', 'style.tense')}
          ${input('문장 리듬', 'style.sentence_rhythm', { rows: 2 })}${input('묘사 밀도', 'style.description_density', { rows: 2 })}
          ${input('대사 비율', 'style.dialogue_ratio')}${input('대사 방식', 'style.dialogue_style')}
          ${input('내면 독백', 'style.inner_monologue')}${input('전개 속도', 'style.pacing')}
          ${input('장면 전환', 'style.scene_transition')}${input('어휘', 'style.vocabulary')}
        </div>
        <div class="grid-2">
          <div class="note ok">${input('지킬 것', 'style.dos', { kind: 'list', rows: 4 })}</div>
          <div class="note err">${input('피할 것', 'style.donts', { kind: 'list', rows: 4 })}</div>
        </div>
        <div class="between"><h3>대표 문단 <span class="small" style="font-weight:400">본문 생성 때 그대로 보여줄 원문 예시, 2~4개</span></h3><button class="btn small" data-action="addPassage">+ 문단</button></div>
        ${passages || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 넣습니다.</div>'}
      </section>
    </div>`;
}

// ----- 3. 기승전결 · 플롯 -----

function viewArc() {
  const p = P();
  const eps = p.episodes;
  if (S.selEp && !ep(S.selEp)) S.selEp = null;
  const sel = S.selEp ? ep(S.selEp) : null;
  const card = (e) => `<button type="button" class="ep-card ${e.status}${sel && sel.plot.number === e.plot.number ? ' sel' : ''}" data-action="selectEp" data-arg="${e.plot.number}">
      <span class="between" style="width:100%"><strong style="font-size:13px">${e.plot.number}화</strong><span class="chip ${e.status}">${STATUS[e.status]}</span></span>
      <span class="t">${esc(e.plot.title)}</span><span class="s">${esc(e.plot.summary)}</span></button>`;

  let board;
  if (!p.arc.length) {
    board = `<div class="card empty"><p>아직 기승전결 구조가 없어요.</p><button class="btn primary" data-action="planArc">AI 로 구조 만들기</button></div>`;
  } else {
    const spans = p.arc.map((a) => Math.max(1, a.end_ep - a.start_ep + 1));
    const cols = p.arc.map((a, i) => {
      const b = `arc.${i}`;
      const inAct = eps.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
      return `<section class="act-col"><div class="act-head ${actClass(a.name)}">
          <strong>${a.name}</strong><span class="act-range"><input type="number" aria-label="${a.name} 시작 화" value="${a.start_ep}" data-bind="${b}.start_ep" data-kind="int">–<input type="number" aria-label="${a.name} 끝 화" value="${a.end_ep}" data-bind="${b}.end_ep" data-kind="int">화</span>
          <textarea rows="2" aria-label="${a.name} 구간 목표" data-bind="${b}.goal" placeholder="구간 목표">${esc(a.goal)}</textarea>
          <textarea rows="2" aria-label="${a.name} 전환점" data-bind="${b}.key_turn" placeholder="전환점">${esc(a.key_turn)}</textarea>
        </div>${inAct.map(card).join('')}</section>`;
    }).join('');
    board = `<div class="board-wrap"><div class="board" style="grid-template-columns:${spans.map((s) => `minmax(160px,${s}fr)`).join(' ')}">${cols}</div></div>`;
  }

  const drafts = eps.filter((e) => e.status === 'draft').length;
  const right = p.arc.length
    ? `<button class="btn" data-action="planArc">구조 다시 제안</button><button class="btn" data-action="draftPlots">${eps.length ? '초안 다시 만들기 (확정 화 제외)' : '화별 플롯 초안 만들기'}</button>${drafts ? `<button class="btn primary" data-action="confirmAll">초안 ${drafts}화 모두 확정</button>` : ''}`
    : '';
  return `${header('3단계', '기승전결 · 화별 플롯', '구간 범위와 목표를 고치고, 화 카드를 눌러 플롯을 다듬은 뒤 확정하세요. 확정된 화만 본문을 쓸 수 있고, 초안을 다시 만들어도 확정된 화는 그대로입니다.', right)}
    <div class="cols">${board}${sel ? `<aside class="card editor-panel" aria-label="${sel.plot.number}화 플롯 편집">${plotEditor(sel)}</aside>` : (eps.length ? '<aside class="card editor-panel note plain">화 카드를 누르면 여기서 플롯을 고칠 수 있어요.</aside>' : '')}</div>`;
}

function plotEditor(e) {
  const n = e.plot.number;
  const i = epIndex(n);
  const b = `episodes.${i}.plot`;
  const locked = e.status === 'written' || e.status === 'finalized';
  const ro = { readonly: locked };
  const cast = P().characters.map((c) => `<label class="row" style="font-size:13px;gap:6px"><input type="checkbox" value="${esc(c.id)}" data-cast-ep="${n}"${e.plot.characters.includes(c.id) ? ' checked' : ''}${locked ? ' disabled' : ''}>${esc(c.name || c.id)}</label>`).join('');
  const act = actOf(n);
  return `<div class="between"><h2>${n}화 플롯</h2><span class="chip ${e.status}">${STATUS[e.status]}</span></div>
    ${act ? `<div class="note info"><strong>${act.name} 구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
    ${locked ? '<div class="note plain">본문이 있는 화라 플롯을 고칠 수 없어요.</div>' : ''}
    ${input('제목', b + '.title', ro)}
    ${input('요약', b + '.summary', { ...ro, rows: 3 })}
    ${input('사건 순서', b + '.events', { ...ro, kind: 'list', rows: 5 })}
    <div class="field"><span class="label">등장 인물</span><div class="row">${cast}</div></div>
    ${input('감정 변화', b + '.emotional_shift', ro)}
    ${input('엔딩 훅', b + '.ending_hook', ro)}
    <div class="grid-2">${input('심을 복선', b + '.foreshadow_plant', { ...ro, kind: 'list', rows: 2 })}${input('회수할 복선 id', b + '.foreshadow_payoff', { ...ro, kind: 'list', rows: 2 })}</div>
    <div class="row">
      ${e.status === 'draft' ? `<button class="btn primary" style="flex:1" data-action="confirmEp" data-arg="${n}">${n}화 확정</button>` : ''}
      ${e.status === 'confirmed' ? `<button class="btn" style="flex:1" data-action="unconfirmEp" data-arg="${n}">초안으로 되돌리기</button><a class="btn primary" style="flex:1" href="${base()}/write/${n}">${n}화 쓰기</a>` : ''}
      ${locked ? `<a class="btn" style="flex:1" href="${base()}/write/${n}">본문 보기</a>` : ''}
    </div>`;
}

// ----- 4. 집필 -----

function epNav(page, n) {
  const nums = P().episodes.map((e) => e.plot.number);
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const arrow = (to, label, d) => to ? `<a class="btn icon-btn" href="${base()}/${page}/${to}" aria-label="${label}"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="${d}"></path></svg></a>` : `<span class="btn icon-btn" aria-hidden="true" style="opacity:.35">·</span>`;
  return `<nav class="row" aria-label="회차 이동" style="gap:4px">${arrow(prev, '이전 화', 'M10 3 5 8l5 5')}${arrow(next, '다음 화', 'm6 3 5 5-5 5')}</nav>`;
}

function noEpisode() {
  return `<div class="card empty"><p>아직 화별 플롯이 없어요.</p><a class="btn primary" href="${base()}/arc">기승전결 · 플롯 만들기</a></div>`;
}

function viewWrite(n) {
  const e = ep(n);
  if (!e) return header('4단계', '집필', '') + noEpisode();
  const act = actOf(n);
  const blocked = P().episodes.filter((x) => x.plot.number < n && x.status !== 'finalized').map((x) => x.plot.number);
  const draft = S.textDraft[n];
  const text = draft ?? e.text;
  const editable = e.status === 'confirmed' || e.status === 'written';
  const isApi = S.mode === 'api';

  let center;
  if (e.status === 'draft') {
    center = `<div class="empty"><p>${n}화 플롯이 아직 초안이에요. 확정해야 쓸 수 있습니다.</p><a class="btn primary" href="${base()}/arc">플롯 확정하러 가기</a></div>`;
  } else if (!e.text && draft === undefined) {
    center = `<div class="empty">
      ${blocked.length ? `<div class="note warn">이전 화(${blocked.join(', ')}화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙입니다.</div>` : ''}
      ${isApi ? `<p>확정된 플롯과 지금까지의 데이터로 ${n}화를 씁니다.</p><button class="btn primary" data-action="writeEp" data-arg="${n}"${blocked.length ? ' disabled' : ''}>${n}화 본문 생성</button>`
        : `<p>작업지시서를 채팅 앱에 붙여 넣고, 받은 본문을 가져오세요.</p><a class="btn primary" href="${base()}/brief/${n}">작업지시서 열기</a>`}
      <button class="btn" data-action="startManual" data-arg="${n}">직접 쓰기</button>
    </div>`;
  } else {
    center = `<div class="prose">${editable
      ? `<textarea aria-label="${n}화 본문" data-draft="${n}" placeholder="여기에 본문을 쓰세요">${esc(text)}</textarea>`
      : `<div class="read">${esc(text)}</div>`}</div>`;
  }

  const ctx = S.context ? `<ol class="panel-list">${S.context.map((c) => `<li><span>${esc(c.title)}</span><span class="small">${c.chars.toLocaleString()}자</span></li>`).join('')}</ol>
      <div class="small">합계 ${S.context.reduce((s, c) => s + c.chars, 0).toLocaleString()}자. 이전 본문 전체 대신 이 데이터만 매번 같은 순서로 넣습니다.</div>` : '<div class="small">플롯을 확정하면 보입니다.</div>';

  const right = `${e.status !== 'finalized' ? `<div class="seg" role="group" aria-label="생성 방식"><button type="button" aria-pressed="${isApi}" data-action="setMode" data-arg="api">Gemini API</button><button type="button" aria-pressed="${!isApi}" data-action="setMode" data-arg="brief">채팅 앱 작업지시서</button></div>` : ''}
    ${e.text && editable && isApi ? `<button class="btn" data-action="writeEp" data-arg="${n}">다시 생성</button>` : ''}
    ${editable && !isApi ? `<a class="btn" href="${base()}/brief/${n}">작업지시서</a>` : ''}
    ${e.status === 'written' ? `<a class="btn primary" href="${base()}/review/${n}">상태 정리로</a>` : ''}`;

  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('write', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${act ? act.name + ' 구간 · ' : ''}${n} / ${P().meta.target_episodes}화</div><h1 style="font-size:24px">${n}화 ${esc(e.plot.title)}</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>
    <div class="cols" style="gap:16px">
      <aside class="card tight" style="flex:1 1 260px;min-width:0" aria-label="이번 화 플롯">
        <h3>이번 화 플롯</h3>
        ${act ? `<div class="note info"><strong>구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
        <p style="font-size:13px;line-height:1.6;color:var(--text-2)">${esc(e.plot.summary)}</p>
        <div class="field"><span class="small">사건</span><ol style="padding-left:20px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.5">${e.plot.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></div>
        <div class="field"><span class="small">등장 인물</span><div style="font-size:13px">${e.plot.characters.map(charName).map(esc).join(', ')}</div></div>
        <div class="field"><span class="small">감정 변화</span><div style="font-size:13px">${esc(e.plot.emotional_shift)}</div></div>
        <div class="field"><span class="small">엔딩 훅</span><div style="font-size:13px">${esc(e.plot.ending_hook)}</div></div>
        ${e.summary ? `<div class="field"><span class="small">승인된 요약</span><div style="font-size:13px;line-height:1.6">${esc(e.summary)}</div></div>` : ''}
        <a href="${base()}/arc" data-action="gotoPlot" data-arg="${n}" style="font-size:13px">플롯 보기</a>
      </aside>
      <section class="card" style="flex:3 1 520px;min-width:0;padding:0;gap:0" aria-label="본문">
        <div class="between" style="padding:10px 16px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)">
          <span>${e.status === 'finalized' ? '상태 반영까지 끝난 화는 읽기 전용입니다' : '본문을 직접 고친 뒤 저장할 수 있어요'}</span>
          <span class="row"><span><strong id="char-count" style="color:var(--text)">${(text || '').length.toLocaleString()}</strong> / ${Number(P().meta.words_per_episode).toLocaleString()}자</span>
          ${editable && (e.text || draft !== undefined) ? `<button class="btn small" id="save-text" data-action="saveText" data-arg="${n}"${draft === undefined ? ' disabled' : ''}>본문 저장</button>` : ''}</span>
        </div>
        ${center}
      </section>
      <aside class="card tight" style="flex:1 1 260px;min-width:0" aria-label="AI 에게 보내는 컨텍스트">
        <h3>AI 에게 보내는 컨텍스트</h3>
        ${ctx}
        ${S.context ? `<button class="btn small" data-action="togglePrompt" data-arg="${n}">${S.promptText ? '프롬프트 닫기' : '프롬프트 원문 보기'}</button>` : ''}
        ${S.promptText ? `<pre class="brief mono" style="max-height:420px">${esc(S.promptText)}</pre>` : ''}
      </aside>
    </div>`;
}

// ----- 5. 상태 승인 -----

function viewReview(n) {
  const e = ep(n);
  if (!e) return header('5단계', '상태 변경안 승인', '') + noEpisode();
  const top = (desc, right = '') => `<header class="page-head"><div class="row" style="gap:12px">${epNav('review', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)}</div><h1 style="font-size:24px">상태 변경안 승인</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>${desc ? `<p class="desc">${desc}</p>` : ''}`;

  if (e.status === 'finalized') {
    const h = [...P().history].reverse().find((d) => d.episode === n);
    return top('이 화는 상태 반영이 끝났어요. 반영된 내용입니다.') + (h ? historyView(h) : '<div class="note plain">반영 기록이 없습니다.</div>');
  }
  if (e.status !== 'written') {
    return top('') + `<div class="card empty"><p>${n}화 본문이 아직 없어요. 본문을 쓴 뒤 상태를 정리합니다.</p><a class="btn primary" href="${base()}/write/${n}">${n}화 집필로</a></div>`;
  }
  const d = S.deltas[n];
  if (!d) {
    return top('AI 가 본문에서 인물 상태, 관계, 확정 사실, 복선을 뽑아 변경안을 만듭니다. 승인한 항목만 데이터에 반영됩니다.') +
      `<div class="cols"><section class="card col"><h2>AI 로 뽑기</h2><p class="desc">${esc(S.config && S.config.stages ? S.config.stages.state.model : '')} 로 ${n}화 본문을 읽고 변경안을 만듭니다.</p><div><button class="btn primary" data-action="extractState" data-arg="${n}">변경안 만들기</button></div></section>
       <section class="card col"><h2>채팅 앱에서 받은 JSON</h2><p class="desc">상태 정리 지시서를 채팅 앱에 붙여 넣고 받은 JSON 을 가져옵니다.</p><div><a class="btn" href="${base()}/brief/${n}" data-action="openStateBrief" data-arg="${n}">상태 정리 지시서 열기</a></div></section></div>`;
  }

  const p = P();
  const total = d.character_updates.length + d.events.length + d.secrets_added.length + d.relationship_updates.length + d.new_facts.length + d.foreshadow_planted.length + d.foreshadow_resolved.length;
  if (!S.preview || S.preview.n !== n) refreshPreview(n);
  const picked = Object.values(S.picks).filter(Boolean).length;
  const box = (key) => `<input type="checkbox" id="pk-${key}" data-pick="${key}"${S.picks[key] ? ' checked' : ''}>`;
  const diff = (before, after) => before && before !== after
    ? `<div class="row"><span class="before">${esc(before)}</span><span class="small">→</span><span class="after">${esc(after)}</span></div>`
    : `<div class="row"><span class="after">${esc(after)}</span></div>`;

  const chars = d.character_updates.map((u, i) => {
    const cur = p.states.find((s) => s.character_id === u.character_id) || {};
    const rows = [['감정', 'emotional_state'], ['목표', 'current_goal'], ['위치', 'location'], ['메모', 'notes']]
      .filter(([, f]) => u[f]).map(([k, f]) => `<div class="small">${k}</div>${diff(cur[f], u[f])}`).join('');
    const knows = u.knows.filter((k) => !(cur.knows || []).includes(k)).map((k) => `<span class="after">+ ${esc(k)}</span>`).join(' ');
    return `<div class="change">${box('c' + i)}<div class="body"><label for="pk-c${i}" style="font-size:14px;font-weight:700">${esc(charName(u.character_id))}</label>${rows}${knows ? `<div class="small">알게 된 정보</div><div class="row">${knows}</div>` : ''}</div></div>`;
  }).join('');

  const events = d.events.map((ev, i) => {
    const good = GOOD_EVENTS.includes(ev.kind);
    const wit = ev.witnesses.length ? ` · 목격: ${ev.witnesses.map(charName).map(esc).join(', ')}` : '';
    const sec = ev.reveals_secret ? ` · 드러난 비밀: ${esc(secretLabel(ev.reveals_secret, d))}` : '';
    return `<div class="change">${box('e' + i)}<div class="body"><label for="pk-e${i}" style="font-size:14px;font-weight:700">${esc(charName(ev.actor))} → ${esc(charName(ev.target))}
        <span class="chip" style="background:${good ? 'var(--green-soft)' : 'var(--red-soft)'};color:${good ? 'var(--green)' : 'var(--red)'}">${esc(ev.kind)}</span> <span class="small" style="font-weight:400">${INTENSITY[ev.intensity] || ev.intensity}${wit}${sec}</span></label>
      ${ev.quote ? `<div style="font-family:var(--serif);font-size:13px;line-height:1.7;color:var(--text-2)">“${esc(ev.quote)}”</div>` : ''}</div></div>`;
  }).join('');
  const secrets = d.secrets_added.map((x, i) => `<div class="change">${box('s' + i)}<label for="pk-s${i}" style="font-size:13px;line-height:1.55"><strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}<br><span class="small">모르는 인물: ${x.hidden_from.map(charName).map(esc).join(', ') || '없음'}</span></label></div>`).join('');
  const rels = d.relationship_updates.map((r, i) => {
    const cur = p.relationships.find((x) => (x.a === r.a && x.b === r.b) || (x.a === r.b && x.b === r.a));
    return `<div class="change">${box('r' + i)}<div class="body"><label for="pk-r${i}" style="font-size:14px;font-weight:700">${esc(charName(r.a))} ↔ ${esc(charName(r.b))}</label>
      ${diff(cur && cur.type, r.type)}${r.description ? diff(cur && cur.description, r.description) : ''}</div></div>`;
  }).join('');

  const facts = d.new_facts.map((f, i) => `<div class="change">${box('f' + i)}<label for="pk-f${i}" style="font-size:13px;line-height:1.55">${esc(f)}</label></div>`).join('');
  const fs = [
    ...d.foreshadow_planted.map((f, i) => `<div class="change">${box('p' + i)}<label for="pk-p${i}" style="font-size:13px;line-height:1.55"><span class="chip confirmed">심음</span> ${esc(f.description)} <span class="small">${esc(f.id)}</span></label></div>`),
    ...d.foreshadow_resolved.map((id, i) => {
      const f = p.foreshadows.find((x) => x.id === id);
      return `<div class="change">${box('x' + i)}<label for="pk-x${i}" style="font-size:13px;line-height:1.55"><span class="chip finalized">회수</span> ${esc(f ? f.description : id)} ${f ? `<span class="small">${f.planted_ep}화에 심음</span>` : '<span class="small">알 수 없는 id</span>'}</label></div>`;
    }),
  ].join('');
  const section = (title, body) => `<section class="card"><h2>${title}</h2>${body || '<div class="small">변경 없음</div>'}</section>`;

  return top('AI 가 본문에서 뽑은 변경안입니다. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요.', `<span class="small">${total}건 중 <strong id="pick-count" style="color:var(--text)">${picked}</strong>건 선택</span>`) +
    (d.warnings.length ? `<section class="note warn" role="alert"><strong>경고 ${d.warnings.length}건 · 본문을 고칠지 확인하세요</strong><ul style="padding-left:18px;margin-top:6px">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul><a href="${base()}/write/${n}" style="color:inherit;font-weight:700">본문으로</a></section>` : '') +
    section('인물 상태', chars) +
    `<div class="cols">
      <section class="card col"><div class="between"><h2>관계 사건</h2><span class="small">AI 는 사건만 적고, 관계 수치는 Canon 이 계산합니다</span></div>${events || '<div class="small">이번 화에 관계 사건이 없어요</div>'}
        ${secrets ? `<h3 style="margin-top:6px">새로 생긴 비밀</h3>${secrets}` : ''}
        ${rels ? `<h3 style="margin-top:6px">관계 유형 · 설명 변경</h3>${rels}` : ''}</section>
      <section class="card col">${relationHeader('반영하면 이렇게 계산됩니다')}<div id="rel-preview">${relationLines(S.preview && S.preview.n === n ? S.preview : null)}</div>
        <div class="small">체크를 바꾸면 바로 다시 계산합니다. 저장은 반영할 때만 됩니다.</div></section>
    </div>` +
    `<div class="grid-auto">${section('확정 사실', facts)}${section('복선', fs)}</div>` +
    `<section class="card"><div class="between"><label for="dsum" style="font-size:16px;font-weight:700">${n}화 요약</label><span class="small">다음 화 생성에 이 요약이 들어갑니다</span></div>
      <textarea id="dsum" rows="4" data-delta-summary="${n}">${esc(d.summary)}</textarea></section>
    <div class="between"><div class="row"><button class="btn" data-action="extractState" data-arg="${n}">다시 추출</button><button class="btn" data-action="dropDelta" data-arg="${n}">버리기</button><a class="btn" href="${base()}/write/${n}">본문으로</a></div>
      <button class="btn primary" data-action="applyDelta" data-arg="${n}">선택한 항목 반영하고 ${n}화 완료</button></div>`;
}

function historyView(h) {
  const li = (arr) => arr.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.5">${arr.map((x) => `<li>${x}</li>`).join('')}</ul>` : '<div class="small">없음</div>';
  return `<section class="card"><h2>요약</h2><p style="font-size:14px;line-height:1.7">${esc(h.summary)}</p></section>
    <div class="grid-auto">
      <section class="card"><h2>인물 상태</h2>${li(h.character_updates.map((u) => `<strong>${esc(charName(u.character_id))}</strong> ${esc([u.emotional_state, u.current_goal, u.location].filter(Boolean).join(' / '))}${u.knows.length ? ` · 앎: ${esc(u.knows.join(', '))}` : ''}`))}</section>
      <section class="card"><h2>관계 사건</h2>${li((h.events || []).map((ev) => `${esc(charName(ev.actor))} → ${esc(charName(ev.target))} · ${esc(ev.kind)} ${INTENSITY[ev.intensity] || ''}${ev.quote ? `<br><span class="small">“${esc(ev.quote)}”</span>` : ''}`))}</section>
      <section class="card"><h2>사실과 복선</h2>${li([...h.new_facts.map(esc), ...h.foreshadow_planted.map((f) => '심음: ' + esc(f.description)), ...h.foreshadow_resolved.map((id) => '회수: ' + esc(id))])}</section>
    </div>`;
}

// ----- 관계 표시 (숫자/말) -----

const GOOD_EVENTS = ['도움', '희생', '약속이행', '칭찬', '진심고백', '사과', '공동경험'];
const INTENSITY = { 1: '가벼움', 2: '보통', 3: '결정적' };

function secretLabel(id, d) {
  const x = [...P().secrets, ...((d && d.secrets_added) || [])].find((s) => s.id === id);
  return x ? x.content : id;
}

function relationHeader(title) {
  const num = !!P().settings.show_numbers;
  return `<div class="between"><h2>${title}</h2><div class="seg" role="group" aria-label="관계 보기 방식">
    <button type="button" aria-pressed="${!num}" data-action="toggleNumbers" data-arg="words">말로</button>
    <button type="button" aria-pressed="${num}" data-action="toggleNumbers" data-arg="numbers">숫자로</button></div></div>`;
}

function relationLines(rel) {
  if (!rel) return '<div class="small">계산하는 중…</div>';
  if (rel.error) return `<div class="note err">${esc(rel.error)}</div>`;
  const text = P().settings.show_numbers ? rel.numbers : rel.words;
  if (!text) return '<div class="small">관계가 없어요. 설정 도우미에서 관계를 추가하세요.</div>';
  return `<ul class="rel-lines">${text.split('\n').map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
}

// ----- 6. 작업지시서 -----

function viewBrief(n) {
  const e = ep(n);
  if (!e) return header('6단계', '채팅 앱 작업지시서', '') + noEpisode();
  const body = S.briefTab === 'episode';
  const stateBlocked = !body && !e.text;
  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('brief', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)} · API 없이 쓰기</div><h1 style="font-size:24px">채팅 앱 작업지시서</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div></header>
    <p class="desc">Claude, Gemini, ChatGPT 구독 앱에 붙여 넣을 지시서입니다. API 생성과 똑같은 컨텍스트를 씁니다.</p>
    <div class="tabs" role="tablist" aria-label="지시서 종류">
      <button type="button" role="tab" aria-selected="${body}" data-action="setBriefTab" data-arg="episode">1 본문 작성 지시서</button>
      <button type="button" role="tab" aria-selected="${!body}" data-action="setBriefTab" data-arg="state">2 상태 정리 지시서</button>
    </div>
    <div class="cols">
      <section class="card" style="flex:1.3 1 480px;min-width:0">
        <div class="between"><h2><span class="small" style="font-weight:400">① </span>복사해서 채팅 앱에 붙여 넣기</h2>
          <div class="row"><button class="btn small" data-action="downloadBrief" data-arg="${n}"${stateBlocked ? ' disabled' : ''}>.md 내려받기</button><button class="btn small dark" data-action="copyBrief"${stateBlocked ? ' disabled' : ''}>복사</button></div></div>
        ${e.status === 'draft' && body ? '<div class="note warn">플롯이 아직 초안이에요. 확정 전 내용으로 지시서가 만들어집니다.</div>' : ''}
        <pre class="brief mono">${esc(S.briefText ?? '불러오는 중…')}</pre>
        ${S.briefText ? `<div class="small">${S.briefText.length.toLocaleString()}자</div>` : ''}
      </section>
      <section class="card" style="flex:1 1 380px;min-width:0">
        ${body ? `<h2><span class="small" style="font-weight:400">② </span>받은 본문 가져오기</h2>
          <label for="imp-body" class="small">채팅 앱이 쓴 본문을 그대로 붙여 넣으세요.</label>
          <textarea id="imp-body" rows="12" style="font-family:var(--serif);line-height:1.8"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}></textarea>
          ${e.status === 'draft' ? '<div class="small">플롯을 확정해야 본문을 저장할 수 있어요.</div>' : ''}${e.status === 'finalized' ? '<div class="small">이미 끝난 화입니다.</div>' : ''}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importText" data-arg="${n}"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}>${n}화 본문으로 저장</button></div>`
        : `<h2><span class="small" style="font-weight:400">② </span>받은 JSON 가져오기</h2>
          <label for="imp-json" class="small">채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지웁니다.</label>
          <textarea id="imp-json" rows="12" class="mono"${e.status !== 'written' ? ' disabled' : ''}></textarea>
          ${e.status !== 'written' ? '<div class="small">본문이 작성된 화에서만 쓸 수 있어요.</div>' : ''}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importJson" data-arg="${n}"${e.status !== 'written' ? ' disabled' : ''}>확인하고 변경안 검토로</button></div>`}
        <div style="padding-top:12px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:8px">
          <strong style="font-size:13px">순서</strong>
          <ol style="padding-left:20px;display:flex;flex-direction:column;gap:4px;font-size:13px;line-height:1.55;color:var(--text-2)">
            <li>본문 작성 지시서 → 받은 본문 저장</li><li>상태 정리 지시서 → 받은 JSON 가져오기</li><li>상태 변경안 승인 화면에서 반영</li></ol>
        </div>
      </section>
    </div>`;
}

// ---------- 연구 (모델 실험) ----------
// 본편 데이터와 분리된 실험실. 결과는 projects/<이름>/research/log.jsonl 에 남고,
// 블라인드 비교에서 채택할 때만 작품 본문이 바뀐다.

const RS_TABS = [['probe', '서버 점검'], ['sample', '샘플 생성'], ['stage', '단계 시험'], ['budget', '컨텍스트 크기'], ['compare', '블라인드 비교'], ['log', '기록']];
const RS_KIND = { sample: '샘플 생성', stage: '단계 시험', budget: '컨텍스트 크기', compare: '블라인드 비교', pick: '비교 고르기' };

function rsInit(name) {
  const c = S.config || {};
  const backend = () => ({ provider: c.provider === 'mock' ? 'mock' : 'local', model: c.local_model || '', url: '' });
  S.rs = {
    name, tab: 'probe', log: [], stages: {}, probe: null, probeUrl: c.local_url || '',
    runs: [backend()], system: '너는 한국어 소설가다.', prompt: '', temperature: '', sample: null,
    stageBackend: backend(), stage: 'style', stageText: '', stageResult: null,
    budgetBackend: backend(), budget: null,
    compareEp: null, compareA: { provider: 'gemini', model: '', url: '' }, compareB: backend(), compare: null, adopt: true, pickResult: null,
  };
}

async function rsLoadLog() {
  const r = await api('GET', `/projects/${enc(S.name)}/research`);
  S.rs.log = r.log;
  S.rs.stages = r.stages;
}

async function rsLoad() {
  if (!S.rs || S.rs.name !== S.name) rsInit(S.name);
  await rsLoadLog();
  if (S.rs.compareEp == null) S.rs.compareEp = currentEp();
  S.rs.compare = (await api('GET', `/projects/${enc(S.name)}/research/compare/${S.rs.compareEp}`)).compare;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset.rs || !S.rs) return;
  setPath(S.rs, el.dataset.rs, el.type === 'checkbox' ? el.checked : el.value);
});

const rsBackend = (b) => ({ provider: b.provider, model: b.model.trim(), url: b.url.trim() });
const rsLabel = (b) => (b.model ? `${b.provider}:${b.model}` : b.provider);
const rsNum = (v, d = 0) => (v == null ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));

Object.assign(actions, {
  rsTab(tab) {
    S.rs.tab = tab;
    render();
  },
  async rsProbe() {
    await run('서버를 확인하는 중', async () => {
      S.rs.probe = await api('POST', '/research/probe', { url: S.rs.probeUrl.trim() });
    });
  },
  rsUseModel(id) {
    S.rs.runs.push({ provider: 'local', model: id, url: S.rs.probeUrl.trim() === (S.config.local_url || '') ? '' : S.rs.probeUrl.trim() });
    S.rs.tab = 'sample';
    toast(`${id} 를 샘플 생성에 넣었습니다`);
    render();
  },
  rsAddRun() {
    S.rs.runs.push({ provider: 'local', model: '', url: '' });
    render();
  },
  rsRemoveRun(i) {
    S.rs.runs.splice(i, 1);
    render();
  },
  async rsSample() {
    if (!S.rs.prompt.trim()) return toast('요청 문장을 넣으세요', true);
    if (!S.rs.runs.length) return toast('백엔드를 하나 이상 넣으세요', true);
    const t = S.rs.temperature === '' ? null : Number(S.rs.temperature);
    await run(`${S.rs.runs.length}개 백엔드로 생성하는 중… (백엔드마다 차례로)`, async () => {
      S.rs.sample = await api('POST', `/projects/${enc(S.name)}/research/sample`,
        { runs: S.rs.runs.map(rsBackend), system: S.rs.system, prompt: S.rs.prompt, temperature: t });
      S.rs.log.unshift(S.rs.sample);
    });
  },
  async rsStage() {
    await run(`${S.rs.stages[S.rs.stage] || S.rs.stage} 시험 중… (저장하지 않음)`, async () => {
      S.rs.stageResult = await api('POST', `/projects/${enc(S.name)}/research/stage`,
        { backend: rsBackend(S.rs.stageBackend), stage: S.rs.stage, sample: S.rs.stageText });
      S.rs.log.unshift(S.rs.stageResult);
    });
  },
  async rsBudget() {
    await run('화별 프롬프트를 재는 중', async () => {
      S.rs.budget = await api('POST', `/projects/${enc(S.name)}/research/budget`, rsBackend(S.rs.budgetBackend));
      S.rs.log.unshift(S.rs.budget);
    });
  },
  async rsCompareEp() {
    S.rs.compareEp = Number($('#rs-cmp-ep').value);
    S.rs.pickResult = null;
    await run('불러오는 중', async () => {
      S.rs.compare = (await api('GET', `/projects/${enc(S.name)}/research/compare/${S.rs.compareEp}`)).compare;
    });
  },
  async rsCompare() {
    const n = S.rs.compareEp;
    if (S.rs.compare && !S.rs.compare.picked && !confirm(`${n}화의 고르지 않은 비교본을 새로 쓴 것으로 바꿀까요?`)) return;
    await run(`${n}화를 두 백엔드로 쓰는 중… (몇 분 걸릴 수 있어요)`, async () => {
      S.rs.compare = (await api('POST', `/projects/${enc(S.name)}/research/compare/${n}`,
        { a: rsBackend(S.rs.compareA), b: rsBackend(S.rs.compareB) })).compare;
      S.rs.pickResult = null;
      await rsLoadLog();
    });
  },
  async rsPick(k) {
    const n = S.rs.compareEp;
    if (S.rs.adopt && ep(n).text && !confirm(`${k}번을 ${n}화 본문으로 바꿀까요?`)) return;
    await run('공개하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/research/compare/${n}/pick`, { k, adopt: S.rs.adopt });
      S.rs.compare = r.compare;
      S.rs.pickResult = r.result;
      S.project = r.project;
      await rsLoadLog();
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${k}번은 ${r.result.picked} 였습니다${r.result.adopted ? `. ${n}화 본문으로 저장했습니다` : ''}`);
    });
  },
});

function rsBackendFields(path, b) {
  const id = 'rs-' + path.replace(/\W/g, '-');
  const opts = [['local', '로컬 서버'], ['gemini', 'Gemini'], ['mock', 'mock']]
    .map(([v, l]) => `<option value="${v}"${b.provider === v ? ' selected' : ''}>${l}</option>`).join('');
  return `<div class="rs-backend">
    <div class="field"><label for="${id}-p">백엔드</label><select id="${id}-p" data-rs="${path}.provider">${opts}</select></div>
    <div class="field"><label for="${id}-m">모델 <span class="hint">비우면 설정값</span></label><input id="${id}-m" type="text" list="rs-models" value="${esc(b.model)}" data-rs="${path}.model"></div>
    <div class="field"><label for="${id}-u">서버 주소 <span class="hint">로컬만, 비우면 설정값</span></label><input id="${id}-u" type="text" value="${esc(b.url)}" data-rs="${path}.url" placeholder="${esc((S.config || {}).local_url || '')}"></div>
  </div>`;
}

function rsModelList() {
  const ids = ((S.rs.probe || {}).models || []).map((m) => m.id);
  if ((S.config || {}).local_model) ids.push(S.config.local_model);
  if ((S.config || {}).model_setting) ids.push(S.config.model_setting);
  return `<datalist id="rs-models">${[...new Set(ids)].map((x) => `<option value="${esc(x)}"></option>`).join('')}</datalist>`;
}

function rsUsage(u, seconds) {
  if (!u) return '';
  const out = u.completion_tokens;
  return `입력 ${rsNum(u.prompt_tokens)} · 출력 ${rsNum(out)} 토큰${out && seconds ? ` · ${rsNum(out / seconds, 1)} 토큰/초` : ''}`;
}

function rsProbeView() {
  const r = S.rs.probe;
  const rows = r ? r.models.map((m) => `<tr><td class="mono">${esc(m.id)}</td><td>${esc(m.parent || '')}</td><td>${m.max_model_len ? rsNum(m.max_model_len) : (m.parent ? '부모와 같음' : '-')}</td><td>${esc(m.owned_by)}</td>
      <td><button class="btn small" data-action="rsUseModel" data-arg="${esc(m.id)}">샘플 생성에 넣기</button></td></tr>`).join('') : '';
  return `<section class="card">
      <p class="desc">OpenAI 호환 서버(vLLM, Ollama, llama.cpp, LM Studio)의 모델 목록과 컨텍스트 길이를 봅니다. 생성 호출은 하지 않습니다.</p>
      <div class="row" style="align-items:flex-end;flex-wrap:nowrap">
        <div class="field" style="flex:1"><label for="rs-probe-url">서버 주소 <span class="hint">/v1 까지</span></label><input id="rs-probe-url" type="text" value="${esc(S.rs.probeUrl)}" data-rs="probeUrl" placeholder="http://nhn-b200:8001/v1"></div>
        <button class="btn dark" data-action="rsProbe">점검</button>
      </div>
      ${r ? `<div class="note ok">${esc(r.url)} · 서버 ${esc(r.server)}${r.version ? ' ' + esc(r.version) : ''} · 모델 ${r.models.length}개 · ${r.seconds}초</div>
        <div class="rs-scroll"><table class="rs-table"><thead><tr><th>모델</th><th>부모 (LoRA)</th><th>최대 컨텍스트</th><th>제공</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="small">컨텍스트가 작은 모델은 '컨텍스트 크기' 탭에서 몇 화부터 넘치는지 확인하세요. 서버 주소와 모델을 고정하려면 <a href="#/settings">설정</a>에 저장하세요.</div>` : ''}
    </section>`;
}

function rsSampleView() {
  const runs = S.rs.runs.map((b, i) => `<div class="row" style="align-items:flex-end;flex-wrap:nowrap"><div style="flex:1">${rsBackendFields(`runs.${i}`, b)}</div>
      <button class="btn icon-btn danger" data-action="rsRemoveRun" data-arg="${i}" aria-label="백엔드 ${i + 1} 빼기">✕</button></div>`).join('');
  const res = S.rs.sample;
  const cards = res ? res.rows.map((r) => `<section class="card tight">
      <div class="between"><h3>${esc(r.backend)}</h3><span class="small">${r.seconds}초</span></div>
      ${r.ok ? `<div class="small">${esc(r.model)} · ${rsNum(r.chars)}자 · 문장 평균 ${rsNum(r.sentence_len_mean, 1)} · 대사 ${rsNum(r.dialogue_ratio, 2)} · 어휘 ${rsNum(r.mattr, 3)}</div>
        <div class="small">${rsUsage(r.usage, r.seconds)}</div>
        <div class="rs-prose">${esc(r.text)}</div>` : `<div class="note err">${esc(r.error)}</div>`}
    </section>`).join('') : '';
  return `<section class="card">
      <p class="desc">같은 요청을 여러 백엔드에 차례로 보내 시간, 토큰, 문체 지표를 나란히 봅니다. 작품 데이터는 쓰지 않습니다.</p>
      ${runs || '<div class="small">백엔드를 넣으세요.</div>'}
      <div><button class="btn small ghost" data-action="rsAddRun">+ 백엔드</button></div>
      <div class="field"><label for="rs-system">시스템 지시</label><textarea id="rs-system" rows="2" data-rs="system">${esc(S.rs.system)}</textarea></div>
      <div class="field"><label for="rs-prompt">요청</label><textarea id="rs-prompt" rows="4" data-rs="prompt" placeholder="비 오는 바닷가 소도시 등대 앞, 오빠를 찾는 서윤의 장면을 600자로 써라.">${esc(S.rs.prompt)}</textarea></div>
      <div class="row" style="align-items:flex-end">
        <div class="field" style="width:160px"><label for="rs-temp">온도 <span class="hint">로컬만</span></label><input id="rs-temp" type="number" step="0.1" min="0" max="2" value="${esc(S.rs.temperature)}" data-rs="temperature" placeholder="설정값"></div>
        <button class="btn dark" data-action="rsSample">생성</button>
      </div>
    </section>
    ${cards ? `<div class="grid-auto">${cards}</div>` : ''}`;
}

function rsStageView() {
  const r = S.rs.stageResult;
  const stages = Object.entries(S.rs.stages).map(([k, l]) => `<option value="${k}"${S.rs.stage === k ? ' selected' : ''}>${l}</option>`).join('');
  let out = '';
  if (r && !r.ok) out = `<div class="note err">${esc(r.error)} · ${r.seconds}초</div>`;
  if (r && r.ok) {
    const filled = r.fields - r.empty.length;
    out = `<section class="card">
      <div class="between"><h2>${esc(S.rs.stages[r.stage] || r.stage)} · ${esc(r.backend)}</h2><span class="small">${r.seconds}초 · 시도 ${r.attempts}회 · ${rsUsage(r.usage, r.seconds)}</span></div>
      <div class="note ${r.empty.length ? 'warn' : 'ok'}">필드 ${r.fields}개 중 ${filled}개 채움${r.empty.length ? `, 빈 필드 ${r.empty.length}개` : ''}</div>
      ${r.empty.length ? `<div class="small mono">${r.empty.map(esc).join(' · ')}</div>` : ''}
      ${r.out_of_range.length ? `<div class="note err">범위를 벗어난 값 ${r.out_of_range.length}개 (스키마 설명의 범위 기준)<br><span class="mono">${r.out_of_range.map(esc).join('<br>')}</span></div>` : ''}
      ${r.attempts > 1 ? '<div class="note warn">첫 응답이 스키마 검증에 실패해 한 번 더 물었습니다.</div>' : ''}
      <details><summary>응답 JSON 보기</summary><pre class="brief mono">${esc(JSON.stringify(r.result, null, 2))}</pre></details>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌려 봅니다. 모델이 건너뛴 필드, 범위를 벗어난 숫자, 재시도 횟수를 확인합니다.</p>
      ${rsBackendFields('stageBackend', S.rs.stageBackend)}
      <div class="field" style="max-width:240px"><label for="rs-stage">단계</label><select id="rs-stage" data-rs="stage">${stages}</select></div>
      <div class="field"><label for="rs-stage-text">문체 분석 원문 <span class="hint">문체 분석에만 씀. 비우면 문체 레퍼런스의 대표 문단</span></label><textarea id="rs-stage-text" rows="5" data-rs="stageText" style="font-family:var(--serif)">${esc(S.rs.stageText)}</textarea></div>
      <div><button class="btn dark" data-action="rsStage">시험</button></div>
    </section>${out}`;
}

function rsBudgetView() {
  const r = S.rs.budget;
  let out = '';
  if (r) {
    const cell = (c) => `<td class="${c.over ? 'over' : c.tight ? 'tight' : ''}">${c.exact ? '' : '~'}${rsNum(c.tokens)}<span class="small"> / ${rsNum(c.total)}</span></td>`;
    const rows = r.rows.map((x) => `<tr><td>${x.episode}화</td><td><span class="chip ${x.status}">${STATUS[x.status]}</span>${x.measured ? '' : ' <span class="small">가정</span>'}</td>${cell(x.write)}${cell(x.check)}${cell(x.state)}</tr>`).join('');
    out = `<section class="card">
      <div class="between"><h2>${esc(r.backend)} · ${esc(r.model)}</h2><span class="small">최대 컨텍스트 ${r.limit ? rsNum(r.limit) + ' 토큰' : '알 수 없음'}</span></div>
      ${r.first_over ? `<div class="note err">${r.first_over}화부터 입력만으로 한도를 넘어 서버가 요청을 거절합니다. 검수(check)는 앞선 본문 전체를 넣어 화가 갈수록 커집니다. 서버의 컨텍스트를 늘리거나, 설정의 단계별 백엔드에서 넘치는 단계를 Gemini 로 돌리세요.</div>` : ''}
      ${r.first_tight && r.first_tight !== r.first_over ? `<div class="note warn">${r.first_tight}화부터 출력 여유까지 더하면 한도를 넘습니다. 응답이 중간에 잘릴 수 있어요.</div>` : ''}
      ${!r.limit ? '<div class="note plain">이 백엔드는 한도를 알려 주지 않아 넘침은 판단하지 않았습니다.</div>' : (!r.first_tight ? '<div class="note ok">플롯이 있는 화는 모두 한도 안에 들어갑니다.</div>' : '')}
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>화</th><th>상태</th><th>본문 쓰기</th><th>검수</th><th>상태 추출</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small">칸마다 '입력 / 입력+출력 여유' 토큰입니다. 출력 여유는 본문 ${rsNum(r.write_reserve)}, 검수·상태 ${rsNum(r.json_reserve)} 토큰으로 잡았습니다. ${r.tokenizer ? '서버 토크나이저로 셌습니다.' : '~ 표시는 글자 수로 어림한 값입니다.'} '가정'인 화는 앞선 화가 모두 목표 분량으로 쓰였다고 보고 쟀습니다. 플롯이 있는 화만 잽니다.</div>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">화마다 본문 쓰기, 검수, 상태 추출에 들어가는 프롬프트 크기를 모델의 컨텍스트 한도와 비교합니다. 생성 호출은 하지 않습니다.</p>
      ${rsBackendFields('budgetBackend', S.rs.budgetBackend)}
      <div><button class="btn dark" data-action="rsBudget">재기</button></div>
    </section>${out}`;
}

function rsCompareView() {
  const eps = P().episodes.filter((e) => e.status !== 'draft');
  const c = S.rs.compare;
  const n = S.rs.compareEp;
  const e = ep(n);
  const reveal = c && c.order;
  const drafts = c ? c.drafts.map((d) => `<section class="card tight${c.picked === d.n ? ' rs-picked' : ''}">
      <div class="between"><h3>${d.n}번${reveal ? ` <span class="chip ai">${esc(c.order[d.n - 1])}</span>` : ''}</h3>
        ${c.picked ? (c.picked === d.n ? '<span class="chip finalized">고름</span>' : '') : `<button class="btn small primary" data-action="rsPick" data-arg="${d.n}">이걸 고르기</button>`}</div>
      <div class="small">${rsNum(d.chars)}자 · 문장 평균 ${rsNum(d.sentence_len_mean, 1)} · 대사 ${rsNum(d.dialogue_ratio, 2)} · 어휘 ${rsNum(d.mattr, 3)}</div>
      ${d.warnings.length ? `<div class="note warn">${d.warnings.map(esc).join('<br>')}</div>` : ''}
      <div class="rs-prose">${esc(d.text)}</div>
    </section>`).join('') : '';
  const wins = S.rs.pickResult ? Object.entries(S.rs.pickResult.wins).map(([k, v]) => `${esc(k)} ${v}`).join(', ') : '';
  return `<section class="card">
      <p class="desc">같은 화를 두 백엔드로 쓰고 1, 2번으로 가립니다. 읽고 고르면 어느 쪽이었는지 공개합니다. 프롬프트는 집필 화면과 같습니다.</p>
      <div class="field" style="max-width:320px"><label for="rs-cmp-ep">화</label>
        <select id="rs-cmp-ep" onchange="actions.rsCompareEp()">${eps.map((x) => `<option value="${x.plot.number}"${x.plot.number === n ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)} · ${STATUS[x.status]}</option>`).join('') || '<option>확정된 화가 없습니다</option>'}</select></div>
      <div class="grid-2"><div><h3>A</h3>${rsBackendFields('compareA', S.rs.compareA)}</div><div><h3>B</h3>${rsBackendFields('compareB', S.rs.compareB)}</div></div>
      <label class="check-row"><input type="checkbox" data-rs="adopt"${S.rs.adopt ? ' checked' : ''}><span><strong>고른 쪽을 본문으로 채택</strong> <span class="small">끄면 고른 기록만 남기고 작품은 그대로 둡니다. 반영이 끝난 화는 채택할 수 없어요.</span></span></label>
      <div><button class="btn dark" data-action="rsCompare"${eps.length && e && e.status !== 'draft' ? '' : ' disabled'}>${n}화 비교본 쓰기</button></div>
      ${e && e.status === 'finalized' ? '<div class="small">이 화는 반영이 끝났습니다. 비교본을 쓰려면 이전 화들이 반영 완료여야 하고, 채택은 끈 채로 고르세요.</div>' : ''}
    </section>
    ${S.rs.pickResult ? `<div class="note ok">${esc(S.rs.pickResult.picked)} 를 골랐습니다. 지금까지 고른 횟수: ${wins}</div>` : ''}
    ${c ? `<div class="small">${esc((c.created || '').replace('T', ' '))} 에 쓴 비교본${c.picked ? '' : ' · 고르기 전까지 백엔드를 가립니다'}</div><div class="rs-compare">${drafts}</div>` : ''}`;
}

function rsLogView() {
  const items = S.rs.log.map((x) => {
    let line = '';
    if (x.kind === 'sample') line = x.rows.map((r) => `${r.backend} ${r.ok ? `${rsNum(r.chars)}자 ${r.seconds}초` : '실패'}`).join(' · ');
    if (x.kind === 'stage') line = `${S.rs.stages[x.stage] || x.stage} · ${x.backend} · ${x.ok ? `빈 필드 ${x.empty.length}/${x.fields}, 범위 밖 ${x.out_of_range.length}, 시도 ${x.attempts}` : '실패'} · ${x.seconds}초`;
    if (x.kind === 'budget') line = `${x.backend} · 한도 ${x.limit ? rsNum(x.limit) : '알 수 없음'} · ${x.first_over ? `${x.first_over}화부터 넘침` : x.first_tight ? `${x.first_tight}화부터 빠듯함` : '넘침 없음'}`;
    if (x.kind === 'compare') line = `${x.episode}화 · ${x.backends.join(' vs ')}`;
    if (x.kind === 'pick') line = `${x.episode}화 · ${x.picked} 고름${x.adopted ? ' (본문 채택)' : ''}`;
    return `<li><div class="between"><span><span class="chip">${RS_KIND[x.kind] || x.kind}</span> ${esc(line)}</span><span class="small">${esc(x.time.replace('T', ' '))}</span></div>
      <details><summary>자세히</summary><pre class="brief mono">${esc(JSON.stringify(x, null, 2))}</pre></details></li>`;
  }).join('');
  return `<section class="card">
      <p class="desc">최근 30개 실험입니다. 전체 기록은 작품 폴더의 research/log.jsonl 에 있습니다.</p>
      ${items ? `<ul class="rs-log">${items}</ul>` : '<div class="small">아직 기록이 없어요.</div>'}
    </section>`;
}

function viewResearch() {
  if (!S.rs) return header('연구', '모델 실험', '') + '<div class="note plain">불러오는 중…</div>';
  const views = { probe: rsProbeView, sample: rsSampleView, stage: rsStageView, budget: rsBudgetView, compare: rsCompareView, log: rsLogView };
  return `${header('연구 · 본편과 분리', '모델 실험', '모델 서버를 점검하고, 같은 요청을 여러 모델로 돌려 비교합니다. 여기서 돌린 결과는 작품 데이터에 들어가지 않고 실험 기록으로만 남습니다. 블라인드 비교에서 채택할 때만 본문이 바뀝니다.')}
    <div class="tabs" role="tablist" aria-label="실험 종류">${RS_TABS.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.rs.tab === k}" data-action="rsTab" data-arg="${k}">${l}</button>`).join('')}</div>
    ${rsModelList()}
    ${views[S.rs.tab]()}`;
}

route();
