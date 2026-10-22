# Canon (MVP)

인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편을 AI 로 쓰는 CLI. 설계는 [DESIGN.md](DESIGN.md).

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate   # macOS Homebrew Python 은 가상환경 필요
python -m pip install -r requirements.txt
export GEMINI_API_KEY=...            # https://aistudio.google.com/apikey
export CANON_MODEL=gemini-4-argon # 선택, 사용할 Gemini 모델 (기본값)
```

API 키 없이 흐름만 보려면 `export CANON_LLM=mock`.

## 웹 UI

```bash
python -m canon serve            # http://127.0.0.1:8000 을 띄우고 브라우저를 연다
python -m canon serve --no-browser     # 브라우저는 열지 않기
CANON_LLM=mock python -m canon serve   # API 키 없이 화면만 둘러보기
```

`serve` 는 시작할 때와 실행 중 10분마다 GitHub `main` 의 새 코드를 확인해 받는다(`git pull` 과 같다). 실행 중에 받으면 진행 중인 요청(Gemini 호출 등)이 끝난 뒤 스스로 다시 시작하고, `requirements.txt` 가 바뀌었으면 의존성도 설치한다. `main` 브랜치가 아니거나, 고친 파일이나 올리지 않은 커밋이 있으면 받지 않고 이유만 출력한다. 작품(`projects/`)과 설정(`~/.canon/config.json`)은 git 이 다루지 않으므로 그대로다. 끄려면 `--no-update`, 간격은 `--update-interval 30`(분). 손으로 받으려면 `python -m canon upgrade`.

macOS 에서는 Finder 로 `scripts/canon-mac.command` 를 더블클릭해도 된다. 저장소의 `.venv` 를 켜고 서버를 띄운 뒤 브라우저를 연다(이미 켜져 있으면 브라우저만 연다). 처음 한 번은 우클릭 → 열기로 실행 허용이 필요할 수 있다. Dock 에 끌어 두면 앱처럼 쓸 수 있다.

Gemini API 키와 모델은 화면 오른쪽 아래 **모델 · API 키 설정**에서 넣는다. `~/.canon/config.json` 에만 저장되고(권한 600), 환경 변수 `GEMINI_API_KEY`, `CANON_MODEL`, `CANON_LLM` 이 있으면 그 값이 우선한다. CLI 도 같은 설정을 쓴다.

작품 홈, 설정 도우미, 문체 레퍼런스, 기승전결 플롯 보드, 집필, 상태 변경안 승인, 채팅 앱 작업지시서 화면이 있다. 사이드바 아래의 **연구 · 모델 실험** 화면은 본편과 분리된 실험실이다 (아래 '연구 화면'). CLI 와 같은 `projects/<이름>/project.json` 을 읽고 쓴다. AI 제안은 바로 저장되지 않고, 화면에서 고르거나 고친 뒤 저장할 때 반영된다.

기승전결 · 플롯 화면의 **대화로 다듬기**를 열면 오른쪽에 대화 패널이 붙는다. "3화 전개가 너무 빨라", "결말을 비극으로 바꿔 줘", "14화로 늘려 줘"처럼 말하면 AI 가 답과 함께 변경안을 내고, 패널에는 바뀌는 칸만 지금 값과 바꿀 값으로 나란히 보인다. 구조(구간 범위·목표·전환점, 총 화수)와 화별 플롯을 하나씩 골라 반영하고, 고르지 않은 것은 그대로다. 본문이 있는 화는 변경안에서 빠지고, 확정한 화는 처음엔 꺼져 있으며 반영하면 초안으로 돌아가 다시 확정해야 한다. 대화는 작품(`project.json` 의 `chats`)에 저장되어 다음에 열어도 이어지고, AI 는 최근 대화와 지금 설정·인물·관계·구조·플롯을 함께 본다. CLI 는 `python -m canon revise 등대 "3화 전개가 너무 빨라"` 로 같은 일을 한다.

**문체 라이브러리**(작품 목록 위 버튼, 사이드바 아래 링크)에서는 붙여 넣어 분석한 문체를 작품과 따로 모아 두고 목록으로 본다. 항목마다 이름, 출처, 메모, 분석한 원문, 스타일 프로필, 원문으로 잰 기준 지표가 있고, 고치기·복제·삭제할 수 있다. 새 작품을 만들 때 라이브러리 문체를 고르거나, 작품의 문체 레퍼런스 화면에서 가져오거나(`적용`) 지금 문체를 라이브러리에 저장할 수 있다. 적용하면 그 시점의 문체가 `project.json` 으로 복사되므로 라이브러리를 고쳐도 쓰고 있는 작품은 다시 적용하기 전까지 그대로다. 둘이 달라지면 문체 화면에 표시되고, 어느 쪽으로 맞출지 고를 수 있다. 라이브러리는 `projects/.styles/<id>.json` 에 저장된다(`CANON_STYLES` 로 경로 변경).

새 작품 폼과 설정 도우미에서 장르를 여러 개 고를 수 있다(로맨스 판타지, 무협 같은 큰 갈래와 회귀, 계약 관계 같은 요소). 고른 장르마다 독자가 기대하는 것, 관습, 자주 쓰는 소재, 전개 속도, 피할 것을 펼쳐 볼 수 있고, 같은 안내가 프롬프트와 작업지시서에 들어간다. 목록에 없는 장르는 직접 적는다. **성인물**을 체크하면 성인 독자 대상으로, 끄면 전연령 수위로 쓰라고 지시한다.

설정 도우미는 처음 쓰는 사람이 빈칸 앞에서 막히지 않게 나눠서 묻는다.

- **로그라인**은 다섯 칸(누가 / 무엇 때문에 / 무엇을 하려 하나 / 무엇이 막나 / 무엇이 걸렸나)으로 쓴다. 칸마다 고른 장르의 예시가 점선 버튼으로 붙어 있고, 합친 문장과 점검(주인공의 특징, 계기, 행동인 목표, 막는 것, 길이)이 바로 보인다. 조사(이/가)는 자동으로 붙는다. 점검은 참고용이라 넘어가는 것을 막지 않는다. 장르마다 칸별로 나눈 예시 로그라인이 두 개씩 있어 "이 예시로 채우기"로 통째로 넣어 볼 수도 있다.
- **주제**는 이 이야기가 끝까지 묻는 질문 하나로, **톤**은 밝다↔어둡다, 가볍다↔진지하다, 빠르다↔느리다 다이얼로 고르면 문장이 만들어진다(직접 고쳐도 된다).
- **인물**은 이름, 역할, 원하는 것, 두려운 것, 숨기는 것, 말투만 먼저 보이고 나머지는 "더 자세히"에 접혀 있다. 인물 id 는 자동으로 짓는다.
- **관계**는 숫자 대신 말로 고른다. 어떤 사이인지, "서윤 → 도현"과 "도현 → 서윤"이 서로를 어떻게 보는지(믿는다, 좋아한다, 경계한다, 미워한다, 빚졌다, 얕본다, 잘 모른다), 원하는 게 부딪치는지(아니다 / 조금 / 정면으로). 고른 말은 `dynamics.VIEWS` 표로 방향별 시작 온기·신뢰·서열·원한이 된다. 숫자로 정하고 싶으면 "숫자로 직접 정하기"를 연다.

CLI 의 `new -i` 도 로그라인을 같은 다섯 칸으로 묻고, 고른 장르의 예시와 점검 결과를 보여 준다.

### 서버에서 상시 실행 (Tailscale)

Vercel 같은 서버리스 호스팅은 맞지 않는다. 소설 데이터를 파일(`project.json`)에 저장하고 Gemini 호출이 길게 걸리기 때문이다. 항상 켜져 있는 리눅스 서버가 있으면 systemd 로 돌리고 Tailscale 로 내 기기에서만 연다. Canon 에는 로그인이 없으니 **Tailscale Funnel 이나 공개 포트로 열지 않는다**.

```bash
# 서버에서: 저장소를 받고 가상환경 준비
git clone https://github.com/c10dev/canon ~/canon && cd ~/canon
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# deploy/canon.service 의 USER 와 경로를 고친 뒤 등록 (부팅 때 자동 실행)
sudo cp deploy/canon.service /etc/systemd/system/canon.service
sudo systemctl daemon-reload && sudo systemctl enable --now canon
# tailnet 안에서만 HTTPS 로 열기 (8446 은 비어 있는 아무 포트)
sudo tailscale serve --bg --https=8446 http://127.0.0.1:8000
```

그러면 같은 tailnet 의 맥, 아이폰에서 `https://<서버이름>.<tailnet>.ts.net:8446` 로 열린다. 작품은 서버의 `~/canon/projects/` 에, API 키는 서버 계정의 `~/.canon/config.json` 에 저장된다. 다른 컴퓨터에서 쓰던 작품은 `projects/<이름>/` 폴더를 그대로 복사하면 된다. 포트 대시보드(예: Portboard)를 쓰고 있으면 systemd 서비스 이름 `Canon - AI 소설 작성 웹 UI` 로 잡힌다. 로그는 `journalctl -u canon -f`.

## CLI 사용 순서

```bash
python -m canon genres                          # 장르 목록
python -m canon new 등대 -i --genre "미스터리, 회귀"   # 1. 설정 도우미 (AI 가 인물/세계관 제안), 성인물이면 --adult
python -m canon style 등대 examples/sample_style.txt   # 2. 예시 텍스트로 문체 프로필 (--save 이름: 라이브러리에도 저장)
#    또는 python -m canon style 등대 --library <id>    문체 라이브러리 항목 적용
python -m canon arc 등대                         # 3. 기승전결 구간
python -m canon plot 등대                        # 4. 화별 플롯 초안
#    projects/등대/project.json 에서 플롯 수정
python -m canon revise 등대 "3화 전개가 너무 빨라"   #    말로 고치기 (변경안 확인 후 반영)
python -m canon confirm 등대 all                 # 5. 플롯 확정
python -m canon run 등대                         # 6. 화마다 본문 생성 → 검수 → 상태 변경안 승인
python -m canon show 등대                        # 진행 상황
python -m canon stats 등대                       # 화별 문체 지표를 레퍼런스와 비교
```

문체 라이브러리는 `python -m canon styles` (목록), `styles add 이름 원문.txt [--source 출처]`, `styles show <id>`, `styles rm <id>` 로도 다룬다.

한 화씩 하려면 `write 등대 3` → `check 등대 3` → `update 등대 3`. `check` 는 앞선 본문·설정과의 모순을 근거 문장과 함께 보여준다 (`run --no-check` 로 생략 가능). 작품에서 쓰지 말아야 할 표현은 `project.json` 의 `style.banned_phrases` 에 넣으면 `stats` 와 본문 지시에 반영된다.

## AI 글티('쇠맛') 줄이기

본문 지시에는 AI 글에서 자주 보이는 버릇을 피하는 문체 기본 규칙(`prompts.PROSE_RULES`)이 들어간다. 감정은 이름 대신 행동으로 보여 주고, "단순한 A가 아니었다. B였다" 같은 부정 후 재정의, 셋씩 나열, 문단 끝 짧은 여운 문장, 번역투를 줄이라는 내용이다. 작품의 스타일 프로필과 부딪히면 스타일 프로필이 이긴다.

`stats` 와 `write`, `update` 는 이 버릇을 재서 경고한다. 쉼표 문장 비율, 짧은 문장으로 끝나는 문단 비율, 대명사 밀도는 레퍼런스보다 높을 때만 경고하고, 부정 후 재정의·셋씩 나열·감정 이름 서술·번역투·서식 흔적은 화당 상한(`metrics.AI_PATTERNS`)을 넘으면 경고한다. 경고는 참고용이며 사람이 쓴 글도 걸릴 수 있다. 예전에 만든 프로젝트는 `style` 을 다시 실행해야 새 지표가 기준값과 비교된다.

## 관계 역학

상태 갱신 때 AI 는 관계 수치를 직접 적지 않고, 본문에서 일어난 **사건**(도움, 배신, 거짓말 발각 등과 강도, 목격자, 근거 문장)만 뽑는다. 관계 변화는 `canon/dynamics.py` 의 수식이 계산한다. 관계는 방향이 있어서 서윤→도현과 도현→서윤을 따로 본다(온기, 신뢰, 원한, 서열, 친숙도, 단계). 긴장도는 이 값들과 목표 충돌, 숨긴 비밀, 불균형 삼각관계로 계산한다.

```bash
python -m canon show 등대 rel                 # 관계 보기
python -m canon view 등대 numbers             # 숫자로 보기 (words 는 말로 보기, 기본)
python -m canon adjust 등대 hero ally --warmth 0.3 --trust 0.6   # hero 가 ally 를 보는 관계 직접 보정
python -m canon revert 등대 3                 # 3화 상태 반영 직후로 되돌리기 (본문은 유지)
python -m canon recalc 등대                   # project.json 의 params 를 바꾼 뒤 재계산
```

계수는 `project.json` 의 `params` 에 있다. 프롬프트에는 숫자 대신 "신뢰: 의심하고 있다" 같은 말로 들어간다.

## 로컬 모델 (Ollama, llama.cpp, vLLM, LM Studio)

OpenAI 호환 API 를 여는 서버면 된다. 단계마다 백엔드를 고를 수 있어서, 계획과 검수는 Gemini 에 두고 본문만 로컬 모델로 쓸 수 있다. 단계마다 모델도 따로 고를 수 있다 (예: 상태 변경안만 빠르고 싼 `gemini-3.8-flash`). 웹 설정 화면의 **로컬 서버**, **단계별 백엔드와 모델**에서 정하거나 환경 변수로 정한다. 모델 칸은 Gemini API 와 로컬 서버의 모델 목록을 불러와 보여 주고, 목록에 없는 이름은 직접 적으면 된다.

```bash
export CANON_LOCAL_URL=http://localhost:11434/v1   # Ollama. llama.cpp :8080/v1, vLLM :8000/v1
export CANON_LOCAL_MODEL=gemma4:31b                # 비우면 서버에 하나뿐인 모델
export CANON_LLM_WRITE=local                       # 본문만 로컬 (plan / write / check / state)
export CANON_MODEL_STATE=gemini-3.8-flash          # 상태 변경안만 다른 모델 (CANON_MODEL_PLAN / _WRITE / _CHECK / _STATE)
# 전부 로컬이면 CANON_LLM=local

python -m canon compare 등대 3                  # 같은 화를 gemini 와 local 로 써서 1, 2 번으로 가림
python -m canon compare 등대 3 --pick 2         # 고른 쪽을 본문으로 쓰고 어느 백엔드였는지 공개
```

본문 생성 샘플링은 `~/.canon/config.json` 의 `local_sampling` 으로 바꾼다 (기본 `{"temperature": 1.0, "top_p": 0.95, "min_p": 0.05}`). 서버가 키를 요구하면 `CANON_LOCAL_KEY`.

## 연구 화면 (모델 실험)

웹 사이드바의 **연구 · 모델 실험**에서 모델을 시험한다. 작품 데이터(`project.json`)는 바꾸지 않고, 결과는 `projects/<이름>/research/log.jsonl` 에 남는다. 블라인드 비교에서 '본문으로 채택'을 켜고 고를 때만 그 화 본문이 바뀐다.

| 탭 | 하는 일 |
|---|---|
| 서버 점검 | 로컬 서버의 모델 목록, 최대 컨텍스트, 서버 종류 (생성 호출 없음) |
| 샘플 생성 | 같은 요청을 여러 백엔드·모델에 보내 시간, 토큰, 문체 지표를 나란히 비교 |
| 단계 시험 | 설정 제안, 문체 분석, 기승전결을 저장 없이 돌려 빈 필드, 범위 밖 숫자, 재시도 횟수 확인 |
| 컨텍스트 크기 | 화별 본문 쓰기, 검수, 상태 추출 프롬프트 토큰을 모델 한도와 비교 (vLLM, llama.cpp 는 서버 토크나이저로 셈) |
| 블라인드 비교 | `compare` 의 웹판. 백엔드마다 모델과 서버 주소를 따로 고를 수 있어 LoRA 끼리도 비교 |
| 기록 | 최근 30개 실험 |

## 채팅 앱(구독형)으로 쓰기

```bash
python -m canon brief 등대 3            # projects/등대/briefs/03-episode.md 를 채팅에 붙여 넣기
python -m canon import 등대 3 본문.txt   # 받은 본문 가져오기
python -m canon brief 등대 3 --state    # 상태 정리 지시서 → 채팅 앱이 JSON 반환
python -m canon update 등대 3 --from-json 응답.json
python -m canon brief 등대 3 --check    # 검수 지시서 → 받은 JSON 은 check 등대 3 --from-json 응답.json
```

## 파일 구조

```
canon/schema.py    데이터 스키마
canon/prompts.py   프롬프트와 컨텍스트 조립, 작업지시서
canon/pipeline.py  단계별 생성/검증/반영 로직
canon/metrics.py   문체 지표 (LLM 없이 계산)
canon/genres.py    장르 목록과 장르별 안내
canon/dynamics.py  관계 역학 수식 (사건 적용, 긴장 계산, 재생, 말로 바꾸기)
canon/llm.py       Gemini, 로컬(OpenAI 호환) 프로바이더와 단계별 선택 (+ mock.py)
canon/research.py  연구 화면 로직: 서버 점검, 샘플 비교, 단계 시험, 컨텍스트 크기, 블라인드 비교
canon/store.py     project.json 저장, 본문을 episodes/NN.md 로 내보내기
canon/library.py   문체 라이브러리 (작품과 따로 저장하는 문체 항목)
canon/cli.py       명령줄
canon/web.py       웹 UI 서버 (FastAPI) + canon/static/ 화면
tests/             흐름 테스트 (mock LLM, 가짜 OpenAI 호환 서버)
```
