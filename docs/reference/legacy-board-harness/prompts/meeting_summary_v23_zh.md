# RK1828 会议总结 Prompt 协议（历史文件入口）

本文档原用于记录 v23 Prompt。当前运行时 Prompt 已更新，完整可读协议请参阅：[meeting_summary_v32_zh.md](meeting_summary_v32_zh.md)。

当前生产代码以以下文件为唯一准据：

- [meeting_harness/product_summary.py](../meeting_harness/product_summary.py)
- [meeting_harness/llm.py](../meeting_harness/llm.py)

当前版本：

```text
PROMPT_VERSION:          meeting-summary.v3
PRODUCT_SUMMARY_VERSION: product-summary.v32
```

当前生产路径统一使用滑动章节窗口，随后执行全文摘要、必要的 action review、speaker batches、确定性校验和原子发布；不再调用一次性全量总结。

为避免旧文件名继续被误认为当前协议，当前 Prompt 的完整内容统一维护在 [meeting_summary_v32_zh.md](meeting_summary_v32_zh.md)。
