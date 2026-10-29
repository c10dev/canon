"""장면 연출 3D 판정: 평면 판정(stage.judge)이 통과시킨 장면에서 높이와 몸 부피 때문에 말이 안 되는 박자를 찾는다.

설계는 docs/stage/3d/specs/04-judge.md (정한 것은 docs/stage/3d/README.md 의 5 · 6 · 7 · 8 · 10).
박자 끝 상태만 보고(frames 의 박자마다), 좌표는 stage.place 그대로다. 결과는 stage.Violation 이라 2D 지적과 같은 길로 간다.
같은 어긋남이 박자마다 되풀이되지 않게, 앞 박자에도 있던 지적은 그 인물들의 자리 · 자세가 이번 박자에 바뀌었을 때만 다시 낸다.
자세 · 장소 모듈이 없는 인물은 판정하지 않는다. LLM 호출 없음.
"""
from __future__ import annotations

import math
from typing import Optional

from .. import stage
from ..logline import josa
from ..schema import Project, StageRoom, StageScene
from . import furniture
from .body import PART_SEGMENT, Capsule, Frames, Person, PostureSpec, penetration

RULES3D = {"reach3d": "높이", "body_overlap": "몸 겹침", "furniture_overlap": "가구", "no_support": "받침", "headroom": "천장"}

# 문턱 (제안값, 실제 자세로 고치는 일은 07)
REACH_GAP_HAND = 0.05   # 손끝 → 부위 점
REACH_GAP_BODY = 0.08   # 부위 점 → 부위 점
BODY_DEPTH = 0.03       # 몸 · 몸 캡슐
ATTACH_DEPTH = 0.08     # 매단 사람과 받치는 사람
FURNITURE_DEPTH = 0.05  # 몸 · 가구 상자 · 벽
FOOT_DEPTH = 0.10       # 발 · 가구 상자: 실제 가구는 아래에 발이 들어갈 틈이 있고, 박자 끝 '걷기'는 보폭이 고정이다 (07 시험 장면)
LIE_OVER = 0.15         # 눕는 면 밖으로 나간 몸
HEAD_STAND = 0.0        # 선 자세: 머리 꼭대기가 천장보다 이만큼 넘게 높으면
HEAD_SIT = 0.05         # 그 밖의 자세

STEP = stage.GAP        # 손 접촉: 선 사람은 기준점 자리 틈만큼 상대 쪽으로 다가설 수 있다 (2D REACH_HAND 도 이 틈을 넣는다)
STEP_TRIES = 4          # 다가서기를 나눠 재는 수

ARMS = ("upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r")
LOWER = ("shin_l", "shin_r", "foot_l", "foot_r")
THIGHS = ("thigh_l", "thigh_r")
# 다리를 어디 둘지 작가가 정하지 않는 앉은 자세: 겹침에서 뺄 다리 마디. 의자 · 쪼그림 · 무릎 꿇기는 넓적다리가 앉는 면 · 몸 아래에
# 놓여 정해지고, 바닥에 앉기는 책상다리 · 무릎 세우기 · 옆으로 모으기 중 무엇인지 모르므로 다리 전체를 뺀다
SEATED = {"chair": LOWER, "squat": LOWER, "kneel": LOWER, "floor": LOWER + THIGHS}
MOVING = ("walk", "run")                       # 앉거나 눕는 기준점 위 · 안에서 이 자세면 그 기준점을 떠나는 중이다
STEPPING = ("stand", "walk", "run")            # 다가설 수 있는 자세
MEET = ("hand", "fingers", "wrist", "forearm")  # 받는 사람이 마주 내밀 수 있는 부위 (막 너머 손 건네기)
SEG_LABELS = {"head": "머리", "torso": "몸통", "pelvis": "골반", "upper_arm_l": "왼 위팔", "upper_arm_r": "오른 위팔",
              "forearm_l": "왼팔", "forearm_r": "오른팔", "thigh_l": "왼 허벅지", "thigh_r": "오른 허벅지",
              "shin_l": "왼 다리", "shin_r": "오른 다리", "foot_l": "왼발", "foot_r": "오른발"}


def _violation(beat: int, cause: int, who: str, rule: str, text: str, contact: str = "") -> stage.Violation:
    # Violation.contact 는 일감 1-1(PR #163)이 더한다. 그 칸이 없는 판에서도 돈다
    extra = {"contact": contact} if "contact" in stage.Violation.model_fields else {}
    return stage.Violation(beat=beat, cause=cause, who=who, rule=rule, text=text, **extra)


def _flat_reach(flat: list[stage.Violation]) -> tuple[set[str], set[tuple[int, str]]]:
    """2D reach 가 짚은 접촉 id. contact 칸이 없는 판이면 (박자, 인물) 로 대신한다."""
    ids, beats = set(), set()
    for v in flat:
        if v.rule == "reach":
            cid = getattr(v, "contact", "")
            if cid:
                ids.add(cid)
            else:
                beats.add((v.beat, v.who))
    return ids, beats


def _changes(fr: Frames) -> list[dict[str, int]]:
    """박자마다 인물별로 자리(기준점 · 관계) · 자세가 마지막으로 바뀐 박자."""
    out, last, seen = [], {}, {}
    for b in fr.beats:
        for w, now in b.state.items():
            key = ((now.at.ref, now.at.rel) if now.at else None, now.posture or "stand")
            if seen.get(w) != key:
                seen[w], last[w] = key, b.k
        out.append(dict(last))
    return out


def _rest(spec: PostureSpec, now: stage.Now, anchors: dict, room_spec) -> Optional[str]:
    """그 인물이 놓인 면: 기준점의 seat · lie · top 중 하나, 아니면 None (바닥). body._base 와 같은 차례."""
    at = now.at
    a = anchors.get(at.ref) if at else None
    if not a or at.rel not in ("on", "in"):
        return None
    for what in spec.surface:
        if what in ("seat", "lie") or (what == "top" and at.rel == "on"):
            if furniture.surface(a, room_spec, what) is not None:
                return what
    return None


def _apart(c: Capsule, d) -> bool:
    """둘레 상자가 떨어져 있나 (깊이 계산 전에 거른다)."""
    box = d.box if not isinstance(d, Capsule) else \
        tuple(min(d.a[i], d.b[i]) - d.r for i in range(3)) + tuple(max(d.a[i], d.b[i]) + d.r for i in range(3))
    return any(min(c.a[i], c.b[i]) - c.r > box[i + 3] or max(c.a[i], c.b[i]) + c.r < box[i] for i in range(3))


def _deepest(xs: list[Capsule], ys, skip_x=(), skip_y=()) -> tuple[float, str, str]:
    """가장 깊이 파고든 짝: (깊이, xs 의 마디, ys 의 마디 또는 빈칸)."""
    best = (0.0, "", "")
    for c in xs:
        if c.segment in skip_x:
            continue
        for d in ys:
            if (isinstance(d, Capsule) and d.segment in skip_y) or _apart(c, d):
                continue
            depth = penetration(c, d)
            if depth > best[0]:
                best = (depth, c.segment, d.segment if isinstance(d, Capsule) else "")
    return best


def _wall_depth(c: Capsule, room: StageRoom) -> float:
    """캡슐이 방 테두리 밖으로 나간 깊이. 선분이라 끝점에서 가장 깊다."""
    xs, ys = (c.a[0], c.b[0]), (c.a[1], c.b[1])
    return max(0.0, c.r - min(xs), max(xs) + c.r - room.w, c.r - min(ys), max(ys) + c.r - room.h)


def _open(fr: Frames) -> bool:
    """야외 틀: 벽 · 천장이 없다 (RoomSpec.open)."""
    return bool(fr.spec and fr.spec.open)


def _cross(p, q, box, dims: int) -> bool:
    """선분 p → q 가 축 맞춤 상자(x0, y0, z0, x1, y1, z1)를 지나나 (dims 2 면 평면만, 3 이면 높이도). slab 방식."""
    t0, t1 = 0.0, 1.0
    for i in range(dims):
        d = q[i] - p[i]
        if abs(d) < 1e-9:
            if not box[i] <= p[i] <= box[i + 3]:
                return False
            continue
        a, z = (box[i] - p[i]) / d, (box[i + 3] - p[i]) / d
        t0, t1 = max(t0, min(a, z)), min(t1, max(a, z))
        if t0 > t1:
            return False
    return True


def _parted(x, y, fr: Frames) -> bool:
    """두 사람의 골반을 잇는 평면 선분이 막(barrier) 상자를 지나면 차체 · 창 면으로 갈린 두 사람이다. 몸 겹침을 보지 않는다
    (차 안에 앉은 사람과 창밖에 선 사람). 창으로 몸을 들이민 겹침은 이 규칙으로 놓친다 (docs/stage/3d/specs/rooms/car_side.md)."""
    p, q = x.joints()["pelvis"], y.joints()["pelvis"]
    return any(s.solid and s.barrier and _cross(p, q, s.box, 2) for s in fr.solids)


def _blocked(c, b, fr: Frames, anchors: dict) -> str:
    """손 접촉의 어깨 → 목표 점이 막 상자를 지나면 그 기준점 이름 (창 높이는 막이 없어 지난다). 손 아닌 접촉 · 막이 없으면 빈칸."""
    me = b.bodies.get(c.who)
    if not c.hands or not me or me.body is None:
        return ""
    joints = me.body.joints()
    other = b.bodies.get(c.to)
    meet = c.part.split("_")[0] in MEET and other is not None and other.body is not None
    for side, t in zip(c.hands, c.points[1::2]):
        if meet:  # 손에 건네기 · 손 잡기: 받는 사람도 손을 내미니 그 어깨까지 길이 트였는지 본다
            t = other.body.joints()["shoulder_" + c.part.rsplit("_", 1)[-1]]
        for s in fr.solids:
            if s.solid and s.barrier and _cross(joints[f"shoulder_{side}"], t, s.box, 3):
                return anchors[s.anchor].name if s.anchor in anchors else "차체"
    return ""


def _outside(c: Capsule, a) -> float:
    """캡슐 끝점이 기준점 평면 자리 밖으로 나간 거리 (가장 먼 것)."""
    def out(p):
        dx = max(a.x - p[0], 0.0, p[0] - (a.x + a.w))
        dy = max(a.y - p[1], 0.0, p[1] - (a.y + a.h))
        return (dx * dx + dy * dy) ** 0.5
    return max(out(c.a), out(c.b))


def _skip(person: Person) -> set[str]:
    """겹침에서 빼는 마디: 팔은 늘(자세 표 값이라 손을 얹거나 짚는 것은 흔하다), 앉은 자세는 SEATED 의 다리 마디도
    (책상 밑 · 소파 앞 · 마주 앉은 사람 사이로 다리를 접거나 옮긴다. 03 측정 c1 · c2 · c5)."""
    return set(ARMS) | set(SEATED.get(person.posture, ()))


def _same_rest(a: Optional[stage.Now], b: Optional[stage.Now]) -> bool:
    """두 사람이 같은 기준점 위 · 안에 있나."""
    return bool(a and b and a.at and b.at and a.at.ref == b.at.ref and not a.at.ref.startswith("@")
                and a.at.rel in ("on", "in") and b.at.rel in ("on", "in"))


def _support(spec: PostureSpec, now: stage.Now, person: Person, w: str, b, fr: Frames, anchors: dict, caps: dict,
             name: str, label: str) -> str:
    """받침 지적 글 (없으면 빈칸)."""
    if "carrier" in spec.surface:
        held = person.attach or any(
            o != w and any(c.to == w and stage.ACTS.get(c.act, stage.Act("", 0)).support for c in s.contacts.values())
            for o, s in b.state.items())
        return "" if held else f"{name}{josa(name, '은', '는')} '{label}' 자세인데 안거나 업은 사람이 없어요."
    if "back_support" in spec.surface:
        ok = now.at and now.at.rel == "against"
        return "" if ok else f"{name}{josa(name, '은', '는')} '{label}' 자세인데 등 뒤에 기댈 곳이 없어요."
    what = _rest(spec, now, anchors, fr.spec)
    if what is None and "floor" not in spec.surface:
        need = "누울 곳" if "lie" in spec.surface else "앉을 곳" if "seat" in spec.surface else "올라설 곳"
        return f"{name}{josa(name, '은', '는')} '{label}' 자세인데 {need}이 없어요."
    if what == "lie":
        a = anchors[now.at.ref]
        over = max(_outside(c, a) for c in caps[w] if c.segment not in ARMS)
        if over > LIE_OVER:
            return f"{name}: 누울 자리가 짧아요. 몸이 {a.name} 밖으로 {over:.2f}m 나가요."
    return ""


def _stepped(c, b, fr: Frames, room: StageRoom, pspecs: dict) -> float:
    """선 사람이 상대 쪽으로 STEP 까지 다가서서 손을 뻗었을 때 가장 작은 틈. 기준점 관계 자리는 가구 바깥 GAP 에 놓이므로
    같은 가구 앞 · 옆에 선 두 사람은 실제보다 멀다(03 측정 c4). 다가서다 가구 · 벽 · 다른 사람을 파고들면 거기서 멈춘다
    (침대 한가운데 앉은 사람은 침대 앞에서 다가서도 닿지 않는다). 좌표는 바꾸지 않고 틈만 다시 잰다."""
    from .body import _placed, reach_to
    me = b.bodies[c.who]
    spec = pspecs.get(me.posture)
    if me.posture not in STEPPING or spec is None or me.body is None or me.body.base > 1e-6:
        return c.gap
    aims = c.points[1::2]
    tx, ty = sum(t[0] for t in aims) / len(aims), sum(t[1] for t in aims) / len(aims)
    x0, y0 = me.body.x, me.body.y
    d = math.hypot(tx - x0, ty - y0)
    if d < 1e-6:
        return c.gap
    ux, uy = (tx - x0) / d, (ty - y0) / d
    others = [(x.body.capsules(), _skip(x)) for w, x in b.bodies.items() if w != c.who and x.body is not None]
    best = c.gap
    for i in range(1, STEP_TRIES + 1):
        s = min(STEP * i / STEP_TRIES, d)
        body = _placed(spec, x0 + ux * s, y0 + uy * s, math.atan2(ux, uy), 0.0)
        caps = [k for k in body.capsules() if k.segment not in ARMS]
        if any(_wall_depth(k, room) > FURNITURE_DEPTH for k in caps if not _open(fr)) or \
                any(o.solid and _deepest(caps, [o])[0] > FURNITURE_DEPTH for o in fr.solids) or \
                any(_deepest(caps, oc, skip_y=skip)[0] > BODY_DEPTH for oc, skip in others):
            break
        best = min(best, max(reach_to(body, side, t) for side, t in zip(c.hands, aims)))
    return best


def _check_beat(b, fr: Frames, room: StageRoom, p: Project, pspecs: dict, skip_ids: set[str], skip_beats: set,
                changed: dict[str, int], order: list[str]) -> list[tuple[tuple, int, str, str, str, str]]:
    """박자 하나의 지적: [(묶는 열쇠, cause, who, rule, text, contact)]."""
    out = []
    anchors = {a.id: a for a in room.anchors}
    people: dict[str, Person] = {w: x for w, x in b.bodies.items() if x.body is not None}
    names = {w: stage._name(p, w) for w in b.state}

    def ch(*ws: str) -> int:
        return max(changed.get(w, 0) for w in ws)

    def label(w: str) -> str:
        pid = b.state[w].posture or "stand"
        return stage.POSTURES[pid].label if pid in stage.POSTURES else pid

    # 높이: 이어지는 접촉의 손끝(또는 부위 점) 틈. 두 사람이 같은 기준점 위 · 안이면 건너뛴다:
    # 평면 자리는 기준점 가운데라 침대 · 소파 어디쯤에 앉았는지 모른다 (침대 머리맡에 걸터앉아 머리를 쓰다듬기)
    for c in b.contacts:
        if c.id in skip_ids or (b.k, c.who) in skip_beats or _same_rest(b.state.get(c.who), b.state.get(c.to)):
            continue
        who, to = names[c.who], names[c.to]
        part = stage.PARTS[c.part].label if c.part in stage.PARTS else c.part
        wall = _blocked(c, b, fr, anchors)
        if wall:
            text = f"{who} → {to} {part}: {wall}에 막혀 손이 닿지 않아요. 창 높이로 손이 지나게 자리나 자세를 바꾸는 박자가 필요해요."
            out.append((("reach3d", c.id), ch(c.who, c.to), c.who, "reach3d", text, c.id))
            continue
        limit = REACH_GAP_HAND if c.hands else REACH_GAP_BODY
        if c.gap <= limit:
            continue
        gap = _stepped(c, b, fr, room, pspecs) if c.hands else c.gap
        if gap <= limit:
            continue
        if c.hands:
            text = (f"{who} → {to} {part}: {to}{josa(to, '이', '가')} '{label(c.to)}' 자세라 {who}{josa(who, '이', '가')} "
                    f"'{label(c.who)}' 자세로는 손이 {gap:.2f}m 모자라요. 자리나 자세를 바꾸는 박자가 필요해요.")
        else:
            text = f"{who} → {to} {part}: 두 부위가 {gap:.2f}m 떨어져 닿지 않아요. 자리나 자세를 바꾸는 박자가 필요해요."
        out.append((("reach3d", c.id), ch(c.who, c.to), c.who, "reach3d", text, c.id))

    # 몸 겹침: 두 사람씩
    ws = [w for w in order if w in people]
    touch: dict[frozenset, set[tuple[str, str]]] = {}
    for w, now in b.state.items():
        for c in now.contacts.values():
            s = touch.setdefault(frozenset((w, c.to)), set())
            if c.part in PART_SEGMENT:
                s.add((c.to, PART_SEGMENT[c.part]))
            if c.by in PART_SEGMENT:
                s.add((w, PART_SEGMENT[c.by]))
    caps = {w: people[w].body.capsules() for w in ws}
    for i, w in enumerate(ws):
        for o in ws[i + 1:]:
            if _parted(people[w].body, people[o].body, fr):
                continue
            pair = frozenset((w, o))
            attach = people[w].attach == o or people[o].attach == w
            near = pair in touch or attach
            # 팔은 늘 뺀다: 자세 표 값이라 나란히 선 두 사람(0.5m)의 팔이 닿는 것은 어긋남이 아니다 (07 시험)
            skip_w = _skip(people[w]) | ({s for x, s in touch.get(pair, ()) if x == w} if near else set())
            skip_o = _skip(people[o]) | ({s for x, s in touch.get(pair, ()) if x == o} if near else set())
            depth, sw, so = _deepest(caps[w], caps[o], skip_w, skip_o)
            if depth > (ATTACH_DEPTH if attach else BODY_DEPTH):
                a, z = names[w], names[o]
                text = f"{a}{josa(a, '과', '와')} {z}{josa(z, '이', '가')} {depth:.2f}m 겹쳐요 ({a} {SEG_LABELS[sw]} · {z} {SEG_LABELS[so]})."
                out.append((("body_overlap", w, o), ch(w, o), w, "body_overlap", text, ""))

    # 받침 · 천장 (가구보다 먼저: 받침 지적이 난 사람은 몸이 놓일 자리가 틀렸으므로 가구 겹침은 그 결과라 내지 않는다)
    unsupported = set()
    for w in ws:
        now, person, name = b.state[w], people[w], names[w]
        spec = pspecs.get(person.posture)
        if spec is None:
            continue
        text = _support(spec, now, person, w, b, fr, anchors, caps, name, label(w))
        if text:
            unsupported.add(w)
            out.append((("no_support", w), ch(w), w, "no_support", text, ""))
        if fr.spec and fr.spec.open:  # 야외: 천장이 없다
            continue
        top = person.body.head_top()
        pid = now.posture or "stand"
        upright = stage.POSTURES[pid].upright if pid in stage.POSTURES else True
        over = top - fr.ceiling
        if over > (HEAD_STAND if upright else HEAD_SIT):
            place = stage.ROOMS[room.template][0] if room.template in stage.ROOMS else room.name or "방"
            text = f"{place}{josa(place, '이라', '라')} '{label(w)}' 자세면 {name} 머리가 천장보다 {over:.2f}m 높아요."
            out.append((("headroom", w), ch(w), w, "headroom", text, ""))

    # 가구: 사람 · 기준점마다 가장 깊은 마디, 벽은 한 덩어리. 팔은 보지 않는다(손을 가구에 얹거나 짚는 것은 흔하고,
    # 팔 각도는 작가가 정하지 않은 자세 표 값이다)
    for w in ws:
        if w in unsupported:
            continue
        body, at = people[w].body, b.state[w].at
        rest = at.ref if at and at.rel in ("on", "in") and body.base > 1e-6 else None  # 앉거나 누운 · 올라선 기준점
        a = anchors.get(at.ref) if at else None
        if a and (a.sit or a.lie) and at.rel in ("on", "in") and people[w].posture in MOVING:
            rest = at.ref  # 앉거나 눕던 자리에서 일어나 떠나는 중 (03 측정 c3). 책상 안을 걷는 것은 그대로 짚는다
        lean = at.ref if at and at.rel == "against" else None
        hits: dict[str, tuple[float, str]] = {}
        for s in fr.solids:
            if not s.solid or s.anchor in (rest, lean):
                continue
            depth, seg, _ = _deepest(caps[w], [s], skip_x=_skip(people[w]))
            if depth > hits.get(s.anchor, (0.0, ""))[0]:
                hits[s.anchor] = (depth, seg)
        for c in caps[w] if not _open(fr) else ():  # 야외: 벽이 없다
            if c.segment in _skip(people[w]):
                continue
            depth = _wall_depth(c, room)
            if depth > hits.get("", (0.0, ""))[0]:
                hits[""] = (depth, c.segment)
        name = names[w]
        for aid, (depth, seg) in sorted(hits.items()):
            if depth <= (FOOT_DEPTH if seg.startswith("foot") and aid else FURNITURE_DEPTH):
                continue
            where = anchors[aid].name if aid in anchors else "벽"
            part = SEG_LABELS[seg]
            text = f"{name} {part}{josa(part, '이', '가')} {where}에 {depth:.2f}m 파고들어요."
            out.append((("furniture_overlap", w, aid), ch(w), w, "furniture_overlap", text, ""))

    return out


def judge3d(scene: StageScene, room: StageRoom, p: Project, frames: Optional[Frames] = None,
            flat: Optional[list[stage.Violation]] = None) -> list[stage.Violation]:
    """3D 규칙 다섯 개(RULES3D)를 박자 끝마다 본다. 2D reach 가 짚은 접촉은 다시 짚지 않는다.
    frames 를 주지 않으면 등록부로 구하고, flat 을 주지 않으면 stage.judge 를 부른다. 박자 순, 같은 박자는 규칙 이름 순."""
    from . import body, postures as posture_reg
    fr = frames if frames is not None else body.frames(scene, room, p)
    skip_ids, skip_beats = _flat_reach(stage.judge(scene, room, p) if flat is None else flat)
    pspecs = posture_reg.load()
    changes = _changes(fr)
    order = list(scene.cast) + [w for w in fr.beats[0].state if w not in scene.cast] if fr.beats else list(scene.cast)
    out: list[stage.Violation] = []
    prev: set = set()
    for b in fr.beats:
        found = _check_beat(b, fr, room, p, pspecs, skip_ids, skip_beats, changes[b.k], order + [w for w in b.state if w not in order])
        if b.k >= 1:  # 시작 상태(0)의 어긋남은 첫 박자에서 cause 0 으로 낸다
            for key, cause, who, rule, text, cid in found:
                if key not in prev or cause == b.k:
                    out.append(_violation(b.k, cause, who, rule, text, cid))
            prev = {f[0] for f in found}
    return sorted(out, key=lambda v: (v.beat, v.rule, v.who, getattr(v, "contact", ""), v.text))


def enabled() -> bool:
    """자세 12개 · 틀(stage.ROOMS)이 다 등록됐을 때만 켠다 (README 정할 것 10)."""
    from . import ready
    return ready()


def judge_if_ready(scene: StageScene, room: StageRoom, p: Project, flat: Optional[list[stage.Violation]] = None) -> list[stage.Violation]:
    """등록부가 덜 찼으면 빈 목록 (2D 만), 다 찼으면 judge3d. stage.judge_all 이 부른다 (check · 검수 지적)."""
    return judge3d(scene, room, p, flat=flat) if enabled() else []
