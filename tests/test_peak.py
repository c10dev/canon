"""정점 대목 지표: 열 낱말(Settings.heat_words)이 가장 몰린 창의 문장 길이 (metrics.peak_window · peak_drift, pipeline.style_drift, 문체 화면)."""
from canon import metrics, pipeline
from canon.schema import Meta, Project, Settings, StyleProfile

from .jsvm import dump, episode, needs_node, run_js

SHORT = "\n\n".join(["그가 섰다. 문이 닫혔다. 숨이 멎었다."] * 40)
LONG_PEAK = "\n\n".join(
    ["그가 섰다. 문이 닫혔다. 숨이 멎었다."] * 20
    + ["떨리는 손끝이 천천히 내려오며 숨이 섞이고 떨림이 번지는 동안 그녀는 떨림을 참으려 입술을 깨물고 버티면서도 다시 떨리는 숨을 삼켰다."] * 12
    + ["그가 섰다. 문이 닫혔다. 숨이 멎었다."] * 10)


def test_no_words_or_too_few_hits_gives_none():
    assert metrics.peak_window(LONG_PEAK, []) is None
    assert metrics.peak_window(LONG_PEAK, ["  "]) is None
    assert metrics.peak_window(SHORT, ["떨림"]) is None  # 낱말이 없음


def test_peak_window_finds_dense_stretch():
    pk = metrics.peak_window(LONG_PEAK, ["떨림", "떨리"])
    assert pk is not None and pk["hits"] >= metrics.PEAK_MIN_HITS
    assert pk["at"] >= LONG_PEAK.index("떨리는")  - metrics.PEAK_WINDOW
    assert pk["sentence_len"] > 40


def test_peak_drift_warns_only_when_much_longer():
    base = metrics.measure(SHORT)
    pk = metrics.peak_window(LONG_PEAK, ["떨림", "떨리"])
    warns = metrics.peak_drift(base, pk)
    assert len(warns) == 1 and warns[0].startswith("정점 대목 문장 길이: 기준 ")
    same = {**pk, "sentence_len": base.sentence_len_mean * (1 + metrics.PEAK_LIMIT)}
    assert metrics.peak_drift(base, same) == []
    assert metrics.peak_drift(base, None) == []
    assert metrics.peak_drift(metrics.StyleMetrics(), pk) == []


def _project(words: list[str]) -> Project:
    p = Project(meta=Meta(title="열", target_episodes=2), style=StyleProfile(), settings=Settings(heat_words=words),
                episodes=[episode(1, text=LONG_PEAK, status="finalized")])
    p.style_baseline = metrics.measure(SHORT)
    return p


def test_style_drift_adds_peak_warning_with_heat_words():
    _, warns = pipeline.style_drift(_project(["떨림", "떨리"]), 1)
    assert any(w.startswith("정점 대목 문장 길이:") for w in warns)
    _, none = pipeline.style_drift(_project([]), 1)
    assert not any(w.startswith("정점 대목") for w in none)


def test_old_settings_have_no_heat_words():
    assert Settings.model_validate({"check_motion": True}).heat_words == []


FILES = ["app.js", "setup.js", "chat.js", "passage.js", "marks.js", "style.js", "mystyle.js", "anchor.js", "stylechat.js"]


@needs_node
def test_rules_card_shows_heat_words_on_work_only():
    p = _project(["떨림", "숨"])
    p.style = StyleProfile(dos=["짧게"], banned_phrases=["가슴이 먹먹했다"])
    expr = """(() => { S.project = data.p; S.name = 'g'; S.route = ['p', 'g', 'style']; S.libs = [];
      const read = pfCard('rules', '지킬 · 피할 것', 'style', '', new Set());
      S.styleOpen = { 'g:rules': true };
      const edit = pfCard('rules', '지킬 · 피할 것', 'style', '', new Set());
      S.lib = { profile: data.p.style }; S.styleOpen = { 'lib:rules': true };
      const lib = pfCard('rules', '지킬 · 피할 것', 'profile', 'lib', new Set());
      return { read, edit, lib }; })()"""
    got = run_js(FILES, expr, {"p": dump(p)})
    assert "열 낱말 2" in got["read"] and ">떨림<" in got["read"]
    assert 'data-bind="settings.heat_words"' in got["edit"]
    assert "열 낱말" not in got["lib"]
