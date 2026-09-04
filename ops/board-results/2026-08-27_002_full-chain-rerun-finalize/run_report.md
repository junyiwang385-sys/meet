# 运行聚合报告 · mtg_9c6133819814365e

- 版本：harness 2.0.0 / summary product-summary.v25 / seg topic-segmentation.v2
- 音频时长：1941.0 s
- 配置：{"ctx": 16384, "predict": 3072, "max_tokens": 3072, "input_safety_tokens": 512, "input_chars_per_token": 1.3, "temperature": 0.0, "resume": false}

## 🚩 优化红旗
- 块摘要偏短：均 98.6 字 < 目标 120
- overview 偏短：243 字 < 目标 300
- 合并率低：8 块仅并到 8 章（continues_previous 合并偏保守）
- speaker 假边界多：5/8 块由换人开启（过切嫌疑）
- chars_per_token 需校准：实测 1.551 vs 配置 1.3（预算估算偏差）
- 空 schema 字段：key_points, decisions, open_questions, risks, keywords（未抽取）

## ⏱ 时延
- 状态 succeeded，总 440.573 s
- 各阶段：{"segmentation": 216.844, "batch_asr": 78.259, "transcript_prepare": 0.019, "llm_summary": 145.212, "compat_export": 0.025}

## ✂️ 分段（A 层）
- policy=deterministic_blocks_map_reduce  块 8 → 章 8
- 边界理由：{"start": 1, "speaker": 5, "cohesion": 5, "gap": 3}
- 换人开启的块：5
- 块字数：{"count": 8, "min": 818, "avg": 1190, "max": 1624}
- 块段数：{"count": 8, "min": 10, "avg": 20.8, "max": 36}
- seg 配置：{"vad_gap_ms": 1500, "cohesion_window_segments": 3, "cohesion_depth_threshold": 0.3, "depth_window_segments": 4, "speaker_weight": 0.25, "cohesion_weight": 1.0, "boundary_score_threshold": 1.0, "min_block_chars": 400, "target_block_tokens": 1800}

## 📝 块摘要（B 层）
- 块数 8，continues_previous 0
- 摘要字数：{"count": 8, "min": 64, "avg": 98.6, "max": 135}
- 重试的块：[]

## 🧵 归并与纪要（C 层）
- overview 来源 source_timeline，字数 243
- 章节摘要字数：{"count": 8, "min": 64, "avg": 98.6, "max": 135}
- 发言人 6，待办 2→1
- 空字段：['key_points', 'decisions', 'open_questions', 'risks', 'keywords']

## 💰 LLM 经济学
- 计数：{"request_count": 11, "transport_request_count": 11, "validation_failed_count": 0, "retry_count": 0, "split_count": 0, "reused_request_count": 0}
- token：prompt 37667 / completion 3513
- finish_reason：{"stop": 11}
- thinking/次：{"block-summary": {"count": 8, "min": 0, "avg": 0, "max": 0}, "action-review": {"count": 1, "min": 1129, "avg": 1129, "max": 1129}, "full-summary": {"count": 1, "min": 0, "avg": 0, "max": 0}, "speaker-batch": {"count": 1, "min": 0, "avg": 0, "max": 0}}
- chars_per_token：实测 1.551 vs 配置 1.3

## ✅ 质量
- pass，warnings=[]
