# 章节摘要上下文策略对照

- 源：`ops\board-results\2026-09-02_003_enrichment-wire-board-verify\g2\harness\meeting_result.json`  章节数：8  模型：qwen3:4b  temp=0
- 金标：`eval\golden\R002S05C01.keypoints.json`

| 臂 | 说明 | recall↑ | anchor_support↑ | contam_ref↓ | bleed_delta↓ | avg_chars |
|---|---|---|---|---|---|---|
| A0 | 仅本章(隔离) | 1.0 | 1.0 | 0.0 | -0.0037 | 74.1 |
| A1 | +上章压缩摘要(现产线) | 0.8 | 1.0 | 0.0 | -0.0029 | 69.8 |
| A1b | +上章摘要(强定位/去重) | 0.8 | 1.0 | 0.0 | -0.0039 | 71.0 |
| A2 | +上章全文(重上下文) | 0.8 | 0.671 | 0.329 | -0.0012 | 83.5 |
| A2b | +上章全文(强标记白名单) | 1.0 | 1.0 | 0.0 | -0.0061 | 77.1 |

## 读法
- recall 高 = 完整性好（收益）；contam_ref / bleed_delta 高 = 串味重（代价）。
- 若带上下文臂(A1/A2) recall 仅微升而 contam/bleed 明显↑，则隔离(A0)或轻上下文(A1)更优——印证 CLAUDE.md 原则4。
- bleed_delta 是自动代理，最终串味判定建议再抽样人工核对每臂 2~3 章摘要。