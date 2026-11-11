"""퇴고가 고칠 자리 찾기 (퇴고 단계, docs/context/specs/13-polish-stage.md 3.2).
집필 요청에서 뺀 '하지 말 것' 규칙(쇠맛 패턴 상한, 금지 표현, 문장 끝 몫, 되풀이 구절)의 위반을 본문에서 코드로 찾는다.
퇴고 요청(prompts.polish_prompt)은 찾은 자리만 인용해 받는다. 대사 · 효과음 줄에 든 것은 퇴고가 바꾸지 못하므로 찾지 않는다.
문체 원문이 있는 작품은 기준값에서 원문이 원래 쓰는 만큼은 찾지 않는다 (metrics.drift 와 같은 뜻)."""
import re
from typing import NamedTuple

from . import echoes, metrics
from .schema import Project

QUOTES = 6   # 규칙마다 인용할 문장 수
LINES = 25   # 블록 전체 줄 수
CLIP = 120   # 인용 한 문장의 글자 수
ENDING_SLACK = 0.05  # '~다.' 끝 몫이 목표보다 이만큼 넘어야 짚는다
# 추상어 규칙('묘한 불안감', '알 수 없는 감정' 같은 추상어)을 코드로 찾는 낱말. metrics.DEFAULT_CLICHES 에 있는 것만 쓴다
ABSTRACT = ("묘한 감정", "알 수 없는 감정", "형언할 수 없는")
_FIXED_OPEN = ("\"", "“", "「", "『", "‘", "'", "─", "—")  # pipeline._FIXED_OPEN 과 같다 (서술 다듬기가 바꾸지 않는 줄)


class Target(NamedTuple):
    name: str          # 규칙 이름
    way: str           # 고칠 방향 (규칙 글에서 가져온다)
    quotes: list[str]  # 인용 문장 (CLIP 자까지)
    count: int         # 찾은 수 (문장 끝은 덩어리 수)


def narration_lines(text: str) -> list[str]:
    """서술 줄. 따옴표로 여는 대사 줄, 줄표로 여는 효과음 줄, 소리 · 몸짓만 적은 효과음 줄은 뺀다."""
    return [s for line in text.split("\n") if (s := line.strip()) and not s.startswith(_FIXED_OPEN) and not metrics.is_sfx_line(line)]


def _sentences(lines: list[str]) -> list[str]:
    return [x for line in lines for x in metrics.sentences(line) if not metrics._QUOTE.fullmatch(x)]


def _clip(s: str) -> str:
    return s if len(s) <= CLIP else s[:CLIP] + "…"


def baseline(p: Project) -> metrics.StyleMetrics:
    """문체 기준값 (pipeline.style_baseline 과 같다. prompts 가 이 모듈을 부르므로 pipeline 을 들이지 않는다)."""
    if p.anchor is not None and p.anchor.metrics is not None:
        return p.anchor.metrics
    return p.style_baseline or metrics.measure("\n\n".join(p.style.sample_passages))


def _gated(base: float | None, cur: float | None) -> bool:
    """원문이 원래 이만큼 쓰면 고치지 않는다."""
    return base is not None and cur is not None and base > 0 and base >= cur


def find(p: Project, n: int, text: str) -> list[Target]:
    """본문의 퇴고 자리. 규칙 차례는 prompts._PROSE_RULES 차례, 그 뒤 금지 표현 · 되풀이 구절 · 문장 끝."""
    from . import prompts  # prompts 가 polish_prompt 에서 이 모듈을 부른다
    styled = prompts.styled(p)
    base = baseline(p)
    cur = metrics.measure(text, p.style.banned_phrases)
    sents = _sentences(narration_lines(text))
    out: list[Target] = []

    def add(name: str, way: str, quotes: list[str], skip_first: bool = False) -> None:
        qs = list(dict.fromkeys(quotes))[1 if skip_first else 0:]  # 한 화에 한 번까지인 규칙은 둘째부터
        if qs:
            out.append(Target(name, way, [_clip(q) for q in qs], len(qs)))

    pats = {"감정 이름 서술": ("감정은 이름으로 말하지 않고 행동, 사물로 드러냅니다", False),
            "부정 후 재정의": ("한 화에 한 번까지", True)}
    if not styled:  # 문체 원문이 있는 작품은 셋씩 나열을 쓰기 규칙에서도 뺀다 (prose_rules)
        pats["셋씩 나열"] = ("한 화에 한 번까지", True)
    rx = {name: r for name, r, _ in metrics.AI_PATTERNS}
    for name, (way, first) in pats.items():
        if not _gated(base.pattern_per_1k.get(name), cur.pattern_per_1k.get(name)):
            add(name, way, [s for s in sents if rx[name].search(s)], first)
    if not _gated(base.short_ending_ratio, cur.short_ending_ratio):
        ends = []
        for para in re.split(r"\n\s*\n", text):
            ss = _sentences(narration_lines(para))
            if len(ss) >= 2 and len(ss[-1]) <= 12 and len(metrics.sentences(para.strip())) == len(ss):
                ends.append(ss[-1])
        add("문단 끝 짧은 여운 문장", "한 화에 한 번까지", ends, True)
    if not styled and not _gated(base.comma_sentence_ratio, cur.comma_sentence_ratio):
        add("쉼표 둘 이상", "문장을 나눕니다", [s for s in sents if s.count(",") >= 2])
    if not _gated(base.pronoun_per_1k, cur.pronoun_per_1k):
        add("대명사", "'그는', '그녀의' 같은 대명사보다 이름이나 생략", [s for s in sents if metrics._PRONOUN.search(s)])
    if not _gated(base.pattern_per_1k.get("번역투"), cur.pattern_per_1k.get("번역투")):
        add("번역투", "'~를 통해', '~에 있어', '~하게 되었다' 대신 능동형 동사", [s for s in sents if rx["번역투"].search(s)])
    add("추상어", "이 장면에만 있는 사물, 소리, 행동으로", [s for s in sents if any(a in s for a in ABSTRACT)])
    marks = re.compile(r"\*\*|^#", re.M) if styled else rx["서식 흔적"]  # 줄 머리 줄표는 효과음 줄이라 이미 빠졌다
    add("서식 흔적", "굵은 글씨, 마크다운 기호를 쓰지 않습니다" if styled else "줄표, 굵은 글씨, 마크다운 기호를 쓰지 않습니다",
        [s for s in sents if marks.search(s)])
    for ph in dict.fromkeys(x for x in p.style.banned_phrases if x.strip()):
        add(f"금지 표현 '{ph}'", "이 표현은 쓰지 않습니다", [s for s in sents if ph in s])
    if p.serial and p.settings.recent_echoes:
        for phrase, ks in echoes.recent(p, n):
            add(f"되풀이 구절 '{phrase}'", f"{', '.join(map(str, ks))}화에 그대로 나온 서술입니다. 일어나는 일과 사실은 그대로 두고 다른 말로",
                [s for s in sents if phrase in s])
    if not prompts.voiced(p, n):  # 서술 말투가 있는 화는 문장 끝 몫을 주지 않는다
        word, _ = prompts.ending_counts(p)
        share = {v: k for k, v in prompts._COUNT.items()}[word] / 10
        da, _ = metrics._endings(text)
        runs = metrics.da_runs(text)
        if (da is not None and da > share + ENDING_SLACK) or runs:
            way = f"서술 문장의 {round(da * 100)}%가 '~다.'로 끝납니다. 열에 {word}쯤으로 줄입니다." if da is not None else ""
            if runs:
                way += f" '~다.' 끝이 {metrics.ENDING_RUN}줄 넘게 이어진 곳 {len(runs)}군데 (첫 문장)"
            out.append(Target("문장 끝", way.strip(), [_clip(r) for r in runs], len(runs)))
    return out


def total(found: list[Target]) -> int:
    """찾은 자리 수. 덩어리 없이 몫만 넘은 문장 끝은 한 곳으로 센다."""
    return sum(max(t.count, 1) for t in found)


HEAD = "# 찾은 자리 (코드가 이 본문에서 찾은 것. 이 문장들의 서술만 고칩니다. 대사 줄과 효과음 줄은 그대로 둡니다)"


def block(found: list[Target]) -> str:
    """퇴고 요청 맨 끝의 찾은 자리 블록. 없으면 빈 글. 규칙마다 QUOTES 개, 모두 LINES 줄까지 적고 뺀 수를 적는다."""
    if not found:
        return ""
    rows, shown = [], 0
    for t in found[:LINES]:
        rows.append(f"- [{t.name} · {t.way}] " + " ".join(f"«{q}»" for q in t.quotes[:QUOTES]))
        shown += max(min(len(t.quotes), QUOTES), 1)
    rows = [r.rstrip() for r in rows]
    all_ = total(found)
    note = f"\n({all_}곳 가운데 {shown}곳만 적었습니다)" if shown < all_ else ""
    return f"\n\n{HEAD}\n" + "\n".join(rows) + note
