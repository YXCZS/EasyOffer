from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core.config import get_settings
from app.models.quiz import Question, QuestionVisualization


SECRET_PATTERN = re.compile(r"(?i)(api[_ -]?key|secret|password|token|access[_ -]?key)")
CHINESE_IMAGE_CONSTRAINT = (
    "图片内如需文字，所有标题、节点、标签和注释必须使用简体中文，禁止出现英文单词或字母；"
    "若无法准确渲染中文，则改为不含文字的技术示意图。"
)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def sanitize_prompt(prompt: str, fallback: str) -> str:
    settings = get_settings()
    value = " ".join((prompt or fallback).split())
    value = SECRET_PATTERN.sub("technical credential", value)
    # Image models often invent English labels even when the surrounding
    # prompt is Chinese. Keep this constraint in every prompt so generated
    # diagrams remain readable for the target audience.
    prefix = "请生成一张面向中文程序员的技术示意图。"
    suffix = f"。{CHINESE_IMAGE_CONSTRAINT}"
    max_chars = settings.image_generation_max_prompt_chars
    available = max(0, max_chars - len(prefix) - len(suffix))
    value = value[:available].rstrip("，。 ")
    return f"{prefix}{value}{suffix}"[:max_chars]


def apply_visualization_policy(question: Question, enabled: bool) -> Question:
    data = question.model_dump()
    visualization = data.get("visualization")
    if not enabled or not isinstance(visualization, dict) or not visualization.get("enabled"):
        data["visualization"] = None
        return Question.model_validate(data)
    fallback = (
        f"面向程序员面试学习的技术教育示意图，表现知识点“{question.knowledge_point}”的核心关系。"
        "画面简洁、专业、无品牌 Logo、无水印、不要大段文字。"
    )
    visualization["mode"] = "image"
    visualization["type"] = visualization.get("type") or "conceptual"
    visualization["image_prompt"] = sanitize_prompt(visualization.get("image_prompt", ""), fallback)
    visualization["alt_text"] = (visualization.get("alt_text") or f"{question.knowledge_point}示意图")[:200]
    visualization["asset_id"] = None
    visualization["image_url"] = None
    visualization["status"] = "pending"
    data["visualization"] = visualization
    return Question.model_validate(data)


def prepare_question_visualizations(questions: list[Question], enabled: bool) -> list[Question]:
    settings = get_settings()
    selected = 0
    result: list[Question] = []
    for question in questions:
        candidate = apply_visualization_policy(question, enabled)
        if candidate.visualization and selected < settings.image_generation_max_per_quiz:
            selected += 1
            result.append(candidate)
        else:
            data = question.model_dump()
            data["visualization"] = None
            result.append(Question.model_validate(data))
    return result
