from __future__ import annotations

import json
from typing import Any

import aiomysql

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_documents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  document_id VARCHAR(80) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  storage_path VARCHAR(500) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  mime_type VARCHAR(120) NOT NULL,
  file_size BIGINT UNSIGNED NOT NULL,
  status ENUM('processing','ready','failed') NOT NULL DEFAULT 'processing',
  error_message VARCHAR(500) NULL,
  chunk_count INT UNSIGNED NOT NULL DEFAULT 0,
  embedding_model VARCHAR(120) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id), UNIQUE KEY uq_knowledge_document_id (document_id),
  UNIQUE KEY uq_knowledge_user_hash (user_id, content_hash),
  KEY idx_knowledge_user_status_updated (user_id, status, updated_at),
  CONSTRAINT fk_knowledge_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


async def ensure_knowledge_table(pool: Any) -> None:
    async with pool.acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(CREATE_SQL)
        await connection.commit()


def _row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("created_at", "updated_at"):
        value = result.get(key)
        if hasattr(value, "strftime"):
            result[key] = value.strftime("%Y-%m-%d %H:%M:%S")
    return result


async def count_user_documents(connection: Any, user_id: int) -> int:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT COUNT(*) AS total FROM knowledge_documents WHERE user_id=%s", (user_id,))
        row = await cursor.fetchone()
    return int(row["total"] if row else 0)


async def find_by_hash(connection: Any, user_id: int, content_hash: str) -> dict[str, Any] | None:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM knowledge_documents WHERE user_id=%s AND content_hash=%s", (user_id, content_hash))
        row = await cursor.fetchone()
    return _row(row) if row else None


async def create_document(connection: Any, data: dict[str, Any]) -> dict[str, Any]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """INSERT INTO knowledge_documents
            (document_id,user_id,original_name,storage_path,content_hash,mime_type,file_size,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'processing')""",
            (data["document_id"], data["user_id"], data["original_name"], data["storage_path"], data["content_hash"], data["mime_type"], data["file_size"]),
        )
    await connection.commit()
    return await get_document(connection, data["user_id"], data["document_id"])


async def get_document(connection: Any, user_id: int, document_id: str) -> dict[str, Any] | None:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT * FROM knowledge_documents WHERE user_id=%s AND document_id=%s", (user_id, document_id))
        row = await cursor.fetchone()
    return _row(row) if row else None


async def list_documents(connection: Any, user_id: int, page: int, page_size: int) -> dict[str, Any]:
    offset = (page - 1) * page_size
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute("SELECT COUNT(*) AS total FROM knowledge_documents WHERE user_id=%s", (user_id,))
        total = int((await cursor.fetchone())["total"])
        await cursor.execute("SELECT * FROM knowledge_documents WHERE user_id=%s ORDER BY updated_at DESC,id DESC LIMIT %s OFFSET %s", (user_id, page_size, offset))
        rows = await cursor.fetchall()
    return {"items": [_row(row) for row in rows], "total": total, "page": page, "page_size": page_size}


async def set_ready(connection: Any, user_id: int, document_id: str, chunk_count: int, embedding_model: str | None) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("UPDATE knowledge_documents SET status='ready', error_message=NULL, chunk_count=%s, embedding_model=%s WHERE user_id=%s AND document_id=%s", (chunk_count, embedding_model, user_id, document_id))
    await connection.commit()


async def set_failed(connection: Any, user_id: int, document_id: str, reason: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("UPDATE knowledge_documents SET status='failed', error_message=%s WHERE user_id=%s AND document_id=%s", (reason[:500], user_id, document_id))
    await connection.commit()


async def reset_processing(connection: Any, user_id: int, document_id: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("UPDATE knowledge_documents SET status='processing', error_message=NULL WHERE user_id=%s AND document_id=%s AND status='failed'", (user_id, document_id))
    await connection.commit()


async def rename_document(connection: Any, user_id: int, document_id: str, original_name: str) -> dict[str, Any] | None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE knowledge_documents
            SET original_name=%s, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=%s AND document_id=%s
            """,
            (original_name, user_id, document_id),
        )
    await connection.commit()
    return await get_document(connection, user_id, document_id)


async def delete_document(connection: Any, user_id: int, document_id: str) -> dict[str, Any] | None:
    row = await get_document(connection, user_id, document_id)
    if row is None:
        return None
    async with connection.cursor() as cursor:
        await cursor.execute("DELETE FROM knowledge_documents WHERE user_id=%s AND document_id=%s", (user_id, document_id))
    await connection.commit()
    return row
