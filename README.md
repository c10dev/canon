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
python -m canon run 등대                         # 6. 화마다 본문 생성 → 검수 → 상태 변경안 승인
python -m canon show 등대                        # 진행 상황
python -m canon stats 등대                       # 화별 문체 지표를 레퍼런스와 비교
```

한 화씩 하려면 `write 등대 3` → `check 등대 3` → `update 등대 3`. `check` 는 앞선 본문·설정과의 모순을 근거 문장과 함께 보여준다 (`run --no-check` 로 생략 가능). 작품에서 쓰지 말아야 할 표현은 `project.json` 의 `style.banned_phrases` 에 넣으면 `stats` 와 본문 지시에 반영된다.

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
canon/llm.py       Gemini 프로바이더 (+ mock.py)
canon/store.py     project.json 저장, 본문을 episodes/NN.md 로 내보내기
canon/cli.py       명령줄
canon/web.py       웹 UI 서버 (FastAPI) + canon/static/ 화면
tests/             웹 API 흐름 테스트 (mock LLM, pytest)
```
