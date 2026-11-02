/* 작품 정착 문체: 문체 화면의 '작품 정착 문체' 카드 (고를 화 · 대표 문단 고르기, 기준 비교, 화별 문체 거리 추이).
   app.js 의 S, actions, api, run, render, toast, askConfirm, saveIfDirty 를 그대로 쓴다.
   서버는 web.py 의 '2-0. 작품 정착 문체', 계산은 canon/anchor.py (LLM 없음). */
'use strict';

Object.assign(S, {
  anchorView: null,   // GET /style/anchor
  anchorPick: null,   // 고르는 중인 화 번호 배열 (null 이면 고르지 않는 중)
  anchorCands: null,  // { passages, chars, later }: 고른 화의 대표 문단 후보
  anchorPass: {},     // 후보 번호 → 체크
});

async function anchorLoad() {
  S.anchorView = await api('GET', `/projects/${enc(S.name)}/style/anchor`).catch(() => null);
}

const anchorNum = (v) => (v == null ? '–' : Number(v).toFixed(2));
const anchorPct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);

function anchorTocWord() {
  const v = S.anchorView;
  if (!v || !v.anchor) return '';
  if (v.anchor.stale) return '다시 재기';
  const last = [...v.trend].reverse().find((t) => t.rolling != null);
  return last && last.rolling > v.warn ? '멀어짐' : rangeText(v.anchor.episodes) + '화';
}

/** 기준 비교 표: 정착 문체 · 레퍼런스 */
function anchorCompare(v) {
  const a = v.anchor && v.anchor.metrics;
  const r = v.reference;
  if (!a) return '';
  const row = (k, f) => `<tr><th scope="row">${k}</th><td>${f(a)}</td><td>${r ? f(r) : '–'}</td></tr>`;
  return `<table class="tbl small anchor-cmp"><thead><tr><th></th><th scope="col">정착 문체</th><th scope="col">레퍼런스</th></tr></thead><tbody>
      ${row('글자 수', (m) => m.chars.toLocaleString())}${row('문장 평균 길이', (m) => `${m.sentence_len.toFixed(1)}자`)}
      ${row('대사 비율', (m) => anchorPct(m.dialogue_ratio))}${row('과거형 비율', (m) => anchorPct(m.past_tense_ratio))}</tbody></table>`;
}

/** 화별 문체 거리 추이 (SVG). 띠는 사람 연재가 머문 범위, 점선은 흐름 경고 기준. 서술 말투 화는 빠진다 */
function anchorChart(v) {
  const pts = v.trend.filter((t) => t.distance != null);
  if (pts.length < 2) return '<p class="small">정착 화 뒤로 화가 쌓이면 화별 문체 거리를 그려요.</p>';
  const W = 640, H = 180, L = 34, R = 8, T = 8, B = 22;
  const n0 = v.trend[0].n, n1 = v.trend[v.trend.length - 1].n;
  const top = Math.max(1.6, ...pts.map((t) => t.distance)) ;
  const x = (n) => L + (n1 === n0 ? 0 : ((n - n0) / (n1 - n0)) * (W - L - R));
  const y = (d) => T + (1 - d / top) * (H - T - B);
  const band = `<rect x="${L}" y="${y(v.band[1])}" width="${W - L - R}" height="${y(v.band[0]) - y(v.band[1])}" class="anchor-band"><title>사람 연재가 80화 뒤 머문 범위 ${v.band[0]}~${v.band[1]}</title></rect>`;
  const warn = `<line x1="${L}" x2="${W - R}" y1="${y(v.warn)}" y2="${y(v.warn)}" class="anchor-warn"><title>흐름 경고 기준 ${v.warn}</title></line>`;
  const roll = v.trend.filter((t) => t.rolling != null);
  const path = roll.map((t, i) => `${i ? 'L' : 'M'}${x(t.n).toFixed(1)},${y(t.rolling).toFixed(1)}`).join('');
  const dots = pts.map((t) => `<circle cx="${x(t.n).toFixed(1)}" cy="${y(t.distance).toFixed(1)}" r="${t.anchor ? 3.5 : 2.2}" class="${t.anchor ? 'anchor-dot own' : t.auto ? 'anchor-dot auto' : 'anchor-dot'}"><title>${t.n}화 ${anchorNum(t.distance)}${t.anchor ? ' (정착 화)' : ''}${t.auto ? ' · 자동 집필' : ''}</title></circle>`).join('');
  const marks = v.trend.filter((t) => t.changed).map((t) => `<line x1="${x(t.n)}" x2="${x(t.n)}" y1="${T}" y2="${H - B}" class="anchor-change"><title>${t.n}화부터 문체(프로필 · 대표 문단)가 바뀜</title></line>`).join('');
  const ticks = [0, 0.5, 1, 1.5].filter((d) => d <= top).map((d) => `<text x="${L - 4}" y="${y(d) + 3}" class="anchor-tick" text-anchor="end">${d}</text>`).join('');
  return `<figure class="anchor-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="화별 정착 문체 거리. ${n0}화부터 ${n1}화까지">
      ${band}${warn}${marks}<path d="${path}" class="anchor-roll"></path>${dots}${ticks}
      <text x="${L}" y="${H - 6}" class="anchor-tick">${n0}화</text><text x="${W - R}" y="${H - 6}" class="anchor-tick" text-anchor="end">${n1}화</text></svg>
    <figcaption class="small">점은 화마다 정착 문체에서 떨어진 거리, 선은 최근 ${v.window}화 평균이에요. 띠는 사람이 쓴 웹소설이 80화 뒤 머문 범위(${v.band[0]}~${v.band[1]})이고, 점선(${v.warn})을 넘으면 다른 작품 글 쪽에 가까워요(다른 작품끼리 평균 ${v.other}). 세로선은 문체를 바꾼 화예요.</figcaption></figure>`;
}

/** 고르기: 화 칩 · 대표 문단 후보 */
function anchorChooser(v) {
  const pick = new Set(S.anchorPick || []);
  const chips = v.usable.map((n) => `<label class="chip-check"><input type="checkbox" data-anchor-ep="${n}"${pick.has(n) ? ' checked' : ''}><span>${n}화</span></label>`).join('');
  const c = S.anchorCands;
  const cands = c ? `<div class="anchor-cands"><p class="small">고른 화 ${c.chars.toLocaleString()}자${c.later != null ? ` · 그 뒤 화들이 이 기준에서 평균 ${anchorNum(c.later)} 떨어져 있어요${c.later > v.band[1] ? '. 고른 화가 뒤 화와 꽤 달라요. 다른 화를 고르는 것도 생각해 보세요' : ''}` : ''}. 대표 문단은 ${'4'}개까지 골라요. 고르면 쓰기 프롬프트의 문체 예시가 레퍼런스 대신 이 문단이 돼요.</p>
      ${c.passages.map((t, i) => `<label class="anchor-cand"><input type="checkbox" data-anchor-pass="${i}"${S.anchorPass[i] ? ' checked' : ''}><span>${esc(t)}</span></label>`).join('') || '<p class="small">후보로 쓸 만한 문단 묶음이 없어요. 대표 문단 없이 저장하면 문체 예시는 레퍼런스 것을 그대로 써요.</p>'}</div>` : '';
  return `<div class="anchor-pick">
      <p class="small">상태 반영이 끝난 화 가운데 이 작품의 목소리가 잘 굳은 화를 골라요. 서술 말투가 있는 시점 인물의 화는 고를 수 없어요. 합쳐 ${v.min_chars.toLocaleString()}자 넘게 골라야 문체 거리를 재요.</p>
      <div class="anchor-eps">${chips || '<span class="small">고를 수 있는 화가 아직 없어요</span>'}</div>
      <div class="row"><button type="button" class="btn small" data-action="anchorCands"${pick.size ? '' : ' disabled'}>대표 문단 후보 보기</button>
        <button type="button" class="btn small primary" data-action="anchorSave"${pick.size ? '' : ' disabled'}>정착 문체로 저장</button>
        <button type="button" class="btn small ghost" data-action="anchorCancel">취소</button></div>
      ${cands}</div>`;
}

function anchorCard() {
  const v = S.anchorView;
  if (!v) return '';
  const a = v.anchor;
  const choosing = S.anchorPick !== null;
  const last = [...v.trend].reverse().find((t) => t.rolling != null);
  const head = `<div class="pf-head"><h2>작품 정착 문체</h2><div class="row">${a && !choosing ? `<button type="button" class="btn small" data-action="anchorStart">다시 고르기</button><button type="button" class="btn small ghost" data-action="anchorDrop">지우기</button>` : ''}${!a && !choosing ? `<button type="button" class="btn small primary" data-action="anchorStart"${v.usable.length ? '' : ' disabled'}>정착 화 고르기</button>` : ''}</div></div>`;
  const intro = '<p class="small pf-sub">레퍼런스는 따라갈 목표이고, 정착 문체는 이 작품이 앞 화에서 실제로 굳힌 목소리예요. 정하면 문체 경고와 화별 흐름이 이 기준을 보고, 고른 대표 문단이 쓰기 프롬프트의 문체 예시가 돼요. 라이브러리에는 올리지 않아요.</p>';
  if (!a) {
    return `<section class="card pf-sec" id="pf-anchor" tabindex="-1">${head}${intro}${choosing ? anchorChooser(v) : (v.usable.length ? `<p class="small">추천: ${rangeText(v.suggest)}화</p>` : '<p class="small">상태 반영이 끝난 화가 생기면 고를 수 있어요.</p>')}</section>`;
  }
  const notes = [];
  if (a.stale) notes.push(`<div class="note warn between" role="status"><span>정착 화 본문이 잰 뒤로 바뀌었어요. 기준은 마지막으로 잰 값을 그대로 써요.</span><button type="button" class="btn small" data-action="anchorRemeasure">다시 재기</button></div>`);
  if (a.later != null && a.later > v.band[1]) notes.push(`<div class="note plain small">잴 때 그 뒤 화들이 평균 ${anchorNum(a.later)} 떨어져 있었어요. 고른 화가 뒤 화와 꽤 달라요.</div>`);
  if (last && last.rolling > v.warn) notes.push(`<div class="note warn small" role="status">최근 ${v.window}화 평균 ${anchorNum(last.rolling)}로 정착 문체에서 멀어졌어요 (${last.n}화까지). 다른 작품 글 쪽에 가까워요.</div>`);
  if (!(a.metrics && a.metrics.distance_ready)) notes.push(`<div class="note plain small">고른 화가 짧아 문체 거리를 재지 못해요. ${v.min_chars.toLocaleString()}자 넘게 골라 주세요.</div>`);
  const pass = a.passages.length
    ? `<details class="anchor-pass"><summary class="small">대표 문단 ${a.passages.length}개 (쓰기 프롬프트의 문체 예시)</summary>${a.passages.map((t) => `<blockquote class="small">${esc(t)}</blockquote>`).join('')}</details>`
    : '<p class="small">대표 문단을 고르지 않아 문체 예시는 레퍼런스 것을 써요.</p>';
  return `<section class="card pf-sec" id="pf-anchor" tabindex="-1">${head}
      <p class="small pf-sub">정착 화 ${rangeText(a.episodes)}화 · ${fmtDateTime(a.at)}에 쟀어요${last ? ` · 최근 ${v.window}화 평균 ${anchorNum(last.rolling)}` : ''}</p>
      ${notes.join('')}${choosing ? anchorChooser(v) : `${anchorCompare(v)}${pass}${anchorChart(v)}`}</section>`;
}

document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.dataset.anchorEp !== undefined) {
    const n = Number(t.dataset.anchorEp);
    const s = new Set(S.anchorPick || []);
    if (t.checked) s.add(n); else s.delete(n);
    S.anchorPick = [...s].sort((a, b) => a - b);
    S.anchorCands = null;
    S.anchorPass = {};
    render();
  } else if (t.dataset.anchorPass !== undefined) {
    const i = Number(t.dataset.anchorPass);
    const on = Object.values(S.anchorPass).filter(Boolean).length;
    if (t.checked && on >= 4) { t.checked = false; toast('대표 문단은 4개까지 고를 수 있어요', true); return; }
    S.anchorPass[i] = t.checked;
  }
});

const anchorBody = () => ({
  episodes: S.anchorPick || [],
  passages: S.anchorCands ? S.anchorCands.passages.filter((_, i) => S.anchorPass[i]) : [],
});

Object.assign(actions, {
  anchorStart() {
    const v = S.anchorView;
    S.anchorPick = v.anchor ? [...v.anchor.episodes] : [...v.suggest];
    S.anchorCands = null;
    S.anchorPass = {};
    render();
  },
  anchorCancel() {
    S.anchorPick = null;
    S.anchorCands = null;
    render();
  },
  async anchorCands() {
    await run('대표 문단 후보를 찾는 중', async () => {
      S.anchorCands = await api('POST', `/projects/${enc(S.name)}/style/anchor/candidates`, { episodes: S.anchorPick, passages: [] });
      S.anchorPass = {};
    });
  },
  async anchorSave() {
    await run('정착 문체를 재는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/style/anchor`, anchorBody());
      S.anchorPick = null;
      S.anchorCands = null;
      await anchorLoad();
      toast('정착 문체를 저장했어요. 다음 화부터 문체 경고와 문체 예시가 이 기준을 봐요');
    });
  },
  async anchorRemeasure() {
    const a = S.anchorView.anchor;
    await run('정착 문체를 다시 재는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/style/anchor`, { episodes: a.episodes, passages: a.passages });
      await anchorLoad();
      toast('정착 문체를 다시 쟀어요');
    });
  },
  async anchorDrop() {
    if (!await askConfirm('정착 문체를 지울까요? 문체 경고와 문체 예시가 레퍼런스 기준으로 돌아가요.', { ok: '지우기', danger: true })) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/style/anchor`);
      await anchorLoad();
      toast('정착 문체를 지웠어요');
    });
  },
});
