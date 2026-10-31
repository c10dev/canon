"""사용자 설정 (LLM 프로바이더, 모델, API 키, 로컬 서버, 단계별 백엔드).

웹 설정 화면에서 저장하면 ~/.canon/config.json 에 들어간다 (CANON_CONFIG 로 경로 변경).
환경 변수가 있으면 파일보다 우선한다: CANON_LLM, CANON_MODEL, GEMINI_API_KEY(또는 GOOGLE_API_KEY),
CANON_LOCAL_URL, CANON_LOCAL_MODEL, CANON_LOCAL_KEY, CANON_LLM_PLAN / _WRITE / _CHECK / _STATE / _NAME / _REVISE,
CANON_MODEL_PLAN / _WRITE / _CHECK / _STATE / _NAME / _REVISE (단계별 모델), CANON_CLAUDE_MODEL, CANON_CLAUDE_BIN,
ANTHROPIC_API_KEY (Claude 백엔드, claude.py), CANON_GEMINI_AUTH(key | vertex, 또는 GOOGLE_GENAI_USE_VERTEXAI=true),
CANON_VERTEX_CREDENTIALS(또는 GOOGLE_APPLICATION_CREDENTIALS), GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION (Vertex AI). prices 는 AI 요금 가격표에서 고친 줄 (usage.py).
작품이 단계 프리셋을 고르면(Settings.model_preset) 그 작품의 호출에서는 프리셋이 설정 파일의 단계 칸을 대신한다 (project_preset).
Claude 구독 로그인은 Claude Code 가 직접 관리하므로 여기에 계정 정보나 토큰을 두지 않는다.
파일은 작품 폴더와 따로 두어 저장소나 project.json 에 키가 섞이지 않게 한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MODEL = "gemini-4-argon"
DEFAULT_VERTEX_LOCATION = "global"  # 새 Gemini 모델은 global 엔드포인트에 먼저 나온다
DEFAULT_LOCAL_URL = "http://localhost:11434/v1"  # Ollama. llama.cpp 는 :8080/v1, vLLM 은 :8000/v1
# claude: 설치된 Claude Code 의 구독 로그인, claude-api: Anthropic API 키 (claude.py)
PROVIDERS = ("gemini", "local", "claude", "claude-api", "mock")
# 단계: plan(설정 제안, 문체 분석, 기승전결, 화별 플롯) / write(본문) / check(검수) / state(상태 추출)
# / name(이름·지명 AI 추천) / revise(본문 부분 수정) / illustration(삽화 프롬프트) / play(플레이 모드 장면)
STAGES = ("plan", "write", "check", "state", "name", "revise", "illustration", "play")
# 따로 정하지 않으면 이 단계의 설정을 따른다 (이름 추천 · 삽화 프롬프트는 계획 단계 일이고, 부분 수정 · 플레이 장면은 본문 쓰기 일이다)
STAGE_PARENT = {"name": "plan", "revise": "write", "illustration": "plan", "play": "write"}
# 단계별 백엔드 · 모델 묶음. 고르면 설정 화면의 단계 칸을 채운다 (적지 않은 단계는 비워서 부모 단계나 생성 방식을 따른다).
# 작가가 만든 묶음은 설정 파일 stage_presets 에 둔다 (save_preset).
BUILTIN_PRESETS = (
    {"id": "gemini", "name": "Gemini",
     "stages": {"plan": "gemini", "write": "gemini", "check": "gemini", "state": "gemini"},
     "stage_models": {"plan": "gemini-4-argon", "write": "gemini-4-argon", "check": "gemini-4-argon",
                      "state": "gemini-3.8-flash", "name": "gemini-3.8-flash"}},
    {"id": "anthropic", "name": "Anthropic (Claude API 키)",
     "stages": {"plan": "claude-api", "write": "claude-api", "check": "claude-api", "state": "claude-api"},
     "stage_models": {"plan": "claude-opus-5-5", "write": "claude-opus-5-5", "check": "claude-opus-5-5",
                      "state": "claude-sonnet-5-5", "name": "claude-haiku-5-5"}},
)
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


def gemini_auth() -> tuple[str, str]:
    """Gemini 를 부르는 방식. key: AI Studio API 키 / vertex: Google Cloud 서비스 계정(Vertex AI)."""
    value, src = _pick(("CANON_GEMINI_AUTH",), _read().get("gemini_auth"), "key")
    if src != "env" and os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes"):
        value, src = "vertex", "env"  # google-genai 가 쓰는 환경 변수도 따른다
    value = value.lower()
    return (value if value in ("key", "vertex") else "key"), src


def vertex_credentials() -> tuple[str, str]:
    """서비스 계정 JSON 키 파일 경로. 파일 내용은 설정에 옮기지 않고 경로만 둔다.
    비우면 gcloud auth application-default login 으로 만든 기본 자격 증명을 쓴다."""
    value, src = _pick(("CANON_VERTEX_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS"), _read().get("vertex_credentials"))
    return (str(Path(value).expanduser()) if value else ""), src


def _key_file_project(path: str) -> str:
    """서비스 계정 키 파일의 project_id. 다른 칸(비밀 키)은 읽어 두지 않는다."""
    try:
        return str(json.loads(Path(path).read_text(encoding="utf-8")).get("project_id") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def vertex_project() -> tuple[str, str]:
    """Google Cloud 프로젝트 ID. 비우면 키 파일의 project_id 를 쓴다 (출처 key_file)."""
    value, src = _pick(("GOOGLE_CLOUD_PROJECT",), _read().get("vertex_project"))
    if value:
        return value, src
    from_file = _key_file_project(vertex_credentials()[0]) if vertex_credentials()[0] else ""
    return (from_file, "key_file") if from_file else ("", "default")


def vertex_location() -> tuple[str, str]:
    return _pick(("GOOGLE_CLOUD_LOCATION",), _read().get("vertex_location"), DEFAULT_VERTEX_LOCATION)


def local_url() -> tuple[str, str]:
    """OpenAI 호환 서버 주소 (/v1 까지). Ollama, llama.cpp, vLLM, LM Studio 모두 같은 형식."""
    return _pick(("CANON_LOCAL_URL",), _read().get("local_url"), DEFAULT_LOCAL_URL)


def local_model() -> tuple[str, str]:
    """비워 두면 서버에 모델이 하나뿐일 때 그 모델을 쓴다."""
    return _pick(("CANON_LOCAL_MODEL",), _read().get("local_model"))


def local_key() -> tuple[str, str]:
    """vLLM --api-key 처럼 서버가 키를 요구할 때만."""
    return _pick(("CANON_LOCAL_KEY",), _read().get("local_key"))


def claude_model() -> tuple[str, str]:
    """Claude 백엔드 기본 모델. 비우면 구독은 Claude Code 기본 모델, API 는 claude.DEFAULT_API_MODEL."""
    return _pick(("CANON_CLAUDE_MODEL",), _read().get("claude_model"))


def claude_bin() -> tuple[str, str]:
    """claude 실행 파일 경로. 비우면 PATH 와 흔한 설치 위치에서 찾는다."""
    return _pick(("CANON_CLAUDE_BIN",), _read().get("claude_bin"))


def anthropic_key() -> tuple[str, str]:
    """claude-api 백엔드의 Anthropic API 키 (Claude Console 에서 발급). 구독 로그인 토큰이 아니다."""
    return _pick(("ANTHROPIC_API_KEY",), _read().get("anthropic_api_key"))


def local_sampling() -> dict:
    """본문 생성용 샘플링 값. 설정 파일의 local_sampling 이 기본값을 덮는다."""
    return {**DEFAULT_SAMPLING, **(_read().get("local_sampling") or {})}


_CURRENT: dict = {}  # stage_provider · stage_model 의 preset 기본값: 지금 작업의 작품이 고른 프리셋


def project_preset(name: str | None = None) -> dict | None:
    """작품이 고른 단계 프리셋 (Settings.model_preset). name 이 없으면 지금 작업의 작품(usage.scope 의 project).
    고르지 않았거나 고른 프리셋이 지워졌으면 None 이고, 그러면 전체 설정의 단계 칸을 따른다."""
    if name is None:
        from . import usage

        name = usage.context().get("project")
    if not name:
        return None
    from . import store

    preset_id = store.model_preset(name)
    return find_preset(preset_id) if preset_id else None


def _stage_value(kind: str, key: str, stage: str, preset: dict | None) -> tuple[str, str]:
    """단계 칸 하나. 단계 환경 변수 → 작품 프리셋(출처 project) → 설정 파일. 작품 프리셋이 있으면 설정 파일의 단계 칸은 보지 않는다
    (설정 화면에서 프리셋을 고른 것과 같다: 프리셋에 없는 단계는 부모 단계나 생성 방식을 따른다)."""
    stage_map = (preset.get(key) or {}) if preset is not None else (_read().get(key) or {})
    value, src = _pick((f"CANON_{kind}_{stage.upper()}",), stage_map.get(stage))
    return value, ("project" if src == "file" and preset is not None else src)


def stage_provider(stage: str | None, preset: dict | None = _CURRENT) -> tuple[str, str]:
    """단계별 백엔드. 지정이 없으면 전체 provider 를 따른다. mock 이면 모든 단계가 mock.
    preset 을 주지 않으면 지금 작업의 작품 프리셋(project_preset)을 쓰고, None 이면 전체 설정만 본다."""
    base = provider()
    if stage is None or base[0] == "mock":
        return base
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 단계: {stage}")
    if preset is _CURRENT:
        preset = project_preset()
    value, src = _stage_value("LLM", "stages", stage, preset)
    if value:
        return value.lower(), src
    return stage_provider(STAGE_PARENT[stage], preset) if stage in STAGE_PARENT else base


def stage_model(stage: str | None, preset: dict | None = _CURRENT) -> tuple[str, str]:
    """단계별 모델 이름. 비어 있으면 그 단계 백엔드의 기본 모델(model 또는 local_model)을 쓴다.
    예: 상태 변경안만 gemini-3.8-flash 로 돌려 비용과 시간을 줄인다.
    이름 추천처럼 부모 단계가 있으면, 백엔드를 따로 정하지 않은 동안은 부모 단계 모델도 따른다. preset 은 stage_provider 와 같다."""
    if stage is None or stage not in STAGES:
        return "", "default"
    if preset is _CURRENT:
        preset = project_preset()
    value, src = _stage_value("MODEL", "stage_models", stage, preset)
    parent = STAGE_PARENT.get(stage)
    if not value and parent and stage_provider(stage, preset) == stage_provider(parent, preset):
        return stage_model(parent, preset)
    return value, src


def stage_env(stage: str, kind: str = "LLM") -> str:
    """이 단계의 백엔드(kind="LLM") 또는 모델(kind="MODEL")을 정한 환경 변수 이름. 설정 파일이나 기본값이 정했으면 "".
    물려받은 값이면 부모 단계나 전체 값의 변수 이름을 준다 (예: CANON_LLM 만 있으면 모든 단계가 CANON_LLM)."""
    if kind == "LLM" and provider()[0] == "mock":
        return "CANON_LLM" if provider()[1] == "env" else ""
    own = f"CANON_{kind}_{stage.upper()}"
    if os.environ.get(own):
        return own
    if ((_read().get("stages" if kind == "LLM" else "stage_models")) or {}).get(stage):
        return ""
    parent = STAGE_PARENT.get(stage)
    if kind == "LLM":
        if parent:
            return stage_env(parent, kind)
        return "CANON_LLM" if provider()[1] == "env" else ""
    return stage_env(parent, kind) if parent and stage_provider(stage) == stage_provider(parent) else ""


def _set_stage_map(data: dict, key: str, values: dict[str, str]) -> None:
    cur = {k: v for k, v in (data.get(key) or {}).items() if k in STAGES}
    for stage, value in values.items():
        if stage not in STAGES:
            raise ValueError(f"알 수 없는 단계: {stage}")
        if value and value.strip():
            cur[stage] = value.strip()
        else:
            cur.pop(stage, None)  # 빈 값이면 기본을 따른다
    if cur:
        data[key] = cur
    else:
        data.pop(key, None)


CLAUDE_BIN_NAMES = ("claude", "claude.exe", "claude.cmd")  # 설정 파일의 claude_bin 으로 받는 파일 이름


def update(*, provider: str | None = None, model: str | None = None,
           api_key: str | None = None, clear_key: bool = False,
           local_url: str | None = None, local_model: str | None = None,
           local_key: str | None = None, stages: dict[str, str] | None = None,
           stage_models: dict[str, str] | None = None, claude_model: str | None = None,
           claude_bin: str | None = None, anthropic_api_key: str | None = None,
           clear_anthropic_key: bool = False, gemini_auth: str | None = None,
           vertex_credentials: str | None = None, vertex_project: str | None = None,
           vertex_location: str | None = None) -> None:
    """None 인 값은 그대로 둔다. 빈 문자열이면 파일에서 지운다."""
    if claude_bin and claude_bin.strip() and Path(claude_bin.strip()).name.lower() not in CLAUDE_BIN_NAMES:
        # 설정 화면(로그인 없는 웹 API)으로 아무 실행 파일이나 부르게 하지 않는다. 다른 이름은 CANON_CLAUDE_BIN 으로
        raise ValueError("claude 실행 파일 경로만 적을 수 있어요 (파일 이름이 claude). 다른 이름이면 CANON_CLAUDE_BIN으로 정하세요")
    data = _read()
    for key, value in (("provider", provider), ("model", model), ("gemini_api_key", api_key),
                       ("local_url", local_url), ("local_model", local_model), ("local_key", local_key),
                       ("claude_model", claude_model), ("claude_bin", claude_bin),
                       ("anthropic_api_key", anthropic_api_key), ("gemini_auth", gemini_auth),
                       ("vertex_credentials", vertex_credentials), ("vertex_project", vertex_project),
                       ("vertex_location", vertex_location)):
        if value is None:
            continue
        if value.strip():
            data[key] = value.strip()
        else:
            data.pop(key, None)
    if clear_key:
        data.pop("gemini_api_key", None)
    if clear_anthropic_key:
        data.pop("anthropic_api_key", None)
    if stages is not None:
        _set_stage_map(data, "stages", stages)  # 빈 값이면 전체 provider 를 따른다
    if stage_models is not None:
        _set_stage_map(data, "stage_models", stage_models)  # 빈 값이면 백엔드 기본 모델
    _write(data)


def _clean_stage_map(values: dict[str, str] | None, providers: bool) -> dict[str, str]:
    out = {}
    for stage, value in (values or {}).items():
        if stage not in STAGES:
            raise ValueError(f"알 수 없는 단계예요: {stage}")
        value = (value or "").strip()
        if providers and value and value not in PROVIDERS:
            raise ValueError(f"알 수 없는 백엔드예요: {stage}={value}")
        if value:
            out[stage] = value
    return out


def presets() -> list[dict]:
    """기본 묶음 다음에 작가가 저장한 묶음. 저장한 것은 builtin=False."""
    mine = [p for p in _read().get("stage_presets") or [] if isinstance(p, dict) and p.get("id") and p.get("name")]
    return ([{**p, "builtin": True} for p in BUILTIN_PRESETS]
            + [{"id": p["id"], "name": p["name"], "stages": p.get("stages") or {},
                "stage_models": p.get("stage_models") or {}, "builtin": False} for p in mine])


def find_preset(preset_id: str) -> dict | None:
    return next((p for p in presets() if p["id"] == preset_id), None)


def save_preset(name: str, stages: dict[str, str] | None, stage_models: dict[str, str] | None) -> dict:
    """단계 칸을 이름 붙여 저장한다. 같은 이름의 내 묶음이 있으면 덮는다. 기본 묶음 이름은 쓸 수 없다."""
    name = (name or "").strip()
    if not name:
        raise ValueError("프리셋 이름을 적어 주세요")
    if any(p["name"] == name for p in BUILTIN_PRESETS):
        raise ValueError("기본 프리셋과 같은 이름이에요. 다른 이름을 적어 주세요")
    item = {"name": name, "stages": _clean_stage_map(stages, True), "stage_models": _clean_stage_map(stage_models, False)}
    if not item["stages"] and not item["stage_models"]:
        raise ValueError("단계 칸이 모두 비어 있어요")
    data = _read()
    mine = [p for p in data.get("stage_presets") or [] if isinstance(p, dict)]
    old = next((p for p in mine if p.get("name") == name), None)
    item["id"] = old["id"] if old else f"my-{os.urandom(4).hex()}"
    data["stage_presets"] = [item if p is old else p for p in mine] + ([] if old else [item])
    _write(data)
    return {**item, "builtin": False}


def delete_preset(preset_id: str) -> None:
    if any(p["id"] == preset_id for p in BUILTIN_PRESETS):
        raise ValueError("기본 프리셋은 지울 수 없어요")
    data = _read()
    mine = [p for p in data.get("stage_presets") or [] if isinstance(p, dict)]
    rest = [p for p in mine if p.get("id") != preset_id]
    if len(rest) == len(mine):
        raise KeyError(preset_id)
    if rest:
        data["stage_presets"] = rest
    else:
        data.pop("stage_presets", None)
    _write(data)


def prices() -> list[dict]:
    """사용자가 고친 AI 요금 가격표 줄 (usage.Price 모양). 기본 가격표는 canon/usage.py 에 있다."""
    rows = _read().get("prices")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def set_prices(rows: list[dict]) -> None:
    data = _read()
    if rows:
        data["prices"] = rows
    else:
        data.pop("prices", None)
    _write(data)


def stage_view(preset: dict | None) -> dict[str, dict]:
    """단계마다 실제로 쓰는 백엔드와 모델 이름(비우면 백엔드 기본 모델 이름)과 출처. preset 은 stage_provider 와 같다."""
    mdl, lmodel, cmodel = model()[0], local_model()[0], claude_model()[0]
    out = {}
    for s in STAGES:
        sp, ssrc = stage_provider(s, preset)
        sm, smsrc = stage_model(s, preset)
        label = {"gemini": mdl, "local": lmodel or "로컬 서버 모델", "mock": "mock",
                 "claude": cmodel or "Claude Code 기본 모델", "claude-api": cmodel or "claude-opus-5-5"}.get(sp, sp)
        if sm and sp != "mock":
            label = sm
        out[s] = {"provider": sp, "source": ssrc, "model": label, "model_source": smsrc}
    return out


def public() -> dict:
    """화면에 보여줄 설정. 키 원문은 내보내지 않는다."""
    prov, prov_src = provider()
    mdl, mdl_src = model()
    key, key_src = api_key()
    lurl, lurl_src = local_url()
    lmodel, lmodel_src = local_model()
    cmodel, cmodel_src = claude_model()
    akey, akey_src = anthropic_key()
    auth, auth_src = gemini_auth()
    vcred, vcred_src = vertex_credentials()
    vproj, vproj_src = vertex_project()
    vloc, vloc_src = vertex_location()
    # Vertex 는 키 문자열 대신 프로젝트(와 키 파일 또는 기본 자격 증명)가 있으면 부를 수 있다
    gemini_ready = bool(vproj) and (not vcred or Path(vcred).is_file()) if auth == "vertex" else bool(key)
    stages = {s: {**v, "env": stage_env(s), "model_env": stage_env(s, "MODEL")} for s, v in stage_view(None).items()}
    return {
        "provider": prov,
        "provider_source": prov_src,
        "model": "mock" if prov == "mock" else mdl,
        "model_setting": mdl,
        "model_source": mdl_src,
        # 모든 단계를 로컬로 돌리면 Gemini 키가 없어도 된다
        "has_key": prov == "mock" or gemini_ready or all(v["provider"] != "gemini" for v in stages.values()),
        "key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("설정됨" if key else ""),
        "key_source": key_src if key else "none",
        "gemini_auth": auth,
        "gemini_auth_source": auth_src,
        "vertex_credentials": vcred,
        "vertex_credentials_source": vcred_src if vcred else "none",
        "vertex_credentials_found": bool(vcred) and Path(vcred).is_file(),
        "vertex_project": vproj,
        "vertex_project_source": vproj_src,
        "vertex_location": vloc,
        "vertex_location_source": vloc_src,
        "local_url": lurl,
        "local_url_source": lurl_src,
        "local_model": lmodel,
        "local_model_source": lmodel_src,
        "has_local_key": bool(local_key()[0]),
        "claude_model": cmodel,
        "claude_model_source": cmodel_src,
        "claude_bin": claude_bin()[0],
        "claude_bin_source": claude_bin()[1],
        "anthropic_key_hint": f"…{akey[-4:]}" if len(akey) >= 8 else ("설정됨" if akey else ""),
        "anthropic_key_source": akey_src if akey else "none",
        "stages": stages,
        "stage_settings": {k: v for k, v in (_read().get("stages") or {}).items() if k in STAGES},
        "stage_model_settings": {k: v for k, v in (_read().get("stage_models") or {}).items() if k in STAGES},
        "stage_presets": presets(),
        "local_sampling": local_sampling(),
        "path": str(config_path()),
    }
