/* 초반 1~3화: 집필 화면의 초반 점검 카드(지표, 흡입력 판정, 여는 방식 여러 안)와 플롯 편집기의 여는 방식 플롯 안.
   app.js 의 S, actions, api, render, startJob, jobBtn 을 그대로 쓴다. 서버는 web.py 의 '4-2. 초반 1~3화'.
   여러 안 본문은 연구 화면의 블라인드 비교와 같은 저장소(compare/NN)를 쓰고, 고르기도 같은 API 로 한다. */
'use strict';

const OPENING_EPISODES = 3;
const HOOK_DOTS = (k) => '●'.repeat(k) + '○'.repeat(5 - k);

Object.assign(S, {
  openingData: {},  // 화 → GET /opening (지표 경고, 판정, 비교본)
  openingWays: [],  // 고른 여는 방식 id
  openingPlots: {}, // 화 → 여는 방식 플롯 안 (반영 전). 하나를 골라도 다시 비교하게 남긴다
  openingUsed: {},  // 화 → 지금 플롯으로 고른 안 번호
  openingPrev: {},  // 화 → 안을 처음 고르기 전 플롯 (되돌리기)
  approaches: null, // 서버 OPENING_APPROACHES
});

JOB_DONE_MSG.hook = (j) => `${j.label}이 끝났어요.`;
JOB_DONE_MSG.openings = (j) => `${j.ep}화 여는 방식 플롯 안이 도착했어요. 플롯 화면에서 고르세요.`;
JOB_DONE_MSG.opening_drafts = (j) => `${j.ep}화를 여는 방식마다 썼어요. 읽고 고르세요.`;
JOB_PAGES.hook = ['write'];
JOB_PAGES.openings = ['arc', 'write'];
JOB_PAGES.opening_drafts = ['write'];
JOB_LINK.hook = (j) => `#/p/${enc(j.project)}/write/${j.ep}`;
JOB_LINK.openings = (j) => `#/p/${enc(j.project)}/arc`;
JOB_LINK.opening_drafts = (j) => `#/p/${enc(j.project)}/write/${j.ep}`;

const isOpening = (n) => n >= 1 && n <= OPENING_EPISODES;

async function openingLoad(n) {
  if (!S.approaches) {
    S.approaches = await api('GET', '/opening/approaches').catch(() => []);
    S.openingWays = S.approaches.filter((a) => a.default).map((a) => a.id);
  }
  if (!isOpening(n) || !ep(n)) return;
  S.openingData[n] = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/opening`).catch(() => null);
}

// app.js 의 applyJobResult 가 부른다
function openingJobResult(j) {
  if (j.kind === 'openings' && j.result) {
    S.openingPlots[j.ep] = j.result.options;
    S.selEp = j.ep;
    return;
  }
  // 판정과 여러 안 본문은 서버가 저장했다. 이 화의 점검 자료를 다시 받아 그린다.
  openingLoad(j.ep).then(() => {
    const d = S.openingData[j.ep];
    const e = ep(j.ep);
    if (j.kind === 'hook' && d && e && !j.label.includes('비교본')) e.hook = d.hook;  // 본문 판정은 서버가 작품에 붙였다
    if (!isTyping()) render();  // 입력 중이면 다음에 그릴 때 보인다 (pollJobs 와 같은 규칙)
  });
}

function openingWayPicker(disabled) {
  const list = S.approaches || [];
  return `<div class="grid-2">${list.map((a) => `<label class="check-row"><input type="checkbox" data-opening-way="${esc(a.id)}"${S.openingWays.includes(a.id) ? ' checked' : ''}${disabled ? ' disabled' : ''}>
      <span><strong>${esc(a.label)}</strong><br><span class="small">${esc(a.how)}</span></span></label>`).join('')}</div>
    <div class="small">2~4개를 고르세요. 안마다 같은 플롯과 자료로 쓰고, 여는 방식만 다르게 지시해요.</div>`;
}

function hookView(h, stale) {
  if (!h) return '';
  const items = h.items.map((it) => `<li><div class="between"><strong>${esc(it.aspect)}</strong><span class="mono" aria-label="${it.score}점" style="letter-spacing:2px">${HOOK_DOTS(it.score)}</span></div>
      <div style="font-size:0.8125rem;line-height:1.55">${esc(it.note)}</div>
      ${it.quote ? `<div style="font-family:var(--serif);font-size:0.8125rem;line-height:1.7;color:var(--text-2)">“${esc(it.quote)}”</div>` : ''}</li>`).join('');
  return `<div class="field" style="gap:8px">
      ${stale ? '<div class="note warn">판정한 뒤 본문이 바뀌었어요. 다시 판정하세요.</div>' : ''}
      <div class="row"><span class="chip ${h.next_click ? 'finalized' : 'written'}">${h.next_click ? '다음 화를 누른다' : '여기서 내릴 수 있다'}</span>
        <span class="small">전제가 나오는 곳: ${h.premise_at >= 0 ? `${h.premise_at.toLocaleString()}자` : '찾지 못함'}</span></div>
      <div style="font-size:0.8125rem;line-height:1.6">${esc(h.reason)}</div>
      ${h.reader_question ? `<div class="note plain"><strong>독자가 들고 갈 질문</strong> · ${esc(h.reader_question)}</div>` : '<div class="note warn">마지막 장면에서 독자가 들고 갈 질문이 보이지 않아요.</div>'}
      <ul class="panel-list" style="gap:0">${items}</ul>
    </div>`;
}

function openingMetricsLine(m) {
  if (!m) return '';
  const at = (v) => (v == null ? '없음' : `${v.toLocaleString()}자`);
  return `<div class="small">첫 대사 ${at(m.first_dialogue_at)} · 주인공 이름 ${at(m.hero_at)} · 이름 나온 인물 ${m.named.length}명 · 앞 3분의 1 대사 ${m.head_dialogue_ratio} · 대사 없이 가장 길게 ${m.longest_narration.toLocaleString()}자</div>`;
}

// 집필 화면 아래에 붙는 초반 점검 카드
function openingPanel(n) {
  if (!isOpening(n)) return '';
  const e = ep(n);
  const d = S.openingData[n];
  const blocked = P().episodes.some((x) => x.plot.number < n && x.status !== 'finalized');
  const canWrite = e.status !== 'draft' && !blocked && S.mode === 'api';
  const hookBtn = jobBtn('hook', n, e.hook ? '다시 판정' : '흡입력 판정');
  const hookRunning = !!jobFor('hook', n);
  const draftsBtn = jobBtn('opening_drafts', n, '여러 안으로 쓰기');
  const c = d && d.compare;
  const reveal = c && c.order;
  const finalized = e.status === 'finalized';
  const drafts = c ? c.drafts.map((x) => `<section class="card tight${c.picked === x.n ? ' rs-picked' : ''}" style="min-width:0">
      <div class="between"><h3>${x.n}번${reveal ? ` <span class="chip ai">${esc(c.order[x.n - 1])}</span>` : ''}</h3>
        ${c.picked ? (c.picked === x.n ? '<span class="chip finalized">고름</span>' : '') : `<button class="btn small primary" data-action="openingPick" data-arg="${n}:${x.n}"${finalized ? ' disabled' : ''}>이 안 쓰기</button>`}</div>
      <div class="small">${x.chars.toLocaleString()}자 · 대사 ${x.dialogue_ratio}</div>
      ${x.opening.length ? `<div class="note warn">${x.opening.map(esc).join('<br>')}</div>` : '<div class="note ok">초반 지표 경고 없음</div>'}
      ${x.hook ? hookView(x.hook, false) : `<button class="btn small" data-action="openingHookDraft" data-arg="${n}:${x.n}"${hookRunning ? ' disabled' : ''}>이 안 판정</button>`}
      <details><summary class="small">본문 읽기</summary><div class="rs-prose">${esc(x.text)}</div></details>
    </section>`).join('') : '';
  return `<section class="card" aria-label="초반 점검">
      <div class="between"><h2>초반 점검</h2><span class="small">${n}화는 독자가 계속 읽을지 정하는 화예요</span></div>
      <div class="cols" style="gap:16px">
        <div class="col" style="flex:1 1 300px;min-width:0;display:flex;flex-direction:column;gap:10px">
          <h3>지표</h3>
          ${!e.text ? '<div class="small">본문을 쓰면 첫 대사 위치, 설정 설명 밀도, 등장인물 수, 흔한 시작과 끝을 재요.</div>'
            : !d ? '<div class="small">재는 중…</div>'
            : d.warnings.length ? `<div class="note warn"><ul style="padding-left:18px;display:flex;flex-direction:column;gap:4px">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>` : '<div class="note ok">기준을 넘은 초반 지표가 없어요.</div>'}
          ${d && d.metrics ? openingMetricsLine(d.metrics) : ''}
          <div class="small">AI를 부르지 않고 재요. 기준은 출발점이라 작품에 맞지 않으면 무시해도 돼요.</div>
        </div>
        <div class="col" style="flex:1 1 300px;min-width:0;display:flex;flex-direction:column;gap:10px">
          <div class="between"><h3>흡입력 판정</h3><button class="btn small" data-action="openingHook" data-arg="${n}"${e.text ? hookBtn.attr : ' disabled'}>${hookBtn.label}</button></div>
          ${e.hook ? hookView(e.hook, d && d.hook_stale) : '<div class="small">AI 편집자가 첫 문단, 주인공, 전제, 설명 부담, 걸린 것, 장르 약속, 엔딩을 근거 문장과 함께 봐요. 본문에서 찾을 수 없는 근거는 지우고 1점으로 내려요.</div>'}
        </div>
      </div>
      <h3>여는 방식 비교</h3>
      <div class="small">같은 화를 여는 방식만 달리해 여러 안으로 쓰고, 어느 방식인지 가린 채 읽고 골라요. 고른 안이 이 화 본문이 돼요.</div>
      ${openingWayPicker(!canWrite)}
      <div class="row"><button class="btn dark" data-action="openingDrafts" data-arg="${n}"${canWrite ? draftsBtn.attr : ' disabled'}>${draftsBtn.label}</button>
        ${!canWrite ? `<span class="small">${e.status === 'draft' ? '플롯을 확정하면 쓸 수 있어요' : blocked ? '이전 화를 반영해야 쓸 수 있어요' : 'Gemini API 방식에서 쓸 수 있어요'}</span>` : ''}</div>
      ${c ? `<div class="small">${esc(fmtDateTime(c.created))}에 쓴 ${c.kind === 'opening' ? '여는 방식' : '백엔드'} 비교본${c.picked ? '' : ' · 고르기 전까지 가려요'}${finalized && !c.picked ? ' · 반영이 끝난 화라 고를 수 없어요' : ''}</div><div class="rs-compare">${drafts}</div>` : ''}
    </section>`;
}

// 플롯 편집기에 붙는 여는 방식 플롯 안
function openingPlotBlock(e) {
  const n = e.plot.number;
  if (!isOpening(n) || e.status === 'written' || e.status === 'finalized') return '';
  const btn = jobBtn('openings', n, S.openingPlots[n] ? '플롯 안 다시 받기' : '여는 방식별 플롯 안 받기');
  const used = S.openingUsed[n];
  const opts = (S.openingPlots[n] || []).map((o, i) => {
    const a = (S.approaches || []).find((x) => x.id === o.approach);
    const p = openingEffective(e, o.plot);
    const diff = used === i ? '' : plotDiff(p);
    const count = (diff.match(/class="diff-row"/g) || []).length;
    return `<div class="card tight" style="gap:6px">
        <div class="between"><strong>${esc(a ? a.label : o.approach)} · ${esc(p.title)}</strong>${used === i ? '<span class="chip confirmed">지금 플롯</span>' : `<button class="btn small primary" data-action="openingUsePlot" data-arg="${n}:${i}">이 안으로</button>`}</div>
        <div class="small">${esc(o.pitch)}</div>
        ${p.reader_question ? `<div style="font-size:0.8125rem"><strong>독자 질문</strong> · ${esc(p.reader_question)}</div>` : ''}
        ${used === i ? '' : `<details${i === 0 ? ' open' : ''}><summary class="small">지금 플롯과 비교 · 바뀌는 칸 ${count}개</summary><div class="diff">${diff}</div></details>`}
      </div>`;
  }).join('');
  const prev = S.openingPrev[n];
  return `<details${S.openingPlots[n] ? ' open' : ''}><summary style="font-weight:700;font-size:0.875rem">초반 화 · 여는 방식 고르기</summary>
      <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px">
        <div class="small">${n}화 플롯을 여는 방식마다 하나씩 받아 비교해요. 고른 안이 이 화 플롯이 되고, 확정했던 화는 초안으로 돌아가요.</div>
        ${openingWayPicker(false)}
        <div class="row"><button class="btn" data-action="openingPlots" data-arg="${n}"${btn.attr}>${btn.label}</button>${S.openingPlots[n] ? `<button class="btn small" data-action="openingDropPlots" data-arg="${n}">안 모두 버리기</button>` : ''}${prev ? `<button class="btn small" data-action="openingUndoPlot" data-arg="${n}">고르기 전 플롯으로 되돌리기</button>` : ''}</div>
        ${opts}
      </div></details>`;
}

/** 안을 고르면 실제로 들어갈 플롯 (pipeline.apply_opening 과 같은 규칙: 시점, 서술 방식, 회수 복선, 넣어 둔 인물은 지금 것을 지킨다). */
function openingEffective(e, plot) {
  const cur = e.plot;
  return { ...plot, pov: cur.pov || plot.pov, pov_mode: cur.pov_mode || plot.pov_mode,
    foreshadow_payoff: cur.foreshadow_payoff.length ? cur.foreshadow_payoff : plot.foreshadow_payoff,
    characters: [...new Set([...cur.characters, ...plot.characters])] };
}

function openingWaysOk() {
  if (S.openingWays.length < 2 || S.openingWays.length > 4) {
    toast('여는 방식을 2~4개 고르세요', true);
    return false;
  }
  return true;
}

Object.assign(actions, {
  openingHook(n) {
    startJob('hook', n);
  },
  openingHookDraft(arg) {
    const [n, k] = String(arg).split(':').map(Number);
    startJob('hook', n, { draft: k });
  },
  openingDrafts(n) {
    if (!openingWaysOk()) return;
    const d = S.openingData[n];
    if (d && d.compare && !d.compare.picked && !confirm(`${n}화의 고르지 않은 비교본을 새로 쓴 것으로 바꿀까요?`)) return;
    startJob('opening_drafts', n, { approaches: S.openingWays });
  },
  openingPlots(n) {
    if (!openingWaysOk()) return;
    const have = (S.openingPlots[n] || []).length;
    if (have && !confirm(`받아 둔 안 ${have}개를 버리고 새로 받을까요?`)) return;
    startJob('openings', n, { approaches: S.openingWays });
  },
  async openingUsePlot(arg) {
    const [n, i] = String(arg).split(':').map(Number);
    const o = (S.openingPlots[n] || [])[i];
    if (!o) return;
    const e = ep(n);
    if (!confirm(`${n}화 플롯을 이 안으로 바꿀까요?${e.status === 'confirmed' ? ' 확정이 풀려 다시 확정해야 해요.' : ''} 지금 플롯은 '고르기 전 플롯으로 되돌리기'로 되찾을 수 있어요.`)) return;
    await run('플롯을 바꾸는 중', async () => {
      await saveIfDirty();
      if (S.openingUsed[n] === undefined) S.openingPrev[n] = structuredClone(ep(n).plot);  // 처음 고를 때의 플롯을 되돌리기용으로 둔다
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/opening-plot`, { plot: o.plot });
      S.openingUsed[n] = i;  // 다른 안과 다시 비교하고 바꿀 수 있게 안은 남긴다
      S.dirty = false;
      toast(`${n}화 플롯을 바꿨어요. 읽어 보고 확정하세요`);
    });
  },
  async openingUndoPlot(n) {
    n = Number(n);
    if (!confirm(`${n}화 플롯을 안을 고르기 전으로 되돌릴까요?`)) return;
    await run('플롯을 되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/opening-plot`, { plot: S.openingPrev[n] });
      delete S.openingPrev[n];
      delete S.openingUsed[n];
      S.dirty = false;
      toast(`${n}화 플롯을 되돌렸어요. 확정했던 화였다면 다시 확정하세요`);
    });
  },
  openingDropPlots(n) {
    n = Number(n);
    if (!confirmDrop(`${n}화 여는 방식 플롯 안`)) return;
    delete S.openingPlots[n];
    delete S.openingUsed[n];
    render();
  },
  async openingPick(arg) {
    const [n, k] = String(arg).split(':').map(Number);
    const unsaved = textUnsaved(n);
    if ((ep(n).text || unsaved) && !confirm(`${k}번을 ${n}화 본문으로 바꿀까요?${unsaved ? '\n고치던 본문은 먼저 저장해 이전 판에 남겨요.' : ''}`)) return;
    await run('공개하는 중', async () => {
      await saveIfDirty();
      await flushText(n);  // 저장하지 않은 본문을 먼저 저장해야 바꿀 때 이전 판에 남는다 (rwAdopt 와 같다)
      const r = await api('POST', `/projects/${enc(S.name)}/research/compare/${n}/pick`, { k, adopt: true });
      S.project = r.project;
      delete S.textDraft[n];
      delete S.deltas[n];
      await openingLoad(n);
      toast(`${k}번은 ${r.result.picked} 였어요. ${n}화 본문으로 저장했어요`);
    });
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || t.dataset.openingWay === undefined) return;
  const id = t.dataset.openingWay;
  S.openingWays = t.checked ? [...new Set([...S.openingWays, id])] : S.openingWays.filter((x) => x !== id);
});
