"""장면 연출: 방 하나 안에서 인물의 자리 · 자세 · 향함 · 손 · 신체 접촉을 박자마다 적은 데이터의 계산. LLM 을 부르지 않는다.

설계는 docs/stage/ (정한 규칙 README.md, 데이터 형식 model.md). 데이터는 Project.rooms 와 Episode.stage 에 둔다.
인물 자리는 '기준점 + 관계 말'(StageSpot)로 저장하고 좌표는 place 가 계산한다. AI 는 좌표를 읽거나 쓰지 않는다.
판정(judge)은 박자를 차례로 겹친 상태(state_at)로 손 · 이동 자세 · 거리 · 향함 · 물건 규칙을 본다.
미성년 인물이 낀 성적 접촉은 blocked 로 거르고, 작가 입력 · AI 결과 · 프롬프트 모두 이 함수를 쓴다.
한 사건에 계획 장면(role plan)과 본문 장면(role text)을 하나씩 두고, diff 가 계획과 다른 곳(Gap)을 잰다.
AI 가 이름으로 적은 장면(StageDraft)은 from_draft 가 id 로 바꾸고, 본문 장면의 판정 · 차이는 to_issues 가 검수 지적으로 바꾼다.
화별 스토리보드(Episode.storyboard, board.py)는 읽기만 한다: 사건을 맡은 스토리보드 장면(board_scene_of)으로 출연진 · 방 후보를 채운다.
장면 연출은 플롯 사건에 붙고 스토리보드 장면 번호에는 붙이지 않는다 (docs/stage/specs/08-board.md).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from . import board as board_mod
from . import cast as cast_mod
from .logline import josa
from .naming import place_key
from .schema import (AnchorAdd, BoardScene, DraftAnchor, ConsistencyIssue, DraftBody, Episode, Project, StageAnchor, StageBeat, StageBody, StageContact, StageDraft, StageRoom,
                     StageScene, StageSpot)

# ---------- 고정 어휘 ----------
# 화면은 vocab() 으로 받는다 (JS 에 두 번 적지 않는다)

# 기준틀(ISO-Space OLINK): 기준점은 상대(앞에 서서 바라본 쪽), 인물은 내재(그 인물이 향한 쪽). docs/stage/model.md
RELS = {"on": "위", "in": "안", "front": "앞", "back": "뒤", "left": "왼쪽", "right": "오른쪽", "beside": "옆",
        "across": "맞은편", "against": "기대어 맞닿음"}
FACINGS = {"n": "위쪽", "ne": "오른쪽 위", "e": "오른쪽", "se": "오른쪽 아래", "s": "아래쪽", "sw": "왼쪽 아래", "w": "왼쪽", "nw": "왼쪽 위"}
_FACING_VEC = {k: (round(math.sin(math.radians(a)), 6), round(-math.cos(math.radians(a)), 6))
               for k, a in zip(FACINGS, range(0, 360, 45))}  # 평면도는 y 가 아래로 커진다


@dataclass(frozen=True)
class Posture:
    label: str
    upright: bool  # 선 자세: 자리를 옮길 수 있다


POSTURES = {
    "stand": Posture("서기", True),
    "walk": Posture("걷기", True),
    "run": Posture("뛰기", True),
    "lean": Posture("기대 서기", True),
    "chair": Posture("의자에 앉기", False),
    "floor": Posture("바닥에 앉기", False),
    "squat": Posture("쪼그려 앉기", False),
    "kneel": Posture("무릎 꿇기", False),
    "lie": Posture("눕기", False),
    "side": Posture("옆으로 눕기", False),
    "prone": Posture("엎드리기", False),
    "held": Posture("안기거나 업히기", False),
}


@dataclass(frozen=True)
class Part:
    label: str
    side: str  # front · back · both: 몸 앞쪽이면 등 뒤에서 손이 닿지 않는다 (behind_front)
    sexual: bool = False


def _parts() -> dict[str, Part]:
    one = [("head", "머리", "both"), ("hair", "머리카락", "both"), ("forehead", "이마", "front"), ("lips", "입술", "front"),
           ("chin", "턱", "front"), ("neck", "목", "front"), ("nape", "목덜미", "back"), ("chest", "가슴", "front", True),
           ("belly", "배", "front"), ("back", "등", "back"), ("waist", "허리", "both"), ("buttocks", "엉덩이", "back", True),
           ("groin", "사타구니", "front", True)]
    pair = [("eye", "눈", "front"), ("cheek", "뺨", "front"), ("ear", "귀", "both"), ("shoulder", "어깨", "both"),
            ("upper_arm", "위팔", "both"), ("elbow", "팔꿈치", "both"), ("forearm", "아래팔", "both"), ("wrist", "손목", "both"), ("hand", "손", "both"),
            ("fingers", "손가락", "both"), ("flank", "옆구리", "both"), ("thigh", "허벅지", "both"),
            ("inner_thigh", "허벅지 안쪽", "front", True), ("knee", "무릎", "front"), ("calf", "종아리", "back"),
            ("ankle", "발목", "both"), ("foot", "발", "both")]
    out = {r[0]: Part(r[1], r[2], len(r) > 3) for r in one}
    for r in pair:
        for suf, word in (("_l", "왼"), ("_r", "오른")):
            out[r[0] + suf] = Part(f"{word} {r[1]}", r[2], len(r) > 3)
    return out


PARTS = _parts()


@dataclass(frozen=True)
class Act:
    label: str
    hands: int  # 보통 쓰는 손 수 (0 은 손 아닌 부위)
    sexual: bool = False   # 동작 자체가 성적
    intimate: bool = False  # 성적 부위에 닿으면 성적 접촉 (가슴을 미는 것은 아니고, 쓰다듬는 것은 그렇다)
    support: bool = False   # 몸무게를 받친다 (DECO 의 '받침'): 업힌 · 안긴 사람이 옮겨질 수 있다


ACTS = {
    "brush": Act("스치다", 1), "press": Act("짚다", 1), "hold": Act("잡다", 1), "grip": Act("움켜쥐다", 1, intimate=True),
    "pull": Act("끌어당기다", 1), "push": Act("밀다", 1), "hit": Act("치다", 1), "restrain": Act("붙들다", 1),
    "stroke": Act("쓰다듬다", 1, intimate=True), "pat": Act("토닥이다", 1), "wrap": Act("감싸다", 1, intimate=True),
    "hug": Act("안다", 2, support=True), "embrace": Act("끌어안다", 2, support=True), "carry": Act("업다", 2, support=True), "support": Act("받치다", 1, support=True),
    "lean": Act("기대다", 0, support=True), "rest_head": Act("머리를 기대다", 0, support=True), "kiss": Act("입 맞추다", 0, intimate=True),
    "bite": Act("깨물다", 0, intimate=True), "lick": Act("핥다", 0, sexual=True), "rub": Act("문지르다", 1, intimate=True),
    "massage": Act("주무르다", 1, intimate=True), "wipe": Act("닦아 주다", 1), "tidy": Act("매만지다", 1),
    "interlace": Act("손깍지 끼다", 1), "link_arm": Act("팔짱 끼다", 0), "shoulder_arm": Act("어깨동무하다", 1),
    "choke": Act("목을 조르다", 2), "twist": Act("비틀다", 1), "caress": Act("애무하다", 1, sexual=True),
}

HANDS = {"left": "왼손", "right": "오른손", "both": "두 손"}
UNKNOWN = "?"  # 손 상태를 모름: 판정기는 빈손으로도 찬 손으로도 보지 않는다

# ---------- 방 틀 ----------
# (이름, 가로, 세로, [(기준점 이름, 종류, x, y, w, h, rot, 앉기, 눕기)]). 문 rot 180 은 앞쪽이 방 안(위)이라는 뜻이다.
# 의자 · 자리 · 소파의 앞은 마주 보는 가구(책상 · 탁자 · 교탁 · 앞유리, 마주 앉는 자리) 쪽이다 (tests/test_stage.py).
# 앉는 자리가 아닌 기준점의 앞자리는 다른 가구 위에 떨어지지 않는다 (2026-10-29, 3D 판정 07. 이미 만든 방은 그대로)

ROOMS = {
    "bedroom": ("침실", 4.0, 3.2, [("침대", "bed", 0.2, 0.25, 1.4, 2.0, 0, True, True), ("책상", "desk", 2.8, 0.15, 1.0, 0.55, 0, False, False),
                                  ("의자", "chair", 2.2, 0.2, 0.5, 0.5, 270, True, False), ("창", "window", 1.5, 3.1, 0.8, 0.1, 180, False, False),
                                  ("문", "door", 3.1, 3.1, 0.8, 0.1, 180, False, False)]),
    "living": ("거실", 5.0, 4.0, [("소파", "sofa", 0.4, 2.9, 2.2, 0.9, 180, True, True), ("탁자", "table", 0.9, 1.6, 1.2, 0.6, 0, False, False),
                                 ("텔레비전", "other", 0.8, 0.0, 1.4, 0.3, 0, False, False), ("창", "window", 3.6, 0.0, 1.2, 0.1, 0, False, False),
                                 ("문", "door", 4.85, 1.6, 0.15, 0.9, 90, False, False)]),
    "classroom": ("교실", 8.0, 7.0, [("교탁", "desk", 3.4, 0.8, 1.2, 0.6, 0, False, False), ("칠판", "wall", 2.0, 0.0, 4.0, 0.1, 0, False, False),
                                    ("앞자리", "seat", 2.0, 2.2, 1.2, 0.6, 180, True, False), ("뒷자리", "seat", 4.8, 5.4, 1.2, 0.6, 180, True, False),
                                    ("창가 자리", "seat", 0.4, 3.8, 1.2, 0.6, 180, True, False), ("앞문", "door", 7.9, 0.6, 0.1, 1.0, 90, False, False),
                                    ("뒷문", "door", 7.9, 5.6, 0.1, 1.0, 90, False, False)]),
    "office": ("사무실", 5.0, 4.0, [("책상", "desk", 1.8, 0.9, 1.6, 0.8, 0, False, False), ("의자", "chair", 2.35, 0.3, 0.5, 0.5, 0, True, False),
                                   ("손님 의자", "chair", 2.35, 2.5, 0.5, 0.5, 180, True, False), ("책장", "other", 0.0, 0.4, 0.4, 2.0, 270, False, False),
                                   ("문", "door", 2.1, 3.9, 0.9, 0.1, 180, False, False)]),
    "car": ("차 안", 1.8, 3.0, [("운전석", "seat", 0.15, 0.9, 0.7, 0.7, 180, True, False), ("조수석", "seat", 0.95, 0.9, 0.7, 0.7, 180, True, False),
                               ("뒷좌석", "seat", 0.15, 2.2, 1.5, 0.7, 180, True, True), ("앞유리", "window", 0.1, 0.0, 1.6, 0.1, 0, False, False)]),
    "carriage": ("마차 안", 1.6, 2.0, [("앞좌석", "seat", 0.1, 0.1, 1.4, 0.55, 0, True, False), ("뒷좌석", "seat", 0.1, 1.35, 1.4, 0.55, 180, True, False),
                                    ("문", "door", 1.5, 0.75, 0.1, 0.5, 90, False, False)]),
    "empty": ("빈 방", 4.0, 3.0, [("문", "door", 1.6, 2.9, 0.8, 0.1, 180, False, False)]),
    # 야외 틀: 벽 · 천장이 없다 (3D 판정은 RoomSpec.open 을 보고 벽 · 천장을 짚지 않는다). 방 테두리는 그린 땅의 끝이다
    # 차 옆: 위(앞)를 보는 큰 차 한 대. 운전석은 차의 왼쪽(평면도 왼쪽). 차체의 앞(rot 90)은 운전석 쪽 옆면이다
    "car_side": ("차 옆", 10.0, 8.0, [("보닛", "vehicle", 3.9, 1.2, 2.2, 0.8, 180, False, False), ("차체", "vehicle", 3.9, 2.0, 2.2, 5.2, 90, False, False),
                                    ("운전석", "seat", 4.0, 2.3, 0.7, 0.7, 180, True, False), ("조수석", "seat", 5.3, 2.3, 0.7, 0.7, 180, True, False),
                                    ("운전석 문", "door", 3.9, 2.05, 0.1, 1.1, 90, False, False), ("운전석 창", "window", 3.9, 2.2, 0.1, 0.8, 90, False, False),
                                    ("조수석 창", "window", 6.0, 2.2, 0.1, 0.8, 270, False, False)]),
    "outdoor": ("야외 빈터", 12.0, 10.0, [("길", "ground", 0.0, 4.2, 12.0, 1.6, 0, False, False), ("큰 나무", "landmark", 2.0, 1.0, 1.2, 1.2, 0, False, False),
                                       ("바위", "landmark", 8.5, 1.5, 1.0, 0.8, 0, True, False), ("표지판", "landmark", 9.5, 7.0, 0.4, 0.2, 180, False, False),
                                       ("모닥불", "landmark", 5.5, 7.5, 0.8, 0.8, 0, False, False)]),
}

# 기준점 종류: id → 화면 이름 (StageAnchor.kind, 화면 방 고치기 static/stage.js 의 kinds 와 같다). 3D 모양 기본값은 stage3d.furniture.KINDS
ANCHOR_KINDS = {"bed": "침대", "door": "문", "window": "창", "desk": "책상", "chair": "의자", "sofa": "소파", "table": "탁자", "wall": "벽",
                "seat": "자리", "vehicle": "차", "landmark": "표지", "ground": "길 · 땅", "other": "기타"}


def make_room(template: str, rid: str, name: str = "", place: str = "") -> StageRoom:
    """틀로 새 방. 모르는 틀은 빈 방."""
    label, w, h, anchors = ROOMS.get(template) or ROOMS["empty"]
    return StageRoom(id=rid, name=name.strip() or label, place=place, template=template if template in ROOMS else "empty", w=w, h=h,
                     anchors=[StageAnchor(id=f"a{i}", name=a[0], kind=a[1], x=a[2], y=a[3], w=a[4], h=a[5], rot=a[6], sit=a[7], lie=a[8])
                              for i, a in enumerate(anchors, 1)])


def vocab() -> dict:
    """화면에 주는 고정 목록."""
    return {
        "rels": RELS, "facings": FACINGS, "hands": HANDS,
        "postures": {k: {"label": v.label, "upright": v.upright} for k, v in POSTURES.items()},
        "parts": {k: {"label": v.label, "side": v.side, "sexual": v.sexual} for k, v in PARTS.items()},
        "acts": {k: {"label": v.label, "hands": v.hands, "sexual": v.sexual, "intimate": v.intimate, "support": v.support} for k, v in ACTS.items()},
        "rooms": {k: v[0] for k, v in ROOMS.items()}, "kinds": ANCHOR_KINDS,
        # 새 장면 방 고르기의 작은 그림: 틀마다 크기와 기준점 상자 [x, y, w, h] (static/stage.js stgThumb)
        "room_shapes": {k: {"w": v[1], "h": v[2], "anchors": [list(a[2:6]) for a in v[3]]} for k, v in ROOMS.items()},
        "rules": rule_names(), "rules3d": sorted(_rules3d()),
    }


# ---------- 막기 ----------

def is_sexual(c: StageContact) -> bool:
    """성적 접촉: 동작이 성적이거나, 성적 부위에 닿는 친밀한 동작."""
    act, part = ACTS.get(c.act), PARTS.get(c.part)
    return bool(act and (act.sexual or (act.intimate and part and part.sexual)))


def minor_ids(p: Project) -> set[str]:
    return {ch.id for ch in p.characters if cast_mod.is_minor_age(ch.age)}


def blocked(c: StageContact, who: str, p: Project, minors: Optional[set[str]] = None) -> bool:
    """미성년 인물이 낀 성적 접촉. 작가 입력 · AI 결과 · 프롬프트 어디에서도 만들지 않는다."""
    m = minor_ids(p) if minors is None else minors
    return is_sexual(c) and (who in m or c.to in m)


# ---------- 상태 겹치기 ----------

@dataclass
class Now:
    """박자 하나가 끝난 뒤 한 인물의 상태. *_at 은 그 칸을 정한 박자 (0 은 시작 상태)."""
    at: Optional[StageSpot] = None
    posture: str = ""
    facing: str = ""
    left: str = UNKNOWN
    right: str = UNKNOWN
    contacts: dict[str, StageContact] = field(default_factory=dict)
    at_at: int = 0
    left_at: int = 0
    right_at: int = 0
    contact_at: dict[str, int] = field(default_factory=dict)


def _apply(now: Now, b: StageBody, k: int) -> None:
    if b.at is not None:
        now.at, now.at_at = b.at, k
    if b.posture:
        now.posture = b.posture
    if b.facing:
        now.facing = b.facing
    if b.left is not None:
        now.left, now.left_at = b.left.strip(), k
    if b.right is not None:
        now.right, now.right_at = b.right.strip(), k
    for cid in b.ends:
        now.contacts.pop(cid, None)
        now.contact_at.pop(cid, None)
    for c in b.contacts:
        now.contacts[c.id] = c
        now.contact_at[c.id] = k


def state_at(scene: StageScene, k: int) -> dict[str, Now]:
    """k 번째 박자까지 겹친 상태 (0 은 시작 상태, 1 은 첫 박자 뒤)."""
    out = {w: Now() for w in scene.cast}
    for b in scene.start:
        _apply(out.setdefault(b.who, Now()), b, 0)
    for i, beat in enumerate(scene.beats[:k], 1):
        for b in beat.bodies:
            _apply(out.setdefault(b.who, Now()), b, i)
    return out


# ---------- 위치 계산 ----------
# static/stage.js 의 stageLayout 과 같은 규칙이라 함께 고친다

# ---------- AI 가 더하자고 한 기준점 (pipeline.draft_stage) ----------
# AI 는 이름 · 종류 · 다른 기준점과의 관계 말만 낸다(DraftAnchor). 좌표는 여기서 정한다: 관계 쪽 바로 곁, 겹치면 옆으로 밀고,
# 기준이 없으면 방 안 빈 자리, 방 밖으로 나가면 방을 넓힌다. 작가가 적용한 뒤 평면도에서 끌어 옮긴다 (2026-10-29 사용자).

# 종류마다 (화면 이름, 폭, 깊이, 앉기, 눕기). 폭은 앞에서 본 가로, 깊이는 앞쪽 방향 길이 (m). 방 틀 값과 비슷하게 둔다.
# 화면 이름만 담은 ANCHOR_KINDS(방 틀 · 화면 종류 목록)와 같은 종류를 모두 가진다
ANCHOR_SIZES = {
    "bed": ("침대", 1.4, 2.0, True, True), "door": ("문", 0.8, 0.1, False, False), "window": ("창", 0.8, 0.1, False, False),
    "desk": ("책상", 1.0, 0.55, False, False), "chair": ("의자", 0.5, 0.5, True, False), "sofa": ("소파", 2.0, 0.9, True, True),
    "table": ("탁자", 1.2, 0.6, False, False), "wall": ("벽", 2.0, 0.1, False, False), "seat": ("자리", 0.7, 0.7, True, False),
    "vehicle": ("차", 2.3, 6.0, False, False), "landmark": ("표지", 1.0, 1.0, False, False), "ground": ("길 · 땅", 2.0, 2.0, False, False),
    "other": ("기타", 0.8, 0.8, False, False),
}
ATTACH = ("door", "window", "wall")  # 기준 기준점에 맞붙여 두는 종류 (창은 운전석 곁에 붙는다)
# 맞붙이지 않는 기준점 사이 틈: 두 기준점의 맞보는 앞자리(각 GAP 0.4 바깥)에 선 두 사람이 겹치지 않게 (0.4 × 2 + 몸 반지름 0.25 × 2 + 0.05).
# 0.9 로 시작했더니 문 앞에 더한 탁자의 앞자리와 문 앞자리가 0.1m 떨어져 3D 몸 겹침이 났다 (mock 시험)
ANCHOR_GAP = 1.35
ROOM_PAD = 0.9    # 더한 기준점 둘레에 남기는 방 여백: 앞자리 GAP 0.4 + 몸 반지름 0.25 + 걸음 0.25. 0.6 이면 짐칸 뒤에 선 발이 벽에 닿았다 (2026-10-29 15화)
ROOM_MAX = 40.0   # 방 한 변 상한 (화면 크기 칸과 같다)
MAX_ADDS = 10     # 한 번에 더하는 기준점 수 상한. 6 이었을 때 차 안 자리 · 창으로 6개를 채워 정비차 · 짐칸이 빠졌다 (2026-10-29 15화)
_ROT_OF = {(0, 1): 0, (-1, 0): 90, (0, -1): 180, (1, 0): 270}


def anchor_kinds() -> dict[str, str]:
    """AI 가 고를 수 있는 기준점 종류: id → 화면 이름. 3D 가구 종류(stage3d.furniture.KINDS)에만 있는 종류도 받는다."""
    out = dict(ANCHOR_KINDS)
    try:
        from .stage3d import furniture  # 순환 import 를 피해 늦게 읽는다
        out.update({k: k for k in furniture.KINDS if k not in out})
    except ImportError:
        pass
    return out


def _hits(a: StageAnchor, others: list[StageAnchor], margin: float) -> bool:
    return any(a.x < b.x + b.w + margin and b.x < a.x + a.w + margin and a.y < b.y + b.h + margin and b.y < a.y + a.h + margin for b in others)


def _zone(a: StageAnchor) -> StageAnchor:
    """기준점과 그 앞자리(사람이 서는 곳, GAP + 몸 반지름)를 덮는 상자. 더한 기준점이 다른 기준점의 앞자리에 떨어지지 않게 본다."""
    fx, fy = _front(a.rot)
    d = GAP + BODY
    return a.model_copy(update={"x": a.x + min(fx, 0) * d, "y": a.y + min(fy, 0) * d, "w": a.w + abs(fx) * d, "h": a.h + abs(fy) * d})


def _clear(c: StageAnchor, others: list[StageAnchor], near: Optional[StageAnchor]) -> bool:
    """c 와 그 앞자리가 다른 기준점 · 앞자리와 겹치지 않는다. 맞붙이는 종류는 near 와 닿아도 된다."""
    for b in others:
        touch = near is not None and b.id == near.id and c.kind in ATTACH
        m = -0.01 if touch else 0.05
        if _hits(c, [b], m) or (not touch and (_hits(_zone(c), [b], 0) or _hits(c, [_zone(b)], 0))):
            return False
    return True


def _moved(a: StageAnchor, dx: float, dy: float) -> StageAnchor:
    return a.model_copy(update={"x": round(a.x + dx, 2), "y": round(a.y + dy, 2)})


def _beside(near: StageAnchor, rel: str, a: StageAnchor, others: list[StageAnchor]) -> tuple[StageAnchor, str]:
    """near 의 rel 쪽 곁에 a 를 놓는다. 앞 · 뒤 · 왼쪽 · 오른쪽은 _anchor_point 와 같은 기준틀이다.
    a 의 앞쪽은 near 를 본다(가구 사이 앞자리에 사람이 선다). 맞붙이는 창 · 문 · 벽은 near 의 반대쪽(바깥)이 앞이다:
    운전석 곁에 붙인 창의 '앞'은 창밖에 선 자리다 (2026-10-29 실제 Gemini 초안이 '운전석 창 앞'을 창밖으로 썼다)."""
    rel = rel if rel in ("front", "back", "left", "right", "beside", "across") else "beside"
    fx, fy = _front(near.rot)
    rx, ry = fy, -fx
    vx, vy = {"front": (fx, fy), "back": (-fx, -fy), "across": (-fx, -fy), "left": (-rx, -ry)}.get(rel, (rx, ry))
    vx, vy = round(vx), round(vy)
    width, depth = a.w, a.h
    w, h = (width, depth) if vx == 0 else (depth, width)
    gap = 0.0 if a.kind in ATTACH else ANCHOR_GAP
    cx = near.x + near.w / 2 + vx * (near.w / 2 + gap + w / 2)
    cy = near.y + near.h / 2 + vy * (near.h / 2 + gap + h / 2)
    rot = _ROT_OF[(vx, vy)] if a.kind in ATTACH else _ROT_OF[(-vx, -vy)]
    base = a.model_copy(update={"x": round(cx - w / 2, 2), "y": round(cy - h / 2, 2), "w": w, "h": h, "rot": rot})
    # 겹치면 관계 쪽과 수직으로 밀고, 그래도 겹치면 더 바깥으로
    for out in (0, 0.5, 1.0, 1.5, 2.0, 3.0):
        for side in (0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5):
            c = _moved(base, vx * out - vy * side, vy * out + vx * side)
            if _clear(c, others, near):
                return c, f"{near.name} {RELS[rel]}"
    return base, f"{near.name} {RELS[rel]}"


CAB = 1.9         # 자리를 품은 차의 앞 운전 칸 길이 (m). 3D 는 이 칸을 비운다 (stage3d.furniture.cab_vehicle)
CAB_SEAT = 1.3    # 차 앞 끝에서 운전 칸 자리 가운데까지 (m): 발 둘 자리 · 계기판을 남긴다


def _axes(v: StageAnchor) -> tuple[tuple[int, int], tuple[int, int], float, float]:
    """차의 (앞 방향, 안에서 앞을 보고 왼쪽, 길이, 폭). 차의 앞(rot)은 긴 쪽이다 (ANCHOR_SIZES 의 깊이)."""
    fx, fy = _front(v.rot)
    f = (round(fx), round(fy))
    return f, (f[1], -f[0]), abs(f[0]) * v.w + abs(f[1]) * v.h, abs(f[1]) * v.w + abs(f[0]) * v.h


def container(a: StageAnchor, anchors: list[StageAnchor]) -> Optional[StageAnchor]:
    """a 의 가운데를 품은 차 (차 안 자리 · 창). 없으면 None."""
    cx, cy = a.x + a.w / 2, a.y + a.h / 2
    return next((v for v in anchors if v.kind == "vehicle" and v.id != a.id
                 and v.x <= cx <= v.x + v.w and v.y <= cy <= v.y + v.h), None)


# ── 붙은 기준점 (docs/stage/specs/09-attach.md) ──
# 자식은 부모 기준 좌표로 저장한다: 부모 가운데에서 부모의 오른쪽 r · 앞 f 쪽으로 잰 x · y(가운데), r · f 쪽 크기 w · h,
# 부모 앞쪽에서 더 돈 rot. 방 벽에 붙은 자식은 벽을 따라간 좌표만 방 기준이고 벽에서 떨어진 좌표는 늘 벽에 맞춘다.
# 좌표를 읽는 곳은 모두 resolve 로 푼 방을 쓴다. 푼 방은 저장하지 않는다.

FACES = {"inside": "안", "top": "위", "front": "앞면", "back": "뒷면", "left": "왼쪽 면", "right": "오른쪽 면"}
WALLS = {"n": "위 벽", "e": "오른쪽 벽", "s": "아래 벽", "w": "왼쪽 벽"}
TOUCH = 0.05  # 옛 방 짐작: 이만큼 안으로 닿으면 붙은 것으로 본다 (m)
FACE_ROT = {"front": 0, "back": 180, "right": 270, "left": 90}  # 그 면 바깥을 보는 자식의 지역 rot
PART_DEPTH = 2.5  # AI 부분 구역의 깊이 상한 (m)


def _frame(rot: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """(앞 f, 오른쪽 r). 오른쪽은 _anchor_point 의 '오른쪽'과 같다(앞에서 바라본 오른쪽 = 안에서 앞을 보고 왼쪽)."""
    fx, fy = _front(rot)
    f = (round(fx), round(fy))
    return f, (f[1], -f[0])


def _extent(w: float, h: float, r: tuple[int, int]) -> tuple[float, float]:
    """세계 가로 · 세로 → (r 쪽, f 쪽) 크기. 거꾸로도 같은 식이다."""
    return (w, h) if r[0] != 0 else (h, w)


def _local_xy(p: StageAnchor, c: StageAnchor) -> tuple[float, float]:
    """붙은 자식의 지역 가운데를 면에 맞춘다. p 는 세계 좌표 부모. 창 · 문 · 벽은 부모 안쪽 테두리, 그 밖은 면 바깥에 맞닿는다."""
    _, r = _frame(p.rot)
    pr, pf = _extent(p.w, p.h, r)

    def clamp(v: float, lim: float) -> float:
        return max(-lim, min(lim, v)) if lim > 0 else 0.0

    inner = c.kind in ATTACH
    x, y = c.x, c.y
    if c.face in ("front", "back"):
        y = (pf / 2 - c.h / 2 if inner else pf / 2 + c.h / 2) * (1 if c.face == "front" else -1)
        x = clamp(x, (pr - c.w) / 2)
    elif c.face in ("left", "right"):
        x = (pr / 2 - c.w / 2 if inner else pr / 2 + c.w / 2) * (1 if c.face == "right" else -1)
        y = clamp(y, (pf - c.h) / 2)
    else:
        x, y = clamp(x, (pr - c.w) / 2), clamp(y, (pf - c.h) / 2)
    return x, y


def _to_world(p: StageAnchor, c: StageAnchor) -> StageAnchor:
    f, r = _frame(p.rot)
    x, y = _local_xy(p, c)
    cx = p.x + p.w / 2 + x * r[0] + y * f[0]
    cy = p.y + p.h / 2 + x * r[1] + y * f[1]
    w, h = _extent(c.w, c.h, r)
    return c.model_copy(update={"x": round(cx - w / 2, 4), "y": round(cy - h / 2, 4), "w": w, "h": h, "rot": (p.rot + c.rot) % 360})


def to_local(p: StageAnchor, c: StageAnchor, face: str) -> StageAnchor:
    """세계 좌표 자식 c 를 세계 좌표 부모 p 의 face 에 붙인 저장 꼴로."""
    f, r = _frame(p.rot)
    dx, dy = c.x + c.w / 2 - (p.x + p.w / 2), c.y + c.h / 2 - (p.y + p.h / 2)
    w, h = _extent(c.w, c.h, r)
    return c.model_copy(update={"parent": p.id, "face": face, "x": round(dx * r[0] + dy * r[1], 3), "y": round(dx * f[0] + dy * f[1], 3),
                                "w": w, "h": h, "rot": (c.rot - p.rot) % 360})


def _wall_world(room: StageRoom, c: StageAnchor) -> StageAnchor:
    x, y = c.x, c.y
    if c.face in ("n", "s"):
        x = min(max(x, 0.0), max(room.w - c.w, 0.0))
        y = 0.0 if c.face == "n" else room.h - c.h
    else:
        y = min(max(y, 0.0), max(room.h - c.h, 0.0))
        x = 0.0 if c.face == "w" else room.w - c.w
    return c.model_copy(update={"x": x, "y": y})


def resolve(room: StageRoom) -> StageRoom:
    """세계 좌표로 푼 사본 (부모부터 차례로). 이미 푼 방은 그대로 돌려준다. parent · face 는 남긴다.
    고리이거나 모르는 부모 · 면이면 그 기준점을 붙지 않은 것으로 읽는다. 저장하지 않는다."""
    if room._world:
        return room
    by = {a.id: a for a in room.anchors}
    out: dict[str, StageAnchor] = {}

    def world(a: StageAnchor, seen: frozenset) -> StageAnchor:
        if a.id in out:
            return out[a.id]
        if a.parent == "room" and a.face in WALLS:
            w = _wall_world(room, a)
        elif a.parent in by and a.parent not in seen and a.face in FACES:
            w = _to_world(world(by[a.parent], seen | {a.parent}), a)
        else:
            w = a.model_copy()
        out[a.id] = w
        return w

    r = room.model_copy(update={"anchors": [world(a, frozenset({a.id})) for a in room.anchors]})
    r._world = True
    return r


def children(room: StageRoom, aid: str) -> list[StageAnchor]:
    """aid 에 붙은 기준점과 그 자식들 (깊이 순)."""
    out, todo = [], [aid]
    while todo:
        cur = todo.pop(0)
        for a in room.anchors:
            if a.parent == cur and a.id != aid and a not in out:
                out.append(a)
                todo.append(a.id)
    return out


def clean_room(room: StageRoom) -> int:
    """저장 전 붙은 곳 정리: 모르는 부모, 자기 자신, 고리, 맞지 않는 면이면 떼어 낸다(좌표는 그대로). 뗀 수."""
    by = {a.id: a for a in room.anchors}
    dropped = 0
    for a in room.anchors:
        ok = (a.parent == "room" and a.face in WALLS) or (a.parent in by and a.parent != a.id and a.face in FACES) or not a.parent
        if ok and a.parent and a.parent != "room":
            seen, cur = {a.id}, by[a.parent]
            while cur.parent in by:
                if cur.id in seen:
                    ok = False
                    break
                seen.add(cur.id)
                cur = by[cur.parent]
        if not ok:
            a.parent, a.face = "", ""
            dropped += 1
        elif not a.parent:
            a.face = ""
    return dropped


def shift_room(room: StageRoom, dx: float, dy: float) -> None:
    """방을 왼쪽 · 위로 dx · dy 넓혔을 때: 뿌리와 벽 자식만 옮긴다. 기준점 자식은 부모 기준이라 그대로다."""
    if not dx and not dy:
        return
    room.anchors = [_moved(a, dx, dy) if a.parent in ("", "room") else a for a in room.anchors]


def _side_of(v: StageAnchor, c: StageAnchor) -> str:
    """세계 좌표 c 가 차 v 의 옆면에 TOUCH 안으로 닿으면 그 면, 아니면 빈칸."""
    f, r = _frame(v.rot)
    pr, pf = _extent(v.w, v.h, r)
    dx, dy = c.x + c.w / 2 - (v.x + v.w / 2), c.y + c.h / 2 - (v.y + v.h / 2)
    x, y = dx * r[0] + dy * r[1], dx * f[0] + dy * f[1]
    cw, ch = _extent(c.w, c.h, r)
    gaps = {"right": pr / 2 - (x + cw / 2), "left": pr / 2 - (cw / 2 - x), "front": pf / 2 - (y + ch / 2), "back": pf / 2 - (ch / 2 - y)}
    face, gap = min(gaps.items(), key=lambda kv: abs(kv[1]))
    return face if abs(gap) <= TOUCH else ""


def _wall_of(room: StageRoom, a: StageAnchor) -> str:
    """방 테두리에 TOUCH 안으로 닿은 벽. 얇은 쪽이 벽과 나란해야 한다 (구석의 창이 엉뚱한 벽에 붙지 않게)."""
    gaps = {"w": a.x, "n": a.y, "e": room.w - a.x - a.w, "s": room.h - a.y - a.h}
    fit = [k for k, g in gaps.items() if abs(g) <= TOUCH and ((k in "ns") == (a.w >= a.h))]
    return min(fit, key=lambda k: abs(gaps[k])) if fit else ""


def attach_guess(room: StageRoom) -> None:
    """옛 방 짐작 (09 '옛 방'): 차 안 가운데면 그 차에 (옆면에 닿은 창 · 문은 그 면, 그 밖은 안),
    창 · 문 · 벽이 방 테두리에 닿으면 그 벽에. 세계 좌표는 바뀌지 않는다. 이미 붙은 기준점은 건드리지 않는다."""
    room.attached = True
    w = resolve(room)
    roots = [a for a in w.anchors if not a.parent]
    out = []
    for a, wa in zip(room.anchors, w.anchors):
        if a.parent:
            out.append(a)
            continue
        v = container(wa, roots) if a.kind != "vehicle" else None
        if v is not None:
            face = _side_of(v, wa) if a.kind in ("window", "door") else ""
            out.append(to_local(v, wa, face or "inside"))
            continue
        edge = _wall_of(room, a) if a.kind in ATTACH else ""
        out.append(a.model_copy(update={"parent": "room", "face": edge}) if edge else a)
    room.anchors = out


def _box(cx: float, cy: float, w: float, h: float, a: StageAnchor, rot: int) -> StageAnchor:
    return a.model_copy(update={"x": round(cx - w / 2, 2), "y": round(cy - h / 2, 2), "w": w, "h": h, "rot": rot})


def _free(c: StageAnchor, others: list[StageAnchor], skip: set[str]) -> bool:
    return not _hits(c, [b for b in others if b.id not in skip], -0.01)


def _in_vehicle(v: StageAnchor, a: StageAnchor, others: list[StageAnchor]) -> Optional[StageAnchor]:
    """차 안 운전 칸에 자리를 놓는다: 앞 끝에서 CAB_SEAT 뒤, 왼쪽(운전석) 먼저 · 오른쪽, 그다음 뒷줄. 앞을 본다. 자리가 없으면 None."""
    f, left, length, width = _axes(v)
    cx, cy = v.x + v.w / 2, v.y + v.h / 2
    side = width / 4
    for row in range(3):
        back = length / 2 - CAB_SEAT - row * 0.9
        if back - a.h / 2 < -length / 2:
            break
        for k in (1, -1):
            px = cx + f[0] * back + left[0] * side * k
            py = cy + f[1] * back + left[1] * side * k
            w, h = (a.w, a.h) if f[0] == 0 else (a.h, a.w)
            c = _box(px, py, w, h, a, _ROT_OF[f])
            if _free(c, others, {v.id}):
                return c
    return None


def _on_vehicle_wall(v: StageAnchor, seat: Optional[StageAnchor], a: StageAnchor, others: list[StageAnchor]) -> Optional[StageAnchor]:
    """차 옆면에 창 · 문을 붙인다. 자리 곁이면 그 자리 높이(앞뒤)에, 자리에 가까운 옆면 먼저 · 맞은편 옆면. 앞(rot)은 차 바깥이다.
    운전석 창 앞에 선 사람은 창밖에 선다 (차 옆 틀 car_side 와 같은 모양)."""
    f, left, length, width = _axes(v)
    cx, cy = v.x + v.w / 2, v.y + v.h / 2
    if seat is not None:
        sx, sy = seat.x + seat.w / 2 - cx, seat.y + seat.h / 2 - cy
        along, lat = sx * f[0] + sy * f[1], sx * left[0] + sy * left[1]
    else:
        along, lat = length / 2 - CAB_SEAT, 1.0
    sides = (1, -1) if lat >= 0 else (-1, 1)
    for shift in (0, -0.9, 0.9, -1.8):
        for k in sides:
            out = (left[0] * k, left[1] * k)
            d = width / 2 - a.h / 2
            px = cx + f[0] * (along + shift) + out[0] * d
            py = cy + f[1] * (along + shift) + out[1] * d
            w, h = (a.w, a.h) if out[0] == 0 else (a.h, a.w)
            c = _box(px, py, w, h, a, _ROT_OF[out])
            if _free(c, others, {v.id} | ({seat.id} if seat else set())):
                return c
    return None


def _empty_spot(room: StageRoom, a: StageAnchor, others: list[StageAnchor]) -> StageAnchor:
    """방 안에서 다른 기준점과 사람 하나 설 틈을 둔 빈 자리 (위 왼쪽부터). 없으면 방 오른쪽 바깥 (방을 넓힌다)."""
    k = 0.25
    for i in range(int(max(room.h - a.h, 0) / k) + 1):
        for j in range(int(max(room.w - a.w, 0) / k) + 1):
            c = a.model_copy(update={"x": round(j * k, 2), "y": round(i * k, 2)})
            if not _hits(c, others, ROOM_PAD) and _clear(c, others, None):
                return c
    return a.model_copy(update={"x": round(room.w + ANCHOR_GAP, 2), "y": 0.0})


def _part_zone(near: StageAnchor, rel: str, a: StageAnchor) -> StageAnchor:
    """AI 부분 구역(짐칸 · 트렁크 · 보닛 앞)의 세계 상자: near 안의 rel 쪽 끝, 폭은 near 를 채우고 깊이는 near 길이의 1/3
    (많아야 PART_DEPTH). 앞쪽은 그 끝의 바깥. rel 이 앞 · 뒤 · 왼쪽 · 오른쪽이 아니면 near 가운데에 종류 크기로."""
    _, r = _frame(near.rot)
    pr, pf = _extent(near.w, near.h, r)
    if rel in ("front", "back"):
        d = min(pf / 3, PART_DEPTH)
        loc = a.model_copy(update={"x": 0.0, "y": (pf - d) / 2 * (1 if rel == "front" else -1), "w": pr, "h": d, "rot": FACE_ROT[rel]})
    elif rel in ("left", "right"):
        d = min(pr / 3, PART_DEPTH)
        loc = a.model_copy(update={"x": (pr - d) / 2 * (1 if rel == "right" else -1), "y": 0.0, "w": d, "h": pf, "rot": FACE_ROT[rel]})
    else:
        loc = a.model_copy(update={"x": 0.0, "y": 0.0, "w": min(a.w, pr), "h": min(a.h, pf), "rot": 0})
    return _to_world(near, loc.model_copy(update={"face": "inside"}))


def _on_face(near: StageAnchor, rel: str, a: StageAnchor) -> tuple[StageAnchor, str]:
    """부분인 창 · 문 · 벽을 near 의 rel 쪽 면 가운데에 (세계 상자, 면). 모르는 쪽은 앞면. 앞쪽은 바깥."""
    face = rel if rel in FACE_ROT else "front"
    long, thin = max(a.w, a.h), min(a.w, a.h)
    w, h = (long, thin) if face in ("front", "back") else (thin, long)
    loc = a.model_copy(update={"x": 0.0, "y": 0.0, "w": w, "h": h, "rot": FACE_ROT[face], "face": face})
    return _to_world(near, loc), face


def place_anchors(room: StageRoom, drafts: list[DraftAnchor]) -> tuple[StageRoom, list[AnchorAdd], float, float]:
    """AI 의 기준점 제안을 방에 놓는다: (더한 방(사본, id 그대로, 저장 꼴), 더한 기준점(저장 꼴), 옛 기준점을 옮긴 dx, dy).
    이미 있는 이름은 건너뛴다. 모르는 종류는 other, 모르는 near 는 빈 자리. 앞에 놓은 제안을 뒤 제안의 near 로 쓸 수 있다.
    자리는 세계 좌표(resolve)로 셈하고, 붙는 기준점은 부모 기준 좌표로 저장한다 (09: part 는 near 의 부분, 차 곁 자리는 차 안).
    더한 기준점 둘레 ROOM_PAD 가 방 밖으로 나가면 방을 넓히고, 왼쪽 · 위로 넓히면 뿌리와 벽 기준점을 그만큼 옮긴다(shift_room)."""
    r = room.model_copy(deep=True)
    r._world = False
    kinds = anchor_kinds()
    adds: list[AnchorAdd] = []
    for d in drafts:
        name = d.name.strip()
        if not name or any(a.name.strip() == name for a in r.anchors):
            continue
        if len(adds) >= MAX_ADDS:
            break
        kind = d.kind.strip() if d.kind.strip() in kinds else "other"
        _, width, depth, sit, lie = ANCHOR_SIZES.get(kind, ANCHOR_SIZES["other"])
        a = StageAnchor(id=_new_id("a", {x.id for x in r.anchors}), name=name, kind=kind, w=width, h=depth, sit=sit, lie=lie)
        world = resolve(r).anchors
        near = next((x for x in world if x.name.strip() == d.near.strip()), None) if d.near.strip() else None
        rel = d.rel.strip()
        # 차에 붙는 자리는 차 안, 차 안 자리 곁의 창 · 문은 차 옆면 (2026-10-29 15화: 운전석 · 창이 캠핑카 밖에 놓였다)
        car = None if near is None else near if near.kind == "vehicle" else container(near, world)
        placed, parent, face, where = None, None, "", ""
        if car is not None and kind == "seat":
            placed, face = _in_vehicle(car, a, world), "inside"
        elif car is not None and kind in ("window", "door"):
            placed = _on_vehicle_wall(car, near if near is not car else None, a, world)
            face = _side_of(car, placed) if placed is not None else ""
        if placed is not None:
            parent, where = car, f"{car.name} {'안' if kind == 'seat' else '옆면'}"
        elif d.part and near is not None:
            # 부분 (2026-10-30 15화: 정비차 짐칸이 트럭 뒤 1.35m 에 따로 떠 있었다)
            parent = near
            if kind in ATTACH:
                placed, face = _on_face(near, rel, a)
                where = f"{near.name} {FACES[face]}"
            else:
                placed, face = _part_zone(near, rel, a), "inside"
                where = f"{near.name} 안" + (f" {RELS[rel]} 끝" if rel in FACE_ROT else "")
        elif near is not None:
            placed, where = _beside(near, rel, a, world)
        else:
            placed, where = _empty_spot(r, a, world), "빈 자리"
        stored = to_local(parent, placed, face or "inside") if parent is not None else placed
        r.anchors.append(stored)
        adds.append(AnchorAdd(anchor=stored, where=where))
    if not adds:
        return r, [], 0.0, 0.0
    ids = {x.anchor.id for x in adds}
    new = [a for a in resolve(r).anchors if a.id in ids]
    x0 = min(0.0, *(a.x - ROOM_PAD for a in new))
    y0 = min(0.0, *(a.y - ROOM_PAD for a in new))
    x1 = max(r.w, *(a.x + a.w + ROOM_PAD for a in new))
    y1 = max(r.h, *(a.y + a.h + ROOM_PAD for a in new))
    dx, dy = round(-x0, 2), round(-y0, 2)
    shift_room(r, dx, dy)
    r.w, r.h = round(min(ROOM_MAX, x1 - x0), 2), round(min(ROOM_MAX, y1 - y0), 2)
    moved = {a.id: a for a in r.anchors if a.id in ids}
    return r, [x.model_copy(update={"anchor": moved[x.anchor.id]}) for x in adds], dx, dy


def grow_room(base: StageRoom, adds: list[AnchorAdd], dx: float, dy: float, w: float, h: float) -> tuple[StageRoom, dict[str, str]]:
    """적용할 때 지금 방(제안 뒤 작가가 고쳤을 수 있다)에 더한다: 뿌리 · 벽 기준점을 dx, dy 옮기고(shift_room), 크기를 넓히고, 기준점을 붙인다.
    더할 id 가 이미 있으면 새 id 로 바꾸고 바꾼 짝을 돌려준다 (장면의 자리 · 향함을 고칠 때 쓴다). 더한 기준점의 부모도 함께 바꾼다."""
    r = base.model_copy(deep=True)
    r._world = False
    shift_room(r, dx, dy)
    r.w, r.h = round(max(r.w + dx, w), 2), round(max(r.h + dy, h), 2)
    remap: dict[str, str] = {}
    added = []
    for x in adds:
        a = x.anchor.model_copy()
        if any(b.id == a.id for b in r.anchors):
            new = _new_id("a", {b.id for b in r.anchors} | {x.anchor.id for x in adds})
            remap[a.id], a.id = new, new
        r.anchors.append(a)
        added.append(a)
    for a in added:
        if a.parent in remap:
            a.parent = remap[a.parent]
    clean_room(r)
    return r, remap


def remap_anchors(scene: StageScene, remap: dict[str, str]) -> None:
    """장면의 기준점 id 를 바꾼다 (자리 ref, 향함 '#id')."""
    if not remap:
        return
    for b in [*scene.start, *(x for beat in scene.beats for x in beat.bodies)]:
        if b.at and b.at.ref in remap:
            b.at.ref = remap[b.at.ref]
        if b.facing.startswith("#") and b.facing[1:] in remap:
            b.facing = "#" + remap[b.facing[1:]]


def room_users(p: Project, rid: str) -> list[tuple[int, StageScene]]:
    """방을 쓰는 장면: (화 번호, 장면)."""
    return [(e.plot.number, s) for e in p.episodes for s in e.stage if s.room == rid]


def room_shared(p: Project, rid: str, n: int, event: int, role: str) -> bool:
    """공용 방인가: 지도 장소에 묶였거나, 이 사건 · 역할의 장면 말고 다른 장면이 쓴다."""
    room = next((r for r in p.rooms if r.id == rid), None)
    if room is None:
        return False
    if room.place.strip():
        return True
    ep = next((e for e in p.episodes if e.plot.number == n), None)
    mine = {id(s) for s in scenes_of(ep, event) if s is not None} if ep else set()  # 같은 사건의 계획 · 본문 장면은 한 무리
    return any(id(s) not in mine for _, s in room_users(p, rid))


GAP = 0.4      # 기준점 바깥으로 떨어지는 거리 (m)
BODY = 0.25    # 몸 반지름 (m)
SPREAD = 0.5   # 같은 자리에 선 사람 사이 간격 (m)
ACROSS = 1.2   # 인물의 맞은편: 마주 보는 거리 (m)
_ROT = {0: (0.0, 1.0), 90: (-1.0, 0.0), 180: (0.0, -1.0), 270: (1.0, 0.0)}


def _front(rot: int) -> tuple[float, float]:
    return _ROT.get(rot % 360, (0.0, 1.0))


def _anchor_point(a: StageAnchor, rel: str) -> tuple[float, float]:
    """기준점 + 관계의 자리. 왼쪽 · 오른쪽은 기준점 앞에서 바라본 쪽이다."""
    cx, cy = a.x + a.w / 2, a.y + a.h / 2
    fx, fy = _front(a.rot)
    rx, ry = fy, -fx

    def out(vx, vy):
        half = (abs(vx) * a.w + abs(vy) * a.h) / 2
        return cx + vx * (half + GAP), cy + vy * (half + GAP)

    if rel == "front":
        return out(fx, fy)
    if rel in ("back", "across"):  # 기준점의 맞은편은 앞의 반대쪽
        return out(-fx, -fy)
    if rel == "against":  # 앞쪽에 몸이 맞닿게 (벽 · 문에 기대어)
        half = (abs(fx) * a.w + abs(fy) * a.h) / 2
        return cx + fx * (half + BODY), cy + fy * (half + BODY)
    if rel == "right":
        return out(rx, ry)
    if rel == "left":
        return out(-rx, -ry)
    if rel == "beside":
        return out(rx, ry)
    return cx, cy  # on · in


def facing_vec(facing: str, me: tuple[float, float], room: StageRoom, pos: dict) -> Optional[tuple[float, float]]:
    """향한 쪽 단위 벡터. 모르면 None."""
    room = resolve(room)
    if facing in _FACING_VEC:
        return _FACING_VEC[facing]
    t = None
    if facing.startswith("@"):
        t = pos.get(facing[1:])
    elif facing.startswith("#"):
        a = next((x for x in room.anchors if x.id == facing[1:]), None)
        t = (a.x + a.w / 2, a.y + a.h / 2) if a else None
    if t is None:
        return None
    dx, dy = t[0] - me[0], t[1] - me[1]
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-6 else None


def place(room: StageRoom, state: dict[str, Now], order: Optional[list[str]] = None,
          prev: Optional[dict[str, tuple[float, float]]] = None) -> dict[str, tuple[float, float]]:
    """인물마다 평면도 좌표 (m). 자리를 모르는 인물은 빠진다. order 는 같은 자리를 펼 때의 순서 (보통 scene.cast).
    prev 는 앞 박자 좌표: 기준 인물이 나를 향하는데 내 자리를 아직 모르면 앞 박자의 내 자리 쪽을 그 인물의 앞으로 친다."""
    names = [w for w in (order or []) if w in state] + [w for w in state if w not in (order or [])]
    room = resolve(room)
    anchors = {a.id: a for a in room.anchors}
    pos: dict[str, tuple[float, float]] = {}
    groups: dict[tuple[str, str], list[str]] = {}
    for w in names:
        at = state[w].at
        if at and at.ref in anchors:
            groups.setdefault((at.ref, at.rel), []).append(w)
    for (ref, rel), ws in groups.items():
        x, y = _anchor_point(anchors[ref], rel)
        fx, fy = _front(anchors[ref].rot)
        for i, w in enumerate(ws):
            # 첫 사람이 가운데, 다음부터 기준점 앞쪽에 수직으로 번갈아 편다
            k = (i + 1) // 2 * (1 if i % 2 else -1)
            pos[w] = (x + fy * SPREAD * k, y - fx * SPREAD * k)
    # 다른 인물 기준 자리: 기준 인물이 정해질 때까지 되풀이, 고리면 고리 첫 인물을 방 가운데에
    rest = [w for w in names if w not in pos and state[w].at and state[w].at.ref.startswith("@")]
    while rest:
        moved = False
        for w in list(rest):
            ref = state[w].at.ref[1:]
            if ref in pos:
                look = {**pos, w: prev[w]} if prev and w in prev else pos
                pos[w] = _person_point(pos[ref], state[ref].facing, state[w].at.rel, room, look, w)
                rest.remove(w)
                moved = True
        if not moved:
            pos[rest.pop(0)] = (room.w / 2, room.h / 2)
    return {w: (min(max(x, BODY), room.w - BODY), min(max(y, BODY), room.h - BODY)) for w, (x, y) in pos.items()}


def layouts(room: StageRoom, scene: StageScene) -> list[dict[str, tuple[float, float]]]:
    """박자마다 좌표 (0 은 시작 상태). 박자마다 앞 박자 좌표를 place 의 prev 로 넘긴다."""
    room = resolve(room)
    out: list[dict[str, tuple[float, float]]] = []
    for k in range(len(scene.beats) + 1):
        out.append(place(room, state_at(scene, k), scene.cast, out[-1] if out else None))
    return out


def _person_point(o: tuple[float, float], facing: str, rel: str, room: StageRoom, pos: dict, me: str = "") -> tuple[float, float]:
    """다른 인물 기준 자리. 앞 · 뒤 · 왼쪽 · 오른쪽은 그 인물이 향한 쪽 기준이다 (모르면 아래를 본다고 친다).
    기준 인물이 나를 향하고 앞 박자의 내 자리를 알면 관계 말과 상관없이 그 쪽에 선다: 그 인물의 앞이 내 쪽이므로 '왼쪽'을 그대로 따르면
    박자마다 90도씩 돌아간다 (2026-10-29 15화 사건 1: 운전석의 최건우를 향한 '최건우 왼쪽'의 이예은이 돌다 벽에 밀려 겹쳤다)."""
    fx, fy = facing_vec(facing, o, room, pos) or (0.0, 1.0)
    rx, ry = -fy, fx  # 그 인물의 오른쪽
    d = BODY * 2 + 0.05
    if rel in ("on", "in"):
        return o[0] + 0.15, o[1]
    if rel == "across":  # 마주 봄 (탁자 하나 건너)
        return o[0] + fx * ACROSS, o[1] + fy * ACROSS
    if rel == "against":  # 몸이 맞닿게
        return o[0] + fx * BODY * 2, o[1] + fy * BODY * 2
    if me and facing == f"@{me}" and me in pos:
        return o[0] + fx * d, o[1] + fy * d
    v = {"front": (fx, fy), "back": (-fx, -fy), "left": (-rx, -ry)}.get(rel, (rx, ry))
    return o[0] + v[0] * d, o[1] + v[1] * d


# ---------- 판정 ----------

REACH_HAND = 1.4   # 손 접촉이 닿는 거리 (m): 팔 약 0.7 + 몸 반지름 둘 + 기준점 자리 틈. 1.2 는 같은 가구 앞 · 옆 두 사람을 짚었다 (03 측정)
REACH_BODY = 0.6   # 손 아닌 부위 접촉
RULES = {"hand_busy": "손", "move_posture": "이동 자세", "reach": "거리", "behind_front": "향함", "handoff": "물건"}


class Violation(BaseModel):
    beat: int           # 어긋난 박자 (1부터)
    cause: int          # 그 상태를 만든 박자 (0 은 시작 상태)
    who: str
    rule: str
    text: str           # 해요체 설명
    contact: str = ""   # 어긋난 접촉 id (reach · behind_front, hand_busy 는 이번 박자에 그 손으로 시작한 접촉). 없으면 빈칸


def _rules3d() -> dict[str, str]:
    from .stage3d.judge import RULES3D  # stage3d 가 stage 를 읽으므로 늦게 읽는다
    return RULES3D


def rule_names() -> dict[str, str]:
    """규칙 id → 화면 이름: 평면 규칙(RULES)과 3D 규칙(stage3d.judge.RULES3D)."""
    return {**RULES, **_rules3d()}


def judge_all(scene: StageScene, room: StageRoom, p: Project) -> list[Violation]:
    """평면 판정에 3D 판정을 더한다 (docs/stage/3d/specs/07-wire.md). 3D 는 자세 · 틀 모듈이 다 등록됐을 때만 돌고
    2D reach 가 짚은 접촉은 다시 짚지 않는다. 박자 순, 같은 박자는 평면 규칙이 먼저."""
    from .stage3d import judge as judge3d
    room = resolve(room)
    flat = judge(scene, room, p)
    return sorted(flat + judge3d.judge_if_ready(scene, room, p, flat=flat), key=lambda v: v.beat)


def _name(p: Project, cid: str) -> str:
    ch = next((c for c in p.characters if c.id == cid), None)
    return ch.name if ch else cid


def _hand_load(now: Now, hand: str) -> list[tuple[str, int]]:
    """그 손이 맡은 것과 맡은 박자: 쥔 물건, 그 손 · 두 손 접촉."""
    out = []
    held, at = (now.left, now.left_at) if hand == "left" else (now.right, now.right_at)
    if held and held != UNKNOWN:
        out.append((held, at))
    for cid, c in now.contacts.items():
        if c.by in (hand, "both"):
            out.append((f"{PARTS[c.part].label if c.part in PARTS else c.part} 접촉", now.contact_at[cid]))
    return out


def _carried(now: dict[str, Now], w: str) -> bool:
    """누군가 선 채로 w 를 받치는 접촉(ACTS 의 support)을 하고 있다."""
    for o, s in now.items():
        if o == w or not POSTURES.get(s.posture, Posture("", False)).upright:
            continue
        if any(c.to == w and ACTS.get(c.act, Act("", 0)).support for c in s.contacts.values()):
            return True
    return False


def judge(scene: StageScene, room: StageRoom, p: Project) -> list[Violation]:
    """박자마다 규칙 다섯 개를 본다. 손 상태가 '?' 이거나 자리 · 향함을 모르면 그 규칙은 짚지 않는다."""
    out: list[Violation] = []
    room = resolve(room)
    prev = state_at(scene, 0)
    spots = layouts(room, scene)
    for k, beat in enumerate(scene.beats, 1):
        now = state_at(scene, k)
        pos = spots[k]
        for b in beat.bodies:
            w, me = b.who, now.get(b.who)
            if me is None:
                continue
            name = _name(p, w)
            # 손: 이번 박자에 손에 새로 맡긴 것이 있는데 그 손이 둘 넘게 맡았다
            for hand in ("left", "right"):
                new = (b.left is not None and hand == "left") or (b.right is not None and hand == "right") \
                    or any(c.by in (hand, "both") for c in b.contacts)
                load = _hand_load(me, hand)
                if new and len(load) > 1:
                    old = [x for x in load if x[1] < k] or load[:1]
                    cid = next((c.id for c in b.contacts if c.by in (hand, "both")), "")
                    out.append(Violation(beat=k, cause=old[0][1], who=w, rule="hand_busy", contact=cid,
                                         text=f"{name} {HANDS[hand]}이 이미 바빠요 (맡은 것: {', '.join(x[0] for x in load)}). 한 손으로 두 곳을 맡을 수 없어요."))
            # 이동 자세: 자리가 바뀌었는데 선 자세가 아니다. 같은 박자에 자세도 바꿨으면 옮긴 다음 그 자세가 된 것으로 본다
            # ("걸어와 앉았다"). 앞 박자 자세 그대로 자리만 바뀌면 짚는다
            was = prev.get(w)
            if b.at is not None and was and was.at is not None and (was.at.ref, was.at.rel) != (b.at.ref, b.at.rel):
                ps = POSTURES.get(me.posture)
                carried = me.posture == "held" and _carried(now, w)
                changed = bool(b.posture) and b.posture not in (was.posture, "held")  # 안기거나 업힘은 받쳐 줄 사람이 있어야 옮긴다
                if ps and not ps.upright and not carried and not changed:
                    out.append(Violation(beat=k, cause=k, who=w, rule="move_posture",
                                         text=f"{name} 자리가 바뀌었는데 자세가 '{ps.label}'예요. 일어서는 박자가 없어요."))
            # 거리 · 향함: 이번 박자에 시작한 접촉
            for c in b.contacts:
                if w not in pos or c.to not in pos:
                    continue
                to_name = _name(p, c.to)
                hand = c.by in HANDS
                d = math.dist(pos[w], pos[c.to])
                limit = REACH_HAND if hand else REACH_BODY
                if d > limit:
                    out.append(Violation(beat=k, cause=max(me.at_at, now[c.to].at_at), who=w, rule="reach", contact=c.id,
                                         text=f"{name} → {to_name}: {d:.1f}m 떨어져 있어 닿지 않아요 ({'손' if hand else '몸'} 접촉은 {limit:g}m 안)."))
                    continue
                part = PARTS.get(c.part)
                tv = facing_vec(now[c.to].facing, pos[c.to], room, pos)
                if hand and part and part.side == "front" and tv and d > 1e-6:
                    ux, uy = pos[w][0] - pos[c.to][0], pos[w][1] - pos[c.to][1]
                    if tv[0] * ux + tv[1] * uy < 0:
                        out.append(Violation(beat=k, cause=k, who=w, rule="behind_front", contact=c.id,
                                             text=f"{name} → {to_name}: 등 뒤에 있는데 몸 앞쪽({part.label})에 닿아요."))
            # 물건: 한 손에 쥔 물건을 놓지 않고 다른 손으로 다시 쥔다
            for hand, other in (("left", "right"), ("right", "left")):
                got = b.left if hand == "left" else b.right
                if not got or got.strip() in ("", UNKNOWN):
                    continue
                kept = me.right if other == "right" else me.left
                if kept == got.strip():
                    cause = me.right_at if other == "right" else me.left_at
                    out.append(Violation(beat=k, cause=cause, who=w, rule="handoff",
                                         text=f"{name}: {HANDS[other]}에 쥔 물건({kept})을 놓지 않고 {HANDS[hand]}으로 다시 쥐어요."))
        prev = now
    return out


# ---------- 작가 입력 정리 · 사건 찾기 · 본문과 잇기 ----------

def clean_scene(scene: StageScene, room: Optional[StageRoom], p: Project) -> int:
    """장면을 그 자리에서 정리하고 막은 접촉 수를 돌려준다.
    목록 밖 자세 · 향함 · 관계는 메모로 옮기고, 모르는 부위 · 동작 접촉과 막는 접촉은 뺀다. 접촉 id 는 장면 안에서 겹치지 않게 다시 단다."""
    minors = minor_ids(p)
    anchors = {a.id for a in room.anchors} if room else set()
    known = set(scene.cast)
    dropped, seen = 0, set()
    for b in [*scene.start, *(x for beat in scene.beats for x in beat.bodies)]:
        if b.who not in known:
            scene.cast.append(b.who)
            known.add(b.who)
        extra = []
        if b.posture and b.posture not in POSTURES:
            extra.append(f"자세: {b.posture}")
            b.posture = ""
        if b.facing and not (b.facing in FACINGS or b.facing[:1] in "@#"):
            extra.append(f"향함: {b.facing}")
            b.facing = ""
        if b.at is not None and (b.at.rel not in RELS or not (b.at.ref in anchors or b.at.ref.startswith("@"))):
            extra.append(f"자리: {b.at.ref} {b.at.rel}")
            b.at = None
        keep = []
        for c in b.contacts:
            if c.part not in PARTS or c.act not in ACTS or not (c.by in HANDS or c.by in PARTS):
                extra.append(f"접촉: {c.by} → {c.to} {c.part} {c.act}")
                continue
            if blocked(c, b.who, p, minors):
                dropped += 1
                continue
            if not c.id or c.id in seen:
                n = 1
                while f"c{n}" in seen:
                    n += 1
                c.id = f"c{n}"
            seen.add(c.id)
            keep.append(c)
        b.contacts = keep
        if extra:
            b.memo = " · ".join(x for x in [b.memo.strip(), *extra] if x)
    return dropped


def find_event(ep: Episode, scene: StageScene) -> tuple[Optional[int], bool]:
    """장면이 가리키는 플롯 사건 번호와 '사건이 바뀌었나'. 같은 글이 있으면 그 번호, 없으면 저장한 번호."""
    events = ep.plot.events
    t = scene.event_text.strip()
    if t:
        for i, e in enumerate(events):
            if e.strip() == t:
                return i, False
    if 0 <= scene.event < len(events):
        return scene.event, bool(t)
    return None, True


_SPACE = re.compile(r"\s+")


def stale(scene: StageScene, text: str) -> list[int]:
    """인용이 본문에 없는 박자 번호 (1부터). 띄어쓰기 차이는 무시한다. 본문이 없으면 (쓰기 전 연출) 빈 목록."""
    flat = _SPACE.sub("", text or "")
    if not flat:
        return []
    return [k for k, beat in enumerate(scene.beats, 1) if beat.quote.strip() and _SPACE.sub("", beat.quote) not in flat]


# ---------- 계획과 견주기 ----------
# 계획의 박자 끝 상태가 본문 장면의 어느 박자에서 처음 이뤄지는지 차례로 찾는다 (docs/stage/model.md '견주기').
# 견주는 칸: 자리(기준점만, 관계 차이는 무시), 자세(선 자세인지만), 접촉(누가 · 누구에게 · 부위 쌍, 손은 왼손 · 오른손 · 두 손을 하나로).
# 향함 · 손에 쥔 것은 견주지 않는다. 본문 장면에서 모르는 칸(자리 · 자세가 없음)은 이뤄졌다고 본다 (짚지 않는다).

GAP_FIELDS = {"at": "자리", "posture": "자세", "contact": "접촉"}


class Gap(BaseModel):
    plan_beat: int      # 계획 박자 (0 은 시작 상태)
    text_beat: int      # 견준 본문 박자 (0 은 시작 상태)
    who: str
    field: str          # at · posture · contact
    plan: str           # 계획 값 (화면 글)
    actual: str         # 본문 값 (화면 글). 없으면 빈칸
    text: str           # 해요체 설명
    contact: str = ""   # 계획 접촉 id (field 가 contact 일 때)


def _bodies(scene: StageScene, k: int) -> list[StageBody]:
    return scene.start if k == 0 else scene.beats[k - 1].bodies


def _spot_word(at: Optional[StageSpot], room: Optional[StageRoom], p: Optional[Project]) -> str:
    if at is None:
        return ""
    rel = RELS.get(at.rel, at.rel)
    if at.ref.startswith("@"):
        return f"{_name(p, at.ref[1:]) if p else at.ref[1:]} {rel}"
    a = next((x for x in room.anchors if x.id == at.ref), None) if room else None
    return f"{a.name if a else at.ref} {rel}"


def _by_kind(by: str) -> str:
    return "hand" if by in HANDS else by


def _contact_word(who: str, c: StageContact, p: Optional[Project]) -> str:
    by = HANDS.get(c.by) or (PARTS[c.by].label if c.by in PARTS else c.by)
    part = PARTS[c.part].label if c.part in PARTS else c.part
    nm = (lambda x: _name(p, x)) if p else (lambda x: x)
    return f"{nm(who)} {by} → {nm(c.to)} {part}"


def _done(fact: tuple, now: dict[str, Now]) -> bool:
    kind, who = fact[0], fact[1]
    me = now.get(who)
    if kind == "at":
        return me is None or me.at is None or me.at.ref == fact[2]
    if kind == "posture":
        ps = POSTURES.get(me.posture) if me else None
        return ps is None or ps.upright == fact[2]
    _, _, to, by, part = fact
    return bool(me) and any(c.to == to and c.part == part and _by_kind(c.by) == by for c in me.contacts.values())


def align(plan: StageScene, text: StageScene, room: Optional[StageRoom] = None, p: Optional[Project] = None,
          text_room: Optional[StageRoom] = None) -> tuple[list[int], list[Gap]]:
    """계획 박자마다 견준 본문 박자(시작 상태 포함, 줄지 않음)와 계획과 다른 곳. 화면의 겹쳐 보기가 앞 목록을 쓴다.
    계획 박자 k 에서 적은 칸마다 지금 본문 박자부터 처음 이뤄지는 박자를 찾고, 다음 계획 박자는 그중 가장 늦은 박자부터 찾는다."""
    text_room = text_room or room
    states = [state_at(text, j) for j in range(len(text.beats) + 1)]
    cast = set(text.cast) | {b.who for j in range(len(text.beats) + 1) for b in _bodies(text, j)}
    match: list[int] = []
    gaps: list[Gap] = []
    j = 0
    for k in range(len(plan.beats) + 1):
        facts: list[tuple[tuple, StageBody, Optional[StageContact]]] = []
        for b in _bodies(plan, k):
            if b.who not in cast:
                continue
            if b.at is not None:
                facts.append((("at", b.who, b.at.ref), b, None))
            if b.posture in POSTURES:
                facts.append((("posture", b.who, POSTURES[b.posture].upright), b, None))
            for c in b.contacts:
                facts.append((("contact", b.who, c.to, _by_kind(c.by), c.part), b, c))
        found, missed = [], []
        for f in facts:
            hit = next((x for x in range(j, len(states)) if _done(f[0], states[x])), None)
            if hit is None:
                missed.append(f)
            else:
                found.append(hit)
        j = max(found, default=j)
        # 화면 짝: 하나도 이뤄지지 않은 계획 박자는 다음 본문 박자에 견준다 (찾기는 j 에서 그대로 잇는다)
        shown = j if found or not facts else min(j + 1, len(text.beats))
        match.append(max([shown, *match[-1:]]))
        for fact, b, c in missed:
            kind, who = fact[0], fact[1]
            # 본문이 계획 대신 한 것: 이 박자 뒤에 그 인물의 그 칸을 처음 바꾼 본문 박자, 없으면 지금 박자
            at = next((x for x in range(j + 1, len(states)) if kind != "contact"
                       and any(t.who == who and (t.at is not None if kind == "at" else bool(t.posture)) for t in _bodies(text, x))), j)
            me = states[at].get(who)
            name = _name(p, who) if p else who
            if kind == "at":
                pv, tv = _spot_word(b.at, room, p), _spot_word(me.at if me else None, text_room, p)
            elif kind == "posture":
                pv, tv = POSTURES[b.posture].label, POSTURES[me.posture].label if me and me.posture in POSTURES else ""
            else:
                pv, tv = _contact_word(who, c, p), ""
            if kind == "contact":
                desc = f"계획의 접촉({pv})이 본문에 없어요."
            else:
                desc = f"{name} {GAP_FIELDS[kind]}가 계획과 달라요 (계획: {pv}, 본문: {tv or '모름'})."
            gaps.append(Gap(plan_beat=k, text_beat=at, who=who, field=kind, plan=pv, actual=tv, text=desc, contact=c.id if c else ""))
    return match, gaps


def diff(plan: StageScene, text: StageScene, room: Optional[StageRoom] = None, p: Optional[Project] = None,
         text_room: Optional[StageRoom] = None) -> list[Gap]:
    """계획 장면과 본문 장면이 다른 곳. 박자 수가 달라도 박자 끝 상태가 차례대로 이뤄지면 빈 목록."""
    return align(plan, text, room, p, text_room)[1]


def _event_of(ep: Episode, scene: StageScene) -> Optional[int]:
    return find_event(ep, scene)[0]


def scenes_of(ep: Episode, event: int) -> tuple[Optional[StageScene], Optional[StageScene]]:
    """사건 하나의 (계획 장면, 본문 장면). 없으면 None."""
    found = {"plan": None, "text": None}
    for s in ep.stage:
        if found[s.role] is None and _event_of(ep, s) == event:
            found[s.role] = s
    return found["plan"], found["text"]


# ---------- AI 결과 정리 (pipeline.draft_stage · extract_stage) ----------
# AI 는 이름으로 적는다. 모르는 인물은 박자 설명에, 모르는 기준점 · 향함은 그 칸 메모에 남긴다. 그 뒤 clean_scene 이 어휘 밖과 막는 접촉을 거른다.

MAX_BEATS = 40   # 장면 하나의 박자 수 상한
EMPTY_HAND = "빈손"


def _names(p: Project) -> dict[str, str]:
    """이름(또는 id) → 인물 id. 같은 이름이면 앞 인물."""
    out: dict[str, str] = {}
    for c in p.characters:
        out.setdefault(c.name.strip(), c.id)
        out.setdefault(c.id, c.id)
    return out


HELD_MAX = 30  # 손에 쥔 것 글자 상한 (모델이 같은 낱말을 되풀이해 늘어놓는 일이 있다)


def _hand(v: str, start: bool, role: str) -> Optional[str]:
    v = (v or "").strip()
    if len(v) > HELD_MAX:
        v = v.split(",")[0].strip()[:HELD_MAX]
    if v in ("", "-"):
        return (UNKNOWN if role == "text" else "") if start else None
    return "" if v in (EMPTY_HAND, "없음", "빈 손") else v


def from_draft(d: StageDraft, p: Project, ep: Episode, event: int, room: StageRoom, role: str = "plan",
               sid: str = "") -> tuple[StageScene, int, list[str]]:
    """AI 장면을 저장 모양으로: (장면, 막은 접촉 수, 정리 기록). 박자는 MAX_BEATS 까지.
    시작 상태에 적지 않은 손은 계획이면 빈손, 본문이면 '?'(본문이 말하기 전까지 모름)다."""
    who_of = _names(p)
    anchors = {a.name.strip(): a.id for a in room.anchors}
    notes: list[str] = []
    cast: list[str] = []
    for nm in d.cast:
        cid = who_of.get(nm.strip())
        if cid and cid not in cast:
            cast.append(cid)
        elif not cid and nm.strip():
            notes.append(f"모르는 인물: {nm.strip()}")
    active: dict[str, list[StageContact]] = {}
    room_kinds = {a.id: a.kind for a in room.anchors}

    def body(x: DraftBody, start: bool) -> tuple[Optional[StageBody], str]:
        cid = who_of.get(x.name.strip())
        if not cid:
            return None, x.name.strip()
        if cid not in cast:
            cast.append(cid)
        memo = [x.memo.strip()] if x.memo.strip() else []
        at = None
        ref = x.at_ref.strip()
        if ref:
            target = anchors.get(ref) or (f"@{who_of[ref]}" if ref in who_of and who_of[ref] != cid else None)
            if target:
                rel = x.at_rel.strip() or "beside"
                # 창 · 문 · 벽 '위' · '안'에는 설 수 없다: 그 앞으로 읽는다 (2026-10-29 15화: '운전석 창 바깥 위'에 선 몸이 차 옆면에 걸렸다)
                if rel in ("on", "in") and room_kinds.get(target) in ATTACH:
                    rel = "front"
                at = StageSpot(ref=target, rel=rel)
            else:
                memo.append(f"자리: {ref} {RELS.get(x.at_rel, x.at_rel)}".strip())
        facing = x.facing.strip()
        if facing and facing not in FACINGS:
            if facing in who_of and who_of[facing] != cid:
                facing = f"@{who_of[facing]}"
            elif facing in anchors:
                facing = f"#{anchors[facing]}"
            else:
                memo.append(f"향함: {facing}")
                facing = ""
        contacts = []
        for c in x.contacts:
            to = who_of.get(c.to.strip())
            if not to or to == cid:
                memo.append(f"접촉: {c.to} {c.part} {c.act}")
                continue
            contacts.append(StageContact(id="", by=c.by.strip(), to=to, part=c.part.strip(), act=c.act.strip()))
        b = StageBody(who=cid, at=at, posture=x.posture.strip(), facing=facing, left=_hand(x.left, start, role),
                      right=_hand(x.right, start, role), contacts=contacts, memo=" · ".join(memo))
        return b, ""

    scene = StageScene(id=sid or "s0", event=event, event_text=ep.plot.events[event] if 0 <= event < len(ep.plot.events) else "",
                       room=room.id, role=role, source="text" if role == "text" else "plot")
    seen_start = set()
    for x in d.start:
        b, unknown = body(x, True)
        if b is None:
            notes.append(f"모르는 인물: {unknown}")
            continue
        if b.who in seen_start:
            continue
        seen_start.add(b.who)
        scene.start.append(b)
    for w in cast:  # 시작 상태에 없는 인물도 모든 칸을 갖게 (손은 위 규칙)
        if w not in seen_start:
            scene.start.append(StageBody(who=w, left=_hand("", True, role), right=_hand("", True, role)))
    # 접촉 id 를 먼저 달아야 ends 가 가리킬 수 있다
    counter = [0]

    def tag(c: StageContact) -> None:
        counter[0] += 1
        c.id = f"c{counter[0]}"

    for b in scene.start:
        for c in b.contacts:
            tag(c)
            active.setdefault(b.who, []).append(c)
    for beat in d.beats[:MAX_BEATS]:
        bodies = []
        lost = []
        for x in beat.bodies:
            b, unknown = body(x, False)
            if b is None:
                lost.append(unknown)
                continue
            ended = []
            for e in x.ends:
                to = who_of.get(e.to.strip())
                hit = next((c for c in reversed(active.get(b.who, [])) if c.to == to and c.part == e.part.strip()), None)
                if hit:
                    ended.append(hit.id)
                    active[b.who].remove(hit)
            b.ends = ended
            for c in b.contacts:
                tag(c)
                active.setdefault(b.who, []).append(c)
            bodies.append(b)
        note = beat.note.strip()
        if lost:
            note = " · ".join(x for x in [note, f"모르는 인물: {', '.join(dict.fromkeys(lost))}"] if x)
            notes.append(f"모르는 인물: {', '.join(dict.fromkeys(lost))}")
        scene.beats.append(StageBeat(quote=beat.quote.strip(), note=note, bodies=bodies))
    if len(d.beats) > MAX_BEATS:
        notes.append(f"박자 {len(d.beats) - MAX_BEATS}개는 {MAX_BEATS}개를 넘어 뺐어요")
    scene.cast = cast
    dropped = clean_scene(scene, room, p)
    if dropped:
        notes.append(f"미성년 인물이 낀 성적 접촉 {dropped}개를 뺐어요")
    return scene, dropped, list(dict.fromkeys(notes))


def end_lines(scene: StageScene, room: Optional[StageRoom], p: Project) -> list[str]:
    """장면이 끝난 상태를 인물마다 한 줄 (다음 장면 프롬프트의 실마리). 모르는 칸은 적지 않는다."""
    out = []
    for w, me in state_at(scene, len(scene.beats)).items():
        bits = []
        if me.at is not None:
            bits.append(_spot_word(me.at, room, p))
        if me.posture in POSTURES:
            bits.append(POSTURES[me.posture].label)
        for hand, held in (("left", me.left), ("right", me.right)):
            if held != UNKNOWN:
                bits.append(f"{HANDS[hand]} {held or '빈손'}")
        bits += [f"접촉 {_contact_word(w, c, p)}" for c in me.contacts.values()]
        if bits:
            out.append(f"- {_name(p, w)}: {', '.join(bits)}")
    return out


# ---------- 검수 지적 (pipeline.apply_check) ----------
# 본문 장면의 규칙 판정(judge_all: 평면 + 3D)과 계획과 다른 곳(diff)을 '동선 · 사소 · 규칙' 지적으로. 인용이 지금 본문에 있는 박자만 짚는다
# (쓰기 전 연출의 판정은 장면 연출 화면에만 보인다). 한 문장의 여러 어긋남은 지적 하나로 합친다.

def to_issues(scene: StageScene, room: Optional[StageRoom], p: Project, n: int, text: str, event: int,
              plan: Optional[StageScene] = None, plan_room: Optional[StageRoom] = None) -> list[ConsistencyIssue]:
    flat = _SPACE.sub("", text or "")

    def quote(k: int) -> str:
        if not 1 <= k <= len(scene.beats):
            return ""
        q = scene.beats[k - 1].quote.strip()
        return q if q and _SPACE.sub("", q) in flat else ""

    rows: dict[str, dict] = {}  # 인용 → {beat, source, texts}
    names = rule_names()
    for v in (judge_all(scene, room, p) if room else []):
        q = quote(v.beat)
        if q:
            r = rows.setdefault(q, {"beat": v.beat, "source": quote(v.cause) if v.cause != v.beat else "", "texts": []})
            r["texts"].append(f"{names[v.rule]}: {v.text}")
    if plan is not None:
        for g in diff(plan, scene, plan_room, p, room):
            q = quote(g.text_beat)
            if q:
                rows.setdefault(q, {"beat": g.text_beat, "source": "", "texts": []})["texts"].append(f"계획과 다름: {g.text}")
    out = []
    for q, r in rows.items():
        texts = list(dict.fromkeys(r["texts"]))
        out.append(ConsistencyIssue(type="동선", description=" / ".join(texts), source_episode=n, source_quote=r["source"],
                                    current_quote=q, suggestion="어긋난 낱말만 고치거나, 본문 연출이 낫다면 그대로 두세요.",
                                    severity="low", origin="rule", stage_event=event, stage_beat=r["beat"]))
    return out


def episode_issues(p: Project, ep: Episode) -> list[ConsistencyIssue]:
    """화 하나의 규칙 지적: 사건마다 본문 장면이 있으면 판정하고, 계획 장면이 있으면 견준다. 본문이 없으면 빈 목록."""
    if not ep.text:
        return []
    out: list[ConsistencyIssue] = []
    for i in range(len(ep.plot.events)):
        plan, text = scenes_of(ep, i)
        if text is None:
            continue
        for x in to_issues(text, room_of(p, text), p, ep.plot.number, ep.text, i, plan, room_of(p, plan) if plan else None):
            if not any(x.current_quote == y.current_quote for y in out):  # 두 사건이 같은 문장을 뽑았으면 앞 사건 것만
                out.append(x)
    return out


# ---------- 화면 (web.py 의 …/stage) ----------

def _new_id(prefix: str, taken: set[str]) -> str:
    k = 1
    while f"{prefix}{k}" in taken:
        k += 1
    return f"{prefix}{k}"


def new_room(p: Project, template: str, name: str = "", place: str = "") -> StageRoom:
    """틀로 방을 만들어 Project.rooms 에 더한다."""
    room = make_room(template, _new_id("r", {r.id for r in p.rooms}), name, place)
    p.rooms.append(room)
    return room


ROLES = {"plan": "계획", "text": "본문"}


def board_scene_of(ep: Episode, event: int) -> Optional[tuple[int, BoardScene]]:
    """사건(0부터)을 맡은 스토리보드 장면: (장면 번호(1부터), 장면). 스토리보드가 없거나 맡은 장면이 없으면 None.
    BoardScene.events 는 1부터라 event + 1 로 찾는다. 두 장면이 같은 사건을 맡으면 앞 장면이다."""
    b = ep.storyboard
    if b is None:
        return None
    return next(((k, sc) for k, sc in enumerate(b.scenes, 1) if event + 1 in sc.events), None)


def room_hints(p: Project, scene: BoardScene) -> list[str]:
    """스토리보드 장면에 맞는 방 id, 잘 맞는 것부터. 이름이 자리(spot)와 같은 방 → 자리와 서로 포함하는 방 → 묶인 지도 장소가
    장면 장소(place)와 같은 방 → 이름이 장소와 같거나 서로 포함하는 방. 띄어쓰기 · 가운뎃점은 무시한다 (naming.place_key).
    맞는 방이 없으면 빈 목록. 화면은 이 방들을 방 목록 앞에 둔다."""
    def near(a: str, b: str) -> bool:
        a, b = place_key(a), place_key(b)
        return bool(a and b) and (a in b or b in a)

    spot, where = scene.spot.strip(), scene.place.strip()
    scored = []
    for i, r in enumerate(p.rooms):
        score = 4 if spot and place_key(r.name) == place_key(spot) else 3 if near(r.name, spot) else 2 if where and place_key(r.place) == place_key(where) else 1 if near(r.name, where) else 0
        if score:
            scored.append((-score, i, r.id))
    return [rid for _, _, rid in sorted(scored)]


def new_scene(p: Project, ep: Episode, event: int, room: StageRoom, role: str = "plan") -> StageScene:
    """플롯 사건 하나의 새 장면. 출연진은 그 사건을 맡은 스토리보드 장면의 present(알려진 인물만), 없으면 그 화 플롯의
    등장 인물이고, 모두 문 앞(문이 없으면 방 가운데)에 빈손으로 선다. 한 사건에 계획 · 본문 장면은 하나씩이다."""
    events = ep.plot.events
    if not 0 <= event < len(events):
        raise ValueError(f"{ep.plot.number}화에 {event + 1}번째 사건이 없어요")
    if role not in ROLES:
        raise ValueError(f"장면 역할을 모르겠어요: {role}")
    if scenes_of(ep, event)[role == "text"] is not None:
        raise ValueError(f"이 사건에는 이미 {ROLES[role]} 장면이 있어요")
    known = {c.id for c in p.characters}
    hit = board_scene_of(ep, event)
    cast_ids = [c for c in dict.fromkeys(hit[1].present) if c in known] if hit else []
    cast_ids = cast_ids or [c for c in ep.plot.characters if c in known]
    door = next((a for a in room.anchors if a.kind == "door"), None)
    start = [StageBody(who=c, at=StageSpot(ref=door.id, rel="front") if door else None, posture="stand", left="", right="")
             for c in cast_ids]
    scene = StageScene(id=_new_id("s", {s.id for s in ep.stage}), event=event, event_text=events[event], room=room.id,
                       cast=cast_ids, start=start, role=role, source="text" if role == "text" else "manual")
    ep.stage.append(scene)
    return scene


def save_scene(p: Project, ep: Episode, scene: StageScene, room: Optional[StageRoom]) -> int:
    """작가가 고친 장면과 방을 저장한다. 같은 id 는 바꾸고 없으면 더한다. 막은 접촉 수를 돌려준다.
    같은 사건 · 같은 역할의 다른 장면이 있으면 막는다 (본문 장면이 계획을 덮지 않게)."""
    ev = _event_of(ep, scene)
    if any(s.id != scene.id and s.role == scene.role and _event_of(ep, s) == ev for s in ep.stage):
        raise ValueError(f"이 사건에는 이미 {ROLES[scene.role]} 장면이 있어요")
    if room is not None:
        clean_room(room)
        i = next((k for k, r in enumerate(p.rooms) if r.id == room.id), None)
        if i is None:
            p.rooms.append(room)
        else:
            p.rooms[i] = room
        scene.room = room.id
    dropped = clean_scene(scene, room or room_of(p, scene), p)
    i = next((k for k, s in enumerate(ep.stage) if s.id == scene.id), None)
    if i is None:
        ep.stage.append(scene)
    else:
        old = ep.stage[i]
        scene.prev = old.prev  # 적용 취소 한 번은 AI 적용만 남긴다
        scene.room_prev, scene.room_made = old.room_prev, old.room_made
        scene.basis = old.basis
        if scene.role == "text" and _content(scene) != _content(old):
            scene.source = "manual"  # 작가가 손본 본문 장면: 검수 때 뽑기가 덮지 않는다 (pipeline.stage_extract_all)
        ep.stage[i] = scene
    return dropped


def _content(s: StageScene) -> dict:
    return s.model_dump(include={"room", "cast", "start", "beats"})


def remove_scene(ep: Episode, sid: str) -> None:
    ep.stage = [s for s in ep.stage if s.id != sid]


def room_of(p: Project, scene: StageScene) -> Optional[StageRoom]:
    return next((r for r in p.rooms if r.id == scene.room), None)


# ---------- 빠진 이동 (계획 장면 안내) ----------
# AI 초안이 '정비차로 걸어가 짐칸을 뒤진다'고 적고 자리(at)는 옮기지 않는 일이 있다 (2026-10-29 15화 실측).
# 판정 규칙이 아니라 비교 화면 · 계획 장면의 안내라 검수 지적(to_issues)으로 가지 않는다.
# 본문 장면은 본문이 말하지 않은 자리를 비워 두므로 보지 않는다

RETURN_WORDS = ("돌아오", "돌아온", "돌아와", "돌아간", "돌아가", "되돌아")


def _call_names(p: Project, cid: str) -> list[str]:
    """박자 설명에서 인물을 찾는 이름: 온 이름, 띄어쓰기 없는 세 글자 이상 이름이면 성을 뗀 이름도 ('이예은' → '예은')."""
    n = _name(p, cid).strip()
    return [n, n[1:]] if len(n) >= 3 and " " not in n else [n] if n else []


def _stray(s: Now, later: Now, k: int, names: dict[str, str]) -> str:
    """k 박자에 기준점 쪽을 보고 걷는데 그 박자에도 다음 박자에도 자리를 바꾸지 않았으면 그 기준점 id, 아니면 빈칸."""
    ref = s.facing[1:] if s.facing.startswith("#") else ""
    if s.posture == "walk" and ref in names and s.at_at != k and later.at_at != k + 1 and (s.at is None or s.at.ref != ref):
        return ref
    return ""


def fill_arrivals(scene: StageScene, room: Optional[StageRoom], p: Project) -> list[str]:
    """AI 계획 초안이 빠뜨린 도착 자리를 채운다 (2026-10-29 사용자): 기준점 쪽으로 걷고 자리를 바꾸지 않았으면
    다음 박자(마지막 박자면 그 박자)에 그 기준점 앞을 넣는다. 채운 곳은 정리 기록으로 돌려준다. 작가가 짠 장면에는 쓰지 않는다."""
    if scene.role != "plan" or room is None:
        return []
    names = {a.id: a.name for a in room.anchors}
    notes = []
    for k in range(1, len(scene.beats) + 1):
        now = state_at(scene, k)
        nxt = state_at(scene, k + 1) if k < len(scene.beats) else now
        for w, s in now.items():
            ref = _stray(s, nxt.get(w, s), k, names)
            if not ref:
                continue
            j = min(k + 1, len(scene.beats))
            beat = scene.beats[j - 1]
            b = next((x for x in beat.bodies if x.who == w), None)
            if b is None:
                b = StageBody(who=w)
                beat.bodies.append(b)
            b.at = StageSpot(ref=ref, rel="front")
            who = _name(p, w)
            notes.append(f"{j}박자: {who}{josa(who, '이', '가')} '{names[ref]}' 쪽으로 걸어가 도착 자리를 '{names[ref]} 앞'으로 채웠어요")
    return notes


def move_gaps(scene: StageScene, room: Optional[StageRoom], p: Project) -> list[dict]:
    """계획 장면에서 박자 설명과 자리가 어긋난 이동: [{beat, who, kind, text}].
    walk: 기준점 쪽을 보고 걷는데 그 박자에도 다음 박자에도 자리를 바꾸지 않았다 (인물 · 기준점마다 한 번).
    back: 박자 설명이 그 인물이 기준점으로 돌아온다는데 앞 박자에도 이미 그 자리였다."""
    if scene.role != "plan" or room is None:
        return []
    names = {a.id: a.name for a in room.anchors}
    out, seen = [], set()
    prev = state_at(scene, 0)
    for k, beat in enumerate(scene.beats, 1):
        now = state_at(scene, k)
        nxt = state_at(scene, k + 1) if k < len(scene.beats) else now
        for w, s in now.items():
            who = _name(p, w)
            ref = _stray(s, nxt.get(w, s), k, names)
            if ref and (w, ref) not in seen:
                seen.add((w, ref))
                spot = _spot_text(s.at, room, p) or "처음 자리"
                out.append({"beat": k, "who": w, "kind": "walk",
                            "text": f"{who}{josa(who, '이', '가')} '{names[ref]}' 쪽으로 걷는데 다음 박자까지 자리가 '{spot}' 그대로예요"})
            at, before = s.at, prev.get(w)
            if (at is not None and at.ref in names and names[at.ref] in beat.note and any(x in beat.note for x in RETURN_WORDS)
                    and any(x in beat.note for x in _call_names(p, w)) and before is not None and before.at is not None
                    and before.at.ref == at.ref):
                out.append({"beat": k, "who": w, "kind": "back",
                            "text": f"{who}{josa(who, '이', '가')} '{names[at.ref]}' 쪽으로 돌아온다는데 앞 박자에서 그 자리를 떠난 적이 없어요"})
        prev = now
    return out


def _paths(scene: StageScene, room: Optional[StageRoom]) -> list[dict]:
    if room is None:
        return []
    from . import stagepath  # stagepath 가 stage3d 를 읽으므로 늦게 읽는다
    return stagepath.paths(scene, room)


def check(p: Project, ep: Episode, scene: StageScene, room: Optional[StageRoom]) -> dict:
    """장면 하나의 화면 값: 사건 찾기, 본문과 다른 박자, 규칙 판정(평면 + 3D, judge_all), 계획 장면의 빠진 이동(moves),
    박자 사이 돌아가는 이동(paths, stagepath.paths), 짝 장면(같은 사건의 다른 역할)과 견준 값.
    gaps 는 계획과 다른 곳(짝이 있을 때만), match 는 계획 박자마다 견준 본문 박자다."""
    event, changed = find_event(ep, scene)
    out = {"event": event, "event_changed": changed, "stale": stale(scene, ep.text),
           "violations": [v.model_dump() for v in judge_all(scene, room, p)] if room else [], "moves": move_gaps(scene, room, p),
           "paths": _paths(scene, room), "pair": None, "gaps": [], "match": []}
    if event is None:
        return out
    pair = scenes_of(ep, event)[scene.role == "plan"]
    if pair is None or pair.id == scene.id:
        return out
    plan, text = (scene, pair) if scene.role == "plan" else (pair, scene)
    plan_room, text_room = (room, room_of(p, pair)) if scene.role == "plan" else (room_of(p, pair), room)
    match, gaps = align(plan, text, plan_room, p, text_room)
    out.update(pair=pair.id, gaps=[g.model_dump() for g in gaps], match=match)
    return out


def board_view(p: Project, n: int) -> dict:
    """화면의 스토리보드 값: 사건마다 맡은 장면(번호 · 장소 · 자리 · 방 후보 hints, 맡은 장면이 없으면 None)과 낡음.
    스토리보드가 없으면 events 가 빈 목록이다."""
    ep = p.episode(n)
    events = []
    if ep.storyboard is not None:
        for k in range(len(ep.plot.events)):
            hit = board_scene_of(ep, k)
            events.append({"no": hit[0], "place": hit[1].place.strip(), "spot": hit[1].spot.strip(),
                           "hints": room_hints(p, hit[1])} if hit else None)
    return {"stale": board_mod.stale(p, n), "events": events}


def view(p: Project, n: int) -> dict:
    """장면 연출 화면 값 (GET …/stage/{n})."""
    ep = p.episode(n)
    return {
        "episode": n,
        "events": ep.plot.events,
        "board": board_view(p, n),
        "scenes": [{"scene": s.model_dump(), **check(p, ep, s, room_of(p, s))} for s in ep.stage],
        "rooms": [r.model_dump() for r in p.rooms],
        "minors": sorted(minor_ids(p)),
        "vocab": vocab(),
    }


# ---------- 쓰기 프롬프트 줄 ----------
# 인물 이름과 기준점 이름만 쓴다. 좌표와 방 기준 8방향은 쓰지 않는다 (평면도 밖에서는 뜻이 없다).
# 박자 줄은 짧게 쓴다: 본문을 동작 묘사로 끌고 가지 않는다. 글로 바꾸고 예산에 맞추는 것은 prompts.stage_block 이다


def _verb(act: str) -> str:
    """'잡다' → '잡기'."""
    label = ACTS[act].label if act in ACTS else act
    return label[:-1] + "기" if label.endswith("다") else label


def _anchor_name(room: Optional[StageRoom], aid: str) -> str:
    return next((a.name for a in (room.anchors if room else []) if a.id == aid), "")


def _spot_text(spot: Optional[StageSpot], room: Optional[StageRoom], p: Project) -> str:
    if spot is None:
        return ""
    base = _name(p, spot.ref[1:]) if spot.ref.startswith("@") else _anchor_name(room, spot.ref)
    return f"{base} {RELS.get(spot.rel, '')}".strip() if base else ""


def _where(spot: Optional[StageSpot], posture: str, room: Optional[StageRoom], p: Project) -> str:
    pose = POSTURES[posture].label if posture in POSTURES else ""
    return " ".join(x for x in [_spot_text(spot, room, p), pose] if x)


def _facing_text(facing: str, room: Optional[StageRoom], p: Project) -> str:
    if facing.startswith("@"):
        return f"{_name(p, facing[1:])} 쪽을 봄"
    name = _anchor_name(room, facing[1:]) if facing.startswith("#") else ""
    return f"{name} 쪽을 봄" if name else ""


def _contact_text(c: StageContact, p: Project) -> str:
    """'왼손 → 도윤 오른 손목(잡기)': 동작 낱말은 괄호 하나로만."""
    by = HANDS.get(c.by) or (PARTS[c.by].label if c.by in PARTS else c.by)
    part = PARTS[c.part].label if c.part in PARTS else c.part
    return f"{by} → {_name(p, c.to)} {part}({_verb(c.act)})"


def _body_text(b: StageBody, before: Optional[Now], room: Optional[StageRoom], p: Project,
               keep: list[StageContact], shown: set[str]) -> str:
    """배경 제약 한 인물 몫. 시작 상태(before 없음)는 모든 칸, 박자는 바뀐 칸만. 빈손 · 모르는 손은 적지 않는다.
    끝난 접촉은 시작을 글에 적은 것만 알린다."""
    bits = []
    if before is None or b.at is not None or b.posture:
        bits.append(_where(b.at, b.posture, room, p))
    bits.append(_facing_text(b.facing, room, p))
    for word, held in (("왼손", b.left), ("오른손", b.right)):
        if held and held.strip() and held.strip() != UNKNOWN:
            bits.append(f"{word}에 {held.strip()}")
    bits += [_contact_text(c, p) for c in keep]
    for cid in (b.ends if before else []):
        c = before.contacts.get(cid)
        if c and cid in shown:
            bits.append(f"{_name(p, c.to)} {PARTS[c.part].label if c.part in PARTS else c.part}에서 뗌")
    bits.append(b.memo.strip())
    return ", ".join(x for x in bits if x)


def episode_lines(p: Project, ep: Episode, board: bool = False) -> tuple[list[list[str]], int, int]:
    """쓰기 프롬프트에 넣을 장면 글: 장면마다 줄 목록(첫 줄은 사건 · 방 · 기준점 머리), 사건 순서.
    두 층이다(docs/stage/specs/05-prompt.md): 박자 설명(StageBeat.note)은 '지시'로 그대로, 자리 · 자세 · 향함 · 손 · 접촉은
    '배치'(배경 제약)로 짧게. 계획 장면만 넣는다: prompt 가 거짓인 장면, 본문 장면(role text, 일감 07), 사건을 찾지 못한 장면은 뺀다.
    미성년이 낀 성적 접촉(blocked)은 어느 작품에서도 빼고, 전연령 작품(Meta.adult 거짓)은 성적 접촉도 뺀다.
    그런 접촉을 뺀 박자는 지시도 뺀다(설명이 그 접촉을 말할 수 있다).
    board 이면 머리 앞에 그 사건을 맡은 스토리보드 장면 번호('스토리보드 장면 2 · ')를 붙인다 (맡은 장면이 없으면 붙이지 않음).
    (장면 글, 미성년이라 뺀 접촉 수, 수위로 뺀 박자 수)를 낸다. 수위로 뺀 박자 수는 화면이 작가에게 알린다 (시작 상태도 박자 하나로 센다)."""
    minors, adult = minor_ids(p), p.meta.adult
    plans = [s for s in ep.stage if s.prompt and getattr(s, "role", "plan") != "text"]
    found = sorted(((k, s) for s in plans for k in [find_event(ep, s)[0]] if k is not None), key=lambda x: x[0])
    out, dropped, filtered = [], 0, 0
    for k, scene in found:
        room = next((r for r in p.rooms if r.id == scene.room), None)
        shown: set[str] = set()

        def body(b: StageBody, before: Optional[Now]) -> tuple[str, bool, bool]:
            """(글, 수위로 뺐나, 미성년이라 뺐나)"""
            nonlocal dropped
            keep, cut, block = [], False, False
            for c in b.contacts:
                if blocked(c, b.who, p, minors):
                    dropped += 1
                    block = True
                elif not adult and is_sexual(c):
                    cut = True
                else:
                    keep.append(c)
            shown.update(c.id for c in keep)
            return _body_text(b, before, room, p, keep, shown), cut, block

        head = f"사건 {k + 1}: {ep.plot.events[k].strip()}"
        hit = board_scene_of(ep, k) if board else None
        if hit:
            head = f"스토리보드 장면 {hit[0]} · {head}"
        if room:
            head += f" · {room.name}" + (f" ({', '.join(a.name for a in room.anchors)})" if room.anchors else "")
        lines, parts, beat_cut = [head], [], False
        for b in scene.start:
            text, cut, _ = body(b, None)
            beat_cut = beat_cut or cut
            if text:
                parts.append(f"{_name(p, b.who)} {text}")
        filtered += beat_cut
        if parts:
            lines.append("- 처음 배치: " + " / ".join(parts))
        for i, beat in enumerate(scene.beats, 1):
            before, parts, beat_cut, beat_block = state_at(scene, i - 1), [], False, False
            for b in beat.bodies:
                text, cut, block = body(b, before.get(b.who, Now()))
                beat_cut, beat_block = beat_cut or cut, beat_block or block
                if text:
                    parts.append(f"{_name(p, b.who)} {text}")
            filtered += beat_cut
            note = "" if beat_cut or beat_block else beat.note.strip()
            row = " | ".join(x for x in [f"지시: {note}" if note else "", "배치: " + " / ".join(parts) if parts else ""] if x)
            if row:
                lines.append(f"{i}. {row}")
        if len(lines) > 1:
            out.append(lines)
    return out, dropped, filtered
