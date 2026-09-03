"""Board-oriented full-context and sliding-chapter meeting summarization."""

from __future__ import annotations

import json
import pathlib
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..storage.artifacts import atomic_write_json, atomic_write_text, load_json, sha256_file
from ..llm.chunking import (
    BudgetPolicy,
    ChunkingError,
    estimate_message_tokens,
    messages_fit,
    stable_hash,
)
from ..llm.llm import LlmConfig, LlmRunError, RkllmServerSession, SYSTEM_PROMPT
from .transcript import render_timeline
from .topic_segmentation import SegmentationConfig, segment_blocks
from .summary_profiles import DomainProfile, GENERIC_PROFILE
from .validation import (
    SummaryValidationError,
    clean_text,
    parse_content,
    validate_summary_object,
)
from ._requests import (
    _RequestRunner,
    PRODUCT_SUMMARY_VERSION,
    _KIND_OUTPUT_TOKENS,
    _THINK_KINDS,
    _apply_think_directive,
    _emit_run_log,
    _kind_output_tokens,
    _kind_uses_think,
    _load_reusable_request,
    _model_identity,
    _request_fingerprint,
    _request_record,
    _save_reusable_request,
)
from ._validate import (
    MIN_OVERVIEW_CHARS,
    _clean_bullet_list,
    _empty_long_summary,
    _expand_core_chapter_ranges,
    _normalize_overlapping_core_candidates,
    _reduce_blocks_to_chapters,
    _summaries_too_similar,
    _validate_actions,
    _validate_block_summary,
    _validate_full_core_result,
    _validate_overview,
    _validate_speaker_batch,
)
from ._speakers import (
    SPEAKER_MIN_CHARS,
    _build_speaker_documents,
    _pack_speaker_documents,
    _truncate_speaker_document_to_budget,
    _truncate_speaker_documents,
)
from ._prompts import (
    ACTION_REVIEW_SHAPE,
    BLOCK_SUMMARY_SHAPE,
    FULL_MEETING_SHAPE,
    FULL_SUMMARY_SHAPE,
    MAX_RETRY_ECHO_CHARS,
    SPEAKER_BATCH_SHAPE,
    _action_review_messages,
    _block_summary_messages,
    _build_retry_messages,
    _full_meeting_messages,
    _full_summary_messages,
    _overview_from_source_messages,
    _prompt_time,
    _render_compact_timeline,
    _speaker_batch_messages,
)
from ._refmap import (
    _build_compact_ref_map,
    _build_compact_ref_map_from_ids,
    _build_compact_speaker_map,
    _compact_ref_name,
    _compactize_payload,
    _expand_payload,
)


# D 层长度门（软约束，触发一次受控重试而不是硬失败）
MIN_BLOCK_SUMMARY_CHARS = 60

# 按 request_kind 决定是否开 think 与输出预留（4B int4）。
# 抽取/压缩类关 think：省紧张的输出预算、避免 thinking 吃掉答案导致 JSON 截断。
# 判断类（action-review，将来的专名纠错）开 think：需要权衡的推理收益最高。
@dataclass(frozen=True)
class ProductSummaryConfig:
    llm: LlmConfig
    safety_tokens: int
    chars_per_token: float
    fixed_overhead_tokens: int
    resume: bool
    # 领域画像（域相关的"抽取什么"）；默认通用版，将来由会议类型识别选出。
    profile: DomainProfile = GENERIC_PROFILE

    @property
    def budget(self) -> BudgetPolicy:
        return BudgetPolicy(
            ctx=self.llm.ctx,
            output_tokens=self.llm.max_tokens,
            safety_tokens=self.safety_tokens,
            chars_per_token=self.chars_per_token,
            fixed_overhead_tokens=self.fixed_overhead_tokens,
            overlap_segments=0,
        )




def run_product_summary_stage(
    *,
    config: ProductSummaryConfig,
    segments: list[dict[str, Any]],
    speaker_ids: list[str],
    timeline: str,
    out_dir: pathlib.Path,
    sampler: Any | None,
    run_log: Any | None = None,
    session: RkllmServerSession | None = None,
) -> dict[str, Any]:
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = config.budget
    ref_map, compact_ref_map = _build_compact_ref_map(segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments] or speaker_ids
    )
    nonempty = [segment for segment in segments if segment.get("text")]
    # A 层：先做确定性话题分割，块数决定走单请求快路径还是分块 map-reduce
    segmentation = segment_blocks(nonempty, budget, SegmentationConfig())
    blocks = segmentation["blocks"]
    full_messages = _full_meeting_messages(
        timeline,
        speaker_ids,
        ref_map=ref_map,
        speaker_map=speaker_map,
    )
    full_estimate = estimate_message_tokens(full_messages, budget)
    # single_request 已降级为"仅单块极短会"的快路径；多块一律走分块 map-reduce。
    use_single_request = len(blocks) <= 1 and messages_fit(full_messages, budget)
    plan: dict[str, Any] = {
        "version": PRODUCT_SUMMARY_VERSION,
        "input_token_budget": budget.input_token_budget,
        "full_estimated_prompt_tokens": full_estimate,
        "full_request_fits": messages_fit(full_messages, budget),
        "block_count": len(blocks),
        "use_single_request": use_single_request,
    }
    # 保留每次传输和业务校验尝试；request_records 继续只表示最终通过校验的请求，
    # 以兼容现有 meeting_result.runtime.llm 契约。
    split_count = 0
    # session 可由调用方注入（pipeline 持有、跨 stage 复用同一活着的 server）；
    # 注入时本 stage 不负责 close（谁开谁关），未注入则维持"自己开自己关"。
    owns_session = session is None
    cached_files: dict[str, Any] | None = session.files if session is not None else None

    def build_session() -> RkllmServerSession:
        nonlocal session, cached_files
        if session is None:
            session = RkllmServerSession(config.llm, out_dir, sampler)
            cached_files = session.files
        return session

    def model_identity() -> dict[str, Any]:
        return _model_identity(build_session().files)

    def ensure_session() -> RkllmServerSession:
        current = build_session()
        current.start()
        return current

    runner = _RequestRunner(
        config=config,
        run_log=run_log,
        ensure_session=ensure_session,
        model_identity=model_identity,
    )

    def result_payload(
        summary: dict[str, Any],
        quality: dict[str, Any],
        policy: str,
    ) -> dict[str, Any]:
        return {
            "summary": summary,
            "quality": quality,
            "policy": policy,
            "request_count": session.request_count if session is not None else 0,
            "transport_request_count": session.transport_request_count if session is not None else 0,
            "http_response_count": session.http_response_count if session is not None else 0,
            "response_parse_success_count": session.response_parse_success_count if session is not None else 0,
            "successful_response_count": session.successful_response_count if session is not None else 0,
            "validated_request_count": len(runner.request_records),
            "validation_failed_count": runner.validation_failed_count,
            "retry_count": runner.retry_count,
            "split_count": split_count,
            "reused_request_count": runner.reused_count,
            "requests": runner.request_records,
            "request_attempts": runner.request_attempts,
            "server_ready_seconds": session.ready_seconds if session is not None else None,
            "resolved_model_files": cached_files,
            "elapsed_seconds": round(time.time() - started, 3),
            "plan": plan,
        }

    try:
        if use_single_request:
            def validate_full(content: str, finish_reason: Any, truncated: bool) -> dict[str, Any]:
                summary, _ = _validate_full_core_result(
                    content,
                    finish_reason,
                    truncated,
                    segments,
                )
                return summary

            summary = runner.run(
                messages=full_messages,
                request_dir=out_dir / "requests" / "full",
                request_id="full",
                request_kind="full",
                phase="llm_summary_full",
                estimate=full_estimate,
                validator=validate_full,
                quality_builder=lambda value: validate_summary_object(value, segments)[1],
            )
            summary, quality = validate_summary_object(summary, segments)
            quality["checks"].update({"finish_reason": True, "context_not_truncated": True})
            if runner.reused_count:
                quality["warnings"].append("reused validated LLM artifact")
            plan["policy"] = "single_request_all_features"
            atomic_write_json(out_dir / "plan.json", plan)
            return result_payload(summary, quality, plan["policy"])

        # A 层切块已在入口算好（segmentation / blocks），这里落盘并建索引。
        atomic_write_json(out_dir / "segmentation.json", segmentation)
        segment_by_id = {segment["segment_id"]: segment for segment in nonempty}

        # B 层：逐块摘要（map），一次调用一块，附上一块上下文判定是否延续同一话题
        block_results: list[dict[str, Any]] = []
        prev_context: dict[str, str] | None = None
        for block in blocks:
            block_id = block["block_id"]
            block_segments = [segment_by_id[seg_id] for seg_id in block["segment_ids"]]
            messages = _block_summary_messages(
                block_segments, prev_context, ref_map=ref_map, speaker_map=speaker_map,
                profile=config.profile,
            )
            estimate = estimate_message_tokens(messages, budget)
            request_dir = out_dir / "blocks" / block_id
            atomic_write_text(request_dir / "timeline.txt", render_timeline(block_segments))

            def validate_block_request(
                content: str,
                finish_reason: Any,
                truncated: bool,
                current_segments: list[dict[str, Any]] = block_segments,
            ) -> dict[str, Any]:
                return _validate_block_summary(
                    content,
                    finish_reason,
                    truncated,
                    current_segments,
                    ref_map=ref_map,
                    speaker_map=speaker_map,
                    profile=config.profile,
                )

            block_result = runner.run(
                messages=messages,
                request_dir=request_dir,
                request_id=block_id,
                request_kind="block-summary",
                phase="llm_block_summary",
                estimate=estimate,
                validator=validate_block_request,
            )
            block_result = {**block_result, "block_id": block_id, "segment_ids": block["segment_ids"]}
            atomic_write_json(request_dir / "validated_block.json", block_result)
            block_results.append(block_result)
            prev_context = {"title": block_result["title"], "summary": block_result["summary"]}

        # 合并（reduce over boundaries）：相邻块 continues_previous 的并成一章，把 A 层过切收回来
        chapters, action_candidates = _reduce_blocks_to_chapters(block_results, segment_by_id)
        atomic_write_json(out_dir / "chapters.json", chapters)
        atomic_write_json(out_dir / "action_candidates.json", action_candidates)

        # 章节质量门：合并后仍过短的章节标记为弱章，不静默平均进 overview（供人工核对）
        weak_chapters = [
            {
                "title": chapter["title"],
                "start_ref": chapter["start_ref"],
                "end_ref": chapter["end_ref"],
                "overview_chars": len(chapter["overview"]),
            }
            for chapter in chapters
            if len(chapter["overview"]) < MIN_BLOCK_SUMMARY_CHARS
        ]

        overview_refs = list(dict.fromkeys(
            str(ref)
            for chapter in chapters
            for ref in chapter.get("refs", [])
            if str(ref) in segment_by_id
        ))
        # 自适应 overview 来源：用 overview 自己的输出预留（比"全都要"的账小）判定原文放不放得下，
        # 尽量多留在原文接地版；放不下才退化为章节摘要 reduce。
        overview_output = _kind_output_tokens("full-summary", config)
        overview_budget = BudgetPolicy(
            ctx=budget.ctx,
            output_tokens=overview_output,
            safety_tokens=budget.safety_tokens,
            chars_per_token=budget.chars_per_token,
            fixed_overhead_tokens=budget.fixed_overhead_tokens,
            overlap_segments=0,
        )
        overview_messages = _overview_from_source_messages(
            timeline, chapters, ref_map=ref_map, speaker_map=speaker_map
        )
        if messages_fit(overview_messages, overview_budget):
            summary_messages = overview_messages
            overview_source = "source_timeline"
        else:
            summary_messages = _full_summary_messages(
                chapters, ref_map=ref_map, speaker_map=speaker_map
            )
            overview_source = "chapter_summaries"
        summary_estimate = estimate_message_tokens(summary_messages, overview_budget)
        if summary_estimate > overview_budget.input_token_budget:
            # TODO(层级归并)：章节过多致此处超预算时，应做树状多级 reduce（每 5~8 章一组，多级合并），
            # 而非硬失败。当前长会章节爆预算会在此 raise，属已知健壮性缺口。
            raise ChunkingError("validated chapters exceed full-summary input budget")
        plan["overview_source"] = overview_source
        plan["overview_estimated_prompt_tokens"] = summary_estimate

        def validate_overview_request(
            content: str,
            finish_reason: Any,
            truncated: bool,
        ) -> dict[str, Any]:
            title, overview = _validate_overview(
                content,
                finish_reason,
                truncated,
                segment_by_id,
                overview_refs,
            )
            return {"title": title, "overview": overview}

        overview_result = runner.run(
            messages=summary_messages,
            request_dir=out_dir / "requests" / "full_summary",
            request_id="full-summary",
            request_kind="full-summary",
            phase="llm_full_summary",
            estimate=summary_estimate,
            validator=validate_overview_request,
        )
        title = overview_result["title"]
        overview = overview_result["overview"]

        action_items = []
        if action_candidates:
            action_messages = _action_review_messages(action_candidates, segment_by_id, ref_map=ref_map, speaker_map=speaker_map)
            action_estimate = estimate_message_tokens(action_messages, budget)
            if action_estimate > budget.input_token_budget:
                raise ChunkingError("action candidates exceed action-review input budget")
            action_items = runner.run(
                messages=action_messages,
                request_dir=out_dir / "requests" / "action_review",
                request_id="action-review",
                request_kind="action-review",
                phase="llm_action_review",
                estimate=action_estimate,
                validator=lambda content, finish_reason, truncated: _validate_actions(
                    content,
                    finish_reason,
                    truncated,
                    segments,
                ),
            )

        speaker_documents = _build_speaker_documents(nonempty)
        speaker_documents, speaker_truncations = _truncate_speaker_documents(
            speaker_documents,
            budget,
            ref_map=ref_map,
            speaker_map=speaker_map,
        )
        speaker_batches = _pack_speaker_documents(speaker_documents, budget, ref_map=ref_map, speaker_map=speaker_map)
        speaker_summaries = []
        speaker_batch_records = []
        speaker_order = {
            document["speaker_id"]: document["first_index"]
            for document in speaker_documents
        }
        def run_speaker_batch(
            batch: list[dict[str, Any]],
            request_id: str,
            request_dir: pathlib.Path,
            split_depth: int = 0,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            """Retry a truncated batch, then split it while keeping IDs stable."""
            nonlocal split_count

            speaker_messages = _speaker_batch_messages(
                batch,
                ref_map=ref_map,
                speaker_map=speaker_map,
            )
            speaker_estimate = estimate_message_tokens(speaker_messages, budget)
            try:
                batch_result = runner.run(
                    messages=speaker_messages,
                    request_dir=request_dir,
                    request_id=request_id,
                    request_kind="speaker-batch",
                    phase="llm_speaker_batch",
                    estimate=speaker_estimate,
                    validator=lambda content, finish_reason, truncated, current_batch=batch: _validate_speaker_batch(
                        content,
                        finish_reason,
                        truncated,
                        current_batch,
                        ref_map=ref_map,
                        speaker_map=speaker_map,
                    ),
                )
                return batch_result, [{
                    "request_id": request_id,
                    "speaker_ids": [document["speaker_id"] for document in batch],
                    "segment_count": sum(len(document["segments"]) for document in batch),
                    "estimated_prompt_tokens": speaker_estimate,
                    "split_depth": split_depth,
                    "truncated_speaker_ids": [
                        document["speaker_id"]
                        for document in batch
                        if document.get("_truncation") is not None
                    ],
                }]
            except SummaryValidationError as exc:
                message = str(exc)
                can_split = (
                    "finish_reason" in message
                    and "length" in message
                    and len(batch) > 1
                    and split_depth < 3
                )
                if not can_split:
                    raise
                midpoint = max(1, len(batch) // 2)
                child_results: list[dict[str, Any]] = []
                child_records: list[dict[str, Any]] = []
                child_request_ids = [
                    f"{request_id}-split-1",
                    f"{request_id}-split-2",
                ]
                split_count += 1
                _emit_run_log(
                    run_log,
                    "batch_split",
                    stage="llm_speaker_batch",
                    message="speaker batch 将拆分后重试",
                    request={
                        "request_id": request_id,
                        "request_kind": "speaker-batch",
                        "split_depth": split_depth,
                        "finish_reason": "length",
                    },
                    details={
                        "parent_request_id": request_id,
                        "child_request_ids": child_request_ids,
                        "parent_batch_size": len(batch),
                        "child_batch_sizes": [len(batch[:midpoint]), len(batch[midpoint:])],
                    },
                )
                for child_index, child_batch in enumerate((batch[:midpoint], batch[midpoint:]), 1):
                    child_result, child_record = run_speaker_batch(
                        child_batch,
                        f"{request_id}-split-{child_index}",
                        request_dir.parent / f"{request_dir.name}-split-{child_index}",
                        split_depth + 1,
                    )
                    child_results.extend(child_result)
                    child_records.extend(child_record)
                return child_results, child_records

        for batch_index, batch in enumerate(speaker_batches, 1):
            batch_result, batch_records = run_speaker_batch(
                batch,
                f"speaker-batch-{batch_index:06d}",
                out_dir / "requests" / "speaker_batches" / f"speaker-batch-{batch_index:06d}",
            )
            speaker_summaries.extend(batch_result)
            speaker_batch_records.extend(batch_records)
        speaker_summaries.sort(
            key=lambda item: speaker_order.get(item["speaker_id"], len(speaker_order))
        )
        atomic_write_json(
            out_dir / "speaker_documents.json",
            [
                {
                    "speaker_id": document["speaker_id"],
                    "segment_ids": [segment["segment_id"] for segment in document["segments"]],
                    "segment_count": len(document["segments"]),
                    **(
                        {"truncation": document["_truncation"]}
                        if document.get("_truncation") is not None
                        else {}
                    ),
                }
                for document in speaker_documents
            ],
        )
        atomic_write_json(out_dir / "speaker_batches.json", speaker_batch_records)

        summary = _empty_long_summary()
        summary.update(
            {
                "title": title,
                "overview": overview,
                "chapters": chapters,
                "speakers": speaker_summaries,
                "action_items": action_items,
            }
        )
        summary, quality = validate_summary_object(summary, segments)
        quality["checks"].update(
            {
                "full_meeting_coverage": segmentation["coverage_complete"],
                "deterministic_blocks": True,
                "speaker_batches_processed": True,
                "overview_source": overview_source,
                "chapter_quality_gate": not weak_chapters,
            }
        )
        if weak_chapters:
            quality["warnings"].append(
                f"{len(weak_chapters)} chapter(s) below quality threshold "
                f"(<{MIN_BLOCK_SUMMARY_CHARS} chars); flagged for manual review"
            )
            quality["weak_chapters"] = weak_chapters
        if runner.reused_count:
            quality["warnings"].append("reused validated LLM artifacts")
        plan.update(
            {
                "policy": "deterministic_blocks_map_reduce",
                "block_count": len(blocks),
                "chapter_count": len(chapters),
                "overview_source": overview_source,
                "weak_chapter_count": len(weak_chapters),
                "segmentation": segmentation,
                "action_candidate_count": len(action_candidates),
                "speaker_count": len(speaker_documents),
                "speaker_batch_count": len(speaker_batch_records),
                "speaker_batches": speaker_batch_records,
                "speaker_truncations": speaker_truncations,
            }
        )
        atomic_write_json(out_dir / "plan.json", plan)
        atomic_write_json(out_dir / "chapters.json", chapters)
        atomic_write_json(out_dir / "full_summary.json", {"title": title, "overview": overview})
        atomic_write_json(out_dir / "action_items.json", action_items)
        return result_payload(summary, quality, plan["policy"])
    finally:
        if session is not None:
            session.validation_failed_count = runner.validation_failed_count
            session.retry_count = runner.retry_count
            session.split_count = split_count
            if owns_session:
                session.close()
