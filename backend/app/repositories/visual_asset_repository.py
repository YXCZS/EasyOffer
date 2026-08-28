from __future__ import annotations

import json
from typing import Any

import aiomysql


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS quiz_visual_assets (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  asset_id VARCHAR(80) NOT NULL,
  dedupe_key VARCHAR(180) NOT NULL,
  task_id VARCHAR(80) NULL,
  quiz_id VARCHAR(80) NULL,
  question_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  guest_token_hash CHAR(64) NULL,
  mode ENUM('image') NOT NULL DEFAULT 'image',
  visualization_type VARCHAR(30) NOT NULL DEFAULT 'conceptual',
  provider VARCHAR(50) NOT NULL DEFAULT 'dashscope',
  model_name VARCHAR(100) NOT NULL DEFAULT 'z-image-turbo',
  status ENUM('pending','generating','uploading','ready','failed') NOT NULL DEFAULT 'pending',
  prompt_hash CHAR(64) NOT NULL,
  image_prompt VARCHAR(1200) NOT NULL,
  alt_text VARCHAR(200) NOT NULL DEFAULT '',
  cos_key VARCHAR(500) NULL,
  image_url VARCHAR(2000) NULL,
  mime_type VARCHAR(100) NULL,
  width INT NULL,
  height INT NULL,
  error_message VARCHAR(500) NULL,
  retry_count INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_visual_asset_id (asset_id),
  UNIQUE KEY uq_visual_asset_dedupe (dedupe_key),
  KEY idx_visual_asset_task (task_id, status),
  KEY idx_visual_asset_quiz (quiz_id, question_id),
  CONSTRAINT fk_visual_asset_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _format(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("created_at", "updated_at"):
        value = result.get(key)
        if hasattr(value, "strftime"):
            result[key] = value.strftime("%Y-%m-%d %H:%M:%S")
    return result


async def ensure_visual_asset_table(pool: Any) -> None:
    async with pool.acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(CREATE_SQL)
            try:
                await cursor.execute(
                    "ALTER TABLE quiz_visual_assets ADD COLUMN "
                    "visualization_type VARCHAR(30) NOT NULL DEFAULT 'conceptual' AFTER mode"
                )
            except Exception as exc:
                if "duplicate" not in str(exc).lower():
                    raise
        await connection.commit()


async def get_asset(connection: Any, asset_id: str) -> dict[str, Any] | None:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM quiz_visual_assets WHERE asset_id=%s", (asset_id,))
        row = await cursor.fetchone()
    await connection.commit()
    return _format(row)


async def create_or_get_asset(
    connection: Any,
    *,
    asset_id: str,
    dedupe_key: str,
    task_id: str | None,
    quiz_id: str | None,
    question_id: str,
    user_id: int | None,
    guest_token_hash: str | None,
    prompt_hash: str,
    image_prompt: str,
    alt_text: str,
    model_name: str,
    visualization_type: str,
) -> dict[str, Any]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """INSERT INTO quiz_visual_assets
            (asset_id,dedupe_key,task_id,quiz_id,question_id,user_id,guest_token_hash,
             prompt_hash,image_prompt,alt_text,model_name,visualization_type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE asset_id=asset_id""",
            (
                asset_id,
                dedupe_key,
                task_id,
                quiz_id,
                question_id,
                user_id,
                guest_token_hash,
                prompt_hash,
                image_prompt,
                alt_text,
                model_name,
                visualization_type,
            ),
        )
    await connection.commit()
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM quiz_visual_assets WHERE dedupe_key=%s", (dedupe_key,))
        row = await cursor.fetchone()
    await connection.commit()
    if row is None:
        raise RuntimeError("图片资源任务创建后未找到")
    return _format(row) or {}


async def claim_asset(connection: Any, asset_id: str) -> bool:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """UPDATE quiz_visual_assets SET status='generating', updated_at=CURRENT_TIMESTAMP
            WHERE asset_id=%s AND status='pending'""",
            (asset_id,),
        )
        changed = cursor.rowcount
    await connection.commit()
    return changed == 1


async def mark_uploading(connection: Any, asset_id: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_visual_assets SET status='uploading', updated_at=CURRENT_TIMESTAMP "
            "WHERE asset_id=%s AND status IN ('generating','uploading')",
            (asset_id,),
        )
    await connection.commit()


async def mark_ready(
    connection: Any,
    asset_id: str,
    *,
    cos_key: str,
    image_url: str,
    mime_type: str,
    width: int,
    height: int,
) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """UPDATE quiz_visual_assets SET status='ready', cos_key=%s, image_url=%s,
            mime_type=%s, width=%s, height=%s, error_message=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE asset_id=%s AND status='uploading'""",
            (cos_key, image_url, mime_type, width, height, asset_id),
        )
    await connection.commit()


async def mark_failed(connection: Any, asset_id: str, message: str, retry_count: int) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """UPDATE quiz_visual_assets SET status='failed', error_message=%s,
            retry_count=%s, updated_at=CURRENT_TIMESTAMP
            WHERE asset_id=%s AND status IN ('pending','generating','uploading')""",
            (message[:500], retry_count, asset_id),
        )
    await connection.commit()


async def list_assets_for_task(connection: Any, task_id: str) -> list[dict[str, Any]]:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM quiz_visual_assets WHERE task_id=%s ORDER BY id", (task_id,))
        rows = await cursor.fetchall()
    await connection.commit()
    return [_format(row) for row in rows]


async def list_assets_for_quiz(connection: Any, quiz_id: str) -> list[dict[str, Any]]:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM quiz_visual_assets WHERE quiz_id=%s ORDER BY question_id", (quiz_id,))
        rows = await cursor.fetchall()
    await connection.commit()
    return [_format(row) for row in rows]


async def update_asset_link(connection: Any, asset_id: str, quiz_id: str | None) -> None:
    if not quiz_id:
        return
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_visual_assets SET quiz_id=%s, updated_at=CURRENT_TIMESTAMP WHERE asset_id=%s",
            (quiz_id, asset_id),
        )
    await connection.commit()


async def bind_task_assets(connection: Any, task_id: str, quiz_id: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_visual_assets SET quiz_id=%s, updated_at=CURRENT_TIMESTAMP WHERE task_id=%s",
            (quiz_id, task_id),
        )
    await connection.commit()


async def sync_task_asset_snapshots(connection: Any, task_id: str, quiz_id: str) -> None:
    assets = await list_assets_for_task(connection, task_id)
    for asset in assets:
        if asset.get("status") not in {"ready", "failed"}:
            continue
        visualization = {
            "enabled": True,
            "mode": "image",
            "type": asset.get("visualization_type") or "conceptual",
            "image_prompt": asset.get("image_prompt"),
            "alt_text": asset.get("alt_text") or "技术示意图",
            "asset_id": asset.get("asset_id"),
            "image_url": asset.get("image_url") if asset.get("status") == "ready" else None,
            "status": asset.get("status"),
        }
        await update_question_visualization(
            connection,
            task_id=task_id,
            quiz_id=quiz_id,
            question_id=str(asset["question_id"]),
            visualization=visualization,
        )


async def update_question_visualization(
    connection: Any,
    *,
    task_id: str | None,
    quiz_id: str | None,
    question_id: str,
    visualization: dict[str, Any],
) -> None:
    """Persist the small visualization snapshot in task and/or quiz JSON."""
    if task_id:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT questions_json, quiz_json, quiz_id FROM quiz_generation_tasks "
                "WHERE task_id=%s FOR UPDATE",
                (task_id,),
            )
            row = await cursor.fetchone()
        if row:
            quiz_id = quiz_id or row.get("quiz_id")
            questions = row["questions_json"]
            if isinstance(questions, str):
                questions = json.loads(questions)
            changed = False
            for question in questions or []:
                if question.get("id") == question_id:
                    question["visualization"] = visualization
                    changed = True
                    break
            if changed:
                quiz_json = row.get("quiz_json")
                if isinstance(quiz_json, str):
                    quiz_json = json.loads(quiz_json)
                if isinstance(quiz_json, dict):
                    quiz_json["questions"] = questions
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE quiz_generation_tasks SET questions_json=%s, quiz_json=%s, version=version+1, updated_at=CURRENT_TIMESTAMP WHERE task_id=%s",
                        (json.dumps(questions, ensure_ascii=False), json.dumps(quiz_json, ensure_ascii=False) if quiz_json else None, task_id),
                    )
    if quiz_id:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT questions_json FROM quiz_sessions WHERE quiz_id=%s FOR UPDATE", (quiz_id,))
            row = await cursor.fetchone()
        if row:
            questions = row["questions_json"]
            if isinstance(questions, str):
                questions = json.loads(questions)
            changed = False
            for question in questions or []:
                if question.get("id") == question_id:
                    question["visualization"] = visualization
                    changed = True
                    break
            if changed:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE quiz_sessions SET questions_json=%s WHERE quiz_id=%s",
                        (json.dumps(questions, ensure_ascii=False), quiz_id),
                    )
    await connection.commit()
