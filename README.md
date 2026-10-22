# Canon (MVP)

인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편부터 200~300화 장편 연재까지 AI 로 쓰는 도구 (CLI, 웹 UI). 설계는 [DESIGN.md](DESIGN.md).

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

`serve` 는 시작할 때와 실행 중 10분마다 GitHub `main` 의 새 코드를 확인해 받는다(`git pull` 과 같다). 실행 중에 받으면 진행 중인 요청과 백그라운드 AI 작업(Gemini 호출 등)이 끝난 뒤 스스로 다시 시작하고, `requirements.txt` 가 바뀌었으면 의존성도 설치한다. `main` 브랜치가 아니거나, 고친 파일이나 올리지 않은 커밋이 있으면 받지 않고 이유만 출력한다. 작품(`projects/`)과 설정(`~/.canon/config.json`)은 git 이 다루지 않으므로 그대로다. 끄려면 `--no-update`, 간격은 `--update-interval 30`(분). 손으로 받으려면 `python -m canon upgrade`.

macOS 에서는 Finder 로 `scripts/canon-mac.command` 를 더블클릭해도 된다. 저장소의 `.venv` 를 켜고 서버를 띄운 뒤 브라우저를 연다(이미 켜져 있으면 브라우저만 연다). 처음 한 번은 우클릭 → 열기로 실행 허용이 필요할 수 있다. Dock 에 끌어 두면 앱처럼 쓸 수 있다.

Gemini API 키와 모델은 화면 오른쪽 아래 **모델 · API 키 설정**에서 넣는다. `~/.canon/config.json` 에만 저장되고(권한 600), 환경 변수 `GEMINI_API_KEY`, `CANON_MODEL`, `CANON_LLM` 이 있으면 그 값이 우선한다. CLI 도 같은 설정을 쓴다.

작품 홈, 설정 도우미, 문체 레퍼런스, 기승전결 플롯 보드, 인과율(요소·설정·사건과 영향 분석), 집필, 상태 변경안 승인, 채팅 앱 작업지시서 화면이 있다. 사이드바 아래의 **연구 · 모델 실험** 화면은 본편과 분리된 실험실이다 (아래 '연구 화면'). CLI 와 같은 `projects/<이름>/project.json` 을 읽고 쓴다. AI 제안은 바로 저장되지 않고, 화면에서 고르거나 고친 뒤 저장할 때 반영된다.

기승전결 · 플롯 화면의 **대화로 다듬기**를 열면 오른쪽에 대화 패널이 붙는다. "3화 전개가 너무 빨라", "결말을 비극으로 바꿔 줘", "14화로 늘려 줘"처럼 말하면 AI 가 답과 함께 변경안을 내고, 패널에는 바뀌는 칸만 지금 값과 바꿀 값으로 나란히 보인다. 구조(구간 범위·목표·전환점, 총 화수)와 화별 플롯을 하나씩 골라 반영하고, 고르지 않은 것은 그대로다. 본문이 있는 화는 변경안에서 빠지고, 확정한 화는 처음엔 꺼져 있으며 반영하면 초안으로 돌아가 다시 확정해야 한다. 대화는 작품(`project.json` 의 `chats`)에 저장되어 다음에 열어도 이어지고, AI 는 최근 대화와 지금 설정·인물·관계·구조·플롯을 함께 본다. CLI 는 `python -m canon revise 등대 "3화 전개가 너무 빨라"` 로 같은 일을 한다.

사이드바의 **인과율**에서는 요소, 특징, 설정, 사건을 언제든 더한다. 종류(세계 규칙, 장소, 물건, 세력, 인물 특징, 과거 사건, 예정 사건, 기타), 이름과 다른 이름, 설명, 관련 인물과 함께 **언제부터 사실인지**(처음부터 사실이었다 / n화부터 생긴다), 일어나거나 꼭 나와야 하는 화, 독자에게 드러나는 화를 적는다. 저장하면 AI 없이 이름·다른 이름·관련 인물로 찾은 **관련 화 지도**가 바로 보인다. **영향 분석**을 누르면 AI 가 이미 쓴 본문과 정해 둔 플롯을 읽고 어긋나는 곳(원문 인용), 바꿀 화별 플롯, 이미 쓴 화의 최소 본문 수정안, 모순을 설명으로 덮을 확정 사실을 낸다. 원문에서 인용을 찾지 못한 지적과 본문이 있는 화의 플롯 변경은 프로그램이 뺀다. 고른 것만 반영하고, 확정한 화의 플롯을 바꾸면 초안으로 돌아간다. 처음부터 사실인 설정이 앞 본문과 부딪치면 '언제부터'를 늦춰 n화부터 생긴 일로 바꾸는 방법도 있다. 더한 요소는 본문 쓰기(관련 있는 화만, 드러나는 화 전에는 암시만), 화별 플롯, 플롯 대화, 검수 프롬프트에 들어간다. CLI 는 `python -m canon causal 등대 add --kind 과거사건 --title 등대지기 --desc "윤만석은 서윤의 친부다" --chars hero`, `causal 등대 show el-01`, `causal 등대 impact el-01`.

**문체 라이브러리**(작품 목록 위 버튼, 사이드바 아래 링크)에서는 붙여 넣어 분석한 문체를 작품과 따로 모아 두고 목록으로 본다. 항목마다 이름, 출처, 메모, 분석한 원문, 스타일 프로필, 원문으로 잰 기준 지표가 있고, 고치기·복제·삭제할 수 있다. 새 작품을 만들 때 라이브러리 문체를 고르거나, 작품의 문체 레퍼런스 화면에서 가져오거나(`적용`) 지금 문체를 라이브러리에 저장할 수 있다. 적용하면 그 시점의 문체가 `project.json` 으로 복사되므로 라이브러리를 고쳐도 쓰고 있는 작품은 다시 적용하기 전까지 그대로다. 둘이 달라지면 문체 화면에 표시되고, 어느 쪽으로 맞출지 고를 수 있다. 라이브러리는 `projects/.styles/<id>.json` 에 저장된다(`CANON_STYLES` 로 경로 변경).

새 작품 폼과 설정 도우미에서 장르를 여러 개 고를 수 있다(로맨스 판타지, 무협 같은 큰 갈래와 회귀, 계약 관계 같은 요소). 고른 장르마다 독자가 기대하는 것, 관습, 자주 쓰는 소재, 전개 속도, 피할 것을 펼쳐 볼 수 있고, 같은 안내가 프롬프트와 작업지시서에 들어간다. 목록에 없는 장르는 직접 적는다. **성인물**을 체크하면 성인 독자 대상으로, 끄면 전연령 수위로 쓰라고 지시한다.

설정 도우미는 처음 쓰는 사람이 빈칸 앞에서 막히지 않게 나눠서 묻는다.

- **로그라인**은 다섯 칸(누가 / 무엇 때문에 / 무엇을 하려 하나 / 무엇이 막나 / 무엇이 걸렸나)으로 쓴다. 칸마다 고른 장르의 예시가 점선 버튼으로 붙어 있고, 합친 문장과 점검(주인공의 특징, 계기, 행동인 목표, 막는 것, 길이)이 바로 보인다. 조사(이/가)는 자동으로 붙는다. 점검은 참고용이라 넘어가는 것을 막지 않는다. 장르마다 칸별로 나눈 예시 로그라인이 두 개씩 있어 "이 예시로 채우기"로 통째로 넣어 볼 수도 있다.
- **주제**는 이 이야기가 끝까지 묻는 질문 하나로, **톤**은 밝다↔어둡다, 가볍다↔진지하다, 빠르다↔느리다 다이얼로 고르면 문장이 만들어진다(직접 고쳐도 된다).
- **인물**은 이름, 역할, 나이, 성별, 원하는 것, 두려운 것, 숨기는 것, 말투만 먼저 보이고 나머지는 "더 자세히"에 접혀 있다. 인물 id 는 자동으로 짓는다.
- **이름·지명**은 세계관에 맞춰 무작위로 뽑는다. 아래 '이름과 지명' 참고.
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

## 이름과 지명

AI 에게 이름을 맡기면 서윤, 도현 같은 몇 개 이름으로 몰리고, 45세 형사에게 2020년대 아기 이름을 붙이기도 한다. 그래서 후보는 코드가 뽑고 AI 는 그중에서 고르게 했다 (`canon/naming.py`, LLM 없이 계산).

- **이름 스타일**: 현대 한국, 조선·사극, 무협(중원), 서양풍 판타지, 일본, SF·우주. 세계관 칸의 '이름 스타일'에서 고르고, 비워 두면 장르와 배경·시대 글에서 짐작한다 (예: 시대에 '현대 일본'이 있으면 일본).
- **현대 한국**은 2015 인구주택총조사 성씨 비율과 출생 연대별 흔한 이름으로 뽑는다. 인물 나이(예: 45세, 40대 초반, 고1)와 시대 칸의 연도로 출생 연도를 어림해 그 시대 이름을 낸다. 일부는 같은 시대 이름의 음절을 섞어 목록에 없는 이름을 만든다.
- 무협은 복성을 포함한 성명과 별호, 문파, 중원 지역과 산·곡·객잔, 서양풍 판타지는 음절 조합 이름과 가문명, 왕국·영지를 만든다. 판타지에 너무 흔한 이름(레온, 카일, 루시안…)과 AI 가 자주 짓는 이름(서윤, 도현…)은 후보에서 뺀다.
- 설정 화면의 인물 카드에서 **이름 후보 뽑기**(즉시, AI 호출 없음)나 **AI 이름 추천**(후보 중에서 골라 이유를 붙임)을 누르고, 마음에 드는 칩을 누르면 이름 칸에 들어간다. 세계관 카드의 **지명 후보 뽑기**는 종류(마을, 산, 고개, 문파, 왕국…)를 골라 장소 목록에 더한다. 다른 인물과 첫 글자나 끝 글자가 겹치는 이름은 뒤로 미룬다.
- **이름 점검**은 글자가 겹치는 이름, 나이와 안 맞는 이름, AI 가 자주 짓는 이름을 알려 준다. 막지는 않는다.
- **이름 규칙**에 "북부 귀족은 성 앞에 '폰'을 붙인다" 같은 규칙을 적으면 AI 추천과 설정 제안 프롬프트에 들어간다. 'AI 제안받기'도 같은 후보 목록을 받아서 고른다.
- AI 추천에 쓰는 모델은 설정 화면 '단계별 백엔드'의 **이름·지명 AI 추천** 줄에서 정한다. 정하지 않으면 계획 단계 설정을 따른다. 모든 단계에 모델 칸이 있어 단계마다 다른 Gemini 모델이나 로컬 모델을 지정할 수 있다 (예: 이름 추천만 gemini-3.8-flash, 환경 변수 `CANON_MODEL_NAME`).

```bash
python -m canon names 등대 --character hero          # 인물 이름 후보 8개 (AI 호출 없음)
python -m canon names 등대 --character hero --ai     # 이름·지명 단계 모델이 골라 이유를 붙임
python -m canon names 등대 --character hero --pick 3 # 3번을 이름으로 반영
python -m canon names 등대 --place 고개 --pick 1      # 지명 후보에서 골라 장소에 추가
python -m canon names 등대 --style joseon            # 이번만 다른 이름 스타일로
python -m canon names 등대 --check                   # 출연진 이름 점검
```

자료 출처와 한계는 `canon/naming_data.py` 머리말에 적었다. 한국 이름 목록은 대법원 출생신고 통계 상위권과 보도를 바탕으로 손으로 정리한 것이라 원자료와 한 줄씩 대조하지는 않았다. 웹소설 본문이나 이름 사이트를 긁어 온 것은 없다.

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
python -m canon causal 등대 add --kind 예정사건 --title 태풍 --desc "12화에 태풍이 온다" --eps 12   #    요소·설정·사건 더하기 (impact ID 로 영향 분석)
python -m canon confirm 등대 all                 # 5. 플롯 확정
python -m canon run 등대                         # 6. 화마다 본문 생성 → 검수 → 상태 변경안 승인
#    또는 python -m canon auto 등대 --to 12          기준에 걸릴 때만 멈추는 자동 집필 (아래)
python -m canon show 등대                        # 진행 상황
python -m canon stats 등대                       # 화별 문체 지표를 레퍼런스와 비교
```

문체 라이브러리는 `python -m canon styles` (목록), `styles add 이름 원문.txt [--source 출처]`, `styles show <id>`, `styles rm <id>` 로도 다룬다.

한 화씩 하려면 `write 등대 3` → `check 등대 3` → `update 등대 3`. `check` 는 앞선 본문·설정과의 모순을 근거 문장과 함께 보여준다 (`run --no-check` 로 생략 가능). 작품에서 쓰지 말아야 할 표현은 `project.json` 의 `style.banned_phrases` 에 넣으면 `stats` 와 본문 지시에 반영된다.

## 장편 연재 (200~300화)

새 작품을 만들 때 형식을 **장편 연재**로 고르면(`new 이름 --serial`, 웹은 새 작품 화면의 '장편 연재') 작품을 **부 → 아크 → 화** 로 나눈다. 단편 작품은 예전과 똑같이 동작한다.

```bash
python -m canon new 탑 -i --serial --episodes 300 --genre "현대판타지"   # 장편 연재로 시작 (--arc-length 로 아크 길이 기본값)
python -m canon series 탑                  # 1. 부 계획: 작품 전체를 부 2~5개로 (부마다 목표, 큰 전환, 아크 아이디어)
python -m canon nextarc 탑                 # 2. 다음 아크 하나만 기획 (자기 기승전결, 갈등, 회수할 떡밥, 새 인물)
#    --len 25: 길이 지정, --note "라이벌 등장": 요청, --redo: 아직 안 쓴 마지막 아크 다시 기획
python -m canon plot 탑                    # 3. 그 아크의 화별 플롯만 초안
python -m canon confirm 탑 all
python -m canon run 탑                     # 4. 아크 끝까지 쓰기
python -m canon recap 탑                   # 5. 끝난 아크 줄거리 요약 (승인 후 저장, 부가 끝나면 recap 탑 part 1)
python -m canon arcs 탑                    # 부와 아크 진행 보기
```

한 번에 300화를 다 기획하지 않는다. 부 계획은 큰 방향만 잡고, 아크는 쓰면서 하나씩 정한다(롤링 기획). 아크가 끝나면 그 아크 줄거리를 요약해 두는데, 다음 화부터는 오래된 화별 요약 대신 이 요약이 들어간다. 그래서 270화를 써도 줄거리 블록이 수천 자로 유지된다.

인물에는 등장 비중(주역 · 조연 · 단역)이 있다. 주역만 매 화 설정 전체가 들어가고, 조연과 단역은 그 화에 나올 때만 들어간다. 본문에 처음 나온 이름 있는 인물은 상태 변경안에 새 인물로 올라오고, 승인하면 조연으로 등록된다. 떡밥은 범위(이번 아크 · 이번 부 · 작품 전체)와 회수 예정 화를 가진다.

웹에서는 '부 · 아크 · 플롯' 화면에서 부 계획, 다음 아크 제안 검토, 아크별 플롯 보드, 아크 · 부 요약 승인을 한다.

## 자동 집필 (목표 화까지)

웹 사이드바의 **자동 집필**에서 목표 화를 고르고 시작하면 화마다 본문 → 검수 + 상태 변경안 → 반영을 알아서 반복한다. 다른 화면으로 옮겨 가거나 창을 닫아도 서버가 계속 돈다.

- **멈추는 기준**: 검수에서 어긋난 곳이 나오거나(허용 개수 조절), 관계가 한 화에 크게 움직이거나(민감도 조절), 설정에 없는 인물이 나오면 그 화에서 멈추고 변경안을 검토 대기로 둔다. 관계 단계 변화, 상태 변경안 경고, N화마다 멈춤, 초안 플롯 자동 확정은 선택. 멈추면 상태 승인 화면에서 골라 반영하고 이어 가거나, 그대로 반영하고 이어 가거나, 그 화를 다시 쓴다.
- 검토 없이 반영한 화는 `자동 반영`으로 표시되고, 자동 집필 화면에서 그 화부터 되돌릴 수 있다(본문은 남는다).
- **배치 켜기/끄기**: 켜면 Gemini Batch API 로 보내 비용이 절반이지만 단계마다 몇 분에서 길게는 24시간 기다린다. 끄면 일반 호출이라 빠르다. 돌고 있을 때도 바꿀 수 있고 다음 단계부터 적용된다. 화는 앞 화가 반영돼야 쓸 수 있어 배치로도 한 화씩 간다. 로컬 모델 단계는 배치 없이 돈다.
- 시작 전에 배치 끔/켬 각각의 예상 비용과 시간을 보여 주고, 진행 중에는 단계별 로그(토큰, 걸린 시간)와 누적 비용을 보여 준다. 일시정지(배치는 남겨 두고 이어 가면 받아 옴), 중지(기다리던 배치 취소)가 있다. 서버가 다시 시작돼도 이어서 돈다. 진행 기록은 `projects/<이름>/autorun.json`.

```bash
python -m canon auto 등대 --to 12 --batch   # 예상 비용·시간을 보여 주고 시작 (Ctrl-C 는 일시정지)
python -m canon auto 등대 --status          # 상태와 최근 로그
python -m canon auto 등대 --resume [--approve | --rewrite]   # 이어 가기 (검토 대기면 그대로 반영 또는 다시 쓰기)
python -m canon auto 등대 --stop            # 중지
```

기준 옵션: `--max-issues 0`, `--max-shift 0.3`(0 이면 안 봄), `--stop-on-stage`, `--stop-on-warnings`, `--confirm-plots`, `--review-every N`, `--no-check`. 가격은 `gemini-4-argon` 정가 추정치($2/$10, 100만 토큰당)로 계산하고 `CANON_PRICE="입력,출력"` 으로 바꿀 수 있다.

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
export CANON_LLM_WRITE=local                       # 본문만 로컬 (plan / write / check / state / name)
export CANON_MODEL_STATE=gemini-3.8-flash          # 상태 변경안만 다른 모델 (CANON_MODEL_PLAN / _WRITE / _CHECK / _STATE / _NAME)
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
canon/elements.py  인과율: 이야기 요소의 관련 화 찾기, 화별로 넣을 요소 고르기 (LLM 없이)
canon/dynamics.py  관계 역학 수식 (사건 적용, 긴장 계산, 재생, 말로 바꾸기)
canon/naming.py    이름·지명 무작위 생성과 출연진 이름 점검 (자료는 naming_data.py)
canon/llm.py       Gemini, 로컬(OpenAI 호환) 프로바이더와 단계별 선택 (+ mock.py)
canon/research.py  연구 화면 로직: 서버 점검, 샘플 비교, 단계 시험, 컨텍스트 크기, 블라인드 비교
canon/store.py     project.json 저장, 본문을 episodes/NN.md 로 내보내기
canon/library.py   문체 라이브러리 (작품과 따로 저장하는 문체 항목)
canon/cli.py       명령줄
canon/web.py       웹 UI 서버 (FastAPI) + canon/static/ 화면
canon/jobs.py      웹에서 오래 걸리는 AI 작업을 백그라운드로 돌리고 진행 상황을 알려 줌
canon/autorun.py   목표 화까지 자동 집필 (승인 정책, 배치, 비용 추정, 이어 가기)
tests/             흐름 테스트 (mock LLM, 가짜 OpenAI 호환 서버)
```
