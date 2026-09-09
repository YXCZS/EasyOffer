from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiomysql

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS quiz_generation_tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  guest_token_hash CHAR(64) NULL,
  request_json JSON NOT NULL,
  status ENUM('queued','generating','completed','failed','expired','cancelled') NOT NULL DEFAULT 'queued',
  generated_count INT UNSIGNED NOT NULL DEFAULT 0,
  total_count INT UNSIGNED NOT NULL DEFAULT 6,
  questions_json JSON NOT NULL,
  answer_records_json JSON NOT NULL,
  current_index INT UNSIGNED NOT NULL DEFAULT 0,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  progress_version INT UNSIGNED NOT NULL DEFAULT 1,
  title VARCHAR(255) NOT NULL DEFAULT '',
  summary TEXT NOT NULL,
  quiz_id VARCHAR(80) NULL,
  quiz_json JSON NULL,
  error_message VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_quiz_generation_task_id (task_id),
  UNIQUE KEY uq_quiz_generation_quiz_id (quiz_id),
  KEY idx_quiz_generation_user_status (user_id, status, updated_at),
  KEY idx_quiz_generation_guest_status (guest_token_hash, status, updated_at),
  KEY idx_quiz_generation_expiry (status, expires_at),
  CONSTRAINT fk_quiz_generation_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

GUEST_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS guest_generation_usage (
  guest_token_hash CHAR(64) NOT NULL,
  usage_date DATE NOT NULL,
  total_count INT UNSIGNED NOT NULL DEFAULT 0,
  active_count INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (guest_token_hash, usage_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


async def ensure_generation_table(pool: Any) -> None:
    async with pool.acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(CREATE_SQL)
            await cursor.execute(GUEST_USAGE_SQL)
            try:
                await cursor.execute("ALTER TABLE quiz_generation_tasks ADD COLUMN guest_token_hash CHAR(64) NULL")
            except Exception as exc:
                if "duplicate" not in str(exc).lower():
                    raise
            try:
                await cursor.execute("ALTER TABLE quiz_generation_tasks ADD KEY idx_quiz_generation_guest_status (guest_token_hash, status, updated_at)")
            except Exception as exc:
                if "duplicate" not in str(exc).lower():
                    raise
            try:
                await cursor.execute(
                    "ALTER TABLE quiz_generation_tasks MODIFY COLUMN status "
                    "ENUM('queued','generating','completed','failed','expired','cancelled') "
                    "NOT NULL DEFAULT 'queued'"
                )
            except Exception as exc:
                if "duplicate" not in str(exc).lower() and "same" not in str(exc).lower():
                    raise
        await connection.commit()


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _format_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["request"] = _json_load(result.pop("request_json", None), {})
    result["questions"] = _json_load(result.pop("questions_json", None), [])
    result["answer_records"] = _json_load(result.pop("answer_records_json", None), [])
    result["quiz"] = _json_load(result.pop("quiz_json", None), None)
    for key in ("created_at", "updated_at", "expires_at"):
        value = result.get(key)
        if hasattr(value, "strftime"):
            result[key] = value.strftime("%Y-%m-%d %H:%M:%S")
    return result


def _owner_clause(user_id: int | None, guest_token_hash: str | None) -> tuple[str, tuple[Any, ...]]:
    if user_id is not None:
        return "user_id=%s", (user_id,)
    if guest_token_hash:
        return "user_id IS NULL AND guest_token_hash=%s", (guest_token_hash,)
    return "user_id IS NULL AND guest_token_hash IS NULL", ()


async def get_task(connection: Any, task_id: str, user_id: int | None = None, guest_token_hash: str | None = None) -> dict[str, Any] | None:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            f"SELECT * FROM quiz_generation_tasks WHERE task_id=%s AND {owner_sql}",
            (task_id, *owner_args),
        )
        row = await cursor.fetchone()
    # The application pool uses autocommit=False. Commit the read transaction
    # so a later poll does not reuse a repeatable-read snapshot.
    await connection.commit()
    return _format_row(row)


async def create_task(
    connection: Any,
    task_id: str,
    user_id: int | None,
    request: dict[str, Any],
    total_count: int = 6,
    ttl_minutes: int = 30,
    guest_token_hash: str | None = None,
) -> dict[str, Any]:
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).replace(tzinfo=None)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """INSERT INTO quiz_generation_tasks
            (task_id,user_id,guest_token_hash,request_json,total_count,questions_json,answer_records_json,summary,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                task_id,
                user_id,
                guest_token_hash,
                json.dumps(request, ensure_ascii=False),
                total_count,
                "[]",
                "[]",
                "",
                expires_at,
            ),
        )
    await connection.commit()
    task = await get_task(connection, task_id, user_id, guest_token_hash)
    if task is None:
        raise RuntimeError("生成任务创建后未找到")
    return task


async def claim_task(connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> bool:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor() as cursor:
        await cursor.execute(
            f"UPDATE quiz_generation_tasks SET status='generating', updated_at=CURRENT_TIMESTAMP WHERE task_id=%s AND {owner_sql} AND status='queued'",
            (task_id, *owner_args),
        )
        changed = cursor.rowcount
    await connection.commit()
    return changed == 1


async def append_question(
    connection: Any,
    task_id: str,
    user_id: int | None,
    question: dict[str, Any],
    expected_version: int,
    guest_token_hash: str | None = None,
) -> dict[str, Any] | None:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            f"SELECT questions_json, generated_count, version, status FROM quiz_generation_tasks WHERE task_id=%s AND {owner_sql} FOR UPDATE",
            (task_id, *owner_args),
        )
        row = await cursor.fetchone()
        if not row or row["version"] != expected_version or row["status"] not in ("generating", "queued"):
            await connection.rollback()
            return None
        questions = _json_load(row["questions_json"], [])
        questions.append(question)
        await cursor.execute(
            "UPDATE quiz_generation_tasks SET questions_json=%s, generated_count=%s, version=version+1, status='generating', updated_at=CURRENT_TIMESTAMP WHERE task_id=%s",
            (json.dumps(questions, ensure_ascii=False), len(questions), task_id),
        )
    await connection.commit()
    return await get_task(connection, task_id, user_id, guest_token_hash)


async def save_progress(
    connection: Any,
    task_id: str,
    user_id: int | None,
    current_index: int,
    answer_records: list[dict[str, Any]],
    expected_version: int,
    guest_token_hash: str | None = None,
) -> dict[str, Any] | None:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """UPDATE quiz_generation_tasks SET current_index=%s, answer_records_json=%s,
            progress_version=progress_version+1, updated_at=CURRENT_TIMESTAMP
            WHERE task_id=%s AND """ + owner_sql + """
            AND progress_version=%s AND status IN ('queued','generating','failed','completed')""",
            (current_index, json.dumps(answer_records, ensure_ascii=False), task_id, *owner_args, expected_version),
        )
        changed = cursor.rowcount
    if changed != 1:
        await connection.rollback()
        return None
    await connection.commit()
    return await get_task(connection, task_id, user_id, guest_token_hash)


async def mark_completed(
    connection: Any,
    task_id: str,
    user_id: int | None,
    quiz_id: str,
    quiz: dict[str, Any],
    title: str,
    summary: str,
    guest_token_hash: str | None = None,
) -> dict[str, Any] | None:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """UPDATE quiz_generation_tasks SET status='completed', quiz_id=%s, quiz_json=%s,
            title=%s, summary=%s, generated_count=total_count, version=version+1,
            updated_at=CURRENT_TIMESTAMP WHERE task_id=%s AND """ + owner_sql + """
            AND status IN ('generating','completed')""",
            (quiz_id, json.dumps(quiz, ensure_ascii=False), title, summary, task_id, *owner_args),
        )
    await connection.commit()
    return await get_task(connection, task_id, user_id, guest_token_hash)


async def mark_failed(connection: Any, task_id: str, user_id: int | None, message: str, guest_token_hash: str | None = None) -> dict[str, Any] | None:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_generation_tasks SET status='failed', error_message=%s, updated_at=CURRENT_TIMESTAMP WHERE task_id=%s AND " + owner_sql + " AND status NOT IN ('completed','expired')",
            (message[:500], task_id, *owner_args),
        )
    await connection.commit()
    return await get_task(connection, task_id, user_id, guest_token_hash)


async def retry_task(connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> dict[str, Any] | None:
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_generation_tasks SET status='queued', error_message=NULL, updated_at=CURRENT_TIMESTAMP WHERE task_id=%s AND " + owner_sql + " AND status='failed'",
            (task_id, *owner_args),
        )
        changed = cursor.rowcount
    await connection.commit()
    return await get_task(connection, task_id, user_id, guest_token_hash) if changed else None


async def cancel_task(connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> dict[str, Any] | None:
    """Stop a queued/running generation task without deleting its snapshot."""
    owner_sql, owner_args = _owner_clause(user_id, guest_token_hash)
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_generation_tasks SET status='cancelled', error_message=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE task_id=%s AND " + owner_sql +
            " AND status IN ('queued','generating')",
            (task_id, *owner_args),
        )
        changed = cursor.rowcount
    await connection.commit()
    return await get_task(connection, task_id, user_id, guest_token_hash) if changed else None


async def guest_usage(connection: Any, guest_token_hash: str) -> tuple[int, int]:
    """Return (active_tasks, tasks_created_today) for one anonymous session."""
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT "
            "SUM(status IN ('queued','generating')), "
            "SUM(created_at >= UTC_DATE()) "
            "FROM quiz_generation_tasks WHERE user_id IS NULL AND guest_token_hash=%s",
            (guest_token_hash,),
        )
        row = await cursor.fetchone()
    await connection.commit()
    active = int((row[0] if row and row[0] is not None else 0))
    daily = int((row[1] if row and row[1] is not None else 0))
    return active, daily


async def reserve_guest_task(connection: Any, guest_token_hash: str, max_active: int, daily_limit: int) -> bool:
    """Atomically reserve one anonymous task slot in MySQL."""
    async with connection.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO guest_generation_usage (guest_token_hash, usage_date, total_count, active_count) "
            "VALUES (%s, UTC_DATE(), 0, 0) ON DUPLICATE KEY UPDATE updated_at=updated_at",
            (guest_token_hash,),
        )
        await cursor.execute(
            "SELECT total_count, active_count FROM guest_generation_usage "
            "WHERE guest_token_hash=%s AND usage_date=UTC_DATE() FOR UPDATE",
            (guest_token_hash,),
        )
        row = await cursor.fetchone()
        total = int(row[0] if row else 0)
        active = int(row[1] if row else 0)
        if total >= daily_limit or active >= max_active:
            await connection.rollback()
            return False
        await cursor.execute(
            "UPDATE guest_generation_usage SET total_count=total_count+1, active_count=active_count+1 "
            "WHERE guest_token_hash=%s AND usage_date=UTC_DATE()",
            (guest_token_hash,),
        )
    await connection.commit()
    return True


async def release_guest_task(connection: Any, guest_token_hash: str | None) -> None:
    if not guest_token_hash:
        return
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE guest_generation_usage SET active_count=IF(active_count>0, active_count-1, 0) "
            "WHERE guest_token_hash=%s AND usage_date=UTC_DATE()",
            (guest_token_hash,),
        )
    await connection.commit()


async def expire_tasks(connection: Any) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_generation_tasks SET status='expired', error_message='生成任务已过期' WHERE status IN ('queued','generating','failed') AND expires_at < CURRENT_TIMESTAMP"
        )
        changed = cursor.rowcount
    await connection.commit()
    return int(changed)


async def recover_interrupted_tasks(connection: Any) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE quiz_generation_tasks SET status='failed', error_message='服务重启导致任务中断，可重试' WHERE status='generating'"
        )
        changed = cursor.rowcount
        await cursor.execute("UPDATE guest_generation_usage SET active_count=0 WHERE usage_date=UTC_DATE()")
    await connection.commit()
    return int(changed)
