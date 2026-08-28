from __future__ import annotations

import base64
import binascii
import io
import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image

from app.core.config import get_settings


DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"


def _image_generation_base_url(settings: Any) -> str:
    """Resolve explicit, workspace-derived, or public DashScope endpoint."""
    configured = str(getattr(settings, "image_generation_base_url", "") or "").strip()
    if configured:
        if "://" not in configured:
            configured = f"https://{configured}"
        parsed = urlsplit(configured)
        path = parsed.path.rstrip("/") or "/api/v1"
        if path == "/api":
            path = "/api/v1"
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)).rstrip("/")
    workspace_id = str(getattr(settings, "dashscope_workspace_id", "") or "").strip()
    if workspace_id:
        region = str(getattr(settings, "dashscope_region", "cn-beijing") or "cn-beijing").strip()
        return f"https://{workspace_id}.{region}.maas.aliyuncs.com/api/v1"
    return DEFAULT_DASHSCOPE_BASE_URL


class ImageProviderError(RuntimeError):
    pass


class ImageProviderUnavailable(ImageProviderError):
    pass


class ImageProviderRejected(ImageProviderError):
    """The provider rejected the request and retrying it unchanged cannot help."""

    pass


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    mime_type: str
    width: int
    height: int


def _find_image_value(value: Any) -> tuple[str, str] | None:
    if isinstance(value, dict):
        for key in ("b64_json", "base64", "data"):
            candidate = value.get(key)
            if isinstance(candidate, str) and len(candidate) > 100:
                return "base64", candidate
        for key in ("url", "image", "image_url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return "url", candidate
        for candidate in value.values():
            found = _find_image_value(candidate)
            if found:
                return found
    elif isinstance(value, list):
        for candidate in value:
            found = _find_image_value(candidate)
            if found:
                return found
    return None


def _decode_data_url(value: str) -> bytes:
    payload = value.split(",", 1)[1] if "," in value else value
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ImageProviderError("百炼返回的 base64 图片无效") from exc


def validate_image_bytes(content: bytes, max_bytes: int) -> GeneratedImage:
    if not content or len(content) > max_bytes:
        raise ImageProviderError("图片为空或超过大小限制")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            mime_type = Image.MIME.get(image.format or "")
    except Exception as exc:
        raise ImageProviderError("返回内容不是有效图片") from exc
    if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ImageProviderError("图片格式不受支持")
    return GeneratedImage(content=content, mime_type=mime_type, width=width, height=height)


class DashScopeImageClient:
    """Small async adapter for DashScope's multimodal image generation API."""

    async def generate(self, prompt: str) -> GeneratedImage:
        settings = get_settings()
        if not settings.image_generation_enabled or not settings.dashscope_api_key:
            raise ImageProviderUnavailable("图片生成功能未配置")
        if not prompt or len(prompt) > settings.image_generation_max_prompt_chars:
            raise ImageProviderError("生图提示词为空或过长")
        is_async_model = settings.image_generation_model.lower() == "z-image-turbo"
        base_url = _image_generation_base_url(settings)
        endpoint = base_url + (
            "/services/aigc/image-generation/generation"
            if is_async_model
            else "/services/aigc/multimodal-generation/generation"
        )
        payload = {
            "model": settings.image_generation_model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {"size": settings.image_generation_size, "n": 1},
        }
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        if is_async_model:
            headers["X-DashScope-Async"] = "enable"
        timeout = httpx.Timeout(settings.image_generation_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            self._raise_for_provider_error(response)
            response.raise_for_status()
            body = response.json()
            if is_async_model:
                body = await self._wait_for_task(client, body, headers, settings)
            found = _find_image_value(body)
            if not found:
                raise ImageProviderError("百炼响应中未找到图片")
            kind, value = found
            if kind == "url":
                image_response = await client.get(value)
                image_response.raise_for_status()
                content = image_response.content
            else:
                content = _decode_data_url(value)
        return validate_image_bytes(content, settings.image_generation_max_bytes)

    @staticmethod
    def _raise_for_provider_error(response: httpx.Response) -> None:
        if 400 <= response.status_code < 500 and response.status_code not in {408, 429}:
            try:
                error_code = str(response.json().get("code") or response.status_code)[:80]
            except Exception:
                error_code = str(response.status_code)
            raise ImageProviderRejected(f"百炼图片生成请求被拒绝（{error_code}）")

    async def _wait_for_task(
        self,
        client: httpx.AsyncClient,
        body: dict[str, Any],
        headers: dict[str, str],
        settings: Any,
    ) -> dict[str, Any]:
        output = body.get("output") if isinstance(body, dict) else None
        task_id = output.get("task_id") if isinstance(output, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise ImageProviderError("百炼异步任务响应中缺少 task_id")
        deadline = time.monotonic() + settings.image_generation_timeout_seconds
        task_url = _image_generation_base_url(settings) + f"/tasks/{task_id}"
        while True:
            if time.monotonic() >= deadline:
                raise ImageProviderError("百炼图片生成任务超时")
            await asyncio.sleep(min(settings.image_generation_poll_interval_seconds, max(0.0, deadline - time.monotonic())))
            response = await client.get(task_url, headers={"Authorization": headers["Authorization"]})
            self._raise_for_provider_error(response)
            response.raise_for_status()
            result = response.json()
            result_output = result.get("output") if isinstance(result, dict) else None
            task_status = str(result_output.get("task_status") if isinstance(result_output, dict) else "").upper()
            if task_status == "SUCCEEDED":
                return result
            if task_status in {"FAILED", "UNKNOWN", "CANCELED", "CANCELLED"}:
                code = str(result.get("code") or task_status)[:80]
                raise ImageProviderError(f"百炼图片任务失败（{code}）")
