"""호칭 · 말씨: 한 인물이 다른 인물을 부르는 말과 그에게 쓰는 말씨(존댓말 · 반말 등). 방향이 있다 (A→B 와 B→A 가 따로).

말투(Character.speech_style)는 인물 하나의 버릇이라, 누구에게 존댓말을 쓰고 누구를 무엇이라 부르는지는 담지 못했다.
실제 장편 4편의 관계 30쌍 중 설명란에 호칭 · 높임을 적은 쌍은 2쌍뿐이었다 (2026-10-30 인물 진단).
처음 값은 작가가 인물 · 관계 화면에서 정한다(Project.address_forms). 본문에서 바뀐 것(반말로 바뀜, 호칭이 바뀜)은
상태 변경안의 address_changes 로 오고, 작가가 상태 승인 화면에서 골라야 반영한다 (기본으로 체크하지 않음, 설정 바꾸기와 같은 대우).
자동 집필 · run -y · 플레이는 반영하지 않고 남겨 둔다(Project.address_held). 바뀐 기록은 Project.address_log 에 전후 값으로 남고,
스냅샷은 호칭을 담지 않으므로 되돌리기는 이 기록으로 한다 (charlog 와 같은 방식). 쓰기 · 검수 · 상태 변경안에는 이번 화 인물끼리의 줄만 넣는다.
LLM 을 부르지 않는다. 화면은 static/cast.js(두 사람 상세) · review.js(바뀜 카드).
"""
from __future__ import annotations

from . import context
from .schema import AddressChange, AddressForm, AddressRecord, Project, StateDelta

# 자주 쓰는 말씨. 칸은 자유 글이고 이 목록은 화면의 고르기 · 프롬프트 안내에만 쓴다
SPEECH_LEVELS: dict[str, str] = {
    "하십시오체": "깍듯한 존댓말 (-습니다, -십시오)",
    "해요체": "부드러운 존댓말 (-어요, -세요)",
    "하오체": "예스러운 높임 (-오, -구려)",
    "하게체": "예스러운 낮춤 (-게, -네)",
    "해체(반말)": "반말 (-어, -지)",
    "해라체": "낮추는 반말 (-다, -라, -느냐)",
}
FIELDS: dict[str, str] = {"calls": "부르는 말", "speech": "말씨"}


def last_done(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def find(p: Project, speaker: str, listener: str) -> AddressForm | None:
    return next((f for f in p.address_forms if f.speaker == speaker and f.listener == listener), None)


def _names(p: Project) -> dict[str, str]:
    return {c.id: c.name or c.id for c in p.characters}


def _set(p: Project, speaker: str, listener: str, field: str, value: str) -> str:
    """한 칸을 바꾸고 이전 값을 돌려준다. 두 칸이 모두 비면 그 방향을 지운다."""
    f = find(p, speaker, listener)
    if f is None:
        f = AddressForm(speaker=speaker, listener=listener)
        p.address_forms.append(f)
    before = getattr(f, field)
    setattr(f, field, value)
    if not f.calls and not f.speech:
        p.address_forms.remove(f)
    return before


# ---------- 작가가 정하기 ----------

def set_form(p: Project, speaker: str, listener: str, calls: str, speech: str) -> list[AddressRecord]:
    """작가가 한 방향의 부르는 말 · 말씨를 정한다. 1화를 반영한 뒤에는 작가 기록으로 남긴다
    (같은 화 뒤에 같은 칸을 여러 번 고치면 한 기록으로 합치고, 처음 값으로 돌아오면 기록을 지운다)."""
    ids = {c.id for c in p.characters}
    if speaker not in ids or listener not in ids:
        raise KeyError(f"인물이 없어요: {speaker if speaker not in ids else listener}")
    if speaker == listener:
        raise ValueError("같은 인물끼리는 호칭을 정하지 않아요")
    n = last_done(p)
    out = []
    for field, value in (("calls", calls.strip()), ("speech", speech.strip())):
        cur = find(p, speaker, listener)
        if (getattr(cur, field) if cur else "") == value:
            continue
        before = _set(p, speaker, listener, field, value)
        if n == 0:
            continue
        last = next((r for r in reversed(p.address_log) if (r.speaker, r.listener, r.field) == (speaker, listener, field)), None)
        if last is not None and last.source == "author" and last.episode == n:
            last.after = value
            if last.after == last.before:
                p.address_log.remove(last)
            continue
        rec = AddressRecord(episode=n, speaker=speaker, listener=listener, field=field, before=before, after=value, source="author")
        p.address_log.append(rec)
        out.append(rec)
    return out


# ---------- 상태 변경안 수명 주기 (features 훅) ----------

def clean(p: Project, changes: list[AddressChange], n: int, new_ids: set[str] = frozenset()) -> tuple[list[AddressChange], list[str]]:
    """있는 인물(또는 이번 화 새 인물) 사이의, 지금 값과 다른 칸만 남긴다. 같은 방향이 두 번 오면 뒤의 것."""
    ids = {c.id for c in p.characters} | set(new_ids)
    out: dict[tuple[str, str], AddressChange] = {}
    warns: list[str] = []
    for x in changes:
        if x.speaker == x.listener:
            continue
        if x.speaker not in ids or x.listener not in ids:
            warns.append(f"설정에 없는 인물({x.speaker if x.speaker not in ids else x.listener})의 호칭 · 말씨 바뀜 제안은 뺐어요")
            continue
        cur = find(p, x.speaker, x.listener)
        calls, speech = x.calls.strip(), x.speech.strip()
        calls = "" if cur and calls == cur.calls else calls
        speech = "" if cur and speech == cur.speech else speech
        if not calls and not speech:
            continue
        out[(x.speaker, x.listener)] = x.model_copy(update={"calls": calls, "speech": speech, "reason": x.reason.strip(),
                                                            "quote": x.quote.strip(), "episode": n})
    return list(out.values()), warns


def clean_delta(p: Project, d: StateDelta) -> list[str]:
    d.address_changes, warns = clean(p, d.address_changes, d.episode, {c.id for c in d.new_characters})
    return warns


def apply(p: Project, changes: list[AddressChange], n: int) -> list[AddressRecord]:
    """고른 바뀜을 쓰고 기록한다. 인물이 없거나 지금 값과 같으면 건너뛴다."""
    ids = {c.id for c in p.characters}
    recs = []
    for x in changes:
        if x.speaker not in ids or x.listener not in ids or x.speaker == x.listener:
            continue
        for field in FIELDS:
            value = getattr(x, field).strip()
            cur = find(p, x.speaker, x.listener)
            if not value or value == (getattr(cur, field) if cur else ""):
                continue
            before = _set(p, x.speaker, x.listener, field, value)
            rec = AddressRecord(episode=n, speaker=x.speaker, listener=x.listener, field=field, before=before, after=value,
                                source="ai", reason=x.reason, quote=x.quote)
            p.address_log.append(rec)
            recs.append(rec)
    return recs


def apply_delta(p: Project, d: StateDelta) -> None:
    """반영 훅 (features.APPLY_FIRST, 새 인물을 더한 직후). 상태 승인 화면은 작가가 고른 것만 보낸다. 자동 집필은 그 전에 hold 로 뺀다."""
    apply(p, d.address_changes, d.episode)


def hold(p: Project, d: StateDelta) -> int:
    """자동 집필 · run -y · 플레이: 바뀜 제안을 반영하지 않고 남겨 두고 변경안에서 뺀다. 남긴 개수."""
    held = [x.model_copy(update={"episode": d.episode}) for x in d.address_changes]
    d.address_changes = []
    p.address_held = [x for x in p.address_held if x.episode != d.episode] + held
    return len(held)


def take_held(p: Project, i: int) -> list[AddressRecord]:
    """남겨 둔 제안 하나를 적용한다. 그 화의 기록으로 남는다."""
    if not 0 <= i < len(p.address_held):
        raise ValueError("남겨 둔 호칭 · 말씨 제안이 없어요. 화면을 새로 고쳐 보세요")
    x = p.address_held.pop(i)
    return apply(p, [x], x.episode)


def drop_held(p: Project, i: int) -> None:
    if not 0 <= i < len(p.address_held):
        raise ValueError("남겨 둔 호칭 · 말씨 제안이 없어요. 화면을 새로 고쳐 보세요")
    p.address_held.pop(i)


def revert(p: Project, n: int) -> None:
    """되돌리기 훅 (features.REVERT_LAST). n화 뒤에 반영한 제안은 지금 값이 그때 그대로면 처음 값으로 돌린다
    (그 뒤 작가가 고쳤으면 작가 값을 둔다). 작가 기록은 지우지 않고 n화로 옮긴다. 지워진 인물의 기록과 n화 뒤 남겨 둔 제안도 정리한다."""
    ids = {c.id for c in p.characters}
    keep: list[AddressRecord] = []
    for r in reversed(p.address_log):
        if r.speaker not in ids or r.listener not in ids:
            continue
        if r.episode > n and r.source == "ai":
            cur = find(p, r.speaker, r.listener)
            if (getattr(cur, r.field) if cur else "") == r.after:
                _set(p, r.speaker, r.listener, r.field, r.before)
            continue
        if r.episode > n:
            r.episode = n
        keep.append(r)
    p.address_log = keep[::-1]
    p.address_held = [x for x in p.address_held if x.episode <= n]


# ---------- 프롬프트 ----------

def lines(p: Project, ids: set[str] | None = None) -> list[str]:
    """speaker 와 listener 가 모두 ids 에 있는 방향의 한 줄씩 (ids 가 None 이면 모두). 지워진 인물은 뺀다."""
    name = _names(p)
    out = []
    for f in p.address_forms:
        if f.speaker not in name or f.listener not in name or (ids is not None and not {f.speaker, f.listener} <= ids):
            continue
        bits = [f"'{f.calls}'라고 부름" if f.calls else "", f"말씨 {f.speech}" if f.speech else ""]
        out.append(f"- {name[f.speaker]} → {name[f.listener]}: {', '.join(b for b in bits if b)}")
    return out


def block(p: Project, ids: set[str] | None, head: str = "# 호칭 · 말씨") -> str:
    """쓰기 · 검수 · 상태 변경안에 넣는 이번 화 인물끼리의 호칭 · 말씨. 장편은 BUDGET['address'] 까지 넣고 뺀 수를 적는다. 없으면 빈 글."""
    rows = lines(p, ids)
    if not rows:
        return ""
    cut = 0
    if p.serial:
        keep, used = [], 0
        for r in rows:
            if used + len(r) + 1 > context.BUDGET["address"]:
                cut += 1
                continue
            keep.append(r)
            used += len(r) + 1
        rows = keep
    note = f" ({cut}줄은 예산을 넘어 뺐습니다)" if cut else ""
    return (f"\n\n{head} (A → B: A 가 B 를 부르는 말과 B 에게 쓰는 말씨. 본문에서 바꾸는 장면이 없으면 대사는 이대로 씁니다){note}\n"
            + "\n".join(rows))


def check_rule(p: Project) -> str:
    """검수 요구사항 한 줄. 정해 둔 호칭 · 말씨가 없으면 빈 글."""
    if not p.address_forms:
        return ""
    return ("\n- 호칭 · 말씨: [호칭 · 말씨]에 정한 부르는 말이나 말씨(존댓말 · 반말)와 다른 대사가 바뀌는 계기 없이 나오는지 봅니다. "
            "type 은 말투, source_episode 는 0, source_quote 는 그 호칭 · 말씨 줄입니다. 본문에서 관계가 바뀌어 일부러 바꾼 것은 모순이 아닙니다.")


def state_rule(p: Project) -> str:
    """상태 변경안 규칙 한 줄. 늘 붙는다 (정해 두지 않은 작품도 본문이 바꾸면 알려야 한다)."""
    levels = " · ".join(SPEECH_LEVELS)
    return ("\n- address_changes 에는 인물끼리 부르는 말(calls)이나 말씨(speech)가 이번 화 본문에서 뒤 화까지 이어지게 바뀐 방향만 넣습니다 "
            "(예: 서로 반말을 쓰기로 했다, '선배님'에서 '오빠'로 부르기 시작했다, 정체가 드러나 '전하'라고 부르게 됐다). "
            "speaker 가 말하는 인물, listener 가 듣는 인물이고 방향마다 따로 적습니다. 바뀐 칸만 적고 그대로인 칸은 비웁니다. "
            f"speech 는 {levels} 가운데 하나나 짧은 설명입니다. quote 에는 근거 대사를 본문 그대로 적습니다. "
            "[호칭 · 말씨]와 어긋나게 쓴 대사는 바뀐 것이 아니라 warnings 에 적습니다. 대부분의 화에는 비어 있습니다.")
