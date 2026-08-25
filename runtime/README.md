# Runtime 目录

该目录仅供 `Meeting_Agent_mainline` 后续新运行生成本地 SQLite、会议目录和临时状态。

原有真实会议、失败会议证据和运行数据库仍保存在：

```text
D:\Meeting_Agent_fresh\runtime\
```

本次拆分没有复制、移动或改写这些数据。需要读取旧会议时，应显式配置外部 runtime 路径，不要把旧数据自动导入新主线。
