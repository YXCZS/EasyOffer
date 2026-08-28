"""Text content safety checks for user-provided learning topics."""

from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import DomainError

logger = logging.getLogger(__name__)


class ContentSafetyBlockedError(DomainError):
    def __init__(self) -> None:
        super().__init__(4002, "该内容不适合作为学习主题，请修改后重试。", 400, {"safety_blocked": True})


class ContentSafetyUnavailableError(DomainError):
    def __init__(self) -> None:
        super().__init__(5032, "内容安全服务暂时不可用，请稍后重试。", 503)


@dataclass(frozen=True)
class LocalMatch:
    category: str
    term: str


# High-confidence emergency rules. WeChat remains authoritative for logged-in
# users and provides the continuously updated policy model.
_LOCAL_TERMS: dict[str, tuple[str, ...]] = {
    "violence": ("制作炸弹", "制造炸弹", "制作武器", "杀人教程", "爆炸物制作"),
    "sexual": ("色情", "淫秽", "裸体", "成人视频"),
    "political": ("颠覆国家政权", "分裂国家", "恐怖主义宣传", "政治敏感内容", "推翻政府", "台独宣传"),
    "illegal": ("洗钱教程", "贩毒教程", "诈骗教程", "入侵他人账号"),
}

_TOKEN_CACHE: tuple[str, float] | None = None
_TOKEN_LOCK = asyncio.Lock()


def _normalize_for_match(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _find_local_match(value: str) -> LocalMatch | None:
    normalized = _normalize_for_match(value)
    for category, terms in _LOCAL_TERMS.items():
        for term in terms:
            if _normalize_for_match(term) in normalized:
                return LocalMatch(category, term)
    return None


async def _request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    settings = get_settings()
    attempts = max(0, settings.wechat_content_security_max_retries) + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=settings.wechat_content_security_timeout_seconds) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("wechat_security_invalid_response")
                return payload
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
    assert last_error is not None
    raise last_error


async def _get_access_token() -> str:
    global _TOKEN_CACHE
    settings = get_settings()
    now = time.time()
    if _TOKEN_CACHE and _TOKEN_CACHE[1] > now + 60:
        return _TOKEN_CACHE[0]
    async with _TOKEN_LOCK:
        now = time.time()
        if _TOKEN_CACHE and _TOKEN_CACHE[1] > now + 60:
            return _TOKEN_CACHE[0]
        payload = await _request_json(
            "GET",
            "https://api.weixin.qq.com/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": settings.wechat_app_id,
                "secret": settings.wechat_app_secret,
            },
        )
        if payload.get("errcode") or not payload.get("access_token"):
            raise ValueError(f"wechat_access_token_error:{payload.get('errcode', 'missing_token')}")
        expires_in = max(300, int(payload.get("expires_in") or 7200))
        _TOKEN_CACHE = (str(payload["access_token"]), now + expires_in)
        return _TOKEN_CACHE[0]


async def check_text_safety(content: str, openid: str | None = None) -> None:
    """Raise a domain error when a learning topic is unsafe.

    msgSecCheck requires openid. Guests therefore use the local high-risk
    rules only, preserving the existing guest-generation behavior.
    """

    match = _find_local_match(content)
    if match:
        logger.info("content_safety_blocked source=local category=%s", match.category)
        raise ContentSafetyBlockedError()

    settings = get_settings()
    if not settings.wechat_content_security_enabled or not openid:
        return
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        if settings.wechat_content_security_fail_closed:
            logger.error("content_safety_unavailable reason=missing_wechat_credentials")
            raise ContentSafetyUnavailableError()
        logger.warning("content_safety_skipped reason=missing_wechat_credentials")
        return

    try:
        token = await _get_access_token()
        payload = await _request_json(
            "POST",
            "https://api.weixin.qq.com/wxa/msg_sec_check",
            params={"access_token": token},
            json={
                "content": str(content)[:2000],
                "version": settings.wechat_msg_sec_version,
                "scene": settings.wechat_msg_sec_scene,
                "openid": openid,
            },
        )
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        if payload.get("errcode") == 87014 or result.get("suggest") in {"review", "block"}:
            logger.info("content_safety_blocked source=wechat errcode=%s", payload.get("errcode"))
            raise ContentSafetyBlockedError()
        if payload.get("errcode"):
            raise ValueError(f"wechat_msg_sec_error:{payload.get('errcode')}")
    except ContentSafetyBlockedError:
        raise
    except Exception as exc:
        logger.warning("content_safety_unavailable error_type=%s", type(exc).__name__)
        if settings.wechat_content_security_fail_closed:
            raise ContentSafetyUnavailableError() from exc
