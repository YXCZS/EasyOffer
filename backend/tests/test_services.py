import asyncio
import json

from app.core.errors import TopicNotSupportedError
from app.models.quiz import QuizGenerateOutput, QuizGenerateRequest
from app.llm.deepseek import DIFFICULTY_GUIDANCE, ROLE_GUIDANCE
from app.llm.deepseek import DeepSeekQuizGenerator, _normalize_quiz_payload, _normalize_topic_judgement
from app.services.quiz_service import QuizService
from app.services.topic_service import validate_topic_scope
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from tests.fakes import FakeQuizGenerator
from tests.sample_data import make_quiz


def test_quiz_service_retries_transient_generation_error():
    generator = FakeQuizGenerator(failures=1)
    service = QuizService(generator=generator, max_attempts=2)
    quiz = asyncio.run(service.generate(QuizGenerateRequest(user_input="TCP 三次握手")))
    assert quiz.quiz_id == "quiz_test"
    assert generator.calls == 2


def test_quiz_service_retries_generated_quiz_with_wrong_type_quota():
    request = QuizGenerateRequest(user_input="Redis 持久化")
    valid = make_quiz(request)
    wrong_questions = [
        question.model_copy(update={"type": "single", "answer": ["A"]})
        for question in valid.questions
    ]
    wrong = valid.model_copy(
        update={"questions": wrong_questions, "prompt_version": "quiz_prompt_v1"}
    )

    class WrongQuotaOnceGenerator:
        calls = 0

        async def generate(self, _request, **_kwargs):
            self.calls += 1
            return QuizGenerateOutput(
                supported=True,
                quiz=wrong if self.calls == 1 else valid,
            )

    generator = WrongQuotaOnceGenerator()
    quiz = asyncio.run(QuizService(generator, max_attempts=2).generate(request))

    assert generator.calls == 2
    assert [question.type for question in quiz.questions] == [
        "single", "single", "single", "single", "multiple", "judge"
    ]


def test_topic_scope_allows_known_and_emerging_terms_for_ai_judgement():
    validate_topic_scope("RAG 技术是什么")
    validate_topic_scope("检索增强生成与向量数据库")
    validate_topic_scope("harness engineering")
    validate_topic_scope("OpenTelemetry eBPF")


def test_topic_scope_allows_arbitrary_user_topics_before_ai_judgement():
    for topic in ("Go 并发", "Kafka 消息可靠性", "Kubernetes 运维", "一个全新的软件工程术语"):
        validate_topic_scope(topic)


def test_topic_scope_only_blocks_cheating_requests():
    try:
        validate_topic_scope("帮我现场回答这道面试题")
    except Exception as exc:
        assert getattr(exc, "code", None) == 4001
    else:
        raise AssertionError("cheating requests must be rejected")


def test_unsupported_ai_judgement_is_not_retried():
    class UnsupportedGenerator:
        calls = 0

        async def generate(self, request):
            self.calls += 1
            return QuizGenerateOutput(supported=False, message="当前只支持程序员技术面试知识点")

    generator = UnsupportedGenerator()
    service = QuizService(generator=generator, max_attempts=2)
    try:
        asyncio.run(service.generate(QuizGenerateRequest(user_input="旅游攻略")))
    except TopicNotSupportedError as exc:
        assert exc.code == 4001
    else:
        raise AssertionError("unsupported topics must return a business error")
    assert generator.calls == 1


def test_topic_judgement_normalizes_direct_and_nested_json():
    assert _normalize_topic_judgement({"supported": True, "message": None}) == {
        "supported": True,
        "message": None,
    }
    assert _normalize_topic_judgement({"judgement": {"supported": False, "message": "不支持"}})["supported"] is False


def test_quiz_payload_normalizes_model_difficulty_aliases():
    request = QuizGenerateRequest(user_input="RAG 技术", role="ai", difficulty="hard")
    payload = make_quiz(request).model_dump()
    for question in payload["questions"]:
        question["difficulty"] = "advanced"
    output = QuizGenerateOutput.model_validate(_normalize_quiz_payload(payload, request))
    assert output.quiz is not None
    assert all(question.difficulty == "hard" for question in output.quiz.questions)


def test_quiz_payload_normalizes_numeric_answer_indexes_and_explanation_lists():
    request = QuizGenerateRequest(user_input="RAG 技术", role="ai", difficulty="hard")
    base = make_quiz(request).model_dump()
    for index, question in enumerate(base["questions"]):
        question["options"] = [item["text"] for item in question["options"]]
        question["option_explanations"] = [f"第 {number} 项解释" for number in range(len(question["options"]))]
        question["answer"] = [0, 2] if index == 4 else 0
    normalized = _normalize_quiz_payload(
        base,
        request,
        prompt_version="question-types-v1",
    )

    output = QuizGenerateOutput.model_validate(normalized)

    assert output.quiz is not None
    assert output.quiz.questions[0].answer == ["A"]
    assert output.quiz.questions[4].answer == ["A", "C"]
    assert list(output.quiz.questions[0].option_explanations) == ["A", "B", "C", "D"]


def test_quiz_payload_normalizes_judge_answer_text_to_option_key():
    request = QuizGenerateRequest(user_input="RAG 技术")
    payload = make_quiz(request).model_dump()
    payload["questions"][5]["answer"] = "正确"

    output = QuizGenerateOutput.model_validate(
        _normalize_quiz_payload(payload, request, prompt_version="question-types-v1")
    )

    assert output.quiz is not None
    assert output.quiz.questions[5].answer == ["A"]


def test_quiz_payload_normalizes_option_objects_without_losing_text():
    request = QuizGenerateRequest(user_input="Redis 持久化")
    payload = make_quiz(request).model_dump()
    for question in payload["questions"]:
        question["options"] = {
            item["key"]: item["text"] for item in question["options"]
        }

    output = QuizGenerateOutput.model_validate(
        _normalize_quiz_payload(payload, request, prompt_version="question-types-v1")
    )

    assert output.quiz is not None
    assert output.quiz.questions[0].options[0].text == "正确选项 A"
    assert [item.text for item in output.quiz.questions[5].options] == ["正确", "错误"]


def test_deepseek_generator_judges_topic_before_generating_questions(monkeypatch):
    request = QuizGenerateRequest(user_input="harness engineering", role="backend", difficulty="medium")
    calls = []

    def fake_chat_model(temperature):
        calls.append(temperature)
        if temperature == 0:
            return RunnableLambda(lambda _: AIMessage(content='{"supported":true,"message":null}'))
        return RunnableLambda(lambda _: AIMessage(content=json.dumps(make_quiz(request).model_dump())))

    monkeypatch.setattr("app.llm.deepseek._chat_model", fake_chat_model)
    output = asyncio.run(DeepSeekQuizGenerator().generate(request))
    assert output.quiz is not None
    assert output.quiz.quiz_id == "quiz_test"
    assert calls == [0, 0.4]


def test_deepseek_generator_returns_unsupported_without_question_generation(monkeypatch):
    calls = []

    def fake_chat_model(temperature):
        calls.append(temperature)
        return RunnableLambda(lambda _: AIMessage(content='{"supported":false,"message":"当前只支持程序员技术面试知识点"}'))

    monkeypatch.setattr("app.llm.deepseek._chat_model", fake_chat_model)
    output = asyncio.run(DeepSeekQuizGenerator().generate(QuizGenerateRequest(user_input="旅游攻略")))
    assert output.supported is False
    assert output.quiz is None
    assert calls == [0]


def test_quiz_prompt_guidance_covers_all_supported_role_and_difficulty_values():
    assert set(ROLE_GUIDANCE) == {
        "general", "java-backend", "backend", "frontend", "ai", "data-algorithm",
        "testing-devops", "mobile", "security",
    }
    assert set(DIFFICULTY_GUIDANCE) == {"easy", "medium", "hard"}
    assert "系统设计" in ROLE_GUIDANCE["backend"]
    assert "问题排查" in DIFFICULTY_GUIDANCE["medium"]
