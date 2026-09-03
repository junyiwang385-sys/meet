# 结果：enrichment 接入 + 板端 4B 实机验证（5 组随机会议）

- **task_id**：2026-09-02_003
- **目标 commit**：`feature/transcript-postprocess` HEAD
- **executed_at**：<填>
- **板端地址**：<填>

## 数据在哪（都是结构化日志，不手抄）

- 每组：`g1..g5/run_report.json`（自带 时长/时延/各 stage 耗时/enrichment 五类计数/金句保真/内存峰值/server 就绪/红旗）+ `g1..g5/enrichment.json`（内容本体）。
- **自动汇总表**：`RESULTS.md`（由 `python eval/run_eval.py --config eval/eval_config_board003.json` 生成，勿手填）。

## 人工只补两句话

- **总体结论**：<5 组是否都跑通到导出 / enrichment 是否跨会稳定非空 / server 是否每组只加载一次 / 有无异常>
- **异常与观察**：<例：某类会 decisions 恒空；enrichment 占总耗时约 X%；内存 5 组是否都回落到基线；某组 run_report flags 命中什么>

## 判定（对照 RESULTS.md）

1. 5 组 timing.status 均 succeeded、`enrichment` stage 有耗时（failed 也在表里，附 error）。
2. enrichment 列 kw/qa/quote/dec/outline 跨会稳定非空（重点 dec/outline）。
3. server.ready_seconds 每组单值 + 每组仅一个 rkllm_server.log = 只加载一次。
4. 拿到 5 个（时长, 总耗时, 摘要耗时, enrich 耗时, 内存峰值）数据点。
