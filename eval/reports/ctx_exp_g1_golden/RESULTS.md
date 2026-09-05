# 章节摘要上下文策略对照

- 源：`ops\board-results\2026-09-02_003_enrichment-wire-board-verify\g1\harness\meeting_result.json`  章节数：9  模型：qwen3:4b  temp=0
- 金标：`eval\golden\g1_school_ops.keypoints.json`

| 臂 | 说明 | recall↑ | anchor_support↑ | contam_ref↓ | bleed_delta↓ | avg_chars |
|---|---|---|---|---|---|---|
| A0 | 仅本章(隔离) | 0.75 | 1.0 | 0.0 | -0.0067 | 71.3 |
| A1 | +上章压缩摘要(现产线) | 0.667 | 1.0 | 0.0 | -0.0015 | 52.8 |
| A1b | +上章摘要(强定位/去重) | 0.833 | 1.0 | 0.0 | -0.0031 | 79.8 |
| A2 | +上章全文(重上下文) | 0.833 | 0.706 | 0.294 | 0.0002 | 80.6 |
| A2b | +上章全文(强标记白名单) | 0.833 | 1.0 | 0.0 | -0.0054 | 78.2 |

## 读法
- recall 高 = 完整性好（收益）；contam_ref / bleed_delta 高 = 串味重（代价）。
- 若带上下文臂(A1/A2) recall 仅微升而 contam/bleed 明显↑，则隔离(A0)或轻上下文(A1)更优——印证 CLAUDE.md 原则4。
- bleed_delta 是自动代理，最终串味判定建议再抽样人工核对每臂 2~3 章摘要。