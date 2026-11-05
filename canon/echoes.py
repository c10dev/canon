"""최근 화에서 되풀이한 구절. LLM 호출 없이 직전 몇 화 본문을 견줘, 여러 화에 걸쳐 같은 말로 다시 쓴 서술 구절을 찾는다.

쓰기 요청은 이전 화 본문 전체를 넣지 않는다(요약 + 직전 화 끝). 그래서 모델은 지난 화에 쓴 비유를 보지 못하고 화마다 같은 비유를 다시 만든다.
metrics.measure 의 '반복 구'는 한 화 안만 센다. 여기서는 화를 넘어 센다.
장편 본문 쓰기 요청의 뒤쪽 블록(prompts.echo_block)이 이 목록을 넣는다. 화마다 바뀌므로 static_context 앞에는 넣지 않는다.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from .metrics import _QUOTE, name_forms

WINDOW = 5          # 견주는 직전 화 수 (본문이 있는 화)
MIN_EPISODES = 3    # 이만큼의 화에 나와야 되풀이로 본다. 본문이 있는 직전 화가 이보다 적으면 그 수 (2 아래면 찾지 않는다)
SEED = 3            # 찾기 시작하는 구절의 어절 수
MAX_WORDS = 8       # 앞뒤로 늘린 구절의 최대 어절 수
GROW_SHARE = 2 / 3  # 나온 곳의 이만큼에서 같은 어절이 이어져야 늘린다. '잡히지 않는' 뒤가 '말랑한 · 묵직한 · 빵빵한' 으로 갈리면 멈춘다
MIN_CHARS = 7       # 띄어쓰기를 뺀 글자 수가 이보다 적은 구절은 뺀다 ('수 밖에 없었다' 같은 흔한 말)
LIMIT = 10          # 블록에 넣는 구절 수 상한

# 확정 사실과 견줄 때 어절 끝에서 떼는 조사. '안쪽의' 와 '안쪽에' 를 같게 본다. 긴 것부터
_PARTICLES = ("에서", "에게", "으로", "의", "에", "을", "를", "이", "가", "은", "는", "로", "와", "과", "도", "만")
_SENT = re.compile(r"[^.!?…\n]+")
_WORD = re.compile(r"[^\s\"'“”‘’「」『』.,!?…·\-—~()\[\]<>《》:;]+")


def _sentences(text: str) -> list[list[str]]:
    """대사(따옴표 안)를 뺀 서술 문장마다 어절 목록. 인물 말버릇은 말투 설정이 정하므로 세지 않는다."""
    text = _QUOTE.sub("\n", text)
    return [w for s in _SENT.findall(text) if (w := _WORD.findall(s))]


def _stem(word: str) -> str:
    for x in _PARTICLES:
        if word.endswith(x) and len(word) > len(x):
            return word[:-len(x)]
    return word


def _stems(words) -> str:
    """어절마다 조사를 떼고 한 칸씩 띄어 붙인다. 앞뒤에 빈칸을 두어 어절 단위로 찾게 한다."""
    return " " + " ".join(_stem(w) for w in words) + " "


def _canon_text(p) -> str:
    """반복해도 되는 말이 적힌 곳: 확정 사실, 세계관, 인물 설정 · 상태, 이야기 요소.
    조사를 뗀 구절이 이 안에 그대로 있으면 뺀다. 예: '왼쪽 허벅지 안쪽의' 는 사실 '왼쪽 허벅지 안쪽에 작은 점이 있다' 에 있다."""
    parts = list(p.facts)
    parts.append(json.dumps(p.world.model_dump(), ensure_ascii=False))
    parts += [json.dumps(c.model_dump(), ensure_ascii=False) for c in p.characters]
    parts += [json.dumps(s.model_dump(), ensure_ascii=False) for s in p.states]
    parts += [f"{e.name} {' '.join(e.aliases)} {e.description}" for e in p.elements]
    return _stems(_WORD.findall("\n".join(parts)))


def _in_canon(words: tuple[str, ...], canon: str) -> bool:
    """구절 안의 SEED 어절 묶음 하나라도 조사를 떼고 canon 에 그대로 있는지.
    늘리며 붙은 어절('안쪽의 까만')이 사실 대조를 비껴가지 않게 한다."""
    return any(_stems(words[i:i + SEED]) in canon for i in range(len(words) - SEED + 1))


def _names(p) -> tuple[str, ...]:
    """구절에 들면 뺄 이름 · 호칭: 인물 이름(성을 뗀 이름 포함), 부르는 말, 이야기 요소 이름.
    조사가 붙은 어절('지훈이')도 앞이 같으면 뺀다."""
    out = {f for c in p.characters for f in name_forms(c.name)}
    out |= {a.calls.strip() for a in p.address_forms if a.calls.strip()}
    out |= {x.strip() for e in p.elements for x in (e.name, *e.aliases) if x.strip()}
    return tuple(sorted(x for x in out if len(x) >= 2))


def _occurs(eps: dict[int, list[list[str]]], gram: tuple[str, ...]) -> list[tuple[int, int, int]]:
    """gram 이 나온 곳마다 (화, 문장, 어절 위치)."""
    k = len(gram)
    return [(n, si, i) for n, ss in eps.items() for si, ws in enumerate(ss)
            for i in range(len(ws) - k + 1) if tuple(ws[i:i + k]) == gram]


def _grow(eps: dict[int, list[list[str]]], gram: tuple[str, ...], need: int, bad) -> tuple[str, ...]:
    """앞뒤 어절을 하나씩 붙인다 (MAX_WORDS 까지). 붙일 어절은 나온 곳의 GROW_SHARE 이상에서 같아야 하고,
    붙인 구절도 need 개 이상의 화에 나와야 한다. 이름 · 호칭 어절은 붙이지 않는다."""
    while len(gram) < MAX_WORDS:
        occ = _occurs(eps, gram)
        best = None
        for side in (1, -1):
            nxt: Counter = Counter()
            at: dict[str, set[int]] = defaultdict(set)
            for n, si, i in occ:
                ws = eps[n][si]
                j = i + len(gram) if side == 1 else i - 1
                if 0 <= j < len(ws) and not bad(ws[j]):
                    nxt[ws[j]] += 1
                    at[ws[j]].add(n)
            for w, c in nxt.most_common(1):
                if c >= GROW_SHARE * len(occ) and len(at[w]) >= need and (best is None or c > best[0]):
                    best = (c, side, w)
        if best is None:
            return gram
        gram = gram + (best[2],) if best[1] == 1 else (best[2],) + gram
    return gram


def window_of(p, n: int, window: int = WINDOW) -> list:
    """n 화보다 앞에서 본문이 있는 화 가운데 마지막 window 개 (화 차례)."""
    return sorted((e for e in p.episodes if e.plot.number < n and e.text.strip()), key=lambda e: e.plot.number)[-window:]


def recent(p, n: int, window: int = WINDOW, limit: int = LIMIT) -> list[tuple[str, list[int]]]:
    """n 화를 쓰기 전, 본문이 있는 직전 window 개 화에서 MIN_EPISODES 개 이상의 화에 그대로 나온 서술 구절과 그 화 번호들.
    나온 화가 많은 것부터 limit 개. 확정 사실 · 설정에 그대로 적힌 구절과 이름 · 호칭이 든 구절은 뺀다.
    나온 곳이 많은 구절부터 늘리고, 앞서 고른 구절을 품거나 그 안에 드는 구절은 뺀다."""
    done = window_of(p, n, window)
    need = min(MIN_EPISODES, len(done))
    if need < 2:
        return []
    eps = {e.plot.number: _sentences(e.text) for e in done}
    names = _names(p)
    canon = _canon_text(p)
    bad = (lambda w: w.startswith(names)) if names else (lambda w: False)
    seen: dict[tuple[str, ...], set[int]] = defaultdict(set)
    hits: Counter = Counter()
    for k, ss in eps.items():
        for ws in ss:
            for i in range(len(ws) - SEED + 1):
                g = tuple(ws[i:i + SEED])
                seen[g].add(k)
                hits[g] += 1
    seeds = [g for g, ks in seen.items() if len(ks) >= need and not any(bad(w) for w in g)]
    seeds.sort(key=lambda g: (-hits[g], -len(seen[g]), min(seen[g])))
    out: dict[str, list[int]] = {}
    for g in seeds:
        if any(f" {' '.join(g)} " in f" {o} " for o in out):
            continue
        long = _grow(eps, g, need, bad)
        phrase = " ".join(long)
        if len(phrase.replace(" ", "")) < MIN_CHARS or _in_canon(long, canon):
            continue
        if any(f" {phrase} " in f" {o} " or f" {o} " in f" {phrase} " for o in out):
            continue
        out[phrase] = sorted({k for k, _, _ in _occurs(eps, long)})
    rows = sorted(out.items(), key=lambda x: (-len(x[1]), -len(x[0])))
    return rows[:limit]
