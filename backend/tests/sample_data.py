from app.models.quiz import Quiz, QuizGenerateRequest, Question, QuestionOption


def make_quiz(request: QuizGenerateRequest) -> Quiz:
    questions = []
    for index in range(6):
        question_type = "multiple" if index == 4 else "judge" if index == 5 else "single"
        if question_type == "judge":
            options = [
                QuestionOption(key="A", text="正确"),
                QuestionOption(key="B", text="错误"),
            ]
            answer = ["A"]
        else:
            options = [
                QuestionOption(key="A", text="正确选项 A"),
                QuestionOption(key="B", text="干扰选项 B"),
                QuestionOption(key="C", text="正确选项 C" if question_type == "multiple" else "干扰选项 C"),
                QuestionOption(key="D", text="干扰选项 D"),
            ]
            answer = ["A", "C"] if question_type == "multiple" else ["A"]
        questions.append(
            Question(
                id=f"q{index + 1}",
                type=question_type,
                stem=f"关于 {request.user_input} 的第 {index + 1} 个判断点是什么？",
                options=options,
                answer=answer,
                explanation="该选项符合题目给出的技术前提。",
                option_explanations={option.key: "符合技术前提。" if option.key in answer else "忽略了关键边界。" for option in options},
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
        prompt_version="question-types-v1",
    )
