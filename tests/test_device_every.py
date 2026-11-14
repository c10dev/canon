"""문체 분석은 장치 최소 간격(StyleDevice.every)을 채우지 않는다 (웹소설 일감 12, 정할 것 19).
문체 대화와 수정에서 배우기로 들어온 값은 그대로 둔다. 실행: python -m pytest tests/test_device_every.py"""
from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Episode, Project, StyleDevice, StyleEdit, StyleProfile, StyleRevision

from .test_library import SAMPLE
from .test_own_style import _edited_project, _plot


def test_style_prompt_asks_every_zero():
    for passages in (True, False):
        text = prompts.style_prompt(SAMPLE, passages)
        assert "every 는 0 으로 두세요. 최소 간격은 작가가 정합니다." in text
        assert "빈도로 짐작한" not in text
        assert "per_1k 는 0 으로 두세요." in text
    assert "every 는 0 으로 두세요. 최소 간격은 작가가 정합니다.\n그런 장치가 담긴 문단은 sample_passages 로 고르지 않습니다." in prompts.style_prompt(SAMPLE)


def test_analysis_drops_model_every():
    prof = pipeline.analyze_style(MockLLM(), SAMPLE)
    assert prof.devices  # 가짜 응답은 every=3 을 적는다
    assert all(d.every == 0 for d in prof.devices)
    prof = StyleProfile(devices=[StyleDevice(name="망상", every=4), StyleDevice(name="침묵", every=-2)])
    pipeline.count_markers(prof, SAMPLE)
    assert [d.every for d in prof.devices] == [0, 0]


def test_analysed_device_never_rests():
    p = Project()
    p.style = pipeline.analyze_style(MockLLM(), SAMPLE)
    assert p.style.devices[0].cues == ["대답"]
    p.episodes += [Episode(plot=_plot(1), status="written", text="대답은 없었다. 대답 대신 창밖을 보았다."),
                   Episode(plot=_plot(2), status="confirmed")]
    block = prompts.device_block(p, 2)
    assert "마지막으로 쓴 화 1화" in block and "이번 화에는 쓰지 않습니다" not in block
    p.style.devices[0].every = 3  # 작가가 간격을 적으면 쉬는 화가 생긴다
    assert "이번 화에는 쓰지 않습니다" in prompts.device_block(p, 2)


def test_style_chat_keeps_every():
    p = Project()
    rev = StyleRevision(reply="고침", edits=[StyleEdit(key="devices", devices=[StyleDevice(name="자문자답 망상", when="설렐 때", every=5)])])
    pipeline.clean_style_revision(p, rev)
    pipeline.apply_style_edits(p, rev, ["devices"])
    assert [(d.name, d.every) for d in p.style.devices] == [("자문자답 망상", 5)]


def test_learning_keeps_every():
    p = _edited_project()
    p.style_learning = pipeline.learn_style(MockLLM(), p)
    idx = [i for i, s in enumerate(p.style_learning.suggestions) if s.kind == "device"]
    pipeline.apply_learning(p, idx)
    assert [d.every for d in p.style.devices] == [5]
