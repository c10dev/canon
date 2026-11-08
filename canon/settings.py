"""사용자 설정 (LLM 프로바이더, 모델, API 키, 로컬 서버, 단계별 백엔드).

웹 설정 화면에서 저장하면 ~/.canon/config.json 에 들어간다 (CANON_CONFIG 로 경로 변경).
환경 변수가 있으면 파일보다 우선한다: CANON_LLM, CANON_MODEL, GEMINI_API_KEY(또는 GOOGLE_API_KEY),
CANON_LOCAL_URL, CANON_LOCAL_MODEL, CANON_LOCAL_KEY, CANON_LLM_<단계> (단계 이름은 STAGES, 예: CANON_LLM_WRITE),
CANON_MODEL_<단계> (단계별 모델, 예: CANON_MODEL_STATE), CANON_EFFORT_<단계> (예: CANON_EFFORT_CHECK)
(단계별 Claude 추론 강도), CANON_CLAUDE_MODEL, CANON_CLAUDE_BIN, CANON_CLAUDE_CONFIG_DIR,
ANTHROPIC_API_KEY (Claude 백엔드, claude.py), CANON_GEMINI_AUTH(key | vertex, 또는 GOOGLE_GENAI_USE_VERTEXAI=true),
CANON_VERTEX_CREDENTIALS(또는 GOOGLE_APPLICATION_CREDENTIALS), GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION (Vertex AI),
CANON_GEMINI_CACHE(0 이면 Gemini 명시 캐시를 끈다, gemini_cache).
gemini_cache_unsupported 는 명시 캐시를 받지 않는다고 API 가 답한 모델 (llm.GeminiLLM 이 적는다). prices 는 AI 요금 가격표에서 고친 줄 (usage.py).
작품이 단계 프리셋을 고르면(Settings.model_preset) 그 작품의 호출에서는 프리셋이 설정 파일의 단계 칸을 대신한다 (project_preset).
Claude 구독 로그인은 Claude Code 가 직접 관리하므로 여기에 계정 정보나 토큰을 두지 않는다.
claude_separate 는 Canon 전용 Claude Code 설정 폴더를 쓸지만 적는다 (claude_config_dir).
파일이 깨져 있으면 읽는 쪽은 기본값을 쓰고, 처음 만났을 때 config.json.corrupt-<시각> 로 보관하고, 쓰는 쪽은 ConfigBroken 으로 막는다 (_load).
파일은 작품 폴더와 따로 두어 저장소나 project.json 에 키가 섞이지 않게 한다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from . import store

DEFAULT_MODEL = "gemini-4-argon"
DEFAULT_VERTEX_LOCATION = "global"  # 새 Gemini 모델은 global 엔드포인트에 먼저 나온다
DEFAULT_LOCAL_URL = "http://localhost:11434/v1"  # Ollama. llama.cpp 는 :8080/v1, vLLM 은 :8000/v1
# claude: 설치된 Claude Code 의 구독 로그인, claude-api: Anthropic API 키 (claude.py)
PROVIDERS = ("gemini", "local", "claude", "claude-api", "mock")
# 단계: plan(설정 제안, 문체 분석, 기승전결, 화별 플롯) / write(본문) / check(검수) / state(상태 추출)
# / name(이름·지명 AI 추천) / revise(본문 부분 수정, 서술 다듬기) / illustration(삽화 프롬프트) / play(플레이 모드 장면)
# / chat(플롯 대화 에이전트, agent.run_turn)
STAGES = ("plan", "board", "write", "check", "state", "name", "revise", "illustration", "play", "chat")
# 따로 정하지 않으면 이 단계의 설정을 따른다 (스토리보드 · 큐 시트, 이름 추천, 삽화 프롬프트, 플롯 대화는 계획 단계 일이고, 부분 수정 · 플레이 장면은 본문 쓰기 일이다)
STAGE_PARENT = {"board": "plan", "name": "plan", "revise": "write", "illustration": "plan", "play": "write", "chat": "plan"}
# 단계별 추론 강도. 비우면 모델 기본값을 쓴다. 단계 프리셋에는 넣지 않는다 (설정 파일 stage_efforts 와 환경 변수만).
# Claude 는 EFFORTS 를 claude --effort · Messages API output_config.effort 로 넘긴다.
# Gemini 는 GEMINI_EFFORTS 를 thinking_level 로 넘긴다. minimal 은 gemini-4-argon · 3.8-flash 가 400 으로 거절한다 (2026-11-04).
# 로컬 · mock 은 이 값을 보지 않는다. 백엔드가 받지 않는 값은 provider_effort 가 가장 가까운 값으로 바꾼다.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
GEMINI_EFFORTS = ("low", "medium", "high")
CLAUDE_PROVIDERS = ("claude", "claude-api")
EFFORT_PROVIDERS = (*CLAUDE_PROVIDERS, "gemini")
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


# 설정 파일을 읽고-고치고-쓰는 동안 잡는 프로세스 안 잠금. 단계 칸 PUT 두 개나 LLM 스레드의 mark_gemini_cache_unsupported 가
# 겹쳐도 한쪽이 다른 쪽의 값을 지우지 않게 한다. CLI 와 서버처럼 다른 프로세스가 함께 쓰는 경우는 막지 않는다
_CONFIG_LOCK = threading.RLock()
# 깨진 설정 파일 (경로, 원문 sha256) → 보관본 경로. 같은 깨진 내용은 한 번만 보관한다
_backups: dict[tuple[str, str], str] = {}


class ConfigBroken(ValueError):
    """설정 파일이 깨져 있어 쓰지 않는다. 웹은 409 와 code config_broken 으로 답한다."""


def _keep_broken(path: Path, raw: bytes) -> str:
    """깨진 설정 파일을 config.json.corrupt-<시각> 로 한 번만 복사한다 (본인만 읽는 0o600, 키가 들어 있을 수 있다).
    같은 내용의 보관본이 이미 있으면 그 경로를 쓴다. 복사하지 못하면 ""."""
    key = (str(path), hashlib.sha256(raw).hexdigest())
    got = _backups.get(key)
    if got and Path(got).exists():
        return got
    try:
        for old in sorted(path.parent.glob(f"{path.name}.corrupt-*")):
            if old.read_bytes() == raw:
                _backups[key] = str(old)
                return str(old)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for n in range(100):
            dest = path.with_name(f"{path.name}.corrupt-{stamp}{f'-{n}' if n else ''}")
            try:
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(raw)
            break
        else:
            return ""
    except OSError:
        logging.getLogger("canon").warning("깨진 설정 파일을 보관하지 못했어요: %s", path)
        return ""
    logging.getLogger("canon").warning("설정 파일이 깨져 있어 %s 에 보관했어요. 고치기 전에는 설정을 저장하지 않아요", dest)
    _backups[key] = str(dest)
    return str(dest)


def _load() -> tuple[dict, bool]:
    """(설정, 깨졌는지). 파일이 없으면 ({}, False). JSON 이 아니거나 객체가 아니거나 읽지 못하면 ({}, True) 이고,
    처음 만났을 때 원문을 보관본으로 남긴다 (_keep_broken). 읽는 쪽은 {} 로 기본값을 쓰고, 쓰는 쪽은 _load_for_write 로 막는다."""
    path = config_path()
    with _CONFIG_LOCK:
        if not path.exists():
            return {}, False
        try:
            raw = path.read_bytes()
        except OSError:
            return {}, True
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            return data, False
        _keep_broken(path, raw)
        return {}, True


def _read() -> dict:
    return _load()[0]


def _write(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _CONFIG_LOCK:
        # 키가 들어 있으므로 처음부터 본인만 읽는 tmp 파일에 써서 바꿔 넣는다. 중간에 멈춰도 옛 설정이 그대로 남는다
        store.write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2), mode=0o600, fsync=True)


def broken_backup() -> str:
    """설정 파일이 깨져 있으면 보관본 경로 (보관하지 못했으면 ""). 깨지지 않았으면 ""."""
    path = config_path()
    with _CONFIG_LOCK:
        if not _load()[1]:
            return ""
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        return _keep_broken(path, raw)


def _broken_message() -> str:
    backup = broken_backup()
    kept = f"원래 내용은 {Path(backup).name}에 보관했어요. " if backup else "원래 내용을 보관하지 못했어요. "
    return (f"설정 파일({config_path().name})이 깨져 있어 저장하지 않았어요. {kept}"
            "설정 화면에서 '기본값으로 새로 시작'을 누르거나 파일을 고쳐 주세요")


def _load_for_write() -> dict:
    """쓰기 전에 읽는다. 깨진 파일이면 ConfigBroken: {} 위에 새 값만 넣어 덮으면 키 · 프리셋 · 가격표가 사라진다.
    부르는 쪽은 _CONFIG_LOCK 을 잡은 채 이것부터 _write 까지 한다."""
    data, broken = _load()
    if broken:
        raise ConfigBroken(_broken_message())
    return data


def reset_broken() -> None:
    """깨진 설정 파일을 빈 설정으로 바꾼다 (설정 화면 '기본값으로 새로 시작'). 보관본은 그대로 둔다.
    깨지지 않은 파일은 지우지 않는다 (키를 잃지 않게)."""
    with _CONFIG_LOCK:
        if not _load()[1]:
            raise ValueError("설정 파일이 깨져 있지 않아요. 새로 시작하지 않았어요")
        broken_backup()  # 보관본을 먼저 남긴다
        _write({})


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


def gemini_cache() -> tuple[str, str]:
    """Gemini 명시 캐시(llm.GeminiLLM 의 caches.create)를 쓸 곳. agent: 플롯 대화 단계(chat)만 / off: 쓰지 않는다.
    기본은 agent 다. 대화 한 턴은 몇 분 안에 같은 앞부분(약 10만 토큰)으로 여러 단계를 부르므로, 명시 캐시를 받는 모델에서
    캐시를 두 번 다시 쓰면 캐시를 만드는 요금과 저장 요금(10분)보다 아끼는 입력 요금이 크다고 본다 (가정).
    기본 모델 gemini-4-argon 은 명시 캐시를 받지 않는다 (2026-11-07 실측). 그런 모델은 gemini_cache_unsupported 에 남아 켜져 있어도 쓰지 않는다. 다른 단계는 같은 앞부분을 몇 분 안에 다시 부르는 일이 적어 켜지 않는다.
    환경 변수 CANON_GEMINI_CACHE=0 (또는 off) 로 끈다."""
    raw = _read().get("gemini_cache")
    if raw is False or raw == 0:  # JSON 의 false · 0 도 끈다 (bool 은 int 라 0 과 같이 본다)
        raw = "off"
    value, src = _pick(("CANON_GEMINI_CACHE",), None if raw is None else str(raw), "agent")
    value = value.strip().lower()
    if value in ("0", "off", "false", "no"):
        return "off", src
    return "agent", src


def gemini_cache_model_key(vertex: bool, model: str) -> str:
    """gemini_cache_unsupported 의 열쇠. API 키와 Vertex AI 는 같은 모델도 받는 기능이 다를 수 있어 나눈다."""
    return f"{'vertex' if vertex else 'key'}:{model}"


def gemini_cache_unsupported() -> dict[str, str]:
    """명시 캐시를 받지 않는다고 API 가 답한 모델 {열쇠(gemini_cache_model_key): 알게 된 날짜}.
    한 번 적히면 지울 때까지 그 모델에서 명시 캐시를 쓰지 않는다. 모델이 나중에 받게 되면 설정 파일에서 그 줄을 지운다."""
    raw = _read().get("gemini_cache_unsupported")
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def mark_gemini_cache_unsupported(vertex: bool, model: str) -> bool:
    """그 모델이 명시 캐시를 받지 않는다고 설정 파일에 적는다. 새로 적었으면 참.
    설정 파일을 읽지 못하면(깨진 JSON) 적지 않는다. 다른 설정을 지우지 않게 하려는 것이다."""
    from datetime import date

    with _CONFIG_LOCK:
        data, broken = _load()
        if broken:
            return False
        seen = data.get("gemini_cache_unsupported")
        seen = dict(seen) if isinstance(seen, dict) else {}
        key = gemini_cache_model_key(vertex, model)
        if key in seen:
            return False
        seen[key] = date.today().isoformat()
        data["gemini_cache_unsupported"] = seen
        _write(data)
        return True


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


def claude_config_dir() -> tuple[str, str]:
    """Canon 이 부르는 Claude Code 의 설정 폴더(CLAUDE_CONFIG_DIR). 비우면 이 컴퓨터의 Claude Code 로그인을 같이 쓴다.
    설정 파일의 claude_separate 를 켜면 설정 파일 옆 claude-code 폴더를 써서 Canon 만 다른 계정으로 로그인한다.
    로그인과 토큰 보관은 그 폴더에서 Claude Code 가 하고 Canon 은 폴더 경로만 넘긴다 (claude.py)."""
    env = os.environ.get("CANON_CLAUDE_CONFIG_DIR", "").strip()
    if env:
        return str(Path(env).expanduser()), "env"
    if _read().get("claude_separate"):
        return str(config_path().parent / "claude-code"), "file"
    return "", "default"


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


def provider_effort(provider: str, value: str) -> str:
    """그 백엔드에 넘길 추론 강도. Gemini 는 xhigh · max 를 high 로 받는다. 강도를 받지 않는 백엔드와 모르는 값은 ""."""
    if provider in CLAUDE_PROVIDERS:
        return value if value in EFFORTS else ""
    if provider == "gemini":
        return "high" if value in ("xhigh", "max") else (value if value in GEMINI_EFFORTS else "")
    return ""


def stage_effort(stage: str | None, preset: dict | None = _CURRENT) -> tuple[str, str]:
    """단계별 추론 강도와 출처. 백엔드에 넘길 값은 provider_effort 로 바꾼다. 단계 환경 변수(CANON_EFFORT_CHECK 등) → 설정 파일 stage_efforts.
    비어 있으면 부모 단계가 같은 백엔드일 때 부모 값을 따르고, 그래도 없으면 ""(모델 기본값).
    EFFORTS 밖의 값은 ""로 본다. preset 은 부모 단계의 백엔드를 비교할 때만 쓴다."""
    if stage is None or stage not in STAGES:
        return "", "default"
    if preset is _CURRENT:
        preset = project_preset()
    value, src = _pick((f"CANON_EFFORT_{stage.upper()}",), (_read().get("stage_efforts") or {}).get(stage))
    value = value.lower()
    if value in EFFORTS:
        return value, src
    parent = STAGE_PARENT.get(stage)
    if parent and stage_provider(stage, preset) == stage_provider(parent, preset):
        return stage_effort(parent, preset)
    return "", "default"


def stage_env(stage: str, kind: str = "LLM") -> str:
    """이 단계의 백엔드(kind="LLM"), 모델(kind="MODEL") 또는 추론 강도(kind="EFFORT")를 정한 환경 변수 이름. 설정 파일이나 기본값이 정했으면 "".
    물려받은 값이면 부모 단계나 전체 값의 변수 이름을 준다 (예: CANON_LLM 만 있으면 모든 단계가 CANON_LLM)."""
    if kind == "LLM" and provider()[0] == "mock":
        return "CANON_LLM" if provider()[1] == "env" else ""
    own = f"CANON_{kind}_{stage.upper()}"
    if os.environ.get(own):
        return own
    key = {"LLM": "stages", "MODEL": "stage_models", "EFFORT": "stage_efforts"}[kind]
    if (_read().get(key) or {}).get(stage):
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
           vertex_location: str | None = None, stage_efforts: dict[str, str] | None = None,
           claude_separate: bool | None = None) -> None:
    """None 인 값은 그대로 둔다. 빈 문자열이면 파일에서 지운다."""
    bad = [f"{k}={v}" for k, v in (stage_efforts or {}).items() if (v or "").strip() and v.strip().lower() not in EFFORTS]
    if bad:
        raise ValueError(f"추론 강도는 {' / '.join(EFFORTS)} 중 하나예요: {', '.join(bad)}")
    if claude_bin and claude_bin.strip() and Path(claude_bin.strip()).name.lower() not in CLAUDE_BIN_NAMES:
        # 설정 화면(로그인 없는 웹 API)으로 아무 실행 파일이나 부르게 하지 않는다. 다른 이름은 CANON_CLAUDE_BIN 으로
        raise ValueError("claude 실행 파일 경로만 적을 수 있어요 (파일 이름이 claude). 다른 이름이면 CANON_CLAUDE_BIN으로 정하세요")
    with _CONFIG_LOCK:
        data = _load_for_write()
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
        if claude_separate is not None:  # 끄면 지운다. 전용 폴더의 로그인은 지우지 않아 다시 켜면 그대로 쓴다
            if claude_separate:
                data["claude_separate"] = True
            else:
                data.pop("claude_separate", None)
        if stages is not None:
            _set_stage_map(data, "stages", stages)  # 빈 값이면 전체 provider 를 따른다
        if stage_models is not None:
            _set_stage_map(data, "stage_models", stage_models)  # 빈 값이면 백엔드 기본 모델
        if stage_efforts is not None:
            _set_stage_map(data, "stage_efforts", {k: (v or "").strip().lower() for k, v in stage_efforts.items()})  # 빈 값이면 모델 기본값
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
    with _CONFIG_LOCK:
        data = _load_for_write()
        mine = [p for p in data.get("stage_presets") or [] if isinstance(p, dict)]
        old = next((p for p in mine if p.get("name") == name), None)
        item["id"] = old["id"] if old else f"my-{os.urandom(4).hex()}"
        data["stage_presets"] = [item if p is old else p for p in mine] + ([] if old else [item])
        _write(data)
    return {**item, "builtin": False}


def delete_preset(preset_id: str) -> None:
    if any(p["id"] == preset_id for p in BUILTIN_PRESETS):
        raise ValueError("기본 프리셋은 지울 수 없어요")
    with _CONFIG_LOCK:
        data = _load_for_write()
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
    with _CONFIG_LOCK:
        data = _load_for_write()
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
        eff, esrc = stage_effort(s, preset) if sp in EFFORT_PROVIDERS else ("", "default")
        eff = provider_effort(sp, eff)
        out[s] = {"provider": sp, "source": ssrc, "model": label, "model_source": smsrc,
                  "effort": eff, "effort_source": esrc}
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
    stages = {s: {**v, "env": stage_env(s), "model_env": stage_env(s, "MODEL"), "effort_env": stage_env(s, "EFFORT")}
              for s, v in stage_view(None).items()}
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
        "claude_config_dir": claude_config_dir()[0],
        "claude_config_dir_source": claude_config_dir()[1],
        "anthropic_key_hint": f"…{akey[-4:]}" if len(akey) >= 8 else ("설정됨" if akey else ""),
        "anthropic_key_source": akey_src if akey else "none",
        "stages": stages,
        "stage_settings": {k: v for k, v in (_read().get("stages") or {}).items() if k in STAGES},
        "stage_model_settings": {k: v for k, v in (_read().get("stage_models") or {}).items() if k in STAGES},
        "stage_effort_settings": {k: v for k, v in (_read().get("stage_efforts") or {}).items() if k in STAGES},
        "efforts": list(EFFORTS),
        "gemini_efforts": list(GEMINI_EFFORTS),
        # 지금 Gemini 연결 방식에서 명시 캐시를 받지 않는 모델 (설정 화면 모델 칸 안내)
        "gemini_cache_unsupported": sorted(k.split(":", 1)[1] for k in gemini_cache_unsupported()
                                           if k.startswith(gemini_cache_model_key(auth == "vertex", ""))),
        "stage_presets": presets(),
        "local_sampling": local_sampling(),
        "path": str(config_path()),
        # 설정 파일이 깨져 있으면 참. 화면은 맨 위에 안내와 '기본값으로 새로 시작'(POST /config/reset)을 보이고, 그때까지 저장은 막힌다
        "config_broken": _load()[1],
        "config_backup": broken_backup(),
    }
