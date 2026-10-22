"""사용자 설정 (LLM 프로바이더, 모델, API 키, 로컬 서버, 단계별 백엔드).

웹 설정 화면에서 저장하면 ~/.canon/config.json 에 들어간다 (CANON_CONFIG 로 경로 변경).
환경 변수가 있으면 파일보다 우선한다: CANON_LLM, CANON_MODEL, GEMINI_API_KEY(또는 GOOGLE_API_KEY),
CANON_LOCAL_URL, CANON_LOCAL_MODEL, CANON_LOCAL_KEY, CANON_LLM_PLAN / _WRITE / _CHECK / _STATE.
파일은 작품 폴더와 따로 두어 저장소나 project.json 에 키가 섞이지 않게 한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MODEL = "gemini-4-argon"
DEFAULT_LOCAL_URL = "http://localhost:11434/v1"  # Ollama. llama.cpp 는 :8080/v1, vLLM 은 :8000/v1
PROVIDERS = ("gemini", "local", "mock")
# 단계: plan(설정 제안, 문체 분석, 기승전결, 화별 플롯) / write(본문) / check(검수) / state(상태 추출)
STAGES = ("plan", "write", "check", "state")
# 로컬 본문 생성 기본 샘플링. 구조화 출력(json)에는 쓰지 않는다.
DEFAULT_SAMPLING = {"temperature": 1.0, "top_p": 0.95, "min_p": 0.05}


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


def local_url() -> tuple[str, str]:
    """OpenAI 호환 서버 주소 (/v1 까지). Ollama, llama.cpp, vLLM, LM Studio 모두 같은 형식."""
    return _pick(("CANON_LOCAL_URL",), _read().get("local_url"), DEFAULT_LOCAL_URL)


def local_model() -> tuple[str, str]:
    """비워 두면 서버에 모델이 하나뿐일 때 그 모델을 쓴다."""
    return _pick(("CANON_LOCAL_MODEL",), _read().get("local_model"))


def local_key() -> tuple[str, str]:
    """vLLM --api-key 처럼 서버가 키를 요구할 때만."""
    return _pick(("CANON_LOCAL_KEY",), _read().get("local_key"))


def local_sampling() -> dict:
    """본문 생성용 샘플링 값. 설정 파일의 local_sampling 이 기본값을 덮는다."""
    return {**DEFAULT_SAMPLING, **(_read().get("local_sampling") or {})}


def stage_provider(stage: str | None) -> tuple[str, str]:
    """단계별 백엔드. 지정이 없으면 전체 provider 를 따른다. mock 이면 모든 단계가 mock."""
    base = provider()
    if stage is None or base[0] == "mock":
        return base
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 단계: {stage}")
    value, src = _pick((f"CANON_LLM_{stage.upper()}",), (_read().get("stages") or {}).get(stage))
    return (value.lower(), src) if value else base


def update(*, provider: str | None = None, model: str | None = None,
           api_key: str | None = None, clear_key: bool = False,
           local_url: str | None = None, local_model: str | None = None,
           local_key: str | None = None, stages: dict[str, str] | None = None) -> None:
    """None 인 값은 그대로 둔다. 빈 문자열이면 파일에서 지운다."""
    data = _read()
    for key, value in (("provider", provider), ("model", model), ("gemini_api_key", api_key),
                       ("local_url", local_url), ("local_model", local_model), ("local_key", local_key)):
        if value is None:
            continue
        if value.strip():
            data[key] = value.strip()
        else:
            data.pop(key, None)
    if clear_key:
        data.pop("gemini_api_key", None)
    if stages is not None:
        cur = {k: v for k, v in (data.get("stages") or {}).items() if k in STAGES}
        for stage, value in stages.items():
            if stage not in STAGES:
                raise ValueError(f"알 수 없는 단계: {stage}")
            if value:
                cur[stage] = value
            else:
                cur.pop(stage, None)  # 빈 값이면 기본(전체 provider)을 따른다
        if cur:
            data["stages"] = cur
        else:
            data.pop("stages", None)
    _write(data)


def public() -> dict:
    """화면에 보여줄 설정. 키 원문은 내보내지 않는다."""
    prov, prov_src = provider()
    mdl, mdl_src = model()
    key, key_src = api_key()
    lurl, lurl_src = local_url()
    lmodel, lmodel_src = local_model()
    stages = {}
    for s in STAGES:
        sp, ssrc = stage_provider(s)
        label = {"gemini": mdl, "local": lmodel or "로컬 서버 모델", "mock": "mock"}.get(sp, sp)
        stages[s] = {"provider": sp, "source": ssrc, "model": label}
    return {
        "provider": prov,
        "provider_source": prov_src,
        "model": "mock" if prov == "mock" else mdl,
        "model_setting": mdl,
        "model_source": mdl_src,
        # 모든 단계를 로컬로 돌리면 Gemini 키가 없어도 된다
        "has_key": prov == "mock" or bool(key) or all(v["provider"] != "gemini" for v in stages.values()),
        "key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("설정됨" if key else ""),
        "key_source": key_src if key else "none",
        "local_url": lurl,
        "local_url_source": lurl_src,
        "local_model": lmodel,
        "local_model_source": lmodel_src,
        "has_local_key": bool(local_key()[0]),
        "stages": stages,
        "stage_settings": {k: v for k, v in (_read().get("stages") or {}).items() if k in STAGES},
        "path": str(config_path()),
    }
