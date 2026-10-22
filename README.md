# Canon (MVP)

인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편을 AI 로 쓰는 CLI. 설계는 [DESIGN.md](DESIGN.md).

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate   # macOS Homebrew Python 은 가상환경 필요
python -m pip install -r requirements.txt
export GEMINI_API_KEY=...            # https://aistudio.google.com/apikey
export CANON_MODEL=gemini-2.5-pro # 선택, 사용할 Gemini 모델
```

API 키 없이 흐름만 보려면 `export CANON_LLM=mock`.

## 웹 UI

```bash
python -m canon serve            # http://127.0.0.1:8000 을 띄우고 브라우저를 연다
python -m canon serve --no-browser     # 브라우저는 열지 않기
CANON_LLM=mock python -m canon serve   # API 키 없이 화면만 둘러보기
```

macOS 에서는 Finder 로 `scripts/canon-mac.command` 를 더블클릭해도 된다. 저장소의 `.venv` 를 켜고 서버를 띄운 뒤 브라우저를 연다(이미 켜져 있으면 브라우저만 연다). 처음 한 번은 우클릭 → 열기로 실행 허용이 필요할 수 있다. Dock 에 끌어 두면 앱처럼 쓸 수 있다.

Gemini API 키와 모델은 화면 오른쪽 아래 **모델 · API 키 설정**에서 넣는다. `~/.canon/config.json` 에만 저장되고(권한 600), 환경 변수 `GEMINI_API_KEY`, `CANON_MODEL`, `CANON_LLM` 이 있으면 그 값이 우선한다. CLI 도 같은 설정을 쓴다.

작품 홈, 설정 도우미, 문체 레퍼런스, 기승전결 플롯 보드, 집필, 상태 변경안 승인, 채팅 앱 작업지시서 화면이 있다. CLI 와 같은 `projects/<이름>/project.json` 을 읽고 쓴다. AI 제안은 바로 저장되지 않고, 화면에서 고르거나 고친 뒤 저장할 때 반영된다.

설정 도우미에서 장르를 여러 개 고를 수 있다(로맨스 판타지, 무협 같은 큰 갈래와 회귀, 계약 관계 같은 요소). 고른 장르마다 독자가 기대하는 것, 관습, 자주 쓰는 소재, 전개 속도, 피할 것을 펼쳐 볼 수 있고, 같은 안내가 프롬프트와 작업지시서에 들어간다. 목록에 없는 장르는 직접 적는다. **성인물**을 체크하면 성인 독자 대상으로, 끄면 전연령 수위로 쓰라고 지시한다.

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
python -m canon style 등대 examples/sample_style.txt   # 2. 예시 텍스트로 문체 프로필
python -m canon arc 등대                         # 3. 기승전결 구간
python -m canon plot 등대                        # 4. 화별 플롯 초안
#    projects/등대/project.json 에서 플롯 수정
python -m canon confirm 등대 all                 # 5. 플롯 확정
python -m canon run 등대                         # 6. 화마다 본문 생성 → 검수 → 상태 변경안 승인
python -m canon show 등대                        # 진행 상황
python -m canon stats 등대                       # 화별 문체 지표를 레퍼런스와 비교
```

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
canon/llm.py       Gemini 프로바이더 (+ mock.py)
canon/store.py     project.json 저장, 본문을 episodes/NN.md 로 내보내기
canon/cli.py       명령줄
canon/web.py       웹 UI 서버 (FastAPI) + canon/static/ 화면
tests/             웹 API 흐름 테스트 (mock LLM, pytest)
```
