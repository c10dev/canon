"""플레이 모드: 세계 작품 속 인물이 되어 시간이 흐르는 삶을 살아 보는 텍스트 게임 (DESIGN.md 10장).

플레이 하나는 세계 작품 폴더를 복사한 작품이다(갈래 branches.make 와 같은 모양). 세계 작품은 바꾸지 않는다.
플레이 정보는 project.json 밖의 play.json (store.load_play · save_play). 구간 하나(코드 이름은 구간, PlayTurn)가 Episode 하나다.
구간은 흘러간 일(beats)과, 있으면 결정 장면(text + choices)으로 된다. 결정 장면이 없으면 행동 없이 다음 구간으로 흐른다(kind flow).
화면 시계가 흘러간 일을 한 줄씩 보이고, 서버는 플레이어가 닿은 구간(PlayInfo.seen)보다 한 구간 넘게 앞서 쓰지 않는다(비용 상한).
구간은 장면 먼저(scene, play 단계) → 상태는 뒤에서(settle, state 단계). 플레이어의 행동(흘려보낸 것도)이 그 구간의 승인이라
자동 집필처럼 사람 검토 없이 반영하고 Episode.auto 로 표시한다. 인물 설정 바꾸기 · 호칭 제안은 features.hold 로 남겨 둔다.
LLM 호출은 scene · settle · 장 요약뿐이고, 나머지는 코드다.

장(StoryArc)은 CHAPTER_LEN 구간 범위로 미리 열고, 마지막 구간을 반영하면 요약으로 접는다(pipeline.recap). prompts.story_parts 는
지금 구간을 덮는 아크가 없으면 최근 구간 요약을 빼므로, 다음 구간을 덮는 장이 늘 있어야 한다(open_chapter).
세계에 부가 있으면 플레이 구간은 '플레이' 부 하나로 덮는다(부 밖의 화는 story_parts 가 부 요약을 쓰지 않는다).
"""
from __future__ import annotations

import random
import shutil

from statistics import median

from . import branches, cancel, dynamics, features, pipeline, prompts, statwin, store, timeline
from .llm import LLM
from .schema import (Act, Birth, Character, Episode, EpisodePlot, Part, PlayBeat, PlayInfo, PlayPerson, PlayScene,
                     PlayTurn, PlayUnit, Project, StateDelta, StoryArc, TurnKind)

CHAPTER_LEN = 20  # 장 하나의 구간 수 (start 가 PlayInfo.chapter_len 에 넣는다)
LUCK = (-2, -1, 0, 1, 2)
LUCK_WEIGHTS = (1, 2, 4, 2, 1)  # 가운데가 많다
SEGMENT_UNITS = 7  # 구간 하나의 최대 시간 칸 [추정: 시안 제안값, 실제 Gemini 속도로 재지 않음]
DECIDED = ("choice", "free", "auto")  # 결정 수 한도에 세는 구간 종류
PLAY_PART = "플레이"
COPY_SKIP = (*branches.COPY_SKIP, "branch.json", "play.json")


def _now() -> str:
    return pipeline._now()


# ---------- 시작 ----------

def start(world: str, to: str, *, player: str = "", character: Character | None = None, birth: Birth | None = None,
          person: PlayPerson = "second", max_turns: int = 0, seed: int | None = None, unit: PlayUnit = "auto",
          focus: str = "", auto_decide: bool = False, end_days: int = 0, end_decisions: int = 0,
          title: str = "", opening: str = "") -> tuple[Project, PlayInfo]:
    """world 작품을 to 폴더로 복사해 플레이를 연다. player 는 세계의 인물 id, 무작위 출생이면 character(birth.to_character)와
    birth 를 준다. opening 은 첫 구간 실마리(BirthSketch.opening)로 play.json 에 남긴다. 세계의 마지막 반영 화 직후 상태에서 시작하고(trim_after), 장편 경로(form serial)와 첫 장을 연다.
    세계 작품의 파일은 바꾸지 않는다. 플레이 사본과 play.json 을 저장한다."""
    if store.exists(to):
        raise ValueError(f"이미 있는 이름이에요: {to}")
    if store.load_play(world) is not None:
        raise ValueError("플레이 사본에서는 새 플레이를 열 수 없어요. 세계 작품에서 여세요")
    w = store.load(world)
    if character is not None:
        if any(c.id == character.id for c in w.characters):
            raise ValueError(f"세계에 이미 있는 인물 id예요: {character.id}")
        player = character.id
    elif not any(c.id == player for c in w.characters):
        raise ValueError(f"세계에 없는 인물이에요: {player or '(비어 있음)'}")
    if min(max_turns, end_days, end_decisions) < 0:
        raise ValueError("한도는 0(없음) 이상이어야 해요")
    world_ep = branches.last_finalized(w)
    last = next((e for e in w.episodes if e.plot.number == world_ep), None)
    info = PlayInfo(world=world, world_ep=world_ep, player=player, origin="random" if character is not None else "character",
                    birth=birth, person=person, seed=random.randrange(1 << 31) if seed is None else seed,
                    max_turns=max_turns, chapter_len=max(1, CHAPTER_LEN), unit=pick_unit(w) if unit == "auto" else unit,
                    segment_units=SEGMENT_UNITS, focus=focus.strip(), auto_decide=auto_decide, end_days=end_days,
                    end_decisions=end_decisions, start_day=last.time.day if last else 0, at=_now(),
                    title=title.strip(), opening=opening.strip())
    dst = store.project_dir(to)
    shutil.copytree(store.project_dir(world), dst, ignore=shutil.ignore_patterns(*COPY_SKIP))
    try:
        p = store.load(to)
        prepare(p, info, character)
        save(to, p, info)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return p, info


def pick_unit(w: Project) -> PlayUnit:
    """세계의 반영한 화 사이 날수 간격의 가운데 값으로 시간 단위를 고른다: 0일 → 한 시간, 1~20일 → 하루, 21~300일 → 한 달,
    그 위 → 한 해. 날수를 적은 화가 둘 넘게 없으면 하루."""
    days = [e.time.day for e in sorted(w.episodes, key=lambda e: e.plot.number) if e.status == "finalized" and e.time.day > 0]
    gaps = [b - a for a, b in zip(days, days[1:]) if b >= a]
    if not gaps:
        return "day"
    g = median(gaps)
    return "hour" if g < 1 else "day" if g <= 20 else "month" if g <= 300 else "year"


def prepare(p: Project, info: PlayInfo, character: Character | None = None) -> None:
    """복사한 세계(p)를 플레이 사본으로 바꾼다: world_ep 뒤를 지우고, 장편 경로로 두고, 첫 장을 연다. 저장하지 않는다."""
    n = info.world_ep
    if n == 0:
        dynamics.ensure_initial(p)
    elif p.snapshot(n) is None:  # 반영은 화 순서대로라 지금 상태가 n화 반영 직후다
        dynamics.take_snapshot(p, n)
    trim_after(p, n)
    _cut(p.story_arcs, n)  # 세계가 n화 뒤로 짜 둔 아크 · 부는 플레이와 상관없다
    _cut(p.parts, n)
    if not p.serial:  # 단편: 쓴 화를 아크 1 로 묶는다 (pipeline.apply_conversion 과 같은 모양, 기획 칸은 비움)
        goals = {a.name: a.goal for a in p.arc}
        p.meta.form = "serial"
        p.story_arcs = [StoryArc(number=1, title=p.meta.title or "세계", start_ep=1, end_ep=n,
                                 goal=p.meta.logline or "세계의 이야기", acts=_acts(1, n, goals))] if n else []
        p.parts, p.arc = [], []
    p.settings.keep_snapshots = True  # 모든 구간으로 되감는다
    if character is not None:
        p.characters.append(character.model_copy(update={"tier": "main"}))
        dynamics.seed_ties(p)
    open_chapter(p, info, n + 1)


def _acts(start: int, end: int, goals: dict[str, str] | None = None) -> list[Act]:
    """start~end 화를 기승전결 넷으로 고르게 나눈다. 4화보다 짧으면 이웃 구간이 한 화를 함께 쓴다 (pipeline.validate_arc)."""
    size = end - start + 1
    out = []
    for k, name in enumerate(pipeline.ACT_NAMES):
        a = start + k * size // 4
        b = max(a, start + (k + 1) * size // 4 - 1)
        out.append(Act(name=name, start_ep=a, end_ep=b, goal=(goals or {}).get(name, "")))
    return out


def _cut(items: list, n: int) -> None:
    """n화를 넘는 아크 · 부를 n화에서 끝낸다 (요약을 비운다). 아크 안 구간도 다시 나눈다."""
    for x in items:
        if x.start_ep <= n < x.end_ep:
            x.end_ep, x.summary = n, ""
            if isinstance(x, StoryArc):
                x.acts = _acts(x.start_ep, n, {a.name: a.goal for a in x.acts})


def open_chapter(p: Project, info: PlayInfo, k: int) -> StoryArc | None:
    """k 구간을 덮는 장이 없으면 k 구간부터 chapter_len 구간 범위로 연다. 구간 한도가 있으면 한도에서 끝낸다.
    세계에 부가 있으면 플레이 부를 늘린다. 연 장 (이미 있으면 None)."""
    if p.arc_for(k) is not None:
        return None
    end = k + max(1, info.chapter_len) - 1
    if info.max_turns:
        end = max(k, min(end, info.world_ep + info.max_turns))
    number = sum(a.start_ep > info.world_ep for a in p.story_arcs) + 1
    arc = StoryArc(number=len(p.story_arcs) + 1, title=f"{number}장", start_ep=k, end_ep=end,
                   goal="플레이어 인물이 고른 행동으로 이어지는 이야기", acts=_acts(k, end))
    p.story_arcs = sorted([*p.story_arcs, arc], key=lambda a: a.start_ep)
    if p.parts:
        last = max(p.parts, key=lambda x: x.start_ep)
        if last.start_ep > info.world_ep:
            last.end_ep = max(last.end_ep, end)
        else:
            p.parts.append(Part(number=last.number + 1, title=PLAY_PART, start_ep=info.world_ep + 1, end_ep=end,
                                goal="플레이어 인물의 이야기"))
    p.meta.target_episodes = max(p.meta.target_episodes, end)
    return arc


# ---------- 되감기 ----------

def trim_after(p: Project, n: int) -> None:
    """n 화(구간) 반영 직후로 돌리고 뒤 Episode 를 지운다. n 뒤에서 시작하는 장 · 부는 빼고, n 을 품은 장이 n 뒤로 이어지면
    요약을 비워 다시 연다 (범위는 그대로라 그 장의 남은 구간을 이어 쓴다). 0 구간(첫 반영 전)도 된다. 저장하지 않는다."""
    if n < 0:
        raise ValueError("0화 이상으로만 되돌릴 수 있어요")
    if n == 0:
        dynamics.ensure_initial(p)
    if any(e.status == "finalized" and e.plot.number > n for e in p.episodes) or p.history and p.history[-1].episode > n:
        pipeline.revert(p, n)
    p.episodes = [e for e in p.episodes if e.plot.number <= n]
    for items in (p.story_arcs, p.parts):
        items[:] = [x for x in items if x.start_ep <= n]
        for x in items:
            if x.end_ep > n:
                x.summary = ""
    for i, a in enumerate(sorted(p.story_arcs, key=lambda a: a.start_ep), 1):
        a.number = i
    pipeline.sync_candidates(p)  # revert 가 돌려 둔 인물 후보 중 남은 화에 나오지 않는 것


def rewind(p: Project, info: PlayInfo, n: int) -> None:
    """n 구간 직후로 되감는다 (trim_after + 구간 기록 자르기, 결말도 지운다). world_ep 면 첫 구간 전으로.
    화면은 결정 장면이 있던 구간을 되감을 곳으로 보인다. 되감은 곳까지는 본 것으로 둔다."""
    applied = {t.number for t in info.turns if t.state == "applied"}
    if n != info.world_ep and n not in applied:
        raise ValueError(f"되감을 수 있는 곳은 시작({info.world_ep}구간)이나 상태를 반영한 구간이에요"
                         + (f" ({pipeline.ep_list(sorted(applied))})" if applied else ""))
    trim_after(p, n)
    info.turns = [t for t in info.turns if t.number <= n]
    info.ending, info.ended_ep, info.seen = "", 0, n
    open_chapter(p, info, n + 1)


def fork(name: str, to: str, n: int, title: str = "") -> tuple[Project, PlayInfo]:
    """'여기서 다르게 해 보기': name 플레이를 to 폴더로 복사하고 사본을 n 구간 직후로 되감는다 (rewind). 원본 플레이는 그대로다.
    갈래(branches.make)와 달리 play.json 을 옮기고 갈래 정보(branch.json)는 옮기지 않는다. 같은 세계의 플레이로 묶인다."""
    if store.exists(to):
        raise ValueError(f"이미 있는 이름이에요: {to}")
    p, info = load(name)
    if n != info.world_ep and n not in {t.number for t in info.turns if t.state == "applied"}:
        rewind(p.model_copy(deep=True), info.model_copy(deep=True), n)  # 되감을 수 없는 곳이면 복사하기 전에 같은 오류를 낸다
    dst = store.project_dir(to)
    shutil.copytree(store.project_dir(name), dst, ignore=shutil.ignore_patterns(*branches.COPY_SKIP, "branch.json"))
    try:
        q, qi = load(to)
        rewind(q, qi, n)
        qi.title, qi.at = title.strip() or qi.title, _now()
        save(to, q, qi)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return q, qi


def end(p: Project, info: PlayInfo, reason: str) -> None:
    """플레이를 끝낸다. 되감으면 다시 이어 갈 수 있다."""
    info.ending = reason.strip() or "플레이어가 끝냈어요"
    info.ended_ep = info.turns[-1].number if info.turns else info.world_ep


# ---------- 구간 ----------

def roll_luck(info: PlayInfo, n: int) -> int:
    """n 구간의 운 -2~2. 같은 시드와 구간이면 같은 값. 가운데(0)가 가장 많다."""
    return random.Random(f"{info.seed}:{n}").choices(LUCK, LUCK_WEIGHTS)[0]


def next_number(info: PlayInfo) -> int:
    return (info.turns[-1].number if info.turns else info.world_ep) + 1


def last_turn(info: PlayInfo) -> PlayTurn | None:
    return info.turns[-1] if info.turns else None


def see(info: PlayInfo, n: int) -> None:
    """화면 시계가 n 구간에 닿았다. 써 둔 마지막 구간보다 뒤로는 가지 않는다."""
    last = last_turn(info)
    info.seen = max(info.seen, min(n, last.number if last else info.world_ep))


def waiting(info: PlayInfo) -> bool:
    """플레이어가 닿은 마지막 구간이 결정 장면에서 멈춰 있다 (고르거나 적어야 다음으로 간다)."""
    t = last_turn(info)
    return t is not None and bool(t.choices) and info.seen >= t.number


def choice_action(info: PlayInfo, i: int) -> tuple[str, TurnKind]:
    """마지막 구간 결정 장면의 i 번째(1부터) 선택지를 scene 에 넘길 (행동, 종류)로."""
    t = last_turn(info)
    if t is None or not t.choices:
        raise ValueError("고를 선택지가 없어요. 행동을 직접 적거나 시간을 흘려보내세요")
    if not 1 <= i <= len(t.choices):
        raise ValueError(f"선택지는 1~{len(t.choices)}번이에요")
    c = t.choices[i - 1]
    if c.skip:  # 턴제 때 만든 play.json
        return (c.text if c.skip in c.text else f"{c.text} ({c.skip} 뒤로)"), "skip"
    return c.text, "choice"


def auto_action(info: PlayInfo) -> tuple[str, TurnKind]:
    """자동 결정: AI 가 낸 lean(이 인물이라면 고를 선택지)을 고른다. 범위 밖이면 첫 선택지."""
    t = last_turn(info)
    if t is None or not t.choices:
        raise ValueError("고를 선택지가 없어요")
    i = t.lean if 1 <= t.lean <= len(t.choices) else 1
    return t.choices[i - 1].text, "auto"


def _skip_of(info: PlayInfo, action: str) -> str:
    t = last_turn(info)
    for c in (t.choices if t else []):
        if c.skip and action in (c.text, f"{c.text} ({c.skip} 뒤로)"):
            return c.skip
    return ""


def _cast_in(p: Project, info: PlayInfo, text: str) -> list[str]:
    """구간에 나온 인물 id. 플레이어 인물이 맨 앞 (dynamics.run_episode 의 만남 계산)."""
    out = [info.player]
    for c in p.characters:
        if c.id != info.player and c.name and c.name in text:
            out.append(c.id)
    return out


def segment_text(p: Project, beats: list[PlayBeat], text: str) -> str:
    """구간 본문 (Episode.text): 흘러간 일 줄('[3일째 아침] ...')과 결정 장면. 상태 변경안 · 줄거리 · 검수가 이 글을 읽는다."""
    lines = []
    for b in beats:
        if not b.text.strip():
            continue
        when = timeline.when(p, b.time) if (b.time.day or b.time.part or b.time.label) else ""
        lines.append(f"[{when}] {b.text.strip()}" if when else b.text.strip())
    return "\n".join(x for x in ("\n".join(lines), text.strip()) if x)


def drop_unseen(p: Project, info: PlayInfo) -> list[int]:
    """플레이어가 아직 닿지 않은 구간(seen 뒤)을 버린다. 흐르는 중 끼어들 때 그 자리에서 행동하게 한다. 버린 구간 번호."""
    gone = [t.number for t in info.turns if t.number > info.seen]
    if gone:
        keep = max(info.seen, info.world_ep)
        trim_after(p, keep)
        info.turns = [t for t in info.turns if t.number <= keep]
        open_chapter(p, info, keep + 1)
    return gone


def check_turn(info: PlayInfo, action: str = "") -> None:
    """다음 구간을 쓸 수 있는가."""
    if info.ending:
        raise ValueError(f"플레이가 끝났어요 ({info.ending}). 이어 가려면 되감으세요")
    t = last_turn(info)
    if t is not None and t.state != "applied":
        raise ValueError(f"{t.number}구간 상태 반영이 끝나지 않았어요"
                         + (f" ({t.error})" if t.state == "failed" and t.error else "") + ". 반영을 마친 뒤 이어 가세요")
    if info.max_turns and len(info.turns) >= info.max_turns:
        raise ValueError(f"구간 한도({info.max_turns}개)에 닿았어요")
    if t is not None and not action and t.number > info.seen:
        raise ValueError("아직 보지 않은 구간이 있어요. 그 구간까지 본 뒤에 다음을 써요")
    if t is not None and not action and t.choices:
        raise ValueError("결정할 차례예요. 선택지를 고르거나 행동을 적으세요")


def scene(llm: LLM, p: Project, info: PlayInfo, action: str = "", kind: TurnKind | None = None) -> PlayScene:
    """다음 구간을 쓴다(prompts.play_scene_prompt). Episode 와 PlayTurn(state pending)을 더한다. 저장하지 않는다.
    행동이 없으면 시간이 흐른다(flow). 결정 장면에서 멈춰 있으면 행동이 있어야 한다. 행동이 있는데 아직 보지 않은 구간이 써져 있으면
    버리고 플레이어가 닿은 곳에서 행동한다(끼어들기). 앞 구간 반영이 끝나지 않았거나, 끝난 플레이거나,
    한 구간 넘게 앞서 쓰게 되면 막는다. 첫 구간은 kind start 이고 행동이 없어도 된다."""
    action = action.strip()
    if action and info.turns:
        drop_unseen(p, info)  # 보지 않은 구간은 반영 중이어도 버린다 (그 앞 구간은 반영이 끝나 있다)
    check_turn(info, action)
    if not info.turns:
        kind = "start"
    elif not action:
        kind = "flow"
    elif kind in (None, "flow", "start"):
        t = last_turn(info)
        kind = "choice" if any(c.text.strip() == action for c in t.choices) else "free"
    n = next_number(info)
    open_chapter(p, info, n)
    luck = roll_luck(info, n)
    prev = next((e for e in p.episodes if e.plot.number == n - 1), None)
    day = prev.time.day if prev else info.start_day
    cancel.check()
    out = llm.json(prompts.SYSTEM_PLAY, prompts.play_scene_prompt(p, info, n, action, luck, kind), PlayScene,
                   hint={"number": n, "action": action, "luck": luck, "kind": kind, "day": day, "unit": info.unit})
    out.beats = [b for b in out.beats if b.text.strip()]
    body = segment_text(p, out.beats, out.text)
    if not body:
        raise ValueError("AI가 빈 구간을 냈어요. 다시 해 보세요")
    if not out.text.strip():  # 결정 장면이 없으면 선택지도 없다
        out.choices, out.lean = [], 0
    act = p.act_for(n)
    title = action.splitlines()[0][:60] if action else ("첫 구간" if kind == "start" else "시간이 흐른다")
    plot = EpisodePlot(number=n, act=act.name if act else "기", title=title,
                       summary=action or ("플레이어 인물이 처음 등장한다" if kind == "start" else "시간이 흐른다"),
                       events=[action] if action else [], characters=_cast_in(p, info, body), emotional_shift="", ending_hook="",
                       pov=info.player, time=(f"{s} 뒤" if (s := _skip_of(info, action)) and kind == "skip" else ""))
    p.episodes = [e for e in p.episodes if e.plot.number != n] + [Episode(plot=plot, status="written", text=body, written_by=pipeline.writer_of(llm))]
    p.episodes.sort(key=lambda e: e.plot.number)
    info.turns.append(PlayTurn(number=n, kind=kind, action=action, luck=luck, beats=out.beats, choices=out.choices,
                               lean=out.lean, ending=out.ending.strip(), at=_now()))
    return out


def _limit_reason(p: Project, info: PlayInfo, n: int) -> str:
    """한도에 닿았으면 끝낼 까닭. 아니면 빈 글."""
    if info.max_turns and len(info.turns) >= info.max_turns:
        return f"구간 한도({info.max_turns}개)에 닿았어요"
    if info.end_decisions and sum(t.kind in DECIDED for t in info.turns) >= info.end_decisions:
        return f"결정 한도({info.end_decisions}번)에 닿았어요"
    day = p.episode(n).time.day
    if info.end_days and day and day - info.start_day >= info.end_days:
        return f"작품 속 {info.end_days}일이 지났어요"
    return ""


def settle(llm: LLM, p: Project, info: PlayInfo, n: int) -> StateDelta:
    """n 구간 상태 변경안을 만들어(prompts.play_state_prompt) 반영한다. 설정 바꾸기 제안은 남겨 두고 Episode.auto 를 켠다.
    장이 끝나면 요약으로 접고 다음 장을 연다. 결말이나 한도면 끝낸다. 저장하지 않는다.
    변경안 만들기가 실패하면 구간을 failed 로 두고(까닭은 error) 예외를 그대로 낸다. 다시 부르면 된다."""
    t = last_turn(info)
    if t is None or t.number != n:
        raise ValueError(f"{n}구간은 마지막 구간이 아니에요" if t else "아직 구간이 없어요")
    if t.state == "applied":
        raise ValueError(f"{n}구간은 이미 상태를 반영했어요")
    try:
        cancel.check()
        d = llm.json(prompts.SYSTEM_EDITOR, prompts.play_state_prompt(p, n), StateDelta,
                     hint={"episode": n, "stats": statwin.enabled(p)})
        d.episode = n
        if not d.time.day and t.beats:  # 마지막 흘러간 일의 시점 (AI 가 적지 않았을 때)
            d.time = next((b.time for b in reversed(t.beats) if b.time.day), d.time)
        pipeline.clean_delta(p, d)
    except Exception as e:
        t.state, t.error = "failed", str(e) or type(e).__name__
        raise
    features.hold(p, d)  # 인물 설정 · 호칭은 작가가 골라야 바뀐다 (autorun 과 같다)
    pipeline.apply_delta(p, d)
    p.episode(n).auto = True
    t.state, t.error = "applied", ""
    fold(llm, p, info)
    if t.ending:
        end(p, info, t.ending)
    elif reason := _limit_reason(p, info, n):
        end(p, info, reason)
    else:
        open_chapter(p, info, n + 1)
    return d


def fold(llm: LLM, p: Project, info: PlayInfo) -> list[int]:
    """모든 구간을 반영했는데 요약이 없는 플레이 장을 요약으로 접는다 (pipeline.recap). 요약에 실패한 장은 다음 구간에 다시 접는다
    (그동안은 구간별 요약이 대신 들어간다). 접은 장 번호."""
    done = []
    for a in p.story_arcs:
        if a.start_ep <= info.world_ep or a.summary or not pipeline.arc_finished(p, a):
            continue
        try:
            r = pipeline.recap(llm, p, "arc", a.number)
        except cancel.Cancelled:
            raise
        except Exception:
            continue
        pipeline.apply_recap(p, "arc", a.number, r.summary)
        done.append(a.number)
    return done


# ---------- 저장 ----------

def save(name: str, p: Project, info: PlayInfo) -> None:
    """플레이 사본과 play.json 을 함께 저장한다 (store.save 가 지운 구간의 episodes/NN.md 도 지운다)."""
    store.save(name, p)
    store.save_play(name, info)


def load(name: str) -> tuple[Project, PlayInfo]:
    info = store.load_play(name)
    if info is None:
        raise ValueError(f"플레이가 아닌 작품이에요: {name}")
    return store.load(name), info
