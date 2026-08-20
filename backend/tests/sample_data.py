from app.models.quiz import Quiz, QuizGenerateRequest, Question, QuestionOption


def make_quiz(request: QuizGenerateRequest) -> Quiz:
    questions = []
    for index in range(6):
        question_type = "judge" if index == 5 else "single"
        questions.append(
            Question(
                id=f"q{index + 1}",
                type=question_type,
                stem=f"关于 {request.user_input} 的第 {index + 1} 个判断点是什么？",
                options=[
                    QuestionOption(key="A", text="正确选项"),
                    QuestionOption(key="B", text="错误选项"),
                ],
                answer=["A"],
                explanation="该选项符合题目给出的技术前提。",
                option_explanations={"A": "符合技术前提。", "B": "忽略了关键边界。"},
                knowledge_point=f"知识点 {index + 1}",
                misconception="把相邻概念混为一谈。",
                difficulty=request.difficulty,
                version_context="通用版本前提",
            )
        )
    return Quiz(
        quiz_id="quiz_test",
        title=request.user_input[:30],
        summary="围绕主题生成的测试题组。",
        topic=request.user_input,
        role=request.role,
        difficulty=request.difficulty,
        questions=questions,
        model_version="fake-model",
        prompt_version="quiz_prompt_v1",
    )
