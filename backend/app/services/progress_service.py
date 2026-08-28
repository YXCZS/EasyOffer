import json
from typing import Any

from app.models.progress import ProgressSaveRequest
from app.models.quiz import Quiz
from app.repositories import progress_repository


class ProgressNotFoundError(Exception):
    pass


class ProgressConflictError(Exception):
    def __init__(self, latest: dict[str, Any] | None = None) -> None:
        super().__init__("练习进度已被其他设备更新，请刷新后重试")
        self.latest = latest


def _validate_and_status(row: dict[str, Any], request: ProgressSaveRequest) -> tuple[int, str]:
    questions = Quiz.model_validate(
        {
            "quiz_id": row["quiz_id"],
            "title": row["title"],
            "summary": row["summary"],
            "topic": row["user_input"],
            "role": row["role"],
            "difficulty": row["difficulty"],
            "questions": row["questions_json"] if isinstance(row["questions_json"], list) else json.loads(row["questions_json"]),
            "model_version": "stored",
            "prompt_version": "stored",
        }
    )
    question_map = {question.id: question for question in questions.questions}
    records = {record.question_id: record for record in request.answer_records}
    if any(question_id not in question_map for question_id in records):
        raise ValueError("答题记录包含未知题目")
    if request.current_index > len(questions.questions):
        raise ValueError("当前题目位置无效")
    for record in records.values():
        valid_keys = {option.key for option in question_map[record.question_id].options}
        if any(key not in valid_keys for key in record.selected_answers):
            raise ValueError("答题选项无效")
    answered_count = len(records)
    status = "ready_for_report" if answered_count == len(questions.questions) else "in_progress"
    return answered_count, status


async def save_progress(connection: Any, user_id: int, quiz_id: str, request: ProgressSaveRequest) -> dict[str, Any]:
    row = await progress_repository.get_progress(connection, user_id, quiz_id)
    if row is None:
        raise ProgressNotFoundError()
    answered_count, status = _validate_and_status(row, request)
    updated = await progress_repository.update_progress(connection, user_id, quiz_id, request, status, answered_count)
    if updated is None:
        latest = await progress_repository.get_progress(connection, user_id, quiz_id)
        raise ProgressConflictError(latest)
    return updated


def to_detail(row: dict[str, Any]) -> dict[str, Any]:
    questions = row["questions_json"] if isinstance(row["questions_json"], list) else json.loads(row["questions_json"])
    quiz = Quiz.model_validate(
        {
            "quiz_id": row["quiz_id"],
            "title": row["title"],
            "summary": row["summary"],
            "topic": row["user_input"],
            "role": row["role"],
            "difficulty": row["difficulty"],
            "questions": questions,
            "model_version": "stored",
            "prompt_version": "stored",
        }
    )
    return {
        "quiz": quiz,
        "status": row["status"],
        "current_index": row["current_index"],
        "answered_count": row["answered_count"],
        "total_questions": row["total_questions"],
        "answer_records": row["answer_records"],
        "version": row["version"],
        "updated_at": row["updated_at"],
        "last_error": row.get("last_error"),
    }
