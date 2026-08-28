import asyncio
import uuid

import aiomysql

from app.core.config import get_settings
from app.core.guest import hash_guest_token
from app.repositories import generation_repository


def test_guest_task_cannot_cross_session():
    async def run() -> None:
        settings = get_settings()
        connection = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            charset="utf8mb4",
        )
        task_id = f"test_guest_{uuid.uuid4().hex}"
        owner = hash_guest_token("guest-session-owner-123456")
        other = hash_guest_token("guest-session-other-123456")
        try:
            assert await generation_repository.reserve_guest_task(connection, owner, 1, 1)
            assert await generation_repository.reserve_guest_task(connection, owner, 1, 1) is False
            await generation_repository.release_guest_task(connection, owner)
            await generation_repository.create_task(
                connection,
                task_id,
                None,
                {"user_input": "RAG", "role": "general", "difficulty": "medium", "question_count": 6},
                guest_token_hash=owner,
            )
            assert await generation_repository.get_task(connection, task_id, None, owner)
            assert await generation_repository.get_task(connection, task_id, None, other) is None
        finally:
            async with connection.cursor() as cursor:
                await cursor.execute("DELETE FROM quiz_generation_tasks WHERE task_id=%s", (task_id,))
                await cursor.execute("DELETE FROM guest_generation_usage WHERE guest_token_hash=%s", (owner,))
                await connection.commit()
            connection.close()

    asyncio.run(run())
