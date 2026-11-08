"""깨진 설정 파일 보관과 덮어쓰기 막기, 설정 쓰기 잠금 (settings._load · _CONFIG_LOCK)."""
import json
import stat
import threading
import time

import pytest

from canon import settings


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("CANON_CONFIG", str(path))
    for k in ("CANON_LLM", "CANON_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return path


BROKEN = '{"gemini_api_key": "AIza-secret-1234", "model": "gemini-4-argon", "stage_presets": [{"id": "my-1"'


def test_broken_file_is_kept_once_and_writers_refuse(cfg):
    cfg.write_text(BROKEN, encoding="utf-8")
    assert settings.model()[0] == settings.DEFAULT_MODEL  # 읽는 쪽은 기본값
    backups = list(cfg.parent.glob("config.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == BROKEN
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600  # 키가 들어 있어 본인만 읽는다
    settings.public()
    settings.provider()
    assert len(list(cfg.parent.glob("config.json.corrupt-*"))) == 1  # 같은 내용은 한 번만
    settings._backups.clear()  # 서버를 다시 켜도 같은 내용이면 새로 만들지 않는다
    settings.model()
    assert len(list(cfg.parent.glob("config.json.corrupt-*"))) == 1

    for write in (lambda: settings.update(model="x"),
                  lambda: settings.save_preset("내 것", {"write": "local"}, {}),
                  lambda: settings.delete_preset("my-1"),
                  lambda: settings.set_prices([{"model": "x", "input": 1, "output": 2}])):
        with pytest.raises(settings.ConfigBroken) as e:
            write()
        assert backups[0].name in str(e.value) and "AIza" not in str(e.value)
    assert not settings.mark_gemini_cache_unsupported(False, "y")
    assert cfg.read_text(encoding="utf-8") == BROKEN  # 원본도 그대로


def test_non_object_json_is_broken(cfg):
    cfg.write_text("[1, 2]", encoding="utf-8")
    assert settings._load() == ({}, "corrupt")
    with pytest.raises(settings.ConfigBroken):
        settings.update(model="x")


def test_public_reports_broken_and_reset_starts_fresh(cfg):
    cfg.write_text(BROKEN, encoding="utf-8")
    pub = settings.public()
    assert pub["config_broken"] is True
    assert pub["config_backup"].startswith(str(cfg) + ".corrupt-")
    assert "AIza" not in json.dumps(pub)
    settings.reset_broken()
    assert json.loads(cfg.read_text(encoding="utf-8")) == {}
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert len(list(cfg.parent.glob("config.json.corrupt-*"))) == 1  # 보관본은 남는다
    pub = settings.public()
    assert pub["config_broken"] is False and pub["config_backup"] == ""
    settings.update(model="gemini-3.8-flash")
    assert settings.model() == ("gemini-3.8-flash", "file")


def test_reset_refuses_healthy_file(cfg):
    settings.update(api_key="AIza-keep-5678")
    with pytest.raises(ValueError):
        settings.reset_broken()
    assert settings.api_key()[0] == "AIza-keep-5678"


def test_web_refuses_with_409_and_reset_route(client, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(BROKEN, encoding="utf-8")
    assert client.get("/api/config").json()["config_broken"] is True
    r = client.put("/api/config", json={"model": "x"})
    assert r.status_code == 409 and r.json()["code"] == "config_broken"
    assert "기본값으로 새로 시작" in r.json()["detail"]
    assert client.post("/api/config/presets", json={"name": "a", "stages": {"write": "local"}}).status_code == 409
    assert client.delete("/api/usage/prices").status_code == 409
    assert cfg.read_text(encoding="utf-8") == BROKEN
    r = client.post("/api/config/reset")
    assert r.status_code == 200 and r.json()["config_broken"] is False
    assert client.put("/api/config", json={"model": "x"}).status_code == 200
    assert client.post("/api/config/reset").status_code == 400  # 깨지지 않은 파일은 새로 시작하지 않는다
    assert json.loads(cfg.read_text(encoding="utf-8"))["model"] == "x"


def test_concurrent_updates_keep_both_keys(cfg, monkeypatch):
    """단계 칸 PUT 두 개가 겹쳐도 두 단계 값이 모두 남는다 (읽기와 쓰기 사이에 다른 쓰기가 끼면 한쪽이 사라졌다)."""
    settings.update(model="m")
    real_write = settings._write

    def slow_write(data):
        time.sleep(0.05)  # 읽은 뒤 쓰기 전에 다른 스레드가 끼어들 틈
        real_write(data)

    monkeypatch.setattr(settings, "_write", slow_write)
    errors = []

    def put(stage, value):
        try:
            settings.update(stages={stage: value})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=put, args=("write", "local")), threading.Thread(target=put, args=("check", "claude"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["stages"] == {"write": "local", "check": "claude"}
    assert data["model"] == "m"


def test_unreadable_file_is_not_reset_or_kept(cfg, monkeypatch):
    """권한 등으로 읽지 못한 파일은 깨진 파일과 다르다: 보관하지 않고, 새로 시작도 거절한다 (권한을 고치면 키가 돌아온다)."""
    cfg.write_text(json.dumps({"model": "m"}), encoding="utf-8")
    real = type(cfg).read_bytes

    def deny(self):
        if self == cfg:
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(type(cfg), "read_bytes", deny)
    assert settings._load() == ({}, "unreadable")
    pub = settings.public()
    assert pub["config_broken"] is True and pub["config_unreadable"] is True and pub["config_backup"] == ""
    with pytest.raises(settings.ConfigBroken, match="권한"):
        settings.update(model="x")
    with pytest.raises(ValueError, match="권한"):
        settings.reset_broken()
    monkeypatch.setattr(type(cfg), "read_bytes", real)
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"model": "m"}  # 파일은 그대로
    assert not list(cfg.parent.glob("config.json.corrupt-*"))


def test_failed_backup_leaves_no_partial_file_and_is_not_retried(cfg, monkeypatch):
    """보관본을 쓰다 실패하면(디스크 가득 등) 반쪽 파일을 지우고, 읽을 때마다 다시 시도하지 않는다."""
    cfg.write_text(BROKEN, encoding="utf-8")
    opened = []
    real_open = settings.os.open

    def counting_open(path, *a, **k):
        opened.append(str(path))
        return real_open(path, *a, **k)

    class Full:
        def __init__(self, fd, mode):
            self.fd = fd

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            settings.os.close(self.fd)

        def fileno(self):
            return self.fd

        def write(self, raw):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(settings.os, "open", counting_open)
    monkeypatch.setattr(settings.os, "fdopen", Full)
    for _ in range(5):
        settings.model()
    assert not list(cfg.parent.glob("config.json.corrupt-*"))
    assert len(opened) == 1  # 같은 내용은 한 번만 시도한다
    assert settings.public()["config_backup"] == ""
