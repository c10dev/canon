"""플레이 모드: 세계 작품 속 인물이 되어 턴마다 장면을 이어 가는 텍스트 게임.

플레이 하나는 세계 작품 폴더를 복사한 작품이다(갈래 branches.make 와 같은 모양). 세계 작품은 바꾸지 않는다.
플레이 정보는 project.json 밖의 play.json (store.load_play · save_play). 한 턴은 Episode 하나다.
턴은 장면 먼저(scene, play 단계) → 상태는 뒤에서(settle, state 단계). 플레이어가 고른 행동이 그 턴의 승인이라
자동 집필처럼 사람 검토 없이 반영하고 Episode.auto 로 표시한다. 인물 설정 바꾸기 제안은 charlog.hold 로 남겨 둔다.
LLM 호출은 scene · settle · 장 요약뿐이고, 나머지는 코드다.

장(StoryArc)은 CHAPTER_LEN 턴 범위로 미리 열고, 마지막 턴을 반영하면 요약으로 접는다(pipeline.recap). prompts.story_parts 는
지금 턴을 덮는 아크가 없으면 최근 턴 요약을 빼므로, 다음 턴을 덮는 장이 늘 있어야 한다(open_chapter).
세계에 부가 있으면 플레이 턴은 '플레이' 부 하나로 덮는다(부 밖의 화는 story_parts 가 부 요약을 쓰지 않는다).
"""
from __future__ import annotations

import random
import shutil

from . import branches, cancel, charlog, dynamics, pipeline, prompts, statwin, store
from .llm import LLM
from .schema import (Act, Birth, Character, Episode, EpisodePlot, Part, PlayInfo, PlayPerson, PlayScene,
                     PlayTurn, Project, StateDelta, StoryArc, TurnKind)

CHAPTER_LEN = 20  # 장 하나의 턴 수 (start 가 PlayInfo.chapter_len 에 넣는다)
LUCK = (-2, -1, 0, 1, 2)
LUCK_WEIGHTS = (1, 2, 4, 2, 1)  # 가운데가 많다
PLAY_PART = "플레이"
COPY_SKIP = (*branches.COPY_SKIP, "branch.json", "play.json")


def _now() -> str:
    return pipeline._now()


# ---------- 시작 ----------

def start(world: str, to: str, *, player: str = "", character: Character | None = None, birth: Birth | None = None,
          person: PlayPerson = "second", max_turns: int = 0, seed: int | None = None) -> tuple[Project, PlayInfo]:
    """world 작품을 to 폴더로 복사해 플레이를 연다. player 는 세계의 인물 id, 무작위 출생이면 character(birth.to_character)와
    birth 를 준다. 세계의 마지막 반영 화 직후 상태에서 시작하고(trim_after), 장편 경로(form serial)와 첫 장을 연다.
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
    if max_turns < 0:
        raise ValueError("턴 한도는 0(없음) 이상이어야 해요")
    world_ep = branches.last_finalized(w)
    info = PlayInfo(world=world, world_ep=world_ep, player=player, origin="random" if character is not None else "character",
                    birth=birth, person=person, seed=random.randrange(1 << 31) if seed is None else seed,
                    max_turns=max_turns, chapter_len=max(1, CHAPTER_LEN), at=_now())
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
    p.settings.keep_snapshots = True  # 모든 턴으로 되감는다
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
    """k 턴을 덮는 장이 없으면 k 턴부터 chapter_len 턴 범위로 연다. 턴 한도가 있으면 한도에서 끝낸다.
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
    """n 화(턴) 반영 직후로 돌리고 뒤 Episode 를 지운다. n 뒤에서 시작하는 장 · 부는 빼고, n 을 품은 장이 n 뒤로 이어지면
    요약을 비워 다시 연다 (범위는 그대로라 그 장의 남은 턴을 이어 쓴다). 0 턴(첫 반영 전)도 된다. 저장하지 않는다."""
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
    """n 턴 직후로 되감는다 (trim_after + 턴 기록 자르기, 결말도 지운다). world_ep 면 첫 장면 전으로."""
    applied = {t.number for t in info.turns if t.state == "applied"}
    if n != info.world_ep and n not in applied:
        raise ValueError(f"되감을 수 있는 곳은 시작({info.world_ep}턴)이나 상태를 반영한 턴이에요"
                         + (f" ({pipeline.ep_list(sorted(applied))})" if applied else ""))
    trim_after(p, n)
    info.turns = [t for t in info.turns if t.number <= n]
    info.ending, info.ended_ep = "", 0
    open_chapter(p, info, n + 1)


def end(p: Project, info: PlayInfo, reason: str) -> None:
    """플레이를 끝낸다. 되감으면 다시 이어 갈 수 있다."""
    info.ending = reason.strip() or "플레이어가 끝냈어요"
    info.ended_ep = info.turns[-1].number if info.turns else info.world_ep


# ---------- 턴 ----------

def roll_luck(info: PlayInfo, n: int) -> int:
    """n 턴의 운 -2~2. 같은 시드와 턴이면 같은 값. 가운데(0)가 가장 많다."""
    return random.Random(f"{info.seed}:{n}").choices(LUCK, LUCK_WEIGHTS)[0]


def next_number(info: PlayInfo) -> int:
    return (info.turns[-1].number if info.turns else info.world_ep) + 1


def last_turn(info: PlayInfo) -> PlayTurn | None:
    return info.turns[-1] if info.turns else None


def choice_action(info: PlayInfo, i: int) -> tuple[str, TurnKind]:
    """마지막 턴 장면의 i 번째(1부터) 선택지를 scene 에 넘길 (행동, 종류)로. 시간 건너뛰기는 행동에 길이를 담는다."""
    t = last_turn(info)
    if t is None or not t.choices:
        raise ValueError("고를 선택지가 없어요. 행동을 직접 적으세요")
    if not 1 <= i <= len(t.choices):
        raise ValueError(f"선택지는 1~{len(t.choices)}번이에요")
    c = t.choices[i - 1]
    if c.skip:
        return (c.text if c.skip in c.text else f"{c.text} ({c.skip} 뒤로)"), "skip"
    return c.text, "choice"


def _skip_of(info: PlayInfo, action: str) -> str:
    t = last_turn(info)
    for c in (t.choices if t else []):
        if c.skip and action in (c.text, f"{c.text} ({c.skip} 뒤로)"):
            return c.skip
    return ""


def _cast_in(p: Project, info: PlayInfo, text: str) -> list[str]:
    """장면에 나온 인물 id. 플레이어 인물이 맨 앞 (dynamics.run_episode 의 만남 계산)."""
    out = [info.player]
    for c in p.characters:
        if c.id != info.player and c.name and c.name in text:
            out.append(c.id)
    return out


def check_turn(info: PlayInfo) -> None:
    """다음 턴 장면을 쓸 수 있는가."""
    if info.ending:
        raise ValueError(f"플레이가 끝났어요 ({info.ending}). 이어 가려면 되감으세요")
    t = last_turn(info)
    if t is not None and t.state != "applied":
        raise ValueError(f"{t.number}턴 상태 반영이 끝나지 않았어요"
                         + (f" ({t.error})" if t.state == "failed" and t.error else "") + ". 반영을 마친 뒤 다음 행동을 보내세요")
    if info.max_turns and len(info.turns) >= info.max_turns:
        raise ValueError(f"턴 한도({info.max_turns}턴)에 닿았어요")


def scene(llm: LLM, p: Project, info: PlayInfo, action: str = "", kind: TurnKind = "choice") -> PlayScene:
    """다음 턴 장면을 쓴다(prompts.play_scene_prompt). Episode 와 PlayTurn(state pending)을 더한다. 저장하지 않는다.
    앞 턴 상태 반영이 끝나지 않았거나 플레이가 끝났으면 막는다. 첫 턴은 kind start 이고 action 은 비워도 된다."""
    check_turn(info)
    action = action.strip()
    if not info.turns:
        kind = "start"
    elif not action:
        raise ValueError("행동을 적거나 선택지를 고르세요")
    n = next_number(info)
    open_chapter(p, info, n)
    luck = roll_luck(info, n)
    cancel.check()
    out = llm.json(prompts.SYSTEM_PLAY, prompts.play_scene_prompt(p, info, n, action, luck), PlayScene,
                   hint={"number": n, "action": action, "luck": luck})
    if not out.text.strip():
        raise ValueError("AI가 빈 장면을 냈어요. 다시 해 보세요")
    act = p.act_for(n)
    title = action.splitlines()[0][:60] if action else "첫 장면"
    plot = EpisodePlot(number=n, act=act.name if act else "기", title=title, summary=action or "플레이어 인물이 처음 등장한다",
                       events=[action] if action else [], characters=_cast_in(p, info, out.text), emotional_shift="", ending_hook="",
                       time=(f"{s} 뒤" if (s := _skip_of(info, action)) and kind == "skip" else ""))
    p.episodes = [e for e in p.episodes if e.plot.number != n] + [Episode(plot=plot, status="written", text=out.text.strip())]
    p.episodes.sort(key=lambda e: e.plot.number)
    info.turns.append(PlayTurn(number=n, kind=kind, action=action, luck=luck, choices=out.choices,
                               ending=out.ending.strip(), at=_now()))
    return out


def settle(llm: LLM, p: Project, info: PlayInfo, n: int) -> StateDelta:
    """n 턴 상태 변경안을 만들어(prompts.play_state_prompt) 반영한다. 설정 바꾸기 제안은 남겨 두고 Episode.auto 를 켠다.
    장이 끝나면 요약으로 접고 다음 장을 연다. 결말이면 끝낸다. 저장하지 않는다.
    변경안 만들기가 실패하면 턴을 failed 로 두고(까닭은 error) 예외를 그대로 낸다. 다시 부르면 된다."""
    t = last_turn(info)
    if t is None or t.number != n:
        raise ValueError(f"{n}턴은 마지막 턴이 아니에요" if t else "아직 턴이 없어요")
    if t.state == "applied":
        raise ValueError(f"{n}턴은 이미 상태를 반영했어요")
    try:
        cancel.check()
        d = llm.json(prompts.SYSTEM_EDITOR, prompts.play_state_prompt(p, n), StateDelta,
                     hint={"episode": n, "stats": statwin.enabled(p)})
        d.episode = n
        pipeline.clean_delta(p, d)
    except Exception as e:
        t.state, t.error = "failed", str(e) or type(e).__name__
        raise
    charlog.hold(p, d)  # 인물 설정은 작가가 골라야 바뀐다 (autorun 과 같다)
    pipeline.apply_delta(p, d)
    p.episode(n).auto = True
    t.state, t.error = "applied", ""
    fold(llm, p, info)
    if t.ending:
        end(p, info, t.ending)
    elif info.max_turns and len(info.turns) >= info.max_turns:
        end(p, info, f"턴 한도({info.max_turns}턴)에 닿았어요")
    else:
        open_chapter(p, info, n + 1)
    return d


def fold(llm: LLM, p: Project, info: PlayInfo) -> list[int]:
    """모든 턴을 반영했는데 요약이 없는 플레이 장을 요약으로 접는다 (pipeline.recap). 요약에 실패한 장은 다음 턴에 다시 접는다
    (그동안은 턴별 요약이 대신 들어간다). 접은 장 번호."""
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
    """플레이 사본과 play.json 을 함께 저장한다 (store.save 가 지운 턴의 episodes/NN.md 도 지운다)."""
    store.save(name, p)
    store.save_play(name, info)


def load(name: str) -> tuple[Project, PlayInfo]:
    info = store.load_play(name)
    if info is None:
        raise ValueError(f"플레이가 아닌 작품이에요: {name}")
    return store.load(name), info
