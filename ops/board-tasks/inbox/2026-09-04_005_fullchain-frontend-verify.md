# 任务单 005：全链路验证（前端 → Gateway → 板端 18082 → 展示）

- **task_id**：2026-09-04_005
- **目的**：验证真实链路能跑通并正确展示——前端切 real 模式，经 Gateway 调板端 18082，跑一场会，逐字段核对展示（重点看 004 修复 + 映射器补齐的 enrichment/发言人总结/纪要总述是否真的显示出来）。
- **关联 commit**：`feature/transcript-postprocess` HEAD（含映射器修复 fe5045d + e78117d，**映射跑在 Gateway 进程里，所以 Gateway 必须是这份代码**）
- **板端**：`linaro@10.10.22.36`，全链路服务端口 18082
- **前置**：004 的 A 段已把新代码部署到板端 `mainline_b92550a`（005 复用它）。

> **和 004 的区别**：004 是直接 Harness（绕过 Gateway/前端）。005 走**真实链路**，涉及重启板端服务，有一个必须由开发机确认的检查点（阶段 A）。**不要自行重启或停止任何板端服务**——阶段 A 只做"打印信息报回来"，等开发机给下一步。

---

## 阶段 A：板端 18082 现状探查（SSH 进板端，整段复制，**只打印不改动**）

18082 历史上指向旧快照（`mainline_8748e75`），必须先确认它现在加载的是哪个快照。

```bash
echo "==== 1. 18082 进程命令行 ===="
ps -ef | grep -E "18082|board_agent" | grep -v grep

echo "==== 2. 18082 健康检查 ===="
curl -s http://127.0.0.1:18082/v1/health || echo "health 无响应"

echo "==== 3. 新快照是否就位 ===="
ls -d /userdata/meeting_agent1/mainline_b92550a/src/meeting_agent && echo "snapshot=ok"

echo "==== 4. 启动脚本存在性 ===="
ls -l /userdata/meeting_agent1/scripts/start_board_agent1_mainline_20260826.py
```

**阶段 A 完成动作**：把以上 4 段输出**原样贴回给开发机**，然后**停下等指令**。开发机据此给出精确的重启命令（阶段 B），因为重启参数取决于当前进程实际的启动方式。

---

## 阶段 B：重启 18082 指向新快照（**开发机确认后填入命令再执行**）

```text
（此处等开发机根据阶段 A 的输出补全重启命令）
重启后自检：curl -s http://127.0.0.1:18082/v1/health  → 应返回 ready
```

---

## 阶段 C：中转机起 Gateway + 前端（`D:\Meeting_Agent_mainline`，PowerShell）

**C1. Gateway（新开一个 PowerShell 窗口，整段复制，保持窗口开着）**

```powershell
cd D:\Meeting_Agent_mainline
git checkout feature/transcript-postprocess
git pull
# 确认 Gateway 配置指向 18082
Get-Content runtime\gateway_settings_agent1.json
# 启动 Gateway（端口 8788；若启动命令不同以仓库 README 为准）
$env:PYTHONPATH = "src"
python -m meeting_agent.adapters.gateway.app --settings runtime\gateway_settings_agent1.json
```

**C1 完成判据**：Gateway 打印监听 8788,不报错。

**C2. 前端（再新开一个 PowerShell 窗口，整段复制，保持开着）**

```powershell
cd D:\Meeting_Agent_mainline\frontend\meeting-agent-ui-v1
npm install
# 切 real 模式并指向 8788（默认是 mock、默认地址是 8787，必须显式覆盖）
"VITE_API_MODE=gateway`nVITE_GATEWAY_URL=http://127.0.0.1:8788" | Out-File -Encoding utf8 .env.local
npm run dev
```

**C2 完成判据**：浏览器开 http://localhost:5173/ ，不再是 mock 的示例会议（列表为空或显示真实任务即对）。

---

## 阶段 D：跑一场会 + 逐字段核对（在浏览器里操作）

1. 前端新建/上传一场**短会音频**（几分钟即可，走通链路为主，不求长会）。
2. 等任务跑完（前端会显示阶段进度：分段→转写→摘要→enrichment→导出）。
3. 打开该会议，**照下表逐项打勾**：

| # | 看哪里 | 通过标准 |
|---|---|---|
| D1 | 会议纪要页开头 | **有一段全文总述**（不是空白）——验 e78117d |
| D2 | 会议纪要页下方「AI 智能纪要」 | 有关键词 chips / 金句 / 问答——验 fe5045d enrichment 投影 |
| D3 | 发言人页 | 每个真实发言人**有一段总结**——验 fe5045d 发言人总结 |
| D4 | 决策与待办页 | 有决策条目（不为空）——验决策兜底 |
| D5 | 原文页 | 章节速览可点击定位；unknown 不显头衔只显时间 |

**阶段 D 完成动作**：把 D1–D5 的打勾结果（✅/❌）+ 任一项 ❌ 时的截图或前端 console 报错，贴回开发机。

---

## 出错就停，按这个反馈（不要自己改命令重试）

- 阶段 C1 Gateway 起不来 → 贴完整报错 + `gateway_settings_agent1.json` 内容
- 阶段 D 任务卡住不完成 → 贴 Gateway 窗口的日志尾部 + `curl http://127.0.0.1:18082/v1/health`
- 阶段 D 某字段空（D1–D4）→ 说明 Gateway 代码或板端产出缺该字段，贴前端 Network 里那次结果响应的 JSON

---

## 依赖与顺序

```
004 A段(部署新快照) ──> 005 A(探查) ──[开发机]──> 005 B(重启18082) ──> 005 C(Gateway+前端) ──> 005 D(核对)
```

005 的 D 段字段核对，是 PC 端预览（mock 灌真实数据）之外，**第一次在真实链路上验证映射器修复**。PC 预览已确认数据契约无误，005 验证的是"真板端→Gateway→前端"这条传输链本身通不通。
