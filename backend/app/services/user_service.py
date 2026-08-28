from typing import Any

import httpx

from app.core.auth import create_access_token
from app.core.config import get_settings
from app.repositories import user_repository


async def exchange_code_for_openid(code: str) -> str:
    settings = get_settings()
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise ValueError("微信登录配置不完整")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={"appid": settings.wechat_app_id, "secret": settings.wechat_app_secret, "js_code": code, "grant_type": "authorization_code"},
        )
    payload = response.json()
    if payload.get("errcode") or not payload.get("openid"):
        raise ValueError(payload.get("errmsg") or "微信登录失败")
    return str(payload["openid"])


async def login(connection: Any, code: str) -> dict[str, Any]:
    openid = await exchange_code_for_openid(code)
    user = await user_repository.find_or_create_user(connection, openid)
    return {"token": create_access_token(user["id"], openid), "user": user}
