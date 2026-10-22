"""사용자 설정 (LLM 프로바이더, 모델, API 키).

웹 설정 화면에서 저장하면 ~/.canon/config.json 에 들어간다 (CANON_CONFIG 로 경로 변경).
환경 변수가 있으면 파일보다 우선한다: CANON_LLM, CANON_MODEL, GEMINI_API_KEY(또는 GOOGLE_API_KEY).
파일은 작품 폴더와 따로 두어 저장소나 project.json 에 키가 섞이지 않게 한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MODEL = "gemini-2.5-pro"


def config_path() -> Path:
    return Path(os.environ.get("CANON_CONFIG", "~/.canon/config.json")).expanduser()


def _read() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)  # 키가 들어 있으므로 본인만 읽게 한다


def _pick(env_names: tuple[str, ...], file_value: str | None, default: str = "") -> tuple[str, str]:
    """(값, 출처) 를 돌려준다. 출처는 env | file | default."""
    for name in env_names:
        if os.environ.get(name):
            return os.environ[name], "env"
    if file_value:
        return file_value, "file"
    return default, "default"


def provider() -> tuple[str, str]:
    value, src = _pick(("CANON_LLM",), _read().get("provider"), "gemini")
    return value.lower(), src


def model() -> tuple[str, str]:
    return _pick(("CANON_MODEL",), _read().get("model"), DEFAULT_MODEL)


def api_key() -> tuple[str, str]:
    return _pick(("GEMINI_API_KEY", "GOOGLE_API_KEY"), _read().get("gemini_api_key"))


def update(*, provider: str | None = None, model: str | None = None,
           api_key: str | None = None, clear_key: bool = False) -> None:
    """None 인 값은 그대로 둔다. 빈 문자열이면 파일에서 지운다."""
    data = _read()
    for key, value in (("provider", provider), ("model", model), ("gemini_api_key", api_key)):
        if value is None:
            continue
        if value.strip():
            data[key] = value.strip()
        else:
            data.pop(key, None)
    if clear_key:
        data.pop("gemini_api_key", None)
    _write(data)


def public() -> dict:
    """화면에 보여줄 설정. 키 원문은 내보내지 않는다."""
    prov, prov_src = provider()
    mdl, mdl_src = model()
    key, key_src = api_key()
    return {
        "provider": prov,
        "provider_source": prov_src,
        "model": "mock" if prov == "mock" else mdl,
        "model_setting": mdl,
        "model_source": mdl_src,
        "has_key": prov == "mock" or bool(key),
        "key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("설정됨" if key else ""),
        "key_source": key_src if key else "none",
        "path": str(config_path()),
    }
