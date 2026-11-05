"""바꿔치기 쓰기(store.write_atomic): 중간에 멈춰도 옛 파일이 남고, 키 파일은 처음부터 본인만 읽는다."""
import json
import os
import stat

import pytest

from canon import library, settings, store
from canon.schema import Meta, Project, StyleEntry


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "cfg" / "config.json"))
    return tmp_path


def _fail_replace(monkeypatch):
    def boom(src, dst):
        raise OSError("디스크가 찼어요")
    monkeypatch.setattr(store.os, "replace", boom)


def test_write_atomic_returns_stat_of_new_file(tmp_path):
    path = tmp_path / "a.json"
    path.write_text("옛")
    st = store.write_atomic(path, "새")
    assert path.read_text(encoding="utf-8") == "새"
    assert st.st_ino == path.stat().st_ino and st.st_size == path.stat().st_size
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_backup_keeps_old_backup(home, monkeypatch):
    old = Project(meta=Meta(title="옛 판", target_episodes=10))
    store.save_backup("p", "before-serial", old)
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        store.save_backup("p", "before-serial", Project(meta=Meta(title="새 판", target_episodes=10)))
    assert store.load_backup("p", "before-serial").meta.title == "옛 판"
    assert not list(store.project_dir("p").glob("*.tmp"))


def test_failed_settings_write_keeps_old_keys(home, monkeypatch):
    settings._write({"gemini_api_key": "옛 키"})
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        settings._write({"gemini_api_key": "새 키"})
    assert json.loads(settings.config_path().read_text(encoding="utf-8")) == {"gemini_api_key": "옛 키"}
    assert not list(settings.config_path().parent.glob("*.tmp"))


def test_settings_file_is_owner_only_even_if_it_was_open(home, monkeypatch):
    path = settings.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    os.chmod(path, 0o644)
    seen = []
    real = store.os.replace

    def spy(src, dst):  # 바꿔 넣기 전 tmp 의 권한
        seen.append(stat.S_IMODE(os.stat(src).st_mode))
        real(src, dst)

    monkeypatch.setattr(store.os, "replace", spy)
    settings._write({"gemini_api_key": "키"})
    assert seen == [0o600]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_library_save_keeps_old_entry_on_failure(home, monkeypatch):
    monkeypatch.setattr(library, "root", lambda: home / "library")
    e = library.save(StyleEntry(id="0123abcd", name="옛 문체"))
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        library.save(e.model_copy(update={"name": "새 문체"}))
    assert json.loads((home / "library" / "0123abcd.json").read_text(encoding="utf-8"))["name"] == "옛 문체"
