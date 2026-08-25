# 目录拆分记录

- 日期：2026-08-25
- 来源：`D:\Meeting_Agent_fresh`
- 新主线：`D:\Meeting_Agent_mainline`
- 旧项目：`D:\Meeting_Agent_legacy`
- 方式：先复制，再逐文件 SHA-256 校验

## 复制校验

| 目录 | 已校验源文件数 | 已校验字节数 |
|---|---:|---:|
| Mainline | 214 | 9,228,784 |
| Legacy | 143 | 1,941,063 |

完整清单见：

```text
manifests/directory-copy-verification-2026-08-25.json
```

`README.md`、`DIRECTORY_SPLIT.md`、`docs/README.md`、`docs/contracts/source-map.md` 和 `runtime/README.md` 是本次生成的目录说明，不计入源文件等值清单。

## 排除内容

```text
.git/
.claude/
__pycache__/
.pytest_cache/
frontend/**/node_modules/
frontend/**/dist/
frontend/**/.vite/
D:\Meeting_Agent_fresh\runtime\
D:\Meeting_Agent_fresh\output\
```

源目录中的受保护运行数据保持不变：`runtime` 13 个文件、572,087,704 字节；`output` 3 个文件、195,259 字节。本次没有移动、删除或覆盖原目录中的任何文件，也没有切换部署入口。
