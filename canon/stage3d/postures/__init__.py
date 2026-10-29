"""자세 등록부: 이 폴더의 모듈마다 POSTURE = PostureSpec(...) 하나 (docs/stage/3d/specs/02-posture.md).

파일 이름은 stage.POSTURES 의 자세 id 와 같다. 자세를 더할 때 이 파일을 고치지 않는다: load() 가 폴더를 훑는다.
시험은 load 를 monkeypatch 하거나 stage3d.frames 에 postures= 를 넘긴다.
"""
from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache


@lru_cache(maxsize=None)
def load() -> dict:
    """자세 id → PostureSpec. 파일 이름과 id 가 다르면 ValueError."""
    out = {}
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if m.name.startswith("_"):
            continue
        spec = importlib.import_module(f"{__name__}.{m.name}").POSTURE
        if spec.id != m.name:
            raise ValueError(f"자세 모듈 {m.name} 의 POSTURE.id 가 {spec.id!r} 예요")
        out[spec.id] = spec
    return out
