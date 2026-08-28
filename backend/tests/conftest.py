import pytest
from fastapi.testclient import TestClient

from app.api.v1.dependencies import get_quiz_service, get_report_service
from app.main import app
from app.services.quiz_service import QuizService
from app.services.report_service import ReportService
from tests.fakes import FakeQuizGenerator, FakeReportGenerator


@pytest.fixture(autouse=True)
def isolate_external_vector_runtime(monkeypatch):
    """Keep unit tests independent from a developer's local .env services.

    Tests that exercise Milvus adapters or the Agentic graph instantiate those
    components directly or can override these settings explicitly.
    """
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", False)
    monkeypatch.setattr(settings, "knowledge_vector_backend", "chroma")


@pytest.fixture
def client():
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(FakeQuizGenerator())
    app.dependency_overrides[get_report_service] = lambda: ReportService(FakeReportGenerator())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides = {}
