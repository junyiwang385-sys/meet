# A3b 双侧上下文 vs A0 单段(项目生产提示词)

- 源:`meeting_result.json`  中间章 i=1..6  模型:qwen3:4b
- 都用 product_summary 生产 block-summary 提示词;A3b 额外注入前后章只读参考。

| 臂 | 中间章数 | 关键点召回 | 串味率 | 段均字 |
|---|---|---|---|---|
| A0_single | 6 | 0.9 | 0.0 | 156 |
| A3b_bilateral | 6 | 1.0 | 0.125 | 142 |