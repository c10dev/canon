"""웹 서버의 Host · Origin 검사 (DNS 리바인딩 · CSRF 막기)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from canon import web


@pytest.fixture()
def client():
    return TestClient(web.app)


@pytest.mark.parametrize("host", [
    "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "100.101.102.103", "192.168.0.7:8000",
    "[fd7a:115c:a1e0::1]:8446", "canon-box.tail1234.ts.net:8446", "CANON-BOX.tail1234.ts.net", "testserver",
])
def test_allowed_hosts_pass(client, host):
    assert client.get("/api/projects", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8000", "localhost.evil.com", "ts.net.evil.com", ""])
def test_other_domain_names_are_rejected(client, host):
    r = client.get("/api/projects", headers={"host": host})
    assert r.status_code == 403
    assert "CANON_ALLOWED_HOSTS" in r.json()["detail"]


def test_machine_hostname_passes(client, monkeypatch):
    monkeypatch.setattr(web.socket, "gethostname", lambda: "Vocado-Dev")
    web._machine_names.cache_clear()
    try:
        assert client.get("/api/projects", headers={"host": "vocado-dev:8000"}).status_code == 200
        assert client.get("/api/projects", headers={"host": "vocado-dev.local"}).status_code == 200
    finally:
        web._machine_names.cache_clear()


def test_env_adds_names(client, monkeypatch):
    assert client.get("/", headers={"host": "canon.home.arpa"}).status_code == 403
    monkeypatch.setenv("CANON_ALLOWED_HOSTS", "testserver, canon.home.arpa:8000")
    assert client.get("/api/projects", headers={"host": "canon.home.arpa"}).status_code == 200


def test_cross_site_write_is_rejected(client):
    r = client.post("/api/update/check", headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403 and "다른 사이트" in r.json()["detail"]
    assert client.post("/api/update/check", headers={"origin": "null"}).status_code == 403
    # 읽기 요청은 Origin 을 보지 않는다 (Host 검사만)
    assert client.get("/api/projects", headers={"origin": "https://evil.example.com"}).status_code == 200


def test_same_origin_and_no_origin_writes_pass(client):
    assert client.post("/api/update/check").status_code == 200  # 명령줄 · curl · GitHub Actions
    assert client.post("/api/update/check", headers={"origin": "http://testserver"}).status_code == 200
    h = {"host": "canon-box.tail1234.ts.net:8446", "origin": "https://canon-box.tail1234.ts.net:8446"}
    assert client.post("/api/update/check", headers=h).status_code == 200


def test_proxy_forwarded_host_matches_origin(client):
    # tailscale serve 가 Host 를 127.0.0.1 로 바꿔 보내도 X-Forwarded-Host 로 같은 출처를 안다
    h = {"host": "127.0.0.1:8000", "x-forwarded-host": "canon-box.tail1234.ts.net:8446",
         "origin": "https://canon-box.tail1234.ts.net:8446"}
    assert client.post("/api/update/check", headers=h).status_code == 200
    h["origin"] = "https://other.tail1234.ts.net"
    assert client.post("/api/update/check", headers=h).status_code == 403
