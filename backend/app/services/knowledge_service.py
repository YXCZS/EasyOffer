from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import secrets
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.repositories import knowledge_repository

logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".md": "text/markdown", ".markdown": "text/markdown"}


class KnowledgeValidationError(ValueError):
    pass


PUBLIC_REQUIRED_METADATA = (
    "chunk_id", "document_id", "document_version", "corpus_version", "parent_id",
    "technology", "role_tags", "knowledge_type", "document_hash", "parent_hash",
    "content_hash", "license_status",
    "review_status", "status",
)


def validate_public_chunk_metadata(item: dict[str, Any]) -> None:
    """Validate governance metadata before any public embedding is requested."""
    missing = [name for name in PUBLIC_REQUIRED_METADATA if not item.get(name)]
    if missing:
        raise ValueError("public chunk metadata incomplete: " + ", ".join(missing))
    status = item.get("status")
    if status not in {"unpublished", "published", "inactive", "withdrawn"}:
        raise ValueError("public chunk status is invalid")
    license_status = item.get("license_status")
    if license_status == "approved":
        return
    # Unlicensed material may be embedded only in an isolated candidate for
    # local evaluation. It remains blocked by the approval/publish gate and
    # cannot pass the public retrieval filter.
    if license_status == "local-evaluation-only" and status == "unpublished":
        return
    if license_status == "local-evaluation-only":
        raise ValueError("local-evaluation-only public chunk cannot be published")
    raise ValueError("public chunk license is not approved")


class SecureDocumentStorage:
    def __init__(self, root: str | None = None):
        self.root = Path(root or get_settings().knowledge_upload_dir).resolve()

    def save(self, user_id: int, original_name: str, content: bytes) -> str:
        safe_name = Path(original_name).name
        target_dir = (self.root / str(user_id)).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = (target_dir / f"{secrets.token_hex(16)}{Path(safe_name).suffix.lower()}").resolve()
        if target.parent != target_dir or self.root not in target.parents:
            raise KnowledgeValidationError("非法文件路径")
        target.write_bytes(content)
        return str(target)

    def remove(self, path: str) -> None:
        target = Path(path).resolve()
        if self.root not in target.parents:
            raise KnowledgeValidationError("非法文件路径")
        target.unlink(missing_ok=True)


def validate_upload(filename: str | None, content_type: str | None, content: bytes) -> tuple[str, str]:
    name = Path(filename or "").name
    extension = Path(name).suffix.lower()
    mime = ALLOWED_EXTENSIONS.get(extension)
    if mime is None or (content_type and content_type not in {mime, "application/octet-stream"}):
        raise KnowledgeValidationError("仅支持 PDF、Word（DOCX）或 Markdown 文件")
    if not content:
        raise KnowledgeValidationError("文件不能为空")
    if len(content) > get_settings().knowledge_max_file_bytes:
        raise KnowledgeValidationError("文件超过大小限制")
    return name, mime


def parse_document(path: str, mime_type: str) -> str:
    extension = Path(path).suffix.lower()
    if extension == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        docs = PyPDFLoader(path).load()
    elif extension == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        docs = Docx2txtLoader(path).load()
    else:
        from langchain_core.documents import Document
        docs = [Document(page_content=Path(path).read_text(encoding="utf-8", errors="ignore"))]
    text = "\n\n".join(doc.page_content for doc in docs)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise KnowledgeValidationError("文档没有可用正文")
    return text


def split_text(text: str) -> list[dict[str, Any]]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(chunk_size=settings.knowledge_chunk_size, chunk_overlap=settings.knowledge_chunk_overlap)
    chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
    if len(chunks) > settings.knowledge_max_chunks:
        raise KnowledgeValidationError("文档分块数量超过限制")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return [{"text": chunk, "chunk_index": index, "chunk_id": hashlib.sha256(f"{digest}:{index}:{chunk}".encode()).hexdigest(), "content_hash": digest} for index, chunk in enumerate(chunks)]


def document_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def process_document(connection: Any, user_id: int, document_id: str, storage: SecureDocumentStorage | None = None) -> None:
    storage = storage or SecureDocumentStorage()
    row = await knowledge_repository.get_document(connection, user_id, document_id)
    if not row:
        return
    try:
        text = parse_document(row["storage_path"], row["mime_type"])
        chunks = split_text(text)
        get_vector_store(user_id).upsert_document(document_id, row["original_name"], chunks)
        await knowledge_repository.set_ready(connection, user_id, document_id, len(chunks), get_settings().embedding_model)
    except Exception as exc:
        logger.warning("knowledge_processing_failed document_id=%s user_id=%s failure_type=%s", document_id, user_id, type(exc).__name__)
        await knowledge_repository.set_failed(connection, user_id, document_id, str(exc))


class EmbeddingProvider:
    def __init__(self):
        self._embeddings = None

    def _get(self):
        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings
            settings = get_settings()
            key = settings.embedding_api_key or settings.dashscope_api_key or settings.deepseek_api_key
            if not key:
                raise RuntimeError("EMBEDDING_API_KEY 或 DEEPSEEK_API_KEY 未配置")
            # DashScope's OpenAI-compatible endpoint expects string inputs; disabling
            # LangChain's token pre-processing avoids sending token-id arrays.
            # DashScope text-embedding-v4 accepts at most 10 input texts per request.
            # Keep the setting configurable, but never allow an invalid batch size.
            kwargs = {
                "model": settings.embedding_model,
                "base_url": settings.embedding_base_url,
                "api_key": key,
                "check_embedding_ctx_length": False,
                "chunk_size": min(max(settings.embedding_batch_size, 1), 10),
            }
            if settings.embedding_dimensions:
                kwargs["dimensions"] = settings.embedding_dimensions
            self._embeddings = OpenAIEmbeddings(**kwargs)
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._get().embed_query(text)


class ChromaVectorStore:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._store = None

    def _get(self):
        if self._store is None:
            from langchain_chroma import Chroma
            settings = get_settings()
            self._store = Chroma(collection_name=f"easyoffer_user_{self.user_id}", embedding_function=EmbeddingProvider(), persist_directory=settings.chroma_persist_dir)
        return self._store

    def upsert_document(self, document_id: str, source_name: str, chunks: list[dict[str, Any]]) -> None:
        store = self._get()
        try:
            store.delete(where={"document_id": document_id})
        except Exception:
            pass
        from langchain_core.documents import Document
        docs = [Document(page_content=item["text"], metadata={"document_id": document_id, "chunk_index": item["chunk_index"], "source_name": source_name, "content_hash": item["content_hash"]}) for item in chunks]
        store.add_documents(docs, ids=[item["chunk_id"] for item in chunks])

    def delete_document(self, document_id: str) -> None:
        self._get().delete(where={"document_id": document_id})

    def search(self, query: str, k: int, document_id: str | None = None) -> list[Any]:
        kwargs: dict[str, Any] = {"k": k}
        if document_id:
            kwargs["filter"] = {"document_id": document_id}
        rows = self._get().similarity_search_with_relevance_scores(query, **kwargs)
        if not document_id:
            return rows
        return [
            (doc, score)
            for doc, score in rows
            if str((getattr(doc, "metadata", None) or {}).get("document_id", "")) == document_id
        ]

    def get_document_chunks(self, document_id: str, limit: int | None = None) -> list[Any]:
        """Return the selected document's chunks in source order.

        A document-only quiz must not use the display filename as an embedding
        query. Chroma's collection ``get`` is an exact metadata lookup, so it
        gives us deterministic, document-scoped grounding instead of the
        top-k chunks that happen to be nearest to a filename.
        """
        from langchain_core.documents import Document

        collection = getattr(self._get(), "_collection", None)
        if collection is None:
            raise RuntimeError("Chroma collection is unavailable")
        kwargs: dict[str, Any] = {
            "where": {"document_id": document_id},
            "include": ["documents", "metadatas"],
        }
        if limit is not None:
            kwargs["limit"] = max(1, limit)
        payload = collection.get(**kwargs) or {}
        documents = payload.get("documents") or []
        metadatas = payload.get("metadatas") or []
        chunks: list[Document] = []
        for index, text in enumerate(documents):
            if not text:
                continue
            metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
            if str(metadata.get("document_id", "")) != document_id:
                continue
            chunks.append(Document(page_content=str(text), metadata=metadata))
        chunks.sort(key=lambda item: int((item.metadata or {}).get("chunk_index", 0)))
        return chunks


class MilvusVectorStore:
    """Milvus-backed store shared by private user and public corpora.

    The adapter is intentionally lazy: importing the application or running
    tests does not require a reachable Milvus server.  Metadata filters are
    applied in Milvus first and verified again locally for defense in depth.
    """

    def __init__(self, user_id: int | None = None, *, public: bool = False):
        self.user_id = user_id
        self.public = public
        self._store = None

    @property
    def collection_name(self) -> str:
        settings = get_settings()
        return settings.milvus_public_collection if self.public else settings.milvus_private_collection

    def _get(self):
        if self._store is None:
            from langchain_milvus import Milvus
            from pymilvus import connections

            settings = get_settings()
            connection_args: dict[str, Any] = {"uri": settings.milvus_uri}
            if settings.milvus_token:
                connection_args["token"] = settings.milvus_token
            kwargs: dict[str, Any] = {
                "embedding_function": EmbeddingProvider(),
                "collection_name": self.collection_name,
                "connection_args": connection_args,
                "consistency_level": settings.milvus_consistency_level,
                "index_params": {
                    "index_type": "AUTOINDEX",
                    "metric_type": settings.milvus_metric_type,
                },
                "search_params": {
                    "metric_type": settings.milvus_metric_type,
                    "params": {},
                },
                "auto_id": False,
                "enable_dynamic_field": True,
            }
            if settings.milvus_vector_dimension:
                # langchain-milvus expects the vector schema as a field
                # configuration (the embedding field type is inferred).
                kwargs["vector_schema"] = {"dim": settings.milvus_vector_dimension}

            class CompatibleMilvus(Milvus):
                def _init(self, *args: Any, **init_kwargs: Any) -> None:
                    # langchain-milvus still inspects collections through the
                    # legacy ORM API after creating a MilvusClient. Register
                    # that client's alias so PyMilvus can resolve it.
                    if not connections.has_connection(self.alias):
                        connections.connect(alias=self.alias, **self._connection_args)
                    super()._init(*args, **init_kwargs)

            self._store = CompatibleMilvus(**kwargs)
        return self._store

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _scope_expr(
        self,
        *,
        document_id: str | None = None,
        role: str | None = None,
        published_only: bool = False,
        corpus_version: str | None = None,
        status: str | None = None,
    ) -> str:
        clauses: list[str] = []
        if self.public:
            effective_status = "published" if published_only else status
            if effective_status:
                clauses.append(f"status == '{self._escape(effective_status)}'")
            if corpus_version:
                clauses.append(f"corpus_version == '{self._escape(corpus_version)}'")
            if role:
                # role_tags is stored as a delimiter-wrapped string, allowing
                # one chunk to belong to several interview roles.
                escaped = self._escape(role)
                clauses.append(f"role_tags like '%|{escaped}|%'")
        elif self.user_id is not None:
            clauses.append(f"owner_id == {int(self.user_id)}")
        if document_id:
            clauses.append(f"document_id == '{self._escape(document_id)}'")
        return " and ".join(clauses)

    @staticmethod
    def _metadata(doc: Any) -> dict[str, Any]:
        return dict(getattr(doc, "metadata", None) or {})

    def _post_filter(
        self,
        rows: list[Any],
        *,
        document_id: str | None = None,
        role: str | None = None,
        published_only: bool = False,
        corpus_version: str | None = None,
        status: str | None = None,
    ) -> list[Any]:
        filtered = []
        for row in rows:
            doc = row[0] if isinstance(row, tuple) else row
            metadata = self._metadata(doc)
            if not self.public and self.user_id is not None and str(metadata.get("owner_id")) != str(self.user_id):
                continue
            if document_id and str(metadata.get("document_id", "")) != document_id:
                continue
            effective_status = "published" if published_only else status
            if effective_status and str(metadata.get("status", "")) != effective_status:
                continue
            if corpus_version and str(metadata.get("corpus_version", "")) != corpus_version:
                continue
            if role:
                tags = metadata.get("role_tags") or ""
                if isinstance(tags, list):
                    matches = role in tags or "general" in tags
                else:
                    matches = f"|{role}|" in f"|{tags}|" or "|general|" in f"|{tags}|"
                if not matches:
                    continue
            filtered.append(row)
        return filtered

    def upsert_document(self, document_id: str, source_name: str, chunks: list[dict[str, Any]]) -> None:
        store = self._get()
        expr = self._scope_expr(document_id=document_id)
        if expr:
            try:
                store.delete(expr=expr)
            except Exception:
                logger.debug("milvus_delete_before_upsert_failed", exc_info=True)
        from langchain_core.documents import Document

        docs = []
        ids = []
        for item in chunks:
            metadata = {
                "document_id": document_id,
                "source_name": source_name,
                "chunk_index": int(item["chunk_index"]),
                "content_hash": item["content_hash"],
                "owner_id": int(self.user_id) if self.user_id is not None else 0,
                "status": "ready",
            }
            docs.append(Document(page_content=item["text"], metadata=metadata))
            ids.append(item["chunk_id"])
        if docs:
            store.add_documents(docs, ids=ids)

    def upsert_public_chunks(self, chunks: list[dict[str, Any]], *, replace_document_id: str | None = None) -> None:
        if not self.public:
            raise ValueError("public chunks require the public Milvus store")
        store = self._get()
        if replace_document_id:
            expr = self._scope_expr(document_id=replace_document_id)
            if expr:
                try:
                    store.delete(expr=expr)
                except Exception:
                    logger.debug("milvus_public_delete_before_upsert_failed", exc_info=True)
        from langchain_core.documents import Document

        docs = []
        ids = []
        for item in chunks:
            validate_public_chunk_metadata(item)
            roles = item.get("role_tags") or item.get("roles") or ["general"]
            if isinstance(roles, str):
                roles = [roles]
            role_tags = "|" + "|".join(sorted({str(role) for role in roles if role})) + "|"
            metadata = {
                "document_id": str(item.get("document_id") or item.get("source_id") or item["chunk_id"]),
                "source_id": str(item.get("source_id") or item.get("document_id") or "public"),
                "source_name": str(item.get("source_name") or item.get("title") or ""),
                "source_url": str(item.get("source_url") or item.get("url") or ""),
                "reference_urls": json.dumps(item.get("reference_urls") or [], ensure_ascii=False),
                "technology": str(item.get("technology") or ""),
                "role_tags": role_tags,
                "version": str(item.get("version") or ""),
                "document_version": str(item.get("document_version") or item.get("version") or ""),
                "corpus_version": str(item.get("corpus_version") or ""),
                "language": str(item.get("language") or "zh-CN"),
                "status": str(item.get("status") or "unpublished"),
                "review_status": str(item.get("review_status") or "pending"),
                "parent_id": str(item.get("parent_id") or ""),
                "parent_type": str(item.get("parent_type") or item.get("knowledge_type") or ""),
                "knowledge_type": str(item.get("knowledge_type") or item.get("parent_type") or ""),
                "section_path": " > ".join(item.get("section_path") or []) if isinstance(item.get("section_path"), list) else str(item.get("section_path") or ""),
                "start_index": int(item.get("start_index", 0)),
                "page_start": int(item["page_start"]) if item.get("page_start") is not None else -1,
                "page_end": int(item["page_end"]) if item.get("page_end") is not None else -1,
                "license_status": str(item.get("license_status") or ""),
                "authority_priority": int(item.get("authority_priority", 100)),
                "published_at": str(item.get("published_at") or ""),
                "structure_confidence": float(item.get("structure_confidence") or 0.0),
                "evidence_text": str(item.get("text") or ""),
                "chunk_index": int(item.get("chunk_index", 0)),
                "child_index": int(item.get("child_index", item.get("chunk_index", 0))),
                "content_hash": str(item.get("content_hash") or ""),
                "document_hash": str(item.get("document_hash") or ""),
                "parent_hash": str(item.get("parent_hash") or ""),
                "owner_id": 0,
            }
            # LangChain Milvus embeds ``page_content``. Keep the enriched
            # retrieval representation there and preserve the unmodified
            # evidence separately for Agentic RAG and parent recovery.
            docs.append(
                Document(
                    page_content=str(item.get("embedding_text") or item["text"]),
                    metadata=metadata,
                )
            )
            ids.append(str(item["chunk_id"]))
        if docs:
            store.upsert(documents=docs, ids=ids)

    def delete_document(self, document_id: str) -> None:
        expr = self._scope_expr(document_id=document_id)
        if expr:
            self._get().delete(expr=expr)

    def search(
        self,
        query: str,
        k: int,
        document_id: str | None = None,
        *,
        role: str | None = None,
        published_only: bool = False,
        corpus_version: str | None = None,
        status: str | None = None,
    ) -> list[Any]:
        # Document-scoped reads are used to build a complete personal quiz;
        # do not silently truncate them to the normal nearest-neighbour top-k.
        configured_limit = get_settings().milvus_retrieval_top_k
        limit = max(1, int(k)) if document_id else min(max(int(k), 1), configured_limit)
        kwargs: dict[str, Any] = {"k": limit}
        expr = self._scope_expr(
            document_id=document_id,
            role=role,
            published_only=published_only,
            corpus_version=corpus_version,
            status=status,
        )
        if expr:
            kwargs["expr"] = expr
        try:
            rows = self._get().similarity_search_with_relevance_scores(query, **kwargs)
        except Exception:
            # Older Milvus servers or schemas may not support LIKE expressions;
            # retry without the role clause and enforce it locally.
            if role and "expr" in kwargs:
                fallback_expr = self._scope_expr(
                    document_id=document_id,
                    published_only=published_only,
                    corpus_version=corpus_version,
                    status=status,
                )
                kwargs["expr"] = fallback_expr
                rows = self._get().similarity_search_with_relevance_scores(query, **kwargs)
            else:
                raise
        return self._post_filter(
            rows,
            document_id=document_id,
            role=role,
            published_only=published_only,
            corpus_version=corpus_version,
            status=status,
        )

    def _milvus_client(self):
        from pymilvus import MilvusClient

        settings = get_settings()
        kwargs: dict[str, Any] = {"uri": settings.milvus_uri}
        if settings.milvus_token:
            kwargs["token"] = settings.milvus_token
        return MilvusClient(**kwargs)

    def query_public_chunks(self, filter_expr: str = "", *, limit: int = 10000) -> list[dict[str, Any]]:
        if not self.public:
            raise ValueError("public scalar queries require the public Milvus store")
        return list(
            self._milvus_client().query(
                collection_name=self.collection_name,
                filter=filter_expr,
                output_fields=["*"],
                limit=max(1, int(limit)),
            )
        )

    def update_public_chunks(self, filter_expr: str, **fields: Any) -> int:
        if not self.public:
            raise ValueError("public updates require the public Milvus store")
        rows = self.query_public_chunks(filter_expr)
        if not rows:
            return 0
        client = self._milvus_client()
        payloads = [{"pk": row["pk"], **fields} for row in rows]
        try:
            client.upsert(
                collection_name=self.collection_name,
                data=payloads,
                partial_update=True,
            )
        except TypeError:
            # Milvus releases without partial scalar upsert require a full-row
            # update. Preserve the vector and every dynamic field returned by
            # the scalar query rather than deleting candidate evidence.
            client.upsert(
                collection_name=self.collection_name,
                data=[{**row, **fields} for row in rows],
            )
        return len(rows)

    def get_parent_chunks(
        self,
        parent_id: str,
        *,
        document_id: str | None = None,
        document_version: str | None = None,
        corpus_version: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.public:
            raise ValueError("parent expansion requires the public Milvus store")
        clauses = [f"parent_id == '{self._escape(parent_id)}'"]
        if document_id:
            clauses.append(f"document_id == '{self._escape(document_id)}'")
        if document_version:
            clauses.append(f"document_version == '{self._escape(document_version)}'")
        if corpus_version:
            clauses.append(f"corpus_version == '{self._escape(corpus_version)}'")
        rows = self.query_public_chunks(" and ".join(clauses))
        return sorted(rows, key=lambda row: int(row.get("child_index", row.get("chunk_index", 0))))

    def get_document_chunks(self, document_id: str, limit: int | None = None) -> list[Any]:
        # Exact source-order lookup is not exposed consistently by every
        # LangChain Milvus version; use a broad similarity query and enforce
        # document scope locally as a compatibility path.
        rows = self.search(document_id, limit or get_settings().knowledge_max_chunks, document_id=document_id)
        docs = [row[0] for row in rows]
        return sorted(docs, key=lambda item: int(self._metadata(item).get("chunk_index", 0)))


def get_vector_store(user_id: int) -> ChromaVectorStore | MilvusVectorStore:
    settings = get_settings()
    if settings.milvus_enabled and settings.knowledge_vector_backend.lower() == "milvus":
        return MilvusVectorStore(user_id)
    return ChromaVectorStore(user_id)


def get_public_vector_store() -> MilvusVectorStore:
    """Return the project-wide public Milvus store.

    Public retrieval is intentionally unavailable when Milvus is not enabled;
    callers can then use their configured web or base-model fallback.
    """
    settings = get_settings()
    if not settings.milvus_enabled or settings.knowledge_vector_backend.lower() != "milvus":
        raise RuntimeError("public Milvus knowledge base is disabled")
    return MilvusVectorStore(public=True)
