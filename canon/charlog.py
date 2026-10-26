"""인물 설정 변경: 본문에서 뒤 화까지 이어지게 바뀐 설정(외모, 성격, 말투 등)과 그 기록.

인물 설정(Character)은 고정이 기본이다. 상태 변경안의 설정 바꾸기 제안(StateDelta.setting_changes)은
작가가 상태 승인 화면에서 골라야 반영되고, 자동 집필은 반영하지 않고 남겨 둔다(Project.setting_held).
반영한 제안과 1화 반영 뒤 작가가 설정 화면에서 고친 것은 Project.setting_log 에 전후 값으로 남아
인물 화면의 화별 변화와 되돌리기에 쓴다. 스냅샷은 인물 설정을 담지 않으므로 되돌리기는 이 기록으로 한다.
기록은 프롬프트에 넣지 않는다 (쓰기 · 검수는 지금 설정만 본다). LLM 을 부르지 않는다.
"""
from __future__ import annotations

from .schema import Character, Project, SettingChange, SettingRecord, StateDelta

# AI 가 바꾸자고 할 수 있는 칸. 화면 이름은 설정 화면과 같다
FIELDS: dict[str, str] = {
    "age": "나이", "role": "역할", "appearance": "외모", "personality": "성격", "speech_style": "말투",
    "background": "배경", "goal": "원하는 것", "wound": "두려운 것 · 약점",
}
# 작가가 고친 것을 기록하는 칸 (AI 칸 + 작가만 고치는 칸)
LOG_FIELDS: dict[str, str] = {"name": "이름", "gender": "성별", **FIELDS, "arc": "아크", "narration_voice": "서술 말투"}


def label(field: str) -> str:
    return LOG_FIELDS.get(field, field)


def last_done(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def _char(p: Project, cid: str) -> Character | None:
    return next((c for c in p.characters if c.id == cid), None)


def clean(p: Project, changes: list[SettingChange], n: int, new_ids: set[str] = frozenset()) -> tuple[list[SettingChange], list[str]]:
    """설정에 있는 인물의, 지금 값과 다른 칸만 남긴다. 같은 칸이 두 번 오면 뒤의 것. 이번 화 새 인물은 설정 전체가 오므로 뺀다."""
    out: dict[tuple[str, str], SettingChange] = {}
    warns: list[str] = []
    for x in changes:
        value = x.value.strip()
        c = _char(p, x.character_id)
        if c is None:
            if x.character_id not in new_ids:
                warns.append(f"설정에 없는 인물({x.character_id})의 설정 바꾸기 제안은 뺐어요")
            continue
        if not value or value == getattr(c, x.field, "").strip():
            continue
        out[(x.character_id, x.field)] = x.model_copy(update={"value": value, "reason": x.reason.strip(), "quote": x.quote.strip(), "episode": n})
    return list(out.values()), warns


def clean_delta(p: Project, d: StateDelta) -> None:
    d.setting_changes, warns = clean(p, d.setting_changes, d.episode, {c.id for c in d.new_characters})
    d.warnings += [w for w in warns if w not in d.warnings]


def apply(p: Project, changes: list[SettingChange], n: int) -> list[SettingRecord]:
    """고른 제안을 인물 설정에 쓰고 기록한다. 지금 값과 같거나 인물이 없으면 건너뛴다."""
    recs = []
    for x in changes:
        c = _char(p, x.character_id)
        value = x.value.strip()
        if c is None or x.field not in FIELDS or not value:
            continue
        before = getattr(c, x.field)
        if value == before:
            continue
        setattr(c, x.field, value)
        rec = SettingRecord(episode=n, character_id=c.id, field=x.field, before=before, after=value, source="ai", reason=x.reason, quote=x.quote)
        p.setting_log.append(rec)
        recs.append(rec)
    return recs


def apply_delta(p: Project, d: StateDelta) -> None:
    """pipeline.apply_delta 에서 부른다. 자동 집필은 그 전에 hold 로 제안을 빼 둔다."""
    apply(p, d.setting_changes, d.episode)


def hold(p: Project, d: StateDelta) -> int:
    """자동 집필: 설정 바꾸기 제안을 반영하지 않고 남겨 두고 변경안에서 뺀다. 남긴 개수."""
    held = [x.model_copy(update={"episode": d.episode}) for x in d.setting_changes]
    d.setting_changes = []
    p.setting_held = [x for x in p.setting_held if x.episode != d.episode] + held
    return len(held)


def take_held(p: Project, i: int, value: str | None = None) -> SettingRecord | None:
    """남겨 둔 제안 하나를 적용한다 (value 를 주면 고친 값으로). 그 화의 기록으로 남는다. 지금 값과 같으면 기록 없이 지운다."""
    if not 0 <= i < len(p.setting_held):
        raise ValueError("남겨 둔 설정 바꾸기 제안이 없어요. 화면을 새로 고쳐 보세요")
    x = p.setting_held.pop(i)
    if value is not None:
        x.value = value
    if _char(p, x.character_id) is None:
        raise KeyError(f"인물이 없어요: {x.character_id}")
    recs = apply(p, [x], x.episode)
    return recs[0] if recs else None


def drop_held(p: Project, i: int) -> None:
    if not 0 <= i < len(p.setting_held):
        raise ValueError("남겨 둔 설정 바꾸기 제안이 없어요. 화면을 새로 고쳐 보세요")
    p.setting_held.pop(i)


def record_author(disk: Project, mine: Project) -> list[SettingRecord]:
    """화면 저장(mine)이 인물 설정을 고쳤으면 작가 기록으로 남긴다. 1화를 반영하기 전에는 기록하지 않는다 (설정을 짜는 중).
    같은 화 뒤에 같은 칸을 여러 번 고치면 한 기록으로 합치고, 처음 값으로 돌아오면 기록을 지운다."""
    n = last_done(disk)
    if n == 0:
        return []
    old = {c.id: c for c in disk.characters}
    out = []
    for c in mine.characters:
        o = old.get(c.id)
        if o is None:
            continue
        for f in LOG_FIELDS:
            before, after = getattr(o, f), getattr(c, f)
            if before == after:
                continue
            last = next((r for r in reversed(mine.setting_log) if r.character_id == c.id and r.field == f), None)
            if last is not None and last.source == "author" and last.episode == n:
                last.after = after
                if last.after == last.before:
                    mine.setting_log.remove(last)
                continue
            rec = SettingRecord(episode=n, character_id=c.id, field=f, before=before, after=after, source="author")
            mine.setting_log.append(rec)
            out.append(rec)
    return out


def revert(p: Project, n: int) -> None:
    """pipeline.revert 뒤에 부른다. n화 뒤에 반영한 제안은 지금 값이 그때 그대로면 처음 값으로 돌린다
    (그 뒤 작가가 고쳤으면 작가 값을 둔다). 작가 기록은 지우지 않고 n화 뒤로 옮긴다. 지워진 인물의 기록과 남겨 둔 제안도 정리한다."""
    keep: list[SettingRecord] = []
    for r in reversed(p.setting_log):
        c = _char(p, r.character_id)
        if c is None:
            continue
        if r.episode > n and r.source == "ai":
            if getattr(c, r.field, None) == r.after:
                setattr(c, r.field, r.before)
            continue
        if r.episode > n:
            r.episode = n
        keep.append(r)
    p.setting_log = keep[::-1]
    p.setting_held = [x for x in p.setting_held if x.episode <= n]


def history(p: Project, cid: str) -> list[dict]:
    """이 인물의 설정 변경 기록 (화 순서). 화면과 명령줄이 쓴다."""
    return [{**r.model_dump(), "label": label(r.field)} for r in p.setting_log if r.character_id == cid]


def state_rule(p: Project) -> str:
    """상태 변경안 규칙 한 줄. 늘 붙는다 (설정을 고정해 둔 작품도 본문이 바꾸면 알려야 한다)."""
    return ("\n- setting_changes 에는 [인물 설정]의 칸(age, role, appearance, personality, speech_style, background, goal, wound)이 "
            "이번 화 본문에서 뒤 화까지 이어지게 바뀐 경우만 넣습니다 (예: 머리를 짧게 잘랐다, 얼굴에 흉터가 남았다, 누구에게나 반말을 쓰기로 했다, "
            "정체가 드러나 역할이 바뀌었다, 몇 년이 지나 나이가 바뀌었다). value 에는 바뀐 뒤 그 칸 전체를 적고 바뀌지 않은 부분도 이어서 씁니다. "
            "reason 에는 무엇이 바뀌었는지 한 줄, quote 에는 근거 문장을 본문 그대로 적습니다. "
            "한 장면의 기분, 옷, 금방 나을 상처는 character_updates 에 두고, 설정과 어긋나게 쓴 말투는 바뀐 것이 아니라 warnings 에 적습니다. "
            "대부분의 화에는 비어 있습니다.")
