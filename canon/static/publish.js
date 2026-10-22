/* 복사 · 내보내기 (집필 화면). 본문을 다른 사이트에 붙여 넣기 좋게 다듬어 클립보드에 넣거나 .txt 로 내려받는다.
   다듬는 규칙은 서버 canon/publish.py 한 곳에 있고, 여기서는 고른 형식으로 요청해 텍스트와 HTML 을 함께 복사한다.
   서식 있는 편집기(블로그, 플랫폼 에디터)는 HTML 을, 메모장 같은 곳은 텍스트를 받아 문단이 그대로 남는다. */
'use strict';

const copyPref = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const copyKeep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* 저장 못 해도 동작에는 상관없다 */ } };

Object.assign(S, {
  copyFormats: null,                               // 서버 publish.FORMATS
  copyFmt: copyPref('canon.copyFmt', 'blank'),        // 고른 형식
  copyTitle: copyPref('canon.copyTitle', '1') === '1', // 'N화. 제목' 줄을 넣을지
  copyRange: null,                                 // 여러 화 { from, to }
});

function writtenNums() {
  return P().episodes.filter((e) => e.text || S.textDraft[e.plot.number] !== undefined).map((e) => e.plot.number);
}

function exportQuery(from, to) {
  return `start=${from}&end=${to}&format=${enc(S.copyFmt)}&title=${S.copyTitle}`;
}

/** 오른쪽 위 '복사 · 내보내기' 카드. */
function exportCard(n) {
  const nums = writtenNums();
  if (!nums.length) return '';
  const r = S.copyRange || { from: nums[0], to: nums[nums.length - 1] };
  const fmts = S.copyFormats || [];
  const hint = (fmts.find((f) => f.id === S.copyFmt) || {}).hint || '';
  const has = nums.includes(n);
  return `<div class="export">
    <h3>복사 · 내보내기</h3>
    <div class="field"><label for="copy-fmt" class="small">줄바꿈 형식</label>
      <select id="copy-fmt" data-copy="fmt">${fmts.map((f) => `<option value="${esc(f.id)}"${f.id === S.copyFmt ? ' selected' : ''}>${esc(f.label)}</option>`).join('')}</select>
      ${hint ? `<span class="small">${esc(hint)}</span>` : ''}</div>
    <label class="row small" style="gap:6px"><input type="checkbox" data-copy="title"${S.copyTitle ? ' checked' : ''}> 맨 위에 '${n}화. 제목' 줄 넣기</label>
    ${has ? `<div class="row" style="gap:6px"><button type="button" class="btn small primary" data-action="copyEp" data-arg="${n}">이 화 복사</button>
      <a class="btn small" href="/api/projects/${enc(S.name)}/export.txt?${exportQuery(n, n)}" download>.txt</a></div>` : ''}
    <div class="row small" style="gap:6px;margin-top:4px">여러 화
      <input type="number" class="ep-num" min="1" value="${r.from}" data-copy="from" aria-label="시작 화">~
      <input type="number" class="ep-num" min="1" value="${r.to}" data-copy="to" aria-label="끝 화">화</div>
    <div class="row" style="gap:6px"><button type="button" class="btn small" data-action="copyRange">한꺼번에 복사</button>
      <a class="btn small" href="/api/projects/${enc(S.name)}/export.txt?${exportQuery(r.from, r.to)}" download>.txt 내려받기</a></div>
    <span class="small">여러 화는 화마다 제목 줄을 넣어 잇고, 본문이 없는 화는 건너뜁니다.</span>
  </div>`;
}

/** 텍스트와 HTML 을 함께 클립보드에 넣는다. 보안 연결이 아니면(예: Tailscale 주소로 연 http) 복사 이벤트로 넣는다. */
async function copyBoth(pending) {
  if (window.isSecureContext && navigator.clipboard && window.ClipboardItem) {
    try {
      // 데이터를 기다리는 동안에도 클릭 직후에 부른 것으로 쳐 주도록 약속(Promise)을 그대로 넘긴다 (Safari)
      await navigator.clipboard.write([new ClipboardItem({
        'text/plain': pending.then((d) => new Blob([d.text], { type: 'text/plain' })),
        'text/html': pending.then((d) => new Blob([d.html], { type: 'text/html' })),
      })]);
      return await pending;
    } catch { /* 아래 방법으로 */ }
  }
  const d = await pending;
  const put = (e) => {
    e.clipboardData.setData('text/plain', d.text);
    e.clipboardData.setData('text/html', d.html);
    e.preventDefault();
  };
  document.addEventListener('copy', put, { once: true });
  const ok = document.execCommand('copy');
  document.removeEventListener('copy', put);
  if (!ok) throw new Error('브라우저가 복사를 막았어요. .txt 로 내려받아 주세요');
  return d;
}

async function copyEpisodes(episodes) {
  const drafts = {};
  episodes.forEach((x) => { if (S.textDraft[x] !== undefined) drafts[x] = S.textDraft[x]; });
  const pending = api('POST', `/projects/${enc(S.name)}/export`, { episodes, format: S.copyFmt, title: S.copyTitle, drafts });
  try {
    const d = await copyBoth(pending);
    const lines = d.text.split('\n').length;
    toast(`${d.episodes.length > 1 ? `${d.episodes[0]}~${d.episodes[d.episodes.length - 1]}화 ` : ''}복사했어요 (${d.text.length.toLocaleString()}자, ${lines.toLocaleString()}줄)`);
  } catch (e) {
    toast(e.message, true);
  }
}

Object.assign(actions, {
  copyEp(n) {
    copyEpisodes([Number(n)]);
  },
  copyRange() {
    const nums = writtenNums();
    const r = S.copyRange || { from: nums[0], to: nums[nums.length - 1] };
    const eps = nums.filter((x) => x >= r.from && x <= r.to);
    if (!eps.length) return toast('그 범위에 본문이 있는 화가 없어요', true);
    copyEpisodes(eps);
  },
});

document.addEventListener('change', (e) => {
  const k = e.target.dataset && e.target.dataset.copy;
  if (!k) return;
  if (k === 'fmt') copyKeep('canon.copyFmt', S.copyFmt = e.target.value);
  if (k === 'title') copyKeep('canon.copyTitle', (S.copyTitle = e.target.checked) ? '1' : '0');
  if (k === 'from' || k === 'to') {
    const nums = writtenNums();
    S.copyRange = { from: nums[0], to: nums[nums.length - 1], ...S.copyRange, [k]: Math.max(1, Number(e.target.value) || 1) };
  }
  render();  // 내려받기 주소와 설명을 새 값으로
});
