# Prompt 文档目录

本目录集中保存 RK1828 Meeting Harness 的可读 Prompt 协议、JSON shape 说明和版本记录。

运行时不直接读取这些文档，运行时 Prompt 以内嵌在以下 Python 源码中的内容为准：

```text
meeting_harness/llm.py
meeting_harness/product_summary.py
```

修改 Prompt 时，应同步更新：

1. `meeting_harness/llm.py` 或 `meeting_harness/product_summary.py` 中的运行时 Prompt；
2. 本目录中的对应协议文档；
3. `PROMPT_VERSION` 或 `PRODUCT_SUMMARY_VERSION`；
4. 本地测试和板端验证记录。

当前版本：

```text
PROMPT_VERSION:          meeting-summary.v3
PRODUCT_SUMMARY_VERSION: product-summary.v32
```

## 当前文档

- [meeting_summary_v32_zh.md](meeting_summary_v32_zh.md)：与当前主线代码同步的可读 Prompt 协议，覆盖公共 System Prompt、章节窗口、full-summary、speaker-batch、action-review 和确定性校验边界。
- [meeting_summary_v23_zh.md](meeting_summary_v23_zh.md)：旧文件名兼容入口，仅指向当前 v32 协议，不再保存旧版 Prompt 正文。
- 当前运行时仍以内嵌在 [meeting_harness/product_summary.py](../meeting_harness/product_summary.py) 和 [meeting_harness/llm.py](../meeting_harness/llm.py) 中的 Prompt 为准；生产路径统一使用滑动章节窗口，不再调用一次性全量总结。
