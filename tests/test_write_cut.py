"""본문 쓰기 출력 한도와 끊긴 본문 거부 (pipeline.write_out_tokens · _write · WriteCut, llm.was_cut, autorun kind cut)."""
import pytest

from canon import autorun, llm, mock, pipeline, store, usage
from canon.llm import LocalLLM, OutputCut, caps, was_cut
from canon.mock import MockLLM
from canon.schema import Episode, EpisodePlot, Project

BODY = "바람이 불었다. 서윤은 등대 앞에 섰다.\n\n\"됐어, 내가 할게.\""


@pytest.fixture()
def project():
    p = Project()
    p.episodes = [Episode(plot=EpisodePlot(number=1, act="기", title="t", summary="s", events=["e"], characters=[],
                                           emotional_shift="", ending_hook=""), status="confirmed")]
    return p


class _Capped(MockLLM):
    """부를 때 걸린 출력 한도를 적는 가짜 LLM."""

    def __init__(self):
        self.caps: list = []

    def _text(self, system, prompt):
        self.caps.append(caps()[0])
        return BODY


def test_write_out_tokens_follows_target_and_range(project):
    project.meta.words_per_episode = 7000
    assert pipeline.write_out_tokens(project) == 7000 * 4 + 16384  # 44,384: 서버 최댓값 24,800 보다 넉넉하다
    project.meta.words_per_episode = 1000
    assert pipeline.write_out_tokens(project) == pipeline.WRITE_OUT_RANGE[0]
    project.meta.words_per_episode = 30000
    assert pipeline.write_out_tokens(project) == pipeline.WRITE_OUT_RANGE[1]
    # 다시 생성 · 다듬기: 지금 본문이 목표보다 길면 그 길이로 잰다
    project.meta.words_per_episode = 5000
    project.episode(1).text = "가" * 9000
    assert pipeline.write_out_tokens(project, 1) == 9000 * 4 + 16384
    assert pipeline.write_out_tokens(project, 99) == 5000 * 4 + 16384  # 없는 화는 목표 분량


def test_write_sets_cap_only_for_backends_that_know_cut(project):
    fake = _Capped()
    assert pipeline._write(fake, project, 1, "쓰기") == BODY
    assert fake.caps == [pipeline.write_out_tokens(project, 1)]

    class Plain:  # 끊김을 알리지 않는 백엔드(구독 · 배치 · 시험용 가짜)는 한도를 걸지 않는다
        seen: list = []

        def text(self, system, prompt):
            self.seen.append(caps()[0])
            return BODY

    plain = Plain()
    assert pipeline._write(plain, project, 1, "쓰기") == BODY
    assert plain.seen == [None]


def test_cut_body_is_retried_then_refused(project, monkeypatch):
    monkeypatch.setattr(mock, "CUT_TEXT", [True])
    fake = _Capped()
    assert pipeline._write(fake, project, 1, "쓰기") == BODY  # 한 번 끊기면 다시 쓴다
    assert len(fake.caps) == 2 and fake.last_finish == "STOP"

    monkeypatch.setattr(mock, "CUT_TEXT", [True] * pipeline.WRITE_TRIES)
    with pytest.raises(pipeline.WriteCut, match=r"출력 길이 한도\(36,384토큰\)에 걸려 끊겼어요 \(3번 중 3번\)"):
        pipeline.write_episode(MockLLM(), project, 1)


def test_web_write_does_not_save_cut_body(client, monkeypatch):
    """본문 쓰기 라우트는 돌려받은 본문을 저장한다. 세 번 모두 끊기면 오류로 끝나고 화 본문은 그대로다."""
    from canon import store as st

    from .test_plot_chat import _project
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    monkeypatch.setattr(mock, "CUT_TEXT", [True] * pipeline.WRITE_TRIES)
    r = client.post("/api/projects/lh/episodes/1/write")
    assert r.status_code >= 400 and "출력 길이 한도" in r.text
    ep = st.load("lh").episode(1)
    assert not ep.text and ep.status == "confirmed"


def test_mixed_failures_are_not_reported_as_cut(project, monkeypatch):
    """세 번 중 일부만 끊기고 나머지가 다른 까닭이면 끊김(WriteCut)이 아니라 까닭을 모두 적은 오류로 멈춘다."""
    monkeypatch.setattr(mock, "CUT_TEXT", [True])

    class Mixed(_Capped):
        def _text(self, system, prompt):
            self.caps.append(caps()[0])
            return "I am thinking about the scene in English first."

    with pytest.raises(ValueError) as e:
        pipeline._write(Mixed(), project, 1, "쓰기")
    assert not isinstance(e.value, pipeline.WriteCut)
    assert "끊긴 응답 1번" in str(e.value) and "다른 글(영어로 된 생각 과정 등) 2번" in str(e.value)


def test_batch_cut_body_is_refused(project, monkeypatch):
    """배치로 쓴 본문도 끝난 이유(MAX_TOKENS)를 받아 끊긴 본문을 받지 않는다. 배치에는 출력 한도를 걸지 않는다."""
    monkeypatch.setattr(mock, "CUT_TEXT", [True])
    names: dict = {}
    b = llm.BatchLLM(MockLLM(), "write", names, lambda: None, lambda s: "")
    out = pipeline._write(b, project, 1, "쓰기")
    assert out and b.last_finish == "STOP" and names == {}
    monkeypatch.setattr(mock, "CUT_TEXT", [True] * pipeline.WRITE_TRIES)
    with pytest.raises(pipeline.WriteCut, match=r"출력 길이 한도에 걸려 끊겼어요 \(3번 중 3번\)"):
        pipeline._write(llm.BatchLLM(MockLLM(), "write", {}, lambda: None, lambda s: ""), project, 1, "쓰기")


def test_empty_cut_reply_counts_as_cut(project, monkeypatch):
    monkeypatch.setattr(mock, "CUT_TEXT", ["empty"])  # 생각만 하다 한도에 걸려 글 없이 끝났다
    fake = _Capped()
    assert pipeline._write(fake, project, 1, "쓰기") == BODY and len(fake.caps) == 2

    monkeypatch.setattr(mock, "CUT_TEXT", ["empty"] * pipeline.WRITE_TRIES)
    with pytest.raises(pipeline.WriteCut, match=r"3번 중 3번"):
        pipeline._write(_Capped(), project, 1, "쓰기")


def test_empty_reply_without_cut_is_not_retried(project):
    class Empty(MockLLM):  # 끊김이 아닌 빈 응답(안전 필터 등)은 지금처럼 오류로 끝난다
        def text(self, system, prompt):
            self.last_finish = "SAFETY"
            raise RuntimeError("Gemini 응답이 비었어요: SAFETY")

    with pytest.raises(RuntimeError, match="SAFETY"):
        pipeline._write(Empty(), project, 1, "쓰기")


def test_local_gets_no_write_cap(project, monkeypatch):
    local = LocalLLM(base_url="http://127.0.0.1:9/v1", model="m", api_key="", sampling={}, timeout=1)
    sent = []

    def fake(method, path, body=None, timeout=None):
        sent.append(body)
        return {"choices": [{"message": {"content": BODY}, "finish_reason": "stop"}]}

    monkeypatch.setattr(local, "_request", fake)
    assert pipeline._write(local, project, 1, "쓰기") == BODY
    assert "max_tokens" not in sent[-1]  # vLLM 은 프롬프트 + max_tokens 가 컨텍스트를 넘으면 400 으로 거절한다


def test_output_cut_error_counts_as_cut(project):
    class Api:  # Claude API 는 끊기면 OutputCut 을 낸다
        knows_cut = True
        calls = 0

        def text(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                raise OutputCut("Claude 응답이 최대 길이(36384 토큰)에서 끊겼어요")
            return BODY

    api = Api()
    assert pipeline._write(api, project, 1, "쓰기") == BODY and api.calls == 2


def test_local_records_length_finish(monkeypatch):
    local = LocalLLM(base_url="http://127.0.0.1:9/v1", model="m", api_key="", sampling={}, timeout=1)
    sent = []

    def reply(finish):
        def fake(method, path, body=None, timeout=None):
            sent.append(body)
            return {"choices": [{"message": {"content": "서윤은 등대 앞에 섰다."}, "finish_reason": finish}]}
        return fake

    monkeypatch.setattr(local, "_request", reply("length"))
    with llm.out_cap(30000):
        local.text("s", "p")
    assert local.last_finish == "length" and was_cut(local) and sent[-1]["max_tokens"] == 30000
    monkeypatch.setattr(local, "_request", reply("stop"))
    local.text("s", "p")
    assert local.last_finish == "stop" and not was_cut(local)
    rows = usage.read()[-2:]  # 끝난 이유와 응답 글자 수가 사용량 칸에 남는다
    assert [(r["stop"], r["out_chars"]) for r in rows] == [("length", 13), ("stop", 13)]


def test_autorun_pauses_without_saving_cut_body(tmp_path, monkeypatch):
    import contextlib
    import io

    from canon.cli import main

    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "3", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    monkeypatch.setattr(mock, "CUT_TEXT", [True] * pipeline.WRITE_TRIES)
    run = autorun.start("demo", 1, False, autorun.Policy(hand_pick_opening=False), foreground=True)
    assert run.status == "paused" and run.halt == "cut" and run.ep == 1
    assert "출력 길이 한도" in run.reasons[0] and "다시 써요" in run.reasons[1]
    p = store.load("demo")
    assert not p.episode(1).text and p.episode(1).status == "confirmed"
    run = autorun.resume("demo", foreground=True)  # 이어 가면 그 화를 다시 쓴다
    assert run.status == "done" and store.load("demo").episode(1).status == "finalized"
