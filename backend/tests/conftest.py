import pytest
from fastapi.testclient import TestClient

from app.api.v1.dependencies import get_quiz_service, get_report_service
from app.main import app
from app.services.quiz_service import QuizService
from app.services.report_service import ReportService
from tests.fakes import FakeQuizGenerator, FakeReportGenerator


@pytest.fixture
def client():
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(FakeQuizGenerator())
    app.dependency_overrides[get_report_service] = lambda: ReportService(FakeReportGenerator())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides = {}
