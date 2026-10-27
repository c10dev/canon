/* 연구 · 모델 실험 화면. app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ---------- 연구 (모델 실험) ----------
// 본편 데이터와 분리된 실험실. 결과는 projects/<이름>/research/log.jsonl 에 남고,
// 블라인드 비교에서 채택할 때만 작품 본문이 바뀐다.

const RS_TABS = [['probe', '서버 점검'], ['sample', '샘플 생성'], ['stage', '단계 시험'], ['budget', '컨텍스트 크기'], ['check', '검수 시험'], ['compare', '블라인드 비교'], ['log', '기록']];
const RS_KIND = { sample: '샘플 생성', stage: '단계 시험', budget: '컨텍스트 크기', check: '검수 시험', compare: '블라인드 비교', pick: '비교 고르기' };

function rsInit(name) {
  const c = S.config || {};
  const backend = () => ({ provider: c.provider === 'mock' ? 'mock' : 'local', model: c.local_model || '', url: '' });
  // 비교 A 는 설정의 본문 쓰기 백엔드, B 는 그와 다른 백엔드 (같으면 서버가 거절한다)
  const writeProv = ((c.stages || {}).write || {}).provider || c.provider || 'gemini';
  const cmpA = { provider: writeProv, model: '', url: '' };
  const cmpB = { provider: writeProv === 'local' ? 'gemini' : 'local', model: '', url: '' };
  S.rs = {
    name, tab: 'probe', log: [], stages: {}, probe: null, probeUrl: c.local_url || '',
    runs: [backend()], system: '너는 한국어 소설가다.', prompt: '', temperature: '', sample: null,
    stageBackend: backend(), stage: 'style', stageText: '', stageResult: null,
    budgetBackend: backend(), budget: null,
    checkBackend: backend(), checkEp: null, checkPlants: '3', check: null, checkModes: {},
    checkJudge: backend(), checkTwoStep: false,
    compareEp: null, compareA: cmpA, compareB: cmpB, compare: null, adopt: true, pickResult: null, probeError: null,
  };
}

async function rsLoadLog() {
  const r = await api('GET', `/projects/${enc(S.name)}/research`);
  S.rs.log = r.log;
  S.rs.stages = r.stages;
  S.rs.checkModes = r.check_modes || {};
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
  async bodyAI(cid) {
    if (!P().characters.some((x) => x.id === cid)) return;
    await run('신체 프로필 제안 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 인물 설정을 읽는다. 방금 고친 나이 · 외모도 보게 먼저 저장한다
      const s = await api('POST', `/projects/${enc(S.name)}/characters/${enc(cid)}/body`);
      S.bodySug = { ...(S.bodySug || {}), [cid]: s };
      S.bodyOpen = { ...(S.bodyOpen || {}), [cid]: true };
    });
  },
  bodyApply(cid) {
    const c = P().characters.find((x) => x.id === cid);
    const s = (S.bodySug || {})[cid];
    if (!c || !s) return;
    const picked = [...document.querySelectorAll(`[data-body-pick="${CSS.escape(cid)}"]:checked`)].map((x) => x.value)
      .filter((k) => !(k === 'measurements' && isMinorAge(c.age)));
    if (!picked.length) { toast('적용할 칸을 고르세요', true); return; }
    c.body = { ...(c.body || {}) };
    picked.forEach((k) => { c.body[k] = s[k]; });
    delete S.bodySug[cid];
    markDirty();
    render();
    toast(`${picked.length}칸을 적용했어요. 저장하면 남아요`);
  },
  bodyDismiss(cid) {
    if (S.bodySug) delete S.bodySug[cid];
    render();
  },
  async voiceAI(cid) {
    const c = P().characters.find((x) => x.id === cid);
    if (!c) return;
    if ((c.narration_voice || '').trim() && !confirm('지금 적힌 서술 말투를 AI 초안으로 바꿀까요? 저장하기 전에는 되돌릴 수 있어요')) return;
    await run('서술 말투 초안 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 인물 설정을 읽는다. 방금 고친 설정이나 새 인물도 보게 먼저 저장한다
      const req = document.getElementById(`voice-req-${cid}`);
      const s = await api('POST', `/projects/${enc(S.name)}/characters/${enc(cid)}/voice`, { request: req ? req.value.trim() : '' });
      c.narration_voice = s.voice;
      S.voices = { ...(S.voices || {}), [cid]: s.note || '' };
      markDirty();
      toast('초안을 칸에 넣었어요. 고친 뒤 저장하세요');
    });
  },
  rsTab(tab) {
    S.rs.tab = tab;
    render();
  },
  async rsProbe() {
    await run('서버를 확인하는 중', async () => {
      try {
        S.rs.probe = await api('POST', '/research/probe', { url: S.rs.probeUrl.trim() });
        S.rs.probeError = null;
      } catch (e) {
        if (e.status !== 400) throw e;
        S.rs.probe = null;
        S.rs.probeError = e.message;  // 토스트는 사라지니 카드 안에 남긴다
      }
    });
  },
  rsUseModel(id) {
    S.rs.runs.push({ provider: 'local', model: id, url: S.rs.probeUrl.trim() === (S.config.local_url || '') ? '' : S.rs.probeUrl.trim() });
    S.rs.tab = 'sample';
    toast(`샘플 생성에 ${id} 모델을 넣었어요`);
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
  async rsCheck() {
    const n = Number(S.rs.checkEp || ($('#rs-check-ep') || {}).value);
    if (!n) return toast('본문이 있는 화를 고르세요', true);
    await run(`${n}화에 모순을 심고 검수 방식마다 검수하는 중… (저장하지 않음)`, async () => {
      S.rs.check = await api('POST', `/projects/${enc(S.name)}/research/check`,
        { backend: rsBackend(S.rs.checkBackend), episode: n, plants: Number(S.rs.checkPlants) || 3,
          ...(S.rs.checkTwoStep ? { judge: rsBackend(S.rs.checkJudge) } : {}) });
      S.rs.log.unshift(S.rs.check);
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
    const adopt = S.rs.adopt && ep(n).status !== 'finalized';  // 반영이 끝난 화는 고른 기록만 남긴다
    if (adopt && ep(n).text && !confirm(`${k}번을 ${n}화 본문으로 바꿀까요?`)) return;
    await run('공개하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/research/compare/${n}/pick`, { k, adopt });
      S.rs.compare = r.compare;
      S.rs.pickResult = r.result;
      S.project = r.project;
      await rsLoadLog();
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${k}번은 ${r.result.picked} 였어요${r.result.adopted ? `. ${n}화 본문으로 저장했어요` : ''}`);
    });
  },
});

function rsBackendFields(path, b, kinds = [['local', '로컬 서버'], ['gemini', 'Gemini'], ['mock', 'mock']]) {
  const id = 'rs-' + path.replace(/\W/g, '-');
  const opts = kinds
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
      <p class="desc">OpenAI 호환 서버(vLLM, Ollama, llama.cpp, LM Studio)의 모델 목록과 컨텍스트 길이를 봐요. 생성 호출은 하지 않아요.</p>
      <div class="row" style="align-items:flex-end;flex-wrap:nowrap">
        <div class="field" style="flex:1"><label for="rs-probe-url">서버 주소 <span class="hint">/v1까지</span></label><input id="rs-probe-url" type="text" value="${esc(S.rs.probeUrl)}" data-rs="probeUrl" placeholder="http://nhn-b200:8001/v1"></div>
        <button class="btn dark" data-action="rsProbe">점검</button>
      </div>
      ${S.rs.probeError ? `<div class="note err" role="alert">${esc(S.rs.probeError)}</div>` : ''}
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
      <p class="desc">같은 요청을 여러 백엔드에 차례로 보내 시간, 토큰, 문체 지표를 나란히 봐요. 작품 데이터는 쓰지 않아요.</p>
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
      ${r.attempts > 1 ? '<div class="note warn">첫 응답이 스키마 검증에 실패해 한 번 더 물었어요.</div>' : ''}
      <details><summary>응답 JSON 보기</summary><pre class="brief mono">${esc(JSON.stringify(r.result, null, 2))}</pre></details>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌려 봐요. 모델이 건너뛴 필드, 범위를 벗어난 숫자, 재시도 횟수를 확인해요.</p>
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
    const parts = (c) => (c.blocks || []).map(([k, v]) => `${k} ${Math.round((v / c.chars) * 100)}%`).join(' · ');
    const cell = (c) => `<td class="${c.over ? 'over' : c.tight ? 'tight' : ''}" title="${esc(parts(c))}">${c.exact ? '' : '~'}${rsNum(c.tokens)}<span class="small"> / ${rsNum(c.total)}</span></td>`;
    const rows = r.rows.map((x) => `<tr><td>${x.episode}화</td><td><span class="chip ${x.status}">${STATUS[x.status]}</span>${x.measured ? '' : ' <span class="small">가정</span>'}</td>${cell(x.write)}${cell(x.check)}${cell(x.state)}</tr>`).join('');
    out = `<section class="card">
      <div class="between"><h2>${esc(r.backend)} · ${esc(r.model)}</h2><span class="small">최대 컨텍스트 ${r.limit ? rsNum(r.limit) + ' 토큰' : '알 수 없음'}</span></div>
      ${r.first_over ? `<div class="note err">${r.first_over}화부터 입력만으로 한도를 넘어 서버가 요청을 거절해요. 단편의 검수(check)는 앞선 본문 전체를 넣어 화가 갈수록 커져요. 서버의 컨텍스트를 늘리거나, 설정의 단계별 백엔드에서 넘치는 단계를 Gemini로 돌리세요.</div>` : ''}
      ${r.first_tight && r.first_tight !== r.first_over ? `<div class="note warn">${r.first_tight}화부터 출력 여유까지 더하면 한도를 넘어요. 응답이 중간에 잘릴 수 있어요.</div>` : ''}
      ${!r.limit ? '<div class="note plain">이 백엔드는 한도를 알려 주지 않아 넘침은 판단하지 않았어요.</div>' : (!r.first_tight ? '<div class="note ok">플롯이 있는 화는 모두 한도 안에 들어가요.</div>' : '')}
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>화</th><th>상태</th><th>본문 쓰기</th><th>검수</th><th>상태 변경안</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small">칸마다 '입력 / 입력+출력 여유' 토큰이에요. 출력 여유는 본문 ${rsNum(r.write_reserve)}, 검수·상태 ${rsNum(r.json_reserve)} 토큰으로 잡았어요. ${r.tokenizer ? '서버 토크나이저로 셌어요.' : '~ 표시는 글자 수로 어림한 값이에요.'} '가정'인 화는 앞선 화가 모두 목표 분량으로 쓰였다고 보고 쟀어요. 플롯이 있는 화만 재요. 칸에 올리면 큰 블록 비중이 보여요.</div>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">화마다 본문 쓰기, 검수, 상태 변경안에 들어가는 프롬프트 크기를 모델의 컨텍스트 한도와 비교해요. 생성 호출은 하지 않아요.</p>
      ${rsBackendFields('budgetBackend', S.rs.budgetBackend)}
      <div><button class="btn dark" data-action="rsBudget">재기</button></div>
    </section>${out}`;
}

function rsCheckView() {
  const eps = P().episodes.filter((e) => e.text);
  const r = S.rs.check;
  let out = '';
  if (r) {
    const modes = r.runs.map((x) => `<th>${esc(x.mode)}<div class="small">${x.tokens == null ? '' : `~${rsNum(x.tokens)} 토큰`}</div>${x.mode === 'twostep' && x.ok ? `<div class="small">판단기 ~${rsNum(x.judge_tokens)} 토큰 · 진술 ${x.claims}개 중 ${x.flagged}개 의심</div>` : ''}</th>`).join('');
    const rows = r.planted.map((x, i) => `<tr><td><div class="small">${esc(x.type)} · 근거: ${x.source_episode ? `${x.source_episode}화 (${x.distance}화 전)` : '설정이나 확정 사실'}</div>
        <div class="rs-prose small"><del>${esc(x.quote)}</del><br><ins>${esc(x.replacement)}</ins></div></td>
        ${r.runs.map((m) => `<td>${!m.ok ? '<span class="chip usage-fail">실패</span>' : m.hits[i] ? '<span class="chip finalized">찾음</span>' : '<span class="chip written">놓침</span>'}${m.ok && m.raised && !m.hits[i] ? `<div class="small">${m.raised[i] ? '판단기는 올림' : '판단기가 놓침'}</div>` : ''}</td>`).join('')}</tr>`).join('');
    const sum = r.runs.map((m) => `<td><strong>${m.ok ? `${m.found}/${r.planted.length}` : esc(m.error)}</strong>${m.ok ? `<div class="small">다른 지적 ${m.other.length}개 · ${m.seconds}초</div>` : ''}</td>`).join('');
    out = `<section class="card">
      <div class="between"><h2>${r.episode}화 · ${esc(r.backend)}</h2><span class="small">심은 모순 ${r.planted.length}개${r.skipped.length ? ` (원문을 못 찾아 ${r.skipped.length}개 뺌)` : ''} · ${r.seconds}초</span></div>
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>심은 모순</th>${modes}</tr></thead><tbody>${rows}<tr><td>찾은 수</td>${sum}</tr></tbody></table></div>
      ${r.runs.filter((m) => m.ok && m.other.length).map((m) => `<details><summary>${esc(m.mode)}의 다른 지적 ${m.other.length}개</summary><ul>${m.other.map((i) => `<li class="small">${esc(i.type)}: ${esc(i.description)}</li>`).join('')}</ul></details>`).join('')}
      ${r.runs.filter((m) => m.mode === 'twostep' && m.ok && m.judged.length).map((m) => `<details><summary>판단기가 본 진술 ${m.judged.length}개 (${esc(m.judge)})</summary><ul>${m.judged.map((j) => `<li class="small">${j.flagged ? '<span class="chip written">의심</span> ' : ''}어긋남 ${Math.round((j.probs[1] || 0) * 100)}% · ${esc(j.claim)}${j.mass < 0.5 ? ' <span class="hint">선택지 밖 답이 많았어요</span>' : ''}</li>`).join('')}</ul></details>`).join('')}
      <div class="small">한 번으로는 우연이 커요. 여러 화에서 몇 번 돌려 기록 탭에서 찾은 비율을 견주세요. 모순을 심는 것도 같은 모델이 해요.</div>
    </section>`;
  }
  const modes = Object.entries(S.rs.checkModes).map(([k, v]) => `<li><strong>${esc(k)}</strong>: ${esc(v)}</li>`).join('');
  return `<section class="card">
      <p class="desc">본문이 있는 화에 모순을 몇 개 심고, 검수 방식마다 그걸 찾는지 봐요. 장편 검수는 입력을 줄인 방식이 기본이라 줄여서 놓치는 게 없는지 확인하는 용도예요. 작품에는 저장하지 않고, 호출은 심기 1번 + 방식마다 1번이에요.</p>
      ${modes ? `<ul class="small">${modes}</ul>` : ''}
      ${rsBackendFields('checkBackend', S.rs.checkBackend)}
      <label class="check-row"><input type="checkbox" data-rs="checkTwoStep" onchange="render()"${S.rs.checkTwoStep ? ' checked' : ''}><span><strong>두 걸음 검수도 시험</strong> <span class="small">위 백엔드가 진술을 뽑고 의심만 판정해요. 그 사이에 판단기가 진술마다 선택지 확률만 내요(로컬 서버는 logprobs 지원 필요). 검수 모델 호출 2번 + 판단기 호출 진술 수만큼 늘어요.</span></span></label>
      ${S.rs.checkTwoStep ? `<h3>판단기</h3>${rsBackendFields('checkJudge', S.rs.checkJudge, [['local', '로컬 서버'], ['mock', 'mock']])}` : ''}
      <div class="row">
        <div class="field" style="max-width:320px"><label for="rs-check-ep">화</label>
          <select id="rs-check-ep" data-rs="checkEp">${eps.map((x) => `<option value="${x.plot.number}"${String(x.plot.number) === String(S.rs.checkEp) ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)}</option>`).join('') || '<option value="">본문이 있는 화가 없어요</option>'}</select></div>
        <div class="field" style="max-width:140px"><label for="rs-check-n">심을 모순</label><input id="rs-check-n" type="number" min="1" max="5" value="${esc(S.rs.checkPlants)}" data-rs="checkPlants"></div>
      </div>
      <div><button class="btn dark" data-action="rsCheck">시험</button></div>
    </section>${out}`;
}

function rsCompareView() {
  const eps = P().episodes.filter((e) => e.status !== 'draft');
  const c = S.rs.compare;
  const n = S.rs.compareEp;
  const e = ep(n);
  // 비교본은 집필과 같은 규칙으로 쓴다: 앞 화가 모두 반영돼야 쓸 수 있다
  const need = (num) => { const b = blockedBefore(num); return b.length ? ` (${b.length > 3 ? `${b[0]}화 등 ${b.length}개 화` : `${b.join(', ')}화`} 반영 필요)` : ''; };
  const blocked = e ? blockedBefore(n) : [];
  const fin = e && e.status === 'finalized';
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
      <p class="desc">같은 화를 두 백엔드로 쓰고 1, 2번으로 가려요. 읽고 고르면 어느 쪽이었는지 공개해요. 프롬프트는 집필 화면과 같아요.</p>
      <div class="field" style="max-width:320px"><label for="rs-cmp-ep">화</label>
        <select id="rs-cmp-ep" onchange="actions.rsCompareEp()">${eps.map((x) => `<option value="${x.plot.number}"${x.plot.number === n ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)} · ${STATUS[x.status]}${need(x.plot.number)}</option>`).join('') || '<option>확정된 화가 없어요</option>'}</select></div>
      <div class="grid-2"><div><h3>A</h3>${rsBackendFields('compareA', S.rs.compareA)}</div><div><h3>B</h3>${rsBackendFields('compareB', S.rs.compareB)}</div></div>
      <label class="check-row"><input type="checkbox" data-rs="adopt"${S.rs.adopt && !fin ? ' checked' : ''}${fin ? ' disabled' : ''}><span><strong>고른 쪽을 본문으로 채택</strong> <span class="small">끄면 고른 기록만 남기고 작품은 그대로 둬요. 반영이 끝난 화는 채택할 수 없어요.</span></span></label>
      <div><button class="btn dark" data-action="rsCompare"${eps.length && e && e.status !== 'draft' && !blocked.length ? '' : ' disabled'}>${n}화 비교본 쓰기</button></div>
      ${blocked.length ? orderNote(blocked) : fin ? '<div class="note plain">이 화는 반영이 끝난 화라 골라도 본문은 바뀌지 않고 고른 기록만 남아요.</div>' : ''}
    </section>
    ${S.rs.pickResult ? `<div class="note ok">고른 쪽: ${esc(S.rs.pickResult.picked)}. 지금까지 고른 횟수: ${wins}</div>` : ''}
    ${c ? `<div class="small">${esc(fmtDateTime(c.created))}에 쓴 비교본${c.picked ? '' : ' · 고르기 전까지 백엔드를 가려요'}</div><div class="rs-compare">${drafts}</div>` : ''}`;
}

function rsLogView() {
  const items = S.rs.log.map((x) => {
    let line = '';
    if (x.kind === 'sample') line = x.rows.map((r) => `${r.backend} ${r.ok ? `${rsNum(r.chars)}자 ${r.seconds}초` : '실패'}`).join(' · ');
    if (x.kind === 'stage') line = `${S.rs.stages[x.stage] || x.stage} · ${x.backend} · ${x.ok ? `빈 필드 ${x.empty.length}/${x.fields}, 범위 밖 ${x.out_of_range.length}, 시도 ${x.attempts}` : '실패'} · ${x.seconds}초`;
    if (x.kind === 'budget') line = `${x.backend} · 한도 ${x.limit ? rsNum(x.limit) : '알 수 없음'} · ${x.first_over ? `${x.first_over}화부터 넘침` : x.first_tight ? `${x.first_tight}화부터 빠듯함` : '넘침 없음'}`;
    if (x.kind === 'compare') line = `${x.episode}화 · ${x.backends.join(' vs ')}`;
    if (x.kind === 'check') line = `${x.episode}화 · ${x.backend} · ${x.runs.map((m) => `${m.mode} ${m.ok ? `${m.found}/${x.planted.length}` : '실패'}`).join(', ')}`;
    if (x.kind === 'pick') line = `${x.episode}화 · ${x.picked} 고름${x.adopted ? ' (본문 채택)' : ''}`;
    return `<li><div class="between"><span><span class="chip">${RS_KIND[x.kind] || x.kind}</span> ${esc(line)}</span><span class="small">${esc(fmtDateTime(x.time))}</span></div>
      <details><summary>자세히</summary><pre class="brief mono">${esc(JSON.stringify(x, null, 2))}</pre></details></li>`;
  }).join('');
  return `<section class="card">
      <p class="desc">최근 30개 실험이에요. 전체 기록은 작품 폴더의 research/log.jsonl에 있어요.</p>
      ${items ? `<ul class="rs-log">${items}</ul>` : '<div class="small">아직 기록이 없어요.</div>'}
    </section>`;
}

function viewResearch() {
  if (!S.rs) return header('연구', '모델 실험', '') + '<div class="note plain">불러오는 중…</div>';
  const views = { probe: rsProbeView, sample: rsSampleView, stage: rsStageView, budget: rsBudgetView, check: rsCheckView, compare: rsCompareView, log: rsLogView };
  return `${header('연구 · 본편과 분리', '모델 실험', '모델 서버를 점검하고, 같은 요청을 여러 모델로 돌려 비교해요. 여기서 돌린 결과는 작품 데이터에 들어가지 않고 실험 기록으로만 남아요. 블라인드 비교에서 채택할 때만 본문이 바뀌어요.')}
    <div class="tabs wrap" role="tablist" aria-label="실험 종류">${RS_TABS.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.rs.tab === k}" aria-controls="rs-panel" data-action="rsTab" data-arg="${k}">${l}</button>`).join('')}</div>
    <div role="tabpanel" id="rs-panel" aria-label="${esc((RS_TABS.find(([k]) => k === S.rs.tab) || [, ''])[1])}">
    ${rsModelList()}
    ${views[S.rs.tab]()}</div>`;
}
