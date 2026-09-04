# 结果：enrichment 接入 + 板端 4B 实机验证（5 组随机会议）

- **task_id**：2026-09-02_003
- **目标 commit**：`feature/transcript-postprocess` HEAD
- **executed_at**：<填>
- **板端地址**：<填>

## 数据在哪（都是结构化日志，不手抄）

- 每组：`g1..g5/run_report.json`（自带 时长/时延/各 stage 耗时/enrichment 五类计数/金句保真/内存峰值/server 就绪/红旗）+ `g1..g5/enrichment.json`（内容本体）。
- **自动汇总表**：`RESULTS.md`（由 `python eval/run_eval.py --config eval/eval_config_board003.json` 生成，勿手填）。

## 结论

- **总体结论（通过）**：5 组 ~31–35min 随机会议**全部跑通到导出**，`enrichment` stage 全 succeeded；enrichment 五类**跨会稳定非空**（关键词 18、金句 3 且全保真、决策 17–30、问答 15–45、层级大纲均有）；**每组 `loaded_once=true`——enrichment 复用了摘要的同一个 rkllm server，没有二次加载模型**（本轮核心目标达成）。
- **性能数据点（板端 4B, ctx16k）**：总耗时 474–581s（约 30min 会议处理 8–10min）；其中 llm_summary 138–152s、enrichment 94–126s（enrichment 约占总耗时 18–24%）；板端峰值内存 2.64–2.74GB，5 组基本持平，无增长趋势。
- **异常与观察**：
  1. `run_report.memory.server_rss_peak_mb` 与 `memory_leak_suspected` 为 None——板端采样器 `memory_summary.json` 键名与预期不同（`board_used_peak_mb` 正常）；需按 `memory.raw_keys` 修一次键映射（板端不用重跑）。
  2. 每组 6/5 条优化红旗，跨会一致：块摘要偏短(85–98<120)、overview 偏短(137–275<300)、块→章合并率低(1:1 未合并)、**chars_per_token 实测 1.5–1.64 vs 配置 1.3**（预算低估，应校准）、meeting_summary 的 keywords/decisions 等字段空（已由 enrichment 另行产出补齐）。
  3. enrichment 的 qa 条数波动较大(15–45)，keywords/quotes 稳定(18/3)。

> **跟进（2026-09-04）**：观察 1 已修——`run_report.py` 内存映射对齐板端采样器结构（server_rss 从 `process_peaks.rkllm_server` 嵌套取、leak 用 cleanup 残留>500MB 推导），g1–g5 回归 server_rss 272–287MB、leak 全 false。观察 2 中 chars_per_token 默认已校准 1.3→1.55；QA 错配/占位待办/合并率低的三处修复已提交（77f63f2），效果待下轮板端验证。

## 判定（对照 RESULTS.md）

1. 5 组 timing.status 均 succeeded、`enrichment` stage 有耗时（failed 也在表里，附 error）。
2. enrichment 列 kw/qa/quote/dec/outline 跨会稳定非空（重点 dec/outline）。
3. server.ready_seconds 每组单值 + 每组仅一个 rkllm_server.log = 只加载一次。
4. 拿到 5 个（时长, 总耗时, 摘要耗时, enrich 耗时, 内存峰值）数据点。
