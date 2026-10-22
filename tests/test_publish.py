"""복사 · 내보내기 테스트: 줄바꿈 형식, HTML, 여러 화 잇기, .txt 내려받기. 실행: python -m pytest tests"""
from canon import publish

from .test_plot_chat import _project
from .test_web import client  # noqa: F401  (pytest fixture)

TEXT = "## 1화\n비가 그친 오후였다.  서윤은 **등대** 앞에 섰다.​ \n\n\n\"여기서 뭐 해요?\"\r\n도현이 물었다.\n\n***\n\n바다가 울었다."


def test_formats():
    assert publish.format_text(TEXT, "blank") == "1화\n비가 그친 오후였다. 서윤은 등대 앞에 섰다.\n\n\"여기서 뭐 해요?\"\n도현이 물었다.\n\n***\n\n바다가 울었다."
    assert publish.format_text(TEXT, "compact").count("\n") == 5
    assert publish.format_text(TEXT, "indent").startswith("　1화\n비가") and "\n　***\n" in publish.format_text(TEXT, "indent")
    assert publish.format_text(TEXT, "raw") == TEXT.strip()
    # 빈 줄이 하나도 없는 본문은 줄마다 문단으로 본다
    assert publish.format_text("가.\n나.\n다.", "blank") == "가.\n\n나.\n\n다."
    h = publish.format_html("<가>\n\n나", "blank")
    assert h == "<p>&lt;가&gt;</p><p><br></p><p>나</p>"


def test_export_endpoints(client):
    _project(client)
    for n in (1, 2):
        client.post(f"/api/projects/lh/episodes/{n}/confirm")
    client.post("/api/projects/lh/episodes/1/write")
    client.put("/api/projects/lh/episodes/1/text", json={"text": TEXT})
    fmts = client.get("/api/publish/formats").json()
    assert [f["id"] for f in fmts] == ["blank", "compact", "indent", "raw"]

    r = client.post("/api/projects/lh/export", json={"episodes": [1], "format": "blank"}).json()
    assert r["text"].startswith("1화. ") and r["episodes"] == [1] and "<p><strong>1화." in r["html"]
    r = client.post("/api/projects/lh/export", json={"episodes": [1], "title": False, "drafts": {"1": "저장 전\n\n본문"}}).json()
    assert r["text"] == "저장 전\n\n본문\n"
    r = client.post("/api/projects/lh/export", json={"episodes": [1, 2]}).json()
    assert r["episodes"] == [1]  # 본문 없는 화는 건너뛴다
    assert client.post("/api/projects/lh/export", json={"episodes": [2]}).status_code == 400
    assert client.post("/api/projects/lh/export", json={"episodes": [99]}).status_code == 400
    assert client.post("/api/projects/lh/export", json={"episodes": [1], "format": "x"}).status_code == 400

    f = client.get("/api/projects/lh/export.txt?format=compact")
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"] and f.text.startswith("1화. ")
