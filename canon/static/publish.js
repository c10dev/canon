/* 복사 · 내보내기 (집필 화면 본문 띠의 분할 복사 버튼과 '여러 화 내보내기' 대화상자). 본문을 다른 사이트에 붙여 넣기 좋게 다듬어 클립보드에 넣거나 .txt 로 내려받는다.
   다듬는 규칙은 서버 canon/publish.py 한 곳에 있고, 여기서는 고른 형식으로 요청해 텍스트와 HTML 을 함께 복사한다.
   서식 있는 편집기(블로그, 플랫폼 에디터)는 HTML 을, 메모장 같은 곳은 텍스트를 받아 문단이 그대로 남는다. */
'use strict';

const copyPref = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const copyKeep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* 저장 못 해도 동작에는 상관없다 */ } };

Object.assign(S, {
  copyFormats: null,                               // 서버 publish.FORMATS
  copyFmt: copyPref('canon.copyFmt', 'blank'),        // 고른 형식
  copyTitle: copyPref('canon.copyTitle', '1') === '1', // 'N화. 제목' 줄을 넣을지
  copyRange: {},                                   // 작품 이름 → 여러 화 { from, to }
});

/** 이 작품의 여러 화 범위. 고치지 않았으면 쓴 첫 화 ~ 마지막 화. */
function copyRangeOf(nums) {
  return { from: nums[0], to: nums[nums.length - 1], ...S.copyRange[S.name] };
}

function writtenNums() {
  return P().episodes.filter((e) => e.text || liveDraft(e.plot.number) !== undefined).map((e) => e.plot.number);
}

/** 집필 화면 본문 띠의 분할 복사 버튼: '복사'는 고른 형식으로 이 화를 복사하고, ▾ 메뉴에서 형식 · 제목 줄 · .txt · 여러 화 내보내기를 고른다. */
function copySplit(n) {
  return `<div class="split"><button type="button" class="btn small" data-action="copyEp" data-arg="${n}" title="고른 줄바꿈 형식으로 복사해요 (▾에서 바꿔요)">복사</button>${menuBtn('copy', CHEVRON, () => copyMenu(n), { cls: 'btn small', aria: '복사 설정과 내보내기' })}</div>`;
}

function copyMenu(n) {
  const fmts = S.copyFormats || [];
  const nums = writtenNums();
  const r = copyRangeOf(nums);
  return `<fieldset class="pop-sec"><legend class="pop-legend">줄바꿈 형식</legend>
      ${fmts.map((f) => `<label class="pop-radio" for="copy-fmt-${esc(f.id)}"><input type="radio" name="copy-fmt" id="copy-fmt-${esc(f.id)}" value="${esc(f.id)}" data-copy="fmt"${f.id === S.copyFmt ? ' checked' : ''}><span><span>${esc(f.label)}</span>${f.id === S.copyFmt && f.hint ? `<span class="small">${esc(f.hint)}</span>` : ''}</span></label>`).join('')}
    </fieldset>
    <div class="pop-sec"><label class="pop-check" for="copy-title"><input type="checkbox" id="copy-title" data-copy="title"${S.copyTitle ? ' checked' : ''}> 맨 위에 '${n}화. 제목' 줄 넣기</label></div>
    <div class="pop-sep" role="separator"></div>
    <button type="button" class="pop-item" data-action="downloadTxt" data-arg="${n}-${n}">이 화 .txt로 내려받기</button>
    ${nums.length ? `<button type="button" class="pop-item" data-action="openExport" aria-haspopup="dialog">여러 화 내보내기…<span class="small">${r.from}~${r.to}화</span></button>` : ''}`;
}

/** '여러 화 내보내기' 대화상자. 형식과 제목 줄은 복사 메뉴와 같은 값을 쓴다. */
function exportDialogHtml() {
  const nums = writtenNums();
  const r = copyRangeOf(nums);
  const last = nums[nums.length - 1];
  const bad = r.from > r.to;
  const inv = bad ? ' aria-invalid="true" aria-describedby="copy-range-err"' : '';
  const fmt = ((S.copyFormats || []).find((f) => f.id === S.copyFmt) || {}).label || S.copyFmt;
  return `<div class="dlg-body">
    <div class="between"><strong id="w-export-title">여러 화 내보내기</strong><button type="button" class="btn small" data-action="closeDialog" data-arg="w-export">닫기</button></div>
    <div class="dlg-range"><span class="small">범위</span>
      <input type="number" id="copy-from" class="ep-num" min="1" max="${last}" value="${r.from}" data-copy="from" aria-label="시작 화"${inv}>~
      <input type="number" id="copy-to" class="ep-num" min="1" max="${last}" value="${r.to}" data-copy="to" aria-label="끝 화"${inv}>화</div>
    ${bad ? `<span class="small warn-text" id="copy-range-err">시작 화가 끝 화보다 커요. ${r.to}~${r.from}화로 바꿔 보세요</span>` : ''}
    <div class="note plain">줄바꿈 형식은 <strong>${esc(fmt)}</strong>예요. 화마다 제목 줄을 넣어 잇고, 본문이 없는 화는 건너뛰어요. 형식은 복사 ▾ 메뉴에서 바꿔요.</div>
    <div class="row" style="justify-content:flex-end;gap:8px">
      <button type="button" class="btn" data-action="downloadTxt" data-arg="${r.from}-${r.to}"${bad ? ' disabled' : ''}>.txt 내려받기</button>
      <button type="button" class="btn primary" data-action="copyRange"${bad ? ' disabled' : ''}>한꺼번에 복사</button></div>
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
  if (!ok) throw new Error('브라우저가 복사를 막았어요. .txt로 내려받아 주세요');
  return d;
}

/** 복사와 내려받기가 같은 본문을 내보낸다: 저장하지 않은 초안이 있으면 그 초안으로. */
function exportBody(episodes) {
  const drafts = {};
  episodes.forEach((x) => { if (liveDraft(x) !== undefined) drafts[x] = liveDraft(x); });
  return api('POST', `/projects/${enc(S.name)}/export`, { episodes, format: S.copyFmt, title: S.copyTitle, drafts });
}

async function copyEpisodes(episodes) {
  const pending = exportBody(episodes);
  try {
    const d = await copyBoth(pending);
    const lines = d.text.split('\n').length;
    toast(`${d.episodes.length > 1 ? `${d.episodes[0]}~${d.episodes[d.episodes.length - 1]}화 ` : ''}복사했어요 (${d.text.length.toLocaleString()}자, ${lines.toLocaleString()}줄)`);
  } catch (e) {
    toast(e.message, true);
  }
}

Object.assign(actions, {
  async downloadTxt(arg) {
    const [a, b] = String(arg).split('-').map(Number);
    const eps = writtenNums().filter((x) => x >= a && x <= b);
    if (!eps.length) return toast('그 범위에 본문이 있는 화가 없어요', true);
    try {
      const d = await exportBody(eps);
      const url = URL.createObjectURL(new Blob([d.text], { type: 'text/plain;charset=utf-8' }));
      const link = Object.assign(document.createElement('a'), { href: url, download: `${S.name}-${a === b ? `${a}화` : `${a}-${b}화`}.txt` });
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast(e.message, true);
    }
  },
  copyEp(n) {
    copyEpisodes([Number(n)]);
  },
  openExport() {
    showDialog('w-export', exportDialogHtml(), '[data-action="menuToggle"][data-arg="copy"]');
  },
  copyRange() {
    const nums = writtenNums();
    const r = copyRangeOf(nums);
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
    const last = nums[nums.length - 1];
    S.copyRange[S.name] = { ...copyRangeOf(nums), [k]: Math.min(last, Math.max(1, Number(e.target.value) || 1)) };
  }
  // 칸을 고치고 Tab 으로 옮길 때 change 가 먼저 온다. 포커스가 옮겨진 뒤 다시 채운다 (render 와 같은 까닭)
  if (document.getElementById('w-export')?.open) setTimeout(() => showDialog('w-export', exportDialogHtml()));
  render();  // 내려받기 주소와 설명을 새 값으로
});
