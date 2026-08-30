"""Operational helpers for Milvus Lite and server deployments.

The application keeps this module optional: importing it never connects to
Milvus, which makes local development and the unit-test suite independent of
the vector service.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings


@dataclass(frozen=True)
class MilvusHealth:
    ok: bool
    version: str | None = None
    error: str | None = None


def _client():
    from pymilvus import MilvusClient

    settings = get_settings()
    kwargs: dict[str, Any] = {"uri": settings.milvus_uri}
    if settings.milvus_token:
        kwargs["token"] = settings.milvus_token
    return MilvusClient(**kwargs)


def health_check() -> MilvusHealth:
    """Return a redacted health result without raising connection errors."""
    try:
        version = str(_client().get_server_version())
        return MilvusHealth(ok=True, version=version)
    except Exception as exc:  # pragma: no cover - exercised with mocked client
        return MilvusHealth(ok=False, error=type(exc).__name__)


def ensure_collection(collection_name: str, dimension: int | None = None) -> bool:
    """Create and load a collection if it does not exist.

    ``MilvusClient.create_collection`` is idempotent from the caller's point
    of view: an existing collection is left untouched. A dimension must be
    supplied for a new collection because Milvus cannot infer it before the
    first embedding is inserted.
    """
    settings = get_settings()
    client = _client()
    if client.has_collection(collection_name):
        try:
            client.load_collection(collection_name)
        except Exception:
            pass
        return False
    dim = dimension or settings.milvus_vector_dimension
    if not dim or int(dim) <= 0:
        raise ValueError("MILVUS_VECTOR_DIMENSION must be configured before creating a collection")
    client.create_collection(
        collection_name=collection_name,
        dimension=int(dim),
        metric_type=settings.milvus_metric_type,
        primary_field_name="pk",
        id_type="string",
        vector_field_name="vector",
        auto_id=False,
        enable_dynamic_field=True,
    )
    try:
        client.load_collection(collection_name)
    except Exception:
        pass
    return True


def initialize_collections() -> dict[str, bool]:
    """Initialize the fixed public/private collections and return creation flags."""
    settings = get_settings()
    return {
        settings.milvus_public_collection: ensure_collection(settings.milvus_public_collection),
        settings.milvus_private_collection: ensure_collection(settings.milvus_private_collection),
    }


if __name__ == "__main__":  # pragma: no cover - convenience for operations
    print(initialize_collections())
