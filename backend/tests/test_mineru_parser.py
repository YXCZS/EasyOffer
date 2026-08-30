import asyncio
import io
import zipfile

import pytest

from app.services.knowledge_service import MinerUParser


class FakeResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return next(self.responses)

    async def put(self, url, **kwargs):
        self.calls.append(("put", url, kwargs))
        return next(self.responses)

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return next(self.responses)


def make_archive(text: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("example/full.md", text)
        bundle.writestr("example/content_list.json", "[]")
    return output.getvalue()


def test_mineru_parser_uploads_polls_and_reads_full_markdown(tmp_path, monkeypatch):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"pdf bytes")
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_api_token", "test-token")
    monkeypatch.setattr(settings, "mineru_poll_interval_seconds", 0)
    client = FakeClient(
        [
            FakeResponse({"code": 0, "data": {"batch_id": "batch-1", "file_urls": ["https://upload.test"]}}),
            FakeResponse({}, status_code=200),
            FakeResponse({"code": 0, "data": {"extract_result": []}}),
            FakeResponse({"code": 0, "data": {"extract_result": [{"file_name": "notes.pdf", "state": "running"}]}}),
            FakeResponse({"code": 0, "data": {"extract_result": [{"file_name": "notes.pdf", "state": "done", "full_zip_url": "https://result.test"}]}}),
            FakeResponse(content=make_archive("# Structured notes\n\nRAG content")),
        ]
    )

    parser = MinerUParser(client_factory=lambda **_kwargs: client)
    text = asyncio.run(parser.parse(str(source), document_id="doc-1", original_name="notes.pdf"))

    assert text == "# Structured notes\n\nRAG content"
    assert [call[0] for call in client.calls] == ["post", "put", "get", "get", "get", "get"]
    assert client.calls[0][2]["json"]["model_version"] == settings.mineru_model_version
    assert client.calls[0][2]["json"]["files"][0]["data_id"] == "doc-1"


def test_mineru_parser_rejects_zip_slip(tmp_path, monkeypatch):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"pdf bytes")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("../full.md", "unsafe")
    with pytest.raises(ValueError):
        MinerUParser._extract_markdown(output.getvalue())


def test_mineru_parser_requires_token(tmp_path, monkeypatch):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"pdf bytes")
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_api_token", None)
    with pytest.raises(RuntimeError, match="MINERU_API_TOKEN"):
        asyncio.run(MinerUParser(client_factory=lambda **_kwargs: None).parse(str(source), document_id="doc-1", original_name="notes.pdf"))
