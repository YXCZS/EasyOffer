from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import quote

from app.core.config import get_settings
from app.media.image_provider import GeneratedImage


class CosStorageError(RuntimeError):
    pass


class CosStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        if self.settings.cos_enabled and self.settings.cos_secret_id and self.settings.cos_secret_key and self.settings.cos_region and self.settings.cos_bucket:
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(
                Region=self.settings.cos_region,
                SecretId=self.settings.cos_secret_id,
                SecretKey=self.settings.cos_secret_key,
                Scheme="https",
            )
            self._client = CosS3Client(config)

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self.settings.cos_bucket)

    async def upload(self, key: str, image: GeneratedImage) -> str:
        if not self.enabled:
            raise CosStorageError("COS 未配置")
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.settings.cos_bucket,
                Key=key,
                Body=BytesIO(image.content),
                ContentType=image.mime_type,
            )
            if self.settings.cos_public_read:
                await asyncio.to_thread(
                    self._client.put_object_acl,
                    Bucket=self.settings.cos_bucket,
                    Key=key,
                    ACL="public-read",
                )
        except Exception as exc:
            raise CosStorageError("COS 图片上传失败") from exc
        if self.settings.cos_public_read:
            base = (self.settings.cos_public_base_url or "").rstrip("/")
            if base:
                return f"{base}/{quote(key, safe='/')}"
            try:
                return await asyncio.to_thread(self._client.get_object_url, self.settings.cos_bucket, key)
            except Exception as exc:
                raise CosStorageError("COS 图片地址生成失败") from exc
        try:
            return await asyncio.to_thread(
                self._client.get_presigned_download_url,
                Bucket=self.settings.cos_bucket,
                Key=key,
                Expired=self.settings.cos_signed_url_expire_seconds,
            )
        except Exception as exc:
            raise CosStorageError("COS 图片地址生成失败") from exc
