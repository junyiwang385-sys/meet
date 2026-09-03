# 结果：enrichment 接入 + 板端 4B 实机验证（5 组随机会议）

- **task_id**：2026-09-02_003
- **目标 commit**：`cf7d9c1`（feature/transcript-postprocess）
- **executed_at**：<填>
- **板端地址**：<填>
- **音频来源**：从库随机抽 5 段（长度不限，见下表）
- **总体结论（一句话）**：<填：5 组是否都跑通 / server 是否均单次加载 / 有无异常>

## 汇总表（一行一组）

| 组 | 音频 | 时长 | 跑通到导出 | enrichment stage | kw / qa / quote / dec / outline | server 启动次数 | 总耗时(s) | llm_summary(s) | enrichment(s) | 峰值内存(MB) | 红旗 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| g1 | | | | | / / / / | | | | | | |
| g2 | | | | | / / / / | | | | | | |
| g3 | | | | | / / / / | | | | | | |
| g4 | | | | | / / / / | | | | | | |
| g5 | | | | | / / / / | | | | | | |

> outline 列填 有/无；峰值内存填 board_used_peak_mb（server_rss_peak_mb 可括注）。

---

## g1

- **时长(duration_ms→分钟)**：
- **exit code / 跑通到 compat_export**：
- **enrichment stage status**（failed 则贴 error）：
- **server 只启一次证据**（rkllm_server.log 的 ready 行）：
- **耗时**：total= ／ llm_summary= ／ enrichment=
- **内存**：board_used_peak_mb= ／ server_rss_peak_mb=
- **run_report flags / block→章数**：
- **enrichment.json**（可全贴，小）：
```json

```

## g2

- **时长**：
- **exit code / 跑通**：
- **enrichment stage status**：
- **server 只启一次证据**：
- **耗时**：total= ／ llm_summary= ／ enrichment=
- **内存**：board_used_peak_mb= ／ server_rss_peak_mb=
- **run_report flags / block→章数**：
- **enrichment.json**：
```json

```

## g3

- **时长**：
- **exit code / 跑通**：
- **enrichment stage status**：
- **server 只启一次证据**：
- **耗时**：total= ／ llm_summary= ／ enrichment=
- **内存**：board_used_peak_mb= ／ server_rss_peak_mb=
- **run_report flags / block→章数**：
- **enrichment.json**：
```json

```

## g4

- **时长**：
- **exit code / 跑通**：
- **enrichment stage status**：
- **server 只启一次证据**：
- **耗时**：total= ／ llm_summary= ／ enrichment=
- **内存**：board_used_peak_mb= ／ server_rss_peak_mb=
- **run_report flags / block→章数**：
- **enrichment.json**：
```json

```

## g5

- **时长**：
- **exit code / 跑通**：
- **enrichment stage status**：
- **server 只启一次证据**：
- **耗时**：total= ／ llm_summary= ／ enrichment=
- **内存**：board_used_peak_mb= ／ server_rss_peak_mb=
- **run_report flags / block→章数**：
- **enrichment.json**：
```json

```

---

## 异常 / 观察（自由填写）

- <跨会 enrichment 是否有系统性丢失，如某类会 decisions 恒空>
- <耗时是否随时长线性、enrichment 占比多少>
- <内存 5 轮后是否回落到基线（server 起停有无泄漏）>
