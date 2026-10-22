# Canon (MVP)

인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편을 AI 로 쓰는 CLI. 설계는 [DESIGN.md](DESIGN.md).

## 설치

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...            # https://aistudio.google.com/apikey
export CANON_MODEL=gemini-2.5-pro # 선택, 사용할 Gemini 모델
```

API 키 없이 흐름만 보려면 `export CANON_LLM=mock`.

## 웹 UI

```bash
python -m canon serve            # http://127.0.0.1:8000
CANON_LLM=mock python -m canon serve   # API 키 없이 화면만 둘러보기
```

작품 홈, 설정 도우미, 문체 레퍼런스, 기승전결 플롯 보드, 집필, 상태 변경안 승인, 채팅 앱 작업지시서 화면이 있다. CLI 와 같은 `projects/<이름>/project.json` 을 읽고 쓴다. AI 제안은 바로 저장되지 않고, 화면에서 고르거나 고친 뒤 저장할 때 반영된다.

## CLI 사용 순서

```bash
python -m canon new 등대 -i                     # 1. 설정 도우미 (AI 가 인물/세계관 제안)
python -m canon style 등대 examples/sample_style.txt   # 2. 예시 텍스트로 문체 프로필
python -m canon arc 등대                         # 3. 기승전결 구간
python -m canon plot 등대                        # 4. 화별 플롯 초안
#    projects/등대/project.json 에서 플롯 수정
python -m canon confirm 등대 all                 # 5. 플롯 확정
python -m canon run 등대                         # 6. 화마다 본문 생성 → 상태 변경안 승인
python -m canon show 등대                        # 진행 상황
```

한 화씩 하려면 `write 등대 3` 다음 `update 등대 3`.

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
```

## 파일 구조

```
canon/schema.py    데이터 스키마
canon/prompts.py   프롬프트와 컨텍스트 조립, 작업지시서
canon/pipeline.py  단계별 생성/검증/반영 로직
canon/dynamics.py  관계 역학 수식 (사건 적용, 긴장 계산, 재생, 말로 바꾸기)
canon/llm.py       Gemini 프로바이더 (+ mock.py)
canon/store.py     project.json 저장, 본문을 episodes/NN.md 로 내보내기
canon/cli.py       명령줄
canon/web.py       웹 UI 서버 (FastAPI) + canon/static/ 화면
tests/             웹 API 흐름 테스트 (mock LLM, pytest)
```
