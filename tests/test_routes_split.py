"""canon/routes/ 로 옮긴 라우트: 앱에 붙고, 작품을 돌려주는 응답도 스냅샷을 화 번호만 보낸다."""
from fastapi.routing import APIRoute


def _all_routes(web):
    out = [r for r in web.app.routes if isinstance(r, APIRoute)]
    for mod in web.ROUTES:
        out += [r for r in __import__(f"canon.routes.{mod}", fromlist=["router"]).router.routes if isinstance(r, APIRoute)]
    return out


def test_project_routes_send_light_snapshots_config(client):  # noqa: F811
    from canon import web
    for r in _all_routes(web):
        if r.response_model is web.Project:
            assert r.response_model_exclude == web._SNAPSHOT_LIGHT, r.path


def test_moved_route_sends_light_snapshots(client):  # noqa: F811
    from canon import store
    from canon.schema import Snapshot
    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "rt", "meta": meta})
    p = store.load("rt")
    p.snapshots = [Snapshot(episode=0, facts=["첫 사실"])]
    store.save("rt", p)
    r = client.put("/api/projects/rt/atlas/title", json={"title": "바닷마을"})
    assert r.status_code == 200 and r.json()["snapshots"] == [{"episode": 0}]
