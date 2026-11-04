"""작업 종류 등록표: 모든 이름이 준비 함수로 이어지고, 모르는 종류는 400 으로 막는다."""
from .test_web import client  # noqa: F401  (pytest fixture)
from canon import web


def test_every_kind_has_maker():
    assert len(web.JOB_MAKERS) >= 26
    for kind, fn in web.JOB_MAKERS.items():
        assert callable(fn) and fn.__name__.startswith("_job_"), kind


def test_unknown_kind_is_rejected(client):  # noqa: F811
    meta = {"title": "등대", "genre": "미스터리", "logline": "오빠를 찾는다", "target_episodes": 10}
    assert client.post("/api/projects", json={"name": "lh", "meta": meta}).status_code == 200
    r = client.post("/api/projects/lh/jobs", json={"kind": "없는작업"})
    assert r.status_code == 400 and "모르는 작업" in r.json()["detail"]
