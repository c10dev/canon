# Chip

상태나 분류를 짧게 붙이는 작은 표로, `<span class="chip">`에 낱말 하나를 쓴다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 낱말 하나(`확정`, `작성됨`), 상태 클래스, 뜻을 더 말해야 하면 `title`.
- 화 상태: `.chip.draft` 초안, `.chip.confirmed` 확정, `.chip.written` 작성됨, `.chip.finalized` 반영 완료. 색은 README의 '화 상태 칩' 표를 따른다.
- `.chip.ai`는 AI가 쓴 것, `.chip.warn`은 사람이 볼 것(남겨 둔 제안 `제안 2`, 고친 칸 `고침`).
- 그 밖의 뜻 칩: `.chip.ok` 잘 됨(`green-soft` · `green-ink`), `.chip.bad` · `.chip.crit` 막힘 · 심각한 지적(`red-soft` · `err-ink`), `.chip.hot` 지금 바뀌는 칸(`accent` · `on-accent`, 대화 변경안이 건드린 카드). 화면 하나만 쓰는 칩(`.chip.csh-*` 인물 카드, `.chip.dev-*` 문체 장치, `.chip.usage-fail` 사용량)은 그 화면의 CSS에 있다.
- 글자 `chip`(12px, 700), 안쪽 2px · 8px, 모서리 `radius-6`.

## 지킬 것

- 칩은 누르는 것이 아니다. 누르게 하려면 버튼을 쓴다.
- 색이 있는 칩도 늘 글자로 뜻을 말한다. 고대비에서는 테두리가 생긴다.
