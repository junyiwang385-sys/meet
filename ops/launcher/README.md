# 桌面启动器（会议纪要端侧演示）

一键在**实验机**上启动整套演示：Windows Gateway（:8787）+ React 前端（Vite :5173），并自动打开浏览器。

> ⚠️ 只在**实验机**（`D:\Meeting_Agent_mainline`，能直连板端 `10.10.22.36`）上用。本机/开发机连不到板端，跑起来也无法处理。

## 一次性：在桌面放一个快捷方式

在实验机上双击运行一次：

```
ops\launcher\create-desktop-shortcut.bat
```

桌面会出现快捷方式 **「Meeting Agent Demo」**。以后双击它即可启动。
（也可以直接双击 `ops\launcher\start-demo.bat`，效果一样。）

## 启动做了什么

双击后 `start-demo.bat` → `launch.ps1` 依次：

1. 检查环境：项目根、`python` / `node` / `npm`；
2. 探测板端 `10.10.22.36:18082` TCP 是否可达（不通只警告、不中止）；
3. 启动 **Gateway**（:8787，`runtime\gateway_settings_agent1.json`，指向板端 18082），等它监听；
4. 经 Gateway 读一次板端健康（`/api/board/health`）；
5. 启动 **前端**（Vite :5173，自动写 `.env.local` 指向 Gateway；首次会 `npm install`，可能几分钟）；
6. 打开浏览器到 `http://127.0.0.1:5173`；若前端还没起好，则先打开 Gateway 内置 UI `http://127.0.0.1:8787/app`。

Gateway 与前端各自开在 **MeetGateway** / **MeetFrontend** 两个窗口里，日志实时可见。

## 停止

双击 `ops\launcher\stop-demo.bat`，或直接关闭 MeetGateway / MeetFrontend 两个窗口。

## 目录里的文件

| 文件 | 作用 |
|---|---|
| `start-demo.bat` | 主入口（双击启动，调用 launch.ps1） |
| `launch.ps1` | 编排：环境检查 / 起 Gateway+前端 / 健康检查 / 开浏览器（状态用英文，兼容 PS 5.1 控制台） |
| `_gateway.bat` | 后台窗口：起 Gateway（路径由 `%~dp0` 自动推导，不写死盘符） |
| `_frontend.bat` | 后台窗口：起 Vite 前端（首次 npm install） |
| `stop-demo.bat` | 停止 Gateway 与前端进程 |
| `create-desktop-shortcut.bat` | 在桌面创建「Meeting Agent Demo」快捷方式 |

## 常见问题

- **板端不可达**：确认在实验机上、板端 Board Agent（18082）在跑；可先跑一遍 `ops/board-bridge` 探针确认。
- **端口被占**：8787/5173 已在监听时启动器会直接复用，不重复起。
- **前端一直起不来**：多为首次 `npm install` 慢，看 MeetFrontend 窗口；装完会自动起在 :5173。此期间可先用 Gateway 内置 UI `/app`。
- **改端口/路径**：Gateway 端口在 `_gateway.bat`；前端指向的 Gateway 地址在 `_frontend.bat` 写的 `.env.local`。
