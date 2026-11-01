# Seg

여럿 중 하나를 고르는 나눔 버튼으로, `<div class="seg" role="group">` 안에 `aria-pressed` 버튼을 둔다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 묶음 이름(`aria-label`), 두세 개의 버튼, 고른 버튼에 `aria-pressed="true"`.
- 받침 `seg` 면, `radius-10`, 버튼 높이 `control-seg`(38px). 고른 칸은 `surface` 면 · `text` 글자 · 700 · `shadow-seg`.
- 손가락 기기(`pointer: coarse`)와 640px 이하에서 버튼 높이는 `touch-min`(44px)이다.
- 고대비 모드(`forced-colors`)에서 고른 칸은 `Highlight` 테두리로 보인다.

## 지킬 것

- 화면을 바꾸는 것은 탭(Tabs)을 쓴다. 나눔 버튼은 같은 화면의 보기 · 방식을 고른다.
