from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.media.cos_storage import CosStorage
from app.media.image_provider import DashScopeImageClient, ImageProviderRejected
from app.repositories import visual_asset_repository
from app.services.visualization_policy import prompt_hash

logger = logging.getLogger(__name__)


class VisualAssetService:
    def __init__(self, provider: Any | None = None, storage: Any | None = None):
        self._provider_injected = provider is not None
        self._storage_injected = storage is not None
        self.provider = provider or DashScopeImageClient()
        self.storage = storage or CosStorage()
        self._semaphore = asyncio.Semaphore(max(1, get_settings().image_generation_max_concurrency))
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _available(self) -> bool:
        settings = get_settings()
        provider_ready = self._provider_injected or bool(settings.dashscope_api_key)
        storage_ready = self._storage_injected or bool(getattr(self.storage, "enabled", False))
        return bool(settings.image_generation_enabled and settings.cos_enabled and provider_ready and storage_ready)

    async def schedule(
        self,
        pool: Any,
        question: Any,
        *,
        task_id: str | None,
        quiz_id: str | None,
        user_id: int | None,
        guest_token_hash: str | None = None,
    ) -> str | None:
        settings = get_settings()
        visualization = question.visualization
        if not visualization or not visualization.enabled:
            return None
        if not self._available() or pool is None or not visualization.image_prompt:
            failed = visualization.model_copy(update={"status": "failed"})
            question.visualization = failed
            if pool is not None:
                async with pool.acquire() as connection:
                    await visual_asset_repository.update_question_visualization(
                        connection,
                        task_id=task_id,
                        quiz_id=quiz_id,
                        question_id=question.id,
                        visualization=failed.model_dump(),
                    )
            return None
        hashed = prompt_hash(visualization.image_prompt)
        asset_id = f"asset_{uuid4().hex}"
        dedupe_key = f"{task_id or quiz_id}:{question.id}:{hashed}"
        async with pool.acquire() as connection:
            asset = await visual_asset_repository.create_or_get_asset(
                connection,
                asset_id=asset_id,
                dedupe_key=dedupe_key,
                task_id=task_id,
                quiz_id=quiz_id,
                question_id=question.id,
                user_id=user_id,
                guest_token_hash=guest_token_hash,
                prompt_hash=hashed,
                image_prompt=visualization.image_prompt,
                alt_text=visualization.alt_text or "技术示意图",
                model_name=settings.image_generation_model,
                visualization_type=visualization.type or "conceptual",
            )
        actual_asset_id = str(asset["asset_id"])
        if asset.get("status") in {"ready", "failed", "generating", "uploading"}:
            return actual_asset_id
        task = asyncio.create_task(
            self.process(
                pool,
                actual_asset_id,
                visualization.image_prompt,
                task_id=task_id,
                quiz_id=quiz_id,
                question_id=question.id,
                alt_text=visualization.alt_text or "技术示意图",
                visualization_type=visualization.type or "conceptual",
            ),
            name=f"visual-asset-{actual_asset_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return actual_asset_id

    async def process(
        self,
        pool: Any,
        asset_id: str,
        image_prompt: str,
        *,
        task_id: str | None,
        quiz_id: str | None,
        question_id: str,
        alt_text: str = "技术示意图",
        visualization_type: str = "conceptual",
    ) -> None:
        settings = get_settings()
        async with pool.acquire() as connection:
            if not await visual_asset_repository.claim_asset(connection, asset_id):
                return
        for attempt in range(settings.image_generation_retry_count + 1):
            try:
                async with self._semaphore:
                    image = await self.provider.generate(image_prompt)
                    async with pool.acquire() as connection:
                        await visual_asset_repository.mark_uploading(connection, asset_id)
                    key = f"easyoffer/quiz-assets/{quiz_id or task_id}/{question_id}/{prompt_hash(image_prompt)}.{image.mime_type.split('/')[-1]}"
                    image_url = await self.storage.upload(key, image)
                visualization = {
                    "enabled": True,
                    "mode": "image",
                    "type": visualization_type,
                    "image_prompt": image_prompt,
                    "alt_text": alt_text,
                    "asset_id": asset_id,
                    "image_url": image_url,
                    "status": "ready",
                }
                async with pool.acquire() as connection:
                    await visual_asset_repository.mark_ready(
                        connection,
                        asset_id,
                        cos_key=key,
                        image_url=image_url,
                        mime_type=image.mime_type,
                        width=image.width,
                        height=image.height,
                    )
                    await visual_asset_repository.update_question_visualization(
                        connection,
                        task_id=task_id,
                        quiz_id=quiz_id,
                        question_id=question_id,
                        visualization=visualization,
                    )
                return
            except Exception as exc:
                logger.warning(
                    "visual_asset_processing_failed asset_id=%s attempt=%s error_type=%s",
                    asset_id,
                    attempt + 1,
                    type(exc).__name__,
                )
                if isinstance(exc, ImageProviderRejected) or attempt >= settings.image_generation_retry_count:
                    async with pool.acquire() as connection:
                        await visual_asset_repository.mark_failed(connection, asset_id, str(exc) or "图片生成失败", attempt + 1)
                        await visual_asset_repository.update_question_visualization(
                            connection,
                            task_id=task_id,
                            quiz_id=quiz_id,
                            question_id=question_id,
                            visualization={
                                "enabled": True,
                                "mode": "image",
                                "type": visualization_type,
                                "image_prompt": image_prompt,
                                "alt_text": alt_text,
                                "asset_id": asset_id,
                                "image_url": None,
                                "status": "failed",
                            },
                        )
