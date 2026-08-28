import pytest

from app.core.guest import hash_guest_token
from app.research.agentic_router import (
    RouteDecision,
    build_policy,
    deterministic_route,
    validate_decision,
)
from app.repositories.generation_repository import _owner_clause


def test_guest_policy_never_exposes_personal_kb():
    policy = build_policy("Harness Engineering", "ai", "hard")
    assert policy.authenticated is False
    assert "personal_kb_search" not in policy.allowed_tools
    decision = deterministic_route(policy)
    assert decision.route == "base_model"
    assert decision.tools == []


def test_document_policy_overrides_public_tools():
    policy = build_policy("my notes", "backend", "medium", user_id=7, document_id="doc_1", knowledge_only=True)
    assert policy.allowed_tools == ["personal_kb_search", "base_model"]
    decision = deterministic_route(policy)
    assert decision.route == "personal_kb"
    assert validate_decision(decision, policy).allow_public_web is False


def test_url_policy_only_allows_extract():
    policy = build_policy("https://example.com/docs", "general", "medium", user_id=7)
    assert policy.is_url is True
    assert policy.allowed_tools == ["tavily_extract", "base_model"]
    assert deterministic_route(policy).tools == ["tavily_extract"]


def test_authenticated_ordinary_policy_requires_public_research():
    policy = build_policy("RAG", "ai", "medium", user_id=7)
    assert "personal_kb_search" not in policy.allowed_tools
    decision = deterministic_route(policy)
    assert decision.route == "web_search"
    assert decision.tools[:2] == ["query_expansion", "tavily_search"]


def test_guest_url_is_still_base_model_only():
    policy = build_policy("https://example.com/docs", "general", "medium")
    assert policy.allowed_tools == ["base_model"]
    assert deterministic_route(policy).route == "base_model"


def test_route_validation_rejects_guest_personal_tool():
    policy = build_policy("RAG", "ai", "medium")
    decision = RouteDecision(route="hybrid", tools=["personal_kb_search"], max_tool_calls=1)
    with pytest.raises(ValueError, match="forbidden|personal"):
        validate_decision(decision, policy)


def test_route_validation_rejects_url_search_escape():
    policy = build_policy("https://example.com", "general", "medium")
    decision = RouteDecision(route="web_search", tools=["tavily_search"], max_tool_calls=1, allow_public_web=True)
    with pytest.raises(ValueError, match="URL"):
        validate_decision(decision, policy)


def test_guest_token_is_hashed_and_not_reversible():
    token = "guest-token-0123456789"
    digest = hash_guest_token(token)
    assert digest and digest != token
    assert len(digest) == 64
    assert hash_guest_token(token) == digest
    assert hash_guest_token("short") is None


def test_guest_owner_clause_binds_task_to_capability_hash():
    clause, args = _owner_clause(None, "a" * 64)
    assert clause == "user_id IS NULL AND guest_token_hash=%s"
    assert args == ("a" * 64,)
    legacy_clause, legacy_args = _owner_clause(None, None)
    assert "guest_token_hash IS NULL" in legacy_clause
    assert legacy_args == ()
