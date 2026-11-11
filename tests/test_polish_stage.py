"""퇴고 단계 (Settings.polish_stage, canon/polishscan.py, docs/context/specs/13-polish-stage.md).
실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_polish_stage.py"""
import time

from canon import autorun, pipeline, polishscan, prompts, store
from canon.autorun import Policy
from canon.schema import Project, RuleLayer
from tests.test_char_context import _long
from tests.test_write_budget import DIRECTIVE_CAP, directives


def _next(p: Project) -> int:
    return next(e.plot.number for e in p.episodes if not e.text)


def _wait(client, jid, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았어요")


def test_off_by_default_and_short_ignores_it():
    p = _long()
    n = _next(p)
    assert p.settings.polish_stage is False and not prompts.polish_split(p)
    before = (prompts.writer_system(p), prompts.episode_prompt(p, n))
    short = Project()
    short.settings.polish_stage = True  # 단편은 켜도 따르지 않는다
    assert not prompts.polish_split(short)
    assert prompts.prose_rules(False) in prompts.writer_system(short)
    assert (prompts.writer_system(p), prompts.episode_prompt(p, n)) == before


def test_split_moves_donts_out_of_write_request():
    p = _long()
    n = _next(p)
    p.style.banned_phrases = ["심장이 쿵"]
    full = prompts.episode_prompt(p, n)
    p.settings.polish_stage = True
    sys, req = prompts.writer_system(p), prompts.episode_prompt(p, n)
    assert "부정 후 재정의" in prompts.prose_rules() and "부정 후 재정의" not in sys
    assert "감정은 행동, 대사, 사물로 드러냅니다" in sys
    assert "banned_phrases" not in req and "심장이 쿵" not in req
    assert "서술 문장의 끝을 섞습니다" not in req and "서술 문장의 끝을 섞습니다" in full
    assert prompts.WRITE_STYLE_SPLIT in req and prompts.WRITE_STYLE_LINE not in req
    assert directives(req) <= DIRECTIVE_CAP and directives(req) < directives(full)


def test_scan_skips_dialogue_and_fx_lines():
    p = _long()
    n = _next(p)
    p.style.banned_phrases = ["심장이 쿵"]
    text = ("\"심장이 쿵 했어.\"\n\n"  # 대사 줄: 퇴고가 바꾸지 못하니 찾지 않는다
            "—심장이 쿵\n\n"  # 줄표로 여는 효과음 줄
            "민호는 문을 열었다. 심장이 쿵 내려앉았다.\n\n"
            "안도감이 밀려왔다.")
    found = polishscan.find(p, n, text)
    names = {t.name: t for t in found}
    assert names["금지 표현 '심장이 쿵'"].quotes == ["심장이 쿵 내려앉았다."]
    assert "감정 이름 서술" in names
    block = polishscan.block(found)
    assert block.startswith("\n\n" + polishscan.HEAD) and "«심장이 쿵 내려앉았다.»" in block


def test_scan_caps_quotes_and_counts_dropped():
    p = _long()
    n = _next(p)
    p.style.banned_phrases = ["푸른 달"]
    text = "\n\n".join(f"{i}번째 밤에 푸른 달이 떴다." for i in range(10))
    found = [t for t in polishscan.find(p, n, text) if t.name.startswith("금지 표현")]
    assert found[0].count == 10
    assert "(10곳 가운데 6곳만 적었습니다)" in polishscan.block(found)


def test_polish_prompt_gets_layer_rules_and_targets_only_when_on():
    p = _long()
    n = _next(p) - 1
    p.style.donts = ["'문득'을 쓰지 않는다"]
    p.style.banned_phrases = ["푸른 달"]
    p.settings.rule_layers = [RuleLayer(text="'문득'을 쓰지 않는다", layer="polish")]
    text = p.episode(n).text + "\n\n푸른 달이 떴다."
    off = prompts.polish_prompt(p, n, text)
    assert polishscan.HEAD not in off and prompts.POLISH_LAYER_HEAD not in off
    assert "'문득'을 쓰지 않는다" in prompts.dump(prompts.style_rules_view(p))  # 끈 작품의 퇴고 줄은 집필 줄이다
    p.settings.polish_stage = True
    on = prompts.polish_prompt(p, n, text)
    assert on.startswith(prompts.static_context(p) + "\n\n# 다듬을 본문\n")  # 앞은 쓰기와 같은 고정 블록(캐시)
    assert prompts.POLISH_LAYER_HEAD in on and polishscan.HEAD in on and "«푸른 달이 떴다.»" in on
    assert "'문득'을 쓰지 않는다" not in prompts.dump(prompts.style_rules_view(p))
    assert on.index(prompts.POLISH_LAYER_HEAD) < on.index(polishscan.HEAD)  # 화마다 바뀌는 찾은 자리가 맨 끝


def test_autorun_always_polishes_when_on(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_BATCH_POLL", "0.01")
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    p = _long()
    n = _next(p)
    p.settings.polish_stage = True
    store.save("ps", p)
    run = autorun.start("ps", n, False, Policy(polish=False, hand_pick_opening=False), foreground=True)
    assert run.status in ("done", "stopped"), run.status
    e = store.load("ps").episode(n)
    assert e.made_by is not None and e.made_by.mode == "polish"


def test_write_job_puts_polish_candidate(client):
    p = _long()
    n = _next(p)
    p.settings.polish_stage = True
    p.settings.check_after_write = True  # 퇴고 단계에서는 판을 고른 뒤 검수한다
    store.save("ps", p)
    j = _wait(client, client.post("/api/projects/ps/jobs", json={"kind": "write", "ep": n}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert j["result"]["candidate"] is True and "check" not in j["result"]
    e = store.load("ps").episode(n)
    assert e.text and e.candidate is not None and e.candidate.request.mode == "polish"
    t = client.get(f"/api/projects/ps/episodes/{n}/polish-targets").json()
    assert t["on"] is True and "total" in t["current"] and t["candidate"] is not None


def test_polish_targets_off(client):
    p = _long()
    store.save("ps", p)
    n = _next(p) - 1
    assert client.get(f"/api/projects/ps/episodes/{n}/polish-targets").json() == {"on": False}


def test_metrics_da_runs():
    from canon import metrics
    text = "\n".join(f"{i}번 문장이다." for i in range(6)) + "\n\"대사.\"\n" + "\n".join(f"짧다 {i}." for i in range(3))
    assert metrics.da_runs(text) == ["0번 문장이다."]
    assert pipeline.polish_problem("가", "가") == ""
