import json
from typing import Any

import aiomysql

from app.models.report import AnswerRecord, Report
from app.models.quiz import Quiz
from app.repositories.progress_repository import mark_completed


async def find_or_create_user(connection: Any, openid: str) -> dict[str, Any]:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            """
            INSERT INTO users (openid) VALUES (%s)
            ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id), updated_at = CURRENT_TIMESTAMP
            """,
            (openid,),
        )
        await connection.commit()
        await cursor.execute(
            "SELECT id, nickname, avatar_url, total_xp FROM users WHERE openid = %s",
            (openid,),
        )
        user = await cursor.fetchone()
    if user is None:
        raise RuntimeError("用户创建后未找到")
    return dict(user)


async def get_user_profile(connection: Any, user_id: int) -> dict[str, Any] | None:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            """
            SELECT u.id, u.nickname, u.avatar_url, u.total_xp,
                   COUNT(DISTINCT qs.quiz_id) AS quiz_count,
                   COALESCE(SUM(ar.correct_count), 0) AS correct_count,
                   COALESCE(AVG(ar.accuracy), 0) AS average_accuracy
            FROM users u
            LEFT JOIN quiz_sessions qs ON qs.user_id = u.id
            LEFT JOIN answer_records ar ON ar.quiz_id = qs.quiz_id AND ar.user_id = u.id
            WHERE u.id = %s
            GROUP BY u.id, u.nickname, u.avatar_url, u.total_xp
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def update_user_profile(connection: Any, user_id: int, nickname: str | None, avatar_url: str | None) -> None:
    updates: list[str] = []
    values: list[str | int] = []
    if nickname is not None:
        updates.append("nickname = %s")
        values.append(nickname)
    if avatar_url is not None:
        updates.append("avatar_url = %s")
        values.append(avatar_url)
    if not updates:
        return
    values.append(user_id)
    async with connection.cursor() as cursor:
        await cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", values)
    await connection.commit()


async def list_quizzes(connection: Any, user_id: int, page: int, page_size: int) -> dict[str, Any]:
    offset = (page - 1) * page_size
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM quiz_sessions qs
            WHERE qs.user_id = %s
              AND EXISTS (SELECT 1 FROM reports r WHERE r.quiz_id = qs.quiz_id AND r.user_id = qs.user_id)
            """,
            (user_id,),
        )
        total_row = await cursor.fetchone()
        await cursor.execute(
            """
            SELECT qs.quiz_id, qs.title,
                   COALESCE(ar.accuracy, 0) AS accuracy,
                   JSON_LENGTH(qs.questions_json) AS question_count,
                   DATE_FORMAT(qs.created_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS created_at
            FROM quiz_sessions qs
            LEFT JOIN answer_records ar ON ar.quiz_id = qs.quiz_id AND ar.user_id = qs.user_id
            WHERE qs.user_id = %s
              AND EXISTS (SELECT 1 FROM reports r WHERE r.quiz_id = qs.quiz_id AND r.user_id = qs.user_id)
            ORDER BY qs.created_at DESC, qs.id DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, page_size, offset),
        )
        rows = await cursor.fetchall()
    return {"items": [dict(row) for row in rows], "total": int(total_row["total"]), "page": page, "page_size": page_size}


async def get_quiz_detail(connection: Any, user_id: int, quiz_id: str) -> dict[str, Any] | None:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            "SELECT quiz_id, title, summary, user_input, questions_json, created_at FROM quiz_sessions WHERE quiz_id = %s AND user_id = %s",
            (quiz_id, user_id),
        )
        quiz = await cursor.fetchone()
        if quiz is None:
            return None
        await cursor.execute(
            "SELECT records_json FROM answer_records WHERE quiz_id = %s AND user_id = %s",
            (quiz_id, user_id),
        )
        answers = await cursor.fetchone()
        await cursor.execute(
            "SELECT report_json FROM reports WHERE quiz_id = %s AND user_id = %s",
            (quiz_id, user_id),
        )
        report = await cursor.fetchone()
    return {
        "quiz": {
            "quiz_id": quiz["quiz_id"],
            "title": quiz["title"],
            "summary": quiz["summary"],
            "topic": quiz["user_input"],
            "questions": json.loads(quiz["questions_json"]),
            "created_at": quiz["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
        },
        "answer_records": json.loads(answers["records_json"]) if answers else [],
        "report": json.loads(report["report_json"]) if report else None,
    }


async def save_quiz(connection: Any, user_id: int, user_input: str, quiz: Quiz) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            INSERT INTO quiz_sessions (quiz_id, user_id, title, summary, user_input, questions_json)
            VALUES (%s, %s, %s, %s, %s, %s) AS new
            ON DUPLICATE KEY UPDATE title = new.title, summary = new.summary, user_input = new.user_input, questions_json = new.questions_json
            """,
            (quiz.quiz_id, user_id, quiz.title, quiz.summary, user_input, json.dumps([q.model_dump() for q in quiz.questions], ensure_ascii=False)),
        )
    await connection.commit()


async def save_report(connection: Any, user_id: int, request: Any, report: Report) -> None:
    records_json = json.dumps([record.model_dump() for record in request.answer_records], ensure_ascii=False)
    report_json = json.dumps(report.model_dump(), ensure_ascii=False)
    xp = 10 + report.score * 2
    await connection.begin()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id FROM reports WHERE quiz_id = %s AND user_id = %s FOR UPDATE",
                (report.quiz_id, user_id),
            )
            existing = await cursor.fetchone()
            await cursor.execute(
                """
                INSERT INTO answer_records (quiz_id, user_id, records_json, total_questions, correct_count, accuracy)
                VALUES (%s, %s, %s, %s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE records_json = new.records_json, total_questions = new.total_questions, correct_count = new.correct_count, accuracy = new.accuracy
                """,
                (report.quiz_id, user_id, records_json, report.total, report.score, report.accuracy),
            )
            await cursor.execute(
                """
                INSERT INTO reports (quiz_id, user_id, report_json)
                VALUES (%s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE report_json = new.report_json
                """,
                (report.quiz_id, user_id, report_json),
            )
            await mark_completed(connection, user_id, report.quiz_id)
            if existing is None:
                await cursor.execute("UPDATE users SET total_xp = total_xp + %s WHERE id = %s", (xp, user_id))
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
