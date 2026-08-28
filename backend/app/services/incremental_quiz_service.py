from __future__ import annotations

import asyncio
import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any, Protocol
from uuid import uuid4

from app.core.errors import DomainError, LLMGenerationError, TopicNotSupportedError
from app.models.generation import (
    QuizGenerationTaskCreateRequest,
    QuizGenerationTaskProgressRequest,
    QuizGenerationTaskSnapshot,
)
from app.models.progress import ProgressSaveRequest
from app.models.report import AnswerRecord
from app.models.quiz import Question, Quiz, QuizGenerateRequest
from app.repositories import generation_repository, knowledge_repository, visual_asset_repository
from app.repositories.progress_repository import create_progress, update_progress
from app.repositories.user_repository import save_quiz
from app.services.topic_service import validate_topic_scope
from app.services.question_types import target_question_type, validate_question_target_type
from app.core.config import get_settings
from app.services.visual_asset_service import VisualAssetService

logger = logging.getLogger(__name__)


async def _get_task(connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.get_task(connection, task_id, user_id)
    return await generation_repository.get_task(connection, task_id, user_id, guest_token_hash)


async def _claim_task(connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.claim_task(connection, task_id, user_id)
    return await generation_repository.claim_task(connection, task_id, user_id, guest_token_hash)


async def _append_question(connection: Any, task_id: str, user_id: int | None, question: dict, version: int, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.append_question(connection, task_id, user_id, question, version)
    return await generation_repository.append_question(connection, task_id, user_id, question, version, guest_token_hash=guest_token_hash)


async def _mark_completed(connection: Any, task_id: str, user_id: int | None, quiz_id: str, quiz: dict, title: str, summary: str, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.mark_completed(connection, task_id, user_id, quiz_id, quiz, title, summary)
    return await generation_repository.mark_completed(connection, task_id, user_id, quiz_id, quiz, title, summary, guest_token_hash=guest_token_hash)


async def _save_progress(connection: Any, task_id: str, user_id: int | None, current_index: int, records: list[dict], version: int, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.save_progress(connection, task_id, user_id, current_index, records, version)
    return await generation_repository.save_progress(connection, task_id, user_id, current_index, records, version, guest_token_hash=guest_token_hash)


async def _retry_task(connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.retry_task(connection, task_id, user_id)
    return await generation_repository.retry_task(connection, task_id, user_id, guest_token_hash)


async def _mark_failed(connection: Any, task_id: str, user_id: int | None, message: str, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.mark_failed(connection, task_id, user_id, message)
    return await generation_repository.mark_failed(connection, task_id, user_id, message, guest_token_hash)


async def _create_task(connection: Any, task_id: str, user_id: int | None, request: dict, guest_token_hash: str | None):
    if guest_token_hash is None:
        return await generation_repository.create_task(connection, task_id, user_id, request)
    return await generation_repository.create_task(connection, task_id, user_id, request, guest_token_hash=guest_token_hash)


class IncrementalGenerator(Protocol):
    async def prepare_incremental(self, request: QuizGenerateRequest, user_id: int | None = None) -> dict: ...

    async def generate_incremental_question(
        self, request: QuizGenerateRequest, index: int, existing_stems: list[str], prepared: dict
    ) -> Question: ...

    def finalize_incremental(self, request: QuizGenerateRequest, questions: list[Question], prepared: dict, quiz_id: str) -> Quiz: ...


def _snapshot(row: dict[str, Any]) -> QuizGenerationTaskSnapshot:
    questions = [Question.model_validate(item) for item in row.get("questions", [])]
    answer_records = [AnswerRecord.model_validate(item) for item in row.get("answer_records", [])]
    quiz = Quiz.model_validate(row["quiz"]) if row.get("quiz") else None
    return QuizGenerationTaskSnapshot(
        task_id=row["task_id"],
        status=row["status"],
        generated_count=int(row.get("generated_count", len(questions))),
        total_count=int(row.get("total_count", 6)),
        version=int(row.get("version", 1)),
        progress_version=int(row.get("progress_version", 1)),
        current_index=int(row.get("current_index", 0)),
        questions=questions,
        answer_records=answer_records,
        title=row.get("title") or (quiz.title if quiz else ""),
        summary=row.get("summary") or (quiz.summary if quiz else ""),
        quiz=quiz,
        error_message=row.get("error_message"),
        retryable=row.get("status") == "failed",
        updated_at=row.get("updated_at", ""),
    )


class IncrementalQuizService:
    def __init__(self, generator: IncrementalGenerator, max_question_attempts: int | None = None, task_timeout: float | None = None, visual_assets: VisualAssetService | None = None):
        self.generator = generator
        settings = get_settings()
        self.max_question_attempts = max_question_attempts or settings.incremental_question_attempts
        self.task_timeout = task_timeout or settings.incremental_task_timeout_seconds
        self.visual_assets = visual_assets or VisualAssetService()

    async def validate_request(self, request: QuizGenerateRequest, user_id: int | None, connection: Any) -> None:
        validate_topic_scope(request.user_input)
        if not request.document_id:
            return
        if user_id is None:
            from app.core.errors import KnowledgeDocumentAccessError

            raise KnowledgeDocumentAccessError()
        if connection is None:
            from app.core.errors import KnowledgeDocumentNotReadyError

            raise KnowledgeDocumentNotReadyError("知识库服务暂时不可用，请稍后重试")
        document = await knowledge_repository.get_document(connection, user_id, request.document_id)
        if document is None:
            from app.core.errors import KnowledgeDocumentAccessError

            raise KnowledgeDocumentAccessError()
        if document.get("status") != "ready":
            from app.core.errors import KnowledgeDocumentNotReadyError

            raise KnowledgeDocumentNotReadyError()

    async def create(
        self,
        payload: QuizGenerationTaskCreateRequest,
        user_id: int | None,
        connection: Any,
        guest_token_hash: str | None = None,
    ) -> QuizGenerationTaskSnapshot:
        request = payload.to_quiz_request()
        await self.validate_request(request, user_id, connection)
        task_id = f"gen_{uuid4().hex}"
        row = await _create_task(connection, task_id, user_id, request.model_dump(), guest_token_hash)
        return _snapshot(row)

    async def run_task(self, pool: Any, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> None:
        if pool is None:
            return
        try:
            async with pool.acquire() as connection:
                row = await _get_task(connection, task_id, user_id, guest_token_hash)
                if row is None or row["status"] == "completed":
                    return
                # Only the executor that atomically claims the queued task may
                # generate questions. A concurrent scheduler must return; it
                # must not generate a second copy of the same quiz.
                if not await _claim_task(connection, task_id, user_id, guest_token_hash):
                    return
                request = QuizGenerateRequest.model_validate(row["request"])

            await asyncio.wait_for(self._generate_all(pool, task_id, user_id, request, guest_token_hash), timeout=self.task_timeout)
        except asyncio.TimeoutError:
            await self._mark_failed(pool, task_id, user_id, "题目生成超时，请重试", guest_token_hash)
        except DomainError as exc:
            await self._mark_failed(pool, task_id, user_id, exc.message, guest_token_hash)
        except Exception as exc:
            logger.exception("incremental_quiz_task_failed", extra={"task_id": task_id})
            await self._mark_failed(pool, task_id, user_id, str(exc) or "AI 生成失败，请重试", guest_token_hash)

    async def _generate_all(self, pool: Any, task_id: str, user_id: int | None, request: QuizGenerateRequest, guest_token_hash: str | None = None) -> None:
        prepare_started = time.perf_counter()
        prepared = await self.generator.prepare_incremental(request, user_id=user_id)
        logger.info(
            "incremental_prepare_completed task_id=%s elapsed_ms=%d",
            task_id,
            int((time.perf_counter() - prepare_started) * 1000),
        )
        if not prepared.get("supported", True):
            raise TopicNotSupportedError(prepared.get("message") or "当前主题不属于程序员技术面试内容")
        async with pool.acquire() as connection:
            row = await _get_task(connection, task_id, user_id, guest_token_hash)
        if row is None:
            return
        questions = [Question.model_validate(item) for item in row.get("questions", [])]
        for index in range(len(questions) + 1, 7):
            existing_stems = [question.stem for question in questions]
            prepared["existing_questions"] = [
                {
                    "stem": question.stem,
                    "knowledge_point": question.knowledge_point,
                    "type": question.type,
                    "answer_conclusion": question.explanation[:300],
                }
                for question in questions
            ]
            last_error: Exception | None = None
            question_started = time.perf_counter()
            prepared["rejection_reason"] = ""
            for attempt in range(1, self.max_question_attempts + 1):
                try:
                    question = await self.generator.generate_incremental_question(
                        request, index, existing_stems, prepared
                    )
                    validate_question_target_type(question, index)
                    diversity_error = self._question_diversity_error(question, questions)
                    if diversity_error:
                        prepared["rejection_reason"] = diversity_error
                        raise ValueError(diversity_error)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    logger.info(
                        "incremental_question_attempt task_id=%s question_index=%s attempt=%s error_type=%s error=%s",
                        task_id,
                        index,
                        attempt,
                        type(exc).__name__,
                        str(exc)[:240],
                    )
            if last_error is not None:
                logger.warning(
                    "incremental_question_failed task_id=%s question_index=%s attempts=%s error_type=%s error=%s",
                    task_id,
                    index,
                    self.max_question_attempts,
                    type(last_error).__name__,
                    str(last_error)[:300],
                    exc_info=True,
                )
                # A malformed single response must not strand an otherwise usable
                # incremental session. Keep the flow moving with a valid, clearly
                # marked fallback question; the next questions still use the LLM.
                question = self._fallback_question(request, index, existing_stems)
                validate_question_target_type(question, index)
                # A bad model response must never be allowed to introduce a
                # duplicate fallback. This is a final local invariant before
                # persisting the question.
                fallback_error = self._question_diversity_error(
                    question, questions, {"trusted_fallback_dimension": str(index)}
                )
                if fallback_error:
                    raise LLMGenerationError(f"降级题目质量校验失败：{fallback_error}")
            logger.info(
                "incremental_question_completed task_id=%s question_index=%s elapsed_ms=%d fallback=%s",
                task_id,
                index,
                int((time.perf_counter() - question_started) * 1000),
                last_error is not None,
            )
            async with pool.acquire() as connection:
                current = await _get_task(connection, task_id, user_id, guest_token_hash)
                if current is None:
                    return
                updated = await _append_question(
                    connection,
                    task_id,
                    user_id,
                    question.model_dump(),
                    int(current["version"]),
                    guest_token_hash,
                )
                if updated is None:
                    raise LLMGenerationError("生成任务版本冲突，请重试")
                questions = [Question.model_validate(item) for item in updated["questions"]]
                if index == 1:
                    logger.info(
                        "incremental_first_question_released task_id=%s latency_ms=%d source=%s",
                        task_id,
                        int((time.perf_counter() - prepare_started) * 1000),
                        ",".join(str(item) for item in prepared.get("evidence_meta", {}).get("source_types", [])),
                    )
                if request.generate_images:
                    await self.visual_assets.schedule(
                        pool,
                        questions[-1],
                        task_id=task_id,
                        quiz_id=None,
                        user_id=user_id,
                        guest_token_hash=guest_token_hash,
                    )

        quiz_id = f"quiz_{uuid4().hex[:12]}"
        quiz = self.generator.finalize_incremental(request, questions, prepared, quiz_id)
        async with pool.acquire() as connection:
            current = await _get_task(connection, task_id, user_id, guest_token_hash)
            if current is None:
                return
            if user_id is not None:
                await save_quiz(connection, user_id, request.user_input, quiz)
                progress = await create_progress(connection, user_id, quiz)
                records = current.get("answer_records", [])
                if records:
                    progress_request = ProgressSaveRequest(
                        current_index=int(current.get("current_index", 0)),
                        answer_records=records,
                        version=int(progress["version"]),
                    )
                    status = "ready_for_report" if len(records) >= len(quiz.questions) else "in_progress"
                    await update_progress(
                        connection,
                        user_id,
                        quiz.quiz_id,
                        progress_request,
                        status,
                        len(records),
                    )
            await _mark_completed(
                connection,
                task_id,
                user_id,
                quiz.quiz_id,
                quiz.model_dump(),
                quiz.title,
                quiz.summary,
                guest_token_hash,
            )
            if request.generate_images:
                await visual_asset_repository.bind_task_assets(connection, task_id, quiz.quiz_id)
                await visual_asset_repository.sync_task_asset_snapshots(connection, task_id, quiz.quiz_id)
            if guest_token_hash:
                await generation_repository.release_guest_task(connection, guest_token_hash)

    @staticmethod
    def _normalize_compare(value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").lower())

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        a = cls._normalize_compare(left)
        b = cls._normalize_compare(right)
        if not a or not b:
            return 0.0
        sequence = SequenceMatcher(None, a, b).ratio()
        if len(a) < 8 or len(b) < 8:
            return sequence
        def shingles(value: str) -> set[str]:
            return {value[i:i + 2] for i in range(len(value) - 1)}
        sa, sb = shingles(a), shingles(b)
        jaccard = len(sa & sb) / max(len(sa | sb), 1)
        return max(sequence, jaccard)

    @classmethod
    def _question_diversity_error(
        cls,
        question: Question,
        existing: list[Question],
        _legacy_context: dict[str, str] | None = None,
    ) -> str | None:
        normalized_stem = cls._normalize_compare(question.stem)
        if any(normalized_stem == cls._normalize_compare(item.stem) for item in existing):
            return "模型生成了重复题目"
        point = cls._normalize_compare(question.knowledge_point)
        for item in existing:
            existing_point = cls._normalize_compare(item.knowledge_point)
            if point and existing_point and point == existing_point:
                return "模型重复考察了同一知识点"
            # Semantic stem similarity is meaningful when the model also
            # assigned the same (or nearly the same) knowledge point. This
            # avoids rejecting legitimate questions that share a short topic
            # prefix while still catching paraphrased duplicates.
            if cls._similarity(question.stem, item.stem) >= 0.72 and (
                not point or not existing_point or cls._similarity(point, existing_point) >= 0.9
            ):
                return "模型生成了语义高度相似的题目"
            stem_similarity = cls._similarity(question.stem, item.stem)
            explanation_similarity = cls._similarity(question.explanation, item.explanation)
            point_similarity = cls._similarity(point, existing_point) if point and existing_point else 0.0
            if (
                _legacy_context is None
                and min(len(point), len(existing_point)) >= 8
                and stem_similarity >= 0.90
            ):
                return "模型生成了语义高度相似的题目"
            # Models often vary the scenario while repeating the same learning
            # objective. Ignore short fixture-like labels, but reject specific
            # long knowledge points that are merely paraphrased.
            if _legacy_context is None and min(len(point), len(existing_point)) >= 8 and point_similarity >= 0.70:
                return "模型重复考察了相近的知识结论"
            if (
                _legacy_context is None
                and
                min(len(point), len(existing_point)) >= 8
                and stem_similarity >= 0.45
                and explanation_similarity >= 0.55
            ):
                return "模型重复考察了相近的知识结论"
        return None

    @staticmethod
    def _fallback_question(
        request: QuizGenerateRequest,
        index: int,
        existing_stems: list[str],
        _legacy_context: dict[str, str] | None = None,
    ) -> Question:
        """Return a valid topic-specific question when an LLM response is unusable."""
        topic = request.user_input.strip()[:100]
        normalized_topic = topic.replace(" ", "").lower()
        target_type = target_question_type(index)
        # If an individual LLM call times out, keep the fallback specific to
        # the requested technology. A generic "目标、边界、验证方式" question
        # is not useful for a focused subject such as Redis persistence.
        if "redis" in normalized_topic and any(term in normalized_topic for term in ("持久化", "rdb", "aof")):
            redis_templates = {
                1: ("Redis 持久化的核心目标是什么？", "通过 RDB 或 AOF 将内存状态恢复所需的数据写入磁盘，降低进程重启后的数据丢失风险。", [
                    ("A", "将内存数据以 RDB 快照或 AOF 日志形式持久化"), ("B", "只把热点 key 保存在客户端"), ("C", "关闭 Redis 的内存淘汰机制"), ("D", "把所有请求同步写入业务数据库")], ["A"]),
                2: ("关于 Redis RDB 快照，下列说法正确的是？", "RDB 是某个时刻的二进制快照，生成间隔内尚未写入快照的数据在进程异常退出时可能丢失。", [
                    ("A", "RDB 记录某一时刻的数据快照"), ("B", "RDB 会记录每一条写命令"), ("C", "RDB 能保证零数据丢失"), ("D", "RDB 只能在从节点生成")], ["A"]),
                3: ("Redis AOF 持久化相比 RDB 的主要特点是什么？", "AOF 追加记录写命令，通常提供更小的丢失窗口，但文件可能更大，需要重写压缩。", [
                    ("A", "追加记录写命令，恢复粒度通常更细"), ("B", "只保存定时快照"), ("C", "完全不需要磁盘"), ("D", "无法执行重写")], ["A"]),
                4: ("Redis AOF 重写过程中，为什么仍能接收新的写请求？", "AOF 重写在后台生成精简文件，重写期间的新写命令会进入重写缓冲区；重写完成后再合并缓冲区并原子切换文件。", [
                    ("A", "新命令先写入重写缓冲区，完成后合并切换"), ("B", "重写期间停止所有写请求"), ("C", "只重新生成 RDB 快照"), ("D", "删除旧 AOF 后再处理新命令")], ["A"]),
                5: ("Redis 主从复制为什么不能替代 RDB 或 AOF 持久化？（可多选）", "主从复制默认是异步的，主节点故障时从节点可能尚未收到最近写入；持久化还能支持进程重启后的磁盘恢复，两者解决的是不同层面的恢复与容灾问题。", [
                    ("A", "异步复制存在尚未同步的写入窗口"), ("B", "持久化可从磁盘恢复，而复制主要提供副本容灾"), ("C", "从节点永远比主节点新"), ("D", "复制会阻止主节点宕机")], ["A", "B"]),
                6: ("Redis 执行 RDB 快照时，fork 和 copy-on-write 会带来什么影响？", "RDB 通常通过 fork 子进程生成快照；父子进程共享页面，写入发生时触发 copy-on-write，内存峰值和 fork 开销会影响大实例性能。", [
                    ("A", "写入会触发 copy-on-write 并增加内存与 CPU 开销"), ("B", "快照完全不占用额外内存"), ("C", "fork 会把 AOF 转成网络请求"), ("D", "RDB 只能在从节点生成")], ["A"]),
            }
            stem, explanation, raw_options, answer = redis_templates.get(index, redis_templates[1])
            if target_type == "judge":
                stem = f"判断以下说法是否正确：{raw_options[0][1]}。"
                raw_options = [("A", "正确"), ("B", "错误")]
                answer = ["A"]
            return Question(
                id=f"fallback-q{index}", type=target_type, stem=stem,
                options=[{"key": key, "text": text} for key, text in raw_options], answer=answer,
                explanation=explanation,
                option_explanations={key: ("符合 Redis 持久化机制。" if key in answer else "与题目考察的持久化机制不符。") for key, _ in raw_options},
                knowledge_point=f"Redis 持久化·{index}",
                misconception="不要把 RDB 快照、AOF 写命令日志和主从复制混为同一种持久化机制。",
                difficulty=request.difficulty, version_context="Redis 6.x/7.x 通用",
            )
        if "mysql" in normalized_topic and any(term in normalized_topic for term in ("mvcc", "explain", "慢查询", "索引")):
            mysql_templates = {
                1: ("MySQL InnoDB 的 MVCC 为什么能让可重复读看到稳定快照？", "普通一致性读通过 Read View 选择可见的 undo log 旧版本；同一事务在 REPEATABLE READ 下复用快照，因此多次读取结果保持稳定。", [("A", "通过 Read View 和 undo log 选择可见版本"), ("B", "所有 SELECT 都强制加排他锁"), ("C", "只依赖二级索引缓存"), ("D", "每次查询都读取最新提交版本")], ["A"]),
                2: ("MySQL 的 SELECT ... FOR UPDATE 与普通快照读有什么关键区别？", "FOR UPDATE 属于当前读，会读取最新版本并对命中的记录加锁；普通 SELECT 通常是快照读，按 Read View 判断可见版本。", [("A", "锁定读是当前读并会加锁"), ("B", "两者都永远读取事务第一次快照"), ("C", "快照读一定阻塞其他事务"), ("D", "FOR UPDATE 只读取二级索引")], ["A"]),
                3: ("使用 EXPLAIN 排查 MySQL 慢查询时，哪组信息最值得优先关注？", "应结合访问类型、实际 key、rows、filtered 和 Extra 判断扫描范围、索引使用、临时表及额外排序，并结合实际执行数据验证估算。", [("A", "type、key、rows、filtered 和 Extra"), ("B", "只看 SQL 字符数"), ("C", "只看表名不看执行计划"), ("D", "只提高连接池大小")], ["A"]),
                4: ("MySQL EXPLAIN 估算 rows 明显大于实际返回行数时，应如何处理？", "先检查统计信息和数据分布，必要时更新统计信息并比较执行计划；不能只凭估算值盲目增加索引。", [("A", "核对统计信息、数据分布并复测执行计划"), ("B", "删除所有现有索引"), ("C", "把事务隔离级别改成最低"), ("D", "关闭慢查询日志")], ["A"]),
                5: ("在 InnoDB REPEATABLE READ 下，范围 SELECT ... FOR UPDATE 可能阻塞并发插入的原因有哪些？（可多选）", "当前读会加记录锁和必要的 gap/next-key 锁，既锁定已有记录，也保护查询范围内的间隙，从而可能阻塞满足条件范围的新插入。", [("A", "锁定读会对已有记录加记录锁"), ("B", "必要时使用 gap/next-key 锁保护查询范围"), ("C", "EXPLAIN 会锁住所有表"), ("D", "undo log 禁止任何新事务")], ["A", "B"]),
                6: ("MySQL 慢查询优化为什么不能只依赖 EXPLAIN 的 rows 估算？", "rows 是优化器估算值，还要结合 EXPLAIN ANALYZE、慢日志、锁等待、I/O 和数据分布验证真实耗时与瓶颈。", [("A", "结合 EXPLAIN ANALYZE 和运行时证据验证"), ("B", "看到 rows 大就必然是全表扫描"), ("C", "只调整客户端超时"), ("D", "只增加 SQL 注释")], ["A"]),
            }
            stem, explanation, raw_options, answer = mysql_templates.get(index, mysql_templates[1])
            if target_type == "judge":
                stem = f"判断以下说法是否正确：{raw_options[0][1]}。"
                raw_options = [("A", "正确"), ("B", "错误")]
                answer = ["A"]
            return Question(
                id=f"fallback-q{index}", type=target_type, stem=stem,
                options=[{"key": key, "text": text} for key, text in raw_options], answer=answer,
                explanation=explanation,
                option_explanations={key: ("符合 MySQL InnoDB 或 EXPLAIN 的工程语义。" if key in answer else "与本题考察的机制不符。") for key, _ in raw_options},
                knowledge_point=f"MySQL {('MVCC' if index in (1, 2, 5) else 'EXPLAIN')}·{index}",
                misconception="不要把快照读、当前读、锁机制和执行计划估算混为一谈。",
                difficulty=request.difficulty, version_context="MySQL 8.0 InnoDB",
            )
        dimensions = [
            ("核心概念", "解释定义、边界和关键术语"),
            ("工作原理", "说明主要流程、组件或数据流"),
            ("适用场景", "判断何时使用以及何时不应使用"),
            ("工程实现", "考察落地实现和关键设计细节"),
            ("性能与可靠性", "分析性能、扩展性、稳定性或安全取舍"),
            ("故障排查", "通过实际问题考察诊断和解决思路"),
        ]
        dimension, objective = dimensions[min(max(index - 1, 0), len(dimensions) - 1)]
        point = f"{topic}·{dimension}"[:100]
        question_type = target_type
        stem_templates = {
            1: f"关于 {topic} 的核心定义与边界，以下哪项表述最准确？",
            2: f"在理解 {topic} 的工作原理时，以下哪条数据流或处理顺序是正确的？",
            3: f"在选择 {topic} 的使用场景时，以下哪种判断最合理？",
            4: f"落地实现 {topic} 时，以下哪项工程做法最值得优先采用？",
            5: f"针对 {topic} 的性能与可靠性权衡，以下哪项方案更稳妥？",
            6: f"线上 {topic} 出现异常时，以下哪种排查顺序最有效？",
        }
        stem = stem_templates.get(index, f"围绕 {topic} 的{dimension}，以下哪项判断最合理？")
        # Keep the fallback deterministic but make every learning dimension
        # materially different, so an upstream outage cannot create six copies
        # of one generic question.
        if any(IncrementalQuizService._similarity(stem, old) >= 0.72 for old in existing_stems):
            stem = f"{topic} 的{dimension}面试题：请说明你的判断依据和关键取舍。"
        if question_type == "multiple":
            options = [
                {"key": "A", "text": f"围绕{dimension}建立可验证的判断标准"},
                {"key": "B", "text": "结合实际约束验证方案，而不是只背结论"},
                {"key": "C", "text": "忽略边界条件，只选择最复杂的实现"},
                {"key": "D", "text": "跳过证据收集，直接修改线上配置"},
            ]
            answer = ["A", "B"]
        elif question_type == "judge":
            stem = (
                f"判断以下说法是否正确：排查 {topic} 的线上异常时，应先收集可复现证据和日志，"
                "再根据证据定位根因并验证修复结果。"
            )
            options = [
                {"key": "A", "text": "正确"},
                {"key": "B", "text": "错误"},
            ]
            answer = ["A"]
        else:
            options = [
                {"key": "A", "text": f"先明确{dimension}的目标、边界和验证方式"},
                {"key": "B", "text": "不分析上下文，直接复制一段看似可用的代码"},
                {"key": "C", "text": "只关注结果，不考虑性能、风险和维护成本"},
                {"key": "D", "text": "遇到异常时忽略日志和可复现证据"},
            ]
            answer = ["A"]
        return Question(
            id=f"fallback-q{index}",
            type=question_type,
            stem=stem,
            options=options,
            answer=answer,
            explanation=(
                f"本题聚焦{dimension}（{objective}）。回答 {topic} 时，应先说明判断依据、适用边界和取舍，再结合场景验证。"
            ),
            option_explanations={
                **{option["key"]: ("符合工程化判断原则。" if option["key"] in answer else "忽略了必要的边界或证据。") for option in options},
            },
            knowledge_point=point,
            misconception=f"不要把{dimension}简化成脱离场景的记忆结论。",
            difficulty=request.difficulty,
            version_context="fallback-question-v2",
        )

    async def snapshot(self, connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> QuizGenerationTaskSnapshot | None:
        row = await _get_task(connection, task_id, user_id, guest_token_hash)
        return _snapshot(row) if row else None

    async def save_progress(
        self,
        connection: Any,
        task_id: str,
        user_id: int | None,
        payload: QuizGenerationTaskProgressRequest,
        guest_token_hash: str | None = None,
    ) -> QuizGenerationTaskSnapshot | None:
        row = await _save_progress(
            connection,
            task_id,
            user_id,
            payload.current_index,
            [record.model_dump() for record in payload.answer_records],
            payload.progress_version,
            guest_token_hash,
        )
        return _snapshot(row) if row else None

    async def retry(self, connection: Any, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> QuizGenerationTaskSnapshot | None:
        row = await _retry_task(connection, task_id, user_id, guest_token_hash)
        return _snapshot(row) if row else None

    async def _mark_failed(self, pool: Any, task_id: str, user_id: int | None, message: str, guest_token_hash: str | None = None) -> None:
        try:
            async with pool.acquire() as connection:
                await _mark_failed(connection, task_id, user_id, message, guest_token_hash)
                if guest_token_hash:
                    await generation_repository.release_guest_task(connection, guest_token_hash)
        except Exception:
            logger.exception("incremental_quiz_task_failure_persist_failed", extra={"task_id": task_id})
