"""장면 연출 3D: 마네킹 뼈대 계약. 관절 계산(FK), 손 IK, 부위 점, 몸 캡슐, 겹침 깊이, 박자마다 관절 좌표(frames).

설계는 docs/stage/3d/specs/01-body.md. 첫 값과 계산은 docs/stage/mockup-3d.html 을 옮겼다.
바깥 좌표: 평면도 x(오른쪽) · y(아래쪽)에 높이 z(위). 단위 m. 바닥은 z = 0.
안쪽 계산은 시안(three.js)과 같은 좌표(X = x, Y = 높이, Z = y)로 하고, 내보낼 때만 바꾼다.
몸 좌표: +x 왼쪽, +y 위, +z 앞. 팔다리 마디는 -y 로 뻗는다.
모든 인물이 같은 마네킹(키 약 1.72m)이다. 난수 없음, LLM 호출 없음.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import stage
from ..schema import StageContact, StageRoom, StageScene
from . import furniture
from .furniture import RoomSpec, Solid

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]
D = math.pi / 180

# ---------- 벡터 · 회전 ----------


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    return mul(a, 1 / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def dist(a: Vec, b: Vec) -> float:
    return norm(sub(a, b))


def mmul(a: Mat, b: Mat) -> Mat:
    (b0, b1, b2) = b
    return tuple((r[0] * b0[0] + r[1] * b1[0] + r[2] * b2[0], r[0] * b0[1] + r[1] * b1[1] + r[2] * b2[1],
                  r[0] * b0[2] + r[1] * b1[2] + r[2] * b2[2]) for r in a)  # type: ignore[return-value]


def mvec(a: Mat, v: Vec) -> Vec:
    return (dot(a[0], v), dot(a[1], v), dot(a[2], v))


def tr(a: Mat) -> Mat:
    return ((a[0][0], a[1][0], a[2][0]), (a[0][1], a[1][1], a[2][1]), (a[0][2], a[1][2], a[2][2]))


I3: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def rx(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def ry(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def rz(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def euler_xyz(x: float, y: float, z: float) -> Mat:
    """three.js Euler 'XYZ' 와 같은 행렬."""
    return mmul(mmul(rx(x), ry(y)), rz(z))


def euler_yxz(x: float, y: float, z: float) -> Mat:
    return mmul(mmul(ry(y), rx(x)), rz(z))


def axis_angle(axis: Vec, ang: float) -> Mat:
    x, y, z = unit(axis)
    c, s, t = math.cos(ang), math.sin(ang), 1 - math.cos(ang)
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def turn(a: Vec, b: Vec) -> Mat:
    """단위 벡터 a 를 b 로 보내는 가장 작은 회전 (three.js setFromUnitVectors)."""
    c = dot(a, b)
    if c < -1 + 1e-9:
        side = cross(a, (1.0, 0.0, 0.0))
        return axis_angle(side if norm(side) > 1e-6 else cross(a, (0.0, 0.0, 1.0)), math.pi)
    v = cross(a, b)
    k = 1 / (1 + c)
    vx = ((0.0, -v[2], v[1]), (v[2], 0.0, -v[0]), (-v[1], v[0], 0.0))
    vx2 = mmul(vx, vx)
    return tuple(tuple(I3[i][j] + vx[i][j] + vx2[i][j] * k for j in range(3)) for i in range(3))  # type: ignore[return-value]


def _io(v: Vec) -> Vec:
    """바깥 좌표(x, y, 높이) ↔ 안쪽 좌표(x, 높이, y). 자기 자신이 역이다."""
    return (v[0], v[2], v[1])


def _clamp(v: float, a: float) -> float:
    return max(-a, min(a, v))


# ---------- 마디 · 각도 · 자세 계약 ----------

@dataclass(frozen=True)
class Lengths:
    thigh: float = 0.44
    shin: float = 0.46
    torso: float = 0.50     # 골반 → 어깨선
    neck: float = 0.08
    head: float = 0.11      # 머리 반지름
    uarm: float = 0.30
    farm: float = 0.27
    hand: float = 0.08
    shoulder: float = 0.19  # 어깨 반폭
    hipw: float = 0.10      # 엉덩이 반폭
    foot: float = 0.22


L = Lengths()
ARM = L.uarm + L.farm + L.hand
HEIGHT = 0.92 + L.torso + L.neck + 2 * L.head  # 선 자세 머리 꼭대기 1.72m
Pair = tuple[float, float]  # (왼, 오른)


@dataclass(frozen=True)
class Angles:
    """관절 각도 (도, 굽힘이 +). 시안 자세 표와 같은 칸."""
    pelvis_h: float = 0.92   # 바닥 또는 앉는 면에서 골반까지 m
    pitch: float = 0         # 몸 전체 앞(+) 뒤(-) 기울기
    roll: float = 0          # 옆으로 눕기: +는 오른쪽이 아래
    spine: float = 0         # 허리 앞굽힘
    shoulder: Pair = (0, 0)  # 어깨 앞올림
    abduct: Pair = (0, 0)    # 팔 벌림
    elbow: Pair = (0, 0)
    hip: Pair = (0, 0)       # 엉덩관절 앞올림
    knee: Pair = (0, 0)
    leg_abduct: Pair = (0, 0)
    hip_rot: Pair = (0, 0)   # 넓적다리 돌림(넓적다리 축 둘레): +는 바깥돌림, 무릎을 굽히면 발이 몸 가운데로 (양반다리)
    ankle: Pair = (0, 0)     # 발목: +는 발끝을 편다(발바닥 쪽), -는 발등 쪽으로 젖힌다
    shift: float = 0         # 향한 쪽으로 옮김 m (의자에 앉기 -0.13: 엉덩이를 등받이 쪽으로)


ANGLE_FIELDS = ("pitch", "roll", "spine", "shoulder", "abduct", "elbow", "hip", "knee", "leg_abduct", "hip_rot", "ankle")


@dataclass(frozen=True)
class Reach:
    lean: float = 30   # 손이 모자랄 때 허리를 더 숙일 수 있는 최대 (도)
    twist: float = 45  # 몸통을 비틀 수 있는 최대 (도)


SURFACES = ("floor", "seat", "lie", "top", "back_support", "carrier")


@dataclass(frozen=True)
class Placement:
    """특수 배치 결과. yaw 는 몸 앞 방향(평면 (sin yaw, cos yaw)), base 는 그 자세가 놓인 바닥 높이 m.
    angles 를 주면 자세 표 대신 그 각도로 몸을 만든다 (옆으로 눕기의 roll ±90 처럼 자리에 따라 바뀌는 각)."""
    x: float
    y: float
    yaw: float
    base: float = 0.0
    attach: Optional[str] = None  # 매단 인물 id (업힘 · 안겨 들림)
    angles: Optional["Angles"] = None


@dataclass
class PlaceCtx:
    """place_hook 이 받는 것. bodies 는 이미 놓인 다른 인물 (특수 배치 없는 인물이 먼저 놓인다)."""
    who: str
    now: stage.Now
    state: dict[str, stage.Now]
    pos: dict[str, tuple[float, float]]   # stage.place 의 평면 좌표
    xy: tuple[float, float]               # 이 인물의 평면 좌표
    yaw: float                            # 향함으로 정한 방향
    base: float                           # 공통 배치의 바닥 높이
    room: StageRoom
    spec: Optional[RoomSpec]
    solids: list[Solid]
    bodies: dict[str, "Body"]


@dataclass(frozen=True)
class PostureSpec:
    id: str                    # stage.POSTURES 의 키 = 파일 이름
    angles: Angles
    surface: tuple[str, ...]   # 놓일 수 있는 면 (SURFACES)
    reach: Reach = Reach()
    feet_to_floor: bool = False  # 앉는 면이 0.45m 와 다르면 무릎 · 엉덩 · 발목을 고쳐 발을 바닥에 댄다
    place_hook: Optional[Callable[[PlaceCtx], Placement]] = None
    head: tuple[float, float] = (70, 35)  # 고개 돌림 한도 (좌우, 위아래 도). 엎드리기는 위아래 0


# ---------- 부위 점 · 캡슐 ----------
# 부위 점 자리: [뼈, x, y, z]. 뼈는 head · torso · body(골반) · ua(위팔) · fa(아래팔) · th(넓적다리) · sh(정강이) · ft(발, 발목이 원점).
# 쌍(_l · _r)은 왼쪽 값을 적고 오른쪽은 x 를 뒤집는다 (+x 가 몸 바깥, inner_thigh 만 안쪽)

PART3D = {
    "head": ("head", 0, 0.06, 0), "hair": ("head", 0, 0.1, -0.05), "forehead": ("head", 0, 0.05, 0.09), "lips": ("head", 0, -0.05, 0.1),
    "chin": ("head", 0, -0.1, 0.06), "neck": ("torso", 0, 0.53, 0.05), "nape": ("torso", 0, 0.53, -0.05), "chest": ("torso", 0, 0.34, 0.11),
    "belly": ("torso", 0, 0.12, 0.11), "back": ("torso", 0, 0.32, -0.1), "waist": ("torso", 0, 0.05, 0.1), "buttocks": ("body", 0, -0.06, -0.11),
    "groin": ("body", 0, -0.1, 0.08),
    "eye": ("head", 0.04, 0.02, 0.1), "cheek": ("head", 0.08, -0.01, 0.07), "ear": ("head", 0.11, 0, 0), "shoulder": ("torso", 0.19, 0.48, 0),
    "upper_arm": ("ua", 0, -0.15, 0), "elbow": ("fa", 0, 0, 0), "forearm": ("fa", 0, -0.13, 0), "wrist": ("fa", 0, -0.27, 0),
    "hand": ("fa", 0, -0.32, 0), "fingers": ("fa", 0, -0.35, 0), "flank": ("torso", 0.15, 0.15, 0), "thigh": ("th", 0, -0.2, 0.06),
    "inner_thigh": ("th", -0.05, -0.22, 0), "knee": ("sh", 0, 0, 0.05), "calf": ("sh", 0, -0.15, -0.05), "ankle": ("sh", 0, -0.42, 0),
    "foot": ("ft", 0, -0.01, 0.1),
}


def _split(pid: str) -> tuple[str, str]:
    """부위 id → (기본 이름, 쪽 'l' · 'r' · '')."""
    if pid[-2:] in ("_l", "_r") and pid[:-2] in PART3D:
        return pid[:-2], pid[-1]
    return pid, ""


PART_POINTS = {pid: PART3D[_split(pid)[0]] for pid in stage.PARTS}

# 캡슐 이름: 마디마다 하나
SEGMENTS = ("head", "torso", "pelvis", "upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r",
            "thigh_l", "thigh_r", "shin_l", "shin_r", "foot_l", "foot_r")
_SEG_OF = {"head": "head", "hair": "head", "forehead": "head", "lips": "head", "chin": "head", "eye": "head", "cheek": "head", "ear": "head",
           "neck": "torso", "nape": "torso", "chest": "torso", "belly": "torso", "back": "torso", "waist": "torso", "flank": "torso",
           "shoulder": "torso", "buttocks": "pelvis", "groin": "pelvis", "upper_arm": "upper_arm", "elbow": "forearm", "forearm": "forearm",
           "wrist": "forearm", "hand": "forearm", "fingers": "forearm", "thigh": "thigh", "inner_thigh": "thigh", "knee": "shin",
           "calf": "shin", "ankle": "shin", "foot": "foot"}


def _segment(pid: str) -> str:
    base, side = _split(pid)
    seg = _SEG_OF[base]
    return f"{seg}_{side}" if side and seg not in ("head", "torso", "pelvis") else seg


PART_SEGMENT = {pid: _segment(pid) for pid in stage.PARTS}  # 접촉 부위 → 판정이 겹침에서 뺄 캡슐

JOINTS = ("pelvis", "neck", "head", "shoulder_l", "elbow_l", "wrist_l", "hand_l", "hip_l", "knee_l", "ankle_l", "toe_l",
          "shoulder_r", "elbow_r", "wrist_r", "hand_r", "hip_r", "knee_r", "ankle_r", "toe_r")


@dataclass(frozen=True)
class Capsule:
    """몸 부피 하나: 선분 a–b 에서 r 안. 머리는 a == b (구)."""
    segment: str
    a: Vec
    b: Vec
    r: float


# ---------- 몸 ----------

class Body:
    """한 인물의 놓인 마네킹. pose() 로 만들고 reach_to · look_at 이 팔 · 몸통 · 고개를 바꾼다."""

    def __init__(self, angles: Angles, x: float, y: float, yaw: float = 0.0, base: float = 0.0, reach: Reach = Reach(),
                 head: tuple[float, float] = (70, 35)):
        self.angles, self.x, self.y, self.yaw, self.base, self.reach, self.head = angles, x, y, yaw, base, reach, head
        self.spine = angles.spine * D
        self.twist = 0.0
        self.knee = list(angles.knee)
        self.hip = list(angles.hip)
        self.ankle = list(angles.ankle)
        self.ua: dict[str, Mat] = {}
        self.fa: dict[str, Mat] = {}
        for i, s, sx in ((0, "l", 1), (1, "r", -1)):
            self.ua[s] = euler_xyz(-angles.shoulder[i] * D, 0, sx * angles.abduct[i] * D)
            self.fa[s] = rx(-angles.elbow[i] * D)
        self.head_rot: Mat = I3
        self._t: Optional[dict[str, tuple[Mat, Vec]]] = None

    @property
    def upright(self) -> bool:
        return not self.angles.pitch and not self.angles.roll

    @property
    def lean(self) -> float:
        """자세 표보다 더 숙인 각 (도)."""
        return (self.spine / D) - self.angles.spine

    def _changed(self) -> None:
        self._t = None

    def _solve(self) -> dict[str, tuple[Mat, Vec]]:
        if self._t is not None:
            return self._t
        a = self.angles
        r0 = ry(self.yaw)
        t0 = (self.x + math.sin(self.yaw) * a.shift, 0.0, self.y + math.cos(self.yaw) * a.shift)
        rb = mmul(r0, euler_xyz(a.pitch * D, 0, a.roll * D))
        tb = add(t0, (0.0, self.base + a.pelvis_h, 0.0))
        rt = mmul(rb, euler_xyz(self.spine, self.twist, 0))
        out = {"body": (rb, tb), "torso": (rt, tb),
               "head": (mmul(rt, self.head_rot), add(tb, mvec(rt, (0.0, L.torso + L.neck + L.head, 0.0))))}
        for i, s, sx in ((0, "l", 1), (1, "r", -1)):
            rua = mmul(rt, self.ua[s])
            tua = add(tb, mvec(rt, (sx * L.shoulder, L.torso - 0.04, 0.0)))
            rfa = mmul(rua, self.fa[s])
            out["ua_" + s] = (rua, tua)
            out["fa_" + s] = (rfa, add(tua, mvec(rua, (0.0, -L.uarm, 0.0))))
            rth = mmul(mmul(rb, euler_xyz(-self.hip[i] * D, 0, sx * a.leg_abduct[i] * D)), ry(sx * a.hip_rot[i] * D))
            tth = add(tb, mvec(rb, (sx * L.hipw, -0.02, 0.0)))
            rsh = mmul(rth, rx(self.knee[i] * D))
            tsh = add(tth, mvec(rth, (0.0, -L.thigh, 0.0)))
            out["th_" + s] = (rth, tth)
            out["sh_" + s] = (rsh, tsh)
            out["ft_" + s] = (mmul(rsh, rx(self.ankle[i] * D)), add(tsh, mvec(rsh, (0.0, -L.shin, 0.0))))
        self._t = out
        return out

    def _at(self, bone: str, local: Vec) -> Vec:
        """뼈 좌표의 점 → 안쪽 세계 좌표."""
        r, t = self._solve()[bone]
        return add(t, mvec(r, local))

    def _joints(self) -> dict[str, Vec]:
        t = self._solve()
        out = {"pelvis": t["body"][1], "neck": self._at("torso", (0.0, L.torso, 0.0)), "head": t["head"][1]}
        for s in ("l", "r"):
            out["shoulder_" + s] = t["ua_" + s][1]
            out["elbow_" + s] = t["fa_" + s][1]
            out["wrist_" + s] = self._at("fa_" + s, (0.0, -L.farm, 0.0))
            out["hand_" + s] = self._at("fa_" + s, (0.0, -(L.farm + L.hand), 0.0))
            out["hip_" + s] = t["th_" + s][1]
            out["knee_" + s] = t["sh_" + s][1]
            out["ankle_" + s] = self._at("sh_" + s, (0.0, -L.shin, 0.0))
            out["toe_" + s] = self._at("ft_" + s, (0.0, 0.0, 0.17))
        return out

    def joints(self) -> dict[str, Vec]:
        """관절 이름(JOINTS) → 바깥 좌표."""
        j = self._joints()
        return {k: _io(j[k]) for k in JOINTS}

    def head_top(self) -> float:
        """머리 꼭대기 높이 m."""
        return self._solve()["head"][1][1] + L.head

    def _part(self, pid: str) -> Vec:
        base, side = _split(pid)
        bone, x, y, z = PART3D[base]
        sx = -1 if side == "r" else 1
        name = bone + "_" + (side or "l") if bone in ("ua", "fa", "th", "sh", "ft") else bone
        return self._at(name, (x * sx, y, z))

    def part_point(self, pid: str) -> Vec:
        """부위 점 (stage.PARTS id) → 바깥 좌표."""
        return _io(self._part(pid))

    def left(self) -> Vec:
        """몸 왼쪽 단위 벡터 (바깥 좌표, 수평)."""
        return _io(mvec(ry(self.yaw), (1.0, 0.0, 0.0)))

    def capsules(self) -> list[Capsule]:
        def seg(name: str, bone: str, p: Vec, q: Vec, r: float) -> Capsule:
            return Capsule(name, _io(self._at(bone, p)), _io(self._at(bone, q)), r)

        out = [seg("head", "head", (0, 0, 0), (0, 0, 0), L.head),
               seg("torso", "torso", (0, 0.13, 0), (0, L.torso - 0.13, 0), 0.13),
               seg("pelvis", "body", (-0.06, 0, 0), (0.06, 0, 0), 0.10)]
        for s in ("l", "r"):
            out += [seg("upper_arm_" + s, "ua_" + s, (0, -0.045, 0), (0, -(L.uarm - 0.045), 0), 0.045),
                    seg("forearm_" + s, "fa_" + s, (0, -0.04, 0), (0, -(L.farm + L.hand - 0.04), 0), 0.04),
                    seg("thigh_" + s, "th_" + s, (0, -0.065, 0), (0, -(L.thigh - 0.065), 0), 0.065),
                    seg("shin_" + s, "sh_" + s, (0, -0.05, 0), (0, -(L.shin - 0.05), 0), 0.05),
                    seg("foot_" + s, "ft_" + s, (0, 0.04, -0.01), (0, 0.04, 0.13), 0.04)]
        order = {n: i for i, n in enumerate(SEGMENTS)}
        return sorted(out, key=lambda c: order[c.segment])


def pose(spec: "PostureSpec | Angles", x: float, y: float, yaw: float = 0.0, base: float = 0.0) -> Body:
    """FK: 자세(또는 각도)를 평면 자리 (x, y) · 방향 yaw · 바닥 높이 base 에 놓는다."""
    if isinstance(spec, PostureSpec):
        return Body(spec.angles, x, y, yaw, base, spec.reach, spec.head)
    return Body(spec, x, y, yaw, base)


def part_point(body: Body, pid: str) -> Vec:
    return body.part_point(pid)


def capsules(body: Body) -> list[Capsule]:
    return body.capsules()


def feet_down(body: Body) -> None:
    """무릎 각을 고쳐 발목을 바닥(z = 0)에 가장 가깝게. 무릎만으로 모자라면(침대처럼 높은 면) 엉덩 굽힘을 FEET_HIP 까지 줄여
    넓적다리를 앞으로 기울인다. 그다음 발목 각으로 발을 바닥과 나란히 두고, 그래도 뜨면 발끝을 펴서 바닥 쪽으로 늘어뜨린다."""
    for i, s in ((0, "l"), (1, "r")):
        def height(k: float) -> float:
            body.knee[i] = k
            body._changed()
            return abs(body._at("sh_" + s, (0.0, -L.shin, 0.0))[1])

        def knee_best() -> float:
            best = min(range(0, 171), key=lambda k: (height(k), k))
            fine = min((best + d / 10 for d in range(-10, 11)), key=lambda k: (height(k), k))
            return height(max(0.0, fine))

        hip0 = body.hip[i]
        for dh in range(0, FEET_HIP + 1):
            body.hip[i] = hip0 - dh
            if knee_best() <= FEET_OK:
                break

        def toe(an: float) -> tuple[float, float]:
            body.ankle[i] = an
            body._changed()
            j = body._joints()
            return j["toe_" + s][1], j["ankle_" + s][1]

        flat = min(range(-40, 41), key=lambda an: abs(float.__sub__(*toe(an))))
        t, a = toe(flat)
        if a > FEET_OK:  # 발이 바닥에 닿지 않는다: 발끝이 바닥에 닿거나 다 펼 때까지 편다
            toe(next((an for an in range(flat, 61) if toe(an)[0] <= 0.005), 60))


FEET_HIP = 30   # 발을 바닥에 대려고 엉덩 굽힘을 줄이는 한도 (도)
FEET_OK = 0.02  # 발목이 바닥에서 이만큼 안이면 닿았다고 본다 (m)


# ---------- 손 IK ----------

DEFAULT_POLE: Vec = (0.6, -1.0, -0.4)  # 팔꿈치가 향할 쪽: 아래 · 바깥 · 뒤 (몸통 좌표, x 는 바깥이 +)


def _lean_toward(body: Body, side: str, t: Vec, reach: Reach) -> None:
    """손이 모자라면 몸통을 대상 쪽으로 비틀고(옆에 있어도) 숙인다(앞에 있을 때만). 서거나 앉은 자세만.
    숙이면 어깨가 옮겨 가므로 네 번까지 다시 잰다."""
    if not body.upright:
        return
    spine0 = body.angles.spine * D
    for _ in range(4):
        rb, tb = body._solve()["body"]
        local = mvec(tr(rb), sub(t, tb))
        need = dist(body._solve()["ua_" + side][1], t) - ARM + 0.01
        ang = math.atan2(local[0], local[2])
        if need <= 0 or abs(ang) > 120 * D:  # 등 뒤는 비틀어도 닿지 않는다
            return
        body.twist = _clamp(ang * 0.6, reach.twist * D)
        if local[2] > 0:  # 숙이기는 앞에 있을 때만
            body.spine = min(spine0 + reach.lean * D, body.spine + need / L.torso)
        body._changed()


def reach_to(body: Body, side: str, target: Vec, pole: Optional[Vec] = None, reach: Optional[Reach] = None) -> float:
    """어깨에서 목표(바깥 좌표)까지 두 마디 IK. 모자라면 먼저 비틀고 숙인다. 돌려주는 값은 손끝 → 목표 틈 (m, 0 이면 닿음)."""
    t = _io(target)
    _lean_toward(body, side, t, body.reach if reach is None else reach)
    sx = 1 if side == "l" else -1
    rt, tt = body._solve()["torso"]
    goal = mvec(tr(rt), sub(t, tt))
    s = (sx * L.shoulder, L.torso - 0.04, 0.0)
    to = sub(goal, s)
    d = norm(to)
    l1, l2 = L.uarm, L.farm + L.hand
    u = unit(to) if d > 1e-9 else (0.0, -1.0, 0.0)
    if 1e-9 < d < l1 + l2 - 1e-3:
        ang = math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
        pl = pole or DEFAULT_POLE
        axis = cross(u, (sx * pl[0], pl[1], pl[2]))
        if norm(axis) < 1e-9:  # pole 이 팔 방향과 나란하면 아래를 pole 로
            axis = cross(u, (0.0, -1.0, 0.0)) if abs(u[1]) < 0.99 else cross(u, (sx * 1.0, 0.0, 0.0))
        u = mvec(axis_angle(axis, ang), u)  # 어깨 → 목표 방향을 pole 쪽으로 ang 만큼 돌린다
    down = (0.0, -1.0, 0.0)
    body.ua[side] = turn(down, unit(u))
    elbow = add(s, mul(unit(u), l1))
    f = unit(mvec(tr(body.ua[side]), sub(goal, elbow)))
    body.fa[side] = turn(down, f if norm(f) > 0 else down)
    body._changed()
    return dist(body._joints()["hand_" + side], t)


def look_at(body: Body, point: Vec) -> None:
    """고개를 점(바깥 좌표)으로. 자세의 고개 한도(PostureSpec.head, 기본 좌우 70° · 위아래 35°) 안에서."""
    turn_max, nod_max = body.head
    rt, tt = body._solve()["torso"]
    v = sub(mvec(tr(rt), sub(_io(point), tt)), (0.0, L.torso + L.neck + L.head, 0.0))
    body.head_rot = euler_yxz(_clamp(-math.atan2(v[1], math.hypot(v[0], v[2])), nod_max * D), _clamp(math.atan2(v[0], v[2]), turn_max * D), 0)
    body._changed()


# ---------- 겹침 깊이 ----------

def _seg_seg(p1: Vec, q1: Vec, p2: Vec, q2: Vec) -> float:
    """두 선분 사이 가장 가까운 거리 (Ericson, Real-Time Collision Detection 5.1.9)."""
    d1, d2, r = sub(q1, p1), sub(q2, p2), sub(p1, p2)
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a <= 1e-12 and e <= 1e-12:
        return dist(p1, p2)
    if a <= 1e-12:
        s, t = 0.0, min(1.0, max(0.0, f / e))
    else:
        c = dot(d1, r)
        if e <= 1e-12:
            s, t = min(1.0, max(0.0, -c / a)), 0.0
        else:
            b = dot(d1, d2)
            den = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / den)) if den > 1e-12 else 0.0
            t = (b * s + f) / e
            if t < 0:
                s, t = min(1.0, max(0.0, -c / a)), 0.0
            elif t > 1:
                s, t = min(1.0, max(0.0, (b - c) / a)), 1.0
    return dist(add(p1, mul(d1, s)), add(p2, mul(d2, t)))


def _box_sdf(p: Vec, box: tuple[float, ...]) -> float:
    """상자까지 부호 있는 거리 (안이면 음수)."""
    q = [abs(p[i] - (box[i] + box[i + 3]) / 2) - (box[i + 3] - box[i]) / 2 for i in range(3)]
    return math.sqrt(sum(max(v, 0.0) ** 2 for v in q)) + min(max(q), 0.0)


def penetration(a: Capsule, b: "Capsule | Solid | tuple[float, ...]") -> float:
    """파고든 깊이 m (떨어져 있으면 0). b 는 캡슐, 가구 상자(Solid), 또는 (x0, y0, z0, x1, y1, z1)."""
    if isinstance(b, Capsule):
        return max(0.0, a.r + b.r - _seg_seg(a.a, a.b, b.a, b.b))
    box = b.box if isinstance(b, Solid) else tuple(b)

    def f(t: float) -> float:
        return _box_sdf(add(a.a, mul(sub(a.b, a.a), t)), box)

    # 볼록 집합의 부호 있는 거리는 선분 위에서 볼록하다: 황금 분할로 가장 작은 값
    lo, hi, g = 0.0, 1.0, (math.sqrt(5) - 1) / 2
    for _ in range(60):
        m1, m2 = hi - g * (hi - lo), lo + g * (hi - lo)
        if f(m1) <= f(m2):
            hi = m2
        else:
            lo = m1
    return max(0.0, a.r - min(f(0.0), f(1.0), f((lo + hi) / 2)))


# ---------- 동작별 손 배치 ----------

@dataclass(frozen=True)
class Act3D:
    wrap: bool = False          # 두 손으로 등을 감는다
    knees: bool = False         # 업힌 사람이 뒤에 매달렸으면 두 손을 그 무릎으로
    pole: Optional[Vec] = None  # 팔꿈치 쪽 (없으면 DEFAULT_POLE)


HUG_POLE: Vec = (0.8, -0.2, 1.0)
ACT3D = {"hug": Act3D(wrap=True, pole=HUG_POLE), "embrace": Act3D(wrap=True, pole=HUG_POLE), "carry": Act3D(knees=True)}


def _hug_targets(me: Body, other: Body) -> list[tuple[str, Vec]]:
    """한 손은 등 위, 한 손은 그 20cm 아래. 등 가운데에서 제 쪽으로 5cm, 등 겉에서 3cm 뒤를 겨눈다."""
    hi, lo = other.part_point("back"), _io(other._at("torso", (0.0, 0.12, -0.1)))
    chest = other.part_point("chest")
    back = unit((hi[0] - chest[0], hi[1] - chest[1], 0.0))
    torso = _io(me._solve()["torso"][1])

    def nudge(p: Vec, side: str) -> Vec:
        sh = _io(me._solve()["ua_" + side][1])
        out = unit((sh[0] - torso[0], sh[1] - torso[1], 0.0))
        return add(add(p, mul(out, 0.05)), mul(back, 0.03))

    return [("l", nudge(hi, "l")), ("r", nudge(lo, "r"))]


def hand_targets(c: StageContact, me: Body, other: Body, other_attach: Optional[str] = None, who: str = "") -> list[tuple[str, Vec, Optional[Vec]]]:
    """접촉 하나의 손 목표: [(쪽 l · r, 목표, pole)]. 손 아닌 부위 접촉(by 가 부위 id)이면 빈 목록."""
    if c.by not in stage.HANDS:
        return []
    hint = ACT3D.get(c.act, Act3D())
    if c.by == "both" and hint.wrap:
        return [(s, p, hint.pole) for s, p in _hug_targets(me, other)]
    if c.by == "both" and hint.knees and who and other_attach == who:
        return [("l", other.part_point("knee_l"), hint.pole), ("r", other.part_point("knee_r"), hint.pole)]
    if c.part not in stage.PARTS:
        return []
    m = other.part_point(c.part)
    if c.by != "both":
        return [("l" if c.by == "left" else "r", m, hint.pole)]
    off = mul(me.left(), 0.07)  # 두 손은 부위 점 좌우로 7cm 씩
    return [("l", add(m, off), hint.pole), ("r", sub(m, off), hint.pole)]


# ---------- 박자마다 좌표 ----------

@dataclass
class Person:
    posture: str
    body: Optional[Body] = None
    missing: Optional[str] = None  # 자세 모듈이 없으면 그 자세 id
    attach: Optional[str] = None   # 매단 인물 id


@dataclass
class Contact:
    id: str
    who: str
    to: str
    part: str
    act: str
    by: str
    hands: list[str]   # IK 를 푼 손 (l · r). 손 아닌 부위 접촉이면 빈 목록
    gap: float         # 손끝(또는 부위 점) → 목표 틈 m. 두 손이면 큰 쪽
    points: list[Vec]  # (손끝, 목표) 짝을 차례로


@dataclass
class BeatFrame:
    k: int                                 # 0 은 시작 상태, k 는 k 번째 박자 뒤
    state: dict[str, stage.Now]
    pos: dict[str, tuple[float, float]]
    bodies: dict[str, Person]
    contacts: list[Contact]


@dataclass
class Frames:
    ceiling: float
    solids: list[Solid]
    beats: list[BeatFrame]
    spec: Optional[RoomSpec] = None  # 장소 모듈 (없으면 종류 기본값만 썼다)

    def to_dict(self) -> dict:
        """렌더러 계약 (docs/stage/3d/specs/01-body.md 의 JSON)."""
        def r(v) -> list[float]:
            return [round(x, 3) for x in v]

        return {
            "ceiling": self.ceiling,
            "open": bool(self.spec and self.spec.open),
            "solids": [{"anchor": s.anchor, "box": r(s.box), "solid": s.solid, "barrier": s.barrier} for s in self.solids],
            "beats": [{"k": b.k,
                       "bodies": {w: {"posture": p.posture, "missing": p.missing, "attach": p.attach,
                                      "joints": {j: r(v) for j, v in p.body.joints().items()} if p.body else None}
                                  for w, p in b.bodies.items()},
                       "contacts": [{"id": c.id, "who": c.who, "to": c.to, "part": c.part, "act": c.act, "by": c.by, "hands": c.hands,
                                     "gap": round(c.gap, 3), "points": [r(v) for v in c.points]} for c in b.contacts]}
                      for b in self.beats],
        }


def _base(spec: PostureSpec, now: stage.Now, anchors: dict, room_spec: Optional[RoomSpec]) -> float:
    """공통 배치의 바닥 높이: 자리가 기준점 on · in 이면 자세가 놓일 수 있는 그 면, 아니면 바닥."""
    at = now.at
    a = anchors.get(at.ref) if at else None
    if not a or at.rel not in ("on", "in"):
        return 0.0
    for what in spec.surface:
        if what in ("seat", "lie") or (what == "top" and at.rel == "on"):
            h = furniture.surface(a, room_spec, what)
            if h is not None:
                return h
    return 0.0


def wrap_carrier(rider: Body, carrier: Body) -> None:
    """매달린 사람의 두 팔로 받치는 사람을 감는다: 같은 방향(업힘)이면 가슴, 마주 보면(안겨 들림) 목뒤.
    두 손은 그 점 좌우 0.08m · 위 0.03m. 업힌 사람이 손 접촉을 적었으면 그 접촉 IK 가 나중에 덮는다."""
    back = math.cos(rider.yaw - carrier.yaw) > 0
    base = carrier.part_point("chest" if back else "nape")
    left = carrier.left()
    for side, sgn in (("l", 1.0), ("r", -1.0)):
        s = sgn if back else -sgn  # 마주 보면 업힌 사람의 왼쪽이 받치는 사람의 오른쪽
        reach_to(rider, side, add(add(base, mul(left, 0.08 * s)), (0.0, 0.0, 0.03)), HUG_POLE)


def _toward(a: tuple[float, float], b: Optional[tuple[float, float]]) -> Optional[tuple[float, float]]:
    if b is None:
        return None
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-6 else None


def default_facing(now: stage.Now, me: tuple[float, float], anchors: dict, pos: dict) -> tuple[float, float]:
    """향함이 비었을 때의 몸 방향 (그림과 판정이 같이 쓴다. 평면 판정 stage.judge 는 향함을 모르는 것으로 둔다).
    1. 기준점 위 · 안 · 기대기: 그 기준점 앞 (앉는 면 앞을 보고, 기댄 면을 등진다)
    2. 손을 뻗는 접촉이 있으면 그 사람 쪽
    3. 기준점 옆 자리(앞 · 뒤 · 왼 · 오른): 그 기준점 앞 (가구를 등지고 방을 본다. 벽에 붙은 문 앞이면 방 안)
    4. 다른 인물 기준 자리: 그 인물 쪽
    5. 아무것도 없으면 평면 아래(+y)"""
    at = now.at
    a = anchors.get(at.ref) if at else None
    if a and at.rel in ("on", "in", "against"):
        return stage._front(a.rot)
    for c in now.contacts.values():
        v = _toward(me, pos.get(c.to))
        if v:
            return v
    if a:
        return stage._front(a.rot)
    if at and at.ref.startswith("@"):
        v = _toward(me, pos.get(at.ref[1:]))
        if v:
            return v
    return (0.0, 1.0)


def _look_point(facing: str, bodies: dict[str, Body], anchors: dict, room_spec: Optional[RoomSpec]) -> Optional[Vec]:
    if facing.startswith("@") and facing[1:] in bodies:
        return bodies[facing[1:]].joints()["head"]
    a = anchors.get(facing[1:]) if facing.startswith("#") else None
    if a:
        return (a.x + a.w / 2, a.y + a.h / 2, furniture.top(furniture.lookup(a, room_spec)))
    return None  # 8방향은 몸 방향이 이미 맞다


def frames(scene: StageScene, room: StageRoom, project=None, postures: Optional[dict[str, PostureSpec]] = None,
           rooms: Optional[dict[str, RoomSpec]] = None) -> Frames:
    """장면 → 박자마다 인물의 관절 좌표 · 접촉 틈과 가구 상자. 판정과 렌더러가 같은 값을 쓴다.
    평면 좌표는 stage.place 그대로다 (그림만의 보정 없음). postures · rooms 를 주지 않으면 등록부를 쓴다.
    project 는 지금 쓰지 않는다 (판정 · 화면과 같은 꼴로 받는다)."""
    from . import postures as posture_reg, rooms as room_reg
    pspecs = posture_reg.load() if postures is None else postures
    rspecs = room_reg.load() if rooms is None else rooms
    room_spec = rspecs.get(room.template) if room.template else None
    room = stage.resolve(room)
    anchors = {a.id: a for a in room.anchors}
    sol = furniture.solids(room, room_spec)
    beats = []
    spots = stage.layouts(room, scene)  # 평면 판정(stage.judge)과 같은 좌표: 박자마다 앞 박자 좌표를 넘긴다
    for k in range(len(scene.beats) + 1):
        state = stage.state_at(scene, k)
        pos = spots[k]
        people: dict[str, Person] = {}
        bodies: dict[str, Body] = {}
        hooked = []
        for w in [w for w in scene.cast if w in pos] + [w for w in pos if w not in scene.cast]:
            now = state[w]
            pid = now.posture or "stand"
            spec = pspecs.get(pid)
            if spec is None:
                people[w] = Person(pid, missing=pid)
                continue
            v = stage.facing_vec(now.facing, pos[w], room, pos) or default_facing(now, pos[w], anchors, pos)
            yaw, base = math.atan2(v[0], v[1]), _base(spec, now, anchors, room_spec)
            if spec.place_hook:
                hooked.append((w, spec, yaw, base))
                continue
            people[w] = Person(pid, body=_placed(spec, pos[w][0], pos[w][1], yaw, base))
            bodies[w] = people[w].body
        # 특수 배치는 두 번 돈다: 첫 번은 출연진 순, 두 번째는 모든 다른 인물의 첫 번 몸을 보고 다시.
        # 받치는 사람(또는 옆에 붙어 누울 사람)이 특수 배치 자세이고 출연진 뒤쪽이어도 찾는다
        for rnd in range(2 if len(hooked) > 1 else 1):
            for w, spec, yaw, base in hooked:
                seen = {o: b for o, b in bodies.items() if o != w}
                pl = spec.place_hook(PlaceCtx(w, state[w], state, pos, pos[w], yaw, base, room, room_spec, sol, seen))
                people[w] = Person(spec.id, body=_placed(spec, pl.x, pl.y, pl.yaw, pl.base, pl.angles), attach=pl.attach)
                bodies[w] = people[w].body
        for w, now in state.items():  # 고개 먼저: 얼굴 부위 점이 접촉 목표가 된다 (머리 가운데는 고개로 옮겨 가지 않는다)
            if w in bodies:
                p = _look_point(now.facing, bodies, anchors, room_spec)
                if p:
                    look_at(bodies[w], p)
        for w, person in people.items():  # 매달린 사람은 받치는 사람을 팔로 감는다
            if person.body and person.attach in bodies:
                wrap_carrier(person.body, bodies[person.attach])
        contacts = _contacts(state, people)
        beats.append(BeatFrame(k, state, pos, people, contacts))
    return Frames(room_spec.ceiling if room_spec else furniture.RoomSpec("").ceiling, sol, beats, room_spec)


_FEET: dict[tuple, tuple[list, list, list]] = {}  # (각도, 면 높이) → feet_down 이 고친 엉덩 · 무릎 · 발목. 자리 · 방향과 상관없다


def _placed(spec: PostureSpec, x: float, y: float, yaw: float, base: float, angles: Optional[Angles] = None) -> Body:
    body = pose(spec, x, y, yaw, base) if angles is None else Body(angles, x, y, yaw, base, spec.reach, spec.head)
    if spec.feet_to_floor and base > 0 and abs(base - 0.45) > 0.005:
        key = (body.angles, round(base, 4))
        if key not in _FEET:
            probe = Body(body.angles, 0.0, 0.0, 0.0, base)
            feet_down(probe)
            _FEET[key] = (probe.hip, probe.knee, probe.ankle)
        body.hip, body.knee, body.ankle = (list(v) for v in _FEET[key])
        body._changed()
    return body


def _contacts(state: dict[str, stage.Now], people: dict[str, Person]) -> list[Contact]:
    """이어지는 접촉마다 손 IK. 두 사람이 서로 손을 뻗을 때를 위해 두 번 푼다."""
    todo = [(w, c) for w, now in state.items() for c in now.contacts.values()
            if people.get(w) and people[w].body and people.get(c.to) and people[c.to].body]
    out: list[Contact] = []
    for rnd in range(2):
        for w, c in todo:
            me, other = people[w].body, people[c.to].body
            aims = hand_targets(c, me, other, people[c.to].attach, w)
            if aims:
                gaps, pts = [], []
                for side, t, pole in aims:
                    gaps.append(reach_to(me, side, t, pole))
                    pts += [me.joints()["hand_" + side], t]
                gap = max(gaps)
            elif c.by in stage.PARTS and c.part in stage.PARTS:
                a, b = me.part_point(c.by), other.part_point(c.part)
                gap, pts = dist(a, b), [a, b]
            else:
                continue
            if rnd == 1:
                out.append(Contact(c.id, w, c.to, c.part, c.act, c.by, [s for s, _, _ in aims], gap, pts))
    return out
