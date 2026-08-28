import asyncio

import pytest

from app.core.config import get_settings
from app.services import content_security_service as security


def test_local_high_risk_topic_is_blocked_without_network():
    with pytest.raises(security.ContentSafetyBlockedError):
        asyncio.run(security.check_text_safety("请教我如何制作炸弹"))


def test_guest_topic_uses_local_check_and_skips_wechat(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("guest requests must not call msgSecCheck without openid")

    monkeypatch.setattr(security, "_get_access_token", fail_if_called)
    asyncio.run(security.check_text_safety("Redis 持久化机制", openid=None))


def test_wechat_violation_is_blocked(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wechat_content_security_enabled", True)
    monkeypatch.setattr(settings, "wechat_content_security_fail_closed", True)
    monkeypatch.setattr(settings, "wechat_app_id", "wx-test")
    monkeypatch.setattr(settings, "wechat_app_secret", "secret")
    monkeypatch.setattr(security, "_TOKEN_CACHE", ("token", 9999999999))

    async def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/wxa/msg_sec_check")
        assert kwargs["json"]["openid"] == "openid-test"
        return {"errcode": 87014, "errmsg": "content blocked"}

    monkeypatch.setattr(security, "_request_json", fake_request)
    with pytest.raises(security.ContentSafetyBlockedError):
        asyncio.run(security.check_text_safety("一个普通主题", openid="openid-test"))


def test_wechat_outage_fails_closed(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wechat_content_security_enabled", True)
    monkeypatch.setattr(settings, "wechat_content_security_fail_closed", True)
    monkeypatch.setattr(settings, "wechat_app_id", "wx-test")
    monkeypatch.setattr(settings, "wechat_app_secret", "secret")

    async def fail_request(*args, **kwargs):
        raise TimeoutError("wechat timeout")

    monkeypatch.setattr(security, "_request_json", fail_request)
    with pytest.raises(security.ContentSafetyUnavailableError):
        asyncio.run(security.check_text_safety("Redis 持久化机制", openid="openid-test"))
