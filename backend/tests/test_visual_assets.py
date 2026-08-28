from __future__ import annotations

import base64
import asyncio
import io

import pytest
from PIL import Image

from app.media.image_provider import (
    DashScopeImageClient,
    GeneratedImage,
    ImageProviderRejected,
    validate_image_bytes,
)
from app.media.cos_storage import CosStorage, CosStorageError
from app.models.quiz import QuestionVisualization, QuizGenerateRequest
from app.services.visual_asset_service import VisualAssetService
from app.services.visualization_policy import prepare_question_visualizations, prompt_hash
from app.llm.deepseek import _normalize_quiz_payload
from tests.sample_data import make_quiz


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_visualization_is_backward_compatible_and_policy_sets_pending():
    request = QuizGenerateRequest(user_input="RAG 技术", generate_images=True)
    question = make_quiz(request).questions[0].model_copy(
        update={
            "visualization": QuestionVisualization(
                enabled=True,
                mode="image",
                type="flowchart",
                image_prompt="展示检索到生成的流程",
                alt_text="RAG 流程图",
            )
        }
    )
    prepared = prepare_question_visualizations([question], True)[0]
    assert prepared.visualization is not None
    assert prepared.visualization.status == "pending"
    assert prepared.visualization.asset_id is None
    assert make_quiz(QuizGenerateRequest(user_input="RAG 技术")).questions[0].visualization is None


def test_deepseek_payload_normalizes_visualization_fields():
    request = QuizGenerateRequest(user_input="RAG 技术", generate_images=True)
    source = make_quiz(request).questions[0].model_dump()
    source["visualization"] = {"enabled": True, "type": "flowchart", "image_prompt": "RAG 流程", "alt_text": "流程"}
    normalized = _normalize_quiz_payload({"questions": [source]}, request)
    visualization = normalized["quiz"]["questions"][0]["visualization"]
    assert visualization["mode"] == "image"
    assert visualization["status"] == "pending"


def test_visualization_policy_caps_and_sanitizes_prompts(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_max_per_quiz", 1)
    request = QuizGenerateRequest(user_input="Redis", generate_images=True)
    questions = []
    for index, question in enumerate(make_quiz(request).questions[:2]):
        questions.append(
            question.model_copy(
                update={
                    "visualization": QuestionVisualization(
                        enabled=True,
                        mode="image",
                        type="conceptual",
                        image_prompt=f"API_KEY=secret {index}",
                        alt_text="示意图",
                    )
                }
            )
        )
    prepared = prepare_question_visualizations(questions, True)
    assert prepared[0].visualization is not None
    assert "secret" not in prepared[0].visualization.image_prompt
    assert "简体中文" in prepared[0].visualization.image_prompt
    assert "禁止出现英文" in prepared[0].visualization.image_prompt
    assert prepared[1].visualization is None
    assert prompt_hash("same") == prompt_hash("same")
    assert prompt_hash("same") != prompt_hash("other")


def test_validate_image_bytes_rejects_invalid_data():
    image = validate_image_bytes(_png_bytes(), 1024 * 1024)
    assert isinstance(image, GeneratedImage)
    assert image.mime_type == "image/png"
    assert image.width == 512
    with pytest.raises(Exception):
        validate_image_bytes(b"not-an-image", 1024 * 1024)


def test_cos_storage_upload_returns_public_url(monkeypatch):
    from types import SimpleNamespace

    class Client:
        acl = None

        def put_object(self, **_kwargs):
            return {"ETag": "ok"}

        def put_object_acl(self, **kwargs):
            self.acl = kwargs

    storage = object.__new__(CosStorage)
    storage._client = Client()
    storage.settings = SimpleNamespace(
        cos_bucket="easyoffer-123",
        cos_public_base_url="https://cdn.example.com",
        cos_public_read=True,
        cos_signed_url_expire_seconds=3600,
    )
    result = __import__("asyncio").run(storage.upload("easyoffer/q1.webp", GeneratedImage(_png_bytes(), "image/png", 512, 512)))
    assert result == "https://cdn.example.com/easyoffer/q1.webp"
    assert storage._client.acl["ACL"] == "public-read"


def test_cos_storage_private_mode_returns_signed_url():
    from types import SimpleNamespace

    class Client:
        def put_object(self, **_kwargs):
            return {"ETag": "ok"}

        def get_presigned_download_url(self, **kwargs):
            assert kwargs["Expired"] == 900
            return "https://signed.example.com/image"

    storage = object.__new__(CosStorage)
    storage._client = Client()
    storage.settings = SimpleNamespace(
        cos_bucket="easyoffer-123",
        cos_public_base_url=None,
        cos_public_read=False,
        cos_signed_url_expire_seconds=900,
    )
    result = asyncio.run(storage.upload("easyoffer/q1.png", GeneratedImage(_png_bytes(), "image/png", 512, 512)))
    assert result == "https://signed.example.com/image"


def test_cos_storage_wraps_sdk_failures():
    from types import SimpleNamespace

    class Client:
        def put_object(self, **_kwargs):
            raise RuntimeError("secret provider detail")

    storage = object.__new__(CosStorage)
    storage._client = Client()
    storage.settings = SimpleNamespace(
        cos_bucket="easyoffer-123",
        cos_public_base_url=None,
        cos_public_read=True,
        cos_signed_url_expire_seconds=900,
    )
    with pytest.raises(CosStorageError, match="COS 图片上传失败"):
        asyncio.run(storage.upload("easyoffer/q1.png", GeneratedImage(_png_bytes(), "image/png", 512, 512)))


def test_dashscope_client_accepts_base64_response(monkeypatch):
    from app.core.config import get_settings
    import app.media.image_provider as provider_module

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_model", "qwen-image-2.0")
    monkeypatch.setattr(settings, "image_generation_enabled", True)
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "image_generation_max_bytes", 1024 * 1024)
    encoded = base64.b64encode(_png_bytes()).decode()

    class Response:
        content = b""
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"output": {"choices": [{"message": {"content": [{"b64_json": encoded}]}}]}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(DashScopeImageClient().generate("生成一个技术流程示意图"))
    assert result.width == 512
    assert result.height == 512


def test_z_image_turbo_uses_async_image_generation_and_polls(monkeypatch):
    from app.core.config import get_settings
    import app.media.image_provider as provider_module

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_model", "z-image-turbo")
    monkeypatch.setattr(settings, "image_generation_enabled", True)
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "image_generation_poll_interval_seconds", 0)
    encoded = base64.b64encode(_png_bytes()).decode()
    requests: list[tuple[str, dict]] = []

    class Response:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, headers, **_kwargs):
            requests.append((url, headers))
            return Response({"output": {"task_id": "task-1", "task_status": "PENDING"}})

        async def get(self, url, headers, **_kwargs):
            requests.append((url, headers))
            return Response(
                {
                    "output": {
                        "task_id": "task-1",
                        "task_status": "SUCCEEDED",
                        "choices": [
                            {"message": {"content": [{"image": "https://provider.example/image.png"}]}}
                        ],
                    }
                }
            )

    class DownloadClient(Client):
        async def get(self, url, headers=None, **_kwargs):
            if url.startswith("https://provider.example"):
                return type("ImageResponse", (), {"status_code": 200, "content": _png_bytes(), "raise_for_status": lambda self: None})()
            return await super().get(url, headers or {})

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", lambda **_kwargs: DownloadClient())
    result = asyncio.run(DashScopeImageClient().generate("RAG 检索流程图"))
    assert result.width == 512
    assert requests[0][0].endswith("/services/aigc/image-generation/generation")
    assert requests[0][1]["X-DashScope-Async"] == "enable"
    assert requests[1][0].endswith("/tasks/task-1")


def test_z_image_turbo_derives_workspace_endpoint(monkeypatch):
    from app.core.config import get_settings
    import app.media.image_provider as provider_module

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_model", "z-image-turbo")
    monkeypatch.setattr(settings, "image_generation_enabled", True)
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "image_generation_base_url", None)
    monkeypatch.setattr(settings, "dashscope_workspace_id", "ws-test")
    monkeypatch.setattr(settings, "dashscope_region", "cn-beijing")
    monkeypatch.setattr(settings, "image_generation_poll_interval_seconds", 0)
    encoded = base64.b64encode(_png_bytes()).decode()
    urls: list[str] = []

    class Response:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **_kwargs):
            urls.append(url)
            return Response({"output": {"task_id": "task-1"}})

        async def get(self, url, **_kwargs):
            urls.append(url)
            if url.startswith("https://provider.example"):
                return type("ImageResponse", (), {"status_code": 200, "content": _png_bytes(), "raise_for_status": lambda self: None})()
            return Response({"output": {"task_status": "SUCCEEDED", "choices": [{"message": {"content": [{"image": "https://provider.example/image.png"}]}}]}})

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(DashScopeImageClient().generate("RAG 流程图"))
    assert result.width == 512
    assert urls[0].startswith("https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1/")
    assert urls[1].startswith("https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1/")


def test_image_endpoint_adds_https_for_host_only_configuration(monkeypatch):
    from app.core.config import get_settings
    from app.media.image_provider import _image_generation_base_url

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_base_url", "ws-test.cn-beijing.maas.aliyuncs.com")
    assert _image_generation_base_url(settings) == "https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1"


def test_dashscope_client_reports_non_retryable_provider_rejection(monkeypatch):
    from app.core.config import get_settings
    import app.media.image_provider as provider_module

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_enabled", True)
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")

    class Response:
        status_code = 400

        def json(self):
            return {"code": "Arrearage", "message": "provider account detail"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", lambda **_kwargs: Client())
    with pytest.raises(ImageProviderRejected, match="Arrearage"):
        asyncio.run(DashScopeImageClient().generate("技术流程示意图"))


def test_visual_asset_failure_only_marks_visualization_failed(monkeypatch):
    from app.core.config import get_settings
    from app.repositories import visual_asset_repository

    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_retry_count", 1)
    calls: list[tuple] = []

    class Provider:
        async def generate(self, _prompt):
            raise RuntimeError("provider unavailable")

    class Storage:
        enabled = True

    class ConnectionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return ConnectionContext()

    async def claim_asset(_connection, asset_id):
        calls.append(("claim", asset_id))
        return True

    async def mark_failed(_connection, asset_id, message, retry_count):
        calls.append(("failed", asset_id, message, retry_count))

    async def update_visualization(_connection, **kwargs):
        calls.append(("visualization", kwargs["visualization"]))

    monkeypatch.setattr(visual_asset_repository, "claim_asset", claim_asset)
    monkeypatch.setattr(visual_asset_repository, "mark_failed", mark_failed)
    monkeypatch.setattr(visual_asset_repository, "update_question_visualization", update_visualization)

    service = VisualAssetService(provider=Provider(), storage=Storage())
    asyncio.run(
        service.process(
            Pool(),
            "asset-1",
            "RAG 数据流示意图",
            task_id="task-1",
            quiz_id=None,
            question_id="q1",
            alt_text="RAG 数据流",
            visualization_type="flowchart",
        )
    )

    failed = next(item for item in calls if item[0] == "failed")
    assert failed[3] == 2
    snapshot = next(item[1] for item in calls if item[0] == "visualization")
    assert snapshot["status"] == "failed"
    assert snapshot["type"] == "flowchart"
    assert snapshot["image_url"] is None
