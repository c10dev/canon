"""화별 스토리보드의 계산: 플롯과 집필 사이에 두는 쓰기 재료(Episode.storyboard)에서 Canon 이 셀 값을 센다.

AI 는 스토리보드에 '무엇이 얼마나 바뀌는지'만 적는다(며칠 뒤에 시작하는지, 상태창 바뀐 양). 날수 · 요일, 창마다 수치,
값 범위 경고는 여기서 매번 센다. 쓰기 모델은 이 값을 그대로 받아 스스로 셈하지 않는다(prompts.board_block).
스토리보드를 만든 입력의 지문(basis)이 지금과 다르면 낡은 것이다. LLM 을 부르지 않는다. AI 호출은 pipeline.make_storyboard.
"""
from __future__ import annotations

import hashlib
import re

from . import statwin, timeline
from .schema import Episode, Project, StatValue, Storyboard

# 이번 화 플롯과 어긋남: 자동 집필이 멈추는 경고 (다음 화 플롯 경고 next_plot · 설정 setting 은 기록만)
STOP_KINDS = ("plot_vs_state", "plot_vs_text", "time")
WARN_LABELS = {"plot_vs_state": "플롯 · 상태", "plot_vs_text": "플롯 · 앞 화 본문", "time": "시간",
               "setting": "설정", "next_plot": "다음 화 플롯"}
PREV_LIMIT = 20_000  # 쓰기 · 스토리보드에 넣는 직전 화 본문 한도 (넘으면 끝부분만)
_FRACTION = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)\s*/\s*(\d[\d,]*(?:\.\d+)?)")
_WEEKDAY = re.compile(r"([월화수목금토일])요일")


def on(p: Project) -> bool:
    """이 작품이 스토리보드를 쓰는지. 작가가 정하지 않았으면 장편 켬 · 단편 끔 (단편 프롬프트를 그대로 둔다)."""
    v = p.settings.storyboard
    return p.serial if v is None else v


def _episode(p: Project, n: int) -> Episode | None:
    return next((e for e in p.episodes if e.plot.number == n), None)


def prev_text(p: Project, n: int) -> str:
    """직전 화 본문 원문. 한 화 분량이라 화수에 따라 커지지 않는다. PREV_LIMIT 를 넘으면 끝부분만."""
    e = _episode(p, n - 1)
    text = e.text if e else ""
    return text if len(text) <= PREV_LIMIT else "(앞부분 생략)\n" + text[-PREV_LIMIT:]


def basis(p: Project, n: int) -> str:
    """스토리보드를 만든 입력의 지문: 직전 화 본문, 이번 화 · 다음 화 플롯, 직전 화 종료 상태(이번 화 인물)."""
    ep, nxt, prev = _episode(p, n), _episode(p, n + 1), _episode(p, n - 1)
    cast = set(ep.plot.characters) if ep else set()
    states = [s for s in p.states if not cast or s.character_id in cast]
    parts = [prev.text.strip() if prev else "", ep.plot.model_dump_json() if ep else "", nxt.plot.model_dump_json() if nxt else "",
             "".join(s.model_dump_json() for s in sorted(states, key=lambda s: s.character_id))]
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def stale(p: Project, n: int) -> bool:
    """본문을 쓰기 전인데 스토리보드를 만든 뒤 입력이 바뀌었다. 본문을 쓴 뒤에는 상태가 앞으로 가서 보지 않는다."""
    e = _episode(p, n)
    b = e.storyboard if e else None
    return bool(b and b.basis and not e.text and b.basis != basis(p, n))


# ---------- 시간 ----------

def weekday(p: Project, n: int, day: int) -> str:
    """day 날의 요일. 작품 기준이 있으면 timeline 이 센다. 없으면 직전 화 기록 글('4일째 화요일 새벽')에서 읽어 센다."""
    label = timeline.day_label(p, day)
    if label:
        return label
    prev = timeline.prev_end(p, n)
    if not prev or prev[1].day <= 0:
        return ""
    m = _WEEKDAY.search(prev[1].label)
    if not m:
        return ""
    return timeline.WEEKDAYS[(timeline.WEEKDAYS.index(m.group(1)) + day - prev[1].day) % 7] + "요일"


def days(p: Project, n: int, b: Storyboard) -> tuple[int, int] | None:
    """(시작 날수, 끝 날수). 직전 화 끝 날수를 모르거나 메인 시간 밖(after -1)이면 None. 1화는 1일째에서 시작한다."""
    if b.time.after < 0:
        return None
    cur = timeline.current_day(p, n) or (1 if n == 1 else 0)
    if cur <= 0:
        return None
    start = cur + (b.time.after if n > 1 else 0)
    return start, start + max(b.time.days, 1) - 1


def _at(p: Project, n: int, day: int, part: str) -> str:
    wd = weekday(p, n, day)
    return " ".join(x for x in (f"{day}일째" if day > 0 else "", wd, part.strip()) if x)


def span_text(p: Project, n: int, b: Storyboard) -> tuple[str, str]:
    """(시작, 끝) 시점 글: '4일째 화요일 새벽'. 날수를 모르면 시간대만, 메인 시간 밖이면 '회상 · 외전' 을 붙인다."""
    t = b.time
    if t.after < 0:
        return f"메인 시간 밖(회상 · 외전) {t.part.strip()}".strip(), t.end_part.strip()
    span = days(p, n, b)
    if span is None:
        later = "직전 화가 끝난 날" if t.after == 0 else f"직전 화가 끝나고 {t.after}일 뒤"
        end = f"{max(t.days, 1)}일째 되는 날 " if t.days > 1 else ""
        return f"{later} {t.part.strip()}".strip(), f"{end}{t.end_part.strip()}".strip()
    return _at(p, n, span[0], t.part), _at(p, n, span[1], t.end_part)


def time_line(p: Project, n: int, b: Storyboard) -> str:
    """쓰기 프롬프트의 시간 한 줄: '4일째 화요일 새벽에 시작해 4일째 화요일 아침에 끝납니다.'"""
    start, end = span_text(p, n, b)
    return f"{start or '시작 시간대 모름'}에 시작해 {end or '끝 시간대 모름'}에 끝납니다."


def deadline_rows(p: Project, n: int, b: Storyboard) -> list[str]:
    """이번 화 날 범위에 걸리거나 아직 열린 기한 줄 (timeline.deadline_lines, 예산 그대로)."""
    if not timeline.enabled(p):
        return []
    return timeline.deadline_lines(p, n)[0]


# ---------- 상태창 ----------

def steps(p: Project, b: Storyboard) -> list[dict]:
    """상태창 단계를 차례로 쌓아 단계마다 바뀌기 전 · 뒤 값을 센다 (statwin.resolve).
    [{character_id, scene, window(창 번호, 창이 아니면 0), notice, rows: [{name, before, after}], values: [StatValue]}]"""
    cur: dict[str, list[StatValue]] = {}
    out, k = [], 0
    for s in b.stats:
        cid = s.character_id
        if cid not in cur:
            st = p.state_of(cid)
            cur[cid] = [x.model_copy() for x in (st.stats if st else [])]
        vals = cur[cid]
        rows = []
        for ch in s.changes:
            if not ch.name.strip():
                continue
            old = next((x for x in vals if x.name == ch.name), None)
            before = old.value if old else ""
            after = statwin.resolve(before, ch.value)
            if old:
                old.value = after
            else:
                vals.append(StatValue(name=ch.name, value=after))
            rows.append({"name": ch.name, "before": before, "after": after})
        if s.window:
            k += 1
        out.append({"character_id": cid, "scene": s.scene, "window": k if s.window else 0, "notice": s.notice.strip(),
                    "rows": rows, "values": [x.model_copy() for x in vals]})
    return out


def window_text(p: Project, step: dict) -> str:
    """단계까지의 값으로 그린 상태창 글 (statwin.render), 알림 한 줄을 붙인다."""
    text = statwin.render(p, step["character_id"], step["values"])
    return text + (f"\n[{step['notice']}]" if step["notice"] else "")


def _num(x: str) -> float:
    return float(x.replace(",", ""))


def checks(p: Project, n: int, b: Storyboard) -> list[str]:
    """Canon 이 센 경고: 맡은 장면이 없는 플롯 사건, 모르는 인물, 0 아래나 한도 위로 간 '현재/한도' 수치, 관계 단계를 두 칸 넘게 옮기는 플롯."""
    out = []
    e = _episode(p, n)
    if e and b.scenes:
        covered = {k for s in b.scenes for k in s.events}
        miss = [str(k) for k in range(1, len(e.plot.events) + 1) if k not in covered]
        if miss:
            out.append(f"플롯 사건 {', '.join(miss)}번을 맡은 장면이 없어요")
    known = {c.id for c in p.characters}
    if known:
        ids = {c for s in b.scenes for c in s.present} | {s.character_id for s in b.stats} \
            | {m.character_id for m in b.moves} | {a.character_id for a in b.attire}
        unknown = sorted(c for c in ids if c and c not in known)
        if unknown:
            out.append(f"인물 목록에 없는 id: {', '.join(unknown)}")
    name = {c.id: c.name or c.id for c in p.characters}
    for st in steps(p, b):
        for r in st["rows"]:
            m = _FRACTION.match(r["after"])
            if not m:
                continue
            x, top = _num(m.group(1)), _num(m.group(2))
            where = f"{name.get(st['character_id'], st['character_id'])} {r['name']} {r['after']}"
            if x < 0:
                out.append(f"값 범위: {where} (0 아래예요)")
            elif x > top:
                out.append(f"값 범위: {where} (한도를 넘어요)")
    from . import pace  # pace 가 prompts 를 거쳐 이 모듈을 부른다
    out += pace.plot_warnings(p, n)  # 플롯이 한 화에 관계 단계를 두 칸 넘게 옮김 (경고만, 자동 집필은 멈추지 않음)
    return out


def stop_reasons(p: Project, n: int, b: Storyboard) -> list[str]:
    """자동 집필이 멈출 이유: 이번 화 플롯과 어긋남 경고와 값 범위 경고. 다음 화 플롯 · 설정 경고는 넣지 않는다."""
    out = [f"{n}화 스토리보드 {WARN_LABELS[w.kind]} 경고: {w.text}" + (f" → {w.resolution}" if w.resolution else "")
           for w in b.warnings if w.target == "this" and w.kind in STOP_KINDS]
    out += [f"{n}화 스토리보드: {c}" for c in b.checks if c.startswith("값 범위")]
    return out


def view(p: Project, n: int) -> dict:
    """집필 화면 카드에 보일 계산 값. 스토리보드가 없으면 켜짐 여부와 낡음만."""
    e = _episode(p, n)
    b = e.storyboard if e else None
    out: dict = {"on": on(p), "stale": stale(p, n), "time": "", "steps": [], "checks": [], "deadlines": []}
    if b is None:
        return out
    name = {c.id: c.name or c.id for c in p.characters}
    out["time"] = " → ".join(x for x in span_text(p, n, b) if x)
    out["deadlines"] = deadline_rows(p, n, b)
    out["checks"] = checks(p, n, b)
    out["steps"] = [{"character_id": s["character_id"], "who": name.get(s["character_id"], s["character_id"]), "scene": s["scene"],
                     "window": s["window"], "notice": s["notice"], "rows": s["rows"],
                     "text": window_text(p, s) if s["window"] else ""} for s in steps(p, b)]
    return out
