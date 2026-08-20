import asyncio

from app.models.quiz import QuizGenerateRequest
from app.services.quiz_service import QuizService
from tests.fakes import FakeQuizGenerator


def test_quiz_service_retries_transient_generation_error():
    generator = FakeQuizGenerator(failures=1)
    service = QuizService(generator=generator, max_attempts=2)
    quiz = asyncio.run(service.generate(QuizGenerateRequest(user_input="TCP 三次握手")))
    assert quiz.quiz_id == "quiz_test"
    assert generator.calls == 2
