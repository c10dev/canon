# 05. 자취 스키마

상태: 끝(2026-11-18, 정할 것 1~5 는 추천안으로 정함) · 계획: [plan.md](../plan.md) 의 5번 · 먼저: 1

## 목표

동작은 바뀌지 않는다.
작품 데이터에 인물 자취(승인한 본문에서 한 인물이 남긴 선택 · 말 · 드러냄)와 그 자취를 뒤 화가 다시 꺼낸 기록을 담을 자리를 만든다.
채우는 길(상태 변경안 · 승인 화면)은 일감 6, 쓰는 길(기획 블록)은 일감 9 다.
옛 작품은 그대로 읽히고, 되돌리기 · 다시 짜기 · 작품 저장 · 인물 지우기에서 기록이 맞게 다뤄진다.

따르는 정한 규칙:

- 2026-11-17: 쓰기 요청에는 자취 블록을 따로 넣지 않는다. 쓰기는 플롯의 이어받기 결정으로만 자취에 닿는다. 이 일감은 요청을 바꾸지 않는다.

같은 꼴의 앞선 일감: 보는 눈 스키마(일감 8-1, #583). 이 명세는 그 흐름을 따른다.

## 정할 것

1. 일감 1(측정) 뒤로 미룰지 — 추천: 미루지 않는다.
   - plan.md 는 5 의 '먼저 끝날 것'을 1 로 적었다. 측정은 6 · 9 의 차례와 모양을 정하는 데 쓴다.
   - 스키마는 기본값이 빈 목록이라 옛 작품에 영향이 없고, 칸을 고칠 일이 생겨도 쓰는 곳이 없어 되돌리기 쉽다.
   - 다른 안: 측정을 먼저 끝낸다. 측정 2(재료가 요청에 있었나)가 자취의 갈래 · 칸을 바꿀 수 있다.
2. 이름 — 추천: '자취', 코드 `trail`(README 정할 것 1).
3. 갈래 — 추천: 선택 · 말 · 드러냄 셋(README 정할 것 3). 코드 값은 한국어 그대로 `Literal["선택", "말", "드러냄"]`. `IssueType` · `EventKind` 처럼 한국어 값을 쓰는 앞선 꼴을 따른다.
4. 다시 꺼냄에 뜻 한 줄 — 추천: 남긴다(README 정할 것 13). 화 · 되짚은 인물 · 그때의 뜻의 작은 모델 목록.
5. id 꼴 — 추천: 프로그램이 `tr-{화:03d}-{그 화 안 차례}` 로 붙인다(예: `tr-012-1`). 복선 id(`fs-03-locket`)처럼 LLM 이 짓게 하지 않는다. 다시 꺼냄 · 보는 눈의 근거(`CharView.basis`) · 이어받기 결정(일감 9)이 이 id 로 가리킨다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | `TrailEcho`, `CharTrail` 모델, `Project.trails` |
| `canon/trails.py` | 새 모듈: `live`, `revert`, `next_id` |
| `canon/features.py` | `REVERT_LAST` 에 `trails.revert` (보는 눈 훅 바로 앞, 보는 눈의 근거가 지워진 자취를 가리키지 않게) |
| `canon/charviews.py` | `revert` · `live` 에서 `basis` 가 없는 자취 id 를 가리키면 그 id 만 뺀다(줄은 남긴다) |
| `canon/reshape.py` | 다시 짜기에서 `trails.revert(p, 0)` (`charviews.revert(p, 0)` 바로 앞) |
| `canon/web.py` | 작품 전체 저장(`_put_locked`)이 화면에서 온 `trails` 를 버리고 디스크 것을 둔다 |
| `tests/test_trails.py` | 새 시험 |
| `docs/modules/story.md` | `### \`canon/trails.py\`` 절. 경로 차례대로 `canon/tofix.py` 절 바로 뒤 |

- 화 번호 옮기기는 하지 않는다. 반영한 화는 번호를 옮기지 않는다(`pipeline.insert_range`, 8-1 에서 확인).
- 반영 취소는 `d.added` 대신 되돌리기 훅으로 한다(호칭 기록 · 보는 눈과 같다).
- 새 LLM 호출 · 프롬프트 · 화면이 없다.

## 데이터 · 스키마

```python
TrailKind = Literal["선택", "말", "드러냄"]

class TrailEcho(BaseModel):
    """뒤 화 본문이 자취를 되짚은 한 번. 프로그램이 저장한다."""
    episode: int = Field(description="되짚은 화")
    character: str = Field(description="되짚은 인물 id. 자취의 주인이 아닐 수 있다(본 사람이 기억함)")
    meaning: str = Field("", description="그때의 뜻, 20자 안팎")

class CharTrail(BaseModel):
    """자취 한 줄: 승인한 본문에서 한 인물이 남긴 선택 · 말 · 드러냄 (canon/trails.py). 프로그램이 저장한다."""
    id: str = Field(description="tr-{화:03d}-{차례}, 프로그램이 붙인다")
    character: str = Field(description="그 일을 한 인물 id")
    episode: int = Field(description="그 일이 나온 화")
    kind: TrailKind = Field("선택")
    label: str = Field(description="40자 안팎의 짧은 이름")
    quote: str = Field("", description="근거 구절, 본문 그대로")
    witnesses: list[str] = Field(default_factory=list, description="그 자리에서 보거나 들은 인물 id")
    echoes: list[TrailEcho] = Field(default_factory=list, description="뒤 화에서 되짚은 기록, 화 차례")
```

- `Project.trails: list[CharTrail] = Field(default_factory=list, …)`. `Project.views` 바로 앞.
- 옛 `project.json` 은 고치지 않고 읽힌다.
- LLM 이 채우는 응답 형식(일감 6 의 `StateDelta.trails`)은 이 모델과 따로 둔다. id 와 화 번호는 반영할 때 프로그램이 붙인다.

## 규칙

- `live(p)`: 주인이 인물 목록에 있는 자취만, 저장 차례 그대로. 본 사람 · 다시 꺼낸 인물 가운데 지워진 인물은 그 칸에서만 뺀 사본을 돌려준다.
- `revert(p, n)`:
  - `episode > n` 인 자취를 지운다.
  - 남은 자취의 `echoes` 에서 `episode > n` 인 줄을 지운다(n화 뒤에 되짚은 기록).
  - 주인이 지워진 자취를 지운다. 본 사람 · 다시 꺼낸 인물 칸의 지워진 인물 id 를 뺀다.
- `next_id(p, n)`: n화 자취의 다음 id. 그 화의 가장 큰 차례 + 1.
- 보는 눈의 근거: `charviews.revert` 가 지워진 자취 id 를 `basis` 에서 뺀다. 되돌리기 훅 차례상 `trails.revert` 가 먼저 돈다.
- 작품 전체 저장은 디스크의 `trails` 를 둔다. 자취는 상태 승인(일감 6)과 인물 화면의 고치기(일감 7)로만 바뀐다.
- 대화 에이전트: 바뀌지 않는다.
- 단편 · 장편이 같다.

## 화면 · 명령줄 · 프롬프트

- 없음. 프롬프트 스냅샷이 바뀌지 않아야 한다.

## 시험

- 새 시험 `tests/test_trails.py`:
  - `trails` 칸이 없는 옛 작품 dict 가 읽히고(`trails == []`), dump 해도 오류가 없다.
  - `CharTrail` · `TrailEcho` 를 넣은 작품이 dump → validate 로 같은 값이 돌아온다.
  - `revert(p, 2)`: 3화 자취가 지워지고, 1화 자취의 3화 다시 꺼냄도 지워지며 2화 다시 꺼냄은 남는다.
  - 인물을 지우면: 주인인 자취는 지워지고, 본 사람 · 다시 꺼낸 인물 칸에서 그 id 만 빠진다.
  - `next_id`: 빈 화는 `tr-005-1`, 차례 1 · 2 가 있으면 `tr-005-3`.
  - 보는 눈의 `basis` 가 지워진 자취를 가리키면 되돌리기 뒤 그 id 만 빠진다.
  - 되돌리기 훅(`features.REVERT_LAST`)을 거치면 위가 일어난다(`tests/test_charviews.py` 의 꼴).
  - 작품 전체 저장(`PUT /api/projects/{name}`)이 화면에서 온 `trails` 를 버린다(`client` fixture).
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`, `ruff check canon tests scripts`, 복잡도 게이트.

## 문서

- `docs/modules/story.md`: `canon/trails.py` 새 절. `canon/charviews.py` 절에 `basis` 정리 한 줄.
- `DESIGN.md`: 8-1 이 더한 `Project.views` 줄 바로 뒤에 `Project.trails` 한 줄.
- 이 폴더: [plan.md](../plan.md) 5번 상태. 정할 것을 정하면 [README.md](../README.md) 정한 규칙에 옮긴다.

## 확인하지 못할 것

- 채우는 길이 없어 실제 작품에서 쌓이는 모습은 일감 6 뒤에 본다.

## 비용

- LLM 비용 없음.
