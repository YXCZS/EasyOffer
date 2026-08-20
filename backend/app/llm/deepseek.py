import json
from uuid import uuid4

from app.core.config import get_settings
from app.models.report import ReportDraft, ReportGenerateRequest
from app.models.quiz import QuizGenerateOutput, QuizGenerateRequest
from app.services.scoring_service import ScoreSummary


def _chat_model(temperature: float):
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    return ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=temperature,
        timeout=30,
        max_retries=1,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


def _message_json(message) -> dict:
    content = message.content
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item) for item in content
        )
    if not isinstance(content, str):
        raise ValueError("模型返回内容不是 JSON 文本")
    return json.loads(content)


def _normalize_quiz_payload(payload: dict, request: QuizGenerateRequest) -> dict:
    quiz = payload.get("quiz") or payload
    quiz.setdefault("quiz_id", f"quiz_{uuid4().hex[:12]}")
    quiz.setdefault("title", f"{request.user_input} 面试练习")
    quiz.setdefault("summary", f"围绕 {request.user_input} 的 6 道技术面试题")
    quiz.setdefault("topic", request.user_input)
    quiz.setdefault("role", request.role)
    quiz.setdefault("difficulty", request.difficulty)
    quiz.setdefault("model_version", get_settings().deepseek_model)
    quiz.setdefault("prompt_version", "mvp-json-v1")
    for index, question in enumerate(quiz.get("questions", []), start=1):
        question["id"] = str(question.get("id") or f"q{index}")
        options = question.get("options", [])
        if options and isinstance(options[0], str):
            question["options"] = [{"key": chr(65 + i), "text": text} for i, text in enumerate(options)]
        else:
            question["options"] = [
                {"key": str(item.get("key", chr(65 + i))), "text": str(item.get("text", item))}
                for i, item in enumerate(options)
            ]
        answers = question.get("answer", [])
        if isinstance(answers, str):
            question["answer"] = [answers]
        option_keys = [item["key"] for item in question.get("options", []) if isinstance(item, dict)]
        question.setdefault("option_explanations", {key: "该选项的判断依据见题目解析。" for key in option_keys})
        question.setdefault("knowledge_point", request.user_input[:100])
        question.setdefault("misconception", "注意区分概念定义与实际工程边界。")
        question.setdefault("difficulty", request.difficulty)
        question.setdefault("version_context", "以当前主流技术版本为准。")
    return {"supported": True, "message": None, "quiz": quiz}


def _normalize_report_payload(payload: dict) -> dict:
    report = payload.get("report") or payload
    for field in ("summary", "advice"):
        value = report.get(field, [])
        if isinstance(value, str):
            report[field] = [value]
    limitations = report.get("limitations", "")
    if isinstance(limitations, list):
        report["limitations"] = "；".join(str(item) for item in limitations)
    return report


class DeepSeekQuizGenerator:
    async def generate(self, request: QuizGenerateRequest) -> QuizGenerateOutput:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是专业的中文程序员技术面试出题助手。必须只返回 JSON，不能包含 Markdown。"
                    "JSON 顶层结构必须是 {{supported, message, quiz}}；支持主题时 supported=true，"
                    "quiz.questions 必须恰好包含 6 道题，每道题包含 id、type、stem、options、answer、"
                    "explanation、option_explanations、knowledge_point、misconception、difficulty、version_context。",
                ),
                (
                    "user",
                    "主题：{topic}\n岗位：{role}\n难度：{difficulty}\n生成 6 道可判定题目。",
                ),
            ]
        )
        message = await (prompt | _chat_model(0.4)).ainvoke(
            {"topic": request.user_input, "role": request.role, "difficulty": request.difficulty}
        )
        return QuizGenerateOutput.model_validate(_normalize_quiz_payload(_message_json(message), request))


class DeepSeekReportGenerator:
    async def generate(
        self, request: ReportGenerateRequest, score_summary: ScoreSummary
    ) -> ReportDraft:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是中文程序员技术面试复盘助手。必须只返回 JSON，不能包含 Markdown。"
                    "JSON 顶层结构必须是 {{summary, advice, limitations}}；summary 必须恰好 3 条。",
                ),
                (
                    "user",
                    "主题：{topic}\n正确：{score}/{total}\n待巩固：{review_points}\n"
                    "请生成三句总结和具体建议。",
                ),
            ]
        )
        message = await (prompt | _chat_model(0.5)).ainvoke(
            {
                "topic": request.topic,
                "score": score_summary.score,
                "total": score_summary.total,
                "review_points": ", ".join(score_summary.review_points),
            }
        )
        return ReportDraft.model_validate(_normalize_report_payload(_message_json(message)))
