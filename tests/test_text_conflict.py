"""본문 저장 충돌 검사(web.put_text 의 base · force): 낡은 탭 · 기기가 그 사이 저장된 본문을 덮지 않는다."""
from canon import store
from canon.schema import Project

from .jsvm import episode


def _demo() -> None:
    p = Project()
    p.meta.title = "등대"
    p.meta.target_episodes = 2
    p.episodes = [episode(1, status="confirmed"), episode(2)]
    store.save("tc", p)


def test_put_text_checks_base(client):  # noqa: F811
    _demo()
    url = "/api/projects/tc/episodes/1/text"
    # base 가 없으면(옛 화면 · 명령줄) 맞춰 보지 않는다
    assert client.put(url, json={"text": "첫 본문"}).json()["episodes"][0]["text"] == "첫 본문"
    # 같은 본문에서 시작한 고침은 저장한다. 앞뒤 공백은 서버가 지우므로 맞출 때도 뺀다
    r = client.put(url, json={"text": "A 탭이 고친 본문", "base": "첫 본문\n"})
    assert r.status_code == 200 and r.json()["episodes"][0]["text"] == "A 탭이 고친 본문"
    # B 탭은 아직 '첫 본문'을 보고 고쳤다: 덮지 않고 409
    r = client.put(url, json={"text": "B 탭이 고친 본문", "base": "첫 본문"})
    assert r.status_code == 409 and r.json()["code"] == "stale_text" and "1화 본문을 먼저 저장했어요" in r.json()["detail"]
    assert store.load("tc").episode(1).text == "A 탭이 고친 본문"
    # 작가가 덮어쓰기를 고르면 force 로 저장한다. 바뀐 부분은 수정 기록에 남는다
    r = client.put(url + "?force=true", json={"text": "B 탭이 고친 본문", "base": "첫 본문"})
    assert r.status_code == 200 and r.json()["episodes"][0]["text"] == "B 탭이 고친 본문"
    assert store.load("tc").episode(1).edits


def test_put_text_checks_base_on_finalized(client):  # noqa: F811
    _demo()
    p = store.load("tc")
    p.episode(1).text, p.episode(1).status = "끝난 본문", "finalized"
    store.save("tc", p)
    url = "/api/projects/tc/episodes/1/text"
    assert client.put(url, json={"text": "고친 본문", "base": "다른 본문"}).status_code == 409
    assert client.put(url, json={"text": "고친 본문", "base": "끝난 본문"}).status_code == 200
