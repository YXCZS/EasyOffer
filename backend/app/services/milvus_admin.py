"""Operational helpers for the Milvus Standalone/Distributed deployment.

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
    collections: dict[str, dict[str, Any]] | None = None


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
        client = _client()
        version = str(client.get_server_version())
        settings = get_settings()
        suffix = settings.milvus_native_collection_suffix
        names = [f"{settings.milvus_public_collection}{suffix}", f"{settings.milvus_private_collection}{suffix}"]
        collections: dict[str, dict[str, Any]] = {}
        healthy = True
        for name in names:
            exists = bool(client.has_collection(name))
            item: dict[str, Any] = {"exists": exists}
            if exists:
                try:
                    state = client.get_load_state(name).get("state") if hasattr(client, "get_load_state") else None
                    item["loaded"] = str(state).lower().endswith("loaded")
                except Exception:
                    item["loaded"] = False
                try:
                    description = client.describe_collection(name) if hasattr(client, "describe_collection") else {}
                    summary = _schema_summary(description)
                    if hasattr(client, "list_indexes"):
                        summary["indexes"] = sorted(str(item) for item in (client.list_indexes(name) or []))
                    item.update(summary)
                    item["row_count"] = int(client.get_collection_stats(name).get("row_count", 0)) if hasattr(client, "get_collection_stats") else None
                except Exception as exc:
                    item["schema_error"] = type(exc).__name__
                healthy = healthy and bool(item.get("loaded", True)) and "schema_error" not in item
            else:
                healthy = False
            collections[name] = item
        return MilvusHealth(ok=healthy, version=version, collections=collections)
    except Exception as exc:  # pragma: no cover - exercised with mocked client
        return MilvusHealth(ok=False, error=type(exc).__name__)


def _schema_summary(description: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, non-sensitive summary of a Milvus collection schema."""
    fields = description.get("fields") or []
    field_names = {str(field.get("name")) for field in fields if isinstance(field, dict)}
    vector_dim = None
    for field in fields:
        if isinstance(field, dict) and field.get("name") == "vector":
            params = field.get("params") or {}
            vector_dim = params.get("dim")
            break
    functions = description.get("functions") or []
    function_names = {str(fn.get("name")) for fn in functions if isinstance(fn, dict)}
    schema_version = "native-hybrid-v2" if {"pk", "text", "vector", "sparse"}.issubset(field_names) and "text_bm25" in function_names else "unknown"
    return {
        "schema_version": schema_version,
        "fields": sorted(field_names),
        "vector_dimension": int(vector_dim) if vector_dim is not None else None,
        "functions": sorted(function_names),
        "indexes": [],
    }


def _validate_native_contract(client: Any, collection_name: str, dimension: int | None) -> None:
    """Fail fast when an existing native collection cannot satisfy the adapter."""
    settings = get_settings()
    if not settings.milvus_native_hybrid_enabled or not hasattr(client, "describe_collection"):
        return
    description = client.describe_collection(collection_name)
    summary = _schema_summary(description)
    if summary["schema_version"] != "native-hybrid-v2":
        raise ValueError(f"Milvus collection {collection_name} has incompatible native schema")
    if dimension is not None and summary.get("vector_dimension") not in (None, int(dimension)):
        raise ValueError(f"Milvus collection {collection_name} vector dimension mismatch")
    if hasattr(client, "list_indexes"):
        indexes = {str(item) for item in (client.list_indexes(collection_name) or [])}
        if not {"vector", "sparse"}.issubset(indexes):
            raise ValueError(f"Milvus collection {collection_name} missing native indexes")


def ensure_collection(collection_name: str, dimension: int | None = None) -> bool:
    """Create and load a native dense + BM25 collection if it does not exist.

    ``MilvusClient.create_collection`` is idempotent from the caller's point
    of view: an existing collection is left untouched. A dimension must be
    supplied for a new collection because Milvus cannot infer it before the
    first embedding is inserted.
    """
    settings = get_settings()
    client = _client()
    if client.has_collection(collection_name):
        dim = dimension or settings.milvus_vector_dimension
        if settings.milvus_native_hybrid_enabled:
            _validate_native_contract(client, collection_name, int(dim) if dim else None)
        try:
            client.load_collection(collection_name)
        except Exception:
            pass
        return False
    dim = dimension or settings.milvus_vector_dimension
    if not dim or int(dim) <= 0:
        raise ValueError("MILVUS_VECTOR_DIMENSION must be configured before creating a collection")
    native_schema_supported = hasattr(client, "create_schema") and hasattr(client, "prepare_index_params")
    if settings.milvus_native_hybrid_enabled and native_schema_supported and collection_name.endswith(settings.milvus_native_collection_suffix):
        from pymilvus import DataType, Function, FunctionType

        schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("pk", DataType.VARCHAR, max_length=256, is_primary=True)
        schema.add_field(
            "text",
            DataType.VARCHAR,
            max_length=max(1024, int(settings.milvus_native_text_max_length)),
            enable_analyzer=True,
            analyzer_params={"type": "standard"},
        )
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=int(dim))
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="text_bm25",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type=settings.milvus_metric_type,
        )
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"drop_ratio_build": 0.2},
        )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level=settings.milvus_consistency_level,
        )
    else:
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
    suffix = settings.milvus_native_collection_suffix
    return {
        f"{settings.milvus_public_collection}{suffix}": ensure_collection(
            f"{settings.milvus_public_collection}{suffix}"
        ),
        f"{settings.milvus_private_collection}{suffix}": ensure_collection(
            f"{settings.milvus_private_collection}{suffix}"
        ),
    }


if __name__ == "__main__":  # pragma: no cover - convenience for operations
    print(initialize_collections())
