from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    tavily_api_key: str | None = None
    tavily_enabled: bool = True
    tavily_max_tool_calls: int = 2
    tavily_tool_timeout_seconds: float = 40.0
    tavily_agent_timeout_seconds: float = 6.0
    tavily_max_results: int = 5
    tavily_max_page_chars: int = 12000
    tavily_max_context_chars: int = 24000
    tavily_max_query_variants: int = 3
    tavily_search_timeout_seconds: float = 18.0
    tavily_extract_timeout_seconds: float = 25.0
    tavily_planner_timeout_seconds: float = 8.0
    tavily_filter_timeout_seconds: float = 12.0
    tavily_research_max_retries: int = 1
    tavily_relevance_threshold: float = 0.75
    tavily_max_filtered_sources: int = 5
    tavily_planner_version: str = "query-planner-v1"
    tavily_filter_version: str = "evidence-filter-v1"
    agentic_rag_enabled: bool = True
    agentic_rag_max_tool_calls: int = 3
    agentic_rag_timeout_seconds: float = 45.0
    agentic_rag_cache_ttl_seconds: int = 3600
    agentic_rag_router_version: str = "policy-agent-v1"
    agentic_rag_router_timeout_seconds: float = 8.0
    agentic_rag_high_confidence: float = 0.75
    agentic_rag_medium_confidence: float = 0.45
    agentic_rag_max_query_variants: int = 2
    guest_generation_enabled: bool = True
    guest_max_active_tasks: int = 2
    guest_daily_task_limit: int = 10
    guest_token_header: str = "X-Guest-Token"
    guest_token_hash_secret: str = "change-guest-secret"
    wechat_app_id: str | None = None
    wechat_app_secret: str | None = None
    wechat_content_security_enabled: bool = False
    wechat_content_security_fail_closed: bool = True
    wechat_content_security_timeout_seconds: float = 5.0
    wechat_content_security_max_retries: int = 1
    wechat_msg_sec_version: int = 2
    wechat_msg_sec_scene: int = 2
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "easyoffer"
    database_url: str | None = None
    database_backend: str = "sqlalchemy"
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 60 * 24 * 30
    upload_dir: str = "uploads"
    knowledge_upload_dir: str = "uploads/knowledge"
    chroma_persist_dir: str = "data/chroma"
    # Milvus is opt-in during migration; Chroma remains the compatibility
    # backend until the Milvus shadow-read checks pass.
    knowledge_vector_backend: str = "chroma"
    milvus_enabled: bool = False
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str | None = None
    milvus_public_collection: str = "easyoffer_public_chunks"
    milvus_private_collection: str = "easyoffer_private_chunks"
    milvus_vector_dimension: int | None = None
    milvus_metric_type: str = "COSINE"
    milvus_consistency_level: str = "Bounded"
    milvus_retrieval_top_k: int = 5
    milvus_public_min_score: float = 0.25
    milvus_shadow_read: bool = False
    milvus_auto_create_collections: bool = True
    agentic_rag_graph_enabled: bool = True
    agentic_rag_max_rounds: int = 3
    agentic_rag_max_context_chars: int = 24000
    agentic_rag_tool_timeout_seconds: float = 18.0
    embedding_api_key: str | None = None
    dashscope_api_key: str | None = None
    # z-image-turbo is served from a Model Studio workspace endpoint.
    dashscope_workspace_id: str | None = None
    dashscope_region: str = "cn-beijing"
    image_generation_enabled: bool = False
    # Low-cost single-image model. Keep this configurable for future model swaps.
    image_generation_model: str = "z-image-turbo"
    image_generation_base_url: str | None = None
    image_generation_timeout_seconds: float = 30.0
    image_generation_poll_interval_seconds: float = 2.0
    image_generation_max_concurrency: int = 2
    image_generation_max_per_quiz: int = 3
    image_generation_max_prompt_chars: int = 1200
    image_generation_max_bytes: int = 5 * 1024 * 1024
    image_generation_retry_count: int = 1
    image_generation_size: str = "512*512"
    cos_secret_id: str | None = None
    cos_secret_key: str | None = None
    cos_region: str | None = None
    cos_bucket: str | None = None
    cos_public_base_url: str | None = None
    cos_enabled: bool = False
    cos_public_read: bool = True
    cos_signed_url_expire_seconds: int = 3600
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int | None = None
    embedding_batch_size: int = 10
    knowledge_max_file_bytes: int = 20 * 1024 * 1024
    knowledge_max_documents: int = 50
    knowledge_max_chunks: int = 5000
    knowledge_chunk_size: int = 900
    knowledge_chunk_overlap: int = 120
    knowledge_top_k: int = 5
    knowledge_enabled: bool = True
    public_base_url: str = "http://127.0.0.1:8000"
    # Incremental generation is latency-sensitive: keep the first question
    # responsive while allowing the normal one-shot flow to retain its
    # existing, more generous model budget.
    incremental_llm_timeout_seconds: float = 30.0
    incremental_llm_max_retries: int = 0
    incremental_evidence_timeout_seconds: float = 30.0
    # Allow the mandatory query-expansion + Tavily search + evidence-filter
    # pipeline to finish before the first question falls back to the base
    # model. This keeps normal first-question latency within the 30-40s target.
    incremental_first_question_evidence_timeout_seconds: float = 40.0
    incremental_plan_timeout_seconds: float = 15.0
    incremental_question_attempts: int = 2
    incremental_task_timeout_seconds: float = 300.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
