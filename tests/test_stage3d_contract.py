"""장면 연출 3D 계약 시험: 등록부의 자세 · 장소 모듈이 01 계약을 지키나 (docs/stage/3d/specs/01-body.md).

모듈이 하나도 없어도 통과한다. 검사 함수는 가짜 자세 · 장소로도 돌려 검사 자체가 맞는지 본다. LLM 호출 없음.
"""
import pytest

from canon import stage
from canon import stage3d as s3
from canon.stage3d import body as bd, fake


def check_posture(name: str, spec: s3.PostureSpec) -> None:
    assert isinstance(spec, s3.PostureSpec)
    assert spec.id == name and spec.id in stage.POSTURES
    a = spec.angles
    for f in bd.ANGLE_FIELDS:
        v = getattr(a, f)
        for x in (v if isinstance(v, tuple) else (v,)):
            assert -180 <= x <= 180, (name, f, x)
    assert 0 <= a.pelvis_h <= 2.0
    assert spec.surface and set(spec.surface) <= set(s3.SURFACES), spec.surface
    assert spec.reach.lean >= 0 and spec.reach.twist >= 0
    if "floor" in spec.surface:
        low = min(v[2] for v in s3.pose(spec, 0, 0).joints().values())
        assert low >= -0.02, (name, low)


def check_room(name: str, spec: s3.RoomSpec) -> None:
    assert isinstance(spec, s3.RoomSpec)
    assert spec.template == name and spec.template in stage.ROOMS
    assert 0.8 <= spec.ceiling <= 6.0
    anchors = stage.ROOMS[name][3]
    names = {a[0] for a in anchors}
    assert set(spec.anchors) <= names, set(spec.anchors) - names  # 틀에 없는 이름은 쓰이지 않는다
    for a_name, kind, *_rest, sit, lie in anchors:
        f = spec.anchors.get(a_name) or s3.KINDS.get(kind)
        assert f is not None, (name, a_name, kind)
        if sit:
            assert f.seat is not None, (name, a_name)
        if lie:
            assert f.lie is not None, (name, a_name)
        assert f.head in ("back", "left", "right")
        for b in f.boxes:
            assert 0 <= b.u0 < b.u1 <= 1 and 0 <= b.v0 < b.v1 <= 1 and 0 <= b.z0 < b.z1 <= spec.ceiling + 0.5, (name, a_name, b)


@pytest.mark.parametrize("name", sorted(s3.posture_specs()))
def test_posture_module(name):
    check_posture(name, s3.posture_specs()[name])


@pytest.mark.parametrize("name", sorted(s3.room_specs()))
def test_room_module(name):
    check_room(name, s3.room_specs()[name])


def test_fakes_pass_checks():
    for name, spec in fake.POSTURES.items():
        check_posture(name, spec)
    for name, spec in fake.ROOMS.items():
        check_room(name, spec)


def test_checks_catch_errors():
    with pytest.raises(AssertionError):
        check_posture("stand", s3.PostureSpec("stand", s3.Angles(0.5), ("floor",)))  # 발이 바닥 아래
    with pytest.raises(AssertionError):
        check_posture("fly", s3.PostureSpec("fly", s3.Angles(), ("floor",)))
    with pytest.raises(AssertionError):
        check_room("bedroom", s3.RoomSpec("bedroom", anchors={"침대": s3.Furniture((s3.Box(0, 1, 0, 1, 0, 0.5),))}))  # 눕는 면 없음


def test_registry_complete():
    m = s3.missing()
    if m["postures"] or m["rooms"]:
        pytest.skip(f"아직 없는 자세 {m['postures']} · 틀 {m['rooms']}")  # 연결 일감 07 이 엄격하게 바꾼다
    assert s3.complete()


def test_registry_scans_folder(tmp_path, monkeypatch):
    """모듈 파일을 폴더에 두기만 하면 등록된다. 파일 이름과 id 가 다르면 막는다."""
    import sys
    from canon.stage3d import postures, rooms
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "stand.py").write_text("from canon.stage3d.body import Angles, PostureSpec\n"
                                             "POSTURE = PostureSpec('stand', Angles(), ('floor',))\n")
    (tmp_path / "p" / "_note.py").write_text("X = 1\n")
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "empty.py").write_text("from canon.stage3d.furniture import RoomSpec\nROOM = RoomSpec('car')\n")
    monkeypatch.setattr(postures, "__path__", [str(tmp_path / "p")])
    monkeypatch.setattr(rooms, "__path__", [str(tmp_path / "r")])
    for m in ("canon.stage3d.postures.stand", "canon.stage3d.rooms.empty"):
        monkeypatch.delitem(sys.modules, m, raising=False)
    try:
        got = postures.load.__wrapped__()
        assert list(got) == ["stand"]
        check_posture("stand", got["stand"])
        with pytest.raises(ValueError):
            rooms.load.__wrapped__()
    finally:
        for m in ("canon.stage3d.postures.stand", "canon.stage3d.rooms.empty"):
            sys.modules.pop(m, None)
