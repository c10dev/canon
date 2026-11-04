# 서버에서 상시 실행 (Tailscale)

README.md 의 웹 UI 절에서 옮겼다. 혼자 쓰는 리눅스 서버에 Canon 을 늘 켜 두고, 내 기기에서만 여는 방법이다.

Vercel 같은 서버리스 호스팅은 맞지 않는다. 소설 데이터를 파일(`project.json`)에 저장하고 Gemini 호출이 길게 걸리기 때문이다. 항상 켜져 있는 리눅스 서버가 있으면 systemd 로 돌리고 Tailscale 로 내 기기에서만 연다. Canon 에는 로그인이 없으니 **Tailscale Funnel 이나 공개 포트로 열지 않는다**.

```bash
# 서버에서: 저장소를 받고 가상환경 준비
git clone https://github.com/c10dev/canon ~/canon && cd ~/canon
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
# deploy/canon.service 의 USER 와 경로를 고친 뒤 등록 (부팅 때 자동 실행)
sudo cp deploy/canon.service /etc/systemd/system/canon.service
sudo systemctl daemon-reload && sudo systemctl enable --now canon
# tailnet 안에서만 HTTPS 로 열기 (8446 은 비어 있는 아무 포트)
sudo tailscale serve --bg --https=8446 http://127.0.0.1:8000
```

그러면 같은 tailnet 의 맥, 아이폰에서 `https://<서버이름>.<tailnet>.ts.net:8446` 로 열린다. 작품은 서버의 `~/canon/projects/` 에, API 키는 서버 계정의 `~/.canon/config.json` 에 저장된다. 다른 컴퓨터에서 쓰던 작품은 `projects/<이름>/` 폴더를 그대로 복사하면 된다. 포트 대시보드(예: Portboard)를 쓰고 있으면 systemd 서비스 이름 `Canon - AI 소설 작성 웹 UI` 로 잡힌다. 로그는 `journalctl -u canon -f`.

## 머지 전에 시험 돌리기

PR 과 `main` 푸시마다 GitHub Actions(`.github/workflows/test.yml`)가 전체 시험을 돌린다. 시험은 가짜 응답만 써서 비밀값이 필요 없다. 서버는 `main` 을 자동으로 받으므로, 시험이 실패한 PR 은 머지하지 않는다.

## 머지하면 바로 받기

서버는 10분마다 새 코드를 확인한다. `main` 에 머지하자마자 받게 하려면 GitHub Actions(`.github/workflows/notify-server.yml`)가 머지 때마다 Tailscale 로 들어와 서버의 `POST /api/update/check` 를 부르게 한다. 이 요청은 확인을 앞당길 뿐이고, 코드는 늘 `origin/main` 에서만 받는다. 진행 중인 AI 작업이 있으면 그 작업이 끝난 뒤 다시 시작하는 것은 같다.

1. Tailscale 관리 화면의 Access controls 에 태그와 규칙을 더한다. 러너는 서버의 Canon 포트에만 들어간다.
   ```json
   "tagOwners": { "tag:ci": ["autogroup:admin"] },
   "grants": [{ "src": ["tag:ci"], "dst": ["<서버의 Tailscale IP 또는 태그>"], "ip": ["tcp:8446"] }]
   ```
2. Settings → OAuth clients 에서 `auth_keys` 쓰기 권한과 태그 `tag:ci` 로 OAuth 클라이언트를 만든다.
3. GitHub 저장소 Settings → Secrets and variables → Actions 에 넣는다.
   - 비밀값 `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`: 2에서 만든 값
   - 변수 `CANON_SERVER_URL`: `https://<서버이름>.<tailnet>.ts.net:8446` (끝에 / 없이)
4. Actions 탭에서 '서버에 새 코드 알리기'를 손으로 한 번 돌려(Run workflow) 서버 로그(`journalctl -u canon -f`)에 `[업데이트]` 줄이 바로 찍히는지 본다.

`CANON_SERVER_URL` 이 없으면 워크플로는 돌지 않는다.
