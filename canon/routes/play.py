"""플레이 모드 (canon/play.py, canon/birth.py) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

import random
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from .. import archetypes, birth, cancel, dynamics, jobs, play, store, timeline, usage
from ..llm import MissingKey, get_llm
from ..schema import Birth, BirthSketch, Episode, PlayInfo, PlayPerson, PlayUnit, Project
from ..web import (  # web 의 공용 도우미
    NAME_ERR,
    NAME_RE,
    NewName,
    _Out,
    _load,
    _need,
    _new_name,
    _play_days,
)

router = APIRouter()

# 플레이 하나는 세계 작품을 복사한 작품 폴더다(play.json 이 있으면 플레이). 시계는 화면에 있고, 서버는 화면이 닿은 구간(see)보다
# 한 구간 넘게 앞서 쓰지 않는다. 구간 작업(play_turn)은 남은 상태 반영 → 장면 → 저장 → 상태 반영 → 저장 순서로 한 스레드에서 돈다.
# 같은 플레이의 구간 작업은 플레이 잠금으로 줄을 세운다. 결정 장면에서 고르면 앞 구간 반영이 끝난 뒤에 쓴다.

class PlayBeatOut(_Out):
    when: str = Field(description="작품 속 시점 (timeline.when). 모르면 빈 값")
    day: int = Field(description="작품 속 날수. 화면 시계가 줄 사이 시간 칸을 센다. 모르면 0")
    text: str


class PlayTurnOut(_Out):
    """구간 하나. 운(luck)은 화면에 보이지 않아 응답에서 뺀다."""
    number: int
    kind: str
    action: str
    beats: list[PlayBeatOut]
    scene: str = Field(description="결정 장면 본문. 없으면 빈 값")
    choices: list[str]
    state: str
    error: str
    ending: str
    when: str = Field(description="구간이 끝난 시점. 상태를 반영하기 전이면 빈 값일 수 있다")
    summary: str


class PlayChapterOut(_Out):
    number: int
    title: str
    start_ep: int
    end_ep: int
    summary: str
    span: str = Field(description="작품 속 시점 범위 ('3일째 ~ 9일째'). 모르면 빈 값")


class PlayMe(_Out):
    id: str
    name: str
    gender: str
    age: str
    role: str
    emotion: str
    goal: str
    location: str
    attire: str


class PlayStatOut(_Out):
    name: str
    value: str


class PlayDeadlineOut(_Out):
    what: str
    left: str = Field(description="'4일 남음' · '오늘' · '2일 지남'. 날을 모르면 빈 값")


class PlayNearOut(_Out):
    """가까운 사람: 그 인물이 플레이어를 보는 관계 (dynamics 계산값을 말로)."""
    id: str
    name: str
    warmth: str
    trust: str
    tension: str
    warmth_value: float = Field(description="-1~1")
    tension_value: float = Field(description="0~10")


class PlayJobOut(_Out):
    id: str
    status: str
    label: str
    ep: int | None = None
    note: str
    error: str
    started: float


class PlayView(_Out):
    """플레이 화면이 보는 값. 플레이 정보와 구간, 옆 패널(내 인물 상태, 상태창, 기한, 가까운 사람), 지금 도는 구간 작업."""
    name: str
    title: str
    world: str
    world_title: str
    world_exists: bool
    world_ep: int
    origin: str
    person: str
    unit: str
    segment_units: int
    focus: str
    auto_decide: bool
    seen: int
    ending: str
    ended_ep: int
    start_day: int
    max_turns: int
    end_days: int
    end_decisions: int
    decisions: int
    days: int
    now: str = Field(description="마지막으로 반영한 구간이 끝난 시점")
    me: PlayMe
    stat_title: str
    stats: list[PlayStatOut]
    deadlines: list[PlayDeadlineOut]
    near: list[PlayNearOut]
    turns: list[PlayTurnOut]
    chapters: list[PlayChapterOut]
    job: PlayJobOut | None = Field(None, description="도는 구간 작업, 또는 마지막 구간 작업이 실패했으면 그 작업")


class PlayRelChange(_Out):
    id: str
    name: str
    before: str = Field(description="처음 (플레이를 시작할 때) 그 인물이 플레이어를 보던 마음. 모르는 사이였으면 빈 값")
    after: str
    trust: str


class PlayLife(_Out):
    """생애 기록: 출생, 장별 요약, 관계 처음 → 끝, 마지막 구간."""
    name: str
    title: str
    world: str
    world_title: str
    player: str
    gender: str
    age: str
    place: str
    origin: str
    seed: int
    ending: str
    days: int
    decisions: int
    free: int = Field(description="직접 적어 해 본 일 수")
    turns: int
    archetype: str
    wound: str
    speech: str
    twist: str
    background: str
    chapters: list[PlayChapterOut]
    relations: list[PlayRelChange]
    last_when: str
    last_text: str


class PlayWorldChar(_Out):
    id: str
    name: str
    role: str
    age: str
    gender: str
    tier: str
    summary: str
    emotion: str
    goal: str


class PlayWorld(_Out):
    """새 플레이 화면이 보는 세계 작품 정보."""
    name: str
    title: str
    genre: str
    form: str
    adult: bool
    world_ep: int = Field(description="플레이가 이어받는 마지막 반영 화")
    unit: str = Field(description="시간 단위 자동 값 (play.pick_unit)")
    characters: list[PlayWorldChar]
    places: int = Field(description="태어날 수 있는 장소 수 (birth.birth_places)")


class BirthIn(BaseModel):
    seed: int | None = None
    gender: str = ""
    age: str = ""


class BirthCard(_Out):
    """굴린 출생과 화면에 보일 이름 (원형 · 상처 · 말투 틀)."""
    birth: Birth
    archetype: str
    wound: str
    speech: str


class SketchIn(BaseModel):
    birth: Birth


class PlayStartIn(BaseModel):
    to: str = Field(description="플레이 폴더 이름")
    title: str = ""
    player: str = Field("", description="세계 인물 id. 무작위 출생이면 비우고 birth · sketch 를 준다")
    birth: Birth | None = None
    sketch: BirthSketch | None = None
    person: PlayPerson = "second"
    unit: PlayUnit = "auto"
    focus: str = ""
    auto_decide: bool = False
    max_turns: int = 0
    end_days: int = 0
    end_decisions: int = 0
    seed: int | None = None


class PlayStarted(_Out):
    name: str
    job: PlayJobOut


class PlayWorldIn(BaseModel):
    name: str
    genres: list[str] = []
    logline: str
    adult: bool = False


class PlayAdvance(BaseModel):
    action: str = Field("", description="직접 적은 행동. 비면 시간이 흐른다 (마지막 구간 반영이 실패했으면 반영을 다시 한다)")
    kind: Literal["flow", "free", "auto"] = Field("flow", description="auto 면 AI 가 낸 lean 을 고른다")
    choice: int = Field(0, description="결정 장면 선택지 번호 (1부터)")


class PlaySee(BaseModel):
    n: int


class PlaySettingsIn(BaseModel):
    title: str | None = None
    focus: str | None = None
    auto_decide: bool | None = None


class PlayRewindIn(BaseModel):
    n: int


class PlayForkIn(BaseModel):
    n: int
    to: str
    title: str = ""


class PlayEndIn(BaseModel):
    reason: str = ""


_play_locks: dict[str, threading.Lock] = {}


def _play_lock(name: str) -> threading.Lock:
    """구간 작업이 플레이 하나를 차례로 쓰게 하는 잠금. LLM 호출 동안 잡으므로 짧은 저장 잠금(jobs.project_lock)과 따로 둔다."""
    with jobs._lock:
        return _play_locks.setdefault(name, threading.Lock())


def _play(name: str) -> tuple[Project, PlayInfo]:
    _need(name)
    info = store.load_play(name)  # 플레이 사본이 아니면 작품을 읽기 전에 알린다 (작품 홈이 화면 이동마다 묻는다)
    if info is None:
        raise ValueError(f"플레이가 아닌 작품이에요: {name}")
    return store.load(name), info


def _play_save(name: str, p: Project | None, info: PlayInfo) -> None:
    """구간 작업의 저장. 그동안 화면이 고친 play.json 칸(닿은 구간, 이름, 초점, 자동 결정)은 디스크 것을 따른다.
    멈춘 작업이면 저장하지 않는다 (되감기 · 끝내기가 먼저 멈춘다)."""
    with jobs.project_lock(name):
        cancel.check()
        fresh = store.load_play(name)
        if fresh is not None:
            play.see(info, fresh.seen)
            info.title, info.focus, info.auto_decide = fresh.title, fresh.focus, fresh.auto_decide
        if p is not None:
            store.save(name, p)
        store.save_play(name, info)


def _play_running(name: str) -> list[jobs.Job]:
    return [j for j in jobs.listing(name) if j.kind == "play_turn" and j.status == "running"]


def _play_stop(name: str, after: int | None = None) -> None:
    """도는 구간 작업을 멈춘다. after 를 주면 그 구간보다 뒤를 쓰는 작업만 (화면이 아직 닿지 않은 구간)."""
    for j in _play_running(name):
        if after is None or (j.ep or 0) > after:
            jobs.stop(j.id)


def _play_job_out(j: jobs.Job) -> PlayJobOut:
    return PlayJobOut(id=j.id, status=j.status, label=j.label, ep=j.ep, note=j.note, error=j.error, started=j.started)


def _play_settle(name: str, p: Project, info: PlayInfo, n: int, llm) -> None:
    with usage.scope(episode=n):
        try:
            play.settle(llm, p, info, n)
        except cancel.Cancelled:
            raise
        except Exception:
            _play_save(name, None, info)  # 반영 실패(failed)만 남긴다. 구간은 그대로다
            raise
    _play_save(name, p, info)


def _play_start_job(name: str, info: PlayInfo, action: str = "", kind: str | None = None) -> jobs.Job:
    """구간 작업을 시작한다. 마지막 구간 반영이 남았으면 먼저 반영하고(행동이 그 구간을 버리면 건너뜀), 행동이 없고 반영만 남았으면
    반영만 한다. 끝나면 _play_continue 가 다음 흐름 구간을 잇는다."""
    scene_llm, state_llm = get_llm("play"), get_llm("state")  # 키가 없으면 바로 알린다
    last = play.last_turn(info)
    retry = not action and last is not None and last.state != "applied"
    if retry:
        n = last.number
        label = f"{n}구간 상태 반영"
    else:
        n = (max(info.seen, info.world_ep) if action and info.turns else play.next_number(info) - 1) + 1
        label = f"{n}구간 쓰기"

    def fn(job: jobs.Job):
        lock = _play_lock(name)
        while not lock.acquire(timeout=0.5):
            cancel.check()
        try:
            p, info = play.load(name)
            t = play.last_turn(info)
            if t is not None and t.state != "applied" and not info.ending and not (action and t.number > info.seen):
                job.note = f"{t.number}구간 상태 반영 중"
                _play_settle(name, p, info, t.number, state_llm)
            if retry:
                return {"turn": n}
            job.note = f"{n}구간 쓰는 중"
            cancel.check()
            with usage.scope(episode=n):
                play.scene(scene_llm, p, info, action or (info.opening if not info.turns else ""), kind)  # type: ignore[arg-type]
            k = play.last_turn(info).number  # 끼어들면 보지 않은 구간을 버려 번호가 당겨진다
            _play_save(name, p, info)  # 구간 먼저 저장한다. 상태 반영이 실패해도 구간은 남는다
            job.done, job.note = 1, f"{k}구간 상태 반영 중"
            _play_settle(name, p, info, k, state_llm)
            job.note = ""
            return {"turn": k}
        finally:
            lock.release()

    def run(job: jobs.Job):
        out = fn(job)
        _play_continue(name, job.id)
        return out

    with usage.scope(project=name, episode=n, task="play"):
        return jobs.start(name, "play_turn", n, label, run, total=1 if retry else 2, owned={n})


def _play_continue(name: str, exclude: str = "") -> None:
    """시간이 흐르는 중이면 다음 구간을 미리 쓴다: 끝나지 않았고, 마지막 구간을 반영했고, 결정 장면이 아니고, 화면이 그 구간에 닿았다.
    그래서 서버는 화면보다 한 구간 넘게 앞서 쓰지 않는다 (play.scene 이 같은 규칙으로 막는다)."""
    if any(j.id != exclude for j in _play_running(name)):
        return
    info = store.load_play(name)
    t = play.last_turn(info) if info else None
    if info is None or t is None or info.ending or t.state != "applied" or t.choices or info.seen < t.number:
        return
    if info.max_turns and len(info.turns) >= info.max_turns:
        return
    try:
        _play_start_job(name, info)
    except (jobs.Busy, MissingKey):
        pass


def _scene_of(p: Project, t, e: Episode | None) -> str:
    """구간 본문(흘러간 일 줄 + 결정 장면)에서 결정 장면만."""
    if e is None or not e.text:
        return ""
    head = play.segment_text(p, t.beats, "")
    return e.text[len(head):].strip() if e.text.startswith(head) else ("" if not t.choices else e.text)


def _play_chapters(p: Project, info: PlayInfo) -> list[PlayChapterOut]:
    out = []
    for a in sorted(p.story_arcs, key=lambda a: a.start_ep):
        if a.end_ep <= info.world_ep:
            continue
        eps = [e for e in p.episodes if a.start_ep <= e.plot.number <= a.end_ep and timeline.known(e.time)]
        days = [b.time for t in info.turns if a.start_ep <= t.number <= a.end_ep for b in t.beats if b.time.day]
        first = days[0] if days else (eps[0].time if eps else None)
        last = eps[-1].time if eps else (days[-1] if days else None)
        span = " ~ ".join(dict.fromkeys(x for x in (timeline.when(p, first), timeline.when(p, last)) if x))
        out.append(PlayChapterOut(number=a.number, title=a.title, start_ep=a.start_ep, end_ep=a.end_ep, summary=a.summary, span=span))
    return out






def _play_view(name: str) -> PlayView:
    p, info = _play(name)
    me = next((c for c in p.characters if c.id == info.player), None)
    st = next((s for s in p.states if s.character_id == info.player), None)
    by_n = {e.plot.number: e for e in p.episodes}
    turns = []
    for t in info.turns:
        e = by_n.get(t.number)
        turns.append(PlayTurnOut(
            number=t.number, kind=t.kind, action=t.action, state=t.state, error=t.error, ending=t.ending,
            beats=[PlayBeatOut(when=timeline.when(p, b.time) if timeline.known(b.time) else "", day=b.time.day, text=b.text) for b in t.beats],
            scene=_scene_of(p, t, e), choices=[c.text for c in t.choices],
            when=timeline.when(p, e.time) if e is not None and timeline.known(e.time) else "", summary=e.summary if e else ""))
    done = max((t.number for t in info.turns if t.state == "applied"), default=info.world_ep)
    last_e = by_n.get(done)
    day = timeline.current_day(p, done + 1)
    deadlines = [PlayDeadlineOut(what=d.what, left=timeline.left(d, day)) for d in timeline.open_deadlines(p, done + 1)][:5]
    near = []
    triads = dynamics.unbalanced_triads(p.ties)
    for c in p.characters:
        tie = dynamics.find_tie(p.ties, c.id, info.player) if c.id != info.player else None
        if tie is None:
            continue
        ten = dynamics.tension(p, c.id, info.player, triads)
        near.append(PlayNearOut(id=c.id, name=c.name, warmth=dynamics.warmth_word(tie.warmth), trust=dynamics.trust_word(tie.trust),
                                tension=dynamics.tension_word(ten), warmth_value=round(tie.warmth, 3), tension_value=round(ten, 2)))
    near.sort(key=lambda x: -x.tension_value)
    job = None
    mine = [j for j in jobs.listing(name) if j.kind == "play_turn"]
    if mine and (mine[-1].status == "running" or mine[-1].status == "error"):
        job = _play_job_out(mine[-1])
    w = store.load(info.world) if store.exists(info.world) else None
    return PlayView(
        name=name, title=info.title or f"{me.name if me else info.player}의 삶", world=info.world, world_title=w.meta.title if w else info.world,
        world_exists=w is not None, world_ep=info.world_ep, origin=info.origin, person=info.person, unit=info.unit,
        segment_units=info.segment_units, focus=info.focus, auto_decide=info.auto_decide, seen=info.seen, ending=info.ending,
        ended_ep=info.ended_ep, start_day=info.start_day, max_turns=info.max_turns, end_days=info.end_days,
        end_decisions=info.end_decisions, decisions=sum(t.kind in play.DECIDED for t in info.turns), days=_play_days(p, info),
        now=timeline.when(p, last_e.time) if last_e is not None and timeline.known(last_e.time) else "",
        me=PlayMe(id=info.player, name=me.name if me else info.player, gender=me.gender if me else "", age=me.age if me else "",
                  role=me.role if me else "", emotion=st.emotional_state if st else "", goal=st.current_goal if st else "",
                  location=st.location if st else "", attire=st.attire if st else ""),
        stat_title=p.stat_window.title, stats=[PlayStatOut(name=x.name, value=x.value) for x in (st.stats if st else []) if x.value],
        deadlines=deadlines, near=near[:5], turns=turns, chapters=_play_chapters(p, info), job=job)


@router.get("/api/projects/{world}/play/world")
def play_world(world: str) -> PlayWorld:
    """새 플레이 화면: 세계 작품의 인물(반영 직후 상태), 시간 단위 자동 값, 태어날 수 있는 장소 수."""
    w = _load(world)
    if store.load_play(world) is not None:
        raise ValueError("플레이 사본에서는 새 플레이를 열 수 없어요. 세계 작품에서 여세요")
    states = {s.character_id: s for s in w.states}
    chars = [PlayWorldChar(id=c.id, name=c.name, role=c.role, age=c.age, gender=c.gender, tier=c.tier,
                           summary=(c.background or c.personality).split("\n")[0][:120],
                           emotion=states[c.id].emotional_state if c.id in states else "",
                           goal=states[c.id].current_goal if c.id in states else "") for c in w.characters if c.name]
    return PlayWorld(name=world, title=w.meta.title or world, genre=w.meta.genre, form=w.meta.form, adult=w.meta.adult,
                     world_ep=birth.last_finalized(w), unit=play.pick_unit(w), characters=chars, places=len(birth.birth_places(w)))


@router.post("/api/projects/{world}/play/roll")
def play_roll(world: str, body: BirthIn) -> BirthCard:
    """무작위 출생을 굴린다 (birth.roll, LLM 없음). 시드를 비우면 새로 정한다."""
    w = _load(world)
    seed = body.seed if body.seed is not None else random.randrange(1 << 31)
    b = birth.roll(w, seed, body.gender, body.age)
    a, wd, sp = archetypes.BY_ID.get(b.archetype), archetypes.WOUND_BY_ID.get(b.wound), archetypes.SPEECH_BY_ID.get(b.speech)
    return BirthCard(birth=b, archetype=a.name if a else b.archetype, wound=wd.name if wd else b.wound, speech=sp.name if sp else b.speech)


@router.post("/api/projects/{world}/play/sketch")
def play_sketch(world: str, body: SketchIn) -> dict:
    """굴린 출생의 배경을 AI 가 채운다 (birth.sketch, 작업). 결과는 작업의 result (BirthSketch)."""
    _load(world)
    llm = get_llm("plan")
    for j in jobs.listing(world):
        if j.kind == "play_sketch" and j.status == "running":
            jobs.stop(j.id)  # 다시 굴렸으면 앞 배경은 쓸모없다
    b = body.birth

    def fn(job: jobs.Job):
        return birth.sketch(llm, store.load(world), b).model_dump()
    with usage.scope(project=world, task="play"):
        return jobs.start(world, "play_sketch", None, f"{b.name or '출생'} 배경 쓰기", fn).public()


@router.post("/api/play/worlds")
def play_new_world(body: PlayWorldIn) -> dict:
    """장르와 한 줄로 새 세계 작품을 만든다 (birth.new_world, 작업). 일반 작품으로 남는다."""
    name = body.name.strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, NAME_ERR)
    if store.exists(name):
        raise HTTPException(409, f"이미 있는 이름이에요: {name}")
    if not body.logline.strip():
        raise ValueError("어떤 세계인지 한 줄로 적어 주세요")
    llm = get_llm("plan")

    def fn(job: jobs.Job):
        birth.new_world(llm, name, body.genres, body.logline, body.adult)
        return {"name": name}
    try:
        with usage.scope(project=name, task="play"):
            return jobs.start(name, "play_world", None, f"새 세계 {name} 만들기", fn).public()
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}


@router.post("/api/projects/{world}/play/start")
def play_start(world: str, body: PlayStartIn) -> PlayStarted:
    """세계 작품을 복사해 플레이를 열고(play.start, LLM 없음) 첫 구간 작업을 시작한다. 세계 작품은 바뀌지 않는다."""
    w = _load(world)
    to = _new_name(NewName(name=body.to))
    get_llm("play"), get_llm("state")  # 키가 없으면 폴더를 만들기 전에 알린다
    character, opening, seed = None, "", body.seed
    if body.birth is not None:
        if body.sketch is None:
            raise ValueError("무작위 출생은 배경을 채운 뒤에 시작해요")
        character, opening = birth.to_character(w, body.birth, body.sketch), body.sketch.opening
        seed = body.birth.seed if seed is None else seed
    with jobs.project_lock(world):
        p, info = play.start(world, to, player=body.player, character=character, birth=body.birth, person=body.person,
                             max_turns=body.max_turns, seed=seed, unit=body.unit, focus=body.focus, auto_decide=body.auto_decide,
                             end_days=body.end_days, end_decisions=body.end_decisions, title=body.title, opening=opening)
    return PlayStarted(name=to, job=_play_job_out(_play_start_job(to, info, opening, "start")))


@router.get("/api/projects/{name}/play")
def get_play(name: str) -> PlayView:
    return _play_view(name)


@router.post("/api/projects/{name}/play/advance")
def play_advance(name: str, body: PlayAdvance) -> PlayJobOut:
    """다음 구간. 고르거나(choice) 적거나(action) 자동 결정(kind auto)이면 그 행동으로, 아니면 시간이 흐른다.
    행동이 있으면 화면이 아직 닿지 않은 구간을 쓰는 작업은 멈추고 버린다(끼어들기). 화면이 닿은 구간의 반영은 끝난 뒤 잇는다."""
    _, info = _play(name)
    if info.ending:
        raise ValueError(f"플레이가 끝났어요 ({info.ending}). 이어 가려면 되감으세요")
    action, kind = body.action.strip(), None
    if body.choice:
        action, kind = play.choice_action(info, body.choice)
    elif body.kind == "auto":
        action, kind = play.auto_action(info)
    elif action:
        kind = "free"  # 선택지와 글이 같으면 play.scene 이 choice 로 센다
    if action:
        _play_stop(name, after=info.seen)
    else:
        running = _play_running(name)
        if running:
            return _play_job_out(running[-1])
        t = play.last_turn(info)
        if t is not None and t.state == "applied":
            play.check_turn(info)  # 결정할 차례 · 아직 보지 않은 구간 · 구간 한도
    return _play_job_out(_play_start_job(name, info, action, kind))


@router.post("/api/projects/{name}/play/see")
def play_see(name: str, body: PlaySee) -> dict:
    """화면 시계가 n 구간에 닿았다. 시간이 흐르는 중이면 다음 구간을 미리 쓰기 시작한다."""
    _play(name)
    with jobs.project_lock(name):
        info = store.load_play(name)
        play.see(info, body.n)
        store.save_play(name, info)
    _play_continue(name)
    return {"seen": info.seen}


@router.put("/api/projects/{name}/play/settings")
def play_settings(name: str, body: PlaySettingsIn) -> PlayView:
    """플레이 이름 · 초점 · 자동 결정. 다음에 쓰는 구간부터 따른다."""
    _play(name)
    with jobs.project_lock(name):
        info = store.load_play(name)
        if body.title is not None:
            info.title = body.title.strip()
        if body.focus is not None:
            info.focus = body.focus.strip()
        if body.auto_decide is not None:
            info.auto_decide = body.auto_decide
        store.save_play(name, info)
    return _play_view(name)


@router.post("/api/projects/{name}/play/rewind")
def play_rewind(name: str, body: PlayRewindIn) -> PlayView:
    """n 구간 직후로 되감는다 (play.rewind). 도는 구간 작업은 멈추고 그 결과는 버린다."""
    _play(name)
    _play_stop(name)
    with jobs.project_lock(name):
        p, info = play.load(name)
        play.rewind(p, info, body.n)
        play.save(name, p, info)
    return _play_view(name)


@router.post("/api/projects/{name}/play/fork")
def play_fork(name: str, body: PlayForkIn) -> dict:
    """'여기서 다르게 해 보기': 이 플레이를 남긴 채 사본을 n 구간 직후로 되감는다 (play.fork)."""
    _play(name)
    to = _new_name(NewName(name=body.to))
    with jobs.project_lock(name):
        play.fork(name, to, body.n, body.title)
    return {"name": to}


@router.post("/api/projects/{name}/play/end")
def play_end(name: str, body: PlayEndIn) -> PlayView:
    """플레이를 끝낸다. 되감으면 다시 이어 갈 수 있다."""
    _play(name)
    _play_stop(name)
    with jobs.project_lock(name):
        p, info = play.load(name)
        if info.ending:
            raise ValueError(f"이미 끝난 플레이예요 ({info.ending})")
        play.end(p, info, body.reason)
        store.save_play(name, info)
    return _play_view(name)


@router.get("/api/projects/{name}/play/life")
def play_life(name: str) -> PlayLife:
    """생애 기록: 출생, 장별 요약, 관계 처음 → 끝(그 인물이 플레이어를 보는 마음), 마지막 구간."""
    p, info = _play(name)
    me = next((c for c in p.characters if c.id == info.player), None)
    b = info.birth
    a = archetypes.BY_ID.get(b.archetype) if b else None
    wd = archetypes.WOUND_BY_ID.get(b.wound) if b else None
    sp = archetypes.SPEECH_BY_ID.get(b.speech) if b else None
    snap = p.snapshot(info.world_ep)
    rels = []
    for c in p.characters:
        tie = dynamics.find_tie(p.ties, c.id, info.player) if c.id != info.player else None
        if tie is None:
            continue
        first = dynamics.find_tie(snap.ties, c.id, info.player) if snap else None
        rels.append(PlayRelChange(id=c.id, name=c.name, before=dynamics.warmth_word(first.warmth) if first else "",
                                  after=dynamics.warmth_word(tie.warmth), trust=dynamics.trust_word(tie.trust)))
    t = play.last_turn(info)
    e = p.episode(t.number) if t else None
    last_text = (_scene_of(p, t, e) or "\n".join(x.text for x in t.beats)) if t else ""
    w = store.load(info.world) if store.exists(info.world) else None
    return PlayLife(
        name=name, title=info.title or f"{me.name if me else info.player}의 삶", world=info.world,
        world_title=w.meta.title if w else info.world, player=me.name if me else info.player, gender=me.gender if me else "",
        age=me.age if me else "", place=b.place if b else "", origin=info.origin, seed=info.seed, ending=info.ending,
        days=_play_days(p, info), decisions=sum(x.kind in play.DECIDED for x in info.turns),
        free=sum(x.kind == "free" for x in info.turns), turns=len(info.turns), archetype=a.name if a else "",
        wound=wd.name if wd else "", speech=sp.name if sp else "", twist=b.twist if b else "", background=me.background if me else "",
        chapters=_play_chapters(p, info), relations=rels,
        last_when=timeline.when(p, e.time) if e is not None and timeline.known(e.time) else "", last_text=last_text)


EXPORTS = (
    "BirthCard",
    "BirthIn",
    "PlayAdvance",
    "PlayBeatOut",
    "PlayChapterOut",
    "PlayDeadlineOut",
    "PlayEndIn",
    "PlayForkIn",
    "PlayJobOut",
    "PlayLife",
    "PlayMe",
    "PlayNearOut",
    "PlayRelChange",
    "PlayRewindIn",
    "PlaySee",
    "PlaySettingsIn",
    "PlayStartIn",
    "PlayStarted",
    "PlayStatOut",
    "PlayTurnOut",
    "PlayView",
    "PlayWorld",
    "PlayWorldChar",
    "PlayWorldIn",
    "SketchIn",
    "_play",
    "_play_chapters",
    "_play_continue",
    "_play_job_out",
    "_play_lock",
    "_play_locks",
    "_play_running",
    "_play_save",
    "_play_settle",
    "_play_start_job",
    "_play_stop",
    "_play_view",
    "_scene_of",
    "get_play",
    "play_advance",
    "play_end",
    "play_fork",
    "play_life",
    "play_new_world",
    "play_rewind",
    "play_roll",
    "play_see",
    "play_settings",
    "play_sketch",
    "play_start",
    "play_world",
)
