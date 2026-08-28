from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, get_current_user
from app.core.config import get_settings


def test_access_token_contains_user_identity():
    token = create_access_token(12, "openid-test")
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["user_id"] == 12
    assert payload["openid"] == "openid-test"
    assert payload["sub"] == "12"


def test_expired_token_is_rejected():
    app = FastAPI()

    @app.get("/private")
    def private(user: dict = Depends(get_current_user)):
        return user

    token = jwt.encode(
        {"user_id": 1, "sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    with TestClient(app) as client:
        response = client.get("/private", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
