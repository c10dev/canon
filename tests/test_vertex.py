"""Gemini 를 Vertex AI(Google Cloud 서비스 계정)로 부르기: 설정 값, 화면에 내보내는 값, 클라이언트 만들기, 배치 끄기.
실제 Vertex 호출은 하지 않는다 (가짜 키 파일로 클라이언트만 만든다).

    python -m unittest tests.test_vertex
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["CANON_LLM"] = "mock"
os.environ["CANON_HOME"] = tempfile.mkdtemp()

from canon import autorun, settings  # noqa: E402
from canon.llm import GeminiLLM, MissingKey  # noqa: E402

ENV = ("CANON_GEMINI_AUTH", "GOOGLE_GENAI_USE_VERTEXAI", "CANON_VERTEX_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS",
       "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GEMINI_API_KEY", "GOOGLE_API_KEY", "CANON_LLM")


def fake_key_file(folder: Path, project: str = "demo-project-123") -> Path:
    """google-auth 가 읽을 수 있는 모양의 가짜 서비스 계정 키 (어디에도 등록되지 않은 새 RSA 키)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    path = folder / "sa.json"
    path.write_text(json.dumps({
        "type": "service_account", "project_id": project, "private_key_id": "x", "private_key": pem,
        "client_email": f"canon@{project}.iam.gserviceaccount.com", "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token"}), encoding="utf-8")
    return path


class VertexSettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        patch = mock.patch.dict(os.environ, {"CANON_CONFIG": str(self.dir / "config.json")})
        patch.start()
        self.addCleanup(patch.stop)
        for name in ENV:
            os.environ.pop(name, None)

    def test_default_is_api_key(self):
        self.assertEqual(settings.gemini_auth(), ("key", "default"))
        self.assertEqual(settings.vertex_location(), ("global", "default"))
        self.assertFalse(settings.public()["has_key"])

    def test_project_comes_from_key_file(self):
        key = fake_key_file(self.dir)
        settings.update(gemini_auth="vertex", vertex_credentials=str(key))
        self.assertEqual(settings.gemini_auth(), ("vertex", "file"))
        self.assertEqual(settings.vertex_project(), ("demo-project-123", "key_file"))
        pub = settings.public()
        self.assertTrue(pub["has_key"])
        self.assertTrue(pub["vertex_credentials_found"])
        # 화면에는 경로만 가고 키 내용은 가지 않는다
        self.assertNotIn("PRIVATE KEY", json.dumps(pub))
        self.assertNotIn("PRIVATE KEY", (self.dir / "config.json").read_text(encoding="utf-8"))

    def test_typed_project_wins_and_missing_file_is_not_ready(self):
        settings.update(gemini_auth="vertex", vertex_credentials=str(self.dir / "nope.json"), vertex_project="other")
        self.assertEqual(settings.vertex_project(), ("other", "file"))
        pub = settings.public()
        self.assertFalse(pub["vertex_credentials_found"])
        self.assertFalse(pub["has_key"])

    def test_google_env_switches_to_vertex(self):
        with mock.patch.dict(os.environ, {"GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_CLOUD_PROJECT": "p1",
                                          "GOOGLE_CLOUD_LOCATION": "us-central1"}):
            self.assertEqual(settings.gemini_auth(), ("vertex", "env"))
            self.assertEqual(settings.vertex_project(), ("p1", "env"))
            self.assertEqual(settings.vertex_location(), ("us-central1", "env"))

    def test_client_uses_service_account(self):
        key = fake_key_file(self.dir)
        settings.update(gemini_auth="vertex", vertex_credentials=str(key), vertex_location="us-central1")
        llm = GeminiLLM(model="gemini-4-argon")
        self.assertTrue(llm.vertex)
        self.assertFalse(llm.can_batch)
        self.assertTrue(llm.client.vertexai)
        api = llm.client._api_client
        self.assertEqual((api.project, api.location), ("demo-project-123", "us-central1"))
        self.assertEqual(api._credentials.service_account_email, "canon@demo-project-123.iam.gserviceaccount.com")

    def test_client_errors_are_setting_hints(self):
        settings.update(gemini_auth="vertex", vertex_credentials=str(self.dir / "nope.json"))
        with self.assertRaisesRegex(MissingKey, "찾지 못했어요"):
            GeminiLLM()
        bad = self.dir / "bad.json"
        bad.write_text('{"type": "authorized_user"}', encoding="utf-8")
        settings.update(vertex_credentials=str(bad), vertex_project="p")
        with self.assertRaisesRegex(MissingKey, "서비스 계정 키 파일이 아니에요"):
            GeminiLLM()

    def test_api_key_mode_unchanged(self):
        settings.update(api_key="AIza-test-key-0000")
        llm = GeminiLLM()
        self.assertFalse(llm.vertex)
        self.assertTrue(llm.can_batch)
        self.assertFalse(llm.client.vertexai)

    def test_autorun_skips_batch_on_vertex(self):
        settings.update(provider="gemini")
        self.assertTrue(autorun.batchable("write"))
        settings.update(gemini_auth="vertex")
        self.assertFalse(autorun.batchable("write"))
        settings.update(stages={"write": "local"})
        self.assertFalse(autorun.batchable("write"))


class VertexWebTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from canon.web import app

        self.dir = Path(tempfile.mkdtemp())
        patch = mock.patch.dict(os.environ, {"CANON_CONFIG": str(self.dir / "config.json")})
        patch.start()
        self.addCleanup(patch.stop)
        for name in ENV:
            os.environ.pop(name, None)
        os.environ["CANON_LLM"] = "mock"
        self.client = TestClient(app)

    def test_put_config_saves_path_not_contents(self):
        key = fake_key_file(self.dir)
        r = self.client.put("/api/config", json={"gemini_auth": "vertex", "vertex_credentials": str(key)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["vertex_project"], "demo-project-123")
        r = self.client.put("/api/config", json={"vertex_credentials": key.read_text(encoding="utf-8")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("경로", r.json()["detail"])
        r = self.client.put("/api/config", json={"gemini_auth": "oauth"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
