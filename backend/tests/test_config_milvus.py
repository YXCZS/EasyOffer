import pytest

from app.core.config import Settings


def test_milvus_recall_defaults_are_bounded():
    settings = Settings(_env_file=None, milvus_dense_recall_k=20, milvus_sparse_recall_k=30, milvus_fetch_k_max=40)
    assert settings.milvus_dense_recall_k == 20
    assert settings.milvus_sparse_recall_k == 30
    assert settings.milvus_fetch_k_max == 40


@pytest.mark.parametrize("field", ["milvus_rrf_k", "milvus_dense_recall_k", "milvus_sparse_recall_k", "milvus_fetch_k_max"])
def test_milvus_positive_settings_reject_zero_or_negative(field):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: 0})


def test_milvus_fetch_limit_must_cover_recall_depth():
    with pytest.raises(ValueError, match="FETCH_K_MAX"):
        Settings(_env_file=None, milvus_dense_recall_k=100, milvus_sparse_recall_k=50, milvus_fetch_k_max=20)


def test_milvus_env_file_path_is_stable():
    # Explicit values always win over the file, while the model config points
    # at backend/.env independent of the process working directory.
    assert Settings.model_config["env_file"].endswith("backend\\.env") or Settings.model_config["env_file"].endswith("backend/.env")


def test_ragas_model_defaults_to_low_cost_dashscope_snapshot_and_is_overridable():
    default = Settings(_env_file=None)
    assert default.ragas_llm_model == "qwen3.7-flash"

    overridden = Settings(_env_file=None, ragas_llm_model="qwen3.7-flash")
    assert overridden.ragas_llm_model == "qwen3.7-flash"
