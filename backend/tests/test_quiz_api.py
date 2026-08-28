from app.api.v1.dependencies import get_quiz_service, get_visual_asset_service
from app.main import app
from app.models.quiz import QuestionVisualization, QuizGenerateOutput
from app.services.quiz_service import QuizService
from tests.sample_data import make_quiz


def test_generate_quiz_returns_six_valid_questions(client):
    response = client.post(
        "/api/v1/quiz/generate",
        json={
            "user_input": "Java HashMap 在 JDK 8 中的扩容机制",
            "role": "java-backend",
            "difficulty": "medium",
            "question_count": 6,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["questions"]) == 6
    assert [question["type"] for question in data["questions"]] == [
        "single", "single", "single", "single", "multiple", "judge"
    ]
    assert [option["text"] for option in data["questions"][5]["options"]] == ["正确", "错误"]
    assert all(
        set(question["answer"]).issubset({item["key"] for item in question["options"]})
        for question in data["questions"]
    )


def test_non_technical_topic_returns_scope_error(client):
    class UnsupportedGenerator:
        async def generate(self, request):
            return QuizGenerateOutput(supported=False, message="当前只支持程序员技术面试知识点")

    app.dependency_overrides[get_quiz_service] = lambda: QuizService(UnsupportedGenerator())
    response = client.post(
        "/api/v1/quiz/generate", json={"user_input": "如何准备明天的旅游行程"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == 4001
    assert response.json()["data"]["supported"] is False


def test_invalid_input_is_rejected(client):
    response = client.post("/api/v1/quiz/generate", json={"user_input": " "})
    assert response.status_code == 422


def test_generate_quiz_rejects_unsupported_question_count(client):
    response = client.post(
        "/api/v1/quiz/generate", json={"user_input": "Redis 缓存", "question_count": 5}
    )
    assert response.status_code == 422


def test_generate_quiz_returns_research_metadata_and_keeps_api_contract(client):
    class ResearchedGenerator:
        async def generate(self, request):
            quiz = make_quiz(request)
            quiz.research_used = True
            quiz.research_mode = "agent"
            quiz.research_tools = ["tavily_search"]
            return QuizGenerateOutput(quiz=quiz)

    app.dependency_overrides[get_quiz_service] = lambda: QuizService(ResearchedGenerator())
    response = client.post("/api/v1/quiz/generate", json={"user_input": "Harness Engineering"})
    assert response.status_code == 200
    assert response.json()["data"]["research_used"] is True
    assert response.json()["data"]["research_tools"] == ["tavily_search"]


def test_research_fallback_generator_still_returns_successful_quiz(client):
    class FallbackGenerator:
        async def generate(self, request):
            return QuizGenerateOutput(quiz=make_quiz(request))

    app.dependency_overrides[get_quiz_service] = lambda: QuizService(FallbackGenerator())
    response = client.post("/api/v1/quiz/generate", json={"user_input": "最新的技术主题"})
    assert response.status_code == 200
    assert response.json()["data"]["research_used"] is False


def test_generate_images_switch_controls_background_asset_scheduling(client):
    scheduled: list[str] = []

    class VisualGenerator:
        async def generate(self, request):
            quiz = make_quiz(request)
            quiz.questions = [
                question.model_copy(
                    update={
                        "visualization": QuestionVisualization(
                            enabled=True,
                            mode="image",
                            type="flowchart",
                            image_prompt=f"{question.knowledge_point} 技术流程图",
                            alt_text=f"{question.knowledge_point} 流程图",
                            status="pending",
                        )
                    }
                )
                for question in quiz.questions
            ]
            quiz.generate_images = request.generate_images
            return QuizGenerateOutput(quiz=quiz)

    class VisualAssets:
        async def schedule(self, _pool, question, **_kwargs):
            scheduled.append(question.id)
            return f"asset-{question.id}"

    app.dependency_overrides[get_quiz_service] = lambda: QuizService(VisualGenerator())
    app.dependency_overrides[get_visual_asset_service] = lambda: VisualAssets()

    disabled = client.post(
        "/api/v1/quiz/generate",
        json={"user_input": "RAG 技术", "generate_images": False},
    )
    assert disabled.status_code == 200
    assert scheduled == []

    enabled = client.post(
        "/api/v1/quiz/generate",
        json={"user_input": "RAG 技术", "generate_images": True},
    )
    assert enabled.status_code == 200
    assert scheduled == ["q1", "q2", "q3", "q4", "q5", "q6"]
