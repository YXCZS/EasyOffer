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
    )


class DeepSeekQuizGenerator:
    async def generate(self, request: QuizGenerateRequest) -> QuizGenerateOutput:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是专业的中文程序员技术面试出题助手，只返回结构化结果。"),
                (
                    "user",
                    "主题：{topic}\n岗位：{role}\n难度：{difficulty}\n生成 6 道可判定题目。",
                ),
            ]
        )
        chain = prompt | _chat_model(0.4).with_structured_output(QuizGenerateOutput)
        return await chain.ainvoke(
            {"topic": request.user_input, "role": request.role, "difficulty": request.difficulty}
        )


class DeepSeekReportGenerator:
    async def generate(
        self, request: ReportGenerateRequest, score_summary: ScoreSummary
    ) -> ReportDraft:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是中文程序员技术面试复盘助手，只返回结构化结果。"),
                (
                    "user",
                    "主题：{topic}\n正确：{score}/{total}\n待巩固：{review_points}\n"
                    "请生成三句总结和具体建议。",
                ),
            ]
        )
        chain = prompt | _chat_model(0.5).with_structured_output(ReportDraft)
        return await chain.ainvoke(
            {
                "topic": request.topic,
                "score": score_summary.score,
                "total": score_summary.total,
                "review_points": ", ".join(score_summary.review_points),
            }
        )
