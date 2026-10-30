"""장소 등록부: 이 폴더의 모듈마다 ROOM = RoomSpec(...) 하나 (docs/stage/3d/specs/03-room.md).

파일 이름은 stage.ROOMS 의 틀 id 와 같다. 장소를 더할 때 이 파일을 고치지 않는다: load() 가 폴더를 훑는다.
시험은 load 를 monkeypatch 하거나 stage3d.frames 에 rooms= 를 넘긴다.
"""
from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache


@lru_cache(maxsize=None)
def load() -> dict:
    """틀 id → RoomSpec. 파일 이름과 template 이 다르면 ValueError."""
    out = {}
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if m.name.startswith("_"):
            continue
        spec = importlib.import_module(f"{__name__}.{m.name}").ROOM
        if spec.template != m.name:
            raise ValueError(f"장소 모듈 {m.name} 의 ROOM.template 이 {spec.template!r} 예요")
        out[spec.template] = spec
    return out
