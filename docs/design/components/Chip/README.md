# Chip

상태나 분류를 짧게 붙이는 작은 표로, `<span class="chip">`에 낱말 하나를 쓴다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 낱말 하나(`확정`, `작성됨`), 상태 클래스, 뜻을 더 말해야 하면 `title`.
- 화 상태: `.chip.draft` 초안, `.chip.confirmed` 확정, `.chip.written` 작성됨, `.chip.finalized` 반영 완료. 색은 README의 '화 상태 칩' 표를 따른다.
- `.chip.ai`는 AI가 쓴 것, `.chip.warn`은 사람이 볼 것(남겨 둔 제안 `제안 2`, 고친 칸 `고침`).
- 그 밖의 뜻 칩: `.chip.ok` 잘 됨(`green-soft` · `green-ink`), `.chip.bad` · `.chip.crit` 막힘 · 심각한 지적(`red-soft` · `err-ink`), `.chip.hot` 지금 바뀌는 칸(`accent` · `on-accent`, 대화 변경안이 건드린 카드). 화면 하나만 쓰는 칩(`.chip.csh-*` 인물 카드, `.chip.dev-*` 문체 장치, `.chip.usage-fail` 사용량, 쇠맛 실험실의 판정 칩 `.chip.v-*` · 출처 칩 `.chip.src` · 가린 조각 `.chip.hid` · 문장 비교 `.chip.same` · `.fp` · `.miss`)은 그 화면의 CSS에 있다(쇠맛 실험실은 `soelab.js` 가 주입).
- 쇠맛 실험실 판정 칩은 새 색 없이: 맞아요 `.v-yes`(`green-soft` · `green-ink`), 약해요 `.v-weak`(`amber-soft` · `amber-ink`), 근거 없음 `.v-none`(`chip` · `text-2`), 아직 모름 `.v-none.v-tbd`(같은 면에 1px 점선 `line-strong`, 1차 작가 판정 기준에서만), 반대 방향 `.v-rev`(`red-soft` · `err-ink`), 표본 부족 `.v-few`(투명 · `muted`, 1px `line-strong` 테두리), 모델마다 달라요 `.v-split`(투명 · `amber-ink`, 1px `amber` 테두리). 잴 수 없으면 칩 없이 `–`. 글자와 클래스는 `soeVerdict` 결과 하나에서 고른다(`labstats.verdict` 와 같은 규칙).
- 글자 `chip`(12px, 700), 안쪽 2px · 8px, 모서리 `radius-6`.

## 지킬 것

- 칩은 누르는 것이 아니다. 누르게 하려면 버튼을 쓴다.
- 색이 있는 칩도 늘 글자로 뜻을 말한다. 고대비에서는 테두리가 생긴다.
