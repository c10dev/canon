"""ComfyUI 로 삽화 그리기 (canon/comfy.py): 프롬프트 옮기기, 워크플로 틀 채우기, 가짜 ComfyUI 로 도는 작업 illust_render, 그림 파일 정리."""
import json
import urllib.error

import pytest

from canon import comfy, illust, store
from canon.schema import Character, CharacterVisual, IllustImage, Meta, Project

from .test_ai_jobs import _run, _wait
from .test_illust import _ill
from .test_passage import TEXT, _written


def test_sd_tag():
    assert comfy.sd_tag("1.2::rain ::") == "(rain:1.2)"
    assert comfy.sd_tag("0.5::hat::") == "(hat:0.5)"
    assert comfy.sd_tag("-1::smile::") == ""  # SD 는 음수 가중치를 받지 못해 뺀다
    assert comfy.sd_tag("{{blush}}") == "(blush:1.1)"
    assert comfy.sd_tag("[glasses]") == "(glasses:0.95)"
    assert comfy.sd_tag("source#hug") == "hug"
    assert comfy.sd_tag("hat (object)") == r"hat \(object\)"
    assert comfy.sd_tag("1::plain::") == "plain"


def _proj():
    p = Project(characters=[Character(id="a", name="가", role="", gender="여"), Character(id="b", name="나", role="", gender="남")],
                visuals=[CharacterVisual(character_id="b", look=["black hair"], negative=["long hair"])])
    p.illust.style = ["watercolor"]
    return p


def test_prompt_of_flattens_characters():
    p = _proj()
    ill = illust.assemble(p, _ill(p), "v4.5-full")
    pos, neg, notes = comfy.prompt_of(p, ill)
    assert pos == "1girl, 1boy, watercolor, indoors, upper body, dim lighting, general, red hair, smile, hug, black hair, pajamas"
    assert neg == "nsfw, hat, long hair"  # 인물 칸 부정 태그도 합친다
    assert notes and "섞일" in notes[0]

    p.illust.quality = True  # NovelAI 품질 태그는 빼고, 영어 문장은 한 덩어리로 끝에 둔다
    ill = illust.assemble(p, ill, "v5-full")
    pos, _, _ = comfy.prompt_of(p, ill)
    assert "masterpiece" not in pos and "no text" not in pos and pos.endswith("general, red hair, smile, hug, black hair, pajamas, Two people hug")

    p.meta = Meta(adult=True)
    ill = illust.assemble(p, _ill(p, rating="questionable"), "v4.5-full")
    assert ", nsfw," in comfy.prompt_of(p, ill)[0]


def test_workflow_slots_and_auto(monkeypatch, tmp_path):
    monkeypatch.setenv("CANON_COMFY_CKPT", "anime.safetensors")
    monkeypatch.setenv("CANON_COMFY_SIZE", "1024x1024")
    wf = comfy.workflow("1girl", "lowres", 7)
    assert wf["4"]["inputs"]["ckpt_name"] == "anime.safetensors"
    assert (wf["6"]["inputs"]["text"], wf["7"]["inputs"]["text"], wf["3"]["inputs"]["seed"]) == ("1girl", "lowres", 7)
    assert (wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]) == (1024, 1024)
    assert comfy.DEFAULT_WORKFLOW["6"]["inputs"]["text"] == "{{prompt}}"  # 틀은 그대로 둔다

    monkeypatch.delenv("CANON_COMFY_CKPT")
    with pytest.raises(comfy.ComfyError, match="CANON_COMFY_CKPT"):
        comfy.workflow("1girl", "", 1)

    # 고정 태그를 앞에 둔 자리표
    tpl = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "masterpiece, {{prompt}}"}}}
    assert comfy.workflow("1girl", "", 1, tpl)["1"]["inputs"]["text"] == "masterpiece, 1girl"

    # 자리표가 없는 틀은 KSampler 의 positive · negative 를 따라가 채운다
    tpl = {"2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
           "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "old neg"}},
           "4": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["2", 0], "negative": ["3", 0]}}}
    wf = comfy.workflow("1girl", "lowres", 99, tpl)
    assert (wf["2"]["inputs"]["text"], wf["3"]["inputs"]["text"], wf["4"]["inputs"]["seed"]) == ("1girl", "lowres", 99)
    with pytest.raises(comfy.ComfyError, match="프롬프트 칸"):
        comfy.workflow("1girl", "", 1, {"1": {"class_type": "SaveImage", "inputs": {}}})

    # 파일 틀: 화면용 JSON 은 API 형식으로 다시 내보내라고 알린다
    f = tmp_path / "wf.json"
    f.write_text(json.dumps({"nodes": [], "links": []}))
    monkeypatch.setenv("CANON_COMFY_WORKFLOW", str(f))
    with pytest.raises(comfy.ComfyError, match="Export"):
        comfy.template()
    f.write_text(json.dumps(tpl))
    assert comfy.template() == tpl and comfy.status()["workflow"] == "wf.json"


REGIONAL = {
    "1": {"class_type": "AnimaPromptFormatter", "inputs": {"text": "{{main}}"}, "_meta": {"title": "Main Prompt"}},
    "2": {"class_type": "AnimaPromptFormatter", "inputs": {"text": "{{char1}}"}, "_meta": {"title": "Area 1 Prompt"}},
    "3": {"class_type": "AnimaPromptFormatter", "inputs": {"text": "{{char2}}"}, "_meta": {"title": "Area 2 Prompt"}},
    "4": {"class_type": "INTConstant", "inputs": {"value": "{{multi:3:1}}"}, "_meta": {"title": "Controlnet Mode Select"}},
    "5": {"class_type": "AnimaPromptFormatter", "inputs": {"text": "worst quality, {{negative}}"}},
    "6": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}"}},
}


def test_parts_order_by_position():
    p = _proj()
    ill = illust.assemble(p, _ill(p), "v4.5-full")
    ill.characters.reverse()  # 오른쪽 인물이 먼저 와도 왼쪽부터 넣는다
    parts = comfy.parts_of(p, ill)
    assert parts.chars == [["red hair", "smile", "hug"], ["black hair", "pajamas", "hug"]]
    assert parts.base[:2] == ["1girl", "1boy"] and parts.people == 2


def test_fill_regional_slots():
    p = _proj()
    parts = comfy.parts_of(p, illust.assemble(p, _ill(p), "v4.5-full"))
    wf, sent, notes = comfy.fill(parts, 7, REGIONAL)
    assert wf["1"]["inputs"]["text"] == "1girl, 1boy, watercolor, indoors, upper body, dim lighting, general"
    assert wf["2"]["inputs"]["text"] == "red hair, smile, hug" and wf["3"]["inputs"]["text"] == "black hair, pajamas, hug"
    assert wf["4"]["inputs"]["value"] == 3 and wf["6"]["inputs"]["seed"] == 7
    assert wf["5"]["inputs"]["text"] == "worst quality, nsfw, hat, long hair"
    assert sent.count(" | ") == 2 and not notes  # 인물을 나눠 넣었으니 섞인다는 알림이 없다

    # 인물이 하나면 기본 칸에 모두 넣고 인물 칸은 비운다
    one = comfy.Parts(base=["1girl", "night"], chars=[["red hair"]], people=1)
    wf, sent, notes = comfy.fill(one, 1, REGIONAL)
    assert (wf["1"]["inputs"]["text"], wf["2"]["inputs"]["text"], wf["4"]["inputs"]["value"]) == ("1girl, night, red hair", "", 1)

    # 인물 칸보다 인물이 많으면 남는 인물은 기본 칸에 넣고 알린다
    three = comfy.Parts(base=["3girls"], chars=[["a"], ["b"], ["c"]], people=3)
    wf, sent, notes = comfy.fill(three, 1, REGIONAL)
    assert wf["1"]["inputs"]["text"] == "3girls, c" and wf["3"]["inputs"]["text"] == "b" and "2개" in notes[0]

    # 인물 칸이 없는 틀은 한 줄로 합치고 섞일 수 있다고 알린다
    flat = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{main}}"}}}
    wf, sent, notes = comfy.fill(parts, 1, flat)
    assert wf["1"]["inputs"]["text"].endswith("red hair, smile, hug, black hair, pajamas") and comfy.MIXED in notes


def test_image_of_prefers_final_title():
    outputs = {"119": {"images": [{"filename": "wip.png", "type": "output"}]},
               "338": {"images": [{"filename": "final.png", "type": "output"}]}}
    wf = {"119": {"_meta": {"title": "Save Image"}}, "338": {"_meta": {"title": "최종 이미지 저장"}}}
    assert comfy._image_of(outputs, wf)["filename"] == "final.png"
    assert comfy._image_of(outputs)["filename"] == "wip.png"


def test_render_reports_comfy_errors(monkeypatch):
    p = _proj()
    ill = illust.assemble(p, _ill(p), "v4.5-full")
    monkeypatch.setenv("CANON_COMFY_CKPT", "x.safetensors")
    monkeypatch.delenv("CANON_COMFY_URL", raising=False)
    with pytest.raises(comfy.ComfyError, match="CANON_COMFY_URL"):
        comfy.render(p, ill)
    monkeypatch.setenv("CANON_COMFY_URL", "http://127.0.0.1:18188")

    def refuse(req, timeout=0):
        raise urllib.error.URLError("Connection refused")
    monkeypatch.setattr(comfy.urllib.request, "urlopen", refuse)
    with pytest.raises(comfy.ComfyError, match="닿지 않아요"):
        comfy.render(p, ill)

    def history_error(method, path, body=None, wait=30):
        if path == "/prompt":
            return b'{"prompt_id": "x1"}'
        if path.startswith("/history/"):
            msg = ["execution_error", {"exception_message": "CUDA out of memory"}]
            return json.dumps({"x1": {"status": {"status_str": "error", "completed": False, "messages": [msg]}}}).encode()
        return b"{}"
    monkeypatch.setattr(comfy, "_http", history_error)
    with pytest.raises(comfy.ComfyError, match="CUDA out of memory"):
        comfy.render(p, ill, poll=0)


def test_reason_reads_node_errors():
    raw = json.dumps({"error": {"message": "Prompt outputs failed validation"},
                      "node_errors": {"4": {"class_type": "CheckpointLoaderSimple", "errors": [{"message": "Value not in list", "details": "ckpt_name: 'x'"}]}}})
    assert comfy._reason(raw.encode()) == "Prompt outputs failed validation / 노드 4 CheckpointLoaderSimple: Value not in list ckpt_name: 'x'"


def test_render_job_with_fake_comfy(client, monkeypatch):
    monkeypatch.setenv("CANON_COMFY_URL", "mock")
    monkeypatch.setenv("CANON_COMFY_CKPT", "anime.safetensors")
    _written(client)
    quote = "서윤은 등대 앞에 섰다."
    client.post("/api/projects/lh/episodes/1/illust", json={"selection": {"start": TEXT.index(quote), "text": quote}})
    assert client.get("/api/comfy").json()["on"] is True

    j = _run(client, "lh", {"kind": "illust_render", "ep": 1, "target": "i1"})
    file = j["result"]["file"]
    im = store.load("lh").episodes[0].illustrations[0].images[0]
    assert im.file == file and im.prompt.startswith("1girl, 1boy") and im.workflow == "기본 틀"
    r = client.get(f"/api/projects/lh/illust-images/{file}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")
    assert client.get("/api/projects/lh/illust-images/..%2Fproject.json").status_code in (400, 404)

    # 없는 삽화는 시작하지 않는다
    assert client.post("/api/projects/lh/jobs", json={"kind": "illust_render", "ep": 1, "target": "i9"}).status_code == 400

    # 그림 지우기 · 삽화 지우기는 파일도 지운다
    j2 = _run(client, "lh", {"kind": "illust_render", "ep": 1, "target": "i1"})
    p = client.delete(f"/api/projects/lh/episodes/1/illust/i1/images/{file}").json()
    assert [x["file"] for x in p["episodes"][0]["illustrations"][0]["images"]] == [j2["result"]["file"]]
    assert sorted(f.name for f in comfy.folder("lh").iterdir()) == [j2["result"]["file"]]
    client.delete("/api/projects/lh/episodes/1/illust/i1")
    assert list(comfy.folder("lh").iterdir()) == []


def test_render_job_needs_url(client, monkeypatch):
    monkeypatch.delenv("CANON_COMFY_URL", raising=False)
    _written(client)
    client.post("/api/projects/lh/episodes/1/illust", json={})
    r = client.post("/api/projects/lh/jobs", json={"kind": "illust_render", "ep": 1, "target": "i1"})
    assert r.status_code == 400 and "CANON_COMFY_URL" in r.json()["detail"]
    assert client.get("/api/comfy").json()["on"] is False


def test_render_job_drops_image_when_illustration_gone(client, monkeypatch):
    monkeypatch.setenv("CANON_COMFY_URL", "mock")
    monkeypatch.setenv("CANON_COMFY_CKPT", "anime.safetensors")
    _written(client)
    client.post("/api/projects/lh/episodes/1/illust", json={})
    real = comfy.render

    def render_then_delete(p, ill, **kw):
        out = real(p, ill, **kw)
        client.delete("/api/projects/lh/episodes/1/illust/i1")  # 그리는 동안 작가가 삽화를 지웠다
        return out
    monkeypatch.setattr(comfy, "render", render_then_delete)
    r = client.post("/api/projects/lh/jobs", json={"kind": "illust_render", "ep": 1, "target": "i1"})
    j = _wait(client, r.json()["id"])
    assert j["status"] == "error" and (not comfy.folder("lh").exists() or not list(comfy.folder("lh").iterdir()))


def test_add_image_keeps_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _proj()
    from canon.schema import Episode, EpisodePlot
    p.episodes = [Episode(plot=EpisodePlot.model_construct(number=1), illustrations=[illust.assemble(p, _ill(p))])]
    for k in range(comfy.IMAGES_KEEP + 2):
        comfy.add_image(p, 1, "i1", IllustImage(file=f"{k:016x}.png"))
    files = [im.file for im in p.episodes[0].illustrations[0].images]
    assert len(files) == comfy.IMAGES_KEEP and files[0] == f"{2:016x}.png"
    d = comfy.folder("x")
    d.mkdir(parents=True)
    for k in range(comfy.IMAGES_KEEP + 2):
        (d / f"{k:016x}.png").write_bytes(b"x")
    (d / "keep.txt").write_text("남의 파일")
    assert comfy.prune("x", p) == 2 and (d / "keep.txt").exists()
