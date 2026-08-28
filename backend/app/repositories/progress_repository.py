import json
from typing import Any

import aiomysql

from app.models.progress import ProgressSaveRequest
from app.models.quiz import Quiz


def _json_load(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value or "[]")


def _format_row(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["answer_records"] = _json_load(row.pop("answer_records_json"))
    updated_at = row.get("updated_at")
    if hasattr(updated_at, "strftime"):
        row["updated_at"] = updated_at.strftime("%Y-%m-%d %H:%M:%S")
    return row


async def create_progress(connection: Any, user_id: int, quiz: Quiz) -> dict[str, Any]:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            """
            INSERT IGNORE INTO quiz_progress
              (quiz_id, user_id, role, difficulty, status, current_index,
               answer_records_json, answered_count, total_questions, version)
            VALUES (%s, %s, %s, %s, 'in_progress', 0, %s, 0, %s, 1)
            """,
            (
                quiz.quiz_id,
                user_id,
                quiz.role,
                quiz.difficulty,
                json.dumps([], ensure_ascii=False),
                len(quiz.questions),
            ),
        )
    await connection.commit()
    row = await get_progress(connection, user_id, quiz.quiz_id)
    if row is None:
        raise RuntimeError("练习进度创建后未找到")
    return row


async def get_progress(connection: Any, user_id: int, quiz_id: str) -> dict[str, Any] | None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT qp.quiz_id, qp.user_id, qp.role, qp.difficulty, qp.status,
                   qp.current_index, qp.answer_records_json, qp.answered_count,
                   qp.total_questions, qp.version, qp.last_error, qp.updated_at,
                   qs.title, qs.summary, qs.user_input, qs.questions_json
            FROM quiz_progress qp
            INNER JOIN quiz_sessions qs ON qs.quiz_id = qp.quiz_id
            WHERE qp.quiz_id = %s AND qp.user_id = %s
            """,
            (quiz_id, user_id),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    if not isinstance(row, dict):
        columns = [
            "quiz_id", "user_id", "role", "difficulty", "status", "current_index",
            "answer_records_json", "answered_count", "total_questions", "version",
            "last_error", "updated_at", "title", "summary", "user_input", "questions_json",
        ]
        row = dict(zip(columns, row))
    return _format_row(row)


async def list_incomplete(connection: Any, user_id: int) -> list[dict[str, Any]]:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            """
            SELECT qp.quiz_id, qs.title, qs.user_input AS topic, qp.role, qp.difficulty,
                   qp.status, qp.answered_count, qp.total_questions, qp.current_index,
                   DATE_FORMAT(qp.updated_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS updated_at
            FROM quiz_progress qp
            INNER JOIN quiz_sessions qs ON qs.quiz_id = qp.quiz_id
            WHERE qp.user_id = %s AND qp.status IN ('in_progress', 'ready_for_report')
            ORDER BY qp.updated_at DESC, qp.id DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def update_progress(
    connection: Any,
    user_id: int,
    quiz_id: str,
    request: ProgressSaveRequest,
    status: str,
    answered_count: int,
) -> dict[str, Any] | None:
    records_json = json.dumps([record.model_dump() for record in request.answer_records], ensure_ascii=False)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE quiz_progress
            SET current_index = %s,
                answer_records_json = %s,
                answered_count = %s,
                status = %s,
                version = version + 1,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE quiz_id = %s AND user_id = %s AND version = %s
              AND status IN ('in_progress', 'ready_for_report')
            """,
            (
                request.current_index,
                records_json,
                answered_count,
                status,
                quiz_id,
                user_id,
                request.version,
            ),
        )
        changed = cursor.rowcount
    if changed != 1:
        await connection.rollback()
        return None
    await connection.commit()
    return await get_progress(connection, user_id, quiz_id)


async def abandon_progress(connection: Any, user_id: int, quiz_id: str) -> bool:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE quiz_progress
            SET status = 'abandoned', abandoned_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP, version = version + 1
            WHERE quiz_id = %s AND user_id = %s
              AND status IN ('in_progress', 'ready_for_report')
            """,
            (quiz_id, user_id),
        )
        changed = cursor.rowcount
    await connection.commit()
    return changed == 1


async def mark_completed(connection: Any, user_id: int, quiz_id: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE quiz_progress
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP,
                last_error = NULL, updated_at = CURRENT_TIMESTAMP,
                version = version + 1
            WHERE quiz_id = %s AND user_id = %s
            """,
            (quiz_id, user_id),
        )
